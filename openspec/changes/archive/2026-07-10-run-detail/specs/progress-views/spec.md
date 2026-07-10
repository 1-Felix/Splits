# progress-views Specification (delta)

## MODIFIED Requirements

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

#### Scenario: A record with no linked activity is not a link
- **WHEN** a record on the wall carries no activity id
- **THEN** it renders as plain text and is not activatable
