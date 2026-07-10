# live-dashboard Specification (delta)

## MODIFIED Requirements

### Requirement: Progress trends render as monthly charts
The dashboard SHALL render the efficiency (pace at reference HR) and cadence
(cadence at reference pace) monthly series as two charts built through the chart
engine, carrying labelled axes, the domain policy declared for each metric, and a
rolling-median reference band. Null months SHALL render as gaps, not as zero or
interpolated points. Each point's `inBandMin` sample weight SHALL be encoded in
its mark, with points beneath the declared floor rendering hollow and excluded
from the line.

#### Scenario: Trends render with honest gaps
- **WHEN** `insights.efficiency.monthly` contains null months between valid
  points
- **THEN** the chart shows a visible gap for those months and continuous lines
  only across consecutive valid points

#### Scenario: Hovering reveals the numbers
- **WHEN** the user hovers (or focuses) a month with a valid point
- **THEN** the month and its value (pace or cadence) are shown, consistent
  with the existing chart hover behavior

#### Scenario: The numbers are legible without hovering
- **WHEN** either trend chart renders
- **THEN** its y axis shows tick labels in pace or cadence units and its x axis
  shows month labels

#### Scenario: Confidence is visible
- **WHEN** two months carry `inBandMin` values of 21 and 338
- **THEN** their marks differ in size, and the reader can see which point rests
  on more evidence

## ADDED Requirements

### Requirement: The cockpit charts the race trajectory
The cockpit SHALL render `insights.trajectory` as a chart: the demonstrated
(Riegel) half-marathon projection and the model prediction over time, the goal
time as a reference rule, and the gap between the two series made visible. Its
domain SHALL always contain the goal. The chart SHALL answer "is the gap
closing?" without interaction.

#### Scenario: The trajectory is a chart, not a sentence
- **WHEN** the cockpit renders with `insights.trajectory` present
- **THEN** a chart shows both projections over time against the goal rule, with
  labelled axes

#### Scenario: The goal is always in frame
- **WHEN** every projection is far slower than the goal
- **THEN** the goal rule is still within the plotted domain

#### Scenario: Absent trajectory degrades quietly
- **WHEN** the data file carries no `insights.trajectory`
- **THEN** the cockpit renders without the chart, with no error and no layout
  breakage

### Requirement: Charts state their scale honestly
No chart SHALL scale its y domain to the data's extent alone. Each chart SHALL
declare a domain policy — minimum span, zero-anchor, or forced goal inclusion —
so the rendered amplitude of a change corresponds to its magnitude. Area fills
SHALL be used only where the filled quantity is meaningful (volume, load), and
SHALL NOT be drawn beneath rate or level metrics such as pace, cadence, VO₂ max,
HRV, or predicted time.

#### Scenario: A small VO₂ change looks small
- **WHEN** VO₂ max varies by 3.6 points across the plotted range
- **THEN** the resolved domain spans at least the metric's declared minimum and
  the series does not sweep the full plot height

#### Scenario: Pace carries no area fill
- **WHEN** the average-pace chart renders
- **THEN** the region beneath the pace line is unfilled

### Requirement: Sleep and heart-rate variability are separate charts
Sleep duration and heart-rate variability SHALL NOT share one plotting frame.
Each SHALL render as its own chart with its own labelled axis; the HRV chart
SHALL draw the personal baseline band that makes a nightly reading interpretable.

#### Scenario: Two measures, two frames
- **WHEN** the sleep and HRV surfaces render
- **THEN** each occupies its own chart with its own y axis, and neither shares a
  frame with a second scale

#### Scenario: A nightly HRV reading is interpretable
- **WHEN** the HRV chart renders
- **THEN** the personal baseline band renders behind the series, and a night
  outside the band is visibly outside it
