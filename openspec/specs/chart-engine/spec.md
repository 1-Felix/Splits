# chart-engine Specification

## Purpose

The shared plotting engine every SPLITS chart renders through: vendored d3
primitives (`vendor/d3-lite.js`), pure geometry and domain policy
(`chart-core.js`), and a spec-to-elements renderer (`chart-view.js`). It owns
the opinions a plotting library refuses to have — minimum spans, zero
anchoring, forced goal inclusion, honest gaps, reference layers, confidence
weighting — plus the accessibility contract and the palette rules that keep
series colour distinct from status colour.

## Requirements

### Requirement: Plotting primitives are vendored, declared, and verified
The project SHALL vendor its plotting primitives (`d3-scale`, `d3-shape`,
`d3-array`, `d3-time-format`) as a single checked-in ESM artifact served from the
application's own origin. A declaration module SHALL name the exact symbol
surface in use, and the artifact SHALL be regenerable by a documented command. No
plotting library SHALL be loaded from a third-party origin, and the runtime
server SHALL remain free of third-party dependencies.

#### Scenario: A stale artifact is caught at test time
- **WHEN** the chart core imports a symbol the vendored artifact does not export
- **THEN** the test suite fails, naming the missing symbol

#### Scenario: The page loads no plotting CDN
- **WHEN** the dashboard renders with every non-same-origin request aborted
- **THEN** all charts render

### Requirement: Chart geometry is pure and independently testable
The engine SHALL confine chart geometry, domain policy, tick selection, null
segmentation, baseline-band computation, confidence weighting, and annotation
placement to a module with no DOM and no framework dependency, testable in
isolation. Rendering SHALL be the only concern of a separate module that consumes
the geometry module's output. The existing hover geometry SHALL be reused, not
reimplemented.

#### Scenario: Geometry is exercised without a browser
- **WHEN** the test suite runs the chart-core tests
- **THEN** they execute with no DOM, no React, and no rendering, and cover
  domain policy, ticks, gaps, bands, confidence, and annotation placement

#### Scenario: Rendering consumes the spec
- **WHEN** the view module renders a chart specification
- **THEN** it produces an element tree and computes no geometry of its own

### Requirement: Every chart resolves its domain against a stated policy
A chart's y domain SHALL be derived from a declared policy rather than from the
data's extent alone. The policy SHALL support a nice-rounded domain, forced
inclusion of reference values (such as a goal), a **minimum span** below which
the domain is expanded symmetrically about its midpoint, and zero-anchoring for
magnitude metrics. Every policy in use SHALL be declared in one place.

#### Scenario: A small change is not rendered as a large one
- **WHEN** a metric varies across a range narrower than its declared minimum span
- **THEN** the resolved domain equals the minimum span, and the plotted series
  occupies proportionally less than the full plot height

#### Scenario: Magnitude metrics start at zero
- **WHEN** weekly volume renders
- **THEN** its y domain begins at zero

#### Scenario: A goal is always in frame
- **WHEN** a chart declares a reference goal value
- **THEN** the resolved domain contains that value regardless of the data's
  extent

### Requirement: Every chart is readable without interaction
Every trend chart SHALL render labelled y-axis ticks and labelled x-axis ticks
without requiring hover or focus. Gridlines SHALL be drawn at tick values, never
at fixed pixel offsets. A chart carrying two or more series SHALL render a
legend; a single-series chart SHALL rely on its title. Value, label, and legend
text SHALL use ink tokens and SHALL NOT be coloured with a series colour.

#### Scenario: A value can be read without hovering
- **WHEN** a trend chart renders
- **THEN** its y axis shows tick labels in the metric's own units and its x axis
  shows time labels

#### Scenario: Identity is never carried by colour alone
- **WHEN** a chart renders two or more series
- **THEN** a legend names each series beside its colour

### Requirement: Missing data is drawn as missing, and uncertainty is drawn as uncertainty
A series SHALL be split into contiguous non-null segments, and no line SHALL be
drawn across a null. Where the data supplies a per-point sample weight, the chart
SHALL encode it — points below a declared floor rendering as hollow marks
excluded from the line, and points above it sized by weight.

#### Scenario: A gap is never bridged
- **WHEN** a monthly series contains null months between valid points
- **THEN** the chart draws separate paths on either side of the gap and no
  segment crosses it

#### Scenario: A thinly-evidenced point looks thin
- **WHEN** two monthly points carry sample weights differing by five times
- **THEN** their marks differ in size, and a point beneath the declared floor
  renders hollow and is excluded from the line

### Requirement: Trends are drawn against a reference
Where a policy declares one, a chart SHALL render a reference layer beneath its
series — a rolling-median band with an interquartile ribbon, a target line, or a
comparison rule. Reference layers SHALL be presentation over already-derived
data and SHALL NOT introduce new training metrics; all metric derivation remains
in the deterministic sync.

#### Scenario: A deviation is visible against the baseline
- **WHEN** a series with a declared baseline band renders
- **THEN** the band renders behind the series, and a point outside the band is
  visibly outside it

#### Scenario: The engine derives no new truth
- **WHEN** the chart modules run
- **THEN** they compute no training metric that the data file does not already
  carry, and require no metrics-version bump

### Requirement: Charts inherit the accessibility contract
Every chart SHALL expose `role="img"` with a descriptive `aria-label`, SHALL be
focusable, SHALL support arrow-key traversal of its data points and
`Enter`/`Space` to pin a reading, and SHALL show a visible focus outline. These
behaviours SHALL be provided by the engine so that no individual chart can omit
them.

#### Scenario: A chart is navigable by keyboard
- **WHEN** a chart receives focus and the user presses the arrow keys
- **THEN** the reading advances point by point and the pinned value is announced
  by the accessible label

#### Scenario: A new chart cannot forget accessibility
- **WHEN** a chart is added through the engine
- **THEN** it carries the role, label, focus behaviour, and keyboard traversal
  without per-chart code

### Requirement: Series colours are reserved and validated
Theme palettes SHALL define series colours distinctly from status colours
(good/warning) and from heart-rate zone colours; no token SHALL serve two roles.
Ordinal ramps (heart-rate zones) SHALL be monotone in lightness rather than
rainbow-hued. Every theme's palette SHALL be checked by the palette validator
against that theme's own surface, and any failure SHALL be fixed before release.

#### Scenario: A status colour is never a series colour
- **WHEN** any theme is inspected
- **THEN** no series token equals a status token or a zone token

#### Scenario: Palettes are validated, not eyeballed
- **WHEN** the test suite runs
- **THEN** each theme's categorical palette passes the validator's lightness,
  chroma, colour-vision-deficiency separation, and contrast checks

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
