## 1. App/data split foundation

- [x] 1.1 Add a data-directory resolver to `serve.mjs`: read `SPLITS_DATA_DIR` (default `/data`), fall back to the project dir when unset/missing so `pnpm dev` works unchanged.
- [x] 1.2 Route `GET /garmin-data.js` and `GET /plan-data.js` to serve from the resolved data dir; keep all other paths served from the image/project dir.
- [x] 1.3 Make `sync_garmin.py` write `garmin-data.js` and place `.garmin_tokens/` and `.garmin_cache/` under `SPLITS_DATA_DIR`, with a fallback to its own directory for local runs.
- [x] 1.4 Verify `pnpm dev` + manual `python sync_garmin.py` still produce a working dashboard with no `SPLITS_DATA_DIR` set (local-dev regression check).
- [x] 1.5 Create `plan-data.default.js` from the current `plan-data.js` content as the shipped default; stop committing the live `plan-data.js` (gitignore it like `garmin-data.js`).

## 2. Sync API + cadence (server)

- [x] 2.1 Add `POST /api/sync` to `serve.mjs` that spawns `sync_garmin.py` and resolves on completion with a structured success/error result.
- [x] 2.2 Add an in-flight lock so at most one sync runs; a trigger during a running sync returns "already running" instead of starting a second.
- [x] 2.3 Add `GET /api/status` returning last successful sync timestamp and an in-progress flag (derive last-sync from the data-file stamp/mtime).
- [x] 2.4 Ensure sync failures return a non-success status with a reason and never crash the server (soft-fail).

## 3. Dashboard sync control (frontend)

- [x] 3.1 Add a "Sync now" control to the dashboard that calls `POST /api/sync`, with a spinner/in-progress state from `GET /api/status`.
- [x] 3.2 On sync success, reload the page so new telemetry renders; on failure, surface the error without breaking the page.
- [x] 3.3 Show a "last synced · <date>" indication sourced from `GET /api/status` / the telemetry stamp.

## 4. Live clock (frontend)

- [x] 4.1 Compute a live `displayToday` from the viewer's local date; drive the race countdown from it instead of baked `today`.
- [x] 4.2 Derive the week plan's current-day highlight from each row's `date` vs `displayToday` (retire the hand-edited `status:'today'` for highlighting).
- [x] 4.3 Derive the training-block current/past week highlight from `displayToday` vs each week's `mon`/`sun`.
- [x] 4.4 Add a time-of-day greeting (morning/afternoon/evening) from local time.
- [x] 4.5 Keep the heatmap + recent runs anchored to the sync date; add the "synced · <date>" caption and a staleness hint when `displayToday` is past the sync date.
- [x] 4.6 Add a midnight-rollover timer so a page left open updates date-driven views without a manual reload.

## 5. Containerization

- [x] 5.1 Write a `Dockerfile` on a base with both Node and Python; install `requirements.txt`; copy app files; expose the server port.
- [x] 5.2 Write an entrypoint that seeds `/data/plan-data.js` from the default if absent (never overwrites existing), then launches the server; the boot sync (when data is missing/stale, soft-fail) and the nightly schedule run in-process in `serve.mjs`.
- [x] 5.3 Configure the nightly sync schedule in-process (`serve.mjs`, no cron daemon) honoring container `TZ`, overridable via env (`SYNC_AT=HH:MM`, default 04:00 local; `SYNC_ON_BOOT` toggle).
- [x] 5.4 Write `docker-compose.yml` that reads `GARMIN_EMAIL`/`GARMIN_PASSWORD` (+ optional `GARMIN_MFA`, `TZ`, `SYNC_AT`) from a git-ignored `.env` via `${VAR}` substitution, a named `/data` volume, port mapping, and `image: ghcr.io/1-felix/splits`.
- [x] 5.5 Add `.dockerignore` (exclude `node_modules`, `.venv`, `.git`, caches, local data/secrets).
- [x] 5.6 Build the image locally and verify a fresh `docker compose up` yields a working dashboard (demo data acceptable without creds) and that `/api/status` responds.

## 6. CI → GHCR

- [x] 6.1 Add a GitHub Actions workflow that builds and pushes `ghcr.io/1-felix/splits` on push to the default branch (tag `latest`) and on version tags (tag the version), amd64-only, using `GITHUB_TOKEN` with `packages: write`.
- [x] 6.2 Confirm the published image runs via the committed `docker-compose.yml` (pull-and-run smoke check).

## 7. Docs

- [x] 7.1 Update `README.md` with the self-host quickstart: `cp .env.example .env` + set credentials, `docker compose up`, open the dashboard; note data lives in the volume.
- [x] 7.2 Document the first-run path (credentials in `.env` → `docker compose up`; account uses no MFA) and the soft-fail behavior; note the optional `GARMIN_MFA=` / interactive seed path only as a fallback if MFA is ever enabled.
- [x] 7.3 Document the LAN-trust posture of `POST /api/sync` and the plaintext-credentials bargain, with bind-to-localhost / shared-token noted as upgrades.
- [x] 7.4 Note that the working `plan-data.js` now lives in the volume (seeded from the default) and remains coach-edited there.
