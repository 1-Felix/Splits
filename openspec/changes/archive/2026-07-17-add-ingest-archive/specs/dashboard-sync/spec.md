# dashboard-sync Specification (delta)

Records behavior shipped 2026-07-17 (instance-aware chrome pass): `/api/status`
carries instance-shape flags so the pages can fit their chrome to the
instance.

## MODIFIED Requirements

### Requirement: Sync status is observable
The server SHALL expose `GET /api/status` returning at least the last
successful sync timestamp, whether a sync is currently in progress, and the
instance's shape: `ingestFed` (true when the instance is fed via the ingest
API and has no Garmin sync to offer) and `archive` (true when an archive
database is present and answerable). The dashboard SHALL use the sync fields
to show a "last synced" indication and a spinner/in-progress state, and the
shape flags to fit its chrome: an ingest-fed instance SHALL NOT offer the
Garmin sync control, and an instance without an archive SHALL NOT offer
archive navigation or archive drill links. Absent shape flags (an older
server) SHALL leave the full chrome visible.

#### Scenario: Status reflects an idle, previously-synced system
- **WHEN** a client requests `GET /api/status` and no sync is running
- **THEN** the response includes the last successful sync time and an in-progress flag of false

#### Scenario: Status reflects an in-progress sync
- **WHEN** a sync is running and a client requests `GET /api/status`
- **THEN** the response reports the in-progress flag as true

#### Scenario: An ingest-fed instance hides the Garmin sync control
- **WHEN** `/api/status` reports `ingestFed: true` and a dashboard page loads
- **THEN** the page renders no Garmin sync control

#### Scenario: An instance without an archive hides archive chrome
- **WHEN** `/api/status` reports `archive: false` and a dashboard page loads
- **THEN** the page renders no archive navigation tab and no archive drill
  links

#### Scenario: The archive flag reflects provisioning, enabling auto-reveal
- **WHEN** an archive database appears on an instance that previously had none
- **THEN** subsequent `/api/status` responses report `archive: true` and pages
  render the archive chrome again with no code change
