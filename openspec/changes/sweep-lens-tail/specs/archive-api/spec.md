## ADDED Requirements

### Requirement: Served interval documents carry their lens version

Any endpoint that serves an interval document, or a listing row derived from one,
SHALL include the stored `lens_version` (as `lensVersion`) so a consumer can
detect a document computed by an older engine between an `INTERVAL_VERSION` bump
and the next sync. The API SHALL NOT filter stale documents out — availability
across a version bump is preserved and staleness is the consumer's decision.
This matches the existing block and course endpoints, which already expose their
version.

#### Scenario: Single-run interval read exposes the version

- **WHEN** a client reads a run's interval document by activity id
- **THEN** the response carries `lensVersion` alongside the document

#### Scenario: Archive listing exposes the version per run

- **WHEN** a client reads the archive run listing
- **THEN** each row that carries interval-derived fields also carries that
  document's `lensVersion`

#### Scenario: Stale documents are served, not hidden

- **WHEN** the stored document's `lens_version` is older than the engine's
  current `INTERVAL_VERSION` (a bump has happened, the sync has not yet run)
- **THEN** the document is still served, with its older `lensVersion` visible
