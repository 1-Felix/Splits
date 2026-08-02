## ADDED Requirements

### Requirement: The course surface is inspectable by touch
The elevation profile and the pace plan SHALL be inspectable on a touch device.

Pressing the profile SHALL place a reading and dragging SHALL scrub it, and the reading SHALL identify the point on the course it refers to.

#### Scenario: The profile scrubs with a finger
- **WHEN** the viewer presses the elevation profile at 390px and drags along it
- **THEN** the reading follows the finger and names the distance, elevation and grade at that point

#### Scenario: Decisive segments are activatable
- **WHEN** the viewer activates a decisive segment at 390px
- **THEN** that segment's detail is presented, rather than the segment being an inert mark

### Requirement: The pace plan keeps its headers in view
A pace-plan table longer than the viewport SHALL keep its column meanings available while it is being read.

#### Scenario: Rows are not read blind
- **WHEN** the viewer scrolls to the middle of the pace plan at 390px
- **THEN** each value's meaning is still identifiable, through a persistent header or through per-row labelling
