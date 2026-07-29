# workout-prior Specification (delta)

## ADDED Requirements

### Requirement: A run's workout definition is acquired at sync time and cached on first sight
The sync pipeline SHALL fetch the Garmin workout named by an archived running
activity's `summary_json.workoutId` through the credentials it already holds,
SHALL store the raw payload once, and SHALL NOT re-fetch a workout it already
holds. Acquisition SHALL be idempotent, SHALL no-op offline, and SHALL never
break the sync on failure. A one-time backfill SHALL catch up historical
workouts and SHALL be resumable.

#### Scenario: A workout already stored is not fetched again
- **WHEN** a sync encounters an activity whose `workoutId` is already banked
- **THEN** no request is made and the stored payload is retained unchanged

#### Scenario: A deleted workout does not break the run
- **WHEN** the workout service returns an error for a `workoutId` that no longer exists
- **THEN** a warning is recorded, the activity keeps its inference-derived document, and the sync completes

#### Scenario: An activity with no workoutId is untouched
- **WHEN** an archived run carries no `workoutId`
- **THEN** no request is made and the run is read by the existing inference path

### Requirement: The step tree is flattened to the device's own step indices
The system SHALL flatten a workout's `workoutSegments[].workoutSteps`
depth-first, descending into every `RepeatGroupDTO` and carrying its
`numberOfIterations` onto the steps it repeats. The system SHALL consume one
index position AFTER each repeat group's children, matching the FIT encoding in
which the repeat instruction follows the steps it repeats, so that the resulting
positions correspond to the `wktStepIndex` recorded on executed laps.

#### Scenario: A repeat group consumes its trailing index
- **WHEN** a workout is warm-up, a repeat of (interval, recovery), then cool-down
- **THEN** the flattened positions are 0 for the warm-up, 1 and 2 for the repeated pair, and 4 for the cool-down

#### Scenario: A workout with no repeat group maps straight through
- **WHEN** every step is executable and none repeats
- **THEN** flattened positions are consecutive from zero

### Requirement: A prior is used only when its mapping is verified against the executed laps
The system SHALL check that every `wktStepIndex` observed on an activity's laps
lands on a flattened step of that activity's workout. When any observed index
does not, the system SHALL discard the prior for that activity entirely and
SHALL fall back to inference. A partial or best-guess mapping SHALL NOT be used.

#### Scenario: An unmappable index discards the whole prior
- **WHEN** an executed lap carries a `wktStepIndex` with no corresponding flattened step
- **THEN** the document is built by inference alone and records that it had no prior

#### Scenario: A verified mapping is used
- **WHEN** every observed index maps to exactly one flattened step
- **THEN** the prior is applied

### Requirement: The document records where its prescription came from
The system SHALL distinguish a workout cached at first sight from one recovered
by backfill, and SHALL carry that distinction in the interval document. Because
the workout service reports no update stamp for these workouts, a backfilled
prescription SHALL be treated as best-effort and SHALL NOT be presented with the
same authority as one banked when the run was new.

#### Scenario: A backfilled prescription is marked as such
- **WHEN** a document is built from a workout recovered by the historical backfill
- **THEN** the document records best-effort provenance

#### Scenario: A document with no workout says so
- **WHEN** no workout is available for the run
- **THEN** the document records the absence rather than omitting the field

## ADDED Requirements — what the prior changes about reading a run

*(`interval-lens` is not an OpenSpec capability — it shipped through the
superpowers/SDD workflow and its ledgers were deleted on completion, so git
history is its record. These are therefore stated as additions here rather than
as deltas against a spec that does not exist. See
`docs/superpowers/specs/2026-07-27-interval-lens-design.md` and
`…/2026-07-28-interval-lens-workout-steps-design.md` for the behaviour they
modify.)*

### Requirement: The prior is consumed before the laps/stream branch
`build_document` SHALL apply the prior ahead of choosing between the device-lap
path and the stream path, so that both producers read one prescription by
identical rules. The lap path SHALL NOT hardcode `prescribed` as absent, and the
two paths SHALL NOT carry independent rep-count floors.

#### Scenario: A prescribed set reports found against prescribed on either path
- **WHEN** a run with a prescribed set of four is read, whether from device laps or from the stream
- **THEN** the document reports the reps it found together with the four that were prescribed

#### Scenario: A bailed session reports its shortfall rather than collapsing
- **WHEN** an athlete completes two reps of a prescribed four
- **THEN** the document reports two found of four prescribed, and does not classify the run as steady

### Requirement: Prescribed step roles override inferred ones
Where a workout is available, a step's declared type SHALL decide whether the
laps executing it are work, recovery, warm-up or cool-down. Inference from
`intensityType` and from repeated `wktStepIndex` SHALL become the fallback for
runs with no workout, not the primary rule.

#### Scenario: An ACTIVE-tagged warm-up is not a rep
- **WHEN** a workout declares a warm-up step and the watch tagged its lap ACTIVE
- **THEN** that lap is a warm-up in the document and is not counted as a rep

#### Scenario: A single prescribed rep between easy bookends is not a pyramid
- **WHEN** a workout prescribes an easy segment, one paced rep, and another easy segment
- **THEN** the document reports one rep, not a three-rep varied set

### Requirement: Set membership is decided by a target's value, not merely its type
Where a workout has no repeat group, the system SHALL group work steps into a
set by comparing both the target TYPE and the target VALUE — the pace band or
the zone number. Steps sharing a type but prescribing materially different
intensities SHALL NOT be members of one set. Sharing a type alone is
insufficient: a recovery float between two efforts is commonly authored as a
work-typed step on the same target type as the efforts it separates.

#### Scenario: A float between two efforts is not a third rep
- **WHEN** a workout prescribes a hard effort, an easy-zone float, and another hard effort, all on the same target type
- **THEN** the document reports two reps separated by a recovery, not a three-rep varied set

#### Scenario: A genuine pyramid survives the same rule
- **WHEN** a workout prescribes three differently-sized efforts whose pace bands are materially the same
- **THEN** all three are members of one varied set

### Requirement: A prescribed rep is a rep regardless of its size
Where a workout prescribes a rep, the system SHALL NOT reject the laps executing
it for falling below the minimum duration or distance that guards inference. The
size floors exist to reject fragments the detector invented; they SHALL NOT
reject a rep the athlete was told to run.

#### Scenario: Twenty-second strides are found, not filtered away
- **WHEN** a workout prescribes four twenty-second reps and the athlete runs them
- **THEN** the document reports four reps rather than promoting the preceding easy segment to a block

### Requirement: A set prescribed by time is named and compared by time
Where a rep's end condition is a duration, the system SHALL name the set by that
duration and SHALL NOT name it by the distance the reps happened to cover.

#### Scenario: Time-prescribed hill reps are named by duration
- **WHEN** a workout prescribes six ninety-second reps whose covered distances vary as the athlete tires
- **THEN** the set is named by its ninety-second prescription

### Requirement: Confidence on the device path is derived, not asserted
A lap-sourced document SHALL NOT carry maximum confidence unconditionally. A
shape that survives because filtering left a single segment standing SHALL be
hedged; a shape corroborated by the prescription MAY be asserted.

#### Scenario: A filtered-down block is hedged
- **WHEN** every prescribed rep is filtered away and one unprescribed segment remains
- **THEN** the resulting shape is reported below the assertion threshold

#### Scenario: A prescription-corroborated set is asserted
- **WHEN** the reps found match the reps prescribed
- **THEN** the document asserts the shape

### Requirement: A prescribed intensity bounds what the run may be called
Where a step declares an easy target, the system SHALL NOT report that step as
quality work. Where a step declares a pace band, the system SHALL report each
executing rep against that band.

#### Scenario: A Z2 prescription is never a rep set
- **WHEN** a workout prescribes a single easy heart-rate-zone segment
- **THEN** the run is not reported as a rep set or a quality block

#### Scenario: A paced rep is compared to its band
- **WHEN** a workout prescribes reps within a pace band and the athlete runs them
- **THEN** each rep carries its relation to that band
