# activity-archive Specification (delta)

## ADDED Requirements

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
Each sync SHALL upsert one wellness record for the current local date, keyed by
date, containing the day's wellness values the sync already fetches (at
minimum: resting heart rate, HRV, and sleep hours when available) together with
the raw fetched payload. A later sync on the same date SHALL refresh that
date's record. Historical wellness backfill is explicitly out of scope.

#### Scenario: The nightly sync banks today's wellness
- **WHEN** a sync runs on a given local date
- **THEN** the archive contains a wellness record for that date with the fetched
  values and raw payload

#### Scenario: A second sync the same day refreshes, not duplicates
- **WHEN** two syncs run on the same local date
- **THEN** the archive contains exactly one wellness record for that date,
  reflecting the later sync

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
