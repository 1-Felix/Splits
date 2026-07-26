# Tasks: add-course-lens

Ordered so pre-race value lands first: profile → pace plan → overlay. The race is
2026-08-09; sections 1–5 are useful before it, section 6 only after.

## 1. Schema + acquisition (Python)

- [x] 1.1 Schema v10 in `activity_archive.py`: additive `courses` and `course_maps` tables, idempotent guarded apply, `--verify-archive` aware of both
- [x] 1.2 `race.courseId` support in `plan-io.mjs` validation: optional integer, rejected when malformed, absent stays valid (extend `test_plan_validate.mjs`)
- [x] 1.3 New `course_lens.py` — acquisition: fetch `/course-service/course/{id}` via `connectapi`, skip when stored `update_date` is unchanged, no-op offline, fail-soft `_warn` so the sync never breaks
- [x] 1.4 Columnar point storage: `{d, lat, lon, elev}` rounded arrays following the `_STREAM_COLUMNS` precision convention; reject/flag a course whose points lack elevation beyond the degraded threshold
- [x] 1.5 Capture the real course (`493447940`, 1 196 points) into `fixtures/` as the test oracle

## 2. Profile derivation (Python)

- [x] 2.1 Distance-window elevation smoothing (window in metres, not samples — point spacing varies); store `elevSmooth` beside raw `elev`
- [x] 2.2 Per-kilometre grade table from the smoothed series; whole-km marks located by nearest stored distance
- [x] 2.3 Decisive-segment detection: sustained climbs and descents found by threshold over a distance window, not hand-listed — the km 12→13 wall and the km 14–15 drop must fall out of the algorithm on the fixture
- [x] 2.4 Totals: gain/loss from the smoothed series, reported beside Garmin's own figures with the source of each named (they disagree by ~40 %)

## 3. Grade-cost calibration + pace model (Python)

- [x] 3.1 Analytic energy-cost curve, coefficients pinned against the published source in a comment; unit-tested at known gradients including the descent reversal
- [x] 3.2 Calibration: fit ONE damping scalar over archived `v`/`gap`/`elev` samples; grade binned, outliers and non-run activities excluded, minimum sample count enforced
- [x] 3.3 Report the fit residual; below a confidence threshold the model falls back to the uncalibrated curve and says so in the document
- [x] 3.4 Pace model output: stored curve identity + damping scalar + residual + flat-equivalent elevation cost — parameters, NOT baked per-target tables (design D5)
- [x] 3.8 Descent-declined variant in the engine: `pace_table(..., decline_descent=True)` plus a target-independent `descentGiveawayFraction` in the document
- [x] 3.5 `COURSE_LENS_VERSION`, recompute on bump, determinism test: same course + version → byte-identical document
- [x] 3.6 Wire into `sync_garmin.py` after the metrics engines; fail-soft
- [x] 3.7 Python tests (`test_course_lens.py`): smoothing, grade table, segment detection, curve values, calibration fit + residual, degraded-elevation path, determinism, fail-soft acquisition

## 4. Data contract + archive API

- [x] 4.1 Additive `courseLens` in `garmin-data.js`: the upcoming race's course document; absent when the race carries no `courseId`
- [x] 4.2 `GET /api/archive/course/:courseId` in `serve.mjs` — stored document verbatim, 404 unknown id, fail-soft 503; added to the existing archive allowlist block
- [x] 4.3 Extend `test_archive_api.mjs`: verbatim document, 404, 503, and no request-time derivation

## 5. `/course` page — profile, map, pace table

- [x] 5.1 `course.dc.html` + route in `serve.mjs`'s page table; topbar entry in `topbar.js`
- [x] 5.2 Elevation profile over DISTANCE via `sharedXScale` + `multiTrackSpec`, mirroring the ELEVATION track in `run.dc.html`; decisive segments annotated from the stored document, never hardcoded
- [x] 5.3 Crosshair readout (`chart-hover.js`): km, elevation, grade
- [x] 5.4 Route on the basemap: `course_maps` rect via `projectTrackMercator` + `tileLayout`, tiles from the existing `/api/archive/tiles/` endpoint; profile renders fine when tiles are unavailable
- [x] 5.5 Sync-side tile acquisition for the course rect, reusing the `route-basemap` throttle and dedup policy
- [x] 5.6 Pace table: per-km grade, target pace, cumulative elapsed, decisive-km markers — computed in-page from the stored model parameters
- [x] 5.7 Target presets (goal / Garmin / Riegel) over the same model; the model's residual surfaced honestly rather than implying false precision
- [x] 5.9 **Cost of caution**: show the pace table both model-optimal and with descent benefit declined (factors clamped to 1.0), with the delta named — so an injury-driven pacing choice reads as a priced trade, not a deviation
- [x] 5.8 `test_course_page.mjs`: renders from the real fixture, chart and table present, degraded and no-course states, demo fallback asserted absent

## 6. Post-race overlay (useful from 2026-08-10)

- [ ] 6.1 Activity matching: race date + run type + distance tolerance; no match → profile and pace plan only, silently
- [ ] 6.2 Distance-domain alignment: normalise actual cumulative distance to the course total, then resample actual pace and HR onto the course grid
- [ ] 6.3 Comparison metrics: per-km actual vs target delta, time attributed to climb / descent / flat, and pace behaviour in the 3 km AFTER the descent (the shin question)
- [ ] 6.4 Overlay rendering on `/course`: elevation backdrop, actual pace and HR against target
- [ ] 6.5 Tests: alignment with a deliberately drifted distance total, attribution arithmetic, unmatched-activity path

## 7. Close-out

- [ ] 7.1 `README.md` / `CLAUDE_CODE_HANDOFF.md` note on the course hook and how to point a future race at its own `courseId`
- [ ] 7.2 Full suite green (Python + `.mjs`), `openspec validate --strict`, NUC deploy verified against the live course
