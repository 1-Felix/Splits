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
    assert arch.get_meta(conn, "schema_version") == "2"
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
# schema v2 (insight-metrics): migration + derived-table accessors
# ──────────────────────────────────────────────────────────────────────────────
# The v1 schema as it shipped in stage 1 — frozen here so the migration test
# exercises a genuine v1 file, not whatever SCHEMA_SQL currently says.
_V1_SCHEMA = """
CREATE TABLE activities (
  activity_id       INTEGER PRIMARY KEY,
  start_time_local  TEXT NOT NULL,
  type_key          TEXT,
  name              TEXT,
  distance_m        REAL,
  duration_s        REAL,
  avg_hr            INTEGER,
  max_hr            INTEGER,
  avg_cadence       REAL,
  elevation_gain_m  REAL,
  summary_json      TEXT NOT NULL,
  detail_json       TEXT,
  detail_fetched_at TEXT,
  first_seen_at     TEXT NOT NULL,
  updated_at        TEXT NOT NULL
);
CREATE INDEX idx_activities_start ON activities(start_time_local);
CREATE TABLE daily_wellness (
  date TEXT PRIMARY KEY, resting_hr INTEGER, hrv INTEGER, sleep_hours REAL,
  raw_json TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE archive_meta (key TEXT PRIMARY KEY, value TEXT);
INSERT INTO archive_meta VALUES ('schema_version', '1');
"""


def _make_v1_db(d):
    import sqlite3
    conn = sqlite3.connect(arch.archive_path(d))
    conn.executescript(_V1_SCHEMA)
    conn.execute(
        "INSERT INTO activities (activity_id, start_time_local, type_key, summary_json,"
        " detail_json, first_seen_at, updated_at) VALUES (1, '2024-05-12 09:00:00',"
        " 'running', '{}', '{\"metricDescriptors\": []}', 'x', 'x')")
    conn.commit()
    conn.close()


def test_v1_to_v2_migration_preserves_data():
    d = _tmp()
    _make_v1_db(d)
    conn = arch.open_archive(d)  # migration happens on open
    assert arch.get_meta(conn, "schema_version") == "2", "version stamped forward"
    assert conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 1, \
        "v1 rows untouched by the migration"
    assert conn.execute("SELECT COUNT(*) FROM run_metrics").fetchone()[0] == 0
    assert arch.race_predictions_empty(conn) is True
    conn.close()

    conn = arch.open_archive(d)  # idempotent re-open at v2
    assert arch.get_meta(conn, "schema_version") == "2"
    assert conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 1
    conn.close()


def _metrics_row(aid, version, start="2026-07-01 08:00:00", **overrides):
    row = {
        "activity_id": aid, "metrics_version": version,
        "start_time_local": start, "is_treadmill": 0,
        "best_1k_s": 290.0, "best_mile_s": 480.0, "best_5k_s": 1620.0,
        "best_10k_s": None, "best_half_s": None,
        "refhr_time_s": 1200.0, "refhr_dist_m": 3400.0,
        "refpace_time_s": 800.0, "refpace_cadence_x_time": 132000.0,
    }
    row.update(overrides)
    return row


def test_run_metrics_upsert_replaces_stale_version():
    conn = arch.open_archive(_tmp())
    arch.upsert_activities(conn, [_act(1)])
    arch.upsert_run_metrics(conn, _metrics_row(1, version=1))
    arch.upsert_run_metrics(conn, _metrics_row(1, version=2, best_1k_s=280.0))
    rows = conn.execute(
        "SELECT metrics_version, best_1k_s FROM run_metrics WHERE activity_id = 1"
    ).fetchall()
    assert rows == [(2, 280.0)], "recompute replaces the stale-version row, never duplicates"
    conn.close()


def test_runs_missing_metrics_detail_and_version():
    conn = arch.open_archive(_tmp())
    arch.upsert_activities(conn, [
        _act(1, start="2026-07-01 08:00:00"),                          # detail + current row
        _act(2, start="2026-07-02 08:00:00"),                          # detail, stale row
        _act(3, start="2026-07-03 08:00:00"),                          # no detail yet
        _act(4, start="2026-07-04 08:00:00", type_key="strength_training"),  # not a run
        _act(5, start="2026-07-05 08:00:00", type_key="treadmill_running"),  # detail, no row
    ])
    for aid in (1, 2, 4, 5):
        arch.write_detail(conn, aid, {"d": 1})
    arch.upsert_run_metrics(conn, _metrics_row(1, version=2))
    arch.upsert_run_metrics(conn, _metrics_row(2, version=1))  # stale

    missing = arch.runs_missing_metrics(conn, version=2)
    assert [(r[0], r[2]) for r in missing] == \
        [(2, "running"), (5, "treadmill_running")], \
        "stale-version + never-computed runs, ordered by start; non-runs and detail-less skipped"
    conn.close()


def test_race_prediction_same_day_refresh():
    conn = arch.open_archive(_tmp())
    arch.upsert_race_prediction(conn, "2026-07-05",
                                {"time_5k_s": 1500.0, "half_s": 7255.0},
                                {"time5K": 1500.0}, "backfill")
    arch.upsert_race_prediction(conn, "2026-07-05",
                                {"time_5k_s": 1495.0, "half_s": 7240.0},
                                {"time5K": 1495.0}, "sync")
    rows = conn.execute(
        "SELECT date, time_5k_s, half_s, source FROM race_predictions").fetchall()
    assert rows == [("2026-07-05", 1495.0, 7240.0, "sync")], \
        "one row per date, later upsert wins"
    assert arch.race_predictions_empty(conn) is False
    conn.close()


def test_detail_payload_roundtrip():
    conn = arch.open_archive(_tmp())
    arch.upsert_activities(conn, [_act(1), _act(2)])
    arch.write_detail(conn, 1, {"metricDescriptors": [{"key": "sumDistance"}]})
    assert arch.detail_payload(conn, 1) == {"metricDescriptors": [{"key": "sumDistance"}]}
    assert arch.detail_payload(conn, 2) is None, "no detail yet → None"
    assert arch.detail_payload(conn, 999) is None, "unknown id → None"
    conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# sync integration (sync_garmin.archive_step / verify_archive), still no network
# ──────────────────────────────────────────────────────────────────────────────
_sg_spec = importlib.util.spec_from_file_location("sync_garmin", REPO / "sync_garmin.py")
sg = importlib.util.module_from_spec(_sg_spec)
_sg_spec.loader.exec_module(sg)


def _steady_detail(seconds=1500, speed=2.2, hr=135, cad=170):
    """A realistic raw detail payload: 1 Hz samples at constant speed — enough
    for the metrics engine to extract best efforts and band aggregates."""
    keys = ("directTimestamp", "sumDistance", "directHeartRate",
            "directRunCadence", "directGradeAdjustedSpeed")
    rows = [{"metrics": [1_700_000_000_000 + i * 1000, speed * i, hr, cad, speed]}
            for i in range(seconds + 1)]
    return {
        "metricDescriptors": [{"key": k, "metricsIndex": i} for i, k in enumerate(keys)],
        "activityDetailMetrics": rows,
    }


class _FakeClient:
    def get_activity_details(self, aid, maxchart=2000, maxpoly=0):
        return _steady_detail()

    def get_race_predictions(self, startdate=None, enddate=None, _type=None):
        return [{"calendarDate": startdate, "time5K": 1500.0,
                 "timeHalfMarathon": 7300.0}]


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
        sg.archive_step(_FakeClient(), acts)
        sg.wellness_step(readiness)
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
        result = sg.safe(lambda: sg.archive_step(_FakeClient(), [_act(1)]), None, "archive step")
        assert result is None, "archive failure must degrade to a warning, never raise"
    finally:
        sg.activity_archive.open_archive = orig


def test_metrics_step_extracts_banks_and_assembles():
    """The full D8 chain against a seeded archive: archive step → metrics step
    (extraction + backfill + banking) → fetch_insights yields the block."""
    d = _tmp()
    orig = _patched_dirs(d)
    try:
        acts = [_act(1, start="2026-06-14 08:00:00"),
                _act(2, start="2026-07-02 08:00:00")]
        sg.archive_step(_FakeClient(), acts)
        pred_doc = {"calendarDate": sg.TODAY.isoformat(), "time5K": 1500.0,
                    "time10K": 3200.0, "timeHalfMarathon": 7255.0}
        sg.metrics_step(_FakeClient(), pred_doc)

        conn = arch.open_archive(d)
        mcov = arch.metrics_coverage(conn, sg.insight_metrics.METRICS_VERSION)
        assert mcov["detailed_runs"] == 2 and mcov["at_version"] == 2, \
            "every detailed run extracted at the current version"
        assert mcov["stale"] == 0
        assert mcov["prediction_rows"] >= 2, "backfill + today's banked row"
        sources = {r[0] for r in conn.execute(
            "SELECT DISTINCT source FROM race_predictions")}
        assert sources == {"backfill", "sync"}, \
            "empty table triggered the history backfill, then today was banked"
        conn.close()

        insights = sg.fetch_insights()
        assert insights is not None and insights["metricsVersion"] >= 1
        assert insights["efficiency"]["monthly"][0]["month"] == "2026-06"
        sg.metrics_step(_FakeClient(), pred_doc)   # idempotent second sync
        conn = arch.open_archive(d)
        assert arch.runs_missing_metrics(conn, sg.insight_metrics.METRICS_VERSION) == [], \
            "second sync finds nothing to extract"
        conn.close()
    finally:
        sg.DATA_DIR, sg.CACHE_DIR = orig


def test_metrics_failsoft_and_insights_omitted():
    """6.4 fail-soft proof: with the archive db unreachable, every new step
    degrades to a warning through the exact safe() wrappers main() uses, and
    fetch_insights yields None so the `insights` key is simply absent."""
    def boom(*_a, **_k):
        raise RuntimeError("db locked / volume gone")

    orig = sg.activity_archive.open_archive
    sg.activity_archive.open_archive = boom
    try:
        assert sg.safe(lambda: sg.metrics_step(_FakeClient(), {}), None, "metrics step") is None
        assert sg.safe(lambda: sg.wellness_step({}), None, "wellness banking") is None
        assert sg.fetch_insights() is None, "failed assembly → no insights, never a partial"
    finally:
        sg.activity_archive.open_archive = orig


def test_fetch_insights_empty_archive_returns_none():
    d = _tmp()
    orig = _patched_dirs(d)
    try:
        arch.open_archive(d).close()   # valid but empty archive
        assert sg.fetch_insights() is None, \
            "no run_metrics yet → block omitted, dashboard keeps working"
    finally:
        sg.DATA_DIR, sg.CACHE_DIR = orig


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


def test_verify_archive_metrics_coverage_paths():
    """8.2 — verify exits non-zero, naming the reason, when metrics coverage
    regresses; a pre-engine archive (no run_metrics at all) still passes."""
    d = _tmp()
    orig = _patched_dirs(d)
    version = sg.insight_metrics.METRICS_VERSION
    try:
        conn = arch.open_archive(d)
        arch.upsert_activities(conn, [_act(1), _act(2, start="2026-07-02 08:00:00")])
        arch.write_detail(conn, 1, {"d": 1})
        arch.write_detail(conn, 2, {"d": 1})
        conn.close()
        assert sg.verify_archive() == 0, "pre-engine archive (metrics never ran) passes"

        conn = arch.open_archive(d)
        arch.upsert_run_metrics(conn, _metrics_row(1, version=version))
        conn.close()
        assert sg.verify_archive() == 1, "partial extraction after a sync → regression"

        conn = arch.open_archive(d)
        arch.upsert_run_metrics(conn, _metrics_row(2, version=version,
                                                   start="2026-07-02 08:00:00"))
        conn.close()
        assert sg.verify_archive() == 0, "full coverage at the current version passes"

        conn = arch.open_archive(d)
        arch.upsert_run_metrics(conn, _metrics_row(2, version=version - 1,
                                                   start="2026-07-02 08:00:00"))
        conn.close()
        assert sg.verify_archive() == 1, "stale-version leftovers → regression"
    finally:
        sg.DATA_DIR, sg.CACHE_DIR = orig


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_"):
            _fn()
            print("ok", _name)
    print("ALL PASS")
