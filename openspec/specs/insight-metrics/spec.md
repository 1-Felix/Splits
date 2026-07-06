# insight-metrics Specification

## Purpose
Versioned, self-healing derived-metrics engine over the activity archive — per-run best efforts and reference-band aggregates, monthly progress series, outdoor-only records, and a Riegel-vs-Garmin race trajectory — assembled fail-soft into an additive `insights` block in `garmin-data.js`.

## Requirements

### Requirement: Per-run metrics are extracted once and versioned
The sync SHALL compute derived metrics (best efforts and reference-band
aggregates) exactly once per archived run per algorithm version, storing one
`run_metrics` row keyed by the activity id and stamped with the engine's
`METRICS_VERSION`. Changing any algorithm parameter SHALL bump the version, and
rows at a stale version SHALL be recomputed automatically by a subsequent sync
with no manual intervention.

#### Scenario: A new run gains metrics on the next sync
- **WHEN** a run is archived with its detail payload and a sync runs
- **THEN** a `run_metrics` row exists for it at the current `METRICS_VERSION`
  with its best efforts and reference-band aggregates

#### Scenario: A version bump self-heals
- **WHEN** `METRICS_VERSION` is increased and the next sync runs
- **THEN** all rows at the older version are recomputed at the new version
  without any flag, migration step, or data loss in the raw tables

#### Scenario: A run without detail is skipped, not failed
- **WHEN** an archived run has no detail payload yet
- **THEN** no `run_metrics` row is written and the sync succeeds; the row
  appears on a later sync once the detail top-up archives the payload

### Requirement: Best efforts are elapsed-time in-run fastest efforts
For each run with streams, the engine SHALL compute the fastest 1 km, 1 mile,
5 km, 10 km, and half-marathon efforts as the minimum **elapsed** time over any
contiguous window of the run covering the target distance, interpolating window
edges at the exact distance. Distances longer than the run SHALL yield NULL,
never an extrapolated value.

#### Scenario: Fastest 5k inside a longer run
- **WHEN** a 16 km run's streams are processed
- **THEN** `best_5k_s` is the minimum elapsed time over any contiguous ~5000 m
  window, at most marginally above the true value given stream resolution

#### Scenario: A pause counts against the effort
- **WHEN** the fastest candidate window contains a recording pause
- **THEN** the elapsed time includes the paused wall-clock time, so the stored
  effort is race-honest

#### Scenario: Run shorter than the target distance
- **WHEN** a 4 km run is processed
- **THEN** `best_5k_s`, `best_10k_s`, and `best_half_s` are NULL

#### Scenario: Cross-validation against Garmin's own splits
- **WHEN** an archived run carries a Garmin `fastestSplit_*` value for a
  distance
- **THEN** the engine's corresponding best effort agrees within the documented
  tolerance (test-enforced against real archived runs)

### Requirement: Progress series pool stream samples at reference bands
The engine SHALL build monthly progress series by pooling stream samples
across all runs of a month — not by classifying whole runs. Pace at reference
HR SHALL be the time-weighted grade-adjusted pace of samples inside the HR
band (after a warm-up cutoff and above a walking speed floor); cadence at
reference pace SHALL be the time-weighted cadence of samples inside the pace
band. Months with less in-band time than a minimum threshold SHALL yield null
points rather than noisy ones. Treadmill runs SHALL contribute to both pools.

#### Scenario: A month with sufficient in-band data gets a point
- **WHEN** the runs of a month contain at least the threshold of in-band time
- **THEN** the series carries one point for that month computed from the
  pooled time-weighted sums stored per run

#### Scenario: A sparse month yields a gap
- **WHEN** a month's runs contain less than the threshold of in-band time
- **THEN** that month's value is null and no point is fabricated

#### Scenario: Treadmill runs feed the trends
- **WHEN** a treadmill run has samples inside a reference band
- **THEN** those samples contribute to the monthly pools like any outdoor run

### Requirement: Records are outdoor-only and computed as a progression
A record event SHALL be a non-treadmill run whose best effort at a distance
beats the best effort of every earlier non-treadmill run at that distance. The
engine SHALL expose all-time and last-90-days best efforts per distance and a
newest-first feed of recent record events with old and new times.

#### Scenario: A record falls
- **WHEN** a new outdoor run's best 5k beats every earlier outdoor run's best 5k
- **THEN** the records feed gains an entry with the date, distance, previous
  best, and new best, and the all-time table reflects the new best

#### Scenario: A treadmill effort cannot set a record
- **WHEN** a treadmill run produces the fastest 1k ever recorded
- **THEN** the records feed and best-efforts tables are unchanged, while the
  run still contributes to the monthly trend pools

### Requirement: The race trajectory tracks Riegel against Garmin weekly
The engine SHALL produce a weekly series from the first qualifying effort to
the current week: a Riegel half-marathon prediction anchored on the best
outdoor 10 km effort within the trailing 84 days (null when no such effort
exists — never substituted from shorter distances), and Garmin's banked
half-marathon prediction as of that week. The existing `predictions.trend`
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

#### Scenario: The trend placeholder is finally filled
- **WHEN** the sync assembles insights with at least ~4 recent weekly Riegel
  points
- **THEN** `predictions.trend` is a non-empty verdict string reflecting whether
  the gap to the goal is closing, opening, or flat

### Requirement: Garmin predictor history is banked and backfilled
Each sync SHALL upsert today's race predictions into the archive from the
predictor document the sync already fetches. When the predictions table is
empty, the sync SHALL backfill daily predictor history back to the account
start automatically, inside the same fail-soft wrapper, requiring no manual
step. Loss of the history endpoint SHALL degrade to bank-on-sync only.

#### Scenario: A normal sync banks today's prediction
- **WHEN** a sync fetches the race predictor document
- **THEN** a row for today exists in `race_predictions` with the promoted
  times and the raw payload

#### Scenario: First sync after deploy backfills history
- **WHEN** a sync runs and `race_predictions` is empty
- **THEN** daily predictor history is backfilled to the account start and the
  trajectory's Garmin line covers past weeks

#### Scenario: Backfill failure does not break the sync
- **WHEN** the history endpoint fails or disappears
- **THEN** the sync completes normally, today's row is still banked when
  available, and the Garmin line simply starts where data exists

### Requirement: Metrics are fail-soft and never block telemetry
All metrics work (extraction, banking, assembly) SHALL run inside the sync's
fail-soft pattern: any failure is a logged warning, the sync exit code is
unaffected, and `garmin-data.js` is still written with all pre-existing keys.
A failed insights assembly SHALL omit the `insights` block entirely rather
than emit a partial one.

#### Scenario: Engine failure leaves telemetry intact
- **WHEN** the metrics step raises on a corrupt stream or locked database
- **THEN** `garmin-data.js` is written with all existing keys, the sync exits
  zero, and a warning is logged

#### Scenario: No partial insights block
- **WHEN** series assembly fails midway
- **THEN** the emitted `garmin-data.js` has no `insights` key at all

### Requirement: Insights surface additively in the data contract
The sync SHALL emit the assembled metrics as one additive `insights` block in
`garmin-data.js` (efficiency and cadence monthly series with their reference
bands, best efforts, records feed, weekly trajectory with the goal, and the
metrics version), leaving every existing key untouched. Data validation SHALL
treat the block as optional but SHALL shape-check it when present.

#### Scenario: A successful sync emits the block
- **WHEN** a sync completes with a populated archive
- **THEN** `garmin-data.js` contains an `insights` block with efficiency,
  cadence, bestEfforts, recordsFeed, trajectory, and metricsVersion, and all
  previously existing keys are byte-for-byte semantically unchanged

#### Scenario: A pre-engine data file stays valid
- **WHEN** validation runs against a `garmin-data.js` without `insights`
- **THEN** validation passes

#### Scenario: A malformed block is caught
- **WHEN** validation runs against a file whose `insights` block is missing
  required members or has wrong types
- **THEN** validation fails naming the offending member

### Requirement: Metrics coverage is verifiable
The archive verification mode SHALL report metrics coverage (runs with detail
vs `run_metrics` rows at the current version), predictor-history bounds, and
assembled series extents, and SHALL exit non-zero when coverage regresses.

#### Scenario: Healthy coverage report
- **WHEN** verification runs after a completed sync
- **THEN** it reports run-metrics coverage equal to detail coverage, the
  `race_predictions` date bounds, and the series' month/week counts

#### Scenario: A coverage regression is caught
- **WHEN** `run_metrics` rows remain at a stale version after a completed sync
- **THEN** verification exits non-zero naming the regression

### Requirement: Best efforts are sliced by calendar year
The engine SHALL emit per-calendar-year best-effort tables into the `insights`
block (`bestEfforts.byYear`) for the same distances as the existing tables,
applying the same outdoor-only records policy in the same single place, and
carrying each effort's activity id and date so the dashboard can link a record
to its run.

#### Scenario: Each year with qualifying runs gets a table
- **WHEN** the archive holds outdoor runs with metrics in 2024, 2025, and 2026
- **THEN** `bestEfforts.byYear` carries one table per year, each entry with
  the effort time, its date, and its activity id

#### Scenario: Treadmill efforts do not enter year tables
- **WHEN** a treadmill run holds the fastest 1 km of a year
- **THEN** that year's 1 km entry reflects the fastest outdoor effort instead

#### Scenario: A distance never covered in a year is null
- **WHEN** a year contains no run covering a distance (e.g. no half-marathon
  effort in 2024)
- **THEN** that year's entry for the distance is null, never extrapolated

### Requirement: Year-over-year monthly aggregates are emitted
The engine SHALL emit `insights.yoy`: for each calendar year in the archive,
monthly running totals over promoted columns — distance, run count, and
average pace — derived at sync time. Months with no runs SHALL carry zero
count/distance and a null pace. The series SHALL cover only months up to the
sync date.

#### Scenario: Aggregates match the archive
- **WHEN** the engine assembles `insights.yoy`
- **THEN** each month's distance and run count equal the archive's sums over
  running activities for that month

#### Scenario: An empty month is honest
- **WHEN** a month within a covered year has no runs
- **THEN** that month carries zero distance, zero count, and a null pace

### Requirement: The new insight members are validated like the rest of the block
Data validation SHALL shape-check `bestEfforts.byYear` and `yoy` when present,
and data files written before these members existed SHALL remain valid.

#### Scenario: A malformed byYear member is caught
- **WHEN** validation runs against an `insights` block whose `byYear` has a
  wrong type or missing fields
- **THEN** validation fails naming the offending member

#### Scenario: A pre-3a insights block stays valid
- **WHEN** validation runs against an `insights` block without `byYear`/`yoy`
- **THEN** validation passes
