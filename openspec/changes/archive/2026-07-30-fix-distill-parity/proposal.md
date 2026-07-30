# Proposal: fix-distill-parity

## Why

The cockpit's compact interval summary and `/run/:id`'s full document are meant to
be the same reading of the same run. They are not: `distill_run_detail` calls
`build_document` with `laps=None` and (since add-workout-prior) no `workout`
either, so the cockpit's summary is stream-only even for the 24 runs whose real
document is lap-sourced (handoff M8). Worse, the nightly ordering distills a new
run **before** its laps are fetched and **before** its workout is banked
(`_distill_pass` runs inside `archive_step`; `_laps_pass` runs after it in the
same function; `workouts_step` runs after `archive_step`) — and because the
distill work-list is gated on `detail_distilled_json IS NULL` with no version
marker (handoff P2.4), that stream-only compact never heals. Stored distilled
`intervals` keys are still v3-era for most of the archive.

## What Changes

- **M8** — `distill_run_detail` gains `laps` and `workout` parameters and passes
  them to `build_document` (the same call shape `intervals_step` uses). The
  archive distill pass supplies both from stored payloads; the recent-runs path
  supplies both from a read-only archive connection, gracefully absent when the
  archive is unreachable.
- **P2.4** — schema **v13** adds `distilled_version` and `distilled_at` columns
  (additive, idempotent migration). A new `GARMIN_DISTILL_VERSION` constant
  mirrors the Health Connect side's `INGEST_DISTILL_VERSION`. The distill
  work-list becomes: no distilled copy, OR older version, OR laps fetched after
  the distill, OR (for runs referencing a workout) the workout banked after the
  distill. `write_distilled` stamps both columns.
- **Ordering** — `_distill_pass` moves out of `archive_step` into its own step
  after `workouts_step`, and `_laps_pass` runs before it: archive → workouts →
  **distill** → intervals. Tonight's run is distilled with its laps and its
  prescription in hand.
- **Self-heal** — the first sync after deploy re-distills every stored compact
  (~170 runs, stored payloads, no network). The 24 lap-sourced runs' cockpit
  sentences move into agreement with `/run/:id`; that movement is the fix, in
  derived disposable data. `INTERVAL_VERSION` does not change; `run_intervals`
  documents do not move.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `activity-archive`: the distilled-detail requirement gains versioned staleness
  — a distilled copy records the distiller version and time it was computed, is
  refreshed when the version bumps or when laps/workout data lands after it was
  computed, and is computed WITH the run's laps and workout definition so the
  compact summary and the full interval document read the run identically.

## Impact

- `sync_garmin.py` (distiller signature, work-list, pass ordering, version
  constant), `activity_archive.py` (schema v13 migration, `write_distilled`
  stamps, `runs_missing_distilled` staleness clauses, `distilled_coverage`
  unchanged in meaning).
- Tests: `test_run_detail.py` (distiller parity + staleness), and
  `test_activity_archive.py` (migration + work-list).
- One-off production effect: full re-distill on first sync (no network); no
  schema-visible change for readers (columns are additive, JSON contract keys
  unchanged).
