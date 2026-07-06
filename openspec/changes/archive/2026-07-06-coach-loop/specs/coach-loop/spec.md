# coach-loop Specification (delta)

## ADDED Requirements

### Requirement: The sync reads the coach-owned plan fail-soft
The sync SHALL obtain the plan as JSON by running a short-lived node child
process that imports the live `plan-data.js` and prints `planData`, invoked
with a kill-timeout and a minimal environment allow-list. Any failure — nonzero
exit, timeout, or unparseable output — SHALL skip the compliance and briefing
steps for that sync with a warning, and SHALL NOT affect `garmin-data.js`
generation or any other sync step.

#### Scenario: A valid plan is ingested
- **WHEN** the nightly sync runs against a well-formed `plan-data.js`
- **THEN** the plan is available to the compliance step as parsed JSON matching
  the file's `planData` export

#### Scenario: A broken plan cannot break the sync
- **WHEN** the plan file throws on import, loops forever, or prints garbage
- **THEN** the sync logs a warning, emits `garmin-data.js` without a
  `compliance` block, and exits successfully

### Requirement: Plan snapshots are banked append-only and content-deduped
The sync SHALL store a snapshot of the plan (raw-text SHA-256, first-seen
date, and the dumped JSON) in a `plan_snapshots` table, inserting a new row
only when the hash is unseen. Compliance rows SHALL reference the snapshot
current at their scoring time, and no later plan edit SHALL change which
snapshot an already-scored day references.

#### Scenario: An unchanged plan adds no rows
- **WHEN** two consecutive syncs run against a byte-identical plan
- **THEN** `plan_snapshots` gains exactly one row across both syncs

#### Scenario: A plan edit cannot rewrite scored history
- **WHEN** a day is scored against snapshot A and the plan is edited afterwards
- **THEN** subsequent syncs bank snapshot B for new scoring while the already-
  scored day still references snapshot A

### Requirement: Actual activities are matched to planned days from plan intent
The compliance engine SHALL match archived activities to planned days per
scored week: same date and kind first (the largest-distance actual takes a
contested slot). A hybrid day — a cross or strength day carrying planned
running km — SHALL be scored on its run component, with same-day activities
of the day's own kind absorbed silently. At week close, missed run slots
SHALL be paired with same-week leftover runs globally by date proximity
(ties: earlier actual, then earlier planned day) and marked `swapped`, scored
against the planned day's targets; a run under half the slot's planned km
SHALL never pair. Remaining actual runs SHALL be `unplanned` (leftover
non-run activities are not reported); planned days past their date without a
match SHALL be `missed` (provisional until week close); future days SHALL be
`pending`. Session intent (kind, load, zone, km) SHALL always come from the
plan snapshot, never derived from the activity.

#### Scenario: A hybrid day is scored on its run component
- **WHEN** a "Spin + Easy Run" cross day with 4 planned km matches a 3.9 km
  run and a same-day indoor-cycling activity
- **THEN** the day scores `done` against the run, and the cycling activity is
  absorbed without producing an unplanned row

#### Scenario: A same-day run is matched
- **WHEN** a 16 km run is archived on a date whose snapshot plans a 16 km long run
- **THEN** the day's compliance row is `done`, carrying planned and actual values

#### Scenario: A day swap is recognized at week close
- **WHEN** a week closes with Friday's planned threshold unrun and an unplanned
  quality run archived on Saturday
- **THEN** Friday's row becomes `swapped`, scored against Friday's targets, and
  Saturday's run is consumed by the swap

#### Scenario: An extra run is unplanned, a skipped day is missed
- **WHEN** a week closes containing one run with no planned counterpart and one
  planned run-day with no activity at all
- **THEN** the former is reported `unplanned` and the latter `missed`

### Requirement: Scoring is coarse, reasoned, and leaves judgment to the coach
Matched runs SHALL be scored from structured plan fields only: distance ratio
≥ 85% of planned km with consistent intensity → `done`; ratio ≥ 50% or
inconsistent intensity → `partial` with a machine-readable reason (`distance`
or `intensity`); ratio < 50% → `missed`. Intensity SHALL be checked only for
Easy/Moderate-intent runs (average HR above 85% of max HR → inconsistent);
Hard-intent runs SHALL be scored on distance alone. Strength and cross days
SHALL be `done` on presence of a matching activity and `missed` on absence,
never `partial`.

#### Scenario: A properly easy run is done
- **WHEN** a planned 5 km Easy run matches a 5.1 km actual at 74% of max HR
- **THEN** the row scores `done`

#### Scenario: An easy day run too hard is flagged, not judged
- **WHEN** a planned Easy run matches an actual at 88% of max HR
- **THEN** the row scores `partial` with reason `intensity`, and the briefing
  presents the flag alongside temperature and drift for the coach to judge

#### Scenario: Quality sessions are not rep-policed
- **WHEN** a planned Hard 8 km threshold session matches an 8 km actual run
  entirely in Z5
- **THEN** the row scores `done` — intensity is not evaluated for Hard intent

### Requirement: Compliance is versioned and recomputable against original snapshots
Compliance rows SHALL carry a `compliance_version`. Each sync SHALL recompute
the open week and the most recently closed week idempotently; older weeks
SHALL be recomputed only when the version bumps, and any recomputation SHALL
score each day against the snapshot it originally referenced.

#### Scenario: Nightly recomputation is idempotent
- **WHEN** the sync runs twice with no new activities and no plan change
- **THEN** the compliance rows are unchanged after the second run

#### Scenario: A version bump preserves historical intent
- **WHEN** `compliance_version` is increased and the next sync runs
- **THEN** all rows are rescored using each day's originally-referenced
  snapshot, not the current plan

### Requirement: The data contract gains an independent compliance block
`garmin-data.js` SHALL gain a top-level `compliance` block — version, per-day
rows (date, planned kind/km/load/title, status, reason, actual km/pace/HR when
matched) and per-week aggregates (planned vs actual km, runs done/planned)
covering the plan block's range up to today — emitted all-or-nothing in a fail
domain independent of `insights`: a plan failure SHALL drop `compliance` while
`insights` survives, and an archive/metrics failure SHALL drop `insights`
while `compliance` survives. `validate_data.py` SHALL validate the block's
shape when present.

#### Scenario: Fail domains are independent
- **WHEN** the metrics engine raises while the plan ingests cleanly
- **THEN** the emitted file carries `compliance` without `insights`, and both
  the sync and contract validation succeed

### Requirement: A coach briefing is generated deterministically every sync
After `garmin-data.js` is written, the sync SHALL render `coach-briefing.md`
into the data directory via temp-file-and-rename, from already-computed inputs
in a fixed section order: days-to-race and current-week arithmetic; per-day
plan-vs-actual for the closing and open weeks (with temperature and drift
alongside intensity flags); records and best efforts; the trajectory triple
(Riegel vs Garmin vs goal) with closing rate; efficiency and cadence tails
with sample-size caveats; today's readiness; the coach-log tail; and profile
constants. Briefing failure SHALL NOT affect `garmin-data.js` or the sync's
exit status.

#### Scenario: The briefing contains the ritual's inputs
- **WHEN** a sync completes with archive, metrics, and plan all healthy
- **THEN** `coach-briefing.md` exists with every fixed section populated from
  the same numbers the contract file carries

#### Scenario: Briefing failure is invisible to the dashboard
- **WHEN** briefing rendering raises after `garmin-data.js` was written
- **THEN** the contract file is untouched and the sync exits successfully with
  a warning

### Requirement: The briefing carries staleness notes and integrity warnings
The briefing SHALL include plan-staleness notes — quality-session pace targets
parsed defensively from the plan's pace strings and compared against
fitness-implied paces (best rolling-12-week 10k effort for threshold intent,
the race goal pace for goal-pace intent), with unparseable strings skipped
silently — and plan-integrity warnings for `days: null` on future weeks and
week-header km that disagree with the week's day sum.

#### Scenario: A stale threshold target is noted
- **WHEN** the plan's threshold target is slower than the fitness-implied
  threshold pace by more than the tolerance
- **THEN** the briefing carries a staleness note naming the session, the
  target, and the implied pace

#### Scenario: An undetailed future week is a warning
- **WHEN** a future week in the current snapshot has `days: null`
- **THEN** the briefing carries a plan-integrity warning naming that week

### Requirement: The /coach skill enforces the ritual's write contract
The repository SHALL provide a `/coach` skill (one adaptive prompt, no modes)
that reads `coach-briefing.md` and the live plan, and when editing the plan:
validates the complete new plan text with the existing plan validator before
any write, writes only the canonical plan file (resolved symlink at home, or
instructs the `plan:push` flow away), preserves the week-km invariant, and
appends a dated `coach.log` entry describing every adjustment. The skill SHALL
NOT write the plan when validation fails and SHALL NOT modify `garmin-data.js`.

#### Scenario: An edit is validated then logged
- **WHEN** a `/coach` session adjusts a future session's pace target
- **THEN** the new plan text passes validation before the file is written, and
  the plan's `coach.log` gains a dated entry describing the change

#### Scenario: A failing validation blocks the write
- **WHEN** an edit would produce a plan the validator rejects
- **THEN** the live plan file is left byte-identical and the session surfaces
  the validation error instead
