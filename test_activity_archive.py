"""Unit tests for activity_archive.py (temp dir, no Garmin network)."""
import importlib.util
import json
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
    assert arch.get_meta(conn, "schema_version") == str(arch.SCHEMA_VERSION)
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


def test_v1_migration_preserves_data():
    d = _tmp()
    _make_v1_db(d)
    conn = arch.open_archive(d)  # migration happens on open (v1 → current)
    assert arch.get_meta(conn, "schema_version") == str(arch.SCHEMA_VERSION), \
        "version stamped forward"
    assert conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 1, \
        "v1 rows untouched by the migration"
    assert conn.execute("SELECT COUNT(*) FROM run_metrics").fetchone()[0] == 0
    assert arch.race_predictions_empty(conn) is True
    conn.close()

    conn = arch.open_archive(d)  # idempotent re-open at the current version
    assert arch.get_meta(conn, "schema_version") == str(arch.SCHEMA_VERSION)
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
        # empty sleep window: today's readiness row is still banked (fetch_sleep failed)
        sg.wellness_step(_FakeClient(), readiness, [])
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
        assert sg.safe(lambda: sg.wellness_step(_FakeClient(), {}, []), None,
                       "wellness banking") is None
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


# ──────────────────────────────────────────────────────────────────────────────
# schema v3 (coach-loop): migration + snapshot/compliance accessors
# ──────────────────────────────────────────────────────────────────────────────
# The v2 additions as they shipped in stage 2 — frozen so the migration test
# exercises a genuine v2 file.
_V2_ADDITIONS = """
CREATE TABLE run_metrics (
  activity_id INTEGER PRIMARY KEY REFERENCES activities(activity_id),
  metrics_version INTEGER NOT NULL, start_time_local TEXT NOT NULL,
  is_treadmill INTEGER NOT NULL,
  best_1k_s REAL, best_mile_s REAL, best_5k_s REAL, best_10k_s REAL,
  best_half_s REAL, refhr_time_s REAL, refhr_dist_m REAL,
  refpace_time_s REAL, refpace_cadence_x_time REAL, computed_at TEXT NOT NULL
);
CREATE TABLE race_predictions (
  date TEXT PRIMARY KEY, time_5k_s REAL, time_10k_s REAL, half_s REAL,
  marathon_s REAL, raw_json TEXT NOT NULL, source TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
UPDATE archive_meta SET value = '2' WHERE key = 'schema_version';
INSERT INTO run_metrics VALUES (1, 1, '2024-05-12 09:00:00', 0,
  300, 500, 1700, 3700, NULL, 600, 1800, 400, 62000, 'x');
"""


def test_v2_to_v3_migration_preserves_data():
    d = _tmp()
    _make_v1_db(d)
    import sqlite3
    conn = sqlite3.connect(arch.archive_path(d))
    conn.executescript(_V2_ADDITIONS)
    conn.commit()
    conn.close()

    conn = arch.open_archive(d)  # v2 → current on open
    assert arch.get_meta(conn, "schema_version") == str(arch.SCHEMA_VERSION)
    assert conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM run_metrics").fetchone()[0] == 1, \
        "v2 derived rows untouched"
    assert conn.execute("SELECT COUNT(*) FROM plan_snapshots").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM plan_compliance").fetchone()[0] == 0
    conn.close()

    conn = arch.open_archive(d)  # idempotent re-open at the current version
    assert arch.get_meta(conn, "schema_version") == str(arch.SCHEMA_VERSION)
    assert conn.execute("SELECT COUNT(*) FROM run_metrics").fetchone()[0] == 1
    conn.close()


def test_plan_snapshot_dedupe():
    conn = arch.open_archive(_tmp())
    a = arch.bank_plan_snapshot(conn, "export const planData = 1;", {"block": []}, "2026-07-05")
    b = arch.bank_plan_snapshot(conn, "export const planData = 1;", {"block": []}, "2026-07-06")
    assert a == b, "identical text → the existing snapshot id"
    assert conn.execute("SELECT COUNT(*) FROM plan_snapshots").fetchone()[0] == 1
    c = arch.bank_plan_snapshot(conn, "export const planData = 2;", {"block": [1]}, "2026-07-07")
    assert c != a
    assert arch.snapshot_plan(conn, c) == {"block": [1]}
    assert arch.snapshot_plan(conn, 999) is None
    conn.close()


def _crow(date, wk="Wk 1", status="done", version=1, snapshot_id=1, kind="run"):
    return {"date": date, "wk": wk, "snapshot_id": snapshot_id,
            "compliance_version": version, "planned_kind": kind,
            "planned_km": 5, "planned_load": "Easy", "planned_title": "Easy Run",
            "status": status, "reason": None, "actual_km": None,
            "actual_pace_s": None, "actual_hr": None, "activity_id": None}


def test_replace_compliance_week_is_scoped_and_idempotent():
    conn = arch.open_archive(_tmp())
    arch.replace_compliance_week(conn, "2026-06-29", "2026-07-05",
                                 [_crow("2026-07-01"), _crow("2026-07-03")])
    arch.replace_compliance_week(conn, "2026-07-06", "2026-07-12",
                                 [_crow("2026-07-08", wk="Wk 2")])
    # replacing week 1 leaves week 2 untouched and fully swaps week 1's rows
    arch.replace_compliance_week(conn, "2026-06-29", "2026-07-05",
                                 [_crow("2026-07-01", status="missed")])
    rows = arch.compliance_rows(conn)
    assert [r["date"] for r in rows] == ["2026-07-01", "2026-07-08"]
    assert rows[0]["status"] == "missed"
    assert rows[1]["wk"] == "Wk 2"
    # unplanned rows sort after the planned row of the same date
    arch.replace_compliance_week(conn, "2026-07-06", "2026-07-12", [
        {**_crow("2026-07-08", wk="Wk 2"), "planned_kind": None, "status": "unplanned"},
        _crow("2026-07-08", wk="Wk 2"),
    ])
    rows = arch.compliance_rows(conn, since_date="2026-07-06")
    assert rows[0]["planned_kind"] == "run" and rows[1]["planned_kind"] is None
    conn.close()


def test_stale_compliance_weeks_and_coverage():
    conn = arch.open_archive(_tmp())
    arch.bank_plan_snapshot(conn, "raw", {"block": []}, "2026-07-05")
    arch.replace_compliance_week(conn, "2026-06-29", "2026-07-05",
                                 [_crow("2026-07-01", version=1)])
    arch.replace_compliance_week(conn, "2026-07-06", "2026-07-12",
                                 [_crow("2026-07-08", wk="Wk 2", version=2)])
    assert arch.stale_compliance_weeks(conn, 2) == [(1, "Wk 1")]
    cov = arch.compliance_coverage(conn, 2)
    assert cov == {"snapshots": 1, "rows": 2, "weeks_scored": 2, "stale": 1,
                   "latest_scored": "2026-07-08"}
    conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# schema v4 (progress-views): distilled-detail column + accessors + sync pass
# ──────────────────────────────────────────────────────────────────────────────
# The v3 additions as they shipped in stage 4 — frozen so the migration test
# exercises a genuine v3 file.
_V3_ADDITIONS = """
CREATE TABLE plan_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT, sha256 TEXT NOT NULL UNIQUE,
  first_seen_date TEXT NOT NULL, plan_json TEXT NOT NULL
);
CREATE TABLE plan_compliance (
  id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, wk TEXT,
  snapshot_id INTEGER NOT NULL REFERENCES plan_snapshots(id),
  compliance_version INTEGER NOT NULL, planned_kind TEXT, planned_km REAL,
  planned_load TEXT, planned_title TEXT, status TEXT NOT NULL, reason TEXT,
  actual_km REAL, actual_pace_s REAL, actual_hr INTEGER, activity_id INTEGER,
  updated_at TEXT NOT NULL
);
UPDATE archive_meta SET value = '3' WHERE key = 'schema_version';
"""


def test_v3_to_v4_migration_is_additive():
    d = _tmp()
    _make_v1_db(d)
    import sqlite3
    conn = sqlite3.connect(arch.archive_path(d))
    conn.executescript(_V2_ADDITIONS)
    conn.executescript(_V3_ADDITIONS)
    conn.commit()
    conn.close()

    conn = arch.open_archive(d)  # v3 → current on open; the v4 column is what this test guards
    assert arch.get_meta(conn, "schema_version") == str(arch.SCHEMA_VERSION), \
        "version stamped forward"
    aid, detail, distilled = conn.execute(
        "SELECT activity_id, detail_json, detail_distilled_json FROM activities"
    ).fetchone()
    assert aid == 1 and detail is not None and distilled is None, \
        "v3 rows untouched; the new column starts NULL"
    assert conn.execute("SELECT COUNT(*) FROM run_metrics").fetchone()[0] == 1
    conn.close()

    # an "old reader" (SQL naming only pre-v4 columns) works unchanged
    conn = sqlite3.connect(arch.archive_path(d))
    rows = conn.execute(
        "SELECT activity_id, start_time_local, detail_json FROM activities").fetchall()
    assert len(rows) == 1
    conn.close()

    conn = arch.open_archive(d)  # idempotent re-open at the current version
    assert arch.get_meta(conn, "schema_version") == str(arch.SCHEMA_VERSION)
    conn.close()


def test_write_distilled_and_missing_list():
    import json
    conn = arch.open_archive(_tmp())
    arch.upsert_activities(conn, [
        _act(1, start="2026-07-01 08:00:00"),
        _act(2, start="2026-07-02 08:00:00"),
        _act(3, start="2026-07-03 08:00:00", type_key="strength_training"),
        _act(4, start="2026-07-04 08:00:00"),
    ])
    for aid in (1, 2, 3):
        arch.write_detail(conn, aid, {"d": 1})
    assert arch.runs_missing_distilled(conn) == [1, 2], \
        "runs with raw detail only, oldest first; non-runs and detail-less skipped"

    assert arch.write_distilled(conn, 1, None) is False, "empty distill refused"
    assert arch.write_distilled(conn, 999, {"splits": []}) is False, "unknown id: no row"
    assert arch.write_distilled(conn, 1, {"splits": [], "driftBpm": 3}) is True
    assert arch.runs_missing_distilled(conn) == [2], "distilled run drops off the list"
    # distilled is derived and disposable — a recompute replaces, never duplicates
    assert arch.write_distilled(conn, 1, {"splits": [], "driftBpm": 5}) is True
    stored = json.loads(conn.execute(
        "SELECT detail_distilled_json FROM activities WHERE activity_id = 1"
    ).fetchone()[0])
    assert stored["driftBpm"] == 5
    assert arch.summary_payload(conn, 1)["activityId"] == 1
    assert arch.summary_payload(conn, 999) is None
    conn.close()


def test_distill_on_topup_and_recovery_pass():
    """progress-views 2.3 + 2.4 — a topped-up run gains distilled detail in the
    same sync; the recovery pass heals pre-v4 rows from stored payloads with no
    client anywhere near it; raw payloads stay byte-identical."""
    import json
    d = _tmp()
    orig = _patched_dirs(d)
    try:
        sg.archive_step(_FakeClient(), [_act(1), _act(2, start="2026-07-02 08:00:00")])
        conn = arch.open_archive(d)
        assert arch.distilled_coverage(conn) == \
            {"detailed_runs": 2, "distilled": 2, "missing": 0}, \
            "topped-up runs distilled within the same archive step"
        assert arch.get_meta(conn, "expected_distilled_runs") == "2", "ratchet recorded"

        # the stored copy IS the recent-run contract from the same distiller
        stored = json.loads(conn.execute(
            "SELECT detail_distilled_json FROM activities WHERE activity_id = 1"
        ).fetchone()[0])
        fresh = sg.fetch_run_detail(_FakeClient(), _act(1))
        assert stored == fresh, "one distiller, two callers"

        # recovery: blank one row's distilled copy (a pre-v4 archive in
        # miniature) and heal it from the stored raw payload
        raw_before = conn.execute(
            "SELECT detail_json FROM activities WHERE activity_id = 2").fetchone()[0]
        conn.execute(
            "UPDATE activities SET detail_distilled_json = NULL WHERE activity_id = 2")
        conn.commit()
        assert sg._distill_pass(conn) == 1, "recovery pass heals the gap"
        assert sg._distill_pass(conn) == 0, "idempotent — second pass finds nothing"
        raw_after = conn.execute(
            "SELECT detail_json FROM activities WHERE activity_id = 2").fetchone()[0]
        assert raw_after == raw_before, "raw payload untouched by distillation"
        conn.close()
    finally:
        sg.DATA_DIR, sg.CACHE_DIR = orig


def test_verify_archive_distilled_coverage_paths():
    """progress-views 2.5 — verify exits non-zero when distillation falls
    behind raw detail; a fully pre-v4 archive (nothing distilled) still passes."""
    d = _tmp()
    orig = _patched_dirs(d)
    try:
        conn = arch.open_archive(d)
        arch.upsert_activities(conn, [_act(1), _act(2, start="2026-07-02 08:00:00")])
        arch.write_detail(conn, 1, {"d": 1})
        arch.write_detail(conn, 2, {"d": 1})
        conn.close()
        assert sg.verify_archive() == 0, "pre-v4 archive (no distilled rows) passes"

        conn = arch.open_archive(d)
        arch.write_distilled(conn, 1, {"splits": []})
        conn.close()
        assert sg.verify_archive() == 1, "partial distillation → regression"

        conn = arch.open_archive(d)
        arch.write_distilled(conn, 2, {"splits": []})
        conn.close()
        assert sg.verify_archive() == 0, "full distilled coverage passes"

        conn = arch.open_archive(d)
        arch.set_meta(conn, "expected_distilled_runs", 5)
        conn.close()
        assert sg.verify_archive() == 1, "count below the ratchet → regression"
    finally:
        sg.DATA_DIR, sg.CACHE_DIR = orig


# ──────────────────────────────────────────────────────────────────────────────
# schema v6 (run-detail): columnar stream column + accessors + sync pass
# ──────────────────────────────────────────────────────────────────────────────
class _StreamFakeClient(_FakeClient):
    """_FakeClient whose raw detail also carries the stream axes (sumDuration),
    so the stream distiller has something to reshape."""
    def get_activity_details(self, aid, maxchart=2000, maxpoly=0):
        det = _steady_detail()
        det["metricDescriptors"].append(
            {"key": "sumDuration", "metricsIndex": len(det["metricDescriptors"])})
        for i, row in enumerate(det["activityDetailMetrics"]):
            row["metrics"].append(float(i))
        return det


def test_v6_streams_column_additive_and_idempotent():
    d = _tmp()
    conn = arch.open_archive(d)
    arch.upsert_activities(conn, [_act(1)])
    cols = [r[1] for r in conn.execute("PRAGMA table_info(activities)")]
    assert cols.count("detail_streams_json") == 1, "v6 column exists exactly once"
    assert conn.execute("SELECT detail_streams_json FROM activities").fetchone()[0] is None, \
        "the new column starts NULL"
    assert arch.get_meta(conn, "schema_version") == str(arch.SCHEMA_VERSION)
    conn.close()
    conn = arch.open_archive(d)   # idempotent re-open at the current version
    cols = [r[1] for r in conn.execute("PRAGMA table_info(activities)")]
    assert cols.count("detail_streams_json") == 1
    # an "old reader" naming only pre-v6 columns works unchanged
    assert conn.execute("SELECT activity_id, detail_json FROM activities").fetchone()[0] == 1
    conn.close()


def test_write_streams_and_missing_list():
    import json
    conn = arch.open_archive(_tmp())
    arch.upsert_activities(conn, [
        _act(1, start="2026-07-01 08:00:00"),
        _act(2, start="2026-07-02 08:00:00"),
        _act(3, start="2026-07-03 08:00:00", type_key="strength_training"),
        _act(4, start="2026-07-04 08:00:00"),
    ])
    for aid in (1, 2, 3):
        arch.write_detail(conn, aid, {"d": 1})
    assert arch.runs_missing_streams(conn) == [1, 2], \
        "runs with raw detail only, oldest first; non-runs and detail-less skipped"

    assert arch.write_streams(conn, 1, None) is False, "empty streams refused"
    assert arch.write_streams(conn, 999, {"t": [0]}) is False, "unknown id: no row"
    assert arch.write_streams(conn, 1, {"t": [0, 1], "d": [0, 3]}) is True
    assert arch.runs_missing_streams(conn) == [2], "streamed run drops off the list"
    # streams are derived and disposable — a recompute replaces, never duplicates
    assert arch.write_streams(conn, 1, {"t": [0], "d": [9]}) is True
    stored = json.loads(conn.execute(
        "SELECT detail_streams_json FROM activities WHERE activity_id = 1").fetchone()[0])
    assert stored["d"] == [9]
    assert arch.streams_coverage(conn) == {"detailed_runs": 2, "streamed": 1, "missing": 1}
    conn.close()


def test_streams_pass_recovery_and_ratchet():
    """run-detail 3.2/3.3 — topped-up runs gain streams inside the same archive
    step; the recovery pass heals a pre-v6 archive from stored payloads with no
    client anywhere near it; raw payloads stay byte-identical."""
    d = _tmp()
    orig = _patched_dirs(d)
    try:
        sg.archive_step(_StreamFakeClient(), [_act(1), _act(2, start="2026-07-02 08:00:00")])
        conn = arch.open_archive(d)
        assert arch.streams_coverage(conn) == \
            {"detailed_runs": 2, "streamed": 2, "missing": 0}, \
            "topped-up runs gain streams within the same archive step"
        assert arch.get_meta(conn, "expected_streamed_runs") == "2", "ratchet recorded"

        # recovery: blank one row's streams (a pre-v6 archive in miniature)
        # and heal it from the stored raw payload
        raw_before = conn.execute(
            "SELECT detail_json FROM activities WHERE activity_id = 2").fetchone()[0]
        conn.execute("UPDATE activities SET detail_streams_json = NULL WHERE activity_id = 2")
        conn.commit()
        assert sg._streams_pass(conn) == 1, "recovery pass heals the gap"
        assert sg._streams_pass(conn) == 0, "idempotent — second pass finds nothing"
        raw_after = conn.execute(
            "SELECT detail_json FROM activities WHERE activity_id = 2").fetchone()[0]
        assert raw_after == raw_before, "raw payload untouched by the stream pass"
        conn.close()
    finally:
        sg.DATA_DIR, sg.CACHE_DIR = orig


def test_verify_archive_streams_coverage_paths():
    """run-detail 3.4 — verify exits non-zero when streaming falls behind raw
    detail; a fully pre-v6 archive (no streams at all) still passes."""
    d = _tmp()
    orig = _patched_dirs(d)
    try:
        conn = arch.open_archive(d)
        arch.upsert_activities(conn, [_act(1), _act(2, start="2026-07-02 08:00:00")])
        arch.write_detail(conn, 1, {"d": 1})
        arch.write_detail(conn, 2, {"d": 1})
        conn.close()
        assert sg.verify_archive() == 0, "pre-v6 archive (no streams) passes"

        conn = arch.open_archive(d)
        arch.write_streams(conn, 1, {"t": [0], "d": [0]})
        conn.close()
        assert sg.verify_archive() == 1, "partial streaming → regression"

        conn = arch.open_archive(d)
        arch.write_streams(conn, 2, {"t": [0], "d": [0]})
        conn.close()
        assert sg.verify_archive() == 0, "full stream coverage passes"

        conn = arch.open_archive(d)
        arch.set_meta(conn, "expected_streamed_runs", 5)
        conn.close()
        assert sg.verify_archive() == 1, "count below the ratchet → regression"
    finally:
        sg.DATA_DIR, sg.CACHE_DIR = orig


# ──────────────────────────────────────────────────────────────────────────────
# schema v5 (wellness-archive): raw wellness payloads + promoted columns
# ──────────────────────────────────────────────────────────────────────────────
_SLEEP_WITH_DATA = {"dailySleepDTO": {"sleepTimeSeconds": 27300, "deepSleepSeconds": 5280},
                    "restingHeartRate": 58, "bodyBatteryChange": 48}
_SLEEP_HOLLOW = {"dailySleepDTO": {"sleepTimeSeconds": None}}
_HRV = {"hrvSummary": {"lastNightAvg": 59, "weeklyAvg": None, "baseline": None, "status": "NONE"}}

_VALUES_WITH_DATA = {"sleep_seconds": 27300, "deep_seconds": 5280, "resting_hr": 58,
                     "hrv_last_night": 59, "hrv_status": "NONE"}
_VALUES_HOLLOW = {"sleep_seconds": None, "resting_hr": None, "hrv_last_night": None}


def _wellness_row(conn, date):
    cur = conn.execute("SELECT * FROM daily_wellness WHERE date = ?", (date,))
    cols = [c[0] for c in cur.description]
    row = cur.fetchone()
    return dict(zip(cols, row)) if row else None


def test_wellness_v5_migration_is_additive():
    """A v1 file gains the wellness columns; the original columns still read."""
    d = _tmp()
    _make_v1_db(d)
    conn = arch.open_archive(d)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(daily_wellness)")}
    for new in ("sleep_json", "hrv_json", "fetched_at", "sleep_seconds",
                "hrv_balanced_low", "hrv_balanced_upper", "hrv_status"):
        assert new in cols, f"{new} added by the v5 migration"
    # an older reader selecting only the v1 columns keeps working
    conn.execute("SELECT date, resting_hr, hrv, sleep_hours, raw_json, updated_at "
                 "FROM daily_wellness").fetchall()
    conn.close()


def test_wellness_promoted_columns_round_trip():
    d = _tmp()
    conn = arch.open_archive(d)
    arch.upsert_wellness(conn, "2024-05-12", _VALUES_WITH_DATA,
                         sleep_raw=_SLEEP_WITH_DATA, hrv_raw=_HRV, fetched_at="2026-07-10T00:00:00")
    row = _wellness_row(conn, "2024-05-12")
    assert row["sleep_seconds"] == 27300
    assert row["resting_hr"] == 58
    assert row["hrv_last_night"] == 59
    assert row["hrv_status"] == "NONE"
    assert json.loads(row["sleep_json"])["restingHeartRate"] == 58, "raw payload stored verbatim"
    assert json.loads(row["hrv_json"])["hrvSummary"]["status"] == "NONE"
    conn.close()


def test_wellness_raw_payload_upgrades_from_hollow_to_data():
    """Garmin had not finalised the night yet. A later sync fills it in."""
    d = _tmp()
    conn = arch.open_archive(d)
    arch.upsert_wellness(conn, "2026-07-09", _VALUES_HOLLOW,
                         sleep_raw=_SLEEP_HOLLOW, fetched_at="2026-07-09T08:00:00")
    assert _wellness_row(conn, "2026-07-09")["sleep_seconds"] is None

    arch.upsert_wellness(conn, "2026-07-09", _VALUES_WITH_DATA,
                         sleep_raw=_SLEEP_WITH_DATA, fetched_at="2026-07-10T08:00:00")
    row = _wellness_row(conn, "2026-07-09")
    assert row["sleep_seconds"] == 27300, "promoted values refreshed"
    assert json.loads(row["sleep_json"])["dailySleepDTO"]["sleepTimeSeconds"] == 27300, \
        "hollow payload replaced by the substantive one"
    conn.close()


def test_wellness_stored_night_is_never_thinned():
    """Once a night carries device data, no later fetch may overwrite it."""
    d = _tmp()
    conn = arch.open_archive(d)
    arch.upsert_wellness(conn, "2024-05-12", _VALUES_WITH_DATA,
                         sleep_raw=_SLEEP_WITH_DATA, fetched_at="2026-07-10T00:00:00")
    arch.upsert_wellness(conn, "2024-05-12", _VALUES_HOLLOW,
                         sleep_raw=_SLEEP_HOLLOW, fetched_at="2026-07-11T00:00:00")
    stored = json.loads(_wellness_row(conn, "2024-05-12")["sleep_json"])
    assert stored["dailySleepDTO"]["sleepTimeSeconds"] == 27300, "substantive payload survives"
    conn.close()


def test_wellness_fetched_at_distinguishes_unfetched_from_empty():
    """Three states: never asked, asked-and-empty, asked-with-data."""
    d = _tmp()
    conn = arch.open_archive(d)
    assert _wellness_row(conn, "2024-06-01") is None, "never asked → no row at all"

    arch.upsert_wellness(conn, "2024-09-02", _VALUES_HOLLOW,
                         sleep_raw=_SLEEP_HOLLOW, fetched_at="2026-07-10T00:00:00")
    empty = _wellness_row(conn, "2024-09-02")
    assert empty["fetched_at"] == "2026-07-10T00:00:00", "asked"
    assert empty["sleep_seconds"] is None, "and the watch recorded nothing"

    arch.upsert_wellness(conn, "2024-05-12", _VALUES_WITH_DATA,
                         sleep_raw=_SLEEP_WITH_DATA, fetched_at="2026-07-10T00:00:00")
    full = _wellness_row(conn, "2024-05-12")
    assert full["fetched_at"] is not None and full["sleep_seconds"] == 27300
    conn.close()


def test_wellness_readiness_snapshot_survives_a_backfill_upsert():
    """`raw_json` holds the sync's computed readiness, not a Garmin payload
    (design D2). A backfill supplies no readiness and must not erase one."""
    d = _tmp()
    conn = arch.open_archive(d)
    arch.upsert_wellness(conn, "2026-07-05", {"resting_hr": 53}, {"score": 92, "status": "High"})
    arch.upsert_wellness(conn, "2026-07-05", _VALUES_WITH_DATA,
                         sleep_raw=_SLEEP_WITH_DATA, fetched_at="2026-07-10T00:00:00")
    row = _wellness_row(conn, "2026-07-05")
    assert json.loads(row["raw_json"])["score"] == 92, "readiness snapshot preserved"
    assert row["sleep_seconds"] == 27300, "and the backfill's values landed"
    conn.close()


def test_wellness_backfilled_row_needs_no_readiness():
    """raw_json is NOT NULL; a date the sync never scored still inserts."""
    d = _tmp()
    conn = arch.open_archive(d)
    arch.upsert_wellness(conn, "2024-05-12", _VALUES_WITH_DATA,
                         sleep_raw=_SLEEP_WITH_DATA, fetched_at="2026-07-10T00:00:00")
    assert json.loads(_wellness_row(conn, "2024-05-12")["raw_json"]) == {}
    conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# route-basemap: tile-rect math (pure, deterministic — no network here)
# ──────────────────────────────────────────────────────────────────────────────

def _loop_track(lat0=47.720, lat1=47.735, lon0=10.300, lon1=10.320, n=40):
    """A rectangular loop around the Allgäu (~1.7 × 1.5 km) as lat/lon columns."""
    lat, lon = [], []
    for i in range(n):                       # south edge, east edge, north, west
        t = i / (n - 1)
        if t < 0.25:
            lat.append(lat0); lon.append(lon0 + (lon1 - lon0) * t * 4)
        elif t < 0.5:
            lat.append(lat0 + (lat1 - lat0) * (t - 0.25) * 4); lon.append(lon1)
        elif t < 0.75:
            lat.append(lat1); lon.append(lon1 - (lon1 - lon0) * (t - 0.5) * 4)
        else:
            lat.append(lat1 - (lat1 - lat0) * (t - 0.75) * 4); lon.append(lon0)
    return lat, lon


def test_merc_world_px_known_values():
    """The Mercator anchor points every tile server agrees on — these same
    values pin the JS mirror in test_chart_core.mjs."""
    assert arch.merc_world_px(0.0, 0.0, 0) == (128.0, 128.0), "origin: centre of the z0 tile"
    x, y = arch.merc_world_px(0.0, 180.0, 1)
    assert (x, y) == (512.0, 256.0), "date line at z1: right edge, vertical centre"
    _, y_top = arch.merc_world_px(85.0511287798066, 0.0, 0)
    assert abs(y_top) < 1e-6, "top of the Mercator square projects to y=0"


def test_tile_rect_is_deterministic():
    lat, lon = _loop_track()
    assert arch.compute_tile_rect(lat, lon) == arch.compute_tile_rect(lat, lon)


def test_tile_rect_crop_is_padded_squarified_and_covered():
    lat, lon = _loop_track()
    m = arch.compute_tile_rect(lat, lon)
    z = m["z"]
    assert z <= 16
    # the crop is square by construction and spans at most three tiles
    assert m["crop_size"] <= 3 * 256 + 1e-6
    # highest such zoom: one step closer would blow past three tiles (or z hit the cap)
    assert z == 16 or m["crop_size"] * 2 > 3 * 256
    # the crop covers the route's own bbox with ~8% margin on the longer side
    pts = [arch.merc_world_px(la, lo, z) for la, lo in zip(lat, lon)]
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    span = max(max(xs) - min(xs), max(ys) - min(ys))
    assert m["crop_x"] <= min(xs) and m["crop_x"] + m["crop_size"] >= max(xs)
    assert m["crop_y"] <= min(ys) and m["crop_y"] + m["crop_size"] >= max(ys)
    margin = min(min(xs) - m["crop_x"], m["crop_x"] + m["crop_size"] - max(xs),
                 min(ys) - m["crop_y"], m["crop_y"] + m["crop_size"] - max(ys))
    assert margin >= 0.079 * span, f"padding must survive squarify (margin {margin})"
    # the tile rect covers the crop exactly
    assert m["x0"] * 256 <= m["crop_x"] and (m["x1"] + 1) * 256 >= m["crop_x"] + m["crop_size"]
    assert m["y0"] * 256 <= m["crop_y"] and (m["y1"] + 1) * 256 >= m["crop_y"] + m["crop_size"]
    assert 0 <= m["x0"] <= m["x1"] < 2 ** z and 0 <= m["y0"] <= m["y1"] < 2 ** z


def test_tile_rect_thin_route_squarifies():
    """An out-and-back on a straight east-west road still gets a square crop."""
    lon = [10.300 + i * 0.001 for i in range(20)]
    lat = [47.720] * 20
    m = arch.compute_tile_rect(lat, lon)
    z = m["z"]
    pts = [arch.merc_world_px(la, lo, z) for la, lo in zip(lat, lon)]
    xs = [p[0] for p in pts]
    assert m["crop_size"] >= (max(xs) - min(xs)), "square side covers the long axis"
    y_mid = pts[0][1]
    assert m["crop_y"] < y_mid < m["crop_y"] + m["crop_size"], "thin axis centred in the square"


def test_tile_rect_small_route_caps_at_zoom_16():
    lat = [47.7200 + i * 0.0001 for i in range(10)]     # ~100 m
    lon = [10.3000 + i * 0.0001 for i in range(10)]
    m = arch.compute_tile_rect(lat, lon)
    assert m["z"] == 16, "zoom never exceeds the cap"
    assert m["crop_size"] >= 64, "near-stationary tracks keep a usable viewport"


def test_tile_rect_long_route_zooms_out():
    lat = [47.5 + i * 0.005 for i in range(60)]          # ~33 km point-to-point
    lon = [10.0 + i * 0.005 for i in range(60)]
    m = arch.compute_tile_rect(lat, lon)
    assert m["z"] < 16
    assert m["crop_size"] <= 3 * 256 + 1e-6, "a long route zooms out, never widens the rect"


def test_schema_v8_adds_map_tables_additively():
    """v8 creates map_tiles + activity_maps and stamps the version; every
    pre-existing table and its columns survive untouched (design D8)."""
    d = _tmp()
    conn = arch.open_archive(d)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"map_tiles", "activity_maps"} <= tables
    assert {"activities", "daily_wellness", "archive_meta", "run_metrics",
            "race_predictions", "plan_snapshots", "plan_compliance"} <= tables
    act_cols = {r[1] for r in conn.execute("PRAGMA table_info(activities)")}
    assert {"summary_json", "detail_json", "detail_distilled_json",
            "detail_streams_json"} <= act_cols, "v1–v6 activity columns intact"
    map_cols = {r[1] for r in conn.execute("PRAGMA table_info(activity_maps)")}
    assert {"activity_id", "z", "x0", "y0", "x1", "y1",
            "crop_x", "crop_y", "crop_size", "updated_at"} == map_cols
    assert arch.get_meta(conn, "schema_version") == "9"
    # re-opening an already-current archive is a no-op, not an error
    conn.close()
    conn = arch.open_archive(d)
    assert arch.get_meta(conn, "schema_version") == "9"
    conn.close()


def test_schema_v9_adds_block_lens_additively():
    """v9 creates block_lens and stamps the version; every pre-existing
    table survives untouched (add-block-lens design D2)."""
    d = _tmp()
    conn = arch.open_archive(d)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "block_lens" in tables
    cols = {r[1] for r in conn.execute("PRAGMA table_info(block_lens)")}
    assert {"race_date", "race_name", "lens_version", "is_complete",
            "block_json", "updated_at"} == cols
    assert arch.get_meta(conn, "schema_version") == "9"
    conn.close()


def test_tile_rect_ignores_null_gaps_and_refuses_no_gps():
    lat, lon = _loop_track()
    gappy_lat = [None, *lat, None]; gappy_lon = [None, *lon, None]
    gappy_lat[5] = None; gappy_lon[5] = None
    clean = [v for i, v in enumerate(lat) if i != 4], [v for i, v in enumerate(lon) if i != 4]
    assert arch.compute_tile_rect(gappy_lat, gappy_lon) == arch.compute_tile_rect(*clean)
    assert arch.compute_tile_rect([], []) is None
    assert arch.compute_tile_rect([None, None], [None, None]) is None
    assert arch.compute_tile_rect([47.7], [10.3]) is None, "a single fix is not a route"
    assert arch.compute_tile_rect(None, None) is None


# ──────────────────────────────────────────────────────────────────────────────
# route-basemap: the fetch step (mocked fetcher — still no network)
# ──────────────────────────────────────────────────────────────────────────────

def _gps_streams():
    lat, lon = _loop_track()
    return {"t": list(range(len(lat))), "d": list(range(len(lat))), "lat": lat, "lon": lon}


class _FetchLog:
    """A fetcher that records calls and can fail on cue."""
    def __init__(self, fail_at=None):
        self.calls = []
        self.fail_at = fail_at

    def __call__(self, z, x, y):
        self.calls.append((z, x, y))
        if self.fail_at is not None and len(self.calls) >= self.fail_at:
            raise OSError("tile server unreachable")
        return b"\x89PNG-fake-" + f"{z}/{x}/{y}".encode()


def _rect_tiles(rect):
    return {(rect["z"], x, y)
            for x in range(rect["x0"], rect["x1"] + 1)
            for y in range(rect["y0"], rect["y1"] + 1)}


def test_map_step_fetches_only_missing_tiles_and_writes_row():
    conn = arch.open_archive(_tmp())
    arch.upsert_activities(conn, [_act(1)])
    streams = _gps_streams()
    rect = arch.compute_tile_rect(streams["lat"], streams["lon"])
    tiles = sorted(_rect_tiles(rect))
    # pre-seed two tiles, as if an earlier run through the area stored them
    for z, x, y in tiles[:2]:
        conn.execute("INSERT INTO map_tiles (z, x, y, png, fetched_at) VALUES (?, ?, ?, ?, ?)",
                     (z, x, y, b"seeded", "2026-07-01T00:00:00"))
    conn.commit()

    fetch = _FetchLog()
    assert arch.ensure_activity_map(conn, 1, streams, fetch=fetch, _sleep=lambda s: None) == "done"
    assert sorted(fetch.calls) == tiles[2:], "the two seeded tiles are never re-fetched"
    stored = {tuple(r) for r in conn.execute("SELECT z, x, y FROM map_tiles")}
    assert stored == set(tiles), "the rect is complete in the store"
    row = conn.execute(
        "SELECT z, x0, y0, x1, y1, crop_x, crop_y, crop_size FROM activity_maps "
        "WHERE activity_id = 1").fetchone()
    assert row == (rect["z"], rect["x0"], rect["y0"], rect["x1"], rect["y1"],
                   rect["crop_x"], rect["crop_y"], rect["crop_size"])
    # a second call is a cheap no-op — no fetches, no sleeps
    fetch2 = _FetchLog()
    assert arch.ensure_activity_map(conn, 1, streams, fetch=fetch2) == "exists"
    assert fetch2.calls == []
    conn.close()


def test_map_step_paces_its_fetches():
    conn = arch.open_archive(_tmp())
    arch.upsert_activities(conn, [_act(1)])
    sleeps = []
    fetch = _FetchLog()
    assert arch.ensure_activity_map(conn, 1, _gps_streams(), fetch=fetch,
                                    pace_s=1.25, _sleep=sleeps.append) == "done"
    assert len(fetch.calls) >= 2, "fixture must need several tiles"
    assert sleeps == [1.25] * (len(fetch.calls) - 1), \
        "one pause between consecutive fetches, none before the first"
    conn.close()


def test_tile_request_identifies_splits_to_osm():
    req = arch._tile_request(15, 17203, 11342)
    assert req.full_url == "https://tile.openstreetmap.org/15/17203/11342.png"
    ua = req.get_header("User-agent") or ""
    assert "SPLITS" in ua and "@" in ua, "OSM policy: identify the app and a contact"


def test_map_step_failure_keeps_tiles_but_no_row_then_retry_heals():
    conn = arch.open_archive(_tmp())
    arch.upsert_activities(conn, [_act(1)])
    streams = _gps_streams()

    fetch = _FetchLog(fail_at=3)          # two tiles land, the third dies
    assert arch.ensure_activity_map(conn, 1, streams, fetch=fetch, _sleep=lambda s: None) == "failed"
    stored = {tuple(r) for r in conn.execute("SELECT z, x, y FROM map_tiles")}
    assert stored == set(fetch.calls[:2]), "tiles fetched before the failure stay stored"
    assert conn.execute("SELECT 1 FROM activity_maps WHERE activity_id = 1").fetchone() is None, \
        "no partial map row (design D6)"

    retry = _FetchLog()
    assert arch.ensure_activity_map(conn, 1, streams, fetch=retry, _sleep=lambda s: None) == "done"
    assert not (set(retry.calls) & stored), "the retry fetches only the gap"
    assert conn.execute("SELECT 1 FROM activity_maps WHERE activity_id = 1").fetchone() is not None
    conn.close()


def test_map_step_skips_runs_without_gps():
    conn = arch.open_archive(_tmp())
    arch.upsert_activities(conn, [_act(1, type_key="treadmill_running")])
    fetch = _FetchLog()
    treadmill = {"t": [0, 1, 2], "d": [0, 5, 10], "hr": [120, 130, 140]}
    assert arch.ensure_activity_map(conn, 1, treadmill, fetch=fetch) == "skipped"
    assert arch.ensure_activity_map(conn, 1, None, fetch=fetch) == "skipped"
    assert fetch.calls == []
    assert conn.execute("SELECT COUNT(*) FROM activity_maps").fetchone()[0] == 0
    conn.close()


def test_sync_maps_pass_maps_gps_runs_and_ignores_treadmills():
    """The sync hook end-to-end (no network): a GPS run gains a map row, a
    treadmill run never enters the work list, and a second pass is a no-op."""
    conn = arch.open_archive(_tmp())
    arch.upsert_activities(conn, [_act(1), _act(2, type_key="treadmill_running")])
    arch.write_streams(conn, 1, _gps_streams())
    arch.write_streams(conn, 2, {"t": [0, 1], "d": [0, 5], "hr": [120, 121]})

    assert arch.runs_missing_maps(conn) == [1], "only the GPS run is work"
    fetch = _FetchLog()
    orig_fetch = sg.activity_archive.fetch_tile
    orig_sleep = sg.activity_archive.time.sleep
    sg.activity_archive.fetch_tile = fetch
    sg.activity_archive.time.sleep = lambda s: None
    try:
        assert sg._maps_pass(conn) == 1
        assert sg._maps_pass(conn) == 0, "idempotent — nothing left to map"
    finally:
        sg.activity_archive.fetch_tile = orig_fetch
        sg.activity_archive.time.sleep = orig_sleep
    assert conn.execute("SELECT COUNT(*) FROM activity_maps").fetchone()[0] == 1
    assert len(fetch.calls) > 0 and len(set(fetch.calls)) == len(fetch.calls), \
        "real fetches, no tile requested twice"
    conn.close()


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_"):
            _fn()
            print("ok", _name)
    print("ALL PASS")
