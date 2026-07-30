# block-lens Specification (delta)

## ADDED Requirements

### Requirement: Blocks are enumerated from plan snapshots, keyed by race date
The sync SHALL enumerate training blocks from `plan_snapshots`, identifying a
block by its `race.date` — the same key the `block_lens` table and the archive
API use. The race name is an attribute taken from the date's latest snapshot:
renaming a race SHALL NOT spawn a new block, only a race-date edit does. A
block's window SHALL span the earliest `week.mon` seen for that date across
its snapshots through `race.date`, and the block's planned shape (weeks,
phases, planned km) SHALL come from the latest snapshot. A block whose race
date is on or after sync-today is the current block; all others are complete.

#### Scenario: One race across many snapshots is one block
- **WHEN** the plan for the same race has been snapshotted 12 times as `/coach` adjusted it
- **THEN** the lens contains exactly one block for that race, shaped by the latest snapshot

#### Scenario: A completed block survives the plan moving on
- **WHEN** `plan-data.js` now holds a new race but snapshots of the previous race exist
- **THEN** the previous race still appears as a complete block derived from its snapshots

#### Scenario: Race date edit mid-block starts a new block identity
- **WHEN** a plan edit changes the race date
- **THEN** subsequent syncs derive a new block row under the new race key, and the old row completes at its own race date

#### Scenario: A race rename stays one block and heals the stored name
- **WHEN** a later snapshot renames the race without moving its date
- **THEN** the lens still holds exactly one block for that date and the next sync's derivation updates the stored race name, even on a completed block

### Requirement: The lens is a versioned, disposable derived table
The sync SHALL store one row per block in a `block_lens` table (schema v9,
additive): promoted columns `race_date` (primary key), `race_name`,
`lens_version`, `is_complete`, plus the full lens document as `block_json`.
Rows SHALL be recomputable at any time from snapshots, compliance, run
metrics, and race predictions; every sync SHALL recompute the current block,
SHALL keep recomputing a completed block while its race day lies within the
completion grace window (so late-syncing race data still reaches the
retrospective), and SHALL recompute completed blocks when `lens_version`
differs from `BLOCK_LENS_VERSION`. Changing any algorithm parameter SHALL
require bumping `BLOCK_LENS_VERSION`.

#### Scenario: Version bump heals stale rows
- **WHEN** `BLOCK_LENS_VERSION` is bumped and a sync runs
- **THEN** all block rows, including completed ones, are recomputed at the new version

#### Scenario: A late-syncing race upload still reaches the retrospective
- **WHEN** the race activity syncs a day after race day
- **THEN** the next sync recomputes the just-completed block and its retrospective carries the race

#### Scenario: Lens derivation failure never breaks the sync
- **WHEN** block-lens derivation raises unexpectedly
- **THEN** the sync warns and completes; `garmin-data.js` and the briefing are still written without the lens

### Requirement: Execution rollup from existing compliance verdicts
The lens document SHALL contain, per plan week: counts of
done/partial/missed/swapped/unplanned days, planned vs actual running km, and
day-level drill rows (planned kind/title/km/load, verdict status and reason,
actual km/pace/HR and `activity_id` when matched). Block-level it SHALL state
overall percent executed as `(done + swapped + 0.5·partial) / scored planned
days` and the quality hit rate (planned Hard-load days executed). Verdicts
whose dates no week of the latest snapshot covers anymore (a week retired by
a mid-block plan edit) SHALL rejoin the rollup as retired week entries grouped
by calendar week — stored work never silently leaves the block's totals or
drill. The lens SHALL never re-score or re-classify a compliance verdict.

#### Scenario: Week rollup matches its compliance rows
- **WHEN** a scored week has 3 done, 1 partial, 1 missed planned days
- **THEN** that week's lens entry reports exactly those counts and the block percent-executed weights the partial at 0.5

#### Scenario: Unscored future weeks are planned-only
- **WHEN** a week of the current block lies entirely in the future
- **THEN** its lens entry carries the planned shape with no verdicts and is excluded from percent-executed

#### Scenario: A week retired from the plan keeps its scored history
- **WHEN** a mid-block edit removes an already-scored week from the plan
- **THEN** the lens still reports that week's verdicts, km and drill rows as a retired week entry, and the block totals include them

### Requirement: Window-scoped adaptation metrics with honesty rules
The lens document SHALL state, per block: the EF proxy delta (median
`refhr_pace_s_per_km` over the block's first 14 days vs its last 14 days),
the cadence delta (`refpace_cadence_spm`, same windows), records fallen
inside the block (a per-distance best effort inside the window beating the
all-time best before the window), and the goal-gap trend (predictor half time
nearest block start vs latest in window, against the race's goal time). Any
metric whose window holds fewer than 3 qualifying runs SHALL be `null` with a
machine-readable reason, never an extrapolated value; a block younger than the
comparison window SHALL likewise be `null` (`insufficient-span`) — identical
windows compare nothing, and a structurally-zero delta is not a measurement.

#### Scenario: Insufficient data is stated, not invented
- **WHEN** the block's first 14 days contain only 2 runs with reference-band aggregates
- **THEN** the EF delta is `null` with reason `insufficient-baseline` and the UI renders an honest gap

#### Scenario: A young block states no delta
- **WHEN** the block spans fewer days than the comparison window
- **THEN** EF and cadence deltas are `null` with reason `insufficient-span`, never a fabricated ±0

#### Scenario: A record counts only against pre-block history
- **WHEN** a run inside the block sets a 5k best that beats everything before the block start but not an earlier in-block run
- **THEN** the block's records feed lists the earlier in-block run's effort once, not both

### Requirement: Forward tilt for the current block only
For the current block the lens document SHALL additionally state: weeks and
planned km remaining (an undetailed week contributes its header km prorated
by the days still ahead of sync-today), the planned weekly-km silhouette
through race day, and plan-integrity flags for undetailed future weeks.
Complete blocks SHALL carry no forward-tilt section.

#### Scenario: Forward tilt disappears on completion
- **WHEN** the first sync after race day runs
- **THEN** the block's row flips to complete and its regenerated document has no forward-tilt section

### Requirement: Additive blockLens object in the data contract
The sync SHALL write an additive top-level `blockLens` object into
`garmin-data.js`: `lensVersion`, `current` (the current block's full lens
document, when one exists), and `past` (headline summaries only — identity,
window, percent executed, km, EF/cadence/gap deltas, records count — newest
race first). When no snapshots exist the object SHALL be absent entirely, and
all consumers SHALL treat absence as a normal state.

#### Scenario: Fresh install has no lens
- **WHEN** the sync runs with no plan snapshots in the archive
- **THEN** `garmin-data.js` contains no `blockLens` key and the dashboard renders without the section

#### Scenario: Past blocks stay summaries in the static contract
- **WHEN** five blocks exist in the archive
- **THEN** `blockLens.past` carries five summary slices and no week-level detail

### Requirement: The Block section renders live on /progress
`/progress` SHALL render a "The Block" section from `blockLens` static-first:
the current block as a live report card — phase strip, per-week execution row
in the established compliance-mark visual language, a headline stats line
(week N of M, percent executed, km done vs planned, EF delta, goal-gap delta,
records count), and the remaining-weeks planned-km silhouette. The week-N
highlight SHALL follow the viewer's live clock while all stated numbers remain
sync-time values. When `blockLens` is absent the section SHALL not render.

#### Scenario: Live report card from static data alone
- **WHEN** /progress loads with the archive API unreachable
- **THEN** the current block's full card, including week drill, renders from `garmin-data.js` alone

#### Scenario: Null metrics render honestly
- **WHEN** the EF delta is `null` with a reason
- **THEN** the headline shows an explicit insufficient-data mark, not a zero or a dash presented as a value

### Requirement: Per-week drill-down to days and runs
Each week row in the Block section SHALL expand to its day-level drill:
planned day vs matcher verdict (status and reason) and actuals, with matched
runs linking to `/run/:id`. The current block SHALL drill from static data;
past blocks SHALL fetch their full document from the archive API and degrade
to the established honest offline state on failure.

#### Scenario: Drilling a swapped day
- **WHEN** a week row is expanded and a day's verdict is swapped
- **THEN** the day shows the planned session, the swapped-in run's actuals, the reason, and a working link to that run's page

#### Scenario: Past-block drill offline
- **WHEN** a past block row is expanded while the archive API is down
- **THEN** the section shows the honest archive-offline state and the static summary remains intact

### Requirement: Past blocks render as retrospectives in the same layout
Past blocks SHALL appear as collapsed summary rows beneath the live card,
newest race first, expanding to the identical report-card layout rendered in
past tense (no forward tilt) from the API-fetched document.

#### Scenario: The first completed block becomes a retrospective
- **WHEN** the current block completes and a later sync runs
- **THEN** it appears as a past-block row whose expanded view matches the live card's layout minus forward tilt

### Requirement: Block-vs-block comparison is URL-addressable
The Block section SHALL offer a comparison of exactly two blocks — headline
metrics side by side with best-per-row marks — with the selection mirrored
into the URL query so a comparison is a shareable link. With fewer than two
blocks in the lens the comparison entry point SHALL be hidden.

#### Scenario: Comparison from a link
- **WHEN** /progress is opened with two valid race-date keys in the query
- **THEN** the comparison renders those two blocks side by side without further interaction

#### Scenario: Only one block exists
- **WHEN** the lens holds a single block
- **THEN** no comparison control is shown and the section renders normally
