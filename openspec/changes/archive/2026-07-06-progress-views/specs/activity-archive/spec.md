# activity-archive Specification (delta)

## ADDED Requirements

### Requirement: Distilled run detail is stored alongside the raw payload
The archive schema SHALL gain an additive column holding each run's distilled
detail (`activities.detail_distilled_json`), applied by the existing
idempotent schema-version migration. The distilled shape SHALL be exactly the
recent-run `detail` contract of `garmin-data.js`, produced by the same
distillation implementation the sync uses for recent runs (one distiller, two
callers). The sync SHALL distill a run when its raw detail is archived, and a
recovery pass SHALL distill already-archived runs from their stored raw
payloads without network access. Raw payloads SHALL remain unmodified.

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
- **THEN** all pre-existing reads work unchanged (the new column is ignored)

#### Scenario: Distillation shares one implementation
- **WHEN** the same run is distilled via the recent-runs path and via the
  archive path
- **THEN** both produce the same distilled object

### Requirement: Distilled coverage is verifiable
The archive verification mode SHALL report distilled-detail coverage (runs
with raw detail vs runs with distilled detail) and SHALL exit non-zero when
distilled coverage regresses behind raw-detail coverage.

#### Scenario: Healthy distilled coverage
- **WHEN** verification runs after the distillation pass and a normal sync
- **THEN** it reports distilled coverage equal to raw-detail coverage

#### Scenario: A distillation gap is caught
- **WHEN** runs hold raw detail without distilled detail after a completed
  sync
- **THEN** verification exits non-zero naming the gap
