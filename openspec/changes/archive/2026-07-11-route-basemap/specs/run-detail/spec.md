## RENAMED Requirements

- FROM: `### Requirement: The route renders as a trace, never from map tiles`
- TO: `### Requirement: The route renders over the archive's own basemap, never a third party`

## MODIFIED Requirements

### Requirement: The route renders over the archive's own basemap, never a third party
The page SHALL render the run's GPS track from the stream's latitude and
longitude columns as a projected polyline on the application's own surface,
with the crosshair's current sample marked on the path. When the run has a
stored map rect, the page SHALL render the archive's own basemap tiles behind
the route by default, dimmed by a dark treatment so the themed route stays
visually primary, and SHALL offer a chip toggle between the map backdrop and
the bare shape; toggling SHALL only show or hide the backdrop, never change
the route's geometry. A mapped trace card SHALL carry the attribution
"Basemap © OpenStreetMap contributors". A run without a stored map rect SHALL
render the bare shape exactly as before, without the toggle. All tile imagery
SHALL be served from the application's own origin; the page SHALL NOT request
map tiles or any other third-party resource.

#### Scenario: The trace follows the crosshair
- **WHEN** the viewer moves the crosshair along any track
- **THEN** the marked position on the route trace moves to the same sample

#### Scenario: The route renders with no network
- **WHEN** the page renders with every non-same-origin request aborted
- **THEN** the route trace renders, and any stored basemap tiles load from the
  application's own origin

#### Scenario: A mapped run shows geography by default
- **WHEN** a run with a stored map rect opens
- **THEN** the trace card renders same-origin tiles behind the route, the
  dark treatment applied, with the OpenStreetMap attribution visible

#### Scenario: The shape toggle hides only the backdrop
- **WHEN** the viewer toggles the trace card from map to shape
- **THEN** the tiles disappear while the route polyline, start/finish markers,
  and pin keep their exact positions

#### Scenario: A run without a map renders as before
- **WHEN** a run has no stored map rect
- **THEN** the trace card renders the bare projected shape with no toggle and
  no tile requests
