# lens-confidence Specification (delta)

## ADDED Requirements

### Requirement: Device-sourced confidence is derived, never constant
A lap-sourced interval document SHALL compute its confidence from the evidence
that produced its shape. The system SHALL NOT assign a fixed confidence to
device-sourced documents on the grounds that the device recorded them, because
the shape reported is the product of the engine's own filtering as well as the
device's recording.

#### Scenario: Two device-sourced documents with different evidence differ in confidence
- **WHEN** one lap-sourced run's shape follows directly from its recorded structure and another's survives only after candidate segments are discarded
- **THEN** the two documents do not carry the same confidence

#### Scenario: The device path can fall below the assertion threshold
- **WHEN** a lap-sourced shape rests on weak evidence
- **THEN** its confidence is below the threshold at which the interface states a verdict

### Requirement: A shape resting on a size-floor discard does not assert
The document SHALL report confidence below the assertion threshold where a work
segment was discarded for being too small AND the reported shape depends on that
discard. Dependence SHALL be established by determining whether the surviving
segments would differ had the size floor not been applied — not inferred from
the presence of a discard alone, since a sub-floor fragment at the end of a run
is routine and decides nothing.

#### Scenario: An easy segment left standing by the size floor is hedged
- **WHEN** every short work segment in a run is discarded for being too small and one long easy segment remains, becoming the reported block
- **THEN** the document does not assert that block

#### Scenario: A routine trailing fragment changes nothing
- **WHEN** a sub-floor fragment is discarded but the surviving segments would be the same without the size floor
- **THEN** the discard does not lower confidence and the shape may assert

#### Scenario: Nothing discarded leaves the verdict unhedged
- **WHEN** no candidate work segment is discarded for size
- **THEN** elimination contributes nothing to the confidence and the shape may assert

### Requirement: Device-corroborated demotion never lowers confidence
The system SHALL NOT hedge a document because a lap was demoted by workout-step
evidence. A warm-up, cool-down or transition the watch tagged as active but
which occupies a non-repeated workout step is rejected on the device's own
evidence, not on an engine guess, and rejecting it is the mechanism by which
device-sourced documents became correct.

#### Scenario: Demoting an ACTIVE warm-up leaves the set asserting
- **WHEN** a lap is excluded from a set because its workout step is not the repeated one
- **THEN** the resulting set still asserts

#### Scenario: The two filters are not treated alike
- **WHEN** one run's shape depends on a size discard and another's depends on a step demotion
- **THEN** only the first is hedged

### Requirement: Corroborated device structure still asserts
The document SHALL remain above the assertion threshold for a set whose reps
share a repeated workout step, meet the size floors, and require no discards.
Hedging SHALL NOT be applied so broadly that genuinely structured workouts stop
stating their verdict.

#### Scenario: A clean repeated-step set asserts
- **WHEN** a run's reps all execute one repeated workout step at full size with nothing discarded
- **THEN** the document asserts the set

#### Scenario: Currently-correct sets do not regress
- **WHEN** the archive is rescored at the new engine version
- **THEN** every set that matched its prescribed count before still asserts

### Requirement: The engine decides whether a document asserts, and the page obeys
The engine SHALL decide whether a document asserts its shape and SHALL carry
that verdict in the document. The interface SHALL render from the verdict and
SHALL NOT compare a confidence value against a threshold of its own, so that
there is exactly one place where the comparison happens and no possibility of
the two drifting.

#### Scenario: Changing the threshold changes the page
- **WHEN** the engine's assertion threshold is altered
- **THEN** the interface's hedging behaviour changes with it, with no second edit

#### Scenario: The interface performs no threshold arithmetic
- **WHEN** the run page renders an interval document
- **THEN** it reads the document's verdict rather than evaluating the confidence value itself

#### Scenario: A hedged document is presented as possible, not certain
- **WHEN** a document's confidence is below the threshold
- **THEN** the interface presents the shape as possible rather than asserting it
