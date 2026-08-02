## ADDED Requirements

### Requirement: The run page leads with what the run was, not with the desktop source order
Below the phone breakpoint the run page's sections SHALL be ordered by what answers the run first.

Where a run has a detected structure, that structure SHALL be presented above the route trace and the best-efforts list, rather than inheriting the desktop grid's source order.

#### Scenario: Structure is not buried
- **WHEN** a run with a detected interval structure is opened at 390px
- **THEN** its rep detail appears above the route trace and the best-efforts list

#### Scenario: Nothing is dropped
- **WHEN** the run page is read at 390px
- **THEN** every section present at 1200px is present, reachable and complete

### Requirement: The rep table's comparisons survive phone width
A rep's deviation from its target SHALL remain readable at phone widths.

#### Scenario: The deviation is still legible
- **WHEN** a run with reps is read at 360px
- **THEN** each rep's deviation from target is conveyed by a mark large enough to read, or by its value, rather than collapsing to an indistinguishable sliver
