# Proposal: chart-engine

## Why

Every chart in SPLITS is produced by one function — `line(vals, h, opt)`,
duplicated verbatim in `Running Dashboard.dc.html` and `progress.dc.html`
(*"chart geometry helpers (same implementations as the cockpit)"*). It returns a
path string, an area fill, and three gridlines at **fixed pixel offsets**. That
is a sparkline generator, and twelve analytical charts are built on it.

Three consequences, all visible in the shipped product:

1. **No chart has a scale.** Not one y-axis tick label exists on either page; the
   only `<text>` in any chart is the month row under the year-over-year bars.
   A value cannot be read without hovering.

2. **Every chart is drawn at "fill the frame" zoom**, because the domain is
   always `[min(values), max(values)]` padded 14%. Against the real telemetry:

   | series | true spread | rendered as |
   |---|---|---|
   | VO₂ max | 3.6 points over 30 months | the full card height |
   | cadence | 46 spm | the full card height |
   | avg pace | 196 s/km | the full card height |

   The VO₂ card's own header reads `+0.3` while its line sweeps corner to
   corner. The header and the chart disagree about how big the news is, and
   without an axis the reader cannot adjudicate. Noise is rendered as signal,
   systematically.

3. **Nothing is drawn against a reference.** No baseline band, no rolling
   median, no target line except the pace goal — which is, not coincidentally,
   the most legible chart in the product.

Meanwhile `insights.trajectory` — 49 weeks of demonstrated-half vs
model-predicted-half against the 1:59:59 goal, the series the ROADMAP calls
*"the highest-motivation insight per unit of work"* — renders as the text string
`closing ≈131s/wk`. The most important measurement in the product has no chart.

And `insights.efficiency.monthly` carries `inBandMin` per point: the number of
minutes of in-band running behind each monthly value, ranging from 21 to 338
across the real series. A 5× difference in confidence, drawn as identical dots.

## What Changes

- **`vendor/d3-lite.js`** — `d3-scale`, `d3-shape`, `d3-array`, `d3-time-format`
  bundled to one ESM file by a documented `esbuild` one-liner, with
  `vendor/entry.js` declaring the exact symbol surface. Measured: **46 KB
  minified, 16.5 KB gzipped.** Vendored under the policy `vendor-runtime`
  establishes; no bundler enters the build, no CDN enters the page.

- **`chart-core.js`** — a pure, DOM-free module beside the existing
  `chart-hover.js`, unit-tested the same way. It owns **domain policy** (the fix
  for point 2 above, which d3 will not choose for you), tick selection, honest
  null-segmentation, rolling-median/IQR baseline bands, confidence weighting,
  and annotation placement. Its output is a `ChartSpec`.

- **`chart-view.js`** — a plain-JS React renderer, `renderChart(spec) → element`.
  It mounts through the dc-runtime's template interpolation, which passes React
  elements straight through (`walkText`: `if (React.isValidElement(v) …) return
  h(Fragment, …)`). A chart's template collapses from ~10 lines of hand-written
  SVG to `{{ vo2.chart }}`. No JSX, no Babel, no build step.

- **Every chart gains a scale and a reference.** Labelled y ticks, labelled x
  ticks, a domain policy per metric (minimum spans, zero-anchoring, goal
  inclusion), and a baseline band or target line wherever one is meaningful.

- **★ The trajectory chart lands on the cockpit** — two series, the goal line,
  and the gap ribbon between them. It is built entirely from
  `insights.trajectory`, already present in `garmin-data.js`, and it is the
  engine's first consumer: if the trajectory chart is ugly, the engine is wrong.

- **Confidence is drawn.** Monthly efficiency and cadence points size their dots
  by `inBandMin`; points below a floor render hollow. Garmin does not do this.
  The ROADMAP's word for what these charts should be is *honest*.

- **Range controls where the data supports them** — a scope row (`6 mo` · `1 y` ·
  `all` on monthly series, `3 mo` · `6 mo` on weekly) that re-derives the domain
  over the selected tail, so a deviation invisible across 30 months resolves
  across 6. Each chart states its true span; a chip is not offered where the
  underlying series cannot honour it.

- **Two chart-discipline defects are corrected.** "Sleep & HRV" is a dual-axis
  chart (hours as bars, milliseconds as a line, one canvas, no axis on either)
  and **splits into two charts**, HRV gaining its personal baseline band. And the
  themes conflate series colour with status colour — in `track`, `accent` and
  `warn` are both `#E8472B`; in `volt`, `accent` is also HR zone 3 and `good` is
  also zone 2. Series tokens are separated from status tokens and the palette is
  validated rather than eyeballed.

Out of scope, and named: **annotations that need new sync-derived data** (block
phases) — only race day and the existing `recordsFeed` dates are drawn here;
**denser static history** for wider range chips (a follow-up, `history-depth`);
the **continuous multi-track crosshair**, which is a different primitive from
`bandRects` and belongs to `run-detail`.

This change touches no Python, adds no sync step, and requires no schema
migration. It is client-side, reversible, and additive to the cockpit.

## Capabilities

### New Capabilities

- `chart-engine`: the vendored plotting primitives, `chart-core.js` (domain
  policy, ticks, bands, confidence, null segmentation, annotation placement) and
  `chart-view.js` (spec → React element via template interpolation) — including
  the accessibility contract every chart inherits and the palette rules that keep
  series colour distinct from status colour.

### Modified Capabilities

- `live-dashboard`: charts render with labelled axes against a domain policy and
  a reference layer, replacing the auto-scaled sparklines; the cockpit gains the
  race-trajectory chart; monthly trend points encode sample-size confidence;
  charts degrade unchanged when their data is absent.
- `progress-views`: the relocated long-game charts render through the engine and
  gain scope controls; "Sleep & HRV" becomes two charts.

## Impact

- **Code:** new `vendor/entry.js` + `vendor/d3-lite.js`, new `chart-core.js`,
  new `chart-view.js`; `Running Dashboard.dc.html` and `progress.dc.html` lose
  their duplicated geometry helpers and their inline SVG; `topbar.js` (`THEMES`
  gains series tokens); `dashboard.css` (axis, band, annotation, scope-row
  styles). `chart-hover.js` is kept and consumed by `chart-core.js` — the band
  geometry is already right.
- **Tests:** new `test_chart_core.mjs` (domain policy per metric, minimum-span
  expansion, nice ticks, null segmentation, band math, confidence radius,
  annotation collision) and `test_chart_view.mjs` (render against a stub React,
  asserting structure, ARIA, and keyboard wiring — no react dependency in the
  test); palette validation over all three themes; `tools/style-audit.mjs`
  extended to assert every chart carries axis labels and a legend when it has
  ≥ 2 series.
- **Data:** none. `garmin-data.js` is read as-is; no sync, schema, or archive
  change.
- **Dependencies:** `d3-scale`, `d3-shape`, `d3-array`, `d3-time-format` enter as
  a checked-in vendored artifact, not as runtime `node_modules`. `serve.mjs`
  stays dependency-free.
- **Sequencing:** requires `vendor-runtime` (the vendoring policy and the
  origin-block test that keeps `d3-lite.js` honest). Race-week risk is contained
  by ordering: the engine and the new trajectory chart land first — additive, no
  regression surface — and the twelve existing charts are retrofitted one page at
  a time behind the style audit.
