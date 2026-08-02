## ADDED Requirements

### Requirement: Charts decide density against their rendered width
Every chart SHALL make its density decisions against the width it is actually rendered at, not against a fixed drawing frame.

Tick count, label thinning, annotation lane assignment and hit-band geometry are all judgements about what fits on screen. Where a chart's drawing frame is scaled to its container, those judgements SHALL be expressed in rendered CSS pixels, so a narrow chart draws fewer ticks rather than the same ticks drawn closer together. A chart rendered at a desktop width SHALL be unchanged by this requirement.

#### Scenario: A narrow chart thins its own axis
- **WHEN** a 30-point monthly chart is rendered in a 324px-wide container
- **THEN** it emits materially fewer x-axis ticks than the same chart rendered at 1066px, and no two adjacent tick labels overlap

#### Scenario: Desktop rendering is unchanged
- **WHEN** every chart is rendered at 1200px and wider
- **THEN** its tick count, label placement and geometry are identical to before this change

#### Scenario: Axis labels stay inside their gutter
- **WHEN** any chart is rendered at 360px
- **THEN** each axis label fits within the space reserved for it and is not painted over the plot

#### Scenario: A track's unit does not collide with its caption
- **WHEN** a stacked track carrying a unit label is rendered at any width
- **THEN** the unit label does not overlap the track's caption or the axis labels of the track above it

### Requirement: The crosshair has a real pointer path
Charts SHALL respond to touch and pen input directly, not by relying on emulated mouse events.

A press SHALL place the reading, a drag SHALL scrub it continuously, and releasing SHALL retain the reading. Vertical page scrolling SHALL remain possible over a chart. The existing mouse path SHALL remain the only path taken by a mouse, so desktop interaction is unchanged.

#### Scenario: Scrubbing works with a finger
- **WHEN** the viewer presses a chart and drags horizontally without lifting
- **THEN** the reading follows the finger continuously and remains after the finger lifts

#### Scenario: The page still scrolls over a chart
- **WHEN** the viewer drags vertically starting on a chart
- **THEN** the page scrolls

#### Scenario: Mouse behaviour is untouched
- **WHEN** a mouse is used on any chart
- **THEN** hover, move, leave and click behave exactly as before this change

### Requirement: A reading is reachable regardless of point spacing
Placing a reading SHALL NOT require the viewer to hit a target narrower than the minimum touch size.

Where a chart's points are spaced more closely than that, the chart SHALL resolve a press to the nearest point rather than requiring a hit on a per-point band.

#### Scenario: Densely spaced points remain inspectable
- **WHEN** the viewer presses anywhere on a chart whose points are spaced under 12px apart at 390px
- **THEN** the nearest point is read

### Requirement: Placing a reading does not move the chart
Placing or clearing a reading SHALL NOT change the position of the chart the viewer is interacting with.

Space required to display a reading SHALL be reserved whether or not a reading is currently placed, and the reading SHALL be rendered where the viewer can see it without scrolling.

#### Scenario: The chart stays under the finger
- **WHEN** the viewer places a reading on any chart at 390px
- **THEN** the chart's position on the page is unchanged

#### Scenario: The reading is visible where it is placed
- **WHEN** the viewer places a reading on a chart at 390px, including on the lowest track of a stack
- **THEN** the reading is within the viewport

### Requirement: Annotation labels are placed by their extent
Annotation labels SHALL be laid out according to the space their text occupies, not the position of their anchor alone.

#### Scenario: Annotations do not overprint
- **WHEN** a chart carries several annotations whose anchors fall close together, at any width
- **THEN** no two labels overlap; labels that cannot be separated are grouped into one

### Requirement: A stack of tracks shows its shared axis
Where several tracks share one x scale, the axis SHALL be readable while any track is being inspected.

#### Scenario: The axis is readable while scrubbing
- **WHEN** the viewer scrubs a track at 390px in a stack taller than the viewport
- **THEN** the shared axis is visible without scrolling away from the track being scrubbed

### Requirement: A shared legend is stated once
Where several tracks share one set of series, the legend SHALL be rendered once for the stack rather than repeated per track.

#### Scenario: The legend does not repeat
- **WHEN** a multi-track stack sharing the same series is rendered at 390px
- **THEN** the legend appears exactly once
