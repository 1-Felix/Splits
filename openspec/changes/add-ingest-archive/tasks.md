# add-ingest-archive — Tasks

## 1. Shared-seam groundwork (behavior-neutral)

- [ ] 1.1 Pin the samples-dict contract: parity test that builds the samples
      structure both ways — a recorded Garmin fixture through
      `insight_metrics.read_stream` and an ingest-shaped synthesis — and
      asserts `best_efforts()` + `band_aggregates()` agree on the fields both
      sources can supply (documents which fields an ingest samples dict has)
- [ ] 1.2 Baseline the Garmin pipeline: run `test_activity_archive.py`,
      `test_insight_metrics.py`, `test_run_detail.py` green before touching
      anything; if any shared helper must move modules, re-run as the
      byte-neutrality guard (spec: Garmin outputs unchanged)

## 2. Id derivation

- [ ] 2.1 `derive_activity_id(session_uid)` in `ingest_builder.py`: first 12
      hex chars of sha256 → int (48-bit, JS-safe); unit tests: deterministic,
      distinct for distinct UIDs, below 2^53
- [ ] 2.2 Collision rule: on upsert, existing row with a different embedded
      sessionUid → salted rehash (`uid#1`, `#2`, …) + loud warning; unit test
      with a forced collision (monkeypatched hash)

## 3. The archive pass in `ingest_builder.py`

- [ ] 3.1 Open/create the db via `activity_archive.ensure_schema` in
      `SPLITS_DATA_DIR`; test: fresh dir → schema version + tables identical
      to a Garmin-created db
- [ ] 3.2 Upsert one row per banked run: promoted columns
      (`start_time_local`, `type_key` running/treadmill_running,
      `distance_m`, `duration_s`, `avg_hr`, `max_hr`), `summary_json` = banked
      payload verbatim (sessionUid recoverable), NULL for
      name/avg_cadence/elevation_gain/detail_json; tests incl. the honest-NULL
      assertions
- [ ] 3.3 Streams synthesis → `detail_streams_json`: shared `t` axis from the
      union of HR/speed sample times, `hr`, `v`, `d` integrated from `v` and
      normalized to the banked `distanceM`; absent metrics are omitted keys;
      tests: axis alignment, final-distance normalization, no
      cad/elev/lat/lon keys, nulls preserved
- [ ] 3.4 `detail_distilled_json`: refactor the builder's existing
      recentRuns-detail derivation into a per-run function and apply it to
      every banked run; parity test: archived dict == `recentRuns[].detail`
      for the same run
- [ ] 3.5 `run_metrics` rows via `insight_metrics.best_efforts` +
      `band_aggregates` over the synthesized samples dict, upserted at
      `METRICS_VERSION` through `activity_archive.upsert_run_metrics`; test:
      rows appear, version stamped, treadmill flag correct
- [ ] 3.6 Write-once + idempotency: derived artifacts recomputed only when
      missing or version-stale (distill marker in `archive_meta`,
      `METRICS_VERSION` on metrics rows); tests: second pass is a no-op,
      version bump recomputes, deleted db fully self-heals with identical ids
- [ ] 3.7 Wire the pass into the builder's main flow after the telemetry
      build; a failure in the archive pass must not sink the telemetry build
      (soft-fail with a loud log)

## 4. Integration + browser coverage

- [ ] 4.1 `test_ingest_e2e.mjs`: after a pushed run, assert the archive db
      exists and `/api/archive/activities`, `/activities/:id`, `/:id/streams`,
      and `/run-metrics` all serve the run
- [ ] 4.2 `test_slim_render.mjs`: the slim (2-run) fixture now grows an
      archive → assert `/api/status` `archive: true`, the Archive nav tab and
      heatmap drill are BACK, `/archive` lists both runs, `/run/:id` renders
      HR/pace charts in no-basemap mode, `/compare?ids=` of the two runs
      renders
- [ ] 4.3 Keep the no-archive shape covered: the Garmin-shaped `fullDir`
      fixture (no db) retains the 404 / hidden-chrome / "No archive on this
      instance" assertions moved off the slim fixture
- [ ] 4.4 Full suite green: `test_ingest_builder.py`,
      `test_activity_archive.py`, `test_insight_metrics.py`, ingest
      API/store/e2e, slim render, cockpit + progress pages

## 5. Deploy + verify (NUC)

- [ ] 5.1 Commit, push, CI image, pull + restart both instances; Felix's
      instance: `/api/status` unchanged (`archive: true`, `ingestFed: false`),
      spot-check a run page
- [ ] 5.2 Max's instance: next build writes the archive → `/api/status`
      `archive: true`; verify /archive lists his runs, a run page renders
      charts, heatmap day-drill navigates, progress drill panel returns rows
- [ ] 5.3 Idempotency in production: trigger a second build (re-sync from the
      bridge), confirm no row churn (updated_at stable on untouched runs)

## 6. Documentation

- [ ] 6.1 Update the change's HANDOFF-style notes + `activity_archive.py`
      header comment: two producers, one schema, ingest archive is a
      disposable derived cache
- [ ] 6.2 Note the follow-up candidates where they'll be found again:
      plan_snapshots/plan_compliance for ingest instances (run-page
      planned-vs-actual for Max), archive year-chips hardcoded from 2024
