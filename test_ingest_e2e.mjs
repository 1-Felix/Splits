// End-to-end: POST /api/ingest → the server spawns ingest_builder.py → a fresh
// garmin-data.js appears in the data dir carrying the pushed run (telemetry-ingest
// task 3.6). Exercises the whole ingest-fed path with the real Python builder.
import assert from "node:assert";
import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import { mkdtemp, rm, copyFile, stat } from "node:fs/promises";
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
    hrSamples: Array.from({ length: 361 }, (_, i) => ({ tSec: i * 5, bpm: 150 })),
    speedSamples: Array.from({ length: 361 }, (_, i) => ({ tSec: i * 5, mps: 2.78 })),
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

  // ── the archive pass (add-ingest-archive 4.1): the same build wrote a real
  // activity-archive.db and every archive endpoint serves the pushed run ────
  const aid = parseInt(createHash("sha256").update("e2e-1").digest("hex").slice(0, 12), 16);
  assert.ok(await waitFor(async () => (await fetch(B + "/api/archive/activities")).ok),
    "archive endpoints did not come up after the build");
  assert.ok(await stat(join(dataDir, "activity-archive.db")).catch(() => null),
    "activity-archive.db exists on the instance's own volume");

  const status = await (await fetch(B + "/api/status")).json();
  assert.strictEqual(status.ingestFed, true, "status: ingest-fed");
  assert.strictEqual(status.archive, true, "status: archive flag flipped by the build");

  const list = await (await fetch(B + "/api/archive/activities")).json();
  assert.strictEqual(list.total, 1, "archive lists the pushed run");
  assert.strictEqual(list.activities[0].activityId, aid, "derived 48-bit id from the session UID");
  assert.strictEqual(list.activities[0].distanceM, 5000, "promoted distance");

  const act = await (await fetch(B + `/api/archive/activities/${aid}`)).json();
  assert.strictEqual(act.type, "running", "promoted type_key");
  assert.ok(act.detail && Array.isArray(act.detail.splits) && act.detail.splits.length >= 4,
    "distilled detail with per-km splits");
  assert.strictEqual(act.name, null, "no name — honest NULL, no fabrication");

  const streams = await (await fetch(B + `/api/archive/activities/${aid}/streams`)).json();
  assert.ok(streams.t.length > 100 && streams.hr && streams.v, "columnar streams serve");
  assert.strictEqual(streams.d[streams.d.length - 1], 5000, "distance normalized to the banked total");
  assert.ok(!("lat" in streams) && !("cad" in streams), "absent metrics are omitted keys");

  const rm2 = await (await fetch(B + "/api/archive/run-metrics?from=2026-07-01&to=2026-07-31")).json();
  assert.strictEqual(rm2.runs.length, 1, "run-metrics serves the run");
  assert.strictEqual(rm2.runs[0].activityId, aid, "run-metrics row keyed by the derived id");
  assert.ok(rm2.runs[0].metricsVersion >= 2, "metrics stamped at the engine's version");

  console.log("ALL PASS");
} catch (e) {
  failed = true;
  console.error("FAIL:", e.message);
} finally {
  server.kill();
  await rm(dataDir, { recursive: true, force: true }).catch(() => {});
}
process.exit(failed ? 1 : 0);
