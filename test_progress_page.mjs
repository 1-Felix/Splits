// test_progress_page.mjs — the /progress drill-down panels end to end
// (chart-drill 4.5). Boots serve.mjs over a fixture data dir (telemetry with
// an insights block + an archive with run_metrics) and drives a real browser,
// keyboard-first: pin → Enter drills, the panel itemizes contributed and
// didn't-count runs, rows navigate to /run/:id, a second drill closes the
// first panel, the offline state degrades inside the panel with a no-reload
// retry, and NO archive request happens before any drill.
import assert from "node:assert";
import { spawn } from "node:child_process";
import { mkdtemp, rename, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";
import { chromium } from "playwright";

const ROOT = dirname(fileURLToPath(import.meta.url));
const PORT = 8181;
const B = "http://localhost:" + PORT;

// ── telemetry fixture: six months of history + the insights block ────────────
// The drilled month is 2025-10 (the FIRST hoverable point → one ArrowRight):
// plotted 452 s/km over 90 in-band minutes. Jan 2026 backs the YoY drill.
const GARMIN_DATA = `export const garminData = ${JSON.stringify({
  today: "2026-07-11",
  profile: { name: "Testa", maxHR: 190 },
  race: { goalPaceSecPerKm: 341 },
  recentRuns: [],
  history: {
    vo2maxStartMonth: "2025-10",
    vo2max: [44, 44.5, 45, 45.2, 45.4, 45.6],
    paceSecPerKm: [470, 465, 460, 458, 455, 452],
    cadenceSpm: [165, 166, 166, 167, 168, 168],
    weeklyKm: [20, 22, 25, 24, 26, 28],
    ctl: [30, 32, 34, 36, 38, 40],
    atl: [28, 33, 32, 37, 36, 41],
  },
  insights: {
    metricsVersion: 2,
    efficiency: {
      refHrBand: [125, 145],
      monthly: [
        { month: "2025-10", paceSecPerKm: 452, inBandMin: 90 },
        { month: "2025-11", paceSecPerKm: 465, inBandMin: 60 },
        { month: "2025-12", paceSecPerKm: null, inBandMin: 5 },
        { month: "2026-01", paceSecPerKm: 455, inBandMin: 100 },
        { month: "2026-02", paceSecPerKm: 450, inBandMin: 80 },
        { month: "2026-03", paceSecPerKm: 448, inBandMin: 129 },
      ],
    },
    cadence: {
      refPaceBand: [420, 480],
      monthly: [
        { month: "2025-10", spm: 166, inBandMin: 90 },
        { month: "2025-11", spm: 167, inBandMin: 60 },
        { month: "2025-12", spm: null, inBandMin: 5 },
        { month: "2026-01", spm: 168, inBandMin: 100 },
        { month: "2026-02", spm: 168, inBandMin: 80 },
        { month: "2026-03", spm: 169, inBandMin: 129 },
      ],
    },
    recordsFeed: [],
    trajectory: { goalSec: 7199, weekly: [] },
    yoy: {
      "2025": Array.from({ length: 12 }, (_, i) => ({
        month: i + 1, km: 40 + i, runs: 4, paceSecPerKm: 460,
      })),
      "2026": [
        { month: 1, km: 42.0, runs: 2, paceSecPerKm: 455 },
        { month: 2, km: 55.5, runs: 5, paceSecPerKm: 452 },
        { month: 3, km: 100.3, runs: 3, paceSecPerKm: 450 },
      ],
    },
  },
}, null, 1)};\n`;

const PLAN_DATA = "export const planData = {};\n";

// ── archive fixture: October 2025 backs the pooled panel, January 2026 the
// YoY panel. Contributed: 920 (60 min) + 910 (30 min); 930 has zero in-band
// time; 940 has no run_metrics row at all.
function makeArchive(dir) {
  const db = new DatabaseSync(join(dir, "activity-archive.db"));
  db.exec(`CREATE TABLE activities (
    activity_id INTEGER PRIMARY KEY, start_time_local TEXT NOT NULL, type_key TEXT,
    name TEXT, distance_m REAL, duration_s REAL, avg_hr INTEGER, max_hr INTEGER,
    avg_cadence REAL, elevation_gain_m REAL, summary_json TEXT NOT NULL,
    detail_json TEXT, detail_fetched_at TEXT, first_seen_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, detail_distilled_json TEXT, detail_streams_json TEXT)`);
  db.exec(`CREATE TABLE run_metrics (
    activity_id INTEGER PRIMARY KEY, metrics_version INTEGER NOT NULL,
    start_time_local TEXT NOT NULL, is_treadmill INTEGER NOT NULL,
    best_1k_s REAL, best_mile_s REAL, best_5k_s REAL, best_10k_s REAL, best_half_s REAL,
    refhr_time_s REAL, refhr_dist_m REAL, refpace_time_s REAL, refpace_cadence_x_time REAL,
    refhr_pace_s_per_km REAL, refpace_cadence_spm REAL, computed_at TEXT NOT NULL)`);
  const act = db.prepare(`INSERT INTO activities (activity_id, start_time_local,
      type_key, name, distance_m, duration_s, avg_hr, max_hr, avg_cadence,
      elevation_gain_m, summary_json, first_seen_at, updated_at)
    VALUES (?, ?, 'running', ?, ?, ?, ?, ?, ?, ?, '{}', 'x', 'x')`);
  act.run(910, "2025-10-05 07:30:00", "Base One", 8000, 3600, 138, 150, 166, 30);
  act.run(920, "2025-10-12 07:30:00", "Base Two", 12000, 5400, 136, 148, 167, 45);
  act.run(930, "2025-10-20 18:00:00", "Hard Intervals", 9000, 2800, 168, 185, 175, 20);
  act.run(940, "2025-10-28 07:30:00", "Fresh Import", 7000, 2500, 140, 152, 165, 25);
  act.run(950, "2026-01-10 08:00:00", "January One", 15000, 5500, 142, 155, 167, 60);
  act.run(960, "2026-01-24 08:00:00", "January Two", 27000, 9800, 145, 158, 168, 110);
  const met = db.prepare(`INSERT INTO run_metrics (activity_id, metrics_version,
      start_time_local, is_treadmill, refhr_time_s, refhr_dist_m, refpace_time_s,
      refpace_cadence_x_time, refhr_pace_s_per_km, refpace_cadence_spm, computed_at)
    VALUES (?, 2, ?, 0, ?, ?, ?, ?, ?, ?, 'x')`);
  met.run(910, "2025-10-05 07:30:00", 1800, 3960.0, 1800, 302400.0, 454.5, 168.0);
  met.run(920, "2025-10-12 07:30:00", 3600, 8000.0, 3600, 612000.0, 450.0, 170.0);
  met.run(930, "2025-10-20 18:00:00", 0, 0, 0, 0, null, null);
  db.close();
}

function startServer(dataDir) {
  const child = spawn(process.execPath, ["serve.mjs"], {
    cwd: ROOT,
    env: { ...process.env, PORT: String(PORT), SYNC_ON_BOOT: "off", SYNC_AT: "off",
           SPLITS_DATA_DIR: dataDir },
    stdio: ["ignore", "ignore", "pipe"],
  });
  let err = "";
  child.stderr.on("data", (d) => (err += d));
  child.errRef = () => err;
  return child;
}
async function waitReady(errRef) {
  for (let i = 0; i < 60; i++) {
    try { const r = await fetch(B + "/api/status"); if (r.ok) return; } catch {}
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error("server not ready\n" + (errRef ? errRef() : ""));
}

const dataDir = await mkdtemp(join(tmpdir(), "splits-progpage-"));
await writeFile(join(dataDir, "garmin-data.js"), GARMIN_DATA);
await writeFile(join(dataDir, "plan-data.js"), PLAN_DATA);
makeArchive(dataDir);
const server = startServer(dataDir);

let browser;
let failed = false;
let step = "boot";
try {
  await waitReady(server.errRef);
  browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1200, height: 1600 } });
  const pageErrors = [];
  page.on("pageerror", (e) => pageErrors.push(String(e)));
  const archiveRequests = [];
  page.on("request", (r) => { if (r.url().includes("/api/archive/")) archiveRequests.push(r.url()); });
  const bodyText = () => page.evaluate(() => document.body.innerText);
  const panelCount = () => page.evaluate(() => document.querySelectorAll("#drill-panel").length);

  const EFF = 'svg[aria-label^="Pace at reference HR"]';
  const CAD = 'svg[aria-label^="Cadence at reference pace"]';
  const YOY = 'svg[aria-label^="Year over year"]';

  // ── load: insight charts render, and NOT ONE archive request yet ──────────
  step = "load";
  await page.goto(B + "/progress", { waitUntil: "domcontentloaded" });
  await page.waitForFunction((sel) => !!document.querySelector(sel), EFF, { timeout: 15000 });
  assert.strictEqual(archiveRequests.length, 0, "no archive request before any drill");

  // ── pin via keyboard: the affordance announces itself, still no fetch ─────
  step = "pin shows affordance";
  await page.focus(EFF);
  await page.keyboard.press("ArrowRight");     // pins the first point (2025-10)
  await page.waitForFunction(() =>
    document.querySelector('[data-card="insEff"]') &&
    document.querySelector('[data-card="insEff"]').innerText.includes("view evidence"),
    null, { timeout: 10000 });
  assert.strictEqual(archiveRequests.length, 0, "the pinned affordance alone fetches nothing");

  // ── Enter drills: panel opens, focus lands on the heading, rows split ─────
  step = "drill opens the panel";
  await page.keyboard.press("Enter");
  await page.waitForFunction(() =>
    document.querySelector("#drill-panel") &&
    document.querySelectorAll("#drill-panel a.drill-run").length >= 2,
    null, { timeout: 10000 });
  assert.ok(archiveRequests.some((u) => u.includes("/api/archive/run-metrics?") &&
    u.includes("from=2025-10-01") && u.includes("to=2025-10-31")),
    "the drill fetched exactly the pinned month: " + JSON.stringify(archiveRequests));
  assert.strictEqual(await page.evaluate(() => document.activeElement && document.activeElement.id),
    "drill-panel-heading", "focus moves into the panel on open");

  const panelText = await page.evaluate(() => document.querySelector("#drill-panel").innerText);
  assert.ok(panelText.includes("7:32"), "the header restates the plotted value (452 s/km) from static data");
  assert.ok(panelText.includes("Base Two") && panelText.includes("Base One"), "contributed runs are itemized");
  assert.ok(panelText.includes("7:30"), "per-run in-band pace (450.0) renders");
  assert.ok(panelText.includes("60 min") && panelText.includes("30 min"), "in-band minutes per run render");
  assert.ok(panelText.includes("67%") && panelText.includes("33%"), "share of the pool renders");
  assert.ok(!panelText.includes("Hard Intervals"), "didn't-count runs sit behind the disclosure");

  step = "didn't-count disclosure";
  await page.click("#drill-panel .drill-disclosure");
  await page.waitForFunction(() =>
    document.querySelector("#drill-panel").innerText.includes("no time in band"),
    null, { timeout: 5000 });
  const openText = await page.evaluate(() => document.querySelector("#drill-panel").innerText);
  assert.ok(openText.includes("Hard Intervals") && openText.includes("no time in band"),
    "a zero-in-band run is listed with its reason");
  assert.ok(openText.includes("Fresh Import") && openText.includes("not yet analysed"),
    "a run without a metrics row is listed as not yet analysed");
  assert.ok(openText.includes("open 2025 in archive"), "the archive link names the year");

  // ── Escape walks back one rung: panel closes, pin stays, focus returns ────
  step = "escape ladder";
  await page.keyboard.press("Escape");
  await page.waitForFunction(() => !document.querySelector("#drill-panel"), null, { timeout: 5000 });
  assert.ok(await page.evaluate(() => !!document.querySelector('[data-card="insEff"]')),
    "the pin (and its card) survives the panel close");
  await page.keyboard.press("Escape");
  await page.waitForFunction(() => !document.querySelector('[data-card="insEff"]'), null, { timeout: 5000 });

  // ── a second drill closes the first panel ─────────────────────────────────
  step = "one panel per page";
  await page.focus(EFF);
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Enter");
  await page.waitForFunction(() => document.querySelectorAll("#drill-panel").length === 1, null, { timeout: 10000 });
  await page.focus(CAD);
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Enter");
  await page.waitForFunction(() =>
    document.querySelectorAll("#drill-panel").length === 1 &&
    document.querySelector("#drill-panel").innerText.includes("Cadence") &&
    document.querySelectorAll("#drill-panel a.drill-run").length >= 2,
    null, { timeout: 10000 });
  assert.strictEqual(await panelCount(), 1, "opening the cadence panel closed the pace panel");
  const cadText = await page.evaluate(() => document.querySelector("#drill-panel").innerText);
  assert.ok(cadText.includes("168") && cadText.includes("170"), "per-run in-band cadence renders");

  // ── YoY drill: every run of the month, no didn't-count section ────────────
  step = "yoy panel";
  await page.focus(YOY);
  await page.keyboard.press("ArrowRight");     // pins January
  await page.keyboard.press("Enter");
  await page.waitForFunction(() =>
    document.querySelectorAll("#drill-panel").length === 1 &&
    document.querySelector("#drill-panel").innerText.includes("Jan 2026") &&
    document.querySelectorAll("#drill-panel a.drill-run").length >= 2,
    null, { timeout: 10000 });
  const yoyText = await page.evaluate(() => document.querySelector("#drill-panel").innerText);
  assert.ok(yoyText.includes("January One") && yoyText.includes("January Two"), "every run of the month listed");
  assert.ok(!(await page.evaluate(() => !!document.querySelector("#drill-panel .drill-disclosure"))),
    "volume counts every run — no didn't-count section");
  assert.ok(archiveRequests.some((u) => u.includes("/api/archive/activities?") &&
    u.includes("from=2026-01-01") && u.includes("to=2026-01-31")),
    "the YoY drill used the listing endpoint's date range");

  // ── a row navigates to the run page ───────────────────────────────────────
  step = "row navigation";
  await page.click("#drill-panel a.drill-run");
  await page.waitForFunction(() => /^\/run\/\d+$/.test(window.location.pathname), null, { timeout: 10000 });
  assert.ok(/\/run\/9[56]0$/.test(new URL(page.url()).pathname), "a January run's page opened: " + page.url());

  // ── offline honesty: 503 degrades inside the panel; retry needs no reload ─
  step = "offline drill";
  await page.goto(B + "/progress", { waitUntil: "domcontentloaded" });
  await page.waitForFunction((sel) => !!document.querySelector(sel), EFF, { timeout: 15000 });
  const dbPath = join(dataDir, "activity-archive.db");
  await rename(dbPath, dbPath + ".away");      // per-request opens → next request 503s
  await page.evaluate(() => { window.__noReload = true; });
  await page.focus(EFF);
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Enter");
  await page.waitForFunction(() =>
    document.querySelector("#drill-panel") &&
    document.querySelector("#drill-panel").innerText.includes("Archive offline"),
    null, { timeout: 10000 });
  assert.ok(await page.evaluate((sel) => !!document.querySelector(sel), EFF),
    "the chart stays fully usable under the offline panel");

  step = "offline retry";
  await rename(dbPath + ".away", dbPath);
  await page.click("#drill-panel button.drill-retry");
  await page.waitForFunction(() =>
    document.querySelectorAll("#drill-panel a.drill-run").length >= 2 &&
    !document.querySelector("#drill-panel").innerText.includes("Archive offline"),
    null, { timeout: 10000 });
  assert.ok(await page.evaluate(() => window.__noReload === true), "retry worked without a page reload");

  assert.strictEqual(pageErrors.length, 0, "no uncaught page errors: " + JSON.stringify(pageErrors));
  console.log("ALL PASS");
} catch (e) {
  failed = true;
  console.error("FAIL at step '" + step + "':", e.message);
} finally {
  if (browser) await browser.close().catch(() => {});
  server.kill();
  await rm(dataDir, { recursive: true, force: true }).catch(() => {});
}
process.exit(failed ? 1 : 0);
