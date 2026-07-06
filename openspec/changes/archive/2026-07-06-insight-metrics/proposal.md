# Proposal: insight-metrics

## Why

The archive (stage 1) now holds every run since 2024-05 with full 1–4 s streams,
but nothing reads it yet — the dashboard still shows a rolling window with no
notion of progress. Five weeks out from Sonthofen (Aug 9, sub-2:00 half goal),
the highest-value insight per unit of work is an honest, deterministic answer to
"is the gap closing?" — Garmin currently predicts 2:00:55 while the demonstrated
best efforts say ~2:13, and neither the gap nor its direction is visible anywhere.

## What Changes

- **New deterministic metrics engine** (`insight_metrics.py`, stdlib-only) that
  runs inside the nightly sync, after the archive step, in the same fail-soft
  pattern: an engine failure can never break `garmin-data.js` or the dashboard.
- **Per-run extraction, computed once**: fastest 1k / mile / 5k / 10k / half
  *inside* every archived run (sliding window over the distance stream, elapsed
  time, interpolated), stored in a new `run_metrics` table in the archive DB
  keyed by `metrics_version` — immutable per run, incremental per sync,
  recomputable when the algorithm version bumps. Garmin's own
  `fastestSplit_*` summary fields serve as a cross-validation oracle in tests.
- **Monthly progress series from pooled stream samples** (not per-run
  classification — strict Z2 runs barely exist in 2024–mid-2025 data):
  - *Pace @ reference HR* — the aerobic engine, grade-adjusted where available.
  - *Cadence @ reference pace* — form efficiency.
- **Records + best-efforts feed**: all-time and rolling best efforts, and a
  "records fell" feed (date, distance, old → new). Treadmill runs count toward
  trends but are excluded from the records feed.
- **Honest race trajectory**: weekly Riegel prediction (exponent 1.06, anchored
  on the best 10k effort in a rolling 12-week window) vs Garmin's race
  predictor, tracked against the sub-2:00 goal. Garmin predictor history is
  backfilled from the API (daily/monthly endpoint, 1 year per call, back to
  2024) and banked on every sync thereafter.
- **`garmin-data.js` gains an `insights` block** (additive; existing keys
  untouched) and the existing `predictions.trend` placeholder is finally
  filled.
- **Dashboard surfaces the insights** (stage 2 includes UI): trend direction on
  the race-prediction card, a records feed, and compact progress trend
  visuals on the existing page. Full multi-view exploration stays in stage 3
  (`progress-views`).

## Capabilities

### New Capabilities

- `insight-metrics`: the deterministic metrics layer over the activity archive —
  per-run best-effort extraction and storage (`run_metrics`, versioned),
  monthly pace@HR and cadence@pace series, records feed, Riegel-vs-Garmin race
  trajectory with predictor banking/backfill, and the `insights` contract
  surfaced into `garmin-data.js`. Fail-soft inside the sync, recomputable from
  the archive at any time.

### Modified Capabilities

- `live-dashboard`: added requirements — the dashboard renders the progress
  insights (race-trajectory trend with gap direction, records-fell feed,
  efficiency and cadence trend visuals) from the `insights` block, degrading
  gracefully when the block is absent (pre-engine data files keep working).

## Impact

- **New code**: `insight_metrics.py` (engine + series assembly), tests
  (`test_insight_metrics.py`) including cross-validation against Garmin
  `fastestSplit_*` values on archived fixtures.
- **Modified code**: `sync_garmin.py` (metrics step after archive step; a
  `--backfill-predictions` / recompute path; `insights` block in the emitted
  contract), `activity_archive.py` (schema v2 migration: `run_metrics` +
  `race_predictions` tables — additive, no changes to existing tables),
  dashboard UI (`Running Dashboard.dc.html`, `support.js`, `dashboard.css`),
  `validate_data.py` (contract check for the new block).
- **Data**: `activity-archive.db` schema v2 (additive). One-time predictor
  backfill (~2–3 API calls). No new Python dependencies; no new auth scopes
  (`get_race_predictions` is already used).
- **Depends on**: stage 1 `activity-archive` (deployed; task 7.3 nightly-append
  confirmation still pending — independent of this change, but the engine reads
  the server archive, so server metrics are only as complete as the server
  backfill, already verified at 536/536).
- **Explicitly out of scope**: multi-page progress views (stage 3), plan
  compliance / coach briefing (stage 4), any AI-computed numbers — everything
  here is deterministic.
