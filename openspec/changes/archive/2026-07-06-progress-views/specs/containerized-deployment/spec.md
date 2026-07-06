# containerized-deployment Specification (delta)

## ADDED Requirements

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
