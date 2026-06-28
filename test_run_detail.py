"""Unit tests for sync_garmin detail helpers (no Garmin network)."""
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("sync_garmin", REPO / "sync_garmin.py")
sg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sg)


def test_downsample():
    assert sg._downsample(list(range(100)), 10) == [0, 10, 20, 30, 40, 50, 60, 70, 80, 90]
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
    rows = [{"metrics": [500, 150, 3.0]}, {"metrics": [900, 160, 3.0]}, {"metrics": [1500, 170, 2.5]}]
    out = sg._bin_splits(rows, idx)
    assert out[0]["km"] == 1 and out[0]["hr"] == 155 and out[0]["pace"] == 333
    assert out[1]["km"] == 2 and out[1]["hr"] == 170


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_"):
            _fn()
            print("ok", _name)
    print("ALL PASS")
