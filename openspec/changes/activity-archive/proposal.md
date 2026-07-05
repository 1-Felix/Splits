# Proposal: activity-archive

## Why

SPLITS has no memory: every sync overwrites `garmin-data.js` with a rolling window
(30 monthly points, 26 weekly points, 365-day heatmap, per-run detail for only the
6 most recent runs), so the deep progress insights the project is aiming for —
pace-at-HR trends, in-run best efforts, year-over-year comparison (ROADMAP stages
2–4) — have nothing to stand on. The account's history starts 2024-05-12 (536
activities as of 2026-07-05) and around November 2026 the 30-month window slides
past that start and begins silently dropping the earliest data; a durable archive
built now is cheap (~540 cached API calls to backfill) and impossible to regret.

## What Changes

- New durable **activity archive**: a SQLite database in the data directory that
  stores every Garmin activity ever synced — summary fields plus the per-activity
  detail payload (splits, HR/cadence/pace streams) — for all activity types, not
  just runs.
- **One-time backfill**: an explicit entry point pulls the full account history
  (May 2024 → today) including per-activity detail into the archive, reusing the
  existing per-activity cache so re-runs are cheap.
- **Append-on-sync**: every sync (boot, nightly, manual "Sync now") upserts new
  and updated activities into the archive after fetching. The archive is
  append-only in spirit: activities are never deleted by the sync, and a failed
  archive write must not break the telemetry sync that feeds the dashboard.
- **Daily wellness snapshot**: each sync also upserts one row of that day's
  wellness values (resting HR, HRV, sleep, readiness inputs) — data the sync
  already fetches and currently discards outside a 14-night window. Historical
  wellness backfill is out of scope.
- **No dashboard change**: `garmin-data.js` and the dashboard contract stay
  exactly as they are. The archive sits behind the sync as the foundation for
  ROADMAP stage 2 (`insight-metrics`); nothing reads it yet except validation
  tooling.
- Local dev and container resolve the archive location the same way the existing
  data files do (`SPLITS_DATA_DIR`, falling back to the project directory).

## Capabilities

### New Capabilities
- `activity-archive`: durable storage of all synced Garmin activities and their
  detail — schema/identity guarantees (dedupe by Garmin activity id), backfill of
  full account history, append/upsert on every sync, a daily wellness snapshot
  row per sync day, survival independent of the rolling dashboard window, and
  fail-soft behavior so archiving never blocks the dashboard sync.

### Modified Capabilities
- `containerized-deployment`: the "personal data persists in a mounted volume"
  requirement grows to include the activity archive database — it must live in
  the data volume and survive restarts and image upgrades like the other
  personal data files.

## Impact

- **`sync_garmin.py`**: gains an archive-write step after activity fetch, and a
  backfill mode (flag or companion script) for the one-time full-history pull.
- **New Python module** for the archive store (schema, upsert, integrity checks) —
  stdlib `sqlite3`, so `requirements.txt`, the Dockerfile, and the image size are
  unchanged.
- **Data volume**: one new file (the SQLite database) alongside `garmin-data.js`,
  `plan-data.js`, the token cache, and the API cache. `docker-compose.yml`
  unchanged (same volume mount).
- **`serve.mjs` / dashboard / `plan-data.js`**: untouched.
- **`.gitignore`**: exclude the local archive database (personal data, like the
  existing symlinked data files).
- **Validation**: a way to assert archive integrity (row counts vs. Garmin,
  detail coverage) so backfill completeness is verifiable, in the spirit of
  `validate_data.py`.
- **README / ROADMAP**: document the archive's role and the backfill ritual.
