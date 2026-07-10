// Web server for the SPLITS dashboard: static files + a thin sync/status API.
//
//   pnpm dev            → serves this folder on http://localhost:8000
//   PORT=3000 pnpm dev  → pick a different port
//
// Responsibilities:
//   • Serve the dashboard and its app modules from this directory (the image).
//   • Serve the two DATA files (garmin-data.js, plan-data.js) from the data dir
//     (a mounted volume in the container; this folder in local dev).
//   • POST /api/sync   → run sync_garmin.py once (single-flight), report result.
//   • GET  /api/status → { syncing, lastSync, lastResult } for the dashboard.
//
// The dashboard never talks to Garmin — it imports running-data.js, which merges
// the data files. This server just produces/serves those files.

import "./load-env.mjs"; // MUST be first — loads .env before the process.env reads below
import { createServer } from "node:http";
import { readFile, writeFile, rename, unlink, stat } from "node:fs/promises";
import { spawn } from "node:child_process";
import { timingSafeEqual } from "node:crypto";
import { gzipSync } from "node:zlib";
import { extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { hashPlan, validatePlanText } from "./plan-io.mjs";

const ROOT = resolve(fileURLToPath(new URL(".", import.meta.url)));
const PORT = Number(process.env.PORT) || 8000;

// Clean page routes (progress-views design D7): every page is its own
// .dc.html served directly — no redirect chains. Adding a page is one file
// plus one line here; the original file paths keep working as static files.
const PAGES = {
  "/": "/Running Dashboard.dc.html",
  "/progress": "/progress.dc.html",
};

// Where personal data lives. The container sets SPLITS_DATA_DIR=/data (the
// mounted volume); when unset, it falls back to the project dir so `pnpm dev`
// works unchanged. (No /data auto-detect — that misfires on Windows, where
// "/data" resolves to C:\data.)
const DATA_DIR = process.env.SPLITS_DATA_DIR
  ? resolve(process.env.SPLITS_DATA_DIR)
  : ROOT;

// Files served from DATA_DIR rather than the image. Everything else is app code.
const DATA_FILES = new Set(["/garmin-data.js", "/plan-data.js"]);

// Interpreter for the sync script. Container sets python3; override for Windows.
const PYTHON = process.env.SPLITS_PYTHON || "python3";

// Auto-sync cadence (in-process — no cron daemon needed; honors the container TZ
// because Node's Date uses process.env.TZ).
//   SYNC_ON_BOOT=off       → skip the boot sync
//   SYNC_AT=HH:MM | off    → daily sync at this local time (default 04:00)
//   SYNC_STALE_HOURS=N     → boot sync only if telemetry is older than N hours
const SYNC_ON_BOOT = (process.env.SYNC_ON_BOOT || "on").toLowerCase() !== "off";
const SYNC_AT = process.env.SYNC_AT || "04:00";
const STALE_HOURS = Number(process.env.SYNC_STALE_HOURS || 18);

// Plan push (PUT /api/plan). OFF unless a token is set — a self-host that doesn't opt in
// never exposes a write endpoint (the route simply 404s like any unknown path).
const PLAN_TOKEN = process.env.SPLITS_PLAN_TOKEN || "";
const PLAN_MAX_BYTES = 512 * 1024;
let planSeq = 0;

// Archive API (GET /api/archive/…). The database normally sits in the data dir;
// SPLITS_ARCHIVE_DIR points dev-against-a-mounted-data-dir at a LOCAL archive
// copy instead — SQLite over an SMB mount is unsupported (see README).
const ARCHIVE_DIR = process.env.SPLITS_ARCHIVE_DIR
  ? resolve(process.env.SPLITS_ARCHIVE_DIR)
  : DATA_DIR;
const ARCHIVE_DB = join(ARCHIVE_DIR, "activity-archive.db");
const ARCHIVE_PAGE_DEFAULT = 50;
const ARCHIVE_PAGE_MAX = 100;

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
  ".map": "application/json; charset=utf-8",
  ".md": "text/markdown; charset=utf-8",
  ".py": "text/plain; charset=utf-8",
};

// ── sync state (single-flight) ────────────────────────────────────────────────
let syncing = false;
let lastResult = null; // { ok, code, at, error } of the most recent sync attempt

// ── response compression (design D4) ─────────────────────────────────────────
// gzip via the built-in node:zlib (the server stays dependency-free) when the
// client advertises it AND the resolved content type is compressible text/JS/
// JSON. Already-compressed types (woff2, images) pass through untouched —
// gzipping them costs CPU and *grows* the body. We never set Content-Length
// ourselves: res.end(buf) lets Node size the exact bytes it sends, so a gzipped
// response can never go out carrying the pre-gzip length (the classic bug).
function acceptsGzip(req) {
  const ae = req.headers["accept-encoding"];
  if (typeof ae !== "string") return false;
  return ae.split(",").some((part) => {
    const seg = part.trim().split(";");
    if (seg[0].toLowerCase() !== "gzip") return false;
    const q = seg.slice(1).map((s) => s.trim()).find((s) => s.toLowerCase().startsWith("q="));
    return !q || Number(q.slice(2)) > 0; // gzip;q=0 means "do not use gzip"
  });
}

function isCompressible(contentType) {
  if (!contentType) return false;
  return /^text\//i.test(contentType)
    || /^application\/javascript\b/i.test(contentType)
    || /^application\/json\b/i.test(contentType);
}

// Send a fully-buffered response, negotiating gzip. `headers` MUST NOT carry a
// Content-Length — Node derives it from the buffer handed to res.end().
function sendBuffer(req, res, status, headers, body, contentType) {
  const h = { ...headers };
  if (isCompressible(contentType)) {
    h["Vary"] = "Accept-Encoding";
    if (acceptsGzip(req) && body.length > 0) {
      body = gzipSync(body);
      h["Content-Encoding"] = "gzip";
    }
  }
  res.writeHead(status, h);
  res.end(body);
}

function json(req, res, status, body) {
  const payload = Buffer.from(JSON.stringify(body), "utf8");
  sendBuffer(req, res, status, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
  }, payload, "application/json; charset=utf-8");
}

// Constant-time string compare (equal-length only; unequal lengths are trivially unequal).
function safeEqual(a, b) {
  const ba = Buffer.from(String(a));
  const bb = Buffer.from(String(b));
  return ba.length === bb.length && timingSafeEqual(ba, bb);
}

// Read a request body as UTF-8, rejecting past `max` bytes (→ err.code === 'TOO_LARGE').
// Once over the cap we stop buffering (bounded memory) but keep draining, so the response
// is sent cleanly after the upload rather than resetting the socket mid-stream.
function readBody(req, max) {
  return new Promise((done, fail) => {
    let size = 0;
    let over = false;
    const chunks = [];
    req.on("data", (c) => {
      size += c.length;
      if (size > max) { over = true; return; }
      chunks.push(c);
    });
    req.on("end", () => {
      if (over) {
        const e = new Error("body too large");
        e.code = "TOO_LARGE";
        fail(e);
      } else {
        done(Buffer.concat(chunks).toString("utf8"));
      }
    });
    req.on("error", fail);
  });
}

// Serialize plan writes: run each push after the previous settles, so the version check and
// the rename form one atomic critical section (no read-check-write interleaving) and at most
// one validator child runs at a time.
let planPushChain = Promise.resolve();
function planPushExclusive(fn) {
  const run = planPushChain.then(fn, fn);
  planPushChain = run.then(() => {}, () => {});
  return run;
}

// Version guard → validate → atomic write. Returns { status, body }. Runs inside the mutex.
async function applyPlanPush(body, ifMatch) {
  const planPath = join(DATA_DIR, "plan-data.js");
  const current = await readFile(planPath, "utf8").catch(() => null);
  const currentHash = current != null ? hashPlan(current) : null;
  if (ifMatch == null)
    return { status: 428, body: { ok: false, error: "If-Match required — pull first, or force", version: currentHash } };
  if (ifMatch !== "*" && ifMatch !== currentHash)
    return { status: 409, body: { ok: false, error: "stale — canonical changed since your pull; pull first", version: currentHash } };
  const v = await validatePlanText(body);
  if (!v.ok) return { status: 422, body: { ok: false, error: v.error } };
  const tmp = join(DATA_DIR, `.plan-data.${process.pid}.${planSeq++}.tmp.js`);
  try {
    await writeFile(tmp, body, "utf8");
    await rename(tmp, planPath);
  } catch (e) {
    await unlink(tmp).catch(() => {}); // don't leave the temp behind on a failed write
    throw e;
  }
  return { status: 200, body: { ok: true, bytes: Buffer.byteLength(body), weeks: v.weeks, version: hashPlan(body) } };
}

// ── archive API — a read-only window over activity-archive.db ────────────────
// The API is a window, not an engine (progress-views design D2): it SELECTs
// stored rows, renames fields, filters and paginates — every derived value it
// returns was written by the Python sync. No domain formulas or policy here.
//
// node:sqlite is imported lazily so an older local Node still boots the server
// and serves every page; only the archive routes 503. The database stays in
// DELETE journal mode with the nightly sync as the single writer, so handles
// are per-request read-only opens and SQLITE_BUSY is an honest 503 — the
// server never holds a connection across the sync's write transactions.
let DatabaseSync;   // resolved on first archive request; false = driver absent

async function openArchive() {
  if (DatabaseSync === undefined) {
    DatabaseSync = await import("node:sqlite")
      .then((m) => m.DatabaseSync)
      .catch(() => false);
  }
  if (!DatabaseSync) throw new Error("runtime lacks node:sqlite (Node >= 24 expected)");
  return new DatabaseSync(ARCHIVE_DB, { readOnly: true }); // throws if the file is missing
}

// Promoted columns only — raw summary_json / detail_json are never selected,
// so no response can leak Garmin's raw shapes into the browser.
const ARCHIVE_SUMMARY_COLS = `activity_id, start_time_local, type_key, name,
  distance_m, duration_s, avg_hr, avg_cadence, elevation_gain_m`;

function archiveSummaryRow(r) {
  return {
    activityId: r.activity_id,
    startTimeLocal: r.start_time_local,
    type: r.type_key,
    name: r.name,
    distanceM: r.distance_m,
    durationS: r.duration_s,
    avgHr: r.avg_hr,
    avgCadence: r.avg_cadence,
    elevationGainM: r.elevation_gain_m,
  };
}

function listArchiveActivities(db, params) {
  const where = [];
  const args = [];
  const type = params.get("type");
  if (type) { where.push("type_key = ?"); args.push(type); }
  const year = params.get("year");
  if (year) { where.push("substr(start_time_local, 1, 4) = ?"); args.push(year); }
  const from = params.get("from");
  if (from) { where.push("substr(start_time_local, 1, 10) >= ?"); args.push(from); }
  const to = params.get("to");
  if (to) { where.push("substr(start_time_local, 1, 10) <= ?"); args.push(to); }
  const cond = where.length ? "WHERE " + where.join(" AND ") : "";
  const limit = Math.min(Math.max(Number(params.get("limit")) || ARCHIVE_PAGE_DEFAULT, 1), ARCHIVE_PAGE_MAX);
  const offset = Math.max(Number(params.get("offset")) || 0, 0);
  const total = db.prepare(`SELECT COUNT(*) AS n FROM activities ${cond}`).get(...args).n;
  const rows = db.prepare(
    `SELECT ${ARCHIVE_SUMMARY_COLS} FROM activities ${cond}
     ORDER BY start_time_local DESC, activity_id DESC LIMIT ? OFFSET ?`
  ).all(...args, limit, offset);
  return {
    activities: rows.map(archiveSummaryRow),
    total,
    limit,
    offset,
    nextOffset: offset + rows.length < total ? offset + rows.length : null,
  };
}

function getArchiveActivity(db, id) {
  const r = db.prepare(
    `SELECT ${ARCHIVE_SUMMARY_COLS}, max_hr, detail_distilled_json
     FROM activities WHERE activity_id = ?`).get(id);
  if (!r) return null;
  // planned-vs-actual and this run's best efforts are plain SELECTs over rows
  // the sync already scored (run-detail D5) — renamed, never derived. Guarded:
  // a pre-v3/pre-metrics archive simply has no such table, which means no plan
  // and no bests, not an outage.
  let plan = null;
  try {
    const p = db.prepare(
      `SELECT date, wk, planned_kind, planned_km, planned_load, planned_title,
              status, reason, actual_km, actual_pace_s, actual_hr
       FROM plan_compliance WHERE activity_id = ? ORDER BY date LIMIT 1`).get(id);
    if (p) {
      plan = {
        date: p.date, wk: p.wk,
        plannedKind: p.planned_kind, plannedKm: p.planned_km,
        plannedLoad: p.planned_load, plannedTitle: p.planned_title,
        status: p.status, reason: p.reason,
        actualKm: p.actual_km, actualPaceS: p.actual_pace_s, actualHr: p.actual_hr,
      };
    }
  } catch { /* no plan_compliance table in this archive */ }
  let bests = null;
  try {
    const b = db.prepare(
      `SELECT best_1k_s, best_mile_s, best_5k_s, best_10k_s, best_half_s
       FROM run_metrics WHERE activity_id = ?`).get(id);
    if (b) {
      bests = {
        best1kS: b.best_1k_s, bestMileS: b.best_mile_s, best5kS: b.best_5k_s,
        best10kS: b.best_10k_s, bestHalfS: b.best_half_s,
      };
    }
  } catch { /* no run_metrics table in this archive */ }
  return {
    ...archiveSummaryRow(r),
    maxHr: r.max_hr,
    // stored verbatim — the sync's distiller wrote it; never recomputed here
    detail: r.detail_distilled_json ? JSON.parse(r.detail_distilled_json) : null,
    plan,
    bests,
  };
}

async function handleArchive(req, res, pathname, url) {
  if (req.method !== "GET") { json(req, res, 405, { ok: false, error: "use GET" }); return; }
  let db;
  try {
    db = await openArchive();
  } catch {
    // missing db / unopenable file / no driver — pages and other APIs keep working
    json(req, res, 503, { ok: false, error: "archive unavailable" });
    return;
  }
  try {
    if (pathname === "/api/archive/activities") {
      json(req, res, 200, listArchiveActivities(db, url.searchParams));
      return;
    }
    // /api/archive/activities/:id and …/:id/streams — the parse accepts the
    // suffix while keeping the ^\d+$ guard on the id itself (run-detail 4.1)
    const rest = pathname.slice("/api/archive/activities/".length);
    const m = /^(\d+)(\/streams)?$/.exec(rest);
    if (!m) { json(req, res, 404, { ok: false, error: "unknown activity" }); return; }
    const id = Number(m[1]);
    if (m[2]) {
      // streams: the stored columnar TEXT served VERBATIM — never parsed,
      // never reshaped (the API stays a window, not an engine); gzip comes
      // from sendBuffer's negotiation, which is what makes 105 KB cost ~29 KB
      let row;
      try {
        row = db.prepare(
          "SELECT detail_streams_json FROM activities WHERE activity_id = ?").get(id);
      } catch (e) {
        // a pre-v6 archive has no streams column — that's "no streams", not
        // an outage; anything else (BUSY, corruption) falls to the 503 below
        if (/no such column/i.test(String(e && e.message))) {
          json(req, res, 404, { ok: false, error: "no streams for this activity" });
          return;
        }
        throw e;
      }
      if (!row) { json(req, res, 404, { ok: false, error: "unknown activity" }); return; }
      if (!row.detail_streams_json) {
        json(req, res, 404, { ok: false, error: "no streams for this activity" });
        return;
      }
      sendBuffer(req, res, 200, {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
      }, Buffer.from(row.detail_streams_json, "utf8"), "application/json; charset=utf-8");
      return;
    }
    const activity = getArchiveActivity(db, id);
    if (!activity) { json(req, res, 404, { ok: false, error: "unknown activity" }); return; }
    json(req, res, 200, activity);
  } catch {
    // SQLITE_BUSY under the sync's write lock, or any other read failure:
    // an honest 503, never a partial payload
    json(req, res, 503, { ok: false, error: "archive unavailable" });
  } finally {
    if (db) try { db.close(); } catch { /* already closed */ }
  }
}

// Last successful sync = mtime of the telemetry file (survives restarts because
// it lives in the volume). Null if it has never been written.
async function lastSyncTime() {
  const info = await stat(join(DATA_DIR, "garmin-data.js")).catch(() => null);
  return info ? info.mtime.toISOString() : null;
}

// Run sync_garmin.py once. Always resolves (soft-fail) — never throws, so a bad
// sync can't crash the server. Returns a structured result.
function runSync() {
  return new Promise((done) => {
    let stderr = "";
    let child;
    try {
      child = spawn(PYTHON, ["sync_garmin.py"], {
        cwd: ROOT,
        env: process.env,
        windowsHide: true,
      });
    } catch (err) {
      done({ ok: false, code: null, at: new Date().toISOString(), error: String(err && err.message || err) });
      return;
    }
    child.stderr && child.stderr.on("data", (d) => { stderr += d.toString(); if (stderr.length > 4000) stderr = stderr.slice(-4000); });
    child.stdout && child.stdout.on("data", (d) => process.stdout.write(d));
    child.on("error", (err) => {
      done({ ok: false, code: null, at: new Date().toISOString(), error: String(err && err.message || err) });
    });
    child.on("close", (code) => {
      done({
        ok: code === 0,
        code,
        at: new Date().toISOString(),
        error: code === 0 ? null : (stderr.trim().split("\n").slice(-6).join("\n") || `sync exited with code ${code}`),
      });
    });
  });
}

// Trigger a sync, honoring single-flight. Returns the result (or already-running).
async function triggerSync() {
  if (syncing) return { ok: false, status: "already-running" };
  syncing = true;
  try {
    lastResult = await runSync();
    return lastResult;
  } finally {
    syncing = false;
  }
}

// Telemetry is stale if it's missing or older than STALE_HOURS.
async function isStale() {
  const iso = await lastSyncTime();
  if (!iso) return true;
  return Date.now() - new Date(iso).getTime() > STALE_HOURS * 3600 * 1000;
}

// On boot, sync in the background when data is missing/stale (soft-fail) so a
// fresh deploy isn't stuck on demo data — without blocking server startup.
async function bootSync() {
  if (!SYNC_ON_BOOT) { console.log("  boot sync disabled (SYNC_ON_BOOT=off)"); return; }
  if (!(await isStale())) { console.log("  boot sync skipped (telemetry is fresh)"); return; }
  console.log("  boot sync: telemetry missing/stale — syncing in background…");
  triggerSync().then((r) => console.log(r.ok ? "  boot sync ok" : `  boot sync failed: ${r.error || r.status}`));
}

// Daily sync at SYNC_AT (local time). Reschedules itself after each run.
function scheduleDailySync() {
  if (SYNC_AT.toLowerCase() === "off") { console.log("  daily sync disabled (SYNC_AT=off)"); return; }
  const m = /^(\d{1,2}):(\d{2})$/.exec(SYNC_AT.trim());
  if (!m) { console.warn(`  SYNC_AT='${SYNC_AT}' invalid (want HH:MM) — daily sync off`); return; }
  const hh = Number(m[1]), mm = Number(m[2]);
  const tick = () => {
    const now = new Date();
    const next = new Date(now);
    next.setHours(hh, mm, 0, 0);
    if (next <= now) next.setDate(next.getDate() + 1);
    const ms = next - now;
    console.log(`  next daily sync: ${next.toString()} (~${Math.round(ms / 360000) / 10}h)`);
    setTimeout(() => {
      triggerSync()
        .then((r) => console.log(r.ok ? "  daily sync ok" : `  daily sync failed: ${r.error || r.status}`))
        .finally(tick);
    }, ms);
  };
  tick();
}

const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url, `http://${req.headers.host}`);
    let pathname = decodeURIComponent(url.pathname);

    // ── API ──────────────────────────────────────────────────────────────────
    if (pathname === "/api/sync") {
      if (req.method !== "POST") { json(req, res, 405, { ok: false, error: "use POST" }); return; }
      const result = await triggerSync();
      json(req, res, result.status === "already-running" ? 409 : result.ok ? 200 : 502, result);
      return;
    }
    if (pathname === "/api/status") {
      json(req, res, 200, { syncing, lastSync: await lastSyncTime(), lastResult });
      return;
    }
    if (pathname === "/api/archive/activities" || pathname.startsWith("/api/archive/activities/")) {
      await handleArchive(req, res, pathname, url);
      return;
    }

    // ── plan push: replace the canonical plan-data.js. Gated on PLAN_TOKEN — when unset
    //    the route falls through to the static handler and 404s, as if it didn't exist.
    if (pathname === "/api/plan" && PLAN_TOKEN) {
      if (req.method !== "PUT") { json(req, res, 405, { ok: false, error: "use PUT" }); return; }
      // auth
      const auth = req.headers["authorization"] || "";
      const token = auth.startsWith("Bearer ") ? auth.slice(7) : "";
      if (!safeEqual(token, PLAN_TOKEN)) { json(req, res, 401, { ok: false, error: "unauthorized" }); return; }
      // reject an oversized declared body up front (streaming cap is the fallback)
      const declared = Number(req.headers["content-length"]);
      if (Number.isFinite(declared) && declared > PLAN_MAX_BYTES) {
        json(req, res, 413, { ok: false, error: "body too large" });
        return;
      }
      // body (size-capped)
      let body;
      try {
        body = await readBody(req, PLAN_MAX_BYTES);
      } catch (e) {
        json(req, res, e.code === "TOO_LARGE" ? 413 : 400, { ok: false, error: e.message });
        return;
      }
      // version guard → validate → atomic write, serialized so concurrent pushes can't
      // interleave (a bad or stale push never touches the live file)
      const out = await planPushExclusive(() => applyPlanPush(body, req.headers["if-match"]));
      json(req, res, out.status, out.body);
      return;
    }

    // clean page routes serve their component file directly; /run/:id is the
    // one parameterised route (run-detail D6) — the page reads its id from
    // location.pathname, never from the served filename
    if (PAGES[pathname]) pathname = PAGES[pathname];
    else if (/^\/run\/\d+$/.test(pathname)) pathname = "/run.dc.html";

    // ── data files come from the volume; everything else from the image ────────
    const baseDir = DATA_FILES.has(pathname) ? DATA_DIR : ROOT;
    const filePath = normalize(join(baseDir, pathname));
    if (!filePath.startsWith(baseDir)) {
      res.writeHead(403).end("Forbidden");
      return;
    }

    const info = await stat(filePath).catch(() => null);
    if (!info || !info.isFile()) {
      res.writeHead(404, { "Content-Type": "text/plain" }).end(`404 — ${pathname} not found`);
      return;
    }

    const body = await readFile(filePath);
    const contentType = MIME[extname(filePath).toLowerCase()] || "application/octet-stream";
    // Vendored assets (react + fonts) are content-stable and version-pinned, so
    // cache them hard; everything else stays uncacheable so a data edit shows up
    // on the next load. sendBuffer negotiates gzip (text/js/json only — the
    // vendored woff2 pass through as-is).
    const cacheControl = pathname.startsWith("/vendor/")
      ? "public, max-age=31536000, immutable"
      : "no-cache, no-store, must-revalidate";
    sendBuffer(req, res, 200, {
      "Content-Type": contentType,
      "Cache-Control": cacheControl,
    }, body, contentType);
  } catch (err) {
    res.writeHead(500, { "Content-Type": "text/plain" }).end(`500 — ${err.message}`);
  }
});

server.listen(PORT, () => {
  console.log(`SPLITS dashboard → http://localhost:${PORT}/`);
  console.log(`  data dir: ${DATA_DIR}`);
  bootSync();
  scheduleDailySync();
});
