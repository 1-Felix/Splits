## ADDED Requirements

### Requirement: An archived activity is one bounded, unambiguous target
Each row in the archive list SHALL render as a visually bounded record whose primary activation area is the whole row.

Selecting a row for comparison SHALL be a separate control that does not overlap the row's identifying text, and missing it SHALL NOT navigate.

#### Scenario: Rows are records, not run-together text
- **WHEN** the archive list is rendered at 360px and 390px
- **THEN** each activity is a bounded unit carrying its date, name, type and measures, and no row's controls overlap its text

#### Scenario: Selecting does not navigate
- **WHEN** the viewer activates a row's comparison control
- **THEN** the row's selection state toggles and no navigation occurs

#### Scenario: Absent measures are omitted
- **WHEN** an activity carries no pace or heart rate
- **THEN** those measures are omitted from the row rather than rendered as placeholder marks

### Requirement: Returning from a run restores the browser's state
Navigating from the archive to a run and back SHALL restore the pages already loaded, the scroll position, and the comparison selection.

#### Scenario: Place is not lost
- **WHEN** the viewer loads further pages, scrolls, selects two runs, opens one, and returns
- **THEN** the same pages are loaded, the scroll position is restored, and both selections are still made

### Requirement: The comparison control states honestly whether it can act
The control that opens a comparison SHALL indicate whether it is currently able to act, and SHALL explain any limit it enforces without breaking its own layout.

#### Scenario: An unusable action says so
- **WHEN** fewer than two runs are selected
- **THEN** the comparison control is presented as unavailable rather than appearing available and doing nothing

#### Scenario: The limit is explained in place
- **WHEN** the viewer selects more runs than a comparison accepts
- **THEN** the tray explains the limit while remaining legible and correctly positioned at 360px
