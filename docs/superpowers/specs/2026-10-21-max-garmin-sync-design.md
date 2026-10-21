# Max on Garmin: switch `splits-max` from Health Connect to Garmin sync

Date: 2026-10-21 · Status: approved by Felix 2026-10-21

## Intent

Max (Felix's brother, 23, beginner, half-marathon block to 2027-04-25) got a
**Forerunner 265S**. It replaces his Galaxy Watch outright. His SPLITS instance
(`splits-max`, NUC port 5733, `https://splits-max.mochii.dev`) has been fed since
2026-07-17 by the self-built Health Connect bridge app through `POST /api/ingest`.
From now on it should run the same nightly Garmin sync Felix's instance runs,
**without losing the June–October history** the bridge banked.

Why now: Felix wants Garmin sync going. Garmin gives Max everything the bridge
never could: sleep, HRV, readiness, VO2max, laps, GPS, cadence, logged strength
sessions. His Wk 16 5K trial (2026-11-07) is the designed plan re-anchor point
and should be recorded on the new watch with the new pipeline in place.

## Decided by Felix

- **The Garmin replaces the Galaxy Watch.** There is no dual-watch period to
  support.
- **History stays inside SPLITS only, for now.** His Health Connect runs are not
  uploaded into his Garmin Connect account. Uploading them later stays an option
  (`garminconnect` has `upload_activity` / `delete_activity`). Nothing in this
  design should make that later step harder.
- **Credentials:** `MAX_GARMIN_EMAIL` / `MAX_GARMIN_PASSWORD` are in the NUC
  compose folder's `.env` (`~/dev/docker-compose-files/splits/.env`).

## Facts established 2026-10-21 (verified, not assumed)

- **Login works.** It ran inside the `splits-max` container with the `.env`
  values. Garmin answered `429 — IP rate limited` to the first two login
  strategies (`mobile+cffi`, `mobile+requests`), then a third succeeded. No MFA.
  Account name "Maximilian". Session tokens are already saved at
  `/data/.garmin_tokens/garmin_tokens.json` in Max's volume (dir 700 root), so
  the first sync needs no fresh login.
- **Garmin account:** device Forerunner 265S. Two runs so far:
  2026-10-19 19:09 (1.35 km, avg HR 116, 2 laps) and 2026-10-21 19:23
  (4.30 km, avg HR 167, 5 laps, VO2max 44). `get_max_metrics` today:
  `vo2MaxPreciseValue` 43.7.
- **His archive** (`/data/activity-archive.db`, schema 15): 51 activities,
  2026-06-10 → 2026-10-19, all running.
  - Every row has `summary_json.sessionUid` (ingest shape). No Garmin row has
    that key.
  - `detail_json` is NULL on all 51.
  - 50 have streams and distilled detail (`distilled_version` NULL; the ingest
    side versions through `archive_meta.ingest_distill_version` = 5).
  - 51 `run_metrics` rows at v3, 50 `run_intervals` rows at v6,
    109 `plan_compliance` rows at v4 over 14 weeks, 0 `daily_wellness` rows.
  - 45 `race_predictions` rows, all `source = 'riegel'` (SPLITS' own model,
    half ≈ 2:13:07), 2026-07-30 → 2026-10-21.
  - Sources: Samsung Health 44, Google Fit 5, Strava 1, **Garmin Connect app 1**.
- **The Garmin Connect app writes Max's runs into Health Connect, and the bridge
  banks them.** The 2026-10-19 Garmin run is already in his archive as an ingest
  row (`source = com.garmin.android.apps.connectmobile`). Raw bank:
  `/data/ingested-runs.json` (80 runs before dedupe), last written 2026-10-20.
- **Live compose on the NUC** (differs from the repo's example): `splits-max`
  has `SYNC_ON_BOOT: "off"`, `SYNC_AT: "off"`,
  `SPLITS_INGEST_TOKEN: ${SPLITS_INGEST_TOKEN_MAX}`, `ATHLETE_NAME: "Max"`,
  `ATHLETE_AGE: "23"`, `ATHLETE_MAX_HR: "199"`. It has two traefik routers:
  `splits-max` (behind `pocketid-auth-family@file`) and `splits-max-ingest`
  (SSO-free, priority 200, `Path(/api/ingest)`). It is on the `proxy` network.

## Goals

1. `splits-max` runs `sync_garmin.py` nightly and on demand from the dashboard's
   sync pill, like Felix's instance.
2. **One continuous history.** His pre-Garmin runs (the "shelf", defined below)
   keep appearing everywhere they appear today:
   - /archive, /run, /compare
   - compliance, the Block report, the coach briefing
   - the cockpit's history surfaces: weekly km + runs, heatmap, CTL/ATL,
     monthly pace, recent runs
3. **No run counted twice** at the seam: Garmin wins any overlap.
4. **The Garmin path tells the truth for an athlete who is not Felix:**
   - no Felix numbers as fallbacks
   - HR zone ranges that match the zones the minutes were counted in
   - his plan's goal, not 1:59:59
5. **Max's watch zones, Garmin's zones and SPLITS' zones agree** (heart-rate
   reserve, max HR 199). This ends the zone trap documented in July: the
   Samsung %max Z2 of 119–139 against SPLITS' Karvonen Z2 of 142–156. Note
   that SPLITS' *Garmin* path uses %max today (see D6), so SPLITS must change
   for Max too, not just his watch.
6. The bridge is retired. Its SSO-free route is gone from the public internet.

## Non-goals

- Uploading the shelf to Garmin Connect (Felix: maybe later).
- Merging shelf best efforts into the personal-bests card. The ingest path never
  had a PB card. On Garmin the card shows Garmin's records, which start
  2026-10-19.
- Making the insight reference bands per-athlete. `REF_HR_BAND` 125–145 and
  `REF_PACE_BAND` 7:00–8:00 are Felix's bands and are already wrong for Max on
  the ingest path. Pre-existing, and worth its own change. Note it in the
  hand-off.
- Pushing Max's plan workouts to his watch (`upload_running_workout` exists; a
  later idea).
- Changing the repo's generic `docker-compose.yml` ingest-fed example. It
  documents a supported mode. Only the NUC compose changes.
- Fixing the Wk 16→17 km seam in his plan. That is coaching work at the
  2026-11-07 re-anchor.

## Anti-goals (failure even if it "works")

- **Felix's instance changes in any way beyond the zone-range fix.** His sync is
  the production path. His `garmin-data.js` must stay key-for-key identical on
  the same inputs, except `hrZones[].lo/hi`.
- **A shelf run is lost, or counted twice.**
- **The nightly sync makes calls that can't return anything**: activity ids
  Garmin has never issued, or VO2max lookups for months before the account
  existed. These are wasted calls from an IP Garmin is already rate-limiting.
- **A number on Max's dashboard is secretly Felix's** (51.3 VO2max, 81 kg, RHR
  47, age 31, "Felix", 1:59:59).
- **A chart silently splices two models into one line**, e.g. SPLITS' Riegel
  estimate continuing as "Garmin's prediction".
- **`--verify-archive` on `splits-max` fails forever** because of rows it was
  never meant to heal.

## Design

### D1. The shelf

**Shelf** = archive rows of ingest origin, i.e. rows whose `summary_json`
carries `sessionUid`. That covers 51/51 rows today and never matches a Garmin
summary. After cutover nothing writes new shelf rows: the ingest route is off
and `ingest_builder.py` no longer runs on this instance. The shelf is frozen.

*My call:* identify the shelf with **one named predicate owned by
`activity_archive`** (an SQL fragment plus a Python twin), used by every query
that must include or exclude it. No schema bump: provenance is already in the
data. If the builder finds a reader where a JSON probe is too slow or awkward,
an explicit `origin` column (schema v16, backfilled from the same predicate)
is acceptable. That's the builder's call.

`/data/ingested-runs.json` and `ingested-rhr.json` stay on the volume untouched,
as the raw backup of what every Health Connect app wrote.

### D2. Garmin wins the seam

- A shelf row whose wall-clock span intersects any Garmin run's span is removed
  from the archive. Remove it the way `ingest_builder.dedupe_overlapping`
  removes losers today: the activity row and its derived rows (run_metrics,
  run_intervals and anything else keyed on the activity id), so /archive and
  the cockpit can't disagree.
- Shelf rows from `com.garmin.android.apps.connectmobile` are Garmin runs seen
  through Health Connect. They go even if the overlap test misses them: belt
  and braces.
- This runs every sync (cheap, idempotent). A late-arriving Garmin upload of an
  old run still wins.
- Expected today: the 2026-10-19 shelf row goes, and the Garmin 2026-10-19
  activity replaces it.

### D3. Garmin passes leave the shelf alone

Audit every nightly and backfill pass in `sync_garmin.py` against a mixed
archive.

- **Known offender:** `_archive_detail_topup` → `missing_detail_ids` selects
  `detail_json IS NULL`, which matches every shelf row. That would ask Garmin
  for 25 non-existent activity ids every night, forever. Exclude the shelf.
- **Naturally excluded today** (they require `detail_json` or a Garmin summary
  key): streams, distill, laps, maps, workouts, metrics. Pin each exclusion with
  a test so a later refactor can't reintroduce the shelf.
- **Intervals runs on stored streams** and already scores the shelf (50 rows at
  v6). That is desired: the lens is source-agnostic. Keep it. The shelf stays
  in the work-floor pool, so shelf documents are rescored whenever the floor
  drifts past the gate or `INTERVAL_VERSION` bumps. That rescoring uses the
  athlete's zone model from D6.
  - **Parity requirement (fix-distill-parity M8):** the cockpit's compact
    summary must agree with /run/:id. `_distill_pass` needs `detail_json` and
    so never refreshes a shelf row's `detail_distilled_json`. Whenever a shelf
    run's interval document is rescored, its stored distilled summary
    (`intervals` part, and any zone-derived fields) must be refreshed from the
    same reading. Builder's call on the mechanism.
- `fetch_hr_zones_this_week` and anything else that calls Garmin per activity
  id must never do so for a shelf id.

### D4. The cockpit sees the shelf

`build_data` aggregates from `acts`, Garmin's activity list. Build an
activity-list-shaped projection of the shelf rows, read from the archive (which
is deduped and consistent with /archive). Feed `acts + shelf` to the history
aggregates:

- `fetch_heatmap`, `fetch_weekly`, `compute_fitness_fatigue`
- `fetch_monthly` (rules below)
- `fetch_recent_runs`

**Monthly series for a young account** (*my call*, settled from the
"no invented numbers" and "no wasted calls" anti-goals):

- Today `fetch_monthly` builds a fixed 30-month window and `ffill` back-fills
  the leading gap from the first real value. For Max that would paint June
  2026's pace back to 2024-05, a flat 43.7 VO2max across 30 months, and
  October's Garmin cadence over months that never had cadence. It would also
  call `get_max_metrics` for ~29 empty months every night.
- New rule: the series starts at the **first month with any run** (shelf or
  Garmin). No back-fill before the first real value. Interior gaps keep the
  current forward-fill, so Felix's output is unchanged: his history fills the
  whole window.
- Cadence and VO2max are `null` for months with no such data, as the ingest
  path already showed for Max (the cockpit renders that today). `validate()`
  accepts this shape. The builder confirms every cockpit/progress reader
  tolerates it.
- `get_max_metrics` month-end lookups only run for months on or after the
  Garmin account's first activity.
- Pace aggregation stays Garmin's (mean of per-run pace), so Felix doesn't
  move. Shelf runs contribute their moving-time pace (below). Max's June–Sept
  pace points will shift slightly from the ingest path's
  total-time ÷ total-distance. Accepted: it's one definition across the
  whole line instead of two.

For shelf rows, `fetch_recent_runs` takes `detail` from the stored
`detail_distilled_json` with **no Garmin call**. Recent runs on day one are
today's Garmin run plus the five newest shelf runs.

- Pace for shelf rows: match what the ingest path showed (moving-time pace via
  `_effort`), or the cockpit's numbers jump at cutover. Builder's call on how to
  share that logic.
- The shelf projection must **never** reach `archive_step` /
  `upsert_activities`. An upsert would overwrite the shelf rows' ingest-shaped
  `summary_json`, and the ingest-side readers depend on it.
- On Felix's instance the shelf is empty, so the projection is empty and
  `build_data` behaves exactly as today. Test this explicitly.

### D5. Felix-shaped defaults on the Garmin path

Found so far in `sync_garmin.py`. **The builder should grep for more.** This
path has only ever run against one account, and the honest-compliance lesson is
that such bugs are invisible on that account.

- `fetch_predictions(..., planned_goal="1:59:59")`: `halfGoal` must come from
  the plan's `race.goalTime`, as `ingest_builder._plan_goal` does (Max:
  2:29:59). The trajectory already reads the plan's goal (coach-loop D5).
- `fetch_profile` fallbacks: `"Felix"`, age `31`, RHR `47`, weight `81.0`,
  VO2max `51.3`.
  - Name, age and max HR are env-set for Max, so they're safe today.
  - The rest must become an honest absence the cockpit already tolerates.
    The ingest path omits `profile.vo2maxCurrent` / `restingHR` when unknown,
    and the cockpit was hardened for that in July.
- `validate()` asserts `profile.vo2maxCurrent == history.vo2max[-1]`. On a
  Garmin account with no VO2max yet, that fails and **no `garmin-data.js` is
  written**. Max already has 43.7, so this doesn't bite him now. Fix it anyway:
  with no VO2max, omit it (as ingest does) and validate accordingly.
- `ATHLETE_MAX_HR` default `197` and `ATHLETE_AGE` default `31` remain as env
  fallbacks. Acceptable, since every instance sets them. Leave them unless a
  test shows harm.

### D6. Zones: one model per athlete, and edges that match the minutes

**Two zone systems live in SPLITS today.** `interval_lens.zone_bounds(max_hr,
rhr=None)` is the single formula. Its docstring says the model differs by
producer on purpose: the Garmin path calls it with max HR only (**%max**), and
the Health Connect path passes resting HR (**Karvonen / HR reserve**). For Max
on the Garmin path that silently moves SPLITS' own Z2 from 142–156 to 119–139,
the July trap again. The bounds drive interval documents' `quality.zone`
(/run/:id, `recentRuns[].detail.intervals`) and compliance's "Z2 confirmed /
zone read Z3" verdicts.

*My call:* **a per-athlete zone model, default unchanged.**

- New env setting on the Garmin path: **`ATHLETE_RESTING_HR`** (bpm). When it's
  set, `sync_garmin.py` passes it into `zone_bounds` everywhere it calls it, so
  the zones are Karvonen. When it's unset, they're %max, today's behaviour. The
  calls today are line ~485 in `distill_run_detail` and line ~1253 in
  `derive_intervals`; the builder finds any others. This is the formula's own
  rule ("rhr known → Karvonen"), so there's no separate mode switch.
- *Refined while planning:* a **pinned** value, not a nightly median. The
  watch's custom zones (D10) are fixed bpm edges. A resting HR that moved every
  night would drift SPLITS away from the watch and churn every interval
  document. The value is read off Garmin at cutover (its 7-day resting-HR
  average). It is changed deliberately, like `ATHLETE_MAX_HR`, together with
  the watch's zones.
- When the zone edges change (first sync, or an edited env value), every stored
  interval document is rescored and every stored distilled summary
  re-derived, so no run keeps a verdict from the old zones.
- `splits-max` sets `ATHLETE_RESTING_HR`. Felix sets nothing, so his interval
  documents, compliance verdicts and `garmin-data.js` don't move.

**The zone card's edges.** `fetch_hr_zones_this_week` counts minutes in
**Garmin's** zones (`hrTimeInZone_N` / `get_activity_hr_in_timezones`), but
labels them with **%max** edges. When the watch's zones aren't %max, the card
shows minutes from one zone system under the ranges of another.

Fix: take the edges from the same source as the minutes. Rows from
`get_activity_hr_in_timezones` carry `zoneLowBoundary`. Use the newest activity
of the week. Fall back to the athlete's `zone_bounds` edges only when Garmin
returns none.

**This changes Felix's cockpit too:** his zone card will show his watch's real
edges. That's the one allowed difference in his output (anti-goal 1). Call it
out in the hand-off so he can confirm the edges match his watch.

**Making the three systems agree for Max.** Garmin's built-in %HRR zone
percentages are not guaranteed to equal SPLITS' `ZONE_FRACTIONS`. So the D10
checklist gives Max the **exact bpm edges** to enter as custom zones on the
watch, computed from `zone_bounds(199, his Garmin RHR)`. Watch, Garmin and
SPLITS then read the same numbers.

### D7. Prediction sources don't splice

Max's `race_predictions` holds 45 rows of `source='riegel'`. From cutover,
`metrics_step` banks Garmin's predictor daily as `source='sync'` (keyed by date,
so it supersedes same-date riegel rows). Readers that draw a prediction series
must not join the two into one line:

- `insight_metrics.weekly_trajectory`'s `garminSec`
- `coach_briefing`
- `block_lens`
- anything else the builder finds

*My call:* readers of a "Garmin prediction" exclude `source='riegel'` rows.
Riegel rows stay in the table as history. **Not** a `source='sync'` filter:
Felix's archive holds 784 `source='backfill'` rows (2024-05-12 → 2026-07-04)
alongside his `sync` rows, and a sync-only filter would cut his trajectory
history. Felix has no riegel rows, so nothing changes for him.

Known, accepted effect: the cockpit's "half now" switches from SPLITS' Riegel
estimate (≈ 2:13) to Garmin's predictor at cutover. That one is honest (it says
whose number it is). Garmin's predictor runs optimistic for a new user, so
mention it to Max.

`metrics_step` auto-backfills Garmin's predictor history only when the table is
empty. Max's isn't, so there's no backfill. Garmin has no history before
2026-10-19 anyway.

### D7b. The Block report's goal gap restarts at the switch (Felix decided)

The problem: `block_lens._goal_gap` anchors the goal gap on a prediction row
within `GOAL_ANCHOR_TOLERANCE_DAYS` (14) of the block start. Max's block
started 2026-07-20; today it anchors on the 2026-07-30 Riegel row. Only
`ingest_builder` banks Riegel rows, so after cutover none are added. With D7's
reader, the Block report would read `no-baseline-prediction` for the whole
block.

**Felix's decision:** restart the comparison from the switch, using Garmin's
race predictor.

- When a block has no non-riegel prediction near its start, but non-riegel
  rows begin mid-block, the goal gap anchors on the **first non-riegel
  prediction on or after that point** (for Max: 2026-10-21, or whichever date
  Garmin's first predictor row lands). It compares against the newest
  non-riegel row.
- Riegel rows are never mixed into either end of the comparison.
- The gap carries its baseline date, and every reader says so in words. The
  Block card and the coach briefing read e.g. "since 2026-10-21 (Garmin
  predictor)", never "since block start".
- *My call:* derive this from the data, like `tracked_kinds`, rather than
  configure it. The condition is "this block's predictions changed source
  mid-block". Felix's blocks always have a non-riegel anchor near the start,
  so his goal gap doesn't move. Bump `BLOCK_LENS_VERSION` if the stored row
  shape changes, so the rows self-heal.
- Expect Garmin's predictor to be optimistic and jumpy for a new user in the
  first weeks. The gap is honest about whose number it is. It isn't a coaching
  signal until it has a few weeks of data.

### D8. The verify gate on a mixed archive

`--verify-archive` must pass on `splits-max` after cutover and keep passing.

- Today's distilled, streams and metrics coverage count "detailed runs"
  (`detail_json NOT NULL`), so shelf rows are invisible to those counts. Good.
- **Future METRICS_VERSION bump:** shelf `run_metrics` rows go stale and the
  Garmin path cannot recompute them (no Garmin detail). That would fail the
  gate forever. Pick one:
  - (a) Recompute shelf metrics from their stored streams, as the ingest side
    did via `_metric_samples`.
  - (b) Exclude the shelf from the stale check, which leaves stale shelf metrics
    out of the insights.

  *My preference is (a)* (the history keeps counting), but it's the builder's
  call by cost. Either way, test it with a version bump.
- Wellness: `--backfill-wellness` should start at the Garmin account's first
  day (`--since 2026-10-19`). The wellness gap check must not then demand June
  through October dates the shelf can't have. Verify how `wellness_coverage`
  picks its window.

### D9. Cutover runbook (NUC)

Order matters only in one place: turn the ingest route off **before or at** the
flip, so the bridge can't bank more Garmin-sourced runs after Garmin sync takes
over. (D2 would catch them anyway; this keeps the shelf truly frozen.)

1. Ship the code: merge, CI builds `:latest`, then `docker compose pull`. Both
   containers get the image. Verify Felix's instance after its next sync, or by
   `docker compose exec splits python3 sync_garmin.py --verify-archive` plus a
   look at his cockpit.
2. Back up Max's state:
   - a consistent `sqlite3.backup` snapshot of
     `/data/activity-archive.db`
   - copies of `ingested-runs.json`, `garmin-data.js`, `coach-briefing.md`
   - `docker-compose.yml.bak-2026-10-21`

   Keep them on the volume.
3. Edit `splits-max` in the NUC compose:
   - `GARMIN_EMAIL: ${MAX_GARMIN_EMAIL}`, `GARMIN_PASSWORD: ${MAX_GARMIN_PASSWORD}`
   - `SYNC_AT: "08:15"`. *My call:* stagger after Felix's 08:00, because both
     accounts hit Garmin from one IP that's already being rate-limited.
   - `SYNC_ON_BOOT` back to default (on)
   - `ATHLETE_RESTING_HR: "<bpm>"` (D6), read off Garmin's 7-day resting-HR
     average at cutover
   - remove `SPLITS_INGEST_TOKEN`, which makes `/api/ingest` 404 and
     `ingestFed: false`, so the sync pill appears
   - remove the `splits-max-ingest` router labels
   - update the comments that say "fed by POST /api/ingest only"
4. `docker compose up -d splits-max`. The boot sync runs. Then, once:
   `docker compose exec splits-max python3 sync_garmin.py --backfill` and
   `--backfill-wellness --since 2026-10-19`.
5. Verify (the evidence to collect):
   - `/api/status` shows `ingestFed: false`, `archive: true`
   - `--verify-archive` exit 0
   - his cockpit's weekly-km chart shows June–October plus this week
   - recent runs show today's 4.30 km Garmin run and shelf runs
   - 2026-10-19 appears once
   - HR zone edges are HRR-based (once Max has set his zones, below)
   - `halfGoal` 2:29:59
   - no 51.3 / 81 / 47 anywhere
   - compliance still at 14+ weeks
   - `/archive` lists 50 shelf + Garmin runs
   - a tokenless `curl -X POST https://splits-max.mochii.dev/api/ingest` no
     longer reaches the app

   Read the page text with `browser_evaluate` on `document.body.innerText`,
   not a navigation-time snapshot (that one shows demo data).
6. Felix's instance: confirm nothing moved but the zone edges.

### D10. Max's side (a short checklist for Felix to send)

Plain language, like `ONBOARDING-PIXEL.md`. *My call on location:*
`docs/onboarding/max-garmin.md`. Contents:

- **Garmin Connect app → user profile:**
  - birth date (age 23)
  - **max HR 199**
  - resting HR on auto
  - HR zones calculated by **% Heart Rate Reserve**, then the **exact bpm
    edges** from D6 entered as custom zones
  That makes the watch's Z2 read the same numbers as SPLITS' (≈142–156,
  recomputed with his Garmin resting HR) instead of Samsung's 119–139.
- Uninstall **SPLITS Bridge**. Leaving Garmin Connect's Health Connect sharing on
  is harmless once the bridge is gone.
- Wear the watch overnight. HRV status needs about 3 weeks to build a baseline,
  so readiness and HRV cards stay thin until then.
- **Record strength and mobility sessions on the watch** (Strength activity).
  That makes those plan days scoreable for the first time: the compliance
  engine's `tracked_kinds` self-heals once two are recorded in 90 days. Until
  then they read "untracked", not "missed".
- Garmin's own race predictor is optimistic for new users. SPLITS shows it, but
  the plan is anchored on the Wk 16 5K (2026-11-07).

## Testing

TDD, repo venv (`./.venv/Scripts/python.exe`).

- **Mixed-archive fixture:** shelf rows copied in shape from a real ingest row
  (`sessionUid`, NULL `detail_json`, streams + distilled), plus Garmin rows,
  including one overlapping pair and one `connectmobile` shelf row.
- **Per-pass exclusion tests** (D3), the seam rule (D2), and the shelf
  projection into each aggregate (D4), including the young-account monthly
  series.
- **Zone model and edges** (D6): %max parity when `ATHLETE_RESTING_HR` is
  unset, Karvonen when it's set.
- **Prediction-source filtering** (D7) and the restarted goal gap (D7b).
- **Verify on a mixed archive** (D8), including a METRICS_VERSION bump and
  shelf parity after an interval rescore (D3).
- **Felix parity:** run `build_data` on a Felix-shaped fixture (no shelf) before
  and after. Key-for-key identical except `hrZones[].lo/hi`. This mirrors how
  the ingest-coach-loop extraction proved parity.
- **Oracle check:** `activity-archive-max.db` at the repo root is stale
  (2026-08-05, 12 rows). Refresh it with the consistent-snapshot recipe
  (`honest-compliance` oracle docstring) before relying on it.
- Existing suites stay green: `test_ingest_*`, `test_slim_render.mjs` (asserts
  `ingestFed` shapes), sync/archive/metrics tests.

## Left to the builder

- Predicate vs `origin` column (D1); where the seam rule lives (archive helper
  vs sync step) (D2).
- How to share moving-time pace between the ingest builder and the shelf
  projection (D4).
- (a) vs (b) for the METRICS_VERSION seam (D8).
- The full list of Felix-shaped constants (D5) and prediction readers (D7).
- Commit granularity and whether this runs as an OpenSpec change or (like
  honest-compliance) as a superpowers spec → plan.

## Known effects to tell Felix and Max

- **"Half now"** changes source at cutover (Riegel ≈ 2:13 → Garmin predictor).
- **Max's Block goal gap** restarts at the switch and says so (D7b).
- **Personal bests** show Garmin records only, starting 2026-10-19.
- **Felix's zone card** shows his watch's real zone edges.
- **New cards on Max's cockpit:** readiness, sleep and VO2max appear, sparse at
  first. The ingest-only energy tile and resting-HR card disappear (the Garmin
  path doesn't emit those keys).
