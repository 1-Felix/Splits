# add-ingest-archive — Proposal

## Why

Ingest-fed instances (Max's) bank every Health Connect run forever in
`ingested-runs.json` — full HR and speed sample series included — but surface
only the last 6 runs with detail (`RECENT = 6` in `ingest_builder.py`).
Everything older collapses into heatmap dots and weekly aggregates, and every
archive-backed surface (/archive, /run/:id, /compare, the cockpit heatmap
day-drill, the progress drill panels) is dead. Over a 40-week training plan
that is a growing loss of history the instance already possesses. The
2026-07-17 instance-aware-chrome pass made those dead surfaces honest (hidden
nav/drills, "No archive on this instance"); this change makes them *live*.

## What Changes

- `ingest_builder.py` additionally writes an `activity-archive.db` in the
  **same schema** the Garmin sync pipeline writes, on the ingest instance's
  own volume. Two producers, one standardized artifact, zero read-path
  changes: `handleArchive`'s existing SQL, degradations ("no map_tiles table
  = no tiles yet", "no streams column/value = no streams"), and tonight's
  `/api/status` `archive` flag light everything up the moment the file exists.
- Per-run archive rows are distilled **at build time** (streams JSON, splits,
  promoted query fields) from the banked HR/speed samples, via distiller code
  **shared with `sync_garmin.py`** (extracted into a common Python module, not
  duplicated).
- Health Connect session UIDs (UUID strings) map to the archive's numeric id
  space via a **stable derived numeric id** (truncated hash of the UID) —
  deterministic, stateless, collision-checked at build time.
- Honest absences remain absent: no GPS route/basemap, no elevation, no
  per-sample cadence (Samsung Health writes none of these) — the run page's
  existing degradation modes cover all three.
- Records the already-shipped 2026-07-17 groundwork as deltas: archive-api's
  404-for-unprovisioned split and dashboard-sync's instance-shape status flags.

## Capabilities

### New Capabilities
- `ingest-archive`: build-time construction of the activity archive database
  from banked ingested runs — schema parity with the Garmin archive, derived
  numeric ids, distilled per-run streams, rebuild/idempotency semantics, and
  degradation rules for fields the ingest source cannot supply.

### Modified Capabilities
- `archive-api`: a database that does not exist is "not provisioned" → 404
  with a distinct error body; 503 is reserved for an existing-but-unusable
  database (outage). *(Shipped 2026-07-17 in the instance-aware-chrome pass —
  delta records it.)*
- `dashboard-sync`: `GET /api/status` additionally reports instance shape:
  `ingestFed` (instance is fed by `/api/ingest`, no Garmin sync to offer) and
  `archive` (an archive database is present and answerable). *(Shipped
  2026-07-17 — delta records it.)*

## Impact

- **Code**: `ingest_builder.py` (archive write pass + id derivation); a new
  shared distiller module extracted from `sync_garmin.py` (refactor —
  behavior-neutral for the Garmin pipeline); `serve.mjs` and the dashboard
  pages are already done (2026-07-17) and need no further changes.
- **Data**: a new `activity-archive.db` appears on ingest-instance volumes
  (Max's `splits-max-data`); Felix's Garmin volume untouched.
- **UX**: /archive, /run/:id, /compare, heatmap day-drill, and progress drill
  panels become fully functional on Max's instance; the instance-aware hiding
  from 2026-07-17 auto-reverses via the `/api/status` `archive` flag.
- **Tests**: distiller-parity tests (shared module keeps `sync_garmin.py`
  output byte-identical); ingest-archive build tests (ids, streams shape,
  idempotent rebuild); slim-render/browser coverage flips from "archive
  absent" fixtures to both-shapes coverage.
- **Deployment**: ships in the existing single image; no compose/env changes.
