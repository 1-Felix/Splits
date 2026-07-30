# fix-distill-parity — implementation notes

## What the code verification added to the handoff's picture

M8 was worse than recorded: `_distill_pass` ran inside `archive_step` BEFORE
`_laps_pass` (same function, lines below it) and before `workouts_step`
(main), so a new run's stored compact was distilled without laps AND without
its prescription — and the `IS NULL` gate meant it never healed. The cockpit's
recent-runs path had the same blindness on every nightly rebuild.

## Decisions taken during implementation

- `workouts.fetched_at` exists (design D2's risk about the column name did not
  materialise) — the late-workout clause shipped as designed.
- `write_distilled` stamps `distilled_at` on every write and takes an optional
  `version`; the Health Connect builder passes none, keeping its own
  `INGEST_DISTILL_VERSION` marker mechanism intact (its rows carry NULL
  version, which is only ever consulted by the Garmin `_distill_pass` — a
  different archive file entirely).
- `distill_step` re-runs `_record_expectations` so the distilled-coverage
  ratchet counts the fresh distills in the same sync (archive_step records
  before the distill now; the ratchet is max-only either way).
- The parity test needed its own raw-detail fixture: `_steady_detail` carries
  no `sumDuration`/`directSpeed`, so the lens sees no usable stream from it.

## Mutation ledger (run 2026-07-30, all against finished code)

| Mutation | Pinned test | Result |
|---|---|---|
| restore `laps=None, workout=None` in the distiller | `test_distilled_compact_agrees_with_the_lap_sourced_document` | RED (killed) |
| delete the version clause | `test_distilled_staleness_clauses` | RED (killed) |
| delete the late-laps clause | same | RED (killed) |
| delete the late-workout clause | same | RED (killed) |
| delete the `distill_step` call in `main()` | `test_sync_distills_after_workouts_and_before_intervals` | RED (killed) |

The ordering mutation SURVIVED on the first pass — the behavioral test calls
`distill_step` directly, so nothing pinned `main()`'s invocation. The
source-order test above was added for exactly that; crude, but it is the only
thing that goes red when the step is dropped or moved.

## Suite at merge

Python `569 passed / 2 skipped`; `test_run_page.mjs`, `test_archive_page.mjs`,
`test_coach_read.mjs`, `test_archive_api.mjs` ALL PASS. The by-id `detail`
exact-key assertion is untouched — versioning lives in columns, not payload.

## Post-deploy (2026-07-30, NUC)

The first sync after deploy re-distilled the archive as designed: **171/171
distilled rows at distill version 1**. The spot-check run — `2026-07-29`, the
`5km easy + 4x20s strides` session this whole arc began with:

```
BEFORE  {"shape": "steady", "label": null,     "source": "stream", "version": 4}
AFTER   {"shape": "reps",   "label": "4×20 s", "source": "laps",   "version": 6}
```

The cockpit now reads the run exactly as /run/:id does. `verify_archive`
exit 0. `run_intervals` untouched: 170 docs, `steady 130 / reps 19 / block 19
/ progression 2`, sources `stream 146 / laps 24`, all at v6, `gapS==0` still
0 of 290 segments.
