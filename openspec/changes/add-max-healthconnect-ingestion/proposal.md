## Why

Max (Felix's brother) is 3 weeks into running and training toward his first half
marathon. We want him on the SPLITS dashboard — seeing a coach-authored plan
scored against his actual runs — but he has a **Galaxy Watch + Pixel (Samsung
Health)**, not a Garmin, so the existing `sync_garmin.py` pipeline cannot reach
his data.

Every *automated* path to pull a Galaxy Watch's runs into a self-hosted box is
blocked or compromised, verified empirically this session:
- **Strava API** now requires a paid Strava subscription just to create an app
  (confirmed live on Felix's account) — off the table.
- **Garmin Connect** refuses inbound third-party activity writes, so we cannot
  relay Max's runs into a Garmin account and reuse the existing sync.
- **Samsung** exposes no public cloud API to pull from server-side.

The one path nobody can paywall or revoke is the one **we own end to end**:
Samsung Health writes running workouts — `Exercise`, `HeartRate`, `Distance`,
`Speed` — into Android **Health Connect** (confirmed at the OS permission level
on a Galaxy S24 running Samsung Health 7.00.0.107). A small self-built Health
Connect reader app on Max's Pixel can push those runs to his own SPLITS
instance. Doing this as a **separate instance** also gives the cleanest possible
separation of Max's training from Felix's — different process, different volume.

## What Changes

- **New Android app** on Max's Pixel that reads running workouts from Health
  Connect (session + per-run heart-rate **samples** + distance + speed) and
  POSTs them to a SPLITS instance. Background, set-and-forget after a one-time
  permission grant.
- **New server ingest endpoint** `POST /api/ingest` on the SPLITS server —
  token-guarded, mirroring the existing plan-push auth pattern — that accepts
  pushed runs and banks them.
- **New telemetry builder** that turns the accumulated stream of pushed runs
  into the dashboard's telemetry contract (`athleteData`), reusing the CTL/ATL
  and Riegel formulas the project already computes for Felix.
- **Second, ingest-fed SPLITS instance for Max** — its own data volume and
  `plan-data.js`, no Garmin credentials, `sync_garmin.py` disabled. Telemetry
  comes from the ingest builder instead of the Garmin sync. Complete data
  isolation from Felix's instance.
- **Scope boundary — "Slim + HR zones."** The builder produces: `recentRuns`,
  weekly volume (`weeklyKm`/`weeklyRuns`), fitness/fatigue (`ctl`/`atl`), monthly
  `paceSecPerKm`, `heatmapKm`, `predictions`, `hrZones`, plus the coach-owned
  `race`/`weekPlan`/`coach` from `plan-data.js`.
- **Explicit non-goals** (Health Connect does not expose them, or they are
  wellness a beginner does not need): VO₂max, readiness/Body Battery,
  sleep/HRV/resting-HR, the **route basemap** (Health Connect carries no workout
  GPS), and per-run **stream drill-downs** on `/run/:id`.

## Capabilities

### New Capabilities
- `healthconnect-bridge`: an Android app that reads running workouts (exercise
  session, heart-rate samples, distance, speed) from Health Connect on Max's
  device and pushes them to a SPLITS instance over an authenticated HTTP
  endpoint, on a recurring background schedule.
- `telemetry-ingest`: the server side — an authenticated `POST /api/ingest`
  that receives pushed runs and banks them, plus the builder that derives Max's
  `athleteData` telemetry contract (the Slim + HR-zones field set) from the
  accumulated runs, so the dashboard renders without a Garmin source.

### Modified Capabilities
- `containerized-deployment`: extend the deployment model to support a **second,
  independent instance for a second athlete** — its own volume and plan, no
  Garmin credentials, with telemetry produced by the ingest builder rather than
  `sync_garmin.py`. The two instances share the image but nothing else.

## Impact

- **New Android codebase** (Kotlin, `androidx.health.connect:connect-client`) —
  sideloaded to Max's Pixel; requires completing Google's Health Connect
  Developer Declaration for data-type access. Not part of the container image.
- **`serve.mjs`** — add the `/api/ingest` route (auth + size-cap + atomic write,
  patterned on the existing `PUT /api/plan`).
- **New telemetry builder** (Python, alongside `sync_garmin.py`) that reuses
  `insight_metrics` CTL/ATL + Riegel logic; runs on ingest / on a schedule to
  (re)build Max's `garmin-data.js`-shaped telemetry from banked runs.
- **`docker-compose.yml`** — a second service + volume for Max's instance.
- **Max's `plan-data.js`** — a beginner→half plan (authored by Felix + AI); no
  code change to the plan format.
- **Dashboard** — degrades on the non-goal panels (VO₂ hero, readiness, route,
  stream drill-downs) for Max's instance; the `profile.vo2maxCurrent ===
  history.vo2max[last]` invariant and `/run/:id` degradation are resolved in
  design.
- **No impact** on Felix's existing instance, sync, or archive — his deployment
  is untouched.
