"""Unit tests for plan_compliance.py (temp dirs, synthetic weeks, no network).

The load_plan tests spawn REAL node children against throwaway plan files —
they exercise the same containment the sync relies on. Everything else runs
against synthetic activity dicts or a temp archive.
"""
import datetime as dt
import json
import tempfile
from pathlib import Path

import activity_archive as arch
import plan_compliance as pc
import sync_garmin as sg

MAX_HR = 197
SNAP = 1


def _tmp() -> Path:
    return Path(tempfile.mkdtemp())


# ── fixtures ─────────────────────────────────────────────────────────────────
def _day(day, date, kind, title, load, km, pace=None):
    d = {"day": day, "date": date, "kind": kind, "title": title,
         "load": load, "km": km}
    if pace:
        d["pace"] = pace
    return d


def _closed_week():
    """A Wk-2-shaped closed week (Jun 29 – Jul 5): hybrid Monday, easy Wed,
    hard Fri, long Sun, strength Tue/Thu/Sat."""
    return {
        "wk": "Wk 2", "mon": "2026-06-29", "sun": "2026-07-05", "km": 32,
        "label": "Jun 29", "phase": "Build", "long": "16 km", "focus": "t",
        "days": [
            _day("Mon", "2026-06-29", "cross", "Spin + Easy Run", "Easy", 4),
            _day("Tue", "2026-06-30", "strength", "Strength", "Moderate", 0),
            _day("Wed", "2026-07-01", "run", "Easy Run", "Easy", 5, "~6:15"),
            _day("Thu", "2026-07-02", "strength", "Strength", "Moderate", 0),
            _day("Fri", "2026-07-03", "run", "Threshold", "Hard", 7, "5:25–5:35"),
            _day("Sat", "2026-07-04", "strength", "Strength · Light", "Easy", 0),
            _day("Sun", "2026-07-05", "run", "Long Run", "Moderate", 16, "~6:10"),
        ],
    }


TODAY = dt.date(2026, 7, 8)  # Wednesday after the closed week


def _a(aid, date, kind, km, hr=140, pace_s=360.0):
    return {"id": aid, "date": date, "kind": kind, "km": km,
            "pace_s": pace_s, "hr": hr}


def _by_date(rows, date, planned_only=True):
    for r in rows:
        if r["date"] == date and (r["planned_kind"] is not None or not planned_only):
            return r
    return None


# ── kind mapping (task 3.1) ──────────────────────────────────────────────────
def test_kind_mapping():
    assert pc.kind_for_type("running") == "run"
    assert pc.kind_for_type("treadmill_running") == "run"
    assert pc.kind_for_type("trail_running") == "run"
    assert pc.kind_for_type("strength_training") == "strength"
    assert pc.kind_for_type("cycling") == "cross"
    assert pc.kind_for_type("indoor_cycling") == "cross"
    assert pc.kind_for_type("road_biking") == "cross"
    assert pc.kind_for_type("yoga") is None
    assert pc.kind_for_type(None) is None


# ── matcher + scoring (tasks 3.2–3.4) ────────────────────────────────────────
def test_same_day_easy_run_done():
    rows = pc.score_week(_closed_week(), [_a(1, "2026-07-01", "run", 5.1, hr=145)],
                         TODAY, MAX_HR, SNAP)
    r = _by_date(rows, "2026-07-01")
    assert r["status"] == "done" and r["reason"] is None
    assert r["actual_km"] == 5.1 and r["actual_hr"] == 145 and r["activity_id"] == 1


def test_easy_run_too_hard_is_partial_intensity():
    hot = int(0.9 * MAX_HR)  # 177 > 85% ceiling
    rows = pc.score_week(_closed_week(), [_a(1, "2026-07-01", "run", 5.0, hr=hot)],
                         TODAY, MAX_HR, SNAP)
    r = _by_date(rows, "2026-07-01")
    assert r["status"] == "partial" and r["reason"] == "intensity"


def test_hard_sessions_not_rep_policed():
    rows = pc.score_week(_closed_week(), [_a(1, "2026-07-03", "run", 7.4, hr=185)],
                         TODAY, MAX_HR, SNAP)
    r = _by_date(rows, "2026-07-03")
    assert r["status"] == "done", "Hard intent is scored on distance alone"


def test_partial_distance():
    rows = pc.score_week(_closed_week(), [_a(1, "2026-07-01", "run", 3.0, hr=140)],
                         TODAY, MAX_HR, SNAP)
    r = _by_date(rows, "2026-07-01")
    assert r["status"] == "partial" and r["reason"] == "distance"


def test_under_half_distance_is_missed_with_actuals():
    rows = pc.score_week(_closed_week(), [_a(1, "2026-07-05", "run", 2.0, hr=140)],
                         TODAY, MAX_HR, SNAP)
    r = _by_date(rows, "2026-07-05")
    assert r["status"] == "missed" and r["actual_km"] == 2.0


def test_missed_and_unplanned():
    # a stray Tuesday run: Mon (4 km slot, 1 day away, ratio 1.0) and Wed
    # (5 km slot, 1 day away, ratio 0.8) tie on distance — the earlier planned
    # day wins the pairing deterministically
    rows = pc.score_week(_closed_week(), [_a(9, "2026-06-30", "run", 4.0)],
                         TODAY, MAX_HR, SNAP)
    assert _by_date(rows, "2026-06-29")["status"] == "swapped"
    assert all(r["status"] != "unplanned" for r in rows)
    # an empty week: every past planned day is missed, nothing is unplanned
    rows = pc.score_week(_closed_week(), [], TODAY, MAX_HR, SNAP)
    for date in ("2026-07-01", "2026-07-03", "2026-07-05"):
        assert _by_date(rows, date)["status"] == "missed"
    assert all(r["status"] != "unplanned" for r in rows)


def test_swap_at_week_close():
    acts = [_a(1, "2026-07-01", "run", 5.0, hr=140),      # Wed done in place
            _a(2, "2026-07-04", "run", 7.2, hr=180),      # Fri threshold done Saturday
            _a(3, "2026-07-05", "run", 16.0, hr=150)]     # Sun done in place
    rows = pc.score_week(_closed_week(), acts, TODAY, MAX_HR, SNAP)
    fri = _by_date(rows, "2026-07-03")
    assert fri["status"] == "swapped" and fri["activity_id"] == 2
    assert all(r["status"] != "unplanned" for r in rows), "swap consumed the Saturday run"


def test_open_week_no_swap_and_pending():
    week = _closed_week()
    week.update(wk="Wk open", mon="2026-07-06", sun="2026-07-12")
    for i, d in enumerate(week["days"]):
        d["date"] = f"2026-07-{6 + i:02d}"
    # today = Wed Jul 8: Mon's run slot missed, Tue had a stray run, Wed+ pending
    rows = pc.score_week(week, [_a(1, "2026-07-07", "run", 4.0)],
                         dt.date(2026, 7, 8), MAX_HR, SNAP)
    assert _by_date(rows, "2026-07-06")["status"] == "missed", "provisional inside open week"
    assert any(r["status"] == "unplanned" and r["date"] == "2026-07-07" for r in rows)
    for date in ("2026-07-08", "2026-07-10", "2026-07-12"):
        assert _by_date(rows, date)["status"] == "pending"


def test_contested_slot_largest_wins():
    # every other run slot is satisfied, so the losing Wednesday double can't
    # be swap-rescued anywhere — it must surface as unplanned
    acts = [_a(1, "2026-07-01", "run", 5.2), _a(2, "2026-07-01", "run", 2.0),
            _a(3, "2026-06-29", "run", 4.0), _a(4, "2026-07-03", "run", 7.0),
            _a(5, "2026-07-05", "run", 16.0)]
    rows = pc.score_week(_closed_week(), acts, TODAY, MAX_HR, SNAP)
    assert _by_date(rows, "2026-07-01")["activity_id"] == 1
    unplanned = [r for r in rows if r["status"] == "unplanned"]
    assert len(unplanned) == 1 and unplanned[0]["activity_id"] == 2


def test_hybrid_day_scored_on_run_component():
    acts = [_a(1, "2026-06-29", "run", 3.9, hr=126),
            _a(2, "2026-06-29", "cross", 0.0, hr=110)]  # the spin class
    rows = pc.score_week(_closed_week(), acts, TODAY, MAX_HR, SNAP)
    mon = _by_date(rows, "2026-06-29")
    assert mon["status"] == "done" and mon["activity_id"] == 1
    assert all(r["status"] != "unplanned" for r in rows), "the spin is absorbed, not noise"


def test_hybrid_day_without_its_run_is_missed():
    rows = pc.score_week(_closed_week(), [_a(2, "2026-06-29", "cross", 0.0)],
                         TODAY, MAX_HR, SNAP)
    assert _by_date(rows, "2026-06-29")["status"] == "missed"


def test_strength_presence_and_absence():
    rows = pc.score_week(_closed_week(), [_a(1, "2026-06-30", "strength", 0.0)],
                         TODAY, MAX_HR, SNAP)
    assert _by_date(rows, "2026-06-30")["status"] == "done"
    assert _by_date(rows, "2026-07-02")["status"] == "missed"
    assert _by_date(rows, "2026-07-04")["status"] == "missed"


# ── honest-compliance: rest, capability, duration ────────────────────────────
def _rest_week():
    """Max's real Wk 1 shape: three run/walk days around four rest days."""
    return {
        "wk": "Wk 1", "mon": "2026-07-20", "sun": "2026-07-26", "km": 8,
        "label": "Jul 20", "phase": "Base", "long": "3 km", "focus": "start",
        "days": [
            _day("Mon", "2026-07-20", "run", "Run/Walk 1:1", "Easy", 2.5),
            _day("Tue", "2026-07-21", "rest", "Rest", "Easy", 0),
            _day("Wed", "2026-07-22", "run", "Run/Walk 1:1", "Easy", 2.5),
            _day("Thu", "2026-07-23", "rest", "Rest", "Easy", 0),
            _day("Fri", "2026-07-24", "rest", "Rest", "Easy", 0),
            _day("Sat", "2026-07-25", "run", "Run/Walk 1:1 · Long", "Easy", 3.0),
            _day("Sun", "2026-07-26", "rest", "Rest", "Easy", 0),
        ],
    }


REST_TODAY = dt.date(2026, 7, 29)  # the week is closed


def test_a_past_rest_day_is_rest_never_missed():
    """Found live on Max's dashboard 2026-08-05: six of his ten ✕ marks were
    rest days. A rest slot falls through _is_run_slot, looks for an activity
    of kind 'rest' that kind_for_type can never return, and was marked missed
    — unsatisfiable by construction. Mutation: drop the rest branch → red."""
    rows = pc.score_week(_rest_week(), [], REST_TODAY, MAX_HR, SNAP)
    for date in ("2026-07-21", "2026-07-23", "2026-07-24", "2026-07-26"):
        r = _by_date(rows, date)
        assert r["status"] == "rest", f"{date} is a rest day, not a failure"
        assert r["reason"] is None


def test_a_future_rest_day_is_still_pending():
    rows = pc.score_week(_rest_week(), [], dt.date(2026, 7, 22), MAX_HR, SNAP)
    assert _by_date(rows, "2026-07-23")["status"] == "pending"


def test_running_on_a_rest_day_keeps_both_facts():
    """The slot is still satisfied — resting was never required of the run —
    and the run itself still surfaces as unplanned. Neither is suppressed."""
    rows = pc.score_week(_rest_week(), [_a(1, "2026-07-23", "run", 1.0)],
                         REST_TODAY, MAX_HR, SNAP)
    assert _by_date(rows, "2026-07-23")["status"] == "rest"
    assert any(r["status"] == "unplanned" and r["date"] == "2026-07-23"
               for r in rows), "the run he did is still reported"


def test_rest_days_are_not_run_slots_in_the_week_aggregate():
    """A rest day carries km 0, so it must never inflate runsPlanned."""
    d = _tmp()
    conn = arch.open_archive(d)
    plan = {"race": {"date": "2027-04-25"}, "block": [_rest_week()]}
    pc.run_compliance(conn, "raw", plan, REST_TODAY, MAX_HR)
    block = pc.assemble_compliance(conn, plan, REST_TODAY)
    assert block["weeks"][0]["runsPlanned"] == 3
    conn.close()


def test_undetailed_week_scores_nothing():
    week = _closed_week()
    week["days"] = None
    assert pc.score_week(week, [_a(1, "2026-07-01", "run", 5.0)],
                         TODAY, MAX_HR, SNAP) == []


# ── plan ingestion via real node children (task 2.3) ─────────────────────────
def _plan_file(d: Path, body: str) -> Path:
    p = d / "plan-data.js"
    p.write_text(body, encoding="utf-8")
    return p


def test_load_plan_valid():
    p = _plan_file(_tmp(), "export const planData = "
                           + json.dumps({"block": [{"wk": "Wk 1"}]}) + ";")
    loaded = pc.load_plan(p)
    assert loaded is not None
    raw, plan = loaded
    assert plan["block"][0]["wk"] == "Wk 1" and "planData" in raw


def test_load_plan_throwing_is_none():
    p = _plan_file(_tmp(), "throw new Error('boom');")
    assert pc.load_plan(p) is None


def test_load_plan_missing_export_is_none():
    p = _plan_file(_tmp(), "export const somethingElse = {block: []};")
    assert pc.load_plan(p) is None


def test_load_plan_busy_loop_is_killed():
    p = _plan_file(_tmp(), "while (true) {}")
    orig = pc.PLAN_DUMP_TIMEOUT_S
    pc.PLAN_DUMP_TIMEOUT_S = 4
    try:
        assert pc.load_plan(p) is None
    finally:
        pc.PLAN_DUMP_TIMEOUT_S = orig


def test_load_plan_garbage_output_is_none():
    p = _plan_file(_tmp(), "export const planData = () => {};")
    assert pc.load_plan(p) is None


def test_load_plan_missing_file_is_none():
    assert pc.load_plan(_tmp() / "nope.js") is None


# ── driver: idempotence, freeze, version self-heal (tasks 3.5/3.7) ───────────
def _garmin_act(aid, date, km, dur_s, hr=140, tk="running"):
    return {"activityId": aid, "startTimeLocal": f"{date} 08:00:00",
            "activityType": {"typeKey": tk}, "distance": km * 1000.0,
            "duration": float(dur_s), "averageHR": hr}


def _seed_archive(d: Path):
    conn = arch.open_archive(d)
    arch.upsert_activities(conn, [
        _garmin_act(1, "2026-06-29", 3.9, 1900, hr=126),
        _garmin_act(2, "2026-06-29", 0.0, 3600, hr=110, tk="indoor_cycling"),
        _garmin_act(3, "2026-06-30", 0.0, 2400, hr=100, tk="strength_training"),
        _garmin_act(4, "2026-07-01", 5.1, 2100, hr=145),
        _garmin_act(5, "2026-07-02", 0.0, 2400, hr=100, tk="strength_training"),
        _garmin_act(6, "2026-07-03", 7.4, 2580, hr=167),
        _garmin_act(7, "2026-07-04", 0.0, 2400, hr=95, tk="strength_training"),
        _garmin_act(8, "2026-07-05", 16.0, 6620, hr=148),
    ])
    return conn


def _plan(week=None):
    return {"race": {"date": "2026-08-09", "goalPaceSecPerKm": 341},
            "block": [week or _closed_week()],
            "coach": {"log": [{"date": "2026-07-05", "text": "entry"}]}}


def test_run_compliance_idempotent():
    d = _tmp()
    conn = _seed_archive(d)
    plan = _plan()
    raw = "export const planData = 1; // v1"
    pc.run_compliance(conn, raw, plan, TODAY, MAX_HR)
    first = arch.compliance_rows(conn)
    stats = pc.run_compliance(conn, raw, plan, TODAY, MAX_HR)
    assert arch.compliance_rows(conn) == first, "same inputs → identical rows"
    assert conn.execute("SELECT COUNT(*) FROM plan_snapshots").fetchone()[0] == 1
    assert stats["weeks_scored"] == 1
    # the seeded week is fully compliant: 4 run slots done, 3 strength done
    statuses = [r["status"] for r in first if r["planned_kind"] is not None]
    assert statuses.count("done") == 7
    conn.close()


def test_closed_week_frozen_against_first_scoring_snapshot():
    d = _tmp()
    conn = _seed_archive(d)
    pc.run_compliance(conn, "raw v1", _plan(), TODAY, MAX_HR)
    snap1 = arch.compliance_rows(conn)[0]["snapshot_id"]

    # a retroactive edit: Wednesday's planned km balloons to 20 (5.1 km would
    # score missed against it) — the frozen week must keep scoring against v1
    edited = _plan()
    edited["block"][0]["days"][2]["km"] = 20
    pc.run_compliance(conn, "raw v2 (edited)", edited, TODAY, MAX_HR)
    rows = arch.compliance_rows(conn)
    wed = next(r for r in rows if r["date"] == "2026-07-01")
    assert wed["snapshot_id"] == snap1, "closed week keeps its original snapshot"
    assert wed["status"] == "done" and wed["planned_km"] == 5
    assert conn.execute("SELECT COUNT(*) FROM plan_snapshots").fetchone()[0] == 2
    conn.close()


def test_recurring_week_label_never_freezes_across_blocks():
    """Block-local labels ("Wk 2") recur across blocks. The frozen-snapshot
    lookup must resolve by the week's DATE WINDOW: the next block's "Wk 2"
    scores against its own snapshot, and the previous block's rows stay
    untouched. (Regression: a label-keyed lookup froze the new week against
    the OLD block's snapshot and rescored the old dates instead.)"""
    d = _tmp()
    conn = _seed_archive(d)
    pc.run_compliance(conn, "raw old block", _plan(), TODAY, MAX_HR)
    old_rows = arch.compliance_rows(conn)
    old_snap = old_rows[0]["snapshot_id"]

    # the NEXT block reuses the label with different dates (post-race restart)
    week = _closed_week()  # keeps wk="Wk 2"
    week.update(mon="2026-08-31", sun="2026-09-06", km=20)
    dates = ["2026-08-31"] + [f"2026-09-{i:02d}" for i in range(1, 7)]
    for day, date in zip(week["days"], dates):
        day["date"] = date
    arch.upsert_activities(conn, [_garmin_act(20, "2026-09-02", 5.0, 2100, hr=145)])
    next_plan = {"race": {"date": "2026-10-11", "goalPaceSecPerKm": 341},
                 "block": [week]}
    pc.run_compliance(conn, "raw next block", next_plan,
                      dt.date(2026, 9, 8), MAX_HR)

    rows = arch.compliance_rows(conn)
    new_wed = next((r for r in rows if r["date"] == "2026-09-02"), None)
    assert new_wed is not None, "the new block's week was scored at all"
    assert new_wed["snapshot_id"] != old_snap, \
        "…against its OWN snapshot, not the old block's"
    assert new_wed["status"] == "done" and new_wed["planned_km"] == 5
    assert [r for r in rows if r["date"] <= "2026-07-05"] == old_rows, \
        "the previous block's frozen rows are untouched"
    conn.close()


def test_version_bump_rescored_against_original_snapshot():
    d = _tmp()
    conn = _seed_archive(d)
    pc.run_compliance(conn, "raw v1", _plan(), TODAY, MAX_HR)
    snap1 = arch.compliance_rows(conn)[0]["snapshot_id"]
    # plan edited after the fact; then the engine version bumps
    edited = _plan()
    edited["block"][0]["days"][2]["km"] = 20
    orig_version = pc.COMPLIANCE_VERSION
    pc.COMPLIANCE_VERSION = orig_version + 1
    try:
        stats = pc.run_compliance(conn, "raw v2 (edited)", edited, TODAY, MAX_HR)
        rows = arch.compliance_rows(conn)
        wed = next(r for r in rows if r["date"] == "2026-07-01")
        assert wed["compliance_version"] == orig_version + 1
        assert wed["snapshot_id"] == snap1, "healed against the ORIGINAL snapshot"
        assert wed["status"] == "done", "history preserved through the bump"
        assert all(r["compliance_version"] == orig_version + 1 for r in rows)
    finally:
        pc.COMPLIANCE_VERSION = orig_version
    conn.close()


# ── contract assembly (tasks 4.1/4.4) ────────────────────────────────────────
def test_assemble_compliance_block():
    d = _tmp()
    conn = _seed_archive(d)
    plan = _plan()
    pc.run_compliance(conn, "raw", plan, TODAY, MAX_HR)
    block = pc.assemble_compliance(conn, plan, TODAY)
    assert block["complianceVersion"] == pc.COMPLIANCE_VERSION
    assert len(block["days"]) == 7
    wk = block["weeks"][0]
    assert wk["plannedKm"] == 32 and wk["runsPlanned"] == 4 and wk["runsDone"] == 4
    assert abs(wk["actualKm"] - 32.4) < 0.05
    conn.close()


def test_assemble_race_day_excluded_from_aggregates():
    d = _tmp()
    conn = arch.open_archive(d)
    week = _closed_week()
    week.update(wk="Race wk", mon="2026-08-03", sun="2026-08-09", km=13)
    dates = ["2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06",
             "2026-08-07", "2026-08-08", "2026-08-09"]
    for day, date in zip(week["days"], dates):
        day["date"] = date
    week["days"][6].update(km=21.1, title="RACE", load="Hard")
    arch.upsert_activities(conn, [_garmin_act(1, "2026-08-09", 21.2, 7150, hr=180)])
    plan = _plan(week)
    pc.run_compliance(conn, "raw", plan, dt.date(2026, 8, 12), MAX_HR)
    block = pc.assemble_compliance(conn, plan, dt.date(2026, 8, 12))
    wk = block["weeks"][0]
    assert wk["actualKm"] == 0, "the race itself stays out of week aggregates"
    race_day = next(dd for dd in block["days"] if dd["date"] == "2026-08-09")
    assert race_day["status"] == "done", "…but the race day itself is scored"
    conn.close()


def test_assemble_raises_without_rows():
    d = _tmp()
    conn = arch.open_archive(d)
    try:
        pc.assemble_compliance(conn, _plan(), TODAY)
        assert False, "must raise with no scored rows"
    except ValueError:
        pass
    conn.close()


# ── fail domains + verify integration (tasks 2.3/4.4, 1.3) ──────────────────
def test_attach_blocks_step_fail_soft_and_independent():
    """The properties the retired fetch_* helpers guaranteed, now through the
    coach_pass seam build_data actually uses: a missing or broken plan omits
    the compliance key without raising, and compliance survives while the
    metrics side (insights) has nothing to offer."""
    d = _tmp()
    orig = sg.DATA_DIR
    sg.DATA_DIR = d
    try:
        # no plan file at all → no compliance key, no raise; the archive is
        # empty too, so no derived key lands at all
        conn = _seed_archive(d)
        conn.close()
        data = {"predictions": {}}
        sg.attach_blocks_step(data)
        assert "compliance" not in data
        # a broken plan → still omitted, still no raise
        _plan_file(d, "throw new Error('kaput');")
        data = {"predictions": {}}
        sg.attach_blocks_step(data)
        assert "compliance" not in data
        # healthy plan + scored archive → block present even though the
        # METRICS side (insights) has nothing to offer (independence)
        conn = _seed_archive(d)
        plan = _plan()
        pc.run_compliance(conn, "raw", plan, dt.date.today(), MAX_HR)
        # rescore relative to the real today so weeks_to_score finds the week
        conn.close()
        _plan_file(d, "export const planData = " + json.dumps(_plan()) + ";")
        data = {"predictions": {}}
        sg.attach_blocks_step(data)
        assert "insights" not in data, "no run_metrics → insights side down"
        assert data.get("compliance") and data["compliance"]["days"], \
            "compliance side survives alone"
    finally:
        sg.DATA_DIR = orig


def test_validate_data_compliance_shape():
    import validate_data as vd
    good = {"complianceVersion": 1,
            "days": [{"date": "2026-07-01", "wk": "Wk 2", "plannedKind": "run",
                      "plannedKm": 5, "plannedLoad": "Easy", "title": "Easy Run",
                      "status": "done", "actualKm": 5.1, "actualPaceS": 411,
                      "actualHr": 145},
                     {"date": "2026-07-02", "wk": "Wk 2", "plannedKind": None,
                      "plannedKm": None, "plannedLoad": None, "title": None,
                      "status": "unplanned", "actualKm": 4.0},
                     # honest-compliance: a rest day is satisfied by resting,
                     # work this instance cannot see is neither done nor missed,
                     # and a time-scored day carries seconds beside its km
                     {"date": "2026-07-03", "wk": "Wk 2", "plannedKind": "rest",
                      "plannedKm": 0, "plannedLoad": "Easy", "title": "Rest",
                      "status": "rest"},
                     {"date": "2026-07-04", "wk": "Wk 2", "plannedKind": "strength",
                      "plannedKm": 0, "plannedLoad": "Easy", "title": "Mobility",
                      "status": "untracked"},
                     {"date": "2026-07-05", "wk": "Wk 2", "plannedKind": "run",
                      "plannedKm": 3.4, "plannedLoad": "Easy", "title": "2 × 10 min",
                      "status": "partial", "reason": "duration",
                      "plannedS": 1320, "actualS": 900,
                      "actualKm": 2.4, "actualPaceS": 578, "actualHr": 151}],
            "weeks": [{"wk": "Wk 2", "mon": "2026-06-29", "sun": "2026-07-05",
                       "plannedKm": 32, "actualKm": 9.1, "runsPlanned": 4,
                       "runsDone": 1}]}
    e = []
    vd.validate_compliance(good, e)
    assert e == [], f"well-formed block must validate: {e}"

    for mutate, expect in (
        (lambda c: c["days"][0].update(status="acing_it"), "invalid status"),
        (lambda c: c["days"][0].update(reason="vibes"), "invalid reason"),
        (lambda c: c["days"][1].update(status="done"), "must be status unplanned"),
        (lambda c: c["days"][4].update(plannedS="twenty"), "must be numeric"),
        (lambda c: c["weeks"][0].update(runsDone="one"), "must be numeric"),
    ):
        bad = json.loads(json.dumps(good))
        mutate(bad)
        e = []
        vd.validate_compliance(bad, e)
        assert any(expect in msg for msg in e), f"expected '{expect}' in {e}"


def test_verify_archive_compliance_regressions():
    d = _tmp()
    orig = sg.DATA_DIR, sg.CACHE_DIR
    sg.DATA_DIR = d
    try:
        conn = _seed_archive(d)
        conn.close()
        assert sg.verify_archive() == 0, "pre-coach-loop archive (no rows) passes"

        conn = arch.open_archive(d)
        pc.run_compliance(conn, "raw", _plan(), TODAY, MAX_HR)
        arch.set_meta(conn, "expected_compliance_weeks", 1)
        conn.close()
        assert sg.verify_archive() == 0, "scored archive passes"

        conn = arch.open_archive(d)
        conn.execute("UPDATE plan_compliance SET compliance_version = 0")
        conn.commit()
        conn.close()
        assert sg.verify_archive() == 1, "stale-version rows → regression"

        conn = arch.open_archive(d)
        conn.execute("DELETE FROM plan_compliance")
        conn.commit()
        conn.close()
        assert sg.verify_archive() == 1, "scored weeks below the ratchet → regression"
    finally:
        sg.DATA_DIR, sg.CACHE_DIR = orig


# ── rep-level quality verdicts (add-plan-prescription) ───────────────────────
def _quality_day(segments_val, date="2026-07-03"):
    d = _day("Fri", date, "run", "Threshold", "Hard", 7)
    d["segments"] = [{"label": "Reps", "val": segments_val}]
    return d


def _quality_week(segments_val):
    w = _closed_week()
    w["days"] = [d if d["date"] != "2026-07-03"
                 else _quality_day(segments_val) for d in w["days"]]
    return w


def _doc_conn(doc, aid=1):
    conn = arch.open_archive(_tmp())
    arch.upsert_run_intervals(conn, {
        "activity_id": aid, "lens_version": 6,
        "start_time_local": "2026-07-03 06:00:00", "shape": doc.get("shape"),
        "label": doc.get("label"), "confidence": 0.9, "source": "stream",
        "work_dist_m": 0, "work_dur_s": 0, "doc_json": json.dumps(doc)})
    return conn


def _annotated(week, doc, act):
    conn = _doc_conn(doc)
    rows = pc.score_week(week, [act], TODAY, MAX_HR, SNAP)
    pc._annotate_quality(conn, week, rows)
    conn.close()
    return _by_date(rows, "2026-07-03")


_REPS_DOC = {"shape": "reps", "label": "4×1 km",
             "set": {"found": 4, "prescribed": None},
             "segments": [{"role": "work", "paceS": p}
                          for p in (330, 330, 333, 340)],
             "quality": {"zone": "Z4"}}


def test_quality_verdict_counts_reps_and_the_band():
    r = _annotated(_quality_week("4×1 km @ 5:25–5:35"), _REPS_DOC,
                   _a(1, "2026-07-03", "run", 7.2))
    q = json.loads(r["quality_json"])
    assert q["prescribed"] == 4 and q["found"] == 4
    assert q["inBand"] == 3, "340 is outside 5:25–5:35"
    assert q["verdict"] == "4/4 reps, 3 inside 5:25–5:35"
    assert r["status"] == "done", "annotation only — coarse scoring decided this"


def test_quality_verdict_shows_a_bailed_set_without_touching_status():
    doc = dict(_REPS_DOC, set={"found": 2},
               segments=[{"role": "work", "paceS": 330}] * 2)
    r = _annotated(_quality_week("4×1 km @ 5:25–5:35"), doc,
                   _a(1, "2026-07-03", "run", 7.0))
    q = json.loads(r["quality_json"])
    assert q["found"] == 2 and q["verdict"].startswith("2/4 reps")
    assert r["status"] == "done", \
        "distance landed; the shortfall is the ANNOTATION's story"


def test_quality_verdict_zone_sets_judge_the_zone_not_pace():
    r = _annotated(_quality_week("6×3 min hard (Z4 effort)"),
                   dict(_REPS_DOC, set={"found": 6}),
                   _a(1, "2026-07-03", "run", 7.0))
    q = json.loads(r["quality_json"])
    assert q["zoneOk"] is True and q["inBand"] is None
    assert "Z4 confirmed" in q["verdict"]
    mism = _annotated(_quality_week("6×3 min hard (Z4 effort)"),
                      dict(_REPS_DOC, set={"found": 6}, quality={"zone": "Z3"}),
                      _a(1, "2026-07-03", "run", 7.0))
    assert "zone read Z3" in json.loads(mism["quality_json"])["verdict"]


def test_quality_verdict_steady_target_tolerance():
    on = _annotated(_quality_week("16 km easy @ ~6:10"), _REPS_DOC,
                    _a(1, "2026-07-03", "run", 16.0, pace_s=373.0))
    q = json.loads(on["quality_json"])
    assert q["kind"] == "steady" and q["onTarget"] is True
    assert q["verdict"] == "6:13 vs ~6:10 — on target"
    off = _annotated(_quality_week("16 km easy @ ~6:10"), _REPS_DOC,
                     _a(1, "2026-07-03", "run", 16.0, pace_s=390.0))
    assert json.loads(off["quality_json"])["verdict"] == "6:30 vs ~6:10 — +20 s/km"


def test_quality_verdict_without_a_document_is_honest():
    conn = arch.open_archive(_tmp())  # no run_intervals row at all
    week = _quality_week("4×1 km @ 5:25–5:35")
    rows = pc.score_week(week, [_a(1, "2026-07-03", "run", 7.0)],
                         TODAY, MAX_HR, SNAP)
    pc._annotate_quality(conn, week, rows)
    conn.close()
    q = json.loads(_by_date(rows, "2026-07-03")["quality_json"])
    assert q["verdict"] == "no interval document"


def test_quality_verdict_steady_doc_against_a_rep_prescription():
    doc = {"shape": "steady", "set": None, "segments": [], "quality": {"zone": None}}
    r = _annotated(_quality_week("4×1 km @ 5:25–5:35"), doc,
                   _a(1, "2026-07-03", "run", 7.0))
    q = json.loads(r["quality_json"])
    assert q["found"] == 0
    assert "no structured set detected" in q["verdict"]


def test_a_cross_days_bike_intervals_are_not_a_rep_verdict_question():
    """Found live on 2026-07-17 ('Bike Intervals', kind cross, km 0): the
    plan prescribes bike work in the same notation, the parser reads it, and
    the verdict said 'no interval document' about a bicycle. The annotator
    now uses the scorer's own _is_run_slot — a non-run slot gets no verdict,
    parseable segments or not. Mutation-proven: dropping the guard → red."""
    week = _closed_week()
    week["days"] = [d if d["date"] != "2026-06-29" else {
        "day": "Mon", "date": "2026-06-29", "kind": "cross",
        "title": "Bike Intervals", "load": "Hard", "km": 0,
        "segments": [{"label": "Reps", "val": "6×3 min hard (Z4 effort)"}],
    } for d in week["days"]]
    conn = _doc_conn({"shape": "steady", "set": None, "segments": [],
                      "quality": {"zone": None}})
    rows = pc.score_week(week, [_a(1, "2026-06-29", "cross", 0.0)],
                         TODAY, MAX_HR, SNAP)
    pc._annotate_quality(conn, week, rows)
    conn.close()
    r = _by_date(rows, "2026-06-29")
    assert r["activity_id"] == 1, "the ride matched its cross slot"
    assert r.get("quality_json") is None, \
        "a bike prescription is not a running rep-verdict question"


def test_an_unplanned_same_day_run_gets_no_verdict():
    """Found live on 2026-07-29: two runs on a quality day — the planned
    strides session plus an unplanned 2.3 km shuffle. The unplanned row
    shares the DATE, so the date-keyed day lookup annotated it '0/4 reps'
    against a prescription it was never given. Only the planned row is the
    prescription's subject. Mutation-proven: dropping the planned_kind guard
    → red."""
    week = _quality_week("4×20 s fast-relaxed")
    acts = [_a(1, "2026-07-03", "run", 6.3),   # the planned session
            # the unplanned shuffle — 1.5 km, under DIST_PARTIAL_RATIO of
            # every planned slot, so the closed week's swap pass cannot
            # rescue it into a missed day; it must land as `unplanned`
            _a(2, "2026-07-03", "run", 1.5)]
    conn = _doc_conn({"shape": "reps", "label": "4×20 s", "set": {"found": 4},
                      "segments": [], "quality": {"zone": None}})
    rows = pc.score_week(week, acts, TODAY, MAX_HR, SNAP)
    pc._annotate_quality(conn, week, rows)
    conn.close()
    planned = _by_date(rows, "2026-07-03")
    unplanned = next(r for r in rows
                     if r["date"] == "2026-07-03" and r["planned_kind"] is None)
    assert planned["quality_json"], "the planned session carries its verdict"
    assert unplanned.get("quality_json") is None, \
        "the shuffle was never asked to run 4×20 s"


def test_unparseable_day_gets_no_quality_json():
    r = _annotated(_quality_week("2 km easy — shin gate: pain-free before any rep"),
                   _REPS_DOC, _a(1, "2026-07-03", "run", 7.0))
    assert r.get("quality_json") is None


def test_annotation_never_changes_status_or_reason():
    """D3's structural pin: identical days, one with a parseable prescription
    — status and reason byte-identical. Mutation-proven: making the verdict
    writer downgrade status goes red here."""
    week_plain = _closed_week()
    week_rx = _quality_week("4×1 km @ 5:25–5:35")
    act = [_a(1, "2026-07-03", "run", 7.0)]
    conn = _doc_conn(dict(_REPS_DOC, set={"found": 1},
                          segments=[{"role": "work", "paceS": 400}]))
    rows_plain = pc.score_week(week_plain, list(act), TODAY, MAX_HR, SNAP)
    rows_rx = pc.score_week(week_rx, list(act), TODAY, MAX_HR, SNAP)
    pc._annotate_quality(conn, week_rx, rows_rx)
    conn.close()
    p, r = _by_date(rows_plain, "2026-07-03"), _by_date(rows_rx, "2026-07-03")
    assert (p["status"], p["reason"]) == (r["status"], r["reason"]), \
        "a 1-of-4 disaster set still cannot move the coarse status"
    assert r["quality_json"] and json.loads(r["quality_json"])["found"] == 1


def test_rescore_at_version_2_adds_verdicts_and_keeps_statuses():
    """COMPLIANCE_VERSION 1→2 self-heal: stale rows gain quality_json by
    rescore against their ORIGINAL snapshot; statuses do not move."""
    d = _tmp()
    conn = arch.open_archive(d)
    week = _quality_week("4×1 km @ 5:25–5:35")
    plan = {"block": [week]}
    snap = arch.bank_plan_snapshot(conn, "raw-v2-test", plan, "2026-07-06")
    arch.upsert_activities(conn, [{
        "activityId": 1, "activityName": "Threshold",
        "startTimeLocal": "2026-07-03 06:00:00",
        "activityType": {"typeKey": "running"},
        "distance": 7200.0, "duration": 2592.0, "averageHR": 170}])
    arch.upsert_run_intervals(conn, {
        "activity_id": 1, "lens_version": 6,
        "start_time_local": "2026-07-03 06:00:00", "shape": "reps",
        "label": "4×1 km", "confidence": 0.9, "source": "stream",
        "work_dist_m": 4000, "work_dur_s": 1320,
        "doc_json": json.dumps(_REPS_DOC)})
    acts = pc._acts_for_range(conn, week["mon"], week["sun"])
    rows = pc.score_week(week, acts, TODAY, MAX_HR, snap)
    for r in rows:  # simulate the version-1 era: old stamp, no annotation
        r["compliance_version"] = 1
        r.pop("quality_json", None)
    arch.replace_compliance_week(conn, week["mon"], week["sun"], rows)
    before = {r[0]: r[1] for r in conn.execute(
        "SELECT date, status FROM plan_compliance WHERE planned_kind IS NOT NULL")}

    healed = pc._rescore_stale(conn, TODAY, MAX_HR)
    assert healed == 1
    after = conn.execute(
        "SELECT status, quality_json FROM plan_compliance "
        "WHERE date = '2026-07-03' AND planned_kind IS NOT NULL").fetchone()
    assert after[0] == before["2026-07-03"], "rescore moves no status"
    assert json.loads(after[1])["verdict"] == "4/4 reps, 3 inside 5:25–5:35"
    conn.close()


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_"):
            _fn()
            print("ok", _name)
    print("ALL PASS")
