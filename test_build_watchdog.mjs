// Watchdog test for triggerBuild (task 10.4): a hung ingest_builder must be
// killed after SPLITS_BUILD_TIMEOUT_S and — crucially — must NOT wedge the
// single-flight latch, so later ingests still rebuild. The hang is simulated by
// pointing SPLITS_BUILDER at a script that sleeps for an hour.
import assert from "node:assert";
import { spawn } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = dirname(fileURLToPath(import.meta.url));
const TOKEN = "test-watchdog-token";
const PORT = 8160;
const B = "http://localhost:" + PORT;

const dataDir = await mkdtemp(join(tmpdir(), "splits-watchdog-test-"));
const hang = join(dataDir, "hang.mjs");
await writeFile(hang, "setTimeout(() => {}, 3600 * 1000);\n", "utf8");

const child = spawn(process.execPath, ["serve.mjs"], {
  cwd: ROOT,
  env: {
    ...process.env,
    PORT: String(PORT),
    SPLITS_DATA_DIR: dataDir,
    SPLITS_INGEST_TOKEN: TOKEN,
    SYNC_ON_BOOT: "off",
    SYNC_AT: "off",
    SPLITS_PYTHON: process.execPath, // "build" = node hang.mjs → hangs
    SPLITS_BUILDER: hang,
    SPLITS_BUILD_TIMEOUT_S: "1",
  },
  stdio: ["ignore", "ignore", "pipe"],
});
let err = "";
child.stderr.on("data", (d) => (err += d));

const timedOutCount = () => (err.match(/build timed out/g) || []).length;

async function until(pred, what, ms = 8000) {
  for (let i = 0; i < ms / 100; i++) {
    if (pred()) return;
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error(`timed out waiting for ${what}\nstderr so far:\n${err}`);
}

let failed = false;
try {
  // server up
  await until(() => err.includes("ingest-fed") || true, "boot", 500);
  for (let i = 0; i < 60; i++) {
    try {
      const r = await fetch(B + "/api/status");
      if (r.ok) break;
    } catch { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 100));
  }

  // the boot build hangs → the watchdog must kill it and say so
  await until(() => timedOutCount() >= 1, "first watchdog kill");

  // the latch must be free again: a new ingest triggers a NEW build (which
  // hangs and times out again) instead of being swallowed by `building`
  const r = await fetch(B + "/api/ingest", {
    method: "POST",
    headers: { Authorization: "Bearer " + TOKEN, "Content-Type": "application/json" },
    body: JSON.stringify({
      sessionUid: "wd-1", startTimeLocal: "2026-07-14T07:30:00", durationS: 1800,
      distanceM: 5000, avgHr: 150, sportType: "running", avgSpeed: 2.78,
      hrSamples: [],
    }),
  });
  assert.strictEqual(r.status, 200, "ingest during/after a timed-out build still banks");
  await until(() => timedOutCount() >= 2, "second watchdog kill (latch was reset)");

  console.log("ALL PASS");
} catch (e) {
  failed = true;
  console.error("FAIL:", e.message);
} finally {
  child.kill();
  await rm(dataDir, { recursive: true, force: true }).catch(() => {});
}
process.exit(failed ? 1 : 0);
