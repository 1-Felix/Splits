# HANDOFF — add-max-healthconnect-ingestion

Read this first, then `design.md` (esp. the 2026-07-15 addendum) and `tasks.md`.
The OpenSpec artifacts (`proposal.md` / `design.md` / `specs/**` / `tasks.md`) are
the source of truth; this doc is the orientation + operational knowledge that
isn't in them (current status, how to build/run/test, environment gotchas, resume
plan). Last updated 2026-07-16.

## TL;DR

Onboard Felix's brother **Max** (Galaxy Watch + Pixel, Samsung Health — no Garmin)
onto a **second, ingest-fed SPLITS instance**. Runs reach the box via an Android
**Health Connect reader app we own**. **The entire server side is now built, tested
green, and expansion-complete** (groups 2–4, 8–10 + compose 5.1): ingest endpoint
(runs + RHR), JSON stores, Python builder with the full D9–D13 derivation set,
dashboard degradation guards, energy tile + RHR trend card, adversarial-review
fixes. What remains is **physical/collaborative**: the 1.4 Samsung gate, Max's
plan (5.2), network path (5.3), NUC smoke (5.4), and finishing the Android app
(6.x, incl. the ingest-payload mapping noted in 7.3).

## Status (what's done vs left)

| Group | What | State |
|---|---|---|
| 1 | Health Connect extraction spike | 1.1✓ 1.2✓ 1.3✓ **1.4 OPEN (gate)** 1.5✓ |
| 2 | `POST /api/ingest` + JSON run store | ✅ built + tested |
| 3 | Python telemetry builder | ✅ built + tested |
| 4 | Dashboard degradation guards | ✅ **done 2026-07-16** — readiness DID crash the page (repro'd); guarded + Playwright-tested |
| 5 | Deployment | 5.1✓ (compose profile) · 5.2 plan / 5.3 network / 5.4 smoke **open** |
| 6 | Finish the Android app | ❌ open (mostly physical; 6.1 must map spike JSON → ingest payload, see 7.3 note) |
| 7 | Reader scope-expansion | 7.1✓ 7.2✓ · 7.3 code lives in the spike already; Declaration paperwork open |
| 8 | Ingest payload + validation expansion | ✅ **done 2026-07-16** (incl. RHR payload form) |
| 9 | Builder expansion (calibration/Karvonen/moving pace/splits/cadence/energy/RHR) | ✅ **done 2026-07-16** incl. both frontend surfaces |
| 10 | Adversarial-review fixes (5 real bugs + misc) | ✅ **done 2026-07-16**, all TDD'd |

## Architecture (the pipeline)

```
Galaxy Watch → Samsung Health → Health Connect ←[bridge app reads]→ POST /api/ingest
                                                                          │ (serve.mjs, token-gated)
                                                    runs → ingested-runs.json (keyed by session UID)
                                                    RHR  → ingested-rhr.json  (keyed by date)
                                                                          │ triggerBuild() spawns (watchdog-guarded)
                                                                          ▼
                                              ingest_builder.py → garmin-data.js (telemetry half)
                                                                          │ running-data.js merges
                                                                          ▼  with plan-data.js
                                                                    Max's dashboard
```

One image, config-only difference. Max's compose service exists behind a profile:
`docker compose --profile max up -d` (port 8001, volume `splits-max-data`,
`SPLITS_INGEST_TOKEN_MAX` env; no Garmin creds, `SYNC_*` off).

## Ingest contract (implemented)

- **Run payload** (POST /api/ingest, bearer `SPLITS_INGEST_TOKEN`): required
  `sessionUid`, `startTimeLocal` (local ISO, calendar-validated), `durationS`,
  `distanceM`, `sportType`, `hrSamples[{tSec,bpm}]`; optional `avgHr`, `avgSpeed`,
  `source`, **`maxHr`, `elevationGainM`, `activeKcal`, `totalKcal`, `steps`,
  `speedSamples[{tSec,mps}]`**. Whitelisted; `__proto__` uid rejected.
- **RHR payload** (same endpoint): `{ restingHeartRate: [{date:"YYYY-MM-DD", bpm}] }`
  → upserted by date into `ingested-rhr.json`, response `{ok, days}`.
- **Builder derivations** (ingest_builder.py): maxHR = max(explicit env, observed
  per-run max) else 220−age; Karvonen zones when RHR banked (median of last ≤7
  days, emitted as `profile.restingHR`); moving pace (speed intervals <1.7 m/s
  stripped from time AND distance) for recentRuns/monthly/Riegel; per-km splits →
  **Garmin-shaped `recentRuns[].detail`** (splits/hrSeries/driftBpm/zoneMin/
  splitShape/elevGain — lights up the existing run-card drill-down + coach-read);
  cadence = steps ÷ moving min; `energy.weekKcal`; `history.restingHr` (90 d).
  Keys omitted entirely when source data is absent (D7-style degradation).
- **Frontend**: cockpit gained an ENERGY KPI tile + a Resting HR trend card
  (chart-core `POLICIES.restingHr`), both hidden without their keys; readiness/
  sleep/HRV cards + VO₂ tiles/cards are `sc-if`-gated (they crashed before);
  `predictions.halfNow` null-safe; zone-percent division-by-zero guarded.

## Files created/changed (cumulative)

- `serve.mjs` — `POST /api/ingest` (run + RHR forms), `ingestExclusive` mutex,
  `triggerBuild()` (single-flight + coalescing + soft-fail + **watchdog**:
  `SPLITS_BUILD_TIMEOUT_S`, default 120 s; `SPLITS_BUILDER` override for tests),
  boot build when `SPLITS_INGEST_TOKEN` set.
- `ingest-store.mjs` — validation (calendar dates, expanded fields, RHR) +
  atomic banking (`bankRun`/`bankRhr`, null-proto stores, tmp cleanup on error).
- `ingest_builder.py` — full derivation set above; row-tolerant (`_usable`),
  dense monthly arrays, case-insensitive sport labels, non-object store tolerance.
- `Running Dashboard.dc.html` / `progress.dc.html` — degradation guards + the
  two new surfaces. `chart-core.js` — `restingHr` policy.
- `docker-compose.yml` — `splits-max` service (profile `max`).
- Tests: `test_ingest_api.mjs`, `test_ingest_store.mjs`, `test_ingest_builder.py`
  (28 cases), `test_ingest_e2e.mjs`, `test_build_watchdog.mjs`,
  `test_slim_render.mjs` (real-builder fixtures: 2-run Max, 0-run fresh boot,
  Garmin-shaped Felix regression; also verifies D8 archive-route degradation).
- `test_cockpit_page.mjs` — deflaked the 'anchorless week inert' step (rapid
  ArrowRights race the re-render; now steps toward W21 with overshoot correction).
- `android-bridge/` — Kotlin spike (= production app base): reads sessions +
  HR/distance/speed + all 4 additions with `dataOrigin` filtering; manifest
  already declares **all 11** READ permissions.
- OpenSpec: tasks 4.x/5.1/8.x/9.x/10.x ticked with annotations;
  `specs/telemetry-ingest/spec.md` extended with the expansion requirements.

## Empirical facts that still bind (from the 2026-07-15 spike)

- `dataOrigin` filtering is MANDATORY (D14) — unfiltered reads double-count.
- Samsung writes session/HR/distance/speed/calories/RHR — NOT cadence, NOT
  elevation, NOT route. → cadence/elevation stay null for Max; the builder
  derives cadence only when steps exist (Garmin-sourced data has them).
- Payload shape verified on 14 real runs; `metadataId`→`sessionUid`.

## The open gate — task 1.4 (highest remaining risk)

Unchanged: Samsung Health `7.00.0.107` reportedly broke exercise-session writes
to HC (~July 1 2026; fix 7.00.5.009 sideload-only). To close: record a run **in
Samsung Health** (HC sync on) → re-run the spike → look for a
`com.sec.android.app.shealth` source. If NO → manual entry fallback.

## Recommended resume order

1. **5.2** Max's `plan-data.js` (needs Felix: race choice/date, then author a
   beginner→half `block` — see running-data.js:20; validate with test_plan_validate).
2. **6.1–6.3** finish the app: map the spike's diagnostic JSON onto the ingest
   payload (field names in “Ingest contract” above), WorkManager sync, config
   screen (server URL + token), backfill + retry. Start **6.4 Declaration** early.
3. **Physical:** 1.4 gate, 5.3 network path (Tailscale vs reverse proxy), 5.4
   NUC smoke (`--profile max`), 6.5 sideload.

## Environment & operational gotchas (Windows dev)

- **`python3` is a Microsoft Store alias** that fails when spawned → use `python`
  or set `SPLITS_PYTHON=python`. Tests set it themselves.
- **Windows port sharing (SO_REUSEADDR)**: two listeners can silently share a
  port — a stray server can hijack test requests (observed: slim test rendered
  Felix's live data). `test_slim_render` therefore uses ports 18471+ AND verifies
  server identity via `/garmin-data.js` before driving the browser. Prefer that
  pattern for new integration tests.
- **repo `garmin-data.js`/`plan-data.js` are LIVE symlinks** to the homeserver
  volume — dev servers started with `SPLITS_DATA_DIR` never touch them, but
  don't run a bare `node serve.mjs` and push/build against the repo root.
- **Git Bash MSYS path conversion** mangles adb remote paths → prefix
  `MSYS_NO_PATHCONV=1` and give adb a `C:/`-form local destination.
- **AGP 9+ has built-in Kotlin** — do NOT add `org.jetbrains.kotlin.android`.
- **Build the app with JDK 21**: `JAVA_HOME="/c/Program Files/Android/Android Studio/jbr"`.
  SDK at `C:\Users\felix\Android\Sdk`.
- **Python console cp1252**: scripts printing `✓` need
  `sys.stdout.reconfigure(encoding="utf-8")`.

### Commands

```bash
# server-side tests (from repo root)
node test_ingest_store.mjs
SPLITS_PYTHON=python node test_ingest_api.mjs
python test_ingest_builder.py
SPLITS_PYTHON=python node test_ingest_e2e.mjs
node test_build_watchdog.mjs
node test_plan_push.mjs

# frontend degradation + regression (Playwright)
node test_slim_render.mjs
node test_cockpit_page.mjs && node test_progress_page.mjs

# build + run the spike (device = Galaxy S24 SM-S921B, all 11 perms granted)
JAVA_HOME="/c/Program Files/Android/Android Studio/jbr" android-bridge/gradlew -p android-bridge :app:assembleDebug --console=plain
adb install -r android-bridge/app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n com.splits.healthspike/.MainActivity
adb shell input tap 539 115   # taps "READ RUNNING WORKOUTS"
MSYS_NO_PATHCONV=1 adb pull /storage/emulated/0/Android/data/com.splits.healthspike/files/splits_spike_runs.json "C:/<abs-windows-path>.json"
# spike output is { runs: [...], restingHeartRate: [...] }
```

## Nothing is committed yet

The working tree holds everything (new files + serve.mjs/dashboard/progress/
chart-core/docker-compose edits + OpenSpec artifacts). Commit when ready — Felix
hasn't asked to yet. No Co-Authored-By line (per global CLAUDE.md).
