# Tasks: wellness-archive

## 1. Fixtures first (design D6)

- [x] 1.1 Capture and check in two real `get_sleep_data` payloads — one from a 2024 date (7 top-level keys) and one recent (18 keys) — plus their `get_hrv_data` counterparts, scrubbed of `userProfilePk`
- [x] 1.2 Capture an `hrvSummary` from the onboarding window (`status: "NONE"`, `baseline: null`) — the null case must be a fixture, not an afterthought

## 2. Schema (designs D1, D2, D3)

- [x] 2.1 Additive migration on `daily_wellness`, guarded by the existing `PRAGMA table_info` idempotency pattern: `sleep_json`, `hrv_json`, `fetched_at`, and the promoted columns (`sleep_seconds`, `deep_seconds`, `rem_seconds`, `light_seconds`, `awake_seconds`, `sleep_score`, `respiration_avg`, `body_battery_change`, `hrv_last_night`, `hrv_weekly_avg`, `hrv_balanced_low`, `hrv_balanced_upper`, `hrv_status`) — `baseline` is an object `{lowUpper, balancedLow, balancedUpper, markerValue}`, so the band columns take `balancedLow`/`balancedUpper`
- [x] 2.2 `_apply_schema_v5`, `SCHEMA_VERSION = 5` (v6 is pre-assigned to `run-detail`; both migrations are additive and guarded, so either may land first — the numbers are fixed only to avoid conflicting on the same line). If `run-detail` lands first, `SCHEMA_VERSION` is already 6 and this task only adds `_apply_schema_v5` to the migration chain
- [x] 2.3 Comment `raw_json` for what it actually holds — the sync's computed readiness snapshot, not a Garmin payload — and leave it in place (design D2)
- [x] 2.4 Raw payload columns are **upgrade-only** (design D1, corrected): an upsert replaces a stored payload only when the stored one carries no device data (`sleep_seconds IS NULL`) and the incoming one does. A literal write-once would freeze the hollow payload Garmin returns for a night it has not yet finalised — `fetch_sleep()` re-fetches the same 14 nights every sync for exactly that reason. Promoted columns are freely recomputed
- [x] 2.5 Test: migration is additive (an older reader ignores the new columns), upgrade-only holds in both directions (hollow→data replaces; data→hollow does not), the readiness snapshot survives a backfill upsert, and the three `fetched_at` states round-trip

## 3. Extraction (designs D1, D6)

- [x] 3.1 Pure `promote_wellness(sleep_payload, hrv_payload) → dict` over the two payloads; no network, no clock
- [x] 3.2 Read `resting_hr` from the sleep payload's top-level `restingHeartRate`; fall back to `get_rhr_day` when that **value is null**, not when the payload is absent (the `empty-night` fixture is a present-but-hollow payload whose `restingHeartRate` is null, while `get_rhr_day` for the same date returns 56.0)
- [x] 3.3 Handle both payload eras from the task-1 fixtures; a field that moved between eras SHALL be found, not silently nulled
- [x] 3.4 Null (not zero) for absent metrics; `hrv_balanced_*` and `hrv_status` null through the onboarding window. Promoted columns are independently nullable — the empty night has null sleep metrics while HRV `weekly_avg` and the baseline band remain populated
- [x] 3.5 Tests over all three fixtures: 2024 era, 2026 era, and the unworn night

## 4. Backfill (design D4)

- [x] 4.1 `sync_garmin.py --backfill-wellness`: walk dates from the archive's earliest activity to today, newest-first, skipping any date whose row already has `fetched_at`
- [x] 4.2 Two calls per date (`get_sleep_data`, `get_hrv_data`), each through the existing `safe()` wrapper; a failing date leaves `fetched_at` NULL so the next run retries it
- [x] 4.3 Fixed inter-request delay plus a `--since` bound, so ~1,600 calls can be spread across nights if Garmin objects
- [x] 4.4 Its own completion marker in `archive_meta` (`wellness_backfill_completed_at`) — distinct from the activity backfill's, so "which backfills have run?" is answerable
- [x] 4.5 Tests: resumability against a fixture archive (interrupt, re-run, converge), idempotence (a second full run makes no writes), and that a failed date does not mark itself fetched

## 5. Steady state (design D5)

- [x] 5.1 `fetch_sleep()` surfaces the raw payloads it already fetches instead of discarding them; `wellness_step()` upserts all fourteen nights
- [x] 5.2 Top up `get_hrv_data` only for nights in the window still missing HRV
- [x] 5.3 Keep the ordering and fail-soft contract exactly as today — after `garmin-data.js` is written, inside `safe()`, never able to fail a sync
- [x] 5.4 Confirm the nightly call count does not increase in steady state (the sleep payloads were already being fetched)
- [x] 5.5 Test: a night missed while the container was down is banked by the next sync that still sees it in the fourteen-night window

## 6. Verification (design D3)

- [x] 6.1 `--verify-archive` reports wellness coverage against the expected span (earliest activity → today): rows present, rows fetched, rows with data, and the gap list
- [x] 6.2 Exit non-zero when wellness coverage regresses
- [x] 6.3 Distinguish "never asked" from "asked, no data" in the report — a legitimately empty night is not a gap

## 7. Run it, and spec sync

- [x] 7.1 Run `--backfill-wellness` against the live account overnight; record the real call count, wall time, and any rate-limit behaviour in the change's notes
- [x] 7.2 Verify coverage from 2024-05-12 to today; confirm the onboarding window's HRV baselines are null rather than zero
- [x] 7.3 Confirm `garmin-data.js` is byte-identical before and after (this change ships no payload change)
- [x] 7.4 Update `openspec/specs/activity-archive/spec.md` from the delta; note in `README.md` that wellness raw payloads are archived and how to backfill
