# The Workout Step Decides What Is A Rep — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop counting warmups, cooldowns and manual laps as interval reps by trusting Garmin's workout-step index, and finish the two Priority-1 rep-card items from the interval-lens handoff.

**Architecture:** `interval_lens.py` gains one filter that decides which lap-derived work segments are genuine reps, replacing the size-only floor from the previous change. Everything else follows from it: a block minimum on the lap path, GAP taken from the device rather than windowed off the stream, and one consistent basis (raw) for the reported spread and fade on both producers. The frontend changes are two small edits to `run.dc.html`. `INTERVAL_VERSION` bumps 3 → 4 and the next sync recomputes every document.

**Tech Stack:** Python 3 (stdlib only, `pytest`), Node `serve.mjs`, `.dc.html` templates rendered by the in-repo chart/view engine, SQLite archive, Docker on the NUC.

**Spec:** `docs/superpowers/specs/2026-07-28-interval-lens-workout-steps-design.md`

## Global Constraints

- **`interval_lens.py` never opens a database.** Callers supply `work_floor`, `bounds`, `laps`. Keep it that way.
- **One engine, two producers.** `sync_garmin.py` and `ingest_builder.py` both call `build_document()`. Any rule added here must not make the two paths read a run by different definitions unless the spec says so explicitly.
- **Lap segments are never deleted, only re-roled.** `segments_from_laps` guarantees each segment's `t0/t1/d0/d1` chains to the next with no gap; `_quality`'s summation and the rep-shaded stream chart both depend on that. Demotion sets `role` to `warmup` / `cooldown` / `recovery` and drops `rep`.
- **Detection stays on the grade-adjusted signal** (design D5). This change alters reporting only.
- **`INTERVAL_VERSION` must end at 4.** Bump it exactly once, in Task 7.
- **Existing constants, verbatim:** `WORK_MIN_S = 30`, `WORK_MIN_M = 150`, `BLOCK_MIN_S = 300`, `BLOCK_MIN_M = 1500`, `REPS_MIN_COUNT = 3`, `VARIED_MAX_ENUMERATE = 5`.
- **Do not touch P2.7b.** The lap path's `len(work) >= 2` versus the stream path's `REPS_MIN_COUNT = 3` stays exactly as it is.
- **`rm -rf __pycache__` before believing any unexpected test result.** A stale `.pyc` whose `(mtime, size)` matches has twice made a must-fail test pass in this repo.
- **Mutation-test every rule you add.** Break it, confirm the suite goes red, restore. A test that passes against broken code is the defect this branch keeps finding.
- **No Co-Authored-By or Claude attribution in commit messages.**

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `interval_lens.py` | the engine — one entry point, no I/O | rep selection, block floor, device GAP, raw cv/fade, version bump |
| `test_interval_lens.py` | synthetic unit tests (96 today) | new fixtures per rule; one existing test reversed |
| `tests/fixtures/lap_workouts.json` | **new** — trimmed real lap DTOs for the 8 production cases | created in Task 1 |
| `test_interval_laps_truth.py` | **new** — asserts the corrected reads for those 8 | created in Task 1, extended in Tasks 2–5 |
| `run.dc.html` | the `/run/:id` page | rep-card headers; `calibrated: false` line |
| `docs/superpowers/HANDOFF-interval-lens.md` | the deferred list | struck items + new findings, Task 9 |

---

### Task 1: Extract the real lap payloads as a test fixture

The engine work in Tasks 2–5 is unverifiable locally without this: the local `activity-archive.db` has 548 activities and **zero** with `laps_json`.

**Files:**
- Create: `tests/fixtures/lap_workouts.json`
- Create: `test_interval_laps_truth.py`

**Interfaces:**
- Produces: `tests/fixtures/lap_workouts.json` — a JSON object keyed by `YYYY-MM-DD`, each value `{"name": str, "summary": {...}, "laps": [ {...}, ... ]}`. Lap dicts carry only `distance`, `duration`, `elapsedDuration`, `averageSpeed`, `avgGradeAdjustedSpeed`, `averageHR`, `intensityType`, `wktStepIndex`. Keys absent in the source stay absent.
- Produces: `test_interval_laps_truth.py::load_workout(date) -> tuple[dict, list[dict]]` returning `(summary, laps)`.

- [ ] **Step 1: Write the extraction script**

Create `C:\Users\felix\AppData\Local\Temp\claude\C--Users-felix-Documents-Github-Splits\47411804-56e7-43c3-99a8-ee89b98c8fa5\scratchpad\extract_laps.py`:

```python
import json, sqlite3
KEEP = ("distance", "duration", "elapsedDuration", "averageSpeed",
        "avgGradeAdjustedSpeed", "averageHR", "intensityType", "wktStepIndex")
DATES = ("2024-07-13", "2024-07-22", "2025-10-17", "2025-11-21", "2025-12-12",
         "2025-12-19", "2026-02-06", "2026-03-20", "2026-04-10", "2026-05-29",
         "2026-06-26", "2026-07-10")
c = sqlite3.connect("file:/data/activity-archive.db?mode=ro", uri=True)
c.row_factory = sqlite3.Row
out = {}
for d in DATES:
    r = c.execute("SELECT name, laps_json, summary_json FROM activities "
                  "WHERE start_time_local LIKE ? AND laps_json IS NOT NULL",
                  (d + "%",)).fetchone()
    if not r:
        raise SystemExit(f"no lap payload for {d}")
    laps = json.loads(r["laps_json"])
    laps = laps.get("lapDTOs", laps) if isinstance(laps, dict) else laps
    summary = json.loads(r["summary_json"]) if r["summary_json"] else {}
    out[d] = {
        "name": r["name"],
        "summary": {k: summary.get(k) for k in ("hasIntensityIntervals", "workoutId")
                    if summary.get(k) is not None},
        "laps": [{k: l[k] for k in KEEP if l.get(k) is not None} for l in laps],
    }
print(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True))
```

Twelve dates, not eight: the four extras (`2025-11-21`, `2026-06-26`, `2026-07-10`, `2024-07-13`) are the cases that must **not** change, and a rule is only trustworthy when its non-firing cases are pinned too.

- [ ] **Step 2: Run it against the NUC and save the fixture**

```bash
scp -q "$SCRATCH/extract_laps.py" felix@192.168.0.37:/tmp/extract_laps.py
ssh felix@192.168.0.37 "docker cp /tmp/extract_laps.py splits:/tmp/extract_laps.py && docker exec splits python /tmp/extract_laps.py" > tests/fixtures/lap_workouts.json
```

If `summary_json` turns out not to be a column, run `ssh felix@192.168.0.37 "docker exec splits python -c \"import sqlite3;c=sqlite3.connect('/data/activity-archive.db');print([d[1] for d in c.execute('PRAGMA table_info(activities)')])\""` and use whichever column holds the activity summary. Do not invent `hasIntensityIntervals` — if no summary column exists, emit `{"workoutId": 1}` for every workout that has any `wktStepIndex`, and note it in the file's own `_note` key.

**NEVER wrap an `ssh … docker … ` call in a client-side `timeout`.** It kills the SSH client, not the remote process, and the orphan holds a write-capable SQLite handle until `docker compose restart splits`.

- [ ] **Step 3: Verify the fixture parses and is complete**

```bash
python -c "
import json
d = json.load(open('tests/fixtures/lap_workouts.json', encoding='utf-8'))
print(len(d), 'workouts')
for k, v in sorted(d.items()):
    steps = sum(1 for l in v['laps'] if 'wktStepIndex' in l)
    print(f\"  {k}  {len(v['laps']):2} laps, {steps:2} with a step  {v['name'][:40]}\")
"
```
Expected: 12 workouts; `2024-07-22` shows 3 of 17 with a step; `2025-12-12` shows 15 of 15.

- [ ] **Step 4: Write the loader and one characterisation test**

Create `test_interval_laps_truth.py`:

```python
#!/usr/bin/env python3
"""The lap path against REAL Garmin lap payloads.

The local activity-archive.db carries no lap data at all — the backfill ran on
the NUC and was never copied down — so test_interval_truth.py cannot reach this
code path. These twelve workouts are the archive's entire lap-sourced
population as of 2026-07-28, trimmed to the fields the engine reads, and they
pin both the sessions this change corrects and the ones it must leave alone.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import interval_lens as il

FIXTURE = Path(__file__).parent / "tests" / "fixtures" / "lap_workouts.json"
WORKOUTS = json.loads(FIXTURE.read_text(encoding="utf-8"))


def load_workout(date: str) -> tuple[dict, list[dict]]:
    """`(summary, laps)` for one archived workout, by its local date."""
    w = WORKOUTS[date]
    return w["summary"], w["laps"]


def build(date: str) -> dict:
    """The document this workout's laps produce. Streams are a flat 3.0 m/s
    grid over the run's whole elapsed span: the lap path takes boundaries,
    roles and per-lap statistics from the device, so the stream only has to be
    long enough to index into."""
    summary, laps = load_workout(date)
    total_s = int(sum(float(l.get("duration") or 0) for l in laps)) + 60
    streams = {"v": [[t, 3.0] for t in range(0, total_s, 5)]}
    return il.build_document(streams, summary, laps)


def test_every_fixture_workout_is_read_as_structured():
    """The gate before any of the rules below: if laps_are_structured stopped
    firing, every assertion in this file would pass against a stream-derived
    document and prove nothing."""
    for date in WORKOUTS:
        summary, laps = load_workout(date)
        assert il.laps_are_structured(summary, laps) is True, \
            f"{date} must take the lap path"
```

- [ ] **Step 5: Run it**

Run: `rm -rf __pycache__ && python -m pytest test_interval_laps_truth.py -v`
Expected: PASS. If `laps_are_structured` returns `False` for any date, the summary fields did not survive extraction — fix Step 2, not the assertion.

The stream shape `{"v": [[t, speed], ...]}` must match what `speed_series` expects; check `interval_lens.speed_series` and `test_interval_lens.make_streams` and copy the real shape if it differs.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/lap_workouts.json test_interval_laps_truth.py
git commit -m "test(interval-lens): pin the archive's real lap payloads

The local archive has no laps_json at all, so the lap path had no real-data
coverage. These twelve workouts are its whole lap-sourced population."
```

---

### Task 2: The workout-step rule

**Files:**
- Modify: `interval_lens.py` — `_apply_lap_work_floor` (lines 553–613) and its one call site in `build_document` (line 775)
- Test: `test_interval_lens.py`, `test_interval_laps_truth.py`

**Interfaces:**
- Consumes: `load_workout`, `build` from Task 1.
- Produces: `interval_lens._lap_rep_segments(segments: list[dict], laps: list[dict]) -> list[dict]` — replaces `_apply_lap_work_floor`. `segments[i]` corresponds to `laps[i]`; `segments_from_laps` appends exactly one segment per lap in order, so the indices align.
- Produces: `interval_lens._rep_step_indices(laps: list[dict], work_idx: set[int]) -> set | None` — the step indices that identify reps, or `None` when the rule must not fire.

- [ ] **Step 1: Write the failing tests**

Add to `test_interval_lens.py`:

```python
def _step_lap(dist, dur, intensity, step, pace_s_per_km=300):
    """A lap carrying a workout STEP index — what a structured workout
    downloaded to the watch produces, and what `_lap` deliberately omits."""
    lap = _lap(dist, dur, intensity)
    lap["wktStepIndex"] = step
    return lap


def test_one_off_active_steps_are_not_reps():
    """The production defect of 2026-07-28. Garmin tags a warmup, a cooldown
    and a mid-workout transition ACTIVE whenever the athlete built them that
    way, and no size floor reaches them — they are LONGER than the reps.
    Only the repeated step is the set."""
    laps = [
        _step_lap(2000, 800, "ACTIVE", 0),      # warmup, tagged ACTIVE
        _step_lap(1000, 310, "ACTIVE", 1),
        _step_lap(300, 150, "RECOVERY", 2),
        _step_lap(1000, 313, "ACTIVE", 1),
        _step_lap(300, 150, "RECOVERY", 2),
        _step_lap(1000, 316, "ACTIVE", 1),
        _step_lap(2000, 1000, "ACTIVE", 4),     # cooldown, tagged ACTIVE
    ]
    doc = _laps_doc(None, laps=laps)
    assert doc["shape"] == "reps"
    assert doc["set"]["found"] == 3, "the two 2 km bookends are not reps"
    assert doc["label"] == "3×1 km"
    assert [s["role"] for s in doc["segments"]] == [
        "warmup", "work", "recovery", "work", "recovery", "work", "cooldown"]
    assert doc["quality"]["workDistM"] == 3000


def test_a_demoted_step_keeps_its_span():
    """Demotion re-roles in place — deleting would open a hole in the run that
    `_quality` and the rep-shaded chart both assume cannot exist."""
    laps = [
        _step_lap(2000, 800, "ACTIVE", 0),
        _step_lap(1000, 310, "ACTIVE", 1),
        _step_lap(300, 150, "RECOVERY", 2),
        _step_lap(1000, 313, "ACTIVE", 1),
    ]
    doc = _laps_doc(None, laps=laps)
    segs = doc["segments"]
    assert len(segs) == 4, "nothing is dropped"
    for a, b in zip(segs, segs[1:]):
        assert a["t1"] == b["t0"], f"gap in the time span: {a} -> {b}"
        assert a["d1"] == b["d0"], f"gap in the distance span: {a} -> {b}"
    assert segs[0]["distM"] == 2000, "the demoted lap keeps its own numbers"
    assert "rep" not in segs[0]
    assert [s["rep"] for s in segs if s["role"] == "work"] == [1, 2]


def test_a_varied_set_with_no_repeated_step_survives_intact():
    """'pYRAMIDE: 1-2-1K' — three distinct steps, each used once. There is no
    repeat block, so the rule must not fire and eat two thirds of the set."""
    laps = [
        _step_lap(2000, 800, "WARMUP", 0),
        _step_lap(1000, 310, "ACTIVE", 1),
        _step_lap(300, 150, "RECOVERY", 2),
        _step_lap(2000, 640, "ACTIVE", 3),
        _step_lap(300, 150, "RECOVERY", 4),
        _step_lap(1000, 315, "ACTIVE", 5),
    ]
    doc = _laps_doc(None, laps=laps)
    assert doc["set"]["found"] == 3
    assert doc["label"] == "1-2-1 km"


def test_a_lap_with_no_step_among_stepped_laps_is_demoted():
    """2026-05-29: a manual lap pressed AFTER the cooldown. It has no step
    index at all, so it was never part of the workout."""
    laps = [
        _step_lap(2000, 800, "WARMUP", 0),
        _step_lap(1000, 310, "ACTIVE", 1),
        _step_lap(300, 150, "RECOVERY", 2),
        _step_lap(1000, 313, "ACTIVE", 1),
        _step_lap(1300, 700, "COOLDOWN", 4),
        _lap(926, 420, "ACTIVE"),               # no wktStepIndex
    ]
    doc = _laps_doc(None, laps=laps)
    assert doc["set"]["found"] == 2
    assert doc["segments"][-1]["role"] == "cooldown"


def test_laps_with_no_steps_anywhere_are_untouched():
    """An unstructured run manually lapped carries no step index on any lap.
    The rule has no evidence to act on and must keep today's behaviour."""
    laps = [_lap(2000, 800, "WARMUP")] + [
        l for d in (1000, 1000, 1000)
        for l in (_pace_lap(d, 300), _lap(300, 150, "REST"))][:-1]
    doc = _laps_doc(None, laps=laps)
    assert doc["set"]["found"] == 3


def test_two_repeated_steps_are_one_alternating_set():
    """4 x [1 km hard, 1 km moderate] is ONE set with TWO repeated steps."""
    laps = [_step_lap(2000, 800, "WARMUP", 0)]
    for _ in range(3):
        laps.append(_step_lap(1000, 300, "ACTIVE", 1))
        laps.append(_step_lap(1000, 360, "ACTIVE", 2))
    doc = _laps_doc(None, laps=laps)
    assert doc["set"]["found"] == 6
```

Add to `test_interval_laps_truth.py`:

```python
@pytest.mark.parametrize("date,found,label", [
    ("2026-04-10", 3, "3×2 km"),      # was 5×2 km — warmup and cooldown counted
    ("2026-03-20", 5, "5×1 km"),      # was "7 reps" — both 2 km bookends counted
    ("2025-12-12", 6, "6×300 m"),     # was 7×300 m — a jog-in counted
    ("2026-05-29", 4, "4×1 km"),      # was 5×1 km — a post-cooldown lap counted
    ("2025-10-17", 6, None),          # was "8 reps"; label asserted separately
])
def test_real_workouts_recover_their_true_rep_count(date, found, label):
    doc = build(date)
    assert doc["shape"] == "reps"
    assert doc["set"]["found"] == found, f"{date}: {WORKOUTS[date]['name']}"
    if label is not None:
        assert doc["label"] == label


@pytest.mark.parametrize("date,found,label", [
    ("2025-11-21", 8, "8×200 m"),     # eight genuine 90 s hill reps
    ("2026-06-26", 3, "1-2-1 km"),    # the pyramid: no repeated step
    ("2026-07-10", 5, "5×1 km"),      # already correct before this change
])
def test_correct_workouts_are_left_alone(date, found, label):
    doc = build(date)
    assert doc["set"]["found"] == found, f"{date} must not change"
    assert doc["label"] == label


def test_no_real_workout_loses_span_coverage():
    """Across every fixture: demotion never deletes."""
    for date in WORKOUTS:
        doc = build(date)
        segs = doc["segments"]
        if not segs:
            continue
        assert len(segs) == len(load_workout(date)[1]), f"{date}: a lap vanished"
        for a, b in zip(segs, segs[1:]):
            assert a["t1"] == b["t0"] and a["d1"] == b["d0"], f"{date}: gap"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `rm -rf __pycache__ && python -m pytest test_interval_lens.py -k "step or demoted or repeated" test_interval_laps_truth.py -v`
Expected: FAIL — real counts still 5 / 7 / 7 / 5 / 8, and `test_one_off_active_steps_are_not_reps` reports `found == 5`.

- [ ] **Step 3: Implement the rule**

In `interval_lens.py`, replace `_apply_lap_work_floor` with:

```python
def _rep_step_indices(laps: list[dict], work_idx: set[int]) -> set | None:
    """Which workout STEP indices identify reps — or None when this activity
    carries no usable step evidence and the caller must keep every work lap.

    `wktStepIndex` is the step of the downloaded workout a lap executed. Reps
    of one set share a single REPEATED step; a warmup, a cooldown or a
    transition occupies its own step, used once. That is the only signal that
    separates them: Garmin tags all of them ACTIVE, and the one-off ones are
    LONGER than the reps, so no size floor can reach them (production defect
    2026-07-28, 8 of 23 lap-sourced documents).

    `work_idx` is the set of lap indices already accepted as work by role and
    by the size floor — counting steps over recovery laps would let a repeated
    RECOVERY step decide which laps are reps.
    """
    if not any(l.get("wktStepIndex") is not None for l in laps):
        return None                       # nothing to go on: keep every rep
    counts = Counter(laps[i].get("wktStepIndex") for i in work_idx
                     if laps[i].get("wktStepIndex") is not None)
    repeated = {step for step, n in counts.items() if n > 1}
    if repeated:
        return repeated
    # every work step distinct — a genuinely varied session (a pyramid). The
    # only thing still disqualifying is carrying no step at all.
    return {s for s in counts}


def _lap_rep_segments(segments: list[dict], laps: list[dict]) -> list[dict]:
    """Which lap-derived work segments are genuine reps.

    Two filters, one question. The SIZE floor (`WORK_MIN_S` / `WORK_MIN_M`,
    the same one `find_bouts` applies to the stream path) rejects fragments —
    the athlete pressing stop, the watch's own end-of-activity lap. The STEP
    rule rejects the opposite failure: a warmup, cooldown or transition the
    watch tagged ACTIVE, which is bigger than a rep rather than smaller.

    A rejected lap is RE-ROLED, never removed: `segments_from_laps` guarantees
    every segment's `t0/t1/d0/d1` chains to the next with no gap, and
    consumers (the rep-shaded stream chart, `_quality`'s summation) rely on
    that full-span coverage. Deleting would open a hole in the run nothing in
    the contract allows. The new role mirrors the vocabulary
    `_segments_from_bouts` already uses for the stream path's own gaps:
    `warmup` before the first surviving rep, `cooldown` after the last,
    `recovery` in between (and when no rep survives at all there is no
    'between' to speak of, but the caller has already demoted the run to
    `steady` or `block`, so the exact word affects no number).

    `idx` never changes. `rep` renumbers 1..N over the SURVIVING work
    segments only, in order, so a demoted lap mid-set leaves no hole.

    A `warmup`/`recovery`/`cooldown` lap is untouched however short: those
    roles carry no minimum on the stream path either.
    """
    sized = {i for i, s in enumerate(segments)
             if s["role"] == "work"
             and s["durS"] >= WORK_MIN_S and s["distM"] >= WORK_MIN_M}
    steps = _rep_step_indices(laps, sized)
    survivors = sized if steps is None else {
        i for i in sized if laps[i].get("wktStepIndex") in steps}

    ordered = sorted(survivors)
    first = ordered[0] if ordered else None
    last = ordered[-1] if ordered else None

    out = []
    rep = 0
    for i, seg in enumerate(segments):
        seg = dict(seg)
        if seg["role"] == "work":
            if i in survivors:
                rep += 1
                seg["rep"] = rep
            else:
                seg.pop("rep", None)
                if first is None:
                    seg["role"] = "recovery"
                elif i < first:
                    seg["role"] = "warmup"
                elif i > last:
                    seg["role"] = "cooldown"
                else:
                    seg["role"] = "recovery"
        out.append(seg)
    return out
```

Add `from collections import Counter` to the imports if it is not already there (check the top of the file first — do not add a duplicate).

Update the call site in `build_document` (line 775):

```python
        segments = _lap_rep_segments(segments_from_laps(laps, gap_grid), laps)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `rm -rf __pycache__ && python -m pytest test_interval_lens.py test_interval_laps_truth.py -v`
Expected: PASS, all of them. The 96 pre-existing tests in `test_interval_lens.py` use `_lap`, which sets no `wktStepIndex`, so they take the `steps is None` branch and are unaffected.

If `2025-10-17` reports 7 rather than 6, the fixture's lap 2 (`ACTIVE 394 m/209 s`) carries the repeated step rather than its own — re-read its `wktStepIndex` values in the fixture and correct the expectation to what the device actually recorded, with a comment. Do not weaken the assertion to make it pass.

- [ ] **Step 5: Mutation-test the rule**

Make each of these three edits in turn, run `rm -rf __pycache__ && python -m pytest test_interval_lens.py test_interval_laps_truth.py -q`, confirm **FAIL**, then revert:

1. `if repeated:` → `if False:`
2. `return None` (the no-steps guard) → `return set()`
3. `counts = Counter(... for i in work_idx ...)` → `for i in range(len(laps))`

Any that stays green means a test is not exercising what it claims. Add the missing test before continuing.

- [ ] **Step 6: Commit**

```bash
git add interval_lens.py test_interval_lens.py test_interval_laps_truth.py
git commit -m "fix(interval-lens): the workout step decides what is a rep

_LAP_ROLES maps ACTIVE to work unconditionally, but Garmin tags warmups,
cooldowns and transitions ACTIVE too, and they are LONGER than the reps, so
the size floor never reached them. wktStepIndex separates them: reps share one
repeated workout step, one-off steps do not.

8 of 23 lap-sourced documents were counting non-reps. 2026-04-10 read 5x2 km
for a 3x2 km session; 2025-12-12's +37.1% fade was one jog-in lap."
```

---

### Task 3: The block floor on the lap path

**Files:**
- Modify: `interval_lens.py` — `build_document`, the laps branch (line 783)
- Test: `test_interval_lens.py`, `test_interval_laps_truth.py`

**Interfaces:**
- Consumes: `_lap_rep_segments` from Task 2.
- Produces: no new symbols. The laps branch's `shape` decision now applies `BLOCK_MIN_S` / `BLOCK_MIN_M`.

- [ ] **Step 1: Write the failing tests**

Add to `test_interval_lens.py`:

```python
def test_a_single_short_work_lap_is_not_a_block():
    """The stream path has always required BLOCK_MIN_S/BLOCK_MIN_M before
    calling something a block; the laps branch called ANY surviving work lap
    one. Task 2 makes the single-survivor case common, so the asymmetry
    started mattering. 'Run Walk Run®' (2024-07-22) asserted a '1 min block'
    over a 205 m fragment of a 25 minute run/walk."""
    laps = [_step_lap(2000, 800, "WARMUP", 0),
            _step_lap(205, 62, "ACTIVE", 1),
            _step_lap(2000, 900, "COOLDOWN", 2)]
    doc = _laps_doc(None, laps=laps)
    assert doc["shape"] == "steady"
    assert doc["label"] is None
    assert doc["segments"] == [], "a steady run gets a document, no segments"
    assert doc["set"] is None


def test_a_single_long_work_lap_is_still_a_block():
    laps = [_step_lap(2000, 800, "WARMUP", 0),
            _step_lap(3000, 1118, "ACTIVE", 1),
            _step_lap(1000, 450, "COOLDOWN", 2)]
    doc = _laps_doc(None, laps=laps)
    assert doc["shape"] == "block"
    assert doc["label"] == "19 min block"
```

Add to `test_interval_laps_truth.py`:

```python
@pytest.mark.parametrize("date,shape", [
    ("2024-07-22", "steady"),   # Run Walk Run® — handoff P2.7a
    ("2024-07-13", "steady"),   # an 801 m 'block' inside an assessment run
    ("2026-06-26", "reps"),     # the pyramid is untouched
])
def test_real_blocks_meet_the_block_floor(date, shape):
    assert build(date)["shape"] == shape
```

- [ ] **Step 2: Run them to verify they fail**

Run: `rm -rf __pycache__ && python -m pytest test_interval_lens.py -k "block" test_interval_laps_truth.py -k "block_floor" -v`
Expected: FAIL — `2024-07-22` reads `block`, and the 205 m fixture reads `block` with label `1 min block`.

- [ ] **Step 3: Implement**

In `build_document`'s laps branch, replace:

```python
        shape = "reps" if len(work) >= 2 else ("block" if work else "steady")
```

with:

```python
        # A single surviving work lap is only a BLOCK if it is big enough to
        # be one — the same BLOCK_MIN_S/BLOCK_MIN_M the stream path has always
        # applied. Task 2's step rule makes the single-survivor case common,
        # and without this a 205 m fragment of a run/walk asserts "1 min
        # block" (handoff P2.7a). The `>= 2` rep threshold is deliberately
        # NOT unified with the stream path's REPS_MIN_COUNT here — see P2.7b,
        # which is entangled with Change 2's expect_reps.
        if len(work) >= 2:
            shape = "reps"
        elif work and work[0]["durS"] >= BLOCK_MIN_S and work[0]["distM"] >= BLOCK_MIN_M:
            shape = "block"
        else:
            shape = "steady"
```

The existing `if shape == "steady": segments = []` below already handles clearing the segments; do not duplicate it.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `rm -rf __pycache__ && python -m pytest test_interval_lens.py test_interval_laps_truth.py -v`
Expected: PASS. Watch `test_lagrasse_strides_reclassify_as_a_block_not_five_reps` — its block is 3040 m / 790 s, comfortably above both floors, and must stay green.

- [ ] **Step 5: Mutation-test**

Change `>= BLOCK_MIN_M` to `>= 0`, run the suite, confirm **FAIL**, revert. Repeat for `>= BLOCK_MIN_S`. If either survives, `test_a_single_short_work_lap_is_not_a_block` is not separating the two floors — add a fixture that fails one and passes the other.

- [ ] **Step 6: Commit**

```bash
git add interval_lens.py test_interval_lens.py test_interval_laps_truth.py
git commit -m "fix(interval-lens): a lap-sourced block must clear the block floor

The stream path has always required BLOCK_MIN_S/BLOCK_MIN_M; the laps branch
called any surviving work lap a block. Closes P2.7a: 'Run Walk Run' no longer
asserts a block over a 205 m fragment."
```

---

### Task 4: GAP comes from the device

**Files:**
- Modify: `interval_lens.py` — `segments_from_laps` (lines 512–550), docstring and the `gapS` assignment
- Test: `test_interval_lens.py`, `test_interval_laps_truth.py`

**Interfaces:**
- Produces: `segments_from_laps(laps, gaps=None)` keeps its signature. `gapS` prefers `lap["avgGradeAdjustedSpeed"]`, falling back to `_window_pace(gaps, t0, t1)`.

- [ ] **Step 1: Write the failing tests**

Add to `test_interval_lens.py`:

```python
def test_lap_gap_comes_from_the_device_when_it_carries_one():
    """`segments_from_laps` derived gapS by windowing the stream's gap grid,
    on the docstring's claim that "a lapDTO carries no grade-adjusted speed".
    It does: avgGradeAdjustedSpeed is present on 553 of the archive's 565
    laps. The device value is also immune to M3 — lap `duration` is MOVING
    time, so on a paused run the accumulated t0 drifts off the stream's
    elapsed axis and the windowed lookup reads the wrong slice."""
    lap = _lap(1000, 300, "ACTIVE")
    lap["avgGradeAdjustedSpeed"] = 4.0          # 250 s/km
    segs = il.segments_from_laps([lap], gaps=[2.0] * 400)   # 500 s/km if windowed
    assert segs[0]["gapS"] == 250, "the device's own number, not the stream's"


def test_lap_gap_falls_back_to_the_stream_grid():
    lap = _lap(1000, 300, "ACTIVE")              # no avgGradeAdjustedSpeed
    segs = il.segments_from_laps([lap], gaps=[4.0] * 400)
    assert segs[0]["gapS"] == 250


def test_lap_gap_is_none_when_neither_source_has_one():
    lap = _lap(1000, 300, "ACTIVE")
    assert il.segments_from_laps([lap], gaps=None)[0]["gapS"] is None
```

Add to `test_interval_laps_truth.py`:

```python
def test_real_reps_carry_a_device_gap():
    """Every fixture lap has avgGradeAdjustedSpeed, so no real rep should be
    falling back — the GAP column was empty on precisely the athlete's genuine
    workout days before it was filled at all."""
    doc = build("2026-07-10")
    work = [s for s in doc["segments"] if s["role"] == "work"]
    assert work and all(s["gapS"] is not None for s in work)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `rm -rf __pycache__ && python -m pytest test_interval_lens.py -k "lap_gap" test_interval_laps_truth.py -k "device_gap" -v`
Expected: FAIL — the first returns 500 (windowed), not 250.

- [ ] **Step 3: Implement**

In `segments_from_laps`, replace the `gapS` line:

```python
            "gapS": _pace_s_per_km(lap["avgGradeAdjustedSpeed"])
                    if lap.get("avgGradeAdjustedSpeed")
                    else _window_pace(gaps, int(round(t0)), int(round(t0 + dur))),
```

And replace the second paragraph of the docstring — it currently states the opposite of the truth:

```python
    `gaps` is a FALLBACK, not the primary source. A lapDTO usually carries
    `avgGradeAdjustedSpeed` (553 of this archive's 565 laps), and the device's
    own number is preferred: it is measured over exactly the lap, whereas the
    windowed lookup indexes the 1 Hz grid by a clock accumulated from lap
    `duration` — MOVING time — so on a paused run it drifts off the stream's
    elapsed axis and reads the wrong slice (handoff M3). `gaps` covers the
    older payloads that have no such field, so the GAP column is not empty on
    precisely the runs that earn a lap-sourced document — the athlete's
    genuine workout days. The lap clock is cumulative from the activity start,
    which is the same origin as the 1 Hz grid, so a lap's [t0, t1) indexes
    straight into it.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `rm -rf __pycache__ && python -m pytest test_interval_lens.py test_interval_laps_truth.py -v`
Expected: PASS.

- [ ] **Step 5: Mutation-test**

Delete the `if lap.get("avgGradeAdjustedSpeed")` condition so the device value is always used, run the suite, confirm **FAIL** (`test_lap_gap_falls_back_to_the_stream_grid` must catch it), revert.

- [ ] **Step 6: Commit**

```bash
git add interval_lens.py test_interval_lens.py test_interval_laps_truth.py
git commit -m "fix(interval-lens): take GAP from the lap, not from a windowed guess

The docstring claimed a lapDTO carries no grade-adjusted speed. It does, on
553 of 565 archived laps. Using it also removes the lap path's exposure to the
moving-vs-elapsed clock drift recorded as M3."
```

---

### Task 5: One basis for spread and fade

**Files:**
- Modify: `interval_lens.py` — `set_stats` (lines 413–475), docstring and the `effort` computation
- Test: `test_interval_lens.py` (one existing test reversed), `test_interval_laps_truth.py`

**Interfaces:**
- Produces: `set_stats(bouts, series, dist_at, hr, raw=None, gaps=None)` keeps its signature. `paceCvPct` and `fadePct` are computed from the **raw** grid, matching what the laps branch already does.

- [ ] **Step 1: Reverse the existing test**

`test_interval_lens.py::test_fade_is_measured_on_effort_while_the_reported_pace_is_raw` (line 718) asserts the behaviour being replaced. **Rewrite it**, do not delete it — the trade-off must stay recorded where the next reader will hit it:

```python
def test_spread_and_fade_are_measured_on_the_same_signal_as_the_bars():
    """CHANGED 2026-07-28, deliberately, and this reverses design D5's
    reporting half. `fadePct`/`paceCvPct` rode the grade-adjusted DETECTION
    signal while the rep table's deviation bars and PACE column were raw, so a
    hilly set fanned its bars out above a sub-line reading '0.0 % spread'.

    Measured before choosing: on the archive's one uncontaminated hill-repeat
    set (2025-11-21, eight genuine 90 s reps) RAW is TIGHTER — cv 9.1 % vs
    GAP 14.7 %. Fixed-duration reps cover less ground as the athlete tires, so
    each samples a different slice of the gradient and its grade adjustment
    varies; GAP there measures the hill, not the athlete. On the stream path
    the two bases differ by under 1.5 points and split both ways across 11
    sets.

    The cost this fixture now pins: a set climbing a CONTINUOUS drag at
    constant effort reads as a fade, which is exactly what D5 warned about.
    No such session exists in 168 runs — every hill session runs each rep up
    the same hill and recovers back down — so successive reps share terrain
    and raw pace compares them honestly. Revisit if one ever appears.

    DETECTION is untouched: the bouts are still found on the grade-adjusted
    signal, so this set is still detected as ONE set."""
    spans = [(600, 2.6, 2.6)]
    for raw in (4.4, 4.2, 4.0, 3.8, 3.6):
        spans += [(250, raw, 4.2), (60, 2.2, 2.2)]
    spans += [(300, 2.6, 2.6)]
    doc = il.build_document(make_dual_streams(spans), work_floor=3.0)
    assert doc["shape"] == "reps" and doc["set"]["found"] == 5, \
        "detection still rides the grade-adjusted signal — one set, not five"
    st = doc["set"]
    assert st["fadePct"] > 15, \
        f"the raw slowdown is now reported as the fade it looks like: {st['fadePct']}%"
    assert st["paceCvPct"] > 5, f"…and as real spread: {st['paceCvPct']}"
    assert all(abs(r["gapS"] - 238) <= 2 for r in st["reps"]), \
        "GAP stays per-rep and unchanged — the terrain read lives in that column"
```

Add to `test_interval_laps_truth.py`:

```python
def test_both_producers_report_spread_on_the_same_basis():
    """The laps branch always computed cv/fade from raw lap paces while
    set_stats used the detection grid. One engine, one definition."""
    doc = build("2026-04-10")
    paces = [r["paceS"] for r in doc["set"]["reps"]]
    mean = sum(paces) / len(paces)
    expected = round(100.0 * (sum((p - mean) ** 2 for p in paces) / len(paces)) ** 0.5 / mean, 1)
    assert doc["set"]["paceCvPct"] == expected
    assert doc["set"]["fadePct"] == round(100.0 * (paces[-1] - paces[0]) / paces[0], 1)


@pytest.mark.parametrize("date,max_cv,max_abs_fade", [
    ("2026-04-10", 3.0, 2.0),    # 3x2 km, was cv 14.8 / fade +17.5
    ("2026-03-20", 4.0, 4.0),    # 5x1 km, was cv 19.5 / fade +18.0
    ("2025-12-12", 6.0, 6.0),    # 6x300 m, was fade +37.1
    ("2026-05-29", 4.0, 2.0),    # 4x1 km, was cv 10.6 / fade +30.5
])
def test_corrected_sets_report_sane_spread(date, max_cv, max_abs_fade):
    """The fabricated spread and fade were the visible damage — a genuine
    tempo set does not fade 17% across its reps."""
    st = build(date)["set"]
    assert st["paceCvPct"] <= max_cv, f"{date}: {st['paceCvPct']}%"
    assert abs(st["fadePct"]) <= max_abs_fade, f"{date}: {st['fadePct']}%"
```

- [ ] **Step 2: Run to verify they fail**

Run: `rm -rf __pycache__ && python -m pytest test_interval_lens.py -k "same_signal_as_the_bars" test_interval_laps_truth.py -k "same_basis" -v`
Expected: FAIL — `fadePct` is `0.0`, not `> 15`.

- [ ] **Step 3: Implement**

In `set_stats`, delete the `effort` line and compute from `paces` instead:

```python
    # Consistency and fade ride the RAW grid — the same signal as the reported
    # `paceS`, the rep table's PACE column and its deviation bars. See
    # test_spread_and_fade_are_measured_on_the_same_signal_as_the_bars for the
    # measurement behind this and what it trades away. DETECTION is unchanged:
    # `series` is still the grade-adjusted grid and still decides the bouts.
    mean_pace = _mean(paces)
    cv = None
    if mean_pace and len(paces) > 1:
        var = sum((p - mean_pace) ** 2 for p in paces) / len(paces)
        cv = round(100.0 * (var ** 0.5) / mean_pace, 1)
```

and the `fadePct` entry in the returned dict:

```python
        "fadePct": round(100.0 * (paces[-1] - paces[0]) / paces[0], 1)
                   if len(paces) > 1 and paces[0] else None,
```

Then replace the docstring's third paragraph ("The split matters for `fadePct` and `paceCvPct`, which stay on the DETECTION signal…") with:

```
    `series` decides WHERE the reps are; `raw` decides what every reported
    number says. `paceCvPct` and `fadePct` used to ride `series`, which put
    them on a different signal from the `paceS` printed beside them and from
    the deviation bars drawn from it — a hilly set fanned its bars out under a
    sub-line reading "0.0 % spread". They now ride `raw`, which is also what
    the laps branch has always done, so the two producers agree.
```

Leave the `raw = series if raw is None else raw` default and the `gaps` handling alone.

- [ ] **Step 4: Run the full suite**

Run: `rm -rf __pycache__ && python -m pytest test_interval_lens.py test_interval_laps_truth.py test_interval_truth.py -v`
Expected: PASS. `test_set_stats_report_consistency_and_fade` (line 329) uses single-grid `make_streams`, where raw and detection are the same series, so it is unaffected — confirm it stays green rather than assuming it.

- [ ] **Step 5: Mutation-test**

Change `paces[-1] - paces[0]` to `paces[0] - paces[-1]`, run, confirm **FAIL**, revert. Then change `cv` to be computed from `effort`-style detection paces again (re-introduce `_window_pace(series, a, b)`), confirm **FAIL**, revert.

- [ ] **Step 6: Commit**

```bash
git add interval_lens.py test_interval_lens.py test_interval_laps_truth.py
git commit -m "fix(interval-lens): spread and fade ride the same signal as the bars

set_stats measured cv/fade on the grade-adjusted detection grid while the
laps branch used raw, and while the rep card's bars and PACE column were both
raw. Both producers now report raw. Detection is untouched.

Measured first: on the archive's one uncontaminated hill-repeat set raw is
tighter than GAP (9.1% vs 14.7%) — fixed-duration reps sample a different
slice of the gradient as they shorten."
```

---

### Task 6: Bump `INTERVAL_VERSION`

Do this once, after every engine change and before any deploy. The document is a disposable versioned cache: the next sync recomputes all of them in seconds, no migration.

**Files:**
- Modify: `interval_lens.py:20`

**Interfaces:**
- Consumes: Tasks 2–5.
- Produces: `INTERVAL_VERSION == 4`.

- [ ] **Step 1: Write the failing test**

Add to `test_interval_lens.py`:

```python
def test_interval_version_is_current():
    """A stored document is only trustworthy if its version moved whenever the
    rules that produced it did. Tasks 2-5 changed which laps are reps, what a
    lap-sourced block must clear, where GAP comes from, and the basis of
    spread and fade — every stored document must be recomputed."""
    assert il.INTERVAL_VERSION == 4
    assert il.build_document(make_streams([(600, 3.0)]), work_floor=3.0)["version"] == 4
```

- [ ] **Step 2: Run it to verify it fails**

Run: `rm -rf __pycache__ && python -m pytest test_interval_lens.py -k interval_version_is_current -v`
Expected: FAIL — `assert 3 == 4`.

- [ ] **Step 3: Implement**

`interval_lens.py:20` — extend the existing running comment rather than replacing it:

```python
INTERVAL_VERSION = 4   # 2: paceS is raw pace and gapS is real (final review I4);
                       # 3: the rep floor applies to lap-derived work segments;
                       # 4: the workout STEP decides what is a rep — one-off
                       #    ACTIVE laps demoted, lap blocks meet BLOCK_MIN_*,
                       #    GAP from the device, spread/fade on the raw grid.
```

Match the existing comment's exact indentation and wording style — read line 20 and the lines under it first.

- [ ] **Step 4: Run the whole Python suite**

Run: `rm -rf __pycache__ && python -m pytest -q`
Expected: PASS — 402 passed / 2 skipped at the previous merge, plus the tests added here. Any *other* failure is a real regression, not a version-number consequence; do not paper over it.

- [ ] **Step 5: Commit**

```bash
git add interval_lens.py test_interval_lens.py
git commit -m "feat(interval-lens): INTERVAL_VERSION 4 — the workout step rules

Every stored document was produced by rules that have since changed. The next
sync recomputes all of them; the cache is disposable by design."
```

---

### Task 7: `PACE` / `GAP` column headers on the rep card (P1.1)

**Files:**
- Modify: `run.dc.html:185-214` (the `sc-for` rep card block)
- Test: `test_run_page.mjs`

**Interfaces:**
- Consumes: nothing from earlier tasks — this is presentation only.
- Produces: a `.rep-head` row inside `.rep-table`, with `.rep-head-pace` and `.rep-head-gap` cells.

- [ ] **Step 1: Write the failing test**

In `test_run_page.mjs`, inside the existing `REP_RUN_ID` block (right after the `.rep-pace` / `.rep-gap` assertions around line 518), add:

```javascript
  // P1.1: pace and GAP were two adjacent unlabelled monospace numbers. The
  // ambiguity was NEW — before gapS was real the GAP cell was always an em
  // dash, so there was nothing to confuse it with.
  const headPace = await page.locator(".rep-table .rep-head-pace").innerText();
  const headGap = await page.locator(".rep-table .rep-head-gap").innerText();
  assert.strictEqual(headPace.trim(), "PACE", "the pace column is labelled");
  assert.strictEqual(headGap.trim(), "GAP", "…and so is the GAP column");
  // the headers sit ABOVE the first rep row, and each is horizontally aligned
  // with the column it names — a header in the wrong order is worse than none
  const boxOf = async (sel) => await page.locator(sel).first().boundingBox();
  const [hp, hg, cp, cg, r0] = await Promise.all([
    boxOf(".rep-head-pace"), boxOf(".rep-head-gap"),
    boxOf(".rep-pace"), boxOf(".rep-gap"), boxOf(".rep-row"),
  ]);
  assert.ok(hp.y + hp.height <= r0.y + 1, "the header row is above the first rep");
  assert.ok(Math.abs((hp.x + hp.width) - (cp.x + cp.width)) <= 2,
    `PACE header is not aligned to the pace column: ${hp.x + hp.width} vs ${cp.x + cp.width}`);
  assert.ok(Math.abs((hg.x + hg.width) - (cg.x + cg.width)) <= 2,
    `GAP header is not aligned to the GAP column: ${hg.x + hg.width} vs ${cg.x + cg.width}`);
```

Assert on the scoped `.rep-head-*` classes, never on page text: `"GAP"` and `"PACE"` appear elsewhere on the page, and a text-matching locator that hits a wordmark is exactly the class of false-green this branch has already found four times.

- [ ] **Step 2: Run it to verify it fails**

Run: `node test_run_page.mjs`
Expected: FAIL — locator `.rep-table .rep-head-pace` resolves to nothing.

- [ ] **Step 3: Implement**

In `run.dc.html`, insert a header row between the `card-sub` div (line 188) and the rows container (line 189):

```html
        <div class="rep-head" style="display:flex;align-items:center;gap:var(--sp-3);font-size:var(--fs-2xs);font-weight:800;letter-spacing:.04em;color:var(--sub);padding-bottom:var(--sp-1)">
          <span style="width:34px"></span>
          <span style="width:56px"></span>
          <span style="width:48px"></span>
          <div style="flex:1"></div>
          <span class="rep-head-pace" style="width:52px;text-align:right">PACE</span>
          <span class="rep-head-gap" style="width:52px;text-align:right">GAP</span>
          <span style="width:44px;text-align:right">HR</span>
        </div>
```

The spacer widths must match the `.rep-row` cells exactly — `34px` (rep number), `56px` (distance), `48px` (time), `flex:1` (the bar), then `52px` / `52px` / `44px`. Re-read lines 192–203 and copy the widths from there rather than trusting this list.

Use the literal characters `PACE`, `GAP`, `HR` in the markup. Never a `\uXXXX` escape in JSX/HTML text content — it renders as a literal backslash string.

- [ ] **Step 4: Run the test to verify it passes**

Run: `node test_run_page.mjs`
Expected: PASS, including the alignment assertions. If a header is off by more than 2 px, a width does not match its column — fix the width, do not widen the tolerance.

- [ ] **Step 5: Check the narrow layout**

Run: `node tools/style-audit.mjs layout`
Expected: PASS. The rep card must not overflow at 390 px. If it does, the header row is the new thing on the page — hide it below the mobile breakpoint rather than shrinking the columns, and note that in the markup.

- [ ] **Step 6: Commit**

```bash
git add run.dc.html test_run_page.mjs
git commit -m "feat(run-page): label the PACE and GAP columns on the rep card

Two adjacent unlabelled monospace numbers. The ambiguity was new: before gapS
carried a real value the GAP cell was always an em dash."
```

---

### Task 8: Surface `calibrated: false` (P1.2)

**Files:**
- Modify: `run.dc.html` — the template (near the rep-card block) and `pg.reps` construction (lines 520–564)
- Test: `test_run_page.mjs`

**Interfaces:**
- Consumes: `run.intervals.calibrated`, already served by the by-id endpoint (`serve.mjs:498` returns the whole `doc_json`).
- Produces: `pg.uncalibrated` — a list of zero or one `{ t: string }`, rendered by an `sc-for` block with class `rep-uncal`.

- [ ] **Step 1: Write the failing test**

In `test_run_page.mjs`, add a fourth interval fixture. Beside the other id constants (near line 172):

```javascript
const UNCAL_RUN_ID = 9004;
```

Beside `STEADY_DOC`, add:

```javascript
// P1.2: a document from an athlete whose archive is too short to calibrate a
// work floor. `calibrated: false` means "we could not judge structure yet" —
// which rendered IDENTICALLY to "we looked and found nothing" before this.
const UNCAL_DOC = {
  version: 4, shape: "steady", source: "stream", calibrated: false,
  confidence: 0.0, label: null, segments: [], set: null, guidedBy: null,
  quality: { workDistM: 0, workDurS: 0, zone: null },
};
```

In the fixture builder, after the `STEADY_RUN_ID` insert:

```javascript
  db.prepare(`INSERT INTO activities (activity_id, start_time_local, type_key, name,
      distance_m, duration_s, avg_hr, max_hr, avg_cadence, elevation_gain_m,
      summary_json, detail_json, first_seen_at, updated_at, detail_distilled_json,
      detail_streams_json)
    VALUES (?, '2026-07-13 06:51:15', 'running', 'Max First Week Run',
      5000.0, 1800, 148, 165, 164.0, 12.0, '{}', '{}', 'x', 'x', ?, NULL)`)
    .run(UNCAL_RUN_ID, JSON.stringify(DETAIL));
  db.prepare(`INSERT INTO run_intervals VALUES (?,?,?,?,?,?,?,?,?,?,?)`).run(
    UNCAL_RUN_ID, 4, "2026-07-13 06:51:15", "steady", null, 0.0, "stream",
    0, 0, JSON.stringify(UNCAL_DOC), "2026-07-28T09:00:00");
```

And after the `STEADY_RUN_ID` assertions (around line 626):

```javascript
  // P1.2: "not enough history to judge structure yet" must NOT render as
  // "steady". This is Max's live state — work_floor needs ~30 runs of pace
  // history and his archive is days old.
  await page.goto(B + `/run/${UNCAL_RUN_ID}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector(".rep-uncal", { timeout: 15000 });
  const uncalText = (await page.locator(".rep-uncal").innerText()).toLowerCase();
  assert.ok(uncalText.includes("not enough"),
    "an uncalibrated run says so plainly: " + uncalText);
  assert.equal(await page.locator(".rep-table").count(), 0,
    "…and still renders no rep table");
  const uncalPage = await page.evaluate(() => document.body.innerText);
  assert.ok(uncalPage.includes("km 6"),
    "the km splits card is unaffected");

  // the discriminating half: a CALIBRATED steady run must NOT carry the
  // notice, or the notice means nothing.
  await page.goto(B + `/run/${STEADY_RUN_ID}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector(".card");
  assert.equal(await page.locator(".rep-uncal").count(), 0,
    "a calibrated steady run looked and found nothing — no notice");
```

Confirm `STEADY_DOC` carries `calibrated: true`. If it omits the key entirely, add it — a fixture that is silent on the field cannot prove the discriminating half.

- [ ] **Step 2: Run it to verify it fails**

Run: `node test_run_page.mjs`
Expected: FAIL — `.rep-uncal` never appears.

- [ ] **Step 3: Implement**

In `run.dc.html`, immediately after the closing `</sc-for>` of the rep-table block (line 214), add:

```html
    <sc-for list="{{ pg.uncalibrated }}" as="uc" hint-placeholder-count="0">
      <div class="card rep-uncal">
        <div class="card-title" style="margin-bottom:var(--sp-1)">Structure</div>
        <div class="card-sub">{{ uc.t }}</div>
      </div>
    </sc-for>
```

And in the script, immediately after the `pg.reps` block (after line 564):

```javascript
      // P1.2: `calibrated: false` means the work floor could not be computed —
      // the athlete's archive is too short (WORK_FLOOR_MIN_SAMPLES ≈ 30 runs).
      // Saying nothing renders that identically to "we looked and found
      // nothing", which is the one distinction the steady-document rule
      // exists to preserve. Lap-sourced documents are always calibrated (the
      // watch is not guessing), so this only ever fires where it is true.
      pg.uncalibrated = (iv && iv.calibrated === false)
        ? [{ t: 'Not enough history to judge this run’s structure yet — that needs a few weeks of runs to learn what "fast" means for you. Pace, HR and splits below are unaffected.' }]
        : [];
```

Use the literal `’` character, not an escape. `iv.calibrated === false` and not `!iv.calibrated`: an older stored document missing the key must stay silent rather than accusing a calibrated run.

- [ ] **Step 4: Run the test to verify it passes**

Run: `node test_run_page.mjs`
Expected: PASS, both halves.

- [ ] **Step 5: Mutation-test the discriminator**

Change `iv.calibrated === false` to `!iv.calibrated`, run `node test_run_page.mjs`, confirm **FAIL** on the STEADY_RUN_ID half (its doc must therefore carry `calibrated: true`), revert.

- [ ] **Step 6: Commit**

```bash
git add run.dc.html test_run_page.mjs
git commit -m "feat(run-page): say when there is not enough history to judge structure

build_document has always written `calibrated`, and nothing read it, so 'we
could not look yet' rendered identically to 'we looked and found nothing'.
That is Max's live state today."
```

---

### Task 9: Deploy and verify on the NUC

Nothing here is believable from a green local suite: the whole change is about real lap data, and the local archive has none.

**Files:** none — this task produces evidence, not code.

**Interfaces:**
- Consumes: Tasks 2–8, all committed.

- [ ] **Step 1: Confirm the working tree is clean and the suite is green**

```bash
rm -rf __pycache__
python -m pytest -q
for f in test_run_page.mjs test_archive_page.mjs test_coach_read.mjs; do echo "== $f"; node "$f"; done
git status --short
```
Expected: Python green, those three suites green, working tree clean.

- [ ] **Step 2: Check for orphaned processes before touching the NUC**

```bash
ssh felix@192.168.0.37 "docker top splits"
```
Expected: only `/sbin/docker-init` and `node serve.mjs`. Anything else is an orphan holding a write-capable SQLite handle — clear it with `ssh felix@192.168.0.37 "cd ~/dev/docker-compose-files/splits && docker compose restart splits"` (the image has neither `ps` nor `kill`, and the orphan runs as root).

**NEVER wrap an `ssh … docker compose exec …` call in a client-side `timeout`** — it kills the SSH client, not the remote process, and creates exactly the orphan above. Use `run_in_background` for anything long.

- [ ] **Step 3: Deploy**

Follow the repo's normal deploy path (`git push` then rebuild on the NUC). Read `CLAUDE_CODE_HANDOFF.md` for the exact commands before running anything — do not improvise a deploy.

Windows CRLF gotcha: files copied to the NUC must have LF endings, or the container's shell rejects the script.

- [ ] **Step 4: Rescore and sweep**

Prefer `POST /api/sync` — `serve.mjs` owns the sync lock and is meant to be the single writer. Running `sync_garmin.py` directly via `docker compose exec` bypasses it.

Then sweep read-only and compare against the merge baseline:

```bash
ssh felix@192.168.0.37 "docker exec splits python -c \"
import json,sqlite3,collections
c=sqlite3.connect('file:/data/activity-archive.db?mode=ro',uri=True)
rows=[json.loads(r[0]) for r in c.execute('SELECT doc_json FROM run_intervals')]
print('versions', collections.Counter(d.get('version') for d in rows))
print('shapes  ', collections.Counter(d.get('shape') for d in rows))
print('sources ', collections.Counter(d.get('source') for d in rows))
for d,n in sorted((json.loads(r[0]),r[1]) for r in c.execute(
    'SELECT i.doc_json, a.name FROM run_intervals i JOIN activities a USING(activity_id) '
    'WHERE json_extract(i.doc_json,\\\"\$.source\\\")=\\\"laps\\\"')):
    print(f\\\"  {d['shape']:10} {str(d['label']):14} {n[:44]}\\\")
\""
```

Expected, against the merge baseline `steady 138 / reps 19 / block 5 / progression 2`:
- every document at `version` 4;
- two block→steady flips (`2024-07-22 Run Walk Run®`, `2024-07-13 Einstufungslauf`);
- `2026-04-10` → `3×2 km`, `2026-03-20` → `5×1 km`, `2025-12-12` → `6×300 m`, `2026-05-29` → `4×1 km`, `2025-10-17` → 6 reps, `2026-02-06` → 6 reps;
- `2025-11-21` still `8×200 m`, `2026-06-26` still `1-2-1 km`, `2026-07-10` still `5×1 km`;
- **stream-sourced shape counts unchanged** — this change must not move them at all. If they moved, Task 5 changed detection, which it must not.

Record the actual output in the handoff (Task 10). If any expectation misses, stop and investigate before writing it up — a surprise here is the finding, not a nuisance.

- [ ] **Step 4b: Look at a corrected run in the browser**

Open `/run/<2026-04-10's activityId>` and confirm: the label reads `3×2 km`, three rep rows, `PACE` and `GAP` headers above their columns, and the sub-line's spread agrees with the bars beside it. This is the one check the test suite cannot make for you.

- [ ] **Step 5: Verify the archive is intact**

```bash
ssh felix@192.168.0.37 "docker exec splits python -c \"import sync_garmin; raise SystemExit(sync_garmin.verify_archive())\""
```
Expected: exit 0.

- [ ] **Step 6: Commit nothing**

This task produces no code. If it produced a fix, that fix is its own commit with its own test.

---

### Task 10: Update the handoff

**Files:**
- Modify: `docs/superpowers/HANDOFF-interval-lens.md`

- [ ] **Step 1: Strike what this change closed**

Mark **P1.1**, **P1.2**, **P2.1**, **P2.7a** and the lap half of **M3** as done, each with the commit that did it and a one-line statement of what was decided — not just "fixed". For P2.1 that means recording the measurement (raw is tighter on the archive's one uncontaminated hill-repeat set, 9.1 % vs 14.7 %) so nobody re-opens it without new data.

- [ ] **Step 2: Correct the P2.3 note**

`2026-05-29`'s celebrated `5×1 km [1000, 1000, 1000, 1000, 926]` was wrong: the 926 m "rep" is a post-cooldown manual lap with no workout step. It now reads `4×1 km`. The conclusion P2.3 draws from it — that the windowed baseline is no longer evidence-backed — is **unaffected**, because that run still takes the lap path. Say both things.

- [ ] **Step 3: Add what this change found and did not fix**

- **Duration-named sets.** `2026-02-06`'s six 90 s hill reps now label as `6×0.23 km`, because their mean distance snaps to no round target. These sets want naming by duration (`6×90 s`) — a `_reps_label` change with blast radius across the `/archive` chip, the rep-card title and the cockpit sentence.
- **`d0/d1` still accumulate from lap `distance`**, and `segments_from_laps` still assumes the stream clock starts at 0. M3's other half stands; only the `gapS` exposure is gone.
- **Drift is real but tiny**: measured across all 17 lap-sourced structured runs, moving-vs-elapsed drift is 0 s on every one except `2026-06-26`, which drifts 40 s.
- **P2.7b untouched**, and why: unifying `len(work) >= 2` with `REPS_MIN_COUNT` would demote the legitimate two-rep session of `2026-06-05`, and it is entangled with Change 2's `expect_reps` (P3.1).

- [ ] **Step 4: Record the new test asset**

`tests/fixtures/lap_workouts.json` + `test_interval_laps_truth.py` pin the archive's whole lap-sourced population as of 2026-07-28. Note that the local `activity-archive.db` has **no** lap data, so `test_interval_truth.py` cannot reach the lap path — that is why the fixture exists, and it is why a future lap-path change must extend the fixture rather than lean on the archive.

- [ ] **Step 5: Paste the real sweep output** from Task 9 Step 4 under a dated heading, the way the previous deploy's findings were recorded.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/HANDOFF-interval-lens.md
git commit -m "docs(handoff): what the workout-step change closed, and what it found"
```

---

## Self-Review

**Spec coverage.** §1–2 → Task 2. §3 → Task 3. §4 → Task 4. §5 and §5.2 → Task 5. §6 → Task 7. §7 → Task 8. §8 → Tasks 6 and 9. §9 → tests inside Tasks 2–5, §9.1 → Task 1. §10 (out of scope) → Task 10 Step 3, logged rather than built. No spec section is unimplemented.

**Ordering.** Task 1 must come first — Tasks 2–5 have no real-data coverage without it. Task 6 (the version bump) must follow every engine change and precede Task 9. Tasks 7 and 8 are frontend-only and independent of 2–6; they can be done in either order but not before Task 1, whose fixture file they do not touch.

**Type consistency.** `_lap_rep_segments(segments, laps)` and `_rep_step_indices(laps, work_idx)` are defined in Task 2 and referenced nowhere else. `load_workout(date)` and `build(date)` are defined in Task 1 and used in Tasks 2–5. `pg.uncalibrated` (Task 8) matches its `sc-for` list name. `.rep-head-pace` / `.rep-head-gap` (Task 7) match between markup and assertions. `UNCAL_DOC` carries `version: 4`, consistent with Task 6.

**Known blast radius on existing tests.** Exactly one existing test changes meaning: `test_fade_is_measured_on_effort_while_the_reported_pace_is_raw` → rewritten in Task 5 Step 1. The other 95 in `test_interval_lens.py` use `_lap`, which sets no `wktStepIndex`, so they take the rule's no-evidence branch. `test_lagrasse_strides_reclassify_as_a_block_not_five_reps` clears both block floors (3040 m / 790 s) and must stay green — verify rather than assume.