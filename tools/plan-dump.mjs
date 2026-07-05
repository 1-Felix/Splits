/* tools/plan-dump.mjs — import the plan file given as argv[2] and print its
 * `planData` export as JSON on stdout. The bridge that lets the Python sync
 * read the coach-owned ES-module plan (coach-loop design D1).
 *
 * Exit 0 = JSON on stdout; exit 2 = reason on stderr. The CALLER supplies the
 * safety: plan_compliance.load_plan() runs this in a child with a kill-timeout
 * and a minimal env allow-list, so a throwing / looping / secret-hungry plan
 * is contained the same way plan-io.mjs contains a pushed plan. */

import { pathToFileURL } from "node:url";

const file = process.argv[2];
if (!file) {
  process.stderr.write("usage: node tools/plan-dump.mjs <plan-file>");
  process.exit(2);
}

try {
  const m = await import(pathToFileURL(file).href);
  const pd = m.planData;
  if (pd === undefined)
    throw new Error("missing a named 'export const planData'");
  process.stdout.write(JSON.stringify(pd));
} catch (e) {
  process.stderr.write(String((e && e.message) || e));
  process.exit(2);
}
