## Context

`interval_lens.py` decides a run's structure by inferring it from execution —
sample streams, or Garmin lap DTOs when the watch recorded something structured.
`build_document` has always taken a `prior` parameter, and it has always been
`None` (design D8). The handoff's plan was to fill it from `plan-data.js`.

An exploration on 2026-07-29 measured the alternative against production,
read-only. `summary_json.workoutId` is present on 92 of 170 running activities
(89 distinct workouts), including **all 24 lap-sourced documents**, and
`garminconnect.Garmin.get_workout_by_id` is already installed. The workout
payload carries the roles, counts, sizes and pace bands the engine currently
infers. See `proposal.md` for the full measurement.

Three structural facts shape this design:

1. **The laps branch never reads `prior`.** It returns at `interval_lens.py:876`
   with `"prescribed": None` hardcoded; `prior` is first read at line 903. Any
   prior placed at the current read site governs the stream path only — and the
   runs that carry a prescription are overwhelmingly lap-sourced.
2. **Rep detection is already good.** 12 of 15 prescribed sets match
   `numberOfIterations` exactly. This is the first *independent* confirmation of
   change 2's step rule (`test_interval_laps_truth.py` is circular by
   construction — handoff N2). The change must not regress it.
3. **The errors are elsewhere.** 14 confirmed wrong of 88, concentrated in
   inventing sets where nothing hard was prescribed, missing or fragmenting a
   prescribed block, and rejecting reps shorter than the inference floors.

## Goals / Non-Goals

**Goals:**

- Acquire and bank each run's workout definition once, idempotently, fail-soft.
- Give `build_document` a prior that both producers read by identical rules.
- Fix the 14 confirmed errors without disturbing the 12 correct sets.
- Make `set.prescribed` real, so design D4's honesty contract is reachable.
- Extend confidence with corroboration, on the base `fix-lap-confidence` lays.

**Non-Goals:**

- Removing the lap path's hardcoded `confidence: 1.0` — split out as
  **`fix-lap-confidence`**, which ships FIRST and is a prerequisite (see D8).
- Parsing `plan-data.js` `segments[].val` (handoff P3.2) — separate change.
- Pushing workouts *to* Garmin (`upload_running_workout`) — see Open Questions.
- Any coverage for the Health Connect instance; `ingest_builder` continues to
  pass `prior=None` and its behaviour is unchanged.
- Re-fetching workouts already banked.
- Rep-level pace compliance on the **stream** path (see D9).

## Decisions

### D1 — The prior VETOES, POINTS and ADMITS; it does not re-derive

The prior constrains the existing engine rather than replacing it. Three
operations, in increasing order of intervention:

| op | the prior may | example |
|---|---|---|
| **VETO** | forbid a segment being reported as work | a step prescribed at HR Z≤2 can never be a rep or a block |
| **POINT** | declare that a shape was prescribed, so the engine looks for it rather than inventing another | `1×5 km @ pace.zone` prescribed → do not report 4 reps |
| **ADMIT** | exempt a prescribed rep from the inference size floors | `4×20 s` prescribed → `WORK_MIN_S = 30` does not apply |

Segment boundaries, paces, HR and every reported number still come from
execution. Traced against all 14 confirmed errors, these three operations fix
every one.

*Alternatives considered.* **Full override** — derive roles and set membership
from the workout, take only measurements from execution. Rejected: the workout
is human-authored and imperfectly typed (`2026-06-05` types its warm-up
`interval`; `2026-06-26` types the same thing `warmup`), so override would
propagate an athlete's authoring mistake straight into the document with no
execution-side check. It also puts the 12 currently-correct sets at risk for no
measured gain. **Gap-fill only** — the prior adds `prescribed` and pace bands
but never contradicts. Rejected: fixes 0 of the 14.

### D1a — POINT locates from the prescription and confirms from execution

VETO and ADMIT are precise operations. POINT is the one with latitude, and it
carries six of the fourteen errors, so it is specified here rather than left to
implementation.

```
1. prescribed size  →  slide a window of exactly that distance (or duration)
2. pick the best-matching window in the run
3. CONFIRM: its mean pace must fall within the prescribed band
     in band     →  block; boundaries come from the window
     out of band →  the athlete did not run it; fall back to inference
```

The prescription **locates**; execution **decides**. Step 3 is the entire safety
property and is directly mutation-testable: break the band check and a run
plodded at 7:00/km must still refuse to report the prescribed block.

*Measured, all six runs.* The three the lens misses entirely are not marginal —
the best window of the prescribed size lands in band and begins within three
metres of where the workout says the block starts, right after the 2 km warm-up:

```
2026-01-09  1×2000 m @ 5:59–6:14   best window 6:08/km, starts at 1998 m
2026-02-13  1×4000 m @ 5:39–5:49   best window 5:37/km, starts at 2001 m
2026-02-27  1×2000 m @ 5:29–5:59   best window 5:28/km, starts at 1998 m
```

The same rule absorbs the three fragmented ones with no second mechanism — the
window that reproduces the prescribed distance is exactly the window enclosing
the fragments:

```
2026-03-13  prescribed 5000 m   fragments span 2053 → 7027 m = 4974 m
2026-04-03  prescribed 7000 m   fragments span 2060 → 9062 m = 7002 m
2026-01-23  prescribed 3000 m   fragments span 2069 → 5035 m = 2966 m
```

*Alternatives considered.* **Lower the calibration floor inside the prescribed
window** — only `2026-01-09`'s band (slow end 6:14) sits below the 6:09 floor;
the other five clear it comfortably and fail for unrelated reasons. Fixes 1 of
6. **Assert the block from the prescription outright** — no execution check, so
a workout the athlete skipped would report as completed, inverting the honesty
contract.

*Consequence.* POINT never consults the calibration floor. That closes handoff
**P2.3**: the three runs it demanded as evidence for a windowed baseline are
fixed without any baseline at all.

*Note for implementation.* `2026-01-23` carries a **304 s gap** mid-block.
Merging it into one block is right — "4 reps" is plainly worse — but the result
must be **hedged rather than asserted**, which is what the confidence work in
`fix-lap-confidence` + D8 exists to carry.

### D2 — The veto threshold is HR zone ≤ 2, and Z3 is deliberately untouched

Measured across every case whose fix depends on a veto:

```
2026-06-05  warm-up typed `interval`  … zone 2   ← veto fires despite the mistyping
2026-01-16  both bookends              … zone 2
2025-12-24  single step                … zone 2
2026-04-29  single step                … zone 2
2026-04-01  single 8 km step           … zone 2
2025-12-05  the float                  … zone 2
2025-12-14  single 14 km step          … zone 3   ← NOT vetoed
```

The veto reads the **target**, not the step type — which is why `2026-06-05`'s
mistyping stops mattering. Z3 is excluded deliberately: `2025-12-14` is a 14 km
Z3 run that the lens reads as `progression`, which is a defensible reading of
how it was executed. Vetoing Z3 would suppress a true positive to fix nothing.

### D3 — Set membership needs the target's VALUE, not just its type

First drafted as "reps of a set share a target type". Validated across all 85
cached workouts, that fails on `W9 HM-Training: Tempo` (`2025-12-05`): three
work steps all on `heart.rate.zone`, being Z4 / Z2 / Z4 — a 2×2 km with a
3-minute float, which the type-only rule would call a 3-rep set (and which the
lens today reads as `"2-0.32-2 km", found 3`).

So grouping compares type **and** value: pace band, or zone number. The genuine
pyramid (`2026-06-26`) survives because its three steps share `pace.zone` *and*
near-identical bands (6:05–6:14 / 5:59–6:10 / 6:05–6:14).

Of 85 workouts: 62 have a single work step, 12 a repeat group, 11 multiple work
steps with no repeat. Only those 11 need this rule at all.

### D4 — The prior is resolved BEFORE the laps/stream branch

This is the structural half of the change. Today `prior` is read after the laps
branch has returned. Moving its resolution upstream is what makes it one
contract instead of a third place the two producers can disagree — and it
retires handoff **P2.7b** (two independent rep-count floors) and **P3.1**
(`classify`'s floor breaking the honesty contract at 2-of-4) as structural
consequences rather than as prerequisites to be fixed first.

### D5 — Cache on first sight; never re-fetch

`updateDate` is `None` on every workout in this account, so an edit after the
fact is undetectable. Re-fetching would trade a knowable provenance for an
unknowable one. A workout banked when the run was new reflects what was
executed; one recovered by backfill is best-effort. The document records which,
and the backfill marker is not merely cosmetic — it is the only honest signal
that a historical prescription may have drifted.

Evidence: `2026-05-29`'s activity is named `Tempo: 5x 1km (Pace 6:00-6:10)` while
its workout says `numberOfIterations: 4`. Either it was edited or the name was
always stale. Unknowable — and it settles that the **activity name is not the
prescription**.

Measured attrition: 85 of 89 workouts still fetchable (4 deleted).

### D6 — Store the raw payload; derive the prior at build time

The `workouts` table holds the Connect payload verbatim plus `fetched_at` and
provenance. All interpretation — flattening, index mapping, grouping — happens
inside `interval_lens` at `build_document` time, versioned by
`INTERVAL_VERSION`. No second version marker, and a rule change self-heals every
document on the next sync exactly as threshold changes do today.

*Alternative:* bank a derived `prior` document per activity. Rejected — it adds
a version marker to keep in sync with `INTERVAL_VERSION` and buys nothing; the
derivation is microseconds.

### D7 — The step→lap join is all-or-nothing, and verified per activity

Flatten `workoutSegments[].workoutSteps` depth-first, descending into
`RepeatGroupDTO` and carrying `numberOfIterations` onto its children. Consume one
index position **after** each repeat group's children — the FIT encoding, where
`repeat_steps` follows the steps it repeats:

```
stepOrder  1  [2=repeat]  3  4  5
wktStepIdx 0              1  2      4
                       ▲
                3 = the repeat instruction itself
```

Verified to reproduce `2026-06-05`, `2026-07-10` and `2026-07-29` exactly.

Every `wktStepIndex` observed on the laps must land on a flattened step. If any
does not, the prior for that activity is **discarded entirely** and the run
falls back to inference. A partial mapping is never used: a half-applied prior
is worse than none, because it looks authoritative.

### D8 — Confidence gains corroboration, on a base that ships first

`interval_lens.py:878` hardcodes `"confidence": 1.0` for every lap-sourced
shape. Measured, stream blocks *are* hedged (0.52 / 0.61 / 0.77) — the constant
is the lap branch's alone, and it is why today's easy run asserts a
`"32 min block"` at full confidence.

**Split into two changes.** Removing the constant needs no workout data, no
schema and no fetch, so it ships first as **`fix-lap-confidence`** with its own
`INTERVAL_VERSION` bump. This change then extends it:

```
fix-lap-confidence  (ships first, no dependency)
    a shape that survives only because filtering removed other
    candidates must NOT assert
      → 2026-07-29 "32 min block", 2025-12-26 "24 min block"  hedged
      → 2026-01-16, 2025-12-05 NOT helped — nothing was filtered,
        those keep bookends/floats IN, so there is no signal to hedge on

add-workout-prior   (this change, extends the above)
    prescription exists and found == prescribed  → assert
    prescription exists and they disagree        → hedge
    POINT merged across a gap                    → hedge  (D1a, 2026-01-23)
```

Two reasons for the split beyond earlier relief. First, honesty: the base change
stops the page **asserting** wrong things, it does not make them **right**, and
shipping it inside a larger change would blur that. Second and more important,
**it is a prerequisite** — D1a merges `2026-01-23` across a 304 s gap, and that
is only defensible if there is already somewhere to put the uncertainty.

Cost is two `INTERVAL_VERSION` bumps, which this design treats as cheap by
construction.

### D9 — Rep-level pace compliance is lap-path only, initially

Comparing a rep to its prescribed band requires knowing which step it executed.
`wktStepIndex` gives that directly on the lap path. The stream path has no such
join, and inventing one (matching bouts to steps by order) is the kind of
plausible heuristic this codebase has been bitten by. Stream-sourced documents
get `prescribed` and the VETO/POINT/ADMIT operations, but not per-rep band
comparison.

### D10 — A bailed session reports `found: 0, prescribed: N`

Design D4 already promises *"3 of 4 prescribed reps found"*. Zero is the
limiting case, not a special one: a workout begun and abandoned is a real
training event and the page should say so rather than presenting the warm-up as
a plain easy run.

## Risks / Trade-offs

- **A mistyped workout propagates into the document.** → D1 keeps the prior
  constraining rather than deriving, and D2 reads targets rather than step
  types. `2026-06-05` is the proof: its warm-up is mistyped and the veto still
  fires correctly.
- **A network call inside the sync.** → Fail-soft, and — mirroring handoff
  **M1**, where `_fetch_raw_laps` caches an envelope *before* confirming
  `lapDTOs` is non-empty — the row is written only after a usable payload is
  confirmed. Never hold a write-capable SQLite handle across the call.
- **89 GETs on backfill could rate-limit the account and break the nightly
  sync.** → Throttled and resumable, run once, out of band from the nightly
  path.
- **Silent workout edits are undetectable.** → Provenance marker (D5); backfilled
  prescriptions are marked best-effort and never presented with first-sight
  authority.
- **The recompute moves documents.** → `INTERVAL_VERSION` → 5 rescoring all ~169.
  The handoff's baseline (`reps 24 / steady 130 / block 12 / progression 2`,
  `stream 145 / laps 23`, floor `2.700`) is the diff target; the expected
  movement is the 14 named runs and nothing else. Anything else moving is a
  defect.
- **This widens the gap between the two producers.** → Max's instance has
  neither workouts nor `plan_compliance` rows (`ingest_builder.py:635`). The
  one-engine design survives — both still call `build_document` — but only one
  producer can supply a prior. Stated, not hidden.
- **Mutation-testing is not optional here.** → Change 1 left four surviving
  mutations (handoff P2.5/P2.6); change 2 found five more in code that had
  already passed review. Every rule added here must be shown to fail the suite
  when broken.
- **Local testing cannot reach the lap path.** → The local `activity-archive.db`
  has **no lap payloads at all**. Extend `tests/fixtures/lap_workouts.json` and
  add a workout fixture set; never lean on the local archive for a lap-path
  conclusion.

## Migration Plan

0. **`fix-lap-confidence` ships first** and is deployed before this change
   starts — D1a depends on the hedging it introduces.
1. Schema: additive `workouts` table. No migration of existing rows.
2. Ship acquisition first, dark — bank workouts on sync, nothing reads them.
   Confirms the fetch, the cache and the fail-soft path in isolation.
3. `--backfill-workouts`, throttled and resumable, out of band. Expect ~85 of 89.
4. Engine change behind `INTERVAL_VERSION` → 5. Next sync recomputes every
   document; seconds, no migration.
5. Verify with the read-only production sweep in the handoff, diffed against the
   recorded baseline.
6. Deploy is CI-mediated: merge to `main` → `gh run watch <id> --exit-status` →
   `docker compose pull` on the NUC. Check `docker top splits` for orphans first,
   and never wrap `ssh … docker …` in a client-side `timeout`.

**Rollback:** revert `INTERVAL_VERSION`; the next sync recomputes every document
from streams and laps alone. The `workouts` table becomes inert rather than
wrong — nothing else reads it.

## Sequencing

```
1. fix-lap-confidence   small; no schema, no fetch. Stops today's false
                        assertion and is a prerequisite for D1a.
2. add-workout-prior    this change — acquisition + VETO / POINT / ADMIT.
                        Fixes the 14.
3. P3.2 plan parser     the coach's intent; 12 runs; rep-level compliance
                        against what was MEANT rather than what was pushed.
4. (deferred) push      only once 2 and 3 both exist — see Parked below.
```

## Parked

**Pushing workouts to Garmin.** `garminconnect` exposes
`upload_running_workout` and `schedule_workout`. If the plan were pushed to the
watch, plan-intent and device-prescription would stop being two artifacts that
can drift and become one object. Deliberately deferred, for three reasons:

1. **It saves none of the work it appears to.** Pushing the plan means
   translating `4×1 km @ 5:25–5:35` into a step tree — which *is* the P3.2
   parser. It is a writer built on top of that change, not a shortcut past it.
2. **It makes the prescription circular.** The lens's authority here comes from
   the workout being an *independent* record of intent. Once SPLITS generates
   it, the lens reads back its own output and calls it ground truth.
3. **It turns the sync into a writer against an external service.** Today it
   writes only tokens. A failed or partial push leaves watch and plan
   disagreeing, with no `updateDate` to detect it — the same blindness that
   already forces the provenance marker in D5.

Revisit after step 3, when both halves exist and pushing is a small step that
collapses them.

## Working on this in a fresh session

### The measurement cache — ephemeral, and it cost 85 authenticated calls

Every finding in this change and in `proposal.md` was measured from a cache built
on 2026-07-29:

```
NUC → container `splits` → /tmp/workouts.json
   {"workouts": {"<workoutId>": <raw Connect payload>, …},   # 85 entries
    "gone":     [<workoutId>, …]}                            # 4 deleted
```

**It lives in the container's `/tmp` and dies with the next restart.** Nothing
persists it — that is what this change's `workouts` table is for. Rebuilding it
means ~85 authenticated `get_workout_by_id` calls against Felix's Garmin account,
so check whether it is still there before re-fetching, and do not re-fetch
casually: excessive auth risks the nightly sync.

```bash
ssh felix@192.168.0.37 'docker exec -i splits python -c "import os;print(os.path.exists(\"/tmp/workouts.json\"))"'
```

Note `sync_garmin.connect()` loads cached tokens from
`DATA_DIR/.garmin_tokens`, so a fetch is token-backed and needs no password or
MFA — but it is still an outward-facing call. Ask before making it.

### Rebuilding the cache

```python
# ssh felix@192.168.0.37 'docker exec -i splits python -' <<'PY'
import json, sqlite3, sys, time
sys.path.insert(0, '/app')
import sync_garmin
c = sqlite3.connect('file:/data/activity-archive.db?mode=ro', uri=True)   # READ-ONLY
wids = {}
for r in c.execute("SELECT activity_id, start_time_local, summary_json FROM activities "
                   "WHERE summary_json IS NOT NULL ORDER BY start_time_local"):
    w = json.loads(r[2] or '{}').get('workoutId')
    if w: wids.setdefault(w, []).append((r[0], r[1][:10]))
client = sync_garmin.connect()
store, gone = {}, []
for wid in wids:
    try: store[str(wid)] = client.get_workout_by_id(wid)
    except Exception: gone.append(wid)
    time.sleep(0.15)                      # be gentle; ~35 s for 89
json.dump({"workouts": store, "gone": gone}, open('/tmp/workouts.json', 'w'))
print(f"fetched {len(store)} / gone {len(gone)}")
```

### The flattener — the FIT index rule in code

Every measurement in this change goes through this. `_it` carries the enclosing
repeat group's `numberOfIterations` down onto the steps it repeats:

```python
def flat(steps, out, it=None):
    for s in steps:
        if s.get('type') == 'RepeatGroupDTO':
            flat(s.get('workoutSteps') or [], out, s.get('numberOfIterations'))
        else:
            out.append(s | {"_it": it})

# then, per workout:
out = []
for seg in (w.get('workoutSegments') or []):
    flat(seg.get('workoutSteps') or [], out)
```

The fields that matter, per flattened step:
`stepType.stepTypeKey` · `endCondition.conditionTypeKey` · `endConditionValue` ·
`targetType.workoutTargetTypeKey` · `targetValueOne` / `targetValueTwo` (m/s) ·
`zoneNumber` · `_it`.

**`zoneNumber` is easy to miss and it is load-bearing.** A first pass that read
only `targetValueOne/Two` mistook four correct HR-Z4 tempo blocks for "no target"
and reported them as lens errors. `heart.rate.zone` targets carry their
intensity in `zoneNumber`, not in the target values — see D2 and D3.

Positions in `out` do **not** map straight to `wktStepIndex`: one index is
consumed after each repeat group's children (D7). Verify per activity before
trusting any mapping.

## Open Questions

1. **Does POINT's window confirm for the wrong reason when the athlete
   substituted a session?** D1a believes a prescribed block when the best window
   of the right size falls in the prescribed band. A genuine rep set run over
   the same stretch can average into that same band — so a workout prescribing
   `1×5 km @ 5:34–5:45` that the athlete actually ran as `5×1 km` hard/easy
   could confirm as a block and have its real structure erased.

   No archive case exercises this: every prescribed block in the 88 was either
   run as prescribed or not run at all. The likely discriminator is within-window
   pace **variance** — a true block is flat, a substituted set is not — but there
   is nothing to measure it against, so the threshold cannot be set honestly
   from this archive. **Ship POINT with the variance guard in place and its
   threshold deliberately conservative, and revisit when a real case appears.**
