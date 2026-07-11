## ADDED Requirements

### Requirement: Stored map tiles are served same-origin as images
The server SHALL expose `GET /api/archive/tiles/:z/:x/:y.png` returning the
stored tile blob with an `image/png` content type and long-lived cache
headers. A tile not present in the store SHALL return 404. The endpoint SHALL
be read-only, GET-only, and fail-soft like the other archive endpoints: an
unreachable archive yields a 503 without taking the server down.

#### Scenario: A stored tile is served from our origin
- **WHEN** a client requests `/api/archive/tiles/<z>/<x>/<y>.png` for a stored
  tile
- **THEN** the response is the PNG blob with `image/png` and cache headers,
  served from the application's own origin

#### Scenario: A missing tile is a quiet 404
- **WHEN** a client requests a tile coordinate not in the store
- **THEN** the server responds 404 without error noise or side effects

## MODIFIED Requirements

### Requirement: Single-activity endpoint serves the established distilled detail contract
The server SHALL expose `GET /api/archive/activities/:id` returning the
activity's promoted summary plus its stored distilled detail in exactly the
shape `garmin-data.js` uses for recent runs (`splits`, `hrSeries`, `driftBpm`,
`zoneMin`, `tempC`, `te`, `load`, `elevGain`, `splitShape`), so existing
drill-down consumers work on any archived run. Activities without a stored
distilled detail SHALL return their summary with a null detail. When the
activity has a stored map record, the response SHALL additionally carry a
`map` field with the zoom, tile rect, and crop box (`z`, `x0`, `y0`, `x1`,
`y1`, `cropX`, `cropY`, `cropSize` — the crop in world pixels at zoom `z`);
activities without a map record SHALL omit the field. Raw Garmin payloads
(`summary_json`, `detail_json`) SHALL NOT be exposed by any endpoint.

#### Scenario: An archived run opens like a recent run
- **WHEN** a client requests `/api/archive/activities/<id>` for a run with
  stored distilled detail
- **THEN** the response's detail object has the same shape as a recent run's
  `detail` in `garmin-data.js`

#### Scenario: Unknown id
- **WHEN** a client requests an id not present in the archive
- **THEN** the server responds 404 with a JSON error body

#### Scenario: An activity without distilled detail degrades to its summary
- **WHEN** a client requests a non-run activity or a run whose detail has not
  been distilled yet
- **THEN** the response carries the promoted summary and a null detail, not an
  error

#### Scenario: Raw payloads stay server-side
- **WHEN** any archive endpoint response is inspected
- **THEN** it contains no raw Garmin `summary_json`/`detail_json` content

#### Scenario: A mapped run carries its rect
- **WHEN** a client requests an activity that has a stored map record
- **THEN** the response carries `map` with `z`, `x0`, `y0`, `x1`, `y1`,
  `cropX`, `cropY`, `cropSize`, and an activity without a map record carries
  no `map` field
