# archive-api Specification (delta)

## ADDED Requirements

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
