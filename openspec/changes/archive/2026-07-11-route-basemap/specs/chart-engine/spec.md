## ADDED Requirements

### Requirement: Tile-backed traces project with Web Mercator alignment
For a run with a stored tile rect, the engine SHALL project latitude and
longitude columns to plot coordinates using the Web Mercator formula at the
rect's zoom, offset by the crop origin — the same math that positions the
tiles — so the route and its basemap align by construction. The projection
SHALL be pure, SHALL require no external resource, and SHALL preserve null
samples as gaps. The existing equirectangular projection SHALL remain the
path for runs without a tile rect, unchanged.

#### Scenario: The route lands on its map
- **WHEN** a route is projected against its tile rect and the rect's tiles are
  laid out at their world positions
- **THEN** every projected point falls at the same world-pixel coordinate the
  tile math assigns that latitude/longitude

#### Scenario: Nulls still gap
- **WHEN** the lat/lon columns contain null samples (GPS dropouts)
- **THEN** the Mercator-projected points are null at those indices and the
  polyline gaps honestly

#### Scenario: Mapless runs are untouched
- **WHEN** a run has no tile rect
- **THEN** the trace uses the existing fitted equirectangular projection with
  identical output to before this change

### Requirement: Trace rendering accepts an optional tile layer behind the route
The trace renderer SHALL accept an optional set of tile references (zoom and
tile coordinates with their placement) and SHALL paint them as an image layer
behind the route path, start/finish markers, and crosshair pin. The route and
its markers SHALL render identically whether the tile layer is present,
hidden, or partially unavailable; a tile that fails to load leaves a gap in
the backdrop, never an error and never a missing route.

#### Scenario: Tiles sit behind the route
- **WHEN** a trace renders with a tile layer
- **THEN** the tile images paint before the route path in the SVG order, and
  the pin and start/finish markers remain on top

#### Scenario: The route never depends on its backdrop
- **WHEN** one or more tile images fail to load
- **THEN** the route polyline, markers, and pin render unaffected
