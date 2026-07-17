# progress-views Specification

## Purpose
The long-game page of the dashboard: `/progress` renders the records wall, year-over-year comparison, and the relocated trend sections static-first, with archive-API drill-downs as the only network-dependent interaction.

## Requirements

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
Each record on the wall SHALL link to the run it was set in. Activating a record
SHALL navigate to that run's page (`/run/<activityId>`), where the run's streams,
splits, records, and plan comparison are presented in full. The inline
drill-down presentation is retired from the records wall.

#### Scenario: Opening a record's run
- **WHEN** the viewer activates a record whose run is only in the archive (not
  among the recent runs)
- **THEN** the browser navigates to that run's page and the run detail renders

#### Scenario: Click-through degrades honestly when the archive is offline
- **WHEN** the viewer activates a record while the archive API returns 503
- **THEN** the run page renders its chrome with an "archive offline" indication,
  and the progress page they left remains functional on return

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
the archive API SHALL be required only for drill-down interactions — record
click-throughs and chart evidence panels. API unavailability MUST NOT blank
any statically-renderable content.

#### Scenario: Full render with the API down
- **WHEN** the progress page loads while archive endpoints return 503
- **THEN** the records wall, year-over-year view, and all relocated sections
  render fully; only drill-down interactions surface the offline state

#### Scenario: A drill against a down API degrades inside its panel
- **WHEN** the viewer drills a chart point while archive endpoints return 503
- **THEN** the panel shows the honest offline state with a retry, and every
  chart and section of the page remains fully usable

### Requirement: Progress charts offer scope controls where the data supports them
Each trend chart on the progress page SHALL offer a scope control that
re-derives its domain over the selected tail of its series, so a deviation
invisible across the full range becomes visible across a shorter one. A scope
option SHALL be offered only where the underlying series carries enough points to
honour it, and each chart SHALL state its actual span alongside its title.

#### Scenario: Narrowing the scope resolves a deviation
- **WHEN** the user selects a six-month scope on a thirty-month series
- **THEN** the chart re-derives its domain and its axes over the last six months
  only, and the subtitle states that span

#### Scenario: A chip is never offered beyond the data
- **WHEN** a series carries fewer points than a scope option requires
- **THEN** that option is not offered, and no chart implies a range it cannot
  render

### Requirement: Year-over-year bars share one domain
The year-over-year comparison SHALL plot every year against a single shared y
domain anchored at zero, so bar heights are comparable across years.

#### Scenario: Years are visually comparable
- **WHEN** the year-over-year chart renders three years of monthly volume
- **THEN** all years share one zero-anchored y domain, and a month's bar height
  is comparable to the same month in another year

### Requirement: Timeline charts carry annotations
Where a chart plots a timeline, it SHALL mark the events already present in the
data file — race day, and the dates on which records fell (`insights.recordsFeed`)
— as annotations that name what happened. Annotation flags SHALL be placed
without overlapping one another.

#### Scenario: A record is marked where it fell
- **WHEN** a timeline chart spans a date in `insights.recordsFeed`
- **THEN** an annotation marks that date and names the distance whose record fell

#### Scenario: Crowded annotations do not collide
- **WHEN** several annotations fall close together on the x axis
- **THEN** they are placed in separate lanes and remain individually legible

### Requirement: Aggregate progress charts drill to their evidence
The progress page's pooled monthly charts SHALL drill to the contribution
panel defined by the chart-drill capability — pace at reference HR and
cadence at reference pace — fed by the archive run-metrics endpoint for the
pinned month. The year-over-year monthly bars SHALL drill to the same panel
shell listing every run of the pinned month (fed by the existing listing
endpoint's date-range filter), without a didn't-count section — volume counts
every run. Panels SHALL render beneath their chart, one open at a time, with
focus moving into the panel on open and returning to the chart on close.

#### Scenario: A pooled month drills to its contribution split
- **WHEN** the viewer drills a pinned month on the pace-at-reference-HR chart
- **THEN** a panel opens beneath the chart showing that month's contributing
  runs (in-band minutes, per-run in-band pace, share) and its didn't-count
  disclosure, each run linking to its `/run/<activityId>` page

#### Scenario: A YoY month drills to all of its runs
- **WHEN** the viewer drills a pinned month on the year-over-year bars
- **THEN** the panel lists every running activity of that month and year with
  date, name, and distance — no didn't-count section — each linking to its run
  page

#### Scenario: Focus is managed across open and close
- **WHEN** the viewer drills a point via keyboard and then presses Escape
- **THEN** focus moves into the panel on open and returns to the chart with
  the pin intact on close

### Requirement: /progress hosts The Block section static-first
The `/progress` page SHALL include the "The Block" section (defined in the
`block-lens` capability) rendered static-first from `blockLens` in
`garmin-data.js`, with the archive API used only for past-block drill and the
block comparison's full documents. Absence of `blockLens` SHALL leave the rest
of `/progress` unaffected.

#### Scenario: Section present with a current block
- **WHEN** `/progress` loads and `blockLens.current` exists
- **THEN** The Block section renders between page load and any network activity, from static data alone

#### Scenario: Section absent without a lens
- **WHEN** `garmin-data.js` has no `blockLens`
- **THEN** `/progress` renders its existing sections with no Block section and no errors
