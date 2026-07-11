# archive-api Delta

## MODIFIED Requirements

### Requirement: Read-only activity listing over promoted columns
The server SHALL expose `GET /api/archive/activities` returning archived
activities as JSON rows built from promoted columns only (activity id, local
start time, type, distance, duration, average HR, average cadence, elevation
gain). The endpoint SHALL support filtering by activity type, calendar year,
date range, and case-insensitive name substring; the name filter SHALL be
parameterized and wildcard-safe (literal `%`, `_`, and `\` in the query match
themselves). Filters SHALL combine as AND, and the reported total SHALL count
the filtered set. The endpoint SHALL return rows newest-first and SHALL
paginate with a bounded page size. Non-GET methods SHALL be rejected.

#### Scenario: Listing the runs of a year
- **WHEN** a client requests `/api/archive/activities?type=running&year=2025`
- **THEN** the response contains only 2025 running activities, newest-first,
  with promoted-column fields and a pagination cursor or offset when more rows
  exist

#### Scenario: Searching by name
- **WHEN** a client requests `/api/archive/activities?q=sonthofen`
- **THEN** the response contains only activities whose name contains
  "sonthofen" case-insensitively, and the reported total counts that filtered
  set

#### Scenario: Wildcard characters match literally
- **WHEN** a client requests the listing with a `q` value containing `%` or `_`
- **THEN** those characters match only themselves in activity names and the
  query executes parameterized, never interpolated into SQL

#### Scenario: Name search combines with other filters
- **WHEN** a client requests `?type=running&year=2026&q=tempo`
- **THEN** the response contains only 2026 runs whose names contain "tempo",
  and total, limit, and offset describe that combined filter

#### Scenario: Pagination is bounded
- **WHEN** a client requests a page size above the server's maximum
- **THEN** the server clamps to its maximum page size rather than returning an
  unbounded result

#### Scenario: Write methods are rejected
- **WHEN** a client sends `POST`, `PUT`, or `DELETE` to an archive endpoint
- **THEN** the server responds with a method-not-allowed error and no state
  changes
