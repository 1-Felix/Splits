# Proposal: add-block-lens

## Why

The roadmap's stage 3c ("block retrospectives") was parked as post-race work — but reframed as a **block lens** (one engine that answers "what is this block doing to me?" over any block window), the same feature delivers value *now*, mid-Sonthofen-block, and becomes the retrospective automatically when the block completes on 2026-08-09. Every ingredient already exists in the archive (`plan_snapshots`, `plan_compliance`, `run_metrics`, `race_predictions`); nothing joins them into a block-level story yet.

## What Changes

- **Block lens derivation** in the deterministic sync: a new engine step that enumerates blocks (keyed by race name + date from plan snapshots; window = first week's Monday → race day) and computes per block:
  - *Execution* — per-week done/partial/missed/swapped, km done vs planned, quality-session hit rate, overall % executed, measured against the snapshot each week was scored against.
  - *Adaptation* — EF start-vs-now within the window, cadence-decoupling delta, records fallen inside the block, Riegel-vs-goal gap at block start vs now.
  - *Forward tilt* (in-flight block only) — weeks/km remaining, planned taper shape to race day, plan-integrity flags.
- **Data contract**: an additive `blockLens` object in `garmin-data.js` (current block in full + past-block summaries), fail-soft absent when there is no plan/snapshot history.
- **"The Block" section on `/progress`**: current block as a live report card (phase strip, per-week execution row reusing the compliance visual language, headline stats, taper silhouette); past blocks as collapsed retrospective rows expanding to the identical layout in past tense.
- **Per-week drill-down**: each week row expands to planned days vs matcher verdicts per day, with actual runs linked to `/run/:id`.
- **Block-vs-block comparison**: any two blocks side by side — execution %, volume, EF delta, gap closed, records.
- **Read-only archive endpoints** `GET /api/archive/blocks` (+ per-block week detail) for past-block drill, so `garmin-data.js` never bloats as blocks accumulate; honest offline degradation like every deep view.
- **Coach briefing**: a mirrored "Block report" section in `coach-briefing.md` (same numbers + judgment hooks: behind-plan, EF stalling, stale targets, undetailed weeks) so `/coach` reasons from the lens the dashboard shows.

## Capabilities

### New Capabilities

- `block-lens`: the deterministic block-summary engine over plan snapshots × compliance × run metrics, the additive `blockLens` data-contract object, and the `/progress` "The Block" surface: live report card, past-block retrospectives, per-week drill, and block-vs-block comparison.

### Modified Capabilities

- `archive-api`: gains read-only block endpoints (`/api/archive/blocks`, per-block week detail) — SELECT-and-shape only, no derivation at request time, fail-soft 503.
- `progress-views`: `/progress` gains "The Block" section, static-first from `garmin-data.js` with the archive API used only for past-block drill.
- `coach-loop`: `coach-briefing.md` gains the deterministic "Block report" section.

## Impact

- **Python sync**: new block-lens derivation module (or extension of the metrics engine) invoked from `sync_garmin.py` after compliance scoring; ingest parity considered for Max's ingest-built instances (fail-soft absent — no plan there today).
- **Data contract**: additive `blockLens` in `garmin-data.js`; no schema migration expected (derives from existing archive tables at sync time).
- **Server**: new read-only routes in `serve.mjs` beside the existing archive endpoints.
- **Dashboard**: `/progress` page (`progress.dc.html`) gains the section + drill + comparison UI.
- **Coach loop**: `coach_briefing.py` emits the new section; `/coach` skill docs updated to read it.
- **Tests**: Python derivation fixtures (including a finished-block fixture so the retrospective tense is proven before Aug 9), `test_archive_api.mjs` extension, `/progress` render tests, briefing test extension.
