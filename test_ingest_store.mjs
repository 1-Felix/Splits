// Unit tests for ingest-store.mjs — validation edge cases + banking robustness
// (adversarial-review fixes, tasks 10.1/10.3/10.5). The happy paths are covered
// end-to-end by test_ingest_api.mjs; this file targets the sharp corners.
import assert from "node:assert";
import { mkdtemp, readdir, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { bankRhr, bankRun, loadRhr, loadRuns, validateRhrPayload, validateRunPayload } from "./ingest-store.mjs";

function run(over = {}) {
  return {
    sessionUid: "sess-1",
    startTimeLocal: "2026-07-14T07:30:00",
    durationS: 1800,
    distanceM: 5000,
    avgHr: 150,
    sportType: "running",
    avgSpeed: 2.78,
    source: "com.sec.android.app.shealth",
    hrSamples: [{ tSec: 0, bpm: 120 }, { tSec: 5, bpm: 132 }],
    ...over,
  };
}

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

// ── 10.1 date-poison: calendar-invalid dates pass Node's Date.parse (it rolls
//    them over) but crash Python's fromisoformat in the builder — reject here.
test("rejects calendar-invalid dates (Feb 29 in a non-leap year)", () => {
  assert.strictEqual(validateRunPayload(run({ startTimeLocal: "2026-02-29T07:30:00" })).ok, false);
});
test("rejects calendar-invalid dates (Apr 31)", () => {
  assert.strictEqual(validateRunPayload(run({ startTimeLocal: "2026-04-31T07:30:00" })).ok, false);
});
test("accepts a real leap day", () => {
  assert.strictEqual(validateRunPayload(run({ startTimeLocal: "2028-02-29T07:30:00" })).ok, true);
});

// ── 10.3 "__proto__" as a sessionUid hits the prototype accessor on a plain
//    object — the run would be silently dropped (or worse). Reject it outright,
//    and keep bankRun safe even if called directly.
test("rejects sessionUid __proto__", () => {
  assert.strictEqual(validateRunPayload(run({ sessionUid: "__proto__" })).ok, false);
});
test("bankRun stores a __proto__ uid as a real key (defense in depth)", async () => {
  const dir = await mkdtemp(join(tmpdir(), "splits-store-test-"));
  try {
    const banked = await bankRun(dir, { ...run(), sessionUid: "__proto__" });
    assert.strictEqual(banked, 1, "run counted");
    const store = await loadRuns(dir);
    assert.strictEqual(Object.prototype.hasOwnProperty.call(store, "__proto__"), true, "own key present after reload");
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

// ── 8.1/8.2 scope expansion: the run payload carries the new optional metrics
//    (design D9–D13) — whitelisted, validated, null when absent.
test("accepts and stores the expanded optional fields", () => {
  const v = validateRunPayload(run({
    maxHr: 182, elevationGainM: 55.2, activeKcal: 402, totalKcal: 455, steps: 5100,
    speedSamples: [{ tSec: 0, mps: 2.5 }, { tSec: 5, mps: 2.7 }],
  }));
  assert.strictEqual(v.ok, true, v.error);
  assert.strictEqual(v.run.maxHr, 182);
  assert.strictEqual(v.run.elevationGainM, 55.2);
  assert.strictEqual(v.run.activeKcal, 402);
  assert.strictEqual(v.run.totalKcal, 455);
  assert.strictEqual(v.run.steps, 5100);
  assert.deepStrictEqual(v.run.speedSamples, [{ tSec: 0, mps: 2.5 }, { tSec: 5, mps: 2.7 }]);
});
test("expanded fields default to null/empty when absent (Samsung reality)", () => {
  const v = validateRunPayload(run());
  assert.strictEqual(v.ok, true, v.error);
  assert.strictEqual(v.run.maxHr, null);
  assert.strictEqual(v.run.elevationGainM, null);
  assert.strictEqual(v.run.activeKcal, null);
  assert.strictEqual(v.run.totalKcal, null);
  assert.strictEqual(v.run.steps, null);
  assert.deepStrictEqual(v.run.speedSamples, []);
});
test("rejects out-of-range expanded fields", () => {
  assert.strictEqual(validateRunPayload(run({ maxHr: 300 })).ok, false, "maxHr 300");
  assert.strictEqual(validateRunPayload(run({ elevationGainM: -1 })).ok, false, "negative elevation");
  assert.strictEqual(validateRunPayload(run({ steps: -5 })).ok, false, "negative steps");
  assert.strictEqual(validateRunPayload(run({ speedSamples: [{ tSec: 0, mps: -2 }] })).ok, false, "negative speed");
  assert.strictEqual(validateRunPayload(run({ speedSamples: "nope" })).ok, false, "non-array speedSamples");
});

// ── 8.1 resting-heart-rate payload: a daily series banked apart from runs
test("validates a resting-heart-rate payload", () => {
  const v = validateRhrPayload({ restingHeartRate: [{ date: "2026-07-10", bpm: 52 }, { date: "2026-07-11", bpm: 50 }] });
  assert.strictEqual(v.ok, true, v.error);
  assert.deepStrictEqual(v.days, [{ date: "2026-07-10", bpm: 52 }, { date: "2026-07-11", bpm: 50 }]);
});
test("rejects bad resting-heart-rate payloads", () => {
  assert.strictEqual(validateRhrPayload({ restingHeartRate: "x" }).ok, false, "non-array");
  assert.strictEqual(validateRhrPayload({ restingHeartRate: [{ date: "2026-02-29", bpm: 52 }] }).ok, false, "calendar-invalid date");
  assert.strictEqual(validateRhrPayload({ restingHeartRate: [{ date: "2026-07-10", bpm: 0 }] }).ok, false, "bpm 0");
  assert.strictEqual(validateRhrPayload({ restingHeartRate: [{ date: "nope", bpm: 52 }] }).ok, false, "non-ISO date");
});
test("bankRhr upserts by date, idempotently", async () => {
  const dir = await mkdtemp(join(tmpdir(), "splits-store-test-"));
  try {
    let n = await bankRhr(dir, [{ date: "2026-07-10", bpm: 52 }, { date: "2026-07-11", bpm: 50 }]);
    assert.strictEqual(n, 2, "two days banked");
    n = await bankRhr(dir, [{ date: "2026-07-11", bpm: 49 }]);
    assert.strictEqual(n, 2, "re-push of a date does not duplicate");
    const store = await loadRhr(dir);
    assert.strictEqual(store["2026-07-11"], 49, "re-push updated in place");
    assert.strictEqual(store["2026-07-10"], 52, "other days untouched");
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

// ── 10.5 a failed atomic write must not leave .tmp litter in the data dir
test("bankRun cleans up its tmp file when the rename fails", async () => {
  const dir = await mkdtemp(join(tmpdir(), "splits-store-test-"));
  try {
    // a DIRECTORY squatting on the store path makes rename(tmp, dest) fail
    const { mkdir } = await import("node:fs/promises");
    await mkdir(join(dir, "ingested-runs.json"));
    await assert.rejects(() => bankRun(dir, run()), "bankRun surfaces the write failure");
    const leftovers = (await readdir(dir)).filter((f) => f.endsWith(".tmp"));
    assert.deepStrictEqual(leftovers, [], "no tmp files left behind");
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

let failed = 0;
for (const [name, fn] of tests) {
  try {
    await fn();
    console.log(`PASS ${name}`);
  } catch (e) {
    failed++;
    console.log(`FAIL ${name}: ${e.message}`);
  }
}
console.log(failed ? `${failed} FAILED` : "ALL PASS");
process.exit(failed ? 1 : 0);
