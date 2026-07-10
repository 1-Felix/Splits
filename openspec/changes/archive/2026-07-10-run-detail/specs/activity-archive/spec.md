# activity-archive Specification (delta)

## ADDED Requirements

### Requirement: Run sample streams are stored alongside the raw payload
The archive schema SHALL gain an additive column holding each run's sample
stream (`activities.detail_streams_json`), applied by the existing idempotent
schema-version migration. The stream SHALL be stored column-oriented and rounded
to each metric's real precision — elapsed time, distance, heart rate, speed,
grade-adjusted speed, cadence, elevation, power, latitude, longitude, and
performance condition — at the full sample resolution of the stored raw payload,
with nulls preserved as nulls. It SHALL be produced by a pure distiller over the
raw payload, SHALL be derived and disposable (a recompute replaces it), and raw
payloads SHALL remain unmodified.

#### Scenario: An archived run gains its stream
- **WHEN** the sync archives a run's raw detail payload
- **THEN** the same sync stores that run's column-oriented stream

#### Scenario: Streams are recovered locally from stored payloads
- **WHEN** the recovery pass runs over an archive holding runs with raw detail
  but no stream
- **THEN** every such run gains its stream, computed from its stored raw payload,
  with no Garmin API calls

#### Scenario: The stream is full resolution
- **WHEN** a run's raw payload holds N sample rows
- **THEN** each stored stream column holds N values

#### Scenario: Raw payloads are untouched
- **WHEN** streams are written or recomputed
- **THEN** the corresponding `detail_json` values are byte-identical to before

#### Scenario: The migration is additive
- **WHEN** an older application version opens a database at the new schema
  version
- **THEN** all pre-existing reads work unchanged and the new column is ignored

### Requirement: The route is recovered from the stream's coordinate columns
The stream SHALL carry the run's latitude and longitude columns, from which the
route is reconstructed. The archive SHALL NOT depend on Garmin's polyline
object, which the sync's fetch parameters leave empty.

#### Scenario: Coordinates are present for every sample
- **WHEN** a run's stream is distilled from an outdoor run's raw payload
- **THEN** its latitude and longitude columns carry a value for every sample

### Requirement: Stream coverage is verifiable
The archive verification mode SHALL report stream coverage (runs holding raw
detail versus runs holding a stored stream) and SHALL exit non-zero when stream
coverage regresses behind raw-detail coverage.

#### Scenario: Healthy stream coverage
- **WHEN** verification runs against an archive where every run with raw detail
  holds a stream
- **THEN** it reports full stream coverage and exits zero

#### Scenario: Coverage regression fails the check
- **WHEN** runs hold raw detail but no stream
- **THEN** verification reports the shortfall and exits non-zero
