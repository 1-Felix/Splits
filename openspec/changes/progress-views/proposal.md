# Proposal: progress-views

## Why

SPLITS was built as a weekend project — one page, one merged data file, no API — and
that architecture is now the bottleneck: the daily cockpit is nine sections deep and
carrying long-game freight, while the archive (536 activities, full detail for all
158 runs, plan snapshots, compliance history) has no path to the browser at all.
This change is the deliberate refactor that lets the dashboard grow sustainably into
a running companion — stage 3a of the roadmap: land the multi-page architecture and
the read-only archive API, proven by two real views (records wall, year-over-year)
on a new `/progress` page.

## What Changes

- **Golden rule rescoped, not deleted.** Old: the dashboard imports one merged
  `running-data.js` and talks to no API. New: the **cockpit stays static-file
  only** (renders on race morning with the server half-dead), while **deep views
  may talk to a read-only archive API** and degrade to an honest "archive offline"
  state. ROADMAP.md is updated to record the rescope and the 3a/3b/3c staging.
- **Read-only archive API in `serve.mjs`** (zero-dependency via `node:sqlite`):
  list/filter activities over promoted columns, single-activity detail, records.
  The API is a **window, not a second brain** — all derivation stays in the
  deterministic Python sync; the API only SELECTs, shapes, and paginates stored
  rows. The single-activity endpoint serves the **same distilled detail shape**
  `garmin-data.js` already uses for recent runs, so `coach-read.js` and the
  existing drill-down UI work on any archived run.
- **Multi-page shell.** Pages become the unit of growth: each view is its own
  `.dc.html` served by `serve.mjs`. The topbar (nav, theme picker, sync pill) is
  extracted from the cockpit component into a shared module; the chosen theme
  persists across pages and reloads via `localStorage` (today it resets on
  reload).
- **Cockpit diet.** The main page sheds THE LONG GAME (weekly volume) and the
  30-month chart grid (VO₂ · pace · fitness/fatigue · cadence · pace@HR-band ·
  cadence@ref-pace · records feed) to `/progress`, becoming a true
  today/this-week/this-block page. The **heatmap stays in the cockpit**.
  Subtractive only — everything the cockpit keeps is not rewired.
- **`/progress` page with two views:**
  - **Records wall** — all-time / last-90-days / by-calendar-year best efforts
    (1k, mile, 5k, 10k, half), each record linking through to the run it fell in
    (via the archive API detail endpoint). By-year slices are a new derivation in
    `insight_metrics.py` (sync-time, tested, versioned — per the
    window-not-engine principle).
  - **Year-over-year** — per-year monthly aggregates (distance, runs, pace) from
    the archive's promoted columns, comparing 2024 / 2025 / 2026 side by side.
- **Node 22 → 24 base image bump** — the enabler for stable `node:sqlite`,
  keeping `serve.mjs` dependency-free.

Out of scope (later stages ride on this one): archive browser + run comparison
(3b), block retrospectives from plan snapshots × compliance (3c).

## Capabilities

### New Capabilities

- `archive-api`: read-only JSON API over `activity-archive.db` in `serve.mjs` —
  endpoints, query shaping, the distilled detail contract, no-derivation rule,
  fail-soft behavior when the archive is missing/locked, and the SQLite-over-SMB
  guard for local dev (the API reads a local archive only, never a mounted one).
- `progress-views`: the `/progress` page — records wall (all-time / 90d /
  by-year, click-through to runs) and year-over-year comparison, including
  offline degradation when the archive API is unreachable.

### Modified Capabilities

- `live-dashboard`: multi-page architecture (shared topbar with nav, theme
  persisted via `localStorage`), the cockpit diet (which sections move, heatmap
  stays), and the rescoped static-file rule (cockpit must render without the
  API; API-backed views must degrade gracefully).
- `insight-metrics`: by-calendar-year best-effort slices and year-over-year
  monthly aggregates added to the sync-time derivation (feed the records wall
  and YoY view). *(Capability is in-flight — archives 2026-07-06; the delta
  lands on top.)*
- `activity-archive`: distilled run detail stored alongside the raw payload
  (additive schema column + shared distiller + local recovery pass + verify
  coverage) — what the API's detail endpoint serves. *(Also in-flight,
  archives 2026-07-06.)*
- `containerized-deployment`: base image moves to Node 24; the container serves
  the archive API from the volume's canonical database.

## Impact

- **Code:** `serve.mjs` (API routes, `node:sqlite`), `Dockerfile` (node:24),
  `Running Dashboard.dc.html` (diet + topbar extraction), new
  `progress.dc.html`, new shared topbar module, `dashboard.css` (nav),
  `insight_metrics.py` (+by-year table), `README.md`, `openspec/ROADMAP.md`.
- **Tests:** new API tests (patterned on `test_plan_push.mjs` /
  `test_run_detail.py`), by-year coverage in `test_insight_metrics.py`,
  `tools/style-audit.mjs` layout assertions extended to `/progress`.
- **Deployment:** image rebuild (Node 24); no volume/schema migration — the API
  reads the existing archive schema v1. Unauthenticated read API on the LAN
  exposes training history read-only — same trust posture as the already-served
  `garmin-data.js`.
- **Dependencies:** none added — `node:sqlite` keeps the zero-dependency server.
- **Sequencing:** builds on the three in-flight changes (archive, insights,
  coach-loop) closing after the 2026-07-06 nightly check; cockpit changes are
  subtractive only, keeping race-week (Aug 9) risk near zero.
