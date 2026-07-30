# Design: fix-distill-parity

## Context

`distill_run_detail` is the one distiller with two callers (spec: "one
distiller, two callers"): `fetch_run_detail` (cockpit recent runs, rebuilt
nightly) and `_distill_pass` (archive recovery). Both currently call
`build_document(streams, activity, None, ...)` — no laps, no workout — while
`intervals_step` calls it with both. The stored compact is written once
(`IS NULL` gate) and never refreshed. Verified orderings: `_distill_pass` runs
before `_laps_pass` inside `archive_step` (sync_garmin.py:1097-1099) and
`workouts_step` runs after `archive_step` (main, sync_garmin.py:1901-1904), so
a new run's stored compact can never have seen its laps or prescription.

Decided with Felix 2026-07-30: per-row columns + reorder (over the HC-style
all-or-nothing meta marker, which cannot see late-arriving laps/workouts).

## Goals / Non-Goals

**Goals:**
- The compact `intervals` summary and the full document are the same reading:
  same source, same shape, same label, same confidence.
- A distilled copy knows when and by what version it was computed, and heals
  itself when it predates its run's laps, workout, or the distiller version.
- Tonight's run is distilled after its laps and workout are in hand.

**Non-Goals:**
- No change to `INTERVAL_VERSION`, `run_intervals`, or any interval document.
- No change to the distilled JSON contract's keys (versioning lives in
  columns, not in the payload — `test_archive_api.mjs` pins the exact key set).
- The Health Connect side keeps its own `INGEST_DISTILL_VERSION` mechanism.

## Decisions

### D1 — versioning in columns, not in the payload or archive_meta

Schema v13 adds `activities.distilled_version INTEGER` and
`activities.distilled_at TEXT`, stamped by `write_distilled`. In-payload
markers would change the served `detail` contract (pinned by exact-key
assertions); an `archive_meta` marker (the HC pattern) is all-or-nothing and
blind to per-run staleness causes. Columns make the work-list one query.

### D2 — the staleness predicate

`runs_missing_distilled(conn, version)` returns runs with raw detail where:

- `detail_distilled_json IS NULL`, or
- `distilled_version IS NULL OR distilled_version < ?` (version bump; NULL
  covers every pre-v13 row → first sync self-heals the archive), or
- `laps_fetched_at > distilled_at` (laps landed after the distill — the same
  clause shape `runs_missing_intervals` already uses), or
- the run's `summary_json.workoutId` references a workout whose banked row's
  `fetched_at > distilled_at` (prescription landed after the distill).

### D3 — pass ordering: archive → workouts → distill → intervals

`_distill_pass` leaves `archive_step` and becomes `distill_step` in `main()`,
after `workouts_step` and before `intervals_step`. `_laps_pass` stays in
`archive_step` (it already runs there; it just no longer races the distill).
With D2 this is belt-and-braces — a missed night heals the next — but zero-lag
is the honest default for "tonight's run".

### D4 — suppliers of laps and workout

`distill_run_detail(det, activity, laps=None, workout=None, work_floor=None)`
stays pure. `_distill_pass` supplies `laps_payload(conn, aid)` and
`workout_payload(conn, summary.workoutId)`. `fetch_run_detail` gains an
optional `conn`; `recent_runs` opens ONE read-only archive connection for its
whole loop (the archive and workout steps have already run by `build_data`)
and passes it down; no archive → both stay `None`, exactly today's behavior.

### D5 — `GARMIN_DISTILL_VERSION = 1`

A new constant in `sync_garmin.py`, bumped whenever the distilled contract or
its inputs change meaning. Starting at 1 with every existing row `NULL`
triggers the one-off full re-distill (~170 runs, stored payloads, no network).

## Risks / Trade-offs

- [First sync re-distills everything → longer sync] → bounded: local-only
  JSON parsing, no network; the recovery pass already does this shape of work.
- [Cockpit sentences change for lap-sourced runs] → that is the fix; the
  briefing reads the same data, so the coach loop sees the corrected reading
  too. Recorded in notes.md with before/after for a spot-check run.
- [Read-only conn inside recent_runs while sync holds no other handle] → the
  steps are sequential in one process; no concurrent writer exists at that
  point (serve.mjs owns the lock for the whole sync).
- [Workout-staleness clause needs the workouts table's fetched_at] → verify
  the column name during implementation; if the banked row carries no
  timestamp, fall back to refreshing workout-referencing runs on version bump
  only, and record the narrowing in notes.md.

## Migration Plan

Schema v12 → v13 via the existing idempotent migration runner (additive
columns, old readers unaffected). Deploy via the standard CI path. Post-deploy:
trigger a sync, then verify distilled coverage is full at version 1, spot-check
one lap-sourced run's cockpit sentence against `/run/:id`, and confirm
`run_intervals` did not move (same sweep as sweep-lens-tail).

## Open Questions

None.
