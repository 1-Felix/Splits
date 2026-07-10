# SPLITS — Running Training Dashboard

A high-contrast performance dashboard for tracking years of Garmin data and
planning toward a goal race (currently: sub-2:00 at the Allgäu Panorama
Halbmarathon, Sonthofen — Aug 9 2026).

![themes: Volt / Track / Sunset](screenshots/full.png)

## What's in this project

| File | What it is |
|------|------------|
| `Running Dashboard.dc.html` | **The cockpit** (served at `/`). Today / this week / this block: hero, KPIs, plan, heatmap, recent runs. Renders complete from static files alone — no API. |
| `progress.dc.html` | **The progress page** (served at `/progress`). The long game: weekly volume, the 30-month chart grid, the records wall (all-time / 90 d / by year — records click through to `/run/:id`), and year-over-year volume. |
| `run.dc.html` | **The run page** (served at `/run/:id` — the one parameterised route). Full-resolution sample streams as synchronised tracks under one crosshair, the GPS trace as a projected polyline, splits vs the run's own median, best efforts, and planned-vs-actual from the compliance join. |
| `topbar.js` | **Shared topbar behavior** — theme registry + `localStorage` persistence, the sync-pill state machine, greeting, and the page nav model. Markup is duplicated per page; behavior lives here once. |
| `dashboard.css` | The dashboard's visual language — design tokens, semantic component classes, and the responsive `@media` layer. |
| `support.js` | The `dc-runtime` that renders the `.dc.html` — a **generated** artifact (never hand-edited). Its CDN React loader is short-circuited: each page pre-seeds `window.React` / `window.ReactDOM` from `vendor/`, so it mounts the component with no network. |
| `vendor/` | **Vendored client runtime** — React 18.3.1 UMD (pinned) plus self-hosted Archivo / JetBrains Mono `woff2` and the OFL licence, all served from our own origin. This project vendors; it does not CDN. See `vendor/README.md`. |
| `running-data.js` | **The contract.** Merges the two data files below into the `athleteData` object the dashboard reads, and attaches each run's coach-read. |
| `coach-read.js` | **The read.** Turns a run's stored `detail` (per-km splits, HR-drift, zones) + the plan into the one-line coach-read shown when you click a run in *Recent Activities* to drill into it. |
| `chart-core.js` | **The chart engine's brain.** Pure, DOM-free geometry and policy: domain resolution (minimum spans, zero anchoring, goal inclusion), tick selection, null segmentation, rolling-median baseline bands, confidence weighting, annotation lanes, and `buildSpec(descriptor) → ChartSpec`. Consumes `chart-hover.js`; tested in `test_chart_core.mjs` with no browser. |
| `chart-view.js` | **The chart engine's hands.** `renderChart(spec, React) → element` — the only file that turns a ChartSpec into elements. SVG carries the stretch-safe marks; all text and dots are HTML overlays so labels stay crisp at any card width. Tested against a stub React in `test_chart_view.mjs`. |
| `chart-hover.js` | **The inspection layer.** Pure `bandRects` + `cardPlace` geometry behind the hover/tap crosshair-and-card — consumed by `chart-core.js`, never reimplemented. |
| `garmin-data.js` | **Telemetry — sync-owned.** Overwritten by `sync_garmin.py` every run. Don't hand-edit. (`FROM GARMIN`) — lives in the `/data` volume when containerized. |
| `plan-data.js` | **The plan — coach-owned.** `race` / `weekPlan` / `block` (the 6-week arc) / `coach`. The sync never touches it. (`EDITABLE`) — lives in the `/data` volume (seeded from the default below). |
| `plan-data.default.js` | The **shipped default plan** — seeds `plan-data.js` into the data volume on first container boot, then never overwrites it. |
| `sync_garmin.py` | Pulls from Garmin Connect and writes `garmin-data.js`. |
| `validate_data.py` | Asserts the §3 data-contract invariants against the merged `running-data.js`. |
| `serve.mjs` | Zero-dependency web server: serves the pages behind clean routes (`/`, `/progress`), serves the data files from the data dir, exposes `POST /api/sync` + `GET /api/status` + the read-only archive API (`GET /api/archive/…`, via the Node 24 built-in `node:sqlite`), and runs the boot + nightly sync. |
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

### Why vendor React and the fonts?

**This project vendors; it does not CDN.** The cockpit's promise — it renders
complete from static files alone — only holds if *every* subresource comes from
our own origin. So the React runtime and both typefaces are checked into
`vendor/` and served by `serve.mjs`; no page loads `unpkg.com`,
`fonts.googleapis.com`, or any other third-party host. `test_offline.mjs`
enforces this by loading the pages with every non-same-origin request aborted and
asserting they still render.

React is pinned to **18.3.1** on purpose: it is the last version published as a
UMD global. Two `<script>` tags in each page pre-seed `window.React` /
`window.ReactDOM` before the generated `support.js` runs, so its CDN loader takes
its `if (w.React && w.ReactDOM) return` early exit and `support.js` stays
byte-for-byte the artifact it ships as. React 19 ships no UMD build, so bumping
the version is not a one-line change — it means adopting a bundler. That
constraint is recorded beside the script tags and in `vendor/README.md`.

`serve.mjs` also gzips `text/*`, JavaScript, and JSON responses (via the built-in
`node:zlib` — still zero-dependency); the vendored `woff2` are served as-is
(already compressed) and cached immutably.

### The chart engine (core → view → spec)

Every chart on both pages renders through one pipeline:

```
descriptor (data + policy + hover payloads)
    │  chart-core.js   — pure geometry: domains, ticks, gaps, bands, lanes
    ▼
ChartSpec (px geometry + a11y contract, no DOM)
    │  chart-view.js   — the only file that makes elements
    ▼
React element  →  {{ vo2.chart }} in the page template
```

`chart-core.js` is testable in node with no browser; `chart-view.js` is tested
against a stub `createElement`. The d3 primitives underneath (`d3-scale`,
`d3-shape`, `d3-array`, `d3-time-format`) are vendored as ONE checked-in ESM
artifact, `vendor/d3-lite.js`, built from `vendor/entry.js` (the declared symbol
surface) by the documented esbuild one-liner in `vendor/README.md` — no bundler
enters the runtime, no CDN enters the page, and `test_chart_core.mjs` fails if
the artifact goes stale against the core's imports.

**The domain-policy table** (`POLICIES` in `chart-core.js`) is where to argue
about how charts look. A chart's y domain is never just the data's extent —
that's how a +0.3 VO₂ month used to sweep the full card height. Each metric
declares its policy; the minimum spans are judgement calls, kept in one table so
they can be changed together:

| Chart | Domain rule | Reference layer |
|---|---|---|
| Trajectory (cockpit) | nice; must include `goalSec`; min span 15 min | goal rule + Riegel↔model ribbon |
| VO₂ max | nice; min span 5.0 pts | 12-mo rolling median band |
| Avg run pace | nice; must include goal pace; min span 60 s/km | goal rule |
| Cadence | nice; min span 20 spm | 12-mo rolling median band |
| Weekly volume | zero-based | 4-wk rolling mean line |
| Fitness & fatigue | shared domain, zero-based | — (legend) |
| Sleep hours | zero-based, 0–10 h | 7–9 h target band |
| HRV | nice; min span 20 ms | personal baseline band (7-night median) |
| Pace @ ref HR | nice; min span 60 s/km | 7-mo median band + `inBandMin` weighted dots |
| Cadence @ ref pace | nice; min span 10 spm | 7-mo median band + weighted dots |
| Year-over-year | zero-based, shared across years | — (legend) |
| Heatmap | sequential single-hue ramp (`hm0…hm4`) | — |

Two rules the engine enforces everywhere: a line never bridges a null month
(gaps stay gaps), and series colours (`series1…series4` in `topbar.js`) are
validated by script — `test_palette.mjs` runs the vendored checker in
`tools/validate-palette.mjs` against every theme's own surface, so status
colours can never impersonate a series and the zone ramp stays legible under
colour-vision deficiency.

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
**Sync now** endpoint (`POST /api/sync`) is unauthenticated, the read-only archive
endpoints (`GET /api/archive/…`) expose your full training history to anyone on the
LAN (the same trust level as the already-served `garmin-data.js`), and your
credentials sit in plain text in `.env` — the normal self-host bargain. If you expose
the port beyond your LAN, put it behind an authenticating reverse proxy, bind the
published port to `127.0.0.1`, and/or use Docker secrets for the credentials.

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
| `SPLITS_ARCHIVE_DIR` | `SPLITS_DATA_DIR` | Where the archive API reads `activity-archive.db`. Set it in dev when the data dir is a network mount — SQLite over SMB is unsupported. |

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
pnpm dev          # → http://localhost:8000/  (cockpit; /progress for the long game)
# (no install needed — serve.mjs is dependency-free. PORT=3000 pnpm dev to change port.)
```

**Node ≥ 24 expected** (declared in `package.json` engines): the archive API uses the
built-in `node:sqlite`, stable in 24. On an older Node the server still boots and
every page serves — only the `/api/archive/…` endpoints answer 503 (and record
click-throughs on `/progress` show their "archive offline" state).

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

## The activity archive (durable history)

`garmin-data.js` is a rolling window — old data slides out of it. The **activity
archive** (`activity-archive.db`, SQLite, in the same data directory) is the
project's memory: every sync also upserts every fetched activity (all types, raw
summary payload), tops up the raw per-activity detail (splits, HR/pace streams)
a few at a time, distills each run's detail into the dashboard's drill-down
shape (stored alongside the raw payload), and banks one wellness row per day
(resting HR, HRV, sleep). Nothing is ever deleted, and an archive problem can
never break the telemetry sync — it degrades to a warning.

**The archive API** (`serve.mjs`) is the browser's read-only window into it:

- `GET /api/archive/activities` — archived activities from the promoted columns
  only, filterable (`type`, `year`, `from`/`to`), paginated (`limit` ≤ 100,
  `offset`), newest-first.
- `GET /api/archive/activities/:id` — one activity's summary plus its stored
  distilled detail (exactly the shape recent runs use in `garmin-data.js`), its
  planned-vs-actual row joined from `plan_compliance`, and the best efforts it
  set from `run_metrics`. Raw Garmin payloads never leave the server.
- `GET /api/archive/activities/:id/streams` — the run's full-resolution sample
  stream, served **verbatim** from `detail_streams_json` and gzipped on the
  wire (~29 KB for the largest archived run). 404 for a run with no stored
  streams; never computed on the fly.

The API is a *window, not an engine*: it performs no derivation — everything it
returns was computed by the deterministic Python sync. It opens the database
read-only per request and fails soft: a missing/locked database (or a Node
without `node:sqlite`) means a 503 on these endpoints while every page and the
rest of the API keep working. The cockpit never touches it; `/progress` needs
it only for record click-throughs and degrades to an honest "archive offline"
state without it.

**Dev against a mounted data dir:** running SQLite over an SMB/network mount is
unsupported. If your `SPLITS_DATA_DIR` is a mount, point `SPLITS_ARCHIVE_DIR` at
a local directory holding a disposable archive copy (rebuildable with
`--backfill`) — data files keep coming from the mount while the archive API
reads locally.

One-time **backfill** pulls your full account history (walks back year by year
until it finds the account start; safe to interrupt and re-run):

```bash
# local
python sync_garmin.py --backfill
python sync_garmin.py --verify-archive   # counts by year/type, detail coverage, exit≠0 on regression

# self-hosted (the canonical copy — inside the container, archive lands in /data)
docker compose exec splits python3 sync_garmin.py --backfill
docker compose exec splits python3 sync_garmin.py --verify-archive
```

A second one-time **wellness backfill** pulls every night's raw sleep and HRV
payload back to your first activity (~2 Garmin calls per date, resumable, safe to
interrupt). Every normal sync then banks its whole fourteen-night sleep window —
payloads it was already fetching and throwing away.

```bash
docker compose exec splits python3 sync_garmin.py --backfill-wellness
docker compose exec splits python3 sync_garmin.py --backfill-wellness --since 2025-01-01  # spread it out
```

The raw payloads are stored, not just the numbers we read today: Garmin's sleep
document has grown from 7 top-level keys in 2024 to 18 now, so anything derived
at fetch time and discarded is lost forever. `daily_wellness.fetched_at` separates
*"we asked and the watch recorded nothing"* from *"we never asked"* — without it a
chart cannot tell a real gap from a missing fetch. `--verify-archive` reports
wellness gaps always, and fails on them only once the backfill has recorded
completion.

**The server volume's copy is canonical; local copies are disposable.** The
archive is entirely derived from Garmin, so any copy can be rebuilt with
`--backfill` — don't sync archive files between machines (and don't run SQLite
across an SMB mount). A corrupt database is quarantined as
`activity-archive.db.corrupt-<date>` and recreated automatically.

### Run streams and the run page (`/run/:id`)

Every archived run's raw detail holds ~1,670 samples × 19 metrics. The sync's
**stream distiller** (`distill_run_streams`) reshapes that row-oriented payload
into rounded COLUMNS — `t`/`d`/`hr`/`v`/`gap`/`cad`/`elev`/`pwr`/`lat`/`lon`/`pc`
— stored in `activities.detail_streams_json` (schema v6, additive). Full
resolution, no downsampling: reshaped and rounded, the largest run costs ~115 KB
raw and **~29 KB gzipped** on the wire. Cadence comes from
`directDoubleCadence`, never `directRunCadence` (which is single-side strides
per minute despite its descriptor). Like the distilled detail, streams are
derived and disposable — the sync writes them for every newly archived run, and
the same pass acts as the **recovery pass** over a pre-v6 archive: stored
payloads in, no Garmin calls, raw payloads byte-identical afterwards.
`--verify-archive` reports stream coverage and fails on regression.

`/run/:id` renders those streams as synchronised tracks (pace with
grade-adjusted pace, heart rate over zone shading, cadence, elevation, power
and performance condition when present) under **one crosshair**, switchable
between distance and time — plus splits against the run's own median, the best
efforts the run set, and what the plan asked for beside what happened.

**Why is there no basemap?** Every map-tile provider is a third-party origin,
and this project vendors rather than CDNs — `test_offline.mjs` loads `/run/:id`
with every non-same-origin request aborted and the route still renders. The GPS
track draws as a projected polyline (equirectangular, cos-latitude corrected,
aspect preserved): the *shape* of the run, not a picture of a city. It works
offline, prints, themes with the page, and costs ~9 KB.

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
