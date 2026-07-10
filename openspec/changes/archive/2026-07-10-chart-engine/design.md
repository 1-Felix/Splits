# Design: chart-engine

## Context

Twelve charts, one primitive. `line(vals, h, opt)` is defined twice — once in
each `.dc.html`, the second copy annotated *"same implementations as the
cockpit"* — and returns:

```js
let mn = opt.min ?? Math.min(...all), mx = opt.max ?? Math.max(...all);
const r = (mx - mn) || 1, head = opt.headroom ?? 0.14;
mn -= r * head; mx += r * head;                       // ← the exaggeration
…
const grid = [padT, padT + (h - padT - padB) / 2, h - padB];   // ← three fixed pixels
return { d, area, grid, lastX, lastY, Y, pts };
```

The domain is always the data's own extent. The gridlines are decoration at
pixels 14, 76, and 138. There are no tick labels anywhere.

Around that sits genuinely good work: `chart-hover.js` is 41 lines of pure,
unit-tested geometry (`bandRects`, `cardPlace`), and every chart already carries
`role="img"`, an `aria-label`, arrow-key navigation, and click-to-pin. **The
interaction layer is not the problem and must not be rebuilt.**

The dc-runtime (`support.js`, generated, unmodifiable) compiles each `.dc.html`
template against a logic class. Three mount points exist for reusable rendering;
their mechanics were traced before this design (see D2).

Constraints: race Aug 9 — the cockpit must stay boring; no bundler; `serve.mjs`
stays dependency-free; all *derivation* lives in the deterministic Python sync,
so anything this change computes must be **presentation**, not new truth.

## Goals / Non-Goals

**Goals**

- A chart reads at a glance: a labelled scale, a reference to compare against,
  and a headline that agrees with the geometry.
- One place to change how all charts look.
- The trajectory chart exists.
- Confidence and null-ness are drawn, not hidden.

**Non-Goals**

- New metrics. Nothing here computes a training truth; `insight_metrics.py`
  remains the only place that does.
- The multi-track run view (`run-detail` owns it; it needs a continuous
  crosshair, not `bandRects`).
- Wider history than `garmin-data.js` already ships (`history-depth` follows).
- Rebuilding hover, keyboard nav, or pinning.

## Decisions

### D1 — Vendor d3 primitives; own the policy

`d3-scale` + `d3-shape` + `d3-array` + `d3-time-format`, bundled by esbuild into
one ESM file. Measured, not estimated: **46,148 bytes minified, 16,504 gzipped**,
verified working:

```
scaleLinear().domain([43.6, 47.2]).nice()  →  [43.5, 47.5]  ticks [44,45,46,47]
scaleLinear().domain([406, 602]).nice()    →  [400, 620]    ticks [400,450,500,550,600]
```

`vendor/entry.js` declares the surface; adding a symbol means editing it and
re-running the documented command. That keeps the dependency visible.

*Rejected:* Recharts / Nivo / visx — no bundler here, and their UMD builds die
on the dc-runtime's `x-import` shim, which passes `require = () => ({})`, so a
UMD taking its CommonJS branch resolves `require('react')` to `{}`. Canvas
libraries (uPlot, ECharts) would cost CSS-variable theming across three themes,
the SVG accessibility already shipped, and print — to buy performance at a scale
(≤ 730 points) that does not exist here. Observable Plot owns the DOM.

**The critical caveat.** `nice()` produces *labels*, not *honesty*. A 3.6-point
VO₂ range still fills the frame, now with ticks confirming it. d3 has no opinion
about domain policy. That opinion is D3, and it is the actual fix for the
complaint that started this change.

### D2 — Mount through template interpolation, not `dc-import`

The dc-runtime's `walkText` ends with:

```js
if (getReact().isValidElement(v) || Array.isArray(v)) {
  return h(getReact().Fragment, { key: i }, v);
}
```

**`{{ expr }}` renders React elements.** So the logic class builds a chart as an
element tree and the template says `{{ vo2.chart }}`. `chart-view.js` is a plain
ESM module loaded exactly as `chart-hover.js` already is
(`import('./chart-hover.js')` in `componentDidMount`, with a graceful
not-yet-loaded state).

*Rejected:* `<dc-import name="Chart"/>` resolves via `fetch("./Chart.dc.html")`
(`COMPONENT_DIR = "."`), and `parseDcDocument` calls `querySelector("x-dc")` —
singular — so components are one-per-file and cannot be declared in-file. It
would add a per-page fetch and a second template language for no gain.
`<x-import from="./chart.js"/>` works but routes through the same fetch plus the
`require` shim, and `.jsx` would pull `@babel/standalone` from a CDN.

### D3 — Domain policy: the core decision

`resolveDomain(values, policy)` applies, in order: nice-extent → forced
inclusions → **minimum span** → zero-anchor. Minimum span is the anti-
exaggeration rule: if the nice domain is narrower than the metric's meaningful
span, expand it symmetrically about the midpoint. A `+0.3` VO₂ month then *looks*
like `+0.3`.

| Chart | Domain rule | Reference layer | Marks |
|---|---|---|---|
| **Trajectory** (cockpit) | nice; must include `goalSec`; min span 15 min | goal line; ribbon between Riegel and Garmin | 2 lines |
| VO₂ max | nice; **min span 5.0 pts** | 12-mo rolling median band | line |
| Avg run pace | nice; must include goal pace; min span 60 s/km | goal line | line |
| Cadence | nice; min span 20 spm | rolling median band | line |
| Weekly volume | **zero-based**; nice max | 4-wk rolling mean line | bars |
| Fitness & fatigue | shared domain, zero-based | — | 2 lines + legend |
| Sleep hours | zero-based, 0–10 h | 7–9 h target band | bars |
| HRV *(split out)* | nice; min span 20 ms | personal baseline band | line |
| Efficiency (pace @ HR band) | nice; min span 60 s/km | rolling median band | line + weighted dots |
| Cadence @ ref pace | nice; min span 10 spm | rolling median band | line + weighted dots |
| Year-over-year volume | zero-based, **shared across years** | — | grouped bars |
| Heatmap | sequential single-hue ramp | — | cells |

Two corollaries.

**Area fills encode magnitude only.** Volume and load may be filled. Pace,
cadence, VO₂, HRV, and predicted time are rates or levels — the area beneath
them is not a quantity of anything. Today `pace.area` fills under a curve where
higher means slower, so a bad month renders as a *large* lime shape: more ink,
worse news. The fills come off; the lines stay.

**Axes are not inverted.** It is tempting to flip pace and predicted time so
"up is better," but runners read a descending pace curve correctly and the goal
line sits naturally beneath it. Consistency is bought instead by removing the
fill (above) and by labelling the axis direction (`faster ↓`).

### D4 — Draw the reference, draw the confidence

`bandFromSeries(values, window)` returns rolling median with an IQR ribbon. This
is presentation over data already shipped, not a new metric — it computes nothing
that `insight_metrics.py` would need to version.

`insights.efficiency.monthly[].inBandMin` ranges 21…338 across the real series.
`confidenceRadius(weight)` maps it through a sqrt scale clamped to [1.5, 4.5] px;
points beneath the floor render hollow and are excluded from the path. Null
months remain gaps — `segmentNulls()` splits the series into contiguous runs so a
gap can never be bridged by a line, which the current implementation only
achieves by accident.

### D5 — Split "Sleep & HRV"; separate series colour from status colour

Sleep hours (bars) and HRV milliseconds (line) currently share one 600×150
canvas with no axis on either. Two incommensurable scales in one frame
manufacture a correlation. They become two charts; HRV gains the baseline band
that makes it readable at all.

The themes conflate roles. In `track`, `accent` and `warn` are the same hex
(`#E8472B`) — the primary series colour *is* the warning colour. In `volt`,
`accent` (`#C7F646`) is also HR zone 3 and `good` (`#34D399`) is also zone 2.
`THEMES` gains `series1…series4`, distinct from `good`/`warn` and from `z1…z5`,
and the zone ramp becomes monotone in lightness rather than a rainbow (`z2` green
and `z3` lime collapse under deuteranopia). The result is **validated by script,
not by eye**, for all three themes against their own surfaces.

### D6 — The `ChartSpec` contract

The seam `run-detail` will build against. `chart-core.js` is pure and knows
nothing of React; `chart-view.js` is the only file that touches elements.

```js
// chart-core.js — no DOM, no React, testable in node
resolveDomain(values, policy)     → { min, max, ticks: [{ v, label }] }
segmentNulls(points)              → [[p,…], [p,…]]        // honest gaps
bandFromSeries(values, window)    → { mid[], lower[], upper[] }
confidenceRadius(weight, policy)  → px
placeAnnotations(anns, xScale, w) → [{ x, label, lane }]  // collision-avoided
buildSpec(descriptor)             → ChartSpec

// ChartSpec
{ frame:{w,h,pad}, x:{ticks,label}, y:{ticks,label},
  layers:[ {kind:'band'|'line'|'bars'|'rule'|'dots'|'annotation', …} ],
  hover:{ bands, points },                       // from chart-hover.js, unchanged
  a11y:{ role:'img', label, keyboard } }

// chart-view.js
renderChart(spec, React) → React element
```

`chart-hover.js` keeps `bandRects` and `cardPlace` and is consumed by
`chart-core.js`. It is not rewritten.

### D7 — Scope controls only where the data can honour them

`garmin-data.js` ships 30 monthly points, 26 weekly, 49 trajectory weeks, 365
heatmap days, 14 sleep nights. So `6 mo · 1 y · all` is real on monthly series
and `3 mo · 6 mo` on weekly; nothing is offered on the 14-night sleep series. A
chip re-derives the domain over the selected tail — which is exactly how a
deviation invisible across 30 months becomes visible across 6. Each chart states
its actual span in its subtitle, so a chip can never imply data that is not
there. Wider ranges wait for `history-depth`.

## Risks / Trade-offs

- **Retrofitting twelve charts is the whole risk.** Mitigated by ordering: the
  engine plus the *new* trajectory chart land first, where there is no
  regression surface. Then `/progress` (not race-critical). Then the cockpit's
  remaining charts. `tools/style-audit.mjs` guards each step.
- **The cockpit gains a section four weeks before the race.** The trajectory
  chart is additive and renders nothing when `insights.trajectory` is absent —
  the existing "insight surfaces degrade gracefully" requirement covers it.
- **Domain policy is a judgement call per metric.** The minimum spans in D3 are
  arguments, not physics. They are in the spec so they can be argued with, and
  in one table so they can be changed together.
- **A vendored d3 can drift from `entry.js`.** A test asserts every symbol
  `chart-core.js` imports is exported by the bundle, so a stale artifact fails
  loudly rather than at runtime.
- **`chart-view.js` under a stub React.** Testing structure against a fake
  `createElement` proves the tree, not the render. Interaction stays covered by
  the existing Playwright audit, which is where it belonged anyway.

## Open Questions

- **Should `bandFromSeries` window be per-metric or global?** A 12-month median
  suits VO₂; a 6-week median suits HRV. Currently modelled as part of the policy
  table; may want its own column once real data is on screen.
- **Does the trajectory chart show the Garmin prediction at all?** It is the
  less honest of the two series (the ROADMAP calls Riegel "demonstrated"). Drawn
  as a recessive second line for now; may become a hover-only readout.
