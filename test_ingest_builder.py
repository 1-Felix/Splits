"""Tests for ingest_builder.build_athlete_data — deriving the telemetry contract
(the Slim + HR-zones field set) from banked Health Connect runs. Pure over its
inputs (today is injected), so the assertions are deterministic."""
import datetime as dt

from ingest_builder import build_athlete_data

TODAY = dt.date(2026, 7, 15)  # a Wednesday; this week's Monday = 2026-07-13
PROFILE = {"name": "Max", "age": 28, "maxHR": 190}


def _hr(bpm, dur=60, step=5):
    # a downsampled HR series: samples every `step`s across `dur`s, all at `bpm`
    return [{"tSec": t, "bpm": bpm} for t in range(0, dur + 1, step)]


RUNS = [
    # today (Wed), 5 km in 30:00 → 360 s/km, HR 150 (→ zone 3 at maxHR 190)
    {"sessionUid": "a", "startTimeLocal": "2026-07-15T07:00:00", "durationS": 1800,
     "distanceM": 5000, "avgHr": 150, "sportType": "running", "avgSpeed": 2.78, "source": "shealth",
     "hrSamples": _hr(150)},
    # Monday this week, 6 km in 40:00 → 400 s/km, HR 145 (→ zone 3)
    {"sessionUid": "b", "startTimeLocal": "2026-07-13T18:00:00", "durationS": 2400,
     "distanceM": 6000, "avgHr": 145, "sportType": "running", "avgSpeed": 2.5, "source": "shealth",
     "hrSamples": _hr(145)},
    # last week (Wed), 3 km in 20:00 → 400 s/km, HR 140
    {"sessionUid": "c", "startTimeLocal": "2026-07-08T07:00:00", "durationS": 1200,
     "distanceM": 3000, "avgHr": 140, "sportType": "running", "avgSpeed": 2.5, "source": "shealth",
     "hrSamples": _hr(140)},
]


def build():
    return build_athlete_data(RUNS, PROFILE, TODAY, plan_goal="1:59:59")


def test_profile_has_no_vo2():
    d = build()
    assert d["profile"] == {"name": "Max", "age": 28, "maxHR": 190}
    assert "vo2maxCurrent" not in d["profile"]


def test_non_goal_fields_omitted():
    d = build()
    assert "readiness" not in d
    assert "vo2max" not in d["history"]
    assert "sleep" not in d["history"]
    # the history-axis anchor stays (drives the pace/cadence x-axis) even though vo2 is gone
    assert d["history"]["vo2maxStartMonth"] == "2026-07"


def test_today_and_heatmap():
    d = build()
    assert d["today"] == "2026-07-15"
    hm = d["heatmapKm"]
    assert len(hm) == 365
    assert hm[364] == 5.0        # today
    assert hm[362] == 6.0        # 2026-07-13
    assert hm[357] == 3.0        # 2026-07-08
    assert sum(1 for v in hm if v) == 3


def test_recent_runs_newest_first_and_integer_pace():
    d = build()
    rr = d["recentRuns"]
    assert [r["date"] for r in rr] == ["2026-07-15", "2026-07-13", "2026-07-08"]
    a = rr[0]
    assert a == {"date": "2026-07-15", "type": "Run", "km": 5.0, "time": "30:00",
                 "pace": 360, "hr": 150, "cad": None}
    assert all(isinstance(r["pace"], int) for r in rr)


def test_weekly_volume_oldest_to_newest():
    d = build()
    h = d["history"]
    assert len(h["weeklyKm"]) == 26 and len(h["weeklyRuns"]) == 26
    assert h["weeklyKm"][-1] == 11.0 and h["weeklyRuns"][-1] == 2   # this week: 5 + 6
    assert h["weeklyKm"][-2] == 3.0 and h["weeklyRuns"][-2] == 1    # last week: 3


def test_fitness_fatigue_shape():
    d = build()
    h = d["history"]
    assert len(h["ctl"]) == 26 and len(h["atl"]) == 26
    assert all(isinstance(v, float) for v in h["ctl"])
    assert h["ctl"][-1] > 0 and h["atl"][-1] > 0   # there is load this week


def test_monthly_pace_and_null_cadence():
    d = build()
    h = d["history"]
    # aggregate month pace = total secs / total km = 5400 / 14 = 385.7 → 386
    assert h["paceSecPerKm"] == [386]
    assert h["cadenceSpm"] == [None]   # Samsung does not write cadence to Health Connect


def test_hr_zones_binned_from_samples():
    d = build()
    z = d["hrZones"]
    assert len(z) == 5
    # bounds at maxHR 190: [95,114,133,152,171,190]; 150 & 145 → zone 3 (133–152)
    assert z[2] == {"z": 3, "label": "Tempo", "min": 2, "lo": 133, "hi": 152}
    assert sum(x["min"] for x in z) == 2   # only this week's two runs, 60 s each


def test_predictions_from_best_effort():
    d = build()
    p = d["predictions"]
    assert p["fiveK"] == "30:00"          # anchor is the 5 km @ 6:00 (fastest)
    assert p["halfGoal"] == "1:59:59"     # from the plan's race goal
    assert isinstance(p["halfNow"], str) and isinstance(p["tenK"], str)


def test_monthly_pace_dense_over_gap_months():
    # a month with no runs must appear as None, not be silently dropped —
    # otherwise the chart mislabels every month after the gap (task 10.2)
    runs = [
        {"sessionUid": "m1", "startTimeLocal": "2026-03-10T07:00:00", "durationS": 1800,
         "distanceM": 5000, "avgHr": 150, "sportType": "running", "avgSpeed": 2.78,
         "source": "x", "hrSamples": []},
        {"sessionUid": "m2", "startTimeLocal": "2026-05-10T07:00:00", "durationS": 1500,
         "distanceM": 5000, "avgHr": 150, "sportType": "running", "avgSpeed": 3.33,
         "source": "x", "hrSamples": []},
    ]
    d = build_athlete_data(runs, PROFILE, TODAY, plan_goal=None)
    h = d["history"]
    assert h["vo2maxStartMonth"] == "2026-03"
    assert h["paceSecPerKm"] == [360, None, 300]   # Mar, (Apr gap), May
    assert h["cadenceSpm"] == [None, None, None]


def test_poisoned_date_row_is_skipped_not_fatal():
    # 2026-02-29 passes Node's Date.parse (rolls over) but raises in fromisoformat;
    # a poisoned banked row must not wedge every future rebuild (task 10.1)
    bad = {"sessionUid": "poison", "startTimeLocal": "2026-02-29T07:00:00",
           "durationS": 1800, "distanceM": 5000, "avgHr": 150,
           "sportType": "running", "avgSpeed": 2.78, "source": "x", "hrSamples": []}
    d = build_athlete_data(RUNS + [bad], PROFILE, TODAY, plan_goal=None)
    assert [r["date"] for r in d["recentRuns"]] == ["2026-07-15", "2026-07-13", "2026-07-08"]


def test_zero_distance_row_is_skipped_not_fatal():
    # distanceM 0 would ZeroDivisionError in pace math (task 10.5)
    bad = {"sessionUid": "zero", "startTimeLocal": "2026-07-14T07:00:00",
           "durationS": 1800, "distanceM": 0, "avgHr": 150,
           "sportType": "running", "avgSpeed": 0, "source": "x", "hrSamples": []}
    d = build_athlete_data(RUNS + [bad], PROFILE, TODAY, plan_goal=None)
    assert [r["date"] for r in d["recentRuns"]] == ["2026-07-15", "2026-07-13", "2026-07-08"]


def test_non_dict_row_is_skipped_not_fatal():
    # a hand-edited or corrupt store row that isn't an object (task 10.5)
    d = build_athlete_data(RUNS + [None, "junk"], PROFILE, TODAY, plan_goal=None)
    assert [r["date"] for r in d["recentRuns"]] == ["2026-07-15", "2026-07-13", "2026-07-08"]


def test_sport_type_label_is_case_insensitive():
    # Health Connect / hand-authored payloads may carry any casing; the label
    # lookup must not miss its table on "TREADMILL_RUNNING" (task 10.5)
    r = dict(RUNS[0], sportType="TREADMILL_RUNNING")
    d = build_athlete_data([r], PROFILE, TODAY, plan_goal=None)
    assert d["recentRuns"][0]["type"] == "Treadmill Run"


def test_main_tolerates_non_object_store(tmp_path=None):
    # a corrupt store whose JSON root isn't an object must build 0 runs, not crash
    import os
    import tempfile
    from pathlib import Path

    import ingest_builder

    with tempfile.TemporaryDirectory() as td:
        Path(td, "ingested-runs.json").write_text('"just a string"', encoding="utf-8")
        old = os.environ.get("SPLITS_DATA_DIR")
        os.environ["SPLITS_DATA_DIR"] = td
        try:
            ingest_builder.main()
        finally:
            if old is None:
                os.environ.pop("SPLITS_DATA_DIR", None)
            else:
                os.environ["SPLITS_DATA_DIR"] = old
        out = Path(td, "garmin-data.js").read_text(encoding="utf-8")
        assert '"recentRuns": []' in out


# ── scope expansion (design D9/D12): zone calibration ────────────────────────
def test_zone_bounds_calibrate_from_observed_max_hr():
    # observed per-run max HR replaces the 220−age fallback (D9)
    r = dict(RUNS[0], maxHr=184)
    d = build_athlete_data([r], {"name": "Max", "age": 30}, TODAY, plan_goal=None)
    assert d["profile"]["maxHR"] == 184          # not 190 (= 220−30)
    assert d["hrZones"][4]["hi"] == 184


def test_max_hr_is_the_best_evidence_available():
    # explicit profile maxHR still wins when higher than anything observed…
    r = dict(RUNS[0], maxHr=184)
    d = build_athlete_data([r], PROFILE, TODAY, plan_goal=None)   # profile maxHR 190
    assert d["profile"]["maxHR"] == 190
    # …but a higher observed max overrides it (an observation is a lower bound on truth)
    r2 = dict(RUNS[0], maxHr=195)
    d2 = build_athlete_data([r2], PROFILE, TODAY, plan_goal=None)
    assert d2["profile"]["maxHR"] == 195


def test_karvonen_zones_when_resting_hr_known():
    # HR-reserve bounds (D12): rhr + fraction × (max − rhr); rhr = median of the
    # last banked days. maxHR 190, rhr 50 → [120,134,148,162,176,190]
    rhr_days = {"2026-07-13": 52, "2026-07-14": 50, "2026-07-15": 48}
    d = build_athlete_data(RUNS, PROFILE, TODAY, plan_goal=None, rhr_days=rhr_days)
    z = d["hrZones"]
    assert [x["lo"] for x in z] == [120, 134, 148, 162, 176]
    assert z[4]["hi"] == 190
    # run a (HR 150) now bins as zone 3 (148–162), run b (145) as zone 2
    assert z[2]["min"] == 1 and z[1]["min"] == 1
    assert d["profile"]["restingHR"] == 50


# ── scope expansion (design D10/D11): moving pace + splits + cadence ─────────
def _speed(mps_by_span, step=5):
    # speedSamples from (start, end, mps) spans, sampled every `step` seconds
    out = []
    for start, end, mps in mps_by_span:
        out.extend({"tSec": t, "mps": mps} for t in range(start, end, step))
    out.append({"tSec": mps_by_span[-1][1], "mps": mps_by_span[-1][2]})
    return out


# ~14 min elapsed with a 60 s dead stop in the middle: 800 s moving over 2400 m
PAUSED_RUN = {
    "sessionUid": "mv", "startTimeLocal": "2026-07-15T07:00:00", "durationS": 860,
    "distanceM": 2400, "avgHr": 150, "maxHr": 165, "sportType": "running",
    "avgSpeed": 2.79, "source": "x", "hrSamples": _hr(150, dur=860),
    "speedSamples": _speed([(0, 500, 3.0), (500, 560, 0.0), (560, 860, 3.0)]),
}


def test_moving_pace_strips_pauses():
    # elapsed pace would be 860/2.4 = 358; moving pace is 800/2.4 = 333 (D10)
    d = build_athlete_data([PAUSED_RUN], PROFILE, TODAY, plan_goal=None)
    assert d["recentRuns"][0]["pace"] == 333
    assert d["history"]["paceSecPerKm"] == [333]


def test_riegel_anchor_uses_moving_effort():
    from ingest_builder import _fmt_hms
    d = build_athlete_data([PAUSED_RUN], PROFILE, TODAY, plan_goal=None)
    assert d["predictions"]["fiveK"] == _fmt_hms(800 * (5 / 2.4) ** 1.06)


def test_pace_stays_elapsed_without_a_speed_series():
    d = build_athlete_data(RUNS, PROFILE, TODAY, plan_goal=None)
    assert d["recentRuns"][0]["pace"] == 360   # unchanged Samsung-less-speed path


# constant 3.0 m/s for 700 s → 2100 m: two full km splits, 100 m sliver dropped
STEADY_RUN = {
    "sessionUid": "sp", "startTimeLocal": "2026-07-15T07:00:00", "durationS": 700,
    "distanceM": 2100, "avgHr": 150, "maxHr": 166, "sportType": "running",
    "avgSpeed": 3.0, "source": "x", "hrSamples": _hr(150, dur=700),
    "speedSamples": _speed([(0, 700, 3.0)]),
    "elevationGainM": 55.4, "activeKcal": 180, "totalKcal": 205, "steps": 1985,
}


def test_splits_and_detail_from_speed_series():
    d = build_athlete_data([STEADY_RUN], PROFILE, TODAY, plan_goal=None)
    det = d["recentRuns"][0]["detail"]
    assert det["splits"] == [{"km": 1, "pace": 333, "hr": 150}, {"km": 2, "pace": 333, "hr": 150}]
    assert det["splitShape"] == "even"
    assert det["driftBpm"] == 0
    assert det["elevGain"] == 55
    assert det["zoneMin"][2] == 12                    # 700 s at HR 150 → zone 3
    assert 0 < len(det["hrSeries"]) <= 30 and all(isinstance(v, int) for v in det["hrSeries"])
    assert det["tempC"] is None and det["te"] is None and det["load"] is None


def test_no_detail_without_a_speed_series():
    d = build_athlete_data(RUNS, PROFILE, TODAY, plan_goal=None)
    assert all("detail" not in r for r in d["recentRuns"])


def test_cadence_from_steps_over_moving_minutes():
    d = build_athlete_data([STEADY_RUN], PROFILE, TODAY, plan_goal=None)
    assert d["recentRuns"][0]["cad"] == 170           # 1985 steps / (700/60) min
    assert d["history"]["cadenceSpm"] == [170]


def test_cadence_stays_null_without_steps():
    d = build_athlete_data([PAUSED_RUN], PROFILE, TODAY, plan_goal=None)
    assert d["recentRuns"][0]["cad"] is None
    assert d["history"]["cadenceSpm"] == [None]


# ── scope expansion (design D12/D13): energy tile data + RHR trend ───────────
def test_energy_this_week_from_calories():
    other = dict(STEADY_RUN, sessionUid="sp2", totalKcal=None, activeKcal=180)
    d = build_athlete_data([STEADY_RUN, other], PROFILE, TODAY, plan_goal=None)
    # totalKcal preferred, activeKcal as the fallback: 205 + 180
    assert d["energy"] == {"weekKcal": 385}


def test_energy_absent_without_calories():
    d = build_athlete_data(RUNS, PROFILE, TODAY, plan_goal=None)
    assert "energy" not in d


def test_rhr_trend_series_last_90_days():
    rhr_days = {"2026-07-13": 52, "2026-07-15": 48, "2026-05-01": 60, "2026-01-01": 70}
    d = build_athlete_data(RUNS, PROFILE, TODAY, plan_goal=None, rhr_days=rhr_days)
    assert d["history"]["restingHr"] == [
        {"date": "2026-05-01", "bpm": 60},        # 2026-01-01 is outside the window
        {"date": "2026-07-13", "bpm": 52},
        {"date": "2026-07-15", "bpm": 48},
    ]


def test_rhr_trend_absent_without_data():
    d = build_athlete_data(RUNS, PROFILE, TODAY, plan_goal=None)
    assert "restingHr" not in d["history"]


def test_empty_store_is_safe():
    d = build_athlete_data([], PROFILE, TODAY, plan_goal=None)
    assert len(d["heatmapKm"]) == 365 and sum(d["heatmapKm"]) == 0
    assert d["recentRuns"] == []
    assert len(d["history"]["weeklyKm"]) == 26
    assert "readiness" not in d and "vo2max" not in d["history"]


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}")
    print("ALL PASS" if not failed else f"{failed} FAILED")
    sys.exit(1 if failed else 0)
