# The workout step decides what is a rep — design

**Date:** 2026-07-28
**Follows:** `docs/superpowers/specs/2026-07-27-interval-lens-design.md` (Change 1, merged `46e8100`)
**Closes from `HANDOFF-interval-lens.md`:** P1.1, P1.2, P2.1, P2.7a, and the lap-path
half of M3. Records new evidence against P2.3 and corrects one handoff claim.

---

## 1. The defect

`interval_lens._LAP_ROLES` maps `ACTIVE` → `work` unconditionally. Garmin emits
`ACTIVE` for laps that are not reps:

- a warmup or cooldown the athlete built as an `ACTIVE` workout step
  (`2026-03-20` lap 1 = `ACTIVE 2000 m/855 s`, lap 12 = `ACTIVE 2000 m/1007 s`);
- a one-off transition step inside a structured workout
  (`2025-10-17` lap 2 = `ACTIVE 394 m/209 s`, between the WARMUP and the first
  genuine 90 s rep);
- a manual lap pressed outside the structure entirely
  (`2026-05-29` lap 10 = `ACTIVE 926 m/420 s`, *after* the COOLDOWN).

`_apply_lap_work_floor` (the P2.7 fix) catches only *tiny* fragments. These are
oversized, so no value of `WORK_MIN_S`/`WORK_MIN_M` reaches them.

Measured on the live archive, 2026-07-28 — 8 of 23 lap-sourced documents count
non-reps as reps, corrupting the count, the label, `paceCvPct` and `fadePct`:

| Session | Reads today | Truth |
|---|---|---|
| `2026-04-10` W14 Tempo | `5×2 km`, cv 14.8, fade **+17.5 %** | `3×2 km`, cv 1.7, fade +0.6 % |
| `2026-03-20` W11 Tempo | `7 reps`, cv 19.5, fade **+18.0 %** | `5×1 km`, cv 2.4, fade +2.3 % |
| `2026-02-06` W5 Hügel | `8 reps`, cv 15.4, fade +10.1 % | 6 × ~230 m, cv 2.1, fade −3.2 % |
| `2025-12-12` W10 Hügel | `7×300 m`, fade **+37.1 %** | `6×300 m`, cv 4.2, fade −4.0 % |
| `2025-10-17` W5 Hügel | `8 reps`, cv 23.9 | `6 reps`, cv 17.4 |
| `2026-05-29` Tempo 5×1 km | `5×1 km`, fade **+30.5 %** | `4×1 km`, cv 2.4, fade +0.3 % |
| `2025-12-19` W11 Tempo | `1.5-0.627 km` | one block |
| `2024-07-22` Run Walk Run® | `3 reps` (**P2.7a**) | not a rep set |

The stream path is unaffected — it finds bouts by pace threshold and never
reads a lap tag.

### 1.1 A handoff claim this overturns

`HANDOFF-interval-lens.md` §P2.3 records `2026-05-29` recovering as
`5×1 km [1000, 1000, 1000, 1000, 926]` and treats that as the engine working.
It is not: the 926 m "rep" is lap 10, run **after** the COOLDOWN at 7:33/km —
1:45/km slower than the four real reps — and carries **no workout step index at
all**. The watch executed four reps of a prescribed five. The correct read is
`4×1 km`, and once Change 2 fills the prior, *"4 of 5 prescribed"*.

---

## 2. The discriminator: `wktStepIndex`

Garmin lap DTOs carry `wktStepIndex` / `wktIndex` — the workout **step** the lap
executed — on 294 of the archive's 565 laps. Reps of one set share a single
**repeated** step index; warmups, cooldowns and transitions occupy their own
step, used once.

`2025-12-12` is the clearest specimen:

```
 #  intensity   step    dist    dur
 1  WARMUP         0   1500m   725s     the warmup
 2  ACTIVE         1     45m   157s     a one-off transition to the hill
 3  ACTIVE         2    286m   120s  ┐
 5  ACTIVE         2    296m   120s  │
 7  ACTIVE         2    321m   120s  ├  step 2, used six times = THE SET
 9  ACTIVE         2    283m   120s  │
11  ACTIVE         2    284m   120s  │
13  ACTIVE         2    297m   120s  ┘
14  ACTIVE         5    267m   154s     a one-off jog-in, currently rep 7
15  COOLDOWN       6    734m   456s
```

Lap 14 alone produces that session's `+37.1 %` fade.

### 2.1 The rule

Applied to work-role laps that already clear the `WORK_MIN_S`/`WORK_MIN_M`
floor, in this order:

1. **No lap in the activity carries a `wktStepIndex`** → keep all of them.
   Unstructured runs and manually-lapped runs behave exactly as today; the rule
   cannot fire where the evidence it needs does not exist.
2. **Some step index occurs more than once among the work laps** → the set is
   exactly the laps whose step index is among the repeated ones. Every other
   work lap is demoted. Counting is over work laps only: a `RECOVERY` step
   repeating says nothing about which laps are reps. More than one step index
   may repeat, and all of them are kept — an alternating session
   (4 × [1 km hard, 1 km moderate]) is one set with two repeated steps.
3. **Every work step index is distinct** → demote only work laps carrying no
   step index at all. This is the genuinely-varied session — the `1-2-1 km`
   pyramid of `2026-06-26` has three distinct steps and must survive intact.

Ordering matters: rule 3 is the fallback for a session with no repeat block, and
must not be reached when a repeat block exists.

### 2.2 Demotion re-roles, never deletes

`_apply_lap_work_floor` already establishes this contract and the new rule
reuses it verbatim: a demoted lap keeps its `idx`, `t0/t1`, `d0/d1`, `durS`,
`distM` and statistics, and takes the role `warmup` (before the first surviving
rep), `cooldown` (after the last) or `recovery` (between). `rep` renumbers
1..N over survivors only.

Deleting would open a hole in the run's span, which `_quality`'s summation and
the rep-shaded stream chart both rely on being gapless.

Both filters — the size floor and the step rule — are two answers to one
question, so they live in one function that owns "which lap is a rep", with one
re-role implementation beneath them.

---

## 3. The block floor on the lap path

`build_document`'s laps branch decides
`shape = "reps" if len(work) >= 2 else ("block" if work else "steady")` with no
minimum on the block case, while the stream path has always applied
`BLOCK_MIN_S` (300 s) / `BLOCK_MIN_M` (1500 m). The laps branch gains the same
test — **on the same OR basis**: `classify()` reads
`if b - a >= BLOCK_MIN_S or dist >= BLOCK_MIN_M`, so either arm alone makes a
block, and the laps branch must match it or the two producers disagree about
what a block is. (Corrected after Task 3's review, which caught this section
claiming parity while the implementation used AND.)

This matters more after §2, which makes the single-surviving-work-lap case
common. Measured blast radius — exactly one run flips to `steady`:

- `2024-07-22 Run Walk Run®`, 205 m / 62 s — fails both arms. **Closes P2.7a.**

`2024-07-13 Einstufungslauf` (801 m / **exactly** 300 s) was expected to flip
too, and does not: its duration sits precisely on `BLOCK_MIN_S`, so the OR's
duration arm carries it and it stays a `block`. One flip, not two.

All six genuine tempo blocks (2000–3040 m) are untouched.

**Explicitly out of scope: P2.7b.** The lap path's `len(work) >= 2` versus the
stream path's `REPS_MIN_COUNT = 3` stays as it is. It is entangled with Change
2's `expect_reps` (P3.1), and unifying it now would demote the legitimate
two-rep session of `2026-06-05` (`[2000, 4000]`).

---

## 4. GAP comes from the device

`segments_from_laps` derives `gapS` by windowing the stream's grade-adjusted
grid, justified by a docstring asserting "a lapDTO carries no grade-adjusted
speed". That is false: `avgGradeAdjustedSpeed` is present on 553 of 565
archived laps.

Take the device value when present; fall back to the stream window otherwise.
Correct the docstring.

This also removes the lap path's exposure to **M3** — lap `duration` is moving
time, so on a paused run the accumulated `t0` drifts off the stream's elapsed
axis and the windowed lookup reads the wrong slice. Measured across all 17
lap-sourced structured runs: drift is 0 s on every one except `2026-06-26`,
which drifts 40 s. Latent today, gone entirely on the primary path afterwards.

M3's other half — `d0/d1` accumulating from lap `distance`, and the assumption
that the stream clock starts at 0 — is unchanged and stays on the handoff.

---

## 5. One basis for the reported numbers

`paceCvPct` and `fadePct` are computed from **different signals on the two
paths** today: `set_stats` uses the grade-adjusted detection grid, the laps
branch uses raw lap `averageSpeed`. Both become **raw**.

Consequences: the sub-line, the deviation bars and the `PACE` column all measure
the same thing, so the card needs no source-dependent qualifier; and the two
producers stop disagreeing, which is what the one-engine design exists to
prevent.

**Detection is untouched.** It stays on the grade-adjusted signal per design D5
— only reporting changes.

### 5.1 Why raw, and why this closes P2.1

P2.1 asked whether the deviation bars should measure GAP or raw pace, and said
to decide by looking at a hilly session. Measured across every lap- and
stream-sourced set in the archive:

- On the one **uncontaminated** hill-repeat set (`2025-11-21`, all eight laps
  genuine 90 s reps), raw is **tighter**: cv 9.1 % vs GAP 14.7 %. Fixed-duration
  reps cover less ground as the athlete tires — 200 m down to 151 m — so each
  rep samples a different slice of the gradient and its grade adjustment varies
  (rep 1 ratio 1.60, rep 4 ratio 1.36). GAP there measures the hill, not the
  athlete's consistency.
- On the **stream** path the two bases differ by under 1.5 points and split both
  ways across 11 sets. It does not matter.
- The large GAP-vs-raw gaps on the other hill sets are §1 contamination, not
  terrain.

No case in the archive supports moving the bars to GAP. `gapS` stays as the
per-rep column, which is where the terrain-adjusted read belongs.

### 5.2 What this trades away, deliberately

`test_fade_is_measured_on_effort_while_the_reported_pace_is_raw` encodes the
opposite rule and is being reversed on purpose. Its fixture is five reps up a
**steady continuous drag**: raw pace decays 4.4 → 3.6 m/s while grade-adjusted
effort never moves, and it asserts `fadePct == 0.0`. Under raw reporting that
same set reads as roughly a 22 % fade.

That is the real cost, and design D5 named it — "using raw pace would split one
set into a fade". Two reasons it is still the right trade:

- **D5 governs detection, and detection is unchanged.** The bouts are still
  found on the grade-adjusted signal, so the set is still detected as one set.
  Only the number reported beside it changes.
- **The fixture's shape does not occur in this archive.** Every hill session
  runs each rep up the *same* hill and recovers back down, so successive reps
  share terrain and raw pace compares them honestly. A point-to-point set
  climbing continuously across its whole span would be misreported; none
  exists in 168 runs.

Revisit if such a session ever appears. The test is rewritten to assert the new
contract and to state this reasoning, not deleted.

---

## 6. The rep table (P1.1)

`run.dc.html` renders pace and GAP as two adjacent unlabelled monospace numbers.
Add `PACE` and `GAP` column headers to the rep card, aligned to the existing
52 px columns.

With §5 the sub-line needs no qualifier — it now rides the same signal as the
bars beside it.

---

## 7. Surfacing `calibrated: false` (P1.2)

`build_document` sets `calibrated` on every document and nothing reads it, so
*"we don't have enough history to judge structure yet"* renders identically to
*"we looked and found nothing"*. That is Max's live state: `work_floor` needs
`WORK_FLOOR_MIN_SAMPLES` = 20 000 samples ≈ 30 runs.

`/run/:id` states it plainly when `intervals.calibrated === false` — one line,
in the rep table's place, saying structure has not been judged yet and why. The
by-id endpoint already serves the whole document, so this is frontend-only.

Lap-sourced documents are always `calibrated: true` (the watch is not guessing),
so this surfaces only where it is true.

`/archive` is already honest — it suppresses the chip for `steady`, so it never
asserts a shape nobody computed. Unchanged.

---

## 8. Rollout

`INTERVAL_VERSION` 3 → 4. The document is a disposable versioned cache: the next
sync recomputes every document in seconds, no migration.

Before believing the change, run the archive sweep read-only and compare the
shape distribution against the merge baseline (`steady 138 / reps 19 / block 5 /
progression 2`, floor 2.700). Expected movement is confined to lap-sourced runs:
two block→steady flips (§3) and eight rep-set corrections (§1).

---

## 9. Testing

Fixtures, each mutation-tested — break the rule and confirm the suite goes red,
per the branch's own standard:

- a lap set with a repeat block plus one-off `ACTIVE` bookends → only the repeat
  block survives, bookends re-roled not deleted, span still gapless;
- a lap set where every work step is distinct (the pyramid) → untouched;
- a lap set with no `wktStepIndex` anywhere → untouched;
- a work lap with no step index in a set that has one → demoted;
- a single surviving work lap below `BLOCK_MIN_M` → `steady`, above → `block`;
- `gapS` taken from `avgGradeAdjustedSpeed` when present, from the stream window
  when absent;
- `paceCvPct` / `fadePct` raw on both paths, over one fixture per path.

### 9.1 The truth test cannot cover this, so a fixture must

The local `activity-archive.db` holds 548 activities and **zero** with
`laps_json` — the lap backfill happened on the NUC and was never copied down.
`test_interval_truth.py` therefore cannot exercise the lap path at all, and
every case in §1 would go unverified by it.

So the eight sessions become a **committed fixture**: their lap DTOs, trimmed to
the fields the engine reads (`distance`, `duration`, `elapsedDuration`,
`averageSpeed`, `avgGradeAdjustedSpeed`, `averageHR`, `intensityType`,
`wktStepIndex`), extracted from the NUC into a JSON file in the repo. Each gets
a test asserting its corrected count, label, spread and fade from §1's table.

This is strictly better than relying on the archive: it runs in CI, it pins the
exact production defects permanently, and it cannot silently skip.

`test_interval_truth.py` itself is unchanged — it reads run names off a
lapless archive and keeps testing the stream path, which this change does not
touch except for §5's reporting basis.

---

## 10. Not in scope

- **Duration-named sets.** With §2 applied, `2026-02-06` labels its six 90 s
  hill reps `6×0.23 km`, because their mean distance snaps to no round target.
  Those sets want naming by duration (`6×90 s`), which is a `_reps_label` change
  with its own blast radius across the `/archive` chip, the rep-card title and
  the cockpit sentence. Log it.
- **P2.7b**, per §3.
- **P2.3 (windowed baseline).** §1.1 removes the last evidence for it: the run
  that motivated it takes the lap path, where the calibration floor is never
  consulted. The handoff's "do not build this without new evidence" stands.
- **P2.2 (boundary extension)**, P2.4–P2.6, P3.x, M1–M13 except the lap half of
  M3.
