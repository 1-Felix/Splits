## Why

The dashboard's two planning panels are static and under-informative. "THIS WEEK"
only ever shows the current week, and each workout is a single dense prose string
where the target pace is inconsistent and buried (a `/km` number on one day, a bare
zone on another, mid-sentence between a spin and a cooldown on a third) — so the pace
is effectively missing and confusing. "ROAD TO SONTHOFEN" shows all seven weeks but
none of them are clickable, so there is no way to look ahead at a future week's plan.

## What Changes

- **Workout detail on click.** Each day card in "THIS WEEK" becomes expandable in
  place (reusing the existing `expandedRun`/`toggleRun` pattern from Recent activities).
  Expanding a run shows a structured breakdown — target pace, target zone, and the
  warm-up / reps / cool-down segments — instead of one prose line.
- **Pace becomes first-class.** The target pace is surfaced as its own field (a pace
  chip on the collapsed card and in the expanded detail), so it is always visible and
  consistently formatted — directly fixing "the pace is not mentioned and is confusing."
- **Enriched plan data model.** Day entries in `plan-data.js` gain structured fields
  (`pace`, `zone`, `segments`, `extra`, `fuel`) alongside the existing prose `detail`,
  which is kept as a fallback/summary. **BREAKING** to the plan-data shape (see Impact).
- **Week selector.** Clicking a week card in "ROAD TO SONTHOFEN" retargets the "THIS
  WEEK" grid to that week's daily plan. A "back to current" affordance falls back to the
  live current week, and the selected week is visually distinguished from the current week.
- **Days folded into the block.** The `weekPlan` + `nextWeekPlan` + `block` triplet is
  consolidated so each block week optionally carries its own `days` array (single source
  of truth). Weeks the coach has not detailed yet (`days: null`) show a graceful summary
  placeholder ("detail lands Monday") built from the week's km / long-run / focus summary,
  rather than an empty grid.

## Capabilities

### New Capabilities
<!-- none — both features extend existing live-dashboard behavior -->

### Modified Capabilities
- `live-dashboard`: adds requirements for an expandable, structured workout detail view
  with first-class target pace; and for selecting a training-block week to drive the
  "THIS WEEK" view with a fallback to the live current week, including a placeholder for
  weeks without a detailed daily plan.

## Impact

- **Plan data (BREAKING shape change):** `plan-data.js` and the shipped seed
  `plan-data.default.js` restructure to `block[i].days` with enriched day fields;
  `weekPlan` / `nextWeekPlan` are removed or retained only as computed back-compat aliases.
- **Merge + coach read:** `running-data.js` / `coach-read.js` currently look up the plan
  via `weekPlan.find(date === run.date)`; this must resolve against the flattened
  `block[*].days` so past-week runs still match their planned day.
- **Dashboard render (`Running Dashboard.dc.html`):** new `selectedWeek` and `expandedDay`
  state; the "THIS WEEK" and "ROAD TO SONTHOFEN" render blocks; a new structured-detail
  template; and the baked-in standalone `buildData()` demo, which still uses the old
  `weekPlan` / `block` shape and must be updated or kept back-compatible.
- **Styling (`dashboard.css`):** pace chip, selected-week ring, and summary-placeholder styles.
- **Tests:** `test_run_detail.py`, `validate_data.py`, and `test_coach_read.mjs` may assert
  on the old `weekPlan` shape and need updating to the new structure.
