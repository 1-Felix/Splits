# Proposal: add-workout-prior

## Why

The interval lens decides what structure a run had by **inferring** it from what
the athlete executed. For every run started from a Garmin workout, the watch
already holds what the athlete was **told to do** — and the lens has never read
it.

`summary_json.workoutId` is present on **92 of 170** running activities (89
distinct workouts), including **every one of the 24 lap-sourced documents**.
`garminconnect.Garmin.get_workout_by_id` is already in the installed client.
The payload carries exactly the fields the lens is guessing at:

```
2026-07-10  '2km wu, 5x1km @ 5:40, 1km cd'
  warmup    distance  2000 m   no.target
  interval  distance  1000 m   pace.zone   5:30–5:49  ×5
  recovery  time        60 s   no.target              ×5
  cooldown  distance  1000 m   no.target
```

`numberOfIterations` is `prescribed`. `endCondition{distance|time|lap.button}`
plus `endConditionValue` is the rep's prescribed size. `targetValueOne/Two` are
the pace band as m/s floats — the same datum a `plan-data.js` parser would have
had to reconstruct from the string `4×1 km @ 5:25–5:35`. `stepTypeKey`
(`warmup` / `interval` / `recovery` / `cooldown` / `rest`) is the role that
`_LAP_ROLES` currently has to guess, because Garmin tags all of them `ACTIVE` —
the exact defect that drove `INTERVAL_VERSION` 4.

**Measured against the production archive (2026-07-29, read-only):**

| | |
|---|---|
| documents with a fetchable workout | **88** |
| lap-sourced rep sets whose `found` matches `numberOfIterations` | **12 / 12** |
| documents the lens reads wrongly, confirmed against the prescription | **15 (≈17 %)** |
| distinct workouts still fetchable | 85 / 89 (4 deleted) |

The 12/12 agreement matters on its own: `test_interval_laps_truth.py` is
circular by construction (handoff N2 — the fixture was *selected* by running
`laps_are_structured`). This is the first **independent** confirmation the step
rule is right.

The ~14 errors fall into four families, and two of them are on the athlete's
page today:

| family | runs | what the page says |
|---|---|---|
| continuous tempo fragmented into a fake set | `2026-01-23` (1×3 km → "4 reps") · `2026-03-13` (1×5 km → "2.66-1.04-0.408-0.39 km") · `2026-04-03` (1×7 km → "8 reps") | a prescribed single block shown as a rep set |
| prescribed tempo missed entirely | `2026-01-09` (1×2 km) · `2026-02-13` (1×4 km) · `2026-02-27` (1×2 km) — all `pace.zone` | **`steady`** |
| easy run promoted to quality | `2025-12-24` (Z2 3 km → "7 min block") · `2026-04-29` (Z2 5 km → **"5 reps"**) · `2026-04-01` | a Z2 prescription asserted as a session |
| short reps dropped, bookend promoted (handoff N4) | `2025-12-26` (4×30 s → "24 min block") · `2026-07-29` (4×20 s → **"32 min block", conf 1.00**) | the warm-up becomes the workout |
| `ACTIVE` bookends kept as reps (handoff N5) | `2026-06-05` (2 km Z-warmup + 4 km tempo → **"2 reps"**) · `2026-01-16` | a warm-up presented as a rep |
| recovery float counted as a rep | `2025-12-05` (2×2 km Z4 with a 3 min Z2 float → **"2-0.32-2 km", found 3**) | a jog presented as a rep |

**Count-level sweep, 2026-07-29 — the shape-level figure was short by exactly
one.** A shape scan cannot see `2025-12-05`, which agrees on shape (`reps`) and
differs only on count. Comparing every prescribed set's `numberOfIterations`
against the lens's `set.found`:

```
88 documents compared
   15 workouts prescribe a set        12 match exactly, 3 do not
   25 prescribe a single block
   48 prescribe nothing hard

the 3:  2025-12-05  found 3 / prescribed 2×2000 m Z4   ← the float (new)
        2025-12-26  found – / prescribed 4×30 s        ← N4, already counted
        2026-07-29  found – / prescribed 4×20 s        ← N4, already counted
```

**Revised total: 14 confirmed wrong of 88 (≈16 %), plus 1 ambiguous.** The
ambiguous one is `2025-12-14` — a 14 km run prescribed at **HR Z3**, which the
lens reads as `progression`. Z3 is not easy, and a progression is a defensible
reading of how it was executed, so it is excluded from the count and from the
veto (design D2).

This reshapes the case for the change. Rep-set detection is in good health —
**12 of 15 prescribed sets are already exactly right**, which is a strong
endorsement of change 2's step rule. The value is almost entirely in the other
three quadrants: not inventing sets where nothing was prescribed (6 runs),
finding prescribed blocks that were missed or fragmented (6 runs), and admitting
reps that are shorter than the inference floors (2 runs).

`2026-01-16` is the sharpest case, because nothing on the page suggests it is
wrong:

```
workout:  interval 2000 m  HR Z2              ← easy
          interval 1000 m  pace 5:45–5:59     ← the whole session
          recovery   60 s
          interval 2000 m  HR Z2              ← easy

lens:     "2-1-2 km", found = 3, source = laps, confidence 1.00
```

One prescribed rep, rendered as a three-rep pyramid at full confidence.

**Why this and not the `plan-data.js` parser** (handoff P3.2). Both fill
`build_document`'s `prior`; they differ by an order of magnitude in reach and in
fidelity:

| | plan-data parser | workout prior |
|---|---|---|
| runs reached | **12** (`plan_compliance` spans `2026-06-29 → 2026-08-02` only) | **92**, retroactive |
| rep pace band | parse `4×1 km @ 5:25–5:35`, `5×1 km by effort · Z4`, `3 km easy · 3×400 m @ 5:41 inside`, and prose that must parse to nothing | two floats |
| rep size | inferred from the string | `endConditionValue` |
| step roles | absent | `stepTypeKey` |
| step ordering | must run before `intervals_step`; today `compliance_step` runs **after** it | none — the workout travels with the activity |

The two are complementary, not competing: the workout is what was **pushed to
the device**, the plan is what the coach **meant**. This change takes the device
half, which is larger, cheaper, retroactive, and free of the step-ordering
problem.

## What Changes

- **Workout acquisition** in the deterministic sync: for any archived running
  activity whose `summary_json` carries a `workoutId` not already stored, fetch
  `get_workout_by_id` once and bank the raw payload. Cache-on-first-sight,
  idempotent, offline no-op — the same acquisition shape as lap DTOs.
  A `--backfill-workouts` flag catches up the 85 fetchable historical workouts.
- **A step-tree reader** turning the Connect payload into the prior:
  - Flatten `workoutSegments[].workoutSteps` depth-first, descending into
    `RepeatGroupDTO` and carrying `numberOfIterations` onto its children.
  - Map flattened steps to `wktStepIndex` by the **FIT** rule — one synthetic
    index is consumed *after* each repeat group's children, because
    `repeat_steps` follows the steps it repeats. Verified to reproduce
    `2026-06-05`, `2026-07-10` and `2026-07-29` exactly.
  - **Validate the mapping per activity**: every observed `wktStepIndex` must
    land on a step. A mismatch means no prior for that run, never a wrong one.
- **`prior` threaded into BOTH branches of `build_document`.** Today `prior` is
  read at line 903 — *after* the laps branch has already returned at line 876,
  with `"prescribed": None` hardcoded. The prior must sit upstream of the
  branch, which is what makes it one contract rather than a third place the two
  paths can disagree.
- **What the prior is allowed to decide**, in order of confidence:
  - `numberOfIterations` → `set.prescribed`, making the D4 honesty contract
    (*"3 of 4 prescribed reps found"*) reachable for the first time.
  - `stepTypeKey` → role, demoting `ACTIVE` warm-ups, cool-downs and
    transitions without inference (handoff N5).
  - `endCondition: time` → the set is named and compared **by duration**
    (handoff N3: `2026-02-06`'s "6×0.23 km" was prescribed `6 × 90 s`;
    `2025-11-21`'s "8×200 m" was `8 × 90 s`).
  - a prescribed rep smaller than `WORK_MIN_S` / `WORK_MIN_M` **is still a
    rep** — dissolving handoff N4, whose one-metre margin on `2025-11-21`
    (151 m vs 150 m) simply stops existing when the prescription is `90 s`.
  - `targetType` + `zoneNumber` → a step prescribed at HR Z2 cannot be quality;
    a `pace.zone` step is where to look for it.
  - `targetValueOne/Two` → rep-level `plan_compliance` against the band.
- **Confidence stops being a constant on the lap path.** Line 878 hardcodes
  `"confidence": 1.0` for every lap-sourced shape. A block that exists because
  our filters left one lap standing is not the same claim as a block the watch
  prescribed, and must not assert as one.
- **Provenance is part of the document.** A workout cached on first sight is
  trustworthy; one fetched by backfill is best-effort, because `updateDate` is
  `None` on every workout in this account and a silent edit is undetectable.
  The document says which it had.

## Capabilities

### New Capabilities

- `workout-prior`: workout acquisition from Garmin's workout service, the step
  tree → `wktStepIndex` reader and its per-activity validation, the prior
  contract, and the provenance marker.

### Modified Capabilities

- `activity-archive`: schema gains a `workouts` table plus a version marker for
  the derived prior.

**Note:** the interval lens itself is **not** an OpenSpec capability — it
shipped through the superpowers/SDD workflow and its ledgers were deleted on
completion, so git history is its record. The behaviour this change alters in
`interval_lens.py` (prior consumed before the laps/stream branch,
`set.prescribed` fillable on both paths, confidence derived rather than constant
on the lap path, `_reps_label` gaining a duration form, `INTERVAL_VERSION`
bumped to self-heal every stored document) is therefore specified in this
change's own `specs/workout-prior/spec.md` rather than as a delta. Its prior
designs are `docs/superpowers/specs/2026-07-27-interval-lens-design.md` and
`…/2026-07-28-interval-lens-workout-steps-design.md`.

## Impact

- **Python sync**: workout acquisition beside `_fetch_raw_laps` in
  `sync_garmin.py`; fail-soft, and it must never hold a write handle across a
  network call.
- **Schema**: additive — `workouts` (raw payload, fetched_at, provenance).
- **Engine**: `interval_lens.build_document` restructured so the prior precedes
  the laps/stream branch; `_rep_step_indices` becomes a **fallback** for runs
  with no workout rather than the primary rule.
- **Recompute**: `INTERVAL_VERSION` bump, ~169 documents, seconds, no migration.
- **Tests**: workout fixtures captured from the five shapes measured here
  (repeat-by-distance with a pace band, repeat-by-time with an HR zone, a
  no-repeat pyramid, a single-step block, an `ACTIVE`-warm-up trap), extending
  `tests/fixtures/` rather than leaning on the local archive — which has **no
  lap data at all**.
- **Closes or dissolves**: handoff N3, N4, N5, P2.7b, P3.1, and the concrete
  half of P2.2 and P2.3.

## Non-Goals

- **No `plan-data.js` segment parsing.** The coach's own intent stays
  unparsed; that is handoff P3.2 and remains a separate change. This one takes
  the device's prescription only.
- **No workout push.** `garminconnect` also exposes `upload_running_workout`
  and `schedule_workout`, which would collapse plan-intent and
  device-prescription into one object. Strategically interesting, out of scope.
- **No coverage for Max.** The Health Connect instance has neither Garmin
  workouts nor `plan_compliance` rows (`ingest_builder.py:635`). This change
  widens the gap between the two producers and must say so rather than pretend
  otherwise.
- **No claim on the 77 stream-sourced runs with no `workoutId`.** They keep
  today's inference path unchanged.
- **No re-fetch of already-cached workouts.** Silent edits are undetectable;
  chasing them would trade a knowable provenance for an unknowable one.

## Open Questions

1. **Is the human-authored workout trustworthy enough to override execution?**
   It is imperfectly typed: `2026-06-26` types its warm-up `warmup`,
   `2026-06-05` types the same thing `interval`. Where the prior and the
   execution disagree, which wins?

   *Validated across all 85 cached workouts (2026-07-29):* 62 have a single work
   step, 12 a repeat group, 11 multiple work steps with no repeat. Of those 11,
   grouping by target **type** alone leaves 2 ambiguous — and one of them,
   `W9 HM-Training: Tempo` (`2025-12-05`), proves the rule as first drafted is
   **wrong**:

   ```
   warmup    2000 m  HR Z2
   interval  2000 m  HR Z4   ┐  all three work steps share heart.rate.zone,
   interval   180 s  HR Z2   │  so "shared target type" makes this a 3-rep set
   interval  2000 m  HR Z4   ┘  — it is 2×2 km with a 3-minute float
   cooldown  2000 m  HR Z2
   ```

   The lens reads it `"2-0.32-2 km", found 3` today, counting the float as a
   rep. The discriminator must therefore be the target's **value** (Z4 vs Z2),
   not its type. The pyramid survives because its three steps share `pace.zone`
   *and* near-identical bands (6:05–6:14 / 5:59–6:10 / 6:05–6:14). Specified as
   "Set membership is decided by a target's value, not merely its type".
2. **What does a prescribed-but-not-executed rep mean for `found`?** D4 says a
   bailed session reports *"3 of 4"*. Does an abandoned workout — warm-up only —
   report `found: 0, prescribed: 5`, or no set at all?
3. **`2026-05-29` reads `prescribed: 4` while its activity is named
   `Tempo: 5x 1km (Pace 6:00-6:10)`.** The handoff records this as *"four of a
   prescribed five"*, reasoning from the name. Either the workout was edited or
   the name was always stale. This is the staleness hazard in miniature, and it
   settles that **the activity name is not the prescription**.
