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
