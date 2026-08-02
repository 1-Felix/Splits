## MODIFIED Requirements

### Requirement: A pinned reading drills down to its evidence
Charts whose points summarize runs SHALL offer a drill-down as the second
activation of the existing pin interaction: activating an already-pinned
reading (clicking its card, tapping its affordance, or pressing Enter on the
pinned point) SHALL invoke the chart's declared drill, and Escape SHALL walk
back one step at a time (evidence view → pinned reading → nothing). The
affordance SHALL be visible on the pinned card before it is invoked, naming
what the drill opens. The drill SHALL be operable entirely by keyboard, and
SHALL be reachable by touch: on a touch device the affordance SHALL be a
target meeting the minimum touch size whose activation invokes the drill
directly, rather than depending on a second activation surviving a re-render.
Charts that declare no drill SHALL behave exactly as before.

#### Scenario: Drilling via keyboard only
- **WHEN** the user focuses a drillable chart, pins a point with Enter, and
  presses Enter again
- **THEN** the point's evidence view opens, and pressing Escape returns to the
  pinned reading with focus back on the chart, and a second Escape dismisses
  the pin

#### Scenario: Drilling by touch
- **WHEN** the user taps a point on a drillable chart to pin it, then taps the
  drill affordance on the pinned reading
- **THEN** the point's evidence view opens, exactly as it does for a mouse at
  the same viewport width

#### Scenario: The affordance announces itself before acting
- **WHEN** a point on a drillable chart is pinned
- **THEN** the pinned card shows a drill affordance naming its target (e.g.
  "view evidence", "view anchor run") and no navigation or fetch has happened
  yet

#### Scenario: A chart without a drill is unchanged
- **WHEN** the user pins a point on a chart that declares no drill and presses
  Enter again
- **THEN** the pin behaves exactly as before this change and no drill
  affordance is rendered

## ADDED Requirements

### Requirement: The evidence view opens where it can be read
The drill's evidence view SHALL open within the viewport, positioned so its heading is visible without further scrolling.

Below the phone breakpoint the evidence view SHALL be presented as a bottom sheet, retaining its identity, its focus behaviour and its dismissal contract.

#### Scenario: The evidence view is not opened below the fold
- **WHEN** the viewer drills a point at 390px
- **THEN** the evidence view's heading is within the viewport and focus lands on it

#### Scenario: The dismissal contract is preserved
- **WHEN** the evidence view is open as a sheet and the viewer presses Escape twice
- **THEN** the first press closes the evidence view and returns to the pinned reading, and the second dismisses the pin
