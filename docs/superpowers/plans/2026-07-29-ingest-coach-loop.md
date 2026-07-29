# Coach loop on the ingest path — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make an ingest-fed SPLITS instance derive the coach loop the way the Garmin path does — plan snapshots, compliance, block lens, the `insights`/`compliance`/`blockLens` telemetry keys, and `coach-briefing.md` — without changing a byte of what the Garmin path produces.

**Architecture:** Extract the four derive-and-render steps out of `sync_garmin.py` into a new `coach_pass.py` that both pipelines call. `ingest_builder.main()` inverts its order so the archive is current before the telemetry is assembled, keeping its "telemetry is written even if everything derived fails" guarantee through per-step fail-soft. Two contained fixes ride along: the trajectory's goal comes from the plan instead of a hardcoded constant, and the ingest path banks its own Riegel prediction so the goal-gap trend can start.

**Tech Stack:** Python 3.12 (stdlib + sqlite3), pytest for the Python suite, Node 20 for `.mjs` tests and the plan validator subprocess. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-29-ingest-coach-loop-design.md` (commit `ac26e4b`). Decisions are referenced below as D1–D7.

## Global Constraints

- **Never hand-edit `garmin-data.js`, `plan-data.js` or the archive db.** They are pipeline outputs; tests write their own temp copies.
- **The telemetry guarantee (D4):** `garmin-data.js` must be written even when the archive, the derive pass and every block assembly fail. Any task that breaks this is wrong regardless of what its own test says.
- **`max_hr` is passed in, never re-read from the environment inside `coach_pass`** (D-note in spec §4). The ingest path must score against the calibrated value from that same build.
- **Parity:** Felix's `garmin-data.js` must be byte-identical for the same inputs after the extraction. Asserted, not assumed (spec §5).
- Python tests are pytest-style plain functions at repo root, named `test_*.py`.
- Run Python as `./.venv/Scripts/python.exe` on this machine (`python3` is a Windows Store alias that fails when spawned).
- Commit messages: no `Co-Authored-By`, no AI attribution.
- Use `pnpm`, never `npm`, for any Node package work.

---

### Task 1: Record the parity golden and write the failing test

The extraction's whole risk is silently changing what the working instance emits. Capture the current behaviour first, as a committed fixture, so the refactor has something to be measured against.

**Files:**
- Create: `test_coach_pass.py`
- Create: `fixtures/coach-pass/golden-blocks.json`
- Create (scratch, NOT committed): `record_golden.py`

**Interfaces:**
- Produces: `fixtures/coach-pass/golden-blocks.json` — a dict with keys `insights`, `compliance`, `blockLens`, `courseLens` (the last is `null` for this fixture), plus `trend` (the string `insight_metrics.trend_verdict` returns, or `null`). Task 2 asserts `coach_pass.attach_blocks` reproduces it exactly.
- Produces: `test_coach_pass._fixture_archive(tmp) -> (conn, plan)` — used by Tasks 2, 3, 4 and 6.

- [ ] **Step 1: Write the fixture builder and the parity test**

Create `test_coach_pass.py`. The fixture is deliberately self-contained rather than imported from `test_block_lens.py`: a committed golden must never drift because an unrelated test file changed its seed data.

```python
"""Tests for coach_pass.py — the derive-and-render steps both pipelines share.

The golden in fixtures/coach-pass/golden-blocks.json was recorded from the
PRE-extraction sync_garmin.fetch_* helpers (see the plan, Task 1). It is the
parity contract: attach_blocks must reproduce it byte for byte, or the
extraction changed what the Garmin instance emits.
"""
import datetime as dt
import json
import tempfile
from pathlib import Path

import activity_archive as arch
import insight_metrics as im
import plan_compliance as pc

TODAY = dt.date(2026, 7, 16)
MAX_HR = 197
GOLDEN = Path(__file__).parent / "fixtures" / "coach-pass" / "golden-blocks.json"

PLAN = {
    "race": {"name": "Sonthofen Half", "date": "2026-08-09",
             "goalTime": "1:59:59", "goalPaceSecPerKm": 341},
    "block": [
        {"wk": "Wk 1", "label": "Jul 6", "mon": "2026-07-06", "sun": "2026-07-12",
         "phase": "Build", "km": 20, "long": "8 km", "focus": "Base", "days": [
             {"day": "Mon", "date": "2026-07-06", "kind": "run", "title": "Easy",
              "load": "Easy", "km": 5},
             {"day": "Tue", "date": "2026-07-07", "kind": "run", "title": "Easy",
              "load": "Easy", "km": 5},
             {"day": "Wed", "date": "2026-07-08", "kind": "rest", "title": "Rest",
              "load": "Easy", "km": 0},
             {"day": "Thu", "date": "2026-07-09", "kind": "run", "title": "Easy",
              "load": "Easy", "km": 5},
             {"day": "Fri", "date": "2026-07-10", "kind": "rest", "title": "Rest",
              "load": "Easy", "km": 0},
             {"day": "Sat", "date": "2026-07-11", "kind": "run", "title": "Long",
              "load": "Moderate", "km": 5},
             {"day": "Sun", "date": "2026-07-12", "kind": "rest", "title": "Rest",
              "load": "Easy", "km": 0},
         ]},
        {"wk": "Wk 2", "label": "Jul 13", "mon": "2026-07-13", "sun": "2026-07-19",
         "phase": "Build", "km": 11, "long": "6 km", "focus": "Hold", "days": [
             {"day": "Mon", "date": "2026-07-13", "kind": "run", "title": "Easy",
              "load": "Easy", "km": 6},
             {"day": "Tue", "date": "2026-07-14", "kind": "rest", "title": "Rest",
              "load": "Easy", "km": 0},
             {"day": "Wed", "date": "2026-07-15", "kind": "run", "title": "Easy",
              "load": "Easy", "km": 5},
             {"day": "Thu", "date": "2026-07-16", "kind": "rest", "title": "Rest",
              "load": "Easy", "km": 0},
             {"day": "Fri", "date": "2026-07-17", "kind": "rest", "title": "Rest",
              "load": "Easy", "km": 0},
             {"day": "Sat", "date": "2026-07-18", "kind": "rest", "title": "Rest",
              "load": "Easy", "km": 0},
             {"day": "Sun", "date": "2026-07-19", "kind": "rest", "title": "Rest",
              "load": "Easy", "km": 0},
         ]},
    ],
}

PLAN_RAW = "export const planData = " + json.dumps(PLAN) + ";\n"


def _act(aid, date, km, tk="running", hr=140):
    return {"activityId": aid, "startTimeLocal": f"{date} 08:00:00",
            "activityType": {"typeKey": tk}, "distance": km * 1000.0,
            "duration": km * 360.0, "averageHR": hr}


def _metrics(conn, aid, date, refhr=None, cad=None, best5k=None):
    arch.upsert_run_metrics(conn, {
        "activity_id": aid, "metrics_version": im.METRICS_VERSION,
        "start_time_local": f"{date} 08:00:00", "is_treadmill": 0,
        "best_5k_s": best5k, "refhr_pace_s_per_km": refhr,
        "refpace_cadence_spm": cad})


def _fixture_archive(tmp: Path):
    """A seeded archive + its plan: two scored weeks, metrics across three
    months (monthly_series needs more than one month to be non-empty), and two
    banked predictions so the trajectory has a line."""
    conn = arch.open_archive(tmp)
    arch.upsert_activities(conn, [
        _act(301, "2026-05-04", 5.0), _act(302, "2026-05-18", 5.0),
        _act(303, "2026-06-08", 5.0), _act(304, "2026-06-22", 8.0),
        _act(305, "2026-07-06", 5.0), _act(306, "2026-07-07", 3.0),
        _act(307, "2026-07-09", 5.2), _act(308, "2026-07-11", 5.0),
        _act(309, "2026-07-13", 6.0),
    ])
    _metrics(conn, 301, "2026-05-04", refhr=470, cad=163, best5k=1750)
    _metrics(conn, 302, "2026-05-18", refhr=466, cad=164)
    _metrics(conn, 303, "2026-06-08", refhr=460, cad=166, best5k=1700)
    _metrics(conn, 304, "2026-06-22", refhr=456, cad=167)
    _metrics(conn, 305, "2026-07-06", refhr=452, cad=168, best5k=1660)
    _metrics(conn, 307, "2026-07-09", refhr=449, cad=169)
    _metrics(conn, 309, "2026-07-13", refhr=447, cad=170)
    arch.upsert_race_prediction(conn, "2026-06-15", {"half_s": 7600}, {}, "test")
    arch.upsert_race_prediction(conn, "2026-07-13", {"half_s": 7400}, {}, "test")
    pc.run_compliance(conn, PLAN_RAW, PLAN, TODAY, MAX_HR)
    return conn, PLAN


def test_attach_blocks_matches_the_recorded_golden():
    """D1 parity: the extracted assembly must reproduce, exactly, what the four
    sync_garmin fetch_* helpers produced before the extraction."""
    import coach_pass

    conn, plan = _fixture_archive(Path(tempfile.mkdtemp()))
    data = {"predictions": {"halfGoal": "1:59:59", "trend": ""}}
    try:
        keys = coach_pass.attach_blocks(conn, plan, TODAY, data)
    finally:
        conn.close()
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert data.get("insights") == golden["insights"]
    assert data.get("compliance") == golden["compliance"]
    assert data.get("blockLens") == golden["blockLens"]
    assert data.get("courseLens") == golden["courseLens"]
    assert data["predictions"]["trend"] == (golden["trend"] or "")
    assert set(keys) == {k for k in ("insights", "compliance", "blockLens",
                                     "courseLens") if golden[k] is not None}
```

- [ ] **Step 2: Write the throwaway recorder**

This runs against the CURRENT code, before `coach_pass` exists. Create `record_golden.py` at repo root — it is deleted in Step 5, never committed.

```python
"""One-shot: record fixtures/coach-pass/golden-blocks.json from the PRE-extraction
sync_garmin.fetch_* helpers. Delete after running."""
import json
import tempfile
from pathlib import Path

import insight_metrics as im
import sync_garmin as sg
from test_coach_pass import PLAN_RAW, TODAY, _fixture_archive

tmp = Path(tempfile.mkdtemp())
conn, plan = _fixture_archive(tmp)
conn.close()
(tmp / "plan-data.js").write_text(PLAN_RAW, encoding="utf-8")

sg.DATA_DIR = tmp
sg.TODAY = TODAY

insights = sg.fetch_insights()
trend = im.trend_verdict(insights["trajectory"]["weekly"]) if insights else None
out = {
    "insights": insights,
    "compliance": sg.fetch_compliance(),
    "blockLens": sg.fetch_block_lens(),
    "courseLens": sg.fetch_course_lens(),
    "trend": trend or None,
}
dest = Path("fixtures/coach-pass/golden-blocks.json")
dest.parent.mkdir(parents=True, exist_ok=True)
dest.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("recorded", dest, {k: (v is not None) for k, v in out.items()})
```

- [ ] **Step 3: Run the recorder**

Run: `./.venv/Scripts/python.exe record_golden.py`

Expected: `recorded fixtures\coach-pass\golden-blocks.json {'insights': True, 'compliance': True, 'blockLens': True, 'courseLens': False, 'trend': ...}`

If `insights` is `False`, the fixture has too few months of `run_metrics` — `insight_metrics.monthly_series` returned empty and `assemble_insights` raised. Add another month of `_metrics` rows and re-run. Do not proceed with a golden whose `insights` is null; it would make the parity test vacuous.

- [ ] **Step 4: Run the parity test to verify it fails for the right reason**

Run: `./.venv/Scripts/python.exe -m pytest test_coach_pass.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'coach_pass'` — not an assertion error. An assertion error here means the golden was recorded from a different fixture than the test builds.

- [ ] **Step 5: Delete the recorder and commit**

```bash
rm record_golden.py
git add test_coach_pass.py fixtures/coach-pass/golden-blocks.json
git commit -m "test(coach-pass): record the pre-extraction parity golden

The four sync_garmin fetch_* helpers, captured against a seeded fixture
archive before coach_pass exists. attach_blocks has to reproduce this
exactly or the extraction changed what the Garmin instance emits."
```

---

### Task 2: `coach_pass.attach_blocks`

**Files:**
- Create: `coach_pass.py`
- Test: `test_coach_pass.py` (extend)

**Interfaces:**
- Consumes: `test_coach_pass._fixture_archive`, the golden from Task 1.
- Produces: `coach_pass.attach_blocks(conn, plan, today, data, log=_noop) -> list[str]`. Mutates `data` in place, adding any of `insights`, `compliance`, `blockLens`, `courseLens` that assemble, and setting `data["predictions"]["trend"]` when `trend_verdict` returns a non-empty verdict. Returns the key names added. `plan=None` is legal and omits only the plan-dependent blocks.
- Produces: `coach_pass._noop(msg)` — the default logger, used by Tasks 3 and 4.

- [ ] **Step 1: Write the module**

```python
"""coach_pass.py — the coach loop's derived state, for every pipeline.

Both producers of `garmin-data.js` must derive compliance, the block lens and
the insights block IDENTICALLY: the Garmin sync (sync_garmin.py) and the Health
Connect builder (ingest_builder.py). This module is the single definition of
that work, for the same reason interval_lens.zone_bounds is the single
definition of a zone boundary — two copies is how two instances start
disagreeing about the athlete's week.

Nothing here reads the environment or the clock: `today`, `max_hr` and the
parsed plan are always passed in, so both pipelines derive from exactly the
values they built their telemetry with.
"""
import activity_archive
import block_lens
import coach_briefing
import insight_metrics
import plan_compliance


def _noop(_msg: str) -> None:
    pass


def _safe(fn, label: str, log):
    """Run an assembly, returning None (and warning) if it throws. Each block is
    an independent fail domain (design D4): a dead trajectory must not take the
    compliance block down with it."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 — resilience is the point here
        log(f"  ! {label} failed ({type(e).__name__}: {e}); block omitted")
        return None


def attach_blocks(conn, plan, today, data, log=_noop) -> list[str]:
    """Assemble every archive-derived block into `data` and fill
    predictions.trend from the trajectory. Returns the keys attached.

    `plan` may be None (unreadable plan file): the plan-dependent blocks are
    then omitted and insights/blockLens still assemble."""
    attached = []

    insights = _safe(lambda: insight_metrics.assemble_insights(conn, today),
                     "insights assembly", log)
    if insights:
        data["insights"] = insights
        attached.append("insights")
        trend = insight_metrics.trend_verdict(insights["trajectory"]["weekly"])
        if trend:
            data.setdefault("predictions", {})["trend"] = trend
        log(f"✓ insights assembled ({len(insights['efficiency']['monthly'])} months, "
            f"{len(insights['trajectory']['weekly'])} weeks)")

    if plan:
        compliance = _safe(
            lambda: plan_compliance.assemble_compliance(conn, plan, today),
            "compliance assembly", log)
        if compliance:
            data["compliance"] = compliance
            attached.append("compliance")
            log(f"✓ compliance assembled ({len(compliance['days'])} days, "
                f"{len(compliance['weeks'])} weeks)")

    lens = _safe(lambda: block_lens.assemble_block_lens(conn, today),
                 "block lens assembly", log)
    if lens:
        data["blockLens"] = lens
        attached.append("blockLens")
        log("✓ block lens assembled ("
            + ("current + " if lens.get("current") else "")
            + f"{len(lens['past'])} past)")

    if plan:
        course = _safe(lambda: _course(conn, plan), "course lens assembly", log)
        if course:
            data["courseLens"] = course
            attached.append("courseLens")

    return attached


def _course(conn, plan):
    """The stored course document for the plan's race, or None — a race without
    a `courseId` has no course, which is the normal state."""
    course_id = ((plan or {}).get("race") or {}).get("courseId")
    if not course_id:
        return None
    doc = activity_archive.course_document(conn, course_id)
    if doc:
        doc["map"] = activity_archive.course_map_row(conn, course_id)
    return doc
```

- [ ] **Step 2: Run the parity test**

Run: `./.venv/Scripts/python.exe -m pytest test_coach_pass.py -v`

Expected: PASS.

If `compliance` differs, check that `assemble_compliance` is being given the same `today`. If `insights` differs, the golden was recorded against a different fixture — re-record rather than editing the golden by hand.

- [ ] **Step 3: Add the fail-domain and no-plan tests**

Append to `test_coach_pass.py`:

```python
def test_one_dead_assembly_omits_only_its_own_key(monkeypatch):
    """D4: an exception assembling one block must not take the others down."""
    import coach_pass
    import insight_metrics as im2

    def boom(*_a, **_k):
        raise ValueError("no run_metrics rows at the current METRICS_VERSION")

    monkeypatch.setattr(im2, "assemble_insights", boom)
    conn, plan = _fixture_archive(Path(tempfile.mkdtemp()))
    data = {"predictions": {}}
    try:
        keys = coach_pass.attach_blocks(conn, plan, TODAY, data)
    finally:
        conn.close()
    assert "insights" not in data and "insights" not in keys
    assert "compliance" in data, "a dead trajectory must not kill compliance"
    assert "blockLens" in data


def test_no_plan_still_assembles_the_plan_free_blocks():
    """An unreadable plan-data.js omits compliance and courseLens only."""
    import coach_pass

    conn, _plan = _fixture_archive(Path(tempfile.mkdtemp()))
    data = {"predictions": {}}
    try:
        keys = coach_pass.attach_blocks(conn, None, TODAY, data)
    finally:
        conn.close()
    assert "compliance" not in keys and "courseLens" not in keys
    assert "insights" in keys and "blockLens" in keys
```

- [ ] **Step 4: Run the tests**

Run: `./.venv/Scripts/python.exe -m pytest test_coach_pass.py -v`

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add coach_pass.py test_coach_pass.py
git commit -m "feat(coach-pass): one definition of the derived blocks

attach_blocks assembles insights, compliance, blockLens and courseLens into
the telemetry dict, each an independent fail domain, and fills
predictions.trend from the trajectory. Reproduces the recorded golden
exactly."
```

---

### Task 3: `coach_pass.derive`

**Files:**
- Modify: `coach_pass.py`
- Test: `test_coach_pass.py` (extend)

**Interfaces:**
- Consumes: `coach_pass._noop`.
- Produces: `coach_pass.derive(conn, plan_raw, plan, today, max_hr, log=_noop) -> dict` with keys `weeks_scored`, `weeks_healed`, `blocks`, `recomputed`. Banks the plan snapshot, rescores compliance, ratchets `expected_compliance_weeks`, and refreshes the block-lens rows. Task 5 and Task 7 both call it.

- [ ] **Step 1: Write the failing test**

```python
def test_derive_banks_a_snapshot_and_scores_the_weeks():
    """D1: the archive-writing half of the pass — what compliance_step and
    block_lens_step did, in one place."""
    import coach_pass

    tmp = Path(tempfile.mkdtemp())
    conn = arch.open_archive(tmp)
    arch.upsert_activities(conn, [
        _act(401, "2026-07-06", 5.0), _act(402, "2026-07-07", 5.0),
        _act(403, "2026-07-09", 5.0), _act(404, "2026-07-11", 5.0),
    ])
    stats = coach_pass.derive(conn, PLAN_RAW, PLAN, TODAY, MAX_HR)
    snapshots = conn.execute("SELECT COUNT(*) FROM plan_snapshots").fetchone()[0]
    scored = conn.execute("SELECT COUNT(*) FROM plan_compliance").fetchone()[0]
    ratchet = arch.get_meta(conn, "expected_compliance_weeks")
    conn.close()
    assert snapshots == 1, "today's plan text banked once"
    assert scored > 0 and stats["weeks_scored"] > 0
    assert int(ratchet) == stats["weeks_scored"]
    assert "blocks" in stats and "recomputed" in stats
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest test_coach_pass.py::test_derive_banks_a_snapshot_and_scores_the_weeks -v`

Expected: FAIL with `AttributeError: module 'coach_pass' has no attribute 'derive'`.

- [ ] **Step 3: Implement `derive`**

Add to `coach_pass.py`, above `attach_blocks`. The bodies move verbatim from `sync_garmin.compliance_step` and `sync_garmin.block_lens_step`; only the connection handling and the `max_hr` source change.

```python
def derive(conn, plan_raw, plan, today, max_hr, log=_noop) -> dict:
    """Bank today's plan snapshot, rescore compliance, refresh the block-lens
    rows. Writes the archive; assembles nothing.

    Runs AFTER the archive is current (it matches against archived activities)
    and BEFORE the telemetry is assembled (attach_blocks reads what this
    wrote). The caller wraps it fail-soft: a plan problem is a warning, never a
    failed build."""
    stats = plan_compliance.run_compliance(conn, plan_raw, plan, today, max_hr)

    # Ratchet the coverage expectation --verify-archive checks against: scored
    # weeks only ever accumulate, so a shrink is a regression.
    weeks_now = activity_archive.compliance_coverage(
        conn, plan_compliance.COMPLIANCE_VERSION)["weeks_scored"]
    prev = activity_archive.get_meta(conn, "expected_compliance_weeks")
    if weeks_now > int(prev or 0):
        activity_archive.set_meta(conn, "expected_compliance_weeks", weeks_now)

    parts = [f"{stats['weeks_scored']} weeks scored"]
    if stats["weeks_healed"]:
        parts.append(f"{stats['weeks_healed']} stale weeks healed")
    log("✓ compliance: " + ", ".join(parts))

    lens = block_lens.derive_block_lens(conn, today)
    if lens["blocks"]:
        log(f"✓ block lens: {lens['blocks']} blocks, {lens['recomputed']} recomputed")
    else:
        log("✓ block lens: no plan snapshots — nothing to derive")

    return {**stats, **lens}
```

- [ ] **Step 4: Run the tests**

Run: `./.venv/Scripts/python.exe -m pytest test_coach_pass.py -v`

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add coach_pass.py test_coach_pass.py
git commit -m "feat(coach-pass): derive banks the snapshot and scores the block

compliance_step and block_lens_step, moved verbatim into the shared module.
max_hr is a parameter now, not an env read — the ingest path must score
against the calibrated value from its own build."
```

---

### Task 4: `coach_pass.briefing`

**Files:**
- Modify: `coach_pass.py`
- Test: `test_coach_pass.py` (extend)

**Interfaces:**
- Produces: `coach_pass.briefing(conn, plan, data, today, path, log=_noop) -> bool` — renders and atomically publishes the briefing, returning False when `plan` is falsy.

- [ ] **Step 1: Write the failing test**

```python
def test_briefing_publishes_atomically():
    """D1: rendering moves too, so /coach reads the same document on both
    instances. write_briefing's temp-file-then-rename is what makes a reader
    (or a crash) unable to observe half a briefing."""
    import coach_pass

    tmp = Path(tempfile.mkdtemp())
    conn, plan = _fixture_archive(tmp)
    data = {"profile": {"maxHR": MAX_HR, "restingHR": 47}, "today": TODAY.isoformat()}
    coach_pass.attach_blocks(conn, plan, TODAY, data)
    dest = tmp / "coach-briefing.md"
    try:
        ok = coach_pass.briefing(conn, plan, data, TODAY, dest)
    finally:
        conn.close()
    text = dest.read_text(encoding="utf-8")
    assert ok is True
    assert text.startswith(f"# Coach Briefing — {TODAY.isoformat()}")
    assert "## Plan vs actual" in text
    assert "insights unavailable" not in text, \
        "the fixture has insights; the briefing must show them"
    assert not list(tmp.glob(".coach-briefing-*.tmp")), "no temp file left behind"


def test_briefing_without_a_plan_is_a_no_op():
    import coach_pass

    tmp = Path(tempfile.mkdtemp())
    conn, _plan = _fixture_archive(tmp)
    dest = tmp / "coach-briefing.md"
    try:
        assert coach_pass.briefing(conn, None, {}, TODAY, dest) is False
    finally:
        conn.close()
    assert not dest.exists()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest test_coach_pass.py -k briefing -v`

Expected: FAIL with `AttributeError: module 'coach_pass' has no attribute 'briefing'`.

- [ ] **Step 3: Implement `briefing`**

```python
def briefing(conn, plan, data, today, path, log=_noop) -> bool:
    """Render coach-briefing.md and publish it atomically. False when there is
    no plan to render against.

    Runs strictly AFTER the telemetry file is written — a briefing problem can
    never affect the contract file."""
    if not plan:
        return False
    coach_briefing.write_briefing(
        path, coach_briefing.render_briefing(conn, plan, data, today))
    log("✓ coach briefing written")
    return True
```

- [ ] **Step 4: Run the tests**

Run: `./.venv/Scripts/python.exe -m pytest test_coach_pass.py -v`

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add coach_pass.py test_coach_pass.py
git commit -m "feat(coach-pass): render and publish the briefing"
```

---

### Task 5: Rewire `sync_garmin` onto `coach_pass`

The riskiest task. Nothing about Felix's output may change.

**Files:**
- Modify: `sync_garmin.py` — delete `fetch_insights`, `fetch_compliance`, `fetch_block_lens`, `fetch_course_lens` (lines ~971–1034); rewrite `compliance_step` (~1313), `block_lens_step` (~1342), `briefing_step` (~1389); rewrite the block-assembly section of `build_data` (~1055–1104).
- Create (scratch, NOT committed): `parity_real.py`

**Interfaces:**
- Consumes: `coach_pass.derive`, `coach_pass.attach_blocks`, `coach_pass.briefing`.
- Produces: no new public names. `sync_garmin.main()`'s step sequence is unchanged.

- [ ] **Step 1: Record the real-archive "before" snapshot**

The committed golden proves parity on a synthetic fixture. This proves it on Felix's actual 165-run archive, which is the one that matters. Create `parity_real.py` at repo root:

```python
"""Scratch: dump the four derived blocks from the REAL local archive, so the
extraction can be diffed before/after. Works against either code generation —
it prefers coach_pass and falls back to the old fetch_* helpers. Not committed."""
import datetime as dt
import json
import shutil
import sys
import tempfile
from pathlib import Path

import activity_archive as arch
import insight_metrics as im
import plan_compliance as pc
import sync_garmin as sg

TODAY = dt.date(2026, 7, 27)          # inside the local archive's coverage
src = Path("activity-archive.db")     # the repo-root copy, refreshed 2026-07-11
tmp = Path(tempfile.mkdtemp())
shutil.copy(src, tmp / arch.DB_NAME)
shutil.copy(Path(sys.argv[1]), tmp / "plan-data.js")   # argv[1] = Felix's plan

sg.DATA_DIR = tmp
sg.TODAY = TODAY
loaded = pc.load_plan(tmp / "plan-data.js")
assert loaded, "plan failed to load — parity cannot be measured"
raw, plan = loaded

try:
    import coach_pass
    conn = arch.open_archive(tmp)
    data = {"predictions": {"trend": ""}}
    coach_pass.attach_blocks(conn, plan, TODAY, data)
    conn.close()
    out = {"insights": data.get("insights"), "compliance": data.get("compliance"),
           "blockLens": data.get("blockLens"), "courseLens": data.get("courseLens"),
           "trend": data["predictions"]["trend"] or None}
    tag = "after"
except ImportError:
    insights = sg.fetch_insights()
    out = {"insights": insights,
           "compliance": sg.fetch_compliance(),
           "blockLens": sg.fetch_block_lens(),
           "courseLens": sg.fetch_course_lens(),
           "trend": (im.trend_verdict(insights["trajectory"]["weekly"])
                     if insights else None) or None}
    tag = "before"

dest = Path(f"parity-{tag}.json")
dest.write_text(json.dumps(out, indent=2, sort_keys=True, ensure_ascii=False),
                encoding="utf-8")
print(tag, "→", dest, {k: (v is not None) for k, v in out.items()})
```

Get Felix's plan and record the "before" — `coach_pass.py` already exists at this point, so temporarily force the fallback by running with it hidden:

```bash
ssh nuc "docker exec splits cat /data/plan-data.js" > felix-plan.js
mv coach_pass.py coach_pass.py.hidden
./.venv/Scripts/python.exe parity_real.py felix-plan.js
mv coach_pass.py.hidden coach_pass.py
```

Expected: `before → parity-before.json {'insights': True, 'compliance': True, 'blockLens': True, ...}`

- [ ] **Step 2: Delete the four `fetch_*` helpers**

In `sync_garmin.py`, delete `fetch_insights`, `fetch_compliance`, `fetch_block_lens` and `fetch_course_lens` entirely (spec §4 — deleted, not wrapped).

- [ ] **Step 3: Rewrite `build_data`'s block section**

Replace the assembly block at the top of `build_data` (the `insights = fetch_insights()` … `lens = fetch_block_lens()` … `course = fetch_course_lens()` sequence) — delete it — and replace the tail of the function (`if insights: data["insights"] = insights` through `data["courseLens"] = course`) with one call:

```python
    conn = activity_archive.open_archive(DATA_DIR)
    try:
        loaded = plan_compliance.load_plan(DATA_DIR / "plan-data.js")
        coach_pass.attach_blocks(conn, loaded[1] if loaded else None,
                                 TODAY, data, log=log)
    finally:
        conn.close()
    return data
```

`predictions` is the same dict object `data["predictions"]` refers to, so `attach_blocks` setting the trend on `data` reaches it exactly as the old in-place assignment did.

Add `import coach_pass` to the import block (alphabetical: after `block_lens`, before `coach_briefing`).

- [ ] **Step 4: Rewrite the three steps as thin wrappers**

```python
def compliance_step() -> None:
    """Bank today's plan snapshot and rescore compliance (coach-loop design
    D2/D3). Runs AFTER the archive step and BEFORE build_data; only ever inside
    safe() — a plan problem is a warning, never a failed sync."""
    loaded = plan_compliance.load_plan(DATA_DIR / "plan-data.js")
    if not loaded:
        return
    raw, plan = loaded
    conn = activity_archive.open_archive(DATA_DIR)
    try:
        coach_pass.derive(conn, raw, plan, TODAY,
                          int(os.getenv("ATHLETE_MAX_HR", "197")), log=log)
    finally:
        conn.close()


def briefing_step(data: dict) -> None:
    """Render coach-briefing.md into the data dir (coach-loop design D6). Runs
    strictly AFTER garmin-data.js is written and only ever inside safe()."""
    loaded = plan_compliance.load_plan(DATA_DIR / "plan-data.js")
    if not loaded:
        return
    conn = activity_archive.open_archive(DATA_DIR)
    try:
        coach_pass.briefing(conn, loaded[1], data, TODAY,
                            DATA_DIR / "coach-briefing.md", log=log)
    finally:
        conn.close()
```

Delete `block_lens_step` entirely — `derive` now does both halves — and remove its line from `main()`:

```python
    safe(compliance_step, None, "compliance step")
    safe(lambda: course_lens_step(client), None, "course lens step")
```

Update the ordering comment above that sequence: the block lens is no longer its own step, it is the second half of the compliance step.

- [ ] **Step 5: Run the full Python suite**

Run: `./.venv/Scripts/python.exe -m pytest test_coach_pass.py test_plan_compliance.py test_block_lens.py test_coach_briefing.py test_activity_archive.py -q`

Expected: all pass. These four existing suites are the regression net for the extraction — a failure here means behaviour moved, not just code.

- [ ] **Step 6: Record the real-archive "after" snapshot and diff**

```bash
./.venv/Scripts/python.exe parity_real.py felix-plan.js
./.venv/Scripts/python.exe -c "import json;a=json.load(open('parity-before.json'));b=json.load(open('parity-after.json'));print('IDENTICAL' if a==b else 'DIFFERS');import sys;sys.exit(0 if a==b else 1)"
```

Expected: `IDENTICAL`. If it differs, dump both to files and diff them — do not proceed. The most likely cause is `attach_blocks` being handed a `plan` where the old code loaded its own.

- [ ] **Step 7: Clean up scratch files and commit**

```bash
rm parity_real.py parity-before.json parity-after.json felix-plan.js
git add sync_garmin.py
git commit -m "refactor(sync): derive the coach blocks through coach_pass

The four fetch_* helpers and block_lens_step are gone; compliance_step and
briefing_step delegate, and build_data attaches all four blocks in one call
on one archive connection instead of four.

Verified identical on the real 165-run archive, not just the fixture."
```

---

### Task 6: The trajectory goal comes from the plan (D5)

**Files:**
- Modify: `insight_metrics.py:441` (`assemble_insights` signature and the trajectory dict)
- Modify: `coach_pass.py` (`attach_blocks` passes it)
- Test: `test_coach_pass.py` (extend)

**Interfaces:**
- Produces: `insight_metrics.assemble_insights(conn, today=None, goal_sec=None) -> dict` — `goal_sec=None` keeps `GOAL_HALF_S` as the fallback.

- [ ] **Step 1: Write the failing test**

```python
def test_goal_seconds_come_from_the_plan_not_the_constant():
    """D5: GOAL_HALF_S is one athlete's goal. The trajectory must measure each
    instance against its own plan."""
    import coach_pass

    conn, plan = _fixture_archive(Path(tempfile.mkdtemp()))
    slow = json.loads(json.dumps(plan))
    slow["race"]["goalTime"] = "2:29:59"
    data = {"predictions": {}}
    try:
        coach_pass.attach_blocks(conn, slow, TODAY, data)
    finally:
        conn.close()
    assert data["insights"]["trajectory"]["goalSec"] == 8999


def test_unparseable_goal_falls_back_to_the_constant():
    import coach_pass
    import insight_metrics as im3

    conn, plan = _fixture_archive(Path(tempfile.mkdtemp()))
    junk = json.loads(json.dumps(plan))
    junk["race"]["goalTime"] = "as fast as possible"
    data = {"predictions": {}}
    try:
        coach_pass.attach_blocks(conn, junk, TODAY, data)
    finally:
        conn.close()
    assert data["insights"]["trajectory"]["goalSec"] == im3.GOAL_HALF_S
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest test_coach_pass.py -k goal -v`

Expected: FAIL — `assert 7199 == 8999`.

- [ ] **Step 3: Thread `goal_sec` through**

In `insight_metrics.py`:

```python
def assemble_insights(conn, today: dt.date | None = None,
                      goal_sec: int | None = None) -> dict:
    """The complete `insights` block per design D9, or an exception — the
    caller omits the block entirely rather than emitting a partial one.

    `goal_sec` is this instance's goal, parsed from the plan's race.goalTime;
    GOAL_HALF_S is only the fallback for a caller that has no plan."""
```

and in its returned dict:

```python
        "trajectory": {"goalSec": goal_sec or GOAL_HALF_S,
                       "weekly": weekly_trajectory(conn, today)},
```

In `coach_pass.py`, replace the insights call inside `attach_blocks`:

```python
    goal_sec = block_lens.parse_goal_seconds(
        ((plan or {}).get("race") or {}).get("goalTime"))
    insights = _safe(
        lambda: insight_metrics.assemble_insights(conn, today, goal_sec),
        "insights assembly", log)
```

- [ ] **Step 4: Run the tests**

Run: `./.venv/Scripts/python.exe -m pytest test_coach_pass.py test_block_lens.py -q`

Expected: all pass. The parity golden still passes because the fixture plan's goal is `1:59:59` → 7199, which is what `GOAL_HALF_S` was.

- [ ] **Step 5: Commit**

```bash
git add insight_metrics.py coach_pass.py test_coach_pass.py
git commit -m "fix(insights): the trajectory goal comes from the plan

GOAL_HALF_S = 7199 is one athlete's sub-2:00. Max's goal is 2:29:59, and
Felix's would go wrong the day he re-anchors it in the plan. The constant
stays as the fallback for a caller with no plan."
```

---

### Task 7: Reorder `ingest_builder.main()` behind the telemetry guarantee

**Files:**
- Modify: `ingest_builder.py` — `main()` (~960–1015), delete `_plan_goal` (~934–945)
- Test: `test_ingest_builder.py` (extend)

**Interfaces:**
- Consumes: `coach_pass.derive`, `coach_pass.attach_blocks`, `coach_pass.briefing`.
- Produces: no new public names. `build_athlete_data`'s signature is unchanged — `plan_goal` is still a parameter, it just comes from the parsed plan now (D7).

- [ ] **Step 1: Write the failing tests**

Note on the clock: `main()` reads `dt.date.today()` — unlike `build_athlete_data`, it has no injectable `today`, so these three tests exercise the real date. The fixture plan's week (2026-07-13…19) is closed and its race date is in the past, which keeps compliance scoreable and the block-lens row derivable whenever the suite runs. If the `blockLens` assertion ever turns flaky, the fix is to give `main()` an injectable `today` — not to weaken the assertion.

```python
def test_main_derives_the_coach_blocks_and_writes_the_briefing():
    # D3 — the ingest build derives what the Garmin build derives.
    import json as _json
    import os
    import tempfile
    from pathlib import Path

    import ingest_builder

    plan = {
        "race": {"name": "First Half", "date": "2026-09-06",
                 "goalTime": "2:29:59", "goalPaceSecPerKm": 427},
        "block": [{"wk": "Wk 1", "label": "Jul 13", "mon": "2026-07-13",
                   "sun": "2026-07-19", "phase": "Base", "km": 11, "long": "6 km",
                   "focus": "Start", "days": [
                       {"day": "Mon", "date": "2026-07-13", "kind": "run",
                        "title": "Easy", "load": "Easy", "km": 6},
                       {"day": "Tue", "date": "2026-07-14", "kind": "rest",
                        "title": "Rest", "load": "Easy", "km": 0},
                       {"day": "Wed", "date": "2026-07-15", "kind": "run",
                        "title": "Easy", "load": "Easy", "km": 5},
                       {"day": "Thu", "date": "2026-07-16", "kind": "rest",
                        "title": "Rest", "load": "Easy", "km": 0},
                       {"day": "Fri", "date": "2026-07-17", "kind": "rest",
                        "title": "Rest", "load": "Easy", "km": 0},
                       {"day": "Sat", "date": "2026-07-18", "kind": "rest",
                        "title": "Rest", "load": "Easy", "km": 0},
                       {"day": "Sun", "date": "2026-07-19", "kind": "rest",
                        "title": "Rest", "load": "Easy", "km": 0}]}],
    }
    with tempfile.TemporaryDirectory() as td:
        store = {r["sessionUid"]: r for r in RUNS}
        Path(td, "ingested-runs.json").write_text(_json.dumps(store), encoding="utf-8")
        Path(td, "plan-data.js").write_text(
            "export const planData = " + _json.dumps(plan) + ";\n", encoding="utf-8")
        old = os.environ.get("SPLITS_DATA_DIR")
        os.environ["SPLITS_DATA_DIR"] = td
        try:
            ingest_builder.main()
        finally:
            if old is None:
                os.environ.pop("SPLITS_DATA_DIR", None)
            else:
                os.environ["SPLITS_DATA_DIR"] = old
        out = Path(td, "garmin-data.js").read_text(encoding="utf-8")
        assert '"compliance"' in out, "compliance must land in the telemetry"
        assert '"blockLens"' in out
        assert Path(td, "coach-briefing.md").exists(), "/coach needs a briefing"
        brief = Path(td, "coach-briefing.md").read_text(encoding="utf-8")
        assert "## Plan vs actual" in brief
        # D7 — the goal reaches predictions without the retired regex
        assert '"halfGoal": "2:29:59"' in out


def test_an_unreadable_plan_still_yields_telemetry():
    # D4 — the telemetry guarantee, plan half.
    import json as _json
    import os
    import tempfile
    from pathlib import Path

    import ingest_builder

    with tempfile.TemporaryDirectory() as td:
        store = {r["sessionUid"]: r for r in RUNS}
        Path(td, "ingested-runs.json").write_text(_json.dumps(store), encoding="utf-8")
        Path(td, "plan-data.js").write_text("this is not javascript {{{",
                                            encoding="utf-8")
        old = os.environ.get("SPLITS_DATA_DIR")
        os.environ["SPLITS_DATA_DIR"] = td
        try:
            ingest_builder.main()
        finally:
            if old is None:
                os.environ.pop("SPLITS_DATA_DIR", None)
            else:
                os.environ["SPLITS_DATA_DIR"] = old
        out = Path(td, "garmin-data.js").read_text(encoding="utf-8")
        assert '"recentRuns"' in out, "telemetry lands even with a broken plan"
        assert '"compliance"' not in out


def test_a_failing_archive_still_yields_telemetry(monkeypatch):
    # D4 — the telemetry guarantee, archive half. This is the property the old
    # ordering got for free by writing telemetry first.
    import json as _json
    import os
    import tempfile
    from pathlib import Path

    import ingest_builder

    def boom(*_a, **_k):
        raise RuntimeError("archive is wedged")

    monkeypatch.setattr(ingest_builder, "build_archive", boom)
    with tempfile.TemporaryDirectory() as td:
        store = {r["sessionUid"]: r for r in RUNS}
        Path(td, "ingested-runs.json").write_text(_json.dumps(store), encoding="utf-8")
        old = os.environ.get("SPLITS_DATA_DIR")
        os.environ["SPLITS_DATA_DIR"] = td
        try:
            ingest_builder.main()
        finally:
            if old is None:
                os.environ.pop("SPLITS_DATA_DIR", None)
            else:
                os.environ["SPLITS_DATA_DIR"] = old
        assert '"recentRuns"' in Path(td, "garmin-data.js").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest test_ingest_builder.py -k "coach_blocks or unreadable_plan or failing_archive" -v`

Expected: the first two FAIL on the missing `"compliance"` / `halfGoal` assertions; the third FAILS because `build_archive` raising currently happens after the write, so it may already pass — confirm it passes for the *right* reason after Step 3, not before.

- [ ] **Step 3: Rewrite `main()`**

Replace the body of `main()` from the `calibration = ...` line to the end with:

```python
    calibration = _calibration(runs, profile, rhr_days)
    max_hr = calibration[0]
    today = dt.date.today()

    # D7 — one plan load per build: the goal for predictions.halfGoal and the
    # goal for the trajectory come from the same parsed object.
    loaded = _safe(lambda: plan_compliance.load_plan(data_dir / "plan-data.js"),
                   "plan load")
    plan_raw, plan = loaded if loaded else (None, None)
    plan_goal = ((plan or {}).get("race") or {}).get("goalTime")

    # D3 — the archive must be current before compliance and insights read it,
    # and both must be derived before the telemetry is assembled. D4 — every
    # step here is fail-soft and the write below is unconditional, so the
    # telemetry lands even if all of them fail.
    _safe(lambda: build_archive(
        data_dir, runs, profile, rhr_days,
        prune_uids=[loser["sessionUid"] for loser, _ in duplicates],
        calibration=calibration), "archive pass")

    data = build_athlete_data(runs, profile, today, plan_goal,
                              rhr_days=rhr_days, calibration=calibration)

    if activity_archive.archive_path(data_dir).exists():
        conn = activity_archive.open_archive(data_dir)
        try:
            if plan:
                _safe(lambda: coach_pass.derive(conn, plan_raw, plan, today,
                                                max_hr, log=_log), "derive pass")
            _safe(lambda: coach_pass.attach_blocks(conn, plan, today, data,
                                                   log=_log), "block assembly")
        finally:
            conn.close()

    tmp = data_dir / f".garmin-data.{os.getpid()}.tmp.js"
    tmp.write_text(build_garmin_data_js(data), encoding="utf-8")
    tmp.replace(data_dir / "garmin-data.js")
    print(f"✓ built garmin-data.js from {len(runs)} ingested run(s)", flush=True)

    # strictly after the write — a briefing problem can never affect the
    # contract file
    if plan and activity_archive.archive_path(data_dir).exists():
        conn = activity_archive.open_archive(data_dir)
        try:
            _safe(lambda: coach_pass.briefing(
                conn, plan, data, today, data_dir / "coach-briefing.md",
                log=_log), "coach briefing")
        finally:
            conn.close()
```

Add the module-level helpers above `main()`:

```python
def _log(msg: str) -> None:
    print(msg, flush=True)


def _safe(fn, label: str):
    """Run a derived step, returning None (and warning) if it throws. The
    telemetry build is never sunk by anything derived from it (design D4)."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 — resilience is the point here
        print(f"  ! {label} failed ({type(e).__name__}: {e}) — "
              f"telemetry build unaffected", file=sys.stderr, flush=True)
        return None
```

Add to the imports at the top of `ingest_builder.py`: `import coach_pass` and `import plan_compliance` (`activity_archive` is already imported). Delete `_plan_goal` and, if `re` is now unused, its import — check with `grep -n "re\." ingest_builder.py` before removing it.

The archive-existence guard matters: a zero-run instance must stay unprovisioned (`test_zero_runs_leaves_the_instance_unprovisioned` asserts the db is never created), so the derive pass must not be what creates it.

- [ ] **Step 4: Run the ingest suite**

Run: `./.venv/Scripts/python.exe -m pytest test_ingest_builder.py -q`

Expected: all pass, including the three new tests and the existing 56.

- [ ] **Step 5: Run the Node-side ingest tests**

Run: `node test_ingest_e2e.mjs && node test_build_watchdog.mjs && node test_ingest_api.mjs`

Expected: all pass. These cover the server's build trigger and the watchdog, which now supervise a longer build.

- [ ] **Step 6: Commit**

```bash
git add ingest_builder.py test_ingest_builder.py
git commit -m "feat(ingest): derive the coach loop on the ingest path

main() inverts its order — archive, derive, assemble, write, brief — so
compliance and insights read a current archive and land in the telemetry.
Every derived step is fail-soft and the write is unconditional, so the
telemetry guarantee the old ordering got for free is kept explicitly.

_plan_goal's regex is retired: the plan is parsed once, and halfGoal and the
trajectory goal come from the same object."
```

---

### Task 8: Bank the ingest path's own prediction (D6)

**Files:**
- Modify: `ingest_builder.py` — extract `_riegel_seconds` out of `predictions` (~459), bank it in `main()`
- Test: `test_ingest_builder.py` (extend)

**Interfaces:**
- Produces: `ingest_builder._riegel_seconds(runs) -> dict | None` with keys `time_5k_s`, `time_10k_s`, `half_s`, `marathon_s` — the promoted shape `activity_archive.upsert_race_prediction` expects.
- Produces: `ingest_builder.MARATHON_KM = 42.195`.

- [ ] **Step 1: Write the failing test**

```python
def test_the_ingest_path_banks_its_own_prediction():
    # D6 — race_predictions is empty on ingest instances, so the goal-gap trend
    # would stay empty forever. Bank the Riegel estimate under its own source
    # so the provenance is recorded, not laundered as Garmin's.
    tmp = _tmpdir()
    ib.build_archive(tmp, [RUNS[0]], PROFILE)
    conn = _db(tmp)
    ib.bank_riegel_prediction(conn, [RUNS[0]], TODAY)
    row = conn.execute(
        "SELECT date, half_s, source FROM race_predictions").fetchone()
    conn.close()
    assert row[0] == TODAY.isoformat()
    assert row[1] > 0
    assert row[2] == "riegel", "not 'sync' — this is not Garmin's predictor"


def test_riegel_seconds_agree_with_the_formatted_predictions():
    # one derivation, two consumers: the banked seconds and the cockpit's
    # strings must come from the same projection
    secs = ib._riegel_seconds(RUNS)
    strings = ib.predictions(RUNS, plan_goal=None)
    assert ib._fmt_hms(secs["time_5k_s"]) == strings["fiveK"]
    assert ib._fmt_hms(secs["half_s"]) == strings["halfNow"]
    assert ib._riegel_seconds([]) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest test_ingest_builder.py -k "riegel" -v`

Expected: FAIL with `AttributeError: module 'ingest_builder' has no attribute 'bank_riegel_prediction'`.

- [ ] **Step 3: Extract and bank**

Add `MARATHON_KM = 42.195` next to `HALF_KM` (~line 46). Replace `predictions` with:

```python
def _riegel_seconds(runs: list[dict]) -> dict | None:
    """Riegel projections in SECONDS from the best recent effort (fastest run
    ≥ 2 km), anchored on the MOVING effort when a speed series exists (design
    D10). None when nothing is long enough to project from.

    The promoted shape activity_archive.upsert_race_prediction expects, so the
    banked row and the cockpit's strings are one derivation (design D6)."""
    eligible = [r for r in runs if r["distanceM"] >= 2000]
    if not eligible:
        return None
    anchor = min(eligible, key=lambda r: (lambda e: e[0] / e[1])(_effort(r)))
    t1, d1 = _effort(anchor)
    riegel = lambda d2: t1 * (d2 / d1) ** RIEGEL_EXPONENT  # noqa: E731
    return {"time_5k_s": riegel(5), "time_10k_s": riegel(10),
            "half_s": riegel(HALF_KM), "marathon_s": riegel(MARATHON_KM)}


def predictions(runs: list[dict], plan_goal: str | None) -> dict:
    """Riegel projections from the best recent effort, formatted for the
    cockpit."""
    s = _riegel_seconds(runs)
    if not s:
        return {"fiveK": None, "tenK": None, "halfNow": None,
                "halfGoal": plan_goal, "trend": None}
    return {
        "fiveK": _fmt_hms(s["time_5k_s"]),
        "tenK": _fmt_hms(s["time_10k_s"]),
        "halfNow": _fmt_hms(s["half_s"]),
        "halfGoal": plan_goal,
        "trend": None,
    }


def bank_riegel_prediction(conn, runs: list[dict], today: dt.date) -> bool:
    """Upsert today's projection so the trajectory has a line to draw. Source
    is "riegel", never "sync": this is our own model's estimate, not Garmin's
    predictor document, and the column exists so that stays visible."""
    s = _riegel_seconds(runs)
    if not s:
        return False
    activity_archive.upsert_race_prediction(
        conn, today.isoformat(), s,
        {"source": "riegel", "exponent": RIEGEL_EXPONENT}, "riegel")
    return True
```

In `main()`, bank it inside the existing archive connection block, before `derive`:

```python
        try:
            _safe(lambda: bank_riegel_prediction(conn, runs, today),
                  "prediction banking")
            if plan:
```

- [ ] **Step 4: Run the tests**

Run: `./.venv/Scripts/python.exe -m pytest test_ingest_builder.py -q`

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add ingest_builder.py test_ingest_builder.py
git commit -m "feat(ingest): bank the Riegel projection so the trajectory starts

race_predictions is empty on an ingest instance, so the goal-gap trend had
no line to draw. The row goes in under source='riegel' — the schema has the
column precisely so our own estimate is not mistaken for Garmin's."
```

---

### Task 9: Deploy and verify on the NUC

**Files:** none — this is the rollout (spec §7).

- [ ] **Step 1: Run the whole suite one last time**

```bash
./.venv/Scripts/python.exe -m pytest -q
node test_ingest_e2e.mjs && node test_build_watchdog.mjs && node test_slim_render.mjs
```

Expected: all pass. Do not deploy on a red suite.

- [ ] **Step 2: Push and pull the image**

```bash
git push
ssh nuc "cd /home/felix/dev/docker-compose-files/splits && docker compose pull && docker compose up -d"
```

Wait for the GitHub Action to publish `ghcr.io/1-felix/splits:latest` before pulling — check with `gh run list --limit 3`.

- [ ] **Step 3: Rebuild Max's instance and verify the tables fill**

```bash
ssh nuc "docker exec splits-max sh -c 'cd /app && python3 ingest_builder.py'"
ssh nuc "docker exec splits-max sh -c 'python3 -c \"
import sqlite3
c = sqlite3.connect(\\\"/data/activity-archive.db\\\")
for t in (\\\"plan_snapshots\\\",\\\"plan_compliance\\\",\\\"block_lens\\\",\\\"race_predictions\\\"):
    print(t, list(c.execute(f\\\"select count(*) from {t}\\\"))[0][0])
\"'"
```

Expected: all four counts non-zero. Before this change they were `0 0 0 0`.

- [ ] **Step 4: Verify the briefing renders with real content**

```bash
ssh nuc "docker exec splits-max head -60 /data/coach-briefing.md"
```

Expected: a `## Plan vs actual` section with day rows, a Block report, and **no** `insights unavailable this sync` lines. Records & best efforts, Trajectory and Progress trends must all carry content — that is the gap this change existed to close.

- [ ] **Step 5: Verify the dashboard**

Load `http://192.168.0.37:5733/` and check for compliance glyphs on the week cards and a "The Block" section on `/progress`. Read the DOM with `browser_evaluate` on `document.body.innerText`, not the saved Playwright snapshot — the snapshot is captured before the dashboard's dynamic `import('./running-data.js')` resolves and shows the built-in demo dataset.

Expect Wk 2 to show Monday missed and Tuesday as an unplanned run: the plan was rewritten mid-week on 2026-07-29 and there is no historical snapshot to score against (spec §3.1). That is the expected artefact, not a bug.

- [ ] **Step 6: Verify Felix's instance is unchanged**

```bash
ssh nuc "docker exec splits sh -c 'cp /data/garmin-data.js /tmp/before.js'"
ssh nuc "docker exec splits sh -c 'cd /app && python3 sync_garmin.py'"
ssh nuc "docker exec splits sh -c 'diff <(grep -v \"^ \\* Built:\" /tmp/before.js) <(grep -v \"^ \\* Built:\" /data/garmin-data.js) && echo IDENTICAL'"
```

Expected: `IDENTICAL` (the build-timestamp line is the only permitted difference). A diff in `readiness` or `recentRuns` is fresh Garmin data, not a regression — re-run the comparison against two consecutive post-change syncs to separate the two. A diff in `insights`, `compliance`, `blockLens` or `courseLens` is a parity failure and must be fixed before this is left running.

- [ ] **Step 7: Update the memory note**

Edit `C:\Users\felix\.claude\projects\C--Users-felix-Documents-Github-Splits\memory\max-training-state.md`: strike the "no briefing / no compliance on the ingest path" gotcha and the manual `docker exec` briefing recipe, replacing them with the shipped state and the commit range. Update the one-line pointer in `MEMORY.md` to match.

---

## Self-Review

**Spec coverage:** D1 → Tasks 2–5. D2 (`log` parameter) → Task 2 Step 1, used in Tasks 3, 4, 5, 7. D3 (reorder) → Task 7 Step 3. D4 (telemetry guarantee) → Task 7 Steps 1 and 3, tested by `test_an_unreadable_plan_still_yields_telemetry` and `test_a_failing_archive_still_yields_telemetry`. D5 (goal_sec) → Task 6. D6 (Riegel banking) → Task 8. D7 (`_plan_goal` retired) → Task 7 Step 3, asserted in `test_main_derives_the_coach_blocks_and_writes_the_briefing`. Spec §5 parity → Tasks 1, 5 (fixture golden + real archive) and Task 9 Step 6 (live). Spec §5.1 watchdog → Task 7 Step 5. Spec §7 rollout → Task 9.

**Placeholders:** none — every code step carries the code, every run step carries the command and the expected output.

**Type consistency:** `attach_blocks(conn, plan, today, data, log)` returns `list[str]` and is called with that signature in Tasks 2, 5, 7 and in `parity_real.py`. `derive(conn, plan_raw, plan, today, max_hr, log)` returns the merged stats dict, called identically in Tasks 3, 5, 7. `briefing(conn, plan, data, today, path, log)` returns `bool`, called identically in Tasks 4, 5, 7. `_riegel_seconds` returns the same four promoted keys `upsert_race_prediction` reads. `assemble_insights(conn, today, goal_sec)` is positional in `coach_pass` and keyword-defaulted everywhere else.

**Known coupling to watch during execution:** Task 5 Step 1 hides `coach_pass.py` to force the recorder's fallback branch. If the reviewer's environment has a stale `coach_pass.pyc`, the import may still succeed — delete `__pycache__/coach_pass*.pyc` if the recorder prints `after` when `before` was wanted.
