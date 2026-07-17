// test_slim_render.mjs — dashboard degradation on an ingest-fed instance
// (design D7, tasks 4.1/4.2 guard half). The cockpit and /progress must render
// clean when vo2max / readiness / sleep are ABSENT (not empty — absent), and
// unchanged when they're present. The slim fixtures are produced by the REAL
// ingest_builder.py over a seeded run store, so the pages are tested against
// the exact contract Max's instance will serve — including the freshly-booted
// zero-runs state.
import assert from "node:assert";
import { spawn } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const ROOT = dirname(fileURLToPath(import.meta.url));
const PYTHON = process.env.SPLITS_PYTHON || "python";
// An out-of-the-way port block: on Windows SO_REUSEADDR lets two processes
// silently share a port, so a stray dev server on a common port can hijack
// requests mid-test. waitReady() additionally verifies each server's identity.
const BASE_PORT = 18471;

// ── date helpers (the builder derives everything from the real today) ────────
const isoLocal = (d) =>
  d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
const daysFromToday = (n) => { const d = new Date(); d.setDate(d.getDate() + n); return d; };
const today = new Date();
const monday = daysFromToday(-((today.getDay() + 6) % 7));
const sunday = new Date(monday); sunday.setDate(monday.getDate() + 6);

// A minimal-but-valid plan half for the ingest-fed instance: race, one block
// week spanning the live week, a coach block (the cockpit reads coach.log).
const PLAN_DATA = `export const planData = ${JSON.stringify({
  race: { name: "First Half", location: "Kempten", date: isoLocal(daysFromToday(120)),
          distanceKm: 21.1, goalTime: "2:15:00", goalPaceSecPerKm: 384, pb: "—" },
  block: [{ wk: "Wk 1", label: "This wk", mon: isoLocal(monday), sun: isoLocal(sunday),
            phase: "Build", km: 20, long: "8 km", focus: "Base", days: null }],
  coach: { headline: "Welcome", note: "Start easy.", focus: ["Consistency"], log: [] },
}, null, 1)};\n`;

// Two plausible Health Connect runs: one today (lands in this week's zones),
// one three days back. hrSamples at 1/5 s; run 1 carries the full expanded
// payload (speed series, steps, calories, elevation, maxHr — design D9–D13).
const hr = (bpm) => Array.from({ length: 25 }, (_, i) => ({ tSec: i * 5, bpm }));
const speed = (mps, dur) => Array.from({ length: dur / 5 + 1 }, (_, i) => ({ tSec: i * 5, mps }));
const INGESTED = {
  "hc-uid-1": { sessionUid: "hc-uid-1", startTimeLocal: isoLocal(today) + "T07:00:00",
    durationS: 1800, distanceM: 5000, avgHr: 152, maxHr: 178, sportType: "running", avgSpeed: 2.78,
    source: "com.sec.android.app.shealth", hrSamples: hr(152), speedSamples: speed(2.78, 1800),
    elevationGainM: 42, activeKcal: 380, totalKcal: 415, steps: 5150 },
  "hc-uid-2": { sessionUid: "hc-uid-2", startTimeLocal: isoLocal(daysFromToday(-3)) + "T18:00:00",
    durationS: 2400, distanceM: 6000, avgHr: 145, sportType: "running", avgSpeed: 2.5,
    source: "com.sec.android.app.shealth", hrSamples: hr(145) },
};
// a fortnight of daily resting HR — feeds Karvonen zones + the trend card (D12)
const RHR = Object.fromEntries(Array.from({ length: 14 }, (_, i) =>
  [isoLocal(daysFromToday(i - 13)), 55 - (i % 4)]));

// A Garmin-shaped fixture (readiness + vo2max + sleep present) proving the
// guards change nothing when the keys are there.
const FULL_GARMIN_DATA = `export const garminData = ${JSON.stringify({
  today: isoLocal(today),
  profile: { name: "Testa", maxHR: 190, restingHR: 47, vo2maxCurrent: 45.6 },
  race: { name: "Half Marathon", location: "Sonthofen", date: isoLocal(daysFromToday(30)),
          distanceKm: 21.1, goalTime: "1:59:59", goalPaceSecPerKm: 341, pb: "2:17:30" },
  readiness: { score: 80, status: "Primed", hrv: 60, restingHR: 47,
               sleepHours: 7.5, trainingLoad: 400, loadStatus: "Optimal" },
  block: [{ wk: "Wk 1", label: "This wk", mon: isoLocal(monday), sun: isoLocal(sunday),
            phase: "Build", km: 30, long: "18 km", focus: "Fixture week", days: null }],
  hrZones: [
    { z: 1, label: "Recovery", min: 90 }, { z: 2, label: "Endurance", min: 180 },
    { z: 3, label: "Tempo", min: 60 }, { z: 4, label: "Threshold", min: 25 },
    { z: 5, label: "VO2 max", min: 8 },
  ],
  predictions: { halfNow: "2:03:40", halfGoal: "1:59:59", trend: "closing ≈8s/wk" },
  recentRuns: [],
  coach: { headline: "Fixture", note: "Fixture note.", focus: ["Focus"],
           log: [{ date: isoLocal(daysFromToday(-10)), text: "Fixture log." }] },
  history: {
    vo2maxStartMonth: "2026-02",
    vo2max: [44, 44.5, 45, 45.2, 45.4, 45.6],
    paceSecPerKm: [470, 465, 460, 458, 455, 452],
    cadenceSpm: [165, 166, 166, 167, 168, 168],
    weeklyKm: [20, 22, 25, 24, 26, 28],
    ctl: [30, 32, 34, 36, 38, 40],
    atl: [28, 33, 32, 37, 36, 41],
    sleep: Array.from({ length: 14 }, (_, i) => ({ hours: 7 + (i % 3) * 0.4, hrv: 55 + (i % 5) })),
  },
  heatmapKm: Array.from({ length: 365 }, (_, i) => (i === 364 ? 8.2 : 0)),
}, null, 1)};\n`;

// ── fixture prep ──────────────────────────────────────────────────────────────
async function runBuilder(dir) {
  await new Promise((resolvePromise, reject) => {
    const child = spawn(PYTHON, ["ingest_builder.py"], {
      cwd: ROOT,
      env: { ...process.env, SPLITS_DATA_DIR: dir, ATHLETE_NAME: "Max", ATHLETE_AGE: "26", ATHLETE_MAX_HR: "192" },
      stdio: ["ignore", "ignore", "pipe"],
    });
    let err = "";
    child.stderr.on("data", (d) => (err += d));
    child.on("close", (code) => (code === 0 ? resolvePromise() : reject(new Error("builder exited " + code + "\n" + err))));
    child.on("error", reject);
  });
}

function startServer(port, dir, extraEnv = {}) {
  const child = spawn(process.execPath, ["serve.mjs"], {
    cwd: ROOT,
    env: { ...process.env, PORT: String(port), SPLITS_DATA_DIR: dir, SYNC_ON_BOOT: "off", SYNC_AT: "off", ...extraEnv },
    stdio: ["ignore", "ignore", "pipe"],
  });
  let err = "";
  child.stderr.on("data", (d) => (err += d));
  child.errRef = () => err;
  return child;
}
async function waitReady(port, child, expectName) {
  for (let i = 0; i < 60; i++) {
    if (child.exitCode !== null) throw new Error(`server on :${port} died\n` + child.errRef());
    try {
      const r = await fetch(`http://localhost:${port}/garmin-data.js`);
      if (r.ok) {
        const t = await r.text();
        if (t.includes(`"name": "${expectName}"`)) return;
        throw new Error(`server on :${port} serves the wrong data (want ${expectName}) — port hijacked?`);
      }
    } catch (e) {
      if (String(e.message || e).includes("wrong data")) throw e;
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error("server not ready\n" + child.errRef());
}

const slimDir = await mkdtemp(join(tmpdir(), "splits-slim-"));      // 2 ingested runs
const emptyDir = await mkdtemp(join(tmpdir(), "splits-slim-empty-")); // 0 runs (fresh boot)
const fullDir = await mkdtemp(join(tmpdir(), "splits-slim-full-"));  // Garmin-shaped

await writeFile(join(slimDir, "ingested-runs.json"), JSON.stringify(INGESTED), "utf8");
await writeFile(join(slimDir, "ingested-rhr.json"), JSON.stringify(RHR), "utf8");
await runBuilder(slimDir);   // → real slim garmin-data.js (2 runs)
await runBuilder(emptyDir);  // → real slim garmin-data.js (0 runs)
await writeFile(join(slimDir, "plan-data.js"), PLAN_DATA);
await writeFile(join(emptyDir, "plan-data.js"), PLAN_DATA);
await writeFile(join(fullDir, "garmin-data.js"), FULL_GARMIN_DATA);
await writeFile(join(fullDir, "plan-data.js"), "export const planData = {};\n");

// slim + empty boot ingest-fed (like Max's real instance) so /api/status
// reports the instance shape the pages key their chrome off; full stays
// Garmin. The ingest boot re-runs the builder, so the athlete env must match
// the fixture build or the boot pass rewrites garmin-data.js differently.
const INGEST_ENV = {
  SPLITS_INGEST_TOKEN: "slim-test-token", SPLITS_PYTHON: process.env.SPLITS_PYTHON || "python",
  ATHLETE_NAME: "Max", ATHLETE_AGE: "26", ATHLETE_MAX_HR: "192",
};
const servers = [
  startServer(BASE_PORT, slimDir, INGEST_ENV),
  startServer(BASE_PORT + 1, emptyDir, INGEST_ENV),
  startServer(BASE_PORT + 2, fullDir),
];

let browser;
let failed = false;
let step = "boot";
try {
  await Promise.all(servers.map((s, i) => waitReady(BASE_PORT + i, s, i === 2 ? "Testa" : "Max")));
  browser = await chromium.launch();

  // Load a page, wait for its settled marker, hand back text + error list.
  async function render(port, path, readyFn) {
    const page = await browser.newPage({ viewport: { width: 1200, height: 1600 } });
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.goto(`http://localhost:${port}${path}`, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(readyFn, null, { timeout: 15000 });
    const text = await page.evaluate(() => document.body.innerText);
    const cardReady = await page.evaluate(() => !!document.querySelector("#card-ready"));
    const heatCells = await page.evaluate(() => document.querySelectorAll('rect[data-hb="heat"]').length);
    await page.close();
    return { text, errors, cardReady, heatCells };
  }
  const cockpitReady = () => document.querySelectorAll('rect[data-hb="heat"]').length > 300;
  const progressReady = () => document.body.innerText.includes("Avg run pace");

  // ── instance-shape API: status flags + the honest archive 404 ─────────────
  step = "instance-shape API";
  {
    const slim = await (await fetch(`http://localhost:${BASE_PORT}/api/status`)).json();
    assert.strictEqual(slim.ingestFed, true, "ingest-fed instance says so");
    assert.strictEqual(slim.archive, false, "no archive db → archive:false");
    const full = await (await fetch(`http://localhost:${BASE_PORT + 2}/api/status`)).json();
    assert.strictEqual(full.ingestFed, false, "Garmin instance is not ingest-fed");
    const arch = await fetch(`http://localhost:${BASE_PORT}/api/archive/activities`);
    assert.strictEqual(arch.status, 404, "no archive db is a 404 (not provisioned), not a 503 (outage)");
  }

  // ── slim instance (2 ingested runs): cockpit ──────────────────────────────
  step = "slim cockpit";
  {
    // settled = heatmap up AND the status fetch landed (the Garmin pill is
    // gone) — the pill/nav assertions below are deterministic after that
    const r = await render(BASE_PORT, "/", () =>
      document.querySelectorAll('rect[data-hb="heat"]').length > 300 &&
      !document.body.innerText.includes("Garmin ·"));
    assert.ok(!r.text.includes("Garmin"), "no Garmin sync pill on an ingest-fed instance");
    assert.ok(!r.text.includes("Archive"), "no Archive nav tab without an archive db");
    assert.deepStrictEqual(r.errors, [], "slim cockpit throws nothing");
    assert.strictEqual(r.heatCells, 365, "full heatmap");
    assert.ok(!r.cardReady, "readiness card hidden when readiness is absent");
    assert.ok(!r.text.includes("TODAY · READINESS"), "no readiness copy");
    assert.ok(!r.text.includes("HRV · overnight"), "no HRV card");
    assert.ok(!r.text.includes("VO₂ MAX"), "no VO₂ KPI tile");
    assert.ok(r.text.includes("WEEKLY VOLUME"), "volume KPI still there");
    assert.ok(r.text.includes("Recovery"), "HR zones render");
    assert.ok(r.text.includes("HALF PREDICTION"), "prediction KPI still there");
    assert.ok(r.text.includes("ENERGY"), "energy tile shows when calories exist (D13)");
    assert.ok(r.text.includes("Resting HR"), "RHR trend card shows when banked (D12)");
  }

  // ── data-load failure: the demo fallback must announce itself ─────────────
  // (an expired SSO session turns the running-data.js import into HTML — the
  // page used to silently render the built-in placeholder dataset as if real)
  step = "data-load failure banner";
  {
    const page = await browser.newPage({ viewport: { width: 1200, height: 1600 } });
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.route("**/running-data.js", (route) => route.abort());
    await page.goto(`http://localhost:${BASE_PORT}/`, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() =>
      document.body.innerText.includes("Couldn't load your training data"), null, { timeout: 15000 });
    const text = await page.evaluate(() => document.body.innerText);
    assert.deepStrictEqual(errors, [], "a failed data import throws nothing");
    assert.ok(text.includes("placeholders, not yours"), "the banner says the numbers are placeholders");
    assert.ok(text.includes("Reload"), "the banner offers a reload");
    await page.close();
  }

  // ── slim instance: /progress ──────────────────────────────────────────────
  step = "slim progress";
  {
    const r = await render(BASE_PORT, "/progress", progressReady);
    assert.deepStrictEqual(r.errors, [], "slim progress throws nothing");
    assert.ok(!r.text.includes("VO₂ max"), "VO₂ card hidden when history.vo2max is absent");
    assert.ok(r.text.includes("Avg run pace"), "pace card renders");
    assert.ok(r.text.includes("Fitness & fatigue"), "fitness card renders");
  }

  // ── slim instance: archive-fed routes degrade, never error (design D8) ────
  step = "slim archive routes";
  {
    // no archive db = "this instance keeps no archive" (permanent shape, no
    // retry) — NOT the transient "Archive offline … try again" outage state
    const arch = await render(BASE_PORT, "/archive", () => document.body.innerText.includes("No archive on this instance"));
    assert.deepStrictEqual(arch.errors, [], "/archive throws nothing without an archive DB");
    assert.ok(!arch.text.includes("Archive offline"), "absent archive is not reported as an outage");

    const cmp = await render(BASE_PORT, "/compare", () => document.body.innerText.includes("Nothing to compare yet"));
    assert.deepStrictEqual(cmp.errors, [], "/compare throws nothing without an archive DB");

    const runPg = await render(BASE_PORT, "/run/12345", () => document.body.innerText.includes("Unknown run"));
    assert.deepStrictEqual(runPg.errors, [], "/run/:id throws nothing without an archive DB");
  }

  // ── freshly-booted instance (0 runs banked): both pages survive ───────────
  step = "empty cockpit";
  {
    const r = await render(BASE_PORT + 1, "/", cockpitReady);
    assert.deepStrictEqual(r.errors, [], "zero-runs cockpit throws nothing");
    assert.strictEqual(r.heatCells, 365, "empty heatmap still renders 365 cells");
    assert.ok(r.text.includes("WEEKLY VOLUME"), "KPI row renders with no runs");
  }
  step = "empty progress";
  {
    const r = await render(BASE_PORT + 1, "/progress", progressReady);
    assert.deepStrictEqual(r.errors, [], "zero-runs progress throws nothing");
  }

  // ── Garmin-shaped instance: the guards must change nothing ────────────────
  step = "full cockpit";
  {
    const r = await render(BASE_PORT + 2, "/", cockpitReady);
    assert.deepStrictEqual(r.errors, [], "full cockpit throws nothing");
    assert.ok(r.text.includes("Garmin"), "the Garmin sync pill survives on a Garmin-fed instance");
    assert.ok(r.cardReady, "readiness card present when readiness exists");
    assert.ok(r.text.includes("HRV · overnight"), "HRV card present");
    assert.ok(r.text.includes("VO₂ MAX"), "VO₂ KPI tile present");
    assert.ok(!r.text.includes("ENERGY"), "no energy tile without an energy block");
    assert.ok(!r.text.includes("Resting HR"), "no RHR trend card without restingHr history");
  }
  step = "full progress";
  {
    const r = await render(BASE_PORT + 2, "/progress", progressReady);
    assert.deepStrictEqual(r.errors, [], "full progress throws nothing");
    assert.ok(r.text.includes("VO₂ max"), "VO₂ chart card present");
  }

  console.log("ALL PASS");
} catch (e) {
  failed = true;
  console.error("FAIL at step '" + step + "':", e.message);
} finally {
  if (browser) await browser.close().catch(() => {});
  for (const s of servers) s.kill();
  for (const d of [slimDir, emptyDir, fullDir]) await rm(d, { recursive: true, force: true }).catch(() => {});
}
process.exit(failed ? 1 : 0);
