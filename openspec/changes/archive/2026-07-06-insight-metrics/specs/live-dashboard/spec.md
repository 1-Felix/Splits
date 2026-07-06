# live-dashboard Specification (delta)

## ADDED Requirements

### Requirement: Race-prediction card shows the honest trajectory
The dashboard SHALL extend the race-prediction card with the trajectory
verdict — the trend direction and rate from `predictions.trend` — and the
current gap between the Riegel projection and Garmin's prediction, so the
"is the gap closing?" answer is visible without leaving the page.

#### Scenario: Trend and gap are visible
- **WHEN** the data file carries `insights.trajectory` and a non-empty
  `predictions.trend`
- **THEN** the prediction card shows the trend verdict (direction and rate)
  and the current Riegel-vs-Garmin gap alongside the existing predicted times

### Requirement: Recent records are surfaced as a feed
The dashboard SHALL render the records feed from `insights.recordsFeed` as a
compact, humanized list (distance, new time, previous time, date), newest
first.

#### Scenario: A fallen record is announced
- **WHEN** `insights.recordsFeed` contains an entry for the 5k
- **THEN** the feed shows a humanized line naming the distance, the new time,
  the previous best, and when it fell

#### Scenario: A quiet period has a calm empty state
- **WHEN** `insights.recordsFeed` is an empty array
- **THEN** the feed area renders a neutral empty state and no error or broken
  layout

### Requirement: Progress trends render as monthly charts
The dashboard SHALL render the efficiency (pace at reference HR) and cadence
(cadence at reference pace) monthly series as two compact charts consistent
with the page's existing chart and hover interaction patterns. Null months
SHALL render as gaps, not as zero or interpolated points.

#### Scenario: Trends render with honest gaps
- **WHEN** `insights.efficiency.monthly` contains null months between valid
  points
- **THEN** the chart shows a visible gap for those months and continuous lines
  only across consecutive valid points

#### Scenario: Hovering reveals the numbers
- **WHEN** the user hovers (or focuses) a month with a valid point
- **THEN** the month and its value (pace or cadence) are shown, consistent
  with the existing chart hover behavior

### Requirement: Insight surfaces degrade gracefully when absent
All insight surfaces SHALL render nothing — with no errors and no layout
breakage — when the `insights` block is missing from the data file, keeping
the dashboard fully functional against pre-engine data.

#### Scenario: Pre-engine data file
- **WHEN** the dashboard loads a `garmin-data.js` without an `insights` block
- **THEN** the prediction card, records feed, and progress charts sections
  show none of the new surfaces and the rest of the page behaves exactly as
  before this change
