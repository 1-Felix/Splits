# Proposal: wellness-archive

## Why

`daily_wellness` holds **one row**, and it is not what the spec says it is.

The `activity-archive` spec requires each sync to bank the day's wellness values
*"together with the raw fetched payload."* The implementation
(`wellness_step()` → `upsert_wellness(conn, TODAY, {...}, readiness)`) stores
SPLITS' own **computed readiness dict** in `raw_json`:

```json
{"score": 50, "status": "Moderate", "hrv": 52, "restingHR": 53,
 "sleepHours": 6.0, "trainingLoad": 52, "loadStatus": "Maintaining"}
```

That is a derived artifact, not a Garmin payload. There is nothing stored to
re-derive from, so nothing about sleep, HRV, or resting heart rate can ever be
recomputed or extended backwards from the archive. Meanwhile the sync *already
fetches* fourteen nights of raw `get_sleep_data` on every run
(`fetch_sleep()`), keeps `hours`, `hrv`, and `deepPct`, and throws the rest away.

The consequence is a hard ceiling. `history.sleep` is fourteen nights, forever.
A personal HRV baseline band — the single most-read screen in Garmin's own app,
and the reference layer `chart-engine` wants for HRV — cannot be computed from
fourteen points. Resting-HR trend, sleep debt, and any seasonal reading of
recovery are simply unavailable.

**A live probe on 2026-07-10 settled the feasibility question** (read-only, cached
tokens):

```
date         lastNightAvg  weeklyAvg  baseline  status        hrvReadings
2024-05-12             59       None      null  NONE                    0
2024-06-20             39         47      set   UNBALANCED              0
2025-01-15             43         44      set   LOW                     0
2026-07-05             56         59      set   BALANCED               91
```

Sleep, HRV summaries, and resting HR all reach back to **2024-05-12** — the
archive's first activity. Three findings shape this change:

- **`hrvReadings` is not backfillable.** The five-minute overnight samples are
  empty on every historical date and populated only recently. Garmin retains raw
  readings for a rolling window. Nightly *summaries* are all history offers.
- **The sleep payload carries `restingHeartRate` at its top level**, so
  `get_rhr_day` is redundant — two calls per date, not three.
- **The payload shape drifts.** Sleep's top-level key count grew from 7 in May
  2024 to 18 today (`avgOvernightHrv`, `hrvStatus`, `sleepStress`,
  `sleepBodyBattery`, `respirationVersion` are all recent). Anything derived at
  fetch time and not stored is lost. **Store raw, derive later** — exactly the
  discipline `activities.summary_json` / `detail_json` already follow.

## What Changes

- **The wellness row stores raw payloads, write-once.** An additive schema
  migration gives `daily_wellness` a `sleep_json` and an `hrv_json` column
  holding the Garmin payloads verbatim, alongside promoted columns that index
  them (deep/REM/light/awake seconds, sleep score, respiration, body-battery
  change, HRV last-night average, weekly average, baseline bounds, status). The
  existing `raw_json` keeps the readiness snapshot it has always held, and is
  documented as such rather than pretending to be raw.

- **Fetched and absent are different states.** A `fetched_at` column plus null
  metrics distinguishes *"the watch was off the wrist"* from *"we never asked."*
  Charts must not bridge a null, and a chart cannot tell the difference unless
  the archive can.

- **`sync_garmin.py --backfill-wellness`** — idempotent, resumable, rate-limit
  aware, in the shape of the existing activity backfill. Roughly 790 dates × 2
  calls ≈ 1,600 requests, one overnight run. Resumes from the newest banked date;
  a re-run is a no-op.

- **Steady state gets cheaper, not dearer.** `fetch_sleep()`'s fourteen-night
  loop already pulls the raw payload; it now banks each one instead of
  discarding it. HRV is fetched only for nights missing it. Fail-soft, always
  after `garmin-data.js` is written — the existing contract.

- **Coverage is verifiable.** `--verify-archive` reports wellness coverage
  against the expected date span (first activity → today), names the gaps, and
  exits non-zero on regression, matching the distilled-detail coverage check.

**Zero UI.** This is a pure data layer, exactly as stage 1 `activity-archive`
was. `garmin-data.js` is not widened here; the dashboard payload change is the
follow-up (`history-depth`), which is also what turns `chart-engine`'s HRV
baseline band from fourteen thin points into a real reference.

## Capabilities

### Modified Capabilities

- `activity-archive`: the daily wellness record stores raw Garmin payloads and
  promoted columns rather than a derived readiness dict; historical wellness
  backfill moves from *"explicitly out of scope"* to a supported, resumable
  mode; wellness coverage joins the verification report; absent and unfetched
  days are distinguishable.

## Impact

- **Code:** `activity_archive.py` (additive migration; `upsert_wellness`
  signature; coverage), `sync_garmin.py` (`--backfill-wellness`, raw banking in
  `fetch_sleep`, HRV top-up), `validate_data.py` (unchanged — no payload change).
- **Tests:** `test_activity_archive.py` (migration additivity, write-once raw,
  fetched-vs-absent, coverage regression), `test_sync_garmin` equivalents for
  the backfill's resumability against a fixture, and a fixture pair capturing
  the 2024-era and 2026-era sleep payload shapes so the promoted-column
  extraction is proven against both.
- **Data:** roughly 790 new `daily_wellness` rows; raw payloads add a few tens of
  megabytes at most. No activity data touched.
- **Schema:** one additive migration, guarded by the existing `PRAGMA
  table_info` idempotency pattern, taking **v5**. (`run-detail` takes v6. The
  numbers are pre-assigned rather than left to merge order, because both changes
  bump `SCHEMA_VERSION` in the same line of `activity_archive.py` and would
  otherwise conflict on every rebase. The migrations themselves are additive and
  order-independent, so either may land first.)
- **API budget:** ~1,600 one-time requests. The nightly sync's call count is
  unchanged (raw payloads it already fetches are now kept).
- **Sequencing:** independent of `vendor-runtime`, `chart-engine`, and
  `run-detail`; it can run in parallel with all of them because it touches no
  template and no chart. It should start early — a backfill's value compounds
  with the history it accumulates, and every night not banked is a night whose
  raw payload may drift further from what the API will later return.
