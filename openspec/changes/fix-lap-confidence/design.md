## Context

`interval_lens.build_document`'s laps branch sets `"confidence": 1.0` at
line 878 — a literal, not a computed value. `_confidence()` (line 747) exists
and works, but its three factors are all stream-derived (`separation` from
2-means, `crisp` from bout widths, `regular` from rep cv) and its own docstring
says *"Lap-sourced documents skip this entirely at 1.0."*

Measured 2026-07-29, the handoff's diagnosis of this was wrong in a way that
matters. Stream blocks hedge correctly — the archive's are `0.52`, `0.61`,
`0.77`, and the half-marathon it names as the example reads `0.52`. All 23
lap-sourced documents assert.

The live consequence:

```
2026-07-29  "5km easy + 4x20s strides"  →  "32 min block", confidence 1.00
2025-12-26  "W12 HM-Training: Tempo"    →  "24 min block", confidence 1.00
```

In both, four short reps were discarded by the size floor and the surviving
*easy* segment became the reported block.

`_lap_rep_segments` (line 609) already computes everything needed. It builds
`sized` (work segments passing `WORK_MIN_S`/`WORK_MIN_M`), derives `steps` from
`_rep_step_indices`, and intersects them into `survivors`. The discards are
sitting in local variables and are thrown away.

## Goals / Non-Goals

**Goals:**

- Replace the constant with a value that reflects the evidence.
- Hedge a shape that exists only because the engine's own size floor removed the
  alternative.
- Leave the 12 currently-correct sets asserting.
- Give engine and page one definition of "asserts" (handoff **M2**).

**Non-Goals:**

- **No shape changes.** `2026-07-29` still reads `"32 min block"`. Correcting it
  to `4×20 s` needs the prescription — `add-workout-prior`, operation ADMIT.
- No stream-path change; it is already derived and measured to behave.
- No revival of the `crisp`/`regular` factors, which handoff P2.5 records as
  mutation-proven dead. Separate work.
- No new data fetched, no schema change.

## Decisions

### D1 — The two filters are not equivalent: size discards may hedge, step discards must not

`_lap_rep_segments` applies two filters, and treating them alike would be a
serious regression.

| filter | what it rejects | evidence behind it |
|---|---|---|
| **size** (`WORK_MIN_S` / `WORK_MIN_M`) | fragments — a stop press, the watch's end-of-activity lap | the engine's own heuristic that something is too small to be real |
| **step** (`_rep_step_indices`) | ACTIVE warm-ups, cooldowns, transitions | the **device**: reps of a set share one repeated workout step |

The step rule is corroborated by the watch, and it is what made 8 of 23
lap-sourced documents correct in change 2. Hedging on it would punish the engine
for being right. The size floor is a guess — and when a run's entire prescribed
structure sits below it, that guess is what produces the wrong shape.

**So: only size discards feed the hedge.**

### D2 — A size discard hedges only when it is MATERIAL

"A size discard occurred" is far too weak a trigger — nearly every lap-sourced
run ends with a sub-floor fragment (`2026-06-05` lap 4 is 11 m). Hedging all of
them would hedge everything and mean nothing.

Materiality is decided by asking the question directly: **re-run the survivor
selection with the size floor lifted. If the survivor set changes, the discard
was material.**

This is cheap — the segments are already computed — and it is a literal
statement of "the shape depends on their absence" rather than a proxy for it.

Traced against the archive:

```
2026-07-29  floor lifted → sized = {1,3,5,7,9}, step counts {0:1, 2:4},
            repeat = {2} → survivors = {3,5,7,9}, not {1}
            CHANGED → material → hedge                                ✓

2026-07-10  the trailing fragment has wktStepIndex None, so the STEP rule
            drops it whether or not the size floor did
            UNCHANGED → immaterial → still asserts                    ✓

2026-06-05  same: its 11 m lap 4 carries no step index and is dropped
            by the step rule regardless
            UNCHANGED → immaterial → still asserts                    ✓
```

That last one is worth stating plainly: `2026-06-05` is a wrong document
(`"2 reps"`) that this change does **not** hedge, because its wrongness has
nothing to do with discards — it is handoff N5, and it belongs to
`add-workout-prior`. Hedging it here would be right by accident, which is not a
property to build on.

Note the pleasing consequence: wherever a genuine repeated step exists, trailing
fragments are killed by the step rule anyway, so the materiality test
self-selects the cases that matter without needing a separate exemption.

### D3 — Lap confidence is a small set of named levels, not a fabricated score

The lap path has no continuous evidence to interpolate over. There is no
`separation` (the device did not classify by pace), and `crisp` measures bout
widths the device did not infer. Producing a continuous number would be false
precision dressed as rigour.

Three levels, each with a stated meaning:

| level | when | asserts |
|---|---|---|
| corroborated | reps share a repeated workout step, no material discard | yes |
| structured | step evidence used via the no-repeat fallback, or a block the device recorded, no material discard | yes |
| eliminated | the shape depends on a material size discard | **no** |

*Alternative considered:* port `_confidence` to the lap path by synthesising a
`separation` from lap paces. Rejected — it would manufacture the input rather
than measure it, and P2.5 already records that two of that function's three
factors are dead code no test exercises. Extending an unexercised function is
the wrong direction.

### D4 — The page reads a boolean, not a threshold

Handoff **M2**: `CONFIDENCE_ASSERT_MIN` is referenced nowhere in Python while
`run.dc.html` hardcodes `< 0.5`. The two can drift silently.

The fix is not to export the constant — that still leaves two places performing
the same comparison. The engine decides and the document carries the **verdict**:
a boolean saying whether this document asserts its shape. The page renders on
that and never compares a number.

One definition, no duplicated arithmetic, and the threshold becomes an internal
detail of the engine that can move without touching the dashboard.

### D5 — Detecting materiality reveals the right answer, and we deliberately do not act on it

D2's floor-lift for `2026-07-29` does not merely prove the discard mattered — it
produces `{3,5,7,9}`, the four strides, which is the correct document.

We stop at hedging anyway. Lifting the floor unconditionally would re-admit
genuine noise elsewhere; what makes those four segments real is that they were
**prescribed**, and the engine cannot know that yet. Acting on the floor-lift is
exactly operation ADMIT in `add-workout-prior`, authorised by the prescription.

Recording this because the temptation to ship the fix here will be strong, and
the reason not to is a real one rather than scope discipline for its own sake.

## Risks / Trade-offs

- **Over-broad hedging silently degrades 23 good documents.** → The spec pins it:
  every set matching its prescribed count before the rescore must still assert.
  The production sweep is the check, diffed against the recorded baseline.
- **`_lap_rep_segments` gains a second return value.** → Its `assert len(segments)
  == len(laps)` invariant and per-segment contract are unchanged; the discard
  bookkeeping is additive. The function is already the single place both filters
  are applied, so nothing new learns about floors.
- **The materiality test runs survivor selection twice.** → Microseconds on ≤ 30
  laps, and the second run is pure. Not worth caching.
- **A hedged document may read as a *worse* answer to the athlete.** → It is a
  more honest one. `2026-07-29` currently claims a 32-minute quality block with
  certainty; "possible" is closer to true, and the real fix follows.
- **Mutation-testing is not optional.** → Change 1 left four surviving mutations
  (P2.5/P2.6); change 2 found five more in already-reviewed code. Both new rules
  — size-vs-step asymmetry, and materiality — must be shown to turn the suite red
  when broken. A test that passes with the hedge deleted is the failure mode this
  branch has hit 29 times.
- **The local archive cannot test this at all.** → It holds **no lap payloads**.
  Extend `tests/fixtures/lap_workouts.json`; never conclude anything about the
  lap path from the local database.

## Migration Plan

1. `INTERVAL_VERSION` → 5. Next sync recomputes all ~169 documents; seconds, no
   migration, no schema change.
2. Verify with the read-only production sweep, diffed against the handoff's
   baseline (`reps 24 / steady 130 / block 12 / progression 2`, `stream 145 /
   laps 23`, floor `2.700`). **Shapes and labels must not move at all** — this
   change alters only confidence. Any shape movement is a defect.
3. Expected confidence movement: `2026-07-29` and `2025-12-26` drop below the
   assert threshold. Nothing else.
4. Deploy is CI-mediated: merge to `main` → `gh run watch <id> --exit-status` →
   `docker compose pull` on the NUC. Check `docker top splits` for orphans first;
   never wrap `ssh … docker …` in a client-side `timeout`.

**Rollback:** revert `INTERVAL_VERSION`; the next sync restores the previous
documents exactly. Nothing is persisted that a rollback would strand.

## Open Questions

1. **Should a block the device recorded with no rep candidates at all sit at
   `corroborated` or `structured`?** D3 puts it at `structured`. The genuine
   tempo blocks (`2025-09-26`, `2025-10-24`, `2025-11-28`, `2025-12-19` — all
   warm-up Z2 / interval Z4 / cooldown Z2) are correct today and would continue
   to assert either way, so nothing observable turns on it in this archive. It
   matters only once `add-workout-prior` adds corroboration-by-prescription, at
   which point a device block confirmed by a prescribed block is genuinely
   better-evidenced than one that is not. Decide it there, with the prescription
   in hand, rather than guessing now.
