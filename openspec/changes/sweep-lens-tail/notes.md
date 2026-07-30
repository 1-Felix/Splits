# sweep-lens-tail — implementation notes

## 1.1 Preflight: the gapS == 0 precondition (2026-07-30, read-only)

Swept all 170 production documents' segments on the NUC
(`/data/activity-archive.db`, `mode=ro`):

```
segments gapS==0: 0 | gapS None: 6 | gapS numeric>0: 284
```

**Zero segments carry `gapS == 0`**, so switching `_pace_s_per_km` to return
`None` for non-positive input cannot change any stored document. D2's
precondition holds; no `INTERVAL_VERSION` bump needed.

## 1.2 Production baseline for the post-deploy no-movement check

```
docs: 170
shapes:   {reps: 19, steady: 130, block: 19, progression: 2}
sources:  {stream: 146, laps: 24}
versions: {6: 170}
```

`docker top splits` clean before the sweep (docker-init + node serve.mjs only).
The work floor is not stored in the document (computed at sync time); the
handoff records it as 2.710 at the v6 rescore. The post-deploy check (7.5)
compares shapes/sources/versions and the gapS counts above — all must be
identical.

## 2.1 audit finding — one production segment carries `paceS == 0`

A 3 s / 1 m warmup lap (button-press artifact) in one lap-sourced block
document has `paceS: 0` — from the stream path's `_window_pace(...) or 0`
coercion, not the helper. It never renders (the rep card shows only
work/recovery segments) and every numeric consumer filters falsy paces, so it
moves nothing. Deliberately left: D2's scope is the helper + GAP rendering;
the `or 0` coercions are a pre-existing pattern with zero visible surface.
Recorded so a future `INTERVAL_VERSION` bump's diff is unsurprising if the
helper change turns it `None`.

## Mutation ledger (D5, run 2026-07-30)

| Mutation | Pinned test | Result |
|---|---|---|
| M1: restore cache-before-check order | `test_empty_lap_envelope_is_not_cached_as_fetched` | RED (killed) |
| M7: drop the activities JOIN | `test_orphaned_interval_rows_do_not_inflate_coverage` | RED (killed) |
| N1: restore positional `recs[i]` | run-page demotion case | RED (killed) |
| N6: restore `else 0` | `test_pace_from_a_non_positive_speed_is_none_not_zero` | RED (by construction) |
| `crisp = 1.0` | `test_confidence_crisp_factor_penalises_a_narrow_bout` | RED (killed) |
| `regular = 1.0` | `test_confidence_regular_factor_penalises_a_ragged_set` | RED (killed) |
| delete monotonicity clause | `test_a_non_monotone_ramp_is_not_a_progression_despite_the_gain` | RED (killed) |
| delete `_hr_grid` hold loop | `test_hr_grid_holds_the_last_value_across_sample_gaps` | RED (killed) |
| filter before merge in `find_bouts` | `test_merge_runs_before_the_floors_so_two_half_reps_make_one_rep` | RED (killed) |
| delete `WORK_MIN_S` arm | `test_stream_duration_floor_alone_drops_a_short_fast_burst` | RED (killed) |
| delete `WORK_MIN_M` arm | `test_stream_distance_floor_alone_drops_a_long_slow_surge` | RED (killed) |
| `laps_are_structured` → unconditional `True` | `test_a_real_unstructured_workout_run_is_refused` | RED (killed) |
| `len(intensities) > 1` → `>= 1` | same test (2025-09-14 is uniform ACTIVE) | RED (killed) |

One mutation was initially mis-aimed (flipping the early-exit branch the
fixture never reaches) and survived; it was re-aimed at the two genuinely
permissive directions above, both killed. N2's fixture lives in its own file
(`tests/fixtures/lap_unstructured.json`) because the structured fixture's
population gate asserts `is True` over every entry.

## N7 — /run audited; a PRE-EXISTING /progress failure observed

`/run` passes the audit at 1200/768/390 (scrollWidth exactly 390 at 390 after
the rep-card column compression; before the fix it measured 408 — the
handoff's ~18 px). While running the audit, `/progress` FAILED at 390
(scrollWidth 451). **Verified pre-existing**: a clean stash of this change
fails identically (plus a drill-panel FAIL that is data-dependent — the audit
reads the LIVE garmin-data.js symlink). Out of this change's scope; left for
a follow-up.

## Final verification (7.1–7.3, 2026-07-30)

- Python: `566 passed, 2 skipped` (was 555/2 before this change's tests).
- JS: `test_run_page.mjs`, `test_archive_page.mjs`, `test_coach_read.mjs`,
  `test_archive_api.mjs` — ALL PASS.
- Mutation ledger above: 13 mutations, 13 killed, run against the finished
  code.
