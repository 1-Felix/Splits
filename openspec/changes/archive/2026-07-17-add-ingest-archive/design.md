# add-ingest-archive — Design

## Context

The Garmin pipeline archives every activity in `activity-archive.db`
(`activity_archive.py` owns the schema, versioned migrations v1→v8;
`sync_garmin.py` writes raw payloads and distills `detail_distilled_json` +
`detail_streams_json`; `insight_metrics.py` computes `run_metrics`). The
archive API (`serve.mjs handleArchive`) is a read-only window over that file
and was built schema-tolerant: no `map_tiles` table = "no tiles yet", no
streams = "no streams", missing db = 404 "not provisioned" (since 2026-07-17).

The ingest pipeline (Max) banks complete runs in `ingested-runs.json` — HR
samples, speed samples, distance, calories, steps — and `ingest_builder.py`
already derives a Garmin-shaped per-run `detail` dict (splits / hrSeries /
driftBpm / zoneMin / splitShape / elevGain) for the 6 most recent runs. It
writes no archive, so all archive-backed surfaces are (honestly) dead on
ingest instances.

Constraint from 2026-07-17 discussion with Felix: **on-par experience, clean
separate pipelines** — no mixing of producers, but no parallel read stack
either.

## Goals / Non-Goals

**Goals**
- Ingest instances get a real `activity-archive.db` — same schema, own volume,
  own producer — lighting up /archive, /run/:id, /compare, the heatmap
  day-drill, and the progress drill panels with zero read-path changes.
- All derivation stays in Python at build time (matching both pipelines'
  existing layering: producers derive, serve is a window).
- Shared code is reused at the right seam; the Garmin pipeline's behavior is
  byte-identical afterwards.
- The archive db remains a disposable derived artifact: delete it and the next
  build fully regenerates it from `ingested-runs.json`.

**Non-Goals**
- Map tiles / GPS routes, elevation, per-sample cadence — Samsung Health
  writes none of these; the run page's existing degradation modes cover them.
- `plan_snapshots` / `plan_compliance` rows (run-page planned-vs-actual chip):
  Max has a plan, so this is *worth doing later* as its own change — the
  compliance engine has its own snapshot semantics and pulling it in here
  doubles the scope. The run page renders no plan row when the table is empty.
- `daily_wellness` and `race_predictions` rows: nothing user-visible on the
  archive surfaces consumes them on an ingest instance today.
- Backfilling Felix's archive or touching the Garmin sync flow in any
  behavior-visible way.

## Decisions

### D1 — Same schema, same schema module, separate file
`ingest_builder.py` imports `activity_archive.ensure_schema` and writes
`activity-archive.db` in the instance's own `SPLITS_DATA_DIR`. No new DDL, no
adapter, no reader changes; schema migrations remain owned by
`activity_archive.py` and run identically on both pipelines' files.
*Rejected:* JSON read-adapter in serve (second reader = contract-drift risk,
against the one-window principle); bespoke ingest schema (reader forks).

### D2 — The producer is a build pass in `ingest_builder.py`
After the telemetry build, an archive pass upserts every banked run. Python
owns all derivation in both pipelines; `serve.mjs` stays a window. Triggering
is unchanged: `triggerBuild()` on ingest / boot already reruns the builder.
*Rejected:* bank-time writes in Node (`ingest-store.mjs`) — derivation split
across two languages and duplicate distiller logic.

### D3 — Stable derived numeric ids
`activity_id = int(sha256(sessionUid).hexdigest()[:12], 16)` — 48 bits:
stateless, deterministic, JS-safe (< 2^53, the API serializes ids into JSON
and `/run/:id` parses `\d+`). The true `sessionUid` is embedded in
`summary_json`, so the mapping is recoverable and collisions are detectable:
on upsert, an existing row whose embedded sessionUid differs re-derives with a
deterministic salt (`sessionUid + "#1"`, `#2`, …) and warns loudly. At
hundreds of runs the birthday bound is ~n²/2⁴⁹ — negligible, but the rule is
specified rather than assumed.

### D4 — `summary_json` is the banked bridge payload, verbatim
The schema's contract is "preserve the complete raw payload as returned by the
source" — for this pipeline the raw source payload IS the banked ingest run.
Promoted columns map from it: `start_time_local`, `type_key`
(`running`/`treadmill_running` — matching the archive page's `type=running`
filter chips), `distance_m`, `duration_s`, `avg_hr`, `max_hr`;
`name`/`avg_cadence`/`elevation_gain_m` stay NULL (honest absence).
`detail_json` stays NULL — no raw Garmin payload exists, and nothing serves it.

### D5 — Streams are synthesized columnar, ingest-owned
`detail_streams_json` gets the run-detail D1 columnar shape built directly
from the banked samples: `t` (shared axis from the union of HR/speed sample
times), `hr`, `v`, and `d` (cumulative integration of `v`, normalized so the
final value equals the banked `distanceM`). Absent metrics (`cad`, `elev`,
`gap`, `pwr`, `lat`/`lon`, `pc`) are **omitted keys**, exactly the "metric
absent from this payload" convention the Garmin distiller and the run page
already honor. A `DISTILL_VERSION`-style marker in `archive_meta` triggers
recompute when the synthesis changes.
*Rejected:* fabricating a raw-Garmin-shaped `activityDetailMetrics` payload so
`distill_run_streams`/`read_stream` run unchanged — clever, but it launders
synthetic data into columns documented as "raw", and couples the ingest
pipeline to Garmin's wire format.

### D6 — `detail_distilled_json` reuses the builder's existing detail derivation
The dict `ingest_builder` already produces for `recentRuns[].detail` is the
same contract `getArchiveActivity` serves from `detail_distilled_json`. The
archive pass runs that existing derivation for **every** banked run, not just
the last 6. One derivation, two consumers — the parity between a run's cockpit
card and its archive page is structural.

### D7 — `run_metrics` reuses the pure engines, not the parser
`insight_metrics.extract_run_metrics` parses raw Garmin payloads
(`read_stream`), which ingest rows don't have. The reuse seam is one level
down: construct the samples dict directly from banked samples and call the
pure `best_efforts()` + `band_aggregates()` engines, upserting at the same
`METRICS_VERSION` so the progress drill panels and records feeds work
identically. The exact samples-dict contract gets pinned by a parity test
during implementation.

### D8 — Disposable-cache rebuild semantics
Every archive pass upserts all banked runs (idempotent; freshest banked run
wins, though banked runs are immutable in practice). Streams/detail/metrics
are recomputed only for rows missing them at the current version markers —
write-once in the steady state, self-healing after a version bump or a deleted
db. Deleting the file is always safe: the next build regenerates everything.
This matches the repo's existing "disposable derived cache" philosophy
(`run_metrics`, `plan_compliance`).

### D9 — Concurrency regime is unchanged
The builder writes under SQLite's DELETE journal while serve does per-request
read-only opens with honest 503s under lock — the exact regime the nightly
Garmin sync already exercises. `triggerBuild()`'s single-flight + coalescing
already serializes builder runs on ingest instances.

## Risks / Trade-offs

- [Schema migrations run on ingest-written dbs] → shared `ensure_schema` is
  the single owner on both pipelines; migration tests already cover empty and
  partial dbs, add an ingest-shaped fixture.
- [Distiller/contract drift between cockpit detail and archive detail] →
  structural (D6: same function); parity test asserts the archived dict equals
  the recentRuns dict for the same run.
- [Samples-dict contract mismatch feeding `best_efforts`] → parity test builds
  the dict both ways (Garmin fixture via `read_stream`, ingest synth) and
  asserts engine outputs agree on overlapping fields.
- [Id collision] → deterministic salt-rehash + loud warning (D3); sessionUid
  embedded in `summary_json` makes any collision observable, never silent.
- [Build-time growth] → full upsert of promoted columns is trivial at
  hundreds-of-runs scale; heavy work (streams/detail/metrics) is write-once
  (D8).
- [Archive page year chips are hardcoded from 2024] → cosmetic, fine for Max
  (history starts 2026); note for a later frontend pass.

## Migration Plan

1. Ship in the normal image; no compose/env changes.
2. Max's next ingest (or container boot) runs the builder → db appears on the
   volume → `/api/status` reports `archive: true` → the 2026-07-17 gating
   auto-reverses and all surfaces go live. No action on Felix's instance.
3. Rollback: previous image + delete `activity-archive.db` from the ingest
   volume (it's a derived cache — nothing is lost).

## Open Questions

- None blocking. Implementation-time pins: the exact samples-dict contract for
  D7 (parity test), and whether `avg_cadence` should be promoted from the
  banked `steps`-derived cadence (builder computes it for recentRuns; cheap to
  include if the archive list ever shows cadence — it currently doesn't).
