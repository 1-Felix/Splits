# SPLITS — Running Training Dashboard

A high-contrast performance dashboard for tracking years of Garmin data and
planning toward a goal race (currently: sub-2:00 at the Allgäu Panorama
Halbmarathon, Sonthofen — Aug 9 2026).

![themes: Volt / Track / Sunset](screenshots/full.png)

## What's in this project

| File | What it is |
|------|------------|
| `Running Dashboard.dc.html` | **The dashboard.** A Claude Design component rendered by `support.js`; imports `running-data.js`. |
| `dashboard.css` | The dashboard's visual language — design tokens, semantic component classes, and the responsive `@media` layer. |
| `support.js` | The `dc-runtime` that renders the `.dc.html` (loads React from a CDN, mounts the component). |
| `running-data.js` | **The contract.** Merges the two data files below into the `athleteData` object the dashboard reads, and attaches each run's coach-read. |
| `coach-read.js` | **The read.** Turns a run's stored `detail` (per-km splits, HR-drift, zones) + the plan into the one-line coach-read shown when you click a run in *Recent Activities* to drill into it. |
| `chart-hover.js` | **The inspection layer.** Pure `bandRects` + `cardPlace` geometry behind the hover/tap crosshair-and-card that every chart, the heatmap, and the ring show for each datapoint. |
| `garmin-data.js` | **Telemetry — sync-owned.** Overwritten by `sync_garmin.py` every run. Don't hand-edit. (`FROM GARMIN`) — lives in the `/data` volume when containerized. |
| `plan-data.js` | **The plan — coach-owned.** `race` / `weekPlan` / `block` (the 6-week arc) / `coach`. The sync never touches it. (`EDITABLE`) — lives in the `/data` volume (seeded from the default below). |
| `plan-data.default.js` | The **shipped default plan** — seeds `plan-data.js` into the data volume on first container boot, then never overwrites it. |
| `sync_garmin.py` | Pulls from Garmin Connect and writes `garmin-data.js`. |
| `validate_data.py` | Asserts the §3 data-contract invariants against the merged `running-data.js`. |
| `serve.mjs` | Zero-dependency web server: serves the dashboard, serves the data files from the data dir, exposes `POST /api/sync` + `GET /api/status`, and runs the boot + nightly sync. |
| `Dockerfile` · `docker-compose.yml` · `docker-entrypoint.sh` | **Self-host packaging** — one image (Node + Python), a one-file compose, and the entrypoint that seeds the plan and starts the server. |
| `.github/workflows/docker-publish.yml` | CI that builds and pushes `ghcr.io/1-felix/splits` on `main` and on version tags. |
| `tools/style-audit.mjs` | Computed-style parity and responsive layout-assertion harness; run `node tools/style-audit.mjs layout` to assert the grid reflows correctly at 1200 / 768 / 390 px. |
| `CLAUDE_CODE_HANDOFF.md` | The backend brief: data contract, metric→source map, formulas, open decisions. |
| `.env.example` | Template for Garmin credentials. Copy to `.env`. |

### Why three data files?

The sync and the coach are two writers that must not clobber each other
(handoff §5.4). So telemetry and plan live in separate files, each with one
owner, and `running-data.js` just merges them:

```
garmin-data.js  (FROM GARMIN, sync-owned) ┐
                                          ├─▶  running-data.js  ──▶  dashboard
plan-data.js    (EDITABLE,   coach-owned) ┘     { ...garmin, ...plan }
```

A nightly `sync_garmin.py` can overwrite `garmin-data.js` freely and never risks
your training plan.

## Self-hosting with Docker (recommended)

SPLITS ships as a single image — Node serves the dashboard, Python runs the Garmin
sync, and your data lives in a Docker volume. To self-host:

1. Put your Garmin login in a git-ignored `.env` (compose reads it automatically):
   ```bash
   cp .env.example .env
   # edit .env → GARMIN_EMAIL, GARMIN_PASSWORD  (optional: TZ, SYNC_AT)
   ```
2. Start it:
   ```bash
   docker compose up -d
   ```
3. Open **http://localhost:8000**.

Credentials never live in `docker-compose.yml` — it references `${GARMIN_EMAIL}` /
`${GARMIN_PASSWORD}` from `.env`, so the compose file stays safe to commit. Missing
creds don't crash anything: the dashboard comes up and the top-bar pill reads
**"Connect Garmin"** until you add them and sync.

On first boot the container seeds your plan, syncs your Garmin data in the
background, and the dashboard comes up. Hit **Sync now** (the pill in the top bar)
any time to pull fresh data; it also re-syncs nightly (see `SYNC_AT`) and on every
restart when the data is stale. The dashboard tracks the real clock — the
countdown, the highlighted "today" in the week, and the greeting all follow your
local date and time of day, while the telemetry stays anchored to the last sync.

**Where your data lives.** Everything personal — `garmin-data.js`, `plan-data.js`,
the cached auth token, and the raw API cache — is stored in the `splits-data`
volume mounted at `/data`. It survives restarts and image upgrades; the image
carries no personal data. Your plan is seeded once from `plan-data.default.js` and
never overwritten after that, so upgrading the image keeps your training plan
intact. The plan stays coach-owned — your agent edits `plan-data.js` in the volume
exactly as before.

**First run / MFA.** This account doesn't use Garmin MFA, so credentials in compose
are all you need. (If you ever enable MFA, set `GARMIN_MFA=<code>` in compose once —
the token is then cached in the volume for ~a year — or seed the first login
interactively: `docker compose run --rm splits python3 sync_garmin.py`.) If a sync
can't authenticate, the dashboard still comes up on demo/last data with a "connect
Garmin" prompt — it never crash-loops.

**Security posture.** This is built for a single user on a trusted home network: the
**Sync now** endpoint (`POST /api/sync`) is unauthenticated and your credentials sit
in plain text in `.env` — the normal self-host bargain. If you expose the port beyond
your LAN, put it behind an authenticating reverse proxy, bind the published port to
`127.0.0.1`, and/or use Docker secrets for the credentials.

**Image source.** The committed compose pulls `ghcr.io/1-felix/splits:latest` (built
by CI for `linux/amd64`). To build from source instead, uncomment `build: .` in the
compose file.

### Config knobs (compose `environment`)

| Var | Default | What it does |
|-----|---------|--------------|
| `GARMIN_EMAIL` / `GARMIN_PASSWORD` | — | Garmin Connect login (required for sync). |
| `TZ` | UTC | Your timezone — drives the live clock and the nightly sync time. |
| `SYNC_AT` | `04:00` | Daily auto-sync time (local). `off` to disable. |
| `SYNC_ON_BOOT` | `on` | Sync once at startup if telemetry is missing/stale. `off` to disable. |
| `ATHLETE_NAME` / `ATHLETE_AGE` / `ATHLETE_MAX_HR` | — | Profile overrides Garmin doesn't always expose. |
| `SPLITS_PLAN_TOKEN` | — | Secret that enables `PUT /api/plan` (plan push). Unset ⇒ no write endpoint. See below. |

## Keeping your plan in sync

Your training plan (`plan-data.js`) is coach-owned and lives on the homeserver's `/data`
volume — that's the single source of truth. There are two ways to edit it.

**At home — edit the file directly (no protocol).** Mount the homeserver's `/data` on your
machine (SMB / NFS / SSHFS over your LAN or VPN), then either symlink the repo's
`plan-data.js` to the mounted file or run dev against the mount:

```bash
# macOS / Linux
SPLITS_DATA_DIR=/mnt/splits-data pnpm dev
```
```powershell
# Windows (PowerShell) — mounted as drive Z:, say
$env:SPLITS_DATA_DIR = "Z:\"; pnpm dev
```

On Windows the symlink route also works: `New-Item -ItemType SymbolicLink -Path plan-data.js -Target Z:\plan-data.js` (Developer Mode or an elevated shell), then just `pnpm dev`.

Now editing `plan-data.js` writes the canonical file — the homeserver dashboard and your
local dev both reflect it on the next load. Bonus: because `garmin-data.js` is in the same
volume, local dev shows **real telemetry** with no local Garmin sync.

**Away — push over HTTPS (opt-in, token-authed).** On the homeserver, set a strong
`SPLITS_PLAN_TOKEN`; the endpoint stays absent until you do. On the client set the same
token plus the dashboard URL (both go in `.env`):

```bash
SPLITS_PLAN_TOKEN=<same-long-random-secret>
SPLITS_PLAN_URL=https://splits.example.com
```

Then:

```bash
pnpm plan:pull    # fetch the canonical plan → local plan-data.js (+ records its version)
#   …edit plan-data.js…
pnpm plan:push    # validates locally, then writes canonical (guarded against stale overwrites)
```

If someone changed the canonical since your pull, `plan:push` stops with a conflict — run
`plan:pull` again, reapply, and push (or `pnpm plan:push --force` to override the guard).

> **Trust model:** the plan is executed as code by the dashboard, so a push writes runnable
> code. The token gates that — whoever holds it can write the plan on your server. Use HTTPS,
> keep `SPLITS_PLAN_TOKEN` secret, and leave the endpoint off (token unset) if you don't need it.

## Running locally (development)

Without Docker — the original dev flow. The dashboard loads ES modules, so **serve
the folder** — don't open the file directly (a `file://` URL blocks the imports and
the page falls back to built-in demo data):

```bash
pnpm dev          # → http://localhost:8000/Running%20Dashboard.dc.html
# (no install needed — serve.mjs is dependency-free. PORT=3000 pnpm dev to change port.)
```

`support.js` pulls React from a CDN at runtime, so the first load needs network
access. Switch visual themes with the three swatches top-right (Volt is default).

The dashboard is **responsive** — it reflows across phone (390 px), tablet (768 px), and desktop (1200 px+), driven by the `@media` rules in `dashboard.css`.

Every chart is **interactive**: hover (or tap) any point — on a line, a bar, the
heatmap, the ring, or a run's sparkline — for a crosshair and a card with that
point's date, value, and context. Charts are keyboard-navigable (Tab to a chart,
arrow keys to inspect).

## Wiring up real Garmin data

```bash
pip install -r requirements.txt   # garminconnect + python-dotenv
cp .env.example .env              # then add GARMIN_EMAIL / GARMIN_PASSWORD
python sync_garmin.py             # writes garmin-data.js from your real numbers
python validate_data.py           # optional: assert the contract still holds
```

Reload the dashboard — it picks up the new telemetry automatically.

- **MFA:** if your account uses it, set `GARMIN_MFA=<code>` in `.env` for the
  first run (or run `sync_garmin.py` in an interactive terminal). Auth tokens are
  then cached in `.garmin_tokens/` for ~a year, so you won't be asked again.
- **What it computes itself:** Garmin doesn't expose CTL/ATL (fitness/fatigue) or
  a guaranteed readiness score, so the sync derives them from daily TSS and an
  HRV/RHR/sleep blend (handoff §4). Race predictions fall back to Riegel.
- Raw API responses are cached per-day in `.garmin_cache/` so re-runs are cheap.

## How the AI coach fits in

No live API runs in the page. The data layer **is** the interface:

- **`sync_garmin.py`** owns `garmin-data.js` (history, heatmap, readiness, zones…).
- The **AI coach** (you, in Claude Code) owns **`plan-data.js`** — `race`,
  `weekPlan`, `block` (the week-by-week build → taper arc), and `coach` (the
  headline, note, focus chips, and adjustment log shown on the dashboard). Edit
  it, reload, done.

## Profile defaults

Name **Felix** · Max HR **197** · HR zones Z1 99–118 / Z2 118–138 / Z3 138–158 /
Z4 158–177 / Z5 177–197 bpm. Override via `.env` (`ATHLETE_NAME` / `ATHLETE_AGE`
/ `ATHLETE_MAX_HR`) or edit `garmin-data.js` → `profile` / `hrZones`.
