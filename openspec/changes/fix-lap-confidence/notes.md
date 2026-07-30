# Implementation notes

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
