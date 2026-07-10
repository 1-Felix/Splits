# Design: run-detail

## Context

The archive stores each run's `get_activity_details` payload untouched
(`maxchart=2000, maxpoly=0`). Nineteen metric descriptors, ~1,670 sample rows
per run, 162 runs, 52.3 MB — more than half the database. The sync distils that
to a ~0.5 KB `detail_distilled_json` (eight per-km splits, thirty downsampled HR
points, zone minutes, drift, load), which is the shape the archive API serves and
the drill-down renders.

`serve.mjs` routes pages through an exact map:

```js
const PAGES = { "/": "/Running Dashboard.dc.html", "/progress": "/progress.dc.html" };
…
if (PAGES[pathname]) pathname = PAGES[pathname];
```

and archive detail through a strict id parse:

```js
const idStr = pathname.slice("/api/archive/activities/".length);
if (!/^\d+$/.test(idStr)) { json(res, 404, …); return; }
```

`chart-hover.js` provides `bandRects(points, vbW, chartH)` — per-point hit bands
whose boundaries sit at neighbour midpoints. Correct for thirty monthly points.
Meaningless for 1,670 samples.

Constraints: the archive API is *a window, not an engine* — it SELECTs stored
rows and never derives. `vendor-runtime` forbids third-party origins. The archive
sits on the homeserver volume, `journal_mode=DELETE`.

## Goals / Non-Goals

**Goals**

- Answer "was yesterday's run good?" without leaving the page.
- Render the stream at full resolution, because it is affordable.
- Show what the plan asked for beside what happened.
- Establish the primitives roadmap 3b (run comparison) will reuse.

**Non-Goals**

- Run-versus-run comparison (3b).
- Any Garmin re-fetch — everything comes from stored payloads.
- A basemap.
- Deriving new training metrics; `insight_metrics.py` remains the only place.

## Decisions

### D1 — Columnar streams, stored at sync time

Row-oriented `[{metrics:[19 floats]}, …]` becomes column-oriented, rounded to the
precision each metric actually has:

| key | source | precision |
|---|---|---|
| `t` | `sumDuration` | int seconds |
| `d` | `sumDistance` | int metres |
| `hr` | `directHeartRate` | int bpm |
| `v` | `directSpeed` | 2 dp m/s |
| `gap` | `directGradeAdjustedSpeed` | 2 dp m/s |
| `cad` | `directDoubleCadence` | int steps/min |
| `elev` | `directElevation` | 1 dp m |
| `pwr` | `directPower` | int W |
| `lat` / `lon` | `directLatitude` / `directLongitude` | 5 dp |
| `pc` | `directPerformanceCondition` | int, nullable |

**Cadence comes from `directDoubleCadence`, never from `directRunCadence`.**
Despite a descriptor claiming `stepsPerMinute`, `directRunCadence` is
single-side strides per minute — it means 79.8 on a run whose promoted
`avg_cadence` is 160.3. `insight_metrics.read_stream` already documents the
quirk and doubles it. The stream stores the already-correct column instead, so
nothing downstream has to remember.

Dropped as redundant: `directTimestamp` (it is `t` plus the start time),
`directRunCadence` and `directFractionalCadence` (both folded into
`directDoubleCadence`), `sumElapsedDuration` / `sumMovingDuration`,
`sumAccumulatedPower`, `directVerticalSpeed` (derives from `elev`).

Measured on the largest run in the archive: **105 KB, 28 KB gzipped**, at full
1,999-sample resolution. Repeated small integers compress extremely well.

**Where the transform runs.** At sync time, into `detail_streams_json`, served
verbatim — exactly the `detail_distilled_json` contract, whose own comment reads
*"derived and disposable — a recompute simply replaces it."* A recovery pass
distils from stored raw payloads with no network, and `--verify-archive` reports
coverage.

*Rejected:* transforming on read in `serve.mjs`. It saves ~15 MB and costs the
archive-API's clearest invariant. "The API SELECTs and never derives" is a rule
worth 15 MB, and reshaping is exactly the kind of thing that would grow into
derivation one commit at a time.

*Rejected:* downsampling to ~1,000 points. Garmin does it because it serves
millions of clients. At 28 KB gzipped there is nothing to buy.

### D2 — The route is a trace, not a basemap

Every tile provider is a third-party origin, and `vendor-runtime` forbids those.
Rather than carve an exception, render the GPS track as a projected polyline on a
plain surface: equirectangular with a `cos(lat₀)` correction on longitude, fit to
the viewport, with the crosshair's sample pinned on the path.

The constraint improves the artifact. A basemap tells you which streets you ran;
the trace tells you the *shape* of the run, which is what you look at a route for
when you already know the city. It also renders offline, prints, themes with the
rest of the page, and costs 9 KB.

### D3 — A continuous crosshair is a new primitive

`bandRects` tiles the x-range into one hit band per point. With 1,670 samples the
bands are sub-pixel and the abstraction is wrong. The run page needs: pointer x
→ domain x → `bisector` → nearest sample index → one index shared by every track.

```js
// chart-core.js
crosshairAt(xScale, xs, pointerPx) → { i, x }      // bisector, clamped
multiTrackSpec(tracks, sharedX)    → ChartSpec[]   // one x domain, n y domains
```

`bandRects` stays exactly as it is, for the charts it was written for. Two hover
primitives, each correct for its data density, is the honest outcome — not one
primitive stretched over both.

**The x axis toggles between distance and time**, which is why `sharedX` is a
parameter rather than a constant: `d` and `t` are both stored columns and the
same crosshair machinery serves either.

### D4 — Track stack, one x, five y

Pace, heart rate, cadence, elevation, power — stacked, sharing the x scale,
each with its own y domain from `chart-engine`'s policy table. Never a dual axis;
five plots is the answer to five scales.

Two overlays that earn their place:

- **Grade-adjusted pace** beneath the pace track as a recessive second line. On a
  hilly run the divergence *is* the story, and both series share pace units, so
  they share one axis legitimately.
- **HR zones as background bands** on the heart-rate track, drawn from
  `profile.hrZones` and the corrected zone ramp `chart-engine` establishes.

Power and performance-condition tracks render only when their columns carry data
(`pc` is 84% covered), and their absence is silent, not an error.

### D5 — Planned versus actual is the differentiator, and it ships in v1

`plan_compliance` carries `activity_id`, `planned_kind`, `planned_km`,
`planned_load`, `planned_title`, `status`, `reason`, and the scored actuals. The
join is one SELECT and the scoring is already done — the sync did it, versioned,
tested, at snapshot time.

Garmin cannot draw this. It does not know that Friday was meant to be
`4×1 km @ 5:25–5:35`. Putting it on the page is what makes this a training
companion's run view rather than a nicer copy of Garmin's.

Unplanned runs render the page without the section. A run matched as *swapped*
says so, with the plan's own reason string.

### D6 — Parameterised page route

`PAGES` is an exact map. `/run/:id` becomes the first prefix route:
`/^\/run\/\d+$/` serves `run.dc.html`, and the page reads the id from
`location.pathname` — never from the served filename, so the component stays one
file. The API's id parse is widened to accept a `/streams` suffix, keeping the
`^\d+$` guard on the id itself.

A malformed id serves the page, which then reports "unknown run" from the API's
404. An unreachable archive shows the established "archive offline" state and a
page that still renders its chrome — the `progress-views` precedent.

## Risks / Trade-offs

- **15 MB of derived data duplicating information already stored.** Accepted, and
  precedented by `detail_distilled_json`. The alternative erodes the API's
  no-derivation rule, which is worth more.
- **1,670-point SVG paths, five of them, plus a trace.** ~8,000 nodes per page.
  Fine for one page on a desktop; worth measuring on a phone. If it bites, the
  fix is render-time simplification (Douglas–Peucker on the *path*, not on the
  *data*) — the stored stream stays full-resolution either way.
- **No basemap will disappoint someone.** Named as a decision (D2) rather than a
  gap, with the reason attached. Reversible only by relaxing the origin rule,
  which is a spec change, not a preference.
- **The crosshair is a second hover primitive.** Two primitives is a maintenance
  cost. One stretched primitive is a correctness cost. Chosen deliberately.
- **`pc` (performance condition) is 84% covered.** Its track is conditional, and
  its absence must be silent — otherwise a sixth of runs render a broken panel.

## Open Questions

- **Does the splits table colour bars against the run's own median, or against
  the planned pace when a plan exists?** The plan is the more useful reference and
  the more opinionated choice. Starting with the run's median; the plan overlay is
  a small follow-up once the page is real.
- **Should `/run/:id` be reachable from the recent-activities table on the
  cockpit?** That table's inline drill-down is fast and race-safe. Probably both:
  the row expands, and the expanded panel links out. Deferred until the page
  exists and the drill-down can be compared against it.
