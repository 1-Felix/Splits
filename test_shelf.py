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
