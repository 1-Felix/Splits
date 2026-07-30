## ADDED Requirements

### Requirement: The rep card pairs each recovery to its rep by time

The rep card SHALL pair a recovery line to a rep by temporal adjacency: the
recovery shown under rep *i* is the first `recovery`-role segment whose start
falls at or after rep *i*'s end and (when a later rep exists) before the next
rep's start. When no recovery matches, the rep SHALL show no recovery line.
Pairing MUST NOT rely on array position, because a mid-set demotion inserts a
`recovery`-role segment that shifts every later position.

#### Scenario: Mid-set demotion does not shift later pairings

- **WHEN** a set contains a demoted mid-set segment (role `recovery`) between two
  reps
- **THEN** every rep after the demotion still shows the recovery that actually
  followed it in time

#### Scenario: A rep with no following recovery shows none

- **WHEN** the final rep of a set is followed by no `recovery`-role segment
  before the cooldown
- **THEN** that rep renders without a recovery line rather than borrowing an
  earlier one

### Requirement: Absent grade-adjusted pace renders as absent, by presence not truthiness

A segment's grade-adjusted pace SHALL be rendered as an em dash exactly when the
value is absent (`null`), and as a formatted pace for every numeric value. The
engine SHALL emit `null` (never `0`) for a grade-adjusted pace it cannot compute,
so no numeric sentinel can be confused with a real pace.

#### Scenario: Missing GAP renders as an em dash

- **WHEN** a segment carries `gapS: null`
- **THEN** the rep card renders an em dash in the GAP position

#### Scenario: Invalid speed produces null, not zero

- **WHEN** the engine derives grade-adjusted pace from a non-positive speed value
- **THEN** the document carries `gapS: null` for that segment
