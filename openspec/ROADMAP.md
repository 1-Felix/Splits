# SPLITS Roadmap — from dashboard to running companion

*Crystallized 2026-07-05 from an explore session. This is the long-term arc; each
stage becomes its own OpenSpec change when work starts.*

## Vision

Turn SPLITS from a beautiful **display** of the last few months into a running
**companion** with memory: deep, honest insight into performance over time —
pace improving at a given heart rate, cadence getting more efficient, milestone
records falling — and a plan that adapts to what actually happened.

## What progress means here (the athlete's own definition)

1. **Pace at a given heart rate improving** — the aerobic engine growing.
2. **Cadence getting more efficient** — form improving at comparable paces.
3. **Records falling at km milestones** — fastest 1k / mile / 5k / 10k / half,
   extracted from *inside* every run, not just official Garmin PRs.

## Ground truth (probed 2026-07-05)

- Garmin account history starts **2024-05-12**; **536 activities** total
  (2026 so far: 69 runs / 608 km · 2025: 77 runs / 510 km · 2024: 16 runs / 49 km,
  plus ~300 strength sessions).
- Backfill of the full account incl. per-activity detail is ~540 API calls — one
  evening job with the existing per-activity cache pattern.
- Today's data layer is a **rolling window** (30 monthly pts, 26 weekly pts,
  365-day heatmap, 14 sleep nights, detail for 6 recent runs) overwritten every
  sync. Around **Nov 2026** the window slides past May 2024 and starts dropping
  the earliest history — archive before then and it never matters.

## Architecture principle (unchanged)

The dashboard's golden rule stays: it imports one merged `running-data.js` and
talks to no API. The durable layer sits **behind** the sync:

```
nightly sync (Python, deterministic — no AI)
├─▶ archive: append every new activity + detail (SQLite in /data, backfilled to 2024)
├─▶ metrics engine: efficiency, best efforts, records, plan-vs-actual
├─▶ garmin-data.js  ──────────────▶ dashboard (windowed view, as today)
└─▶ coach-briefing.md  ← pre-digested state for the coach
                │
                ▼
   /coach in Claude Code (subscription, no API) — reads briefing,
   discusses, edits plan-data.js (the live symlink / volume file)
```

**Constraint that shapes the coach loop:** no agent API — the AI coach runs only
as Claude Code sessions on the subscription plan. Therefore everything
quantitative lives in the deterministic sync; AI is reserved for judgment
(adapting the plan), invoked manually as a one-command ritual. The dashboard
must stay fully functional if `/coach` is never run.

## The staged arc

Each stage is shippable alone and makes the next more valuable.

### 1. `activity-archive` — the foundation *(shipped 2026-07-05)*
SQLite database in the `/data` volume. One-time backfill of all activities since
2024-05 including per-run detail (splits, HR, cadence streams); the sync appends
every new activity forever after. Pure data layer, zero UI. The archive schema
is the long-lived contract everything later reads — it gets its own design pass.

**As built** (what stage 2 reads): `<DATA_DIR>/activity-archive.db`, module
`activity_archive.py` (stdlib sqlite3). Tables: `activities` (raw
`summary_json` + raw `detail_json` per Garmin activityId, promoted columns
`start_time_local`/`type_key`/distance/duration/HR/cadence/elevation as the
index), `daily_wellness` (one row per date: RHR, HRV, sleep + `raw_json`),
`archive_meta` (`schema_version` = 1, coverage expectations). Entry points:
`sync_garmin.py --backfill` (full-history pull, idempotent/resumable) and
`--verify-archive` (coverage report, exit ≠ 0 on regression); every normal
sync appends summaries, tops up ≤ 25 details, and banks today's wellness row —
fail-soft, always after `garmin-data.js` is written.

### 2. `insight-metrics` — the measures of progress *(serves Sonthofen, Aug 9 2026)*
Deterministic metrics engine over the archive, surfaced into `garmin-data.js`:
- **Efficiency Factor trend** — speed ÷ HR on steady/Z2 runs, over months.
- **Cadence–pace decoupling** — cadence at a reference pace over time.
- **In-run best efforts + records feed** — fastest 1k/mile/5k/10k/half inside
  any run; best-efforts curve; "records fell this month" feed.
- **Honest race trajectory** — Riegel-from-best-efforts vs Garmin's predictor,
  tracked weekly: is the gap to the goal (sub-2:00 half) closing?

### 3. `progress-views` — room to explore *(post-race is fine)*
The dashboard need not stay one page. A cockpit (today/this week — the current
page) plus progress views: records wall, efficiency story, year-over-year
comparisons, archive browser / run comparison.

### 4. `coach-loop` — the companion closes the loop
Plan-vs-actual compliance scoring in the sync (matched sessions, pace/zone
execution vs targets), `coach-briefing.md`, and a `/coach` skill that reads the
briefing and edits `plan-data.js`. Turns the existing manual coaching workflow
into a one-command ritual.

## Sequencing rationale

- Archive first: cheap now, impossible to regret, and stage 2–4 all read it.
- Metrics second: five weeks out from the goal race, "is the gap closing" is
  the highest-motivation insight per unit of work.
- Views and coach-loop after: they get better the more archive depth and metric
  history exist.
