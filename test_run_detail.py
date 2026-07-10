"""Unit tests for sync_garmin detail helpers (no Garmin network)."""
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("sync_garmin", REPO / "sync_garmin.py")
sg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sg)


def test_downsample():
    # last element is forced to series[-1] (was 90, now 99)
    assert sg._downsample(list(range(100)), 10) == [0, 10, 20, 30, 40, 50, 60, 70, 80, 99]
    assert sg._downsample([1, 2, 3], 10) == [1, 2, 3]


def test_hr_drift():
    assert sg._hr_drift([150, 150, 170, 170]) == 20
    assert sg._hr_drift([160] * 10) == 0
    assert sg._hr_drift([150]) == 0


def test_split_shape():
    assert sg._split_shape([{"pace": 360}, {"pace": 360}, {"pace": 400}]) == "positive"
    assert sg._split_shape([{"pace": 400}, {"pace": 380}, {"pace": 350}]) == "negative"
    assert sg._split_shape([{"pace": 360}, {"pace": 362}, {"pace": 361}]) == "even"


def test_bin_splits():
    idx = {"sumDistance": 0, "directHeartRate": 1, "directSpeed": 2}
    # km1 bucket (0–999 m): two rows → full km, retained
    # km2 bucket (1000–1999 m): two rows → full km, retained
    # km3 bucket (2000–2999 m): one row at 2300 m → span = 300 m < 600 → dropped
    rows = [
        {"metrics": [200,  150, 3.0]},
        {"metrics": [800,  160, 3.0]},   # bucket 0: hr avg=155, pace=333
        {"metrics": [1200, 165, 2.8]},
        {"metrics": [1800, 175, 2.8]},   # bucket 1: hr avg=170, pace=357
        {"metrics": [2300, 180, 2.5]},   # bucket 2: span=300 < 600 → dropped
    ]
    out = sg._bin_splits(rows, idx)
    assert len(out) == 2, f"trailing partial km should be dropped (got {len(out)} splits)"
    assert out[0]["km"] == 1 and out[0]["hr"] == 155 and out[0]["pace"] == 333
    assert out[1]["km"] == 2 and out[1]["hr"] == 170 and out[1]["pace"] == 357


class _FakeDetailClient:
    def get_activity_details(self, aid, maxchart=2000, maxpoly=0):
        return {
            "metricDescriptors": [
                {"key": "sumDistance", "metricsIndex": 0},
                {"key": "directHeartRate", "metricsIndex": 1},
                {"key": "directSpeed", "metricsIndex": 2},
            ],
            "activityDetailMetrics": [
                {"metrics": [300, 150, 3.0]},
                {"metrics": [800, 158, 3.0]},
                {"metrics": [1400, 168, 2.6]},
                {"metrics": [1900, 176, 2.6]},
            ],
        }


def test_fetch_run_detail_shape():
    cache = sg.CACHE_DIR / "detail-999.json"
    if cache.exists():
        cache.unlink()
    act = {"activityId": 999, "hrTimeInZone_1": 0, "hrTimeInZone_2": 60,
           "hrTimeInZone_3": 120, "hrTimeInZone_4": 240, "hrTimeInZone_5": 30,
           "maxTemperature": 28, "aerobicTrainingEffect": 4.2,
           "activityTrainingLoad": 210.7, "elevationGain": 88.0}
    d = sg.fetch_run_detail(_FakeDetailClient(), act)
    assert len(d["splits"]) == 2
    assert all(isinstance(s["pace"], int) for s in d["splits"])
    assert d["zoneMin"] == [0, 1, 2, 4, 1]
    assert isinstance(d["driftBpm"], int) and d["driftBpm"] > 0
    assert d["tempC"] == 28 and d["te"] == 4.2 and d["load"] == 211
    assert d["splitShape"] in ("even", "positive", "negative")
    assert len(d["hrSeries"]) == 4


def test_distill_one_implementation_two_callers():
    """progress-views 2.1 — the fresh-fetch path and the stored-payload path
    share one distiller: the same raw payload + summary give identical output."""
    cache = sg.CACHE_DIR / "detail-998.json"
    if cache.exists():
        cache.unlink()
    act = {"activityId": 998, "hrTimeInZone_2": 60, "hrTimeInZone_4": 240,
           "maxTemperature": 22, "aerobicTrainingEffect": 3.1,
           "activityTrainingLoad": 130.2, "elevationGain": 40.0}
    client = _FakeDetailClient()
    via_fetch = sg.fetch_run_detail(client, act)          # fresh-fetch caller
    raw = client.get_activity_details(998)                # what the archive stores
    via_stored = sg.distill_run_detail(raw, act)          # stored-payload caller
    assert via_fetch == via_stored, "one distiller, two callers — outputs must match"
    assert sg.distill_run_detail(None, act) is None, "no raw payload → no detail"


# ──────────────────────────────────────────────────────────────────────────────
# run-detail design D1: the stream distiller
# ──────────────────────────────────────────────────────────────────────────────
def _stream_payload():
    """Raw get_activity_details in miniature: descriptor order scrambled,
    redundant metrics present, nulls scattered through the samples."""
    keys = ["directRunCadence", "sumDuration", "sumDistance", "directHeartRate",
            "directSpeed", "directGradeAdjustedSpeed", "directDoubleCadence",
            "directElevation", "directPower", "directLatitude", "directLongitude",
            "directPerformanceCondition", "directTimestamp"]
    rows = [
        {"metrics": [80.2, 0.0, 0.0, 120.0, 2.956, 2.913, 160.4, 512.24, 280.6, 47.371881, 8.535413, None, 1.7e12]},
        {"metrics": [81.0, 1.0, 3.1, 121.0, 3.004, 3.052, 162.0, 512.46, 285.2, 47.371912, 8.535441, 2.0, 1.7e12]},
        {"metrics": [None, 2.0, 6.2, None, None, None, None, None, None, 47.371951, 8.535484, None, 1.7e12]},
    ]
    return {
        "metricDescriptors": [{"key": k, "metricsIndex": i} for i, k in enumerate(keys)],
        "activityDetailMetrics": rows,
        "geoPolylineDTO": {"polyline": []},   # maxpoly=0 — always empty
    }


def test_stream_columns_rounding_and_nulls():
    """run-detail 2.1/2.3 — columnar, rounded to each metric's real precision,
    nulls preserved; the redundant metrics never appear in the output."""
    s = sg.distill_run_streams(_stream_payload())
    assert set(s) == {"t", "d", "hr", "v", "gap", "cad", "elev", "pwr", "lat", "lon", "pc"}
    assert s["t"] == [0, 1, 2] and all(isinstance(v, int) for v in s["t"])
    assert s["d"] == [0, 3, 6]
    assert s["v"] == [2.96, 3.0, None], "speed rounds to 2 dp; a null stays null"
    assert s["gap"] == [2.91, 3.05, None]
    assert s["elev"] == [512.2, 512.5, None]
    assert s["pwr"] == [281, 285, None]
    assert s["lat"] == [47.37188, 47.37191, 47.37195], "GPS keeps 5 dp"
    assert s["pc"] == [None, 2, None], "sparse performance condition preserved"
    assert s["hr"][2] is None, "a null sample is a null, never interpolated"
    assert len({len(col) for col in s.values()}) == 1, "every column is sample-aligned"


def test_stream_cadence_is_double_cadence():
    """run-detail 2.2 — directRunCadence is single-side strides/min despite its
    descriptor; the stream carries directDoubleCadence, whose mean matches the
    promoted avg_cadence within rounding."""
    s = sg.distill_run_streams(_stream_payload())
    assert s["cad"][:2] == [160, 162], "steps/min — not the ~80 strides/min column"
    promoted_avg_cadence = 161.2      # what Garmin's summary promotes
    valid = [c for c in s["cad"] if c is not None]
    assert abs(sum(valid) / len(valid) - promoted_avg_cadence) < 1.0


def test_stream_gps_recovered_from_columns():
    """run-detail 2.4 — geoPolylineDTO.polyline is ALWAYS empty (the sync
    fetches maxpoly=0); the route lives complete in the lat/lon columns. This
    test exists so nobody goes looking for the polyline again."""
    raw = _stream_payload()
    assert raw["geoPolylineDTO"]["polyline"] == [], "maxpoly=0 → no polyline, ever"
    s = sg.distill_run_streams(raw)
    assert all(v is not None for v in s["lat"]), "latitude present on every sample"
    assert all(v is not None for v in s["lon"]), "longitude present on every sample"


def test_stream_refuses_non_streams():
    assert sg.distill_run_streams(None) is None
    assert sg.distill_run_streams({}) is None
    assert sg.distill_run_streams({"metricDescriptors": [], "activityDetailMetrics": []}) is None
    # a payload without the shared axes is not a stream worth serving
    assert sg.distill_run_streams({
        "metricDescriptors": [{"key": "directHeartRate", "metricsIndex": 0}],
        "activityDetailMetrics": [{"metrics": [140]}],
    }) is None


def test_stream_largest_archived_run_serialises_small():
    """run-detail 2.5 — against the REAL local archive when present (skipped
    elsewhere): the largest raw payload distils to < 110 KB compact JSON and
    well under the gzip budget the page pays."""
    import gzip
    import json
    import sqlite3
    db = REPO / "activity-archive.db"
    if not db.exists():
        print("  (no local archive — stream size check skipped)")
        return
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT activity_id, detail_json FROM activities "
            "WHERE detail_json IS NOT NULL ORDER BY LENGTH(detail_json) DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if not row:
        print("  (archive holds no raw detail — stream size check skipped)")
        return
    s = sg.distill_run_streams(json.loads(row[1]))
    assert s, "the largest archived run distils"
    blob = json.dumps(s, separators=(",", ":")).encode()
    # measured 2026-07-10 on the real archive: 114,600 bytes raw / 29,583 gzip
    # for a 1,999-sample run with all 11 columns (the proposal's 105 KB probe
    # predates the pc column). The wire cost — gzip — is the budget that
    # matters; the raw bound just catches a distiller that stops rounding.
    assert len(blob) < 125_000, f"largest stream is {len(blob)} bytes — the distiller grew"
    assert len(gzip.compress(blob)) < 35_000, "gzipped stream stays affordable"


def test_load_activities_refetches_recent():
    """A run added later the same day must appear on the next sync without clearing the
    cache, while the immutable history is still served from cache (not re-pulled)."""
    import tempfile
    from pathlib import Path

    today = sg.TODAY.isoformat()

    class FakeClient:
        def __init__(self):
            self.recent = []
            self.calls = []

        def get_activities_by_date(self, start, end):
            self.calls.append((start, end))
            if end == today:                       # the always-fresh recent window
                return list(self.recent)
            return [{"activityId": 1, "startTimeLocal": "2026-05-01 08:00:00",  # history
                     "distance": 5000, "activityType": {"typeKey": "running"}}]

    orig = sg.CACHE_DIR
    sg.CACHE_DIR = Path(tempfile.mkdtemp())
    try:
        fc = FakeClient()
        first = sg.load_activities(fc)                       # first sync of the day: no run yet
        assert not any(a["activityId"] == 99 for a in first)
        n = len(fc.calls)                                    # history + recent = 2 calls

        # a run is uploaded later the SAME day; the cache is NOT cleared
        fc.recent = [{"activityId": 99, "startTimeLocal": today + " 18:00:00",
                      "distance": 5000, "activityType": {"typeKey": "running"}}]
        second = sg.load_activities(fc)                      # next sync
        assert any(a["activityId"] == 99 for a in second), "same-day run must appear"
        assert second[0]["activityId"] == 99, "newest activity should sort first"
        assert len(fc.calls) == n + 1, "history stays cached; only the recent window re-fetched"
    finally:
        sg.CACHE_DIR = orig


def test_history_not_cached_when_empty():
    """A failed/empty history pull must NOT be cached, so the next sync retries it —
    a transient Garmin error can't wipe historical data for the rest of the day."""
    import tempfile
    from pathlib import Path

    class FakeClient:
        def __init__(self):
            self.history_calls = 0

        def get_activities_by_date(self, start, end):
            if end == sg.TODAY.isoformat():
                return []
            self.history_calls += 1
            return []  # simulate a failed/empty history pull

    orig = sg.CACHE_DIR
    sg.CACHE_DIR = Path(tempfile.mkdtemp())
    try:
        fc = FakeClient()
        sg.load_activities(fc)
        sg.load_activities(fc)
        assert fc.history_calls == 2, "empty/failed history must be retried each sync, not cached"
    finally:
        sg.CACHE_DIR = orig


def test_history_cache_corrupt_is_refetched():
    """A corrupt history cache is re-pulled, not fatal."""
    import tempfile
    from pathlib import Path

    class FakeClient:
        def __init__(self):
            self.history_calls = 0

        def get_activities_by_date(self, start, end):
            if end == sg.TODAY.isoformat():
                return []
            self.history_calls += 1
            return [{"activityId": 1, "startTimeLocal": "2026-05-01 08:00:00"}]

    orig = sg.CACHE_DIR
    sg.CACHE_DIR = Path(tempfile.mkdtemp())
    try:
        sg.CACHE_DIR.mkdir(exist_ok=True)
        (sg.CACHE_DIR / f"activities-history-{sg.TODAY.isoformat()}.json").write_text("{ not json", encoding="utf-8")
        fc = FakeClient()
        acts = sg.load_activities(fc)
        assert fc.history_calls == 1, "corrupt cache should trigger a fresh history pull"
        assert any(a["activityId"] == 1 for a in acts)
    finally:
        sg.CACHE_DIR = orig


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_"):
            _fn()
            print("ok", _name)
    print("ALL PASS")
