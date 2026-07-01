## ADDED Requirements

### Requirement: Single image bundling web server and sync
The project SHALL be deployable as a single container image that bundles the Node web/API server and the Python sync runtime, so the dashboard and its Garmin sync run from one image.

#### Scenario: One image serves the dashboard and can sync
- **WHEN** the published image is run
- **THEN** it serves the dashboard over HTTP and is able to execute `sync_garmin.py` within the same container

### Requirement: Compose-driven deployment with credentials and a data volume
The repository SHALL provide a `docker-compose.yml` that runs the image, supplies Garmin credentials and profile/timezone settings as environment variables, and mounts a persistent volume for personal data. A user SHALL be able to deploy by setting credentials in compose and running `docker compose up`.

#### Scenario: Deploy from compose
- **WHEN** a user sets `GARMIN_EMAIL`/`GARMIN_PASSWORD` (and optional `ATHLETE_*`/`TZ`) in `docker-compose.yml` and runs `docker compose up`
- **THEN** the dashboard becomes reachable and syncs use the provided credentials

### Requirement: Personal data persists in a mounted volume
`garmin-data.js`, `plan-data.js`, the auth token cache, and the raw API cache SHALL be stored in a mounted data volume so they survive container restarts and image upgrades. Application code SHALL ship in the image and SHALL NOT be required in the volume.

#### Scenario: Data survives a restart
- **WHEN** the container is recreated (e.g., after an image upgrade) with the same volume attached
- **THEN** previously synced telemetry, the plan, and the cached token are still present and used

### Requirement: App/data split in serving and writing
The web server SHALL serve `garmin-data.js` and `plan-data.js` from the configured data directory, and the sync SHALL write its output there via configuration. Outside the container (local dev), both SHALL fall back to the project directory so `pnpm dev` and a manual `python sync_garmin.py` keep working unchanged.

#### Scenario: Data files served from the volume in the container
- **WHEN** the dashboard requests `garmin-data.js` or `plan-data.js` while running in the container
- **THEN** the server returns the copy from the data directory

#### Scenario: Local development needs no data directory
- **WHEN** a developer runs `pnpm dev` outside the container
- **THEN** data files resolve from the project directory and the dashboard works without a configured volume

### Requirement: Plan seeded from a default, never clobbered on upgrade
The image SHALL ship a default plan. On first boot, if no `plan-data.js` exists in the data volume, the system SHALL seed it from the default. If a `plan-data.js` already exists in the volume, the system SHALL leave it untouched on subsequent boots and upgrades.

#### Scenario: Fresh volume gets a working plan
- **WHEN** the container boots with an empty data volume
- **THEN** `plan-data.js` is created in the volume from the shipped default

#### Scenario: Existing plan is preserved across upgrades
- **WHEN** the container boots (including after an image upgrade) and the volume already contains `plan-data.js`
- **THEN** the existing plan is preserved and not overwritten by the default

### Requirement: Image published to the repository container registry
A CI workflow SHALL build and publish the image to `ghcr.io/1-felix/splits` on pushes to the default branch and on version tags, producing a rolling `latest` and tag-pinned releases.

#### Scenario: Publish on push to main
- **WHEN** a commit is pushed to the default branch
- **THEN** CI builds the image and pushes it to `ghcr.io/1-felix/splits` with a `latest` tag

#### Scenario: Publish a tagged release
- **WHEN** a version tag is pushed
- **THEN** CI builds and pushes an image tagged with that version
