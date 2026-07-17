"""Unit tests for coach_briefing.py (temp archive, synthetic inputs, no network)."""
import datetime as dt
import json
import tempfile
from pathlib import Path

import activity_archive as arch
import coach_briefing as cb
import insight_metrics as im
import plan_compliance as pc

TODAY = dt.date(2026, 7, 8)
MAX_HR = 197


def _tmp() -> Path:
    return Path(tempfile.mkdtemp())


def _day(day, date, kind, title, load, km, pace=None):
    d = {"day": day, "date": date, "kind": kind, "title": title,
         "load": load, "km": km}
    if pace:
        d["pace"] = pace
    return d


def _plan(wk3_header_km=27, wk4_days=None):
    return {
        "race": {"name": "Allgäu Panorama Halbmarathon", "date": "2026-08-09",
                 "goalTime": "1:59:59", "goalPaceSecPerKm": 341, "pb": "2:19:07"},
        "block": [
            {"wk": "Wk 2", "mon": "2026-06-29", "sun": "2026-07-05", "km": 32,
             "label": "Jun 29", "phase": "Build", "long": "16 km", "focus": "build",
             "days": [
                 _day("Mon", "2026-06-29", "cross", "Spin + Easy Run", "Easy", 4),
                 _day("Tue", "2026-06-30", "strength", "Strength", "Moderate", 0),
                 _day("Wed", "2026-07-01", "run", "Easy Run", "Easy", 5, "~6:15"),
                 _day("Thu", "2026-07-02", "strength", "Strength", "Moderate", 0),
                 _day("Fri", "2026-07-03", "run", "Threshold", "Hard", 7, "5:25–5:35"),
                 _day("Sat", "2026-07-04", "strength", "Strength · Light", "Easy", 0),
                 _day("Sun", "2026-07-05", "run", "Long Run", "Moderate", 16, "~6:10"),
             ]},
            {"wk": "Wk 3", "mon": "2026-07-06", "sun": "2026-07-12", "km": wk3_header_km,
             "label": "Jul 6", "phase": "Build", "long": "18 km", "focus": "grow",
             "days": [
                 _day("Mon", "2026-07-06", "cross", "Spin + Easy Run", "Easy", 4),
                 _day("Tue", "2026-07-07", "strength", "Strength", "Moderate", 0),
                 _day("Wed", "2026-07-08", "run", "Easy Run", "Easy", 5, "~6:15"),
                 _day("Thu", "2026-07-09", "strength", "Strength", "Moderate", 0),
                 _day("Fri", "2026-07-10", "run", "Threshold Reps", "Hard", 0, "6:00"),
                 _day("Sat", "2026-07-11", "strength", "Strength · Light", "Easy", 0),
                 _day("Sun", "2026-07-12", "run", "Long Run", "Moderate", 18, "~6:10"),
             ]},
            {"wk": "Wk 4", "mon": "2026-07-13", "sun": "2026-07-19", "km": 38,
             "label": "Jul 13", "phase": "Build", "long": "19 km",
             "focus": "longest yet", "days": wk4_days},
        ],
        "coach": {"log": [
            {"date": "2026-07-05", "text": "Block detailed to race day."},
            {"date": "2026-06-29", "text": "Plan correction: spin class."},
        ]},
    }


# A current-block lens document with DISTINCTIVE values, so the Block-report
# assertions prove numbers are lifted from the document — never recomputed.
BLOCK_LENS_CURRENT = {
    "raceName": "Allgäu Panorama Halbmarathon", "raceDate": "2026-08-09",
    "goalTime": "1:59:59",
    "window": {"start": "2026-06-29", "end": "2026-08-09"},
    "isComplete": False, "weeksTotal": 6, "weekNow": 2,
    "weeks": [],
    "execution": {"percentExecuted": 73, "scoredDays": 11,
                  "qualityHitRate": {"hit": 2, "of": 3},
                  "kmPlanned": 187, "kmPlannedToDate": 41, "kmActual": 33.4,
                  "counts": {"done": 7, "partial": 2, "missed": 2,
                             "swapped": 1, "unplanned": 0}},
    "adaptation": {
        "ef": {"deltaSPerKm": None, "reason": "insufficient-baseline",
               "startRuns": 2, "endRuns": 4},
        "cadence": {"startSpm": 165.5, "endSpm": 168, "deltaSpm": 2.5,
                    "startRuns": 4, "endRuns": 4},
        "records": [{"distance": "5k", "sec": 1626, "prevSec": 1644,
                     "date": "2026-07-03", "activityId": 3}],
        "goalGap": {"goalS": 7199, "startHalfS": 7300, "nowHalfS": 7250,
                    "gapStartS": 101, "gapNowS": 51, "deltaS": -50},
    },
    "forward": {"weeksRemaining": 5, "kmRemaining": 146,
                "silhouette": [], "undetailedWeeks": ["Wk 5"]},
    "summary": {},
}

DATA = {
    "readiness": {"score": 50, "status": "Moderate", "hrv": 52, "restingHR": 53,
                  "sleepHours": 6, "loadStatus": "Maintaining"},
    "profile": {"maxHR": 197, "restingHR": 53, "vo2maxCurrent": 45, "weightKg": 71},
    "recentRuns": [{"date": "2026-07-05", "detail": {"tempC": 31, "driftBpm": 6}}],
    "predictions": {"trend": "closing ≈131s/wk"},
    "insights": {
        "recordsFeed": [{"date": "2026-07-03", "distance": "5k",
                         "oldSec": 1644, "newSec": 1626}],
        "bestEfforts": {"allTime": {
            "oneK": {"sec": 291, "date": "2026-07-03"}, "mile": None,
            "fiveK": {"sec": 1626, "date": "2026-07-03"},
            "tenK": {"sec": 3657, "date": "2026-06-28"},
            "half": {"sec": 8347, "date": "2025-12-28"}}, "last90d": {}},
        "trajectory": {"goalSec": 7199, "weekly": [
            {"week": "2026-W27", "riegelSec": 8068, "garminSec": 7156}]},
        "efficiency": {"monthly": [
            {"month": "2026-06", "paceSecPerKm": 478, "inBandMin": 131},
            {"month": "2026-07", "paceSecPerKm": 420, "inBandMin": 20}]},
        "cadence": {"monthly": [{"month": "2026-07", "spm": 157, "inBandMin": 56}]},
    },
    "blockLens": {"lensVersion": 1, "current": BLOCK_LENS_CURRENT, "past": []},
}


def _garmin_act(aid, date, km, dur_s, hr=140, tk="running"):
    return {"activityId": aid, "startTimeLocal": f"{date} 08:00:00",
            "activityType": {"typeKey": tk}, "distance": km * 1000.0,
            "duration": float(dur_s), "averageHR": hr}


def _seeded_conn(d: Path):
    conn = arch.open_archive(d)
    arch.upsert_activities(conn, [
        _garmin_act(1, "2026-06-29", 3.9, 1900, hr=126),
        _garmin_act(2, "2026-07-01", 5.1, 2100, hr=145),
        _garmin_act(3, "2026-07-03", 7.4, 2580, hr=167),
        _garmin_act(4, "2026-07-05", 16.0, 6620, hr=148),
    ])
    # a demonstrated best 10k of 55:00 → implied 5:30/km, inside the window
    arch.upsert_run_metrics(conn, {
        "activity_id": 3, "metrics_version": im.METRICS_VERSION,
        "start_time_local": "2026-07-03 08:00:00", "is_treadmill": 0,
        "best_1k_s": 291, "best_mile_s": 498, "best_5k_s": 1626,
        "best_10k_s": 3300, "best_half_s": None,
        "refhr_time_s": None, "refhr_dist_m": None,
        "refpace_time_s": None, "refpace_cadence_x_time": None})
    plan = _plan()
    pc.run_compliance(conn, "raw", plan, TODAY, MAX_HR)
    return conn, plan


# ── pace parser (task 5.2) ───────────────────────────────────────────────────
def test_parse_pace_target():
    assert cb.parse_pace_target("5:25–5:35") == 330
    assert cb.parse_pace_target("~6:10") == 370
    assert cb.parse_pace_target("easy + 5:41") == 341
    assert cb.parse_pace_target("5:41") == 341
    assert cb.parse_pace_target("Z2") is None
    assert cb.parse_pace_target(None) is None
    assert cb.parse_pace_target(370) is None


# ── signal sections (tasks 5.2/5.3) ──────────────────────────────────────────
def test_staleness_note_fires_and_goal_intent_is_quiet():
    d = _tmp()
    conn, plan = _seeded_conn(d)
    # future Hard day at 6:00 vs implied 5:30 → 30 s/km slower → note
    notes = cb.staleness_notes(conn, plan, TODAY)
    assert len(notes) == 1 and "6:00" in notes[0] and "slower" in notes[0]
    # a goal-pace session (5:41 vs goal 341) draws no note
    plan["block"][1]["days"][4]["pace"] = "5:41"
    assert cb.staleness_notes(conn, plan, TODAY) == []
    # unparseable targets are skipped silently
    plan["block"][1]["days"][4]["pace"] = "hard but controlled"
    assert cb.staleness_notes(conn, plan, TODAY) == []
    conn.close()


def test_integrity_warnings():
    plan = _plan(wk4_days=None)  # future week undetailed
    warnings = cb.integrity_warnings(plan, TODAY)
    assert any("Wk 4" in w and "no days" in w for w in warnings)
    # header km vs day sum: Wk 3 days sum to 27 (4+5+0+18); header says 35
    warnings = cb.integrity_warnings(_plan(wk3_header_km=35), TODAY)
    assert any("Wk 3" in w and "35" in w for w in warnings)
    # past race date
    past = _plan()
    past["race"]["date"] = "2026-07-01"
    assert any("in the past" in w for w in cb.integrity_warnings(past, TODAY))
    # a fully consistent plan (Wk 4 detailed) is quiet
    ok = _plan(wk4_days=[
        _day("Mon", "2026-07-13", "run", "Easy", "Easy", 38)] + [
        _day("Tue", f"2026-07-{14 + i}", "strength", "S", "Easy", 0) for i in range(6)])
    assert cb.integrity_warnings(ok, TODAY) == []


# ── rendering (tasks 5.1/5.5) ────────────────────────────────────────────────
SECTIONS = ["# Coach Briefing", "## Race countdown", "## Plan vs actual",
            "## Block report", "## Records & best efforts", "## Trajectory",
            "## Progress trends", "## Readiness today", "## Plan staleness",
            "## Plan integrity", "## Coach log", "## Profile"]


def test_render_sections_fixed_order_and_content():
    d = _tmp()
    conn, plan = _seeded_conn(d)
    text = cb.render_briefing(conn, plan, DATA, TODAY)
    conn.close()
    positions = [text.find(s) for s in SECTIONS]
    assert all(p >= 0 for p in positions), \
        f"missing sections: {[s for s, p in zip(SECTIONS, positions) if p < 0]}"
    assert positions == sorted(positions), "sections out of fixed order"
    assert "32 days" in text, "race countdown arithmetic"
    assert "Wk 2 (2026-06-29 → 2026-07-05) — closed" in text
    assert "Wk 3 (2026-07-06 → 2026-07-12) — open" in text
    assert "| 2026-07-05 | Sun |" in text and "done" in text
    assert "31 °C · drift +6" in text, "temp/drift joined onto the actual"
    assert "2:14:28" in text, "Riegel projection formatted"
    assert "closing ≈131s/wk" in text
    assert "(thin sample)" in text, "thin in-band months are caveated"
    assert "⚠" in text and "Wk 4" in text, "integrity warning rendered"
    assert "Block detailed to race day." in text, "coach log tail"
    assert text == cb.render_briefing(_seeded_conn(_tmp())[0], plan, DATA, TODAY), \
        "deterministic: same inputs → byte-identical briefing"


def test_block_report_numbers_match_the_lens_document():
    """Every Block-report number is lifted from blockLens.current — the same
    document the dashboard shows — never recomputed from the archive."""
    d = _tmp()
    conn, plan = _seeded_conn(d)
    text = cb.render_briefing(conn, plan, DATA, TODAY)
    conn.close()
    assert "week 2 of 6" in text, "weekNow/weeksTotal from the document"
    assert "73% executed" in text, "percent executed verbatim"
    assert "33.4 of 41 km planned to date" in text
    assert "quality 2/3" in text
    assert "cadence @ ref pace: 165.5 → 168 spm (+2.5 spm)" in text
    assert "goal gap (1:59:59): +1:41 → +0:51 vs goal — closing" in text
    assert "5k 27:06 (was 27:24)" in text, "records fell inside the block"
    # judgment hooks, stated as facts
    assert "⚠ volume behind plan to date: 33.4 of 41 km (81%)" in text
    assert "⚠ undetailed future weeks: Wk 5" in text


def test_block_report_null_metric_is_stated_not_omitted():
    d = _tmp()
    conn, plan = _seeded_conn(d)
    text = cb.render_briefing(conn, plan, DATA, TODAY)
    assert "pace @ ref HR: insufficient data (insufficient-baseline)" in text, \
        "a null EF delta is said out loud, never dropped or invented"
    # a non-null EF delta that is not improving fires the stalling hook
    stalled = json.loads(json.dumps(DATA))
    stalled["blockLens"]["current"]["adaptation"]["ef"] = {
        "startPaceSPerKm": 452, "endPaceSPerKm": 455, "deltaSPerKm": 3.0,
        "startRuns": 4, "endRuns": 4}
    text = cb.render_briefing(conn, plan, stalled, TODAY)
    conn.close()
    assert "pace @ ref HR: 7:32 → 7:35 /km (+3 s/km)" in text
    assert "⚠ pace @ ref HR is not improving across this block (+3 s/km)" in text


def test_block_report_omitted_without_a_lens():
    d = _tmp()
    conn, plan = _seeded_conn(d)
    no_lens = {k: v for k, v in DATA.items() if k != "blockLens"}
    text = cb.render_briefing(conn, plan, no_lens, TODAY)
    assert "## Block report" not in text, "no lens → no section"
    for s in SECTIONS:
        if s != "## Block report":
            assert s in text, f"section {s} must render regardless"
    # a lens with only past blocks (no current) also omits the section
    past_only = json.loads(json.dumps(DATA))
    past_only["blockLens"] = {"lensVersion": 1, "past": [{"raceDate": "2026-05-10"}]}
    assert "## Block report" not in cb.render_briefing(conn, plan, past_only, TODAY)
    conn.close()


def test_render_survives_missing_insights():
    d = _tmp()
    conn, plan = _seeded_conn(d)
    data = {k: v for k, v in DATA.items() if k != "insights"}
    text = cb.render_briefing(conn, plan, data, TODAY)
    conn.close()
    assert "insights unavailable this sync" in text
    for s in SECTIONS:
        assert s in text, f"section {s} must render regardless"


def test_write_briefing_atomic_replace():
    d = _tmp()
    target = d / "coach-briefing.md"
    cb.write_briefing(target, "first")
    cb.write_briefing(target, "second")
    assert target.read_text(encoding="utf-8") == "second"
    leftovers = [p for p in d.iterdir() if p.name != "coach-briefing.md"]
    assert leftovers == [], f"temp files must not survive: {leftovers}"


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_"):
            _fn()
            print("ok", _name)
    print("ALL PASS")
