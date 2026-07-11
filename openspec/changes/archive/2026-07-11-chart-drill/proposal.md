# Chart Drill — from Aggregate Points to the Runs Behind Them

## Why

The dashboard's aggregate charts (monthly pace @ reference HR, cadence @
reference pace, year-over-year volume, the weekly race trajectory, the activity
heatmap) are conclusions without evidence: a point summarizes a month or week
of runs, but nothing on the page says *which* runs fed it or lets the viewer
reach them. The evidence already exists — `run_metrics` stores every run's
band aggregates, `/run/:id` and `/archive` are shipped — the summary layer
just doesn't connect to it. Closing that gap also explains the charts' honest
gaps and hollow dots ("February has six runs but none in band"), which today
read as mysteries.

## What Changes

- **Engine-level drill affordance**: a pinned chart reading (click / Enter —
  already shipped) gains a second activation step that drills into the point's
  evidence. Click the pinned card or press Enter again to drill; Escape walks
  back up (panel → pin → nothing). Provided by the chart engine as part of its
  interaction/a11y contract, so no chart can ship a mouse-only drill.
- **Honest contribution panel** for the pooled monthly charts (pace @ ref HR,
  cadence @ ref pace): an inline panel under the chart listing the month's
  runs split into **contributed** (in-band minutes, per-run in-band value,
  share of the pool) and **didn't count** (with the reason, e.g. "no time in
  band"), each row linking to `/run/:id`, plus an "open month in archive"
  link. Data is lazy-fetched from the archive API on drill — never before —
  and degrades to an honest offline state inside the panel.
- **Year-over-year bars** drill to the same panel without the exclusion
  section (volume counts every run), fed by the existing listing endpoint's
  date-range filter.
- **Race trajectory** weekly points carry their anchoring 10 km effort's
  activity id, so the pinned card names the anchor and links straight to that
  run — static data, no API involved.
- **Heatmap day cells** click through to that day's run (lazy lookup via the
  existing listing endpoint; a chooser when a day holds several runs).
- **New archive API endpoint** serving `run_metrics` rows verbatim over a
  bounded date range, joined with the activities' promoted columns — a window,
  no derivation, fail-soft like every archive endpoint.
- **Per-run display values** (in-band pace, in-band cadence) become stored
  `run_metrics` columns at a `METRICS_VERSION` bump (self-healing recompute),
  so the server keeps serving columns verbatim and derivation stays in Python.
- **Out of scope**: wellness charts (sleep, HRV) — their points are nightly
  readings, not run aggregates; drilling them is a different feature.

## Capabilities

### New Capabilities

- `chart-drill`: the cross-cutting drill contract — the pinned-reading drill
  affordance, the honest contribution panel (contributed/excluded split, row
  click-through, archive link), lazy fetching with honest degradation, and
  direct-link drills for single-run points.

### Modified Capabilities

- `insight-metrics`: `run_metrics` gains per-run in-band display columns at a
  `METRICS_VERSION` bump; trajectory weekly points carry their anchor's
  activity id; the new insight members are shape-checked like the rest.
- `archive-api`: a new read-only endpoint serves `run_metrics` rows verbatim
  over a bounded date range (same fail-soft, read-only, no-derivation,
  no-raw-payload contract as the existing endpoints).
- `chart-engine`: the interaction/a11y contract gains the drill affordance on
  pinned readings — declared per chart, rendered and keyboard-wired by the
  engine, inert for charts that declare none.
- `progress-views`: the monthly insight charts and the year-over-year bars
  drill to contribution panels; the static-first rule generalizes from "record
  click-throughs" to "drill-down interactions" as the only API-dependent ones.
- `live-dashboard`: the cockpit's trajectory card links to its anchor run and
  heatmap day cells click through to their runs, while the cockpit's render
  remains complete without any API.

## Impact

- **Python sync**: `insight_metrics.py` (new per-run columns, version bump,
  trajectory anchor id), `activity_archive.py` (`run_metrics` schema/upsert),
  `validate_data.py` (shape checks); `test_insight_metrics.py`,
  `test_wellness.py` untouched.
- **Server**: `serve.mjs` gains the run-metrics endpoint; `test_archive_api.mjs`
  grows coverage.
- **Chart engine**: `chart-core.js` (drill descriptor in the spec build),
  `chart-view.js` (card affordance + key handling); `test_chart_core.mjs`,
  `test_chart_view.mjs`.
- **Pages**: `progress.dc.html` (two contribution panels + YoY panel),
  `Running Dashboard.dc.html` (trajectory card link, heatmap click-through);
  Playwright page tests and the style audit.
- **Data contract**: additive `insights` members only; pre-change data files
  stay valid.
- **Not affected**: wellness archive and its charts, coach loop, plan sync,
  compare page, archive browser page (gains inbound links only).
