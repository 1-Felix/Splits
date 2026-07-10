# Proposal: run-detail

## Why

The dashboard answers "am I on track for sub-2:00?" beautifully and "was
yesterday's run good?" not at all.

Every run in the archive holds a full sample stream — `get_activity_details` is
fetched with `maxchart=2000` and stored raw. Measured against the real database:

```
162 runs, all with raw detail        ~1,670 samples each, 19 metrics per sample
coverage across the 12 latest runs   speed, grade-adjusted speed, elevation,
                                     cadence, heart rate, lat/lon, air temp,
                                     distance, duration            100.0 %
                                     running power                  99.9 %
                                     performance condition          84.3 %
```

What reaches the screen: an eight-point per-kilometre split sparkline and a
thirty-point downsampled heart-rate line, each 26 pixels tall, inside a table
row. Grade-adjusted pace and running power — two tracks Garmin's own app
shows — are rendered nowhere. Elevation is a single summary number. There is no
run page.

The archive also already knows things the run page should say and nobody asks it:
`run_metrics` holds each run's best 1k / mile / 5k / 10k / half, so "you set a
5k best inside this run" is a lookup. And `plan_compliance` carries
`activity_id`, so **planned versus actual** is a join — the one thing on a run
page that Garmin structurally cannot show, because Garmin does not know what the
coach asked for.

The obstacle was assumed to be payload size. It is not:

```
raw detail_json, per run             median 336 KB   max 449 KB   (52.3 MB total)
  served as-is, gzipped                        102 KB
  columnar + rounded, 10 metrics                28 KB   ← full resolution, no downsampling
  GPS track alone (lat/lon)                      9 KB
```

The payload is fat because it is row-oriented JSON with nineteen float objects
per sample, not because there is too much data. Reshaped to columns and rounded
to real precision, **the entire stream costs 28 KB gzipped.** Garmin downsamples
to ~1,000 points because it serves millions of users. This serves one.

One correction to an earlier assumption: `geoPolylineDTO.polyline` is `[]` — the
sync passes `maxpoly=0`, so Garmin never sent the track. But `directLatitude` and
`directLongitude` are present and non-null on **every** sample. The route is
fully recoverable from the stream columns, with no re-fetch and no API change.

## What Changes

- **Schema: `activities.detail_streams_json`.** An additive column holding each
  run's stream as rounded columns (`t`, `d`, `hr`, `v`, `gap`, `cad`, `elev`,
  `pwr`, `lat`, `lon`, `pc`), written by the sync's distiller pass and
  recomputable offline from the stored raw payload. It follows
  `detail_distilled_json` exactly: derived, disposable, served verbatim, coverage
  verified. Cost: roughly 15 MB on a 100 MB database.

- **`GET /api/archive/activities/:id/streams`** — serves the stored columns
  verbatim, gzipped. The API keeps its window-not-engine rule: it SELECTs and
  sends, it derives nothing.

- **`/run/:id`** — a new page. Page routes are an exact map today
  (`PAGES["/progress"]`); this adds the first parameterised route, with the id
  read from the location rather than baked into the served filename.

- **The multi-track chart.** Pace (with grade-adjusted pace beneath it), heart
  rate over zone-shaded bands, cadence, elevation, and power — stacked, sharing
  one x axis, toggleable between distance and time, with **one crosshair moving
  through every track at once**. This is a new primitive: `chart-hover.js`'s
  `bandRects` tiles the x-range into per-point bands, which is right for thirty
  monthly points and wrong for 1,670 samples. A bisector-based continuous
  crosshair joins `chart-core.js`.

- **The route is a trace, not a basemap.** `vendor-runtime` forbids third-party
  origins, and every map-tile provider is one. The GPS track renders as a
  projected polyline on a plain surface, with the crosshair's position pinned on
  it. No tiles, no API key, no network. The constraint produces the better
  artifact: it is the shape of the run, not a picture of a city.

- **Splits, records, and the verdict.** A per-kilometre splits table with bars
  coloured by pace relative to the run's own median; the best efforts this run
  set, from `run_metrics`; and a headline that answers the question the page
  exists for, reusing the coach-read line the drill-down already renders.

- **Planned versus actual.** Joined from `plan_compliance` on `activity_id`: what
  the plan asked for, what happened, and the compliance verdict already scored by
  the sync. Absent for unplanned runs, and absent gracefully.

- **Records click through to the page.** The records wall currently expands an
  inline drill-down; it now navigates to `/run/:id`, where there is room.

Out of scope: run-versus-run comparison (roadmap 3b — this page is its
precondition), the hypnogram and wellness overlays, and any re-fetch from Garmin.

## Capabilities

### New Capabilities

- `run-detail`: the `/run/:id` page — synchronised multi-track streams, the GPS
  trace, splits, records set, planned-versus-actual, and honest degradation when
  the archive is unreachable.

### Modified Capabilities

- `activity-archive`: run streams stored alongside the raw payload and the
  distilled detail (additive column, shared distiller, local recovery pass,
  verified coverage).
- `archive-api`: a streams endpoint serving the stored columns verbatim, under
  the existing no-derivation and fail-soft rules.
- `chart-engine`: a continuous crosshair primitive and a multi-track chart
  specification sharing one x scale across stacked plots.
- `progress-views`: activating a record navigates to that run's page rather than
  expanding an inline drill-down.

## Impact

- **Code:** `sync_garmin.py` (stream distiller), `activity_archive.py` (additive
  migration, coverage), `serve.mjs` (streams endpoint, parameterised page route),
  new `run.dc.html`, `chart-core.js` (`crosshairAt`, multi-track spec,
  equirectangular projection), `chart-view.js` (track stack, trace), `dashboard.css`,
  `progress.dc.html` (click-through).
- **Tests:** stream distillation is pure and tested against a stored raw payload
  (columns, rounding, null handling, GPS recovery); `test_archive_api.mjs` gains
  the streams endpoint (shape, 404, 503, gzip, no-writes); `test_chart_core.mjs`
  gains crosshair bisection and projection; a Playwright pass over `/run/:id`
  asserting the crosshair moves every track together and the page degrades when
  the archive 503s.
- **Data:** ~15 MB of derived columns. No raw payload is touched, no Garmin call
  is made — the recovery pass distils from what is already stored.
- **Schema:** one additive migration, guarded by the `PRAGMA table_info` pattern,
  taking **v6**. (`wellness-archive` takes v5. The numbers are pre-assigned rather
  than left to merge order, because both changes bump `SCHEMA_VERSION` in the same
  line of `activity_archive.py` and would otherwise conflict on every rebase. The
  migrations themselves are additive and order-independent, so either may land
  first.)
- **Sequencing:** requires `vendor-runtime` (gzip, and the no-third-party-origin
  rule that makes the trace-not-basemap decision) and `chart-engine` (scales,
  axes, `ChartSpec`, the hover contract). Independent of `wellness-archive`.
  Its data half — the stream distiller, the migration, the recovery pass, the
  streams endpoint (tasks 2–4) — depends on neither and can proceed alongside
  `chart-engine`; only the page (tasks 5–6) waits. The cockpit is never touched,
  so nothing here sits on the race's critical path.
