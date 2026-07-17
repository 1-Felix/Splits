# Design: add-block-lens

## Context

Roadmap 3c reframed: one deterministic engine ("the block lens") that answers
"what is this block doing to me?" over any block window — live report card for
the in-flight block today, retrospective for completed blocks forever after.

Everything it needs already exists in the archive:

- `plan_snapshots` — append-only, content-deduped plan versions (`plan_json`
  carries `race` + `block` weeks), so past blocks stay derivable after
  `plan-data.js` moves on to the next race.
- `plan_compliance` — per-day verdicts (`status`, `reason`, planned vs actual
  fields, `activity_id`) keyed to the snapshot they were scored against.
- `run_metrics` — per-run best efforts + reference-band aggregates
  (`refhr_pace_s_per_km` for EF-style pace-at-reference-HR,
  `refpace_cadence_spm` for cadence at reference pace).
- `race_predictions` — daily predictor rows (`half_s`) for the Riegel/goal gap.

Architecture rules that bind this design: all derivation lives in the
deterministic sync; the archive API is a window, not an engine (SELECTs stored
rows, never derives at request time); `/progress` is static-first with
archive-API drill as the only network-dependent interaction; everything is
fail-soft and additive.

## Goals / Non-Goals

**Goals:**

- One derivation, three surfaces: `/progress` "The Block" section (live +
  retrospectives + per-week drill + block-vs-block comparison), `blockLens`
  in `garmin-data.js`, and a "Block report" section in `coach-briefing.md`.
- Past blocks remain fully drillable years later without bloating
  `garmin-data.js`.
- The Sonthofen block renders as a live report card immediately; on 2026-08-09
  it becomes the first archived retrospective with zero further work.

**Non-Goals:**

- No AI/judgment in the sync — the lens states numbers; `/coach` judges.
- No re-scoring or re-classification of compliance — the lens rolls up
  existing verdicts, never second-guesses the matcher.
- No block *editing* surface — blocks are what the plan history says they were.
- No ingest-side (Max) block lens — his instance has no plan; the lens is
  simply absent there (fail-soft), like `compliance` today.

## Decisions

### D1 — Block identity: keyed by race, enumerated from snapshots

A block is `(race.name, race.date)` as found in `plan_snapshots.plan_json`.
For each distinct race key: window = earliest `week.mon` seen across that
race's snapshots → `race.date`; the **latest** snapshot for the race defines
the final planned shape (weeks, phases, planned km). The block whose race date
is ≥ today (from the live plan) is *current*; all others are *past*.
Compliance rows keep their own `snapshot_id` linkage — execution is always
measured against what the plan said at the time, which the snapshot mechanism
already guarantees.

*Alternative considered:* block boundaries from the live plan file only —
rejected because past blocks vanish the moment the plan moves to the next
race; snapshots are the durable record.

### D2 — Storage: one derived table, disposable-cache semantics (schema v9)

```sql
CREATE TABLE IF NOT EXISTS block_lens (
  race_date    TEXT PRIMARY KEY,   -- block identity
  race_name    TEXT NOT NULL,
  lens_version INTEGER NOT NULL,   -- BLOCK_LENS_VERSION, like METRICS_VERSION
  is_complete  INTEGER NOT NULL,   -- race date < sync-today
  block_json   TEXT NOT NULL,      -- the FULL lens document (weeks, drill, metrics)
  updated_at   TEXT NOT NULL
);
```

Additive schema v9, derived-only, always recomputable from snapshots ×
compliance × run_metrics × race_predictions — same contract as `run_metrics`
and `plan_compliance`. This is what lets the archive API stay a window: block
endpoints SELECT `block_json` verbatim, deriving nothing at request time.
Every sync recomputes the current block's row; completed blocks recompute only
when `lens_version` bumps (cheap either way — it's aggregation, not stream
processing).

*Alternative considered:* derive only into `garmin-data.js` with no table —
rejected: past-block drill would force either request-time derivation
(violates the API rule) or unbounded `garmin-data.js` growth.

### D3 — Engine: new module `block_lens.py`, invoked after compliance + insights

Same module pattern as `plan_compliance.py` / `insight_metrics.py`: pure
functions over `(conn, today)`, `BLOCK_LENS_VERSION` covering all algorithm
parameters, `_warn` fail-soft, called from `sync_garmin.py` **after**
compliance scoring and metrics extraction (it reads both), always after
`garmin-data.js`'s upstream inputs exist. Per block it computes:

- **Execution** (from `plan_compliance` grouped by week window): per-week
  counts of done/partial/missed/swapped/unplanned, planned vs actual km,
  quality hit rate (planned `load == "Hard"` days executed), overall
  `% executed = (done + swapped + 0.5·partial) / scored planned days`.
- **Adaptation** (window-scoped): EF proxy = median `refhr_pace_s_per_km`
  over the block's first 14 days vs its last 14 days (honest `null` + reason
  when either end has < 3 qualifying runs); cadence delta likewise from
  `refpace_cadence_spm`; records fallen inside the block = per-distance best
  inside the window that beats the all-time best *before* the window;
  Riegel/goal gap = `race_predictions.half_s` nearest block start vs latest,
  against goal seconds from the race's `goalTime`.
- **Forward tilt** (current block only): weeks/km remaining, planned weekly
  km silhouette to race day, plan-integrity flags (undetailed weeks — same
  rule `coach_briefing.integrity_warnings` applies).

### D4 — Data contract: `blockLens` in `garmin-data.js`, summaries-only for past blocks

Additive top-level object: `{ lensVersion, current: <full lens document>,
past: [<summary slice>...] }` where the past-block summary is the headline
numbers only (identity, window, % executed, km, EF/gap/records deltas). Full
past-block documents come from the API. Absent entirely when there are no
snapshots (fresh install, ingest instances) — consumers hide the section,
exactly like `compliance` today.

### D5 — Archive API: two SELECT-and-shape endpoints

- `GET /api/archive/blocks` — all `block_lens` rows as summaries (promoted
  columns + headline slice of `block_json`), newest race first.
- `GET /api/archive/blocks/:raceDate` — one full `block_json` verbatim.

Same `node:sqlite` read-only pattern, fail-soft 503, no derivation. `:raceDate`
as the key keeps URLs stable and human-readable (`/api/archive/blocks/2026-08-09`).

### D6 — UI: "The Block" on `/progress`, URL-addressable like the archive browser

- **Live card** (current block, static from `blockLens.current`): phase strip,
  per-week execution row reusing the compliance-mark visual language, headline
  stats line, taper silhouette of remaining planned weeks. "Week N of M"
  highlight follows the live-dashboard display-today rule (client clock), while
  all numbers are sync-time truth.
- **Per-week drill**: a week row expands to planned days vs matcher verdicts
  (status + reason + actual km/pace/HR), runs linking to `/run/:id`. Current
  block drills from static data; past blocks fetch the full document from D5
  and degrade to the honest "archive offline" state.
- **Retrospectives**: past blocks as collapsed rows under the live card
  (from `blockLens.past`), expanding via the API to the identical layout in
  past tense (no forward tilt).
- **Comparison**: a compare toggle selects exactly two blocks; state mirrored
  into the URL (`/progress?blocks=2026-08-09,2027-04-XX`) following the
  archive-browser convention, so a comparison is a link. Renders headline
  metrics side by side with best-per-row marks (run-comparison's visual
  grammar). With fewer than two blocks the toggle is hidden — nothing to
  compare is a normal state, not an error.

### D7 — Coach briefing: same document, rendered as prose

`coach_briefing.render_briefing` gains a "Block report" section rendered from
the same lens document (passed in, not recomputed): headline numbers plus
judgment hooks stated as facts — behind-plan volume, EF stalling/regressing,
stale pace targets (existing `staleness_notes` stays), undetailed weeks.
`/coach` skill docs updated to read the section. Briefing degrades to omitting
the section when the lens is absent.

## Risks / Trade-offs

- [Only one block exists today] → comparison UI hidden below two blocks;
  retrospective rendering is still proven now via a finished-block test
  fixture, not first exercised on race day.
- [EF/cadence windows noisy on short or interrupted blocks] → explicit
  qualifying-run minimums with `null` + human-readable reason in the document;
  the UI renders an honest "insufficient data" mark, never a fabricated delta.
- [Seed/default plan creates a lens for the sample race on fresh installs] →
  acceptable and correct: the lens reflects whatever plan was actually live;
  documented in the default plan header.
- [Race date changes mid-block (plan edit)] → the race key changes, spawning a
  new block row; the old row's `is_complete` flips at its race date with the
  compliance history it accrued. Documented behavior; snapshots make both
  derivable, and a lens_version bump can revisit the policy.
- [block_json grows with long blocks] → bounded in practice (a block is weeks,
  not years); summaries keep `garmin-data.js` flat regardless.

## Migration Plan

1. Schema v9 applied idempotently on sync start (additive table only) — same
   mechanism as v2–v8; NUC picks it up on the next container deploy + sync.
2. Rollback = redeploy previous image; the extra table is inert to old code
   and disposable by contract (derived cache, recomputable).
3. No backfill step needed: first sync at the new version derives every block
   snapshots can describe (on the NUC that's the Sonthofen block).

## Open Questions

None blocking — parameter values (14-day EF windows, minimum qualifying runs,
partial-credit weight) are pinned in specs/tests and covered by
`BLOCK_LENS_VERSION` so they can evolve without ambiguity.
