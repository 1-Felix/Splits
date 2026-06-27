# SPLITS — Running Training Dashboard

A high-contrast performance dashboard for tracking years of Garmin data and
planning toward a goal race (currently: sub-2:00 at the Allgäu Panorama
Halbmarathon, Sonthofen — Aug 9 2026).

![themes: Volt / Track / Sunset](screenshots/full.png)

## What's in this project

| File | What it is |
|------|------------|
| `Running Dashboard.dc.html` | **The dashboard.** A Claude Design component rendered by `support.js`; imports `running-data.js`. |
| `support.js` | The `dc-runtime` that renders the `.dc.html` (loads React from a CDN, mounts the component). |
| `running-data.js` | **The contract.** Merges the two data files below into the `athleteData` object the dashboard reads. |
| `garmin-data.js` | **Telemetry — sync-owned.** Overwritten by `sync_garmin.py` every run. Don't hand-edit. (`FROM GARMIN`) |
| `plan-data.js` | **The plan — coach-owned.** `race` / `weekPlan` / `block` (the 6-week arc) / `coach`. The sync never touches it. (`EDITABLE`) |
| `sync_garmin.py` | Pulls from Garmin Connect and writes `garmin-data.js`. |
| `validate_data.py` | Asserts the §3 data-contract invariants against the merged `running-data.js`. |
| `serve.mjs` | Zero-dependency static server (`pnpm dev`). |
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

## Running the dashboard

The dashboard loads ES modules, so **serve the folder** — don't open the file
directly (a `file://` URL blocks the imports and the page falls back to built-in
demo data):

```bash
pnpm dev          # → http://localhost:8000/Running%20Dashboard.dc.html
# (no install needed — serve.mjs is dependency-free. PORT=3000 pnpm dev to change port.)
```

`support.js` pulls React from a CDN at runtime, so the first load needs network
access. Switch visual themes with the three swatches top-right (Volt is default).

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
