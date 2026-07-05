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
def test_fetch_compliance_fail_soft_and_independent():
    d = _tmp()
    orig = sg.DATA_DIR
    sg.DATA_DIR = d
    try:
        # no plan file at all → block omitted, no raise
        assert sg.fetch_compliance() is None
        # a broken plan → still None
        _plan_file(d, "throw new Error('kaput');")
        assert sg.fetch_compliance() is None
        # healthy plan + scored archive → block present even though the
        # METRICS side (insights) has nothing to offer (independence)
        conn = _seed_archive(d)
        plan = _plan()
        pc.run_compliance(conn, "raw", plan, dt.date.today(), MAX_HR)
        # rescore relative to the real today so weeks_to_score finds the week
        conn.close()
        _plan_file(d, "export const planData = " + json.dumps(_plan()) + ";")
        assert sg.fetch_insights() is None, "no run_metrics → insights side down"
        block = sg.fetch_compliance()
        assert block and block["days"], "compliance side survives alone"
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
                      "status": "unplanned", "actualKm": 4.0}],
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


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_"):
            _fn()
            print("ok", _name)
    print("ALL PASS")
