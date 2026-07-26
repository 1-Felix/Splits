# archive-api Specification (delta)

## ADDED Requirements

### Requirement: Read-only course document
The server SHALL expose `GET /api/archive/course/:courseId` returning the stored
course document verbatim, 404 when no such course exists, and the established
fail-soft 503 when the archive is unavailable. The endpoint SHALL select and
shape stored rows only — no derivation at request time, no writes — and the
server process SHALL never crash on archive failure.

#### Scenario: The stored document is served verbatim
- **WHEN** `GET /api/archive/course/493447940` is requested and that course exists
- **THEN** the response is the stored course document verbatim

#### Scenario: Unknown course id
- **WHEN** a course id with no stored row is requested
- **THEN** the endpoint returns 404

#### Scenario: Archive away is fail-soft
- **WHEN** the archive database is unavailable
- **THEN** the endpoint returns 503 and the server keeps serving other routes

#### Scenario: No derivation at request time
- **WHEN** the endpoint handles a request
- **THEN** it performs only a SELECT against the stored course row, computing no profile, calibration or pace table
