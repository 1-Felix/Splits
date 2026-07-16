// Integration test for POST /api/ingest — the Health Connect run-ingest endpoint
// (telemetry-ingest capability). Mirrors test_plan_push.mjs: token gate, method,
// size cap, payload validation, and idempotent banking by session UID.
import assert from "node:assert";
import { spawn } from "node:child_process";
import { mkdtemp, rm, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = dirname(fileURLToPath(import.meta.url));
const TOKEN = "test-ingest-token";
const auth = { Authorization: "Bearer " + TOKEN, "Content-Type": "application/json" };

function startServer(port, token, dir) {
  const child = spawn(process.execPath, ["serve.mjs"], {
    cwd: ROOT,
    env: { ...process.env, PORT: String(port), SPLITS_DATA_DIR: dir, SPLITS_INGEST_TOKEN: token, SYNC_ON_BOOT: "off", SYNC_AT: "off", SPLITS_PYTHON: process.env.SPLITS_PYTHON || "python" },
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
      const r = await fetch(base + "/api/status");
      if (r.ok) return;
    } catch { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error("server not ready\n" + (errRef ? errRef() : ""));
}

function run(over = {}) {
  return JSON.stringify({
    sessionUid: "sess-1",
    startTimeLocal: "2026-07-14T07:30:00",
    durationS: 1800,
    distanceM: 5000,
    avgHr: 150,
    sportType: "running",
    avgSpeed: 2.78,
    source: "com.sec.android.app.shealth",
    hrSamples: [{ tSec: 0, bpm: 120 }, { tSec: 5, bpm: 132 }, { tSec: 10, bpm: 148 }],
    ...over,
  });
}

const dataDir = await mkdtemp(join(tmpdir(), "splits-ingest-test-"));
const dataDirOff = await mkdtemp(join(tmpdir(), "splits-ingest-off-"));
const PORT = 8140;
const B = "http://localhost:" + PORT;
const Boff = "http://localhost:" + (PORT + 1);
const post = (headers, body) => fetch(B + "/api/ingest", { method: "POST", headers, body });
const banked = async () => JSON.parse(await readFile(join(dataDir, "ingested-runs.json"), "utf8").catch(() => "{}"));

const server = startServer(PORT, TOKEN, dataDir);
const serverOff = startServer(PORT + 1, "", dataDirOff); // no token → endpoint absent

let failed = false;
try {
  await waitReady(B, server.errRef);
  await waitReady(Boff, serverOff.errRef);

  // endpoint disabled (no token) → 404, as if the route doesn't exist
  assert.strictEqual((await fetch(Boff + "/api/ingest", { method: "POST", body: "{}" })).status, 404, "disabled endpoint → 404");

  // auth
  assert.strictEqual((await post({ "Content-Type": "application/json" }, run())).status, 401, "no token → 401");
  assert.strictEqual((await post({ Authorization: "Bearer nope", "Content-Type": "application/json" }, run())).status, 401, "wrong token → 401");

  // wrong method
  assert.strictEqual((await fetch(B + "/api/ingest", { method: "GET", headers: auth })).status, 405, "GET → 405");

  // size cap → 413
  const big = JSON.stringify({ sessionUid: "big", startTimeLocal: "2026-07-14T07:30:00", durationS: 1, distanceM: 1, avgHr: 100, sportType: "running", hrSamples: [], pad: "x".repeat(1100 * 1024) });
  assert.strictEqual((await post(auth, big)).status, 413, "oversized → 413");

  // invalid payloads → 422, nothing banked
  assert.strictEqual((await post(auth, JSON.stringify({ sessionUid: "x" }))).status, 422, "missing fields → 422");
  assert.strictEqual((await post(auth, run({ durationS: 0 }))).status, 422, "non-positive duration → 422");
  assert.strictEqual((await post(auth, run({ sessionUid: "" }))).status, 422, "empty sessionUid → 422");
  assert.strictEqual((await post(auth, "not json")).status, 400, "non-JSON body → 400");
  assert.deepStrictEqual(await banked(), {}, "nothing banked after invalid pushes");

  // valid push → 200, run banked keyed by sessionUid
  const ok = await post(auth, run());
  assert.strictEqual(ok.status, 200, "valid push → 200");
  const okBody = await ok.json();
  assert.strictEqual(okBody.ok, true, "200 body ok:true");
  assert.strictEqual(okBody.runs, 1, "runs count = 1");
  let store = await banked();
  assert.strictEqual(Object.keys(store).length, 1, "one run banked");
  assert.strictEqual(store["sess-1"].distanceM, 5000, "banked distance");
  assert.strictEqual(store["sess-1"].hrSamples.length, 3, "banked HR samples");
  assert.ok(!("pad" in store["sess-1"]), "unknown fields not stored");

  // idempotent: re-push same UID with new data → still ONE entry, updated
  assert.strictEqual((await post(auth, run({ distanceM: 6000 }))).status, 200, "re-push → 200");
  store = await banked();
  assert.strictEqual(Object.keys(store).length, 1, "still one run after re-push");
  assert.strictEqual(store["sess-1"].distanceM, 6000, "re-push updated in place");

  // a distinct run → two entries
  assert.strictEqual((await post(auth, run({ sessionUid: "sess-2" }))).status, 200, "second run → 200");
  store = await banked();
  assert.strictEqual(Object.keys(store).length, 2, "two runs banked");

  // scope expansion (8.1/8.2): the new optional metrics ride the same payload
  const rich = await post(auth, run({ sessionUid: "sess-3", maxHr: 182, elevationGainM: 55, activeKcal: 400, totalKcal: 452, steps: 5100, speedSamples: [{ tSec: 0, mps: 2.5 }] }));
  assert.strictEqual(rich.status, 200, "expanded run → 200");
  store = await banked();
  assert.strictEqual(store["sess-3"].maxHr, 182, "maxHr banked");
  assert.strictEqual(store["sess-3"].steps, 5100, "steps banked");
  assert.strictEqual(store["sess-3"].speedSamples.length, 1, "speed series banked");

  // resting heart rate: its own payload form, banked apart from runs (D12)
  const rhr = await post(auth, JSON.stringify({ restingHeartRate: [{ date: "2026-07-10", bpm: 52 }, { date: "2026-07-11", bpm: 50 }] }));
  assert.strictEqual(rhr.status, 200, "rhr push → 200");
  assert.strictEqual((await rhr.json()).days, 2, "rhr day count in response");
  const rhrStore = JSON.parse(await readFile(join(dataDir, "ingested-rhr.json"), "utf8"));
  assert.deepStrictEqual(rhrStore, { "2026-07-10": 52, "2026-07-11": 50 }, "rhr banked by date");
  assert.strictEqual((await post(auth, JSON.stringify({ restingHeartRate: [{ date: "2026-02-29", bpm: 52 }] }))).status, 422, "invalid rhr day → 422");

  console.log("ALL PASS");
} catch (e) {
  failed = true;
  console.error("FAIL:", e.message);
} finally {
  server.kill();
  serverOff.kill();
  await rm(dataDir, { recursive: true, force: true }).catch(() => {});
  await rm(dataDirOff, { recursive: true, force: true }).catch(() => {});
}
process.exit(failed ? 1 : 0);
