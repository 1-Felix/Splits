# Tasks: add-block-lens

## 1. Schema + engine (Python)

- [x] 1.1 Schema v9 in `activity_archive.py`: additive `block_lens` table (race_date PK, race_name, lens_version, is_complete, block_json, updated_at), idempotent apply, `--verify-archive` aware of the new table
- [x] 1.2 New `block_lens.py`: block enumeration from `plan_snapshots` (race-key identity, window = earliest week.mon → race.date, latest snapshot shapes the plan; race-date edit spawns a new block)
- [x] 1.3 Execution rollup: per-week verdict counts + km + day-level drill rows from `plan_compliance`; block percent-executed (partial = 0.5) and quality hit rate; future weeks planned-only
- [x] 1.4 Adaptation metrics: EF proxy + cadence deltas (median over first/last 14 days, min 3 qualifying runs else `null` + reason), in-block records vs pre-block all-time bests, goal-gap trend from `race_predictions` vs the race goal time
- [x] 1.5 Forward tilt (current block only): weeks/km remaining, planned weekly-km silhouette, undetailed-week flags (reuse the `integrity_warnings` rule)
- [x] 1.6 Persist + version: `BLOCK_LENS_VERSION`, current block recomputed every sync, completed blocks healed on version bump; wire into `sync_garmin.py` after compliance + metrics, fail-soft (`_warn`, sync never breaks)
- [x] 1.7 Data contract: additive `blockLens` (`lensVersion`, `current` full, `past` summaries newest-first) written into `garmin-data.js`; absent when no snapshots
- [x] 1.8 Python tests (`test_block_lens.py`): fixtures incl. a **finished block** (retrospective tense proven pre-race), multi-snapshot single-block identity, race-date-edit split, insufficient-baseline nulls, in-block record dedup, rollup weights, fail-soft derivation error

## 2. Archive API (serve.mjs)

- [x] 2.1 `GET /api/archive/blocks` — stored rows as summaries, newest race first; empty list is 200
- [x] 2.2 `GET /api/archive/blocks/:raceDate` — stored `block_json` verbatim; 404 unknown key; 503 fail-soft when the archive is away
- [x] 2.3 Extend `test_archive_api.mjs`: listing order, summary shape, verbatim document, 404, 503, no request-time derivation (no plan tables touched beyond SELECT on `block_lens`)

## 3. The Block section (/progress)

- [x] 3.1 Live report card from `blockLens.current`: phase strip, per-week execution row (compliance visual language), headline stats line, taper silhouette; live-clock week-N highlight over sync-time numbers; honest insufficient-data marks for null metrics
- [x] 3.2 Per-week drill: day rows (planned vs verdict + actuals, reason), matched runs → `/run/:id`; current block fully static
- [x] 3.3 Past blocks: collapsed summary rows from `blockLens.past`, expanding via `/api/archive/blocks/:raceDate` to the same layout in past tense; honest archive-offline state on failure
- [x] 3.4 Block-vs-block comparison: two-block picker, side-by-side headline metrics with best-per-row marks, selection mirrored to the URL query (comparison is a link); hidden below two blocks
- [x] 3.5 Section absent cleanly when `blockLens` is missing; rest of /progress unaffected
- [x] 3.6 Render tests (`test_progress_page.mjs` extension or `test_block_section.mjs`): static-first card, drill expansion, offline degradation, URL-driven comparison, absence, null-metric honesty

## 4. Coach briefing + ritual

- [x] 4.1 `coach_briefing.py`: "Block report" section rendered from the passed-in lens document (never recomputed) — headline numbers + factual judgment hooks; omitted cleanly when no lens
- [x] 4.2 Extend `test_coach_briefing.py`: numbers identical to the `blockLens.current` document, explicit null-metric prose, section omitted without snapshots
- [x] 4.3 Update the `/coach` skill docs: Block report joins the ritual's reading list as the block-level state of record

## 5. Verify + deploy

- [x] 5.1 Full local test run (Python + mjs) green; run a real local sync and eyeball `blockLens` in `garmin-data.js`, the /progress section, and the briefing section
- [ ] 5.2 Deploy to the NUC (container build + sync), verify schema v9 applied, the Sonthofen block renders live, API endpoints respond, briefing carries the Block report
- [ ] 5.3 Sync delta specs to main specs and mark the roadmap's 3c as shipped-early via the block lens
