# archive-browser Specification

## Purpose
The archive's own page: `/archive` lists every archived activity newest-first
over the read-only list endpoint, filterable by type, year, and name — with
the filters mirrored into the URL so a filtered view is a link — and degrades
to an honest offline state when the archive is away. Run rows lead to
`/run/:id`; everything else is a plain row.

## Requirements

### Requirement: An archive page exists at /archive in the shared shell

The dashboard SHALL serve an archive browser page at `/archive` as its own
component page, carrying the shared topbar (navigation with Archive marked
current, theme picker, sync pill) and the persisted theme, and reflowing
responsively at the established breakpoints. The topbar's navigation on every
page SHALL include the Archive entry via the shared topbar module, without
changes to existing pages beyond that module.

#### Scenario: The page serves and matches the shell
- **WHEN** a viewer navigates to `/archive`
- **THEN** the page renders with the shared topbar, the viewer's persisted
  theme, and the navigation marking Archive as the current page

#### Scenario: Archive is reachable from other pages
- **WHEN** the viewer opens the cockpit or the progress page
- **THEN** the topbar navigation offers the Archive entry

#### Scenario: The page reflows at the standard breakpoints
- **WHEN** the page renders at 1200, 768, and 390 px widths
- **THEN** the layout reflows with no horizontal overflow

### Requirement: The browser lists archived activities newest-first with honest pagination

The archive page SHALL list archived activities from the read-only list
endpoint, newest-first, each row built from promoted summary fields alone
(date, name, type, distance, duration, average HR — with a pace column
presented as duration ÷ distance over those fields). No domain value SHALL be
recomputed client-side. The page SHALL state how many of the
total matching activities are shown and SHALL offer a load-more control that
appends the next page while the endpoint reports more rows, never re-fetching
or reordering rows already shown.

#### Scenario: First page renders with its count
- **WHEN** the archive page loads and the archive holds more activities than
  one page
- **THEN** the first page of rows renders newest-first with a visible
  "shown of total" count and a load-more control

#### Scenario: Load more appends
- **WHEN** the viewer activates load-more
- **THEN** the next page's rows append below the existing rows and the count
  updates; when no more rows exist the control is no longer offered

### Requirement: The browser filters by type, year, and name — mirrored in the URL

The archive page SHALL offer filters for activity type, calendar year, and a
name search, combining as AND and driving the list endpoint's corresponding
parameters. Active filters SHALL be reflected in the page's query string so a
filtered view survives reload and back navigation, and changing any filter
SHALL reset pagination. A filter combination matching nothing SHALL render an
explicit empty state, never a blank or broken list.

#### Scenario: Filtering to a year of runs
- **WHEN** the viewer selects the running type and a year
- **THEN** the list shows only that year's runs, newest-first, and the page's
  URL reflects both filters

#### Scenario: Searching by name
- **WHEN** the viewer types a name fragment into the search field
- **THEN** the list narrows to activities whose names contain the fragment,
  combined with any active type/year filter

#### Scenario: A filtered view survives reload
- **WHEN** the viewer reloads a URL carrying filter parameters
- **THEN** the page restores those filters in its controls and renders the
  matching rows

#### Scenario: Nothing matches
- **WHEN** the active filters match no archived activity
- **THEN** the page renders an explicit "no matches" state and the filters
  remain usable

### Requirement: Run rows navigate to the run's page; other rows are not interactive

Rows for running activities SHALL navigate to that run's `/run/<activityId>`
page when activated. Rows for non-run activities SHALL render as plain,
non-interactive rows — no focusable controls that do nothing.

#### Scenario: Opening an archived run
- **WHEN** the viewer activates a run row
- **THEN** the browser navigates to that run's page

#### Scenario: A strength session is a plain row
- **WHEN** the list shows a non-run activity
- **THEN** its row is not focusable as a control and activating it does
  nothing

### Requirement: The archive page degrades honestly when the archive is unreachable

The archive page SHALL render its chrome with an honest "archive offline"
state in place of the list whenever the archive API is unavailable, and MUST
NOT render a broken or blank page — it is a deep view and depends on the API
only for its list. Recovery SHALL NOT require a full reload if the viewer
retries a filter or load action after the archive returns.

#### Scenario: Archive API down at load
- **WHEN** the archive page loads while the list endpoint returns 503
- **THEN** the topbar and page chrome render and an archive-offline state
  appears where the list would be

#### Scenario: Archive API fails mid-session
- **WHEN** a load-more or filter request returns 503 after rows are already
  shown
- **THEN** the shown rows remain and the failure is reported honestly, without
  clearing the list
