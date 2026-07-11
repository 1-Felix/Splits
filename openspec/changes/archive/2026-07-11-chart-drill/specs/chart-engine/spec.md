# chart-engine Delta

## ADDED Requirements

### Requirement: The pinned reading carries a declared drill affordance
The engine SHALL let a chart declare a drill descriptor — a per-point label
and action — and SHALL render, on the pinned reading's card, a visible
affordance carrying that label. Activating the pinned reading again (clicking
the card or pressing Enter on the pinned point) SHALL invoke the declared
action for that point; Escape SHALL return from the drilled state to the
pinned reading before dismissing the pin. The affordance and its keyboard path
SHALL be provided by the engine so no opted-in chart can omit them, and the
accessible label SHALL announce the drill target. The engine SHALL NOT fetch
data or navigate itself — the action is the chart's. Points whose descriptor
yields no action SHALL render no affordance, and charts declaring no
descriptor SHALL keep today's pin behavior exactly.

#### Scenario: The affordance renders from the declaration
- **WHEN** a chart declaring a drill descriptor has a point pinned
- **THEN** the card shows the descriptor's label for that point and the
  chart's accessible reading announces the available drill

#### Scenario: Enter drills, Escape walks back
- **WHEN** the user pins a point with Enter on an opted-in chart, presses
  Enter again, and then presses Escape
- **THEN** the first Enter pins, the second invokes the point's drill action,
  and Escape returns to the pinned reading rather than dismissing everything
  at once

#### Scenario: A point without an action is inert
- **WHEN** a drill descriptor returns no action for a null point
- **THEN** that point's pinned card shows no affordance and repeated Enter
  presses do not invoke anything

#### Scenario: Non-drill charts are untouched
- **WHEN** a chart without a descriptor renders and its points are pinned via
  mouse and keyboard
- **THEN** its pin, card, and Escape behavior are identical to before this
  change
