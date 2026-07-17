// test_block_section.mjs — "The Block" on /progress end to end (add-block-lens
// 3.6). Boots serve.mjs over fixture data dirs and drives a real browser:
// the live report card renders static-first (NO archive request before any
// past-block drill), week rows drill to day rows with working /run/:id links,
// null metrics render the explicit insufficient-data mark, past blocks expand
// via the archive API to the past-tense layout and degrade to the honest
// offline state, the two-block comparison is URL-addressable, a single block
// hides the comparison entry point, and a data file without blockLens renders
// /progress with no Block section and no errors.
import assert from "node:assert";
import { spawn } from "node:child_process";
import { mkdtemp, rename, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";
import { chromium } from "playwright";

const ROOT = dirname(fileURLToPath(import.meta.url));
const PORT = 8191;                     // two-block fixture
const B = "http://localhost:" + PORT;
const Bnone = "http://localhost:" + (PORT + 1);  // no blockLens at all
const Bone = "http://localhost:" + (PORT + 2);   // a single (current) block

// ── shared telemetry base (history the page always needs) ────────────────────
const BASE = {
  today: "2026-07-16",
  profile: { name: "Testa", maxHR: 190 },
  race: { goalPaceSecPerKm: 341 },
  recentRuns: [],
  history: {
    vo2maxStartMonth: "2026-02",
    vo2max: [44, 44.5, 45, 45.2, 45.4, 45.6],
    paceSecPerKm: [470, 465, 460, 458, 455, 452],
    cadenceSpm: [165, 166, 166, 167, 168, 168],
    weeklyKm: [20, 22, 25, 24, 26, 28],
    ctl: [30, 32, 34, 36, 38, 40],
    atl: [28, 33, 32, 37, 36, 41],
  },
};

// ── the current block's lens document (engine-shaped) ────────────────────────
const CURRENT_SUMMARY = {
  raceName: "Sonthofen Half", raceDate: "2026-08-09",
  window: { start: "2026-07-06", end: "2026-08-09" },
  isComplete: false, weeksTotal: 3, percentExecuted: 75,
  kmPlanned: 79, kmActual: 24.2, efDeltaSPerKm: null,
  cadenceDeltaSpm: 2.0, goalGapDeltaS: -50, recordsCount: 0,
};
const CURRENT_DOC = {
  raceName: "Sonthofen Half", raceDate: "2026-08-09", goalTime: "1:59:59",
  window: { start: "2026-07-06", end: "2026-08-09" },
  isComplete: false, weeksTotal: 3, weekNow: 2,
  weeks: [
    { wk: "Wk 1", mon: "2026-07-06", sun: "2026-07-12", phase: "Build", plannedKm: 25, scored: true,
      counts: { done: 3, partial: 1, missed: 1, swapped: 0, unplanned: 0 }, actualKm: 18.2,
      days: [
        { date: "2026-07-06", plannedKind: "run", plannedKm: 5, plannedLoad: "Easy", title: "Easy Run", status: "done", actualKm: 5, actualPaceS: 372, actualHr: 141, activityId: 910 },
        { date: "2026-07-07", plannedKind: "run", plannedKm: 5, plannedLoad: "Easy", title: "Easy Run", status: "partial", reason: "distance", actualKm: 3, actualPaceS: 380, actualHr: 139, activityId: 911 },
        { date: "2026-07-08", plannedKind: "run", plannedKm: 5, plannedLoad: "Easy", title: "Easy Run", status: "missed" },
        { date: "2026-07-09", plannedKind: "run", plannedKm: 5, plannedLoad: "Easy", title: "Easy Run", status: "done", actualKm: 5.2, actualPaceS: 370, actualHr: 143, activityId: 912 },
        { date: "2026-07-10", plannedKind: "run", plannedKm: 5, plannedLoad: "Hard", title: "Threshold Reps", status: "done", actualKm: 5, actualPaceS: 340, actualHr: 162, activityId: 913 },
      ] },
    { wk: "Wk 2", mon: "2026-07-13", sun: "2026-07-19", phase: "Peak", plannedKm: 34, scored: true,
      counts: { done: 1, partial: 0, missed: 0, swapped: 0, unplanned: 0 }, actualKm: 6,
      days: [
        { date: "2026-07-13", plannedKind: "run", plannedKm: 6, plannedLoad: "Easy", title: "Easy Run", status: "done", actualKm: 6, actualPaceS: 375, actualHr: 140, activityId: 914 },
        { date: "2026-07-16", plannedKind: "run", plannedKm: 5, plannedLoad: "Easy", title: "Easy Run", status: "pending" },
      ] },
    { wk: "Wk 3", mon: "2026-07-20", sun: "2026-07-26", phase: "Taper", plannedKm: 20, scored: false,
      days: [{ date: "2026-07-21", plannedKind: "run", plannedKm: 6, plannedLoad: "Easy", title: "Easy Run", status: "pending" }] },
  ],
  execution: { percentExecuted: 75, scoredDays: 8, qualityHitRate: { hit: 1, of: 1 },
    kmPlanned: 79, kmPlannedToDate: 31, kmActual: 24.2,
    counts: { done: 4, partial: 1, missed: 1, swapped: 0, unplanned: 0 } },
  adaptation: {
    ef: { deltaSPerKm: null, reason: "insufficient-baseline", startRuns: 2, endRuns: 2 },
    cadence: { startSpm: 165, endSpm: 167, deltaSpm: 2.0, startRuns: 4, endRuns: 4 },
    records: [],
    goalGap: { goalS: 7199, startDate: "2026-07-07", startHalfS: 7300,
      nowDate: "2026-07-15", nowHalfS: 7250, gapStartS: 101, gapNowS: 51, deltaS: -50 },
  },
  forward: { weeksRemaining: 2, kmRemaining: 40,
    silhouette: [{ wk: "Wk 2", mon: "2026-07-13", km: 34, phase: "Peak" },
                 { wk: "Wk 3", mon: "2026-07-20", km: 20, phase: "Taper" }],
    undetailedWeeks: [] },
  summary: CURRENT_SUMMARY,
};

// ── the past block: summary in the static file, FULL doc only in the archive ─
const SPRING_SUMMARY = {
  raceName: "Spring Half", raceDate: "2025-04-12",
  window: { start: "2025-03-30", end: "2025-04-12" },
  isComplete: true, weeksTotal: 2, percentExecuted: 100,
  kmPlanned: 40, kmActual: 41.2, efDeltaSPerKm: -12.0,
  cadenceDeltaSpm: 3.0, goalGapDeltaS: -200, recordsCount: 1,
};
const SPRING_DOC = {
  raceName: "Spring Half", raceDate: "2025-04-12", goalTime: "2:05:00",
  window: { start: "2025-03-30", end: "2025-04-12" },
  isComplete: true, weeksTotal: 2,
  weeks: [
    { wk: "S-Wk1", mon: "2025-03-30", sun: "2025-04-05", phase: "Build", plannedKm: 20, scored: true,
      counts: { done: 2, partial: 0, missed: 0, swapped: 0, unplanned: 0 }, actualKm: 20,
      days: [
        { date: "2025-03-31", plannedKind: "run", plannedKm: 8, plannedLoad: "Easy", title: "Easy Run", status: "done", actualKm: 8, activityId: 800 },
        { date: "2025-04-04", plannedKind: "run", plannedKm: 12, plannedLoad: "Moderate", title: "Long Run", status: "done", actualKm: 12, activityId: 801 },
      ] },
    { wk: "S-Wk2", mon: "2025-04-06", sun: "2025-04-12", phase: "Taper", plannedKm: 20, scored: true,
      counts: { done: 2, partial: 0, missed: 0, swapped: 0, unplanned: 0 }, actualKm: 21.2,
      days: [
        { date: "2025-04-08", plannedKind: "run", plannedKm: 6, plannedLoad: "Easy", title: "Easy Run", status: "done", actualKm: 6, activityId: 802 },
        { date: "2025-04-12", plannedKind: "run", plannedKm: 21.1, plannedLoad: "Hard", title: "RACE", status: "done", actualKm: 15.2, activityId: 803 },
      ] },
  ],
  execution: { percentExecuted: 100, scoredDays: 3, qualityHitRate: { hit: 0, of: 0 },
    kmPlanned: 40, kmPlannedToDate: 26, kmActual: 41.2,
    counts: { done: 4, partial: 0, missed: 0, swapped: 0, unplanned: 0 } },
  adaptation: {
    ef: { startPaceSPerKm: 456, endPaceSPerKm: 444, deltaSPerKm: -12.0, startRuns: 3, endRuns: 3 },
    cadence: { startSpm: 166, endSpm: 169, deltaSpm: 3.0, startRuns: 3, endRuns: 3 },
    records: [{ distance: "5k", sec: 1640, prevSec: 1700, date: "2025-04-04", activityId: 801 }],
    goalGap: { goalS: 7500, startHalfS: 8100, nowHalfS: 7900, gapStartS: 600, gapNowS: 400, deltaS: -200 },
  },
  summary: SPRING_SUMMARY,
};

const lensData = (blockLens) => `export const garminData = ${JSON.stringify(
  blockLens ? { ...BASE, blockLens } : BASE, null, 1)};\n`;

function makeArchive(dir) {
  const db = new DatabaseSync(join(dir, "activity-archive.db"));
  db.exec(`CREATE TABLE block_lens (
    race_date TEXT PRIMARY KEY, race_name TEXT NOT NULL,
    lens_version INTEGER NOT NULL, is_complete INTEGER NOT NULL,
    block_json TEXT NOT NULL, updated_at TEXT NOT NULL)`);
  db.prepare("INSERT INTO block_lens VALUES (?, ?, ?, ?, ?, ?)")
    .run("2025-04-12", "Spring Half", 1, 1, JSON.stringify(SPRING_DOC), "x");
  db.close();
}

function startServer(port, dataDir) {
  const child = spawn(process.execPath, ["serve.mjs"], {
    cwd: ROOT,
    env: { ...process.env, PORT: String(port), SYNC_ON_BOOT: "off", SYNC_AT: "off",
           SPLITS_DATA_DIR: dataDir },
    stdio: ["ignore", "ignore", "pipe"],
  });
  let err = "";
  child.stderr.on("data", (d) => (err += d));
  child.errRef = () => err;
  return child;
}
async function waitReady(base, errRef) {
  for (let i = 0; i < 60; i++) {
    try { const r = await fetch(base + "/api/status"); if (r.ok) return; } catch {}
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error("server not ready\n" + (errRef ? errRef() : ""));
}

const dataDir = await mkdtemp(join(tmpdir(), "splits-blocksec-"));
const noneDir = await mkdtemp(join(tmpdir(), "splits-blocksec-none-"));
const oneDir = await mkdtemp(join(tmpdir(), "splits-blocksec-one-"));
await writeFile(join(dataDir, "garmin-data.js"),
  lensData({ lensVersion: 1, current: CURRENT_DOC, past: [SPRING_SUMMARY] }));
await writeFile(join(noneDir, "garmin-data.js"), lensData(null));
await writeFile(join(oneDir, "garmin-data.js"),
  lensData({ lensVersion: 1, current: CURRENT_DOC, past: [] }));
for (const d of [dataDir, noneDir, oneDir]) {
  await writeFile(join(d, "plan-data.js"), "export const planData = {};\n");
}
makeArchive(dataDir);

const server = startServer(PORT, dataDir);
const serverNone = startServer(PORT + 1, noneDir);
const serverOne = startServer(PORT + 2, oneDir);

let browser;
let failed = false;
let step = "boot";
try {
  await waitReady(B, server.errRef);
  await waitReady(Bnone, serverNone.errRef);
  await waitReady(Bone, serverOne.errRef);
  browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1200, height: 1800 } });
  const pageErrors = [];
  page.on("pageerror", (e) => pageErrors.push(String(e)));
  const archiveRequests = [];
  page.on("request", (r) => { if (r.url().includes("/api/archive/")) archiveRequests.push(r.url()); });
  const sectionText = () => page.evaluate(() => (document.getElementById("block-section") || {}).innerText || "");

  // ── static-first: the live card renders with ZERO archive requests ─────────
  step = "static-first live card";
  await page.goto(B + "/progress", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => !!document.getElementById("block-section"), null, { timeout: 15000 });
  let text = await sectionText();
  assert.ok(text.includes("Sonthofen Half"), "the current block's race names the card");
  assert.ok(text.includes("75%"), "percent executed from static data");
  assert.ok(text.includes("24.2 / 79"), "km done vs planned from static data");
  assert.ok(/Wk 1/.test(text) && /Wk 3/.test(text), "every week row renders");
  assert.ok(text.includes("TO RACE DAY"), "forward tilt renders on the live card");
  assert.strictEqual(archiveRequests.length, 0, "no archive request before any past-block drill");

  // ── null-metric honesty: the EF delta is a mark, not a number ──────────────
  step = "null-metric honesty";
  assert.ok(await page.evaluate(() => {
    const el = document.querySelector("#block-section .block-insufficient");
    return !!el && /insufficient data/i.test(el.innerText);
  }), "a null EF delta renders the explicit insufficient-data mark");
  assert.ok(!/PACE @ REF HR\s*\n\s*0/.test(text), "never a zero presented as the EF value");

  // ── week drill: day rows + run links, still fully static ──────────────────
  step = "week drill";
  await page.click("#block-section button.block-week");
  await page.waitForFunction(() => document.querySelectorAll("#block-section .block-day").length >= 5, null, { timeout: 5000 });
  const drill = await page.evaluate(() => document.querySelector("#block-section .block-drill").innerText);
  assert.ok(drill.includes("missed"), "a missed day states its verdict");
  assert.ok(drill.includes("partial") && drill.includes("shorter than planned"), "a partial day carries its reason in words");
  assert.ok(drill.includes("5.2 km"), "actuals render beside the plan");
  const runHref = await page.evaluate(() => document.querySelector("#block-section a.block-run-link").getAttribute("href"));
  assert.strictEqual(runHref, "./run/910", "a matched day links to its run page");
  assert.strictEqual(archiveRequests.length, 0, "the current block drills from static data alone");

  // ── past block: expands via the archive API to the past-tense layout ───────
  step = "past block expands";
  await page.click("#block-section button.block-past");
  await page.waitForFunction(() => !!document.querySelector("#block-section .block-card-past"), null, { timeout: 10000 });
  assert.ok(archiveRequests.some((u) => u.includes("/api/archive/blocks/2025-04-12")),
    "the drill fetched exactly the expanded block: " + JSON.stringify(archiveRequests));
  const pastText = await page.evaluate(() => document.querySelector("#block-section .block-card-past").innerText);
  assert.ok(pastText.includes("S-Wk1") && pastText.includes("retrospective"), "the full past document renders in the same layout");
  assert.ok(pastText.includes("100%"), "the past block's own numbers render");
  assert.ok(!(await page.evaluate(() => !!document.querySelector(".block-card-past .block-forward"))),
    "no forward tilt on a completed block");
  step = "past week drill";
  await page.click(".block-card-past button.block-week");
  await page.waitForFunction(() => document.querySelectorAll(".block-card-past .block-day").length >= 2, null, { timeout: 5000 });
  assert.ok((await page.evaluate(() => document.querySelector(".block-card-past a.block-run-link").getAttribute("href"))).endsWith("/run/800"),
    "past-block days link to their runs");

  // ── comparison is URL-addressable, from static summaries ───────────────────
  step = "comparison from a link";
  const before = archiveRequests.length;
  await page.goto(B + "/progress?blocks=2026-08-09,2025-04-12", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => !!document.querySelector("#block-section .block-compare"), null, { timeout: 15000 });
  const cmp = await page.evaluate(() => document.querySelector("#block-section .block-compare").innerText);
  assert.ok(cmp.includes("Sonthofen Half") && cmp.includes("Spring Half"), "both blocks render side by side without interaction");
  assert.ok(cmp.includes("EXECUTED") && cmp.includes("GOAL GAP"), "headline metrics compare row by row");
  assert.strictEqual(archiveRequests.length, before, "the comparison renders from static summaries");
  // best-per-row: Spring's 100% wins EXECUTED (accent + 800)
  assert.ok(await page.evaluate(() => {
    const cells = [...document.querySelectorAll("#block-section .block-compare div")];
    const c = cells.find((el) => el.textContent.trim() === "100%");
    return c && c.style.fontWeight === "800";
  }), "the best value per row is marked");
  // toggling a chip off mirrors back into the URL
  step = "comparison mirrors the URL";
  await page.click('#block-section .block-cmp-chip[aria-pressed="true"]');
  await page.waitForFunction(() => !new URL(window.location.href).searchParams.get("blocks"), null, { timeout: 5000 });

  // ── single block: no comparison entry point, section still renders ─────────
  // Each secondary origin gets its OWN page: navigating a single page across
  // origins while the previous page's module imports are mid-flight trips a
  // Chromium race that strands the new document with a rejected import.
  step = "single block hides comparison";
  const pageOne = await browser.newPage({ viewport: { width: 1200, height: 1800 } });
  pageOne.on("pageerror", (e) => pageErrors.push(String(e)));
  await pageOne.goto(Bone + "/progress", { waitUntil: "domcontentloaded" });
  await pageOne.waitForFunction(() => !!document.getElementById("block-section"), null, { timeout: 15000 });
  assert.ok((await pageOne.evaluate(() => document.getElementById("block-section").innerText)).includes("Sonthofen Half"),
    "the lone block renders normally");
  assert.ok(!(await pageOne.evaluate(() => !!document.querySelector("#block-section .block-cmp-chip"))),
    "below two blocks there is no comparison control");
  await pageOne.close();

  // ── absence: no blockLens → no section, rest of /progress unaffected ───────
  step = "absence";
  const pageNone = await browser.newPage({ viewport: { width: 1200, height: 1800 } });
  pageNone.on("pageerror", (e) => pageErrors.push(String(e)));
  await pageNone.goto(Bnone + "/progress", { waitUntil: "domcontentloaded" });
  await pageNone.waitForFunction(() => document.body.innerText.includes("THE LONG GAME"), null, { timeout: 15000 });
  assert.ok(!(await pageNone.evaluate(() => document.body.innerText.includes("THE BLOCK"))),
    "no blockLens → no Block section");
  assert.ok(!(await pageNone.evaluate(() => !!document.getElementById("block-section"))), "…and no empty shell either");
  await pageNone.close();

  // ── offline honesty: the expanded past block degrades, retry needs no reload
  step = "offline past block";
  await page.goto(B + "/progress", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => !!document.getElementById("block-section"), null, { timeout: 15000 });
  const dbPath = join(dataDir, "activity-archive.db");
  await rename(dbPath, dbPath + ".away");
  await page.evaluate(() => { window.__noReload = true; });
  await page.click("#block-section button.block-past");
  await page.waitForFunction(() =>
    document.querySelector("#block-section") &&
    document.querySelector("#block-section").innerText.includes("Archive offline"),
    null, { timeout: 10000 });
  text = await sectionText();
  assert.ok(text.includes("100% executed"), "the static summary row stays intact while offline");
  step = "offline retry";
  await rename(dbPath + ".away", dbPath);
  await page.click("#block-section button.block-retry");
  await page.waitForFunction(() => !!document.querySelector("#block-section .block-card-past"), null, { timeout: 10000 });
  assert.ok(await page.evaluate(() => window.__noReload === true), "retry worked without a page reload");

  assert.strictEqual(pageErrors.length, 0, "no uncaught page errors: " + JSON.stringify(pageErrors));
  console.log("ALL PASS");
} catch (e) {
  failed = true;
  console.error("FAIL at step '" + step + "':", e.message);
} finally {
  if (browser) await browser.close().catch(() => {});
  server.kill();
  serverNone.kill();
  serverOne.kill();
  await rm(dataDir, { recursive: true, force: true }).catch(() => {});
  await rm(noneDir, { recursive: true, force: true }).catch(() => {});
  await rm(oneDir, { recursive: true, force: true }).catch(() => {});
}
process.exit(failed ? 1 : 0);
