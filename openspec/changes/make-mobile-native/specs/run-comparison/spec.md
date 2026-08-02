## ADDED Requirements

### Requirement: Compared runs remain identifiable at every width
Every run in a comparison SHALL remain distinguishable from the others at every supported width.

A run's identity SHALL NOT be reduced to a truncation that cannot be told apart from another run's, and its measures SHALL NOT collide with a neighbouring run's.

#### Scenario: Runs can be told apart
- **WHEN** four runs are compared at 360px and 390px
- **THEN** each run is identifiable by name or date, and no two runs' values overlap

#### Scenario: Split bars stay meaningful
- **WHEN** four runs are compared at 390px
- **THEN** each per-kilometre bar retains enough width to convey its relative length

### Requirement: The comparison is composed per run at phone widths
Below the phone breakpoint the comparison SHALL be composed as one unit per run rather than as an N-column table.

Every measure the desktop comparison shows SHALL be present, including the best-per-measure marking.

#### Scenario: Content parity in the phone composition
- **WHEN** the comparison is read at 390px
- **THEN** every summary measure, every per-kilometre split and every best-per-measure mark present at 1200px is also present

### Requirement: The comparison offers a way back
The comparison page SHALL offer navigation to the rest of the application.

#### Scenario: Not a dead end
- **WHEN** the comparison is opened directly from a shared link at 390px
- **THEN** navigation to the other pages is available without using the browser's back control
