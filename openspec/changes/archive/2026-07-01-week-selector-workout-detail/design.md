## Context

The dashboard (`Running Dashboard.dc.html`) is a Claude Design component that renders
`athleteData`, produced by `running-data.js` merging coach-owned `plan-data.js` with
sync-owned `garmin-data.js`. Two planning panels are in scope:

- **THIS WEEK** — renders `D.weekPlan` (the current week's 7 days) as static cards.
- **ROAD TO SONTHOFEN** — renders `D.block` (7 summary rows: `wk, label, mon, sun, phase,
  km, long, focus`) as static cards; the current week auto-highlights by date.

Today the plan is spread across three shapes: `weekPlan` (current week days),
`nextWeekPlan` (next week days), and `block` (all 7 weeks, summary only). Only 2 of the
7 block weeks have a daily breakdown. Each day's `detail` is a single prose string, so
target pace is inconsistent and buried.

The component already has the interaction primitive both features need:
`state.expandedRun` + `toggleRun(id)` expand a completed run in place to a drill-down.
Live data loads at runtime via `import('./running-data.js')`, with a deterministic
`buildData()` fallback baked in so the component renders standalone.

## Goals / Non-Goals

**Goals:**
- Make each planned workout expandable to a structured detail (pace, zone, segments).
- Make target pace first-class and always visible, killing the "pace is confusing" issue.
- Let any "ROAD TO SONTHOFEN" week drive the "THIS WEEK" grid, with a fallback to the
  live current week.
- Consolidate the plan to a single source of truth: `block[i].days`.
- Degrade gracefully for weeks the coach has not detailed yet.

**Non-Goals:**
- Planned-vs-actual comparison (cross-referencing `recentRuns` by date). Deferred; the
  enriched model leaves room for it later.
- Auto-generating full daily sessions for un-detailed weeks (rejected — it would invent
  paces/days the coach never approved).
- A modal/drawer detail surface. Detail expands in place, consistent with `expandedRun`.
- Editing the plan from the UI. The coach still edits `plan-data.js`.

## Decisions

### D1 — Fold daily plans into the block; `block[i].days` is the single source of truth
`block` becomes the one plan list. Each week gains an optional `days` array (the same
day shape used by `weekPlan` today). Weeks without a detailed plan carry `days: null`.
`weekPlan` / `nextWeekPlan` are removed as authored data.

- **Why:** The ask is "click *any* training week." A single list makes every week
  addressable and removes the awkward triplet. It also gives the detail view (D2) one
  code path across all weeks.
- **Alternative (rejected):** Keep `weekPlan`/`nextWeekPlan`, make only Wk2/Wk3
  clickable. Ships faster but honors 2 of 7 weeks — reads as half-built.
- **Back-compat:** `running-data.js` derives a flattened `athleteData.weekPlan` =
  `block.flatMap(w => w.days || [])` so `coach-read.js`'s
  `weekPlan.find(w => w.date === run.date && w.kind === 'run')` keeps working, and
  past-week runs still match their planned day (they wouldn't if we only exposed the
  current week). We deliberately do NOT expose a static "current week" field from
  `running-data.js`: which week is current is a live-clock question, so the dashboard
  derives `currentWeekIndex` itself from the block `mon`/`sun` dates vs the live date.

### D2 — Enrich the day model; pace is a first-class field
Each day entry gains structured fields, keeping `detail` as a human-readable fallback:

```js
{ day:'Fri', date:'2026-07-03', kind:'run', title:'Threshold', load:'Hard', km:7,
  pace:'5:25–5:35', zone:'Z4',
  segments:[ {label:'Warm-up', val:'1.5 km easy'},
             {label:'Reps',    val:'4×1 km @ 5:25–5:35', rest:'60s jog'},
             {label:'Cool-down',val:'1.5 km easy'} ],
  extra:'7:00 a.m. spin · 1h · level 2', fuel:null,
  detail:'…existing prose…' }
```

- **Why:** Surfacing pace as its own field is the direct fix to the complaint. The render
  stays dumb; the coach's edits stay readable. `segments`/`extra`/`fuel` are optional, so
  a plain easy run degrades to just title + pace + km.
- **Alternative (rejected):** Regex-parse the prose at render time — brittle to any
  rephrasing, and still leaves pace formatting inconsistent.
- **Non-run days** (`strength`, `cross`) carry no `pace`/`segments`; the detail view shows
  title + `detail`/`extra` only.

### D3 — Pace chip on the collapsed card, full breakdown on expand
The collapsed day card surfaces `pace` (and `zone` when present) as a chip, so pace is
visible without interacting. Expanding reveals `segments`, `extra`, and `fuel`.

- **Why:** "The pace is not mentioned" is fixed even for users who never expand a card.
- **Fallback:** If a day has no `pace`, the chip is omitted (e.g. strength days).

### D4 — Week selection via `state.selectedWeek`, fallback to live current week
Add `state.selectedWeek` (a block index, or `null` = follow the live clock). Compute
`currentWeekIndex` from `mon/sun` vs `displayToday` (logic already exists for the block
highlight). `activeWeekIndex = state.selectedWeek ?? currentWeekIndex`. The "THIS WEEK"
grid renders `block[activeWeekIndex].days`.

- Clicking a "ROAD TO SONTHOFEN" card sets `selectedWeek` to that index.
- The panel header names the active week and shows a "back to current" control whenever
  `selectedWeek` is set and differs from `currentWeekIndex`; it resets `selectedWeek` to
  `null`.
- Visual language: the **current** week keeps its existing "THIS WK" highlight; the
  **selected/active** week gets a distinct ring/`aria-pressed` state so "current" and
  "being viewed" are never confused.
- Block cards become buttons: `role`, `tabIndex`, `aria-pressed`, keyboard activation —
  matching the accessibility already applied to the runs rows.

### D5 — Graceful placeholder for `days: null`
When the active week has no `days`, the grid is replaced by a placeholder built from the
week's summary (`km`, `long`, `focus`): e.g. "Not detailed yet — the coach writes each
week's sessions as it approaches. Shape: 35 km · long run 18 km · Threshold reps."

- **Why:** Just-in-time authoring ("roll the next week in each Monday") is the existing
  workflow; the UI should state that, not show an empty grid.

### D6 — `expandedDay` mirrors `expandedRun`
Add `state.expandedDay` + `toggleDay(id)` (id = week index + day, e.g. `"2:Fri"`).
Reuse the existing expand/collapse visual pattern. Selecting a different week collapses
any open day.

## Risks / Trade-offs

- **[BREAKING plan-data shape ripples to multiple files]** → Update `plan-data.js`,
  `plan-data.default.js` (the shipped seed the entrypoint copies on first boot), and the
  standalone `buildData()` demo in the same change; keep the flattened `weekPlan` alias so
  `coach-read.js` is untouched behaviorally. Migration Plan below sequences this.
- **[The baked-in demo silently diverges]** → It uses the old `weekPlan`/`block` shape
  (lines ~628–655). If not updated it will crash the standalone render. Update it to the
  new shape (at least one week with `days`, the rest `null`) so the component still renders
  with no live data.
- **[Tests assert the old shape]** → `test_run_detail.py`, `validate_data.py`,
  `test_coach_read.mjs` may reference `weekPlan`. Update assertions to the flattened alias
  / new structure.
- **[Selected ≠ current confusion]** → Distinct visual states (D4) and an always-present
  "back to current" affordance when viewing a non-current week.
- **[Coach editing burden]** → Enriched fields are all optional; a minimal day is still
  `{day,date,kind,title,load,km}`. Only quality sessions need `segments`.

## Migration Plan

1. Restructure `plan-data.default.js` (seed) to `block[i].days` with enriched day fields;
   set `days: null` on weeks not yet detailed. Mirror into the live `plan-data.js`.
2. Update `running-data.js` to expose the flattened `weekPlan` alias; confirm
   `coach-read.js` lookups still resolve (the dashboard derives the current week from
   block dates on the live clock — no static current-week field is exposed).
3. Update `buildData()` fallback in the `.dc.html` to the new shape.
4. Implement render + state (D2–D6) in the `.dc.html`; add styles in `dashboard.css`.
5. Update tests to the new structure; run `validate_data.py`, `test_coach_read.mjs`,
   `test_run_detail.py`.

Rollback: the change is confined to plan data + dashboard render; reverting the commit
restores the previous static panels. No data migration of synced telemetry is involved.

## Open Questions

- None blocking. Deferred: planned-vs-actual overlay (Non-Goal) — revisit once the
  enriched model is in use.
