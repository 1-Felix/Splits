# Design: sweep-lens-tail

## Context

Every item here was re-verified against the working tree at `3f0b9ff` on 2026-07-30
(the same day `fix-lap-confidence` and `add-workout-prior` were deployed). The
handoff's own numbering is kept — M1, N1, M4, M5/N6, M6, M7, M9, M10, M12, N2, N7,
P2.5, P2.6a/c/d — so each fix can be traced back to its origin. Several items the
handoff lists are **not** in scope because the July-30 changes already closed them:
M2, M11 (+N3), M13/P3.1, P2.7b, the laps half of M12, and the `rc.durS` half of M5.

Constraints: the race is 2026-08-09. Production documents must not move — no
`INTERVAL_VERSION` bump, no recompute, no schema change.

## Goals / Non-Goals

**Goals:**

- Close every remaining mechanical defect from the handoff that can be fixed
  without touching scoring behavior.
- Convert the known mutation-survivor list (P2.5, P2.6a/c/d, M12-stream, N2) into
  pinned, mutation-proven coverage.
- Give the run page responsive audit coverage and fix its one known overflow (N7).

**Non-Goals:**

- M8 + P2.4 (cockpit distill parity and a Garmin-side distill version marker) —
  deliberately a separate follow-up change with its own design.
- P2.2 boundary extension and M3 `elapsedDuration` — engine changes; deferred past
  the race.
- The `corroborated`-vs-`structured` confidence distinction (open question inherited
  from `fix-lap-confidence`) — a design question that belongs with P3.2-era work.
- Any change to what any archived document says.

## Decisions

### D1 — M4 exposes `lensVersion`; it does not filter

Filtering stale rows out would blank every run's interval card between a future
version bump and the next sync, and would require exporting Python's
`INTERVAL_VERSION` across the language boundary into `serve.mjs`. The actual
contract violation is that a consumer *cannot tell* a stale document from a current
one; exposing the stored `lens_version` (as `lensVersion`, the block/course
precedent) fixes exactly that. The list JOIN adds `i.lens_version`; the by-id read
selects it alongside `doc_json`.

### D2 — M5 and N6 land as one unit

`_pace_s_per_km` currently returns `0` for non-positive speed; `run.dc.html`
renders `—` for falsy `gapS`. Fixing either alone regresses the other: honest
`None` + falsy check keeps rendering `—` for a future genuine `0`, and keeping `0`
+ `!= null` check renders a bogus pace. So: the helper returns `None` for
`mps <= 0`, the template checks `s.gapS != null`. All call sites of
`_pace_s_per_km` are audited for `None`-safety (labels and `set_stats` consumers).
A read-only production sweep confirms no archived document carries `gapS == 0` —
that is the evidence that this cannot change any stored document and therefore
needs no version bump. If the sweep finds a counterexample, stop and re-decide.

### D3 — N1 pairs by time, not position

The recovery shown under rep *i* becomes: the first segment with
`role === 'recovery'` whose `t0 >= work[i].t1` and (when a next rep exists)
`t0 < work[i+1].t0`. No match → no recovery line for that rep (today a wrong one
can be shown). Both producers emit `t0/t1` on every segment from one internally
consistent axis per document, so the join is exact on both paths — the laps path's
known absolute-axis drift (M3) cancels because reps and recoveries share the same
accumulated axis. Display-only; no document change.

### D4 — M1 trades a bounded refetch for cache honesty

Write the lap cache only when `lapDTOs` is a non-empty list. A run whose reply is
genuinely empty is re-asked on later syncs — bounded by `runs_missing_laps`'s
existing `ORDER BY … DESC LIMIT 40` — instead of being permanently marked fetched
and silently starving the queue behind it. This mirrors what `_workouts_pass`
already does.

### D5 — every new test must fail under mutation before it counts

The handoff records 29 defects found by mutation-testing across two changes, every
one an assertion that could not fail. Each test in the bundle is committed only
after its target mutation was applied and the test observed red:

| Test | Mutation that must go red |
|---|---|
| `crisp` pin (P2.5) | replace `crisp` factor with `1.0` |
| `regular` pin (P2.5) | replace `regular` factor with `1.0` |
| progression monotonicity (P2.6a) | delete the monotonicity clause |
| `_hr_grid` hold (P2.6c) | delete the sample-and-hold branch |
| merge-then-filter (P2.6d) | swap filter before merge in `find_bouts` |
| stream floor split (M12) | delete `WORK_MIN_S` arm; then `WORK_MIN_M` arm |
| unstructured workout (N2) | make `laps_are_structured` return `True` unconditionally |
| `_RUN_TYPE_SQL` import (M10) | (structural — drift now impossible by construction) |

N2's fixture entry comes from the ~101 real `laps_json` rows the structured
predicate excludes; the entry is trimmed to the fields the engine reads, like the
existing 23.

### D6 — N7 resolves a real run id at audit time

`style-audit.mjs` cannot hardcode a run id. It asks the running server's own list
endpoint for the most recent run with an interval document and audits
`/run/<that id>` at the same widths as the other deep views; if the archive is
empty it reports the view as skipped rather than failing. The 390 px overflow is
fixed at its measured source (`.card.rep-table`), not by clipping a parent —
`overflow-x: auto` on the card is acceptable only if the table genuinely cannot
compress; prefer letting the rep rows shrink.

### D7 — M6 renames the parameter, not the function

`build_document(work_floor=…)` becomes `build_document(floor_override=…)` (or
equivalent); the module-level `work_floor()` keeps its name because it is the
older, more widely referenced symbol. Three call sites move with it.

## Risks / Trade-offs

- [Sweep finds `gapS == 0` in production] → D2 halts; re-decide with the evidence
  (the value would mean a real lap carried non-positive grade-adjusted speed).
- [N1's "no match → no line" hides a recovery previously shown] → that display was
  *wrong* (mis-paired); showing nothing is the honest state. The change is pinned
  by a fixture with a mid-set demotion, the exact case that mis-pairs today.
- [M1 refetch loops on a permanently-empty run] → bounded at 40 per sync by the
  existing query; no new mechanism.
- [M4 consumers ignore `lensVersion`] → acceptable; the field is informational.
  Nothing in-tree needs to react to it today.
- [Style-audit `/run` view flakes when serve.mjs isn't running] → same posture as
  the existing deep views; the audit already requires a live server.

## Migration Plan

None. No schema, no version bump, no recompute. Deploy is the standard CI path
(merge to `main` → `docker-publish.yml` → `docker compose pull` on the NUC), and
the post-deploy check is the standard read-only sweep asserting the document
distribution is **unchanged**: `steady 130 / reps 19 / block 19 / progression 2`,
sources unchanged, floor `2.710`.

## Open Questions

None — the two judgment calls (D1 expose-not-filter, D2 pairing) were decided with
Felix during brainstorming on 2026-07-30.
