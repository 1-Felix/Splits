## 1. Preflight evidence (read-only, against production)

- [x] 1.1 Run a read-only sweep on the NUC asserting no archived document carries
      `gapS == 0` in any segment (D2's precondition). Record the count in the
      change's notes.md. If any exists, STOP and re-decide D2 with Felix.
- [x] 1.2 Record the current production distribution baseline in notes.md
      (`steady 130 / reps 19 / block 19 / progression 2`, sources, floor 2.710)
      for the post-deploy no-movement check.

## 2. Engine-adjacent fixes (no scoring change)

- [x] 2.1 M5+N6: `_pace_s_per_km` returns `None` for non-positive input; audit
      every call site for `None`-safety (labels, `set_stats`, laps segments).
- [x] 2.2 M5+N6: `run.dc.html` renders GAP with `s.gapS != null` instead of
      truthiness.
- [x] 2.3 M6: rename `build_document`'s `work_floor` parameter so it no longer
      shadows the module-level `work_floor()`; update the 3 call sites.
- [x] 2.4 M9: correct the zone-model comment at both locations (fractions
      unified; model deliberately differs per spec — %max Garmin, Karvonen HC).
- [x] 2.5 Run `rm -rf __pycache__ && .venv/Scripts/python.exe -m pytest -q` —
      full suite green before moving on.

## 3. Acquisition and serving fixes

- [x] 3.1 M1: `_fetch_raw_laps` writes the cache only when `lapDTOs` is a
      non-empty list; empty/absent list leaves no cache entry.
- [x] 3.2 M1: test — an empty envelope is not cached and the run stays eligible;
      a populated reply is cached write-once. Mutation-prove by restoring the
      old cache-first order and observing red.
- [x] 3.3 M7: `intervals_coverage` joins `run_intervals` to `activities`; test
      with an orphaned interval row asserting `scored` excludes it (mutation:
      drop the join, observe red).
- [x] 3.4 M4: archive list JOIN selects `i.lens_version` and rows carry
      `lensVersion`; by-id interval read returns `lensVersion` alongside the
      document. No filtering.
- [x] 3.5 M4: extend the API tests (or `test_run_page.mjs`/`test_archive_page.mjs`
      if that is where API assertions live) to pin `lensVersion` presence on
      both reads. (Landed in `test_archive_api.mjs` — list row
      `intervalLensVersion`, by-id `lensVersion`, and absence on a run with no
      document.)

## 4. Rep card pairing (N1)

- [x] 4.1 Replace `recs[i]` in `run.dc.html` with the time join from design D3
      (first recovery with `t0 >= work[i].t1`, before `work[i+1].t0` when it
      exists; no match → no recovery line).
- [x] 4.2 Add a `test_run_page.mjs` case with a mid-set demotion fixture (a
      `recovery`-role segment between two reps) asserting the later reps pair
      with the recoveries that actually follow them. Mutation-prove by
      restoring the positional join and observing red.

## 5. Test-debt bundle (each mutation-proven before it counts)

- [x] 5.1 P2.5: fixture pair pinning `crisp` — identical separation and
      regularity, different edge crispness; mutation: `crisp = 1.0` → red.
- [x] 5.2 P2.5: fixture pair pinning `regular` — identical separation and
      crispness, different bout-width variance; mutation: `regular = 1.0` → red.
- [x] 5.3 P2.6a: non-monotone-but-gaining stream fixture asserting NOT
      `progression`; mutation: delete the monotonicity clause → red.
- [x] 5.4 P2.6c: stream fixture with HR sample gaps (~2 s cadence) asserting the
      held HR grid / `quality.zone`; mutation: delete sample-and-hold → red.
- [x] 5.5 P2.6d: fixture where filter-before-merge changes the outcome (two
      sub-floor bouts that merge into a passing bout); mutation: swap order →
      red.
- [x] 5.6 M12: stream-side fixtures separating `WORK_MIN_S` from `WORK_MIN_M`
      (long-but-slow fails M only; short-but-fast fails S only); mutations:
      delete each arm → red.
- [x] 5.7 N2: add one real known-unstructured workout (from the ~101 excluded
      `laps_json` rows, trimmed like the existing 23) to
      `tests/fixtures/lap_workouts.json` with a
      `laps_are_structured(...) is False` test; mutation: predicate returns
      `True` unconditionally → red.
- [x] 5.8 M10: `test_interval_truth.py` imports `_RUN_TYPE_SQL` from
      `activity_archive` instead of re-hardcoding the predicate.

## 6. Run-page audit coverage (N7)

- [x] 6.1 `tools/style-audit.mjs`: resolve the most recent run with an interval
      document via the server's list endpoint and audit `/run/<id>` at the same
      widths as the other deep views; report skipped (not failed) when no run
      resolves.
- [x] 6.2 Fix the ~18 px `.card.rep-table` horizontal overflow at 390 px at its
      source (prefer letting rep rows compress; `overflow-x: auto` on the card
      only if the table genuinely cannot).
- [x] 6.3 Run `node tools/style-audit.mjs layout` and confirm `/run` passes at
      390 px with zero horizontal overflow.

## 7. Verification and ship

- [x] 7.1 `rm -rf __pycache__ && .venv/Scripts/python.exe -m pytest -q` — full
      Python suite green.
- [x] 7.2 `node test_run_page.mjs && node test_archive_page.mjs &&
      node test_coach_read.mjs` — all green.
- [x] 7.3 Re-run every mutation in design D5's table one final time on the
      finished branch; record each red in notes.md.
- [ ] 7.4 Merge to `main`, `gh run watch` the docker-publish build,
      `docker compose pull && up -d` on the NUC (check `docker top splits` for
      orphans first).
- [ ] 7.5 Post-deploy read-only sweep: document distribution byte-identical to
      the 1.2 baseline (no shape, source, or floor movement); `verify_archive`
      exit 0; spot-check `/run/:id` lensVersion and a rep card in the browser.
- [ ] 7.6 Update HANDOFF-interval-lens.md: mark the swept items closed, note
      M8+P2.4 as the next change.
