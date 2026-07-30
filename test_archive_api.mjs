// Integration tests for the read-only archive API (progress-views group 4).
// Patterned on test_plan_push.mjs: real server processes over temp data dirs.
// Needs a Node with node:sqlite (stable in 24; experimental-but-present in 22.19).
import assert from "node:assert";
import http from "node:http";
import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { gunzipSync } from "node:zlib";
import { DatabaseSync } from "node:sqlite";

const ROOT = dirname(fileURLToPath(import.meta.url));

// The recent-run `detail` contract of garmin-data.js — the by-id endpoint must
// serve exactly this shape, verbatim from detail_distilled_json.
const DETAIL = {
  splits: [{ km: 1, pace: 341, hr: 152 }, { km: 2, pace: 339, hr: 154 }],
  hrSeries: [140, 150, 152, 154],
  driftBpm: 4,
  zoneMin: [0, 12, 24, 6, 0],
  tempC: 18,
  te: 3.6,
  load: 182,
  elevGain: 44,
  splitShape: "even",
};

const RAW_MARKER = "raw-garmin-payload-marker";

// A recognisable fake tile blob — the endpoint must serve these exact bytes.
const TILE_PNG = Buffer.from("\x89PNG-fake-tile-bytes-15/17000/11300", "latin1");

// Columnar streams (run-detail D1), stored as ONE exact string — the endpoint
// must serve these bytes verbatim, never parse-and-reserialise. Long enough
// that gzip negotiation engages.
const STREAMS_TEXT = JSON.stringify({
  t: Array.from({ length: 400 }, (_, i) => i),
  d: Array.from({ length: 400 }, (_, i) => i * 3),
  hr: Array.from({ length: 400 }, (_, i) => (i % 7 === 3 ? null : 140 + (i % 20))),
  v: Array.from({ length: 400 }, (_, i) => +(2.5 + (i % 10) / 20).toFixed(2)),
  lat: Array.from({ length: 400 }, (_, i) => +(47.37 + i * 0.00001).toFixed(5)),
  lon: Array.from({ length: 400 }, (_, i) => +(8.53 + i * 0.00001).toFixed(5)),
});

// Block-lens documents (add-block-lens 2.x), stored as EXACT strings — the
// by-date endpoint must serve these bytes verbatim, never parse-and-
// reserialise; the listing lifts the summary EMBEDDED by the Python engine.
// NOTE: this archive deliberately carries NO plan_snapshots / plan_compliance
// tables — a 200 from the block endpoints proves they touch nothing beyond a
// SELECT on block_lens (no request-time derivation).
const BLOCK_SUMMARY_CURRENT = {
  raceName: "Sonthofen Half", raceDate: "2026-08-09",
  isComplete: false, weeksTotal: 5, percentExecuted: 69,
  kmPlanned: 116, kmActual: 24.2, efDeltaSPerKm: null,
  cadenceDeltaSpm: 0.0, goalGapDeltaS: -50, recordsCount: 0,
};
const BLOCK_DOC_CURRENT = JSON.stringify({
  raceName: "Sonthofen Half", raceDate: "2026-08-09", isComplete: false,
  weeks: [{ wk: "Wk 1", days: [{ date: "2026-07-06", status: "done" }] }],
  summary: BLOCK_SUMMARY_CURRENT,
});
const BLOCK_SUMMARY_SPRING = {
  raceName: "Spring Half", raceDate: "2025-04-12",
  isComplete: true, weeksTotal: 4, percentExecuted: 100,
  kmPlanned: 55, kmActual: 55, efDeltaSPerKm: -12.0,
  cadenceDeltaSpm: 3.0, goalGapDeltaS: -200, recordsCount: 1,
};
const BLOCK_DOC_SPRING = JSON.stringify({
  raceName: "Spring Half", raceDate: "2025-04-12", isComplete: true,
  weeks: [{ wk: "Wk 1" }], summary: BLOCK_SUMMARY_SPRING,
});
const BLOCK_DOC_AUTUMN = JSON.stringify({
  raceName: "Autumn 10K", raceDate: "2024-10-01", isComplete: true,
  weeks: [], summary: { raceName: "Autumn 10K", raceDate: "2024-10-01", isComplete: true },
});

// run_intervals fixtures (add-interval-lens, schema v11): REP_RUN_ID is a
// brand-new fixture activity carrying a full document; PLAIN_RUN_ID REUSES
// an existing fixture activity (run 20, above) that gets no run_intervals
// row at all — a real 200 with the field genuinely absent, never a 404
// masquerading as an absent field.
const REP_RUN_ID = 9001;
const PLAIN_RUN_ID = 20;
const REP_DOC = {
  version: 1, shape: "reps", source: "stream", confidence: 0.86,
  label: "5×1 km", guidedBy: null,
  segments: [{ idx: 1, role: "warmup", t0: 0, t1: 600, d0: 0, d1: 1560,
               durS: 600, distM: 1560, paceS: 385, gapS: null, hr: 132, cad: null }],
  set: { found: 5, prescribed: null, nominalDistM: 1000, varied: false,
         paceS: 334, paceCvPct: 1.8, fadePct: 2.4, recoveryS: 60,
         recoveryHrDrop: 24, reps: [] },
  quality: { workDistM: 5000, workDurS: 1250, zone: "Z4" },
};

function makeArchive(dir) {
  const db = new DatabaseSync(join(dir, "activity-archive.db"));
  db.exec(`CREATE TABLE activities (
    activity_id       INTEGER PRIMARY KEY,
    start_time_local  TEXT NOT NULL,
    type_key          TEXT,
    name              TEXT,
    distance_m        REAL,
    duration_s        REAL,
    avg_hr            INTEGER,
    max_hr            INTEGER,
    avg_cadence       REAL,
    elevation_gain_m  REAL,
    summary_json      TEXT NOT NULL,
    detail_json       TEXT,
    detail_fetched_at TEXT,
    first_seen_at     TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    detail_distilled_json TEXT,
    detail_streams_json TEXT
  )`);
  const ins = db.prepare(
    `INSERT INTO activities (activity_id, start_time_local, type_key, name,
       distance_m, duration_s, avg_hr, max_hr, avg_cadence, elevation_gain_m,
       summary_json, detail_json, first_seen_at, updated_at, detail_distilled_json,
       detail_streams_json)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'x', 'x', ?, ?)`);
  const raw = JSON.stringify({ secret: RAW_MARKER });
  // 4 runs across 2025/2026 + one strength session; run 20 has no distilled
  // detail and no streams
  ins.run(10, "2025-03-10 08:01:00", "running", "Tempo Tuesday",
    10210.5, 3480.0, 156, 171, 168.5, 44.0, raw, raw, JSON.stringify(DETAIL), STREAMS_TEXT);
  ins.run(20, "2026-02-14 09:00:00", "running", "Valentine Long Run",
    21100.0, 7200.0, 148, 165, 166.0, 120.0, raw, raw, null, null);
  ins.run(30, "2025-06-01 18:00:00", "strength_training", "Gym",
    null, 3600.0, 110, 140, null, null, raw, null, null, null);
  ins.run(40, "2025-09-01 07:30:00", "running", "September Base",
    8000.0, 2900.0, 140, 150, 165.0, 30.0, raw, raw, null, null);
  ins.run(50, "2025-11-20 07:30:00", "running", "November Base",
    9000.0, 3200.0, 141, 152, 165.0, 35.0, raw, raw, null, null);
  // a second March-2025 run (treadmill) + run_metrics rows for the
  // run-metrics endpoint (chart-drill 2.x): run 10 contributed (in-band time),
  // run 60 has zero in-band time, run 15 has NO metrics row at all
  ins.run(60, "2025-03-22 06:45:00", "treadmill_running", "Belt Miles",
    6000.0, 2100.0, 151, 160, 167.0, 0.0, raw, raw, null, null);
  ins.run(15, "2025-03-30 10:00:00", "running", "Unanalysed Sunday",
    5000.0, 1800.0, 139, 149, 164.0, 20.0, raw, raw, null, null);
  db.exec(`CREATE TABLE run_metrics (
    activity_id      INTEGER PRIMARY KEY REFERENCES activities(activity_id),
    metrics_version  INTEGER NOT NULL,
    start_time_local TEXT NOT NULL,
    is_treadmill     INTEGER NOT NULL,
    best_1k_s REAL, best_mile_s REAL, best_5k_s REAL,
    best_10k_s REAL, best_half_s REAL,
    refhr_time_s REAL, refhr_dist_m REAL,
    refpace_time_s REAL, refpace_cadence_x_time REAL,
    refhr_pace_s_per_km REAL, refpace_cadence_spm REAL,
    computed_at TEXT NOT NULL
  )`);
  const mins = db.prepare(
    `INSERT INTO run_metrics (activity_id, metrics_version, start_time_local,
       is_treadmill, refhr_time_s, refhr_dist_m, refpace_time_s,
       refpace_cadence_x_time, refhr_pace_s_per_km, refpace_cadence_spm,
       computed_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'x')`);
  mins.run(10, 2, "2025-03-10 08:01:00", 0, 1543.2, 3390.7, 1201.0, 204170.0, 455.2, 170.0);
  mins.run(60, 2, "2025-03-22 06:45:00", 1, 0.0, 0.0, 0.0, 0.0, null, null);
  mins.run(20, 2, "2026-02-14 09:00:00", 0, 900.0, 2000.0, 0.0, 0.0, 450.0, null);
  // route-basemap (schema v8): the deduped tile store + run 10's map rect —
  // run 20 deliberately has NO map row (its payload must omit `map`)
  db.exec(`CREATE TABLE map_tiles (
    z INTEGER NOT NULL, x INTEGER NOT NULL, y INTEGER NOT NULL,
    png BLOB NOT NULL, fetched_at TEXT NOT NULL,
    PRIMARY KEY (z, x, y))`);
  db.exec(`CREATE TABLE activity_maps (
    activity_id INTEGER PRIMARY KEY REFERENCES activities(activity_id),
    z INTEGER NOT NULL, x0 INTEGER NOT NULL, y0 INTEGER NOT NULL,
    x1 INTEGER NOT NULL, y1 INTEGER NOT NULL,
    crop_x REAL NOT NULL, crop_y REAL NOT NULL, crop_size REAL NOT NULL,
    updated_at TEXT NOT NULL)`);
  const tins = db.prepare("INSERT INTO map_tiles (z, x, y, png, fetched_at) VALUES (?, ?, ?, ?, 'x')");
  tins.run(15, 17000, 11300, TILE_PNG);
  tins.run(15, 17001, 11300, Buffer.from("second-fake-tile"));
  db.prepare(`INSERT INTO activity_maps (activity_id, z, x0, y0, x1, y1,
      crop_x, crop_y, crop_size, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'x')`)
    .run(10, 15, 17000, 11300, 17001, 11300, 4352123.5, 2893456.25, 412.75);
  // block-lens rows (schema v9), inserted OUT of race-date order so the
  // listing's ORDER BY is what sorts them
  db.exec(`CREATE TABLE block_lens (
    race_date    TEXT PRIMARY KEY,
    race_name    TEXT NOT NULL,
    lens_version INTEGER NOT NULL,
    is_complete  INTEGER NOT NULL,
    block_json   TEXT NOT NULL,
    updated_at   TEXT NOT NULL)`);
  const bins = db.prepare("INSERT INTO block_lens VALUES (?, ?, ?, ?, ?, ?)");
  bins.run("2025-04-12", "Spring Half", 1, 1, BLOCK_DOC_SPRING, "2026-07-17T04:00:00");
  bins.run("2026-08-09", "Sonthofen Half", 1, 0, BLOCK_DOC_CURRENT, "2026-07-17T04:00:00");
  bins.run("2024-10-01", "Autumn 10K", 1, 1, BLOCK_DOC_AUTUMN, "2026-07-17T04:00:00");

  // course rows (schema v10, add-course-lens) — one course with a stored map
  db.exec(`CREATE TABLE courses (
    course_id    INTEGER PRIMARY KEY,
    course_name  TEXT NOT NULL,
    race_date    TEXT,
    distance_m   REAL NOT NULL,
    gain_m       REAL,
    loss_m       REAL,
    bbox_json    TEXT NOT NULL,
    points_json  TEXT NOT NULL,
    lens_version INTEGER NOT NULL,
    lens_json    TEXT NOT NULL,
    update_date  TEXT,
    fetched_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL)`);
  db.exec(`CREATE TABLE course_maps (
    course_id INTEGER PRIMARY KEY, z INTEGER NOT NULL,
    x0 INTEGER NOT NULL, y0 INTEGER NOT NULL, x1 INTEGER NOT NULL, y1 INTEGER NOT NULL,
    crop_x REAL NOT NULL, crop_y REAL NOT NULL, crop_size REAL NOT NULL,
    updated_at TEXT NOT NULL)`);
  db.prepare("INSERT INTO courses VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)").run(
    493447940, "Allgau Panorama Halbmarathon", "2026-08-09", 21114.2, 197.43, 200.03,
    COURSE_BBOX, '{"d":[0,1000],"lat":[47.5,47.51],"lon":[10.27,10.28],"elev":[741,742]}',
    1, COURSE_LENS_DOC, "2026-07-26T10:00:00", "2026-07-26T22:00:00", "2026-07-26T22:00:00");
  db.prepare("INSERT INTO course_maps VALUES (?,?,?,?,?,?,?,?,?,?)").run(
    493447940, 13, 4300, 2860, 4302, 2862, 12.5, 8.25, 700.0, "2026-07-26T22:00:00");

  // run_intervals rows (schema v11, add-interval-lens): one run with a full
  // document. This is a NEW fixture activity, dated newer than everything
  // above, so it also rides the newest page of the plain listing. Run 20
  // (already inserted, above) deliberately gets no row here — that is
  // PLAIN_RUN_ID's whole point.
  ins.run(REP_RUN_ID, "2026-07-10 06:51:15", "running", "Track 5×1 km",
    6560.0, 1850.0, 158, 178, 172.0, 10.0, raw, raw, null, null);
  db.exec(`CREATE TABLE run_intervals (
    activity_id INTEGER PRIMARY KEY, lens_version INTEGER NOT NULL,
    start_time_local TEXT NOT NULL, shape TEXT NOT NULL, label TEXT,
    confidence REAL, source TEXT NOT NULL, work_dist_m REAL, work_dur_s REAL,
    doc_json TEXT NOT NULL, computed_at TEXT NOT NULL)`);
  db.prepare(`INSERT INTO run_intervals VALUES (?,?,?,?,?,?,?,?,?,?,?)`).run(
    REP_RUN_ID, 1, "2026-07-10 06:51:15", "reps", "5×1 km", 0.86, "stream",
    5000, 1250, JSON.stringify(REP_DOC), "2026-07-27T09:00:00");
  db.close();
}

const COURSE_BBOX = JSON.stringify({ lowerLeft: { latitude: 47.43, longitude: 10.26 },
                                    upperRight: { latitude: 47.52, longitude: 10.29 } });
const COURSE_LENS_DOC = JSON.stringify({
  lensVersion: 1, degraded: false, elevationCoverage: 1,
  perKm: [{ km: 1, endM: 1000, lengthM: 1000, grade: 0.004, factor: 1.02, elevEnd: 742 }],
  segments: [{ kind: "climb", startKm: 11.84, endKm: 13.38, changeM: 102.2, grade: 0.0663 }],
  model: { curve: "minetti-2002", calibrated: true, damping: 0.3323, residual: 0.007 },
  elevationCostFraction: 0.00229, steepDescentGiveawayFraction: 0.0075,
});

function startServer(port, env) {
  const child = spawn(process.execPath, ["serve.mjs"], {
    cwd: ROOT,
    env: { ...process.env, PORT: String(port), SYNC_ON_BOOT: "off", SYNC_AT: "off", ...env },
    stdio: ["ignore", "ignore", "pipe"],
  });
  let err = "";
  child.stderr.on("data", (d) => (err += d));
  child.errRef = () => err;
  return child;
}

async function waitReady(base, errRef) {
  for (let i = 0; i < 60; i++) {
    try {
      const r = await fetch(base + "/api/status");
      if (r.ok) return;
    } catch { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error("server not ready\n" + (errRef ? errRef() : ""));
}

// A pre-insight-metrics archive: activities only, NO run_metrics table. The
// run-metrics endpoint must serve identity rows with null metric fields — a
// missing derived table is "not yet analysed", never an outage.
function makeBareArchive(dir) {
  const db = new DatabaseSync(join(dir, "activity-archive.db"));
  db.exec(`CREATE TABLE activities (
    activity_id INTEGER PRIMARY KEY, start_time_local TEXT NOT NULL, type_key TEXT,
    name TEXT, distance_m REAL, duration_s REAL, avg_hr INTEGER, max_hr INTEGER,
    avg_cadence REAL, elevation_gain_m REAL, summary_json TEXT NOT NULL,
    detail_json TEXT, detail_fetched_at TEXT, first_seen_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, detail_distilled_json TEXT)`);
  db.prepare(`INSERT INTO activities (activity_id, start_time_local, type_key,
      name, distance_m, duration_s, avg_hr, max_hr, avg_cadence,
      elevation_gain_m, summary_json, first_seen_at, updated_at)
    VALUES (?, ?, 'running', ?, ?, ?, ?, ?, ?, ?, '{}', 'x', 'x')`)
    .run(70, "2025-03-05 07:00:00", "Old Faithful", 7000.0, 2500.0, 142, 155, 164.0, 25.0);
  db.close();
}

const dataDir = await mkdtemp(join(tmpdir(), "splits-archive-test-"));
const emptyDir = await mkdtemp(join(tmpdir(), "splits-archive-empty-"));
const bareDir = await mkdtemp(join(tmpdir(), "splits-archive-bare-"));
const brokenDir = await mkdtemp(join(tmpdir(), "splits-archive-broken-"));
makeArchive(dataDir);
makeBareArchive(bareDir);
// provisioned-but-unusable: the file exists, SQLite can't read it → 503
await writeFile(join(brokenDir, "activity-archive.db"), "this is not a database");
const dbPath = join(dataDir, "activity-archive.db");
const dbBytesBefore = await readFile(dbPath);

const PORT = 8140;
const B = "http://localhost:" + PORT;          // archive in DATA_DIR (default flow)
const Bmissing = "http://localhost:" + (PORT + 1); // no archive anywhere → 503
const Boverride = "http://localhost:" + (PORT + 2); // SPLITS_ARCHIVE_DIR override
const Bbare = "http://localhost:" + (PORT + 3);    // pre-metrics archive (no run_metrics table)
const Bbroken = "http://localhost:" + (PORT + 4);  // corrupt archive file → 503

const server = startServer(PORT, { SPLITS_DATA_DIR: dataDir });
const serverMissing = startServer(PORT + 1, { SPLITS_DATA_DIR: emptyDir });
const serverOverride = startServer(PORT + 2, { SPLITS_DATA_DIR: emptyDir, SPLITS_ARCHIVE_DIR: dataDir });
const serverBare = startServer(PORT + 3, { SPLITS_DATA_DIR: bareDir });
const serverBroken = startServer(PORT + 4, { SPLITS_DATA_DIR: brokenDir });

const list = (base, qs = "") => fetch(base + "/api/archive/activities" + qs);
const byId = (base, id) => fetch(base + "/api/archive/activities/" + id);
const streams = (base, id) => fetch(base + "/api/archive/activities/" + id + "/streams");
const runMetrics = (base, qs = "") => fetch(base + "/api/archive/run-metrics" + qs);

// raw node:http request (undici's fetch silently decompresses, hiding the very
// Content-Encoding the gzip assertion needs to observe — test_compression.mjs
// establishes this pattern)
const rawGet = (base, path, headers = {}) => new Promise((resolve, reject) => {
  const req = http.request(base + path, { headers }, (res) => {
    const chunks = [];
    res.on("data", (c) => chunks.push(c));
    res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks) }));
  });
  req.on("error", reject);
  req.end();
});

let failed = false;
try {
  await waitReady(B, server.errRef);
  await waitReady(Bmissing, serverMissing.errRef);
  await waitReady(Boverride, serverOverride.errRef);
  await waitReady(Bbare, serverBare.errRef);
  await waitReady(Bbroken, serverBroken.errRef);

  // ── listing: newest-first promoted rows ────────────────────────────────────
  const all = await (await list(B)).json();
  assert.strictEqual(all.total, 8, "all activities listed");
  assert.deepStrictEqual(all.activities.map((a) => a.activityId),
    [9001, 20, 50, 40, 30, 15, 60, 10], "newest first");
  // add-interval-lens: the newest row (REP_RUN_ID) has a document, so its
  // list row carries intervalShape/intervalLabel on top of the promoted cols
  const withDoc = all.activities[0];
  assert.strictEqual(withDoc.activityId, REP_RUN_ID);
  assert.deepStrictEqual(Object.keys(withDoc).sort(),
    ["activityId", "avgCadence", "avgHr", "distanceM", "durationS", "elevationGainM",
     "intervalLabel", "intervalLensVersion", "intervalShape", "name", "startTimeLocal", "type"],
    "a run with a document rides intervalShape/intervalLabel/intervalLensVersion on top of the promoted columns");
  assert.strictEqual(withDoc.intervalShape, "reps");
  assert.strictEqual(withDoc.intervalLabel, "5×1 km");
  // sweep-lens-tail M4: the stored engine version rides on the list row —
  // exposed (parity with block/course), never filtered, so a stale document
  // stays served and detectable between a version bump and the next sync.
  assert.strictEqual(withDoc.intervalLensVersion, 1);
  // the very next row (PLAIN_RUN_ID = 20) has NO run_intervals row — the
  // fields are omitted, not just absent because the whole run is missing
  const first = all.activities[1];
  assert.strictEqual(first.activityId, PLAIN_RUN_ID);
  assert.deepStrictEqual(Object.keys(first).sort(),
    ["activityId", "avgCadence", "avgHr", "distanceM", "durationS", "elevationGainM", "name", "startTimeLocal", "type"],
    "promoted-column fields only — no interval fields for a run without a document");
  assert.strictEqual(first.distanceM, 21100.0);

  // filters
  const runs2025 = await (await list(B, "?type=running&year=2025")).json();
  assert.deepStrictEqual(runs2025.activities.map((a) => a.activityId), [50, 40, 15, 10], "type+year filter");
  const ranged = await (await list(B, "?from=2025-06-01&to=2025-09-30")).json();
  assert.deepStrictEqual(ranged.activities.map((a) => a.activityId), [40, 30], "date range filter, bounds inclusive");

  // name search (archive-browser): case-insensitive substring over name
  const base = await (await list(B, "?q=base")).json();
  assert.deepStrictEqual(base.activities.map((a) => a.activityId), [50, 40], "q matches a name substring");
  assert.strictEqual(base.total, 2, "total counts the filtered set");
  const upper = await (await list(B, "?q=BASE")).json();
  assert.deepStrictEqual(upper.activities.map((a) => a.activityId), [50, 40], "q is case-insensitive");
  // wildcard characters match only themselves (parameterized + escaped)
  assert.strictEqual((await (await list(B, "?q=%")).json()).total, 0, "literal % matches nothing here — not everything");
  assert.strictEqual((await (await list(B, "?q=e_po")).json()).total, 0, "literal _ is not a single-char wildcard");
  // q composes with the other filters under the same AND semantics
  const combined = await (await list(B, "?type=running&year=2025&q=base")).json();
  assert.deepStrictEqual(combined.activities.map((a) => a.activityId), [50, 40], "q AND type AND year");
  const qPage = await (await list(B, "?q=base&limit=1")).json();
  assert.strictEqual(qPage.total, 2, "filtered total drives the cursor");
  assert.strictEqual(qPage.nextOffset, 1, "q respects pagination");
  assert.deepStrictEqual(
    (await (await list(B, "?q=base&limit=1&offset=1")).json()).activities.map((a) => a.activityId),
    [40], "q + offset pages through the filtered set");

  // pagination: bounded pages, offset cursor
  const page1 = await (await list(B, "?type=running&limit=2")).json();
  assert.strictEqual(page1.activities.length, 2);
  assert.deepStrictEqual(page1.activities.map((a) => a.activityId), [9001, 20]);
  assert.strictEqual(page1.nextOffset, 2, "more rows → cursor to the next page");
  const page2 = await (await list(B, "?type=running&limit=2&offset=2")).json();
  assert.deepStrictEqual(page2.activities.map((a) => a.activityId), [50, 40]);
  assert.strictEqual(page2.nextOffset, 4, "still more rows → cursor advances");
  const page3 = await (await list(B, "?type=running&limit=2&offset=4")).json();
  assert.deepStrictEqual(page3.activities.map((a) => a.activityId), [15, 10]);
  assert.strictEqual(page3.nextOffset, null, "last page → no cursor");
  const clamped = await (await list(B, "?limit=5000")).json();
  assert.strictEqual(clamped.limit, 100, "page size clamped to the server maximum");

  // ── single activity: the distilled detail contract, verbatim ──────────────
  const run = await (await byId(B, 10)).json();
  assert.strictEqual(run.activityId, 10);
  assert.strictEqual(run.maxHr, 171);
  assert.deepStrictEqual(run.detail, DETAIL, "detail equals the stored distilled contract, unmodified");
  assert.deepStrictEqual(Object.keys(run.detail).sort(),
    ["driftBpm", "elevGain", "hrSeries", "load", "splitShape", "splits", "te", "tempC", "zoneMin"],
    "detail shape = the recent-run detail contract of garmin-data.js");

  // no distilled detail yet → summary with null detail, not an error
  const undistilled = await byId(B, 20);
  assert.strictEqual(undistilled.status, 200);
  assert.strictEqual((await undistilled.json()).detail, null, "undistilled run → null detail");
  const strength = await (await byId(B, 30)).json();
  assert.strictEqual(strength.detail, null, "non-run → null detail");

  // ── interval lens (add-interval-lens): the stored document, verbatim ──────
  const repRun = await (await byId(B, REP_RUN_ID)).json();
  assert.strictEqual(repRun.activityId, REP_RUN_ID);
  assert.deepStrictEqual(repRun.intervals, REP_DOC,
    "the interval document is served byte-for-byte, parsed once from doc_json");
  assert.strictEqual(repRun.intervals.shape, "reps");
  assert.strictEqual(repRun.intervals.label, "5×1 km");
  assert.ok(Array.isArray(repRun.intervals.segments), "segments survive the API");
  assert.strictEqual(repRun.intervals.set.found, 5, "nested fields ride through untouched");
  // sweep-lens-tail M4: the stored row's lens_version rides beside the
  // document (parity with block/course) — and only when a document exists.
  assert.strictEqual(repRun.lensVersion, 1,
    "the by-id read exposes the stored lens_version beside the document");

  // a run with no document: the field is OMITTED, not null — same rule as
  // map. PLAIN_RUN_ID genuinely exists (200, real promoted fields) — this
  // isn't a 404 masquerading as an absent field.
  const plainRun = await (await byId(B, PLAIN_RUN_ID)).json();
  assert.strictEqual(plainRun.activityId, PLAIN_RUN_ID, "the plain run genuinely exists");
  assert.ok(!("intervals" in plainRun), "a run with no run_intervals row omits the field");
  assert.ok(!("lensVersion" in plainRun), "no document → no lensVersion either");

  // unknown ids → 404
  assert.strictEqual((await byId(B, 999999)).status, 404, "unknown id → 404");
  assert.strictEqual((await byId(B, "not-a-number")).status, 404, "malformed id → 404");

  // raw payloads never leave the server
  for (const r of [await list(B), await byId(B, 10), await byId(B, 30), await byId(B, REP_RUN_ID)]) {
    assert.ok(!(await r.clone().text()).includes(RAW_MARKER), "raw summary/detail JSON must never be serialized");
  }

  // ── streams endpoint (run-detail group 4): stored columns, verbatim ───────
  const st = await streams(B, 10);
  assert.strictEqual(st.status, 200, "streams for a streamed run → 200");
  assert.strictEqual(st.headers.get("content-type"), "application/json; charset=utf-8");
  const stText = await st.text();
  assert.strictEqual(stText, STREAMS_TEXT,
    "the stored streams TEXT is served verbatim — never parsed and reserialised");
  const stJson = JSON.parse(stText);
  assert.strictEqual(stJson.t.length, 400, "full resolution — no downsampling");
  assert.strictEqual(stJson.hr[3], null, "nulls survive the wire");

  // gzip negotiation (run-detail 4.4): the raw wire carries Content-Encoding
  // gzip and gunzips to the stored bytes; without Accept-Encoding it's plain
  const gz = await rawGet(B, "/api/archive/activities/10/streams", { "accept-encoding": "gzip" });
  assert.strictEqual(gz.headers["content-encoding"], "gzip", "streams are gzipped on the wire");
  assert.ok(gz.body.length < Buffer.byteLength(STREAMS_TEXT) / 2, "gzip actually pays for itself");
  assert.strictEqual(gunzipSync(gz.body).toString("utf8"), STREAMS_TEXT, "gunzips to the stored bytes");
  const plainSt = await rawGet(B, "/api/archive/activities/10/streams");
  assert.ok(!plainSt.headers["content-encoding"], "no Accept-Encoding → plain body");

  // the fail-soft contract (run-detail 4.3)
  assert.strictEqual((await streams(B, 999999)).status, 404, "unknown id → 404");
  assert.strictEqual((await streams(B, 20)).status, 404, "run without stored streams → 404");
  assert.strictEqual((await fetch(B + "/api/archive/activities/abc/streams")).status, 404, "malformed id → 404");
  assert.strictEqual((await fetch(B + "/api/archive/activities/10/streamsX")).status, 404, "junk suffix → 404");
  assert.strictEqual((await fetch(B + "/api/archive/activities/10/streams", { method: "POST", body: "x" })).status, 405, "POST streams → 405");
  assert.ok(!stText.includes(RAW_MARKER), "raw payloads never leave via streams");

  // ── run-metrics endpoint (chart-drill 2.x): stored rows over a bounded range ──
  const march = await runMetrics(B, "?from=2025-03-01&to=2025-03-31");
  assert.strictEqual(march.status, 200, "a month range is served");
  const marchRows = (await march.json()).runs;
  assert.deepStrictEqual(marchRows.map((r) => r.activityId), [15, 60, 10],
    "every March RUNNING activity (treadmill included), newest-first; the strength session never appears");
  const tempo = marchRows.find((r) => r.activityId === 10);
  assert.deepStrictEqual(tempo, {
    activityId: 10, startTimeLocal: "2025-03-10 08:01:00", name: "Tempo Tuesday",
    distanceM: 10210.5, durationS: 3480.0, isTreadmill: false,
    refhrTimeS: 1543.2, refhrDistM: 3390.7, refhrPaceSPerKm: 455.2,
    refpaceTimeS: 1201.0, refpaceCadenceSpm: 170.0, metricsVersion: 2,
  }, "identity + metric fields byte-equal to the stored columns, nothing derived");
  const belt = marchRows.find((r) => r.activityId === 60);
  assert.strictEqual(belt.isTreadmill, true, "the treadmill flag is honest");
  assert.strictEqual(belt.refhrTimeS, 0, "zero in-band time survives as zero…");
  assert.strictEqual(belt.refhrPaceSPerKm, null, "…while its display value stays null");
  const unanalysed = marchRows.find((r) => r.activityId === 15);
  assert.strictEqual(unanalysed.refhrTimeS, null, "a run without a metrics row appears…");
  assert.strictEqual(unanalysed.metricsVersion, null, "…with null metric fields, not omitted");
  assert.strictEqual(unanalysed.name, "Unanalysed Sunday");

  // bounds: both params required, invalid dates and >92-day spans rejected
  for (const qs of ["", "?from=2025-03-01", "?to=2025-03-31",
                    "?from=not-a-date&to=2025-03-31", "?from=2025-04-01&to=2025-03-01"]) {
    assert.strictEqual((await runMetrics(B, qs)).status, 400, "bad params → 400: " + (qs || "(none)"));
  }
  assert.strictEqual((await runMetrics(B, "?from=2025-01-01&to=2025-04-03")).status, 200,
    "a 92-day span is the allowed maximum");
  const oversized = await runMetrics(B, "?from=2025-01-01&to=2025-04-04");
  assert.strictEqual(oversized.status, 400, "a 93-day span → 400");
  assert.ok(/92/.test((await oversized.json()).error), "the refusal names the constraint");

  // non-GET rejected; not-provisioned 404 without a database; raw payloads never leave
  assert.strictEqual((await fetch(B + "/api/archive/run-metrics?from=2025-03-01&to=2025-03-31",
    { method: "POST", body: "x" })).status, 405, "POST run-metrics → 405");
  assert.strictEqual((await runMetrics(Bmissing, "?from=2025-03-01&to=2025-03-31")).status, 404,
    "missing db → 404 (not provisioned) on run-metrics");
  assert.ok(!(await (await runMetrics(B, "?from=2025-03-01&to=2025-03-31")).text()).includes(RAW_MARKER),
    "raw payloads never leave via run-metrics");

  // a pre-metrics archive (no run_metrics table): identity rows with null
  // metric fields — "not yet analysed", not an outage
  const bare = await runMetrics(Bbare, "?from=2025-03-01&to=2025-03-31");
  assert.strictEqual(bare.status, 200, "an archive without run_metrics still serves");
  const bareRows = (await bare.json()).runs;
  assert.deepStrictEqual(bareRows.map((r) => [r.activityId, r.refhrTimeS, r.metricsVersion]),
    [[70, null, null]], "pre-metrics archive rows carry null metric fields");

  // ── route-basemap: the map field + the same-origin tile endpoint ──────────
  const mapped = await (await byId(B, 10)).json();
  assert.deepStrictEqual(mapped.map,
    { z: 15, x0: 17000, y0: 11300, x1: 17001, y1: 11300,
      cropX: 4352123.5, cropY: 2893456.25, cropSize: 412.75 },
    "a mapped run carries zoom, tile rect and crop box");
  const unmapped = await (await byId(B, 20)).json();
  assert.ok(!("map" in unmapped), "an activity without a map row omits the field");

  const tile = await rawGet(B, "/api/archive/tiles/15/17000/11300.png", { "accept-encoding": "gzip" });
  assert.strictEqual(tile.status, 200, "a stored tile is served");
  assert.strictEqual(tile.headers["content-type"], "image/png");
  assert.ok(/max-age=\d{6,}/.test(tile.headers["cache-control"] || ""),
    "tiles carry a long-lived cache header — the blobs never change");
  assert.ok(!tile.headers["content-encoding"], "PNG is never gzipped (already compressed)");
  assert.ok(tile.body.equals(TILE_PNG), "the stored blob, byte for byte");

  assert.strictEqual((await fetch(B + "/api/archive/tiles/15/1/1.png")).status, 404, "missing tile → quiet 404");
  assert.strictEqual((await fetch(B + "/api/archive/tiles/xx/1/1.png")).status, 404, "malformed coords → 404");
  assert.strictEqual((await fetch(B + "/api/archive/tiles/15/17000/11300.png",
    { method: "POST", body: "x" })).status, 405, "POST tile → 405");
  assert.strictEqual((await fetch(Bmissing + "/api/archive/tiles/15/17000/11300.png")).status, 404,
    "missing db → 404 on tiles (not provisioned, like every archive endpoint)");

  // a pre-v8 archive (no map_tiles/activity_maps tables): by-id serves
  // without a map field and tiles are absent — "no maps yet", never an outage
  const bareRun = await (await byId(Bbare, 70)).json();
  assert.strictEqual(bareRun.activityId, 70, "an archive without map tables still serves by-id");
  assert.ok(!("map" in bareRun), "pre-v8 archive: no map field");
  assert.strictEqual((await fetch(Bbare + "/api/archive/tiles/15/17000/11300.png")).status, 404,
    "pre-v8 archive: tile → 404, not a 503");

  // a pre-v11 archive (no run_intervals table at all): both the listing and
  // by-id keep serving 200s — no structure detected yet, never an outage
  assert.ok(!("intervals" in bareRun), "pre-v11 archive: by-id omits intervals too");
  const bareList = await (await list(Bbare)).json();
  assert.strictEqual(bareList.total, 1, "an archive without run_intervals still lists");
  assert.ok(!("intervalShape" in bareList.activities[0]), "pre-v11 archive: no intervalShape field");
  assert.ok(!("intervalLabel" in bareList.activities[0]), "pre-v11 archive: no intervalLabel field");

  // ── block-lens endpoints (add-block-lens 2.x) ─────────────────────────────
  // listing: newest race first, promoted columns + the EMBEDDED summary slice
  const blocks = (await (await fetch(B + "/api/archive/blocks")).json()).blocks;
  assert.deepStrictEqual(blocks.map((b) => b.raceDate),
    ["2026-08-09", "2025-04-12", "2024-10-01"], "blocks are listed newest race first");
  assert.deepStrictEqual(Object.keys(blocks[0]).sort(),
    ["isComplete", "lensVersion", "raceDate", "raceName", "summary", "updatedAt"],
    "listing rows carry promoted columns + summary, nothing else");
  assert.strictEqual(blocks[0].isComplete, false);
  assert.strictEqual(blocks[1].isComplete, true);
  assert.deepStrictEqual(blocks[0].summary, BLOCK_SUMMARY_CURRENT,
    "the summary is the engine's embedded slice, lifted verbatim");
  assert.deepStrictEqual(blocks[1].summary, BLOCK_SUMMARY_SPRING);
  assert.ok(!blocks.some((b) => "weeks" in (b.summary || {})),
    "the listing never carries week-level detail");

  // single block: the stored TEXT byte-for-byte (never parse-and-reserialise)
  const blockDoc = await fetch(B + "/api/archive/blocks/2026-08-09");
  assert.strictEqual(blockDoc.status, 200);
  assert.strictEqual(await blockDoc.text(), BLOCK_DOC_CURRENT,
    "the stored lens document is served verbatim");
  assert.strictEqual(await (await fetch(B + "/api/archive/blocks/2025-04-12")).text(),
    BLOCK_DOC_SPRING);

  // fail-soft contract: unknown key / malformed key → 404; POST → 405
  assert.strictEqual((await fetch(B + "/api/archive/blocks/2030-01-01")).status, 404,
    "unknown race date → 404");
  assert.strictEqual((await fetch(B + "/api/archive/blocks/not-a-date")).status, 404,
    "malformed race date → 404");
  assert.strictEqual((await fetch(B + "/api/archive/blocks", { method: "POST", body: "x" })).status,
    405, "POST blocks → 405");
  assert.strictEqual((await fetch(B + "/api/archive/blocks/2026-08-09", { method: "PUT", body: "x" })).status,
    405, "PUT block → 405");

  // ── course endpoint (add-course-lens) ───────────────────────────────────
  const course = await fetch(B + "/api/archive/course/493447940");
  assert.strictEqual(course.status, 200);
  const cdoc = await course.json();
  assert.strictEqual(cdoc.courseId, 493447940);
  assert.strictEqual(cdoc.courseName, "Allgau Panorama Halbmarathon");
  assert.strictEqual(cdoc.distanceM, 21114.2);
  assert.strictEqual(cdoc.lensVersion, 1);
  assert.ok(cdoc.bbox && cdoc.bbox.lowerLeft, "bbox is parsed, not a JSON string");
  // the derived document is passed through intact — the API derives nothing
  assert.strictEqual(cdoc.model.damping, 0.3323, "the stored model rides through verbatim");
  assert.strictEqual(cdoc.segments[0].kind, "climb");
  assert.strictEqual(cdoc.perKm[0].factor, 1.02);
  assert.deepStrictEqual(cdoc.map,
    { z: 13, x0: 4300, y0: 2860, x1: 4302, y1: 2862, cropX: 12.5, cropY: 8.25, cropSize: 700 },
    "the stored basemap rect is attached");
  // the raw points_json is NOT shipped — the document carries a downsampled track
  assert.ok(!("points_json" in cdoc) && !("pointsJson" in cdoc),
    "the full point track stays in the database");

  assert.strictEqual((await fetch(B + "/api/archive/course/999")).status, 404,
    "unknown course id → 404");
  assert.strictEqual((await fetch(B + "/api/archive/course/not-a-number")).status, 404,
    "malformed course id → 404");
  assert.strictEqual((await fetch(B + "/api/archive/course/493447940",
    { method: "POST", body: "x" })).status, 405, "POST course → 405");
  assert.strictEqual((await fetch(Bbare + "/api/archive/course/493447940")).status, 404,
    "pre-v10 archive: no courses table → 404, not a 503");
  assert.strictEqual((await fetch(Bmissing + "/api/archive/course/493447940")).status, 404,
    "missing archive → 404");
  assert.strictEqual((await fetch(Bbroken + "/api/archive/course/493447940")).status, 503,
    "corrupt archive → 503 fail-soft, and the server keeps serving");

  // a pre-v9 archive (no block_lens table): empty list with 200 on the
  // listing, 404 by date — "no lens yet", never an outage
  const bareBlocks = await fetch(Bbare + "/api/archive/blocks");
  assert.strictEqual(bareBlocks.status, 200, "pre-v9 archive: listing still 200");
  assert.deepStrictEqual((await bareBlocks.json()).blocks, [], "…with an empty list");
  assert.strictEqual((await fetch(Bbare + "/api/archive/blocks/2026-08-09")).status, 404,
    "pre-v9 archive: by-date → 404, not a 503");

  // archive away: missing db → 404 (not provisioned), corrupt db → 503 on
  // both endpoints — and the server keeps serving everything else
  assert.strictEqual((await fetch(Bmissing + "/api/archive/blocks")).status, 404,
    "missing db → 404 on the block listing");
  assert.strictEqual((await fetch(Bmissing + "/api/archive/blocks/2026-08-09")).status, 404,
    "missing db → 404 on the block document");
  assert.strictEqual((await fetch(Bbroken + "/api/archive/blocks")).status, 503,
    "unusable db → 503 fail-soft on the block listing");
  assert.strictEqual((await fetch(Bbroken + "/api/archive/blocks/2026-08-09")).status, 503,
    "unusable db → 503 fail-soft on the block document");
  assert.ok((await fetch(Bbroken + "/api/status")).ok,
    "the server process survives archive failure");

  // write methods rejected, no state change
  assert.strictEqual((await fetch(B + "/api/archive/activities", { method: "POST", body: "x" })).status, 405, "POST → 405");
  assert.strictEqual((await fetch(B + "/api/archive/activities/10", { method: "PUT", body: "x" })).status, 405, "PUT → 405");
  assert.strictEqual((await fetch(B + "/api/archive/activities/10", { method: "DELETE" })).status, 405, "DELETE → 405");

  // ── fail-soft: no database file = "not provisioned" (404, distinct error
  // body), everything else keeps serving. 503 is reserved for an existing-
  // but-unusable db (outage) — instance-aware chrome / add-ingest-archive. ───
  const missingList = await list(Bmissing);
  assert.strictEqual(missingList.status, 404, "missing db → 404 on the list");
  assert.strictEqual((await missingList.json()).error, "no archive on this instance",
    "the body names the shape, not an outage");
  assert.strictEqual((await byId(Bmissing, 10)).status, 404, "missing db → 404 on by-id");
  assert.strictEqual((await streams(Bmissing, 10)).status, 404, "missing db → 404 on streams");
  assert.ok((await fetch(Bmissing + "/api/status")).ok, "other APIs unaffected");
  assert.ok((await fetch(Bmissing + "/Running%20Dashboard.dc.html")).ok, "dashboard page still serves");

  // ── SPLITS_ARCHIVE_DIR: archive from a local dir, data files elsewhere ────
  const overridden = await (await list(Boverride, "?type=running")).json();
  assert.strictEqual(overridden.total, 6, "archive read from SPLITS_ARCHIVE_DIR");

  // ── read-only: the database file is byte-identical after everything ───────
  assert.ok(dbBytesBefore.equals(await readFile(dbPath)), "no request may write to the archive");

  console.log("ALL PASS");
} catch (e) {
  failed = true;
  console.error("FAIL:", e.message);
} finally {
  server.kill();
  serverMissing.kill();
  serverOverride.kill();
  serverBare.kill();
  serverBroken.kill();
  await rm(dataDir, { recursive: true, force: true }).catch(() => {});
  await rm(emptyDir, { recursive: true, force: true }).catch(() => {});
  await rm(bareDir, { recursive: true, force: true }).catch(() => {});
  await rm(brokenDir, { recursive: true, force: true }).catch(() => {});
}
process.exit(failed ? 1 : 0);
