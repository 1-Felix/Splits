## 1. Schema v13

- [ ] 1.1 Add `distilled_version INTEGER` and `distilled_at TEXT` to
      `activities` via the idempotent migration runner; bump `schema_version`
      to 13. Verify the workouts table's fetched-at column name for D2's
      fourth clause (fall back per design if absent).
- [ ] 1.2 Migration test: a v12 archive opens at v13 with both columns present
      and every existing row NULL; a second open is a no-op.

## 2. Distiller parity (M8)

- [ ] 2.1 `distill_run_detail(det, activity, laps=None, workout=None,
      work_floor=None)` — pass laps + workout to `build_document`; docstring
      records the parity contract.
- [ ] 2.2 `_distill_pass` supplies `laps_payload` / `workout_payload` from the
      archive connection.
- [ ] 2.3 `fetch_run_detail` gains an optional archive connection;
      `recent_runs` opens ONE read-only connection for its loop and passes it
      down; both laps and workout stay None when the archive is unreachable.
- [ ] 2.4 Parity test: a run with structured laps distilled via the archive
      path carries `intervals.source == "laps"` and the same label as the full
      document; mutation — restore `laps=None` at the build_document call →
      red.

## 3. Versioned staleness (P2.4)

- [ ] 3.1 `GARMIN_DISTILL_VERSION = 1` in sync_garmin.py;
      `write_distilled(conn, aid, distilled, version, at)` stamps both columns.
- [ ] 3.2 `runs_missing_distilled(conn, version)` implements D2's four
      staleness clauses.
- [ ] 3.3 Tests, each mutation-proven: NULL-version rows are stale (the
      self-heal); an older version is stale; `laps_fetched_at > distilled_at`
      is stale; a workout banked after `distilled_at` is stale; a current,
      complete row is NOT stale (the pass stays idempotent).

## 4. Pass ordering

- [ ] 4.1 `_distill_pass` leaves `archive_step`; a `distill_step` runs in
      `main()` after `workouts_step`, before `intervals_step`.
- [ ] 4.2 Ordering test (or assertion on the step list if one exists): distill
      runs after laps + workouts, before intervals.

## 5. Verification and ship

- [ ] 5.1 `rm -rf __pycache__ && .venv/Scripts/python.exe -m pytest -q` green;
      `node test_run_page.mjs`, `test_archive_page.mjs`, `test_coach_read.mjs`,
      `test_archive_api.mjs` green (the by-id `detail` exact-key assertion
      must NOT change — versioning is columns-only).
- [ ] 5.2 Re-run every mutation in this change's tests; record in notes.md.
- [ ] 5.3 Merge → CI → NUC deploy. Trigger a sync (`POST /api/sync`); confirm
      the one-off full re-distill completes.
- [ ] 5.4 Post-deploy: distilled coverage full at version 1; spot-check a
      lap-sourced run (e.g. the 4×20 s strides run) — cockpit sentence agrees
      with /run/:id; `run_intervals` distribution unchanged (same sweep as
      sweep-lens-tail); `verify_archive` exit 0.
- [ ] 5.5 Update HANDOFF-interval-lens.md (M8 + P2.4 closed) and notes.md
      (before/after cockpit sentence for the spot-check run).
