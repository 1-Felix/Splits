# live-dashboard Specification (delta)

## ADDED Requirements

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
