"""The Health Connect 'shelf': frozen ingest rows (summary_json carries sessionUid)
that live beside Garmin rows in one archive. Garmin passes must leave them alone."""
import datetime as dt
import importlib.util
from pathlib import Path

import pytest

from garmin_fixtures import garmin_row, shelf_row

REPO = Path(__file__).resolve().parent

S1, S2, G1, G2 = 9_000_000_001, 9_000_000_002, 20_000_000_001, 20_000_000_002


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


arch = _load("activity_archive_shelf_test", REPO / "activity_archive.py")


@pytest.fixture
def conn(tmp_path):
    c = arch.open_archive(tmp_path)
    shelf_row(c, S1, "uid-1", dt.datetime(2026, 9, 1, 7, 0), 1800, 5000.0, streams=True)
    shelf_row(c, S2, "uid-2", dt.datetime(2026, 9, 3, 7, 0), 1800, 5000.0, streams=False)
    garmin_row(c, G1, dt.datetime(2026, 10, 1, 7, 0), 1800, 5000.0)
    garmin_row(c, G2, dt.datetime(2026, 10, 3, 7, 0), 1800, 5000.0)
    yield c
    c.close()


def test_missing_detail_ids_never_lists_the_shelf(conn):
    assert set(arch.missing_detail_ids(conn)) == set()  # garmin rows carry detail_json={}
    conn.execute("UPDATE activities SET detail_json=NULL WHERE activity_id=?", (G1,))
    assert arch.missing_detail_ids(conn) == [G1]


def test_garmin_work_lists_exclude_the_shelf(conn):
    shelf = {S1, S2}
    # positive control: a Garmin row with no streams IS listed, so the
    # exclusion below is not a vacuous empty list
    assert {G1, G2} <= set(arch.runs_missing_streams(conn))
    for ids in (arch.runs_missing_streams(conn),
                arch.runs_missing_distilled(conn, 1),
                arch.runs_missing_laps(conn),
                arch.runs_missing_maps(conn),
                [r[0] for r in arch.runs_missing_metrics(conn, 3)]):
        assert not shelf & set(ids)


def test_streamed_runs_keeps_the_shelf(conn):  # intervals are source-agnostic (spec D3)
    assert S1 in {aid for aid, _ in arch.streamed_runs(conn)}


def test_is_shelf_summary():
    assert arch.is_shelf_summary({"sessionUid": "x"}) and not arch.is_shelf_summary({"activityId": 1})
    assert not arch.is_shelf_summary(None)


def test_shelf_clause_alias():
    assert arch.shelf_clause() == "json_extract(a.summary_json, '$.sessionUid') IS NOT NULL"
    assert arch.shelf_clause(None) == "json_extract(summary_json, '$.sessionUid') IS NOT NULL"


# ──────────────────────────────────────────────────────────────────────────────
# Task 2: Garmin wins the seam
# ──────────────────────────────────────────────────────────────────────────────
import os  # noqa: E402
import sys  # noqa: E402

from garmin_fixtures import FakeClient, load_sync_garmin  # noqa: E402

shelf = _load("shelf_under_test", REPO / "shelf.py")

S3 = 9_000_000_003


@pytest.fixture
def seam(tmp_path):
    c = arch.open_archive(tmp_path)
    yield c
    c.close()


def _ids(c):
    return {r[0] for r in c.execute("SELECT activity_id FROM activities")}


def _derived_rows(c, aid):
    c.execute("INSERT INTO run_metrics (activity_id, metrics_version, start_time_local, "
              "is_treadmill, computed_at) VALUES (?, 1, '2026-10-19T19:09:04', 0, 'x')", (aid,))
    c.execute("INSERT INTO run_intervals (activity_id, lens_version, start_time_local, "
              "shape, source, doc_json, computed_at) "
              "VALUES (?, 1, '2026-10-19T19:09:04', 'steady', 'test', '{}', 'x')", (aid,))
    c.commit()


def _count(c, table, aid):
    return c.execute(f"SELECT COUNT(*) FROM {table} WHERE activity_id=?", (aid,)).fetchone()[0]


def test_overlapping_shelf_row_is_pruned_garmin_kept(seam):
    shelf_row(seam, S1, "u1", "2026-10-19T19:09:04", 883, 1350)
    garmin_row(seam, G1, "2026-10-19 19:10:00", 900, 1360)
    _derived_rows(seam, S1)
    assert _count(seam, "run_metrics", S1) == 1 and _count(seam, "run_intervals", S1) == 1
    assert shelf.resolve_seam(seam) == [S1]
    assert _ids(seam) == {G1}
    assert _count(seam, "run_metrics", S1) == 0
    assert _count(seam, "run_intervals", S1) == 0


def test_connect_app_shelf_row_goes_without_overlap(seam):
    shelf_row(seam, S2, "u2", "2026-10-12T08:00:00", 1800, 5000,
              source=shelf.GARMIN_CONNECT_SOURCE)
    assert shelf.resolve_seam(seam) == [S2]


def test_disjoint_shelf_rows_survive_and_seam_is_idempotent(seam):
    shelf_row(seam, S3, "u3", "2026-10-18T11:34:03", 1553, 3710)
    garmin_row(seam, G1, "2026-10-19 19:10:00", 900, 1360)
    assert shelf.resolve_seam(seam) == [] and shelf.resolve_seam(seam) == []
    assert _ids(seam) == {S3, G1}


def test_seam_matches_across_timestamp_formats(seam):  # Review Focus 2
    shelf_row(seam, S1, "u1", "2026-10-19T19:09:04.512", 883, 1350)
    garmin_row(seam, G1, "2026-10-19 19:09:04", 883, 1350)
    assert shelf.resolve_seam(seam) == [S1]


def test_shelf_row_with_null_duration_never_crashes(seam):
    shelf_row(seam, S1, "u1", "2026-10-19T19:09:04", 883, 1350)
    garmin_row(seam, G1, "2026-10-19 19:00:00", 3600, 9000)
    seam.execute("UPDATE activities SET duration_s=NULL WHERE activity_id=?", (S1,))
    seam.commit()
    # zero-length span at its start sits inside the Garmin run's span
    assert shelf.resolve_seam(seam) == [S1]


def test_shelf_rows_do_not_prune_each_other(seam):
    shelf_row(seam, S1, "u1", "2026-10-19T19:09:04", 883, 1350)
    shelf_row(seam, S3, "u3", "2026-10-19T19:10:00", 883, 1350)
    assert shelf.resolve_seam(seam) == []


@pytest.fixture
def sg_env(tmp_path, monkeypatch):
    saved = dict(os.environ)
    sg = load_sync_garmin(tmp_path)
    monkeypatch.setattr(sg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(sg, "CACHE_DIR", tmp_path / "cache")
    yield sg, tmp_path
    os.environ.clear()
    os.environ.update(saved)


def _garmin_act():
    return {"activityId": G1, "startTimeLocal": "2026-10-19 19:10:00",
            "activityType": {"typeKey": "running"}, "activityName": "Run",
            "distance": 1360.0, "duration": 900.0, "averageHR": 150.0, "maxHR": 170.0}


def _expected(c):
    return int(arch.get_meta(c, "expected_activity_count"))


def test_archive_step_prunes_before_ratcheting(sg_env):
    sg, data_dir = sg_env
    c = arch.open_archive(data_dir)
    shelf_row(c, S1, "u1", "2026-10-19T19:09:04", 883, 1350)
    c.close()
    sg.archive_step(FakeClient(), [_garmin_act()])
    c = arch.open_archive(data_dir)
    try:
        assert _ids(c) == {G1}
        assert _expected(c) == 1
    finally:
        c.close()
    assert sg.verify_archive() == 0


def test_backfill_prunes_before_ratcheting(sg_env):
    sg, data_dir = sg_env
    c = arch.open_archive(data_dir)
    shelf_row(c, S1, "u1", "2026-10-19T19:09:04", 883, 1350)
    c.close()
    act = _garmin_act()
    client = FakeClient({"get_activities_by_date":
                         lambda start, end: [act] if start.startswith("2026") else []})
    sg.run_backfill(client)
    c = arch.open_archive(data_dir)
    try:
        assert _ids(c) == {G1}
        assert _expected(c) == 1
    finally:
        c.close()
    sg.archive_step(FakeClient(), [act])
    assert sg.verify_archive() == 0


# ──────────────────────────────────────────────────────────────────────────────
# Task 3: the cockpit sees the shelf
# ──────────────────────────────────────────────────────────────────────────────
import json  # noqa: E402

from test_garmin_parity import RESPONSES  # noqa: E402

import ingest_builder  # noqa: E402

T3_S1, T3_S2, T3_S3 = 9_100_000_001, 9_100_000_002, 9_100_000_003
SHELF_DATES = {"2026-10-20", "2026-09-03", "2026-09-01"}


@pytest.fixture
def t3(sg_env):
    sg, data_dir = sg_env
    c = arch.open_archive(data_dir)
    shelf_row(c, T3_S1, "t3-1", dt.datetime(2026, 10, 20, 7, 0), 1800, 5000.0, streams=True)
    shelf_row(c, T3_S2, "t3-2", dt.datetime(2026, 9, 3, 7, 0), 1800, 5000.0, streams=False)
    shelf_row(c, T3_S3, "t3-3", dt.datetime(2026, 9, 1, 7, 0), 5400, 16000.0, streams=True)
    acts = shelf.shelf_activities(c)
    yield sg, c, acts
    c.close()


def summary_json_of(c, aid):
    return c.execute("SELECT summary_json FROM activities WHERE activity_id=?", (aid,)).fetchone()[0]


def stored_distilled(c, aid):
    return json.loads(c.execute(
        "SELECT detail_distilled_json FROM activities WHERE activity_id=?", (aid,)).fetchone()[0])


def by_id(acts, aid):
    return next(a for a in acts if a["activityId"] == aid)


def _garmin_acts():
    return [dict(_garmin_act(), activityId=G1, startTimeLocal="2026-10-01 07:00:00"),
            dict(_garmin_act(), activityId=G2, startTimeLocal="2026-10-03 07:00:00")]


def test_projection_shape_matches_ingest_pace(t3):
    sg, c, acts = t3
    assert [a["activityId"] for a in acts] == [T3_S1, T3_S2, T3_S3]  # newest first
    a = acts[0]
    run = json.loads(summary_json_of(c, T3_S1))
    t, km = ingest_builder._effort(run)
    assert a["splitsShelf"] is True and a["splitsPaceSecPerKm"] == round(t / km)
    assert a["activityType"]["typeKey"] == "running" and a["distance"] == run["distanceM"]
    assert a["duration"] == run["durationS"] and a["averageHR"] == 143 and a["maxHR"] == 162
    assert a["startTimeLocal"].startswith("2026-10-20")


def test_projection_tolerates_a_row_without_streams(t3):  # Review Focus 3
    sg, c, acts = t3
    a = by_id(acts, T3_S2)
    assert a["splitsDetail"] is None and a["splitsPaceSecPerKm"] > 0


def test_projection_without_speed_samples_uses_elapsed_pace(t3):
    sg, c, acts = t3
    run = json.loads(summary_json_of(c, T3_S2))
    run["speedSamples"] = []
    c.execute("UPDATE activities SET summary_json=? WHERE activity_id=?", (json.dumps(run), T3_S2))
    c.commit()
    assert by_id(shelf.shelf_activities(c), T3_S2)["splitsPaceSecPerKm"] == 360


def test_recent_runs_mix_shelf_and_garmin_without_calling_garmin_for_shelf(t3):
    sg, c, acts = t3
    client = FakeClient({})
    rows = sg.fetch_recent_runs(client, _garmin_acts() + acts)
    assert [r["date"] for r in rows] == sorted((r["date"] for r in rows), reverse=True)
    shelf_rows = [r for r in rows if r["date"] in SHELF_DATES]
    assert len(shelf_rows) == 3
    assert shelf_rows[0]["detail"] == stored_distilled(c, T3_S1) and shelf_rows[0]["cad"] is None
    assert shelf_rows[0]["vo2"] is None and "detail" not in shelf_rows[1]
    assert not any(str(T3_S1) in repr(args) for _, args in client.calls)
    assert not any(str(s) in repr(args) for s in (T3_S2, T3_S3) for _, args in client.calls)
    assert {args[0] for n, args in client.calls if n == "get_activity_details"} == {G1, G2}


def test_recent_shelf_rows_read_as_the_ingest_path_showed_them(t3):
    sg, c, acts = t3
    rows = sg.fetch_recent_runs(FakeClient({}), acts)
    long = next(r for r in rows if r["date"] == "2026-09-01")
    # ingest labelled every plain run "Run"; classify() would say "Long Run" at 16 km
    assert long["type"] == "Run" and long["km"] == 16.0 and long["time"] == "1:30:00"
    assert rows[0]["km"] == 5.0 and rows[0]["hr"] == 143
    c.execute("UPDATE activities SET avg_hr=NULL WHERE activity_id=?", (T3_S2,))
    c.commit()
    bare = json.loads(summary_json_of(c, T3_S2))
    bare["avgHr"] = None
    c.execute("UPDATE activities SET summary_json=? WHERE activity_id=?", (json.dumps(bare), T3_S2))
    c.commit()
    rows = sg.fetch_recent_runs(FakeClient({}), shelf.shelf_activities(c))
    assert next(r for r in rows if r["date"] == "2026-09-03")["hr"] is None


def test_hr_zones_skip_shelf_runs(t3):
    sg, c, acts = t3
    client = FakeClient({})
    this_week = [a for a in acts if a["startTimeLocal"] >= "2026-10-19"]
    assert this_week
    sg.fetch_hr_zones_this_week(client, this_week, 199)
    assert client.calls == []


def test_build_data_counts_shelf_km_in_weekly_heatmap_and_ctl(t3):
    sg, c, acts = t3
    data = sg.build_data(FakeClient(RESPONSES), [], shelf_acts=acts)
    assert sum(data["heatmapKm"]) == pytest.approx(sum(a["distance"] for a in acts) / 1000, abs=0.2)
    assert data["history"]["ctl"][-1] > 0 and sum(data["history"]["weeklyKm"]) > 0
    assert any(r["date"] == "2026-10-20" for r in data["recentRuns"])


def test_build_data_keeps_shelf_history_when_garmin_fails(t3):  # Review Focus 4
    sg, c, acts = t3
    data = sg.build_data(FakeClient(fail=True), [], shelf_acts=acts)
    assert sum(data["heatmapKm"]) > 0


def test_build_data_without_shelf_is_unchanged(t3):
    sg, c, acts = t3
    a = sg.build_data(FakeClient(RESPONSES), _garmin_acts())
    b = sg.build_data(FakeClient(RESPONSES), _garmin_acts(), shelf_acts=[])
    assert a == b


def test_main_loads_the_projection_and_never_archives_it(sg_env, monkeypatch):
    sg, data_dir = sg_env
    c = arch.open_archive(data_dir)
    shelf_row(c, T3_S1, "t3-1", dt.datetime(2026, 10, 20, 7, 0), 1800, 5000.0)
    c.close()
    loaded = sg._load_shelf_acts()
    assert [a["activityId"] for a in loaded] == [T3_S1]
    seen = {}
    client = FakeClient(RESPONSES)
    monkeypatch.setattr(sg, "connect", lambda: client)
    monkeypatch.setattr(sg, "load_activities", lambda cl: _garmin_acts())
    monkeypatch.setattr(sg, "archive_step", lambda cl, acts: seen.setdefault("archived", list(acts)))
    for step in ("workouts_step", "distill_step", "intervals_step", "compliance_step",
                 "briefing_step", "wellness_step", "metrics_step", "course_lens_step"):
        monkeypatch.setattr(sg, step, lambda *a, **k: None)
    monkeypatch.setattr(sg, "validate", lambda d: None)
    monkeypatch.setattr(sg, "OUTPUT_PATH", data_dir / "garmin-data.js")
    monkeypatch.setattr(sys, "argv", ["sync_garmin.py"])
    sg.main()
    assert {a["activityId"] for a in seen["archived"]} == {G1, G2}
    assert "2026-10-20" in (data_dir / "garmin-data.js").read_text(encoding="utf-8")


def _set_steps(c, aid, steps):
    run = json.loads(summary_json_of(c, aid))
    run["steps"] = steps
    c.execute("UPDATE activities SET summary_json=? WHERE activity_id=?", (json.dumps(run), aid))
    c.commit()
    return run


def test_shelf_run_with_steps_keeps_the_ingest_cadence(t3):
    sg, c, acts = t3
    run = _set_steps(c, T3_S1, 4800)
    expected = ingest_builder._cadence(run)
    assert expected
    acts = shelf.shelf_activities(c)
    assert by_id(acts, T3_S1)["averageRunningCadenceInStepsPerMinute"] == expected
    rows = sg.fetch_recent_runs(FakeClient({}), acts)
    assert next(r for r in rows if r["date"] == "2026-10-20")["cad"] == expected


def test_shelf_run_without_steps_has_no_cadence(t3):
    sg, c, acts = t3
    assert "averageRunningCadenceInStepsPerMinute" not in by_id(acts, T3_S2)
    rows = sg.fetch_recent_runs(FakeClient({}), acts)
    assert next(r for r in rows if r["date"] == "2026-09-03")["cad"] is None


# ──────────────────────────────────────────────────────────────────────────────
# Task 4: a young account's monthly series
# ──────────────────────────────────────────────────────────────────────────────
import copy  # noqa: E402


def shelf_acts_from(date, km=5.0, pace=360):
    """A shelf-projection run (what shelf.shelf_activities hands the cockpit)."""
    return [{"activityId": 9_400_000_001, "startTimeLocal": f"{date} 07:00:00",
             "activityType": {"typeKey": "running"}, "distance": km * 1000.0,
             "duration": km * pace, "splitsShelf": True,
             "splitsPaceSecPerKm": pace, "splitsDetail": {}}]


def garmin_acts_from(date, vo2=None, cad=None, km=5.0, pace=330):
    a = {"activityId": 20_400_000_001, "startTimeLocal": f"{date} 07:00:00",
         "activityType": {"typeKey": "running"}, "distance": km * 1000.0,
         "duration": km * pace, "averageHR": 150.0, "maxHR": 170.0}
    if vo2 is not None:
        a["vO2MaxValue"] = vo2
    if cad is not None:
        a["averageRunningCadenceInStepsPerMinute"] = cad
    return [a]


def test_lead_null_ffill(sg_env):
    sg, _ = sg_env
    assert sg.lead_null_ffill([]) == []
    assert sg.lead_null_ffill([None, None]) == [None, None]
    assert sg.lead_null_ffill([None, 3, None, 5, None]) == [None, 3, 3, 5, 5]


def test_young_account_window_starts_at_first_run_without_backfill(sg_env):
    sg, _ = sg_env
    acts = shelf_acts_from("2026-06-10") + garmin_acts_from("2026-10-19", vo2=44.0, cad=162)
    client = FakeClient({"get_max_metrics": [{"generic": {"vo2MaxPreciseValue": 43.7}}]})
    m = sg.fetch_monthly(client, acts)
    assert m["vo2maxStartMonth"] == "2026-06" and len(m["paceSecPerKm"]) == 5
    assert m["vo2max"][:4] == [None] * 4 and m["vo2max"][-1] == 44.0
    assert m["cadenceSpm"][:4] == [None] * 4 and m["cadenceSpm"][-1] == 162
    assert all(v for v in m["paceSecPerKm"])          # pace is filled throughout
    assert all(name != "get_max_metrics" or args[0] >= "2026-10" for name, args in client.calls)


def test_all_shelf_account_never_asks_garmin_for_vo2(sg_env):
    sg, _ = sg_env
    client = FakeClient({"get_max_metrics": [{"generic": {"vo2MaxPreciseValue": 43.7}}]})
    m = sg.fetch_monthly(client, shelf_acts_from("2026-08-10"))
    assert m["vo2max"] == [None] * 3 and not client.calls


def test_no_runs_gives_the_current_month_only(sg_env):  # controller ruling R5
    sg, _ = sg_env
    m = sg.fetch_monthly(FakeClient({}), [])
    assert m == {"vo2maxStartMonth": "2026-10", "vo2max": [None],
                 "paceSecPerKm": [None], "cadenceSpm": [None]}


def _young_data(sg):
    acts = shelf_acts_from("2026-06-10") + garmin_acts_from("2026-10-19", vo2=44.0, cad=162)
    return sg.build_data(FakeClient(RESPONSES), acts)


def test_validate_accepts_leading_nulls_only(sg_env):
    sg, _ = sg_env
    young = _young_data(sg)
    assert young["history"]["vo2max"][0] is None
    sg.validate(young)                                  # leading None ok
    for key in ("vo2max", "paceSecPerKm", "cadenceSpm"):
        bad = copy.deepcopy(young)
        bad["history"][key][2] = 40 if key != "vo2max" else 40.0
        bad["history"][key][3] = None                   # interior: a None after a value
        with pytest.raises(AssertionError):
            sg.validate(bad)
        bad = copy.deepcopy(young)
        bad["history"][key][-2] = 40                    # a real value, then a trailing None
        bad["history"][key][-1] = None
        with pytest.raises(AssertionError):
            sg.validate(bad)
    for key in ("weeklyKm", "weeklyRuns", "ctl", "atl"):
        bad = copy.deepcopy(young)
        bad["history"][key][0] = None
        with pytest.raises(AssertionError):
            sg.validate(bad)


def test_no_vo2_anywhere_omits_vo2maxCurrent_and_still_validates(sg_env):
    sg, _ = sg_env
    data = sg.build_data(FakeClient({}), [], shelf_acts=shelf_acts_from("2026-10-10"))
    assert "vo2maxCurrent" not in data["profile"]
    assert data["history"]["vo2max"] == [None]
    sg.validate(data)


# ── Task 5: no Felix numbers as Garmin-path fallbacks ────────────────────────
def _plan_with_goal(data_dir, goal):
    (data_dir / "plan-data.js").write_text(
        "export const planData = { race: { name: 'Half', date: '2026-10-18', "
        f"goalTime: '{goal}' }}, block: [] }};\n", encoding="utf-8")


def test_half_goal_comes_from_the_plan(sg_env):
    sg, data_dir = sg_env
    _plan_with_goal(data_dir, "2:29:59")
    assert sg._plan_goal_time() == "2:29:59"
    assert sg.build_data(FakeClient(RESPONSES), [])["predictions"]["halfGoal"] == "2:29:59"


def test_half_goal_is_omitted_when_the_plan_has_none(sg_env):
    sg, data_dir = sg_env                               # no plan-data.js at all
    assert sg._plan_goal_time() is None
    assert "halfGoal" not in sg.build_data(FakeClient(RESPONSES), [])["predictions"]
    assert "halfGoal" not in sg.fetch_predictions({}, None)
    assert sg.fetch_predictions({}, "1:59:59")["halfGoal"] == "1:59:59"


def test_profile_omits_what_garmin_did_not_say(sg_env):
    sg, _ = sg_env
    os.environ.pop("ATHLETE_NAME", None)
    p = sg.fetch_profile(FakeClient({}), None)
    for k in ("restingHR", "weightKg", "vo2maxCurrent"):
        assert k not in p
    assert p["name"] == "Athlete"


def test_profile_name_comes_from_the_client_when_env_is_unset(sg_env):
    sg, _ = sg_env
    os.environ.pop("ATHLETE_NAME", None)
    c = FakeClient({})
    c.full_name = "Max Keller"
    assert sg.fetch_profile(c, None)["name"] == "Max"


def test_profile_keeps_what_garmin_said(sg_env):
    sg, _ = sg_env
    p = sg.fetch_profile(FakeClient(RESPONSES), 44.04)
    assert (p["restingHR"], p["weightKg"], p["vo2maxCurrent"]) == (48, 80.5, 44.0)


def test_readiness_omitted_without_evidence(sg_env):          # Review Focus 5
    sg, _ = sg_env
    empty = [{"hours": 0.0, "hrv": 0, "deepPct": 0}] * 14
    assert sg.fetch_readiness(FakeClient({}), empty, 199) is None


def test_readiness_without_rhr_omits_the_key_and_load_label_is_honest(sg_env):
    sg, _ = sg_env
    night = [{"hours": 7.0, "hrv": 55, "deepPct": 18}]
    r = sg.fetch_readiness(
        FakeClient({"get_training_readiness": [{"score": 64, "level": "READY"}]}), night, 199)
    assert "restingHR" not in r and r["loadStatus"] == "" and r["score"] == 64


def test_readiness_level_none_falls_back_to_the_score_label(sg_env):
    # a new watch's readiness is still calibrating: Garmin sends the string
    # "NONE" as its level, which must not reach the card as "None"
    sg, _ = sg_env
    night = [{"hours": 7.2, "hrv": 94, "deepPct": 18}]
    for level in ("NONE", "none", ""):
        r = sg.fetch_readiness(
            FakeClient({"get_training_readiness": [{"score": 84, "level": level}]}), night, 199)
        assert r["status"] == sg._readiness_label(84) == "Primed"
    r = sg.fetch_readiness(
        FakeClient({"get_training_readiness": [{"score": 64, "level": "MODERATE"}]}), night, 199)
    assert r["status"] == "Moderate"


def test_build_data_omits_readiness_for_an_account_with_no_evidence(sg_env):
    sg, _ = sg_env
    data = sg.build_data(FakeClient({}), [])
    assert "readiness" not in data
    for k in ("restingHR", "weightKg", "vo2maxCurrent"):
        assert k not in data["profile"]
    sg.validate(data)


def test_wellness_step_takes_an_empty_readiness(sg_env):
    sg, data_dir = sg_env
    sg.wellness_step(FakeClient({}), {}, [])            # the fetch_sleep-failed branch
    c = arch.open_archive(data_dir)
    try:
        assert c.execute("SELECT COUNT(*) FROM daily_wellness").fetchone()[0] == 1
    finally:
        c.close()


# ── Task 6: zones per athlete, zone-card edges from the watch ────────────────
import interval_lens as il  # noqa: E402
from garmin_fixtures import _load as _fx_load  # noqa: E402

ib_under_test = _fx_load("ingest_builder_zone_test", REPO / "ingest_builder.py")


@pytest.fixture
def zn(sg_env, monkeypatch):
    sg, data_dir = sg_env
    monkeypatch.setenv("ATHLETE_MAX_HR", "199")
    monkeypatch.delenv("ATHLETE_RESTING_HR", raising=False)
    c = arch.open_archive(data_dir)
    shelf_row(c, S1, "uid-1", dt.datetime(2026, 9, 1, 7, 0), 1800, 5000.0, streams=True)
    garmin_row(c, G1, dt.datetime(2026, 10, 1, 7, 0), 1800, 5000.0)
    streams = arch.streams_payload(c, S1)
    assert arch.write_streams(c, G1, streams)
    assert arch.write_distilled(c, G1, {"intervals": {"stale": True}}, version=sg.GARMIN_DISTILL_VERSION)
    yield sg, c
    c.close()


def docs(c):
    return dict(c.execute("SELECT activity_id, doc_json FROM run_intervals").fetchall())


def garmin_distilled_versions(c):
    return {r[0] for r in c.execute(
        "SELECT a.distilled_version FROM activities a WHERE a.detail_distilled_json IS NOT NULL "
        f"AND NOT {arch.shelf_clause('a')}")}


def distilled_of(c, aid):
    return c.execute("SELECT detail_distilled_json FROM activities WHERE activity_id=?", (aid,)).fetchone()[0]


def doc_of(c, aid):
    return c.execute("SELECT doc_json FROM run_intervals WHERE activity_id=?", (aid,)).fetchone()[0]


def test_zone_model_follows_resting_hr_env(sg_env, monkeypatch):
    sg, _ = sg_env
    monkeypatch.setenv("ATHLETE_MAX_HR", "199")
    monkeypatch.delenv("ATHLETE_RESTING_HR", raising=False)
    assert sg.athlete_zone_bounds() == [100, 119, 139, 159, 179, 199]
    monkeypatch.setenv("ATHLETE_RESTING_HR", "57")
    assert sg.athlete_zone_bounds() == [128, 142, 156, 171, 185, 199]
    assert sg.athlete_zone_bounds(max_hr=190) == il.zone_bounds(190, 57)


def test_first_stamp_does_not_rescore_then_a_change_does(zn, monkeypatch):
    sg, c = zn
    sg.derive_intervals(c)                       # meta absent -> stamp only
    assert json.loads(arch.get_meta(c, "interval_zone_bounds")) == [100, 119, 139, 159, 179, 199]
    assert garmin_distilled_versions(c) == {sg.GARMIN_DISTILL_VERSION}   # first stamp invalidates nothing
    before = docs(c)
    assert before
    sg.derive_intervals(c)                       # unchanged -> nothing moves
    assert docs(c) == before
    seen = []
    real = il.build_document
    monkeypatch.setattr(il, "build_document",
                        lambda *a, **k: (seen.append(a[4]), real(*a, **k))[1])
    sg.derive_intervals(c)
    assert seen == []                            # same edges again -> no rescoring
    monkeypatch.setenv("ATHLETE_RESTING_HR", "57")
    sg.derive_intervals(c)
    assert seen and all(b == [128, 142, 156, 171, 185, 199] for b in seen)   # every doc rescored
    assert garmin_distilled_versions(c) == {None}
    assert json.loads(arch.get_meta(c, "interval_zone_bounds")) == [128, 142, 156, 171, 185, 199]
    assert json.loads(distilled_of(c, S1))["intervals"] == il.compact(json.loads(doc_of(c, S1)))


def _poison(c, aid):
    d = json.loads(distilled_of(c, aid))
    d["intervals"], d["zoneMin"] = {"poison": True}, [99, 99, 99, 99, 99]
    c.execute("UPDATE activities SET detail_distilled_json=? WHERE activity_id=?",
              (json.dumps(d), aid))
    c.commit()


def _summary(c, aid):
    return json.loads(c.execute("SELECT summary_json FROM activities WHERE activity_id=?", (aid,)).fetchone()[0])


def test_zone_change_patches_the_shelf_copy_and_not_the_garmin_one(zn, monkeypatch):
    sg, c = zn
    sg.derive_intervals(c)
    run = _summary(c, S1)
    old_zone_min = ib_under_test.zone_minutes(run, il.zone_bounds(199))
    new_zone_min = ib_under_test.zone_minutes(run, il.zone_bounds(199, 57))
    assert old_zone_min != new_zone_min
    _poison(c, S1)
    _poison(c, G1)
    g1_before = distilled_of(c, G1)
    monkeypatch.setenv("ATHLETE_RESTING_HR", "57")
    sg.derive_intervals(c)
    d = json.loads(distilled_of(c, S1))
    assert d["intervals"] == il.compact(json.loads(doc_of(c, S1)))
    assert d["zoneMin"] == new_zone_min
    assert distilled_of(c, G1) == g1_before             # Garmin copies go via _distill_pass


def test_shelf_row_without_hr_samples_keeps_its_zone_min(zn, monkeypatch):
    sg, c = zn
    sg.derive_intervals(c)
    run = _summary(c, S1)
    run["hrSamples"] = []
    c.execute("UPDATE activities SET summary_json=? WHERE activity_id=?", (json.dumps(run), S1))
    c.commit()
    _poison(c, S1)
    monkeypatch.setenv("ATHLETE_RESTING_HR", "57")
    sg.derive_intervals(c)
    assert json.loads(distilled_of(c, S1))["zoneMin"] == [99, 99, 99, 99, 99]


def test_a_pass_that_dies_midway_does_not_lose_the_rescore(zn, monkeypatch):
    sg, c = zn
    sg.derive_intervals(c)
    monkeypatch.setenv("ATHLETE_RESTING_HR", "57")
    real = arch.upsert_run_intervals
    calls = {"n": 0}

    def flaky(conn, row):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database is locked")
        return real(conn, row)
    monkeypatch.setattr(sg.activity_archive, "upsert_run_intervals", flaky)
    with pytest.raises(RuntimeError):
        sg.derive_intervals(c)
    assert json.loads(arch.get_meta(c, "interval_zone_bounds")) == [100, 119, 139, 159, 179, 199]
    seen = []
    realb = il.build_document
    monkeypatch.setattr(il, "build_document", lambda *a, **k: (seen.append(a[4]), realb(*a, **k))[1])
    sg.derive_intervals(c)
    assert seen and all(b == [128, 142, 156, 171, 185, 199] for b in seen)
    assert json.loads(arch.get_meta(c, "interval_zone_bounds")) == [128, 142, 156, 171, 185, 199]


def test_patch_distilled_replaces_only_the_named_keys(zn):
    sg, c = zn
    before = json.loads(distilled_of(c, S1))
    assert arch.patch_distilled(c, S1, {"intervals": {"shape": "x"}}) is True
    after = json.loads(distilled_of(c, S1))
    assert after["intervals"] == {"shape": "x"}
    assert {k: v for k, v in after.items() if k != "intervals"} == \
        {k: v for k, v in before.items() if k != "intervals"}
    assert arch.patch_distilled(c, 424242, {"intervals": {}}) is False


def test_invalidate_distilled_spares_the_shelf(zn):
    sg, c = zn
    shelf_before = distilled_of(c, S1)
    assert arch.invalidate_distilled(c) == 1
    assert garmin_distilled_versions(c) == {None}
    assert distilled_of(c, S1) == shelf_before


def test_rescore_flag_is_offline_and_rescores(zn, monkeypatch, tmp_path):
    sg, c = zn
    sg.derive_intervals(c)
    before = docs(c)
    c.close()

    def boom():
        raise AssertionError("connect() must not be called")
    monkeypatch.setattr(sg, "connect", boom)
    monkeypatch.setattr(sys, "argv", ["sync_garmin.py", "--rescore-intervals"])
    with pytest.raises(SystemExit) as e:
        sg.main()
    assert e.value.code == 0
    c2 = arch.open_archive(sg.DATA_DIR)
    try:
        assert garmin_distilled_versions(c2) == {None}
        assert set(docs(c2)) == set(before)
    finally:
        c2.close()


def _watch_rows(lows):
    return [{"zoneNumber": z, "secsInZone": 60, "zoneLowBoundary": lo}
            for z, lo in zip(range(1, 6), lows)]


def _week_run(aid=30_000_000_001, **extra):
    a = {"activityId": aid, "startTimeLocal": "2026-10-20 07:00:00",
         "activityType": {"typeKey": "running"}, "distance": 5000.0, "duration": 1800.0}
    a.update(extra)
    return a


def test_zone_card_edges_come_from_the_watch(sg_env):
    sg, _ = sg_env
    client = FakeClient({"get_activity_hr_in_timezones": _watch_rows((99, 128, 142, 156, 171))})
    zones = sg.fetch_hr_zones_this_week(client, [_week_run()], 199)
    assert [(z["lo"], z["hi"]) for z in zones] == [(99, 128), (128, 142), (142, 156), (156, 171), (171, 199)]
    assert [z["min"] for z in zones] == [1] * 5
    assert len(client.calls) == 1


def test_zone_card_edges_cost_at_most_one_extra_call(sg_env):
    sg, _ = sg_env
    seconds = {f"hrTimeInZone_{z}": 120.0 for z in range(1, 6)}
    client = FakeClient({"get_activity_hr_in_timezones": _watch_rows((99, 128, 142, 156, 171))})
    acts = [_week_run(30_000_000_001, **seconds),
            _week_run(30_000_000_002, startTimeLocal="2026-10-21 07:00:00", **seconds)]
    zones = sg.fetch_hr_zones_this_week(client, acts, 199)
    assert zones[1]["lo"] == 128 and [z["min"] for z in zones] == [4] * 5
    assert client.calls == [("get_activity_hr_in_timezones", ("30000000002",))]   # the newest run


def test_zone_card_falls_back_to_athlete_bounds(sg_env, monkeypatch):
    sg, _ = sg_env
    monkeypatch.setenv("ATHLETE_RESTING_HR", "57")
    client = FakeClient({})
    zones = sg.fetch_hr_zones_this_week(client, [_week_run()], 199)
    assert [z["lo"] for z in zones] == sg.athlete_zone_bounds(199)[:5]
    assert zones[4]["hi"] == 199
    assert len(client.calls) == 1                # no second call once the rows lack edges


# ── Task 7: shelf metrics heal from their streams ────────────────────────────
import insight_metrics as im  # noqa: E402

_METRIC_COLS = ("is_treadmill", "best_1k_s", "best_mile_s", "best_5k_s", "best_10k_s",
                "best_half_s", "refhr_time_s", "refhr_dist_m", "refpace_time_s",
                "refpace_cadence_x_time", "refhr_pace_s_per_km", "refpace_cadence_spm")


def metrics_row(c, aid, version):
    cols = ", ".join(_METRIC_COLS)
    return c.execute(f"SELECT {cols} FROM run_metrics WHERE activity_id = ? "
                     "AND metrics_version = ?", (aid, version)).fetchone()


def ingest_computed_metrics(c, aid):
    """What ingest_builder.build_archive computes for a run's metrics row."""
    run = json.loads(c.execute("SELECT summary_json FROM activities WHERE activity_id = ?",
                               (aid,)).fetchone()[0])
    mrow = {"is_treadmill": 1 if run.get("sportType", "").lower() == "treadmill_running" else 0}
    samples = ib_under_test._metric_samples(ib_under_test.synth_streams(run))
    mrow.update(im.best_efforts(samples, declared_dist_m=run.get("distanceM")))
    mrow.update(im.band_aggregates(samples))
    return tuple(mrow.get(k) for k in _METRIC_COLS)


@pytest.fixture
def heal(sg_env):
    sg, data_dir = sg_env
    c = arch.open_archive(data_dir)
    shelf_row(c, S1, "uid-1", dt.datetime(2026, 9, 1, 7, 0), 1800, 5000.0, streams=True)
    shelf_row(c, S2, "uid-2", dt.datetime(2026, 9, 3, 7, 0), 1800, 5000.0, streams=False)
    garmin_row(c, G1, dt.datetime(2026, 10, 1, 7, 0), 1800, 5000.0)
    yield sg, c
    c.close()


def test_metrics_version_bump_heals_shelf_rows(heal, monkeypatch):
    sg, c = heal
    monkeypatch.setattr(im, "METRICS_VERSION", im.METRICS_VERSION + 1)
    im.extract_run_metrics(c)
    row = metrics_row(c, S1, im.METRICS_VERSION)
    assert row is not None and row == ingest_computed_metrics(c, S1)
    assert row[1] is not None                       # positive control: not an empty row
    assert metrics_row(c, S2, im.METRICS_VERSION) is None   # no streams: never listed
    assert sg.verify_archive() == 0


def test_shelf_runs_missing_metrics_lists_only_streamed_shelf_rows(heal):
    _, c = heal
    v = im.METRICS_VERSION
    got = arch.shelf_runs_missing_metrics(c, v)
    assert [r[0] for r in got] == [S1] and len(got[0]) == 4
    assert S1 not in {r[0] for r in arch.runs_missing_metrics(c, v)}
    im.extract_run_metrics(c)
    assert arch.shelf_runs_missing_metrics(c, v) == []


def test_samples_from_streams_parity(heal):
    _, c = heal
    streams = arch.streams_payload(c, S1)
    assert ib_under_test._metric_samples(streams) == im.samples_from_streams(streams)
    assert len(im.samples_from_streams(streams)) == len(streams["t"])


# ── Final review A1: the wellness window starts at the watch ─────────────────
# The shelf predates the Garmin account, so Garmin has no nights for it: asking
# costs calls from a rate-limited IP, and demanding them keeps the gate unarmed.
def _sleep_doc(date):
    return {"dailySleepDTO": {"calendarDate": date, "sleepTimeSeconds": 27000},
            "restingHeartRate": 57}


def _wellness_client():
    return FakeClient({"get_sleep_data": _sleep_doc, "get_hrv_data": lambda d: {}})


def _wellness_dates(client):
    return sorted({args[0] for name, args in client.calls
                   if name in ("get_sleep_data", "get_hrv_data", "get_rhr_day")})


@pytest.fixture
def mixed(sg_env, monkeypatch):
    """Max at cutover: shelf from 2026-06-10, Garmin from 2026-10-19."""
    sg, data_dir = sg_env
    monkeypatch.setattr(sg.time, "sleep", lambda s: None)
    c = arch.open_archive(data_dir)
    shelf_row(c, S1, "uid-1", "2026-06-10T18:47:45", 1800, 5000.0)
    shelf_row(c, S2, "uid-2", "2026-09-03T07:00:00", 1800, 5000.0)
    garmin_row(c, G1, "2026-10-19 19:10:00", 900, 1360.0)
    c.close()
    yield sg, data_dir


def test_earliest_garmin_activity_date_skips_the_shelf(tmp_path):
    c = arch.open_archive(tmp_path)
    try:
        assert arch.earliest_garmin_activity_date(c) is None          # empty archive
        shelf_row(c, S1, "uid-1", "2026-06-10T18:47:45", 1800, 5000.0)
        assert arch.earliest_garmin_activity_date(c) is None          # shelf only
        garmin_row(c, G1, "2026-10-19 19:10:00", 900, 1360.0)
        assert arch.earliest_garmin_activity_date(c) == "2026-10-19"
    finally:
        c.close()


def test_wellness_backfill_asks_garmin_only_from_the_first_garmin_run(mixed):
    sg, data_dir = mixed
    client = _wellness_client()
    sg.run_wellness_backfill(client)
    assert _wellness_dates(client) == ["2026-10-19", "2026-10-20", "2026-10-21"]
    c = arch.open_archive(data_dir)
    try:
        assert arch.get_meta(c, "wellness_backfill_completed_at") is not None
        cov = arch.wellness_coverage(c, "2026-10-21")
        assert (cov["earliest"], cov["expected"], cov["gaps"]) == ("2026-10-19", 3, [])
    finally:
        c.close()
    assert sg.verify_archive() == 0


def test_wellness_backfill_since_the_first_garmin_day_completes(mixed):
    sg, data_dir = mixed
    client = _wellness_client()
    sg.run_wellness_backfill(client, since="2026-10-19")      # the plan's runbook flag
    assert _wellness_dates(client) == ["2026-10-19", "2026-10-20", "2026-10-21"]
    c = arch.open_archive(data_dir)
    try:
        assert arch.get_meta(c, "wellness_backfill_completed_at") is not None
    finally:
        c.close()


def test_the_armed_gate_catches_a_gap_inside_the_garmin_window(mixed):
    sg, data_dir = mixed
    sg.run_wellness_backfill(_wellness_client())
    assert sg.verify_archive() == 0                       # shelf months are not gaps
    c = arch.open_archive(data_dir)
    c.execute("UPDATE daily_wellness SET fetched_at = NULL WHERE date = '2026-10-20'")
    c.commit()
    c.close()
    assert sg.verify_archive() == 1


def test_a_shelf_only_archive_has_no_wellness_window(sg_env, monkeypatch):
    sg, data_dir = sg_env
    c = arch.open_archive(data_dir)
    shelf_row(c, S1, "uid-1", "2026-06-10T18:47:45", 1800, 5000.0)
    cov = arch.wellness_coverage(c, "2026-10-21")
    assert (cov["expected"], cov["gaps"], cov["earliest"]) == (0, [], None)
    arch.set_meta(c, "wellness_backfill_completed_at", "2026-10-21T08:00:00+02:00")
    c.close()
    client = _wellness_client()
    sg.run_wellness_backfill(client)
    assert client.calls == []
    assert sg.verify_archive() == 0


def test_a_felix_shaped_archive_keeps_its_window(sg_env, monkeypatch):
    sg, data_dir = sg_env
    monkeypatch.setattr(sg.time, "sleep", lambda s: None)
    c = arch.open_archive(data_dir)
    garmin_row(c, G1, "2026-10-15 07:00:00", 1800, 5000.0)
    garmin_row(c, G2, "2026-10-18 07:00:00", 1800, 5000.0)
    first = c.execute("SELECT MIN(start_time_local) FROM activities").fetchone()[0][:10]
    assert arch.wellness_coverage(c, "2026-10-21")["earliest"] == first == "2026-10-15"
    c.close()
    client = _wellness_client()
    sg.run_wellness_backfill(client)
    assert _wellness_dates(client) == [f"2026-10-{d}" for d in range(15, 22)]


# ── Final review A2: a shelf cadence must look like running ──────────────────
# Google Fit rows carry sparse speed samples, so steps ÷ moving minutes reads
# 391 or 1466 spm; the monthly forward-fill then paints that over months.
def test_shelf_cadence_band_constant():
    assert shelf.SHELF_CADENCE_SPM == (120, 230)


@pytest.mark.parametrize("spm, kept", [(1466, False), (100, False), (165, True),
                                       (120, True), (230, True), (119, False), (231, False)])
def test_shelf_cadence_outside_the_running_band_is_dropped(t3, spm, kept):
    sg, c, _ = t3
    t, _ = ingest_builder._effort(json.loads(summary_json_of(c, T3_S1)))
    run = _set_steps(c, T3_S1, round(spm * t / 60.0))
    assert ingest_builder._cadence(run) == spm          # the ingest formula reads spm
    acts = shelf.shelf_activities(c)
    entry = by_id(acts, T3_S1)
    cad = next(r for r in sg.fetch_recent_runs(FakeClient({}), acts)
               if r["date"] == "2026-10-20")["cad"]
    if kept:
        assert entry["averageRunningCadenceInStepsPerMinute"] == spm and cad == spm
    else:
        assert "averageRunningCadenceInStepsPerMinute" not in entry and cad is None


# ── Final review A5: ATHLETE_RESTING_HR is parsed once, forgivingly ──────────
PCT_MAX_199 = [100, 119, 139, 159, 179, 199]


@pytest.mark.parametrize("raw, want", [("57", 57), ("57.4", 57), ("56.5", 57), (" 58 ", 58),
                                       ("", None), (None, None)])
def test_athlete_resting_hr_reads_integers_and_decimals(sg_env, monkeypatch, capsys, raw, want):
    sg, _ = sg_env
    if raw is None:
        monkeypatch.delenv("ATHLETE_RESTING_HR", raising=False)
    else:
        monkeypatch.setenv("ATHLETE_RESTING_HR", raw)
    assert sg.athlete_resting_hr() == want
    assert "ATHLETE_RESTING_HR" not in capsys.readouterr().err


@pytest.mark.parametrize("raw", ["RHR", "abc"])
def test_a_garbled_resting_hr_warns_once_and_reads_as_unset(sg_env, monkeypatch, capsys, raw):
    sg, _ = sg_env
    monkeypatch.setenv("ATHLETE_MAX_HR", "199")
    monkeypatch.setenv("ATHLETE_RESTING_HR", raw)
    assert sg.athlete_resting_hr() is None
    assert sg.athlete_zone_bounds() == PCT_MAX_199
    assert sg.athlete_zone_bounds() == PCT_MAX_199
    err = capsys.readouterr().err
    assert err.count("ATHLETE_RESTING_HR") == 1 and repr(raw) in err


def _tiny_detail(n=240, hr=150.0, mps=3.0):
    keys = ["sumDuration", "sumDistance", "directHeartRate", "directSpeed", "directTimestamp"]
    return {"metricDescriptors": [{"key": k, "metricsIndex": i} for i, k in enumerate(keys)],
            "activityDetailMetrics": [{"metrics": [i * 5.0, i * 5.0 * mps, hr + (i % 7),
                                                   mps, 1.7e12 + i * 5000.0]}
                                      for i in range(n + 1)]}


def test_every_zone_reader_survives_a_garbled_resting_hr(zn, monkeypatch):
    sg, c = zn
    monkeypatch.setenv("ATHLETE_RESTING_HR", "RHR")
    sg.derive_intervals(c)                                    # was: ValueError, run skipped
    assert json.loads(arch.get_meta(c, "interval_zone_bounds")) == PCT_MAX_199
    zones = sg.fetch_hr_zones_this_week(FakeClient({}), [_week_run()], 199)
    assert [z["lo"] for z in zones] == PCT_MAX_199[:5]        # was: build_data crashed
    act = {"activityId": G1, "startTimeLocal": "2026-10-01 07:00:00", "duration": 1200.0,
           "distance": 3600.0, "activityType": {"typeKey": "running"}}
    assert sg.distill_run_detail(_tiny_detail(), act) is not None   # was: _distill_pass crashed
