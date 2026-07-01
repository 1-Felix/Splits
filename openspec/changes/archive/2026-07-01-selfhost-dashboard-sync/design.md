## Context

Splits is a static, self-contained dashboard (`Running Dashboard.dc.html` + `support.js` rendering React from a CDN) that imports a single data module, `running-data.js`. That module merges two writers: `garmin-data.js` (telemetry, produced by `sync_garmin.py`, gitignored) and `plan-data.js` (the plan, owned by the AI coach). Today the sync is a manual CLI run, the page is served by a zero-dependency Node static server (`serve.mjs`), and the dashboard's notion of "today" is whatever date the last sync baked into `garmin-data.js`.

`sync_garmin.py` is already complete and working — it authenticates, pulls activities, computes CTL/ATL and readiness, validates invariants, and emits a correct `garmin-data.js`. The work here is **packaging and wiring**, not re-implementing data logic.

Constraints that shaped this design:
- The AI-coach workflow (Claude Code editing `plan-data.js`) must remain untouched.
- The dashboard's data contract (`athleteData` shape) and demo-data fallback must remain intact.
- Single-user, home-network self-host is the target — not a multi-tenant public service.
- Two runtimes already exist (Node serve, Python sync) and the sync depends on a Python-only Garmin library.

## Goals / Non-Goals

**Goals:**
- Trigger a Garmin sync from the dashboard with no terminal.
- One container image, published to `ghcr.io/1-felix/splits`, run by a minimal `docker-compose.yml`.
- Credentials supplied via a git-ignored `.env` (referenced by compose with `${VAR}` substitution); personal data persisted in a `/data` volume across restarts and image upgrades.
- The dashboard reflects the real date and time of day (countdown, current-day highlight, greeting), while telemetry stays honestly anchored to the last sync.
- A fresh `docker compose up` produces a working dashboard (demo data at worst) without manual steps.

**Non-Goals:**
- Rewriting `sync_garmin.py` in JavaScript (explicitly rejected — see Decisions).
- Authentication / multi-user / public-internet hardening of the sync endpoint (LAN-trust is accepted).
- Live log streaming of the sync into the UI (deferred; start with spinner + timestamp).
- Changing the AI-coach contract or the `athleteData` schema.
- Multi-arch images now (amd64-only; arm64 is a later one-line toggle).
- Editing `plan-data.js` content or automating plan *content* roll-over (only the presentational "today" highlight is derived).

## Decisions

### D1 — One image bundling Node + Python; Node spawns the Python sync
The Node server is the front door; `POST /api/sync` spawns the existing `sync_garmin.py` as a subprocess.
- **Why:** the sync is a complete, proven, Python-library-dependent program. Spawning it costs a few lines and zero behavioral risk.
- **Alternatives:** (a) rewrite the sync in Node against a less-mature JS Garmin lib — large effort, real correctness risk, discards the most valuable asset; (b) two containers sharing the volume — cross-container triggering fights both "sync from the dashboard" and "simple docker-compose." Both rejected.
- **Trade-off:** a larger base image (Node + Python). Negligible on a home server.

### D2 — Two "todays": live display-today vs. anchored data-today
`display-today = new Date()` (browser-local) drives countdown, week-status, block highlight, and greeting. `data-today` (from `garmin-data.js`) anchors the heatmap's right edge and recent runs, with a "synced ·  <date>" caption and a staleness hint when the clock has drifted past it.
- **Why:** telemetry cannot be fresher than the last sync, but presentation can and should follow the wall clock. Conflating them is what makes a 3-days-stale page silently lie.
- **Alternatives:** (a) re-sync on every page load to keep one baked date — slow, offline-fragile, hammers Garmin; (b) make only countdown/greeting live — leaves the week highlight and block wrong. Both rejected.
- **Side effect:** the week plan's highlighted day is derived from each row's `date` vs. display-today, retiring the manual Monday `status:'today'` rolling. Plan *content* is still the coach's.
- **Why browser-local time:** "time of day" is the viewer's local time; the personal, single-user context makes trusting the client clock the right call. `TZ` is still set on the container for the nightly cron and server-side stamps.

### D3 — App in image, data in the `/data` volume
Application files ship in the image; `garmin-data.js`, `plan-data.js`, `.garmin_tokens/`, and `.garmin_cache/` live in `/data`. `serve.mjs` resolves `/garmin-data.js` and `/plan-data.js` from `SPLITS_DATA_DIR` (default `/data`); everything else is served from the image. `sync_garmin.py` writes to `SPLITS_DATA_DIR` with a fallback to its own directory so `pnpm dev` keeps working outside Docker.
- **Why:** personal health data and auth tokens must persist and stay out of the image; app code must be replaceable by an image upgrade without touching data.
- **`plan-data.js` placement:** it is coach-edited, so edits must persist → it lives in `/data`. The image ships `plan-data.default.js`; the entrypoint seeds `/data/plan-data.js` from it only if absent, so upgrades never clobber the user's plan.

### D4 — Sync cadence: button + on-boot + nightly, all in-process
`POST /api/sync` (manual button), a boot-time sync when data is missing/stale, and a nightly sync — the latter two run in-process in `serve.mjs` (a `SYNC_AT=HH:MM` daily scheduler, no cron daemon), so there's one process and the schedule honors the container `TZ`.
- **Why:** the button is the headline; on-boot prevents a fresh deploy from showing demo data; nightly keeps an unattended box current. All three call the same one sync path.
- **Alternatives:** button-only (fresh deploy stuck on demo) or button+boot (drifts stale between visits). Rejected as strictly weaker for a set-and-forget self-host.

### D5 — Graceful degradation over crash-loop
If a sync cannot authenticate or reach Garmin (missing/invalid credentials, network failure — or, were MFA ever enabled, a missing code), sync fails *soft*: the server returns a structured error, the dashboard renders demo/last data with a "connect Garmin" prompt, and the boot/nightly sync logs and continues. The token cache in `/data` makes auth a one-time concern.
- **Why:** a crash-looping container on first run is the worst possible onboarding. The demo fallback already exists in the page — lean on it.
- **MFA:** the target account does not use MFA, so the happy path is just credentials in `.env`. The soft-fail and the optional `GARMIN_MFA` path remain available if MFA is ever turned on, but are off the documented main road.

### D6 — Unauthenticated sync endpoint (LAN-trust)
`POST /api/sync` has no auth.
- **Why:** single-user home network; a token adds setup friction for little gain on a trusted LAN. Documented explicitly, with the shared-token and localhost-bind options noted as upgrades if the port is ever exposed.

### D7 — GHCR publish via GitHub Actions
A workflow builds and pushes `ghcr.io/1-felix/splits` on push to `main` and on tags, using `GITHUB_TOKEN` with `packages: write`. amd64-only.
- **Why:** "image as part of this repo's container registry" = GHCR tied to `1-Felix/Splits`. Tags give pinnable releases; `main` gives a rolling `latest`.

### D8 — Reload-on-success for data refresh
The page imports data once as ES modules; after a successful sync the client reloads (the server already sends no-cache headers).
- **Why:** simplest correct refresh; matches the "start simple" decision. A fetch-and-re-render path is a later refinement, not needed now.

## Risks / Trade-offs

- **Authentication failure on first run** (wrong credentials, network) → boot sync fails. Mitigation: D5 soft-fail; the account uses no MFA, so the documented first run is just credentials in `.env`. (If MFA is ever enabled, a one-time `GARMIN_MFA=` or interactive `docker compose run --rm splits python sync_garmin.py` seeds the token in the volume.)
- **Plaintext credentials in `.env`** → standard self-host bargain. Mitigation: creds live in a git-ignored `.env` (never in the committed compose, which references `${VAR}`); note Docker secrets as an advanced option.
- **Unauthenticated sync trigger** (D6) → anyone on the LAN can initiate a Garmin pull. Mitigation: documented; bind-to-localhost and shared-token escape hatches noted.
- **Client-clock trust** (D2) → a wrong device clock skews display-today. Mitigation: acceptable for personal use; telemetry (the data of record) is unaffected.
- **Image size from dual runtime** (D1) → larger pulls. Mitigation: slim base, layer ordering, `.dockerignore`; acceptable on a home server.
- **Concurrent syncs** (button during a nightly run) → double Garmin hits / file write race. Mitigation: a single in-flight lock; `/api/sync` returns "already running" and `/api/status.syncing` reflects it.
- **`plan-data.js` leaving the committed tree** → the repo no longer carries the live plan. Mitigation: ship `plan-data.default.js`; document that the working plan now lives in the volume and is coach-edited there.

## Migration Plan

1. Land the app/data split (`SPLITS_DATA_DIR` resolution in `serve.mjs` and `sync_garmin.py`) with local-dev fallbacks — `pnpm dev` must keep working unchanged.
2. Add the API routes and the live-clock frontend behavior (both degrade safely with no container).
3. Add `Dockerfile`, entrypoint (seed `plan-data.js`, then launch the server), `docker-compose.yml` (creds via `.env`), `.dockerignore`. The boot sync and nightly scheduler run in-process in `serve.mjs`.
4. Add the GHCR workflow.
5. Update README with the self-host quickstart and the MFA first-run note.

**Rollback:** the change is additive to the existing dev flow — `pnpm dev` + manual `python sync_garmin.py` continue to work, so reverting the container layer leaves a functioning local setup. The volume data layout is forward-compatible (files simply move from repo root to `/data`).

## Open Questions

- **MFA:** Resolved — the account does not use MFA, so the documented first run is just credentials in `.env` + `docker compose up`. The soft-fail handling (D5) and optional `GARMIN_MFA` path are kept available but stay off the main docs path.
- **Nightly cron time / `TZ` default** — pick a sensible default (e.g., 04:00 local) and make it overridable via env. Confirm during implementation.
