# plan-sync Specification (delta)

## ADDED Requirements

### Requirement: The race may name its course
Plan validation SHALL accept an optional `courseId` on `planData.race`, SHALL
reject a value that is not a positive integer, and SHALL treat its absence as
valid. A plan carrying a malformed `courseId` SHALL fail validation before it
can be written, so a coaching edit can never publish a plan the course engine
cannot read.

#### Scenario: A race without a course stays valid
- **WHEN** a plan whose race carries no `courseId` is validated
- **THEN** validation passes

#### Scenario: A malformed course id is rejected before writing
- **WHEN** a plan carries a `courseId` that is not a positive integer
- **THEN** validation fails and the live plan is left untouched
