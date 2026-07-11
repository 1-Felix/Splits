// Integration tests for the read-only archive API (progress-views group 4).
// Patterned on test_plan_push.mjs: real server processes over temp data dirs.
// Needs a Node with node:sqlite (stable in 24; experimental-but-present in 22.19).
import assert from "node:assert";
import http from "node:http";
import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
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
  db.close();
}

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

const dataDir = await mkdtemp(join(tmpdir(), "splits-archive-test-"));
const emptyDir = await mkdtemp(join(tmpdir(), "splits-archive-empty-"));
makeArchive(dataDir);
const dbPath = join(dataDir, "activity-archive.db");
const dbBytesBefore = await readFile(dbPath);

const PORT = 8140;
const B = "http://localhost:" + PORT;          // archive in DATA_DIR (default flow)
const Bmissing = "http://localhost:" + (PORT + 1); // no archive anywhere → 503
const Boverride = "http://localhost:" + (PORT + 2); // SPLITS_ARCHIVE_DIR override

const server = startServer(PORT, { SPLITS_DATA_DIR: dataDir });
const serverMissing = startServer(PORT + 1, { SPLITS_DATA_DIR: emptyDir });
const serverOverride = startServer(PORT + 2, { SPLITS_DATA_DIR: emptyDir, SPLITS_ARCHIVE_DIR: dataDir });

const list = (base, qs = "") => fetch(base + "/api/archive/activities" + qs);
const byId = (base, id) => fetch(base + "/api/archive/activities/" + id);
const streams = (base, id) => fetch(base + "/api/archive/activities/" + id + "/streams");

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

  // ── listing: newest-first promoted rows ────────────────────────────────────
  const all = await (await list(B)).json();
  assert.strictEqual(all.total, 5, "all activities listed");
  assert.deepStrictEqual(all.activities.map((a) => a.activityId), [20, 50, 40, 30, 10], "newest first");
  const first = all.activities[0];
  assert.deepStrictEqual(Object.keys(first).sort(),
    ["activityId", "avgCadence", "avgHr", "distanceM", "durationS", "elevationGainM", "name", "startTimeLocal", "type"],
    "promoted-column fields only");
  assert.strictEqual(first.distanceM, 21100.0);

  // filters
  const runs2025 = await (await list(B, "?type=running&year=2025")).json();
  assert.deepStrictEqual(runs2025.activities.map((a) => a.activityId), [50, 40, 10], "type+year filter");
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
  assert.strictEqual(page1.nextOffset, 2, "more rows → cursor to the next page");
  const page2 = await (await list(B, "?type=running&limit=2&offset=2")).json();
  assert.deepStrictEqual(page2.activities.map((a) => a.activityId), [40, 10]);
  assert.strictEqual(page2.nextOffset, null, "last page → no cursor");
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

  // unknown ids → 404
  assert.strictEqual((await byId(B, 999999)).status, 404, "unknown id → 404");
  assert.strictEqual((await byId(B, "not-a-number")).status, 404, "malformed id → 404");

  // raw payloads never leave the server
  for (const r of [await list(B), await byId(B, 10), await byId(B, 30)]) {
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

  // write methods rejected, no state change
  assert.strictEqual((await fetch(B + "/api/archive/activities", { method: "POST", body: "x" })).status, 405, "POST → 405");
  assert.strictEqual((await fetch(B + "/api/archive/activities/10", { method: "PUT", body: "x" })).status, 405, "PUT → 405");
  assert.strictEqual((await fetch(B + "/api/archive/activities/10", { method: "DELETE" })).status, 405, "DELETE → 405");

  // ── fail-soft: no database → 503, everything else keeps serving ───────────
  assert.strictEqual((await list(Bmissing)).status, 503, "missing db → 503 on the list");
  assert.strictEqual((await byId(Bmissing, 10)).status, 503, "missing db → 503 on by-id");
  assert.strictEqual((await streams(Bmissing, 10)).status, 503, "missing db → 503 on streams");
  assert.ok((await fetch(Bmissing + "/api/status")).ok, "other APIs unaffected");
  assert.ok((await fetch(Bmissing + "/Running%20Dashboard.dc.html")).ok, "dashboard page still serves");

  // ── SPLITS_ARCHIVE_DIR: archive from a local dir, data files elsewhere ────
  const overridden = await (await list(Boverride, "?type=running")).json();
  assert.strictEqual(overridden.total, 4, "archive read from SPLITS_ARCHIVE_DIR");

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
  await rm(dataDir, { recursive: true, force: true }).catch(() => {});
  await rm(emptyDir, { recursive: true, force: true }).catch(() => {});
}
process.exit(failed ? 1 : 0);
