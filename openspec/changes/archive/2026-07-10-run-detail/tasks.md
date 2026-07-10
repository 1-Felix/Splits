# Tasks: run-detail

## 1. Prerequisites

- [x] 1.1 `vendor-runtime` landed — gzip makes the 28 KB stream affordable, and the no-third-party-origin rule is what decides design D2
- [x] 1.2 `chart-engine` landed — `chart-core.js`, `ChartSpec`, the domain-policy table, and the accessibility contract this page inherits

## 2. Stream distillation (design D1)

- [x] 2.1 Pure `distill_run_streams(raw_detail) → dict` in `sync_garmin.py`: columnar, rounded per the D1 table, nulls preserved as nulls; no network, no clock
- [x] 2.2 Cadence comes from `directDoubleCadence` (steps/min), **never** `directRunCadence` (single-side strides/min — 79.8 where the promoted `avg_cadence` is 160.3; see `insight_metrics.read_stream`'s quirk note). A test asserts the stream's mean cadence matches the run's promoted `avg_cadence` within rounding
- [x] 2.3 Drop the redundant metrics (`directTimestamp`, `directRunCadence`, `directFractionalCadence`, `sumElapsedDuration`, `sumMovingDuration`, `sumAccumulatedPower`, `directVerticalSpeed`) and record in a comment why each is derivable
- [x] 2.4 Recover the GPS track from `directLatitude` / `directLongitude` — `geoPolylineDTO.polyline` is empty because the sync fetches with `maxpoly=0`; assert this in a test so nobody goes looking for it again
- [x] 2.5 Tests against a stored raw payload: column shapes, rounding, null preservation, GPS non-null across all samples, and that the largest archived run serialises under 110 KB

## 3. Schema and recovery (design D1)

- [x] 3.1 Additive `activities.detail_streams_json` via the guarded `PRAGMA table_info` pattern; `_apply_schema_v6`, `SCHEMA_VERSION = 6` (v5 is pre-assigned to `wellness-archive`; both migrations are additive and guarded, so either may land first — the numbers are fixed only to avoid conflicting on the same line)
- [x] 3.2 The sync writes streams whenever a run's raw detail is archived (append and top-up paths), inside the existing fail-soft wrapper
- [x] 3.3 Recovery pass writes streams for already-archived runs from their stored raw payloads, with no Garmin calls; idempotent and re-runnable
- [x] 3.4 `--verify-archive` reports stream coverage against runs holding raw detail; exit non-zero on regression
- [x] 3.5 Run the recovery pass over the local archive: 162/162 runs gain streams; raw payloads byte-identical afterwards; record the real database growth

## 4. The streams endpoint (design D6)

- [x] 4.1 `GET /api/archive/activities/:id/streams` — widen the id parse to accept the suffix while keeping the `^\d+$` guard on the id itself
- [x] 4.2 Serve `detail_streams_json` verbatim; never serialise `detail_json` or `summary_json` into any response; derive nothing
- [x] 4.3 404 for an unknown id, 404 for a run with no stored streams, 503 under a missing or locked archive — the established fail-soft contract
- [x] 4.4 Confirm the response is gzipped by `vendor-runtime`'s content negotiation, and assert the wire size for the largest run
- [x] 4.5 `test_archive_api.mjs`: shape, 404s, 503, gzip, method rejection, and the no-writes assertion (database bytes unchanged)

## 5. Chart primitives (designs D3, D4)

- [x] 5.1 `crosshairAt(xScale, xs, pointerPx) → { i, x }` in `chart-core.js` — bisector lookup, clamped at both ends; `bandRects` is left untouched for the charts it was written for
- [x] 5.2 `multiTrackSpec(tracks, sharedX) → ChartSpec[]` — one x domain, one y domain per track from the policy table
- [x] 5.3 Equirectangular projection with `cos(lat₀)` longitude correction, fitted to the viewport, aspect preserved
- [x] 5.4 `test_chart_core.mjs`: bisection at the ends, midpoint, and beyond the domain; projection preserves aspect and is translation-invariant; one crosshair index maps to every track

## 6. The page (designs D2, D4, D5, D6)

- [x] 6.1 Parameterised route `/^\/run\/\d+$/` → `run.dc.html` in `serve.mjs`; the page reads its id from `location.pathname`, never from the filename
- [x] 6.2 Headline verdict at the top — reuse the coach-read line the drill-down already renders; the page must answer "was this run good?" before any chart is read
- [x] 6.3 Track stack: pace (with grade-adjusted pace as a recessive second line), heart rate over zone bands from `profile.hrZones`, cadence, elevation, power. Power and performance-condition tracks render only when their columns carry data, and their absence is silent
- [x] 6.4 One crosshair through every track; x axis toggles distance ⇄ time
- [x] 6.5 GPS trace with the crosshair's sample pinned on the path — no tiles, no external origin (design D2)
- [x] 6.6 Splits table with per-kilometre bars coloured against the run's own median pace
- [x] 6.7 Records set inside this run, from `run_metrics` (best 1k / mile / 5k / 10k / half)
- [x] 6.8 Planned versus actual from `plan_compliance` joined on `activity_id`: planned kind, distance, load, title, the compliance status and its reason. Absent and silent for unplanned runs; a swapped session says so
- [x] 6.9 Archive-offline state: page chrome renders, an honest "archive offline" indication replaces the data, nothing throws

## 7. Click-through and consistency

- [x] 7.1 The records wall navigates to `/run/:id` instead of expanding the inline drill-down; keep the offline degradation the current spec requires
- [x] 7.2 Confirm the cockpit's recent-activities drill-down is unchanged — it is race-safe and stays as it is
- [x] 7.3 Topbar nav is untouched; `/run/:id` is reached from links, not from the nav

## 8. Guards and spec sync

- [x] 8.1 Playwright pass over `/run/:id`: the crosshair moves every track together, the trace pin follows it, the distance/time toggle re-renders the axis, the page degrades under a 503
- [x] 8.2 `test_offline.mjs` extended — `/run/:id` renders with every third-party origin blocked (this is what the trace-not-basemap decision buys)
- [x] 8.3 Measure the page on a phone: ~8,000 path nodes across five tracks plus the trace. If it bites, simplify the *rendered path*, never the stored stream
- [x] 8.4 Write `openspec/specs/run-detail/spec.md` from the delta; update `activity-archive`, `archive-api`, `chart-engine`, and `progress-views`
- [x] 8.5 `README.md`: the streams contract, the recovery pass, and why there is no basemap
