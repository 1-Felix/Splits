## ADDED Requirements

### Requirement: An empty lap-detail reply is never cached as fetched

The lap acquisition SHALL write its raw-reply cache only after confirming the
reply carries a non-empty lap list. A reply whose `lapDTOs` is empty or absent
SHALL leave no cache entry, so the run is asked again on a later sync. A
permanently lap-less run therefore costs a bounded refetch per sync rather than
being silently marked complete — and can never starve the backfill queue behind
a cached empty envelope.

#### Scenario: Empty envelope is not cached

- **WHEN** the lap fetch for a run returns `{"lapDTOs": []}`
- **THEN** no cache entry is written and the run remains eligible for a future
  lap fetch

#### Scenario: Populated reply is cached write-once

- **WHEN** the lap fetch for a run returns a non-empty `lapDTOs` list
- **THEN** the reply is cached and the run is not fetched again

### Requirement: Interval coverage counts only documents joined to a live activity

The interval coverage counter SHALL count only `run_intervals` rows that join to
a currently live activity row, so interval rows orphaned by activity dedupe or
pruning cannot inflate the scored count past the population of streamed runs.

#### Scenario: Orphaned interval rows are not counted

- **WHEN** a `run_intervals` row exists whose activity row has been pruned
- **THEN** interval coverage does not count it, and `scored` cannot exceed the
  number of streamed runs
