# activity-archive Specification (delta)

## MODIFIED Requirements

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
sleep payload, falling back to
the dedicated resting-heart-rate endpoint whenever that value is null — including
when the payload itself is present but carries no device data. Promoted columns
SHALL be independently nullable, so a date may carry no sleep metrics while still
carrying rolling HRV values. The record's readiness snapshot SHALL be retained in
its existing column and SHALL NOT be mistaken for a raw payload.

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

## ADDED Requirements

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
