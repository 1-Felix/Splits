# archive-api Specification (delta)

## ADDED Requirements

### Requirement: Read-only block listing
The server SHALL expose `GET /api/archive/blocks` returning all `block_lens`
rows newest race first, each as promoted columns (`race_date`, `race_name`,
`lens_version`, `is_complete`, `updated_at`) plus the headline summary slice
of the stored document. The endpoint SHALL select and shape stored rows only —
no derivation at request time, no writes.

#### Scenario: Blocks are listed newest first
- **WHEN** `GET /api/archive/blocks` is requested with three stored blocks
- **THEN** the response lists all three ordered by race date descending, summaries only

#### Scenario: Empty table is a normal response
- **WHEN** no `block_lens` rows exist
- **THEN** the endpoint returns an empty list with status 200

### Requirement: Read-only single-block document
The server SHALL expose `GET /api/archive/blocks/:raceDate` returning the
stored `block_json` document verbatim for the block with that race date, 404
when no such block exists, and the established fail-soft 503 when the archive
is unavailable — the server process SHALL never crash on archive failure.

#### Scenario: Full document by race date
- **WHEN** `GET /api/archive/blocks/2026-08-09` is requested and that block exists
- **THEN** the response is the stored lens document verbatim

#### Scenario: Unknown race date
- **WHEN** the race-date key matches no stored block
- **THEN** the server responds 404 with a JSON error body

#### Scenario: Archive away
- **WHEN** the archive database is missing or unreadable
- **THEN** both block endpoints respond 503 fail-soft and the server keeps serving
