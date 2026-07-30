# course-lens Specification

## Purpose
The race-course engine: sync-time acquisition of the plan's Garmin course (geo points with distance and elevation) through the credentials the sync already holds, a smoothed grade model calibrated against the athlete's own running, detected decisive segments with honest cost estimates, and the deterministic, disposable course document behind the course surface and the race-vs-course comparison.

## Requirements

### Requirement: The race course is acquired at sync time, never by the browser
The sync pipeline SHALL fetch the Garmin course named by `planData.race.courseId`
through the credentials it already holds, and SHALL store its geo points as
rounded columnar arrays. The browser SHALL NOT be the fetching party. Re-derivation and
re-storage SHALL be skipped when the stored copy's update stamp is unchanged at
the current engine version, the step SHALL no-op when offline, and it SHALL
never break the sync on failure.

#### Scenario: An unchanged course is not re-derived or rewritten
- **WHEN** a sync runs and the stored course's update stamp matches the remote one
- **THEN** the stored course and its derived document are retained unchanged, and neither the derivation nor the database write is repeated

#### Scenario: A missing course id leaves the feature dark
- **WHEN** the plan's race carries no `courseId`
- **THEN** no course is fetched, no `courseLens` object is written, and the sync completes normally

#### Scenario: An acquisition failure never breaks the sync
- **WHEN** the course endpoint errors or the sync is running offline
- **THEN** the last stored course is retained, a warning is recorded, and the sync completes

### Requirement: Grade is derived from a smoothed elevation series
The system SHALL smooth stored elevation over a DISTANCE window before computing
any gradient, and SHALL store the smoothed series alongside the raw one. Every
gradient reported by this feature SHALL derive from the smoothed series, so that
the pace model and the rendered profile can never disagree about the grade at a
given kilometre.

#### Scenario: Point-spacing variation does not distort smoothing
- **WHEN** stored points are unevenly spaced along the course
- **THEN** the smoothing window is applied over distance rather than sample count

#### Scenario: Raw elevation survives derivation
- **WHEN** the lens is recomputed at a new engine version
- **THEN** the raw elevation series is unchanged and the smoothed series is rebuilt from it

### Requirement: Decisive segments are detected, not hand-listed
The system SHALL identify sustained climbs and descents algorithmically from the
smoothed profile, and SHALL surface them as part of the derived document. Course
features SHALL NOT be hardcoded in the renderer.

#### Scenario: The real course yields its wall and its drop
- **WHEN** the engine runs over the stored 2026 Sonthofen half-marathon course
- **THEN** the kilometre 12→13 climb and the kilometre 14–15 descent are both reported as decisive segments

### Requirement: The pace model is calibrated against the athlete's own running
The system SHALL price gradient using an analytic energy-cost curve scaled by a
single damping factor fitted from archived per-sample speed, grade-adjusted
speed and elevation. The derived document SHALL carry the model parameters and
the fit residual. When the fit is below a confidence threshold the system SHALL
fall back to the uncalibrated curve and SHALL record that it did so.

#### Scenario: A steep descent is never priced as free speed
- **WHEN** the model prices a kilometre at approximately −6 % gradient
- **THEN** the benefit is bounded by the curve's descent reversal rather than extrapolated linearly

#### Scenario: A weak fit is disclosed rather than hidden
- **WHEN** the calibration residual falls below the confidence threshold
- **THEN** the document reports the uncalibrated fallback and the surface presents the model's accuracy honestly

### Requirement: The derived document stores model parameters rather than baked tables
The system SHALL store the profile together with the calibrated cost parameters
so that a per-kilometre pace table for any target finish is computable by the
consumer without a sync or schema change. Named target presets SHALL be presets
over that model, not separately precomputed tables.

#### Scenario: A new target needs no pipeline change
- **WHEN** a pace table is requested for a target finish that is not one of the presets
- **THEN** it is computed from the stored parameters with no sync run and no schema change

### Requirement: The cost of declining descent benefit is quantified
The system SHALL express what the course costs when descent benefit is
deliberately not taken, by clamping sub-unity pace factors to level running, and
SHALL surface that alongside the model-optimal figure. The surface SHALL present
both, so that a pacing decision made for injury reasons is shown as a priced
trade rather than as an unexplained deviation from target.

#### Scenario: Both readings are available for one target
- **WHEN** a pace table is produced for a target finish
- **THEN** the model-optimal and descent-declined variants are both computable, and their difference is reported

#### Scenario: A flat course prices caution at nothing
- **WHEN** no kilometre carries a pace factor below one
- **THEN** the cost of declining descent benefit is zero

### Requirement: The derived document is deterministic and disposable
The system SHALL produce a byte-identical document for the same stored course at
the same engine version, and SHALL treat the document as a recomputable cache
keyed by that version, with the stored raw course as the source of truth.

#### Scenario: Recomputation is stable
- **WHEN** the engine runs twice over the same stored course at the same version
- **THEN** both passes produce identical documents

#### Scenario: A version bump heals the cache
- **WHEN** the engine version is raised
- **THEN** the stored document is recomputed from the raw course with no manual step

### Requirement: Degraded elevation data is disclosed, not drawn
The system SHALL mark the profile as degraded when stored elevation is missing
beyond a threshold fraction of points, and the surface SHALL present that state
rather than rendering an interpolated profile as though it were measured.

#### Scenario: A sparse course refuses to lie
- **WHEN** elevation is absent from more points than the threshold allows
- **THEN** the document marks the profile degraded and the page shows that state

### Requirement: The course surface presents profile, route and pace targets
The system SHALL provide a `/course` page rendering the elevation profile against
DISTANCE with detected segments annotated, a crosshair readout of kilometre,
elevation and grade, the route over the existing basemap, and a per-kilometre
pace table computed from the stored model. The page SHALL remain useful when map
tiles are unavailable.

#### Scenario: The profile survives a missing basemap
- **WHEN** tiles for the course rect are unavailable
- **THEN** the profile, pace table and readouts render, and only the map is absent

#### Scenario: Annotations come from the document
- **WHEN** the page annotates the decisive kilometres
- **THEN** the annotations are read from the derived document rather than hardcoded in the page

### Requirement: A completed race is compared against the course in the distance domain
The system SHALL match a completed race activity to its course by race date, run
type and distance tolerance, SHALL normalise the activity's cumulative distance
to the course total before resampling, and SHALL attribute time gained and lost
to climb, descent and flat terrain. When no activity matches, the surface SHALL
show profile and pace plan alone without an error state.

#### Scenario: GPS drift does not smear the alignment
- **WHEN** the matched activity's total distance differs from the course total
- **THEN** its distance is normalised to the course total before resampling, so a given kilometre denotes the same place in both series

#### Scenario: Before the race the overlay is simply absent
- **WHEN** no activity matches the course
- **THEN** the page renders profile and pace plan with no empty overlay and no error
