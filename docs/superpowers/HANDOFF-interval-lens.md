# Interval lens — handoff

**Merged:** 2026-07-27, `46e8100` on `main` (37 commits from `feat/interval-lens`).
**Suite at merge:** 402 Python passed / 2 skipped, 27 `.mjs` suites ALL PASS.
**Design:** `docs/superpowers/specs/2026-07-27-interval-lens-design.md`
**Plan:** `docs/superpowers/plans/2026-07-27-add-interval-lens.md`
**Full execution ledger** (every task, every finding, every deferral):
`.superpowers/sdd/2026-07-27-add-interval-lens/progress.md` — gitignored, local only.

This file is the list of what is **not** done. Everything here was found, understood
and deliberately deferred; none of it is a surprise waiting to be discovered.

---

## What shipped

`interval_lens.py` decides what structure a run had — `reps` / `block` /
`progression` / `steady` — from its sample streams, preferring Garmin lap data
when the watch recorded a genuinely structured workout. One engine, two
producers: `sync_garmin.py` and `ingest_builder.py` both call
`build_document()`, so a run is read by identical rules whichever watch
recorded it.

Work is defined against the athlete's **own pace history** (p93 of their whole
archive), not against the rest of the run. That distinction is the whole
feature: within-run comparison classified **62 %** of a real 165-run archive as
interval sessions, because 2-means always yields a "fast half". Calibration
brings it to **12 %**.

Measured on the real archive at merge: floor **2.700 m/s** (6:10/km),
`steady 138 / reps 19 / block 5 / progression 2`, one run with no usable stream.
`2km wu, 5x1km @ 5:40` recovers exactly 5 reps labelled `5×1 km`; the hill
sessions recover `6×200 m`; the `pYRAMIDE: 1-2-1K` stays varied and enumerated.

---

## Priority 1 — visible on the page, small fixes

### P1.1 The rep table has no column headers

`run.dc.html` renders pace and GAP as two adjacent unlabelled monospace numbers
(pace bold, GAP muted). This ambiguity is **new**: before the final fix wave the
GAP cell was always an em dash, so there was nothing to confuse it with.

Add `PACE` / `GAP` headers to the rep card. While there, note the second half of
the same finding: the card sub-line reports `paceCvPct` / `fadePct`, which ride
the **grade-adjusted** signal, while the deviation **bars** are drawn from
`paceS`, which is now **raw**. On a hilly set the bars fan out above a sub-line
reading `0.0 % spread`. Qualify the sub-line as "grade-adjusted", or move the
bars onto `gapS` — see P2.1 for why that is a real design question, not a typo.

*Source: final whole-branch re-review, agreed by the controller.*

### P1.2 `calibrated: false` is written but never surfaced

`interval_lens.build_document` sets `calibrated` on every document, and nothing
reads it — not the API, not `run.dc.html`, not `validate_data.py`.

So "we don't have enough history to judge structure yet" renders **identically**
to "we looked and found nothing". That is precisely the distinction the
contract's steady-document rule exists to preserve, and it is Max's live state
today: `work_floor` needs `WORK_FLOOR_MIN_SAMPLES` = 20 000 samples ≈ 30 runs,
and his archive is days old.

A run that says *"not enough history to judge structure yet"* is a fine thing to
ship to a beginner. A run that says *"steady"* when nobody looked is not.

*Source: final whole-branch review, M7 — and the strongest single reason the
feature is not yet honest for Max.*

---

## Priority 2 — correctness and quality, no user-visible breakage

### P2.1 Should the deviation bars measure GAP or raw pace?

Open design question, deliberately not decided. `paceS` is raw pace (what you
ran); `gapS` is grade-adjusted (what it cost). The bars currently use `paceS`.
On rolling ground GAP is arguably the honest basis for comparing reps to each
other — it is why the engine detects on GAP in the first place (design D5).

Decide it by looking at a hilly session on `/run/:id`.

### P2.2 Ragged labels on 3 of 19 detections

Bout boundaries land where pace crosses a threshold, not where the rep actually
began and ended, so a set whose reps were run at varying effort fragments. The
final fix wave collapsed the unenumerable ones to `N reps` (clean labels went
6/19 → 16/19), which removed the user-visible damage.

The underlying fix is **boundary extension**: walk each bout's edges outward
while effort persists, rather than stopping at the exit threshold. That would
also fix the truncated final rep that still shortens some sets. Costs an
`INTERVAL_VERSION` bump and a recompute — no migration, by design.

### P2.3 The calibration baseline is all-time, but fitness moves

An older workout is judged against a percentile that includes everything you
have run since, including your current faster self. This is why the
ground-truth test carries a documented skip: `Tempo: 5x 1km (Pace 6:00-6:10)`
reads `steady` because its prescribed pace sits **exactly** on the 6:10 floor —
its three real reps measure 5:52 / 6:21 / 6:06 and only two clear it.

Fix: a **trailing/windowed baseline** — price each run against the athlete you
were within, say, ±6 months of it. Highest-value follow-up in this file.

Worth knowing before you build it: that run is one of the 7
`hasIntensityIntervals` runs, so once its laps land it takes the lap path and
the calibration boundary stops mattering *for it*. The windowed baseline may
matter less than it looks. Measure before building.

### P2.4 No distill version marker on the Garmin side

`_distill_pass` only fills rows where `detail_distilled_json IS NULL`, and there
is no version marker (the Health Connect side has `INGEST_DISTILL_VERSION` for
exactly this). So previously-archived runs' stored distilled detail can never
retroactively gain `intervals`.

Both current in-tree readers are already covered — `coach-read.js` is fed from
`garmin-data.js`, which the sync rebuilds fresh every night, and `run.dc.html`
is fed the API document directly — so this is latent, not live. Any **future**
consumer of `detail_distilled_json.intervals` would hit it.

Mirror `INGEST_DISTILL_VERSION` when convenient.

### P2.5 Two of three confidence factors are untested

Mutation-proven dead coverage in `interval_lens.py`: replacing the `crisp`
factor with `1.0` leaves the suite green; so does replacing `regular` with
`1.0`. Only the separation factor is actually exercised.

Related and more concrete: a single-bout `block` always has `cv is None` and
`shortest ≥ 300 s`, so blocks score confidence `1.0` and can **never** be
hedged. A half-marathon race in the archive reads `conf=1.00 "6 min block"`.

### P2.6 Other mutation survivors

All found by the final whole-branch review, all in `interval_lens.py`:

- Deleting `_is_progression`'s monotonicity clause → suite still green.
  Matters disproportionately: `progression` is the **only** non-steady shape
  reachable without a work floor, i.e. Max's only possible detection today.
- Making `classify`'s block branch unconditional → still green.
  `BLOCK_MIN_S` / `BLOCK_MIN_M` have no negative coverage.
- Deleting `_hr_grid`'s sample-and-hold → still green. This is live code on
  every Garmin run (~2 s samples); without it half the HR grid is null and
  `quality.zone` shifts.
- Moving the calibration floor filter **before** the merge step in `find_bouts`
  → still green. The ledger records merge-then-filter order as load-bearing and
  proves it by hand; there is no regression test.

---

## Priority 3 — Change 2 blockers

These must be resolved **before** the prescription parser ships, not after.

### P3.1 `classify`'s rep floor breaks the honesty contract at 2-of-4

Design D4 promises that a session you bailed on reads as *"3 of 4 prescribed
reps found"*. The floor is `2 if expect_reps <= 2 else REPS_MIN_COUNT (3)`, so a
prior expecting 4 does **not** lower it. Bailing at 3-of-4 reports correctly;
bailing at **2-of-4 classifies as `steady`**, `set_stats` never runs, and the
document cannot report `found: 2, prescribed: 4` at all.

The session you gave up on is exactly the one the guardrail was for.

Fix: `max(2, min(REPS_MIN_COUNT, expect_reps))` — a prescribed set that was cut
short is still a set. Unreachable in Change 1 (`prior` is always `None` per D8),
which is why it shipped.

### P3.2 The prescription parser itself

The plan's Change 2 covers: parsing `plan-data.js`'s `segments[].val` strings
(`4×1 km @ 5:25–5:35`), rep-level `plan_compliance`, quality volume in the block
lens and coach briefing, and `/compare` aligning two sessions rep-by-rep.

`build_document` already takes `prior` and every document carries
`guidedBy: null`, so the contract does not need reshaping — Change 2 fills the
prior and bumps `INTERVAL_VERSION`, which self-heals every stored document.

---

## Priority 4 — minor, scheduled

| # | Where | What |
|---|---|---|
| M1 | `sync_garmin._fetch_raw_laps` | Caches the envelope *before* checking for `lapDTOs`. A reply of `{"lapDTOs": []}` is cached permanently and `write_laps` never called. Combined with `runs_missing_laps`'s `ORDER BY … DESC LIMIT 40`, enough such runs at the head of the queue would starve the backlog. Fix: only write the cache after confirming a non-empty list. |
| M2 | `interval_lens.CONFIDENCE_ASSERT_MIN` | Referenced nowhere in Python; `run.dc.html` hardcodes `< 0.5`. The comment claims it is "part of INTERVAL_VERSION like every other parameter" — it isn't, and the two can drift. |
| M3 | `interval_lens.segments_from_laps` | Accumulates `t0` from lap `duration` (moving) rather than `elapsedDuration`, so on a run with pauses the lap-derived `t0/t1` drift from the stream's elapsed axis the rep bands are drawn against. Same for `d0/d1`. Also assumes the stream clock starts at 0 — true for all 165 archived runs (measured), but unguarded. |
| M4 | `serve.mjs` | Neither the list JOIN nor the by-id read filters on `lens_version`. Between an `INTERVAL_VERSION` bump and the next sync, the API asserts stale documents as current. The block/course endpoints carry their version; these should too. |
| M5 | `run.dc.html` | `s.gapS ? …` and `rc.durS` truthiness: a genuine `0` renders as `—`. `recs[i]` pairs recoveries to reps positionally — exact for stream-derived segments, a heuristic on the laps path. |
| M6 | `interval_lens.build_document` | The `work_floor` parameter shadows the module-level `work_floor()` function. Harmless today; a `TypeError` waiting for whoever adds a call. |
| M7 | `activity_archive.intervals_coverage` | `scored` counts `run_intervals` rows unconditionally. `ingest_builder`'s dedupe prunes `activities` rows; orphaned interval rows would inflate `scored` past `streamed_runs`. |
| M8 | `sync_garmin.distill_run_detail` | Always passes `laps=None`, so the cockpit's compact summary is stream-sourced even for runs whose archive document is lap-sourced. Becomes a visible cockpit-vs-`/run/:id` disagreement now that late-arriving laps trigger recomputes. |
| M9 | Zone model | Garmin passes `zone_bounds(max_hr)` (plain %max); Health Connect passes `_zone_bounds(max_hr, rhr)` (Karvonen). Moving `ZONE_FRACTIONS` into `interval_lens` unified the fractions but not the model — the comment claiming "the two producers cannot drift on what Z4 means" overstates it. Defensible per spec; the comment should say so. |
| M10 | `test_interval_truth.py` | Re-hardcodes `_RUN_TYPE_SQL`'s predicate as a literal, so the truth test and production can drift on what counts as a run. Also holds all 165 stream payloads in memory from module import. |
| M11 | `interval_lens` laps branch | Builds its label inline and emits `None` for a varied lap-sourced set; the `/archive` chip then falls back to the bare word "reps". Cosmetic; no lap-sourced documents existed at merge. |
| M12 | `find_bouts` coverage | No fixture separates `WORK_MIN_S` from `WORK_MIN_M` — both floors fail together on the existing fixture. A long-but-slow uphill surge is a live false-positive vector and the archive contains hill sessions. |
| M13 | Design testing section | Two named synthetic cases are absent: *"a hilly easy run that must not trigger"* (the archive-wide `test_full_archive_is_not_mostly_intervals` is a good substitute) and *"a bailed session that must report 3 of 4"* (unreachable until P3.1). |

---

## Environment hazard — unrelated to this feature, but live

**Stale `__pycache__` in this repo has twice produced a false test result.**

A `.pyc` from an older revision whose `(mtime, size)` matched was accepted by
CPython; disassembly showed it executing `paces[0] - paces[-1]` against a source
saying the opposite. It made a test that *must* fail **pass**.

Worse: git's index uses the same `(mtime, size)` stat cache, so
`git checkout -- <file>` **silently no-ops** after a length-preserving edit —
you have to `rm` the file before it will restore.

`rm -rf __pycache__` before believing any unexpected red.

---

## How to work on any of this

The document is a **disposable, versioned cache**. Change a threshold, bump
`INTERVAL_VERSION`, and the next sync recomputes all 165 documents — seconds,
no migration. That is the design working as intended; use it freely.

Two things worth doing before any engine change:

1. **Run the archive sweep.** Score every run read-only and check the shape
   distribution against the merge baseline (`steady 138 / reps 19 / block 5 /
   progression 2`, floor 2.700). Synthetic tests pass while the engine is wrong
   on real data — that is exactly how the 62 % over-detection survived 54 green
   unit tests.

2. **Mutation-test the change.** Break the thing you just wrote and confirm the
   suite goes red. This branch found **24 defects, every single one a test that
   did not exercise what it claimed** — assertions satisfied by empty results,
   by absent elements, by a case-insensitive locator matching a page wordmark,
   by comparing a value to a re-derivation of itself. The suite kills 24 of 33
   mutations today; the survivors are listed in P2.5 and P2.6.
