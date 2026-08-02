## ADDED Requirements

### Requirement: The image ships the installable web-app assets
The published image SHALL contain the web app manifest and every icon it references, served from the application's own origin.

The server SHALL respond to the manifest with the `application/manifest+json` media type, and SHALL serve the icons with cache headers appropriate to immutable assets.

#### Scenario: The assets are present in the image
- **WHEN** the container is started from the published image
- **THEN** requesting the manifest returns 200 with the manifest media type, and requesting each icon it references returns 200

#### Scenario: No third-party origin is contacted
- **WHEN** the pages are loaded with all non-same-origin requests aborted
- **THEN** the manifest and icons still resolve and the pages render completely

### Requirement: The test suite runs before an image is published
The repository SHALL provide a single command that runs the test suite and a single command that runs the responsive layout gate, and continuous integration SHALL run both before building and publishing the image.

The responsive gate SHALL run against committed fixture data, so its result does not depend on whichever telemetry happens to be present.

#### Scenario: One command runs the suite
- **WHEN** a developer runs the repository's test command
- **THEN** the full JavaScript test suite runs and its exit status reflects the result

#### Scenario: The gate is data-independent
- **WHEN** the responsive layout gate runs against the committed fixture and against a populated data directory
- **THEN** it asserts the same layout expectations in both cases

#### Scenario: A failing suite blocks publication
- **WHEN** continuous integration runs on the default branch and the suite fails
- **THEN** no image is built or pushed
