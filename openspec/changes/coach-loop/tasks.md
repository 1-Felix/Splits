# Tasks: coach-loop

## 1. Archive schema v3

- [x] 1.1 In `activity_archive.py`: forward-only migration to schema v3 —
      create `plan_snapshots` (id, sha256 UNIQUE, first_seen_date, plan_json)
      and `plan_compliance` (date, snapshot_id, compliance_version, wk, planned
      kind/km/load/title, status, reason, actual km/pace_s/hr, activity_id)
      per design D2/D3; bump `archive_meta.schema_version` to 3; v1/v2 tables
      untouched
- [x] 1.2 Accessors: `bank_plan_snapshot(raw_text, plan_json, seen_date)` → id
      (hash-dedupe insert), `snapshot_plan(id)`,
      `replace_compliance_week(mon, sun, rows)` (delete-range + insert in one
      transaction — cleaner idempotence than row upserts since unplanned rows
      make dates non-unique), `compliance_rows(since_date)`,
      `stale_compliance_weeks(version)`, `compliance_coverage(version)`
- [x] 1.3 Extend `--verify-archive`: compliance section reported (snapshots,
      rows/weeks, stale); regressions = stale-version rows after a sync, or
      scored weeks below the `expected_compliance_weeks` ratchet
- [x] 1.4 Tests: v2→v3 migration on a populated db (frozen v2 DDL), idempotent
      re-open at v3, snapshot dedupe, replace_compliance_week scoped to its
      week + idempotent, stale-week listing + coverage

## 2. Plan ingestion (design D1)

- [x] 2.1 `tools/plan-dump.mjs`: import the plan file given as argv, print
      `JSON.stringify(planData)`, exit 2 with the reason on stderr when the
      named export is missing or import throws
- [x] 2.2 In `plan_compliance.py`: `load_plan(path)` — spawn node child with
      kill-timeout and the minimal env allow-list (mirror `plan-io.mjs`
      `SAFE_ENV_KEYS`), parse stdout JSON; any failure → `None` + warning
      (caller skips compliance and briefing, never raises). Found en route:
      the data volume has no package.json, so node parses a bare `.js` path
      as CommonJS — the dump therefore runs against a temp `.mjs` copy of the
      plan text (the same trick plan-io.mjs uses)
- [x] 2.3 Tests: valid plan dumps and parses; throwing plan → `None`;
      busy-loop plan is killed by the timeout → `None`; garbage stdout →
      `None`; missing file/export → `None`; `fetch_compliance` returns `None`
      (block omitted) for a missing and a throwing plan

## 3. Compliance engine (`plan_compliance.py`, design D3/D4)

- [x] 3.1 Kind mapping from archived `type_key`: running/treadmill → `run`,
      strength_training → `strength`, cycling/biking → `cross`;
      everything else ignored by the matcher
- [x] 3.2 Matcher pass 1 — same date + kind → matched, largest-distance actual
      takes a contested slot, leftovers become unplanned candidates. Hybrid
      days (cross/strength with planned km > 0, the live plan's "Spin + Easy
      Run" Mondays) are scored on their RUN component; same-day activities of
      the day's own kind are absorbed silently so the spin is never noise
- [x] 3.3 Matcher pass 2 at week close — missed run slots paired with leftover
      same-week runs globally by date proximity (ties: earlier actual, then
      earlier planned day — so a far slot can't steal a nearer slot's run) →
      `swapped`; a run under half the slot's km never pairs. Leftover RUNS
      become `unplanned` (extra rides/strength are life, not noise); future
      days `pending`, past days in the open week provisionally `missed`
- [x] 3.4 Scoring with named module constants: distance ratio ≥ 85% + intensity
      consistent → `done`; ≥ 50% or intensity off → `partial` + reason
      (`distance`|`intensity`); < 50% → `missed`; intensity (avg HR > 85% max)
      checked only for Easy/Moderate intent; Hard scored on distance alone;
      strength/cross presence → `done` / absence → `missed`; intent always
      from the snapshot, never re-classified
- [x] 3.5 Driver: each sync banks today's snapshot, rescores the open week
      (current snapshot) + last closed week (FROZEN at its first post-close
      scoring — nightly rescores only catch late-syncing activities), and
      heals stale-version weeks against their originally-referenced snapshots
- [x] 3.6 Unit tests on synthetic week fixtures: matched / swapped / unplanned
      / missed / pending / contested slot / partial-distance /
      partial-intensity (easy run at 90% max) / Hard-not-policed / hybrid-day
      run component + absorption / strength presence + absence / undetailed
      week scores nothing
- [x] 3.7 Versioning tests: two identical syncs → identical rows + one
      snapshot; retroactive plan edit can't rescore a closed week (freeze);
      version bump → rescored against original snapshot ids with history
      preserved

## 4. Contract: the `compliance` block (design D5)

- [x] 4.1 `assemble_compliance(conn, plan, today)` → `{ complianceVersion,
      days: [...], weeks: [...] }` covering the block range up to today, or
      raises (caller omits the block — no partials); race-day rows excluded
      from week aggregates per the plan's own convention
- [x] 4.2 `sync_garmin.py`: `compliance_step` after `metrics_step`, before
      `build_data`, in the same fail-soft `safe()` pattern (+ the
      `expected_compliance_weeks` ratchet); block emitted into
      `garmin-data.js` independently of `insights`
- [x] 4.3 `validate_data.py`: `validate_compliance` shape check when the block
      is present (day fields, allowed statuses/reasons/kinds, week aggregates)
- [x] 4.4 Tests: compliance block assembles while insights side is down
      (independence), broken/missing plan → block omitted, assemble raises
      without rows, validator accepts a good block and names each defect,
      verify-archive compliance regression paths

## 5. Briefing (`coach_briefing.py`, design D6)

- [x] 5.1 Renderer with fixed section order: days-to-race + current-week
      arithmetic · per-day plan-vs-actual for closing + open weeks (temp and
      drift joined from recentRuns detail) · records + best efforts ·
      trajectory triple with closing rate · efficiency/cadence tails with
      thin-sample caveats · today's readiness · staleness · integrity ·
      coach-log tail · profile constants
- [x] 5.2 Staleness notes: defensive pace-string parser pinned to the live
      plan's formats ("5:25–5:35", "~6:10", "5:41", "easy + 5:41";
      unparseable → skip silently); implied pace from best 84-day outdoor 10k
      (threshold intent) and the race block's goal pace (goal-pace intent);
      note beyond `STALENESS_TOLERANCE_S`
- [x] 5.3 Integrity warnings: `days:null` on a future week, week-header km ≠
      day sum (race-date day excluded per the plan's own convention), race
      date in the past
- [x] 5.4 Sync wiring: `briefing_step` renders to `DATA_DIR/coach-briefing.md`
      via temp-file + rename, strictly after the `garmin-data.js` write,
      inside `safe()` — failure is a warning only
- [x] 5.5 Tests: fixture-archive briefing (fixed section order, table content,
      temp/drift join, Riegel formatting, thin-sample caveat, warnings, log
      tail, byte-determinism), parser cases, staleness + integrity paths,
      renders whole without insights, atomic write leaves no temp files

## 6. Dashboard compliance marks (spec: live-dashboard)

- [x] 6.1 Day marks in THIS WEEK and selected block weeks from
      `compliance.days` joined by date — `.wk-comp` glyph (✓ ⇄ ◐ ✕) colored
      good/warn beside the day dot; the expanded day detail carries a Status
      row with the humanized reason and actuals
- [x] 6.2 Week-row aggregates from `compliance.weeks`: "32.4/32 km · 4/4
      runs" under the volume bar (neutral while the week is open, good/warn
      once closed); rows without compliance data render exactly as today
- [x] 6.3 Graceful absence: no `compliance` block → zero new surfaces, no
      errors (verified against the standalone demo fallback, which predates
      the block: 7 day cards + 7 week rows, zero marks)
- [x] 6.4 Visual check against real data: local sync + screenshots
      (splits-compliance-week.png: all 7 ✓ marks, Sunday expanded with
      "Status done: 16 km @ 6:54/km · HR 148"; splits-compliance-block.png:
      Wk 2 aggregate under the bar). A mid-check demo-data scare turned out
      to be the dc-loader resolving modules against a second test server's
      origin — framework quirk of the two-server test setup, not a bug

## 7. Seed plan philosophy flip (design D8)

- [x] 7.1 `plan-data.default.js`: every week's `days` detailed (sample
      content through taper + race day), header rewritten to the full-plan /
      adjust-don't-author rule, coach note mentions the compliance loop
- [x] 7.2 Test (`test_default_plan.mjs`): the shipped seed passes
      `validatePlanText`, every week fully detailed, headers match day sums
      (race day excluded)

## 8. The `/coach` skill (design D7)

- [x] 8.1 `.claude/skills/coach/SKILL.md` — one adaptive prompt encoding the
      ritual contract: read `coach-briefing.md` (data dir / repo symlink) +
      the live plan; discuss; on edit — validate the complete new text via
      `plan-io.mjs` `validatePlanText` before any write, write the resolved
      canonical file at home or instruct `pnpm plan:push` away, keep the
      week-km invariant, always append a dated `coach.log` entry; never touch
      `garmin-data.js`; offer block-building when future weeks are undetailed
- [x] 8.2 Dry-run done against the first real briefing: a genuine judgment
      (keep the 5:25–5:35 threshold targets despite the staleness note — the
      Jul 3 reps prove the speed) executed end-to-end: candidate → validate
      (ok, 7 weeks) → write canonical → post-validate → next compliance pass
      banked snapshot #2 while Wk 2 rows stayed on snapshot #1. The ritual
      needed nothing outside the briefing + plan

## 9. End-to-end verification

- [x] 9.1 Full test suite green — 11/11 files (5 Python, 6 node), including
      the two new suites and the schema-version assertions updated for v3
- [x] 9.2 Local real-sync smoke: v3 migrated on the local archive, snapshot
      banked, Wk 2 scored (7/7 done, 32.4/32 km), `compliance` block emitted
      + `validate_data.py` green on the merged contract, first real
      `coach-briefing.md` rendered (all sections; staleness notes fired on
      the threshold targets exactly as designed), dashboard shows the marks
- [x] 9.3 `COMPLIANCE_VERSION` bump rehearsal 1→2→1 on the real archive:
      rescored at each version against the same snapshot with statuses
      preserved, `--verify-archive` green after each step

## 10. Deploy to the homeserver

- [x] 10.1 Merged to `main` (b2a24ab + f3409f0) → CI images green; container
      pulled + recreated on the same volume (twice — see 10.2's finding)
- [x] 10.2 In-container sync: v3 migrated, snapshot banked, Wk 2 scored,
      compliance block + briefing emitted; `--verify-archive` exit 0;
      `validate_data.py` green against the canonical files (run through the
      LAN symlinks — in-container it can't resolve `/data`, a pre-existing
      limitation). Found + fixed en route: `mkstemp`'s 0600 + the root
      container published the briefing unreadable over the share →
      `write_briefing` now chmods 0644 before the rename (f3409f0)
- [x] 10.3 Live dashboard spot-check (fresh context, 192.168.0.37:5732):
      Wk 2 row reads 32.4/32 km · 4/4 runs, all seven day marks ✓, Sunday's
      status row "done: 16 km @ 6:54/km · HR 148"
      (splits-coachloop-live.png); demo fallback still renders mark-free
- [x] 10.4 First session against the server-generated briefing (read over
      the share, exactly as the ritual will): all sections populated; the
      coach-log section quotes back the "Coach loop live" judgment written
      through the ritual's own write contract earlier today — loop closure
      observed end-to-end. Review verdict: Wk 2 fully compliant, staleness
      notes already adjudicated (kept + logged), plan stands for Wk 3.
      Nothing found missing from the briefing
- [x] 10.5 After the next nightly sync (2026-07-06, combined with the
      stage-1/2 steady-state check): Wk 2 finalizes as the closed week
      against its frozen snapshot, Wk 3 opens with pending days, briefing
      refreshed, no new snapshot unless the plan changed — steady state
      confirmed
