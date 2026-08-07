// test_course_page.mjs — the /course view end to end (add-course-lens 5.8).
//
// Boots serve.mjs over a data dir carrying a REAL course document (derived from
// the committed Sonthofen fixture by course_lens.py, so the page is tested
// against the same numbers the Python tests assert) and drives a real browser:
// the profile renders over distance, decisive segments come from the document
// rather than the page, the pace table hits its target, the cost-of-caution
// toggle changes the numbers, and a plan with no courseId leaves the whole
// feature dark instead of showing an empty page.
import assert from "node:assert";
import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { paceTable, parseTarget, fmtDuration, fmtPace, fmtGrade, decisiveKm } from "./course-plan.js";

const ROOT = dirname(fileURLToPath(import.meta.url));
const PORT = 8188;
const B = "http://localhost:" + PORT;

// ── the course document, built by the Python engine from the real fixture ────
// Generated once here rather than hand-written, so this test can never drift
// from what the sync actually stores.
const LENS = JSON.parse(await readFile(join(ROOT, "fixtures/course/sonthofen-lens.json"), "utf8"));

const garminDataFor = (lens) => {
  const d = {
    profile: { name: "Felix", age: 28, restingHR: 47, maxHR: 197, weightKg: 71, vo2maxCurrent: 45 },
    today: "2026-07-27",
    readiness: { score: 91, status: "High", hrv: 53, restingHR: 46, sleepHours: 7.4, trainingLoad: 20, loadStatus: "Recovery" },
    hrZones: [], predictions: { fiveK: "24:44", tenK: "52:52", halfNow: "2:01:48", halfGoal: "1:59:59", trend: "flat" },
    personalBests: { oneK: "4:51", mile: "8:18", fiveK: "27:06", tenK: "1:00:57", half: "2:19:07" },
    recentRuns: [], history: { monthly: [], weekly: [] }, heatmapKm: {},
  };
  if (lens) d.courseLens = lens;      // absent entirely when the race names no course
  return `export const garminData = ${JSON.stringify(d)};
export default garminData;
`;
};

const planFor = (courseId, opts = {}) => `export const planData = {
  race: { name: "Allgäu Panorama Halbmarathon", location: "Sonthofen", date: "${opts.date || "2026-08-09"}",
          distanceKm: 21.1, goalTime: "1:59:59", goalPaceSecPerKm: 341, pb: "2:19:07"${
            courseId ? `, courseId: ${courseId}` : ""}${
            opts.prep ? `, prep: ${JSON.stringify(opts.prep)}` : ""} },
  block: [{ wk: "Wk 7", label: "Aug 3", mon: "2026-08-03", sun: "2026-08-09",
            phase: "Race", km: 9, long: "Race", focus: "Taper", days: null }],
  coach: { headline: "h", note: "n", focus: [], log: [] },
};
export default planData;
`;

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

// ── pure-module checks (no browser needed) ───────────────────────────────────
// course-plan.js MIRRORS course_lens.pace_table(); these assertions are the
// contract between the two implementations.
{
  const t = paceTable(LENS, 7199);
  assert.ok(t.length >= 21, "a table row per kilometre");
  assert.ok(Math.abs(t[t.length - 1].cumulativeSeconds - 7199) < 1,
    "the table hits its target exactly");
  const wall = t.reduce((a, r) => (r.paceSecPerKm > a.paceSecPerKm ? r : a));
  assert.strictEqual(wall.km, 13, "the wall kilometre is the slowest");

  const declined = paceTable(LENS, 7199, -0.02);
  assert.ok(Math.abs(declined[declined.length - 1].cumulativeSeconds - 7199) < 1,
    "declining the descent still hits the target");
  const byKm = Object.fromEntries(t.map((r) => [r.km, r]));
  const decKm = Object.fromEntries(declined.map((r) => [r.km, r]));
  assert.ok(decKm[15].paceSecPerKm > byKm[15].paceSecPerKm,
    "the steep descent km is no longer run faster than level");
  assert.ok(decKm[5].paceSecPerKm < byKm[5].paceSecPerKm,
    "…and the flat kms must speed up to compensate");

  assert.strictEqual(parseTarget("1:59:59"), 7199);
  assert.strictEqual(parseTarget("59:30"), 3570);
  assert.strictEqual(parseTarget("nope"), null);
  assert.strictEqual(parseTarget(""), null);
  assert.strictEqual(parseTarget("1:99:00"), null, "an impossible minute is refused");
  assert.strictEqual(fmtDuration(7199), "1:59:59");
  assert.strictEqual(fmtDuration(341), "5:41");
  assert.strictEqual(fmtPace(341), "5:41/km");
  assert.strictEqual(fmtGrade(0.0816), "+8.16%");
  assert.strictEqual(fmtGrade(null), "—");
  assert.strictEqual(paceTable(LENS, 0).length, 0, "a zero target yields no table");
  assert.strictEqual(paceTable(null, 7199).length, 0, "no lens yields no table");

  const dec = decisiveKm(LENS);
  assert.ok(dec.get(13) === "climb", "km 13 is flagged as the climb");
  assert.ok([...dec.values()].includes("descent"), "a descent km is flagged too");
}

const dataDir = await mkdtemp(join(tmpdir(), "splits-coursepage-"));
await writeFile(join(dataDir, "garmin-data.js"), garminDataFor(LENS));
await writeFile(join(dataDir, "plan-data.js"), planFor(493447940));
const server = startServer(dataDir);

let browser;
let failed = false;
let step = "boot";
try {
  await waitReady(server.errRef);
  browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1200, height: 1800 } });
  const pageErrors = [];
  page.on("pageerror", (e) => pageErrors.push(String(e)));
  const bodyText = () => page.evaluate(() => document.body.innerText);

  // ── the page renders from the STATIC contract ─────────────────────────────
  step = "load";
  const archiveRequests = [];
  page.on("request", (r) => { if (r.url().includes("/api/archive/")) archiveRequests.push(r.url()); });
  await page.goto(B + "/course", { waitUntil: "networkidle" });
  await page.waitForSelector('svg[aria-label^="Course elevation by distance"]', { timeout: 10000 });
  let text = await bodyText();

  assert.ok(/Allgäu Panorama/.test(text), "the course name renders");
  assert.ok(/21\.11 km/.test(text), "the distance renders");
  assert.ok(!/demo|Demo Athlete/i.test(text), "the demo fallback is NOT what we are looking at");

  // ── decisive segments come from the DOCUMENT ─────────────────────────────
  step = "segments";
  assert.ok(/km 11\.8–13\.4/.test(text) || /km 11\.8/.test(text),
    "the detected climb is surfaced with its own bounds: " + text.slice(0, 400));
  assert.ok(/\+102 m/.test(text), "the climb's elevation change is shown");
  // the page must not hardcode the course's shape
  const pageSrc = await readFile(join(ROOT, "course.dc.html"), "utf8");
  assert.ok(!/km 12.*13.*wall/i.test(pageSrc.replace(/<!--[\s\S]*?-->/g, "")),
    "the page does not hardcode where the wall is");

  // ── the pace table ────────────────────────────────────────────────────────
  step = "pace-table";
  const rowCount = await page.evaluate(() => document.querySelectorAll(".crs-tbl tbody tr").length);
  assert.ok(rowCount >= 21, "a row per kilometre, got " + rowCount);
  assert.ok(/1:59:59/.test(text), "the goal target is offered");
  assert.ok(/2:01:48/.test(text), "Garmin's prediction is offered");

  // the model line states its own accuracy rather than implying precision
  assert.ok(/minetti-2002/.test(text), "the curve is named");
  assert.ok(/residual/.test(text), "the fit residual is disclosed");

  // ── cost of caution toggles the numbers ──────────────────────────────────
  step = "caution";
  const km15 = () => page.evaluate(() => {
    const rows = [...document.querySelectorAll(".crs-tbl tbody tr")];
    const r = rows.find((tr) => tr.children[0].innerText.trim() === "15");
    return r ? r.children[2].innerText.trim() : null;
  });
  const declinedPace = await km15();
  assert.ok(declinedPace, "km 15 has a target pace");
  await page.click('button[aria-pressed="true"]:has-text("Descent declined")');
  await page.waitForTimeout(200);
  const optimalPace = await km15();
  assert.notStrictEqual(optimalPace, declinedPace,
    "taking the descent changes km 15's target");
  const toSecs = (s) => { const [m, x] = s.replace("/km", "").split(":"); return +m * 60 + +x; };
  assert.ok(toSecs(optimalPace) < toSecs(declinedPace),
    "model-optimal runs km 15 faster than the cautious plan");
  const afterText = await bodyText();
  assert.ok(/Model-optimal/.test(afterText), "the toggle names its state");

  // ── before race day there is no overlay and no empty state ───────────────
  step = "no-overlay";
  assert.ok(!/How it actually went/.test(afterText),
    "no overlay before the race, and no empty placeholder either");

  // ── a plan with no courseId leaves the feature dark ──────────────────────
  // Faithful to what the sync produces: no courseId means no `courseLens` key
  // in the contract at all, not a stale document left lying around. A FRESH
  // browser context is required — ES modules are cached per context, so a
  // reload would keep serving the old garmin-data.js.
  step = "no-course";
  await writeFile(join(dataDir, "plan-data.js"), planFor(null));
  await writeFile(join(dataDir, "garmin-data.js"), garminDataFor(null));
  const ctx2 = await browser.newContext({ viewport: { width: 1200, height: 1200 } });
  const page2 = await ctx2.newPage();
  const page2Errors = [];
  page2.on("pageerror", (e) => page2Errors.push(String(e)));
  await page2.goto(B + "/course", { waitUntil: "networkidle" });
  await page2.waitForTimeout(600);
  const darkText = await page2.evaluate(() => document.body.innerText);
  assert.ok(/No course for this race/.test(darkText), "the page explains itself: " + darkText.slice(0, 300));
  assert.strictEqual(
    await page2.evaluate(() => document.querySelectorAll(".crs-tbl").length), 0,
    "no pace table without a course (the class name lives in the stylesheet, so count elements)");
  assert.strictEqual(
    await page2.evaluate(() => document.querySelectorAll("svg").length), 0,
    "and no profile chart either");
  // and the nav must not advertise a Course tab on an instance without one
  const navLabels = await page2.evaluate(() =>
    [...document.querySelectorAll('nav[aria-label="Pages"] a')].map((a) => a.innerText.trim()));
  assert.ok(!navLabels.includes("Course"), "no Course tab when there is no course: " + navLabels);
  assert.deepStrictEqual(page2Errors, [], "no page errors on the dark page");
  await ctx2.close();

  // ── the race-prep checklist (plan-owned, one-off) ─────────────────────────
  // Content lives in race.prep, not the page — same rule as the wall. The race
  // date is computed relative to NOW so this test reads the same before and
  // after the real Sonthofen weekend.
  step = "prep";
  const iso = (d) => d.toISOString().slice(0, 10);
  const PREP = { title: "Race weekend — the prep plan", updated: "2026-08-07", sections: [
    { title: "TONIGHT", items: ["Pasta dinner", "Mix the flask"] },
    { title: "RACE MORNING", items: ["Oats at 6:15"] },
  ] };
  await writeFile(join(dataDir, "garmin-data.js"), garminDataFor(LENS));
  await writeFile(join(dataDir, "plan-data.js"),
    planFor(493447940, { date: iso(new Date(Date.now() + 2 * 864e5)), prep: PREP }));
  const ctx3 = await browser.newContext({ viewport: { width: 1200, height: 1800 } });
  const page3 = await ctx3.newPage();
  const page3Errors = [];
  page3.on("pageerror", (e) => page3Errors.push(String(e)));
  await page3.goto(B + "/course", { waitUntil: "networkidle" });
  await page3.waitForSelector(".prep-item", { timeout: 10000 });
  let prepText = await page3.evaluate(() => document.body.innerText);
  assert.ok(/Race weekend — the prep plan/.test(prepText), "the prep card renders from race.prep");
  assert.ok(/0 \/ 3/.test(prepText), "the tick counter starts empty");
  await page3.click(".prep-item");
  await page3.waitForTimeout(150);
  assert.strictEqual(
    await page3.evaluate(() => document.querySelector(".prep-item").getAttribute("aria-pressed")),
    "true", "a clicked item reads as ticked");
  prepText = await page3.evaluate(() => document.body.innerText);
  assert.ok(/1 \/ 3/.test(prepText), "the counter follows the tick");
  // the tick must survive a reload — it lives in localStorage, not React state
  await page3.reload({ waitUntil: "networkidle" });
  await page3.waitForSelector(".prep-item", { timeout: 10000 });
  assert.strictEqual(
    await page3.evaluate(() => document.querySelector(".prep-item").getAttribute("aria-pressed")),
    "true", "ticks persist across a reload");
  assert.deepStrictEqual(page3Errors, [], "no page errors on the prep page");
  await ctx3.close();

  // ── once the race is run the checklist hides ──────────────────────────────
  step = "prep-hidden";
  await writeFile(join(dataDir, "plan-data.js"),
    planFor(493447940, { date: iso(new Date(Date.now() - 2 * 864e5)), prep: PREP }));
  const ctx4 = await browser.newContext({ viewport: { width: 1200, height: 1200 } });
  const page4 = await ctx4.newPage();
  await page4.goto(B + "/course", { waitUntil: "networkidle" });
  await page4.waitForSelector('svg[aria-label^="Course elevation by distance"]', { timeout: 10000 });
  const goneText = await page4.evaluate(() => document.body.innerText);
  assert.ok(!/Race weekend — the prep plan/.test(goneText), "the prep card hides after race day");
  assert.strictEqual(
    await page4.evaluate(() => document.querySelectorAll(".prep-item").length), 0,
    "no tickable items after race day");
  await ctx4.close();

  assert.deepStrictEqual(pageErrors, [], "no page errors");
  console.log("ALL PASS");
} catch (e) {
  failed = true;
  console.error("FAILED at step: " + step);
  console.error(e && e.stack || e);
  console.error("server stderr:\n" + server.errRef());
} finally {
  if (browser) await browser.close();
  server.kill();
  await rm(dataDir, { recursive: true, force: true });
  if (failed) process.exit(1);
}
