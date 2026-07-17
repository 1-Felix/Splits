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

## Architecture principle (rescoped 2026-07-05, stage 3a)

The golden rule was rescoped when the dashboard went multi-page — the rule's
*reason* (race-morning resilience) attaches to the cockpit, not to every page:

- **The cockpit (`/`) renders complete from static files** — one merged
  `running-data.js`, no fetch it can't lose.
- **Deep views may talk to the read-only archive API** (`/api/archive/…` in
  `serve.mjs` — a window, not an engine: it SELECTs stored rows, never derives)
  and must degrade to an honest "archive offline" state, never a broken page.

All derivation still lives in the deterministic sync:

```
nightly sync (Python, deterministic — no AI)
├─▶ archive: append every new activity + raw detail + distilled detail (SQLite in /data)
├─▶ metrics engine: efficiency, best efforts (incl. by-year), yoy, records, plan-vs-actual
├─▶ garmin-data.js  ──────────────▶ cockpit `/` (static-only) + /progress (static-first)
└─▶ coach-briefing.md  ← pre-digested state for the coach
                │                        ▲
                ▼                        │ read-only /api/archive (drill-downs)
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

### 3. `progress-views` — room to explore *(reframed 2026-07-05: the refactor
the dashboard deserved — grow the weekend project into a running companion)*

Split into three sub-stages; 3a is the architectural investment the rest ride on.

- **3a — the refactor + two views** *(shipped 2026-07-05)*: multi-page shell (cockpit `/` + `/progress`, shared
  `topbar.js` behavior, theme persisted via `localStorage`), the read-only
  archive API (`node:sqlite`, Node 24, distilled detail stored at sync time —
  archive schema v4), the cockpit diet (long-game sections move to `/progress`;
  the heatmap stays), and two views proving it: the **records wall**
  (all-time / 90 d / by-year, click-through to any archived run) and
  **year-over-year** monthly volume.
- **3b — archive browser + run comparison** *(post-race)*: browse/filter all
  archived activities over the list endpoint; compare runs side by side —
  natural first use: compare Sonthofen to the tune-up races.
- **3c — block retrospectives** *(shipped early 2026-07-18 as `add-block-lens`)*:
  reframed from a post-race report into the **block lens** — one deterministic
  engine over `plan_snapshots` × `plan_compliance` × `run_metrics` ×
  `race_predictions` (schema v9 `block_lens` table) that renders the in-flight
  block as a live report card on `/progress` ("The Block": per-week execution,
  day drill, adaptation metrics, forward tilt, block-vs-block comparison) and
  becomes each block's retrospective automatically when its race date passes.
  Same numbers reach `/coach` as the briefing's "Block report" section.

### 4. `coach-loop` — the companion closes the loop
Plan-vs-actual compliance scoring in the sync (matched sessions, pace/zone
execution vs targets), `coach-briefing.md`, and a `/coach` skill that reads the
briefing and edits `plan-data.js`. Turns the existing manual coaching workflow
into a one-command ritual.

**Decisions from the 2026-07-05 explore session:**

- **Full plan upfront, adjust-don't-author.** The block is detailed to race
  day from day one; the ritual *adjusts* the standing plan from actuals rather
  than authoring next week from a summary row. Progressive elaboration
  (`days: null` until the week approaches) is retired — an undetailed future
  week is a plan-integrity warning in the briefing. `plan-data.default.js`
  (seed plan + header docs) flips to the new philosophy as part of the change.
  Rationale: progressive elaboration exists because *human* re-planning is
  expensive; with an AI coach revision is cheap, and a fully detailed living
  draft beats `null` for compliance, diffable coaching, and the dashboard.
- **Plan snapshots are mandatory.** Under adjust-don't-author the plan file
  mutates constantly; the sync snapshots the scored week into the archive
  (append-only) so a later plan edit can never rewrite what a past run was
  measured against.
- **Matcher** (well-defined because the plan is total): same date + kind →
  matched; same week, nearest unmatched same-kind day → swapped; otherwise
  unplanned. Planned day with no actual by week's end → missed. Scoring stays
  coarse on the structured fields (kind / km / load / zone); intent comes from
  the plan, never re-classified.
- **Plan staleness signal:** deterministic comparison of the plan's pace
  targets vs current demonstrated fitness (best efforts / Riegel anchor),
  surfaced in the briefing; the skill judges whether to reprice.
- **Dashboard compliance marks are in scope:** per-day compliance block in
  `garmin-data.js` (done / partial / missed / swapped / unplanned), joined
  onto the block's week rows and THIS WEEK by date, degrading gracefully when
  the block is absent.
- **One adaptive `/coach` skill, no modes** — offers block-building when
  future weeks are undetailed, review-and-adjust otherwise.
- **Python reads the coach-owned JS plan** via a short-lived node child that
  imports it and prints JSON (the `plan-io.mjs` CHECK_SCRIPT pattern),
  fail-soft: plan unreadable → skip compliance, never break `garmin-data.js`.
- **Briefing contents** to be specced from a hand-run of the ritual (the
  2026-07-05 Wk 2–6 detailing session): whatever the coach reached for is
  what `coach-briefing.md` must contain.

## Sequencing rationale

- Archive first: cheap now, impossible to regret, and stage 2–4 all read it.
- Metrics second: five weeks out from the goal race, "is the gap closing" is
  the highest-motivation insight per unit of work.
- Views and coach-loop after: they get better the more archive depth and metric
  history exist.
