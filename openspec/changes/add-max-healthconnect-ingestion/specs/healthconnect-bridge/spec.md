## ADDED Requirements

### Requirement: Read running workouts from Health Connect
The bridge app SHALL read completed running exercise sessions from Android
Health Connect, and for each session SHALL read the associated heart-rate
samples, distance, and speed that fall within the session's time window.
Non-running exercise types SHALL be excluded. The app SHALL request the Health
Connect read permissions required for these data types and SHALL function after
a one-time user permission grant.

#### Scenario: A completed run is read with its metrics
- **WHEN** a running exercise session exists in Health Connect with heart-rate, distance, and speed data
- **THEN** the app reads the session's start time, duration, distance, average heart rate, heart-rate samples, and speed

#### Scenario: Non-running exercise is ignored
- **WHEN** the session in Health Connect is a non-running type (e.g., cycling, strength)
- **THEN** the app does not read or push it

#### Scenario: Permission not granted
- **WHEN** the required Health Connect read permissions have not been granted
- **THEN** the app requests them and does not crash or push data until they are granted

### Requirement: Push a normalized run payload to a SPLITS instance
The bridge app SHALL push each run to a configured SPLITS ingest URL as an
authenticated HTTP request carrying a bearer token. The payload SHALL be a
normalized per-run object containing at least: start time (local), duration,
distance, average heart rate, sport type, a downsampled heart-rate sample series
sufficient to compute minutes-in-zone, and the Health Connect session UID. The
server URL and token SHALL be configurable without rebuilding the app.

#### Scenario: A run is pushed successfully
- **WHEN** the app has a run to push and valid URL + token configuration
- **THEN** it sends an authenticated POST with the normalized run payload and treats a success response as delivered

#### Scenario: Server unreachable
- **WHEN** the ingest endpoint is unreachable or returns an error
- **THEN** the app retains the run and retries on a later sync without losing data

### Requirement: Idempotent delivery by session UID
The bridge app SHALL include the Health Connect session UID with every pushed
run so that re-pushing the same session does not create a duplicate on the
server. Re-running a sync SHALL be safe.

#### Scenario: The same run is pushed twice
- **WHEN** a run that was already delivered is pushed again (e.g., after a retry or re-sync)
- **THEN** it carries the same session UID and the server treats it as the same run, not a new one

### Requirement: Recurring background sync with initial backfill
The bridge app SHALL sync on a recurring background schedule after setup,
requiring no per-run user interaction (set-and-forget). On first run it SHALL
backfill runs since a configurable start date; thereafter it SHALL push newly
recorded runs on the next scheduled sync.

#### Scenario: A new run is picked up automatically
- **WHEN** a new running session is recorded in Health Connect after setup
- **THEN** the app pushes it on the next scheduled background sync without the user opening the app

#### Scenario: First-run backfill
- **WHEN** the app runs for the first time with a configured backfill start date
- **THEN** it reads and pushes all qualifying runs recorded on or after that date
