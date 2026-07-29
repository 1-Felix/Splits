# The coach loop runs on the ingest path too — design

**Date:** 2026-07-29
**Follows:** `openspec/changes/archive/2026-07-17-add-ingest-archive/` (which banked
the archive on ingest instances but deliberately left the coach loop out of scope)
**Found by:** the first real `/coach` session against Max's instance, 2026-07-29.

---

## 1. The defect

An ingest-fed instance banks everything the coach loop needs and derives none of
it. `ingest_builder.main()` writes `garmin-data.js` and the archive, then stops.
Four things `sync_garmin` does after its archive step have no counterpart:

| Step | Garmin path | Ingest path |
|---|---|---|
| plan snapshot + compliance scoring | `compliance_step()` | — |
| block lens rows | `block_lens_step()` | — |
| `insights` / `compliance` / `blockLens` keys in the telemetry | `fetch_*()` in `build_data` | — |
| `coach-briefing.md` | `briefing_step()` | — |

Measured on Max's live instance, 2026-07-29, before this change:

```
run_metrics      7      ← banked, unused
race_predictions 0
plan_snapshots   0
plan_compliance  0
block_lens       0
```

Consequences, all visible:

- **`/coach` has no state of record.** There is no `coach-briefing.md` on the
  volume at all — `coach_briefing.render_briefing` is only ever called from
  `sync_garmin.briefing_step`. The ritual's step 1 ("read the briefing") cannot
  be performed; this session had to hand-render it through `docker exec`.
- **The dashboard shows no compliance marks and no Block report.** Both read
  from the empty tables above.
- **Three briefing sections print `insights unavailable this sync`** — Records &
  best efforts, Trajectory, Progress trends. This one is pure omission:
  `insight_metrics.assemble_insights(conn, today)` *already returns a valid
  block* against Max's archive today (verified 2026-07-29: `bestEfforts`,
  `recordsFeed`, `efficiency`, `cadence` all assemble). Nothing is missing but
  the call.

`ingest_builder.py` line ~635 already names the first half of this as a
follow-up: *"plan_snapshots/plan_compliance rows … Worth its own change."* This
is that change, widened by what the `/coach` session found.

### 1.1 Two defects found while measuring, folded in

**`insight_metrics.GOAL_HALF_S = 7199` is hardcoded to one athlete's goal.**
The trajectory block measures every instance against sub-2:00. Max's goal is
2:29:59. Felix's plan currently reads `goalTime: "1:59:59"`, so today the
constant happens to be right for him and wrong for his brother — and it would
go wrong for him too the day he re-anchors his goal in the plan.

**`ingest_builder._plan_goal` scrapes `plan-data.js` with a regex.** It has
already produced a silent `null` once (`halfGoal` on Max's instance, fixed
2026-07-17 by widening the pattern). Once this change loads the plan properly
it should stop guessing.

---

## 2. Decisions

### D1 — one module, called by both pipelines

New `coach_pass.py` owns the derive-and-render steps. `sync_garmin` and
`ingest_builder` both call it; neither owns a private copy.

```python
derive(conn, plan_raw, plan, today, max_hr, log)  -> stats   # writes the archive
attach_blocks(conn, plan, today, data, log)       -> [keys]  # writes into the telemetry
briefing(conn, plan, data, today, path, log)      -> bool    # writes coach-briefing.md
```

This follows the rule the codebase already applies to anything two producers
must agree on: `interval_lens.zone_bounds` exists once so the two producers
cannot drift on what "Z4" means (its own docstring says so), and
`ingest_builder._calibration` exists once so the cockpit and the archive cannot
disagree on `max_hr`. Compliance scoring is the same class of thing: it decides
what the dashboard *says about the athlete's week*. Two copies of it is how the
two instances start disagreeing.

The rejected alternative was inlining the four step bodies into
`ingest_builder.main()` — smaller diff, no risk to the working nightly sync, but
~60 lines of near-identical open-conn/load-plan/call-engine/log duplicated into
the file that is hardest to keep in step.

A third alternative — a separate pass spawned by `serve.mjs` after the build —
does not work for the data blocks: `insights`, `compliance` and `blockLens` live
*inside* `garmin-data.js`, so a second pass would have to rewrite the file the
builder just atomically published, breaking the single-write property.

### D2 — `log` is a parameter, not a global

Each entry point takes a `log` callable. `sync_garmin` passes its `log()`;
`ingest_builder` passes a `print`-based one. This is the pattern
`course_lens.course_step(conn, client, race, log=log)` already established, and
it keeps each pipeline's output format its own.

### D3 — the ingest build inverts its order

Compliance and insights are read *from* the archive, so the archive must be
current before them, and the derived blocks must exist before the telemetry file
is written:

```
dedupe → calibration → build_archive → derive → build_athlete_data
       → attach_blocks → write garmin-data.js → briefing
```

Today the order is the reverse (telemetry first, archive last).

### D4 — the reorder must not cost the telemetry guarantee

Today `garmin-data.js` is written *before* the archive pass, so an archive
failure cannot stop it landing. That guarantee is load-bearing — it is why the
current code wraps the archive in a bare `except` with the note *"the archive is
a derived cache; a failure here must never sink the telemetry build"*.

After the reorder it is preserved differently:

- `build_archive` and `derive` are fail-soft; a raise is logged and skipped.
- `build_athlete_data` and the atomic write happen **unconditionally** afterward.
- `attach_blocks` fail-domains **per key**: an exception assembling one block
  omits that key and leaves the others (mirrors `sync_garmin`'s `safe()`
  discipline, where insights, compliance, block lens and course lens are each
  independent).
- `briefing` runs strictly **after** the write, so it can never affect the
  contract file — the rule `briefing_step` already states.

Worst case, the file lands exactly as it does today, minus the new keys.

### D5 — `goal_sec` comes from the plan

`assemble_insights(conn, today, goal_sec=None)` — `None` keeps `GOAL_HALF_S` as
the fallback. Both callers pass `race.goalTime` parsed by the existing
`block_lens.parse_goal_seconds` (no third copy of a time parser). For Felix's
current plan this resolves to 7199 and changes nothing.

### D6 — the ingest path banks its own predictions, labelled

`race_predictions` is empty on ingest instances, so `trajectory.weekly` is `[]`
and the goal-gap trend would stay empty forever. The builder banks its
Riegel estimate each build through
`activity_archive.upsert_race_prediction(conn, date, promoted, raw, "riegel")` —
the table already carries a `source` column (`"sync"` for Garmin's predictor),
so the provenance is recorded rather than laundered. One row per build day,
building the line forward from today. It will read "insufficient data" for the
first weeks, which is the correct thing for it to say.

`insight_metrics.bank_prediction` is left alone; it is Garmin-document-shaped
and the ingest path has no such document.

### D7 — `_plan_goal`'s regex is retired

`derive` needs the parsed plan anyway (`plan_compliance.load_plan`), so
`predictions.halfGoal` reads `race.goalTime` off that object and the regex scrape
in `ingest_builder._plan_goal` is deleted. One plan load per build, one source of
the goal — the same value D5 hands to the trajectory.

---

## 3. What changes on screen

**Max's dashboard** gains per-day compliance marks, The Block section, the
records feed, and the efficiency/cadence trends. **`/coach`** gains a real
briefing on his volume.

**Felix's dashboard must not change at all.** See §5.

### 3.1 Scoring a plan that has no history

`plan_snapshots` is append-only and content-deduped so a later plan edit can
never rewrite what a past day was scored against. Max's instance has *no*
snapshots, so that protection has nothing to protect: the first run of this
change scores every past week against the plan **as it reads today**.

Concretely, from the 2026-07-29 coaching pass: Wk 1 was not edited and scores
cleanly, but Wk 2 was rewritten that afternoon. Max's real Tuesday run now falls
on a day the plan calls `Rest`, so it scores as an *unplanned run* row (the
engine's `leftover_runs` path, `planned_kind: None`), and Monday's untouched
planned run scores as missed. That is honest, and it is a one-time artefact of
turning the loop on mid-week. It is not worth backfilling synthetic snapshots to
hide — see §6.

---

## 4. Interface detail

```python
# coach_pass.py

def derive(conn, plan_raw, plan, today, max_hr, log=_noop) -> dict:
    """Bank today's plan snapshot, rescore compliance, refresh block-lens rows.
    Returns {'weeks_scored', 'weeks_healed', 'blocks', 'recomputed'}."""

def attach_blocks(conn, plan, today, data, log=_noop) -> list[str]:
    """Assemble every archive-derived block into `data` — insights, compliance,
    blockLens, courseLens — and fill predictions.trend from the trajectory.
    Each block is an independent fail domain. Returns the keys attached."""

def briefing(conn, plan, data, today, path, log=_noop) -> bool:
    """Render and atomically publish coach-briefing.md. False when the plan is
    unreadable (the caller has already logged why)."""
```

`max_hr` is passed in, never re-read from the environment: the ingest path must
score against the **calibrated** value `_calibration()` produced for that same
build, not `int(os.getenv("ATHLETE_MAX_HR", "197"))`. On Max's instance those
two differed by 25 bpm as recently as this morning.

On the Garmin side: `compliance_step`, `block_lens_step` and `briefing_step`
become thin wrappers that open the connection and delegate; the four `fetch_*`
helpers are **deleted**, and `build_data`'s four separate calls (plus its
`trend_verdict` line) collapse into one `attach_blocks`. Bodies move verbatim
into `coach_pass`.

---

## 5. Testing

**Parity is the acceptance test.** The extraction must leave Felix's
`garmin-data.js` byte-identical for the same inputs. This is the one way the
change could quietly damage the instance that already works, and a
looks-harmless diff is not evidence. Note the `fetch_*` helpers each open their
own archive connection today; `attach_blocks` uses one for all four assemblies.
That is strictly better and it is a behaviour change, which is exactly why
parity gets asserted rather than assumed.

New `test_coach_pass.py`:

- `derive` banks a snapshot and scores the weeks it should;
- an assembly that raises omits **only** its own key from `data`;
- `briefing` publishes atomically (temp file + rename, 0644);
- `goal_sec` reaches the trajectory from `race.goalTime`, and an absent/garbage
  `goalTime` falls back to `GOAL_HALF_S`.

Extended `test_ingest_builder.py`:

- after `main()`, the telemetry carries `compliance`, `blockLens`, `insights`
  and `coach-briefing.md` exists on the volume;
- **fail-soft, plan**: an unparseable `plan-data.js` still yields telemetry;
- **fail-soft, archive**: an archive that raises still yields telemetry;
- a banked prediction row appears with `source = "riegel"`.

Regression net, must stay green untouched: `test_plan_compliance.py`,
`test_block_lens.py`, `test_coach_briefing.py`, `test_activity_archive.py`, and
the `.mjs` ingest suites (`test_ingest_api`, `test_ingest_e2e`,
`test_build_watchdog`).

### 5.1 The watchdog budget

`serve.mjs` kills a builder after `SPLITS_BUILD_TIMEOUT_S` (120 s default). This
change adds one Node subprocess spawn per build (`plan_compliance.load_plan`
dumps the plan through `node`, ~300 ms) plus scoring, lens derivation, four
assemblies and a render. On Felix's 165-run archive the same work already fits
inside the nightly sync, so the budget is not at risk — but it does lengthen the
window in which a killed builder is still holding the archive db, which the
`test_build_watchdog.mjs` settle-on-close fix exists to cover. That test stays
in the net.

---

## 6. Not in scope

- **No daily rebuild tick.** `triggerBuild()` fires on ingest POST and on boot
  only, so on a day with no push, `today`, the this-week zone split, the heatmap
  and the briefing's date all age in place. The `/coach` freshness gate is
  designed to catch exactly this and offer a rebuild. A `BUILD_AT` scheduler is
  a separate change.
- **No wellness on ingest instances.** No readiness, HRV, sleep or VO2max —
  design D7 of the ingest-archive change stands; Health Connect gives us none of
  it.
- **No backfill of historical plan snapshots.** Weeks before today score against
  the current plan (§3.1). Synthesising snapshots for weeks nobody snapshotted
  would be inventing a record, which is worse than an honest artefact.
- **No change to `bank_prediction`** or to how the Garmin path banks its
  predictor document.

---

## 7. Rollout

1. Extract `coach_pass.py`, rewire `sync_garmin`, assert parity — Felix's
   instance must be provably unchanged before the ingest path is touched.
2. Reorder `ingest_builder.main()` behind its fail-soft guarantees (D4).
3. Deploy to the NUC; verify on `splits-max` that the five tables fill, the
   cockpit shows compliance marks and The Block, and `coach-briefing.md` renders
   with its Plan-vs-actual, Block report and insights sections populated.
4. Verify on `splits` that the nightly sync still produces identical telemetry.
