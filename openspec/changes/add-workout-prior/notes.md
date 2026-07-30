# Implementation notes

## Two design premises falsified by measurement, corrected in place

1. **`updatedDate` is populated** (the exploration read the wrong key,
   `updateDate`). Staleness is per-run detectable — workout `1357916773`
   backs both `2025-10-17` (edited after it: stale, and structurally refused
   by the all-or-nothing mapping) and `2025-11-14` (exact). Design D5 and the
   provenance spec requirement were rewritten; the document's `guidedBy`
   carries `{workoutId, stale}`.
2. **Within-window pace cannot single out `2026-01-23`** as the one POINT
   hedge case — its 304 s "gap" is a shallow jog, while the "clean"
   `2026-01-09` dips below its band for longer. The hedge follows evidence of
   interruption instead (a deep stop ≥ 60 s below 0.8×band-lo, or a
   bout-fragmented window). Measured: only `2026-01-09` of the six executed
   its block uninterrupted; `2026-02-27`'s genuine 92 s standstill — which
   the design's own trace called clean — hedges too. Design D1a corrected.

Also: the handoff's P3.1 fix formula `max(2, min(REPS_MIN_COUNT, expect))`
still reads 3 at expect 4 and cannot report the 2-of-4 case it was written
for; implemented as `2 if expect >= 2 else REPS_MIN_COUNT` (`_reps_min`).

## The production movement audit (task 12.4) — 22 documents, all intended

Diffed against `baseline-before.md` after the v6 rescore (170/170 at v6,
shapes `steady 130 / reps 19 / block 19 / progression 2`):

| kind | runs |
|---|---|
| easy runs un-promoted (VETO) | `2025-12-24`, `2026-04-29`, `2026-04-01` → steady |
| missed tempos found (POINT) | `2026-01-09` (asserts 0.9 — the one uninterrupted execution), `2026-02-13`, `2026-02-27` (hedged — real mid-tempo stops, measured) |
| fragmented tempos merged (POINT) | `2026-01-23`, `2026-03-13`, `2026-04-03` → one block each, hedged |
| short reps admitted (ADMIT) | `2026-07-29` → `4×20 s`, `2025-12-26` → `4×30 s`, both asserting at 1.0 |
| bookends vetoed | `2026-06-05` → `25 min block`, `2026-01-16` → `5 min block`, both asserting |
| float excluded (value rule) | `2025-12-05` → `2×2 km`, found 2 = prescribed 2 |
| time-prescribed names (N3) | `2025-09-19` → `6×60 s`, `2025-11-14` → `6×90 s`, `2025-11-21` → `8×90 s`, `2025-12-12` → `6×120 s`, `2026-02-06` → `6×90 s` |
| corroboration only | `2026-04-24` 0.77 → 0.9 (stream set matches its prescription); `2025-12-28` — the half-marathon RACE — junk `6 min block` @0.52 → **`139 min block` @0.9**: its race workout carries a pace band and POINT confirmed the whole race as the prescribed block |
| prescribed structure the lens declines to call reps | `2024-07-22` (Run Walk Run®) steady, now hedged — its workout prescribed structure, so asserting steady overstated certainty |

Untouched, as required: the stale-edited `2025-10-17`, and every one of the
12 prescribed-count-matching sets (five of them gained their honest
time-based names; no count or shape moved).

## Backfill

85 of 89 referenced definitions banked (`provenance = backfill`), 4 deleted
(404) — exactly the exploration's attrition. The nightly `workouts_step`
banks new definitions at `first-sight`, bounded 10/sync, before the
intervals pass so a fresh run is scored with its prescription in hand.
