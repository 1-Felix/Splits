# Proposal: coach-loop

## Why

The companion loop is three-quarters built: the archive holds every run, the
metrics engine says whether the gap to sub-2:00 is closing, and the plan is now
fully detailed to race day under the standing rule that coaching *adjusts* the
plan from actuals rather than authoring weeks late. But the adjusting itself is
still an unscripted manual ritual: the coach (a Claude Code session) hand-joins
plan days against `garmin-data.js` runs, re-derives compliance by eye, and edits
`plan-data.js` from memory of prior commitments. The 2026-07-05 hand-run of that
ritual proved every input it needs is already computable deterministically — and
with five weekly rituals left before Sonthofen (Aug 9), each one done by hand is
both slower and less honest than it should be.

## What Changes

- **Plan-vs-actual compliance scoring in the nightly sync** (deterministic, no
  AI): a matcher joins archived activities to planned days — same date + kind →
  matched; same week, nearest unmatched same-kind day → swapped; leftover actual
  → unplanned; planned day past with no actual → missed — and scores matched
  runs coarsely on the plan's structured fields (km, load, zone). Intent comes
  from the plan, never re-classified.
- **Plan snapshots in the archive** (schema v3, additive): the sync banks a
  content-hash-deduped snapshot of the plan and scores each day against the
  snapshot current at scoring time, so a later plan edit can never rewrite what
  a past run was measured against. Compliance rows are recomputable from
  snapshots + archive at any time (versioned like `run_metrics`).
- **The sync reads the coach-owned JS plan** via a short-lived node child that
  imports it and prints JSON (the `plan-io.mjs` validator pattern; both
  runtimes ship in the image). Fail-soft: plan unreadable → skip compliance and
  briefing, never break `garmin-data.js`.
- **`coach-briefing.md` generated every sync** into the data volume: the
  pre-digested state the hand-run reached for — per-day plan-vs-actual for the
  closing week, records + best efforts, the Riegel-vs-Garmin-vs-goal trajectory
  with closing rate, efficiency/cadence tails with sample-size caveats, today's
  readiness, the coach-log tail (prior commitments), profile constants, and
  days-to-race arithmetic — plus **plan-staleness notes** (plan pace targets vs
  currently demonstrated fitness) and **plan-integrity warnings** (undetailed
  future weeks).
- **A `/coach` skill** (one adaptive prompt, no modes): reads the briefing and
  the live plan, discusses, then applies plan edits with validation before
  write and a `coach.log` entry documenting every adjustment. Offers
  block-building when future weeks are undetailed, review-and-adjust otherwise.
- **`garmin-data.js` gains a `compliance` block** (additive, independent of
  `insights` — separate fail domain) and the dashboard marks each block-week
  day done / partial / missed / swapped / unplanned, degrading gracefully when
  the block is absent.
- **`plan-data.default.js` flips to the full-plan philosophy**: seed plan
  detailed for every week, header docs rewritten from "flesh out each week as
  it approaches" to adjust-don't-author.

## Capabilities

### New Capabilities

- `coach-loop`: the closing of the companion loop — plan ingestion from the
  coach-owned JS file, plan snapshots (archive schema v3), the plan-vs-actual
  matcher and coarse compliance scoring, plan-staleness and plan-integrity
  signals, `coach-briefing.md` assembly, the `compliance` contract surfaced
  into `garmin-data.js`, and the `/coach` skill's ritual contract
  (validate-before-write, always log). Fail-soft inside the sync, recomputable
  from the archive at any time.

### Modified Capabilities

- `live-dashboard`: added requirements — the dashboard renders per-day
  compliance marks on the block's week rows and THIS WEEK from the
  `compliance` block, degrading gracefully when the block is absent
  (pre-coach-loop data files keep working).

## Impact

- **New code**: `plan_compliance.py` (plan ingestion, snapshots, matcher,
  scoring, staleness), `coach_briefing.py` (briefing assembly),
  `tools/plan-dump.mjs` (plan → JSON child), `.claude/skills/coach/SKILL.md`
  (the ritual), tests (`test_plan_compliance.py`, `test_coach_briefing.py`).
- **Modified code**: `sync_garmin.py` (compliance + briefing steps, `compliance`
  block in the emitted contract), `activity_archive.py` (schema v3:
  `plan_snapshots` + `plan_compliance` tables — additive),
  `validate_data.py` (contract check for the new block), dashboard UI
  (`Running Dashboard.dc.html`, `support.js`, `dashboard.css`),
  `plan-data.default.js` (philosophy flip).
- **Data**: `activity-archive.db` schema v3 (additive). `coach-briefing.md`
  written to the data volume next to `garmin-data.js`. No new Python
  dependencies; no new network calls, auth scopes, or API usage.
- **Depends on**: `activity-archive` (deployed) for actuals; `insight-metrics`
  (deployed) for the trajectory/records/efficiency content of the briefing;
  `plan-sync` conventions for safe plan writes (the skill validates with the
  same validator before writing).
- **Explicitly out of scope**: multi-page progress views (stage 3), any
  AI-computed numbers in the sync, automated plan edits without a human in the
  session, away-mode push automation inside the skill (it documents the
  existing `plan:push` path instead).
