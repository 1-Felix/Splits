## ADDED Requirements

### Requirement: Second, ingest-fed instance for an additional athlete
The same published image SHALL support running an additional independent
instance for a second athlete whose telemetry is produced by the ingest builder
rather than `sync_garmin.py`. Such an instance SHALL run with no Garmin
credentials, with the Garmin sync disabled, with `SPLITS_INGEST_TOKEN` set to
enable ingestion, and with its own data volume and `plan-data.js`. The two
instances SHALL differ only by environment and mounted volume — no per-athlete
code branch — and SHALL share nothing but the image.

#### Scenario: Deploy an ingest-fed instance
- **WHEN** the image is run as a second compose service with its own volume, no Garmin credentials, the Garmin sync disabled, and `SPLITS_INGEST_TOKEN` set
- **THEN** the dashboard becomes reachable and its telemetry is produced from ingested runs rather than a Garmin sync

#### Scenario: The second instance never runs a Garmin sync
- **WHEN** the ingest-fed instance boots or runs on its schedule
- **THEN** it does not spawn `sync_garmin.py` and does not require Garmin credentials to serve the dashboard

#### Scenario: Instances are isolated
- **WHEN** data is written to one instance's volume (telemetry, plan, or banked runs)
- **THEN** the other instance's data is unaffected
