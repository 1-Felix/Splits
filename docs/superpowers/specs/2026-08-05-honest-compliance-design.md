# SPLITS — Honest Compliance

**Date:** 2026-08-05
**Status:** Approved design, ready for implementation plan
**Goal:** Stop the compliance layer from marking an athlete down for a day he was never asked to
do, could never record, or completed in the unit the plan actually prescribed — without hiding a
single real miss from the coach.

---

## 1. Context

### The report

Max (brother, 23, beginner block toward a first half marathon, Health Connect instance at
`splits-max.mochii.dev`) reports that most of his runs and workouts show as *not fulfilled* or
*too short*, even when he follows the plan and completes the whole session.

### The measurement

His archive was read directly on the NUC (`docker compose exec splits-max`, read-only
`file:…?mode=ro`). **22 scored rows in `plan_compliance`; 10 of them are `missed`:**

| `planned_kind` | status | n |
|---|---|---|
| `rest` | **missed** | **6** |
| `strength` (Calf & Core, Mobility · Calves) | **missed** | **3** |
| `run` | missed | 1 |
| `run` | done | 4 |
| `run` | swapped | 1 |
| `run` | partial (`distance`) | 2 |
| `cross` / `rest` / `run` / `strength` | pending | 4 |
| — | unplanned | 1 |

**Nine of his ten ✕ marks are for days where nothing was required of him, or where nothing could
ever be recorded.** Exactly one genuine skipped run exists in the entire block: Mon 2026-07-20,
his first planned day.

His `/progress` headline reads **35% EXECUTED**. His true run adherence is **7 of 8 sessions**.

### The four defects

**A. A rest day is scored as a failure.** `_is_run_slot()` (`plan_compliance.py:159`) is false for
`kind: 'rest'` (`km` is `0.0`), so the day falls to the else branch, looks for an activity of kind
`rest`, never finds one — `kind_for_type()` (`:126`) cannot return `rest` — and is marked
**missed** (`:229`). A rest day is unsatisfiable by construction.

**B. Unrecordable work is scored as a failure.** The Health Connect bridge pushes *running*
sessions only. A `strength` or `cross` slot on Max's instance can therefore never be matched, and
lands **missed** every time. He does his calf & core in the living room; nothing on earth records
it.

**C. Time-prescribed sessions are scored in kilometres.** Thu 2026-07-30 is
`title: "2 × 10 min"`, `detail: "5 min walk wu · 10 min jog · 2 min walk · 10 min jog · 3 min walk
cd"`, `pace: "~8:00"`, `km: 3.4` — where the `km` is nothing but *20 min × the assumed 8:00 pace*.
`plan_prescription` refuses `"2×10/10 min jog"` (`_REPS_RE` needs the unit immediately after the
first number), so the day falls back to distance-only scoring and he loses a third of the credit
for running slower than an assumption nobody asked him to hold. Same shape on Sat 2026-08-01.

**D. An uncalibrated lens is quoted as if it had counted.** `interval_lens.work_floor()` returns
`None` below `WORK_FLOOR_MIN_SAMPLES = 20_000` (≈30 runs; `interval_lens.py:96`), so every one of
Max's 6 runs is banked `shape: "steady", calibrated: false` — the engine's own comment reads
*"Without a floor we cannot tell those apart, so we make no rep claim at all"* (`:1362-1364`).
`_quality_verdict()` (`plan_compliance.py:282`) ignores the flag and writes
`"0/8 reps, no structured set detected"` onto a session where he did all eight. `/run` already
respects `calibrated` (`run.dc.html:641`); the compliance layer does not.

### Why this was invisible

Felix's own instance has **zero** `rest` rows — his plan does not author rest days — and his Garmin
logs strength, so he sits at 13 strength-`done` / 3 `missed`. Every defect above requires a plan
with rest days *and* an athlete whose non-run work is not recorded. The author's instance has
neither.

### One hypothesis the data refuted

The Easy/Moderate HR ceiling (`EASY_HR_CEILING = 0.85` → 169 bpm against Max's measured 199 maxHR)
was the prime suspect before measurement. It has **never fired**: his avg HRs run 137–157. The rule
is left untouched.

---

## 2. Principle

> Never mark an athlete down for something he was not asked to do, could not record, or did in the
> unit the plan actually prescribed. Never hide a real miss from the coach.

Scoring gets fixed. The verdict vocabulary — `done` / `partial` / `missed` / `swapped` /
`unplanned` — stays: it is correct once it is applied to the right things, and every downstream
consumer keeps its shape.

---

## 3. Decisions

### D1 — A rest day is satisfied by resting

New status **`rest`**. A `kind: 'rest'` slot whose date has passed scores `rest`, never `missed`.

Rendered `✓ rest` in `var(--sub)` — deliberately *not* `var(--good)`. Resting on a rest day is
compliance, not an achievement, and colouring it green would make a week of pure rest look like a
week of training.

If the athlete runs on a rest day, the slot still reads `rest` and the run still appears as
`unplanned`. Both facts are true and neither is suppressed.

*Retires 6 of Max's 10 ✕.*

### D2 — A slot kind is scoreable only if this instance can see that kind

Capability is derived from the archive, never configured. A kind *K* is **tracked** on an instance
when it holds at least `TRACKED_MIN_ACTIVITIES = 2` activities mapping to *K* within
`TRACKED_WINDOW_DAYS = 90`.

- kind tracked, no evidence on the day → `missed` (today's behaviour, preserved)
- kind **not** tracked, no evidence → **`untracked`**, rendered `— not tracked` in `var(--sub)`,
  excluded from every count and every aggregate
- evidence present → scored normally, whatever the capability says

Two activities rather than one so a single stray log cannot condemn every subsequent day; a
trailing window rather than all-time so the answer tracks what the instance can *currently* see.

Self-healing in both directions. Felix's archive is thick with strength, so his 3 genuinely missed
strength days stay `missed`. Max's has never held one, so his read `untracked` — and on the day his
phone does start logging strength, strength days start scoring for him automatically, with no code
change and no config.

**Run slots are never `untracked`.** Running is the one kind every instance records; if it were not,
there would be no block to score.

**Purity constraint.** `score_week()` is documented pure and deterministic (`plan_compliance.py:193`)
and that must not change. The tracked-kind set is computed once by the caller from the archive and
passed **into** `score_week()`, exactly as `max_hr` and `snapshot_id` already are.

*Retires the remaining 3.*

### D3 — A time-prescribed day is scored on time

`plan_prescription` gains a duration reading beside its existing rep/steady grammar. The plan
already labels its own segments, so the parse is structural rather than heuristic:

```js
{ label: "Warm-up",   val: "5 min brisk walk" }
{ label: "Blocks",    val: "2×10/10 min jog", rest: "2 min walk between" }
{ label: "Cool-down", val: "3 min walk" }
```

`planned_work_s` = the sum of minute/second tokens across segments, **excluding any segment
labelled warm-up or cool-down**. A rep segment contributes its work *and* the recoveries that fall
between reps — never a trailing one:

```
segment_s = count × rep_s + (count − 1) × rest_s
```

so `"2×10/10 min jog"` with `rest: "2 min walk between"` yields 2 × 10 + 1 × 2 = **22 min**, and a
plain segment contributes its own duration. A segment carrying no readable duration makes the
whole day unreadable, and the day falls back to km — partial arithmetic is never attempted.

Excluding the walk warm-up and cool-down is the load-bearing call. They are not the session, and in
practice they are not even recorded — the watch starts when the running starts. That gap *is* the
discrepancy: 22 prescribed core minutes against a recorded 23 is a completed session; 30 nominal
minutes against a recorded 23 is a fabricated shortfall.

When `planned_work_s` resolves, the day is scored on the activity's `duration_s` against it, using
the existing `DIST_DONE_RATIO` / `DIST_PARTIAL_RATIO` thresholds unchanged (0.85 / 0.50) and
carrying `reason: "duration"` instead of `"distance"`. Otherwise the day keeps today's km scoring
exactly.

| day | today | scored on time |
|---|---|---|
| Thu 30 Jul `2 × 10 min` | 2.4 / 3.4 km = 71% → **partial** | 23 / 22 min = 105% → **done** |
| Sat 1 Aug `Long · 2 × 12 min` | 3.0 / 3.9 km = 77% → **partial** | ≈28 / 26 min → **done** |

**Refusal stays the safe state**, matching the module's existing contract: an unparseable day falls
back to distance scoring rather than guessing. The grammar is pinned the same way the existing one
is — `tests/fixtures/plan_vals.json` today holds 29 distinct `val` strings, each mapped to its
exact parse or to `null` for an explicit refusal, and a currency test fails when a live plan
introduces a string the fixture does not pin. Every string in that fixture comes from **Felix's**
plan, which is entirely km-based; the fixture is extended with Max's distinct segment strings (the
minute forms) and gains the duration expectation alongside the existing one.

`_acts_for_range()` already selects `duration_s` and discards it after computing pace; it now
carries it through.

### D4 — The swap pass runs mid-week

The swap pass that rescues "I ran it Wednesday instead of Tuesday" runs only when
`week["sun"] < today` (`plan_compliance.py:238`). Until the week closes, a shifted run therefore
shows `✕ missed` on the planned day **and** `+ unplanned` on the day it happened — for up to six
days, twice punished for one completed session.

It now runs over the past days of the open week too. Safe by construction: every sync rescores the
whole week from scratch and replaces its rows wholesale (`replace_compliance_week`), so a
provisional pairing is never sticky and self-corrects as the week fills in.

### D5 — An uncalibrated lens makes no rep claim

`_quality_verdict()` reads `doc["calibrated"]`. When false it emits
`"reps not verifiable — the interval lens needs ~30 runs of history"` and sets `found: null`.
Never `0/8`. Steady and distance verdicts are unaffected; a calibrated document behaves exactly as
today.

This adds no new judgement — it propagates a distinction the lens already draws and `/run` already
honours.

### D6 — `percentExecuted` counts work that was required and visible

`block_lens.py` currently admits every non-pending planned day to the denominator
(`if r["planned_kind"] is not None and r["status"] != "pending"`, `:190`), so Max's rest days are
counted as failed days. The denominator excludes `rest`, `untracked` and `pending`; `_STATUSES`
(`:139`) gains the two new values so the counts dict stays complete.

Max's headline moves **35% → 88%** (7 of 8 sessions). `PARTIAL_CREDIT = 0.5` is unchanged.

`var(--warn)` amber is reserved for `missed` and `partial` on a slot that was both **required** and
**trackable**.

### D7 — The coach still gets the whole truth

`coach_briefing.py` gains an explicit line naming what is unverifiable on this instance — e.g.
*"strength/mobility days are not tracked on this instance; 4 such days this block"* — so the AI
coach can never read silence as compliance.

Nothing is concealed from the coach. It simply stops being **shouted at the athlete**.

---

## 4. Contract changes

### Statuses

`done` · `swapped` · `partial` · `missed` · `unplanned` · `pending` · **`rest`** · **`untracked`**

`plan_compliance.status` is `TEXT NOT NULL` with no CHECK constraint (`activity_archive.py:140`),
so the new values need **no schema migration**.

### Reasons

| reason | word |
|---|---|
| `distance` | shorter than planned *(unchanged)* |
| `duration` | **shorter than the prescribed time** *(new)* |
| `intensity` | ran too hard for the intent *(unchanged)* |

### New columns

`planned_s` and `actual_s`, both nullable, added through the existing
add-column-if-missing pattern (`activity_archive.py:393`, precedent: `quality_json`) and appended
to `_COMPLIANCE_COLS`. Populated only for time-scored days; surfaced in the `compliance` block as
`plannedS` / `actualS` so `/run`, the cockpit and The Block can render *"2.4 km · 23 min"* without
reconstructing duration from `actualKm × actualPaceS`.

### Version

`COMPLIANCE_VERSION` **3 → 4**. `_rescore_stale()` then rescores every frozen week against its
*original* snapshot on the next sync — Max's whole history heals itself, with no manual step and
no risk of a later plan edit rewriting history (design D2 of the original coach-loop).

### Glyphs

Three maps gain the two statuses, identically:

| file | line |
|---|---|
| `Running Dashboard.dc.html` | 1015 |
| `progress.dc.html` | 651 |
| `run.dc.html` | 423 |

```
rest:      { t: '✓', fg: 'var(--sub)', word: 'rest' }
untracked: { t: '—', fg: 'var(--sub)', word: 'not tracked' }
```

The approved day-row reading, on Max's real Wk 2:

```
WK 2 · 27 Jul – 2 Aug                    3/3 runs · 8.0 km

Mon  Run/Walk 2:1        3.0 km    ⇄ done (ran Tue)   2.6 km @ 9:05
Tue  Rest                —         ✓ rest
Wed  Calf & Core         —         — not tracked
Thu  2 × 10 min          20 min    ✓ done             2.4 km · 23 min
Fri  Rest                —         ✓ rest
Sat  Long · 2 × 12 min   24 min    ✓ done             3.0 km · 28 min
Sun  Mobility · Calves   —         — not tracked
```

---

## 5. Blast radius

| file | change |
|---|---|
| `plan_compliance.py` | `rest` + `untracked` statuses, tracked-kind parameter, duration scoring, mid-week swap, `calibrated`-aware quality verdict, `VERSION` 4 |
| `plan_prescription.py` | minute/second duration reading with warm-up/cool-down exclusion |
| `activity_archive.py` | `planned_s` / `actual_s` columns (schema v15) |
| `validate_data.py` | `_COMPLIANCE_STATUSES`, the `plannedKind` and `reason` whitelists, numeric `plannedS` / `actualS` — **widened first**, before any producer emits the new vocabulary, or the first sync after deploy fails validation on its own output |
| `block_lens.py` | `_STATUSES`, `percentExecuted` denominator |
| `coach_briefing.py` | status wording, unverifiable-days line |
| 3 × `.dc.html` | glyph maps, reason words, duration in the actual column |

No schema version bump (columns are added by the existing if-missing pattern). No data migration.
No change to the sync, the ingest bridge, the lens engines, or the plan files.

---

## 6. Testing

**TDD, per the repo's standing practice.** Every decision above lands as a failing test first.

- `test_plan_compliance.py` — a past rest slot is `rest`, never `missed`; an untracked kind with no
  evidence is `untracked`; a *tracked* kind with no evidence is still `missed`; evidence scores
  normally regardless of capability; a time-shaped day is scored on work minutes with warm-up and
  cool-down excluded; an unparseable day falls back to km; the swap pass rescues a shifted run
  inside the open week; `plannedS` / `actualS` reach the contract.
- `test_plan_prescription.py` — a corpus fixture over the distinct segment strings in **both** live
  plans: every string either yields an exact duration or is explicitly refused, and a new string in
  a live plan fails the currency test.
- `test_block_lens.py` — `rest` / `untracked` are absent from the `percentExecuted` denominator and
  present in `counts`.
- `test_coach_briefing.py` — the unverifiable-days line appears when a kind is untracked and is
  absent when it is not.
- `test_run_page.mjs` + the progress/cockpit render tests — both new glyphs, and the duration
  reading in the actual column.
- **Real-data regression.** Rescore both archives under v4 from consistent NUC snapshots and assert:
  Max → 88% executed, exactly 1 `missed`, 0 `partial`; Felix → his 3 strength `missed` unchanged,
  his 1 `partial` unchanged, `percentExecuted` moves only where a decision above intends it.

**Verification before completion:** deploy to the NUC, `--verify-archive` green on both containers,
and both dashboards read correctly in a browser. Evidence before assertions.

---

## 7. Out of scope

- **A self-report tick for untracked days.** Considered and declined in favour of the neutral mark:
  it needs a write path, auth, storage and conflict handling on pages that are read-only today.
  Revisit if the neutral mark proves unsatisfying in use.
- **Inferring reps from the speed stream, or lowering `WORK_FLOOR_MIN_SAMPLES`.** The floor exists
  because an uncalibrated percentile is noise. D5 makes the lens's silence legible; it does not try
  to break the silence.
- **The Easy HR ceiling.** Measured, never fires for Max, left alone.
- **The Wk 16 → 17 volume seam** (11.5 → 19.5 km) in Max's plan. A plan-content question for a
  coaching session, not a compliance question.
- **Any change to the ingest bridge, the sync, or the lens engines.**

---

## 8. Risks

| Risk | Mitigation |
|---|---|
| `TRACKED_MIN_ACTIVITIES` / `TRACKED_WINDOW_DAYS` (2 / 90 d) are judgement calls | The number most likely to want revisiting. Compliance rows are a disposable cache: changing it and bumping `COMPLIANCE_VERSION` re-heals all history, so it is cheap to correct. Both values are named constants beside the existing scoring constants. |
| A sliding capability window makes a frozen week's score time-dependent | Frozen weeks are only rescored on a version bump or the nightly last-closed-week pass, so drift is bounded and always recomputed from the archive of record. `score_week()` stays pure — the set is computed by the caller and passed in. |
| The minute grammar leans on the plan generator's segment labels staying well-formed | Refusal is the safe state (falls back to km, i.e. today's behaviour), and the corpus fixture fails loudly the moment a live plan introduces unpinned notation. |
| Excluding warm-up/cool-down could over-credit a genuinely cut-short session | The 0.85 / 0.50 thresholds still apply to the *core* minutes; a session that skips half the blocks still lands `partial` or `missed`. |
| `rest` in `var(--sub)` might read as "nothing happened" rather than "correct" | The word `rest` carries it, and green would be worse — a week of pure rest must not look like a week of training. Re-tune after Max sees it. |
| Two new statuses reaching an un-updated consumer | Every glyph map falls back to `pending` (`BLOCK_GLYPH[d.status] || BLOCK_GLYPH.pending`), so an unhandled status degrades to a neutral dot rather than breaking a page. The three maps are updated together and covered by render tests. |
| Max's `percentExecuted` jumping 35 → 88 looks like a fudge | It is the same arithmetic over a corrected denominator, and the one real miss stays visible. The briefing states what is unverifiable, so the coach reads the change as a correction, not a grade inflation. |
