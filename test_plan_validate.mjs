import assert from "node:assert";
import { validatePlanText, hashPlan } from "./plan-io.mjs";

const week = (wk, days) =>
  `{ wk:"${wk}", label:"L", mon:"2026-07-06", sun:"2026-07-12", phase:"Build", km:32, long:"17 km", focus:"f", days:${days} }`;
const sevenDays = `[
  { day:"Mon", date:"2026-07-06", kind:"cross", title:"Spin", load:"Easy", km:0 },
  { day:"Tue", date:"2026-07-07", kind:"strength", title:"S", load:"Moderate", km:0 },
  { day:"Wed", date:"2026-07-08", kind:"run", title:"Easy", load:"Easy", km:5 },
  { day:"Thu", date:"2026-07-09", kind:"strength", title:"S", load:"Moderate", km:0 },
  { day:"Fri", date:"2026-07-10", kind:"run", title:"Threshold", load:"Hard", km:8 },
  { day:"Sat", date:"2026-07-11", kind:"strength", title:"S", load:"Easy", km:0 },
  { day:"Sun", date:"2026-07-12", kind:"run", title:"Long", load:"Moderate", km:18 }
]`;

// valid — one summary-only week + one detailed week
let r = await validatePlanText(`export const planData = { block: [ ${week("Wk 1", "null")}, ${week("Wk 2", sevenDays)} ] };`);
assert.ok(r.ok, "valid plan accepted: " + r.error);
assert.strictEqual(r.weeks, 2, "reports the week count");

// minimal valid — a single summary-only week
r = await validatePlanText(`export const planData = { block: [ ${week("Wk 1", "null")} ] };`);
assert.ok(r.ok, "minimal plan accepted: " + r.error);

// missing block
r = await validatePlanText(`export const planData = { race: {} };`);
assert.ok(!r.ok && /block/.test(r.error), "missing block rejected");

// block not an array
r = await validatePlanText(`export const planData = { block: {} };`);
assert.ok(!r.ok, "non-array block rejected");

// week missing a required field (focus)
r = await validatePlanText(
  `export const planData = { block: [ { wk:"Wk 1", label:"L", mon:"2026-07-06", sun:"2026-07-12", phase:"Build", km:32, long:"17 km" } ] };`
);
assert.ok(!r.ok && /focus/.test(r.error), "week missing focus rejected");

// days present but not 7 entries
r = await validatePlanText(`export const planData = { block: [ ${week("Wk 1", '[{ day:"Mon" }]')} ] };`);
assert.ok(!r.ok && /7/.test(r.error), "days length != 7 rejected");

// day missing a required field (load)
const badDay = sevenDays.replace('kind:"run", title:"Easy", load:"Easy", km:5', 'kind:"run", title:"Easy", km:5');
r = await validatePlanText(`export const planData = { block: [ ${week("Wk 1", badDay)} ] };`);
assert.ok(!r.ok && /load/.test(r.error), "day missing load rejected");

// syntax error
r = await validatePlanText(`export const planData = {{{`);
assert.ok(!r.ok, "syntax error rejected");

// a default-only export is rejected — the dashboard imports the NAMED planData
r = await validatePlanText(`export default { block: [ ${week("Wk 1", "null")} ] };`);
assert.ok(!r.ok && /named/.test(r.error), "default-only export rejected");

// the validator child does NOT inherit the parent env (secrets can't leak to pushed code)
process.env.PLAN_TEST_CANARY = "leaked";
r = await validatePlanText(
  `if (process.env.PLAN_TEST_CANARY) throw new Error("env leaked"); export const planData = { block: [ ${week("Wk 1", "null")} ] };`
);
delete process.env.PLAN_TEST_CANARY;
assert.ok(r.ok, "validator env is stripped (canary not visible to pushed code): " + r.error);

// a plan that never finishes loading is rejected, not left hanging the caller:
//  (a) an unsettled top-level await — node exits on its own
r = await validatePlanText(`export const planData = { block: [ ${week("Wk 1", "null")} ] }; await new Promise(() => {});`);
assert.ok(!r.ok, "unsettled-await plan rejected");
//  (b) a busy loop node can't detect — our timeout kills it (short timeout so the test is fast)
process.env.SPLITS_PLAN_VALIDATE_MS = "800";
r = await validatePlanText(`export const planData = { block: [ ${week("Wk 1", "null")} ] }; while (true) {}`);
delete process.env.SPLITS_PLAN_VALIDATE_MS;
assert.ok(!r.ok && /timed out/.test(r.error), "busy-loop plan times out: " + r.error);

// hashPlan: stable and content-sensitive
assert.strictEqual(hashPlan("abc"), hashPlan("abc"), "hash is stable");
assert.notStrictEqual(hashPlan("abc"), hashPlan("abd"), "hash differs on content change");

console.log("ALL PASS");
