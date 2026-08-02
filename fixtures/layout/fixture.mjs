// fixtures/layout/fixture.mjs — the responsive gate's own data.
//
// `tools/style-audit.mjs layout` used to run against whatever telemetry
// happened to sit in the repo. With no data file it fell back to the pages'
// built-in demo data, `#block-section` never rendered, and the gate printed
// "LAYOUT: ALL PASS" while the real page overflowed by 67px. A gate that is
// green against an empty directory proves nothing.
//
// So the gate builds this fixture into a temp directory and points
// SPLITS_DATA_DIR / SPLITS_ARCHIVE_DIR at it. Everything here is synthetic —
// no personal telemetry is committed (see .gitignore) — but it is deliberately
// SHAPED to be hostile to the layout:
//
//   • long week labels ("Wk 13 · deload") in the block lens, so the week row's
//     identity column is stressed rather than flattered;
//   • a full insights block, so #sec-records and #sec-yoy are guaranteed to
//     exist and can be asserted rather than treated as optional;
//   • three streamed runs, so /archive lists rows, /compare renders a real
//     track stack and /run/:id renders a rep table with a route trace.
//
// The plan is the shipped default (plan-data.default.js) rather than a second
// copy: the sample plan is committed, deterministic, and already spans a race
// block, so the gate exercises what a fresh self-host actually sees.

import { copyFile, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL("./", import.meta.url));
const REPO = fileURLToPath(new URL("../../", import.meta.url));

// The plan's block runs 2026-06-29 → 2026-08-09; this "today" sits inside
// Wk 3, so the cockpit renders a live week and the block lens a current block.
export const FIXTURE_TODAY = "2026-07-16";

const seq = (n, f) => Array.from({ length: n }, (_, i) => f(i));
const round1 = (x) => Math.round(x * 10) / 10;

// ── history: 30 months of monthly series, 26 weeks of weekly series ─────────
const HISTORY = {
  vo2maxStartMonth: "2024-02",
  vo2max: seq(30, (i) => round1(41 + i * 0.16)),
  paceSecPerKm: seq(30, (i) => Math.round(492 - i * 1.4)),
  cadenceSpm: seq(30, (i) => Math.round(158 + i * 0.35)),
  weeklyKm: seq(26, (i) => round1(18 + 12 * Math.abs(Math.sin(i / 3.1)))),
  weeklyRuns: seq(26, (i) => 3 + (i % 3)),
  ctl: seq(26, (i) => round1(26 + i * 0.55)),
  atl: seq(26, (i) => round1(24 + i * 0.55 + 4 * Math.sin(i / 2))),
  sleep: seq(14, (i) => ({ hours: round1(6.4 + 1.4 * Math.abs(Math.sin(i / 2.3))), hrv: 52 + (i % 7) * 3, deepPct: 14 + (i % 5) })),
};

// ── insights ───────────────────────────────────────────────────────────────
const MONTHS_28 = seq(28, (i) => {
  const m = 5 + i;                       // from 2024-05
  return (2024 + Math.floor((m - 1) / 12)) + "-" + String(((m - 1) % 12) + 1).padStart(2, "0");
});
const effort = (sec, date, activityId) => ({ sec, date, activityId });

const INSIGHTS = {
  metricsVersion: 2,
  efficiency: {
    refHrBand: [128, 148],
    // every fourth month is a genuine gap — the engine's "thin evidence" state
    monthly: MONTHS_28.map((month, i) => (i % 7 === 3
      ? { month, paceSecPerKm: null, inBandMin: 4 }
      : { month, paceSecPerKm: Math.round(478 - i * 1.1), inBandMin: 40 + (i % 9) * 12 })),
  },
  cadence: {
    refPaceBand: [420, 480],
    monthly: MONTHS_28.map((month, i) => (i % 7 === 3
      ? { month, spm: null, inBandMin: 4 }
      : { month, spm: round1(160 + i * 0.22), inBandMin: 40 + (i % 9) * 12 })),
  },
  recordsFeed: seq(10, (i) => ({
    date: "2026-0" + (1 + (i % 7)) + "-1" + (i % 9),
    distance: ["1k", "mile", "5k", "10k", "half"][i % 5],
    oldSec: 320 + i * 40, newSec: 305 + i * 40,
  })),
  bestEfforts: {
    allTime: { oneK: effort(291, "2026-07-03", 9101), mile: effort(498, "2026-07-03", 9101),
               fiveK: effort(1626, "2026-07-03", 9101), tenK: effort(3657, "2026-06-28", 9102),
               half: effort(8347, "2025-12-28", 9103) },
    last90d: { oneK: effort(291, "2026-07-03", 9101), mile: effort(498, "2026-07-03", 9101),
               fiveK: effort(1626, "2026-07-03", 9101), tenK: effort(3657, "2026-06-28", 9102),
               half: null },
    byYear: {
      2024: { oneK: effort(318, "2024-09-14", null), mile: effort(545, "2024-09-14", null),
              fiveK: effort(1780, "2024-10-02", null), tenK: effort(3960, "2024-11-11", null), half: null },
      2025: { oneK: effort(306, "2025-08-19", null), mile: effort(504, "2025-08-19", null),
              fiveK: effort(1644, "2025-09-07", null), tenK: effort(3805, "2025-10-05", null),
              half: effort(8347, "2025-12-28", 9103) },
      2026: { oneK: effort(291, "2026-07-03", 9101), mile: effort(498, "2026-07-03", 9101),
              fiveK: effort(1626, "2026-07-03", 9101), tenK: effort(3657, "2026-06-28", 9102), half: null },
    },
  },
  trajectory: {
    goalSec: 7199,
    weekly: seq(52, (i) => ({
      week: (i < 21 ? "2025-W" + String(32 + i).padStart(2, "0") : "2026-W" + String(i - 20).padStart(2, "0")),
      riegelSec: Math.round(8900 - i * 22),
      garminSec: i % 3 === 0 ? Math.round(8700 - i * 18) : null,
      anchorId: i % 3 === 0 ? 9101 : null,
    })),
  },
  yoy: {
    2024: seq(12, (i) => ({ month: i + 1, km: round1(38 + i * 2.4), runs: 4 + (i % 4), paceSecPerKm: 486 - i })),
    2025: seq(12, (i) => ({ month: i + 1, km: round1(52 + i * 3.1), runs: 6 + (i % 5), paceSecPerKm: 470 - i })),
    2026: seq(7, (i) => ({ month: i + 1, km: round1(74 + i * 4.2), runs: 9 + (i % 4), paceSecPerKm: 458 - i })),
  },
};

// ── the block lens ─────────────────────────────────────────────────────────
// Deliberately long week identities: the audit's overflow was the week row's
// identity column, so the fixture must carry the worst label the plan format
// permits, not the tidiest.
const BLOCK_PHASES = ["Rebuild", "Base", "Build", "Build", "Peak", "Taper", "Race"];
const BLOCK_WEEK_LABELS = ["Wk 8", "Wk 9", "Wk 10", "Wk 11", "Wk 12", "Wk 13 · deload", "Wk 14"];
const DAY_STATUS = ["done", "done", "partial", "done", "missed", "swapped", "done"];

const blockWeek = (i) => {
  const mon = new Date(Date.UTC(2026, 5, 8 + i * 7));           // 2026-06-08 + i weeks
  const iso = (d) => d.toISOString().slice(0, 10);
  const sun = new Date(mon.getTime() + 6 * 86400000);
  const scored = i < 5;
  return {
    wk: BLOCK_WEEK_LABELS[i], mon: iso(mon), sun: iso(sun), phase: BLOCK_PHASES[i],
    label: iso(mon).slice(5), focus: "Threshold repeats and a long run back to 18 km",
    plannedKm: 24 + i * 2, actualKm: scored ? round1(21 + i * 2.1) : null, scored,
    counts: { done: 4, partial: 1, missed: 1, swapped: 1, unplanned: 0 },
    days: seq(7, (j) => {
      const date = iso(new Date(mon.getTime() + j * 86400000));
      const status = scored ? DAY_STATUS[(i + j) % 7] : "pending";
      const ran = status === "done" || status === "partial" || status === "swapped";
      return {
        date, plannedKind: j === 6 ? "cross" : "run", plannedKm: j === 5 ? 16 : 6,
        plannedLoad: j === 5 ? "Moderate" : "Easy",
        title: j === 5 ? "Long Run" : j === 2 ? "Threshold Repeats" : "Easy Run",
        status, ...(status === "partial" ? { reason: "distance" } : {}),
        ...(ran ? { actualKm: j === 5 ? 15.4 : 5.8, actualPaceS: 372 + j, actualHr: 138 + j,
                    activityId: [9101, 9102, 9103][(i + j) % 3] } : {}),
      };
    }),
  };
};

const BLOCK_WEEKS = seq(7, blockWeek);
const BLOCK_CURRENT = {
  raceName: "Fixture Half Marathon", raceDate: "2026-08-09", goalTime: "1:59:59",
  window: { start: "2026-06-08", end: "2026-08-09" },
  isComplete: false, weeksTotal: 7, weekNow: 5,
  weeks: BLOCK_WEEKS,
  execution: { percentExecuted: 84, scoredDays: 34, qualityHitRate: { hit: 3, of: 4 },
               kmPlanned: 210, kmPlannedToDate: 138, kmActual: 129.4,
               counts: { done: 24, partial: 4, missed: 4, swapped: 2, unplanned: 1 } },
  adaptation: {
    ef: { startRuns: 5, endRuns: 5, startPaceSPerKm: 471.2, endPaceSPerKm: 458.6, deltaSPerKm: -12.6 },
    cadence: { startRuns: 6, endRuns: 5, startSpm: 162.4, endSpm: 165.1, deltaSpm: 2.7 },
    // one null metric so the explicit insufficient-data mark renders too
    goalGap: { goalS: 7199, startDate: "2026-06-08", startHalfS: 7526,
               nowDate: FIXTURE_TODAY, nowHalfS: null, gapStartS: 327,
               gapNowS: null, deltaS: null, reason: "no-predictions" },
    records: [
      { distance: "1k", sec: 291, prevSec: 306, date: "2026-07-03", activityId: 9101 },
      { distance: "5k", sec: 1626, prevSec: 1644, date: "2026-07-03", activityId: 9101 },
    ],
  },
  forward: { weeksRemaining: 2, kmRemaining: 33,
             silhouette: [{ wk: "Wk 13 · deload", mon: "2026-07-27", km: 21, phase: "Taper" },
                          { wk: "Wk 14", mon: "2026-08-03", km: 12, phase: "Race" }],
             undetailedWeeks: [] },
  summary: { raceName: "Fixture Half Marathon", raceDate: "2026-08-09",
             window: { start: "2026-06-08", end: "2026-08-09" }, isComplete: false,
             weeksTotal: 7, percentExecuted: 84, kmPlanned: 210, kmActual: 129.4,
             efDeltaSPerKm: -12.6, cadenceDeltaSpm: 2.7, goalGapDeltaS: null, recordsCount: 2 },
};

// ── compliance (the cockpit's THIS WEEK marks) ─────────────────────────────
const COMPLIANCE = {
  complianceVersion: 3,
  days: BLOCK_WEEKS.slice(2).flatMap((w) => w.days.map((d) => ({
    date: d.date, wk: w.wk, plannedKind: d.plannedKind, plannedKm: d.plannedKm,
    plannedLoad: d.plannedLoad, title: d.title, status: d.status,
    actualKm: d.actualKm ?? null, actualPaceS: d.actualPaceS ?? null, actualHr: d.actualHr ?? null,
  }))),
  weeks: BLOCK_WEEKS.map((w) => ({ wk: w.wk, mon: w.mon, sun: w.sun,
    plannedKm: w.plannedKm, actualKm: w.actualKm ?? 0, runsPlanned: 6, runsDone: 5 })),
};

// ── recent runs (cockpit drill-downs) ──────────────────────────────────────
const recentRun = (date, km, timeStr, pace, hr, cad) => ({
  date, type: "Run", km, time: timeStr, pace, hr, cad, vo2: 45.6,
  detail: {
    splits: seq(Math.round(km), (i) => ({ km: i + 1, pace: pace + (i % 3) * 11 - 11, hr: hr + (i % 4) - 1 })),
    hrSeries: seq(30, (i) => hr - 12 + Math.round(18 * Math.sin(i / 5))),
    driftBpm: 6, zoneMin: [4, 22, 9, 2, 0], tempC: 18, te: 3.1, load: 132,
    elevGain: 58, splitShape: "even",
  },
});

// ── telemetry ──────────────────────────────────────────────────────────────
export const FIXTURE_TELEMETRY = {
  today: FIXTURE_TODAY,
  profile: { name: "Fixture", age: 28, restingHR: 50, maxHR: 190, weightKg: 70.0, vo2maxCurrent: 45.6 },
  readiness: { score: 72, status: "Moderate", hrv: 61, restingHR: 50, sleepHours: 7.2,
               trainingLoad: 41, loadStatus: "Maintaining" },
  hrZones: [
    { z: 1, label: "Recovery", min: 31, lo: 95, hi: 114 },
    { z: 2, label: "Endurance", min: 47, lo: 114, hi: 133 },
    { z: 3, label: "Tempo", min: 50, lo: 133, hi: 152 },
    { z: 4, label: "Threshold", min: 9, lo: 152, hi: 171 },
    { z: 5, label: "VO2 max", min: 1, lo: 171, hi: 190 },
  ],
  predictions: { fiveK: "24:44", tenK: "52:54", halfNow: "2:01:59", halfGoal: "1:59:59", trend: "flat" },
  personalBests: {
    oneK: { time: "4:51", date: "2026-07-03" }, oneMile: { time: "8:18", date: "2026-07-03" },
    fiveK: { time: "27:06", date: "2026-07-03" }, tenK: { time: "1:00:57", date: "2026-06-28" },
    half: { time: "2:19:07", date: "2025-12-28" }, longestRunKm: 21.3,
  },
  heatmapKm: seq(365, (i) => (i % 3 === 0 ? 0 : round1(3 + 9 * Math.abs(Math.sin(i / 11))))),
  recentRuns: [
    recentRun("2026-07-15", 6, "37:12", 372, 148, 166),
    recentRun("2026-07-13", 16, "1:41:20", 380, 143, 163),
    recentRun("2026-07-11", 8, "48:04", 360, 152, 168),
  ],
  history: HISTORY,
  insights: INSIGHTS,
  compliance: COMPLIANCE,
  blockLens: { lensVersion: 2, past: [], current: BLOCK_CURRENT },
};

// ── the three-run archive ──────────────────────────────────────────────────
const N = 600;
const streamsFor = (baseV, baseHr) => ({
  t: seq(N, (i) => i * 2),
  d: seq(N, (i) => Math.round(i * 10.05)),
  hr: seq(N, (i) => baseHr + Math.round(14 * Math.sin(i / 40))),
  v: seq(N, (i) => +(baseV + 0.4 * Math.sin(i / 25)).toFixed(2)),
  gap: seq(N, (i) => +(baseV + 0.1 + 0.3 * Math.sin(i / 25)).toFixed(2)),
  cad: seq(N, (i) => 162 + (i % 5)),
  elev: seq(N, (i) => +(420 + 25 * Math.sin(i / 80)).toFixed(1)),
  lat: seq(N, (i) => +(47.37 + 0.004 * Math.sin(i / 90)).toFixed(5)),
  lon: seq(N, (i) => +(8.53 + 0.006 * (i / N)).toFixed(5)),
});
const detailFor = (kms, pace, hr) => ({
  splits: seq(kms, (i) => ({ km: i + 1, pace: pace + (i % 3) * 12 - 12, hr: hr + i })),
  hrSeries: [135, 140, 145, 148], driftBpm: 6, zoneMin: [4, 18, 8, 2, 0],
  tempC: 19, te: 3.2, load: 140, elevGain: 60, splitShape: "even",
});

// a 5×1 km rep document on the newest run, so /run/:id renders its rep table
// (the page's widest component) and style-audit's run resolver prefers it
const REP_SEGMENTS = (() => {
  const out = [{ idx: 1, role: "warmup", t0: 0, t1: 600, d0: 0, d1: 1560,
                 durS: 600, distM: 1560, paceS: 385, gapS: 379, hr: 132, cad: null }];
  let t = 600, d = 1560;
  for (let i = 0; i < 5; i++) {
    out.push({ idx: out.length + 1, role: "work", rep: i + 1, t0: t, t1: t + 250,
               d0: d, d1: d + 1000, durS: 250, distM: 1000,
               paceS: 330 + i * 3, gapS: 326 + i * 3, hr: 168 + i, cad: null });
    t += 250; d += 1000;
    if (i < 4) {
      out.push({ idx: out.length + 1, role: "recovery", t0: t, t1: t + 60, d0: d, d1: d + 140,
                 durS: 60, distM: 140, paceS: 430, gapS: 424, hr: 144, cad: null });
      t += 60; d += 140;
    }
  }
  out.push({ idx: out.length + 1, role: "cooldown", t0: t, t1: t + 300, d0: d, d1: d + 700,
             durS: 300, distM: 700, paceS: 415, gapS: 409, hr: 138, cad: null });
  return out;
})();
const REP_DOC = {
  version: 6, shape: "reps", source: "laps", calibrated: true, confidence: 0.86,
  asserts: true, label: "5×1 km", guidedBy: null, segments: REP_SEGMENTS,
  set: { found: 5, prescribed: null, nominalDistM: 1000, varied: false, paceS: 336,
         paceCvPct: 1.8, fadePct: 2.4, recoveryS: 60, recoveryHrDrop: 24, reps: [] },
  quality: { workDistM: 5000, workDurS: 1250, zone: "Z4" },
};

export function buildFixtureArchive(dir) {
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
  db.exec(`CREATE TABLE run_intervals (
    activity_id INTEGER PRIMARY KEY, lens_version INTEGER NOT NULL,
    start_time_local TEXT NOT NULL, shape TEXT NOT NULL, label TEXT,
    confidence REAL, source TEXT NOT NULL, work_dist_m REAL, work_dur_s REAL,
    doc_json TEXT NOT NULL, computed_at TEXT NOT NULL)`);
  db.exec(`CREATE TABLE plan_compliance (
    id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, wk TEXT,
    snapshot_id INTEGER NOT NULL, compliance_version INTEGER NOT NULL,
    planned_kind TEXT, planned_km REAL, planned_load TEXT, planned_title TEXT,
    status TEXT NOT NULL, reason TEXT, actual_km REAL, actual_pace_s REAL,
    actual_hr INTEGER, activity_id INTEGER, quality_json TEXT, updated_at TEXT NOT NULL)`);

  const act = db.prepare(`INSERT INTO activities (activity_id, start_time_local, type_key,
      name, distance_m, duration_s, avg_hr, max_hr, avg_cadence, elevation_gain_m,
      summary_json, detail_json, first_seen_at, updated_at, detail_distilled_json,
      detail_streams_json)
    VALUES (?, ?, 'running', ?, ?, ?, ?, ?, ?, ?, '{}', '{}', 'x', 'x', ?, ?)`);
  act.run(9101, "2026-07-15 07:30:00", "Fixture Threshold Repeats", 8420, 3010, 152, 178, 168, 62,
    JSON.stringify(detailFor(8, 360, 152)), JSON.stringify(streamsFor(3.0, 152)));
  act.run(9102, "2026-07-13 08:10:00", "Fixture Long Run Around The Lake", 16040, 6080, 143, 161, 163, 140,
    JSON.stringify(detailFor(16, 380, 143)), JSON.stringify(streamsFor(2.7, 143)));
  act.run(9103, "2026-07-11 06:45:00", "Fixture Easy Shakeout", 6020, 2280, 138, 150, 166, 30,
    JSON.stringify(detailFor(6, 372, 138)), JSON.stringify(streamsFor(2.9, 138)));

  const met = db.prepare(`INSERT INTO run_metrics (activity_id, metrics_version,
      start_time_local, is_treadmill, best_1k_s, best_mile_s, best_5k_s, best_10k_s,
      best_half_s, refhr_time_s, refhr_dist_m, refpace_time_s, refpace_cadence_x_time,
      refhr_pace_s_per_km, refpace_cadence_spm, computed_at)
    VALUES (?, 2, ?, 0, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, 'x')`);
  met.run(9101, "2026-07-15 07:30:00", 291, 498, 1626, null, 1800, 3960.0, 1800, 302400.0, 454.5, 168.0);
  met.run(9102, "2026-07-13 08:10:00", 318, 540, 1710, 3657, 3600, 8000.0, 3600, 612000.0, 450.0, 170.0);
  met.run(9103, "2026-07-11 06:45:00", 330, 560, 1780, null, 1500, 3200.0, 1500, 252000.0, 458.0, 166.0);

  db.prepare(`INSERT INTO run_intervals VALUES (?,?,?,?,?,?,?,?,?,?,?)`).run(
    9101, 6, "2026-07-15 07:30:00", "reps", "5×1 km", 0.86, "laps", 5000, 1250,
    JSON.stringify(REP_DOC), "2026-07-15T09:00:00");

  const comp = db.prepare(`INSERT INTO plan_compliance (date, wk, snapshot_id,
      compliance_version, planned_kind, planned_km, planned_load, planned_title,
      status, reason, actual_km, actual_pace_s, actual_hr, activity_id, updated_at)
    VALUES (?, ?, 1, 3, 'run', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'x')`);
  comp.run("2026-07-15", "Wk 12", 8, "Hard", "Threshold Repeats", "done", null, 8.4, 357, 152, 9101);
  comp.run("2026-07-13", "Wk 12", 18, "Moderate", "Long Run", "partial", "distance", 16.0, 379, 143, 9102);
  comp.run("2026-07-11", "Wk 11", 6, "Easy", "Easy Run", "done", null, 6.0, 378, 138, 9103);
  db.close();
}

// Write the whole fixture data dir. `dir` must already exist.
//
// The course lens is the committed Sonthofen fixture — a real engine document,
// so /course renders its profile, pace plan and decisive segments rather than
// its empty state, and every page's nav model yields the full four tabs (the
// widest chrome the tab bar has to lay out).
export async function writeLayoutFixture(dir) {
  const courseLens = JSON.parse(await readFile(join(HERE, "..", "course", "sonthofen-lens.json"), "utf8"));
  const telemetry = { ...FIXTURE_TELEMETRY, courseLens };
  await writeFile(join(dir, "garmin-data.js"),
    "/* GENERATED from fixtures/layout/fixture.mjs — the responsive gate's data. */\n" +
    "export const garminData = " + JSON.stringify(telemetry, null, 1) + ";\n");
  // The plan is the shipped default plus a deliberately HOSTILE coach block:
  // the real note is one 5,503-character text node with no newline in it and
  // the real log runs to 17 entries, which is what made the cockpit 18.3
  // screens tall. The sample plan's 431-character note and single log entry
  // would never exercise the paragraph split, the phone clamp or the sheet.
  const plan = await readFile(join(REPO, "plan-data.default.js"), "utf8");
  await writeFile(join(dir, "plan-data.js"), plan + "\n" + FIXTURE_COACH_OVERRIDE);
  buildFixtureArchive(dir);
  return dir;
}

const LONG_NOTE = [
  "Aug 1 check-in, eight days out.",
  "The block did what it was asked to do and the numbers say so plainly.",
  "Friday's session held pace within one and a half percent across three kilometre repeats, which is the discipline the race needs.",
  "Heart rate climbed through the set in the heat, so the cool morning air is worth several beats.",
  "CHANGES: (1) Sunday's long run becomes sixty to seventy-five minutes on the bike, with the gel at forty minutes so the fuelling rehearsal survives.",
  "(2) The descent drill is cut, and the cost is named rather than hidden: the quads meet kilometre fourteen unrehearsed.",
  "(3) Wednesday's four kilometres becomes the gate, and what it says decides the opening pace.",
  "(4) Friday's four hundreds are conditional on that gate.",
  "(5) Cadence becomes an explicit race instruction, because it drifted the wrong way across this block.",
  "Honest read: a patient, controlled race lands somewhere between two hours five and two hours twelve.",
  "Floor before ceiling, unchanged.",
].join(" ");

const FIXTURE_COACH_OVERRIDE = `
/* fixture only — see fixtures/layout/fixture.mjs */
planData.coach = {
  ...(planData.coach || {}),
  headline: 'Eight days out — sharpen, do not pile on.',
  note: ${JSON.stringify(LONG_NOTE)},
  log: ${JSON.stringify(seq(9, (i) => ({
    date: "2026-0" + (7 - Math.floor(i / 5)) + "-" + String(28 - i * 3).padStart(2, "0"),
    text: "Session design and the sub-two conversation, adjustment " + (9 - i)
        + ". The week's load was repriced against what the last block actually delivered, and the "
        + "long run moved to keep the quality day intact.",
  })))},
};
`;

export const FIXTURE_DIR = HERE;
