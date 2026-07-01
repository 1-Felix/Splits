## ADDED Requirements

### Requirement: Manual sync from the dashboard
The dashboard SHALL provide a "Sync now" control that triggers a Garmin sync via `POST /api/sync` without requiring a terminal. The server SHALL run the sync by spawning the existing `sync_garmin.py`. On a successful sync the dashboard SHALL reload so the new telemetry is reflected.

#### Scenario: User triggers a sync and sees fresh data
- **WHEN** the user activates the "Sync now" control and the sync completes successfully
- **THEN** the server runs `sync_garmin.py`, writes a new `garmin-data.js` to the data directory, and the dashboard reloads to display the updated telemetry

#### Scenario: Sync reports failure without breaking the page
- **WHEN** the user triggers a sync and the sync fails (e.g., bad credentials or Garmin unreachable)
- **THEN** `POST /api/sync` returns a non-success status with an error reason, and the dashboard surfaces the failure while continuing to render the last available data

### Requirement: Sync status is observable
The server SHALL expose `GET /api/status` returning at least the last successful sync timestamp and whether a sync is currently in progress. The dashboard SHALL use it to show a "last synced" indication and a spinner/in-progress state.

#### Scenario: Status reflects an idle, previously-synced system
- **WHEN** a client requests `GET /api/status` and no sync is running
- **THEN** the response includes the last successful sync time and an in-progress flag of false

#### Scenario: Status reflects an in-progress sync
- **WHEN** a sync is running and a client requests `GET /api/status`
- **THEN** the response reports the in-progress flag as true

### Requirement: Only one sync runs at a time
The server SHALL ensure at most one sync executes concurrently. A trigger received while a sync is in progress SHALL NOT start a second sync.

#### Scenario: Concurrent trigger is rejected
- **WHEN** a sync is already in progress and `POST /api/sync` is called again
- **THEN** the server does not start a second sync and responds indicating a sync is already running

### Requirement: Sync on container boot
On container start the system SHALL run a sync when telemetry data is missing or stale, so a fresh deployment shows real data rather than demo data. A boot sync that fails SHALL NOT prevent the dashboard from starting.

#### Scenario: Fresh deployment with valid credentials
- **WHEN** the container starts with valid credentials/token and no existing `garmin-data.js`
- **THEN** a sync runs at boot and the dashboard serves the resulting telemetry

#### Scenario: Boot sync failure does not block startup
- **WHEN** the container starts and the boot sync fails
- **THEN** the web server still starts and the dashboard serves demo/last data

### Requirement: Nightly scheduled sync
The container SHALL run an automatic sync on a daily schedule so an unattended deployment stays current. The schedule time SHALL honor the container timezone and be overridable via configuration.

#### Scenario: Unattended nightly refresh
- **WHEN** the container has been running and the scheduled sync time is reached
- **THEN** a sync runs automatically and updates the telemetry in the data volume

### Requirement: Graceful degradation when sync cannot authenticate
When a sync cannot authenticate or reach Garmin (missing/invalid credentials, no cached token, network failure — or, for accounts that use it, a missing MFA code), sync SHALL fail soft: the server returns a structured error, scheduled/boot syncs log and continue, and the dashboard renders demo/last data with a prompt to connect Garmin. The system SHALL NOT crash-loop.

#### Scenario: First run cannot authenticate
- **WHEN** the container starts and the boot sync cannot authenticate (e.g., credentials missing or invalid)
- **THEN** the sync fails soft, the dashboard comes up on demo/last data with a "connect Garmin" prompt, and the container keeps running

#### Scenario: Token cache satisfies steady-state auth
- **WHEN** a valid token exists in the data volume from a prior login
- **THEN** subsequent syncs authenticate using the cached token without requiring credentials re-entry or MFA
