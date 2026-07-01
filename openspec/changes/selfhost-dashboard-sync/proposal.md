## Why

Splits today is a developer's workspace, not something a stranger can self-host. The Garmin sync is a manual `python sync_garmin.py` on the author's laptop; the dashboard freezes its date at the last sync run; and there is no packaging story at all. The goal is to turn it into a "drop credentials into `docker-compose.yml`, run `docker compose up`, open the dashboard" tool — where sync is a button, data persists in a volume, and the dashboard tracks the real clock — without disturbing the AI-coach workflow that edits `plan-data.js`.

## What Changes

- **Sync from the dashboard.** A "Sync now" control triggers a Garmin pull via a new server endpoint (`POST /api/sync`) that spawns the existing, unchanged `sync_garmin.py`. A status endpoint exposes last-sync time and an in-progress flag. On success the page reloads to show fresh telemetry. (Start simple: spinner + "last synced" timestamp; no live log streaming yet.)
- **Sync runs on a schedule too.** The container syncs once on boot (if data is missing/stale) and nightly via an in-container cron, so a fresh deploy isn't stuck on demo data and stays current unattended.
- **Graceful first-run handling.** If a sync can't authenticate or reach Garmin (wrong/missing credentials, network failure), the dashboard still comes up on demo/last data with a "connect Garmin" prompt instead of crash-looping. This account does not use MFA, so first run needs only credentials in compose; steady-state reuses the cached token in the volume.
- **The dashboard tracks the real clock.** Race countdown, the week plan's "today" highlight (derived from each row's date, not a hand-rolled `status`), the "Road to Sonthofen" current-week highlight, and a time-of-day greeting all follow the live clock. Telemetry (heatmap, recent runs) stays anchored to the last sync and gains a "synced ·  <date>" / staleness caption. A midnight-rollover keeps a page left open overnight correct. This retires the manual Monday `status:'today'` rolling.
- **Fully containerized, one image.** A single `ghcr.io/1-felix/splits` image bundles Node (serves the page + API) and Python (runs the sync). GitHub Actions builds and pushes it on `main` and on tags (amd64-only; multi-arch is a later one-line toggle).
- **Credentials in compose, data in a volume.** Garmin credentials and profile overrides are set as environment variables in `docker-compose.yml`. `garmin-data.js`, `plan-data.js`, and the token/raw caches live in a mounted `/data` volume and survive restarts and image upgrades. `plan-data.js` is seeded from a shipped default on first boot; the AI-coach workflow continues to edit it (now in the volume) — **untouched by this change**.
- **App/data split.** Application code ships in the image; personal data is served from and written to `/data`. `serve.mjs` serves `garmin-data.js` / `plan-data.js` from the data dir; `sync_garmin.py` writes there via an env-configurable path (with a local-dev fallback so `pnpm dev` still works outside Docker).

## Capabilities

### New Capabilities
- `dashboard-sync`: Triggering and scheduling Garmin syncs — the dashboard "Sync now" control, the `POST /api/sync` and `GET /api/status` endpoints, sync-on-boot, nightly in-container scheduling, reload-on-success, and graceful degradation when credentials/token/MFA are unavailable.
- `live-dashboard`: Date/time-driven dashboard behavior — separating live "display-today" (countdown, week-status derivation, block highlight, time-of-day greeting, midnight rollover) from last-sync-anchored telemetry (heatmap, recent runs) with an explicit freshness/staleness indicator.
- `containerized-deployment`: Self-host packaging — the single Node+Python image, `docker-compose.yml` with credentials and a persistent `/data` volume, the app-in-image vs data-in-volume split with default-seeded `plan-data.js`, and the GitHub Actions → GHCR publish pipeline.

### Modified Capabilities
<!-- None — no existing specs in openspec/specs/. -->

## Impact

- **Code:** `serve.mjs` (new API routes + serve data files from `/data`), `sync_garmin.py` (env-configurable output/cache paths), `Running Dashboard.dc.html` + `support.js` (live-clock derivation, sync control, freshness caption), `running-data.js` (data-file resolution).
- **New files:** `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `plan-data.default.js`, container entrypoint script, `.github/workflows/` publish workflow.
- **Data layout:** introduces `/data` as the canonical home for `garmin-data.js`, `plan-data.js`, `.garmin_tokens/`, `.garmin_cache/`. `plan-data.js` moves out of the committed tree into a default-seeded volume file.
- **Config/secrets:** Garmin credentials, `ATHLETE_*`, `TZ`, and `SPLITS_DATA_DIR` become container environment variables; credentials are plaintext in `docker-compose.yml` (the standard self-host bargain, documented).
- **Surface/security:** `POST /api/sync` is unauthenticated (LAN-trust, single-user, documented) — it can pull Garmin using container-held credentials.
- **Unchanged:** the AI-coach contract (`plan-data.js` ownership, the `running-data.js` merge shape, the dashboard's data contract) and the existing demo-data fallback.
