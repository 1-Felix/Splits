"""Unit tests for wellness extraction (pure, no Garmin network).

Every expectation below is a real value read out of `fixtures/wellness/`, which
was captured from the live account on 2026-07-10. The three fixtures exist
because the sleep payload's shape drifted across the account's lifetime and a
backfill has to survive every era it meets — see
openspec/changes/wellness-archive/design.md (D6).
"""
import importlib.util
import json
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent
FIX = REPO / "fixtures" / "wellness"

_arch_spec = importlib.util.spec_from_file_location("activity_archive", REPO / "activity_archive.py")
arch = importlib.util.module_from_spec(_arch_spec)
_arch_spec.loader.exec_module(arch)

_sg_spec = importlib.util.spec_from_file_location("sync_garmin", REPO / "sync_garmin.py")
sg = importlib.util.module_from_spec(_sg_spec)
_sg_spec.loader.exec_module(sg)


def _fx(tag, kind):
    return json.loads((FIX / f"{tag}-{kind}.json").read_text(encoding="utf-8"))


def test_promote_wellness_mature_era():
    """2026 payload: 18 top-level keys, HRV baseline established."""
    got = sg.promote_wellness(_fx("era2026-mature", "sleep"), _fx("era2026-mature", "hrv"))
    assert got["sleep_seconds"] == 26400
    assert got["deep_seconds"] == 6240
    assert got["rem_seconds"] == 1500
    assert got["light_seconds"] == 18660
    assert got["awake_seconds"] == 1200
    assert got["sleep_score"] == 70
    assert got["respiration_avg"] == 14.0
    assert got["body_battery_change"] == 74
    assert got["resting_hr"] == 53
    assert got["hrv_last_night"] == 56
    assert got["hrv_weekly_avg"] == 59
    assert got["hrv_balanced_low"] == 53
    assert got["hrv_balanced_upper"] == 63
    assert got["hrv_status"] == "BALANCED"


def test_promote_wellness_2024_era_finds_the_same_fields():
    """2024 payload: only 7 top-level keys. Nothing that exists may be nulled."""
    got = sg.promote_wellness(_fx("era2024-onboarding", "sleep"), _fx("era2024-onboarding", "hrv"))
    assert got["sleep_seconds"] == 27300
    assert got["deep_seconds"] == 5280
    assert got["rem_seconds"] == 5760
    assert got["light_seconds"] == 16260
    assert got["awake_seconds"] == 660
    assert got["sleep_score"] == 94
    assert got["respiration_avg"] == 14.0
    assert got["body_battery_change"] == 48
    assert got["resting_hr"] == 58
    assert got["hrv_last_night"] == 59


def test_promote_wellness_onboarding_baseline_is_null_not_zero():
    """Garmin had not established a baseline yet: null is the truth, 0 is a lie."""
    got = sg.promote_wellness(_fx("era2024-onboarding", "sleep"), _fx("era2024-onboarding", "hrv"))
    assert got["hrv_weekly_avg"] is None
    assert got["hrv_balanced_low"] is None
    assert got["hrv_balanced_upper"] is None
    assert got["hrv_status"] == "NONE"


def test_promote_wellness_unworn_night_nulls_sleep_but_keeps_rolling_hrv():
    """The watch was off the wrist. The payload is present but hollow, and HRV's
    rolling values survive — promoted columns are independently nullable."""
    got = sg.promote_wellness(_fx("empty-night", "sleep"), _fx("empty-night", "hrv"))
    assert got["sleep_seconds"] is None
    assert got["deep_seconds"] is None
    assert got["sleep_score"] is None
    assert got["respiration_avg"] is None
    assert got["body_battery_change"] is None
    assert got["resting_hr"] is None       # caller must fall back to get_rhr_day
    assert got["hrv_last_night"] is None
    assert got["hrv_weekly_avg"] == 50     # rolling values outlive the missing night
    assert got["hrv_balanced_low"] == 48
    assert got["hrv_balanced_upper"] == 60
    assert got["hrv_status"] == "BALANCED"


def test_promote_wellness_tolerates_missing_payloads():
    for sleep, hrv in ((None, None), ({}, {}), (None, {}), ({}, None)):
        got = sg.promote_wellness(sleep, hrv)
        assert set(got) == set(sg.WELLNESS_COLUMNS), "shape is stable regardless of input"
        assert all(v is None for v in got.values()), "absent means null, never zero"


def test_promote_wellness_is_pure():
    """No clock, no network, no mutation of its inputs."""
    sleep, hrv = _fx("era2026-mature", "sleep"), _fx("era2026-mature", "hrv")
    before = json.dumps(sleep, sort_keys=True), json.dumps(hrv, sort_keys=True)
    a = sg.promote_wellness(sleep, hrv)
    b = sg.promote_wellness(sleep, hrv)
    assert a == b
    assert before == (json.dumps(sleep, sort_keys=True), json.dumps(hrv, sort_keys=True))


def test_promote_wellness_populates_the_legacy_columns():
    """`hrv` and `sleep_hours` predate this change and stay populated."""
    got = sg.promote_wellness(_fx("era2026-mature", "sleep"), _fx("era2026-mature", "hrv"))
    assert got["hrv"] == 56, "legacy hrv mirrors hrv_last_night"
    assert got["sleep_hours"] == 7.3, "26400 s → 7.3 h"


def test_promoted_keys_are_exactly_the_archive_columns():
    """One source of truth: the projection and the table cannot drift apart."""
    assert set(sg.promote_wellness(None, None)) == set(arch.WELLNESS_PROMOTED_COLUMNS)


# ──────────────────────────────────────────────────────────────────────────────
# fetch path + backfill (fake client, still no network)
# ──────────────────────────────────────────────────────────────────────────────
class _FakeClient:
    """Serves fixture payloads by date. `broken` dates raise, as Garmin does."""

    def __init__(self, sleep=None, hrv=None, rhr=None, broken=()):
        self.sleep, self.hrv, self.rhr = sleep or {}, hrv or {}, rhr or {}
        self.broken = set(broken)
        self.calls = []

    def _serve(self, table, date, label):
        self.calls.append((label, date))
        if date in self.broken:
            raise RuntimeError(f"garmin exploded on {label} {date}")
        # Garmin answers every date with a document, however empty. Only a raised
        # exception means "we failed to ask" — that distinction is the whole point
        # of `fetched_at`, so the fake must not blur it by returning None.
        return table.get(date, {})

    def get_sleep_data(self, date):
        return self._serve(self.sleep, date, "sleep")

    def get_hrv_data(self, date):
        return self._serve(self.hrv, date, "hrv")

    def get_rhr_day(self, date):
        return self._serve(self.rhr, date, "rhr")


_RHR_DOC = {"allMetrics": {"metricsMap": {"WELLNESS_RESTING_HEART_RATE": [
    {"value": 56.0, "calendarDate": "2024-09-02"}]}}}


def _client_with_fixtures():
    return _FakeClient(
        sleep={"2024-05-12": _fx("era2024-onboarding", "sleep"),
               "2024-09-02": _fx("empty-night", "sleep"),
               "2026-07-05": _fx("era2026-mature", "sleep")},
        hrv={"2024-05-12": _fx("era2024-onboarding", "hrv"),
             "2024-09-02": _fx("empty-night", "hrv"),
             "2026-07-05": _fx("era2026-mature", "hrv")},
        rhr={"2024-09-02": _RHR_DOC},
    )


def _tmp_conn():
    return arch.open_archive(Path(tempfile.mkdtemp()))


def test_fetch_wellness_day_reads_resting_hr_from_the_sleep_payload():
    """Two calls on a normal night — no resting-HR endpoint needed."""
    c = _client_with_fixtures()
    sleep, hrv, values, complete = sg.fetch_wellness_day(c, "2026-07-05")
    assert complete is True
    assert values["resting_hr"] == 53
    assert [label for label, _ in c.calls] == ["sleep", "hrv"], "no third call"


def test_fetch_wellness_day_falls_back_to_the_rhr_endpoint_on_a_null_value():
    """The unworn night: the sleep payload EXISTS but restingHeartRate is null.
    A payload-presence check would have silently lost resting HR here."""
    c = _client_with_fixtures()
    sleep, hrv, values, complete = sg.fetch_wellness_day(c, "2024-09-02")
    assert complete is True
    assert values["resting_hr"] == 56, "recovered from get_rhr_day"
    assert values["sleep_seconds"] is None, "and the night still has no sleep"
    assert [label for label, _ in c.calls] == ["sleep", "hrv", "rhr"]


def test_fetch_wellness_day_reports_incomplete_when_a_call_fails():
    c = _FakeClient(sleep={}, hrv={}, broken={"2024-06-01"})
    _, _, _, complete = sg.fetch_wellness_day(c, "2024-06-01")
    assert complete is False


def test_backfill_walks_newest_first_and_banks_every_date():
    conn = _tmp_conn()
    c = _client_with_fixtures()
    stats = sg.backfill_wellness(conn, c, earliest="2024-05-12", today="2024-05-14", delay=0)
    assert stats["fetched"] == 3
    dates = [r[0] for r in conn.execute("SELECT date FROM daily_wellness ORDER BY date")]
    assert dates == ["2024-05-12", "2024-05-13", "2024-05-14"]
    assert [d for label, d in c.calls if label == "sleep"][0] == "2024-05-14", "newest first"
    conn.close()


def test_backfill_is_idempotent():
    conn = _tmp_conn()
    first = sg.backfill_wellness(conn, _client_with_fixtures(), earliest="2024-05-12",
                                 today="2024-05-13", delay=0)
    c2 = _client_with_fixtures()
    second = sg.backfill_wellness(conn, c2, earliest="2024-05-12", today="2024-05-13", delay=0)
    assert first["fetched"] == 2
    assert second["fetched"] == 0 and second["skipped"] == 2
    assert c2.calls == [], "a complete backfill makes no requests at all"
    conn.close()


def test_backfill_failed_date_is_retried_not_marked_fetched():
    conn = _tmp_conn()
    broken = _FakeClient(sleep={}, hrv={}, broken={"2024-05-13"})
    stats = sg.backfill_wellness(conn, broken, earliest="2024-05-12", today="2024-05-13", delay=0)
    assert stats["failed"] == 1
    row = conn.execute("SELECT fetched_at FROM daily_wellness WHERE date = '2024-05-13'").fetchone()
    assert row is None or row[0] is None, "a failed date is never marked fetched"

    healed = sg.backfill_wellness(conn, _FakeClient(sleep={}, hrv={}), earliest="2024-05-12",
                                  today="2024-05-13", delay=0)
    assert healed["fetched"] == 1, "the next run retries it"
    conn.close()


def test_backfill_resumes_from_where_it_stopped():
    conn = _tmp_conn()
    sg.backfill_wellness(conn, _client_with_fixtures(), earliest="2024-05-13",
                         today="2024-05-14", delay=0)
    c = _client_with_fixtures()
    stats = sg.backfill_wellness(conn, c, earliest="2024-05-12", today="2024-05-14", delay=0)
    assert stats["fetched"] == 1 and stats["skipped"] == 2
    assert {d for _, d in c.calls} == {"2024-05-12"}, "only the missing date is fetched"
    conn.close()


def test_backfill_since_bounds_the_walk():
    conn = _tmp_conn()
    stats = sg.backfill_wellness(conn, _client_with_fixtures(), earliest="2024-05-12",
                                 today="2024-05-16", since="2024-05-15", delay=0)
    assert stats["fetched"] == 2
    dates = [r[0] for r in conn.execute("SELECT date FROM daily_wellness ORDER BY date")]
    assert dates == ["2024-05-15", "2024-05-16"]
    conn.close()


def test_backfill_completion_marker_only_on_full_coverage():
    conn = _tmp_conn()
    broken = _FakeClient(sleep={}, hrv={}, broken={"2024-05-13"})
    sg.backfill_wellness(conn, broken, earliest="2024-05-12", today="2024-05-13", delay=0)
    assert arch.get_meta(conn, "wellness_backfill_completed_at") is None, \
        "a failed date leaves the backfill incomplete"

    sg.backfill_wellness(conn, _FakeClient(sleep={}, hrv={}), earliest="2024-05-12",
                         today="2024-05-13", delay=0)
    assert arch.get_meta(conn, "wellness_backfill_completed_at") is not None
    assert arch.get_meta(conn, "backfill_completed_at") is None, \
        "distinct from the activity backfill's marker"
    conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# steady state: the nightly sync banks the whole sleep window
# ──────────────────────────────────────────────────────────────────────────────
import datetime as _dt


def _patched(d, today):
    orig = (sg.DATA_DIR, sg.CACHE_DIR, sg.TODAY)
    sg.DATA_DIR, sg.CACHE_DIR, sg.TODAY = d, d / ".garmin_cache", _dt.date.fromisoformat(today)
    return orig


def _restore(orig):
    sg.DATA_DIR, sg.CACHE_DIR, sg.TODAY = orig


_READINESS = {"restingHR": 47, "hrv": 55, "sleepHours": 7.5, "score": 41, "status": "High"}


def test_wellness_step_banks_every_night_in_the_window():
    """fetch_sleep already pulls these payloads; the sync used to discard them."""
    d = Path(tempfile.mkdtemp())
    orig = _patched(d, "2026-07-05")
    try:
        window = [("2026-07-03", _fx("era2026-mature", "sleep")),
                  ("2026-07-04", _fx("empty-night", "sleep")),
                  ("2026-07-05", _fx("era2026-mature", "sleep"))]
        sg.wellness_step(_client_with_fixtures(), _READINESS, window)
    finally:
        _restore(orig)
    conn = arch.open_archive(d)
    rows = {r[0]: r[1] for r in conn.execute("SELECT date, sleep_seconds FROM daily_wellness")}
    assert set(rows) == {"2026-07-03", "2026-07-04", "2026-07-05"}, "all three nights banked"
    assert rows["2026-07-04"] is None, "the unworn night is stored as empty, not skipped"
    conn.close()


def test_wellness_step_tops_up_hrv_only_for_nights_missing_it():
    """Steady state must not grow the nightly call count (task 5.4)."""
    d = Path(tempfile.mkdtemp())
    orig = _patched(d, "2026-07-05")
    try:
        window = [("2026-07-05", _fx("era2026-mature", "sleep"))]
        first = _client_with_fixtures()
        sg.wellness_step(first, _READINESS, window)
        assert ("hrv", "2026-07-05") in first.calls, "first sync fetches HRV"

        second = _client_with_fixtures()
        sg.wellness_step(second, _READINESS, window)
        assert [c for c in second.calls if c[0] == "hrv"] == [], \
            "a night whose HRV is already stored is never re-fetched"
    finally:
        _restore(orig)


def test_wellness_step_banks_today_even_when_the_sleep_window_is_empty():
    """fetch_sleep failed outright — today's readiness snapshot still lands."""
    d = Path(tempfile.mkdtemp())
    orig = _patched(d, "2026-07-05")
    try:
        sg.wellness_step(_client_with_fixtures(), _READINESS, [])
    finally:
        _restore(orig)
    conn = arch.open_archive(d)
    row = conn.execute("SELECT resting_hr, raw_json, fetched_at FROM daily_wellness "
                       "WHERE date = '2026-07-05'").fetchone()
    assert row is not None, "today's row is banked"
    assert row[0] == 47 and json.loads(row[1])["score"] == 41, "readiness snapshot kept"
    assert row[2] is None, "we never fetched it, so it is not marked fetched"
    conn.close()


def test_wellness_step_stamps_todays_readiness_alongside_the_raw_payload():
    d = Path(tempfile.mkdtemp())
    orig = _patched(d, "2026-07-05")
    try:
        sg.wellness_step(_client_with_fixtures(), _READINESS,
                         [("2026-07-05", _fx("era2026-mature", "sleep"))])
    finally:
        _restore(orig)
    conn = arch.open_archive(d)
    raw_json, sleep_json, fetched = conn.execute(
        "SELECT raw_json, sleep_json, fetched_at FROM daily_wellness "
        "WHERE date = '2026-07-05'").fetchone()
    assert json.loads(raw_json)["score"] == 41, "readiness snapshot"
    assert json.loads(sleep_json)["dailySleepDTO"]["sleepTimeSeconds"] == 26400, "raw payload"
    assert fetched is not None, "and the date is marked as asked"
    conn.close()


def test_fetch_sleep_surfaces_the_raw_payloads_it_already_fetched():
    d = Path(tempfile.mkdtemp())
    orig = _patched(d, "2026-07-05")
    try:
        raws = []
        out = sg.fetch_sleep(_client_with_fixtures(), nights=3, raw_out=raws)
        assert len(out) == 3, "the history.sleep contract is unchanged"
        assert [date for date, _ in raws] == ["2026-07-03", "2026-07-04", "2026-07-05"]
        assert raws[-1][1]["dailySleepDTO"]["sleepTimeSeconds"] == 26400
    finally:
        _restore(orig)


# ──────────────────────────────────────────────────────────────────────────────
# coverage verification
# ──────────────────────────────────────────────────────────────────────────────
def _seed_activity(conn, date="2024-05-12 09:00:00"):
    conn.execute(
        "INSERT INTO activities (activity_id, start_time_local, type_key, summary_json,"
        " first_seen_at, updated_at) VALUES (1, ?, 'running', '{}', 'x', 'x')", (date,))
    conn.commit()


def test_wellness_coverage_counts_asked_and_answered_separately():
    conn = _tmp_conn()
    _seed_activity(conn)
    arch.upsert_wellness(conn, "2024-05-12", {"sleep_seconds": 27300},
                         sleep_raw={"a": 1}, fetched_at="2026-07-10T00:00:00")
    arch.upsert_wellness(conn, "2024-05-13", {"sleep_seconds": None},
                         sleep_raw={}, fetched_at="2026-07-10T00:00:00")
    cov = arch.wellness_coverage(conn, today="2024-05-14")
    assert cov["expected"] == 3, "2024-05-12 … 2024-05-14"
    assert cov["fetched"] == 2
    assert cov["with_data"] == 1, "the unworn night was asked about, and was empty"
    assert cov["gaps"] == ["2024-05-14"], "only the never-asked date is a gap"
    conn.close()


def test_wellness_coverage_empty_night_is_not_a_gap():
    conn = _tmp_conn()
    _seed_activity(conn)
    arch.upsert_wellness(conn, "2024-05-12", {"sleep_seconds": None},
                         sleep_raw={}, fetched_at="2026-07-10T00:00:00")
    cov = arch.wellness_coverage(conn, today="2024-05-12")
    assert cov["gaps"] == [], "asked-and-empty is not missing data"
    assert cov["with_data"] == 0
    conn.close()


def test_verify_archive_does_not_gate_wellness_before_the_backfill_completes():
    """The nightly sync starts stamping `fetched_at` the moment it deploys, which
    would make every prior date look like a gap. The gate is ratcheted on the
    backfill's own completion marker, exactly like the activity expectations."""
    d = Path(tempfile.mkdtemp())
    orig = _patched(d, "2024-05-13")
    try:
        conn = arch.open_archive(d)
        _seed_activity(conn)
        conn.close()
        assert sg.verify_archive() == 0, "nothing banked yet → not a regression"

        conn = arch.open_archive(d)
        arch.upsert_wellness(conn, "2024-05-13", {"sleep_seconds": 27300},
                             sleep_raw={"a": 1}, fetched_at="2026-07-10T00:00:00")
        conn.close()
        assert sg.verify_archive() == 0, \
            "a sync banked last night; the 2024 history is not yet a regression"
    finally:
        _restore(orig)


def test_verify_archive_fails_on_a_wellness_gap_once_the_backfill_has_completed():
    d = Path(tempfile.mkdtemp())
    orig = _patched(d, "2024-05-13")
    try:
        conn = arch.open_archive(d)
        _seed_activity(conn)
        arch.upsert_wellness(conn, "2024-05-12", {"sleep_seconds": 27300},
                             sleep_raw={"a": 1}, fetched_at="2026-07-10T00:00:00")
        arch.set_meta(conn, "wellness_backfill_completed_at", "2026-07-10T01:00:00")
        conn.close()
        assert sg.verify_archive() == 1, "2024-05-13 was never fetched → regression"

        conn = arch.open_archive(d)
        arch.upsert_wellness(conn, "2024-05-13", {"sleep_seconds": None},
                             sleep_raw={}, fetched_at="2026-07-10T00:00:00")
        conn.close()
        assert sg.verify_archive() == 0, "asked-and-empty closes the gap"
    finally:
        _restore(orig)


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_"):
            _fn()
            print("ok", _name)
    print("ALL PASS")
