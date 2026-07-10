# archive-api Specification

## Purpose
A read-only window onto the activity archive: two zero-dependency `node:sqlite` endpoints that select, shape, and paginate stored rows — no domain formulas, no writes, fail-soft 503s that never take the server down.

## Requirements

### Requirement: Read-only activity listing over promoted columns
The server SHALL expose `GET /api/archive/activities` returning archived
activities as JSON rows built from promoted columns only (activity id, local
start time, type, distance, duration, average HR, average cadence, elevation
gain). The endpoint SHALL support filtering by activity type, calendar year,
and date range, SHALL return rows newest-first, and SHALL paginate with a
bounded page size. Non-GET methods SHALL be rejected.

#### Scenario: Listing the runs of a year
- **WHEN** a client requests `/api/archive/activities?type=running&year=2025`
- **THEN** the response contains only 2025 running activities, newest-first,
  with promoted-column fields and a pagination cursor or offset when more rows
  exist

#### Scenario: Pagination is bounded
- **WHEN** a client requests a page size above the server's maximum
- **THEN** the server clamps to its maximum page size rather than returning an
  unbounded result

#### Scenario: Write methods are rejected
- **WHEN** a client sends `POST`, `PUT`, or `DELETE` to an archive endpoint
- **THEN** the server responds with a method-not-allowed error and no state
  changes

### Requirement: Single-activity endpoint serves the established distilled detail contract
The server SHALL expose `GET /api/archive/activities/:id` returning the
activity's promoted summary plus its stored distilled detail in exactly the
shape `garmin-data.js` uses for recent runs (`splits`, `hrSeries`, `driftBpm`,
`zoneMin`, `tempC`, `te`, `load`, `elevGain`, `splitShape`), so existing
drill-down consumers work on any archived run. Activities without a stored
distilled detail SHALL return their summary with a null detail. Raw Garmin
payloads (`summary_json`, `detail_json`) SHALL NOT be exposed by any endpoint.

#### Scenario: An archived run opens like a recent run
- **WHEN** a client requests `/api/archive/activities/<id>` for a run with
  stored distilled detail
- **THEN** the response's detail object has the same shape as a recent run's
  `detail` in `garmin-data.js`

#### Scenario: Unknown id
- **WHEN** a client requests an id not present in the archive
- **THEN** the server responds 404 with a JSON error body

#### Scenario: An activity without distilled detail degrades to its summary
- **WHEN** a client requests a non-run activity or a run whose detail has not
  been distilled yet
- **THEN** the response carries the promoted summary and a null detail, not an
  error

#### Scenario: Raw payloads stay server-side
- **WHEN** any archive endpoint response is inspected
- **THEN** it contains no raw Garmin `summary_json`/`detail_json` content

### Requirement: The API performs no derivation
Archive endpoints SHALL only select stored rows, rename/shape fields, filter,
and paginate. Domain formulas (drift, zones, efforts, projections) and domain
policy (e.g. records are outdoor-only) SHALL NOT be implemented in the server;
all derived values it returns MUST be read from columns the Python sync wrote.

#### Scenario: Distilled detail is served verbatim
- **WHEN** the single-activity endpoint returns a detail object
- **THEN** it is the stored `detail_distilled_json` content unmodified, not a
  server-side recomputation

### Requirement: Archive endpoints are fail-soft and never take the server down
Archive endpoints SHALL respond 503 with a JSON error body whenever the
archive database is missing, cannot be opened, is busy under the sync's write
lock, or the runtime lacks a SQLite driver — while every other route (pages,
data files, existing APIs) continues to work. The server MUST NOT fail to
boot for any archive-related reason.

#### Scenario: Missing database
- **WHEN** no archive database exists at the configured path
- **THEN** archive endpoints return 503 and the dashboard pages still serve

#### Scenario: Busy under the sync writer
- **WHEN** a request arrives while the sync holds the database's write lock
- **THEN** the endpoint returns either a correct result or 503 — never a
  partial or corrupt payload

#### Scenario: Runtime without a SQLite driver
- **WHEN** the server runs on a Node version without `node:sqlite`
- **THEN** the server boots normally, serves all pages, and archive endpoints
  return 503

### Requirement: The API opens the database read-only
Archive endpoints SHALL open the database in read-only mode per request and
release the handle after responding, never holding a long-lived connection
across the sync's write transactions and never executing a write statement.

#### Scenario: No writes from the web server
- **WHEN** any archive endpoint executes
- **THEN** the database file's content is unchanged by the request

### Requirement: Archive location is configurable and never SQLite-over-SMB by default flow
The API SHALL read the archive from the configured data directory by default
and SHALL honor an override environment variable (`SPLITS_ARCHIVE_DIR`) so a
developer working against a network-mounted data directory can point the API
at a local archive copy. Documentation SHALL state that running SQLite over an
SMB mount is unsupported.

#### Scenario: Container reads the canonical volume copy
- **WHEN** the server runs in the container with the data volume mounted
- **THEN** archive endpoints serve from the volume's `activity-archive.db`

#### Scenario: Dev-against-mount uses a local archive
- **WHEN** `SPLITS_ARCHIVE_DIR` points at a local directory while the data
  directory is a network mount
- **THEN** archive endpoints read the local copy while `garmin-data.js` and
  `plan-data.js` still serve from the mounted data directory

### Requirement: Single-activity streams endpoint serves the stored stream verbatim
The server SHALL expose `GET /api/archive/activities/:id/streams`, returning the
run's stored column-oriented sample stream exactly as the sync wrote it. The
endpoint SHALL derive nothing — no downsampling, no reshaping, no computed
metric — and SHALL NOT serialize raw `summary_json` or `detail_json` into any
response. The activity id SHALL remain strictly numeric.

#### Scenario: A run's stream is served
- **WHEN** a client requests the streams endpoint for an archived run holding a
  stream
- **THEN** the response is the stored stream, unmodified

#### Scenario: A run without a stored stream
- **WHEN** a client requests the streams endpoint for an archived run holding no
  stream
- **THEN** the response is 404 and no stream is computed on the fly

#### Scenario: A non-numeric id is rejected
- **WHEN** a client requests the streams endpoint with a non-numeric id
- **THEN** the response is 404 and no query is issued

#### Scenario: Raw payloads never leave the server
- **WHEN** any archive endpoint responds
- **THEN** no raw Garmin payload appears in the response body

### Requirement: Stream responses are compressed
The streams endpoint SHALL be served through the server's content-negotiated
compression, so a full-resolution run stream crosses the wire at a fraction of
its serialized size.

#### Scenario: A compressing client receives a compressed stream
- **WHEN** a client requests a run's streams with `Accept-Encoding: gzip`
- **THEN** the response carries `Content-Encoding: gzip` and decodes to the
  stored stream

### Requirement: Streams endpoints are fail-soft and perform no writes
The streams endpoint SHALL follow the archive API's existing failure contract: a
missing, unopenable, or locked database SHALL yield an honest 503 rather than a
partial payload or a server crash, and no archive request SHALL write to the
database.

#### Scenario: The archive is locked by the sync
- **WHEN** the streams endpoint is requested while the database is write-locked
- **THEN** the response is 503 with an "archive unavailable" body and the server
  keeps serving pages

#### Scenario: The database is never written
- **WHEN** a sequence of streams requests is served
- **THEN** the database file's bytes are unchanged
