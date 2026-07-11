// test_cockpit_page.mjs — the cockpit's drill-downs end to end (chart-drill
// 5.3). Boots serve.mjs over a fixture data dir and drives a real browser:
// the trajectory's pinned week links to its anchoring run from STATIC data
// (zero archive requests), an anchorless week stays inert, heatmap day cells
// resolve lazily on activation (one run navigates, several offer a chooser,
// 503 shows an inline offline note, zero-km cells stay inert), and the whole
// cockpit renders complete with every /api/* route failing.
import assert from "node:assert";
import { spawn } from "node:child_process";
import { mkdtemp, rename, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";
import { chromium } from "playwright";

const ROOT = dirname(fileURLToPath(import.meta.url));
const PORT = 8191;
const B = "http://localhost:" + PORT;

// Heatmap indexing: cell i ↔ (today − 364 + i), so i 0 = 2025-07-12 and
// i 364 = today (2026-07-11):
//   i 354 = 2026-07-01 (one run), i 355 = 2026-07-02 (rest, inert),
//   i 357 = 2026-07-04 (two runs → chooser).
const I_SINGLE = 354, I_ZERO = 355, I_MULTI = 357;
const heatmapKm = Array.from({ length: 365 }, () => 0);
heatmapKm[I_SINGLE] = 8.2;
heatmapKm[I_MULTI] = 12.0;

const GARMIN_DATA = `export const garminData = ${JSON.stringify({
  today: "2026-07-11",
  profile: { name: "Testa", maxHR: 190, restingHR: 47, vo2maxCurrent: 45.6 },
  race: { name: "Half Marathon", location: "Sonthofen", date: "2026-08-09",
          distanceKm: 21.1, goalTime: "1:59:59", goalPaceSecPerKm: 341, pb: "2:17:30" },
  readiness: { score: 80, status: "Primed", hrv: 60, restingHR: 47,
               sleepHours: 7.5, trainingLoad: 400, loadStatus: "Optimal" },
  block: [{ wk: "Wk 1", label: "Jul 6", mon: "2026-07-06", sun: "2026-07-12",
            phase: "Build", km: 30, long: "18 km", focus: "Fixture week", days: null }],
  hrZones: [
    { z: 1, label: "Recovery", min: 90 }, { z: 2, label: "Endurance", min: 180 },
    { z: 3, label: "Tempo", min: 60 }, { z: 4, label: "Threshold", min: 25 },
    { z: 5, label: "VO2 max", min: 8 },
  ],
  predictions: { halfNow: "2:03:40", halfGoal: "1:59:59", trend: "closing ≈8s/wk" },
  recentRuns: [],
  coach: { headline: "Fixture", note: "Fixture note.", focus: ["Focus"],
           log: [{ date: "2026-07-01", text: "Fixture log." }] },
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
  heatmapKm,
  insights: {
    metricsVersion: 2,
    efficiency: { refHrBand: [125, 145], monthly: [{ month: "2026-06", paceSecPerKm: 450, inBandMin: 90 }] },
    cadence: { refPaceBand: [420, 480], monthly: [{ month: "2026-06", spm: 168, inBandMin: 90 }] },
    recordsFeed: [],
    trajectory: {
      goalSec: 7199,
      weekly: [
        { week: "2026-W20", riegelSec: 8200, garminSec: 7300, anchorId: 777 },
        { week: "2026-W21", riegelSec: null, garminSec: 7280 },
        { week: "2026-W22", riegelSec: 8100, garminSec: 7250, anchorId: 778 },
        { week: "2026-W23", riegelSec: 8068, garminSec: 7230, anchorId: 778 },
      ],
    },
    yoy: {},
  },
}, null, 1)};\n`;

const PLAN_DATA = "export const planData = {};\n";

function makeArchive(dir) {
  const db = new DatabaseSync(join(dir, "activity-archive.db"));
  db.exec(`CREATE TABLE activities (
    activity_id INTEGER PRIMARY KEY, start_time_local TEXT NOT NULL, type_key TEXT,
    name TEXT, distance_m REAL, duration_s REAL, avg_hr INTEGER, max_hr INTEGER,
    avg_cadence REAL, elevation_gain_m REAL, summary_json TEXT NOT NULL,
    detail_json TEXT, detail_fetched_at TEXT, first_seen_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, detail_distilled_json TEXT, detail_streams_json TEXT)`);
  const act = db.prepare(`INSERT INTO activities (activity_id, start_time_local,
      type_key, name, distance_m, duration_s, avg_hr, max_hr, avg_cadence,
      elevation_gain_m, summary_json, first_seen_at, updated_at)
    VALUES (?, ?, 'running', ?, ?, ?, ?, ?, ?, ?, '{}', 'x', 'x')`);
  act.run(777, "2026-05-17 09:00:00", "Anchor Tenk", 10500, 3600, 165, 182, 172, 60);
  act.run(778, "2026-05-31 09:00:00", "Faster Tenk", 10400, 3480, 166, 184, 173, 55);
  act.run(810, "2026-07-01 07:30:00", "Solo Wednesday", 8200, 3000, 140, 152, 166, 30);
  act.run(820, "2026-07-04 08:00:00", "Morning Shakeout", 4000, 1500, 132, 141, 164, 10);
  act.run(830, "2026-07-04 18:30:00", "Evening Long", 8000, 3000, 148, 160, 168, 45);
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

const dataDir = await mkdtemp(join(tmpdir(), "splits-cockpitpage-"));
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

  const TRAJ = 'svg[aria-label^="Race trajectory"]';
  const HEAT = 'svg[aria-label^="Running heatmap"]';
  const cockpitReady = () => page.waitForFunction(() =>
    document.querySelectorAll('rect[data-hb="heat"]').length > 300 &&
    !!document.querySelector('svg[aria-label^="Race trajectory"]'),
    null, { timeout: 15000 });
  const clickCell = (i) => page.evaluate((i) =>
    document.querySelectorAll('rect[data-hb="heat"]')[i].dispatchEvent(
      new MouseEvent("click", { bubbles: true, cancelable: true })), i);

  // ── the cockpit renders complete with EVERY /api/* route failing ──────────
  step = "render with API down";
  await page.route("**/api/**", (route) => route.abort());
  await page.goto(B + "/", { waitUntil: "domcontentloaded" });
  await cockpitReady();
  const down = await page.evaluate(() => ({
    hero: !!document.querySelector("#card-hero"),
    week: document.querySelectorAll(".week-grid .day, .wk-placeholder").length,
    cells: document.querySelectorAll('rect[data-hb="heat"]').length,
  }));
  assert.ok(down.hero && down.week >= 1 && down.cells === 365,
    "hero, week and full heatmap render with the API down: " + JSON.stringify(down));
  await page.unroute("**/api/**");

  // ── trajectory: a pinned anchored week links straight to its run ──────────
  step = "trajectory anchor drill";
  await page.goto(B + "/", { waitUntil: "domcontentloaded" });
  await cockpitReady();
  await page.focus(TRAJ);
  await page.keyboard.press("ArrowRight");           // pins 2026-W20 (anchored)
  await page.waitForFunction(() =>
    document.querySelector('[data-card="traj"]') &&
    document.querySelector('[data-card="traj"]').innerText.includes("view anchor run"),
    null, { timeout: 10000 });
  assert.strictEqual(archiveRequests.length, 0, "the anchor affordance needs no API");
  await page.click('[data-card="traj"]');   // a real mouse click on the card drills
  await page.waitForFunction(() => window.location.pathname === "/run/777", null, { timeout: 10000 });
  assert.strictEqual(archiveRequests.filter((u) => !u.includes("/api/archive/activities/777")).length, 0,
    "navigation came from static data — the only archive requests are the run page's own");

  // ── an anchorless week offers nothing and Enter keeps today's semantics ───
  step = "anchorless week inert";
  await page.goto(B + "/", { waitUntil: "domcontentloaded" });
  await cockpitReady();
  await page.focus(TRAJ);
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");           // 2026-W21: null Riegel
  await page.waitForFunction(() =>
    document.querySelector('[data-card="traj"]') &&
    document.querySelector('[data-card="traj"]').innerText.includes("W21"),
    null, { timeout: 10000 });
  assert.ok(!(await page.evaluate(() => document.querySelector('[data-card="traj"]').innerText)).includes("view anchor run"),
    "a week without an anchor renders no drill affordance");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(400);
  assert.strictEqual(new URL(page.url()).pathname, "/", "Enter on an anchorless week navigates nowhere");

  // ── heatmap: a single-run day navigates directly, lazily ──────────────────
  step = "heatmap single-run day";
  const before = archiveRequests.length;
  await clickCell(I_SINGLE);                          // first activation: pin
  await page.waitForFunction(() =>
    document.querySelector('[data-card="heat"]') &&
    document.querySelector('[data-card="heat"]').innerText.includes("view this day"),
    null, { timeout: 10000 });
  assert.strictEqual(archiveRequests.length, before, "pinning a cell fetches nothing");
  await page.focus(HEAT);                             // second activation: Enter drills
  await page.keyboard.press("Enter");
  await page.waitForFunction(() => window.location.pathname === "/run/810", null, { timeout: 10000 });
  assert.ok(archiveRequests.some((u) => u.includes("from=2026-07-01") && u.includes("to=2026-07-01")),
    "the drill looked up exactly that day");

  // ── a multi-run day offers a minimal chooser ──────────────────────────────
  step = "heatmap multi-run chooser";
  await page.goto(B + "/", { waitUntil: "domcontentloaded" });
  await cockpitReady();
  await clickCell(I_MULTI);
  await page.waitForFunction(() => !!document.querySelector('[data-card="heat"]'), null, { timeout: 10000 });
  await page.focus(HEAT);
  await page.keyboard.press("Enter");
  await page.waitForFunction(() =>
    document.body.innerText.includes("Morning Shakeout") &&
    document.body.innerText.includes("Evening Long"),
    null, { timeout: 10000 });
  await page.click('a.heat-run:has-text("Evening Long")');
  await page.waitForFunction(() => window.location.pathname === "/run/830", null, { timeout: 10000 });

  // ── a zero-km cell is inert: no affordance, no fetch, no navigation ───────
  step = "zero-km cell inert";
  await page.goto(B + "/", { waitUntil: "domcontentloaded" });
  await cockpitReady();
  const zeroBefore = archiveRequests.length;
  await clickCell(I_ZERO);
  await page.waitForFunction(() => !!document.querySelector('[data-card="heat"]'), null, { timeout: 10000 });
  assert.ok(!(await page.evaluate(() => document.querySelector('[data-card="heat"]').innerText)).includes("view this day"),
    "a rest day offers no drill");
  await page.focus(HEAT);
  await page.keyboard.press("Enter");
  await page.waitForTimeout(400);
  assert.strictEqual(new URL(page.url()).pathname, "/", "a rest day's activation navigates nowhere");
  assert.strictEqual(archiveRequests.length, zeroBefore, "a rest day never fetches");

  // ── an offline archive degrades at the cell with an inline note ───────────
  step = "heatmap offline note";
  const dbPath = join(dataDir, "activity-archive.db");
  await rename(dbPath, dbPath + ".away");
  await clickCell(I_SINGLE);
  await page.waitForFunction(() =>
    document.querySelector('[data-card="heat"]') &&
    document.querySelector('[data-card="heat"]').innerText.includes("view this day"),
    null, { timeout: 10000 });
  await page.focus(HEAT);
  await page.keyboard.press("Enter");
  await page.waitForFunction(() => document.body.innerText.includes("Archive offline"), null, { timeout: 10000 });
  assert.strictEqual(new URL(page.url()).pathname, "/", "the offline drill never navigates");
  assert.strictEqual(await page.evaluate(() => document.querySelectorAll('rect[data-hb="heat"]').length), 365,
    "the heatmap itself is untouched by the failed lookup");
  await rename(dbPath + ".away", dbPath);

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
