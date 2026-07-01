/* plan-migrate.js — upgrade a legacy plan to the current block shape.
 *
 * Before the block carried a per-week `days` array, a plan-data.js stored the current and
 * next week as top-level `weekPlan` / `nextWeekPlan` and a `block` with only week summaries
 * (no `days`). A self-host data volume seeded with that older shape is NEVER overwritten on
 * image upgrade (the entrypoint only seeds when plan-data.js is absent), so the new dashboard
 * — which renders `block[i].days` — would show every week as "not detailed yet".
 *
 * This maps the legacy weekPlan/nextWeekPlan arrays onto their block weeks (by date when the
 * rows carry one, else by current/next-week position) so an old plan renders in place until
 * the coach re-authors it in the richer shape. Pure and dependency-free: running-data.js
 * applies it to whatever a volume holds, and it is unit-testable with Node. A plan already in
 * the new shape (any block week has `days`) is returned untouched. Mutates `data` in place. */

export function migrateLegacyPlan(data, todayISO) {
  const block = data && data.block;
  if (!Array.isArray(block) || block.length === 0) return data;
  if (block.some((w) => Array.isArray(w.days))) return data; // already the new (days) shape

  const today = todayISO || new Date().toISOString().slice(0, 10);
  let curIdx = block.findIndex((b) => b.mon && b.sun && today >= b.mon && today <= b.sun);
  if (curIdx < 0) curIdx = 0; // today outside the block → treat the first week as current

  // weekPlan → current week, nextWeekPlan → the week after, unless the rows carry dates that
  // pin them to a specific block week (the precise, common case for a dated plan).
  const targets = [ [data.weekPlan, curIdx], [data.nextWeekPlan, curIdx + 1] ];
  for (const [arr, fallbackIdx] of targets) {
    if (!Array.isArray(arr) || arr.length === 0) continue;
    let idx = fallbackIdx;
    const dated = arr.find((x) => x && x.date);
    if (dated) {
      const m = block.findIndex((b) => b.mon && b.sun && dated.date >= b.mon && dated.date <= b.sun);
      if (m >= 0) idx = m;
    }
    if (block[idx] && !Array.isArray(block[idx].days)) block[idx].days = arr;
  }
  return data;
}

export default migrateLegacyPlan;
