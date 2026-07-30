# run-detail Specification

## Purpose

The run's own page at `/run/:id`: full-resolution sample streams as
synchronised tracks under one crosshair, the GPS trace as a projected polyline
(never a basemap), per-kilometre splits against the run's own median, the best
efforts the run set, and — the part Garmin structurally cannot draw — what the
plan asked for beside what happened. Fails soft when the archive is away.
## Requirements
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

### Requirement: The rep card pairs each recovery to its rep by time
The rep card SHALL pair a recovery line to a rep by temporal adjacency: the
recovery shown under rep *i* is the first `recovery`-role segment whose start
falls at or after rep *i*'s end and (when a later rep exists) before the next
rep's start. When no recovery matches, the rep SHALL show no recovery line.
Pairing MUST NOT rely on array position, because a mid-set demotion inserts a
`recovery`-role segment that shifts every later position.

#### Scenario: Mid-set demotion does not shift later pairings
- **WHEN** a set contains a demoted mid-set segment (role `recovery`) between two
  reps
- **THEN** every rep after the demotion still shows the recovery that actually
  followed it in time

#### Scenario: A rep with no following recovery shows none
- **WHEN** the final rep of a set is followed by no `recovery`-role segment
  before the cooldown
- **THEN** that rep renders without a recovery line rather than borrowing an
  earlier one

### Requirement: Absent grade-adjusted pace renders as absent, by presence not truthiness
A segment's grade-adjusted pace SHALL be rendered as an em dash exactly when the
value is absent (`null`), and as a formatted pace for every numeric value. The
engine SHALL emit `null` (never `0`) for a grade-adjusted pace it cannot compute,
so no numeric sentinel can be confused with a real pace.

#### Scenario: Missing GAP renders as an em dash
- **WHEN** a segment carries `gapS: null`
- **THEN** the rep card renders an em dash in the GAP position

#### Scenario: Invalid speed produces null, not zero
- **WHEN** the engine derives grade-adjusted pace from a non-positive speed value
- **THEN** the document carries `gapS: null` for that segment

### Requirement: The plan card shows the prescription's verdict beside the executed structure
The `/run/:id` plan card SHALL render the planned prescription text and its
verdict alongside the existing planned-vs-actual line whenever the run's
matched plan day carries a rep-level verdict. When no verdict exists the card SHALL render
exactly as before — absence, not emptiness.

#### Scenario: A quality day's run shows the verdict
- **WHEN** the run's plan day carries a verdict (`4/4 reps, 3 inside
  5:25–5:35`)
- **THEN** the plan card renders the planned text and that verdict

#### Scenario: A day without a verdict renders unchanged
- **WHEN** the run's plan day has no `quality` annotation
- **THEN** the plan card renders exactly its pre-existing content
