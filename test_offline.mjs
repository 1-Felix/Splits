// test_offline.mjs — the golden rule as an executable test (vendor-runtime D5).
//
// "The cockpit renders complete without any API" has always meant more than "no
// /api/* response": the page must not depend on any THIRD-PARTY ORIGIN either.
// This test boots serve.mjs and, in a real browser (Playwright chromium, already
// a devDependency), ABORTS EVERY REQUEST WHOSE ORIGIN IS NOT THE SERVER'S OWN —
// by origin, never by a hardcoded CDN host list (design D5), so a future
// contributor who reintroduces cdn.example.com fails here without anyone editing
// a denylist. It then asserts the cockpit and the progress page render their key
// surfaces, that React came from the vendored copy (window.React === 18.3.1, so
// support.js took its `if (w.React && w.ReactDOM) return` short-circuit and never
// reached unpkg), and that NOT ONE non-same-origin request was even attempted.
//
// DATA (documented choice): the worktree ships no garmin-data.js — it is
// gitignored and lives only in the main checkout — so the cockpit and progress
// pages render from their built-in demo fallback (`const D = this.state.data ||
// this.buildData()`). That is the self-contained option the task allows (the
// alternative was pointing SPLITS_DATA_DIR at the main checkout's SMB-mounted
// data). Consequence: the same-origin dynamic import of running-data.js 404s on
// the absent garmin-data.js / plan-data.js and the demo data renders instead —
// those two SAME-ORIGIN 404s are expected here and have nothing to do with the
// origin block. A throwaway activity-archive.db is created in a temp dir pointed
// at by SPLITS_DATA_DIR, so the progress page's same-origin archive-API request
// returns 200 — proving the block is origin-scoped, not blanket.
//
// CONSOLE: every *.dc.html ships its raw <x-dc> template with mustache SVG
// geometry attributes (<rect x="{{ b.x }}">). Chromium validates SVG attributes
// at HTML-parse time and logs one "Expected length"/"Expected moveto" error per
// attribute — pre-existing noise, present on main, independent of this change and
// of the network. We assert there are NO uncaught page errors and NO console
// error beyond those two documented, change-independent categories (mustache
// template noise; the same-origin data-file 404s), plus the real teeth: zero
// non-same-origin requests, React vendored at 18.3.1, and the surfaces render.

import assert from "node:assert";
import { spawn } from "node:child_process";
import { mkdtemp, rm, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";
import { chromium } from "playwright";

const ROOT = dirname(fileURLToPath(import.meta.url));
const PORT = 8156;
const ORIGIN = "http://localhost:" + PORT;

// Minimal read-only archive so the progress page's same-origin archive request
// returns 200 (schema mirrors test_archive_api.mjs; two running activities).
function makeArchive(dir) {
  const db = new DatabaseSync(join(dir, "activity-archive.db"));
  db.exec(`CREATE TABLE activities (
    activity_id INTEGER PRIMARY KEY, start_time_local TEXT NOT NULL, type_key TEXT,
    name TEXT, distance_m REAL, duration_s REAL, avg_hr INTEGER, max_hr INTEGER,
    avg_cadence REAL, elevation_gain_m REAL, summary_json TEXT NOT NULL,
    detail_json TEXT, detail_fetched_at TEXT, first_seen_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, detail_distilled_json TEXT, detail_streams_json TEXT)`);
  const ins = db.prepare(`INSERT INTO activities (activity_id, start_time_local,
    type_key, name, distance_m, duration_s, avg_hr, max_hr, avg_cadence,
    elevation_gain_m, summary_json, first_seen_at, updated_at, detail_distilled_json,
    detail_streams_json)
    VALUES (?, ?, 'running', ?, ?, ?, ?, ?, ?, ?, '{}', 'x', 'x', ?, ?)`);
  // run 1 carries a distilled detail + full streams so /run/1 renders its
  // tracks and trace under the origin block (run-detail 8.2)
  const N = 300;
  const streams = JSON.stringify({
    t: Array.from({ length: N }, (_, i) => i * 3),
    d: Array.from({ length: N }, (_, i) => Math.round(i * 33.4)),
    hr: Array.from({ length: N }, (_, i) => 140 + Math.round(10 * Math.sin(i / 30))),
    v: Array.from({ length: N }, (_, i) => +(2.8 + 0.3 * Math.sin(i / 20)).toFixed(2)),
    cad: Array.from({ length: N }, (_, i) => 165 + (i % 4)),
    elev: Array.from({ length: N }, (_, i) => +(410 + 15 * Math.sin(i / 60)).toFixed(1)),
    lat: Array.from({ length: N }, (_, i) => +(47.37 + 0.003 * Math.sin(i / 70)).toFixed(5)),
    lon: Array.from({ length: N }, (_, i) => +(8.53 + 0.005 * (i / N)).toFixed(5)),
  });
  const detail = JSON.stringify({
    splits: Array.from({ length: 10 }, (_, i) => ({ km: i + 1, pace: 300 + i * 3, hr: 145 + i })),
    hrSeries: [140, 145, 150], driftBpm: 5, zoneMin: [5, 20, 10, 3, 0],
    tempC: 20, te: 3.0, load: 120, elevGain: 40, splitShape: "even",
  });
  ins.run(1, "2026-05-01 07:00:00", "Morning Run", 10000, 3000, 150, 165, 168, 40, detail, streams);
  ins.run(2, "2026-05-08 07:00:00", "Long Run", 21000, 7200, 148, 162, 166, 120, null, null);
  db.close();
}

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
    try { const r = await fetch(ORIGIN + "/api/status"); if (r.ok) return; } catch {}
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error("server not ready\n" + (errRef ? errRef() : ""));
}

// A console error we tolerate: (1) inert-template mustache SVG noise, or (2) a
// same-origin resource 404 (the demo-fallback data files; favicon). Everything
// else — a blocked CDN, a broken React, a failed font — must make the test fail.
function isBenignConsoleError(text) {
  if (text.includes("{{")) return true;                       // raw-template SVG mustache
  if (/Failed to load resource/.test(text) && /40\d|50\d/.test(text)) return true; // same-origin 4xx/5xx (verified below)
  return false;
}

const dataDir = await mkdtemp(join(tmpdir(), "splits-offline-"));
makeArchive(dataDir);

const server = startServer(dataDir);
let browser;
let failed = false;
try {
  await waitReady(server.errRef);

  browser = await chromium.launch();
  const page = await browser.newPage();

  const consoleErrors = [];
  const pageErrors = [];
  const blocked = [];               // non-same-origin requests we aborted
  const badSameOrigin = [];         // same-origin responses with status >= 400
  const ok200 = new Set();          // same-origin paths that returned 200

  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("pageerror", (e) => pageErrors.push(String(e)));
  page.on("response", (r) => {
    const u = new URL(r.url());
    if (u.origin !== ORIGIN) return;
    if (r.status() >= 400) badSameOrigin.push(u.pathname + " -> " + r.status());
    else if (r.status() === 200) ok200.add(u.pathname);
  });

  // THE golden-rule mechanism: abort by origin, not by a known-CDN list (D5).
  await page.route("**/*", (route) => {
    const u = new URL(route.request().url());
    if (u.origin !== ORIGIN) { blocked.push(u.href); return route.abort(); }
    return route.continue();
  });

  // ── cockpit ────────────────────────────────────────────────────────────────
  await page.goto(ORIGIN + "/", { waitUntil: "domcontentloaded" });
  // wait until React has mounted the demo cockpit (heatmap cells + week cards)
  await page.waitForFunction(
    () => document.querySelectorAll('rect[data-hb="heat"]').length > 50 &&
          document.querySelectorAll(".week-grid .day").length >= 7,
    null, { timeout: 15000 });

  const cockpit = await page.evaluate(() => {
    const hero = document.querySelector("#card-hero");
    return {
      reactVersion: window.React && window.React.version,
      reactDomPresent: typeof window.ReactDOM !== "undefined",
      heroText: hero ? hero.innerText : "",
      weekDays: document.querySelectorAll(".week-grid .day").length,
      heatCells: document.querySelectorAll('rect[data-hb="heat"]').length,
    };
  });

  // React is the vendored 18.3.1 global → support.js short-circuited, no unpkg.
  assert.strictEqual(cockpit.reactVersion, "18.3.1", "window.React is the vendored 18.3.1 UMD");
  assert.ok(cockpit.reactDomPresent, "window.ReactDOM is present (vendored)");
  // hero: race name + a live countdown
  assert.ok(/Half Marathon|Lakeside Half/.test(cockpit.heroText), "hero shows the race name");
  assert.ok(/\bweeks out\b/.test(cockpit.heroText) && /\bdays\b/.test(cockpit.heroText),
    "hero shows the countdown (days / weeks out)");
  // THIS WEEK: seven day cards; heatmap: a full grid
  assert.ok(cockpit.weekDays >= 7, "THIS WEEK renders at least seven day cards (got " + cockpit.weekDays + ")");
  assert.ok(cockpit.heatCells > 300, "the heatmap renders a full year of cells (got " + cockpit.heatCells + ")");

  // The vendored subresources were actually served from our origin.
  for (const p of [
    "/vendor/react.production.min.js",
    "/vendor/react-dom.production.min.js",
    "/support.js",
    "/dashboard.css",
  ]) assert.ok(ok200.has(p), "served 200 from our origin: " + p);

  // No third-party origin was even attempted while loading the cockpit.
  assert.strictEqual(blocked.length, 0,
    "cockpit made zero non-same-origin requests; blocked=" + JSON.stringify(blocked));

  // ── progress ─────────────────────────────────────────────────────────────────
  await page.goto(ORIGIN + "/progress", { waitUntil: "domcontentloaded" });
  // wait until React has mounted the demo progress view (its long-history charts).
  // innerText excludes the hidden <x-dc> template, so this only sees rendered text.
  await page.waitForFunction(
    () => document.body.innerText.includes("Weekly volume"),
    null, { timeout: 15000 });
  const progress = await page.evaluate(() => {
    const t = document.body.innerText;
    return {
      reactVersion: window.React && window.React.version,
      hasWeeklyVolume: t.includes("Weekly volume"),
      hasFitness: t.includes("Fitness"),
    };
  });
  assert.strictEqual(progress.reactVersion, "18.3.1", "progress: React is the vendored 18.3.1");
  assert.ok(progress.hasWeeklyVolume, "progress: the weekly-volume section renders");
  assert.ok(progress.hasFitness, "progress: the fitness & fatigue section renders");

  // Origin-scoped, not blanket: a SAME-ORIGIN archive request still succeeds
  // (200) under the very block that aborts every foreign origin.
  const archive = await page.evaluate(async () => {
    const r = await fetch("/api/archive/activities");
    return { status: r.status, total: (await r.json()).total };
  });
  assert.strictEqual(archive.status, 200, "same-origin archive API returns 200 under the origin block");
  assert.strictEqual(archive.total, 2, "same-origin archive API returns its rows");

  // ── /run/:id ─────────────────────────────────────────────────────────────
  // The trace-not-basemap decision is exactly what makes this page render with
  // every third-party origin blocked: no tiles, no tile host (run-detail 8.2).
  await page.goto(ORIGIN + "/run/1", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(
    () => document.querySelectorAll("svg[data-chart='trend']").length >= 3 &&
          document.querySelectorAll("svg[data-chart='trace']").length === 1,
    null, { timeout: 15000 });
  const runPage = await page.evaluate(() => ({
    reactVersion: window.React && window.React.version,
    tracks: document.querySelectorAll("svg[data-chart='trend']").length,
    trace: document.querySelectorAll("svg[data-chart='trace']").length,
    splits: document.body.innerText.includes("Splits"),
  }));
  assert.strictEqual(runPage.reactVersion, "18.3.1", "run page: React is the vendored 18.3.1");
  assert.ok(runPage.tracks >= 3, "run page: the track stack renders");
  assert.strictEqual(runPage.trace, 1, "run page: the GPS trace renders — with no tile origin to block");
  assert.ok(runPage.splits, "run page: the splits table renders");

  // Still zero foreign-origin requests after all three pages.
  assert.strictEqual(blocked.length, 0,
    "no page attempted any non-same-origin request; blocked=" + JSON.stringify(blocked));

  // Every same-origin failure is only a demo-fallback data 404 (or favicon) —
  // nothing else (react/fonts/css/support/topbar) errored.
  for (const b of badSameOrigin) {
    assert.ok(/\/(garmin-data|plan-data)\.js|\/favicon\.ico/.test(b),
      "the only same-origin failures are the demo-fallback data files / favicon; saw: " + b);
  }

  // No uncaught exceptions, and no console error beyond the two documented,
  // change-independent categories.
  assert.strictEqual(pageErrors.length, 0, "no uncaught page errors: " + JSON.stringify(pageErrors));
  const significant = consoleErrors.filter((t) => !isBenignConsoleError(t));
  assert.strictEqual(significant.length, 0,
    "no console errors beyond documented template/data noise; got: " + JSON.stringify(significant));

  // ── task 4.4 guard: the invariant fails at the source, not only in a browser ──
  for (const f of ["Running Dashboard.dc.html", "progress.dc.html", "run.dc.html", "dashboard.css"]) {
    const src = await readFile(join(ROOT, f), "utf8");
    const m = src.match(/https?:\/\/[^\s"')]+/);
    assert.ok(!m, `${f} must contain no absolute http(s) subresource URL; found: ${m && m[0]}`);
  }

  console.log("ALL PASS");
} catch (e) {
  failed = true;
  console.error("FAIL:", e.message);
} finally {
  if (browser) await browser.close().catch(() => {});
  server.kill();
  await rm(dataDir, { recursive: true, force: true }).catch(() => {});
}
process.exit(failed ? 1 : 0);
