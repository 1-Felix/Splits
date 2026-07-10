# containerized-deployment Specification

## Purpose
TBD - created by archiving change selfhost-dashboard-sync. Update Purpose after archive.
## Requirements
### Requirement: Single image bundling web server and sync
The project SHALL be deployable as a single container image that bundles the Node web/API server and the Python sync runtime, so the dashboard and its Garmin sync run from one image.

#### Scenario: One image serves the dashboard and can sync
- **WHEN** the published image is run
- **THEN** it serves the dashboard over HTTP and is able to execute `sync_garmin.py` within the same container

### Requirement: Compose-driven deployment with credentials and a data volume
The repository SHALL provide a `docker-compose.yml` that runs the image, reads Garmin credentials and timezone from a git-ignored `.env` (via `${VAR}` substitution) and passes them to the container as environment variables, and mounts a persistent volume for personal data. A user SHALL be able to deploy by putting credentials in `.env` and running `docker compose up`. Credentials SHALL NOT be committed — the compose file references them, it does not contain them.

#### Scenario: Deploy from compose
- **WHEN** a user sets `GARMIN_EMAIL`/`GARMIN_PASSWORD` (and optional `TZ`) in `.env` and runs `docker compose up`
- **THEN** the dashboard becomes reachable and syncs use the credentials supplied via `.env`

#### Scenario: Missing credentials do not block startup
- **WHEN** `.env` is absent or the credentials are unset
- **THEN** compose still starts the container (creds resolve to empty) and the dashboard comes up in the graceful-degradation state rather than failing to launch

### Requirement: Personal data persists in a mounted volume
`garmin-data.js`, `plan-data.js`, the activity archive database, the auth token cache, and the raw API cache SHALL be stored in a mounted data volume so they survive container restarts and image upgrades. Application code SHALL ship in the image and SHALL NOT be required in the volume.

#### Scenario: Data survives a restart
- **WHEN** the container is recreated (e.g., after an image upgrade) with the same volume attached
- **THEN** previously synced telemetry, the plan, the cached token, and the
  activity archive are still present and used

#### Scenario: The archive accumulates across image upgrades
- **WHEN** the image is upgraded and the container recreated with the same volume
- **THEN** the activity archive retains all previously archived activities and
  wellness records, and subsequent syncs continue appending to it

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

### Requirement: The server runtime provides a built-in SQLite driver
The image SHALL provide a Node runtime with a stable built-in SQLite driver
(`node:sqlite`, Node 24 or later) so the archive API runs without adding any
npm dependency. The web server SHALL remain zero-dependency. On a runtime
without the driver (e.g. an older local Node), the server SHALL still boot and
serve all pages while archive endpoints degrade per the archive-api spec, and
the expected Node version SHALL be declared in `package.json` engines and the
README.

#### Scenario: The container serves the archive API dependency-free
- **WHEN** the published image runs
- **THEN** archive endpoints work using the runtime's built-in SQLite driver
  and the server has no production npm dependencies

#### Scenario: An older local runtime degrades, not breaks
- **WHEN** a developer runs `pnpm dev` on a Node without `node:sqlite`
- **THEN** the server boots, both pages serve, and only archive endpoints
  return 503

### Requirement: The image ships the vendored client runtime
The image SHALL contain the vendored client assets (React UMD builds, typefaces,
and any vendored client library) as application code, served from the
application's own origin. These assets SHALL NOT live in the data volume, and
the container SHALL render the cockpit with outbound network access removed.

#### Scenario: The container serves the cockpit with no egress
- **WHEN** the container runs with outbound DNS and HTTP blocked and a browser
  on the LAN loads the cockpit
- **THEN** the page renders completely

#### Scenario: Vendored assets upgrade with the image, not the volume
- **WHEN** the image is upgraded and the container recreated with the same
  volume attached
- **THEN** the vendored assets come from the new image and no volume migration
  is required

### Requirement: Static and JSON responses are served compressed
The server SHALL negotiate `gzip` for responses whose content type is `text/*`,
`application/javascript`, or `application/json` when the request advertises
`Accept-Encoding: gzip`, setting `Content-Encoding` and `Vary: Accept-Encoding`.
Already-compressed types (fonts, images) SHALL be served unencoded. Compression
SHALL use the runtime's built-in facilities, keeping the server free of
third-party dependencies.

#### Scenario: A compressing client
- **WHEN** a client requests `garmin-data.js` with `Accept-Encoding: gzip`
- **THEN** the response carries `Content-Encoding: gzip` and decodes to bytes
  identical to the uncompressed response

#### Scenario: A non-compressing client
- **WHEN** a client requests the same resource without `Accept-Encoding`
- **THEN** the response body is the plain bytes and carries no
  `Content-Encoding`

#### Scenario: Fonts are not double-compressed
- **WHEN** a client requests a vendored `woff2` with `Accept-Encoding: gzip`
- **THEN** the response carries no `Content-Encoding`

