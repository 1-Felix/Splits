# Proposal: sweep-lens-tail

## Why

After `fix-lap-confidence` (v5) and `add-workout-prior` (v6) shipped on 2026-07-30, a
2026-07-30 verification pass measured every remaining open item in
`docs/superpowers/HANDOFF-interval-lens.md` against the code at `3f0b9ff`. What
survives is a tail of small, verified defects and known-dead test coverage — several
of which became *more* reachable after v6 (mid-set demotions now exist, so the rep
card's positional recovery pairing has live trigger conditions). The race is
2026-08-09: this sweep deliberately contains **no `INTERVAL_VERSION` bump and no
document movement** — every fix is acquisition-, serving-, display-, or test-side.

## What Changes

- **M1** — `sync_garmin._fetch_raw_laps` no longer caches an empty `{"lapDTOs": []}`
  envelope; the cache is written only after confirming a non-empty lap list. An
  empty reply is refetched on later syncs instead of permanently starving the
  backfill queue. (The newer `_workouts_pass` already follows this rule and cites
  "the M1 lesson"; this applies it to the code that taught the lesson.)
- **N1** — `run.dc.html`'s rep card pairs each rep with the recovery segment whose
  span follows it in time (first recovery with `t0 >= rep.t1` before the next rep),
  replacing the positional `recs[i]` join that mis-pairs after any mid-set demotion.
- **M4** — `serve.mjs` exposes `lensVersion` on the archive run list and the
  single-run interval document read, matching what the block and course endpoints
  already do. Expose, not filter: the API stays available across a version bump and
  consumers can detect staleness.
- **M5 + N6, together** — `interval_lens._pace_s_per_km` returns `None` (not `0`)
  for non-positive input, and `run.dc.html` renders the em dash on `gapS == null`
  rather than on falsiness. Done as a pair because either half alone makes the other
  half's bug worse (a bogus `0` would render as a real pace). A read-only production
  sweep verifies no archived document carries `gapS == 0`, which is why no
  `INTERVAL_VERSION` bump is required.
- **M6** — the `work_floor` parameter of `build_document` is renamed so it no longer
  shadows the module-level `work_floor()` function (3 call sites).
- **M7** — `activity_archive.intervals_coverage` joins `run_intervals` back to
  `activities`, so orphaned interval rows can no longer inflate `scored` past
  `streamed_runs`.
- **M9** — the "the two producers cannot drift on what Z4 means" comment is
  corrected to state what is actually unified (the fractions) and what deliberately
  differs per spec (the zone model: %max for Garmin, Karvonen for Health Connect).
- **Test-debt bundle** (pure additions, each mutation-proven before it counts):
  - pin the `crisp` and `regular` confidence factors independently (P2.5);
  - a non-monotone-but-gaining fixture proving `_is_progression`'s monotonicity
    clause (P2.6a);
  - an HR-gap fixture proving `_hr_grid`'s sample-and-hold (P2.6c);
  - an order-sensitive fixture proving `find_bouts`' merge-then-filter order
    (P2.6d);
  - stream-side separation of `WORK_MIN_S` from `WORK_MIN_M` (M12, matching the
    lap-side test that already exists);
  - one real known-unstructured workout added to the lap fixture with a
    `laps_are_structured(...) is False` assertion (N2);
  - `test_interval_truth.py` imports `_RUN_TYPE_SQL` instead of re-hardcoding the
    predicate (M10).
- **N7** — `tools/style-audit.mjs` visits `/run/:id` (resolving a real run id at
  audit time), and the pre-existing ~18 px horizontal overflow of `.card.rep-table`
  at 390 px is fixed.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `archive-api`: the run listing and single-run interval document responses carry
  `lensVersion`, so a consumer can detect a stale document between an
  `INTERVAL_VERSION` bump and the next sync (parity with block/course endpoints).
- `run-detail`: the rep card's recovery line is paired to its rep by time, not by
  array position; an absent grade-adjusted pace renders as an em dash only when the
  value is absent (`null`), never for a genuine numeric value.
- `activity-archive`: a lap-detail reply with an empty `lapDTOs` list is not
  permanently cached as fetched; interval coverage counts only interval rows that
  still join to a live activity.

## Impact

- `sync_garmin.py` (M1), `interval_lens.py` (N6, M6, M9 — helper edge case, rename,
  comment; no scoring behavior change), `activity_archive.py` (M7), `serve.mjs`
  (M4), `run.dc.html` (N1, M5), `tools/style-audit.mjs` + run-page CSS (N7).
- Test files: `test_interval_lens.py`, `test_interval_truth.py`,
  `test_interval_laps_truth.py`, `tests/fixtures/lap_workouts.json`.
- No schema change, no `INTERVAL_VERSION` bump, no recompute, no migration. The
  production document set is byte-identical before and after this change (verified
  by the read-only sweep).
