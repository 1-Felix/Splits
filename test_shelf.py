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
