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


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_"):
            _fn()
            print("ok", _name)
    print("ALL PASS")
