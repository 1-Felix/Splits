## 1. Restructure the plan data model

- [x] 1.1 In `plan-data.default.js` (the shipped seed), fold the plan into a single `block` list where each week carries an optional `days` array; set `days: null` for weeks not yet detailed. Remove `weekPlan` / `nextWeekPlan` as authored data.
- [x] 1.2 Enrich detailed day entries with first-class fields: `pace`, `zone`, `segments` (`{label, val, rest?}`), `extra`, `fuel`. Keep the prose `detail` as a fallback. Ensure a minimal day (`{day,date,kind,title,load,km}`) still validates.
- [x] 1.3 Mirror the same restructure and enrichment into the live `plan-data.js` (at least the current and next week detailed; enrich Friday's threshold session as the reference example).

## 2. Merge and coach-read compatibility

- [x] 2.1 In `running-data.js`, derive a flattened `athleteData.weekPlan = block.flatMap(w => w.days || [])` back-compat alias. (Which week is "current" is a live-clock question, so the dashboard derives the active week itself from block dates rather than exposing a static current-week field.)
- [x] 2.2 Confirm `coach-read.js`'s `weekPlan.find(w => w.date === run.date && w.kind === 'run')` still resolves against the flattened alias, including runs from a past week. (Verified by a new test in `test_coach_read.mjs`.)

## 3. Standalone demo fallback

- [x] 3.1 Update the baked-in `buildData()` fallback in `Running Dashboard.dc.html` to the new `block[i].days` shape (Wk 2 current + Wk 3 detailed, the rest `days: null`) so the component still renders with no live data.

## 4. Workout detail view (Feature 1)

- [x] 4.1 Add `state.expandedDay` and a `toggleDay(id)` method mirroring `expandedRun` / `toggleRun`; id keyed by week index + day (e.g. `"2:Fri"`). Collapse any open day when the selected week changes (`selectWeek`/`clearWeek` reset `expandedDay`).
- [x] 4.2 Make each "THIS WEEK" day card an expandable control: `role="button"`, `tabIndex`, `aria-expanded`, keyboard (Enter/Space) activation, and a chevron affordance.
- [x] 4.3 Render a pace chip (pace + zone when present) on the collapsed card; omit it for days with no `pace` (e.g. strength).
- [x] 4.4 Render the expanded structured detail for run days: target pace (chip), target zone, and segments (warm-up / reps with rest / cool-down), plus `extra` and `fuel` when present.
- [x] 4.5 Render the expanded detail for non-run days as title + descriptive detail (`noteRow`), with no pace/segment breakdown.

## 5. Week selector (Feature 2)

- [x] 5.1 Add `state.selectedWeek` (block index or `null`); compute `currentWeekIndex` from `mon/sun` vs `displayToday` and derive `activeWeekIndex = selectedWeek ?? currentWeekIndex`.
- [x] 5.2 Render the "THIS WEEK" grid from `block[activeWeekIndex].days`; recompute the panel's derived meta (km total, run/strength/spin counts) for the active week instead of hard-coded counts.
- [x] 5.3 Make "ROAD TO SONTHOFEN" week cards activatable (`role="button"`, `tabIndex`, `aria-pressed`, keyboard) to set `selectedWeek` to that index.
- [x] 5.4 Give the current week and the selected/active week distinct visual states in the block panel (current = filled panel + "THIS WK"; selected-other = accent ring + "VIEWING").
- [x] 5.5 Show the active week's label in the "THIS WEEK" header and a "back to current" control whenever `selectedWeek` is set and differs from `currentWeekIndex`; activating it resets `selectedWeek` to `null`.

## 6. Placeholder for un-detailed weeks

- [x] 6.1 When `block[activeWeekIndex].days` is `null`, replace the day grid with a placeholder built from that week's `km` / `long` / `focus` summary, communicating that the detailed sessions are authored closer to the week.

## 7. Styling

- [x] 7.1 Add `dashboard.css` styles for the pace chip, the selected-week ring/state, the expanded-detail segment layout, and the summary placeholder; convert the mobile `.day--wk` agenda reflow from positional to class-based selectors so the added chip/chevron/expand don't shift it.

## 8. Tests and verification

- [x] 8.1 Update `validate_data.py` for the new `block[i].days` model and the flattened `weekPlan` alias; add a `test_coach_read.mjs` case proving a past-week run resolves against the flattened alias. (`test_run_detail.py` covers `sync_garmin.py` telemetry helpers only — untouched by the plan-shape change — and still passes.)
- [x] 8.2 Ran the full suite (coach-read, validate_data, run-detail — all pass) and drove the dashboard with Playwright: pace chip visible collapsed, expanding a workout shows pace + segments, selecting detailed/un-detailed block weeks retargets THIS WEEK (cards vs placeholder), and "back to current" restores the live week. No new console errors (the only console noise is pre-existing SVG placeholder-template warnings in the unmodified charts).
