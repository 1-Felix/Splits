// test_course_overlay.mjs — the post-race overlay on /course (add-course-lens 6.5).
//
// Builds a synthetic race from the plan ITSELF plus two known perturbations —
// +30 s on the climb and +12 s on the final partial kilometre — then asserts
// the page attributes each to the right terrain. The finish penalty is the
// load-bearing one: it only shows up if the 113 m stub row survives, which a
// km*1000 boundary rebuild silently drops.
//
// Matching, distance normalisation and resampling are NOT tested here — they
// moved into the sync (design D6) and are covered by test_course_lens.py's
// RaceComparisonTests. What is left for the page is deltas and attribution.
import assert from "node:assert";
import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { paceTable } from "./course-plan.js";

const ROOT = dirname(fileURLToPath(import.meta.url));
const PORT = 8191;
const B = "http://localhost:" + PORT;

const LENS = JSON.parse(await readFile(join(ROOT, "fixtures/course/sonthofen-lens.json"), "utf8"));

// The race is in the PAST for this fixture, so the page looks for an actual run.
const RACE_DATE = "2026-07-20";
const TARGET = 7199;                 // 1:59:59
const CLIMB_PENALTY_S = 30;
const FINISH_PENALTY_S = 12;   // on the partial stub — the row a km*1000 rebuild drops
const ACTUAL_TOTAL_M = 21050;        // GPS drift vs the course's 21114.2

// ── synthesise the race, as the SYNC would have stored it ───────────────────
// The comparison now lives on the document (design D6): matching, normalising
// and resampling happen in Python at sync time and are covered by
// test_course_lens.py. What is left for the page — and what this file tests —
// is turning per-kilometre actuals into deltas against a chosen target and
// attributing them to terrain.
function buildComparison() {
  const plan = paceTable(LENS, TARGET, LENS.steepDescentThreshold ?? -0.02);
  const climbKm = plan.reduce((a, r) => ((r.grade ?? 0) > (a.grade ?? 0) ? r : a));
  const finishKm = plan[plan.length - 1];
  let total = 0;
  const perKm = plan.map((r) => {
    const penalty = (r.km === climbKm.km ? CLIMB_PENALTY_S : 0)
                  + (r.km === finishKm.km ? FINISH_PENALTY_S : 0);
    const actual = r.secondsForKm + penalty;
    total += actual;
    return { km: r.km, startM: r.startM, endM: r.endM, grade: r.grade,
             partial: r.partial, actualSeconds: Math.round(actual * 10) / 10, hr: 165 };
  });
  return { comparison: { activityId: 777, name: "Allgäu Panorama Halbmarathon",
                         activityDistanceM: ACTUAL_TOTAL_M,
                         normalisedBy: LENS.distanceM / ACTUAL_TOTAL_M,
                         totalSeconds: Math.round(total * 10) / 10, perKm },
           climbKm: climbKm.km, finishKm: finishKm.km };
}

const BUILT = buildComparison();

const garminData = () => {
  const d = {
    profile: { name: "Felix", maxHR: 197 }, today: "2026-07-27",
    readiness: { score: 91, status: "High" }, hrZones: [],
    predictions: { halfNow: "2:01:48", halfGoal: "1:59:59" },
    personalBests: { tenK: "1:00:57", half: "2:19:07" },
    recentRuns: [], history: { monthly: [], weekly: [] }, heatmapKm: {},
    courseLens: { ...LENS, comparison: BUILT.comparison },
  };
  return `export const garminData = ${JSON.stringify(d)};\nexport default garminData;\n`;
};
const planData = `export const planData = {
  race: { name: "Allgäu Panorama Halbmarathon", date: "${RACE_DATE}", distanceKm: 21.1,
          goalTime: "1:59:59", goalPaceSecPerKm: 341, pb: "2:19:07", courseId: 493447940 },
  block: [{ wk: "Wk 7", label: "Jul 14", mon: "2026-07-14", sun: "${RACE_DATE}",
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

const dataDir = await mkdtemp(join(tmpdir(), "splits-courseovl-"));
await writeFile(join(dataDir, "garmin-data.js"), garminData());
await writeFile(join(dataDir, "plan-data.js"), planData);
const server = startServer(dataDir);

let browser;
let failed = false;
let step = "boot";
try {
  await waitReady(server.errRef);
  browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1200, height: 2000 } });
  const pageErrors = [];
  page.on("pageerror", (e) => pageErrors.push(String(e)));

  step = "overlay-renders";
  await page.goto(B + "/course", { waitUntil: "networkidle" });
  await page.waitForSelector("text=How it actually went", { timeout: 12000 });
  const text = await page.evaluate(() => document.body.innerText);

  // ── attribution ──────────────────────────────────────────────────────────
  // The synthetic runner was exactly on plan everywhere except the climb, so
  // the climb bucket must carry the penalty and the others must be ~zero.
  step = "attribution";
  const stat = (label) => {
    const m = new RegExp("([+−]\\d+) s\\s*\\n" + label).exec(text);
    return m ? Number(m[1].replace("−", "-")) : null;
  };
  const climb = stat("ON THE CLIMBS");
  const desc = stat("ON THE DESCENTS");
  const flat = stat("ON THE FLAT");
  const overall = stat("OVERALL");
  assert.ok(climb != null && desc != null && flat != null && overall != null,
    "all four attribution stats render: " + text.slice(0, 600));
  assert.ok(Math.abs(climb - CLIMB_PENALTY_S) <= 6,
    `the climb carries the ${CLIMB_PENALTY_S}s penalty, got ${climb}`);
  assert.ok(Math.abs(desc) <= 6, `the descents are ~neutral, got ${desc}`);
  // the finish stub is flat terrain, so its penalty lands in the flat bucket —
  // and its presence there is exactly what proves the stub was not dropped
  assert.ok(Math.abs(flat - FINISH_PENALTY_S) <= 8,
    `the flat bucket carries the finish penalty, got ${flat}`);
  assert.ok(Math.abs(overall - (CLIMB_PENALTY_S + FINISH_PENALTY_S)) <= 10,
    `overall ≈ both penalties (${CLIMB_PENALTY_S}+${FINISH_PENALTY_S}), got ${overall} — ` +
    `a dropped finish stub would read ~${CLIMB_PENALTY_S}`);

  // ── the stored comparison identifies its run ─────────────────────────────
  // (picking the RIGHT run out of a race-day shakeout is the sync's job and is
  // asserted in test_course_lens.py — asserting it here would be vacuous.)
  step = "matching";
  assert.ok(/Allgäu Panorama Halbmarathon/.test(text), "the race run is named");

  // ── the aftermath readout (the shin question) ────────────────────────────
  step = "aftermath";
  assert.ok(/after the descent/.test(text), "the post-descent verdict renders: " + text.slice(-400));

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
