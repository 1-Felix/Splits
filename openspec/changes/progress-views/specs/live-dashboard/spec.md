# live-dashboard Specification (delta)

## ADDED Requirements

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
