# run-detail Specification

## ADDED Requirements

### Requirement: A run has its own page at /run/:id
The server SHALL serve a run-detail page at `/run/<activityId>`, resolving the
route by pattern rather than by an exact path map, and the page SHALL read its
activity id from the location. An unknown or unarchived id SHALL produce an
honest "unknown run" state, not a broken page.

#### Scenario: A run page loads by id
- **WHEN** a viewer opens `/run/` followed by an archived activity id
- **THEN** the run-detail page renders that run's streams, splits, and summary

#### Scenario: An unknown id degrades honestly
- **WHEN** a viewer opens `/run/` followed by an id the archive does not hold
- **THEN** the page renders its chrome and reports that the run is unknown

### Requirement: The page answers whether the run was good before any chart is read
The run page SHALL lead with a plain-language verdict for the run, drawn from
the same read the recent-run drill-down already renders, so the page's core
question is answered without interpreting a chart.

#### Scenario: The verdict is above the charts
- **WHEN** a run page renders
- **THEN** a summary verdict appears before the track stack

### Requirement: Streams render as synchronised tracks over one shared axis
The page SHALL render the run's streams as stacked tracks — pace, heart rate,
cadence, elevation, and power — sharing one x axis and one crosshair, so a
single position is read across every track at once. Each track SHALL carry its
own labelled y axis; no track SHALL plot two measures against two scales. The x
axis SHALL be switchable between distance and elapsed time. Tracks whose stream
column carries no data SHALL be omitted silently.

#### Scenario: One crosshair, every track
- **WHEN** the viewer moves the pointer across any track
- **THEN** every track shows the reading at the same sample, and the values are
  those of one moment in the run

#### Scenario: The axis switches basis
- **WHEN** the viewer switches the x axis from distance to time
- **THEN** every track re-renders against elapsed time with a labelled axis, and
  the crosshair continues to index one shared sample

#### Scenario: A missing stream is silent
- **WHEN** a run carries no power data
- **THEN** the power track is absent and no error or empty panel renders

### Requirement: Grade-adjusted pace overlays pace, and heart-rate zones shade the heart-rate track
The pace track SHALL draw grade-adjusted pace as a recessive second line in the
same units and on the same axis, so the divergence on hilly runs is visible. The
heart-rate track SHALL shade its background with the athlete's heart-rate zones.

#### Scenario: A hilly run shows its adjustment
- **WHEN** a run's grade-adjusted pace diverges from its raw pace
- **THEN** both lines render on the pace track's single axis, with the
  grade-adjusted line visually recessive

#### Scenario: Zones are readable behind the trace
- **WHEN** the heart-rate track renders
- **THEN** the athlete's zone boundaries shade the plot background, and the
  series remains legible against them

### Requirement: The route renders as a trace, never from map tiles
The page SHALL render the run's GPS track from the stream's latitude and
longitude columns as a projected polyline on the application's own surface,
with the crosshair's current sample marked on the path. The page SHALL NOT
request map tiles or any other third-party resource.

#### Scenario: The trace follows the crosshair
- **WHEN** the viewer moves the crosshair along any track
- **THEN** the marked position on the route trace moves to the same sample

#### Scenario: The route renders with no network
- **WHEN** the page renders with every non-same-origin request aborted
- **THEN** the route trace renders

### Requirement: Splits, records, and the plan are shown beside the streams
The page SHALL render a per-kilometre splits table with a bar per split scaled
against the run's own pace distribution; the best efforts this run established,
read from the archive's per-run metrics; and, where the run matched a planned
session, what the plan asked for beside what happened together with the
compliance verdict the sync already scored. A run with no matching planned
session SHALL omit that section without comment.

#### Scenario: A record set inside a run is named
- **WHEN** a run holds the archive's best 5k effort
- **THEN** the page names that best effort among the records this run set

#### Scenario: A planned session is shown beside its outcome
- **WHEN** the run is matched to a planned session in the archive's compliance
  records
- **THEN** the page shows the planned kind, distance, and title alongside the
  actual distance, pace, and heart rate, and the scored compliance status

#### Scenario: An unplanned run omits the comparison
- **WHEN** the run matched no planned session
- **THEN** the planned-versus-actual section does not render, and no placeholder
  or error appears

#### Scenario: A swapped session explains itself
- **WHEN** the run was scored as a swapped session
- **THEN** the page states that it was swapped and shows the reason recorded by
  the sync

### Requirement: The run page degrades honestly when the archive is unreachable
When the archive API is unavailable, the page SHALL render its chrome and show
an "archive offline" indication in place of the run's data, and SHALL NOT throw
or break layout.

#### Scenario: Streams unavailable
- **WHEN** the streams endpoint returns 503
- **THEN** the page shows an archive-offline indication where the tracks would
  be, and the rest of the page remains functional
