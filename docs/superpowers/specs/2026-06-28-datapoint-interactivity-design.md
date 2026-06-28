# Universal Datapoint Interactivity — Design

**Date:** 2026-06-28
**Status:** Approved (design), pending implementation plan
**Branch:** `feat/splits-dashboard`

## Context & goal

Every chart on the SPLITS dashboard currently renders as a static SVG — a line,
a bar group, a heatmap, a ring. None of them tell you what an individual point
*is*. The goal: make **every line, every graph, every diagram surface the detail
behind each datapoint**. Hovering (desktop) or tapping (touch) a point reveals a
crosshair, a highlighted dot, and a small floating card — date/label, value, and
one line of context — for all nine visualisations.

This is the second dashboard interactivity upgrade, following the per-run
drill-down. Where the drill-down added depth to one table, this adds a single,
uniform inspection layer across the whole dashboard.

### Chosen approach (of three considered)

**Per-point hit-bands + JS hover/tap state (Approach A).** Each chart renders a
row of transparent `<rect>` "hit-bands" — one per datapoint — wired with
`onMouseEnter` (hover) and `onClick` (pin), the same declarative event pattern
the run-rows already use. A single `hover` state field drives a shared overlay
(crosshair + dot + card) rendered entirely in **viewBox units**.

Rejected alternatives:
- **One continuous `onMouseMove` + inverse-scale math** — fires per-pixel
  (hundreds of re-renders per sweep, needs throttling) and the
  screen→data coordinate math is brittle under the responsive `width:100%` /
  viewBox scaling. Worse fit.
- **Pure CSS `:hover` reveal** — zero JS, but cannot pin on tap (the chosen
  trigger needs it), SVG paint-order occludes tooltips, and pre-rendering all
  365 heatmap tooltips bloats the DOM.

Approach A matches the runtime's proven event model, keeps all geometry as pure
testable functions, satisfies hover **and** tap uniformly, and re-renders only on
band *crossings* (≤ ~30 per sweep), not per pixel.

### Runtime feasibility (verified)

- `support.js` converts any camelCase `on*` attribute to a React handler
  (`collectProps`, line 401) — so `onMouseEnter` / `onMouseLeave` / `onClick` /
  `onKeyDown` all bind, exactly as the run-row `onKeyDown` already does.
- All chart data is **static per render** — every datapoint's value and label is
  known at render time, so card content is fully precomputed and no live data
  flows during interaction.
- `support.js` is a generated runtime and is **not** edited; all work lives in
  `Running Dashboard.dc.html` plus one new pure JS module.

## Decisions locked during brainstorming

- **Trigger:** hover (desktop) **and** tap-to-pin (touch). Pure CSS is therefore
  out; a JS `hover` state is required.
- **Scope:** all **nine** surfaces — the six core line/bar charts, the heatmap,
  the readiness ring, and the drill-down sparklines (the ninth surface, rendered
  as two sub-charts, `splits` and `drift`).
- **Presentation:** crosshair + highlighted dot + floating card. Card shows
  date/label, the primary value, and one context line. (Rejected: "header
  repoint", which does not map to the ring or heatmap.)
- **Accessibility:** keyboard navigation is **in** — one tab stop per chart with
  arrow-key datapoint navigation (not deferred).

## Non-goals / scope

- **No backend / sync change.** This is presentation over already-synced,
  already-validated data. `sync_garmin.py`, `garmin-data.js`, `plan-data.js`,
  and `validate_data.py` are untouched. (Per-series date *anchors* in the sync
  were considered and rejected as unnecessary — see §4 Labels.)
- **No new chart types, range toggles, or plan-vs-actual overlays** — separate
  future upgrades.
- **`support.js` is not edited** — it is a generated runtime.

## 1 · State & interaction lifecycle

One new field on the component `state` (alongside `theme`, `data`, `expandedRun`):

```js
this.state.hover = null | { chart: <id>, i: <index>, pinned: <bool> }
```

- `chart` — a surface id: `'vo2' | 'pace' | 'fit' | 'cad' | 'vol' | 'sleep' |
  'heat' | 'ring' | 'splits' | 'drift'`.
- `i` — datapoint index within that chart.
- `pinned` — `false` for a transient hover, `true` for a tapped/clicked sticky
  point.

**Handlers** (methods on the component, wired into each band as closures, exactly
like the run-row `toggle`/`onKey`):

| Trigger | Handler | Behaviour |
|---|---|---|
| `onMouseEnter` band | `hoverPoint(chart, i)` | set `{chart, i, pinned:false}` — tooltip follows the pointer |
| `onMouseLeave` chart | `leaveChart(chart)` | if not pinned and same chart → clear |
| `onClick` / tap band | `pinPoint(chart, i, e)` | `e.stopPropagation()`; tap-same toggles off, else `{chart, i, pinned:true}` |
| `onClick` root container | `dismissHover(e)` | if `hover.pinned` → clear (the band's `stopPropagation` shields real taps) |
| theme switch / run toggle / data reload | (existing handlers) | also clear `hover` — no stale index |

Resulting behaviour:
- **Desktop** — the card tracks the pointer and vanishes on leave; an optional
  click pins one open (survives leave) until a click-away.
- **Touch** — a tap fires enter→click, net `pinned:true`; tapping the same point
  unpins; tapping elsewhere dismisses. Touch has no reliable `mouseleave`, so a
  pinned card correctly persists.

## 2 · Reusable mechanism

### 2a · Pure module — `chart-hover.js` (+ `test_chart_hover.mjs`)

Two data-agnostic, error-prone geometry functions are extracted and unit-tested,
mirroring the `coach-read.js` / `test_coach_read.mjs` precedent:

```js
// Hit-band spans: each band owns the territory nearest its point.
// Boundaries sit at midpoints between neighbours; first & last bands
// extend to the chart edges. n<=1 → one full-width band; n===0 → [].
export function bandRects(points, chartH, padX) -> [{ x, y:0, w, h:chartH }]

// Clamped top-left for the floating card. Flips above/below the point so it
// never spills past `bounds`; horizontal clamp keeps it within [0, bounds.w].
// Allows negative y (escape above) when bounds permit — used by sparklines.
export function cardBox(x, y, w, h, bounds) -> { x, y }
```

These two are the only pieces with tricky off-by-one / edge-overflow risk, so
they are the only ones extracted. Per-surface *content* stays in the dashboard,
which has the data and the existing formatters (`fmtPace`, `mDate`).

### 2b · Dashboard method — `hoverLayer(chartId, points)`

```js
// points: [{ x, y, lines:[{ t, em? }], dotColor? }]   // viewBox units
// returns:
//   bands:   [{ x, y, w, h, onEnter, onClick, ariaLabel }]   // transparent, always rendered
//   overlay: null | { crossX, dots:[{x,y,color}], card:{ x, y, w, h, rows } }
//            // present only when state.hover.chart === chartId (and i in range)
```

Each surface builds its `points` array and calls `hoverLayer`. The method:
- delegates band spans to `bandRects` and card placement to `cardBox`;
- wires each band's `onEnter`/`onClick` to `hoverPoint`/`pinPoint`;
- when this chart is the hovered one, assembles the overlay for `state.hover.i`.

`line()` gains one addition: it already computes the per-point vertices
internally — it will also **return `pts`** (the `[x,y]` array) so line charts can
place bands and dots without recomputing.

### 2c · Rendering

The template renders, per chart, in this paint order (SVG has no z-index):

1. the existing data shape(s) — path / bars / cells;
2. the transparent **bands** (`pointer-events:auto`);
3. the **overlay** (only if present): a crosshair `<line>`, the dot(s)
   `<circle>`, and the **card** — a `<g>` of a rounded `<rect>`
   (`fill var(--panel2)`, `stroke var(--line)`) plus `<text>` rows (value in
   `var(--ink)` weight-800, date/context in `var(--sub)`).

**The entire overlay group carries `pointer-events:none`** so moving onto the
card or crosshair never re-triggers enter/leave flicker; only the bands are
interactive.

The card lives in **viewBox units** throughout — positioning *and* edge-clamping
are exact and measurement-free (no `getBoundingClientRect`, no dependence on the
responsive pixel width). Card width is estimated from the longest row's character
count with generous padding — the single approximation, and a safe one.

## 3 · Per-surface points & card content

`line()`'s returned `pts` feeds the four line charts directly.

| Surface | id | Points (x, y) | Card rows (label · **value** · context) |
|---|---|---|---|
| VO₂ max | `vo2` | line vertices ×30 | `Mar 2025` · **VO₂ 46.3** · `+0.4 vs prev` |
| Pace | `pace` | line vertices ×30 | `Mar 2025` · **4:32 /km** · `+0:11 vs goal` |
| Fitness | `fit` | CTL vertices ×26 | `5 wks ago` · **CTL 41 / ATL 38** · `Form +3` |
| Cadence | `cad` | line vertices ×30 | `Mar 2025` · **161 spm** · `+3 vs prev` |
| Volume | `vol` | bar centre / top ×26 | `this week` · **31.0 km** · `+4 vs prev` |
| Sleep + HRV | `sleep` | night x ×14 | `2 nights ago` · **7.4 h** · `HRV 58 ms` |
| Heatmap | `heat` | existing cells ×365 | `Sat Mar 14` · **14.2 km** |
| Readiness ring | `ring` | one hit-circle | **Readiness 70 · Moderate** · `HRV 61 · RHR 53 · Sleep 6.7 h` |
| Splits spark | `splits` | binned km vertices | `km 7` · **4:52 /km** |
| Drift spark | `drift` | HR vertices | `seg 4` · **156 bpm** |

**Crosshair / dot per family:**
- **Line charts** — vertical crosshair at the vertex x + one dot at the vertex.
  `fit` adds a **second dot** on the ATL line at the same x (`dots` is an array).
- **Bars** (`vol`) — crosshair at the bar centre; the hovered bar brightens.
- **Sleep** — crosshair at the night x; both the bar and the HRV dot highlight.
- **Heatmap** — no crosshair; the hovered cell is outlined. Cells are already
  discrete rects, so `onMouseEnter`/`onClick` wire **directly onto the cells**
  (no separate bands). Card bounds are the heatmap's own `w × h`, not 600×150.
- **Ring** — no crosshair, no dot; a single invisible hit-circle over the ring
  shows only the breakdown card, sourced from `D.readiness`
  (`score`, `status`, `hrv`, `restingHR`, `sleepHours`).

**Sparkline exception (the one special case):** the two drill-down sparklines are
26 px tall (`viewBox 0 0 600 30`) — a multi-row card cannot fit inside. Fix: set
`overflow:visible` on those two `<svg>`s so the **same** SVG card escapes upward
into the detail-strip space, with `cardBox`'s up/down flip keeping it placed. The
crosshair + dot still fit inside the 26 px band, so the mechanism stays uniform —
one CSS property, no special-case card renderer.

## 4 · Labels (date/label per point)

Computed in the dashboard, exact where an anchor exists, derived otherwise — **no
stored anchors are added to the sync**:

- **Monthly** (`vo2`, `pace`, `cad`, ×30) — exact, from
  `history.vo2maxStartMonth` (`"2024-01"`) + index → `mDate`-style `MMM YYYY`.
- **Daily** (`heat`, ×365) — exact, already derived from `today` in the existing
  heatmap loop (`start = today − 364`).
- **Per-run** (`splits`, `drift`) — exact: km index (`km N`) / HR segment index.
- **Weekly** (`vol`, `fit`, ×26) and **nightly** (`sleep`, ×14) — **derived
  relative** labels counting back from the most-recent period (the last value is
  the current week / last night): `this week` / `N wks ago`, `last night` /
  `N nights ago`. These series carry no date anchor; relative labels are both
  sufficient and more readable than an inferred exact date.

## 5 · Edge cases & error handling

Presentation over already-validated data must **never sink the render**. The
overlay computation is fully guarded:

- **Index bounds** — `overlay` is `null` unless `state.hover.i` is within the
  chart's `points.length`; a pinned id whose chart no longer renders (e.g. a
  collapsed run's sparkline) simply shows nothing.
- **Stale hover** — cleared on theme switch, run toggle, and data reload.
- **Single / zero-point series** — `bandRects` returns one full-width band for
  `n===1`, `[]` for `n===0`; `line()`'s `X` already yields `0.5` for `n<=1`.
- **Heatmap rest days** (`km===0`) — card reads `rest`, not `0.0 km`.
- **Sparkline bands** sit inside the detail strip, clear of the run-row's own
  click-to-collapse target — no event conflict.
- **Pointer flicker** — prevented by `pointer-events:none` on the overlay group.
- **Performance** — re-render fires on band crossings (≤ ~30 per sweep), not per
  pixel; `renderVals` is light arithmetic (~1 ms) and reconciliation a few ms —
  the run-row toggle already round-trips a full re-render and feels instant. The
  365 heatmap cell handlers are acceptable; further optimisation is
  measure-first, not pre-emptive.

## 6 · Accessibility

Extends the run-row keyboard work:

- **One tab stop per chart**, never one per point. Each interactive chart
  container is `tabindex="0"` with `role="group"` / `img` and an `aria-label`
  summary.
- The focused chart takes **arrow keys**: ←/→ move `hover.i` between datapoints
  (reusing the same hover state, showing each card); **Enter** pins, **Escape**
  dismisses. The heatmap also takes ↑/↓ for week-to-week movement under the same
  single-tab-stop model — avoiding 365 tab stops.
- An `aria-live="polite"` region announces the focused point
  (e.g. "VO₂ 46.3, March 2025") so the detail reaches screen readers.
- Each band still carries a descriptive `ariaLabel` for pointer-AT users.

## 7 · Testing & verification

- **Unit** — `test_chart_hover.mjs` (Node, the `test_coach_read.mjs` pattern):
  - `bandRects` — midpoint boundaries; first/last extend to edges; `n===1`
    full-width; `n===0` empty; even spacing.
  - `cardBox` — clamps left/right within bounds; flips above when the point is
    near the bottom and below when near the top; permits negative-y escape for
    the sparkline bounds.
- **Live render verification** — screenshots render black on this runtime
  (hidden placeholder DOM), so use the proven path: dispatch
  `mouseenter` / `pointerdown` / `keydown` via Playwright/devtools `evaluate`,
  read back the overlay DOM, and assert crosshair x / dot coords / card text
  match the hovered datapoint. Cover: hover-track, leave-clear, tap-pin,
  tap-away dismiss, arrow-key navigation, and no console errors beyond the benign
  SVG-placeholder baseline — against a fresh real re-sync (spot-check monthly
  label exactness, a heatmap date, and the ring breakdown).

## 8 · File changes

| File | Change |
|------|--------|
| `chart-hover.js` | **create** — pure `bandRects()` + `cardBox()`. |
| `test_chart_hover.mjs` | **create** — Node unit tests for both. |
| `Running Dashboard.dc.html` | `hover` state + `hoverPoint`/`leaveChart`/`pinPoint`/`dismissHover`; `line()` returns `pts`; `hoverLayer()`; per-surface points + overlay in `renderVals`; bands/crosshair/dot/card + a11y attributes in the template. |
| `README.md` | one line documenting datapoint interactivity. |

`garmin-data.js`, `plan-data.js`, `sync_garmin.py`, `validate_data.py`, and
`support.js` are **unchanged**.

## Open decisions

None outstanding. Defaults chosen: hover+tap trigger, all nine surfaces, crosshair
+ floating card, viewBox-unit SVG card, relative labels for weekly/nightly series
(no sync anchors), keyboard navigation included (one tab stop per chart).
