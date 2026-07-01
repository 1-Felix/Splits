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

import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { spawn } from "node:child_process";
import { extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(fileURLToPath(new URL(".", import.meta.url)));
const PORT = Number(process.env.PORT) || 8000;
const ENTRY = "/Running%20Dashboard.dc.html";

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

function json(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
  });
  res.end(payload);
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
      if (req.method !== "POST") { json(res, 405, { ok: false, error: "use POST" }); return; }
      const result = await triggerSync();
      json(res, result.status === "already-running" ? 409 : result.ok ? 200 : 502, result);
      return;
    }
    if (pathname === "/api/status") {
      json(res, 200, { syncing, lastSync: await lastSyncTime(), lastResult });
      return;
    }

    if (pathname === "/") {
      res.writeHead(302, { Location: ENTRY });
      res.end();
      return;
    }

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
    res.writeHead(200, {
      "Content-Type": MIME[extname(filePath).toLowerCase()] || "application/octet-stream",
      "Cache-Control": "no-cache, no-store, must-revalidate",
    });
    res.end(body);
  } catch (err) {
    res.writeHead(500, { "Content-Type": "text/plain" }).end(`500 — ${err.message}`);
  }
});

server.listen(PORT, () => {
  console.log(`SPLITS dashboard → http://localhost:${PORT}${ENTRY}`);
  console.log(`  data dir: ${DATA_DIR}`);
  bootSync();
  scheduleDailySync();
});
