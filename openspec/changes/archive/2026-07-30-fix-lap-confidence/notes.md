# Implementation notes

## One shape move in the production diff — measured, not caused by this change

Task 7.4's sweep found exactly one shape/label movement against
`baseline-before.md`: `2025-09-17` (VO2max, stream-sourced) moved
`steady` → `block "7 min block"`. Reproduced deterministically against the
local archive copy: at work floor **2.700** (the archive-wide p93 when the v4
full rescore ran on 2026-07-28) the run reads `steady`; at **2.71** (the
production floor after the two 2026-07-29 activities entered the baseline) it
reads `block`. The 0.4 % floor drift is below the 2 % threshold that forces a
floor-move rescore, so the run sat un-rescored at the stale floor until the
`INTERVAL_VERSION` bump pushed every document through the current one. Any
version bump would have produced the identical movement; nothing in the
confidence change touches stream classification, and the document's
confidence was 1.0 in both sweeps. The same effect will accompany future
bumps whenever the floor has drifted sub-threshold since the last full
rescore.

## The Garmin side has no distill version marker (handoff P2.4) — out of scope

The `asserts` verdict lands in every document both producers build, and the
Health Connect side recomputes its stored distilled detail because
`INGEST_DISTILL_VERSION` was bumped to 5. The Garmin side has **no equivalent
marker**: `sync_garmin._distill_pass` only fills `detail_distilled_json` where
the column is NULL, so previously-archived runs' stored distilled detail will
NOT gain `intervals.asserts` retroactively there.

Harmless for everything in-tree today — `garmin-data.js` re-distills fresh
every sync, and `/run/:id` injects the fresh API document — but any future
consumer of the stored `detail_distilled_json.intervals` on the Garmin side
reads a pre-verdict document. Recorded here so it is not rediscovered;
mirroring `INGEST_DISTILL_VERSION` on the Garmin side remains handoff P2.4.
