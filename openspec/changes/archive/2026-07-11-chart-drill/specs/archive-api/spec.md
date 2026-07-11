# archive-api Delta

## ADDED Requirements

### Requirement: Run-metrics rows are served verbatim over a bounded date range
The server SHALL expose `GET /api/archive/run-metrics?from=<date>&to=<date>`
returning, for each running activity whose local start date falls within the
range, one row joining the activity's promoted identity columns (activity id,
local start time, name, distance, duration, treadmill flag) with its stored
`run_metrics` band-aggregate and display columns (`refhr_time_s`,
`refhr_dist_m`, `refhr_pace_s_per_km`, `refpace_time_s`,
`refpace_cadence_spm`, `metrics_version`) — verbatim, newest-first. A running
activity without a `run_metrics` row SHALL appear with null metric fields
rather than being omitted. Both range parameters SHALL be required and spans
longer than 92 days SHALL be rejected with a client error; within that bound
the response SHALL NOT paginate. Non-GET methods SHALL be rejected. The
endpoint SHALL inherit the archive API's existing contracts: read-only
per-request database access, fail-soft 503 behavior, no derivation, and no
raw Garmin payloads in any response.

#### Scenario: A month's evidence rows are served
- **WHEN** a client requests `/api/archive/run-metrics?from=2026-03-01&to=2026-03-31`
- **THEN** the response holds one row per March running activity, newest-first,
  each carrying the promoted identity fields and the stored metric columns
  unmodified

#### Scenario: A run not yet analysed appears with nulls
- **WHEN** the range contains a running activity that has no `run_metrics` row
- **THEN** that activity appears in the response with null metric fields, not
  omitted and not computed on the fly

#### Scenario: An oversized span is rejected
- **WHEN** a client requests a range spanning more than 92 days, or omits
  `from` or `to`
- **THEN** the server responds with a client error naming the constraint and
  issues no unbounded query

#### Scenario: The endpoint derives nothing
- **WHEN** the response's metric fields are compared with the stored
  `run_metrics` columns
- **THEN** they are identical — no value in the response was computed by the
  server

#### Scenario: Fail-soft under a missing or locked archive
- **WHEN** the archive database is missing or write-locked at request time
- **THEN** the endpoint responds 503 with a JSON error body while every other
  route keeps serving
