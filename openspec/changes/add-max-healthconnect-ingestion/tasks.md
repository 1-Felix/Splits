## 1. Phase 0 — Health Connect extraction spike (verify before building)

- [x] 1.1 Minimal Kotlin reader using `androidx.health.connect:connect-client`, requesting `READ_EXERCISE`, `READ_HEART_RATE`, `READ_DISTANCE`, `READ_SPEED` (plus `READ_HEALTH_DATA_HISTORY` and `READ_HEALTH_DATA_IN_BACKGROUND`) — *scaffolded at `android-bridge/` (connect-client 1.1.0, AGP 9.2/Gradle 9.4.1, minSdk 26); HR reads paged via `pageToken`; the Android-14 permission-usage `activity-alias` included*
- [x] 1.2 Read recent running `ExerciseSession` records + their HR samples / distance / speed within each session window; dump the result as JSON — *filters `EXERCISE_TYPE_RUNNING`(+treadmill); emits per-run JSON incl. `sourcePackage`/`isSamsungHealth` + a `GATE: YES/NO` verdict; output to Logcat `SPLITS_SPIKE` + a pullable file. Build/install/run remains a physical step (1.3)*
- [x] 1.3 `adb install` on the Galaxy S24, grant permissions, capture JSON for the Garmin-sourced runs already in Health Connect — confirms the read path and the real field shape — *DONE 2026-07-15: HC SDK AVAILABLE, 6/6 perms, 14 running sessions read; all 14 carry avgHR + HR series + distance + speed; source = com.garmin.android.apps.connectmobile*
- [ ] 1.4 **Decision gate:** on Max's Pixel (Samsung Health 7.00.0.107), record an outdoor run on the Galaxy Watch and confirm an `ExerciseSession` with HR actually lands in Health Connect. If Samsung does not write sessions on this build, stop and fall back to manual entry until it is fixed — *STILL OPEN: spike reported `GATE: NO Samsung Health runs` — all sampled runs were Garmin-sourced; needs a Samsung Health-recorded workout to answer*
- [x] 1.5 Freeze the run payload schema (fields + Health Connect session UID + downsampled HR series) from what the spike actually returned — *confirmed against real data; `metadataId`→`sessionUid`, `heartRate[]` already `{tSec,bpm}`, maps 1:1 to the ingest contract*

## 2. Server — ingest endpoint + run store

- [x] 2.1 Define the banked-run store in the instance data dir (dedicated schema: `startTimeLocal`, `durationS`, `distanceM`, `avgHr`, `hrSamples`, `sportType`, `sessionUid`) — decoupled from the Garmin archive — *implemented as a JSON store keyed by `sessionUid` (`ingest-store.mjs` → `ingested-runs.json`); JSON over SQLite for cross-language Node-write/Python-read at this volume*
- [x] 2.2 Add `POST /api/ingest` to `serve.mjs`: `SPLITS_INGEST_TOKEN` bearer auth, size cap, atomic write; route absent (404) when the token is unset — patterned on `PUT /api/plan`
- [x] 2.3 Idempotent banking by `sessionUid` (upsert, no duplicates)
- [x] 2.4 Tests: authorized push banks the run; missing/invalid token → 401; token unset → 404; oversized body → 413; re-ingest of the same UID → a single stored run — *`test_ingest_api.mjs`, all green; plan-push regression green*

## 3. Server — telemetry builder

- [x] 3.1 Builder module (Python, alongside `sync_garmin.py`) that reads banked runs and produces `athleteData`: `recentRuns`, `weeklyKm`/`weeklyRuns`, monthly `paceSecPerKm`, `heatmapKm[365]` — *`ingest_builder.py`*
- [x] 3.2 Reuse `insight_metrics` for `ctl`/`atl` (TSS EWMA) and `predictions` (Riegel), consistent with the Garmin pipeline — *formulas mirrored verbatim (same `/42` `/7` EWMA, `^1.06` Riegel) with source citations; not import-coupled to Garmin-shaped code*
- [x] 3.3 Compute weekly `hrZones` by binning each run's HR samples against `profile.maxHR`-derived bounds (zone policy lives server-side) — *`maxHR` from `ATHLETE_MAX_HR` env / `220−age`; 30 s pause cap on sample gaps*
- [x] 3.4 Omit non-goal fields (`profile.vo2maxCurrent`, `history.vo2max`, `readiness`, `history.sleep`) entirely; enforce invariants (integer pace sec/km, `heatmapKm.length === 365` ending today, history arrays oldest→newest) — *`history.vo2maxStartMonth` kept as the pace-axis anchor per the degradation audit*
- [x] 3.5 Run the builder single-flight after each successful ingest and on boot; write `garmin-data.js` atomically — *`triggerBuild()` in `serve.mjs`, fire-and-forget + soft-fail + coalescing; boot build gated on `INGEST_TOKEN`*
- [x] 3.6 Tests: built telemetry passes the contract invariants; non-goal fields absent; a run flows end-to-end (ingest → build → appears in `recentRuns`, volume, `ctl`, `hrZones`) — *`test_ingest_builder.py` (10 cases) + `test_ingest_e2e.mjs` (real subprocess build), all green*

## 4. Dashboard degradation (protect the one-image principle)

- [x] 4.1 Verify the VO₂ hero and progress views render an empty/hidden state when `vo2max`/`readiness`/`sleep` keys are absent; add guards if any panel throws (D7) — *readiness DID throw (`renderVals` blanked the page — repro'd); guarded cockpit (hasReady/hasVo2/hasSleep + null-halfNow + zero-division zones) and progress (hasVo2); `test_slim_render.mjs` drives REAL builder output (2-run, 0-run, Garmin-shaped fixtures); cockpit+progress regression suites green*
- [x] 4.2 Verify `/run/:id`, `/archive`, `/compare` show empty/degraded states on an ingest-fed instance instead of erroring (D8) — no per-instance routing added — *verified by test: all three render their "Archive offline" / "Nothing to compare yet" states with zero page errors*

## 5. Deployment — Max's instance

- [x] 5.1 Add a second compose service + volume for Max: no Garmin credentials, `SYNC_ON_BOOT=off` / `SYNC_AT=off`, `SPLITS_INGEST_TOKEN` set — *`splits-max` service behind an opt-in compose profile (`docker compose --profile max up -d`), port 8001, own volume; `compose config` validates; NUC rollout itself is 5.4*
- [ ] 5.2 Author Max's `plan-data.js` (beginner→half marathon, Felix + AI); validate against the plan schema
- [ ] 5.3 Establish the phone→NUC network path (Tailscale or TLS reverse proxy) so the app reaches `/api/ingest` securely
- [ ] 5.4 End-to-end smoke: spike app (or a curl-simulated payload) → `/api/ingest` → the run shows on Max's dashboard with correct pace/volume/load/zones, and Felix's instance is unaffected

## 6. Finish the Android app (Phase 2)

- [ ] 6.1 Background recurring sync (WorkManager); one-time permission grant flow; config screen for server URL + token
- [ ] 6.2 First-run backfill since a configured start date, incremental thereafter, idempotent by session UID
- [ ] 6.3 Retry with no data loss when the ingest endpoint is unreachable
- [ ] 6.4 Complete Google's Health Connect Developer Declaration for sideloaded data-type access (start early — schedule risk, not feasibility)
- [ ] 6.5 Sideload to Max's Pixel and verify set-and-forget operation over several days

## 7. Scope expansion — bridge reader (data-types research; proven in the extended spike)

- [x] 7.1 Harvest per-run **max HR** from the HR series; read `ElevationGained`, `Active`/`TotalCaloriesBurned`, `Steps` (DELTA → summed); read `RestingHeartRate` (daily, over window); emit a downsampled **speed series** — *proven on 14 real Garmin runs (extended spike)*
- [x] 7.2 Filter EVERY metric read by the session's `dataOrigin` (double-count fix — MANDATORY) — *proven: fixed steps 302→~155 spm and total calories 8-records→1*
- [ ] 7.3 Port 7.1/7.2 into the production bridge app + add the 5 new READ permissions to the manifest + update the Google Health Connect Developer Declaration — *reader code + all 11 manifest permissions already live in `android-bridge/` (the spike is the production app's base, group 6); OPEN: map the spike's diagnostic JSON onto the ingest payload shape during 6.1, and the Declaration paperwork (with 6.4)*

## 8. Scope expansion — ingest payload + validation

- [x] 8.1 Extend the run payload: `maxHr`, `elevationGainM`, `activeKcal`, `totalKcal`, `steps`, `speedSamples[{tSec,mps}]`; plus a separate daily `restingHeartRate` series (banked apart from runs) — *RHR rides the same `POST /api/ingest` as its own payload form `{restingHeartRate:[{date,bpm}]}` → `ingested-rhr.json` keyed by date (upsert)*
- [x] 8.2 Extend `validateRunPayload` for the new optional fields — *optional, null-defaulted, range-checked; `validateRhrPayload` added; store + API tests green*

## 9. Scope expansion — builder

- [x] 9.1 Zone bounds + CTL/ATL intensity from observed `maxHr` (fallback `220−age` only when absent) — *effective maxHR = max(explicit `ATHLETE_MAX_HR`, observed per-run max); 220−age only when neither exists*
- [x] 9.2 Karvonen HR-reserve zones when `restingHr` present (D12) — *bounds = rhr + fraction×(max−rhr); rhr = median of last ≤7 banked days; emitted as `profile.restingHR`*
- [x] 9.3 Moving pace (strip pauses via the speed series) for `recentRuns` / monthly pace / the Riegel anchor (D10) — *`moving_effort()` strips <1.7 m/s intervals from time AND distance; elapsed fallback without a series*
- [x] 9.4 Per-km splits from the speed/distance series (D11) — *emitted as a Garmin-shaped `recentRuns[].detail` (splits/hrSeries/driftBpm/zoneMin/splitShape, formulas mirrored from sync_garmin) so the existing run-card drill-down + coach-read light up unchanged*
- [x] 9.5 Cadence = steps ÷ moving-minutes when steps present (stays null for Samsung) — *per-run `cad` + monthly `cadenceSpm`*
- [x] 9.6 Elevation + calories into `recentRuns` + an energy tile (D13) — *elevation → `detail.elevGain`; `energy.weekKcal` (totalKcal, activeKcal fallback) → new ENERGY KPI tile, hidden when the key is absent (Felix unchanged)*
- [x] 9.7 RHR trend series in `history` + a dashboard trend line (D12) — *`history.restingHr` last 90 days → new Resting HR card (median-band line, `POLICIES.restingHr` added to chart-core), hidden when absent*
- [x] 9.8 Tests for each derivation — *`test_ingest_builder.py` (28 cases) + `test_slim_render.mjs` asserts tile/card show for Max and stay hidden for Felix*

## 10. Adversarial-review fixes (server core)

- [x] 10.1 Date-poison: reject calendar-invalid dates in validation **and** wrap the builder's per-run work in try/except so one bad row can't wedge every rebuild — *validation rejects roll-over dates (`test_ingest_store.mjs`); builder `_usable()` skips poisoned/zero/non-object rows (`test_ingest_builder.py`)*
- [x] 10.2 Dense `monthly_pace` array (`None` for gap months) so charts don't mislabel — *dense first→last active month (`test_monthly_pace_dense_over_gap_months`)*
- [x] 10.3 Reject `sessionUid: "__proto__"` / build the store with `Object.create(null)` — *both: validation rejects, and `bankRun` uses a null-prototype store (the silent-drop repro'd in `test_ingest_store.mjs`)*
- [x] 10.4 Watchdog timeout on the builder child in `triggerBuild` — *kills + unlatches after `SPLITS_BUILD_TIMEOUT_S` (default 120 s); proven unwedged by `test_build_watchdog.mjs`*
- [x] 10.5 sportType lowercase before label lookup; Python store non-object tolerance; `bankRun` tmp cleanup on error; ZeroDivisionError guard — *all four TDD'd (`test_ingest_builder.py` + `test_ingest_store.mjs`); zero-distance guard rides `_usable()`*
