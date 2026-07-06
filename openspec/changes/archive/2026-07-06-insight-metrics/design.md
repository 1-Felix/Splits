# Design: insight-metrics

## Context

Stage 1 (`activity-archive`) shipped: `<DATA_DIR>/activity-archive.db` holds
every activity since 2024-05-12 with raw summary + raw detail JSON. Probing the
real archive (2026-07-05, 162 runs) established the ground truth this design
builds on:

- **Detail streams are complete and rich**: all 162 runs have
  `activityDetailMetrics` at 1–4 s sampling with `directSpeed`, `sumDistance`,
  `directHeartRate`, `directRunCadence`, `directGradeAdjustedSpeed` (missing on
  only 4 runs), elevation and GMT timestamps. One treadmill run has low sample
  density (75 points / 53 min) but is still usable for pooled series.
- **Garmin pre-computes in-run fastest splits**: `fastestSplit_1000/1609/5000/
  10000` in `summary_json` (coverage 145/143/115/38 of 162). No half distance,
  gaps in coverage, unknown method — not sufficient as the source, but a free
  cross-validation oracle for our own extraction.
- **Strict Z2 runs barely exist historically**: 0 qualifying runs in most
  months of 2024–mid-2025 (avg-HR-in-Z2 filter). A run-level "steady/Z2"
  efficiency metric would produce a mostly-empty chart — the roadmap's original
  phrasing does not survive contact with the data.
- **Garmin's race predictor has a history endpoint**:
  `get_race_predictions(startdate, enddate, _type='daily'|'monthly')`, max one
  year per call — the predictor trajectory is backfillable to 2024, not just
  bankable from now.

Decisions locked with Felix (2026-07-05 explore session): stage 2 includes
visible UI; best efforts use **elapsed** time; treadmill runs count in trends
but not records; Riegel anchors on the best 10k effort in a rolling ~12-week
window (Sunday runs are reliably >10 km).

## Goals / Non-Goals

**Goals:**
- Deterministic, versioned metrics computed from the archive inside the nightly
  sync — no AI, no manual steps, recomputable from raw data at any time.
- The three progress definitions made visible: pace at a reference HR,
  cadence at a reference pace, records falling at km milestones.
- An honest race trajectory: Riegel-from-demonstrated-efforts vs Garmin's
  predictor vs the sub-2:00 goal, weekly, backfilled to 2024.
- Insights surfaced in `garmin-data.js` (additive block) and rendered on the
  existing dashboard page; everything degrades gracefully when absent.
- Telemetry invariant preserved: existing `garmin-data.js` keys are written
  even if every new step fails.

**Non-Goals:**
- No multi-page progress views, records wall, or archive browser — stage 3.
- No plan-vs-actual compliance, no coach briefing — stage 4.
- No new Python dependencies (stdlib `sqlite3` + `math` suffice) and no new
  Garmin auth scopes.
- No modification of stage 1's raw tables — schema v2 is strictly additive.
- No GPS/route-based metrics (elevation profiles, segments).

## Decisions

### D1 — Two-phase engine in its own module
`insight_metrics.py`, stdlib-only, imported by `sync_garmin.py` (mirrors
`activity_archive.py`):

1. **Per-run extraction** (expensive, once per activity): parse `detail_json`
   streams → best efforts + reference-band aggregates → one `run_metrics` row.
   Runs only for activities with detail and no row at the current
   `METRICS_VERSION`; a version bump therefore self-heals by recomputing all
   rows over subsequent syncs (162 runs ≈ seconds — done in one pass, no cap).
2. **Series assembly** (cheap, every sync): SQL over `run_metrics` +
   `race_predictions` → the `insights` block. Pure aggregation; no stream
   parsing.

### D2 — `run_metrics`: derived, versioned, disposable (schema v2)
Additive migration guarded by `archive_meta.schema_version = 2`:

```sql
CREATE TABLE run_metrics (
  activity_id     INTEGER PRIMARY KEY REFERENCES activities(activity_id),
  metrics_version INTEGER NOT NULL,
  start_time_local TEXT NOT NULL,       -- denormalized for series SQL
  is_treadmill    INTEGER NOT NULL,     -- type_key = 'treadmill_running'
  -- best efforts, elapsed seconds; NULL when run shorter than the distance
  best_1k_s REAL, best_mile_s REAL, best_5k_s REAL,
  best_10k_s REAL, best_half_s REAL,
  -- reference-band aggregates (time-weighted sums → monthly series by SUM)
  refhr_time_s REAL, refhr_dist_m REAL,          -- pace @ reference HR
  refpace_time_s REAL, refpace_cadence_x_time REAL,  -- cadence @ reference pace
  computed_at TEXT NOT NULL
);
CREATE INDEX idx_run_metrics_start ON run_metrics(start_time_local);

CREATE TABLE race_predictions (
  date TEXT PRIMARY KEY,                -- local ISO date
  time_5k_s REAL, time_10k_s REAL, half_s REAL, marathon_s REAL,
  raw_json TEXT NOT NULL,
  source TEXT NOT NULL,                 -- 'backfill' | 'sync'
  updated_at TEXT NOT NULL
);
```

Unlike the raw tables, `run_metrics` rows are freely deletable/replaceable —
they are a cache of deterministic computation, owned by this capability. The
band definitions and algorithm parameters are constants in
`insight_metrics.py`; changing any of them bumps `METRICS_VERSION`.

### D3 — Best efforts: two-pointer sliding window on elapsed time
Build a monotonic series of `(elapsed_s, cumulative_m)` points per run from
`directTimestamp` (GMT ms; fallback `sumElapsedDuration`) and `sumDistance`
(clamped non-decreasing, `None` samples dropped). For each target distance
(1000, 1609.344, 5000, 10000, 21097.5 m) a two-pointer pass finds the minimum
elapsed time over any window covering the distance, linearly interpolating the
window edges at the exact target.

- **Elapsed, not moving time**: a "fastest 5k" containing a pause is honestly
  slower — race-comparable numbers are the point (decision locked with Felix).
- Sampling at 1–4 s (Garmin caps chart data at 2000 points) makes interpolation
  error ≪ 1 %; acceptable.
- **Test oracle**: on archived runs where Garmin's `fastestSplit_*` exists, our
  value must be within tolerance (~3 %, ours may read slightly slower since
  Garmin computes on-device from 1 s recording). This pins the algorithm to
  reality with zero hand-built fixtures.

### D4 — Progress series from pooled stream samples, not run classification
The roadmap's "EF on steady/Z2 runs" is replaced (with Felix's sign-off) by
sample-level pooling, robust to how the athlete actually trained:

- **Pace @ reference HR**: per run, sum time and grade-adjusted distance
  (`directGradeAdjustedSpeed`; fallback `directSpeed` when absent) over samples
  with HR inside the reference band, after a warm-up cutoff (first 8 min
  excluded — HR lag) and above a walking floor (speed ≥ 1.4 m/s). Monthly
  point = `SUM(refhr_dist_m) / SUM(refhr_time_s)` across runs, rendered as
  sec/km; months with < 10 min of in-band time yield `null` (no point) rather
  than a noisy one.
- **Cadence @ reference pace**: same pattern over samples with pace inside the
  reference band; monthly cadence = `SUM(cadence_x_time) / SUM(time)`.
- Bands validated against the real archive during implementation (density
  check, task 3.1) and frozen as `METRICS_VERSION` 1 constants: **HR 125–145
  bpm** (dense in every month since structured training began 2025-07; earlier
  months were sporadic hard running and honestly null) and **pace 7:00–8:00
  min/km** (the design's 5:30–6:00 default was near race pace and gap-heavy in
  13/21 trained months; 7:00–8:00 is the bread-and-butter easy pace and leaves
  only genuinely untrained months below threshold).
- Treadmill runs contribute to both pools (decision: trends include them).

### D5 — Records: outdoor-only, computed as a progression
A record event = a run whose best effort at a distance beats every *earlier*
run's best (SQL window over `run_metrics` ordered by `start_time_local`,
`is_treadmill = 0`). The `insights` block carries:

- `bestEfforts`: all-time best per distance (time + date) and best-in-last-90d
  — the honest "records wall" seed for stage 3. Treadmill excluded here too:
  these are records; trends are where treadmill counts.
- `recordsFeed`: the most recent ~10 record events (`date`, `distance`,
  `oldSec → newSec`), newest first — the "records fell this month" feed.

### D6 — Trajectory: weekly Riegel vs banked Garmin predictor
For every ISO week from the first qualifying effort to now:

- **Riegel line**: best 10k effort (outdoor) in the trailing 84 days ending
  that week → `half = t10k × (21.0975/10)^1.06`. No 10k in the window ⇒ `null`
  for that week — a gap is more honest than a flattering 1k-based estimate.
- **Garmin line**: last banked `race_predictions.half_s` on or before the
  week's end.
- `predictions.trend` (the existing empty placeholder in `garmin-data.js`)
  gets a compact verdict derived from the last ~4 weeks of the Riegel line:
  `"closing"` / `"opening"` / `"flat"` plus the rate, e.g. `"closing ≈8s/wk"`.

### D7 — Predictor history: auto-backfill once, bank every sync
On each sync the metrics step upserts today's row from the predictor document
the sync already fetches (`fetch_predictions` — zero extra calls). When
`race_predictions` is empty (first run after deploy), the step backfills
daily history back to the account start (3 calls of ≤ 1 year each) inside the
same fail-soft wrapper — idempotent, no manual ritual. If the unofficial
history endpoint ever disappears, the bank-on-sync path alone still builds the
line forward from that day.

### D8 — Sync order inverts: archive → metrics → build → write *(amends stage 1 D6)*
Stage 1 deliberately ran the archive step *after* `garmin-data.js` was written.
Insights live *in* `garmin-data.js` and must include today's run, so the order
becomes:

```
fetch acts → archive step (upsert + detail top-up) → metrics step (D1 phase 1)
          → build_data (incl. insights assembly, D1 phase 2) → write garmin-data.js
```

The invariant that mattered is preserved, restated: **every step between fetch
and write is `safe()`-wrapped, and telemetry keys are written even if archive,
metrics, and insights all fail** — a failed assembly omits the `insights`
block entirely rather than emitting a partial one. Steady-state cost of the
moved archive step is 0–3 detail calls (backlog already drained), so telemetry
freshness is not meaningfully delayed.

### D9 — The `insights` contract in `garmin-data.js` (additive)
One new top-level block; every existing key untouched:

```js
insights: {
  metricsVersion: 1,
  efficiency: { refHrBand: [125, 145],
                monthly: [{ month: "2025-07", paceSecPerKm: 391, inBandMin: 312 }, …] },
  cadence:    { refPaceBand: [420, 480],       // sec/km
                monthly: [{ month: "2025-07", spm: 162, inBandMin: 208 }, …] },
  bestEfforts: { allTime: { oneK: { sec, date }, mile: …, fiveK: …, tenK: …, half: … },
                 last90d: { … } },
  recordsFeed: [{ date, distance: "5k", oldSec, newSec }, …],
  trajectory: { goalSec: 7199,
                weekly: [{ week: "2026-W27", riegelSec, garminSec }, …] }
}
```

`validate_data.py` treats the block as optional (pre-engine files stay valid)
but shape-checks it when present. Size is bounded: ~113 weekly points + ~26
monthly points ≈ 10–15 KB — negligible against the current file.

### D10 — Dashboard: three surfaces on the existing page, hidden when absent
Stage 2 UI is deliberately compact (stage 3 owns exploration):

1. **Race-prediction card** gains the trend verdict (arrow + rate from
   `predictions.trend`) and the current Riegel-vs-Garmin gap.
2. **Records feed card**: the last few record events, humanized
   ("5k record fell — 27:06, was 27:48").
3. **Progress trends**: two compact monthly line charts (pace @ ref HR,
   cadence @ ref pace) reusing the existing chart + hover patterns
   (`chart-hover.js`, current CSS), with `null` months rendered as gaps.

Every surface checks `garminData.insights` and renders nothing when the block
is missing — the dashboard keeps working against pre-engine data files.

### D11 — Verification: metrics coverage joins `--verify-archive`
The existing verify mode gains a metrics section: runs-with-detail vs
`run_metrics` rows at current version, `race_predictions` date bounds and row
count, and the assembled series' month/week counts. Exit non-zero when
coverage regresses (e.g. rows at a stale version after a completed sync).

## Risks / Trade-offs

- [Chart-resolution streams vs Garmin's on-device splits disagree] → oracle
  test with explicit tolerance; systematic direction (ours ≥ Garmin's) is
  acceptable and honest — we never claim a faster time than demonstrated.
- [Reference bands mis-chosen → sparse or noisy series] → bands are constants
  validated against the full archive during implementation (density-check
  task); `METRICS_VERSION` bump makes later re-tuning a one-line change that
  self-heals (D1).
- [Archive step now precedes the telemetry write (D8)] → all steps `safe()`d;
  steady-state top-up is 0–3 calls; worst case matches today's failure surface
  (a hung Garmin call already blocks the sync in `load_activities`).
- [Unofficial predictor-history endpoint disappears or shifts shape] →
  backfill is opportunistic and fail-soft; bank-on-sync builds the line
  forward regardless; raw payload stored (`raw_json`) so a parse fix can
  re-promote columns.
- [Version-bump recompute parses ~100 MB of JSON in one nightly] → measured
  seconds on the dress-rehearsal db; if volume grows 10×, phase 1 can gain a
  per-sync cap without contract changes.
- [Riegel-from-10k reads ~2:13 while Garmin says ~2:01 — the gap may
  demotivate] → this is the point of "honest"; the trend (closing/opening) is
  the motivational surface, not the absolute number, and both lines are shown.

## Migration Plan

1. Merge to `main` → CI publishes the image; pull + recreate on the homeserver
   (same volume).
2. First nightly (or manual) sync: schema v2 migration applies, phase 1
   computes `run_metrics` for all archived runs, predictor backfill fills
   `race_predictions` to 2024, `garmin-data.js` gains `insights`, dashboard
   shows the new surfaces.
3. `docker compose exec splits python3 sync_garmin.py --verify-archive` —
   metrics coverage should match detail coverage; spot-check the dashboard.

Rollback: revert the image. Schema v2 tables are additive and invisible to
stage 1 code; the reverted sync writes `garmin-data.js` without `insights` and
the dashboard hides the surfaces. Nothing to clean up.

## Open Questions

1. **Final band values** — RESOLVED (task 3.1 density check, 2026-07-05):
   HR 125–145 kept; pace band moved from 5:30–6:00 to **7:00–8:00 min/km**
   (420–480 s/km) — the default was near race pace and gap-heavy in 13/21
   trained months, the frozen band leaves only genuinely untrained months
   (≤2 runs) below the 10-minute threshold.
2. **Mile in the UI or data-only?** `best_mile_s` is computed and archived
   either way; whether the dashboard surfaces the mile alongside 1k/5k/10k/half
   is a rendering choice deferred to the UI task.
