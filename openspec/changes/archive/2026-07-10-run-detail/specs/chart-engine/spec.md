# chart-engine Specification (delta)

## ADDED Requirements

### Requirement: A continuous crosshair primitive serves dense series
The engine SHALL provide a continuous crosshair primitive that maps a pointer
position through the x scale to the nearest sample by bisection, clamped at both
ends of the domain, for series too dense for per-point hit bands. The existing
per-point band primitive SHALL remain unchanged and continue to serve sparse
series. Neither primitive SHALL be generalised to cover both.

#### Scenario: A dense series resolves the nearest sample
- **WHEN** a pointer position falls between two of a thousand-plus samples
- **THEN** the crosshair resolves to the nearer sample's index

#### Scenario: Positions beyond the domain clamp
- **WHEN** a pointer position falls outside the x domain
- **THEN** the crosshair resolves to the first or last sample, without error

#### Scenario: Sparse charts keep their band geometry
- **WHEN** a monthly trend chart renders
- **THEN** it uses per-point hit bands, unchanged by this addition

### Requirement: Stacked tracks share one x scale and one crosshair index
The engine SHALL provide a multi-track specification: several plots stacked
vertically, sharing one x domain and one crosshair index, each carrying its own y
domain resolved through the domain policy. The shared x basis SHALL be a
parameter, so the same tracks can be plotted against distance or against elapsed
time. No track SHALL carry two y scales.

#### Scenario: One index, many tracks
- **WHEN** the crosshair resolves an index on one track
- **THEN** every track in the stack reads the value at that same index

#### Scenario: The shared basis is a parameter
- **WHEN** the shared x basis changes from distance to elapsed time
- **THEN** every track re-resolves its x scale and its ticks against the new
  basis, and the y domains are unaffected

### Requirement: Geographic coordinates project to a fitted trace
The engine SHALL project latitude and longitude columns to plot coordinates
using an equirectangular projection with a cosine-of-latitude correction on
longitude, fitted to the viewport with the aspect ratio preserved, so a route's
shape is not distorted. Projection SHALL be pure and require no external
resource.

#### Scenario: A route keeps its shape
- **WHEN** a run's coordinates are projected into a viewport of any aspect ratio
- **THEN** the trace's own aspect ratio is preserved and the path fits within
  the viewport

#### Scenario: Projection is translation-invariant
- **WHEN** the same route is projected from two different origins
- **THEN** the resulting paths are congruent
