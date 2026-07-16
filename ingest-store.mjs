// ingest-store.mjs — validation + durable banking for pushed Health Connect runs
// (telemetry-ingest capability). The ingest endpoint hands each run here; the
// Python builder (ingest_builder.py) reads the banked store to (re)build the
// instance's garmin-data.js.
//
// The store is a single JSON object keyed by the Health Connect session UID:
// tiny data (a few runs/week), cross-language readable (Node writes, Python
// reads), and idempotent by construction — re-pushing a UID overwrites its row.
// SQLite would add an experimental Node dependency and a Node-writes/Python-reads
// coordination we don't need at this volume.

import { readFile, writeFile, rename, unlink } from "node:fs/promises";
import { join } from "node:path";

export const STORE_FILE = "ingested-runs.js" + "on"; // ingested-runs.json
export const RHR_FILE = "ingested-rhr.js" + "on"; // ingested-rhr.json — daily series, banked apart from runs (D12)
const MAX_HR_SAMPLES = 20000; // ~28 h at 1 sample / 5 s — a sane upper bound
const MAX_SPEED_SAMPLES = 20000;
const MAX_RHR_DAYS = 4000; // >10 years of daily records per push
const TIME_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?/; // local ISO, no tz
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

const isNum = (v) => typeof v === "number" && Number.isFinite(v);

// Date.parse rolls calendar-invalid dates over (2026-02-29 → Mar 1) but Python's
// fromisoformat in the builder raises on them — reject them at the door.
function isCalendarDate(ymd) {
  const [y, mo, day] = ymd.split("-").map(Number);
  const cal = new Date(Date.UTC(y, mo - 1, day));
  return cal.getUTCFullYear() === y && cal.getUTCMonth() === mo - 1 && cal.getUTCDate() === day;
}

// Validate + normalize a pushed run. Returns { ok:true, run } with ONLY the
// whitelisted fields, or { ok:false, error } — never throws. The whitelist means
// a client can't smuggle arbitrary keys into the store.
export function validateRunPayload(obj) {
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return { ok: false, error: "body must be a run object" };

  const uid = obj.sessionUid;
  if (typeof uid !== "string" || uid.length === 0 || uid.length > 200) return { ok: false, error: "sessionUid must be a non-empty string (<=200 chars)" };
  if (uid === "__proto__") return { ok: false, error: "sessionUid is reserved" }; // prototype accessor on plain objects

  if (typeof obj.startTimeLocal !== "string" || !TIME_RE.test(obj.startTimeLocal) || !Number.isFinite(Date.parse(obj.startTimeLocal)))
    return { ok: false, error: "startTimeLocal must be a local ISO datetime (YYYY-MM-DDTHH:MM[:SS])" };
  if (!isCalendarDate(obj.startTimeLocal.slice(0, 10)))
    return { ok: false, error: "startTimeLocal is not a valid calendar date" };

  if (!isNum(obj.durationS) || obj.durationS <= 0) return { ok: false, error: "durationS must be a positive number" };
  if (!isNum(obj.distanceM) || obj.distanceM <= 0) return { ok: false, error: "distanceM must be a positive number" };

  const avgHr = obj.avgHr == null ? null : obj.avgHr;
  if (avgHr !== null && (!isNum(avgHr) || avgHr <= 0 || avgHr >= 260)) return { ok: false, error: "avgHr must be null or a bpm in (0,260)" };

  if (typeof obj.sportType !== "string" || obj.sportType.length === 0) return { ok: false, error: "sportType must be a non-empty string" };

  const avgSpeed = obj.avgSpeed == null ? null : obj.avgSpeed;
  if (avgSpeed !== null && (!isNum(avgSpeed) || avgSpeed < 0)) return { ok: false, error: "avgSpeed must be null or a non-negative number" };

  if (!Array.isArray(obj.hrSamples)) return { ok: false, error: "hrSamples must be an array" };
  if (obj.hrSamples.length > MAX_HR_SAMPLES) return { ok: false, error: `hrSamples exceeds ${MAX_HR_SAMPLES}` };
  const hrSamples = [];
  for (const s of obj.hrSamples) {
    if (!s || typeof s !== "object" || !isNum(s.tSec) || s.tSec < 0 || !isNum(s.bpm) || s.bpm <= 0 || s.bpm >= 300)
      return { ok: false, error: "each hrSample must be { tSec>=0, 0<bpm<300 }" };
    hrSamples.push({ tSec: s.tSec, bpm: s.bpm });
  }

  const source = typeof obj.source === "string" ? obj.source : null;

  // scope expansion (design D9–D13): optional per-run metrics — null when the
  // provider doesn't write them (Samsung: no elevation/steps), validated when it does
  const maxHr = obj.maxHr == null ? null : obj.maxHr;
  if (maxHr !== null && (!isNum(maxHr) || maxHr <= 0 || maxHr >= 260)) return { ok: false, error: "maxHr must be null or a bpm in (0,260)" };
  const nonNeg = { elevationGainM: null, activeKcal: null, totalKcal: null, steps: null };
  for (const k of Object.keys(nonNeg)) {
    const v = obj[k] == null ? null : obj[k];
    if (v !== null && (!isNum(v) || v < 0)) return { ok: false, error: `${k} must be null or a non-negative number` };
    nonNeg[k] = v;
  }
  const rawSpeed = obj.speedSamples == null ? [] : obj.speedSamples;
  if (!Array.isArray(rawSpeed)) return { ok: false, error: "speedSamples must be an array" };
  if (rawSpeed.length > MAX_SPEED_SAMPLES) return { ok: false, error: `speedSamples exceeds ${MAX_SPEED_SAMPLES}` };
  const speedSamples = [];
  for (const s of rawSpeed) {
    if (!s || typeof s !== "object" || !isNum(s.tSec) || s.tSec < 0 || !isNum(s.mps) || s.mps < 0)
      return { ok: false, error: "each speedSample must be { tSec>=0, mps>=0 }" };
    speedSamples.push({ tSec: s.tSec, mps: s.mps });
  }

  return {
    ok: true,
    run: {
      sessionUid: uid,
      startTimeLocal: obj.startTimeLocal,
      durationS: obj.durationS,
      distanceM: obj.distanceM,
      avgHr,
      maxHr,
      sportType: obj.sportType,
      avgSpeed,
      source,
      hrSamples,
      speedSamples,
      elevationGainM: nonNeg.elevationGainM,
      activeKcal: nonNeg.activeKcal,
      totalKcal: nonNeg.totalKcal,
      steps: nonNeg.steps,
    },
  };
}

// Validate a resting-heart-rate push: { restingHeartRate: [{ date, bpm }, …] }.
// A daily wellness series, independent of any run — the client may re-push
// overlapping windows freely (banking upserts by date).
export function validateRhrPayload(obj) {
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return { ok: false, error: "body must be an object" };
  const arr = obj.restingHeartRate;
  if (!Array.isArray(arr)) return { ok: false, error: "restingHeartRate must be an array" };
  if (arr.length > MAX_RHR_DAYS) return { ok: false, error: `restingHeartRate exceeds ${MAX_RHR_DAYS} days` };
  const days = [];
  for (const d of arr) {
    if (!d || typeof d !== "object" || typeof d.date !== "string" || !DATE_RE.test(d.date) || !isCalendarDate(d.date))
      return { ok: false, error: "each day must carry a valid ISO date (YYYY-MM-DD)" };
    if (!isNum(d.bpm) || d.bpm <= 0 || d.bpm >= 260) return { ok: false, error: "each day's bpm must be in (0,260)" };
    days.push({ date: d.date, bpm: d.bpm });
  }
  return { ok: true, days };
}

// Load a banked JSON-object store. Missing/corrupt file reads as empty — a
// fresh instance has banked nothing yet.
async function loadStore(dataDir, file) {
  const raw = await readFile(join(dataDir, file), "utf8").catch(() => null);
  if (raw == null) return {};
  try {
    const o = JSON.parse(raw);
    return o && typeof o === "object" && !Array.isArray(o) ? o : {};
  } catch {
    return {};
  }
}

export const loadRuns = (dataDir) => loadStore(dataDir, STORE_FILE);
export const loadRhr = (dataDir) => loadStore(dataDir, RHR_FILE);

let seq = 0;

// Write a store atomically (temp file + rename); a failed write never litters
// the data dir with its temp file.
async function writeStore(dataDir, file, store) {
  const dest = join(dataDir, file);
  const tmp = join(dataDir, `.${file}.${process.pid}.${seq++}.tmp`);
  try {
    await writeFile(tmp, JSON.stringify(store), "utf8");
    await rename(tmp, dest);
  } catch (e) {
    await unlink(tmp).catch(() => {});
    throw e;
  }
}

// Upsert one run into the store, atomically. Keyed by sessionUid, so a re-push
// overwrites in place — idempotent. Callers MUST serialize invocations (see the
// ingest mutex in serve.mjs) so the read-modify-write can't interleave.
// Returns the total run count after the write.
export async function bankRun(dataDir, run) {
  // Null prototype so a uid like "__proto__" is a plain own key, never the
  // prototype accessor (validation rejects it too — this is defense in depth).
  const store = Object.assign(Object.create(null), await loadRuns(dataDir));
  store[run.sessionUid] = run;
  await writeStore(dataDir, STORE_FILE, store);
  return Object.keys(store).length;
}

// Upsert a batch of daily resting-HR records ({ date, bpm }), atomically —
// keyed by date, so overlapping windows re-push safely. Same serialization
// contract as bankRun. Returns the total day count after the write.
export async function bankRhr(dataDir, days) {
  const store = Object.assign(Object.create(null), await loadRhr(dataDir));
  for (const d of days) store[d.date] = d.bpm;
  await writeStore(dataDir, RHR_FILE, store);
  return Object.keys(store).length;
}
