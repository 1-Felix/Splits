# Design: coach-loop

## Context

Stages 1–3 of the roadmap left a nearly-closed loop: the archive holds every
activity, `insight_metrics.py` turns it into progress verdicts, the dashboard
renders both, and the plan is fully detailed to race day under the standing
rule that coaching *adjusts* the plan from actuals (ROADMAP stage 4 decisions,
2026-07-05). What remains manual is the join: comparing planned days to
archived actuals, and assembling the state a coaching session needs.

Constraints carried forward unchanged:

- **No agent API.** The AI coach runs only as Claude Code sessions on the
  subscription; everything quantitative is deterministic Python in the sync.
- **The golden rule.** The dashboard imports merged data files and talks to no
  API; it must stay fully functional if `/coach` is never run and if any new
  sync step fails (fail-soft, `garmin-data.js` always written).
- **Two-writer discipline.** The sync owns `garmin-data.js`; the coach owns
  `plan-data.js`. This change makes the sync *read* the plan but never write it.
- **Runtimes.** The container ships Python 3.12 + the node binary; the
  homeserver volume is the canonical data dir; Felix edits the plan through a
  symlink at home and `plan:push` away.

The briefing contents were specced empirically: the 2026-07-05 hand-run of the
ritual recorded exactly what a session reaches for (per-day plan-vs-actual,
records/best efforts, trajectory triple with closing rate, efficiency/cadence
tails with sample-size caveats, readiness, coach-log tail, profile constants,
days-to-race arithmetic).

## Goals / Non-Goals

**Goals:** deterministic plan-vs-actual compliance in the nightly sync; honest
compliance history that plan edits cannot rewrite; a generated
`coach-briefing.md` containing everything the hand-run reached for; a `/coach`
skill that makes the ritual one command; per-day compliance marks on the
dashboard.

**Non-Goals:** AI-computed numbers in the sync; automated plan edits without a
human in the session; multi-page progress views (stage 3); training-theory
sophistication in scoring (TSS models, zone-time targets per session) — the
deterministic layer stays coarse and the AI supplies judgment; away-mode push
automation inside the skill.

## Decisions

### D1 — Plan ingestion: a node child dumps the plan to JSON
`tools/plan-dump.mjs` imports the plan file (path argument) and prints
`JSON.stringify(planData)`. Python invokes it via `subprocess.run` with a
kill-timeout and a minimal environment (the `plan-io.mjs` validator's
allow-list approach), parses stdout, and on any failure — nonzero exit,
timeout, unparseable output — skips compliance and briefing for this sync with
a warning. The trust model is plan-sync D4's: whoever can edit the volume file
already owns the deployment.

*Implementation note:* the dump runs against a temp `.mjs` copy of the plan
text, not the live path — the data volume has no `package.json`, so node
would parse a bare `.js` path there as CommonJS and reject the `export`
(the same reason `plan-io.mjs` validates via a `.mjs` temp file).
- **Alternative rejected:** parsing JS with regex/ast in Python — fragile
  against a coach-owned file that is deliberately free-form prose + code.
- **Alternative rejected:** a JSON mirror written by the server on plan writes
  — misses direct symlink/volume edits, the 90% path at home.

### D2 — Snapshots: content-hash-deduped full-plan rows, append-only
Schema v3 adds `plan_snapshots(id, sha256 UNIQUE, first_seen_date, plan_json)`.
Each sync dumps the plan, hashes the raw file text, and inserts a row only when
the hash is new. Compliance rows carry `snapshot_id` = the snapshot current at
scoring time. History is therefore immutable-by-construction: editing the plan
creates a new snapshot; already-scored days keep pointing at the plan they were
actually measured against, and a `compliance_version` bump recomputes rows
against their *original* snapshots.
- **Alternative rejected:** per-week or per-day snapshots — more rows and
  bookkeeping for no benefit; the whole plan file is ~10 KB.
- **Alternative rejected:** no snapshots — a Thursday repricing would silently
  rewrite what Monday was scored against (explicitly ruled out in the roadmap).

### D3 — Matcher: date+kind first, swaps at week close, plan is the intent
Garmin activities map to plan kinds (`running` → `run`, strength →
`strength`, cycling/indoor-cycling → `cross`). Per scored week:

1. Same date + same kind → **matched** (several same-day actuals: the largest
   by distance takes the planned slot; the rest become unplanned candidates).
   **Hybrid days** — cross/strength days carrying planned running km (the live
   plan's "Spin + Easy Run" Mondays) — are scored on their *run* component;
   same-day activities of the day's own kind are absorbed silently so the spin
   never surfaces as noise.
2. At week close, a second pass pairs missed run slots with leftover same-week
   runs **globally by date proximity** (ties: earlier actual, then earlier
   planned day — day-order assignment would let a far slot steal a nearer
   slot's run) → **swapped**, scored against the planned day's targets. A run
   under half the slot's km never pairs.
3. Leftover actual **runs** → **unplanned** (extra rides and strength sessions
   are life, not noise); planned days past their date with no match →
   **missed** (provisional inside an open week — a swap can still rescue them
   at close); future days → **pending**.

The sync recomputes the open week (against the current snapshot — midweek plan
edits legitimately change open targets) and the last closed week every night.
A closed week's targets **freeze at its first post-close scoring**: the
nightly rescore exists only to catch late-syncing activities and reuses the
snapshot its rows already reference. Older weeks are frozen unless the version
bumps. Intent (kind, load, zone, km) always comes from the snapshot — never
re-derived from the activity, so the matcher can't disagree with the plan
about what a session was for.

### D4 — Scoring: coarse, with a reason, judgment left to the coach
Runs: distance ratio ≥ 85% of planned km *and* intensity consistent → `done`;
ratio ≥ 50% but < 85%, or intensity inconsistent → `partial` with a machine
`reason` (`distance` | `intensity`); ratio < 50% → `missed`. Intensity is
checked only for Easy/Moderate-intent runs (avg HR > 85% of max → inconsistent)
— Hard sessions are scored on distance alone, because judging rep quality
deterministically would rebuild training theory in Python. Strength/cross days:
presence of a matching activity → `done`, absence → `missed`, never `partial`.
The briefing carries temperature and drift next to every intensity flag so the
coach can excuse a hot day; the deterministic layer reports, the AI judges.
- **Alternative rejected:** parsing segment strings ("4×1 km @ 5:25–5:35") for
  rep-level scoring — brittle against coach-authored prose, and the hand-run
  showed coarse day-level status is what the ritual actually consumes.

### D5 — Contract: a top-level `compliance` block, independent of `insights`
`garmin-data.js` gains `compliance: { complianceVersion, days: [...], weeks:
[...] }` covering the block's date range up to today — per-day: date, planned
kind/km/load/title, status, reason, actual km/pace/HR when matched; per-week:
planned vs actual km and runs done/planned. It is emitted in the same
all-or-nothing fashion as `insights` but in a **separate fail domain**: a plan
problem drops `compliance` while `insights` survives, and vice versa.
`validate_data.py` checks the shape when the block is present.
- **Alternative rejected:** nesting under `insights` — couples two failure
  modes that have nothing to do with each other (archive/metrics vs plan file).

### D6 — Briefing: deterministic markdown, atomic write, generated last
`coach_briefing.py` renders `coach-briefing.md` into the data dir from already-
computed inputs (compliance rows, `insights`, readiness, plan JSON, coach-log
tail, profile) — fixed section order, pre-formatted numbers, no AI. It includes
the two derived signal sections: **staleness notes** (quality-session pace
targets parsed defensively from the plan's `pace` strings and compared to
fitness-implied paces — best 12-week 10k effort for threshold work, the race
block's goal pace for goal-pace work; unparseable strings are skipped
silently; deviation beyond a tolerance emits a note) and **integrity warnings**
(`days:null` on a future week, week-header km ≠ days sum, race-date drift).
The briefing is written by temp-file + rename *after* `garmin-data.js`
succeeds; its failure can never affect the contract file.
Step order in the sync: `archive → metrics → compliance → build/write
garmin-data.js → briefing → wellness`.

### D7 — `/coach`: a repo skill wrapping the ritual with hard guardrails
`.claude/skills/coach/SKILL.md`, one adaptive prompt. The contract: read
`coach-briefing.md` + the live plan; discuss; when editing the plan — validate
the complete new text with `plan-io.mjs`'s `validatePlanText` (node one-liner)
*before* writing, resolve the symlink and write the canonical file (home) or
instruct `pnpm plan:push` (away), keep the week-km invariant, and **always**
append a dated `coach.log` entry describing what changed and why. If future
weeks are undetailed it offers block-building; otherwise review-and-adjust.
It never touches `garmin-data.js` and never writes without validation passing.

### D8 — Seed plan flips to the shipped philosophy
`plan-data.default.js` gets every week detailed and its header rewritten to the
adjust-don't-author rule, so a fresh deployment starts in the state the loop
assumes. Entrypoint seeding behavior is unchanged.

## Risks / Trade-offs

- **[Plan file is arbitrary JS executed by the dump child]** → same mitigations
  and trust model as plan-sync D4: minimal env allow-list, kill-timeout,
  volume-owner ≈ deployment-owner. The child only ever *prints JSON*.
- **[Unrecorded sessions score as missed]** (e.g., a spin class without a
  Garmin activity) → statuses stay honest to the data; the `reason` field and
  briefing context let the coach excuse them. If it becomes chronic noise, a
  plan-side `untracked: true` day flag is a cheap later addition.
- **[Heat makes easy-run intensity flags unfair]** → by design: the flag is
  reported with temp/drift alongside; judgment lives in the session, not
  Python (the Jul 5 hand-run showed exactly this pattern working).
- **[Pace-string parsing drifts from coach authoring habits]** → the parser is
  defensive and skip-on-fail; staleness notes silently thin out rather than
  erroring. Tests pin the formats currently in the live plan.
- **[Schema v3 on the live DB]** → additive tables only, same migration
  pattern as v2; `--verify-archive` extends to snapshot/compliance coverage;
  rollback = revert image (new tables are inert to old code).
- **[Provisional `missed` inside an open week may flip to `swapped`]** → the
  dashboard renders the current status without promising finality; the weekly
  ritual reads the *closed* week, where statuses are final.

## Migration Plan

1. Ship code; the first nightly sync migrates the archive to schema v3, banks
   the first snapshot, scores the open + last closed week, emits `compliance`,
   and writes the first `coach-briefing.md`.
2. Dashboard change is pure rendering; it activates when the block appears and
   is inert against older data files.
3. Verify on the homeserver: `--verify-archive` (v3 coverage), `validate_data.py`
   (contract), then a first real `/coach` session against the generated
   briefing.
4. Rollback: revert the image — additive tables and the briefing file are
   harmless leftovers; the dashboard degrades gracefully without the block.

## Open Questions

None blocking. Tolerance constants (85%/50% distance bands, 85%-of-max HR
ceiling, 10 s/km staleness threshold) are named module constants settled
during implementation with tests; the weekly aggregate shown on block rows
(km vs sessions) is a rendering choice deferred to the dashboard task.
