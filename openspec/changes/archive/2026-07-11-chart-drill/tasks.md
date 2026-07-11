# Tasks — chart-drill

## 1. Sync: per-run display columns + trajectory anchor

- [x] 1.1 Add `refhr_pace_s_per_km` and `refpace_cadence_spm` to the
      `run_metrics` schema and `upsert_run_metrics` in `activity_archive.py`
      (additive columns, NULL-able)
- [x] 1.2 Compute both in `insight_metrics.py` band extraction — NULL when the
      run has no in-band distance/time, never zero — and bump
      `METRICS_VERSION` so the self-heal recomputes every row
- [x] 1.3 Carry the anchoring effort's activity id through
      `weekly_trajectory`: emit `anchorId` on weeks with non-null `riegelSec`,
      omit it on null weeks
- [x] 1.4 Shape-check `anchorId` in `validate_data.py` (optional, numeric when
      present); pre-change data files must still pass
- [x] 1.5 Extend `test_insight_metrics.py`: per-run values consistent with
      stored aggregates, NULL honesty for out-of-band runs, version-bump
      self-heal, `anchorId` presence/absence per week, validation of a
      malformed `anchorId`
- [x] 1.6 Run a full sync against the local archive copy and verify coverage
      (verification mode reports all rows at the new version)

## 2. Archive API: run-metrics endpoint

- [x] 2.1 Add `GET /api/archive/run-metrics?from&to` to `serve.mjs`: running
      activities in range LEFT-JOINed with `run_metrics` columns, verbatim,
      newest-first; both params required; spans > 92 days rejected with 400;
      non-GET rejected; read-only per-request open; fail-soft 503; no raw
      payloads
- [x] 2.2 Extend `test_archive_api.mjs`: month range served with identity +
      metric fields, run without a metrics row appears with nulls, oversized
      span and missing params rejected, non-GET rejected, 503 when the
      database is absent, response fields byte-equal to stored columns

## 3. Chart engine: drill affordance on the pinned reading

- [x] 3.1 Thread a `drill` descriptor (per-point label + action) through
      `buildSpec` in `chart-core.js` — pure pass-through, no DOM; points whose
      descriptor yields no action carry none
- [x] 3.2 Render the affordance row on the pinned card in `chart-view.js`;
      wire card click and Enter-on-pinned to the action; Escape steps drilled
      → pinned → dismissed; accessible label announces the drill target
- [x] 3.3 Charts without a descriptor byte-identical in behavior: no
      affordance, Enter/Escape semantics unchanged
- [x] 3.4 Extend `test_chart_core.mjs` (descriptor pass-through, null-point
      inertness) and `test_chart_view.mjs` (affordance renders from
      declaration, key ladder, non-drill charts untouched)

## 4. Progress page: contribution panels

- [x] 4.1 Panel shell in `progress.dc.html`: full-width region beneath the
      chart, one open per page, focus into the panel heading on open and back
      to the chart (pin intact) on close, Escape closes
- [x] 4.2 Pooled panels for pace @ ref HR and cadence @ ref pace: lazy fetch
      `/api/archive/run-metrics` for the pinned month on drill (never
      before); header restates the plotted value from the static insights
      block; contributed rows with in-band minutes, per-run value, share;
      didn't-count rows behind a disclosure with reasons (no time in band /
      not yet analysed); rows link to `/run/<id>`; footer "open <year> in
      archive →" link
- [x] 4.3 YoY bars panel: same shell fed by the listing endpoint
      (`type=running&from&to` for the pinned month), all runs, no didn't-count
      section
- [x] 4.4 Offline honesty: 503/404/network failure renders the in-panel
      offline state with a working no-reload retry; chart and page stay fully
      usable
- [x] 4.5 Extend the progress Playwright test (`domcontentloaded` +
      `waitForFunction`, drill driven via keyboard): drill opens with correct
      rows and split, second panel closes the first, row navigates to
      `/run/<id>`, offline drill degrades in-panel and retries, no archive
      request before any drill (new dedicated `test_progress_page.mjs` — no
      progress-interaction Playwright test existed to extend)

## 5. Cockpit: trajectory anchor link + heatmap click-through

- [x] 5.1 Trajectory chart in `Running Dashboard.dc.html` declares a link
      drill from `anchorId` (static, no API): pinned week → "view anchor run
      →" → `/run/<anchorId>`; null weeks and pre-anchor data files declare
      nothing
- [x] 5.2 Heatmap day cells with km > 0 resolve on activation via the listing
      endpoint (`from=to=day&type=running`): one run navigates, several offer
      a minimal chooser, 503 shows an inline offline note; zero-km cells
      inert; no request before activation
- [x] 5.3 Extend the cockpit Playwright test: anchor link navigates without
      any API request, anchorless week inert, heatmap single-run navigation,
      multi-run chooser, offline note, cockpit renders complete with all
      `/api/*` routes failing (new dedicated `test_cockpit_page.mjs` — no
      cockpit-interaction Playwright test existed to extend)

## 6. Verification

- [x] 6.1 Register any new interactive surfaces with `tools/style-audit.mjs`
      and keep every page audit green
- [x] 6.2 Full test suite (Python + Node + Playwright) green; run
      `validate_data.py` against a freshly synced data file
- [x] 6.3 End-to-end walk on the built container: pin → drill → panel → run
      detail on /progress; trajectory anchor and heatmap click-through on the
      cockpit; offline states with the archive stopped
