# containerized-deployment Specification (delta)

## MODIFIED Requirements

### Requirement: Personal data persists in a mounted volume
`garmin-data.js`, `plan-data.js`, the activity archive database, the auth token
cache, and the raw API cache SHALL be stored in a mounted data volume so they
survive container restarts and image upgrades. Application code SHALL ship in
the image and SHALL NOT be required in the volume.

#### Scenario: Data survives a restart
- **WHEN** the container is recreated (e.g., after an image upgrade) with the same volume attached
- **THEN** previously synced telemetry, the plan, the cached token, and the
  activity archive are still present and used

#### Scenario: The archive accumulates across image upgrades
- **WHEN** the image is upgraded and the container recreated with the same volume
- **THEN** the activity archive retains all previously archived activities and
  wellness records, and subsequent syncs continue appending to it
