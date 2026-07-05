# progress-views Specification

## ADDED Requirements

### Requirement: A dedicated progress page exists at /progress
The dashboard SHALL serve a progress page at `/progress` as its own component
page, carrying the shared topbar (navigation, theme picker, sync pill) and the
active theme, and reflowing responsively at the established breakpoints
(desktop / tablet / phone).

#### Scenario: The page serves and matches the shell
- **WHEN** a viewer navigates to `/progress`
- **THEN** the page renders with the shared topbar, the viewer's persisted
  theme, and the navigation marking Progress as the current page

#### Scenario: The page reflows at the standard breakpoints
- **WHEN** the page renders at 1200, 768, and 390 px widths
- **THEN** the layout reflows per the responsive rules with no horizontal
  overflow

### Requirement: Records wall renders all-time, last-90-days, and by-year best efforts
The progress page SHALL render a records wall from the static `insights`
block: best efforts (1 km, 1 mile, 5 km, 10 km, half-marathon) for all-time,
the last 90 days, and each calendar year, each record showing its time and
date. The wall SHALL render entirely from static data — no API request is
required to display it.

#### Scenario: The wall renders without the archive API
- **WHEN** the progress page loads while the archive API is unavailable
- **THEN** the records wall renders fully from the `insights` block

#### Scenario: Distances without a qualifying effort stay honest
- **WHEN** a year or window has no qualifying effort at a distance
- **THEN** that cell renders an explicit empty state, never a fabricated or
  extrapolated time

### Requirement: Records click through to the run they fell in
Each record on the wall SHALL link to the run it was set in. Activating a
record SHALL fetch that activity from the archive API and present its
drill-down (coach-read line, splits, HR) using the established recent-run
drill-down presentation.

#### Scenario: Opening a record's run
- **WHEN** the viewer activates a record whose run is only in the archive (not
  among the recent runs)
- **THEN** the run's drill-down renders from the archive API's distilled
  detail, matching the recent-run drill-down presentation

#### Scenario: Click-through degrades honestly when the archive is offline
- **WHEN** the viewer activates a record while the archive API returns 503
- **THEN** the page shows an "archive offline" indication for the drill-down
  and the rest of the page remains functional

### Requirement: Year-over-year comparison renders per-year monthly aggregates
The progress page SHALL render a year-over-year view from `insights.yoy`
comparing calendar years side by side on monthly distance, run count, and
average pace. Months without runs SHALL render as gaps or zeros per their
meaning (no runs = zero distance, no pace), and the current year SHALL show
only elapsed months.

#### Scenario: Years compare side by side
- **WHEN** the data file carries `insights.yoy` with multiple years
- **THEN** the view renders each year's monthly series in one comparable
  visualization, hover/focus revealing month values per the existing chart
  interaction pattern

#### Scenario: The current partial year stays honest
- **WHEN** the current year has months that have not yet occurred
- **THEN** those months render as not-yet rather than as zero-performance

### Requirement: The relocated long-game sections render on the progress page
The progress page SHALL render the sections moved off the cockpit — weekly
volume; the monthly chart grid of VO₂ max, average pace, fitness/fatigue,
cadence, pace at reference HR, and cadence at reference pace; and the records
feed — with their established behavior preserved: chart hover/crosshair
interaction, keyboard navigation, and graceful absence when their data keys
are missing.

#### Scenario: Moved sections keep their behavior
- **WHEN** the progress page renders with a full data file
- **THEN** the relocated sections render with working hover cards and keyboard
  chart navigation, as they did on the single-page dashboard

#### Scenario: Missing insight data degrades as before
- **WHEN** the data file has no `insights` block
- **THEN** the insight-fed sections render nothing, without errors or layout
  breakage, and the remaining sections render normally

### Requirement: The progress page is static-first
The progress page SHALL render all of its views from static data files alone;
the archive API SHALL be required only for record click-through drill-downs.
API unavailability MUST NOT blank any statically-renderable content.

#### Scenario: Full render with the API down
- **WHEN** the progress page loads while archive endpoints return 503
- **THEN** the records wall, year-over-year view, and all relocated sections
  render fully; only drill-down interactions surface the offline state
