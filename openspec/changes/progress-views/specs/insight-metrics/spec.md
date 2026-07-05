# insight-metrics Specification (delta)

## ADDED Requirements

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
