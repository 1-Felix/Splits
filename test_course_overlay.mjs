// test_course_overlay.mjs — the post-race overlay on /course (add-course-lens 6.5).
//
// Builds a synthetic race from the plan ITSELF plus a known perturbation — the
// runner executes every kilometre exactly on target except the climb, which
// costs a deliberate +30 s — then asserts the page attributes that time to the
// climb and not to the flat or the descent. The actual run's total distance is
// deliberately WRONG by 64 m so the distance-domain normalisation (design D6)
// is exercised rather than assumed: without it, every kilometre boundary would
// drift and the climb's cost would smear across two rows.
import assert from "node:assert";
import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";
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
const ACTUAL_TOTAL_M = 21050;        // GPS drift vs the course's 21114.2

// ── synthesise the run ───────────────────────────────────────────────────────
// Per-kilometre durations = the declined-descent plan, plus the penalty on the
// steepest climb kilometre. Sampled every 100 m, interpolating inside each km.
function buildStreams() {
  const plan = paceTable(LENS, TARGET, LENS.steepDescentThreshold ?? -0.02);
  const climbKm = plan.reduce((a, r) => ((r.grade ?? 0) > (a.grade ?? 0) ? r : a));
  const edges = [{ courseM: 0, t: 0 }];
  let t = 0;
  for (const r of plan) {
    t += r.secondsForKm + (r.km === climbKm.km ? CLIMB_PENALTY_S : 0);
    edges.push({ courseM: r.km * 1000 <= LENS.distanceM ? r.km * 1000 : LENS.distanceM, t });
  }
  const scale = ACTUAL_TOTAL_M / LENS.distanceM;   // the run's own, drifted axis
  const d = [], time = [];
  for (let m = 0; m <= LENS.distanceM; m += 100) {
    let i = 1;
    while (i < edges.length - 1 && edges[i].courseM < m) i++;
    const a = edges[i - 1], b = edges[i];
    const frac = b.courseM === a.courseM ? 0 : (m - a.courseM) / (b.courseM - a.courseM);
    d.push(Math.round(m * scale));
    time.push(Math.round(a.t + (b.t - a.t) * frac));
  }
  d.push(ACTUAL_TOTAL_M);
  time.push(Math.round(edges[edges.length - 1].t));
  return { d, t: time, hr: d.map(() => 165), climbKm: climbKm.km };
}

const S = buildStreams();

function makeArchive(dir) {
  const db = new DatabaseSync(join(dir, "activity-archive.db"));
  db.exec(`CREATE TABLE activities (
    activity_id INTEGER PRIMARY KEY, start_time_local TEXT NOT NULL, type_key TEXT,
    name TEXT, distance_m REAL, duration_s REAL, avg_hr INTEGER, max_hr INTEGER,
    avg_cadence REAL, elevation_gain_m REAL, summary_json TEXT NOT NULL,
    detail_json TEXT, detail_distilled_json TEXT, detail_streams_json TEXT)`);
  db.prepare(`INSERT INTO activities (activity_id, start_time_local, type_key, name,
      distance_m, duration_s, avg_hr, max_hr, avg_cadence, elevation_gain_m,
      summary_json, detail_streams_json)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)`).run(
    777, RACE_DATE + " 09:15:00", "running", "Allgäu Panorama Halbmarathon",
    ACTUAL_TOTAL_M, S.t[S.t.length - 1], 168, 182, 162, 197, "{}",
    JSON.stringify({ d: S.d, t: S.t, hr: S.hr }));
  // a decoy on the same day: a short run that must NOT be picked as the race
  db.prepare(`INSERT INTO activities (activity_id, start_time_local, type_key, name,
      distance_m, duration_s, summary_json, detail_streams_json)
    VALUES (?,?,?,?,?,?,?,?)`).run(
    778, RACE_DATE + " 07:00:00", "running", "Shakeout", 2000, 700, "{}",
    JSON.stringify({ d: [0, 1000, 2000], t: [0, 350, 700] }));
  db.close();
}

const garminData = () => {
  const d = {
    profile: { name: "Felix", maxHR: 197 }, today: "2026-07-27",
    readiness: { score: 91, status: "High" }, hrZones: [],
    predictions: { halfNow: "2:01:48", halfGoal: "1:59:59" },
    personalBests: { tenK: "1:00:57", half: "2:19:07" },
    recentRuns: [], history: { monthly: [], weekly: [] }, heatmapKm: {},
    courseLens: LENS,
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
makeArchive(dataDir);
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
  assert.ok(Math.abs(flat) <= 8, `the flat is ~neutral, got ${flat}`);
  assert.ok(Math.abs(overall - CLIMB_PENALTY_S) <= 10,
    `overall ≈ the penalty, got ${overall}`);

  // ── the right activity was matched ───────────────────────────────────────
  step = "matching";
  assert.ok(/Allgäu Panorama Halbmarathon/.test(text), "the race run is named");
  assert.ok(!/Shakeout/.test(text), "the 2 km decoy on the same day is not the race");

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
