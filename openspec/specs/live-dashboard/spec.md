# live-dashboard Specification

## Purpose
TBD - created by archiving change selfhost-dashboard-sync. Update Purpose after archive.
## Requirements
### Requirement: Date-driven views follow the live clock
The dashboard SHALL compute a live "display-today" from the viewer's current local date and use it to drive the race countdown, the week plan's current-day highlight, and the training-block current-week highlight — rather than the date baked into telemetry at sync time.

#### Scenario: Countdown reflects the real date, not the last sync
- **WHEN** the dashboard is opened on a date later than the last sync date
- **THEN** the race countdown is computed from the current local date and shows the correct number of days remaining

#### Scenario: Current day highlights without a manual edit
- **WHEN** the local date matches one of the week plan rows' dates
- **THEN** that row is highlighted as "today" derived from its date, with no hand-edited `status` required

#### Scenario: Current training-block week highlights by date
- **WHEN** the local date falls within a block week's Monday–Sunday range
- **THEN** that block week is marked current and earlier weeks are marked past, based on the live date

### Requirement: Time-of-day greeting
The dashboard SHALL display a greeting that reflects the viewer's local time of day (e.g., morning/afternoon/evening).

#### Scenario: Greeting matches the local time
- **WHEN** the dashboard renders at a given local time of day
- **THEN** the greeting corresponds to that part of the day

### Requirement: Telemetry stays anchored to the last sync with a freshness indicator
Telemetry-bound views (the activity heatmap and recent runs) SHALL remain anchored to the last sync date rather than the live clock, and the dashboard SHALL display when the data was last synced. When the live date has advanced beyond the last sync, the dashboard SHALL indicate that the telemetry is stale.

#### Scenario: Heatmap edge and sync caption
- **WHEN** the dashboard renders telemetry
- **THEN** the heatmap and recent runs reflect the last sync, and a "synced · <date>" caption is shown

#### Scenario: Staleness is surfaced
- **WHEN** the live date is later than the last sync date
- **THEN** the dashboard shows a staleness indication prompting a re-sync

### Requirement: Midnight rollover for an open page
When the dashboard is left open across a date boundary, it SHALL update its date-driven views to the new date without requiring a manual reload.

#### Scenario: Day boundary crossed while open
- **WHEN** the local date changes while the dashboard remains open
- **THEN** the countdown, current-day highlight, and block highlight update to the new date

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

### Requirement: Days carry compliance marks
The dashboard SHALL mark each day that has a compliance row — in THIS WEEK and
in any selected block week — with its status (done / partial / missed /
swapped / unplanned / pending), visually distinguishable at a glance and
consistent with the page's existing chip and color language. A `partial` mark
SHALL expose its reason (distance or intensity) on the day's detail.

#### Scenario: A completed day is visibly done
- **WHEN** the data file's `compliance.days` marks a rendered date `done`
- **THEN** that day's card carries the done mark

#### Scenario: A partial day explains itself
- **WHEN** a rendered date is marked `partial` with reason `intensity`
- **THEN** the day shows the partial mark and its detail view names intensity
  as the reason

### Requirement: Block week rows show plan-vs-actual aggregates
The dashboard SHALL show, on each block week row that has compliance data, the
week's actual running volume against its planned km and the sessions completed
against sessions planned, without disturbing the existing row layout for weeks
that have no compliance data.

#### Scenario: A closed week reads at a glance
- **WHEN** `compliance.weeks` carries a closed week with 32.4 actual of 32
  planned km and 4 of 4 runs done
- **THEN** that week's row shows the volume and session aggregates

### Requirement: Compliance surfaces degrade gracefully when absent
All compliance surfaces SHALL render nothing — no errors, no layout breakage,
no placeholder noise — when the `compliance` block is missing from the data
file, keeping the dashboard fully functional against pre-coach-loop data.

#### Scenario: Pre-coach-loop data file
- **WHEN** the dashboard loads a `garmin-data.js` without a `compliance` block
- **THEN** day cards and week rows render exactly as before this change

### Requirement: The dashboard is a multi-page shell with a shared topbar
The dashboard SHALL be served as multiple pages behind clean routes — the
cockpit at `/` and the progress page at `/progress` — each page carrying the
shared topbar: navigation with the current page marked, the theme picker, the
sync pill, and the greeting. Topbar behavior SHALL be implemented once in a
shared module; adding a page SHALL NOT require changes to existing pages.
The previous entry URL SHALL continue to serve the cockpit.

#### Scenario: Navigating between pages
- **WHEN** the viewer activates the Progress link in the cockpit's topbar
- **THEN** the progress page loads with the same topbar, and its navigation
  marks Progress as current

#### Scenario: The old entry URL keeps working
- **WHEN** a client requests the original dashboard file path
- **THEN** the cockpit is served as before

#### Scenario: Sync pill works from any page
- **WHEN** the viewer triggers a sync from the progress page's topbar
- **THEN** the sync starts and the pill reflects its state, identical to
  cockpit behavior

### Requirement: The chosen theme persists across pages and reloads
The viewer's theme choice SHALL persist in browser storage and apply on every
page from first paint. A viewer who has never chosen a theme SHALL get the
default theme.

#### Scenario: Theme survives navigation
- **WHEN** the viewer picks a theme on the cockpit and navigates to `/progress`
- **THEN** the progress page renders in the chosen theme with no flash of the
  default theme

#### Scenario: Theme survives a reload
- **WHEN** the viewer reloads any page after picking a theme
- **THEN** the page renders in the chosen theme

### Requirement: The cockpit renders complete without any API
The cockpit page SHALL render its full content from static files alone. No
cockpit surface SHALL require an API response to display; API-dependent
surfaces belong to non-cockpit pages. (The sync pill enriches with `/api/status`
but the page SHALL be complete without it.)

#### Scenario: Cockpit under total API failure
- **WHEN** every `/api/*` route fails while static files serve
- **THEN** the cockpit renders all of its sections with correct data from the
  static files

### Requirement: The cockpit is scoped to now
The cockpit SHALL comprise the today/this-week/this-block surfaces — hero
(race, readiness, coach), KPI tiles, THIS WEEK, the training-block panel, the
activity heatmap, and recent activities with drill-down — and SHALL NOT carry
the long-game surfaces (weekly volume; the monthly chart grid: VO₂ max,
average pace, fitness/fatigue, cadence, pace at reference HR, cadence at
reference pace; the records feed), which render on the progress page instead.

#### Scenario: Long-game sections are on the progress page, not the cockpit
- **WHEN** the cockpit renders
- **THEN** it contains no weekly-volume, monthly-chart-grid, or records-feed
  sections, and those sections render on `/progress`

#### Scenario: Everything the cockpit keeps behaves as before
- **WHEN** the cockpit renders after the diet
- **THEN** the retained sections (including the heatmap and recent-run
  drill-downs) render and interact exactly as before the split

