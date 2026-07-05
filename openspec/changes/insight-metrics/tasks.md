# Tasks: insight-metrics

## 1. Archive schema v2

- [x] 1.1 In `activity_archive.py`: forward-only migration to schema v2 —
      create `run_metrics` and `race_predictions` tables per design D2,
      bump `archive_meta.schema_version` to 2; v1 tables untouched
- [x] 1.2 Accessors: `runs_missing_metrics(version)` (has detail, no row at
      version), `upsert_run_metrics(row)` (replace-on-conflict — derived rows
      are disposable), `upsert_race_prediction(date, values, raw, source)`,
      `race_predictions_empty()`
- [x] 1.3 Tests: v1→v2 migration on a populated dress-rehearsal-style db,
      idempotent re-open at v2, metrics upsert replaces stale-version row,
      prediction upsert refreshes same-day row

## 2. Engine — per-run extraction (`insight_metrics.py`)

- [x] 2.1 Stream reader: descriptor index → monotonic `(elapsed_s,
      cumulative_m, hr, cadence, gas_speed)` samples from a raw detail payload
      (`directTimestamp` with `sumElapsedDuration` fallback, `sumDistance`
      clamped non-decreasing, `None`s dropped, GAS falling back to
      `directSpeed`)
- [x] 2.2 Best efforts: two-pointer minimum-elapsed window with edge
      interpolation for 1k / mile / 5k / 10k / half; NULL when the run is
      shorter than the target (design D3)
- [x] 2.3 Reference-band aggregates: time-weighted sums for pace@HR (warm-up
      cutoff 8 min, walking floor 1.4 m/s) and cadence@pace, per design D4;
      band constants + `METRICS_VERSION` defined here
- [x] 2.4 Extraction driver: compute + upsert `run_metrics` for all runs
      missing the current version (treadmill flagged from `type_key`), no cap,
      per-run commit
- [x] 2.5 Unit tests with synthetic streams: known fastest windows (incl. a
      pause inside the best window counting against elapsed), interpolation at
      edges, short-run NULLs, band sums with warm-up/floor exclusions
- [x] 2.6 Oracle test against the real archive: for runs where Garmin
      `fastestSplit_*` exists, ours within ~3% — reads the local
      `activity-archive.db`, `skip` when absent (CI has no personal data;
      no GPS-bearing fixtures get committed)

## 3. Band validation (one-time, against the real archive)

- [x] 3.1 Density check: samples-in-band minutes per month for the default
      HR (125–145) and pace (5:30–6:00) bands across the full local archive;
      adjust constants if any trained month yields a gap-heavy series, then
      freeze them under `METRICS_VERSION` 1 (design D4 / open question 1)
      → HR 125–145 kept; pace moved to 7:00–8:00 (420–480 s/km): the default
      was gap-heavy in 13/21 trained months, the frozen band leaves only
      genuinely untrained months (≤2 runs) below threshold

## 4. Engine — series assembly

- [x] 4.1 Monthly series SQL: pace@HR and cadence@pace from summed
      `run_metrics` aggregates, null below the 10-in-band-minutes threshold
- [x] 4.2 Records progression (outdoor only): all-time and last-90d bests per
      distance, newest-first feed of record events with old → new times
- [x] 4.3 Weekly trajectory: Riegel (best outdoor 10k in trailing 84 days,
      exponent 1.06, null when absent) vs banked Garmin half prediction;
      trend verdict string (closing/opening/flat + rate) from recent weeks
- [x] 4.4 `assemble_insights(conn)` → the complete `insights` dict per design
      D9, or raises (caller omits the block — no partials)
- [x] 4.5 Tests on seeded `run_metrics`/`race_predictions` rows (no streams):
      monthly sums and null months, record-fall detection, treadmill exclusion
      from records but not trends, Riegel math, null-over-substitution weeks,
      trend verdict wording

## 5. Predictor banking + backfill

- [x] 5.1 Bank-on-sync: upsert today's row from the predictor document
      `fetch_predictions` already fetched (zero extra calls)
- [x] 5.2 Auto-backfill when `race_predictions` is empty: daily history back
      to account start in ≤1-year windows, fail-soft, idempotent (design D7)
- [x] 5.3 Tests with a mocked client: banking, empty-table triggers backfill,
      endpoint failure leaves sync green and banks what it can

## 6. Sync integration (order inversion, design D8)

- [x] 6.1 Reorder `main()`: fetch → archive step → metrics step (extraction +
      banking/backfill) → `build_data` → write `garmin-data.js`; every new
      step `safe()`-wrapped (wellness banking moved after the write — it needs
      readiness, which build_data computes; nothing downstream needs it)
- [x] 6.2 Insights assembly inside `build_data` via `safe()`: on any failure
      the `insights` key is absent, all existing keys still emitted
- [x] 6.3 Log lines: `✓ metrics: +N runs extracted, prediction banked,
      insights assembled (M months, W weeks)` and warning paths
- [x] 6.4 Fail-soft proof test: block the archive db → sync still writes
      `garmin-data.js` with existing keys, no `insights`, exit code 0

## 7. Contract validation

- [x] 7.1 `validate_data.py`: `insights` optional; when present shape-check
      efficiency/cadence (bands + monthly), bestEfforts, recordsFeed,
      trajectory (goalSec + weekly), metricsVersion — failures name the member
- [x] 7.2 Tests: pre-engine file passes, well-formed block passes, truncated
      block fails with the offending member named

## 8. Verify mode

- [x] 8.1 Extend `--verify-archive`: metrics coverage (runs-with-detail vs
      current-version rows), `race_predictions` bounds/count, series extents
- [x] 8.2 Exit non-zero with a named reason when metrics coverage regresses
      (stale-version rows after a completed sync); test both paths

## 9. Dashboard UI (stage 2 surfaces, design D10)

- [x] 9.1 Race-prediction card: trend verdict (direction + rate) from
      `predictions.trend` and the current Riegel-vs-Garmin gap
- [x] 9.2 Records feed card: humanized newest-first list from
      `insights.recordsFeed`; calm empty state for an empty feed
- [x] 9.3 Progress trends: two compact monthly charts (pace@refHR,
      cadence@refPace) reusing the existing chart + hover patterns; null
      months render as gaps, hover/focus reveals month + value
- [x] 9.4 Graceful absence: all three surfaces render nothing (no errors, no
      layout break) when `garminData.insights` is missing (verified live via
      the standalone fallback, which has no insights block)
- [x] 9.5 Visual check against real data: local sync with the local archive,
      screenshot the three surfaces, confirm gaps/hover/empty states
      (splits-insights-hero.png, splits-insights-trends.png; hover pop
      verified: "Jan 26 · 8:09 /km · 152 min in band")

## 10. End-to-end verification

- [x] 10.1 Full test suite (`test_*.py`, `test_*.mjs`) green — no regressions
      from the sync reorder
- [x] 10.2 Local real-sync smoke: `python sync_garmin.py` → schema v2
      migrated, 162/162 runs extracted, 785 days of predictor history
      backfilled (to 2024-05-12), `garmin-data.js` gained a validating
      `insights` block (27 months, 48 weeks, 10 records), dashboard renders
      the surfaces. Found + fixed en route: stream `directRunCadence` is
      single-side strides/min (half the summary spm) — doubled in read_stream
- [x] 10.3 Version-bump rehearsal: bumped `METRICS_VERSION` 1→2 → sync
      recomputed all 162 with no manual step → reverted 2→1 → sync recomputed
      again (self-heal proven both directions), verify green

## 11. Deploy to the homeserver

- [x] 11.1 Merge to `main` → CI image; pull + recreate the container on the
      same volume (commit 36cc8f1, image pulled + recreated 2026-07-05)
- [x] 11.2 Trigger a sync in the container; then
      `docker compose exec splits python3 sync_garmin.py --verify-archive` —
      162/162 detailed runs at v1 (536-activity baseline intact), 785 daily
      prediction rows back to 2024-05-12, insights 27 months / 48 weeks /
      10 records, exit 0
- [x] 11.3 Spot-check the live dashboard: hero card shows RIEGEL 2:14:28
      +15:12 vs model · ↘ closing ≈131s/wk, records feed populated, both
      trend charts render with honest gaps
- [ ] 11.4 After the next nightly sync: `run_metrics` grew with any new run,
      today's prediction row banked, insights refreshed — stage 2 steady state
      confirmed
