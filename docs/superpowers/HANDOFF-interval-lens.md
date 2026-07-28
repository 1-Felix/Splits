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

## UPDATE 2026-07-28 — "the workout step decides what is a rep" shipped

**Merged:** `9f3ac32` on `main` (17 commits). **Deployed and verified on the NUC
the same day**; all 168 documents recomputed at `INTERVAL_VERSION` 4,
`verify_archive` exit 0.
**Design:** `docs/superpowers/specs/2026-07-28-interval-lens-workout-steps-design.md`
**Plan:** `docs/superpowers/plans/2026-07-28-interval-lens-workout-steps.md`
**Suite at merge:** 458 Python passed / 2 skipped; `test_run_page.mjs`,
`test_archive_page.mjs`, `test_coach_read.mjs` ALL PASS.

**Closed by it:** P1.1, P1.2, P2.1, P2.7a, and the lap half of M3.

That change found a defect this file did not know about: `_LAP_ROLES` maps
`ACTIVE` → work unconditionally, and Garmin tags warmups, cooldowns and
transitions `ACTIVE` too. Those are **longer** than the reps, so P2.7's size
floor never reached them — 8 of 23 lap-sourced documents were counting non-reps
as reps. `wktStepIndex` separates them: reps of a set share one *repeated*
workout step; a one-off step is not a rep.

Production sweep after the deploy — shapes moved `reps 26→24`, `steady 129→130`,
`block 11→12`, and stream-sourced counts did not move at all (145, unchanged):

```
2026-04-10  5×2 km, cv 14.8, fade +17.5  →  3×2 km,  cv 1.7, fade +0.6
2026-03-20  7 reps, cv 19.5, fade +18.0  →  5×1 km,  cv 2.4, fade +2.3
2025-12-12  7×300 m,         fade +37.1  →  6×300 m, cv 4.2, fade −4.0
2026-05-29  5×1 km,          fade +30.5  →  4×1 km,  cv 2.4, fade +0.3
2026-02-06  8 reps, cv 15.4               →  6 reps,  cv 2.1, fade −3.2
2025-10-17  8 reps, cv 23.9               →  6 reps
2025-12-19  1.5-0.627 km                  →  14 min block
2024-07-22  3 reps (Run Walk Run®)        →  steady          ← closes P2.7a
unchanged:  2025-11-21 8×200 m · 2026-06-26 1-2-1 km · 2026-07-10 5×1 km
            2024-07-13 block · every genuine tempo block
```

**A claim in this file it overturns — see §1.1 of that design.** P2.3 below
records `2026-05-29` recovering as `5×1 km [1000,1000,1000,1000,926]` and treats
it as the engine working. It was not: that 926 m "rep" is a manual lap run
**after** the COOLDOWN at 7:33/km with no workout step index at all. It now
reads `4×1 km`, which is the truth — the watch executed four of a prescribed
five. P2.3's *conclusion* is unaffected: that run still takes the lap path,
where the calibration floor is never consulted, so the windowed baseline remains
unmotivated.

**New test asset.** `tests/fixtures/lap_workouts.json` +
`test_interval_laps_truth.py` pin all **23** of the archive's structured
lap-sourced workouts, trimmed to the fields the engine reads. This exists
because the local `activity-archive.db` carries **no lap data at all** — the
backfill ran on the NUC and was never copied down — so `test_interval_truth.py`
cannot reach the lap path. **Any future lap-path change must extend this fixture
rather than lean on the local archive.** Its own trap, twice hit during this
change: a conclusion drawn locally about a run that takes the *lap* path in
production is worthless (see P2.3 above, and §5.3 of the design).

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

## Priority 1 — visible on the page, small fixes  ✅ ALL CLOSED 2026-07-28

### ~~P1.1 The rep table has no column headers~~ — DONE 2026-07-28 (`83a96c5`, `4d98949`)

`PACE` / `GAP` headers ship on the rep card, width-matched to their columns and
pinned by bounding-box assertions that were themselves mutation-proven (an
earlier version could not fail: the `flex:1` spacer sits before those cells and
absorbs any width delta, so comparing right edges alone measured nothing).
The sub-line needs no qualifier now — P2.1 put it on the same signal as the bars.

<details><summary>original entry</summary>


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

</details>

### ~~P1.2 `calibrated: false` is written but never surfaced~~ — DONE 2026-07-28 (`e272054`)

`/run/:id` now says "Not enough history to judge this run's structure yet" when
`intervals.calibrated === false`, and stays silent otherwise. `=== false`, not
`!calibrated`: a document predating the flag has no key and must not be accused.
Felix's archive currently has 0 uncalibrated documents; this is for Max.

<details><summary>original entry</summary>


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

</details>

---

## Priority 2 — correctness and quality, no user-visible breakage

### ~~P2.1 Should the deviation bars measure GAP or raw pace?~~ — DECIDED 2026-07-28 (`b003e9d`)

**Raw, and the bars were already right.** Measured before choosing: on the
archive's one *uncontaminated* hill-repeat set (`2025-11-21`, eight genuine 90 s
reps) raw is TIGHTER — cv 9.1 % vs GAP 14.7 %. Fixed-duration reps cover less
ground as the athlete tires, so each samples a different slice of the gradient
and its grade adjustment varies; GAP there measures the hill, not the athlete.
On the stream path the two bases differ by under 1.5 points and split both ways
across 11 sets. The large GAP-vs-raw gaps on the other hill sets turned out to be
the ACTIVE-lap contamination above, not terrain.

So `paceCvPct`/`fadePct` moved to raw on BOTH producers, matching the bars and
the PACE column. **Do not reopen without a session that climbs continuously
point-to-point** — that is the one shape raw misreports, and none exists in 168
runs. See §5.1/§5.2 of the design for what it trades away.

<details><summary>original entry</summary>


Open design question, deliberately not decided. `paceS` is raw pace (what you
ran); `gapS` is grade-adjusted (what it cost). The bars currently use `paceS`.
On rolling ground GAP is arguably the honest basis for comparing reps to each
other — it is why the engine detects on GAP in the first place (design D5).

Decide it by looking at a hilly session on `/run/:id`.

</details>

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

**UPDATE 2026-07-28, measured in production — this is now much lower priority.**
The whole-branch reviewer predicted that once this run's laps landed it would
take the lap path and the calibration boundary would stop mattering for it.
That is exactly what happened. After the lap backfill and the rescore it reads:

```
5×1 km   Tempo: 5x 1km (Pace 6:00-6:10)   [1000, 1000, 1000, 1000, 926]   source=laps, conf 1.00
```

So the one piece of hard evidence motivating a windowed baseline has evaporated.
Every genuinely-structured workout the athlete has run carries Garmin lap data
and now takes the device path, where the calibration floor is not consulted at
all. The all-time baseline only governs runs the watch did *not* record as
structured — where a false positive matters more than a false negative anyway.

**Do not build this without new evidence.** Measure first: find a run you know
was a workout, that has no usable lap structure, and that reads `steady`. If you
cannot find one, the windowed baseline is solving a problem you no longer have.

(The skip in `test_interval_truth.py` is now stale in its *reasoning* — the run
still reads `steady` against a local archive with no laps banked, so the test is
correct as written, but the recorded cause no longer applies in production.)

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

## Priority 2.7 — found in production (a: closed, b: open)

The deploy on 2026-07-27 banked 124 runs' lap data, which created the first
lap-sourced documents that had ever existed. Two defects surfaced immediately
that no fixture could have caught, because the code path had never met its
input. The first was fixed the same night (`INTERVAL_VERSION` 2→3); the second
was not.

### ~~P2.7a — Galloway run/walk sessions misclassify as rep sets~~ — DONE 2026-07-28 (`4f62625`)

Fixed as a side effect of the step rule plus a block floor on the lap path.
`Run Walk Run®` now reads **`steady`**: its run/walk laps carry no repeated
workout step, and the single survivor (205 m / 62 s) fails both `BLOCK_MIN_S`
and `BLOCK_MIN_M`. The block floor is an **OR**, matching `classify()` — the
stream path has always used OR, and a draft of this change used AND until review
caught the asymmetry.

<details><summary>original entry</summary>


`Leinfelden-Echterdingen - Run Walk Run®` has lap distances
`[205, 106, 81, 145, 52, 94, 66, 118, 52, 97, 50, 111, 42, 173, 914]`. It is a
Galloway run/walk, not an interval session, and it should not be `reps` at all.

Before the lap floor it read `found: 15` with no label; after, three segments
survive the floor **by chance** and it reads `found: 3, label "3 reps"` — a more
specific wrong answer, not a fixed one. No floor value fixes this: the
misclassification is that a run/walk pattern looks structurally identical to a
rep set, and a count threshold does not help because 3 clears any plausible one.

Needs either a run/walk-aware shape (Garmin's `splitSummaries` already carries
`RWD_RUN` / `RWD_WALK` counts, which would identify these directly) or a
whole-set-trust rule that refuses to call a set when most of its laps failed the
floor. One run out of 168 today.

</details>

### P2.7b — the two paths disagree on how many reps make a set

The lap path classifies `reps` at `len(work) >= 2`; the stream path uses
`REPS_MIN_COUNT = 3`, which is what design D2 specifies. Pre-existing, untouched
by the lap-floor fix, and it changed neither flagged case's outcome — but it is
one more place the two paths quietly differ, which is exactly what the
one-engine design exists to prevent.

Note this interacts with **P3.1**: whatever `expect_reps` logic lands with the
prescription parser must apply to both paths, not just the stream one.

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
| M3 | `interval_lens.segments_from_laps` | **HALF DONE 2026-07-28** (`66ecc28`): `gapS` now comes from the lap's own `avgGradeAdjustedSpeed` (present on 553 of 565 laps — the old docstring claiming lapDTOs carry no GAP was simply false), so the windowed lookup is a fallback and the drift no longer reaches it. Measured drift across all 17 lap-sourced structured runs: 0 s on every one except `2026-06-26` (40 s). **Still open:** accumulates `t0` from lap `duration` (moving) rather than `elapsedDuration`, so on a run with pauses the lap-derived `t0/t1` drift from the stream's elapsed axis the rep bands are drawn against. Same for `d0/d1`. Also assumes the stream clock starts at 0 — true for all 165 archived runs (measured), but unguarded. |
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

## New — found by the 2026-07-28 change, deliberately not fixed

| # | Where | What |
|---|---|---|
| N1 | `run.dc.html` rep card | `recs[i]` pairs recoveries to reps positionally. A **mid-set** demotion (a one-off `ACTIVE` step *between* two reps) becomes a `recovery` segment and shifts every later pairing, so rep 3 can display the transition's duration and rep 4 gets rep 3's. Pre-existing pattern, but the step rule makes it reachable for full-size transitions — and §1 of the design proves those are real (`2025-10-17` lap 2). No archived run triggers it today; the sweep confirmed none has a mid-set demotion. **Most likely future breakage in this area.** |
| N2 | `test_interval_laps_truth.py` | `test_every_fixture_workout_is_read_as_structured` is circular by construction: the 23-workout fixture was *selected* by running `laps_are_structured`, and every entry is a positive. As a frozen-JSON guard it still catches the predicate becoming too **strict**; it cannot catch it becoming too **permissive**. That direction is covered only by synthetic tests (`test_autolap_beats_the_workout_flag`, `test_uniform_intensity_is_not_structure`). Fix: add one known-**unstructured** real workout from the ~101 excluded `laps_json` rows with an `is False` assertion. |
| N3 | `_reps_label` | `2026-02-06` labels its six 90 s hill reps `6×0.23 km`, because their mean distance snaps to no round target. Those sets want naming by **duration** (`6×90 s`) — the reps are time-prescribed, and their distances vary precisely *because* the athlete tires. Blast radius: the `/archive` chip, the rep-card title and the cockpit sentence. |
| N4 | `interval_lens._lap_rep_segments` | The size floor runs **before** the step rule, so a rep the floor drops is also dropped from the step evidence. `2025-11-21` lap 8 is **151 m** against `WORK_MIN_M = 150` — one metre of GPS noise turns that session from 8 reps into 7 plus a mid-set "recovery", compounding N1. Ordering is correct and documented; the margin is not. |
| N5 | `interval_lens._rep_step_indices` rule 3 | When no work step repeats, ACTIVE bookends are **not** demoted (by design — the `1-2-1 km` pyramid needs it). So a hypothetical ACTIVE-warmup / ACTIVE-tempo / ACTIVE-cooldown workout on three distinct steps still reads "3 reps". Unchanged from before, no archive case hits it, but the change's headline promise holds only where a repeat block exists. |
| N6 | `interval_lens._pace_s_per_km` | Returns `0` for a negative input, so a nonsense negative `avgGradeAdjustedSpeed` would report `gapS: 0` rather than `None`. Shared helper, every call site. Triaged as zero user-visible impact: `gapS`'s only consumer is `run.dc.html`'s `s.gapS ? … : '—'`, which renders `0` as the same em dash `None` produces. |
| N7 | `tools/style-audit.mjs` | Never visits `/run` at all, so the run page has no responsive coverage. It carries a **pre-existing** ~18 px horizontal overflow at 390 px — measured identically with and without the new header row, so not caused by it, and the overflow is `.card.rep-table` itself rather than any row. |

Note **P2.4** (no distill version marker on the Garmin side) is now more
reachable than when it was written: `detail_distilled_json.intervals` is still
filled only where the column is `NULL`, so it is not refreshed by an
`INTERVAL_VERSION` bump. Harmless today — `/run/:id` injects the fresh document
before calling `coachRead`, and the cockpit re-distills every sync — but any
future consumer of that stored key reads a v3-era document.

## NUC operations — a trap hit during this very deploy

**Never wrap `ssh … docker compose exec …` in a client-side `timeout`.**

Doing so kills the *SSH client*, not the remote process. The Python process
keeps running inside the container, orphaned, holding a write-capable SQLite
handle — and the next writer dies with `sqlite3.OperationalError: database is
locked`. That is exactly how the first lap-backfill attempt of this deploy
failed, aborting on its first write.

It was harmless only because of three existing design choices worth preserving:
`write_laps` commits per call (nothing half-written), DELETE journal mode leaves
no journal when a reader dies, and the archive was verifiably intact afterwards.

Two further facts learned the hard way:

- **The image has neither `ps` nor `kill`.** To find an orphan, run
  `docker top splits` from the NUC host; the PIDs it prints are host PIDs.
- **The orphan runs as root**, so `kill` as `felix` fails. The reliable
  clearance is `docker compose restart splits` — the container is stateless,
  all data lives in the `splits-data` volume.

Use `run_in_background` for long remote commands, or put the timeout *inside*
the container.

Related: `serve.mjs` owns the sync lock and is meant to be the single writer.
Running `sync_garmin.py` directly via `docker compose exec` bypasses that lock.
It is fine when nothing else is syncing — but check `docker top splits` first,
and prefer `POST /api/sync` for a routine sync.

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
