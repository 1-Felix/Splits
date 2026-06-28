# Per-Run Drill-Down with Plan-Aware Coach-Read — Design

**Date:** 2026-06-28
**Status:** Approved (design), pending implementation plan
**Branch:** `feat/splits-dashboard`

## Context & goal

The SPLITS dashboard currently shows a **Recent Activities** table that lists the
last 6 runs as a single summary line each (date, type, km, time, pace, HR, cad).
The goal is to make each run **drillable**: click a row and it expands in place
into a detail strip — per-km splits, an HR-drift sparkline, HR-zone breakdown,
Training Effect / temperature — topped by a one-line **coach-read** that
interprets the run the way a coach would (e.g. *"Easy on paper — 30 °C pushed HR
to threshold; bank recovery."*).

This is the first of several possible interactivity upgrades; it was chosen as
the highest insight-per-pixel option.

### Chosen approach (of three considered)

**Split the work.** The sync (Python) crunches and stores each run's *objective*
detail into `garmin-data.js`; the dashboard composes the *coach-read sentence*
from those numbers **plus the plan** (matched by date), so it can reference what
was intended that day. Rejected alternatives: "all in the sync" (can't see
`plan-data.js`, so no plan-awareness) and "all in the page" (heavy logic in the
generated `dc.html`, recomputed every render).

This deliberately diverges the generated `dc.html` further from its Claude Design
source — explicitly fine; the design source was a stepping stone and the
`dc.html` is now the source of truth.

## Non-goals / scope

- **Runs only.** The Recent Activities table contains runs; strength/cycling are
  not in it and get no drill-down.
- **6 runs** (current `RECENT_RUNS`). Bumping to 8 is a one-line change, out of
  scope here.
- **No live API in the page.** Detail is pre-computed at sync time and rendered
  from stored data, consistent with the rest of the project.
- Not adding hover tooltips, chart range toggles, or plan-vs-actual overlays —
  those are separate future upgrades.

## 1 · Data layer — `sync_garmin.py` → `garmin-data.js`

New fetcher `fetch_run_detail(client, activity) -> dict`, called for each run in
`fetch_recent_runs`. It attaches a `detail` object to each `recentRuns[i]`:

```js
recentRuns[i].detail = {
  splits:   [ { km: 1, pace: 384, hr: 151 }, ... ],  // pace = sec/km, one per full km
  hrSeries: [151, 153, 156, ...],                    // ~30-pt downsampled HR, for the sparkline
  driftBpm: 16,                                       // 2nd-half avg HR − 1st-half avg HR
  zoneMin:  [0, 6, 32, 55, 5],                        // minutes in Z1..Z5
  tempC:    28,                                        // from activity min/maxTemperature (°C)
  te:       5.0,                                       // aerobicTrainingEffect
  load:     299,                                       // activityTrainingLoad
  elevGain: 105,                                        // metres
  splitShape: "positive"                               // "even" | "positive" | "negative"
}
```

**Computation:**
- Pull `client.get_activity_details(activityId, maxchart=2000)`; read the
  `metricDescriptors` → indices for `sumDistance`, `directHeartRate`,
  `directSpeed`, `directElevation`.
- `splits`: bin samples by `int(distance // 1000)` → average pace + HR per km.
- `driftBpm`: split the HR samples in half, `round(avg(2nd) − avg(1st))`.
- `hrSeries`: evenly downsample the HR samples to ~30 points.
- `zoneMin`: from the activity summary's `hrTimeInZone_1..5` seconds → minutes.
- `tempC`: from the activity's `maxTemperature`/`minTemperature` (already °C);
  use a representative value (e.g. round of the average). No weather call needed
  — the activity carries temperature, avoiding the °F conversion the weather
  endpoint returns.
- `te`, `load`, `elevGain`: straight from the activity summary fields
  (`aerobicTrainingEffect`, `activityTrainingLoad`, `elevationGain`).
- `splitShape`: compare first-third vs last-third average pace;
  `> +4 %` slower → `"positive"`, `< −4 %` → `"negative"`, else `"even"`.

**Caching & cost:** each activity's computed detail is cached to
`.garmin_cache/detail-{activityId}.json`. A nightly sync therefore fetches detail
only for genuinely new runs (≈1 `get_activity_details` call per new run). All
fetches go through the existing `safe()` wrapper; a failed detail fetch yields
`detail: null` and never sinks the sync.

## 2 · Coach-read engine — dashboard (`renderVals`), plan-aware

A pure method on the component, `coachRead(run)`, returns one sentence from
`run.detail` + the plan. Lives in the dashboard because it needs the **merged**
data (telemetry + `weekPlan`).

**Intent resolution:** find a `weekPlan` entry whose `date` equals `run.date` and
`kind === "run"`. If found, intent comes from that entry (`title`, `load`);
otherwise fall back to `run.type` (`Long Run`/`Tempo Run`/`Recovery`/`Run`).
Define `intentEasy` = matched load in {Easy, Moderate} or type in
{Recovery, Long Run, Run}; `intentHard` = load Hard or type Tempo Run.

**Ordered rules (first match wins),** using `hrPct = run.hr / profile.maxHR`:

1. `intentEasy && hrPct ≥ 0.83 && tempC ≥ 25 && driftBpm ≥ 10` →
   *"Easy on paper — {tempC} °C pushed HR to threshold ({hr} avg, +{driftBpm} drift). Bank recovery."*
2. `driftBpm ≥ 12` →
   *"Big cardiac drift (+{driftBpm}) — heat, dehydration, or too hot a start."*
3. `splitShape === "negative"` →
   *"Negative split — controlled, finished stronger than you started."*
4. `intentEasy && splitShape === "positive"` →
   *"Faded in the back half — ease the opening pace on easy days."*
5. `intentHard && (zoneMin[3]+zoneMin[4]) ≥ 0.4 × totalMin` →
   *"Quality threshold work — {zoneMin[3]} min in Z4."*
6. `intentEasy && hrPct ≤ 0.75` →
   *"Properly easy — exactly the aerobic stimulus intended."*
7. fallback →
   *"{km} km at {pace}/km, avg HR {hr}."*

Plan-matching is exact for the current week's runs; older runs use type-based
intent (acceptable — the most recent runs are the interesting ones).

## 3 · Dashboard UI — inline expand

**State & handler** (mirrors the existing theme switch):
- add `expandedRun: null` to the component `state`
- `toggleRun = (id) => this.setState({ expandedRun: this.state.expandedRun === id ? null : id })`
  (one row open at a time; click again to collapse).

**View-model:** in `renderVals`, each entry of the `runs` array gains
`id`, `expanded` (bool), `toggle` (fn), and — when `run.detail` exists — a
`detailView` with: a splits bar-sparkline (SVG path), an HR-drift sparkline (SVG
path over `hrSeries`) with `{hrStart} → {hrEnd} (+{driftBpm} bpm)` (where
`hrStart`/`hrEnd` are the first/last points of `hrSeries`), zone mini-bars
(Z1–Z5 using `var(--z1..z5)`), `TE {te} · {tempC} °C`, and `coachRead(run)`.

**Template:** Recent Activities rows become clickable
(`onClick="{{ r.toggle }}"`) with a chevron that reflects `r.expanded`. When
expanded, a full-width detail row renders beneath, styled to match the dashboard
(JetBrains Mono numerals, accent for the ⚡ read line, existing zone colors).

## 4 · Edge cases

- **No / failed detail** (`detail: null`): row stays clickable but the strip
  shows only the summary line + "detail unavailable"; never crashes.
- **Demo / offline mode** (built-in `buildData()` runs, no `detail`): expansion
  is disabled (chevron hidden) so the demo still renders cleanly.
- **Runs without HR** (older activities): `hrSeries`/`zoneMin` empty → sparklines
  hidden, `coachRead` falls back to rule 7.
- **Data size:** ~6 runs × (≤21 split entries + ~30 HR points) ≈ a few KB added to
  the gitignored `garmin-data.js`. Negligible.

## 5 · Testing & verification

- Extend `validate_data.py`: when `recentRuns[i].detail` is present, assert
  `splits` non-empty with integer `pace`, `zoneMin` length 5, `driftBpm` numeric.
- Offline transform test: feed a synthetic `get_activity_details` payload to
  `fetch_run_detail` and assert the `detail` shape (extends the existing
  `offline_test.py` pattern; no Garmin network).
- Render verification: Playwright — load the dashboard, click a run, screenshot,
  confirm the inline detail strip + coach-read render and a second click
  collapses it.

## 6 · File changes

| File | Change |
|------|--------|
| `sync_garmin.py` | `fetch_run_detail()` + per-activity detail cache; attach `detail` in `fetch_recent_runs`. |
| `garmin-data.js` | (regenerated) `recentRuns[i].detail` added. Gitignored. |
| `Running Dashboard.dc.html` | `expandedRun` state + `toggleRun`; `coachRead()`; clickable rows + inline detail template. |
| `validate_data.py` | optional `detail`-shape assertions. |
| `offline_test.py` (or new) | `fetch_run_detail` shape test. |
| `README.md` | one line noting the drill-down. |

## Open decisions

None outstanding. Defaults chosen: 6 runs, runs-only, temperature from the
activity (not the weather endpoint), coach-read in the dashboard for
plan-awareness.
