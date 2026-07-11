# insight-metrics Delta

## ADDED Requirements

### Requirement: Per-run in-band display values are stored columns
The engine SHALL compute and store, in each run's `run_metrics` row, the run's
own reference-band display values: pace at reference HR
(`refhr_pace_s_per_km`, from the run's in-band time over its in-band distance)
and cadence at reference pace (`refpace_cadence_spm`, from the run's
time-weighted in-band cadence). A run with no in-band distance or time SHALL
store NULL for the respective value, never zero or an extrapolation. These
columns SHALL be introduced with a `METRICS_VERSION` bump so the existing
self-heal recomputes every row with no manual step.

#### Scenario: A run with in-band samples stores its own values
- **WHEN** a run with samples inside the HR band is extracted at the new
  version
- **THEN** its row stores the run's in-band pace consistent with its stored
  time and distance aggregates

#### Scenario: A run outside the bands stays honest
- **WHEN** a run with zero in-band time is extracted
- **THEN** its per-run display values are NULL and its aggregate columns are
  zero, so a consumer can distinguish "no evidence" from "slow"

#### Scenario: The bump self-heals existing rows
- **WHEN** the first sync runs after deploying the new version
- **THEN** every `run_metrics` row is recomputed at the new version carrying
  the new columns, with no flag or migration step

## MODIFIED Requirements

### Requirement: The race trajectory tracks Riegel against Garmin weekly
The engine SHALL produce a weekly series from the first qualifying effort to
the current week: a Riegel half-marathon prediction anchored on the best
outdoor 10 km effort within the trailing 84 days (null when no such effort
exists — never substituted from shorter distances), and Garmin's banked
half-marathon prediction as of that week. Each week with a non-null Riegel
value SHALL carry its anchoring effort's activity id (`anchorId`), so the
dashboard can link the prediction to the run that demonstrated it; weeks with
a null Riegel value SHALL carry no anchor. The existing `predictions.trend`
field SHALL carry a verdict (closing / opening / flat, with a rate) derived
from the recent Riegel trend against the goal.

#### Scenario: A week with a recent 10k effort gets a Riegel point
- **WHEN** an outdoor run in the trailing 84 days contains a 10 km best effort
- **THEN** that week's `riegelSec` is the Riegel projection (exponent 1.06) of
  the fastest such effort

#### Scenario: No recent 10k means an honest gap
- **WHEN** no outdoor 10 km effort exists in a week's trailing 84 days
- **THEN** that week's `riegelSec` is null rather than an estimate from a
  shorter distance

#### Scenario: The anchoring run is identified
- **WHEN** a week's `riegelSec` is non-null
- **THEN** that week carries the `anchorId` of the run holding the anchoring
  10 km effort, and a week with a null `riegelSec` carries no `anchorId`

#### Scenario: The trend placeholder is finally filled
- **WHEN** the sync assembles insights with at least ~4 recent weekly Riegel
  points
- **THEN** `predictions.trend` is a non-empty verdict string reflecting whether
  the gap to the goal is closing, opening, or flat

### Requirement: The new insight members are validated like the rest of the block
Data validation SHALL shape-check `bestEfforts.byYear`, `yoy`, and the
trajectory's per-week `anchorId` when present, and data files written before
these members existed SHALL remain valid.

#### Scenario: A malformed byYear member is caught
- **WHEN** validation runs against an `insights` block whose `byYear` has a
  wrong type or missing fields
- **THEN** validation fails naming the offending member

#### Scenario: A malformed anchorId is caught
- **WHEN** validation runs against a trajectory whose `anchorId` is present
  with a non-numeric type
- **THEN** validation fails naming the offending member

#### Scenario: A pre-3a insights block stays valid
- **WHEN** validation runs against an `insights` block without `byYear`/`yoy`
  or without `anchorId` on trajectory weeks
- **THEN** validation passes
