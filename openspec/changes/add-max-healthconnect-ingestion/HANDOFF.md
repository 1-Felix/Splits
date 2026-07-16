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
fixes. **The Android bridge app is now production-complete too (6.1–6.3 +
the 7.3 payload mapping, verified end-to-end on the S24 2026-07-16).** What
remains is **physical/collaborative**: the 1.4 Samsung gate, Max's plan (5.2),
network path (5.3), the Developer Declaration (6.4), and sideloading to Max's
Pixel (6.5).

## Status (what's done vs left)

| Group | What | State |
|---|---|---|
| 1 | Health Connect extraction spike | 1.1✓ 1.2✓ 1.3✓ **1.4 OPEN (gate)** 1.5✓ |
| 2 | `POST /api/ingest` + JSON run store | ✅ built + tested |
| 3 | Python telemetry builder | ✅ built + tested |
| 4 | Dashboard degradation guards | ✅ **done 2026-07-16** — readiness DID crash the page (repro'd); guarded + Playwright-tested |
| 5 | Deployment | 5.1✓ 5.4✓ (**NUC live 2026-07-16**, see below) · 5.2 plan / 5.3 network **open** |
| 6 | Finish the Android app | 6.1✓ 6.2✓ 6.3✓ (**built + on-device-verified 2026-07-16**) · 6.4 Declaration / 6.5 Max sideload **open** |
| 7 | Reader scope-expansion | 7.1✓ 7.2✓ · 7.3 payload mapping ✓ (IngestClient); Declaration paperwork open (rides 6.4) |
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

One image, config-only difference. Max's compose service exists behind a profile
in the repo template (`docker compose --profile max up -d`, port 8001).

## NUC deployment (LIVE since 2026-07-16)

- Committed, pushed, CI image built, and **both instances deployed on the
  NUC**: `splits` (Felix, host port 5732, verified untouched) and `splits-max`
  (host port 5733 on the LAN **and public since 2026-07-16 evening**:
  `https://splits-max.mochii.dev` via Cloudflare Tunnel → traefik — dashboard
  behind `pocketid-auth`, `/api/ingest` on its own higher-priority SSO-free
  router; gotcha: the service must be on the `proxy` network or traefik hangs).
  Max needs a pocket-id account to view his dashboard (Felix admin task).
  Max's plan (5.2) live on the volume; `ATHLETE_AGE=25` set.
- NUC compose: `~/dev/docker-compose-files/splits/docker-compose.yml` (backup
  `docker-compose.yml.bak-2026-07-16`); volume `./volumes/splits-max-data`.
- The ingest token lives in that folder's `.env` as `SPLITS_INGEST_TOKEN_MAX`
  (generated 2026-07-16) — the bridge app will need this value + the URL.
- 5.4 smoke PASSED on the NUC: curl run + RHR payloads → 200 → rebuilt
  telemetry had correct pace/volume/zones (Karvonen), energy, calibrated maxHR;
  smoke data then removed, instance back to a clean 0-run state with the
  default seeded plan.

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
- `android-bridge/` — **now the production bridge app** (spike evolved in place,
  2026-07-16): `BridgeConfig` (prefs: URL/token/backfill date + pushed-UID and
  RHR-watermark bookkeeping), `RunReader` (all HC reads, `dataOrigin`-filtered),
  `IngestClient` (payload mapping + bearer POST, suspend/IO — a main-thread POST
  threw NetworkOnMainThreadException on-device before), `SyncEngine` (full-window
  re-scan + unseen-UID push + 7-day-overlap RHR + 10-min session settle guard),
  `SyncWorker` (6 h periodic WorkManager, Result.retry() on transient),
  `MainActivity` (config UI + grant flow + Sync now + the diagnostic GATE dump
  kept for 1.4 + reset-delivery-state). Manifest adds INTERNET +
  `usesCleartextTraffic` (private LAN/tailnet transport until 5.3; https works
  unchanged). Deps + `androidx.work:work-runtime-ktx:2.11.2`. App label now
  "SPLITS Bridge"; applicationId unchanged (`com.splits.healthspike`) so the
  existing permission grants survive upgrades.
- OpenSpec: tasks 4.x/5.1/8.x/9.x/10.x ticked with annotations;
  `specs/telemetry-ingest/spec.md` extended with the expansion requirements.

## Empirical facts that still bind (from the 2026-07-15 spike)

- `dataOrigin` filtering is MANDATORY (D14) — unfiltered reads double-count.
- Samsung writes session/HR/distance/speed/calories/RHR — NOT cadence, NOT
  elevation, NOT route. → cadence/elevation stay null for Max; the builder
  derives cadence only when steps exist (Garmin-sourced data has them).
- Payload shape verified on 14 real runs; `metadataId`→`sessionUid`.

## The gate — task 1.4 (MOSTLY CLEARED 2026-07-16 on the S24)

**GATE: YES.** Samsung Health `7.00.5.009` (now on regular rollout — Felix's S24
has it) writes running `ExerciseSession`s + distance + speed series + calories
to HC, and **backfilled 4 historic workouts** once allowed to write.

**Root cause of the earlier `GATE: NO`: Health Connect denies Samsung Health
WRITE permissions by default** (`WRITE_EXERCISE: granted=false` while READ was
granted). Fix: Health Connect → App permissions → Samsung Health → enable the
Write toggles. This is a mandatory Max-onboarding step or his feed is silently
empty.

**Left for Max's Pixel:** check the Samsung Health version (Play-Store-update if
`7.00.0.107`), grant the HC write toggles, record a **watch** run and confirm HR
samples arrive (phone-recorded and Samsung phone-auto-detected sessions carry
**no HR**; the watch path is what Max will use). The app's "Diagnostic dump"
button now also lists ALL sessions (any type/source) to debug sync issues fast.

## On-device E2E verification (2026-07-16, Galaxy S24 + local dev server)

Dev server (`PORT=18497`, scratchpad `SPLITS_DATA_DIR`, `SPLITS_INGEST_TOKEN`)
+ `adb reverse tcp:18497 tcp:18497` so the app reached `http://127.0.0.1:18497`:

- Backfill from 2026-05-01: **26 runs + 76 RHR days pushed**, server banked 26,
  builder produced a full contract — maxHR **187** calibrated from observed (D9),
  Karvonen restingHR **51** (D12), recentRuns with pace/cad/`detail.splits`
  (D10/D11), ctl/atl, heatmap 365, Riegel predictions, `history.restingHr` 76 d;
  vo2/readiness/sleep keys absent.
- Idempotency: the background pass that ran right after scheduling pushed **0**.
- Retry (6.3): reverse removed → "Server unreachable … will retry", no UID
  marked; restored → 26 re-pushed, server still 26 (upsert, no dupes).
- WorkManager: `#SyncWorker#` visible in `dumpsys jobscheduler`.

## Recommended resume order

1. **1.4 the gate**: record a Samsung Health run on the Galaxy Watch → tap
   "Diagnostic dump (gate check)" in the bridge app → look for a
   `com.sec.android.app.shealth` session source / GATE: YES.
2. ~~5.2 Max's plan~~ — DONE 2026-07-16: 40-week beginner→half live on the NUC
   volume (race anchor Sun 2027-04-25, Allgäu half TBD; regenerate with
   `max-plan-generator.py` in this folder when he registers — edit RACE/START,
   run, validate, docker-exec onto the volume; default seed backed up as
   `plan-data.js.bak-default`).
3. ~~5.3 network path~~ — DONE: public traefik route `https://splits-max.mochii.dev`
   (ingest SSO-exempt; dashboard on the NEW `pocketid-auth-family@file`
   middleware — 403s until the pocket-id groups exist, see below).
4. ~~6.4 Declaration~~ — RESOLVED: sideload-only needs no filing (form retired
   into Play Console; enforcement targets Play apps). Watch-item: Play
   closed-testing under the AirPipe account if that changes.
5. **Felix's pocket-id admin steps (before Max's dashboard works):** at
   pocket-id.felix-keller.com create groups `admin` (Felix) and `family`
   (Felix + Max), create user `max` + one-time access link → Max registers a
   passkey on his Pixel. AFTERWARDS, optionally lock the main `pocketid-auth`
   middleware to `admin` — the prepared Authorization block is left commented
   in traefik's fileConfig.yml (until then any pocket-id account passes SSO on
   ~24 services incl. code-server).
6. **6.5** onboard Max's Pixel: Samsung Health ≥ 7.00.5.009 (Play-update if
   7.00.0.107) → Health Connect → App permissions → Samsung Health → enable
   WRITE toggles (the gate's root cause!) → watch-run → app's Diagnostic dump
   wants GATE: YES **with hrSampleCount > 0** → configure the bridge app: URL
   `https://splits-max.mochii.dev` + `SPLITS_INGEST_TOKEN_MAX` (NUC `.env`) +
   backfill date → Sync now → verify set-and-forget over several days.

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

# build + run the bridge app (device = Galaxy S24 SM-S921B, all 11 perms granted)
# applicationId renamed 2026-07-16 (Play-clean): com.splits.bridge; the CODE
# namespace stays com.splits.healthspike, so the component is the mixed name:
JAVA_HOME="/c/Program Files/Android/Android Studio/jbr" android-bridge/gradlew -p android-bridge :app:assembleDebug --console=plain
adb install -r android-bridge/app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n com.splits.bridge/com.splits.healthspike.MainActivity
# UI (top→bottom): URL / token / backfill-date fields, then buttons:
#   GRANT PERMISSIONS · SYNC NOW · DIAGNOSTIC DUMP (GATE CHECK) · RESET DELIVERY STATE
# logs: adb logcat -s SPLITS_BRIDGE
# local E2E: adb reverse tcp:<port> tcp:<port> → app URL http://127.0.0.1:<port>
# diagnostic dump still writes the pullable file with the GATE verdict:
MSYS_NO_PATHCONV=1 adb pull /storage/emulated/0/Android/data/com.splits.bridge/files/splits_spike_runs.json "C:/<abs-windows-path>.json"
```

## Commit state

Server side + spike are committed and NUC-deployed (`8021c43`…`f525d13`,
see the NUC section). **The 2026-07-16 bridge-app work (6.1–6.3) is uncommitted**
— `android-bridge/` app sources + manifest + gradle + these OpenSpec updates.
Commit when Felix asks. No Co-Authored-By line (per global CLAUDE.md).
