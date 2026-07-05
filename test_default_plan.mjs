/* test_default_plan.mjs — the shipped seed plan honors the contract it ships
 * with: validates like a pushed plan, and stays fully detailed to race day
 * with week headers matching their day sums (coach-loop design D8). */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { validatePlanText } from "./plan-io.mjs";
import { planData } from "./plan-data.default.js";

const text = await readFile(new URL("./plan-data.default.js", import.meta.url), "utf8");
const res = await validatePlanText(text);
assert.equal(res.ok, true, `seed must validate: ${res.error}`);
assert.equal(res.weeks, planData.block.length);

const raceDate = planData.race.date;
for (const w of planData.block) {
  assert.ok(Array.isArray(w.days) && w.days.length === 7,
    `${w.wk} must ship fully detailed (days:null is a plan-integrity gap)`);
  const sum = w.days.reduce((a, d) => a + (d.date === raceDate ? 0 : d.km), 0);
  assert.ok(Math.abs(sum - w.km) <= 0.5,
    `${w.wk}: header says ${w.km} km but its days sum to ${sum}`);
}
console.log(`ok default plan — validates, ${planData.block.length} weeks fully detailed, headers match day sums`);
console.log("ALL PASS");
