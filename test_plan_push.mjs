import assert from "node:assert";
import { spawn } from "node:child_process";
import { mkdtemp, copyFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { hashPlan } from "./plan-io.mjs";

const ROOT = dirname(fileURLToPath(import.meta.url));
const TOKEN = "test-secret-token";
const auth = { Authorization: "Bearer " + TOKEN };

function startServer(port, token) {
  const child = spawn(process.execPath, ["serve.mjs"], {
    cwd: ROOT,
    env: { ...process.env, PORT: String(port), SPLITS_DATA_DIR: dataDir, SPLITS_PLAN_TOKEN: token, SYNC_ON_BOOT: "off", SYNC_AT: "off" },
    stdio: ["ignore", "ignore", "pipe"],
  });
  let err = "";
  child.stderr.on("data", (d) => (err += d));
  child.errRef = () => err;
  return child;
}

async function waitReady(base, errRef) {
  for (let i = 0; i < 60; i++) {
    try {
      const r = await fetch(base + "/plan-data.js");
      if (r.ok) return;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error("server not ready\n" + (errRef ? errRef() : ""));
}

const dataDir = await mkdtemp(join(tmpdir(), "splits-plan-test-"));
await copyFile(join(ROOT, "plan-data.default.js"), join(dataDir, "plan-data.js"));

const PORT = 8130;
const B = "http://localhost:" + PORT;
const put = (headers, body) => fetch(B + "/api/plan", { method: "PUT", headers, body });

const server = startServer(PORT, TOKEN);
const serverOff = startServer(PORT + 1, ""); // no token → endpoint absent
const Boff = "http://localhost:" + (PORT + 1);

let failed = false;
try {
  await waitReady(B, server.errRef);
  await waitReady(Boff, serverOff.errRef);

  const original = await (await fetch(B + "/plan-data.js")).text();
  const version = hashPlan(original);

  // endpoint disabled (no token) → 404, as if the route doesn't exist
  assert.strictEqual((await fetch(Boff + "/api/plan", { method: "PUT", body: "x" })).status, 404, "disabled endpoint → 404");

  // auth
  assert.strictEqual((await put({}, "x")).status, 401, "no token → 401");
  assert.strictEqual((await put({ Authorization: "Bearer nope" }, "x")).status, 401, "wrong token → 401");

  // wrong method
  assert.strictEqual((await fetch(B + "/api/plan", { method: "POST", headers: auth, body: "x" })).status, 405, "POST → 405");

  // size cap → 413 (checked before the version guard)
  const big = "// " + "x".repeat(600 * 1024);
  assert.strictEqual((await put({ ...auth }, big)).status, 413, "oversized → 413");

  // version guard
  assert.strictEqual((await put({ ...auth }, original)).status, 428, "missing If-Match → 428");
  assert.strictEqual((await put({ ...auth, "If-Match": "deadbeef" }, original)).status, 409, "stale If-Match → 409");

  // bad plan → 422, live file byte-for-byte unchanged
  assert.strictEqual((await put({ ...auth, "If-Match": version }, "export const planData = {};")).status, 422, "bad plan → 422");
  assert.strictEqual(await (await fetch(B + "/plan-data.js")).text(), original, "live file unchanged after 422");

  // good plan → 200, canonical updated atomically, new version returned
  const edited = original + "\n// edited by test\n";
  const good = await put({ ...auth, "If-Match": version }, edited);
  assert.strictEqual(good.status, 200, "good plan → 200");
  const gbody = await good.json();
  assert.strictEqual(gbody.version, hashPlan(edited), "response version = hash(new content)");
  assert.strictEqual(await (await fetch(B + "/plan-data.js")).text(), edited, "canonical updated");

  // force (If-Match:*) bypasses the guard
  const forced = original + "\n// forced\n";
  assert.strictEqual((await put({ ...auth, "If-Match": "*" }, forced)).status, 200, "force (If-Match:*) → 200");
  assert.strictEqual(await (await fetch(B + "/plan-data.js")).text(), forced, "force wrote canonical");

  // concurrent pushes with the same If-Match: the mutex serializes them → exactly one wins,
  // the other sees the updated canonical and gets 409 (no silent lost update)
  const cur = await (await fetch(B + "/plan-data.js")).text();
  const curV = hashPlan(cur);
  const [ra, rb] = await Promise.all([
    put({ ...auth, "If-Match": curV }, cur + "\n// concurrent A\n"),
    put({ ...auth, "If-Match": curV }, cur + "\n// concurrent B\n"),
  ]);
  assert.deepStrictEqual([ra.status, rb.status].sort(), [200, 409], "concurrent same-version pushes → one 200, one 409");

  console.log("ALL PASS");
} catch (e) {
  failed = true;
  console.error("FAIL:", e.message);
} finally {
  server.kill();
  serverOff.kill();
  await rm(dataDir, { recursive: true, force: true }).catch(() => {});
}
process.exit(failed ? 1 : 0);
