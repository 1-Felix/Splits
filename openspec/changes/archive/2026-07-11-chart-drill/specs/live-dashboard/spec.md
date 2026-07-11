# live-dashboard Delta

## ADDED Requirements

### Requirement: The trajectory card links each week to its anchoring run
The cockpit's race-trajectory chart SHALL declare a link drill from static
data: a pinned week whose Riegel point carries an `anchorId` SHALL offer
"view anchor run" navigating to `/run/<anchorId>`, requiring no API request.
Weeks without an anchor (null Riegel, or a data file predating `anchorId`)
SHALL offer no drill, and the chart SHALL otherwise render and behave exactly
as before.

#### Scenario: A pinned week links to its anchor
- **WHEN** the viewer pins a trajectory week whose data carries an `anchorId`
  and activates the drill
- **THEN** the browser navigates to that run's `/run/<anchorId>` page, with no
  archive API request involved

#### Scenario: An anchorless week offers nothing
- **WHEN** the viewer pins a week with a null Riegel value or loads a data
  file without `anchorId`
- **THEN** no drill affordance renders and the pin behaves as before this
  change

### Requirement: Heatmap day cells click through to their runs
Heatmap cells for days with recorded distance SHALL resolve their runs on
activation via the archive listing endpoint: exactly one run SHALL navigate
directly to its `/run/<activityId>` page; several SHALL present a minimal
chooser naming each run; an unavailable archive SHALL surface an inline
offline indication without breaking the cell or the page. Zero-distance cells
SHALL remain inert. The cockpit's rendering SHALL remain complete without any
API — no request SHALL be issued before a cell is activated.

#### Scenario: A single-run day navigates directly
- **WHEN** the viewer activates a heatmap cell for a day holding exactly one
  running activity
- **THEN** the browser navigates to that run's page

#### Scenario: A multi-run day offers a chooser
- **WHEN** the viewer activates a cell for a day holding two running
  activities
- **THEN** a chooser names both and activating an entry navigates to that
  run's page

#### Scenario: The cockpit stays static before activation
- **WHEN** the cockpit renders and the viewer hovers heatmap cells without
  activating any
- **THEN** no archive API request is made and the page is complete

#### Scenario: An offline archive degrades at the cell
- **WHEN** the viewer activates a cell while the archive API returns 503
- **THEN** an inline offline indication appears and the heatmap and page
  remain fully functional
