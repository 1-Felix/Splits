// test_run_page.mjs — the /run/:id page end to end (run-detail 8.1).
//
// Boots serve.mjs over a fixture archive (streams + compliance + run_metrics)
// and drives a real browser: the crosshair moves EVERY track together, the
// trace pin follows it, the distance ⇄ time toggle re-renders the shared axis,
// and the page degrades honestly when the archive 503s or the id is unknown.
import assert from "node:assert";
import { spawn } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
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
    };
  });
  assert.ok(before.tracks >= 4, `pace/hr/cad/elev tracks render (got ${before.tracks})`);
  assert.strictEqual(before.power, false, "a power-less run renders NO power track — absence is silent");
  assert.strictEqual(before.trace, 1, "the GPS trace renders");
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
