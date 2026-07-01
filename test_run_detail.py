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
