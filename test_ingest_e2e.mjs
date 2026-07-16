// End-to-end: POST /api/ingest → the server spawns ingest_builder.py → a fresh
// garmin-data.js appears in the data dir carrying the pushed run (telemetry-ingest
// task 3.6). Exercises the whole ingest-fed path with the real Python builder.
import assert from "node:assert";
import { spawn } from "node:child_process";
import { mkdtemp, rm, copyFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = dirname(fileURLToPath(import.meta.url));
const TOKEN = "e2e-token";
const auth = { Authorization: "Bearer " + TOKEN, "Content-Type": "application/json" };

function startServer(port, dir) {
  return spawn(process.execPath, ["serve.mjs"], {
    cwd: ROOT,
    env: {
      ...process.env, PORT: String(port), SPLITS_DATA_DIR: dir,
      SPLITS_INGEST_TOKEN: TOKEN, SYNC_ON_BOOT: "off", SYNC_AT: "off",
      SPLITS_PYTHON: process.env.SPLITS_PYTHON || "python", // Windows dev: python3 is a Store alias
      ATHLETE_NAME: "Max", ATHLETE_AGE: "28", ATHLETE_MAX_HR: "190",
    },
    stdio: ["ignore", "inherit", "inherit"],
  });
}

async function waitFor(fn, ms = 8000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    try { if (await fn()) return true; } catch { /* keep polling */ }
    await new Promise((r) => setTimeout(r, 150));
  }
  return false;
}

const dataDir = await mkdtemp(join(tmpdir(), "splits-e2e-"));
await copyFile(join(ROOT, "plan-data.default.js"), join(dataDir, "plan-data.js"));
const PORT = 8150;
const B = "http://localhost:" + PORT;
const server = startServer(PORT, dataDir);

let failed = false;
try {
  assert.ok(await waitFor(async () => (await fetch(B + "/api/status")).ok), "server did not start");

  const body = JSON.stringify({
    sessionUid: "e2e-1", startTimeLocal: "2026-07-14T07:00:00",
    durationS: 1800, distanceM: 5000, avgHr: 150, sportType: "running",
    avgSpeed: 2.78, source: "com.sec.android.app.shealth",
    hrSamples: [{ tSec: 0, bpm: 150 }, { tSec: 5, bpm: 150 }, { tSec: 10, bpm: 150 }],
  });
  const r = await fetch(B + "/api/ingest", { method: "POST", headers: auth, body });
  assert.strictEqual(r.status, 200, "ingest → 200");

  // Poll-import until the telemetry reflects the posted run — the boot build runs
  // first against an empty store, so we wait for the ingest-triggered rebuild to win.
  const gd = join(dataDir, "garmin-data.js");
  let d = null;
  const built = await waitFor(async () => {
    const mod = await import(pathToFileURL(gd).href + "?t=" + Date.now());
    if (mod.garminData && (mod.garminData.recentRuns || []).length === 1) { d = mod.garminData; return true; }
    return false;
  });
  assert.ok(built, "garmin-data.js did not reflect the posted run");

  assert.strictEqual(d.recentRuns.length, 1, "one recent run");
  const run = d.recentRuns[0];
  assert.strictEqual(run.km, 5.0, "run km");
  assert.strictEqual(run.pace, 360, "run pace (int sec/km)");
  assert.strictEqual(run.hr, 150, "run hr");
  assert.strictEqual(run.type, "Run", "run type label");

  assert.strictEqual(d.profile.name, "Max", "profile name from ATHLETE_NAME");
  assert.strictEqual(d.profile.maxHR, 190, "profile maxHR from ATHLETE_MAX_HR");
  assert.ok(!("vo2maxCurrent" in d.profile), "no vo2maxCurrent (D7)");
  assert.ok(!("readiness" in d), "no readiness (D7)");
  assert.ok(!("vo2max" in d.history), "no history.vo2max (D7)");
  assert.ok(!("sleep" in d.history), "no history.sleep (D7)");
  assert.strictEqual(d.hrZones.length, 5, "5 HR zones");
  assert.strictEqual(d.heatmapKm.length, 365, "heatmap length 365");
  assert.strictEqual(d.predictions.halfGoal, "1:59:59", "halfGoal from plan-data.js goal");

  console.log("ALL PASS");
} catch (e) {
  failed = true;
  console.error("FAIL:", e.message);
} finally {
  server.kill();
  await rm(dataDir, { recursive: true, force: true }).catch(() => {});
}
process.exit(failed ? 1 : 0);
