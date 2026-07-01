import assert from "node:assert";
import { migrateLegacyPlan } from "./plan-migrate.js";

// legacy shape: dated weekPlan/nextWeekPlan + a block with mon/sun but no `days`
const legacy = () => ({
  block: [
    { wk: "Wk 1", mon: "2026-06-22", sun: "2026-06-28" },
    { wk: "Wk 2", mon: "2026-06-29", sun: "2026-07-05" },
    { wk: "Wk 3", mon: "2026-07-06", sun: "2026-07-12" },
    { wk: "Wk 4", mon: "2026-07-13", sun: "2026-07-19" },
  ],
  weekPlan: [{ day: "Wed", date: "2026-07-01", kind: "run", title: "Easy", load: "Easy", km: 5 }],
  nextWeekPlan: [{ day: "Wed", date: "2026-07-08", kind: "run", title: "Easy", load: "Easy", km: 5 }],
});

// dated arrays pin to their exact block week: weekPlan → Wk2, nextWeekPlan → Wk3
let d = migrateLegacyPlan(legacy(), "2026-07-01");
assert.ok(Array.isArray(d.block[1].days) && d.block[1].days.length === 1, "weekPlan attaches to Wk2 by date");
assert.ok(Array.isArray(d.block[2].days) && d.block[2].days.length === 1, "nextWeekPlan attaches to Wk3 by date");
assert.ok(!d.block[0].days && !d.block[3].days, "unmatched weeks stay without days (→ placeholder)");

// dateless legacy arrays fall back to the current + next week by position
const dateless = () => ({
  block: [
    { wk: "Wk 1", mon: "2026-06-29", sun: "2026-07-05" },
    { wk: "Wk 2", mon: "2026-07-06", sun: "2026-07-12" },
  ],
  weekPlan: [{ day: "Mon", kind: "cross", title: "Spin", load: "Easy", km: 0 }],
  nextWeekPlan: [{ day: "Mon", kind: "cross", title: "Spin", load: "Easy", km: 0 }],
});
d = migrateLegacyPlan(dateless(), "2026-07-01"); // today ∈ Wk1
assert.ok(d.block[0].days && d.block[1].days, "dateless plans fall back to current + next week");

// today outside the block → first week treated as current
d = migrateLegacyPlan(dateless(), "2020-01-01");
assert.ok(d.block[0].days, "today before the block → attaches to the first week");

// already-new shape (a block week has `days`) is left untouched
const modern = {
  block: [{ wk: "Wk 1", mon: "2026-06-29", sun: "2026-07-05", days: [{ day: "Mon" }] }],
  weekPlan: [{ day: "X", date: "2026-06-29", kind: "run" }],
};
const before = modern.block[0].days;
migrateLegacyPlan(modern, "2026-07-01");
assert.strictEqual(modern.block[0].days, before, "modern plan is not modified");

// missing / empty block → no throw
migrateLegacyPlan({}, "2026-07-01");
migrateLegacyPlan({ block: [] }, "2026-07-01");

console.log("ALL PASS");
