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
import block_lens as bl
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


def _metrics(conn, aid, date, refhr=None, cad=None, best5k=None, best10k=None):
    arch.upsert_run_metrics(conn, {
        "activity_id": aid, "metrics_version": im.METRICS_VERSION,
        "start_time_local": f"{date} 08:00:00", "is_treadmill": 0,
        "best_5k_s": best5k, "best_10k_s": best10k,
        "refhr_pace_s_per_km": refhr, "refpace_cadence_spm": cad})


def _fixture_archive(tmp: Path):
    """A seeded archive + its plan: two scored weeks, metrics across three
    months (monthly_series needs more than one month to be non-empty), banked
    predictions, 10k efforts across enough weeks for a non-empty trend
    verdict, and derived block-lens rows.

    Every golden key the Garmin path can produce must be NON-NULL here —
    a null golden key makes the parity assertion for that block vacuous
    (the plan's own rule for insights, applied to all of them). courseLens
    stays null deliberately: the plan has no courseId, which is the normal
    state, and the key-set assertion covers the omission."""
    conn = arch.open_archive(tmp)
    arch.upsert_activities(conn, [
        _act(301, "2026-05-04", 5.0), _act(302, "2026-05-18", 5.0),
        _act(303, "2026-06-08", 12.0), _act(304, "2026-06-22", 12.0),
        _act(305, "2026-07-06", 11.0), _act(306, "2026-07-07", 3.0),
        _act(307, "2026-07-09", 5.2), _act(308, "2026-07-11", 5.0),
        _act(309, "2026-07-13", 11.0),
    ])
    _metrics(conn, 301, "2026-05-04", refhr=470, cad=163, best5k=1750)
    _metrics(conn, 302, "2026-05-18", refhr=466, cad=164)
    _metrics(conn, 303, "2026-06-08", refhr=460, cad=166, best5k=1700, best10k=3560)
    _metrics(conn, 304, "2026-06-22", refhr=456, cad=167, best10k=3520)
    _metrics(conn, 305, "2026-07-06", refhr=452, cad=168, best5k=1660, best10k=3470)
    _metrics(conn, 307, "2026-07-09", refhr=449, cad=169)
    _metrics(conn, 309, "2026-07-13", refhr=447, cad=170, best10k=3420)
    arch.upsert_race_prediction(conn, "2026-06-15", {"half_s": 7600}, {}, "test")
    arch.upsert_race_prediction(conn, "2026-07-13", {"half_s": 7400}, {}, "test")
    pc.run_compliance(conn, PLAN_RAW, PLAN, TODAY, MAX_HR)
    bl.derive_block_lens(conn, TODAY)
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
