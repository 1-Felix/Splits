## 1. Baseline and fixtures

- [x] 1.1 Capture a fresh production sweep read-only (`shape`, `label`, `source`, `confidence`, `asserts`, `set.found` per document, plus the shape/source counters) and commit it as `baseline-before.md` in this change folder. fix-lap-confidence's baseline is stale — the archive is at `INTERVAL_VERSION` 5 now and carries the verdict. *(170 docs; 92 carry a workoutId.)*
- [x] 1.2 Build `tests/fixtures/workouts.json`: raw Connect workout payloads keyed by the same local dates as `tests/fixtures/lap_workouts.json`, trimmed to the fields the reader consumes (`workoutSegments[].workoutSteps`, `stepType.stepTypeKey`, `type`/`RepeatGroupDTO`, `numberOfIterations`, `endCondition.conditionTypeKey`, `endConditionValue`, `targetType.workoutTargetTypeKey`, `targetValueOne/Two`, `zoneNumber`, `stepOrder`). Cover the five measured shapes: repeat-by-distance with a pace band (`2026-07-10`), repeat-by-time with an HR zone (`2026-02-06`, `2025-11-21`), a no-repeat pyramid (`2026-06-26`), a single-step block (`2026-02-13`), the `ACTIVE`-typed-warmup trap (`2026-06-05`), plus the Z4/Z2/Z4 float trap (`2025-12-05`) and the sub-floor strides (`2026-07-29`, `2025-12-26`). The container's `/tmp/workouts.json` measurement cache is DEAD (container restarted 2026-07-30) — fetch these ~9 payloads one at a time via the cached tokens (`sync_garmin.connect()`), throttled, **after confirming with Felix**; the fetch script pattern is in `design.md` "Rebuilding the cache". *(Felix authorized; fetched 28 payloads — the full superset every test block needs, including the stream-path dates — 0 gone. FOUND during the fetch: `updatedDate` IS populated (the exploration read the wrong key) — design D5 and the provenance spec requirement corrected in place; staleness is now per-run (`updatedDate` vs activity start), proven real by workout 1357916773 backing both `2025-10-17` (stale) and `2025-11-14` (exact).)*
- [x] 1.3 Confirm `test_interval_laps_truth.py` still passes unchanged with the new fixture file present — the additions must pin nothing by accident. *(31 passed.)*

## 2. Schema and acquisition — dark (design D5, D6)

- [x] 2.1 Write the failing tests: `activity_archive` gains `write_workout(conn, workout_id, payload, provenance)` (write-once: an existing row is never overwritten; an empty/falsy payload is refused and NOT cached — the M1 lesson: only bank after a usable payload is confirmed) and `workout_payload(conn, workout_id)`.
- [x] 2.2 Implement the additive `workouts` table (raw payload JSON, `fetched_at`, `provenance` in `{'first-sight','backfill'}`) with a schema-version bump, and the two helpers. No migration of existing rows.
- [x] 2.3 Write the failing test: the acquisition step banks each `summary_json.workoutId` not already stored, exactly once, and never holds a write-capable connection across the network call (fetch first into memory, open, write, close).
- [x] 2.4 Implement `workouts_step` in `sync_garmin.py` beside the laps acquisition: for archived running activities with an unbanked `workoutId`, `get_workout_by_id` once, provenance `first-sight`, fail-soft per workout (a deleted workout warns and skips), offline no-op, only ever inside `safe()`. Wire into `main()` after the archive step.
- [x] 2.5 Implement `--backfill-workouts`: throttled (≥0.15 s between calls), resumable (skips banked ids), provenance `backfill`, out of band from the nightly path. Expect ~85 of 89 with 4 deleted.
- [x] 2.6 Add a workouts line to `--verify-archive` coverage output (banked / referenced / gone counts) so drift is visible.
- [x] 2.7 Mutation-prove 2.2's write-once and refuse-empty rules: overwriting on re-fetch, or caching an empty payload, turns the suite red.

## 3. The step-tree reader (design D6, D7)

- [x] 3.1 Write the failing tests from the spec's scenarios: flatten `workoutSegments[].workoutSteps` depth-first descending into `RepeatGroupDTO` carrying `numberOfIterations` onto its children; a repeat group consumes one index position AFTER its children (warmup 0, repeated pair 1 and 2, cooldown 4); a no-repeat workout maps consecutive from zero.
- [x] 3.2 Implement the flattener + index mapper in `interval_lens.py` (the engine stays pure: raw payload in, prior out, no database). Note `zoneNumber` is load-bearing — `heart.rate.zone` targets carry intensity there, not in `targetValueOne/Two`.
- [x] 3.3 Write the failing test: an observed `wktStepIndex` with no corresponding flattened step discards the prior for that activity ENTIRELY — the document is built by inference alone and records the absence. A partial mapping is never used.
- [x] 3.4 Implement per-activity validation (all-or-nothing), and verify the mapping reproduces `2026-06-05`, `2026-07-10` and `2026-07-29` exactly against the real fixtures. *(The whole 28-pair population maps except `2025-10-17` — the stale-edit case, refused STRUCTURALLY by the all-or-nothing rule: the payload edited 2025-11-14 has four executable steps where that run observed five. Same payload maps cleanly for `2025-11-14`.)*
- [x] 3.5 Mutation-prove: dropping the consume-after-repeat rule (mapping `out` positions straight to `wktStepIndex`) turns the suite red on the repeat-group fixture. *(13 tests fail with the consume-after-repeat rule dropped; reverted green.)*

## 4. The prior sits upstream of the branch (design D4)

- [x] 4.1 Write the failing test: `build_document` resolves the prior BEFORE the laps/stream branch — a lap-sourced document from a run with a prescribed set carries `set.prescribed = numberOfIterations` (today the laps branch hardcodes `"prescribed": None` at ~line 900).
- [x] 4.2 Restructure `build_document`: derive the prior from the raw workout payload (new `workout` parameter, default None) ahead of the branch; both paths read one prior contract. `ingest_builder` continues to pass no workout and its behaviour is unchanged — add the guard test. *(`prior` param replaced by `workout` — the raw payload; all callers passed None positionally. `derive_intervals` passes the banked payload; `runs_missing_intervals` gains a workout clause mirroring the lap clause so a late-banked workout triggers one rescore.)*
- [x] 4.3 Unify the rep-count floor (retires handoff P2.7b and P3.1): `max(2, min(REPS_MIN_COUNT, expect_reps))` where a prior expects a set, on BOTH paths. `2026-06-05` must stop reading `"2 reps"` via the lap path's bare `>= 2`. *(The handoff's `max(2, min(REPS_MIN_COUNT, expect))` formula still reads 3 at expect 4 and cannot report the 2-of-4 case it was written for — implemented as `2 if expect >= 2 else REPS_MIN_COUNT`, recorded in `_reps_min`'s docstring. Three synthetic tests that pinned the lap path's bare `>= 2` moved to 3-rep fixtures.)*
- [x] 4.4 Write the failing test (design D10): a workout begun and abandoned — warm-up executed, no rep laps — reports `found: 0, prescribed: N`, not `steady` with no set. *(Plus the 2-of-4 bailed case and an unprescribed-2-laps pin.)*
- [x] 4.5 Mutation-prove: reverting the floor unification (lap path back to bare `>= 2`) turns the suite red. *(`>= 2` restored → `test_two_unprescribed_work_laps_are_not_a_set` fails; reverted green.)*

## 5. VETO — a prescribed easy step is never work (design D2)

- [ ] 5.1 Write the failing tests: a step whose target VALUE is HR zone ≤ 2 cannot be reported as a rep or a block, whatever its `stepTypeKey` says — `2026-06-05`'s warm-up is typed `interval` and the veto still fires; `2026-01-16` collapses from `"2-1-2 km" found 3` to its one prescribed rep; `2025-12-24`/`2026-04-29` read `steady`.
- [ ] 5.2 Write the failing guard test: Z3 is deliberately NOT vetoed — `2025-12-14` (14 km @ HR Z3) keeps its `progression` reading.
- [ ] 5.3 Implement the veto, reading the target's value (`zoneNumber`), never the step type.
- [ ] 5.4 Mutation-prove both directions: widening the veto to Z3 turns the suite red (5.2), and deleting it turns the suite red (5.1).

## 6. Set membership by target VALUE, not type (design D3)

- [ ] 6.1 Write the failing test: `2025-12-05` (Z4 2 km / Z2 float / Z4 2 km — all three on `heart.rate.zone`) reads 2 reps with a recovery between, `found: 2`, not `"2-0.32-2 km" found 3`.
- [ ] 6.2 Write the failing guard test: the genuine pyramid (`2026-06-26`, three sizes sharing `pace.zone` AND near-identical bands) still reads all three as one varied set.
- [ ] 6.3 Implement grouping by target type + value (pace band, or zone number). Only the 11 no-repeat multi-work-step workouts reach this rule.
- [ ] 6.4 Mutation-prove: comparing type alone (the first-draft rule the design records as wrong) turns the suite red on 6.1.

## 7. ADMIT — a prescribed rep is a rep regardless of size (spec, handoff N4)

- [ ] 7.1 Write the failing tests: `2026-07-29` reads `4×20 s` (not `"32 min block"`) and `2025-12-26` reads `4×30 s` (not `"24 min block"`) — the prescribed reps are exempt from `WORK_MIN_S`/`WORK_MIN_M`.
- [ ] 7.2 Implement the exemption: the size floors keep rejecting fragments the detector invented; they never reject laps executing a prescribed rep step.
- [ ] 7.3 Verify the interaction with fix-lap-confidence's materiality rule: once the strides are admitted, nothing material is discarded and both documents assert their now-correct shape.
- [ ] 7.4 Mutation-prove: re-applying the floor to prescribed reps turns the suite red.

## 8. POINT — locate from the prescription, confirm from execution (design D1a)

- [ ] 8.1 Write the failing tests for the three missed tempos (`2026-01-09`, `2026-02-13`, `2026-02-27`): a prescribed single block is found by sliding a window of exactly the prescribed size; the best window's mean pace falls in the prescribed band; the document reads `block`, boundaries from the window. These need stream fixtures — build them from the local archive's real streams (it HAS streams; it lacks only laps).
- [ ] 8.2 Write the failing tests for the three fragmented tempos (`2026-01-23`, `2026-03-13`, `2026-04-03`): the same window rule absorbs the fragments with no second mechanism.
- [ ] 8.3 Write the SAFETY test before implementing: a run that plodded the prescribed window out of band (synthetic 7:00/km) refuses the block and falls back to inference — step 3 of D1a is the entire honesty property.
- [ ] 8.4 Implement POINT with the within-window variance guard in place and its threshold deliberately conservative (design Open Question 1 — no archive case can set it honestly; a flat window confirms, a hard/easy rep pattern must not).
- [ ] 8.5 `2026-01-23`'s 304 s mid-block gap: the merged block is HEDGED, never asserted — the case D8 split the two changes over. Write the test on the real stream fixture.
- [ ] 8.6 POINT never consults the calibration floor (closes handoff P2.3 — `2026-01-09`'s band sits below the floor and must be found anyway).
- [ ] 8.7 Mutation-prove: breaking the band check (always confirm) turns the suite red via 8.3; breaking the variance guard (never guard) turns the suite red via its synthetic case.

## 9. Time-prescribed sets are named by time (spec, handoff N3)

- [ ] 9.1 Write the failing tests: `2026-02-06` reads `6×90 s` (not `6×0.23 km`) and `2025-11-21` reads `8×90 s` (not `8×200 m`) — `endCondition: time` names and compares the set by duration.
- [ ] 9.2 Implement the duration form in `_reps_label` and the set naming path; `set.nominalDistM` semantics stay intact for distance-prescribed sets.
- [ ] 9.3 Confirm handoff N4's one-metre margin dissolves: `2025-11-21` lap 8 (151 m vs the 150 m floor) is admitted by its 90 s prescription, not by luck.

## 10. Confidence corroboration and provenance (design D5, D8)

- [ ] 10.1 Write the failing tests, extending fix-lap-confidence's levels: a prescription that corroborates (`found == prescribed`) asserts; a prescription that disagrees hedges; a POINT block merged across a gap hedges (8.5).
- [ ] 10.2 Implement, on top of `_lap_confidence`/`_verdict` — the assert threshold comparison stays in exactly one place.
- [ ] 10.3 Write the failing tests: the document records where its prescription came from — `first-sight` with full authority, `backfill` marked best-effort (silent edits undetectable, `updateDate` is None on every workout), and explicit absence when no workout exists.
- [ ] 10.4 Implement the provenance marker in the document; `compact()` carries it to the cockpit.
- [ ] 10.5 Mutation-prove: inverting corroboration (disagreement asserts) turns the suite red.

## 11. Version bump and local verification

- [ ] 11.1 `INTERVAL_VERSION` → 6 with a history comment (the design says 5, but fix-lap-confidence took 5 on 2026-07-30 — note this in the comment), and update `test_interval_version_is_current`.
- [ ] 11.2 `rm -rf __pycache__` then `.venv/Scripts/python.exe -m pytest -q` — full suite green. The `rm` is not optional here.
- [ ] 11.3 Browser suites green: `node test_run_page.mjs`, `node test_archive_page.mjs`, `node test_coach_read.mjs`.
- [ ] 11.4 Confirm `test_ingest_builder.py` green — the Health Connect path passes no workout and must be byte-stable.

## 12. Deploy and verify against production

- [ ] 12.1 Merge to `main`, `gh run watch <id> --exit-status`, then on the NUC: `docker top splits` FIRST (orphan check), `docker compose pull splits && docker compose up -d splits`. Never wrap `ssh … docker …` in a client-side `timeout`.
- [ ] 12.2 Run `--backfill-workouts` once, out of band (confirm with Felix first — ~89 authenticated calls against his account). Expect ~85 banked, 4 gone.
- [ ] 12.3 `curl -s -X POST http://localhost:5732/api/sync` — the recompute rescores all ~170 documents at v6.
- [ ] 12.4 Re-run the sweep and diff against `baseline-before.md`. Expected movement is EXACTLY the named set and nothing else: the 3 missed tempos → `block`; the 3 fragmented tempos → one `block` each (`2026-01-23` hedged); `2025-12-24`, `2026-04-29`, `2026-04-01` → `steady`; `2026-07-29` → `4×20 s` and `2025-12-26` → `4×30 s` (both asserting again); `2026-06-05` → its prescribed tempo (warm-up demoted); `2026-01-16` → one rep; `2025-12-05` → `found: 2`; `2026-02-06` → `6×90 s`; `2025-11-21` → `8×90 s`. The 12 prescribed-count-matching sets must be untouched. Anything else moving is a defect.
- [ ] 12.5 `--verify-archive` exits 0; `docker top splits` clean.
- [ ] 12.6 Load `/run/:id` for `2026-07-29` (now `4×20 s`, asserting) and `2026-01-16` (one rep) and confirm the pages match the documents.
- [ ] 12.7 Update the interval-lens memory + handoff: N3, N4, N5, P2.7b, P3.1 closed; P2.3's windowed baseline formally retired; the archive-side sweep baseline updated.
