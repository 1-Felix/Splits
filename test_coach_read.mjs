import assert from "node:assert";
import { coachRead } from "./coach-read.js";

const maxHR = 197;
const wp = [{ date: "2026-06-28", kind: "run", load: "Moderate", title: "Long Run" }];

// rule 1 — easy intent, hot, high HR + drift -> heat/threshold
let r = { date: "2026-06-28", type: "Long Run", km: 16, pace: 372, hr: 170,
  detail: { zoneMin: [0, 6, 32, 55, 5], driftBpm: 16, tempC: 28, splitShape: "positive", te: 5.0 } };
assert.match(coachRead(r, wp, maxHR), /pushed HR to threshold/);

// rule 2 — big drift, not hot
r = { date: "x", type: "Run", km: 10, pace: 400, hr: 150,
  detail: { zoneMin: [2, 20, 20, 5, 0], driftBpm: 14, tempC: 14, splitShape: "even" } };
assert.match(coachRead(r, [], maxHR), /cardiac drift/);

// rule 3 — negative split
r = { date: "x", type: "Run", km: 8, pace: 360, hr: 150,
  detail: { zoneMin: [5, 20, 10, 2, 0], driftBpm: 3, tempC: 15, splitShape: "negative" } };
assert.match(coachRead(r, [], maxHR), /Negative split/);

// rule 6 — properly easy
r = { date: "x", type: "Run", km: 6, pace: 600, hr: 140,
  detail: { zoneMin: [10, 8, 0, 0, 0], driftBpm: 2, tempC: 15, splitShape: "even" } };
assert.match(coachRead(r, [], maxHR), /Properly easy/);

// fallback — mid HR, nothing notable
r = { date: "x", type: "Run", km: 5, pace: 360, hr: 155,
  detail: { zoneMin: [2, 8, 6, 0, 0], driftBpm: 2, tempC: 15, splitShape: "even" } };
assert.match(coachRead(r, [], maxHR), /5 km at/);

// no detail -> empty string
assert.strictEqual(coachRead({ km: 5 }, [], maxHR), "");

console.log("ALL PASS");
