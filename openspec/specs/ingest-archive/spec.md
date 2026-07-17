# ingest-archive Specification

## Purpose
Build-time construction of the activity archive database on ingest-fed
instances: `ingest_builder.py` writes an `activity-archive.db` in the same
schema as the Garmin pipeline's archive — derived numeric ids, verbatim raw
payloads, distilled per-run streams/detail, shared-engine run metrics, and
disposable-cache rebuild semantics — so every archive-backed surface works
identically on both instance shapes with zero read-path changes.
## Requirements
### Requirement: Every banked run is archived at build time
The ingest builder SHALL, as part of every build pass, write an activity
archive database (`activity-archive.db` in the configured data directory) in
the same schema as the Garmin pipeline's archive, using the shared schema
module (`activity_archive.ensure_schema`) — no ingest-specific DDL. Every run
banked in `ingested-runs.json` SHALL have exactly one archive row; the archive
SHALL NOT be capped by the telemetry contract's recent-runs window.

#### Scenario: A run older than the recent-runs window is browsable
- **WHEN** an instance has more banked runs than the telemetry contract's
  recent-runs cap and the archive page requests the activity list
- **THEN** every banked run appears in the list, including those absent from
  `recentRuns`

#### Scenario: Schema parity with the Garmin archive
- **WHEN** the ingest builder creates or migrates the archive database
- **THEN** the resulting schema version and tables are identical to those the
  Garmin pipeline would produce, and the archive API serves the file without
  any ingest-specific code path

### Requirement: Archive ids are stable, derived, and collision-safe
Each banked run's archive `activity_id` SHALL be derived deterministically
from its Health Connect session UID (truncated cryptographic hash, at most 48
bits so the id is JS-safe and matches the `/run/:id` numeric route). The
originating session UID SHALL be recoverable from the stored row. On upsert,
a pre-existing row whose stored session UID differs from the incoming run's
SHALL trigger a deterministic re-derivation (salted rehash) and a loud
warning — a collision MUST NOT silently overwrite another run's row.

#### Scenario: Rebuild produces identical ids
- **WHEN** the archive database is deleted and the next build pass regenerates
  it from the same banked runs
- **THEN** every run receives the same `activity_id` as before, so previously
  shared `/run/:id` links keep resolving

#### Scenario: An id collision is detected, not absorbed
- **WHEN** two distinct session UIDs derive the same `activity_id`
- **THEN** the later run is re-derived with the specified deterministic salt,
  both runs get distinct rows, and a warning is logged

### Requirement: Raw payload preservation and honest promoted columns
Each archive row's `summary_json` SHALL be the banked ingest run payload
verbatim — the raw payload as received from the bridge. Promoted columns
SHALL map from it: local start time, type key (`running` /
`treadmill_running`), distance, duration, average and max HR. Fields the
ingest source does not supply (name, average cadence, elevation gain, raw
Garmin detail) SHALL remain NULL rather than being fabricated.

#### Scenario: The archive list renders from promoted columns
- **WHEN** the archive page lists an ingest-archived run
- **THEN** date, type, distance, duration, and pace-derived display values are
  correct, and absent fields render as the page's existing "—" placeholders

#### Scenario: The source payload survives verbatim
- **WHEN** an archived row is inspected
- **THEN** `summary_json` parses to the exact banked run payload, including
  its session UID

### Requirement: Streams are synthesized columnar with omitted-key degradation
The builder SHALL write `detail_streams_json` in the archive's columnar
streams contract, synthesized from the banked samples: a shared time axis,
heart rate, speed, and cumulative distance normalized so its final value
equals the banked run distance. Metrics the source does not supply (cadence,
elevation, GPS, power, grade-adjusted speed, performance condition) SHALL be
omitted keys — never fabricated columns — so the run page's existing
absent-metric degradation applies.

#### Scenario: The run page charts HR and pace from synthesized streams
- **WHEN** `/run/:id` loads an ingest-archived run with banked HR and speed
  samples
- **THEN** the streams endpoint serves the columnar document and the page
  renders its HR and pace charts

#### Scenario: No route, no map
- **WHEN** an ingest-archived run's page renders
- **THEN** no `lat`/`lon` keys exist in its streams and the page shows its
  existing no-basemap mode

### Requirement: Distilled detail is derivation-identical to the cockpit's
The archive row's `detail_distilled_json` SHALL be produced by the same
derivation that builds the telemetry contract's `recentRuns[].detail`, applied
to every banked run. For a run present in both surfaces the two dicts SHALL be
identical.

#### Scenario: Cockpit card and archive page agree
- **WHEN** a run appears in `recentRuns` and is also fetched via the archive
  API
- **THEN** the archive `detail` object equals the run's `recentRuns[].detail`
  object

### Requirement: Run metrics come from the shared pure engines
The builder SHALL compute `run_metrics` rows for archived runs using the
insight-metrics engine's pure computation functions (best efforts, band
aggregates) over a samples structure built from the banked samples, stored at
the engine's current metrics version. The Garmin raw-payload parser SHALL NOT
be involved, and no ingest-specific best-effort or aggregate formulas SHALL be
introduced.

#### Scenario: Progress drill panels light up
- **WHEN** the progress page opens a drill panel over a month containing
  ingest-archived runs
- **THEN** `/api/archive/run-metrics` returns rows for those runs and the
  panel renders them

#### Scenario: A version bump recomputes
- **WHEN** the insight-metrics engine's metrics version increases and the next
  build pass runs
- **THEN** ingest-archived runs' metrics rows are recomputed at the new
  version, matching the Garmin pipeline's recompute semantics

### Requirement: The ingest archive is a disposable derived cache
The archive database SHALL be fully regenerable from `ingested-runs.json`:
build passes SHALL be idempotent (re-running without new banked runs changes
no user-visible content), derived artifacts (streams, distilled detail,
metrics) SHALL be recomputed only when missing or version-stale, and deleting
the database file SHALL be safe — the next build pass regenerates it
completely.

#### Scenario: Idempotent steady state
- **WHEN** two consecutive build passes run with no new banked runs
- **THEN** the second pass writes no new rows and recomputes no derived
  artifacts

#### Scenario: Deleted database self-heals
- **WHEN** the archive database is deleted and a build pass runs
- **THEN** the archive is rebuilt with all runs, streams, detail, and metrics
  present, and identical ids

### Requirement: The Garmin pipeline is behavior-neutral under shared-code reuse
Any refactor that exposes shared derivation code to the ingest builder SHALL
leave the Garmin sync pipeline's outputs byte-identical for the same inputs:
archived rows, distilled artifacts, metrics rows, and `garmin-data.js` content
are unchanged.

#### Scenario: Garmin outputs unchanged after the refactor
- **WHEN** the Garmin pipeline's distillation and metrics tests run against
  recorded fixtures after the refactor
- **THEN** outputs are identical to the pre-refactor baselines
