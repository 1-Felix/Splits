# Tasks: chart-engine

## 1. Prerequisites

- [x] 1.1 `vendor-runtime` is landed — the vendoring policy and `test_offline.mjs`'s origin block are what keep `d3-lite.js` from becoming a CDN reference
- [x] 1.2 Capture a "before" screenshot of the cockpit and `/progress` at the current commit, for the retrofit diff

## 2. Vendor d3 (design D1)

- [x] 2.1 `vendor/entry.js` re-exporting exactly the symbols in use: `scaleLinear`, `scaleUtc`, `scaleBand`, `scalePoint`, `line`, `area`, `curveMonotoneX`, `curveStepAfter`, `extent`, `bisector`, `quantile`, `ticks`, `max`, `min`, `mean`, `group`, `rollup`, `timeFormat`, `utcFormat`
- [x] 2.2 Build `vendor/d3-lite.js` (`esbuild entry.js --bundle --format=esm --minify`); check in the artifact; record the exact command, the four source versions, and the measured size in `vendor/README.md`
- [x] 2.3 Test: every symbol `chart-core.js` imports is exported by the bundle, so a stale artifact fails at test time rather than at runtime

## 3. `chart-core.js` — pure geometry and policy (designs D3, D4, D6)

- [x] 3.1 `resolveDomain(values, policy)`: nice-extent → forced inclusions → minimum-span expansion about the midpoint → zero-anchor; returns ticks with formatted labels
- [x] 3.2 The policy table from design D3, one exported constant per chart, so the twelve arguments live together and can be changed together
- [x] 3.3 `segmentNulls(points)`: contiguous runs only — a line SHALL never bridge a null month
- [x] 3.4 `bandFromSeries(values, window)`: rolling median plus IQR ribbon; asymmetric windows at the series edges, never extrapolated
- [x] 3.5 `confidenceRadius(weight, policy)`: sqrt scale clamped to [1.5, 4.5] px; below-floor points marked hollow and excluded from the path
- [x] 3.6 `placeAnnotations(anns, xScale, width)`: lane assignment so overlapping flags never collide; deterministic ordering
- [x] 3.7 `buildSpec(descriptor) → ChartSpec` per design D6; consumes `chart-hover.js`'s `bandRects`/`cardPlace` unchanged
- [x] 3.8 `test_chart_core.mjs`: minimum-span expansion (a 3.6-point VO₂ range yields a ≥ 5.0 domain), zero-anchoring, forced goal inclusion, nice ticks, null segmentation, band math at the edges, confidence radius monotonicity and clamping, annotation collision — all pure, no DOM

## 4. `chart-view.js` — spec to elements (design D2, D6)

- [x] 4.1 `renderChart(spec, React) → element`: frame, grid, axes with labelled ticks, band, line/bars/rule/dots layers, annotation flags, hover bands, crosshair, floating card
- [x] 4.2 Accessibility parity, not reinvention: preserve `role="img"`, the per-chart `aria-label`, arrow-key navigation, `Enter`/`Space` pinning, and focus-visible outlines exactly as they behave today
- [x] 4.3 A legend renders whenever a chart carries ≥ 2 series; a single-series chart has none (its title names it). Values, labels, and legend text wear ink tokens, never the series colour
- [x] 4.4 `test_chart_view.mjs`: render against a stub `React.createElement` that returns a plain tree; assert axis text nodes exist, gaps are separate paths, the legend appears only at ≥ 2 series, and the ARIA/keyboard props are wired. No React dependency in the test
- [x] 4.5 Load it from the logic classes the way `chart-hover.js` is already loaded — dynamic `import()` in `componentDidMount`, rendering a neutral placeholder until resolved

## 5. ★ The trajectory chart (cockpit) — the engine's first consumer

- [x] 5.1 Build it from `insights.trajectory` (49 weekly points of `riegelSec` / `garminSec`, plus `goalSec`): two lines, the goal rule, and the gap ribbon between the series
- [x] 5.2 Domain per D3 — nice, must include `goalSec`, minimum span 15 minutes; no area fill; x axis in ISO weeks with month labels
- [x] 5.3 Render nothing, with no layout breakage, when `insights.trajectory` is absent (the existing graceful-degradation requirement)
- [x] 5.4 Look at it. If it does not answer "is the gap closing?" in two seconds, the policy in D3 is wrong — fix the policy, not the chart

## 6. Palette: series colours are not status colours (design D5)

- [x] 6.1 `topbar.js`: `THEMES` gains `series1…series4`, distinct from `good`/`warn` and from `z1…z5`. Fix `track`, where `accent` and `warn` are both `#E8472B`
- [x] 6.2 Make `z1…z5` monotone in lightness rather than a rainbow; zones are ordinal
- [x] 6.3 Validate every theme with the palette validator (lightness band, chroma floor, adjacent-pair CVD separation, contrast) against that theme's own surface — light and dark. Fix any FAIL before proceeding; a contrast WARN obligates a visible label
- [x] 6.4 Test asserting no theme reuses a status token as a series token

## 7. Retrofit `/progress` (not race-critical — do this first)

- [x] 7.1 Split "Sleep & HRV" into two charts; HRV gains its personal baseline band (design D5)
- [x] 7.2 Port VO₂, avg pace, fitness & fatigue, cadence, efficiency, cadence-at-ref-pace, weekly volume, and year-over-year onto `buildSpec` + `renderChart`
- [x] 7.3 Weighted dots on the two `inBandMin` series; hollow below the floor
- [x] 7.4 Scope row (`6 mo` · `1 y` · `all` on monthly, `3 mo` · `6 mo` on weekly) re-deriving the domain over the tail; each subtitle states the true span; no chip offered where the series cannot honour it (design D7)
- [x] 7.5 Annotations: race day and `insights.recordsFeed` dates, on the charts where they mean something
- [x] 7.6 Delete the duplicated `line`/`hoverLayer`/`attachOverlay`/`monthLabel` helpers from `progress.dc.html`

## 8. Retrofit the cockpit (race-critical — do this last)

- [x] 8.1 Port the sleep chart, the heatmap, and the per-run drill-down sparklines
- [x] 8.2 Delete the duplicated geometry helpers from `Running Dashboard.dc.html`; `chart-hover.js` stays and is now reached through `chart-core.js`
- [x] 8.3 Re-run `test_offline.mjs` — the cockpit still renders with every third-party origin blocked
- [x] 8.4 Diff against the task 1.2 screenshots; every intentional change is in the D3 table, and nothing else moved

## 9. Guards and spec sync

- [x] 9.1 `tools/style-audit.mjs`: assert every trend chart carries y-axis tick labels and x-axis labels; assert a legend exists wherever ≥ 2 series render; assert no chart bridges a null
- [x] 9.2 Full suite green (`test_chart_core.mjs`, `test_chart_view.mjs`, `test_topbar.mjs`, `test_archive_api.mjs`, `test_offline.mjs`, style audit)
- [x] 9.3 Write `openspec/specs/chart-engine/spec.md` from the delta; update `live-dashboard` and `progress-views`
- [x] 9.4 `README.md`: the chart architecture (core → view → spec), the vendoring command, and the domain-policy table as the place to argue about how charts look
