## 1. The parser and its corpus

- [ ] 1.1 Extract the live plan's distinct `val` strings (read-only on the
      symlink) into `tests/fixtures/plan_vals.json`, each mapped to its
      expected parse or `null` (refusal).
- [ ] 1.2 `plan_prescription.py`: `prescription_for_day(segments) -> dict | None`
      per design D1 — rep sets (distance, time, zone/effort, embedded form;
      `×`/`x`, `–`/`-`; single pace → ±5 s/km band) and `@ ~pace` steady
      targets; first rep set wins; everything else refused.
- [ ] 1.3 `test_plan_prescription.py`: the fixture sweep (every string pins its
      shape or refusal) + targeted grammar cases. Mutation-prove at least:
      band widening (drop the ±5 → red), embedded extraction (return first
      segment only → red), refusal honesty (parse HR bands as steady → red).
- [ ] 1.4 Corpus-currency test: re-extract distinct strings from plan-data.js
      at test time; an unpinned new string fails with a message naming it.

## 2. The verdict in compliance

- [ ] 2.1 Schema v14: guarded ALTER adds `plan_compliance.quality_json TEXT`;
      migration test (both columns present, second open no-op).
- [ ] 2.2 `plan_compliance`: compute the verdict per design D2 when a matched
      run day has a parsed prescription — reading the activity's interval
      document from `run_intervals`; write `quality_json`. `COMPLIANCE_VERSION
      = 2`.
- [ ] 2.3 Tests with synthetic documents: complete set in band; bailed 2-of-4;
      out-of-band reps; zone set (quality.zone match and mismatch); steady
      target on/off; no interval document (honest verdict); non-parse day
      (quality_json NULL).
- [ ] 2.4 D3 annotate-only pin: two identical days, one with a parseable
      prescription — `status` and `reason` byte-identical. Mutation: make the
      verdict writer downgrade status → red.
- [ ] 2.5 Rescore test: a week scored at version 1 gains verdicts when
      rescored at version 2, statuses unchanged.

## 3. Surfaces

- [ ] 3.1 Briefing: the compliance section appends the verdict sentence on
      annotated days; test via the existing briefing fixtures.
- [ ] 3.2 `serve.mjs`: by-id `plan` object carries `quality` (omitted when
      NULL); pin in `test_archive_api.mjs` both presence and absence.
- [ ] 3.3 `run.dc.html`: plan card renders planned text + verdict when
      `quality` exists; `test_run_page.mjs` case with a verdict fixture and
      the discriminating no-verdict case (card unchanged). Mutation-prove the
      rendering (drop the verdict node → red).

## 4. Verification and ship

- [ ] 4.1 Full Python suite + all four JS suites green;
      `node tools/style-audit.mjs layout` — /run still passes at 390.
- [ ] 4.2 Re-run every mutation above on the finished branch; ledger in
      notes.md.
- [ ] 4.3 Merge → CI → NUC deploy → `POST /api/sync`. Post-deploy: current
      block's quality days carry verdicts; statuses byte-identical to
      pre-deploy (capture before); briefing renders the sentences;
      `run_intervals` untouched; `verify_archive` exit 0.
- [ ] 4.4 Spot-check /run/:id for one quality day (e.g. a 4×1 km session) in
      the browser; update HANDOFF-interval-lens.md (P3.2 closed — the arc's
      roadmap is complete) and memory.
