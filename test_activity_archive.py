"""Unit tests for activity_archive.py (temp dir, no Garmin network)."""
import importlib.util
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("activity_archive", REPO / "activity_archive.py")
arch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(arch)


def _tmp() -> Path:
    return Path(tempfile.mkdtemp())


def _act(aid, name="Morning Run", start="2026-07-01 08:00:00", type_key="running"):
    return {
        "activityId": aid,
        "activityName": name,
        "startTimeLocal": start,
        "activityType": {"typeKey": type_key},
        "distance": 5000.0,
        "duration": 1800.0,
        "averageHR": 150.2,
        "maxHR": 172,
        "averageRunningCadenceInStepsPerMinute": 168.0,
        "elevationGain": 42.0,
    }


def test_double_upsert_dedupes():
    conn = arch.open_archive(_tmp())
    rows = [_act(1), _act(2, start="2026-07-02 08:00:00")]
    assert arch.upsert_activities(conn, rows) == 2, "first upsert: both new"
    assert arch.upsert_activities(conn, rows) == 0, "second upsert: nothing new"
    assert conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 2
    conn.close()


def test_fresh_summary_wins_first_seen_preserved():
    conn = arch.open_archive(_tmp())
    arch.upsert_activities(conn, [_act(1, name="Old Name")])
    sentinel = "2000-01-01T00:00:00"
    conn.execute("UPDATE activities SET first_seen_at = ?", (sentinel,))
    conn.commit()

    arch.upsert_activities(conn, [_act(1, name="Renamed on Garmin")])
    name, first_seen, updated = conn.execute(
        "SELECT name, first_seen_at, updated_at FROM activities WHERE activity_id = 1"
    ).fetchone()
    assert name == "Renamed on Garmin", "fresh summary must win"
    assert first_seen == sentinel, "first_seen_at must survive the re-upsert"
    assert updated != sentinel, "updated_at must be bumped"
    conn.close()


def test_rows_without_id_are_skipped():
    conn = arch.open_archive(_tmp())
    assert arch.upsert_activities(conn, [{"activityName": "no id"}, _act(5)]) == 1
    assert conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 1
    conn.close()


def test_detail_write_once():
    conn = arch.open_archive(_tmp())
    arch.upsert_activities(conn, [_act(1)])

    assert arch.write_detail(conn, 1, None) is False, "empty payload refused"
    assert arch.write_detail(conn, 1, {}) is False, "falsy payload refused"

    assert arch.write_detail(conn, 1, {"metricDescriptors": [1, 2]}) is True
    assert arch.write_detail(conn, 1, {"metricDescriptors": [9]}) is False, \
        "detail is write-once — a second payload must not overwrite"
    assert arch.write_detail(conn, 1, None) is False, "failed re-fetch must not erase"

    stored = conn.execute("SELECT detail_json FROM activities WHERE activity_id = 1").fetchone()[0]
    assert "1, 2" in stored, "original detail payload must be intact"
    assert arch.write_detail(conn, 999, {"x": 1}) is False, "unknown activity: no row written"
    conn.close()


def test_missing_detail_ids_order_and_limit():
    conn = arch.open_archive(_tmp())
    arch.upsert_activities(conn, [
        _act(1, start="2026-07-01 08:00:00"),
        _act(2, start="2026-07-03 08:00:00"),
        _act(3, start="2026-07-02 08:00:00"),
    ])
    assert arch.missing_detail_ids(conn) == [2, 3, 1], "newest first"
    assert arch.missing_detail_ids(conn, limit=2) == [2, 3], "cap respected"
    arch.write_detail(conn, 2, {"d": 1})
    assert arch.missing_detail_ids(conn) == [3, 1], "filled detail drops out"
    conn.close()


def test_wellness_same_day_refresh():
    conn = arch.open_archive(_tmp())
    arch.upsert_wellness(conn, "2026-07-05", {"resting_hr": 47, "hrv": 55, "sleep_hours": 7.2},
                         {"score": 41})
    arch.upsert_wellness(conn, "2026-07-05", {"resting_hr": 46, "hrv": 58, "sleep_hours": 7.2},
                         {"score": 44})
    rows = conn.execute("SELECT date, resting_hr, hrv FROM daily_wellness").fetchall()
    assert rows == [("2026-07-05", 46, 58)], "exactly one row per date, later sync wins"
    conn.close()


def test_corrupt_db_quarantined_and_recreated():
    d = _tmp()
    db = arch.archive_path(d)
    db.write_text("this is not a sqlite database at all", encoding="utf-8")

    conn = arch.open_archive(d)  # must not raise
    assert arch.upsert_activities(conn, [_act(1)]) == 1, "fresh archive is usable"
    conn.close()

    quarantined = list(d.glob("activity-archive.db.corrupt-*"))
    assert len(quarantined) == 1, "corrupt file renamed aside, not deleted"
    assert "not a sqlite database" in quarantined[0].read_text(encoding="utf-8")


def test_meta_and_coverage():
    conn = arch.open_archive(_tmp())
    assert arch.get_meta(conn, "schema_version") == "1"
    arch.set_meta(conn, "expected_activity_count", 536)
    assert arch.get_meta(conn, "expected_activity_count") == "536"

    arch.upsert_activities(conn, [
        _act(1, start="2024-05-12 09:00:00"),
        _act(2, start="2026-07-03 08:00:00"),
        _act(3, start="2026-01-01 08:00:00", type_key="strength_training"),
    ])
    arch.write_detail(conn, 2, {"d": 1})
    arch.upsert_wellness(conn, "2026-07-05", {}, {})

    cov = arch.coverage(conn)
    assert cov["total"] == 3
    assert cov["by_year"] == {"2024": 1, "2026": 2}
    assert cov["by_type"]["running"] == 2 and cov["by_type"]["strength_training"] == 1
    assert cov["with_detail"] == 1 and cov["without_detail"] == 2
    assert cov["wellness_rows"] == 1
    assert cov["earliest"].startswith("2024-05-12") and cov["latest"].startswith("2026-07-03")
    conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# sync integration (sync_garmin.archive_step / verify_archive), still no network
# ──────────────────────────────────────────────────────────────────────────────
_sg_spec = importlib.util.spec_from_file_location("sync_garmin", REPO / "sync_garmin.py")
sg = importlib.util.module_from_spec(_sg_spec)
_sg_spec.loader.exec_module(sg)


class _FakeClient:
    def get_activity_details(self, aid, maxchart=2000, maxpoly=0):
        return {"metricDescriptors": [{"key": "sumDistance", "metricsIndex": 0}],
                "activityDetailMetrics": [{"metrics": [1000]}]}


def _patched_dirs(d: Path):
    orig = (sg.DATA_DIR, sg.CACHE_DIR)
    sg.DATA_DIR, sg.CACHE_DIR = d, d / ".garmin_cache"
    return orig


def test_archive_step_banks_everything():
    d = _tmp()
    orig = _patched_dirs(d)
    try:
        acts = [_act(1), _act(2, start="2026-07-02 08:00:00")]
        readiness = {"restingHR": 47, "hrv": 55, "sleepHours": 7.5, "score": 41}
        sg.archive_step(_FakeClient(), acts, readiness)
    finally:
        sg.DATA_DIR, sg.CACHE_DIR = orig

    conn = arch.open_archive(d)
    cov = arch.coverage(conn)
    assert cov["total"] == 2 and cov["with_detail"] == 2, "summaries + detail top-up banked"
    assert cov["wellness_rows"] == 1, "today's wellness row banked"
    assert arch.get_meta(conn, "expected_activity_count") == "2", "expectations ratcheted"
    assert arch.get_meta(conn, "last_append_at"), "append stamped"
    conn.close()


def test_archive_step_failsoft():
    """The exact wrapper main() uses must swallow ANY archive failure — the
    sync's exit code stays 0 even when the archive is unwritable."""
    def boom(*_a, **_k):
        raise RuntimeError("disk full / file locked / volume gone")

    orig = sg.activity_archive.open_archive
    sg.activity_archive.open_archive = boom
    try:
        result = sg.safe(lambda: sg.archive_step(_FakeClient(), [_act(1)], {}), None, "archive step")
        assert result is None, "archive failure must degrade to a warning, never raise"
    finally:
        sg.activity_archive.open_archive = orig


def test_verify_archive_regression_exit_codes():
    d = _tmp()
    orig = _patched_dirs(d)
    try:
        conn = arch.open_archive(d)
        arch.upsert_activities(conn, [_act(1, start="2024-05-12 09:00:00"), _act(2)])
        arch.set_meta(conn, "expected_activity_count", 2)
        arch.set_meta(conn, "expected_earliest", "2024-05-12 09:00:00")
        conn.close()
        assert sg.verify_archive() == 0, "matching expectations → exit 0"

        conn = arch.open_archive(d)
        arch.set_meta(conn, "expected_activity_count", 536)
        conn.close()
        assert sg.verify_archive() == 1, "count below expectation → exit 1"
    finally:
        sg.DATA_DIR, sg.CACHE_DIR = orig


def test_verify_archive_missing_db():
    d = _tmp()
    orig = _patched_dirs(d)
    try:
        assert sg.verify_archive() == 2, "no archive file → distinct exit code"
    finally:
        sg.DATA_DIR, sg.CACHE_DIR = orig


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_"):
            _fn()
            print("ok", _name)
    print("ALL PASS")
