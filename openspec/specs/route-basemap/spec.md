# route-basemap Specification

## Purpose
TBD - created by archiving change route-basemap. Update Purpose after archive.
## Requirements
### Requirement: A run's tile rect is derived deterministically from its stored streams
The system SHALL compute each run's map coverage from the stored latitude and
longitude stream columns as a pure function: the GPS bounding box, padded by
approximately 8%, squarified by extending the shorter side symmetrically, at
the highest Web Mercator zoom level not exceeding 16 whose squarified crop
spans at most three tiles on its longer side. The covering tile rect and crop
SHALL be reproducible: the same streams SHALL always yield the same zoom and
rect.

#### Scenario: The same run always maps to the same rect
- **WHEN** the tile math runs twice over the same stored lat/lon columns
- **THEN** both passes yield the identical zoom, tile rect, and crop box

#### Scenario: A long point-to-point run zooms out instead of overflowing
- **WHEN** a run's padded, squarified crop would span more than three tiles on
  its longer side at some zoom
- **THEN** a lower zoom is chosen so the crop fits within three tiles, never a
  larger tile rect

### Requirement: Map tiles are fetched at sync time and stored deduplicated
The sync pipeline SHALL fetch OpenStreetMap raster tiles for each archived
GPS run's tile rect from the standard tile server, and SHALL store each tile
blob once, keyed by zoom/x/y, shared across all runs. Before fetching, the
pipeline SHALL probe the store and request only tiles not already present. The
browser SHALL NOT be the fetching party: tile acquisition happens exclusively
server-side, where the sync's network access already lives.

#### Scenario: A second run through the same neighbourhood reuses stored tiles
- **WHEN** a new run's tile rect overlaps tiles already stored by earlier runs
- **THEN** only the missing tiles are fetched and the overlapping tiles are
  stored exactly once

#### Scenario: Tile fetching is a sync concern
- **WHEN** any dashboard page loads in the browser
- **THEN** no request to any tile server origin is made by the page

### Requirement: Tile fetching complies with the OSM tile usage policy
Tile requests SHALL be throttled to approximately one request per second,
SHALL carry a User-Agent identifying the application, and SHALL be bounded to
each run's computed rect. Bulk operations (backfill) SHALL use the same
throttled path.

#### Scenario: Fetches are paced
- **WHEN** a run requires multiple missing tiles
- **THEN** the fetches are spaced at the configured throttle rather than
  issued concurrently

### Requirement: A run's map record is complete or absent
The system SHALL record a per-run map row (activity id, zoom, tile rect) only
after every tile in the rect is stored. A failed or interrupted fetch SHALL
leave no per-run map row, and a subsequent sync SHALL retry that run's
remaining tiles.

#### Scenario: An interrupted fetch heals on the next sync
- **WHEN** tile fetching for a run fails partway through
- **THEN** the run has no map row, its already-fetched tiles remain stored,
  and the next sync fetches only the still-missing tiles before writing the row

### Requirement: Runs without usable GPS are skipped silently
The map step SHALL skip treadmill runs and activities whose streams carry no
latitude/longitude data, writing no map row and raising no error.

#### Scenario: A treadmill run produces no map work
- **WHEN** the map step processes a run whose streams have no GPS columns
- **THEN** no tiles are fetched, no map row is written, and the sync continues

### Requirement: The existing archive is backfilled on demand
The sync entrypoint SHALL offer a backfill flag that runs the map step over
every archived activity, using the same dedup, throttle, and completeness
rules as the nightly path.

#### Scenario: Backfill covers the archive without refetching shared tiles
- **WHEN** the backfill flag runs over an archive of runs concentrated in a few
  areas
- **THEN** every GPS run gains a map row while each unique tile is fetched at
  most once

