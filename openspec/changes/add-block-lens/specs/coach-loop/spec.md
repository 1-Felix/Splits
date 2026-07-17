# coach-loop Specification (delta)

## ADDED Requirements

### Requirement: The briefing carries a deterministic Block report
`coach-briefing.md` SHALL include a "Block report" section rendered from the
same lens document the dashboard consumes (passed in, never recomputed):
the block's headline numbers (week N of M, percent executed, km done vs
planned, quality hit rate, EF and cadence deltas, goal-gap trend, records)
plus factually-stated judgment hooks — behind-plan volume, EF stalling or
regressing, undetailed future weeks. The section SHALL state numbers only;
judgment stays with the `/coach` ritual. When no lens exists the briefing
SHALL omit the section and remain otherwise complete.

#### Scenario: Briefing and dashboard agree
- **WHEN** a sync writes both `garmin-data.js` and `coach-briefing.md`
- **THEN** the Block report's numbers are identical to the dashboard's `blockLens.current` values

#### Scenario: Null metrics stay honest in prose
- **WHEN** the EF delta is `null` for insufficient baseline
- **THEN** the Block report says so explicitly rather than omitting or inventing the line

#### Scenario: No lens, intact briefing
- **WHEN** the sync runs with no plan snapshots
- **THEN** the briefing is written without a Block report section and all existing sections are unchanged

### Requirement: The /coach ritual reads the Block report
The `/coach` skill documentation SHALL direct the ritual to read the Block
report as the block-level state of record before adjusting the plan, alongside
the existing week tables and staleness notes.

#### Scenario: Ritual grounded in the lens
- **WHEN** `/coach` is invoked during an active block
- **THEN** the skill's reading list includes the Block report section and the ritual's reasoning references its numbers
