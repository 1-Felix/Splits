## ADDED Requirements

### Requirement: Planned workouts expand to a structured detail view
Each day card in the "THIS WEEK" panel SHALL be expandable in place. When expanded, a run
workout SHALL present a structured breakdown — its target pace, target training zone, and
its segments (e.g. warm-up, reps with rest, cool-down) — rather than only a single prose
line. Non-run workouts SHALL show their title and any descriptive detail. Only one day
SHALL be expanded at a time, and expanding SHALL be operable by keyboard.

#### Scenario: Expanding a quality run shows its segments and pace
- **WHEN** the viewer activates a run day that carries structured segments (e.g. Friday's
  threshold session)
- **THEN** the card expands in place to show the target pace, the target zone, and each
  segment (warm-up, reps with their rest, cool-down)

#### Scenario: Expanding a second day collapses the first
- **WHEN** one day card is expanded and the viewer activates a different day card
- **THEN** the previously expanded day collapses and the newly activated day expands

#### Scenario: A non-run day expands without a pace breakdown
- **WHEN** the viewer activates a strength or cross-training day
- **THEN** the card expands to show its title and descriptive detail and does not show a
  running pace/segment breakdown

#### Scenario: Detail is keyboard operable
- **WHEN** a day card has focus and the viewer activates it via keyboard
- **THEN** the card toggles its expanded state, with `aria-expanded` reflecting the state

### Requirement: Target pace is a first-class, always-visible field
The dashboard SHALL surface a run workout's target pace as its own field, formatted
consistently, on the collapsed day card (not only inside the prose detail). When a target
zone is defined it SHALL be shown alongside the pace. Days without a defined target pace
(e.g. strength days) SHALL omit the pace indicator rather than show an empty or misleading value.

#### Scenario: Pace is visible without expanding the card
- **WHEN** a run day defines a target pace
- **THEN** the collapsed card displays that pace (and its zone when defined) as a distinct
  field, without requiring the viewer to expand the card

#### Scenario: Days without a target pace omit the indicator
- **WHEN** a day has no defined target pace (e.g. a strength session)
- **THEN** no pace field is shown for that day

### Requirement: Selecting a training-block week drives the THIS WEEK view
Clicking a week card in the "ROAD TO SONTHOFEN" panel SHALL retarget the "THIS WEEK" panel
to display that week's daily plan. The dashboard SHALL provide a fallback control that
returns the "THIS WEEK" view to the live current week. The selected week SHALL be visually
distinguished from the live current week so the two are not confused, and block week cards
SHALL be operable by keyboard.

#### Scenario: Selecting a future week retargets THIS WEEK
- **WHEN** the viewer activates a block week card other than the current week
- **THEN** the "THIS WEEK" panel displays that selected week's daily plan and the panel
  indicates which week is being shown

#### Scenario: Falling back to the current week
- **WHEN** a non-current week is being shown and the viewer activates the "back to current"
  control
- **THEN** the "THIS WEEK" panel returns to the live current week and the fallback control
  is no longer offered

#### Scenario: Current and selected weeks are visually distinct
- **WHEN** the viewer has selected a week that is not the live current week
- **THEN** the selected week and the live current week are shown with distinct visual states
  in the block panel

#### Scenario: Selection defaults to the live current week
- **WHEN** the dashboard loads and the viewer has not selected a week
- **THEN** the "THIS WEEK" panel shows the live current week, consistent with the
  date-driven current-week highlight

### Requirement: Weeks without a detailed plan show a graceful placeholder
When a training-block week has no detailed daily plan, selecting it SHALL show a placeholder
built from that week's summary (planned volume, long-run, and focus) rather than an empty
grid, and SHALL communicate that the detailed sessions are authored closer to the week.

#### Scenario: Selecting an un-detailed week shows its summary
- **WHEN** the viewer selects a block week that has no daily plan
- **THEN** the "THIS WEEK" panel shows a placeholder summarizing that week's planned volume,
  long run, and focus, and indicates the detail is not yet authored

#### Scenario: A detailed week shows its days, not the placeholder
- **WHEN** the viewer selects a block week that has a daily plan
- **THEN** the "THIS WEEK" panel shows that week's day cards and not the placeholder
