// test_run_page.mjs — the /run/:id page end to end (run-detail 8.1).
//
// Boots serve.mjs over a fixture archive (streams + compliance + run_metrics)
// and drives a real browser: the crosshair moves EVERY track together, the
// trace pin follows it, the distance ⇄ time toggle re-renders the shared axis,
// and the page degrades honestly when the archive 503s or the id is unknown.
import assert from "node:assert";
import { spawn } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";
import { chromium } from "playwright";

const ROOT = dirname(fileURLToPath(import.meta.url));
const PORT = 8161;
const B = "http://localhost:" + PORT;
const Bmissing = "http://localhost:" + (PORT + 1);

// a plausible 600-sample run: 6 km at ~3 m/s with rolling hills and GPS
const N = 600;
const STREAMS = {
  t: Array.from({ length: N }, (_, i) => i * 2),
  d: Array.from({ length: N }, (_, i) => Math.round(i * 10.05)),
  hr: Array.from({ length: N }, (_, i) => 138 + Math.round(14 * Math.sin(i / 40))),
  v: Array.from({ length: N }, (_, i) => +(2.9 + 0.4 * Math.sin(i / 25)).toFixed(2)),
  gap: Array.from({ length: N }, (_, i) => +(3.0 + 0.3 * Math.sin(i / 25)).toFixed(2)),
  cad: Array.from({ length: N }, (_, i) => 162 + (i % 5)),
  elev: Array.from({ length: N }, (_, i) => +(420 + 25 * Math.sin(i / 80)).toFixed(1)),
  lat: Array.from({ length: N }, (_, i) => +(47.37 + 0.004 * Math.sin(i / 90)).toFixed(5)),
  lon: Array.from({ length: N }, (_, i) => +(8.53 + 0.006 * (i / N)).toFixed(5)),
};
const DETAIL = {
  splits: Array.from({ length: 6 }, (_, i) => ({ km: i + 1, pace: 330 + (i % 3) * 12, hr: 140 + i })),
  hrSeries: [135, 140, 145, 148], driftBpm: 6, zoneMin: [4, 18, 8, 2, 0],
  tempC: 19, te: 3.2, load: 140, elevGain: 60, splitShape: "even",
};

// add-interval-lens: run 7 ("Fixture Tempo", above) is PLAIN_RUN_ID — it gets
// no run_intervals row at all, so its splits card must still render while no
// rep table appears. REP_RUN_ID is a brand-new fixture activity carrying a
// full document with all five work segments AND the four recoveries between
// them populated (Task 12's fixture only ever populated the warmup segment,
// since that task just tested passthrough — this page renders reps and
// recoveries, so both must be real here). REP_RUN_ID also carries a real
// DETAIL (splits) so the "km splits card still renders below the rep table"
// claim is genuinely exercised, not merely matched against the "SPLITS"
// header wordmark that appears on every page regardless.
//
// gapS is populated (not null) on every work segment: GAP is the engine's own
// grade-adjusted signal, not decoration — a rep up a drag and a rep down it
// can carry the same raw pace deviation for very different real effort, and
// GAP is what tells them apart. Each work rep's gapS runs 4 s/km faster than
// its raw paceS, simulating a net-downhill grade adjustment.
const PLAIN_RUN_ID = 7;
const REP_RUN_ID = 9001;
const REP_SEGMENTS = [];
let t = 600, d = 1560, rep = 0;
REP_SEGMENTS.push({ idx: 1, role: "warmup", t0: 0, t1: 600, d0: 0, d1: 1560,
                    durS: 600, distM: 1560, paceS: 385, gapS: null, hr: 132, cad: null });
for (let i = 0; i < 5; i++) {
  rep += 1;
  REP_SEGMENTS.push({ idx: REP_SEGMENTS.length + 1, role: "work", rep,
    t0: t, t1: t + 250, d0: d, d1: d + 1000, durS: 250, distM: 1000,
    paceS: 330 + i * 3, gapS: 330 + i * 3 - 4, hr: 168 + i, cad: null });
  t += 250; d += 1000;
  if (i < 4) {
    REP_SEGMENTS.push({ idx: REP_SEGMENTS.length + 1, role: "recovery",
      t0: t, t1: t + 60, d0: d, d1: d + 140, durS: 60, distM: 140,
      paceS: 430, gapS: null, hr: 144, cad: null });
    t += 60; d += 140;
  }
}
const REP_DOC = {
  version: 1, shape: "reps", source: "stream", confidence: 0.86,
  label: "5×1 km", guidedBy: null,
  segments: REP_SEGMENTS,
  set: { found: 5, prescribed: null, nominalDistM: 1000, varied: false,
         paceS: 336, paceCvPct: 1.8, fadePct: 2.4, recoveryS: 60,
         recoveryHrDrop: 24, reps: [] },
  quality: { workDistM: 5000, workDurS: 1250, zone: "Z4" },
};

// LOWCONF_RUN_ID: a genuine "reps" detection, but weak (confidence 0.35 < the
// 0.5 hedge threshold) — the honesty contract this card exists for: a session
// the athlete may have bailed on says "possible structure", not a flat claim.
// This is a fixture no task in this plan has ever exercised (grepped: the
// "possible structure" string appears nowhere in any test across the plan).
const LOWCONF_RUN_ID = 9002;
const LOWCONF_SEGMENTS = [];
let lt = 300, ld = 700, lrep = 0;
LOWCONF_SEGMENTS.push({ idx: 1, role: "warmup", t0: 0, t1: 300, d0: 0, d1: 700,
                        durS: 300, distM: 700, paceS: 428, gapS: null, hr: 128, cad: null });
for (let i = 0; i < 3; i++) {
  lrep += 1;
  LOWCONF_SEGMENTS.push({ idx: LOWCONF_SEGMENTS.length + 1, role: "work", rep: lrep,
    t0: lt, t1: lt + 200, d0: ld, d1: ld + 800, durS: 200, distM: 800,
    paceS: 250 + i * 10, gapS: 246 + i * 10, hr: 160 + i * 2, cad: null });
  lt += 200; ld += 800;
  if (i < 2) {
    LOWCONF_SEGMENTS.push({ idx: LOWCONF_SEGMENTS.length + 1, role: "recovery",
      t0: lt, t1: lt + 90, d0: ld, d1: ld + 200, durS: 90, distM: 200,
      paceS: 450, gapS: null, hr: 140, cad: null });
    lt += 90; ld += 200;
  }
}
const LOWCONF_DOC = {
  version: 1, shape: "reps", source: "stream", confidence: 0.35,
  label: "3×800 m", guidedBy: null,
  segments: LOWCONF_SEGMENTS,
  set: { found: 3, prescribed: null, nominalDistM: 800, varied: false,
         paceS: 260, paceCvPct: 6.2, fadePct: 8.0, recoveryS: 90,
         recoveryHrDrop: 18, reps: [] },
  quality: { workDistM: 2400, workDurS: 630, zone: "Z3" },
};

// STEADY_RUN_ID: every streamed run gets a run_intervals ROW (derive_intervals
// writes a document for every run, never skips one) — the realistic "no
// reps" case is a document present with shape:"steady", not an absent row.
// In production, a real steady classification always ships `segments: []`
// (interval_lens.py: `if shape == "steady": segments = []`), which means the
// segments-truthiness check alone already suppresses the table for every
// steady run seen in practice today — the `iv.shape !== 'steady'` clause in
// run.dc.html's guard is never actually exercised by that emptiness alone.
// This fixture deliberately gives a shape:"steady" document ONE populated
// `work` segment specifically so the test exercises the explicit shape
// check itself, not the segments-emptiness fallback — see the guard-removal
// proof in the fix-round report.
const STEADY_RUN_ID = 9003;
const STEADY_SEGMENTS = [
  { idx: 1, role: "work", t0: 0, t1: 1800, d0: 0, d1: 5000,
    durS: 1800, distM: 5000, paceS: 360, gapS: 355, hr: 150, cad: null },
];
const STEADY_DOC = {
  version: 1, shape: "steady", source: "stream", confidence: 0.95,
  label: null, guidedBy: null,
  segments: STEADY_SEGMENTS,
  set: null,
  quality: { workDistM: 5000, workDurS: 1800, zone: "Z2" },
};

function makeArchive(dir) {
  const db = new DatabaseSync(join(dir, "activity-archive.db"));
  db.exec(`CREATE TABLE activities (
    activity_id INTEGER PRIMARY KEY, start_time_local TEXT NOT NULL, type_key TEXT,
    name TEXT, distance_m REAL, duration_s REAL, avg_hr INTEGER, max_hr INTEGER,
    avg_cadence REAL, elevation_gain_m REAL, summary_json TEXT NOT NULL,
    detail_json TEXT, detail_fetched_at TEXT, first_seen_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, detail_distilled_json TEXT, detail_streams_json TEXT)`);
  db.exec(`CREATE TABLE plan_compliance (
    id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, wk TEXT,
    snapshot_id INTEGER NOT NULL, compliance_version INTEGER NOT NULL,
    planned_kind TEXT, planned_km REAL, planned_load TEXT, planned_title TEXT,
    status TEXT NOT NULL, reason TEXT, actual_km REAL, actual_pace_s REAL,
    actual_hr INTEGER, activity_id INTEGER, updated_at TEXT NOT NULL)`);
  db.exec(`CREATE TABLE run_metrics (
    activity_id INTEGER PRIMARY KEY, metrics_version INTEGER,
    best_1k_s REAL, best_mile_s REAL, best_5k_s REAL, best_10k_s REAL, best_half_s REAL)`);
  db.prepare(`INSERT INTO activities (activity_id, start_time_local, type_key, name,
      distance_m, duration_s, avg_hr, max_hr, avg_cadence, elevation_gain_m,
      summary_json, detail_json, first_seen_at, updated_at, detail_distilled_json,
      detail_streams_json)
    VALUES (7, '2026-07-08 07:30:00', 'running', 'Fixture Tempo', 6030, 1198, 143, 168,
      164, 60, '{}', '{}', 'x', 'x', ?, ?)`)
    .run(JSON.stringify(DETAIL), JSON.stringify(STREAMS));
  db.prepare(`INSERT INTO plan_compliance (date, wk, snapshot_id, compliance_version,
      planned_kind, planned_km, planned_load, planned_title, status, reason,
      actual_km, actual_pace_s, actual_hr, activity_id, updated_at)
    VALUES ('2026-07-08', 'Wk 3', 1, 1, 'run', 6.0, 'Hard', 'Tempo Run', 'partial',
      'intensity', 6.0, 199, 143, 7, 'x')`).run();
  db.prepare(`INSERT INTO run_metrics (activity_id, metrics_version, best_1k_s,
      best_mile_s, best_5k_s, best_10k_s, best_half_s)
    VALUES (7, 1, 315.2, 512.0, 1660.4, NULL, NULL)`).run();
  // ── route-basemap: run 8 = run 7's streams PLUS a stored map (schema v8).
  // The rect/crop values are compute_tile_rect's real output for these
  // streams (z16, 3×3 tiles) — the fixture is what the sync would write.
  // Run 7 stays mapless on purpose: it pins the unchanged bare-shape path.
  db.exec(`CREATE TABLE map_tiles (
    z INTEGER NOT NULL, x INTEGER NOT NULL, y INTEGER NOT NULL,
    png BLOB NOT NULL, fetched_at TEXT NOT NULL, PRIMARY KEY (z, x, y))`);
  db.exec(`CREATE TABLE activity_maps (
    activity_id INTEGER PRIMARY KEY, z INTEGER NOT NULL,
    x0 INTEGER NOT NULL, y0 INTEGER NOT NULL, x1 INTEGER NOT NULL, y1 INTEGER NOT NULL,
    crop_x REAL NOT NULL, crop_y REAL NOT NULL, crop_size REAL NOT NULL,
    updated_at TEXT NOT NULL)`);
  db.prepare(`INSERT INTO activities (activity_id, start_time_local, type_key, name,
      distance_m, duration_s, avg_hr, max_hr, avg_cadence, elevation_gain_m,
      summary_json, detail_json, first_seen_at, updated_at, detail_distilled_json,
      detail_streams_json)
    VALUES (8, '2026-07-09 07:30:00', 'running', 'Mapped Morning', 6030, 1198, 143, 168,
      164, 60, '{}', '{}', 'x', 'x', ?, ?)`)
    .run(JSON.stringify(DETAIL), JSON.stringify(STREAMS));
  db.prepare(`INSERT INTO activity_maps (activity_id, z, x0, y0, x1, y1,
      crop_x, crop_y, crop_size, updated_at)
    VALUES (8, 16, 34320, 22950, 34322, 22952, 8785955.1, 5875295.98, 638.57, 'x')`).run();
  // a real 1×1 PNG so every <image> load succeeds under networkidle
  const PNG1 = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
    "base64");
  const tins = db.prepare("INSERT INTO map_tiles (z, x, y, png, fetched_at) VALUES (?, ?, ?, ?, 'x')");
  for (let x = 34320; x <= 34322; x++) for (let y = 22950; y <= 22952; y++) tins.run(16, x, y, PNG1);
  // ── add-interval-lens: REP_RUN_ID carries a full run_intervals document —
  // five work segments, four recoveries between them — AND a real DETAIL
  // (splits), so "the km splits card still renders below the rep table" is
  // an honest claim about THIS run's page, not proven only on a different
  // run. Run 7 (PLAIN_RUN_ID, already inserted above) gets no run_intervals
  // row here — that absence is the point.
  db.prepare(`INSERT INTO activities (activity_id, start_time_local, type_key, name,
      distance_m, duration_s, avg_hr, max_hr, avg_cadence, elevation_gain_m,
      summary_json, detail_json, first_seen_at, updated_at, detail_distilled_json,
      detail_streams_json)
    VALUES (?, '2026-07-10 06:51:15', 'running', 'Track 5×1 km',
      6560, 1850, 158, 178, 172.0, 10.0, '{}', '{}', 'x', 'x', ?, NULL)`)
    .run(REP_RUN_ID, JSON.stringify(DETAIL));
  db.exec(`CREATE TABLE run_intervals (
    activity_id INTEGER PRIMARY KEY, lens_version INTEGER NOT NULL,
    start_time_local TEXT NOT NULL, shape TEXT NOT NULL, label TEXT,
    confidence REAL, source TEXT NOT NULL, work_dist_m REAL, work_dur_s REAL,
    doc_json TEXT NOT NULL, computed_at TEXT NOT NULL)`);
  db.prepare(`INSERT INTO run_intervals VALUES (?,?,?,?,?,?,?,?,?,?,?)`).run(
    REP_RUN_ID, 1, "2026-07-10 06:51:15", "reps", "5×1 km", 0.86, "stream",
    5000, 1250, JSON.stringify(REP_DOC), "2026-07-27T09:00:00");

  // ── fix-round finding 2: LOWCONF_RUN_ID — a genuine "reps" detection below
  // the 0.5 hedge threshold. Renders as a rep table, but must hedge honestly.
  db.prepare(`INSERT INTO activities (activity_id, start_time_local, type_key, name,
      distance_m, duration_s, avg_hr, max_hr, avg_cadence, elevation_gain_m,
      summary_json, detail_json, first_seen_at, updated_at, detail_distilled_json,
      detail_streams_json)
    VALUES (?, '2026-07-11 06:51:15', 'running', 'Maybe Fartlek',
      3000.0, 890, 150, 172, 168.0, 5.0, '{}', '{}', 'x', 'x', NULL, NULL)`)
    .run(LOWCONF_RUN_ID);
  db.prepare(`INSERT INTO run_intervals VALUES (?,?,?,?,?,?,?,?,?,?,?)`).run(
    LOWCONF_RUN_ID, 1, "2026-07-11 06:51:15", "reps", "3×800 m", 0.35, "stream",
    2400, 630, JSON.stringify(LOWCONF_DOC), "2026-07-27T09:00:00");

  // ── fix-round finding 3: STEADY_RUN_ID — every streamed run gets a
  // run_intervals ROW; the realistic "no reps" case is shape:"steady" with a
  // document present, not an absent row. Real DETAIL too, so the km splits
  // card is proven to render (with real content) while no rep table does.
  db.prepare(`INSERT INTO activities (activity_id, start_time_local, type_key, name,
      distance_m, duration_s, avg_hr, max_hr, avg_cadence, elevation_gain_m,
      summary_json, detail_json, first_seen_at, updated_at, detail_distilled_json,
      detail_streams_json)
    VALUES (?, '2026-07-12 06:51:15', 'running', 'Ordinary Easy Run',
      5000.0, 1800, 145, 160, 165.0, 15.0, '{}', '{}', 'x', 'x', ?, NULL)`)
    .run(STEADY_RUN_ID, JSON.stringify(DETAIL));
  db.prepare(`INSERT INTO run_intervals VALUES (?,?,?,?,?,?,?,?,?,?,?)`).run(
    STEADY_RUN_ID, 1, "2026-07-12 06:51:15", "steady", null, 0.95, "stream",
    5000, 1800, JSON.stringify(STEADY_DOC), "2026-07-27T09:00:00");
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
    try { const r = await fetch(base + "/api/status"); if (r.ok) return; } catch {}
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error("server not ready\n" + (errRef ? errRef() : ""));
}

const dataDir = await mkdtemp(join(tmpdir(), "splits-runpage-"));
const emptyDir = await mkdtemp(join(tmpdir(), "splits-runpage-empty-"));
makeArchive(dataDir);
// a present-but-unopenable db = a real OUTAGE (503 → "Archive offline"); a
// missing file would be "not provisioned" (404) and show different copy
await writeFile(join(emptyDir, "activity-archive.db"), "not a sqlite file");
const server = startServer(PORT, { SPLITS_DATA_DIR: dataDir });
const serverMissing = startServer(PORT + 1, { SPLITS_DATA_DIR: emptyDir });

let browser;
let failed = false;
try {
  await waitReady(B, server.errRef);
  await waitReady(Bmissing, serverMissing.errRef);
  browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1200, height: 1400 } });
  const pageErrors = [];
  page.on("pageerror", (e) => pageErrors.push(String(e)));

  // ── the full page over the fixture archive ─────────────────────────────────
  await page.goto(B + "/run/7", { waitUntil: "networkidle" });
  await page.waitForSelector("svg[data-chart='trend']", { timeout: 15000 });
  const before = await page.evaluate(() => {
    const t = document.body.innerText;
    return {
      tracks: document.querySelectorAll("svg[data-chart='trend']").length,
      trace: document.querySelectorAll("svg[data-chart='trace']").length,
      traceCircles: document.querySelectorAll("svg[data-chart='trace'] circle").length,
      verdict: t.includes("Fixture Tempo"),
      plan: t.includes("Planned vs actual") && t.includes("Tempo Run") && t.includes("partial"),
      reason: t.includes("ran too hard for the intent"),
      bests: t.includes("Best efforts inside this run") && t.includes("5:15"),
      splits: t.includes("Splits") && t.includes("km 6"),
      xTick: t.includes("km"),
      power: t.includes("POWER"),
      traceImages: document.querySelectorAll("svg[data-chart='trace'] image").length,
      chipLabels: [...document.querySelectorAll("button.scope-chip")].map((b) => b.textContent),
    };
  });
  assert.ok(before.tracks >= 4, `pace/hr/cad/elev tracks render (got ${before.tracks})`);
  assert.strictEqual(before.power, false, "a power-less run renders NO power track — absence is silent");
  assert.strictEqual(before.trace, 1, "the GPS trace renders");
  assert.strictEqual(before.traceImages, 0, "a mapless run renders the bare shape — no tiles");
  assert.deepStrictEqual(before.chipLabels, ["distance", "time"],
    "a mapless run offers NO map/shape toggle");
  assert.ok(before.verdict && before.plan && before.bests && before.splits, JSON.stringify(before));
  assert.ok(before.reason, "a partial session names its reason");

  // ── one crosshair through every track; the trace pin follows ──────────────
  const svgs = await page.$$("svg[data-chart='trend']");
  const box = await svgs[1].boundingBox();
  await page.mouse.move(box.x + box.width * 0.3, box.y + box.height / 2);
  await page.mouse.move(box.x + box.width * 0.7, box.y + box.height / 2, { steps: 3 });
  await page.waitForFunction(() =>
    [...document.querySelectorAll("svg[data-chart='trend'] line")]
      .filter((l) => l.getAttribute("stroke-dasharray") === "3 3").length >= 4,
    null, { timeout: 5000 });
  const crossState = await page.evaluate(() => {
    const lines = [...document.querySelectorAll("svg[data-chart='trend'] line")]
      .filter((l) => l.getAttribute("stroke-dasharray") === "3 3");
    return {
      perTrack: lines.length,
      xs: lines.map((l) => l.getAttribute("x1")),
      readout: [...document.querySelectorAll("span")].filter((s) => ["at", "hr", "cad", "elev"].includes(s.textContent)).length,
      pinned: document.querySelectorAll("svg[data-chart='trace'] circle").length,
    };
  });
  assert.ok(crossState.perTrack >= 4, "a crosshair line renders in every track");
  assert.strictEqual(new Set(crossState.xs).size, 1, "ONE x position shared by every track: " + crossState.xs.join(","));
  assert.ok(crossState.readout >= 3, "the readout row shows the sample's values");
  assert.ok(crossState.pinned > before.traceCircles, "the trace pins the crosshair's sample");

  // ── the distance ⇄ time toggle re-renders the shared axis ─────────────────
  const kmTicks = await page.evaluate(() =>
    [...document.querySelectorAll(".chart-xtick")].map((e) => e.textContent).filter((t) => t.includes("km")).length);
  assert.ok(kmTicks >= 2, "distance mode: km tick labels");
  await page.click("button.scope-chip[aria-pressed='false']");   // → time
  await page.waitForFunction(() =>
    [...document.querySelectorAll(".chart-xtick")].some((e) => /^\d+:\d{2}$/.test(e.textContent)),
    null, { timeout: 5000 });
  const timeTicks = await page.evaluate(() =>
    [...document.querySelectorAll(".chart-xtick")].map((e) => e.textContent).filter((t) => /^\d+:\d{2}$/.test(t)).length);
  assert.ok(timeTicks >= 2, "time mode: m:ss tick labels on the shared axis");

  // ── route-basemap: the mapped run draws tiles behind the route ────────────
  const tileResponses = [];
  page.on("response", (r) => {
    if (r.url().includes("/api/archive/tiles/")) tileResponses.push(r.status());
  });
  await page.goto(B + "/run/8", { waitUntil: "networkidle" });
  await page.waitForSelector("svg[data-chart='trace'] image", { timeout: 15000 });
  const mapped = await page.evaluate(() => {
    const imgs = [...document.querySelectorAll("svg[data-chart='trace'] image")];
    return {
      images: imgs.length,
      hrefs: imgs.map((i) => i.getAttribute("href")),
      layer: !!document.querySelector("svg[data-chart='trace'] g.trace-basemap"),
      attribution: document.body.innerText.includes("© OpenStreetMap contributors"),
      chips: [...document.querySelectorAll("button.scope-chip")].map((b) => b.textContent),
      routeD: (document.querySelector("svg[data-chart='trace'] path") || {}).getAttribute?.("d") || "",
    };
  });
  assert.strictEqual(mapped.images, 9, "the full 3×3 tile rect renders");
  assert.ok(mapped.hrefs.every((h) => /^api\/archive\/tiles\/16\/\d+\/\d+\.png$/.test(h)),
    "every tile href is our own origin, relative: " + mapped.hrefs[0]);
  assert.ok(mapped.layer, "tiles live in the dark-treatable .trace-basemap layer");
  assert.ok(mapped.attribution, "OSM attribution on the card");
  assert.deepStrictEqual(mapped.chips, ["distance", "time", "map", "shape"],
    "the mapped run offers the map/shape toggle");
  assert.strictEqual(tileResponses.length, 9, "nine tile requests hit the archive API");
  assert.ok(tileResponses.every((s) => s === 200), "every tile serves 200: " + tileResponses.join(","));
  assert.ok(mapped.routeD.length > 0, "the route path renders over the tiles");

  // the crosshair pin still tracks on a Mercator-projected trace
  const mappedCircles = await page.evaluate(() =>
    document.querySelectorAll("svg[data-chart='trace'] circle").length);
  const trackSvgs = await page.$$("svg[data-chart='trend']");
  const tbox = await trackSvgs[0].boundingBox();
  await page.mouse.move(tbox.x + tbox.width * 0.4, tbox.y + tbox.height / 2);
  await page.mouse.move(tbox.x + tbox.width * 0.6, tbox.y + tbox.height / 2, { steps: 3 });
  await page.waitForFunction((n) =>
    document.querySelectorAll("svg[data-chart='trace'] circle").length > n,
    mappedCircles, { timeout: 5000 });

  // the shape toggle hides ONLY the backdrop — the route geometry stays put
  await page.getByRole("button", { name: "shape" }).click();
  await page.waitForFunction(() =>
    document.querySelectorAll("svg[data-chart='trace'] image").length === 0,
    null, { timeout: 5000 });
  const bare = await page.evaluate(() => ({
    layer: !!document.querySelector("svg[data-chart='trace'] g.trace-basemap"),
    routeD: (document.querySelector("svg[data-chart='trace'] path") || {}).getAttribute?.("d") || "",
  }));
  assert.strictEqual(bare.layer, false, "shape mode: the basemap layer is gone");
  assert.strictEqual(bare.routeD, mapped.routeD, "toggling never moves the route");
  await page.getByRole("button", { name: "map", exact: true }).click();
  await page.waitForFunction(() =>
    document.querySelectorAll("svg[data-chart='trace'] image").length === 9,
    null, { timeout: 5000 });

  // ── add-interval-lens: reps render as reps, measured against the SET's own
  // median (not the run's) — recoveries shown between them ─────────────────
  await page.goto(B + `/run/${REP_RUN_ID}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector(".rep-table", { timeout: 15000 });
  assert.equal(await page.locator(".rep-row").count(), 5, "five reps render");
  assert.match(await page.locator(".rep-title").innerText(), /5×1 km/,
    "the rep card titles itself with the detected label");
  const firstRowText = await page.locator(".rep-row").first().innerText();
  assert.match(firstRowText, /5:3\d/,
    "the first rep shows ITS OWN pace (330 s = 5:30), not a placeholder or the wrong segment");
  // fix-round finding 1: time and GAP are computed but were never rendered.
  // Pin both to the FIRST work segment's real values: durS 250 s -> "4:10",
  // gapS 326 s/km -> "5:26" (paceS 330 minus the fixture's -4 s/km grade
  // adjustment) — not merely that the cells exist.
  assert.match(firstRowText, /4:10/,
    "the first rep shows its real elapsed time (durS 250s), not a placeholder");
  assert.match(firstRowText, /5:26/,
    "the first rep shows its real grade-adjusted pace (gapS 326), distinct from raw pace");
  assert.match(await page.locator(".rep-time").first().innerText(), /4:10/,
    "the time cell specifically carries the real value");
  assert.match(await page.locator(".rep-gap").first().innerText(), /5:26/,
    "the GAP cell specifically carries the real grade-adjusted value");
  // the recovery between reps is shown, and there is one fewer of them —
  // nothing trails the final rep
  assert.equal(await page.locator(".rep-rec").count(), 4);
  assert.match(await page.locator(".rep-rec").first().innerText(), /60 s recovery/,
    "the recovery row shows its real duration, not a placeholder");
  // fix-round finding 2 (discriminating half): a high-confidence (0.86) set
  // must NOT carry the low-confidence hedge.
  const repSub = await page.locator(".rep-table .card-sub").innerText();
  assert.ok(!repSub.includes("possible structure"),
    "a confident detection (0.86) does not hedge: " + repSub);
  // the per-km splits card renders BELOW the rep table on the SAME page —
  // pinned to real content ("km 6"), not the "SPLITS" header wordmark that
  // appears on every page regardless of whether this card renders
  const repPageText = await page.evaluate(() => document.body.innerText);
  assert.ok(repPageText.includes("Splits") && repPageText.includes("km 6"),
    "the km splits card still renders its real rows alongside the rep table");

  // fix-round finding 2: a genuine but WEAK detection (confidence 0.35 < 0.5)
  // renders as reps, but hedges honestly as "possible structure" — untested
  // anywhere in this plan before this fix round.
  await page.goto(B + `/run/${LOWCONF_RUN_ID}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector(".rep-table", { timeout: 15000 });
  assert.equal(await page.locator(".rep-row").count(), 3, "the weak detection still renders its reps");
  const lowConfSub = await page.locator(".rep-table .card-sub").innerText();
  assert.ok(lowConfSub.includes("possible structure"),
    "confidence 0.35 hedges honestly instead of asserting structure: " + lowConfSub);

  // fix-round finding 3: the REALISTIC "no reps" case — every streamed run
  // gets a run_intervals document (derive_intervals never skips one); a
  // steady run's document has shape:"steady", not an absent row. No rep
  // table must render, and the km splits card (real DETAIL on this fixture
  // too) must still render its real content.
  await page.goto(B + `/run/${STEADY_RUN_ID}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector(".card");
  const steadyText = await page.evaluate(() => document.body.innerText);
  assert.ok(steadyText.includes("Splits") && steadyText.includes("km 6"),
    "steady run: the km splits card still renders its real rows");
  assert.equal(await page.locator(".rep-table").count(), 0,
    "steady run: a run_intervals document with shape:'steady' renders NO rep table");

  // a run with no run_intervals row at all (PLAIN_RUN_ID reuses run 7) — the
  // other real "no reps" path — shows no rep table either, and the km
  // splits card is unaffected
  await page.goto(B + `/run/${PLAIN_RUN_ID}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector(".card");
  assert.equal(await page.locator(".rep-table").count(), 0, "no structure detected — no rep table");
  const plainText = await page.evaluate(() => document.body.innerText);
  assert.ok(plainText.includes("Splits") && plainText.includes("km 6"),
    "the km splits card still renders its real per-km rows — 'km 6' is DETAIL's last split");

  // ── degradation: archive offline / unknown run — chrome still renders ─────
  await page.goto(Bmissing + "/run/7", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => document.body.innerText.includes("Archive offline"), null, { timeout: 15000 });
  const off = await page.evaluate(() => ({
    topbar: !!document.querySelector("header.topbar"),
    text: document.body.innerText.includes("Archive offline"),
  }));
  assert.ok(off.topbar && off.text, "offline: page chrome + honest message, nothing thrown");

  await page.goto(B + "/run/999999", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => document.body.innerText.includes("Unknown run"), null, { timeout: 15000 });

  assert.strictEqual(pageErrors.length, 0, "no uncaught page errors: " + JSON.stringify(pageErrors));
  console.log("ALL PASS");
} catch (e) {
  failed = true;
  console.error("FAIL:", e.message);
} finally {
  if (browser) await browser.close().catch(() => {});
  server.kill();
  serverMissing.kill();
  await rm(dataDir, { recursive: true, force: true }).catch(() => {});
  await rm(emptyDir, { recursive: true, force: true }).catch(() => {});
}
process.exit(failed ? 1 : 0);
