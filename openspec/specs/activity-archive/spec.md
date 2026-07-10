# activity-archive Specification

## Purpose
Durable, deduplicated archive of the account's complete Garmin history — activity summaries, per-activity detail, and daily wellness — kept independently of the dashboard's rolling window, with backfill, verification, and fail-soft behavior.

## Requirements

### Requirement: Every synced activity is stored durably and deduplicated
The system SHALL maintain a durable activity archive (a SQLite database in the
configured data directory) holding one record per Garmin activity, keyed by the
Garmin activity id. Each record SHALL preserve the complete raw activity
summary payload as returned by Garmin, alongside promoted fields for querying
(at minimum: local start time and activity type). Archived activities SHALL be
retained regardless of any rolling window used by the dashboard data files.

#### Scenario: An activity outlives the dashboard's rolling window
- **WHEN** an activity was archived and enough time passes that it falls outside
  the 30-month window used to build `garmin-data.js`
- **THEN** the activity remains present in the archive with its raw summary payload

#### Scenario: Re-syncing does not duplicate
- **WHEN** a sync fetches an activity whose id already exists in the archive
- **THEN** the existing record is updated in place and the archive still contains
  exactly one record for that id

### Requirement: Every sync appends to the archive
Every sync — boot, scheduled nightly, and manual "Sync now" — SHALL upsert all
fetched activity summaries into the archive. On conflict the freshly fetched
summary SHALL win, so Garmin-side edits (e.g. a renamed activity) propagate.
The sync SHALL NOT delete archive records under any circumstances; an activity
no longer returned by Garmin SHALL remain archived.

#### Scenario: A new run appears after a normal nightly sync
- **WHEN** the nightly sync runs after a new activity was recorded on Garmin
- **THEN** the archive contains that activity after the sync completes

#### Scenario: A Garmin-side rename propagates
- **WHEN** an archived activity's name is changed on Garmin Connect and a sync runs
- **THEN** the archived record reflects the new name while keeping the same id

#### Scenario: Deletion on Garmin does not remove archived data
- **WHEN** an archived activity is deleted on Garmin Connect and subsequent syncs run
- **THEN** the activity remains in the archive

### Requirement: Per-activity detail is archived write-once
The archive SHALL store, per activity, the raw detail payload
(`get_activity_details` response) as fetched from Garmin. Detail SHALL be
written only on a successful fetch and SHALL NOT be overwritten with an empty
or failed result. Regular syncs SHALL top up missing detail for archived
activities, newest first, bounded by a per-sync cap so a backlog is worked off
across successive syncs. Detail payloads already present in the per-activity
API cache SHALL be reused without a network fetch.

#### Scenario: A new activity's detail is archived
- **WHEN** a sync archives a new activity and the detail fetch succeeds (within the per-sync cap)
- **THEN** the raw detail payload is stored on that activity's archive record

#### Scenario: A failed detail fetch does not erase existing detail
- **WHEN** an activity already has archived detail and a later detail fetch fails
- **THEN** the previously archived detail remains unchanged

#### Scenario: A backlog drains across syncs
- **WHEN** more activities lack detail than the per-sync cap allows (e.g. after a long gap)
- **THEN** each sync fetches detail for up to the cap, newest first, until no
  archived activity lacks detail

### Requirement: Full-history backfill is available, idempotent, and resumable
The system SHALL provide an explicit backfill mode that populates the archive
with the account's complete activity history: it SHALL walk backwards in time
until it detects the account's start (no activities in consecutive prior
periods) rather than relying on a hardcoded start date, upsert every summary,
and fetch detail for every archived activity that lacks it with no per-sync
cap. Backfill SHALL be safe to interrupt and re-run: progress is persisted as
it goes, completed work is not repeated, and re-running after completion
SHALL result in no duplicate records.

#### Scenario: Backfill captures the whole account
- **WHEN** backfill runs to completion on this account
- **THEN** the archive contains every activity Garmin returns for the account's
  lifetime (earliest known: 2024-05-12) with detail present for each

#### Scenario: An interrupted backfill resumes where it left off
- **WHEN** backfill is interrupted partway and then re-run
- **THEN** already-archived summaries and details are not re-fetched needlessly
  and the run completes the remainder

### Requirement: Each sync records a daily wellness snapshot
Each sync SHALL upsert a wellness record for every date in its sleep window,
keyed by date, storing the **raw Garmin sleep and HRV payloads verbatim**
alongside promoted columns derived from them (sleep duration and stage seconds,
sleep score, respiration, body-battery change, resting heart rate, HRV
last-night average, weekly average, balanced-range bounds, and status). Raw
payloads SHALL be upgrade-only: a stored payload carrying device data SHALL NOT
be replaced, while a stored payload carrying none MAY be replaced by one that
does — so a night Garmin has not yet finalised can be filled in, and no stored
night can ever be thinned. Promoted columns SHALL remain recomputable from the
stored payloads without network access, and a later sync on the same date SHALL
refresh that date's promoted values. Resting heart rate SHALL be read from the
sleep payload, falling back to the dedicated resting-heart-rate endpoint whenever
that value is null — including when the payload itself is present but carries no
device data. Promoted columns SHALL be independently nullable, so a date may
carry no sleep metrics while still carrying rolling HRV values. The record's
readiness snapshot SHALL be retained in its existing column and SHALL NOT be
mistaken for a raw payload.

#### Scenario: The nightly sync banks the window's wellness
- **WHEN** a sync runs on a given local date
- **THEN** the archive contains a wellness record for each date in the sync's
  sleep window, each carrying the raw sleep payload and its promoted values

#### Scenario: A second sync the same day refreshes, not duplicates
- **WHEN** two syncs run on the same local date
- **THEN** the archive contains exactly one wellness record for that date, with
  promoted values reflecting the later sync

#### Scenario: A substantive stored payload is never overwritten
- **WHEN** a date already holding a sleep payload with device data is fetched
  again
- **THEN** the stored payload is unchanged and only promoted columns are
  refreshed

#### Scenario: An unfinalised night is filled in by a later sync
- **WHEN** a date holds a sleep payload carrying no device data and a later sync
  fetches a payload for it that does
- **THEN** the stored payload is replaced by the one carrying data

#### Scenario: A stored night is never thinned
- **WHEN** a date holding a sleep payload with device data is fetched again and
  Garmin returns a payload carrying none
- **THEN** the stored payload is unchanged

#### Scenario: A missed night self-heals
- **WHEN** the sync did not run for a night that still falls inside the next
  sync's sleep window
- **THEN** that night's wellness record is banked by the next sync

#### Scenario: Resting heart rate survives a night off the wrist
- **WHEN** a date's sleep payload is present but its `restingHeartRate` is null
- **THEN** resting heart rate is fetched from the dedicated endpoint and stored

#### Scenario: Rolling HRV values outlive a night with no sleep data
- **WHEN** a date carries no sleep metrics but its HRV payload carries a weekly
  average and a balanced range
- **THEN** the record stores null sleep metrics and the populated HRV values

### Requirement: Wellness backfill is available, idempotent, and resumable
The sync SHALL offer a wellness backfill mode that walks every date from the
archive's earliest activity to the current date, fetching and banking the raw
sleep and HRV payloads for dates not yet fetched. The mode SHALL be resumable —
using the archive itself as its cursor — SHALL be a no-op when coverage is
complete, SHALL rate-limit its requests, and SHALL record its own completion
marker distinct from the activity backfill's. A date whose fetch fails SHALL
remain unfetched so a later run retries it.

#### Scenario: An interrupted backfill resumes
- **WHEN** a wellness backfill is interrupted and re-run
- **THEN** it fetches only the dates not already banked and converges on
  complete coverage

#### Scenario: A completed backfill is a no-op
- **WHEN** a wellness backfill runs against an archive with full coverage
- **THEN** it performs no writes and no fetches

#### Scenario: A failed date is retried, not marked done
- **WHEN** a date's fetch raises
- **THEN** that date remains unfetched and the next run attempts it again

#### Scenario: Backfill completion is separately answerable
- **WHEN** the archive metadata is inspected
- **THEN** activity-backfill completion and wellness-backfill completion are
  distinct records

### Requirement: Unfetched, empty, and populated wellness days are distinguishable
A wellness record SHALL carry a fetch timestamp distinguishing three states: a
date never requested (no timestamp, no metrics), a date requested for which the
device recorded nothing (timestamp set, metrics null), and a date with data
(timestamp set, metrics populated). Consumers SHALL be able to tell a genuine
absence from a missing fetch, so a chart never draws across a day it merely
failed to ask about.

#### Scenario: A night the watch was not worn
- **WHEN** a date is fetched and Garmin returns no sleep data
- **THEN** the record carries a fetch timestamp and null metrics

#### Scenario: A night never requested
- **WHEN** a date has never been fetched
- **THEN** the record is absent or carries no fetch timestamp, and is reported
  as a coverage gap

### Requirement: Wellness coverage is verifiable
The archive verification mode SHALL report wellness coverage over the expected
span (earliest activity date to the current date) — records present, records
fetched, records carrying data, and the list of gaps. A fetched date with no
device data SHALL NOT be reported as a gap. Gaps SHALL cause a non-zero exit only
once the wellness backfill has recorded its completion, so that deploying the
nightly banking before running the backfill does not fail the health check: an
archive that has never reached full coverage cannot regress from it.

#### Scenario: Healthy wellness coverage
- **WHEN** verification runs against an archive with every date fetched
- **THEN** it reports zero gaps and exits zero, regardless of how many dates
  carry no device data

#### Scenario: Coverage regression fails the check after the backfill
- **WHEN** the backfill has recorded completion and dates within the expected
  span have never been fetched
- **THEN** verification names them and exits non-zero

#### Scenario: Gaps are reported but not fatal before the backfill
- **WHEN** the nightly sync has banked recent nights but the backfill has never
  completed
- **THEN** verification reports the historical gaps and exits zero

### Requirement: Archiving is fail-soft and the archive is rebuildable
An archive failure of any kind (locked file, corrupt database, full disk) SHALL
NOT cause the sync to fail, block, or delay the writing of `garmin-data.js`;
archive errors SHALL be logged as warnings. A corrupt archive database SHALL be
quarantined (renamed aside) and a fresh archive created on the next archive
write. The archive SHALL be fully reconstructable from Garmin via the backfill
mode.

#### Scenario: Archive failure does not break telemetry
- **WHEN** the archive database cannot be written during a sync
- **THEN** the sync still writes `garmin-data.js` successfully and reports the
  archive problem as a warning

#### Scenario: A corrupt database heals
- **WHEN** the archive file is corrupt at the next sync
- **THEN** the corrupt file is renamed aside, a fresh archive is created, and a
  subsequent backfill restores full history

### Requirement: Archive integrity is verifiable
The system SHALL provide a verification mode that reports, at minimum: total
activity count, counts by year and by activity type, detail coverage (archived
activities with and without detail), wellness record count, and the archive's
date bounds. Verification SHALL exit non-zero when coverage regresses against
the archive's recorded expectations, so it can serve as an acceptance check
after backfill and a periodic health check.

#### Scenario: Post-backfill acceptance
- **WHEN** verification runs after a completed backfill
- **THEN** it reports the totals and date bounds and exits zero when the archive
  matches expectations

#### Scenario: A regression is caught
- **WHEN** the archive has lost previously recorded coverage (e.g. fewer
  activities than the recorded expectation)
- **THEN** verification exits non-zero and names what regressed

### Requirement: Archive location follows the existing data-directory resolution
The archive database SHALL live in the same data directory as the other
personal data files, resolved exactly as the sync already resolves it
(`SPLITS_DATA_DIR` when set — `/data` in the container — otherwise the project
directory for local development). Local archive copies SHALL be treated as
disposable (the canonical archive is the server volume's) and SHALL be
excluded from version control.

#### Scenario: Container archives into the volume
- **WHEN** a sync runs inside the container
- **THEN** the archive database is created and updated inside the mounted data volume

#### Scenario: Local development needs no configuration
- **WHEN** a developer runs the sync locally without `SPLITS_DATA_DIR`
- **THEN** the archive database is created in the project directory and is
  ignored by git

### Requirement: Distilled run detail is stored alongside the raw payload
The archive schema SHALL gain an additive column holding each run's distilled
detail (`activities.detail_distilled_json`), applied by the existing
idempotent schema-version migration. The distilled shape SHALL be exactly the
recent-run `detail` contract of `garmin-data.js`, produced by the same
distillation implementation the sync uses for recent runs (one distiller, two
callers). The sync SHALL distill a run when its raw detail is archived, and a
recovery pass SHALL distill already-archived runs from their stored raw
payloads without network access. Raw payloads SHALL remain unmodified.

#### Scenario: A topped-up run gains distilled detail
- **WHEN** the sync archives a run's raw detail payload
- **THEN** the same sync stores the run's distilled detail in the new column

#### Scenario: Already-archived runs are distilled locally
- **WHEN** the distillation pass runs over an archive with runs that have raw
  detail but no distilled detail
- **THEN** every such run gains distilled detail computed from its stored raw
  payload, with no Garmin API calls

#### Scenario: The migration is additive and reversible by ignoring
- **WHEN** an older application version opens a database at the new schema
  version
- **THEN** all pre-existing reads work unchanged (the new column is ignored)

#### Scenario: Distillation shares one implementation
- **WHEN** the same run is distilled via the recent-runs path and via the
  archive path
- **THEN** both produce the same distilled object

### Requirement: Distilled coverage is verifiable
The archive verification mode SHALL report distilled-detail coverage (runs
with raw detail vs runs with distilled detail) and SHALL exit non-zero when
distilled coverage regresses behind raw-detail coverage.

#### Scenario: Healthy distilled coverage
- **WHEN** verification runs after the distillation pass and a normal sync
- **THEN** it reports distilled coverage equal to raw-detail coverage

#### Scenario: A distillation gap is caught
- **WHEN** runs hold raw detail without distilled detail after a completed
  sync
- **THEN** verification exits non-zero naming the gap
