## MODIFIED Requirements

### Requirement: Distilled run detail is stored alongside the raw payload
The archive schema SHALL gain an additive column holding each run's distilled
detail (`activities.detail_distilled_json`), applied by the existing
idempotent schema-version migration. The distilled shape SHALL be exactly the
recent-run `detail` contract of `garmin-data.js`, produced by the same
distillation implementation the sync uses for recent runs (one distiller, two
callers). The sync SHALL distill a run when its raw detail is archived, and a
recovery pass SHALL distill already-archived runs from their stored raw
payloads without network access. Raw payloads SHALL remain unmodified.

The distiller SHALL be given the run's device laps and its banked workout
definition when they exist, so the compact `intervals` summary inside the
distilled detail is the same reading as the run's full interval document —
same source, shape, label, and confidence. Each distilled copy SHALL record
the distiller version and computation time (additive columns
`distilled_version`, `distilled_at`), and SHALL be recomputed when the
distiller version bumps, or when the run's laps or its workout definition
arrived after the distilled copy was computed. The nightly sync SHALL distill
a run only after that sync's lap fetch and workout banking have run.

#### Scenario: A topped-up run gains distilled detail
- **WHEN** the sync archives a run's raw detail payload
- **THEN** the same sync stores the run's distilled detail in the new column

#### Scenario: Already-archived runs are distilled locally
- **WHEN** the distillation pass runs over an archive with runs that have raw
  detail but no distilled detail
- **THEN** every such run gains distilled detail computed from its stored raw
  payload, with no Garmin API calls

#### Scenario: The migration is additive and reversible by ignoring
- **WHEN** an older application version opens a database at the new schema
  version
- **THEN** all pre-existing reads work unchanged (the new columns are ignored)

#### Scenario: Distillation shares one implementation
- **WHEN** the same run is distilled via the recent-runs path and via the
  archive path
- **THEN** both produce the same distilled object

#### Scenario: The compact summary agrees with the interval document
- **WHEN** a run's laps are banked and read as structured by the lens
- **THEN** the distilled detail's `intervals` summary carries the same source,
  shape, and label as the run's full interval document

#### Scenario: A version bump refreshes every stored copy
- **WHEN** the distiller version is bumped and the next distillation pass runs
- **THEN** every run whose stored `distilled_version` is older (or absent) is
  re-distilled from stored payloads and stamped with the new version

#### Scenario: Laps arriving after the distill make it stale
- **WHEN** a run's laps are fetched after its distilled copy was computed
- **THEN** the next distillation pass re-distills that run with the laps in
  hand

#### Scenario: A workout banked after the distill makes it stale
- **WHEN** a run references a workout definition that was banked after the
  run's distilled copy was computed
- **THEN** the next distillation pass re-distills that run with the
  prescription in hand
