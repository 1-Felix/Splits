## ADDED Requirements

### Requirement: Single canonical plan on the homeserver
The homeserver's data volume SHALL hold the one authoritative copy of `plan-data.js`. The
dashboard SHALL render that canonical copy, and all sync paths (home and away) SHALL read
from and write to it, so no machine keeps a competing authoritative copy.

#### Scenario: Dashboard renders the canonical plan
- **WHEN** the dashboard loads
- **THEN** it reads `plan-data.js` from the data volume (the canonical copy)

#### Scenario: Telemetry is not affected by plan sync
- **WHEN** the plan is synced by any path
- **THEN** `garmin-data.js` is not read, written, or transferred by the plan-sync mechanism

### Requirement: Home path edits the canonical file directly
The system SHALL support editing the canonical plan directly from the home machine by
mounting the data volume, with no push/pull protocol. Documentation SHALL describe mounting
the volume and pointing the repo at it (a symlink to the mounted `plan-data.js`, or running
with `SPLITS_DATA_DIR` set to the mount).

#### Scenario: A home edit is immediately canonical
- **WHEN** the home machine edits the mounted `plan-data.js`
- **THEN** the change is written to the canonical file with no additional sync step, and the
  homeserver dashboard reflects it on the next load

#### Scenario: Local dev reads canonical data from the mount
- **WHEN** local dev runs against the mounted data volume
- **THEN** it renders the canonical plan (and the homeserver's telemetry) without a separate
  local sync

### Requirement: Away path pushes over an opt-in authenticated endpoint
The server SHALL expose a `PUT /api/plan` endpoint that writes the canonical `plan-data.js`,
enabled only when a plan-sync token is configured. When no token is configured the endpoint
SHALL NOT be available. A request without a valid bearer token SHALL be rejected and SHALL
NOT modify the canonical file.

#### Scenario: Endpoint is absent when unconfigured
- **WHEN** no plan-sync token is configured and a client requests `PUT /api/plan`
- **THEN** the server responds as if the route does not exist (404) and nothing is written

#### Scenario: Missing or wrong token is rejected
- **WHEN** the endpoint is enabled and a request has a missing or incorrect bearer token
- **THEN** the server responds 401 and the canonical file is unchanged

#### Scenario: Authorized push updates the canonical plan
- **WHEN** an authorized request submits a valid plan that satisfies the version guard
- **THEN** the server writes it to the canonical `plan-data.js` and responds success with the
  new version

### Requirement: Concurrent edits are guarded by a content version
A push SHALL carry the content version (a hash) the client last read, and the server SHALL
apply the write only if that version still matches the current canonical file. A push whose
version does not match the current canonical SHALL be rejected without writing, so a stale
edit cannot overwrite a newer plan.

#### Scenario: Stale push is refused
- **WHEN** the canonical plan has changed since the client last read it and the client pushes
  with the old version
- **THEN** the server rejects the write (409) and instructs the client to pull first

#### Scenario: Up-to-date push succeeds
- **WHEN** the client pushes with the version matching the current canonical
- **THEN** the write is applied and the response returns the new version

### Requirement: A push is validated before it can replace the canonical plan
Before replacing the canonical file, the server SHALL validate that the submitted content
loads as a plan module with a well-formed training `block`. Invalid content SHALL be
rejected and SHALL leave the canonical file byte-for-byte unchanged. Oversized bodies SHALL
be rejected. The replacement SHALL be atomic, so a failed or partial write can never leave a
corrupt canonical plan.

#### Scenario: Invalid plan is rejected without touching the live file
- **WHEN** a submitted body fails to load as a plan or has a malformed `block`
- **THEN** the server responds 422 with an error and the canonical file is unchanged

#### Scenario: Oversized body is rejected
- **WHEN** a submitted body exceeds the size limit
- **THEN** the server responds 413 and the canonical file is unchanged

#### Scenario: Replacement is atomic
- **WHEN** a valid plan is written
- **THEN** the canonical file is replaced atomically (no reader ever observes a partial file)

### Requirement: Client pull and push commands
The project SHALL provide commands to pull the canonical plan to a local working copy and to
push local changes back. Pull SHALL fetch the canonical plan and record its version. Push
SHALL validate the local plan, then submit it with the recorded version; it SHALL surface a
version conflict as an instruction to pull first, and SHALL support an explicit override.

#### Scenario: Pull fetches canonical and records the version
- **WHEN** the user runs the pull command
- **THEN** the local working copy is replaced with the canonical plan and its version is
  recorded for a later push

#### Scenario: Push submits with the recorded version
- **WHEN** the user runs the push command after editing the local working copy
- **THEN** the local plan is validated and submitted with the recorded version, and on success
  the recorded version is updated

#### Scenario: Push surfaces a conflict
- **WHEN** the push is refused because the canonical changed
- **THEN** the command reports the conflict and instructs the user to pull before pushing
