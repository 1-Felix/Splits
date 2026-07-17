// test_compare_page.mjs — the /compare view end to end (run-comparison 5.10).
//
// Boots serve.mjs over a fixture archive holding runs of DIFFERENT lengths and
// different stream columns, and drives a real browser: the comparison is
// driven purely by ?ids= (shareable), every measure overlays the runs on ONE
// shared scale, the crosshair reads all runs at the same distance (a finished
// run reads as ended), splits align by kilometre with honest tails, and the
// page degrades honestly per slot — unknown ids, stream-less runs, non-runs —
// and wholesale when the archive is away.
import assert from "node:assert";
import { spawn } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";
import { chromium } from "playwright";

const ROOT = dirname(fileURLToPath(import.meta.url));
const PORT = 8181;
const B = "http://localhost:" + PORT;
const Bmissing = "http://localhost:" + (PORT + 1);

// run 7: 6 km with pace/hr/cadence/elevation; run 8: 8 km WITHOUT cadence —
// the cadence track must carry run 7 alone. run 9: a run with splits but no
// stored stream. id 30: not a run at all.
function streams(n, mps, dStep, withCad) {
  const s = {
    t: Array.from({ length: n }, (_, i) => i * 2),
    d: Array.from({ length: n }, (_, i) => Math.round(i * dStep)),
    hr: Array.from({ length: n }, (_, i) => 140 + Math.round(10 * Math.sin(i / 40))),
    v: Array.from({ length: n }, (_, i) => +(mps + 0.3 * Math.sin(i / 25)).toFixed(2)),
    elev: Array.from({ length: n }, (_, i) => +(400 + 20 * Math.sin(i / 70)).toFixed(1)),
  };
  if (withCad) s.cad = Array.from({ length: n }, (_, i) => 160 + (i % 6));
  return s;
}
const splits = (n, base) => Array.from({ length: n }, (_, i) => ({ km: i + 1, pace: base + (i % 4) * 10, hr: 142 + i }));

function makeArchive(dir) {
  const db = new DatabaseSync(join(dir, "activity-archive.db"));
  db.exec(`CREATE TABLE activities (
    activity_id INTEGER PRIMARY KEY, start_time_local TEXT NOT NULL, type_key TEXT,
    name TEXT, distance_m REAL, duration_s REAL, avg_hr INTEGER, max_hr INTEGER,
    avg_cadence REAL, elevation_gain_m REAL, summary_json TEXT NOT NULL,
    detail_json TEXT, detail_fetched_at TEXT, first_seen_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, detail_distilled_json TEXT, detail_streams_json TEXT)`);
  const ins = db.prepare(`INSERT INTO activities (activity_id, start_time_local, type_key,
      name, distance_m, duration_s, avg_hr, max_hr, avg_cadence, elevation_gain_m,
      summary_json, detail_json, first_seen_at, updated_at, detail_distilled_json,
      detail_streams_json)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', null, 'x', 'x', ?, ?)`);
  ins.run(7, "2026-06-14 08:00:00", "running", "Tune-up Tempo", 6030, 1198, 148, 168, 164, 40,
    JSON.stringify({ splits: splits(6, 320) }), JSON.stringify(streams(600, 3.1, 10.05, true)));
  ins.run(8, "2026-07-05 08:30:00", "running", "Sonthofen Rehearsal", 8010, 1710, 152, 172, null, 90,
    JSON.stringify({ splits: splits(8, 335) }), JSON.stringify(streams(700, 2.95, 11.45, false)));
  ins.run(9, "2026-05-01 07:00:00", "running", "Summary-only Run", 5000, 1500, 139, 160, 162, 25,
    JSON.stringify({ splits: splits(5, 350) }), null);
  ins.run(30, "2026-06-01 18:00:00", "strength_training", "Gym", null, 3600, 110, 140, null, null, null, null);
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

const dataDir = await mkdtemp(join(tmpdir(), "splits-cmppage-"));
const emptyDir = await mkdtemp(join(tmpdir(), "splits-cmppage-empty-"));
makeArchive(dataDir);
// a present-but-unopenable db = a real OUTAGE (503 → "Archive offline"); a
// missing file would be "not provisioned" (404) and show different copy
await writeFile(join(emptyDir, "activity-archive.db"), "not a sqlite file");
const server = startServer(PORT, { SPLITS_DATA_DIR: dataDir });
const serverMissing = startServer(PORT + 1, { SPLITS_DATA_DIR: emptyDir });

let browser;
let failed = false;
let step = "boot";
try {
  await waitReady(B, server.errRef);
  await waitReady(Bmissing, serverMissing.errRef);
  browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1200, height: 1600 } });
  const pageErrors = [];
  page.on("pageerror", (e) => pageErrors.push(String(e)));
  const bodyText = () => page.evaluate(() => document.body.innerText);

  // ── a two-run comparison from a bare URL — no prior selection state ────────
  step = "two-run compare";
  await page.goto(B + "/compare?ids=7,8", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => document.querySelectorAll("svg[data-chart='trend']").length >= 3, null, { timeout: 20000 });
  const t1 = await bodyText();
  assert.ok(t1.includes("Comparing 2 runs"), "the header names the comparison");
  assert.ok(t1.includes("Tune-up Tempo") && t1.includes("Sonthofen Rehearsal"), "both runs are named");
  assert.ok(t1.includes("Splits, kilometre by kilometre"), "the splits section renders");

  // every measure overlays the runs on ONE scale: pace/hr/elev carry both
  // series, cadence only the run that has cadence — and the missing one is
  // silent, not an empty placeholder
  const tracks = await page.evaluate(() =>
    [...document.querySelectorAll("svg[data-chart='trend']")].map((svg) => ({
      label: (svg.getAttribute("aria-label") || "").split(" of ")[0],
      series: Number(svg.getAttribute("data-series") || 0),
      legend: svg.closest(".chart-frame") ? svg.closest(".chart-frame").querySelectorAll(".chart-legend-item").length : 0,
      yticksSets: 1,
    })));
  const byLabel = Object.fromEntries(tracks.map((t) => [t.label, t]));
  assert.strictEqual(byLabel["pace"].series, 2, "pace overlays both runs on one axis");
  assert.strictEqual(byLabel["pace"].legend, 2, "a two-series track carries a legend");
  assert.strictEqual(byLabel["heart rate"].series, 2, "heart rate overlays both runs");
  assert.strictEqual(byLabel["cadence"].series, 1, "a run without cadence is absent from that track — silently");
  assert.strictEqual(byLabel["cadence"].legend, 0, "a one-series track carries no legend");
  assert.strictEqual(byLabel["elevation"].series, 2, "elevation overlays both runs");

  // the summary marks best values (presentation only)
  const bestMarks = await page.evaluate(() =>
    [...document.querySelectorAll(".cmp-summary .metric")].filter((e) => e.style.color === "var(--accent)").length);
  assert.ok(bestMarks >= 3, "best-per-row values are marked in the summary (got " + bestMarks + ")");

  // splits align by km; the longer run's tail renders ALONE (km 7–8 of the
  // 8 km run beside an em-dash lane for the 6 km run)
  // the dc-runtime wraps each interpolation in span.sc-interp — one per value
  const splitRows = await page.evaluate(() =>
    [...document.querySelectorAll(".cmp-splits-row")].map((r) => {
      const spans = [...r.querySelectorAll("span.sc-interp")].map((s) => s.textContent);
      return { km: spans[0], paces: spans.slice(1) };
    }));
  assert.strictEqual(splitRows.length, 8, "rows run to the LONGEST run's kilometres");
  const km8 = splitRows.find((r) => r.km === "km 8");
  assert.strictEqual(km8.paces[0], "—", "the shorter run's lane is honest at km 8");
  assert.ok(/^\d+:\d{2}$/.test(km8.paces[1]), "the longer run's km 8 split renders alone");
  const km3 = splitRows.find((r) => r.km === "km 3");
  assert.ok(km3.paces.every((p) => /^\d+:\d{2}$/.test(p)), "shared kilometres read across both runs");

  // ── one crosshair, every run at the same distance; a finished run reads
  //    as ended, never as a value ─────────────────────────────────────────────
  step = "crosshair";
  const svgs = await page.$$("svg[data-chart='trend']");
  const box = await svgs[0].boundingBox();
  await page.mouse.move(box.x + box.width * 0.4, box.y + box.height / 2);
  await page.mouse.move(box.x + box.width * 0.5, box.y + box.height / 2, { steps: 2 });
  await page.waitForFunction(() => document.body.innerText.includes("at ") &&
    [...document.querySelectorAll("svg[data-chart='trend'] line")].filter((l) => l.getAttribute("stroke-dasharray") === "3 3").length >= 3,
    null, { timeout: 5000 });
  const crossXs = await page.evaluate(() =>
    [...document.querySelectorAll("svg[data-chart='trend'] line")]
      .filter((l) => l.getAttribute("stroke-dasharray") === "3 3").map((l) => l.getAttribute("x1")));
  assert.strictEqual(new Set(crossXs).size, 1, "ONE x position shared by every track: " + crossXs.join(","));
  const mid = await bodyText();
  assert.ok(mid.includes("bpm"), "the readout carries per-run values");
  // both runs still alive at ~4 km → two value rows, no 'ended'
  assert.ok(!mid.includes("ended at"), "mid-course, both runs read values");
  // push the crosshair past the shorter run's finish (~90% of 8 km)
  await page.mouse.move(box.x + box.width * 0.9, box.y + box.height / 2, { steps: 2 });
  await page.waitForFunction(() => document.body.innerText.includes("ended at"), null, { timeout: 5000 });
  const late = await bodyText();
  assert.ok(late.includes("ended at 6"), "the 6 km run reads as ended, not as a value");

  // ── garbage ids are dropped; the valid pair still compares ────────────────
  step = "garbage ids";
  await page.goto(B + "/compare?ids=abc,7,,8,7", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => document.body.innerText.includes("Comparing 2 runs"), null, { timeout: 20000 });

  // ── an unknown id gets an honest slot; the known runs compare normally ────
  step = "unknown id slot";
  await page.goto(B + "/compare?ids=7,8,999999", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => document.body.innerText.includes("Comparing 2 runs"), null, { timeout: 20000 });
  const unk = await bodyText();
  assert.ok(unk.includes("no archived run has this id"), "the unknown slot says so");
  assert.ok(unk.includes("Tune-up Tempo") && unk.includes("Sonthofen Rehearsal"), "the known runs compare normally");

  // ── a stream-less run keeps its summary and splits columns ────────────────
  step = "stream-less run";
  await page.goto(B + "/compare?ids=7,9", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => document.body.innerText.includes("has no stored sample stream"), null, { timeout: 20000 });
  const noStream = await bodyText();
  assert.ok(noStream.includes("Comparing 2 runs") && noStream.includes("Summary-only Run"), "the run stays in the comparison");
  await page.waitForFunction(() => document.querySelectorAll("svg[data-chart='trend']").length >= 3, null, { timeout: 10000 });
  const soloSeries = await page.evaluate(() =>
    [...document.querySelectorAll("svg[data-chart='trend']")].map((s) => Number(s.getAttribute("data-series"))));
  assert.ok(soloSeries.every((n) => n === 1), "tracks carry only the streamed run — scales cover the runs actually shown");

  // ── fewer than two resolvable runs → an honest prompt, never a broken page ─
  step = "prompt states";
  await page.goto(B + "/compare?ids=abc", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => document.body.innerText.includes("Nothing to compare yet"), null, { timeout: 15000 });
  await page.goto(B + "/compare?ids=7", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => document.body.innerText.includes("Nothing to compare yet"), null, { timeout: 15000 });
  // a non-run id resolves but does not compare: only one RUN remains
  await page.goto(B + "/compare?ids=7,30", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => document.body.innerText.includes("Not enough runs to compare"), null, { timeout: 15000 });

  // ── archive down → chrome + honest offline state ──────────────────────────
  step = "offline";
  await page.goto(Bmissing + "/compare?ids=7,8", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => document.body.innerText.includes("Archive offline"), null, { timeout: 15000 });
  const off = await page.evaluate(() => ({ topbar: !!document.querySelector("header.topbar") }));
  assert.ok(off.topbar, "offline: the chrome still renders");

  assert.strictEqual(pageErrors.length, 0, "no uncaught page errors: " + JSON.stringify(pageErrors));
  console.log("ALL PASS");
} catch (e) {
  failed = true;
  console.error("FAIL at step '" + step + "':", e.message);
} finally {
  if (browser) await browser.close().catch(() => {});
  server.kill();
  serverMissing.kill();
  await rm(dataDir, { recursive: true, force: true }).catch(() => {});
  await rm(emptyDir, { recursive: true, force: true }).catch(() => {});
}
process.exit(failed ? 1 : 0);
