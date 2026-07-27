# Interval lens — automatic split detection for structured runs

**Date:** 2026-07-27
**Status:** Approved (design) — ready for implementation plan
**Author:** Felix (with Claude Code)

## Context

"Splits" in SPLITS means **per-kilometre** splits, and has since the beginning. Both
pipelines bin the speed stream into 1 km buckets — `sync_garmin._bin_splits` for Garmin,
`ingest_builder.run_splits` for Health Connect — and reduce the result to a `splitShape`
verdict computed from the first and last third.

That contract is blind to structure. A session of `2 km wu · 5×1 km @ 5:40 · 1 km cd`
renders as nine kilometre averages, each one smearing work and recovery together, and its
`splitShape` reads "even" because the warmup and cooldown cancel out. The rep paces — the
only numbers that session was run to produce — appear nowhere in the dashboard.

**What the data already carries.** Every archived run has full-resolution streams
(`t/d/hr/v/gap/cad/elev/pwr/lat/lon/pc` at ~2 s), including `gap` — grade-adjusted speed.
Garmin summaries carry `lapCount`, `hasIntensityIntervals` (true on 7 of 165 runs),
`workoutId` (91 runs) and `splitSummaries`. Real per-lap data lives behind
`get_activity_splits()` → `lapDTOs`, which **the sync does not fetch today**.

**The asymmetry that shapes the design.** Max's Galaxy Watch writes no `ExerciseLap` at
all (already noted in `ingest_builder.run_splits`), his samples are coarser (HR ~1/5 s),
and some of his runs carry no `SpeedRecord` whatsoever. Anything that depends on lap data
existing cannot serve both athletes.

## Goals / Non-Goals

**Goals**

- One engine, both athletes: detect the structure of a run from its stream, using Garmin
  lap data as ground truth when it genuinely encodes structure.
- Recognise rep sets (including unequal reps), sustained blocks, and progression runs.
- Per-rep insight on `/run/:id`: pace, GAP, HR, and the recovery between reps.
- Feed the coaching layer: rep-level compliance against the prescribed workout, quality
  volume in the block lens and the coach briefing.
- Work retroactively across the whole archive, and stay recomputable after any algorithm
  change.

**Non-Goals (YAGNI)**

- Per-run manual override of the detected structure. The document is a derived cache with
  one writer; correcting the algorithm and bumping the version is the fix path.
- Fartlek and hill-rep detection. Irregular surge sessions fall through as `steady` — this
  is where false positives live, and a hilly easy run looks like fartlek to a naive
  detector.
- Detecting structure in non-run activities.
- Replacing per-kilometre splits. They stay; they are blunt, not wrong.

## Decisions taken

| # | Decision | Rationale |
|---|---|---|
| D1 | Device laps win when the activity is genuinely structured; stream detection otherwise and always for Max | Garmin's `lapDTOs` carry exact boundaries, `intensityType` roles, and the workout's per-rep targets. Nothing derived beats that. Cost accepted: two code paths. |
| D2 | Shapes detected: `reps`, `block`, `progression`, `steady` | Covers what the plan actually prescribes. `progression` replaces `splitShape`'s crude thirds heuristic with something real. |
| D3 | Detection is **plan-guided** — the day's prescription is a prior | Higher recall on messy or low-resolution data, which is exactly Max's situation. Cost accepted: the compliance verdict is no longer fully independent evidence, so D4 exists. |
| D4 | The prior may inform boundaries, never invent a rep | A bout must clear the evidence bar in the stream to exist. A bailed session reports `found: 3, prescribed: 4`. Without this, D3 makes the detector a liar. |
| D5 | Grade-adjusted speed (`gap`) is the detection signal where available | On hills, a rep up a drag and one down it are the same effort. Using raw pace would split one set into a fade. |
| D6 | The document is a versioned, disposable derived cache | Same semantics as `run_metrics` / `block_lens` / `course_lens`. A threshold tweak is a version bump, not a migration. |
| D7 | Ships as two OpenSpec changes, designed together | The seam is producer/consumer. Change 1's detector can be verified against real interval history before five pages depend on its output. |

## The document contract

One document per run, produced by one engine, consumed by everything.

```js
{
  version: 1,                       // INTERVAL_VERSION — bump self-heals the cache
  shape: "reps" | "block" | "progression" | "steady",
  source: "laps" | "laps+stream" | "stream",
  confidence: 0.0–1.0,
  label: "4×1 km",                  // or "1-2-1 km pyramid", "20 min block", null
  guidedBy: null | { date, prescription: "4×1 km @ 5:25–5:35", usedPrior: true },
  segments: [
    { idx, role, rep?, t0, t1, d0, d1, durS, distM, paceS, gapS, hr, cad, hrDrop? }
  ],
  set: {                            // only when shape === "reps"
    found: 4, prescribed: 4,        // these can disagree — see D4
    nominalDistM: 1000, varied: false,
    paceS: 331, paceCvPct: 1.8, fadePct: 2.4,
    recoveryS: 62, recoveryHrDrop: 24
  },
  quality: { workDistM: 4000, workDurS: 1324, zone: "Z4" }
}
```

`role` ∈ `warmup` / `work` / `recovery` / `cooldown` / `step` / `steady`. A `progression`
run emits its ramp as `step` segments (one per detected pace tier, in time order); a
`block` run emits `warmup` / `work` / `cooldown`; a `steady` run emits none.

`set.prescribed` is `null` when no prescription was parsed — distinct from `0`, which
would claim the plan asked for nothing.

`quality.zone` is the modal HR zone across the run's `work` segments, computed with the
same zone bounds each pipeline already uses (`_zone_bounds` in `ingest_builder`, Garmin's
`hrTimeInZone_*` for the sync). It is `null` when the run has no HR stream.

`confidence` is derived from three factors, multiplied and clamped: class separation (how
far apart the two pace classes sit relative to their spread), boundary crispness (median
pace gradient at the detected edges), and rep regularity (inverse of `paceCvPct` for
`reps`). Lap-sourced documents are fixed at `1.0` — the watch is not guessing. The
threshold below which the UI says *possible* structure rather than asserting one is
`0.5`, and it is part of `INTERVAL_VERSION` like every other parameter.

Two contract rules matter beyond the field list:

- **A steady run still gets a document** (`shape: "steady"`, no segments). "We looked and
  there was no structure" must be distinguishable from "we never looked" — the same
  distinction `fetched_at` draws for wellness nights in schema v5.
- **`quality.workDistM` is the coaching layer's number.** Everything else belongs to the
  run page. Consumers depend on `quality` and `set`, never on `segments`.

Why a document rather than promoted columns: it mirrors `block_lens.block_json` and
`course_lens.lens_json` — columns index, JSON is the truth, and the whole thing is always
recomputable.

## The engine

`interval_lens.py` — pure over its inputs, no clock, no network, testable the way
`chart-core.js` is.

**Signal.** `gap` where Garmin provides it, else `v`, converted to pace, resampled onto a
uniform 1 s grid, smoothed with a ~15 s rolling median. The window is chosen against the
30 s minimum bout: long enough to kill GPS chatter, short enough not to blur a rep edge.

**Segmentation.** Thresholding against the run's own median fails on a session that is
half reps — the median sits *between* work and rest. Instead the smoothed pace
distribution is split into two classes (1-D k-means / Otsu). If the classes are not
genuinely separated, the run is steady and detection stops there. If they are, the trace
is walked with **hysteresis** — enter work at the fast-class boundary, leave at a slacker
one — so chatter cannot shred one rep into three. Minimum bouts: work ≥ 30 s **and**
≥ 150 m; recovery ≥ 20 s.

**Classification.**

- ≥ 3 work bouts → `reps` (≥ 2 when a plan prior expects a set — a prescribed 2×2 km is a
  real session, but two unexplained bouts are more likely noise). Label `N×D`. Rep
  distances differing by > 20 % set `varied: true` and produce `1-2-1 km` rather than a
  false nominal length.
- Exactly one bout ≥ 5 min or ≥ 1.5 km, flanked by easier running → `block`.
- No class separation, but pace falling monotonically across quintiles beyond threshold →
  `progression`.
- Otherwise `steady`.

**Lap override (D1).** When the activity is genuinely structured — `hasIntensityIntervals`
true, or `workoutId` present with non-uniform lap `intensityType` — `lapDTOs` are taken
verbatim: boundaries, roles from `intensityType`, per-lap stats from the DTO
(`source: "laps"`). Manual laps carrying no intensity labels are intent without semantics,
so they are handed to the stream detector as **boundary anchors**
(`source: "laps+stream"`).

One guard is load-bearing: **if every lap is within ±5 % of 1.000 km (or 1 mile), it is
Garmin auto-lap and is ignored entirely.** The archive holds a 19-lap run that is simply a
19 km easy run; without this guard it reads as a 19-rep session.

**Plan prior (D3/D4).** When the day's plan parses to (count, length or duration, target
band), the prior seeds the expected count and length, relaxes the entry threshold *only
inside windows where a rep is expected*, and snaps boundaries to the nearest strong
gradient within ±15 s. It never lowers the evidence bar to zero: a bout with no support in
the stream does not exist, and the document reports `found` below `prescribed` when the
session was cut short. `guidedBy` records that the plan participated, so the UI can say so.

## Acquisition and storage

**Schema v11**, additive like every migration before it:

- `run_intervals` — `activity_id` PK, `lens_version`, `shape`, `label`, `confidence`,
  `source`, `work_dist_m`, `work_dur_s`, `doc_json`, `computed_at`.
- `activities.laps_json` — one write-once column, same rule as `detail_json`: only stored
  on a successful fetch, never overwritten with an empty result.

`run_intervals` follows `run_metrics` exactly: `runs_missing_intervals(conn,
INTERVAL_VERSION)` returns rows that are absent *or* stale, so a version bump after a
threshold tweak recomputes every row with no manual step. A full recompute of the current
archive is seconds.

**Lap acquisition.** `sync_garmin` gains `get_activity_splits(aid)`, cached to
`.garmin_cache/laps-<id>.json` beside the detail cache. Only fetched where `lapCount > 1`,
which skips 42 runs outright; the backfill is ~120 calls, the same shape and cost as the
route-basemap backfill that fetched 160.

**Max.** `ingest_builder` calls the same engine over his speed and HR samples resampled
onto the same 1 s grid, writing the same document to his own archive. `source` is always
`"stream"`. A run with no `SpeedRecord` gets no document at all — the rule
`ingest_builder.run_detail` already applies when it returns `None` without a speed series.

**Read paths.** The full document rides on `/api/archive/activities/:id`; `shape` and
`label` ride on the list rows so `/archive` can label a page without N fetches. The
**compact summary** (label, set stats, quality) also lands in each recent run's `detail`
in `garmin-data.js` — the cockpit renders complete from static files with no API, and
interval labels must not be what breaks that promise.

## Change 1 — `add-interval-lens`

Lap acquisition, schema v11, the engine, the archive API, and the primary render.

**`/run/:id`** gains a rep table when `shape !== "steady"`: rep #, distance, time, pace,
GAP, avg HR, with the recovery beneath each rep (duration + HR drop). Deviation bars
measure against the **set's own median** — the run median is meaningless when half the run
is warmup and cooldown. Reps are shaded on the existing stream tracks, so the crosshair
tells you which rep you are in. The per-km splits card stays, below.

**Cockpit + `coach-read.js`**: the recent-run drill-down reads `5×1 km @ 5:34, +2.4 %
fade` in place of the `splitShape` verdict. **`/archive`**: a shape chip per row.

## Change 2 — `add-interval-coaching`

**The prescription parser** is the new risk surface and gets the tightest scope: an
explicit grammar over the plan's `segments[].val` strings — `N×D @ band`, `N×T min @
band`, `D km easy`, with `rest` read from the sibling field — and **anything it cannot
parse returns `null` rather than a guess**. The live plan holds 18 `segments` blocks, so
the grammar is validated against real prescriptions rather than invented ones.

**`plan_compliance`** (version bump): the planned-vs-actual join stops being
distance-only. `status` gains rep-level reasoning — `4/4 reps in band`, or `3 of 4 reps ·
last one 16 s off` — which is the `found`/`prescribed` honesty from D4 surfacing where it
matters most.

**`block_lens`** (version bump): weekly **quality volume** (km at work intensity) as a
first-class block metric, rep-pace trend across the block, and execution rate — reps
completed over reps prescribed. **`coach_briefing`** gains the matching section so the
coaching ritual reads it without opening a page.

**`/compare`**: when both runs are `reps`, align them rep-by-rep instead of km-by-km. A
5×1 km in June against a 5×1 km in July is the comparison that answers "am I getting
faster".

## Failure modes

| Situation | Behaviour |
|---|---|
| No speed stream (some of Max's runs) | No document. Nothing renders; nothing lies. |
| Treadmill | Works. `v` exists, `gap` is absent, pace is used. |
| Garmin auto-lap at 1 km | Laps ignored as structure (±5 % guard); stream detection decides. |
| Steady run | `shape: "steady"` document — looked, found nothing. |
| Low confidence | Rendered as *possible* structure, never asserted. |
| Detector wrong | Fix the algorithm, bump `INTERVAL_VERSION`, everything recomputes. No manual override exists by design. |
| Prescription unparseable | `guidedBy: null`; blind detection, no degradation. |

## Testing

`test_interval_lens.py` over synthetic streams covers the cases that decide whether this
works: a clean 5×1 km, an unequal 1-2-1 pyramid, a hilly easy run that must **not**
trigger, a 19-lap auto-lap run that must not read as structure, and a bailed session that
must report 3 of 4.

Beyond synthetics, **the archive is a free labelled test set**. Runs named `2km wu, 5x1km
@ 5:40, 1km cd` and `pYRAMIDE: 1-2-1K Tempo` state their own ground truth, so the
acceptance test asserts the detector recovers what the name says across every
self-describing run in the archive — real GPS noise, real hills, no fixtures.

A parity test asserts both pipelines emit identical documents for equivalent input
(mirroring `test_course_parity.mjs`), and Playwright specs cover the rep table and the
shape chips.
