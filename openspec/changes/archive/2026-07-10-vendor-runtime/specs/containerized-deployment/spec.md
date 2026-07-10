# containerized-deployment Specification (delta)

## ADDED Requirements

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
