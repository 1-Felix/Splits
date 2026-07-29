# Proposal: fix-lap-confidence

## Why

`interval_lens.py:878` hardcodes `"confidence": 1.0` on every lap-sourced
document, for every shape. It is not a computed value that happens to reach 1.0
— it is a constant, and it means a lap-sourced verdict can never be hedged
however much filtering it took to reach.

The handoff records this as *"a single-bout `block` always has `cv is None` and
`shortest ≥ 300 s`, so blocks score confidence 1.0 and can never be hedged. A
half-marathon race reads `conf=1.00 "6 min block"`."* Measured on 2026-07-29,
that diagnosis is wrong in a way that matters: **stream-sourced blocks are
hedged perfectly well** — the archive's are `0.52`, `0.61`, `0.77`, and the
half-marathon reads `0.52`, not `1.00`. The problem is the lap branch's constant
alone, which covers all 23 lap-sourced documents.

It is live and wrong today:

```
2026-07-29  "Leinfelden-Echterdingen - 5km easy + 4x20s strides"
            reads  "32 min block"   confidence 1.00

  lap  intensity  step  dist    dur
   1   ACTIVE     0     5000 m  1918 s   ← the easy 5 km
   3   ACTIVE     2       35 m    20 s   ┐
   5   ACTIVE     2       79 m    20 s   │ four strides on ONE repeated
   7   ACTIVE     2       84 m    20 s   │ step — all four below
   9   ACTIVE     2       90 m    20 s   ┘ WORK_MIN_S = 30, so all dropped

  → work set = {lap 1}, the easy 5 km, promoted to a 32-minute quality block
    and ASSERTED at full confidence
```

`2025-12-26` fails identically (four prescribed 30 s reps → `"24 min block"`).
The engine knows it discarded four candidate segments; it simply has no way to
say so.

This change does not make those documents right — that needs the workout
prescription, and is `add-workout-prior`. It makes them stop **asserting**. That
is worth doing on its own, and it is a **prerequisite** for `add-workout-prior`:
that change merges a fragmented block across a 304 s gap (`2026-01-23`), which
is only defensible once there is somewhere to put the uncertainty.

## What Changes

- **Remove the constant.** Lap-sourced confidence becomes a derived value, as it
  already is on the stream path.
- **Hedge a shape that survives by elimination.** When the engine's own filters
  discard candidate work segments and the surviving shape depends on their
  absence, the document SHALL fall below `CONFIDENCE_ASSERT_MIN`. This is
  information the engine already has at the point of decision and currently
  throws away.
- **Keep asserting where the device genuinely corroborates.** A set whose reps
  share a repeated workout step, at full size, with no discards, is exactly the
  case the lap path was built to trust — it must not be hedged into uselessness.
  Measured, 12 of the archive's 15 prescribed sets are already exactly right;
  none of them may regress.
- **`CONFIDENCE_ASSERT_MIN` becomes load-bearing in Python.** It is currently
  referenced nowhere outside a comment, while `run.dc.html` hardcodes `< 0.5`
  (handoff **M2**). The two can drift silently today; this change makes the
  Python constant the definition and the page read it.

## Capabilities

### New Capabilities

- `lens-confidence`: how an interval document's confidence is derived on the
  device path, what hedging means, and the single definition of the assertion
  threshold shared by engine and page.

## Impact

- **Engine**: `interval_lens.build_document`'s laps branch — the `confidence`
  value and the discard bookkeeping that feeds it. `_lap_rep_segments` already
  knows which segments it re-roled; that knowledge becomes an output.
- **Recompute**: `INTERVAL_VERSION` → 5, rescoring all ~169 documents. Seconds,
  no migration.
- **Dashboard**: `run.dc.html`'s hardcoded `0.5` replaced by the value the
  document/contract carries.
- **Tests**: extend `tests/fixtures/lap_workouts.json` and
  `test_interval_laps_truth.py` — the local `activity-archive.db` has **no lap
  payloads at all**, so no lap-path conclusion may be drawn from it. Every new
  rule must be mutation-proven: this branch has found 29 defects that were all
  tests not exercising what they claimed.
- **Expected production movement**: `2026-07-29` and `2025-12-26` drop below the
  assert threshold. Nothing else should move — anything that does is a defect.

## Non-Goals

- **No shape changes.** `2026-07-29` still reads `"32 min block"`; it just stops
  claiming certainty about it. Correcting it to `4×20 s` requires the
  prescription and belongs to `add-workout-prior`.
- **No stream-path change.** Stream confidence is already derived and measured
  to behave (0.52 / 0.61 / 0.77).
- **No new confidence factors.** Handoff P2.5 records that two of the three
  existing factors (`crisp`, `regular`) are mutation-proven dead. Reviving them
  is separate work; this change is about the constant.
- **No corroboration against a prescription.** That needs the workout and is
  specified in `add-workout-prior` D8.
