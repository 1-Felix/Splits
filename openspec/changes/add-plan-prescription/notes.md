# add-plan-prescription — implementation notes

## Deviations from the task list

- **3.2's pins live in `test_run_page.mjs`, not `test_archive_api.mjs`** —
  that suite's archive deliberately carries NO `plan_compliance` table (its
  absence proves the block endpoints touch nothing beyond `block_lens`).
  The run-page suite owns the plan fixtures, so presence and absence of
  `quality` are pinned there, over the real server.
- **`serve.mjs` reads the plan row with `SELECT *`** (named columns before):
  serve opens the archive read-only and never migrates, so right after a
  deploy the table may not carry `quality_json` yet — a named-column SELECT
  would throw and take the whole plan card with it. Missing column → absent
  field, nothing else changes.
- The briefing golden (`fixtures/coach-pass/golden-blocks.json`) moved by
  exactly one line: `complianceVersion` 1 → 2.

## Mutation ledger (run 2026-07-30/31, against finished code)

| Mutation | Pinned test | Result |
|---|---|---|
| drop single-pace ±5 band widening | `test_single_pace_widens_to_a_symmetric_band` | RED (killed) |
| steady accepts `@` without `~` | `test_steady_target_requires_the_approx_marker` | RED (killed) |
| rep regex anchored to string head | `test_embedded_rep_set_wins_over_its_warmup` | RED (killed) |
| zone never read | `test_time_based_sets_carry_durations_not_distances` | RED (killed) |
| `min` not converted to seconds | same | RED (killed) |
| verdict writer downgrades status | `test_annotation_never_changes_status_or_reason` | RED (killed) |
| `inBand` counts every rep | `test_quality_verdict_counts_reps_and_the_band` | RED (killed) |
| zone verdict always confirms | `test_quality_verdict_zone_sets_judge_the_zone_not_pace` | RED (killed) |
| steady tolerance unbounded | `test_quality_verdict_steady_target_tolerance` | RED (killed) |
| drop the plan-card quality node | run-page quality case | RED (killed) |
| drop the briefing verdict append | `test_render_speaks_the_rep_verdict_beside_the_status` | RED (killed) |
| drop the `_is_run_slot` guard in the annotator | `test_a_cross_days_bike_intervals_are_not_a_rep_verdict_question` | RED (killed) |
| drop the unplanned-row guard | `test_an_unplanned_same_day_run_gets_no_verdict` | RED (killed) |

13 mutations, 13 killed.

## Second live seam: the unplanned same-day run

The first deploy's briefing annotated 2026-07-29's UNPLANNED second activity
(a 2.3 km shuffle after the strides session) with `0/4 reps, no structured
set detected` — the date-keyed day lookup handed the planned day's
prescription to a row that was never its subject. The annotator now skips
rows with `planned_kind IS NULL`. The current week is open (rescored every
sync), so this healed on the next rescore without a version bump. Writing the
fixture found a subtlety worth recording: a closed week's swap pass will
rescue a same-day leftover ≥ 50 % of any missed slot's km into `swapped`, so
the test's shuffle had to be 1.5 km to land as `unplanned` at all.

## Found live on first deploy, fixed before final: the bike-intervals seam

The first production rescore annotated `2026-07-17` — **"Bike Intervals"**,
kind `cross`, km 0 — with `"no interval document"`. The plan prescribes bike
work in the same `6×3 min hard (Z4 effort)` notation, so the parser read it;
but the rep verdict is a RUNNING question, and the lens never reads a ride.
The annotator now shares the scorer's own `_is_run_slot` predicate; a non-run
slot gets no verdict regardless of how parseable its segments are.

Two verdicts the first deploy proved out as genuinely informative:
`2026-07-03` reads `4/4 reps, 0 inside 5:25–5:35` because the reps measured
4:52/5:12/5:13/5:16 — all FASTER than prescribed (run too hot; exactly the
conversation the coach loop exists for), and `2026-07-29`'s strides read
`4/4 reps` count-only, as designed for 20 s efforts.

## Suite at merge

Python `593 passed / 2 skipped` at the final commit (569 before this change);
all four JS suites ALL PASS; style-audit `/run` clean at 390.

## Pre-deploy status capture (for 4.3's byte-identical check)

35 planned rows, 2026-06-29 → 2026-08-02. Non-`done`: 07-08 partial
(distance), 07-15 missed, 07-23 missed, 07-24 swapped, 07-25 missed, 07-26
missed, 07-30…08-02 pending. Every one of these must be IDENTICAL after the
version-2 rescore — only `quality_json` may appear.

## Post-deploy (2026-07-30 evening, NUC, three deploys)

Final state at `116e5a1`: 35 rows all at COMPLIANCE_VERSION 3, statuses
byte-identical to the pre-deploy capture, 7 run verdicts live, zero verdicts
on cross days or unplanned rows, `verify_archive` exit 0. The briefing's
2026-07-29 lines read `done · 4/4 reps` (planned) and plain `unplanned`
(shuffle). The /run API serves `plan.quality` verbatim; the page rendering is
pinned by the Playwright suite against a real Chromium.
