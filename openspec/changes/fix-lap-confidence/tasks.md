## 1. Baseline and fixtures

- [x] 1.1 Capture the current production sweep read-only (`shape`, `label`, `source`, `confidence` per document, plus the shape/source counters) and commit it into this change folder as `baseline-before.md`. This is the diff target for 7.3 — shapes and labels must not move at all.
- [x] 1.2 Extend `tests/fixtures/lap_workouts.json` with the two size-discard cases: `2026-07-29` (`5km easy + 4x20s strides`) and `2025-12-26` (`4×30 s`), trimmed to the fields the engine reads. Note the local `activity-archive.db` has NO lap payloads — pull these from the NUC, read-only. *(2025-12-26 was already in the fixture; only 2026-07-29 was new — two activities share that date, so the pull keyed by activity_id 23771823931.)*
- [x] 1.3 Extend the same fixture with at least two cases that must NOT hedge: one step-demotion set (`2026-04-10` or `2025-10-17`, where change 2's rule demoted an ACTIVE lap) and one clean repeated-step set with a trailing fragment (`2026-07-10`). *(All already present in the 23-entry fixture; verified their laps carry the needed evidence — full-size demoted laps on 2026-04-10/2025-10-17, `wktStepIndex: None` trailing fragments on 2026-07-10/2026-06-05.)*
- [x] 1.4 Confirm `test_interval_laps_truth.py` still passes unchanged against the enlarged fixture, so the additions are additive and pin nothing new by accident. *(21 passed.)*

## 2. Discard bookkeeping — the two filters are distinct (design D1)

- [x] 2.1 Write the failing test: `_lap_rep_segments` reports which work segments the SIZE floor rejected separately from those the STEP rule rejected.
- [x] 2.2 Implement it — surface the two discard sets alongside the segments. `sized`, `steps` and `survivors` already exist as locals at `interval_lens.py:642-647`; this exposes them rather than deriving anything new. *(Survivor selection extracted into `_lap_survivors(segments, laps, size_floor=True)` so design D2's materiality check can re-run it with the floor lifted; `_lap_rep_segments` returns `(segments, {"size": …, "step": …})`.)*
- [x] 2.3 Verify the existing contract is untouched: the `assert len(segments) == len(laps)` invariant, one segment per lap in order, every segment's `t0/t1/d0/d1` chaining with no gap, and `rep` renumbering 1..N over survivors. *(All pre-existing `_lap_rep_segments` and whole-fixture span-coverage tests pass unchanged.)*
- [x] 2.4 Update every call site of `_lap_rep_segments` and confirm no other module reaches into it. *(One call in `build_document`, seven in `test_interval_lens.py`; no other module references it.)*
- [x] 2.5 Mutation-prove: collapsing the two discard sets into one turns the suite red. *(`{"size": size|step, "step": set()}` → `test_lap_rep_segments_reports_size_and_step_discards_separately` fails; reverted green.)*

## 3. Materiality — a discard only counts if it decided something (design D2)

- [x] 3.1 Write the failing test: on the `2026-07-29` fixture, lifting the size floor changes the survivor set from `{lap 1}` to `{laps 3,5,7,9}` — material. *(Plus the same test for `2025-12-26`: `{9}` → `{1,3,5,7}`.)*
- [x] 3.2 Write the failing test: on the `2026-07-10` and `2026-06-05` fixtures, the trailing sub-floor fragment carries no `wktStepIndex`, so the step rule drops it either way and the survivor set is unchanged — immaterial.
- [x] 3.3 Implement the materiality check by re-running survivor selection with the size floor lifted and comparing survivor sets. Pure, no state. *(`_size_discard_is_material` — two `_lap_survivors` calls.)*
- [x] 3.4 Mutation-prove both directions: replacing the check with `True` (always hedge) turns the suite red, and replacing it with `False` (never hedge) turns the suite red. A check that only fails one way is not tested. *(`True` → both immaterial tests fail; `False` → both material tests fail; reverted green.)*

## 4. Confidence levels and the assert verdict (design D3, D4)

- [x] 4.1 Write the failing test: lap-sourced confidence is no longer constant — two lap-sourced documents with different evidence do not carry the same value.
- [x] 4.2 Write the failing test: a set whose shape depends on a STEP demotion still asserts (spec: device-corroborated demotion never lowers confidence). *(`2026-04-10` and `2025-10-17`.)*
- [x] 4.3 Write the failing test: every fixture set whose `found` matches its prescribed count asserts. This is the anti-regression guard — over-broad hedging is the main way this change could do damage. *(Strengthened: every fixture document except the two material cases asserts — the 12 prescribed-count matches are a subset.)*
- [x] 4.4 Implement the three levels — corroborated / structured / eliminated — in the laps branch, replacing the literal `"confidence": 1.0` at `interval_lens.py:878`. *(`_lap_confidence(raw_segments, laps) -> (level, value)`; corroborated and structured share 1.0 deliberately — design open question 1 defers the numeric split to add-workout-prior — so production confidence moves ONLY on the two eliminated documents.)*
- [x] 4.5 Add the assert verdict to the document in `base` so BOTH producers carry it, and make `CONFIDENCE_ASSERT_MIN` the single place the comparison happens. *(`asserts` is stamped by `_verdict()` — the one comparison — on both branch returns; it cannot literally live in `base` because confidence is branch-computed, but both producers and both paths carry it.)*
- [x] 4.6 Mutation-prove: hardcoding the level back to `corroborated` turns the suite red; so does inverting the verdict. *(Eliminated made unreachable → 4 tests fail; verdict inverted → 6 fail across lap AND stream paths; reverted green.)*

## 5. Contract, page, and the second version marker

- [ ] 5.1 `validate_data.py` (~line 320, beside the existing `intervals.shape` check): assert the verdict field's presence and type on `detail.intervals`.
- [ ] 5.2 `run.dc.html:550` — replace `iv.confidence != null && iv.confidence < 0.5` with a read of the verdict. Delete the literal; this closes handoff **M2**.
- [ ] 5.3 `test_run_page.mjs`: a hedged document renders "possible structure" and an asserting one does not. Mutation-prove the assertion CAN fail — handoff records a page assertion that could not, because a `flex:1` spacer absorbed the delta it measured.
- [ ] 5.4 Bump `INGEST_DISTILL_VERSION` (`ingest_builder.py:642`) — the verdict lands in `base`, so Health Connect documents change shape too and their stored distilled detail must be recomputed. Confirm `test_ingest_builder.py` still passes.
- [ ] 5.5 Note in the change folder that the Garmin side has no equivalent marker (handoff **P2.4**), so `detail_distilled_json.intervals` will not gain the verdict retroactively there. Out of scope; recorded so it is not rediscovered.

## 6. Version bump and local verification

- [ ] 6.1 `INTERVAL_VERSION` → 5 with a comment naming this change, in the existing running-history style at the top of `interval_lens.py`.
- [ ] 6.2 `rm -rf __pycache__` then `.venv/Scripts/python.exe -m pytest -q` — full suite green. The `rm` is not optional: a stale `.pyc` has twice made a must-fail test pass.
- [ ] 6.3 Browser suites green: `node test_run_page.mjs`, `node test_archive_page.mjs`, `node test_coach_read.mjs`.
- [ ] 6.4 `node tools/style-audit.mjs layout` unchanged (it does not visit `/run` — handoff N7 — so this only confirms no collateral damage).

## 7. Deploy and verify against production

- [ ] 7.1 Merge to `main`, then `gh run watch <id> --exit-status`. Deployment is CI-mediated; there is no direct-push path.
- [ ] 7.2 `ssh felix@192.168.0.37` then `docker top splits` FIRST to check for orphans. Never wrap `ssh … docker …` in a client-side `timeout`.
- [ ] 7.3 `docker compose pull splits && docker compose up -d splits`, then `curl -s -X POST http://localhost:5732/api/sync` (serve.mjs owns the sync lock).
- [ ] 7.4 Re-run the sweep and diff against `baseline-before.md`. **Every shape and label must be identical** — this change alters only confidence. Any shape movement is a defect, not a surprise.
- [ ] 7.5 Confirm the only confidence movement is `2026-07-29` and `2025-12-26` dropping below the assert threshold, and that all 12 prescribed-count-matching sets still assert.
- [ ] 7.6 `--verify-archive` exits 0, and `docker top splits` shows no orphaned process afterwards.
- [ ] 7.7 Load `/run/:id` for `2026-07-29` and confirm it now says "possible structure" rather than asserting a 32-minute block.
