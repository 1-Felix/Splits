// test_compression.mjs — content-negotiated gzip in serve.mjs (vendor-runtime D4).
//
// Uses raw node:http (NOT fetch): undici auto-adds Accept-Encoding and silently
// decompresses, which would hide the very Content-Encoding we need to observe.
// node:http sends exactly the headers we pass and hands back the raw bytes.
//
// Asserts: a text/js/json resource with `Accept-Encoding: gzip` comes back
// gzipped and gunzips to bytes identical to the plain response; the same resource
// without Accept-Encoding comes back plain with no Content-Encoding; a vendored
// woff2 is never gzipped (already compressed) and is served immutable; the
// archive JSON is gzipped; and — the classic bug — a compressed response never
// advertises a Content-Length describing the *uncompressed* body.

import assert from "node:assert";
import http from "node:http";
import { spawn } from "node:child_process";
import { gunzipSync } from "node:zlib";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";

const ROOT = dirname(fileURLToPath(import.meta.url));
const PORT = 8158;
const ORIGIN = "http://localhost:" + PORT;

function makeArchive(dir) {
  const db = new DatabaseSync(join(dir, "activity-archive.db"));
  db.exec(`CREATE TABLE activities (activity_id INTEGER PRIMARY KEY,
    start_time_local TEXT NOT NULL, type_key TEXT, name TEXT, distance_m REAL,
    duration_s REAL, avg_hr INTEGER, max_hr INTEGER, avg_cadence REAL,
    elevation_gain_m REAL, summary_json TEXT NOT NULL, detail_json TEXT,
    detail_fetched_at TEXT, first_seen_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    detail_distilled_json TEXT)`);
  const ins = db.prepare(`INSERT INTO activities (activity_id, start_time_local,
    type_key, name, distance_m, duration_s, avg_hr, max_hr, avg_cadence,
    elevation_gain_m, summary_json, first_seen_at, updated_at)
    VALUES (?, ?, 'running', ?, ?, ?, ?, ?, ?, ?, '{}', 'x', 'x')`);
  for (let i = 1; i <= 40; i++)
    ins.run(i, "2026-05-01 07:00:00", "Run " + i, 10000 + i, 3000, 150, 165, 168, 40);
  db.close();
}

// raw request — send exactly `headers`, return raw (possibly compressed) bytes.
function raw(path, headers = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request(ORIGIN + path, { headers }, (res) => {
      const chunks = [];
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks) }));
    });
    req.on("error", reject);
    req.end();
  });
}

async function waitReady(errRef) {
  for (let i = 0; i < 60; i++) {
    try { const r = await fetch(ORIGIN + "/api/status"); if (r.ok) return; } catch {}
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error("server not ready\n" + (errRef ? errRef() : ""));
}

const dataDir = await mkdtemp(join(tmpdir(), "splits-gzip-"));
makeArchive(dataDir);
// a compressible garmin-data.js in the data dir (the spec's example resource)
await writeFile(
  join(dataDir, "garmin-data.js"),
  "export const garminData = " +
    JSON.stringify({ recentRuns: Array.from({ length: 60 }, (_, i) => ({ km: i, pace: 300 + i, hr: 150 })), note: "x".repeat(800) }) +
    ";\n", "utf8");

const server = spawn(process.execPath, ["serve.mjs"], {
  cwd: ROOT,
  env: { ...process.env, PORT: String(PORT), SYNC_ON_BOOT: "off", SYNC_AT: "off", SPLITS_DATA_DIR: dataDir },
  stdio: ["ignore", "ignore", "pipe"],
});
let serr = ""; server.stderr.on("data", (d) => (serr += d));

let failed = false;
try {
  await waitReady(() => serr);

  // ── a compressing client gets gzip that decodes to the identical bytes ───────
  const plain = await raw("/garmin-data.js");
  const gz = await raw("/garmin-data.js", { "Accept-Encoding": "gzip" });
  assert.strictEqual(plain.status, 200);
  assert.ok(!plain.headers["content-encoding"], "no Accept-Encoding → no Content-Encoding");
  assert.strictEqual(gz.headers["content-encoding"], "gzip", "Accept-Encoding: gzip → Content-Encoding: gzip");
  assert.ok(/accept-encoding/i.test(gz.headers["vary"] || ""), "gzipped response sets Vary: Accept-Encoding");
  assert.ok(gunzipSync(gz.body).equals(plain.body), "gunzip(gzipped) === the plain bytes");
  assert.ok(gz.body.length < plain.body.length, "the gzipped body is actually smaller on the wire");

  // ── the classic bug: never a Content-Length describing the uncompressed body ─
  if (gz.headers["content-length"] != null) {
    assert.strictEqual(Number(gz.headers["content-length"]), gz.body.length,
      "any Content-Length on a gzipped response describes the COMPRESSED body");
    assert.notStrictEqual(Number(gz.headers["content-length"]), plain.body.length,
      "the gzipped response must not carry the uncompressed length");
  }

  // ── gzip;q=0 means 'do not gzip' ─────────────────────────────────────────────
  const q0 = await raw("/dashboard.css", { "Accept-Encoding": "gzip;q=0" });
  assert.ok(!q0.headers["content-encoding"], "gzip;q=0 → no Content-Encoding");

  // ── woff2 is never double-compressed, and is served immutable ────────────────
  const woff = await raw("/vendor/fonts/archivo-latin.woff2", { "Accept-Encoding": "gzip" });
  assert.strictEqual(woff.status, 200);
  assert.ok(!woff.headers["content-encoding"], "woff2 is never gzipped");
  assert.strictEqual(woff.headers["content-type"], "font/woff2", "woff2 keeps its MIME type");
  assert.ok(/immutable/.test(woff.headers["cache-control"] || ""), "vendored woff2 is cached immutable");

  // ── vendored react.js: gzipped, decodes identical, cached immutable ──────────
  const rjsPlain = await raw("/vendor/react.production.min.js");
  const rjsGz = await raw("/vendor/react.production.min.js", { "Accept-Encoding": "gzip" });
  assert.strictEqual(rjsGz.headers["content-encoding"], "gzip", "vendored react.js is gzipped");
  assert.ok(gunzipSync(rjsGz.body).equals(rjsPlain.body), "gunzip(react.js) === plain react.js");
  assert.ok(/immutable/.test(rjsGz.headers["cache-control"] || ""), "vendored react.js is cached immutable");

  // ── archive JSON goes through the same path ──────────────────────────────────
  const arcPlain = await raw("/api/archive/activities");
  const arcGz = await raw("/api/archive/activities", { "Accept-Encoding": "gzip" });
  assert.strictEqual(arcGz.headers["content-encoding"], "gzip", "/api/archive/activities is gzipped");
  assert.ok(!arcPlain.headers["content-encoding"], "archive without Accept-Encoding → plain");
  assert.ok(gunzipSync(arcGz.body).equals(arcPlain.body), "gunzip(archive) === the plain JSON bytes");
  assert.strictEqual(JSON.parse(gunzipSync(arcGz.body).toString("utf8")).total, 40, "decoded archive JSON is intact");

  // measured wire sizes (react + react-dom), for the record
  const rdomPlain = await raw("/vendor/react-dom.production.min.js");
  const rdomGz = await raw("/vendor/react-dom.production.min.js", { "Accept-Encoding": "gzip" });
  const rawKB = (rjsPlain.body.length + rdomPlain.body.length) / 1024;
  const gzKB = (rjsGz.body.length + rdomGz.body.length) / 1024;
  console.log(`  react+react-dom on the wire: ${rawKB.toFixed(1)} KB plain -> ${gzKB.toFixed(1)} KB gzip`);

  console.log("ALL PASS");
} catch (e) {
  failed = true;
  console.error("FAIL:", e.message);
} finally {
  server.kill();
  await rm(dataDir, { recursive: true, force: true }).catch(() => {});
}
process.exit(failed ? 1 : 0);
