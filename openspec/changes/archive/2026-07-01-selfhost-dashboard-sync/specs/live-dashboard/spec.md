## ADDED Requirements

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
