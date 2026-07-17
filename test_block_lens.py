"""Unit tests for block_lens.py (temp archive, synthetic inputs, no network).

The finished-block fixture (block A, raced 2026-05-10) proves the
retrospective document shape BEFORE the live block ever completes — the
first real completion on 2026-08-09 exercises nothing new.
"""
import datetime as dt
import json
import tempfile
from pathlib import Path

import activity_archive as arch
import block_lens as bl
import insight_metrics as im
import plan_compliance as pc

TODAY = dt.date(2026, 7, 16)
MAX_HR = 197


def _tmp() -> Path:
    return Path(tempfile.mkdtemp())


def _d(date, kind, km, load, title="Session", pace=None):
    day = {"day": "X", "date": date, "kind": kind, "title": title,
           "load": load, "km": km}
    if pace:
        day["pace"] = pace
    return day


def _w(wk, mon, sun, km, days, phase="Build", label=None, focus=None):
    return {"wk": wk, "mon": mon, "sun": sun, "km": km, "days": days,
            "phase": phase, "label": label or mon, "focus": focus}


def _act(aid, date, km, tk="running", hr=140):
    return {"activityId": aid, "startTimeLocal": f"{date} 08:00:00",
            "activityType": {"typeKey": tk}, "distance": km * 1000.0,
            "duration": km * 360.0, "averageHR": hr}


def _metrics(conn, aid, date, refhr=None, cad=None, best5k=None, treadmill=0):
    arch.upsert_run_metrics(conn, {
        "activity_id": aid, "metrics_version": im.METRICS_VERSION,
        "start_time_local": f"{date} 08:00:00", "is_treadmill": treadmill,
        "best_5k_s": best5k, "refhr_pace_s_per_km": refhr,
        "refpace_cadence_spm": cad})


# ── block A: a FINISHED half on 2026-05-10, four weeks, fully executed ───────
PLAN_A = {
    "race": {"name": "Spring Half", "date": "2026-05-10",
             "goalTime": "2:05:00", "goalPaceSecPerKm": 355},
    "block": [
        _w("A-Wk1", "2026-04-13", "2026-04-19", 18, [
            _d("2026-04-13", "run", 5, "Easy"),
            _d("2026-04-15", "run", 5, "Easy"),
            _d("2026-04-18", "run", 8, "Easy"),
        ], phase="Base"),
        _w("A-Wk2", "2026-04-20", "2026-04-26", 15, [
            _d("2026-04-21", "run", 5, "Easy"),
            _d("2026-04-26", "run", 10, "Moderate"),
        ]),
        _w("A-Wk3", "2026-04-27", "2026-05-03", 18, [
            _d("2026-04-29", "run", 6, "Easy"),
            _d("2026-05-03", "run", 12, "Moderate"),
        ]),
        _w("A-Wk4", "2026-05-04", "2026-05-10", 4, [
            _d("2026-05-08", "run", 4, "Easy"),
            _d("2026-05-10", "run", 21.1, "Hard", title="RACE"),
        ], phase="Taper"),
    ],
}

# ── block B: the CURRENT block, race 2026-08-09, mid-flight at TODAY ─────────
PLAN_B = {
    "race": {"name": "Sonthofen Half", "date": "2026-08-09",
             "goalTime": "1:59:59", "goalPaceSecPerKm": 341},
    "block": [
        _w("B-Wk1", "2026-07-06", "2026-07-12", 25, [
            _d("2026-07-06", "run", 5, "Easy"),
            _d("2026-07-07", "run", 5, "Easy"),
            _d("2026-07-08", "run", 5, "Easy"),
            _d("2026-07-09", "run", 5, "Easy"),
            _d("2026-07-10", "run", 5, "Hard"),
        ]),
        _w("B-Wk2", "2026-07-13", "2026-07-19", 34, [
            _d("2026-07-13", "run", 6, "Easy"),
            _d("2026-07-14", "run", 4, "Easy"),
            _d("2026-07-15", "strength", 0, "Moderate"),
            _d("2026-07-16", "run", 5, "Easy"),
            _d("2026-07-18", "run", 5, "Hard"),
            _d("2026-07-19", "run", 14, "Moderate"),
        ]),
        _w("B-Wk3", "2026-07-20", "2026-07-26", 20, [
            _d("2026-07-21", "run", 6, "Easy"),
            _d("2026-07-23", "run", 6, "Easy"),
            _d("2026-07-26", "run", 8, "Moderate"),
        ], phase="Peak"),
        _w("B-Wk4", "2026-07-27", "2026-08-02", 30, None, phase="Peak"),
        _w("B-Wk5", "2026-08-03", "2026-08-09", 7, [
            _d("2026-08-03", "run", 4, "Easy"),
            _d("2026-08-05", "run", 3, "Easy"),
            _d("2026-08-09", "run", 21.1, "Hard", title="RACE"),
        ], phase="Taper"),
    ],
}


def _seed_block_a(conn):
    arch.upsert_activities(conn, [
        _act(100, "2026-03-01", 5.2),        # pre-block 5k baseline
        _act(101, "2026-04-13", 5.0), _act(102, "2026-04-15", 5.0),
        _act(103, "2026-04-18", 8.0),
        _act(104, "2026-04-22", 5.0),        # planned Tue 4/21 → swapped
        _act(105, "2026-04-26", 10.0),
        _act(106, "2026-04-29", 6.0),
        _act(107, "2026-05-03", 12.0), _act(108, "2026-05-08", 4.0),
        _act(109, "2026-05-10", 21.1),
    ])
    _metrics(conn, 100, "2026-03-01", best5k=1700)
    _metrics(conn, 101, "2026-04-13", refhr=460, cad=165)
    _metrics(conn, 102, "2026-04-15", refhr=456, cad=166)
    _metrics(conn, 103, "2026-04-18", refhr=452, cad=167)
    _metrics(conn, 106, "2026-04-29", refhr=448, cad=168)
    _metrics(conn, 107, "2026-05-03", refhr=444, cad=169, best5k=1650)
    _metrics(conn, 108, "2026-05-08", refhr=440, cad=170, best5k=1640)
    arch.upsert_race_prediction(conn, "2026-04-14", {"half_s": 8100}, {}, "test")
    arch.upsert_race_prediction(conn, "2026-05-09", {"half_s": 7900}, {}, "test")
    # score every week as it closed, the way nightly syncs did
    for day in (dt.date(2026, 4, 20), dt.date(2026, 4, 27),
                dt.date(2026, 5, 4), dt.date(2026, 5, 11)):
        pc.run_compliance(conn, "raw-plan-a", PLAN_A, day, MAX_HR)


def _seed_block_b(conn):
    arch.upsert_activities(conn, [
        _act(201, "2026-07-06", 5.0),
        _act(202, "2026-07-07", 3.0),        # 60% of planned → partial
        _act(203, "2026-07-09", 5.2),
        _act(204, "2026-07-10", 5.0),
        _act(205, "2026-07-13", 6.0),
        _act(206, "2026-07-15", 0.0, tk="strength_training"),
    ])
    _metrics(conn, 201, "2026-07-06", refhr=452, cad=165)  # only TWO refhr runs
    _metrics(conn, 203, "2026-07-09", refhr=449, cad=166)
    _metrics(conn, 204, "2026-07-10", cad=167)
    _metrics(conn, 205, "2026-07-13", cad=168)
    arch.upsert_race_prediction(conn, "2026-07-07", {"half_s": 7300}, {}, "test")
    arch.upsert_race_prediction(conn, "2026-07-15", {"half_s": 7250}, {}, "test")
    pc.run_compliance(conn, "raw-plan-b", PLAN_B, TODAY, MAX_HR)


def _seeded_conn():
    conn = arch.open_archive(_tmp())
    _seed_block_a(conn)
    _seed_block_b(conn)
    return conn


def _docs(conn) -> dict:
    return {rd: json.loads(doc) for rd, _n, _c, doc in arch.block_lens_rows(conn)}


# ── goal-time parsing ────────────────────────────────────────────────────────
def test_parse_goal_seconds():
    assert bl.parse_goal_seconds("1:59:59") == 7199
    assert bl.parse_goal_seconds("2:05:00") == 7500
    assert bl.parse_goal_seconds("49:30") == 2970
    assert bl.parse_goal_seconds("fast") is None
    assert bl.parse_goal_seconds(None) is None
    assert bl.parse_goal_seconds(7199) is None


# ── enumeration (design D1) ──────────────────────────────────────────────────
def test_enumeration_and_identity():
    conn = _seeded_conn()
    blocks = bl.enumerate_blocks(conn)
    assert [b["race_date"] for b in blocks] == ["2026-05-10", "2026-08-09"]
    assert [b["is_live"] for b in blocks] == [False, True]
    conn.close()


def test_multi_snapshot_single_block():
    conn = arch.open_archive(_tmp())
    pc.run_compliance(conn, "raw-b-v1", PLAN_B, TODAY, MAX_HR)
    # a later edit of the SAME race drops Wk1 and reshapes Wk3
    edited = json.loads(json.dumps(PLAN_B))
    edited["block"] = edited["block"][1:]
    edited["block"][1]["km"] = 24
    pc.run_compliance(conn, "raw-b-v2", edited, TODAY, MAX_HR)
    blocks = bl.enumerate_blocks(conn)
    assert len(blocks) == 1, "one race across many snapshots is one block"
    b = blocks[0]
    assert b["start"] == "2026-07-06", "window keeps the earliest mon ever seen"
    assert len(b["weeks"]) == 4 and b["weeks"][1]["km"] == 24, \
        "the latest snapshot shapes the plan"
    conn.close()


def test_race_date_edit_spawns_new_block():
    conn = arch.open_archive(_tmp())
    v1 = json.loads(json.dumps(PLAN_B))
    v1["race"]["date"] = "2026-08-16"
    pc.run_compliance(conn, "raw-edit-v1", v1, TODAY, MAX_HR)
    v2 = json.loads(json.dumps(PLAN_B))
    v2["race"]["date"] = "2026-08-23"
    pc.run_compliance(conn, "raw-edit-v2", v2, TODAY, MAX_HR)

    bl.derive_block_lens(conn, TODAY)
    docs = _docs(conn)
    assert set(docs) == {"2026-08-16", "2026-08-23"}, "new key → new block row"
    assert "forward" in docs["2026-08-23"], "the live key is the current block"
    assert "forward" not in docs["2026-08-16"], "the orphan is not current"
    assert docs["2026-08-16"]["isComplete"] is False, "not complete before its date"

    bl.derive_block_lens(conn, dt.date(2026, 8, 17))
    docs = _docs(conn)
    assert docs["2026-08-16"]["isComplete"] is True, \
        "the old row completes at its own race date"
    conn.close()


# ── the finished block (retrospective tense, proven pre-race) ────────────────
def test_finished_block_document():
    conn = _seeded_conn()
    bl.derive_block_lens(conn, TODAY)
    doc = _docs(conn)["2026-05-10"]

    assert doc["isComplete"] is True
    assert "forward" not in doc and "weekNow" not in doc, \
        "complete blocks carry no forward tilt"
    assert doc["window"] == {"start": "2026-04-13", "end": "2026-05-10"}
    assert doc["weeksTotal"] == 4

    ex = doc["execution"]
    assert ex["percentExecuted"] == 100
    assert ex["counts"]["swapped"] == 1 and ex["counts"]["done"] == 7, \
        "race day sits outside every aggregate (convention: race week km " \
        "excludes the race)"
    assert ex["kmActual"] == 55.0
    assert ex["qualityHitRate"] == {"hit": 0, "of": 0}, \
        "the race is the only Hard day and it is excluded"

    wk2 = doc["weeks"][1]
    assert wk2["counts"] == {"done": 1, "partial": 0, "missed": 0,
                             "swapped": 1, "unplanned": 0}
    swapped_day = next(d for d in wk2["days"] if d["status"] == "swapped")
    assert swapped_day["activityId"] == 104, "the drill links the swapped-in run"
    race_day = next(d for d in doc["weeks"][3]["days"]
                    if d["date"] == "2026-05-10")
    assert race_day["status"] == "done", "the race still appears in the drill"

    ad = doc["adaptation"]
    assert ad["ef"]["deltaSPerKm"] == -12.0
    assert ad["ef"]["startPaceSPerKm"] == 456 and ad["ef"]["endPaceSPerKm"] == 444
    assert ad["cadence"]["deltaSpm"] == 3.0
    assert ad["records"] == [{"distance": "5k", "sec": 1640, "prevSec": 1700,
                              "date": "2026-05-08", "activityId": 108}], \
        "one entry per distance — the better in-block effort, deduped"
    gg = ad["goalGap"]
    assert gg["gapStartS"] == 600 and gg["gapNowS"] == 400 and gg["deltaS"] == -200

    s = doc["summary"]
    assert s["percentExecuted"] == 100 and s["efDeltaSPerKm"] == -12.0
    assert s["recordsCount"] == 1 and s["isComplete"] is True
    conn.close()


# ── the current block (live report card) ─────────────────────────────────────
def test_current_block_document():
    conn = _seeded_conn()
    bl.derive_block_lens(conn, TODAY)
    doc = _docs(conn)["2026-08-09"]

    assert doc["isComplete"] is False
    assert doc["weekNow"] == 2 and doc["weeksTotal"] == 5

    # rollup weights: Wk1 = 3 done, 1 partial, 1 missed → partial counts 0.5
    wk1 = doc["weeks"][0]
    assert wk1["counts"] == {"done": 3, "partial": 1, "missed": 1,
                             "swapped": 0, "unplanned": 0}
    assert wk1["actualKm"] == 18.2
    ex = doc["execution"]
    assert ex["scoredDays"] == 8
    assert ex["percentExecuted"] == 69          # (3+0.5 + 2) / 8 = 68.75
    assert ex["qualityHitRate"] == {"hit": 1, "of": 1}
    assert ex["kmPlannedToDate"] == 35.0 and ex["kmActual"] == 24.2
    assert ex["kmPlanned"] == 25 + 34 + 20 + 30 + 7

    # unscored future weeks are planned-only and outside percent-executed
    wk3 = doc["weeks"][2]
    assert wk3["scored"] is False and "counts" not in wk3
    assert all(d["status"] == "pending" for d in wk3["days"])

    # honesty: two qualifying EF runs → null + machine-readable reason
    ad = doc["adaptation"]
    assert ad["ef"]["deltaSPerKm"] is None
    assert ad["ef"]["reason"] == "insufficient-baseline"
    assert ad["ef"]["startRuns"] == 2
    assert ad["cadence"]["deltaSpm"] == 0.0, \
        "cadence has enough evidence even while EF does not"
    assert ad["goalGap"]["deltaS"] == -50

    fw = doc["forward"]
    assert fw["weeksRemaining"] == 4
    assert fw["kmRemaining"] == 24 + 20 + 30 + 7, \
        "day-level ahead of today; header km for the undetailed week; race excluded"
    assert [s["km"] for s in fw["silhouette"]] == [34, 20, 30, 7]
    assert fw["undetailedWeeks"] == ["B-Wk4"]

    s = doc["summary"]
    assert s["efDeltaSPerKm"] is None and s["cadenceDeltaSpm"] == 0.0
    conn.close()


# ── persistence + versioning (design D2) ─────────────────────────────────────
def test_current_recomputes_completed_freezes():
    conn = _seeded_conn()
    bl.derive_block_lens(conn, TODAY)
    stats = bl.derive_block_lens(conn, TODAY)
    assert stats == {"blocks": 2, "recomputed": 1}, \
        "the current block recomputes every sync; the completed one is frozen"
    # a late-synced run changes the current block's numbers on the next derive
    arch.upsert_activities(conn, [_act(207, "2026-07-14", 4.0)])
    pc.run_compliance(conn, "raw-plan-b", PLAN_B, TODAY, MAX_HR)
    bl.derive_block_lens(conn, TODAY)
    doc = _docs(conn)["2026-08-09"]
    assert doc["execution"]["kmActual"] == 28.2, "kmActual grew by the late run"
    conn.close()


def test_version_bump_heals_stale_rows():
    conn = _seeded_conn()
    bl.derive_block_lens(conn, TODAY)
    conn.execute("UPDATE block_lens SET lens_version = 0")
    conn.commit()
    stats = bl.derive_block_lens(conn, TODAY)
    assert stats["recomputed"] == 2, "stale-version rows heal, completed included"
    assert arch.block_lens_coverage(conn, bl.BLOCK_LENS_VERSION)["stale"] == 0
    conn.close()


def test_fail_soft_derivation_error():
    conn = _seeded_conn()
    real = bl.build_block_document

    def explode(conn_, block, today, is_current):
        if block["race_date"] == "2026-05-10":
            raise RuntimeError("synthetic derivation failure")
        return real(conn_, block, today, is_current)

    bl.build_block_document = explode
    try:
        stats = bl.derive_block_lens(conn, TODAY)  # must not raise
    finally:
        bl.build_block_document = real
    assert stats == {"blocks": 2, "recomputed": 1}, \
        "one bad block warns and skips; the other still derives"
    assert set(_docs(conn)) == {"2026-08-09"}
    conn.close()


# ── contract assembly (design D4) ────────────────────────────────────────────
def test_assemble_contract():
    conn = _seeded_conn()
    bl.derive_block_lens(conn, TODAY)
    out = bl.assemble_block_lens(conn, TODAY)
    assert out["lensVersion"] == bl.BLOCK_LENS_VERSION
    assert out["current"]["raceDate"] == "2026-08-09"
    assert "weeks" in out["current"], "current is the FULL document"
    assert [p["raceDate"] for p in out["past"]] == ["2026-05-10"]
    assert "weeks" not in out["past"][0], "past blocks stay summaries"
    conn.close()


def test_assemble_raises_without_lens_rows():
    conn = arch.open_archive(_tmp())
    try:
        bl.assemble_block_lens(conn, TODAY)
        raise AssertionError("must raise so the sync omits the key entirely")
    except ValueError:
        pass
    conn.close()


def test_assemble_no_current_after_race_without_new_plan():
    conn = _seeded_conn()
    bl.derive_block_lens(conn, TODAY)
    # the live plan's race passes and no new plan lands: no current, two pasts
    later = dt.date(2026, 8, 10)
    bl.derive_block_lens(conn, later)
    out = bl.assemble_block_lens(conn, later)
    assert "current" not in out
    assert [p["raceDate"] for p in out["past"]] == ["2026-08-09", "2026-05-10"], \
        "past summaries are newest race first"
    assert out["past"][0]["isComplete"] is True, \
        "the first completed block becomes a retrospective"
    conn.close()


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_"):
            _fn()
            print("ok", _name)
    print("ALL PASS")
