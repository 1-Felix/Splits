# archive-api Specification (delta)

Records behavior shipped 2026-07-17 (instance-aware chrome pass): an archive
database that does not exist is "not provisioned" (404), distinct from an
existing-but-unusable database (503).

## MODIFIED Requirements

### Requirement: Archive endpoints are fail-soft and never take the server down
Archive endpoints SHALL respond with a JSON error body and never take the
server down when the archive is unusable, distinguishing two states: when no
archive database file exists at the configured path, endpoints SHALL return
404 with a "no archive on this instance" body (the instance is not
provisioned with an archive — e.g. ingest-fed before the ingest archive is
built); when the database file exists but cannot be opened, is busy under a
writer's lock, or the runtime lacks a SQLite driver, endpoints SHALL return
503 with an "archive unavailable" body (an outage). In both cases every other
route (pages, data files, existing APIs) continues to work. The server MUST
NOT fail to boot for any archive-related reason.

#### Scenario: Missing database is "not provisioned", not an outage
- **WHEN** no archive database file exists at the configured path
- **THEN** archive endpoints return 404 with a "no archive on this instance"
  body and the dashboard pages still serve

#### Scenario: Existing but unopenable database is an outage
- **WHEN** the database file exists but cannot be opened
- **THEN** archive endpoints return 503 with an "archive unavailable" body

#### Scenario: Busy under the sync writer
- **WHEN** a request arrives while the sync holds the database's write lock
- **THEN** the endpoint returns either a correct result or 503 — never a
  partial or corrupt payload

#### Scenario: Runtime without a SQLite driver
- **WHEN** the server runs on a Node version without `node:sqlite` and the
  database file exists
- **THEN** the server boots normally, serves all pages, and archive endpoints
  return 503

### Requirement: Streams endpoints are fail-soft and perform no writes
The streams endpoint SHALL follow the archive API's failure contract: a
missing database file SHALL yield 404 ("no archive on this instance"), an
existing-but-unopenable or locked database SHALL yield an honest 503 rather
than a partial payload or a server crash, and no archive request SHALL write
to the database.

#### Scenario: The archive is locked by the sync
- **WHEN** the streams endpoint is requested while the database is write-locked
- **THEN** the response is 503 with an "archive unavailable" body and the server
  keeps serving pages

#### Scenario: No archive database on this instance
- **WHEN** the streams endpoint is requested and no archive database file exists
- **THEN** the response is 404 with a "no archive on this instance" body

#### Scenario: The database is never written
- **WHEN** a sequence of streams requests is served
- **THEN** the database file's bytes are unchanged
