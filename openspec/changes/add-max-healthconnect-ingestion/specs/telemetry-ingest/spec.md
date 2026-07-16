## ADDED Requirements

### Requirement: Authenticated ingest endpoint
The server SHALL expose `POST /api/ingest` guarded by a bearer token equal to
`SPLITS_INGEST_TOKEN`. When `SPLITS_INGEST_TOKEN` is unset the route SHALL NOT
exist — the request SHALL fall through to a 404 as for any unknown path — so an
instance that does not opt in never exposes a write endpoint. Requests SHALL be
size-capped, and a banked run SHALL be written atomically.

#### Scenario: Authorized push is accepted
- **WHEN** a client POSTs a valid run payload with a bearer token matching `SPLITS_INGEST_TOKEN`
- **THEN** the server banks the run and responds with success

#### Scenario: Missing or invalid token
- **WHEN** a client POSTs to `/api/ingest` without a valid bearer token while the token is configured
- **THEN** the server responds 401 and banks nothing

#### Scenario: Endpoint absent when not opted in
- **WHEN** `SPLITS_INGEST_TOKEN` is unset and a client POSTs to `/api/ingest`
- **THEN** the route does not exist and the server responds 404

#### Scenario: Oversized body is rejected
- **WHEN** a request body exceeds the configured size cap
- **THEN** the server responds 413 and banks nothing

### Requirement: Idempotent banking by session UID
The server SHALL bank runs keyed by their Health Connect session UID. Ingesting
a run whose UID is already banked SHALL update that run in place rather than
create a duplicate.

#### Scenario: Re-ingesting the same run
- **WHEN** a run with a session UID that is already banked is ingested again
- **THEN** the stored set still contains exactly one run for that UID, updated to the latest payload

### Requirement: Builder derives the telemetry contract from banked runs
After a successful ingest, and on server boot, the server SHALL rebuild the
instance's `garmin-data.js` from the banked runs, producing the `athleteData`
telemetry contract. The build SHALL reuse the project's existing derivations —
CTL/ATL via the training-load EWMA and race predictions via Riegel — so a
non-Garmin instance renders the dashboard's derived panels consistently with the
Garmin pipeline.

#### Scenario: A new run appears on the dashboard
- **WHEN** a run is ingested and the builder runs
- **THEN** the rebuilt telemetry includes that run in `recentRuns` and updates weekly volume, `ctl`/`atl`, monthly pace, `heatmapKm`, and `predictions`

### Requirement: Built telemetry honors contract invariants and omits non-goal fields
The builder's output SHALL satisfy the telemetry contract invariants: pace as
integer seconds per km, `heatmapKm` of length 365 ending on today, and all
`history.*` arrays ordered oldest→newest. The builder SHALL omit the non-goal
fields entirely (not emit empty values): `profile.vo2maxCurrent`,
`history.vo2max`, `readiness`, and `history.sleep`. The dashboard SHALL render
without error when those fields are absent.

#### Scenario: Output validates against the contract
- **WHEN** the builder produces telemetry from banked runs
- **THEN** pace fields are integer seconds/km, `heatmapKm.length === 365` with the last element being today, and history arrays are oldest→newest

#### Scenario: Non-goal fields are absent and the page degrades cleanly
- **WHEN** the telemetry omits `vo2max`, `readiness`, and `sleep`
- **THEN** the dashboard hides or empties those panels and renders the remaining panels without error

### Requirement: Weekly HR zones computed server-side
The builder SHALL compute weekly minutes-in-zone (`hrZones`) by binning each
run's heart-rate samples using zone bounds derived from `profile.maxHR`. Zone
policy SHALL live on the server, not in the bridge app.

#### Scenario: A run contributes minutes to the correct zones
- **WHEN** a run's heart-rate samples are binned against the `maxHR`-derived bounds
- **THEN** the resulting `hrZones` reflect the minutes spent in each zone for that week

### Requirement: Expanded run payload (scope expansion, design D9–D13)
The run payload SHALL accept the optional fields `maxHr`, `elevationGainM`,
`activeKcal`, `totalKcal`, `steps`, and `speedSamples[{tSec,mps}]` — validated
when present, null/empty when absent — and the endpoint SHALL additionally
accept a resting-heart-rate payload form `{ restingHeartRate: [{date, bpm}] }`,
banked apart from runs and keyed by date (idempotent upsert).

#### Scenario: Expanded run fields are banked
- **WHEN** a run payload carries the expanded optional fields
- **THEN** they are validated and stored on the banked run; absent fields bank as null

#### Scenario: Resting-HR series is banked apart from runs
- **WHEN** a client POSTs `{ restingHeartRate: [{date, bpm}] }` with a valid token
- **THEN** the days are upserted by date into a store separate from the run store, and re-pushing an overlapping window creates no duplicates

### Requirement: Calibrated and enriched derivations (scope expansion)
The builder SHALL calibrate zone bounds and load intensity from the best
max-HR evidence available (the higher of the explicit profile setting and the
observed per-run max; `220−age` only when neither exists), SHALL use Karvonen
HR-reserve bounds when a resting HR is banked, SHALL compute pace from the
moving effort (pauses stripped via the speed series) for `recentRuns`, monthly
pace, and the Riegel anchor, SHALL derive per-km splits and cadence
(steps ÷ moving minutes) when the source data exists, and SHALL emit
`energy.weekKcal` and `history.restingHr` — omitting each key entirely when its
source data is absent so the dashboard degrades per the one-image principle.

#### Scenario: Moving pace replaces elapsed pace when a speed series exists
- **WHEN** a banked run carries a speed series with a mid-run pause
- **THEN** its pace in `recentRuns`, monthly pace, and the Riegel anchor reflects moving time over moving distance

#### Scenario: Splits light up the existing run drill-down
- **WHEN** a banked run carries a speed series
- **THEN** its `recentRuns` entry carries a Garmin-shaped `detail` (splits, hrSeries, driftBpm, zoneMin, splitShape, elevGain)

#### Scenario: Expansion keys absent for a provider that lacks the data
- **WHEN** no banked run carries calories and no resting HR is banked
- **THEN** `energy` and `history.restingHr` are omitted entirely and the energy tile and RHR trend card do not render
