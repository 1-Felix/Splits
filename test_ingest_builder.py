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


# ── the archive pass (add-ingest-archive) ────────────────────────────────────
import json
import sqlite3
import tempfile
from pathlib import Path

import activity_archive as arch
import ingest_builder as ib
import insight_metrics as im


def _tmpdir() -> Path:
    return Path(tempfile.mkdtemp())


def _db(data_dir: Path) -> sqlite3.Connection:
    return sqlite3.connect(arch.archive_path(data_dir))


def test_samples_dict_parity_with_read_stream():
    # 1.1 — the same physical run recorded both ways: 1 s sampling, constant
    # 2.2 m/s, HR 135 for 20 min. The Garmin path goes through read_stream;
    # the ingest path through synth_streams + _metric_samples. The pure
    # engines must agree on every field both sources can supply — and the
    # fields ingest cannot supply (cadence) must be empty/NULL, never zero-ish
    # fabrications. This test IS the samples-dict contract pin (design D7).
    seconds = 1200
    keys = ("sumElapsedDuration", "sumDistance", "directHeartRate",
            "directRunCadence", "directGradeAdjustedSpeed")
    det = {"metricDescriptors": [{"key": k, "metricsIndex": i}
                                 for i, k in enumerate(keys)],
           "activityDetailMetrics": [{"metrics": [t, 2.2 * t, 135, 85, 2.2]}
                                     for t in range(seconds + 1)]}
    garmin = im.read_stream(det)
    run = {"sessionUid": "par", "startTimeLocal": "2026-07-15T07:00:00",
           "durationS": seconds, "distanceM": 2.2 * seconds, "avgHr": 135,
           "sportType": "running", "source": "x",
           "hrSamples": [{"tSec": t, "bpm": 135} for t in range(seconds + 1)],
           "speedSamples": [{"tSec": t, "mps": 2.2} for t in range(seconds + 1)]}
    ingest = ib._metric_samples(ib.synth_streams(run))

    eg, ei = im.best_efforts(garmin), im.best_efforts(ingest)
    assert ei["best_1k_s"] is not None and abs(ei["best_1k_s"] - eg["best_1k_s"]) <= 1.0
    assert abs(ei["best_mile_s"] - eg["best_mile_s"]) <= 1.0
    assert ei["best_5k_s"] is None and eg["best_5k_s"] is None, \
        "distances beyond the run stay NULL on both paths"

    ag, ai = im.band_aggregates(garmin), im.band_aggregates(ingest)
    assert abs(ai["refhr_time_s"] - ag["refhr_time_s"]) <= 2, (ag, ai)
    assert abs(ai["refhr_dist_m"] - ag["refhr_dist_m"]) <= 10, (ag, ai)
    assert abs(ai["refhr_pace_s_per_km"] - ag["refhr_pace_s_per_km"]) <= 2
    # what an ingest samples dict HAS: t, d, hr, v. What it lacks: cadence —
    # so the refpace pools stay empty and the display value stays NULL.
    assert ag["refpace_time_s"] > 0, "the Garmin fixture does carry cadence"
    assert ai["refpace_time_s"] == 0.0 and ai["refpace_cadence_x_time"] == 0.0
    assert ai["refpace_cadence_spm"] is None, "no evidence ≠ zero cadence"


def test_derive_activity_id_deterministic_distinct_js_safe():
    uid = "11111111-2222-3333-4444-555555555555"
    a = ib.derive_activity_id(uid)
    assert a == ib.derive_activity_id(uid), "deterministic"
    assert a != ib.derive_activity_id("99999999-2222-3333-4444-555555555555")
    assert 0 <= a < 2 ** 48 < 2 ** 53, "48-bit, JS-safe"
    assert ib.derive_activity_id(uid, salt=1) not in (a, ib.derive_activity_id(uid, salt=2)), \
        "salted derivations are distinct from the base and each other"


def test_id_collision_salted_rehash_not_silent():
    # 2.2 — force two distinct UIDs onto one id: the later run must land on the
    # deterministic salted rehash, both rows must exist, neither overwritten.
    tmp = _tmpdir()
    real = ib.derive_activity_id

    def forced(uid, salt=0):
        return 777 if salt == 0 else real(uid, salt)

    a = dict(STEADY_RUN, sessionUid="col-a")
    b = dict(STEADY_RUN, sessionUid="col-b",
             startTimeLocal="2026-07-16T07:00:00")
    ib.derive_activity_id = forced
    try:
        ib.build_archive(tmp, [a, b], PROFILE)
    finally:
        ib.derive_activity_id = real
    conn = _db(tmp)
    rows = {aid: json.loads(s)["sessionUid"] for aid, s in
            conn.execute("SELECT activity_id, summary_json FROM activities")}
    conn.close()
    assert rows == {777: "col-a", real("col-b", 1): "col-b"}, \
        "earlier run keeps the base id; the collider re-derives with salt #1"


def test_archive_schema_parity_with_garmin_created_db():
    # 3.1 — a fresh ingest-built archive must be indistinguishable in shape
    # from one the Garmin pipeline would create: same tables, same version.
    ingest_dir, garmin_dir = _tmpdir(), _tmpdir()
    ib.build_archive(ingest_dir, [STEADY_RUN], PROFILE)
    arch.open_archive(garmin_dir).close()

    def shape(d):
        conn = _db(d)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%'")}
        version = conn.execute(
            "SELECT value FROM archive_meta WHERE key = 'schema_version'"
        ).fetchone()[0]
        conn.close()
        return tables, version

    assert shape(ingest_dir) == shape(garmin_dir)
    assert shape(ingest_dir)[1] == str(arch.SCHEMA_VERSION)


def test_archive_row_promoted_columns_and_verbatim_summary():
    # 3.2 — promoted columns map from the banked payload; summary_json is that
    # payload VERBATIM; fields the source can't supply stay NULL (even when a
    # cousin field like elevationGainM exists in the payload — promotion is
    # honest absence, the distilled detail owns elevation display).
    tmp = _tmpdir()
    tread = dict(STEADY_RUN, sessionUid="tm", sportType="TREADMILL_RUNNING",
                 startTimeLocal="2026-07-14T07:00:00")
    ib.build_archive(tmp, [STEADY_RUN, tread, RUNS[0]], PROFILE)
    conn = _db(tmp)
    row = conn.execute(
        """SELECT start_time_local, type_key, distance_m, duration_s, avg_hr,
                  max_hr, name, avg_cadence, elevation_gain_m, detail_json,
                  summary_json
           FROM activities WHERE activity_id = ?""",
        (ib.derive_activity_id("sp"),)).fetchone()
    assert row[:6] == ("2026-07-15T07:00:00", "running", 2100, 700, 150, 166)
    assert row[6:10] == (None, None, None, None), \
        "name / avg_cadence / elevation_gain_m / detail_json stay NULL"
    assert json.loads(row[10]) == STEADY_RUN, "banked payload survives verbatim"
    t_key = conn.execute(
        "SELECT type_key FROM activities WHERE activity_id = ?",
        (ib.derive_activity_id("tm"),)).fetchone()[0]
    assert t_key == "treadmill_running", "type_key normalized to the filter chips"
    n = conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
    conn.close()
    assert n == 3, "every banked run gets a row — no recent-runs cap"


def test_streams_synthesis_axis_normalization_and_omitted_keys():
    # 3.3 — shared t axis from the union of sample times, hr/v aligned with
    # nulls preserved, d integrated and normalized to the banked distance,
    # absent metrics omitted entirely.
    run = {"sessionUid": "st", "startTimeLocal": "2026-07-15T07:00:00",
           "durationS": 100, "distanceM": 315, "avgHr": 150,
           "sportType": "running", "source": "x",
           "hrSamples": [{"tSec": t, "bpm": 150} for t in range(0, 101, 5)],
           "speedSamples": [{"tSec": t, "mps": 3.0} for t in range(0, 101, 10)]}
    st = ib.synth_streams(run)
    assert st["t"] == list(range(0, 101, 5)), "union axis of HR + speed times"
    assert st["v"][0] == 3.0 and st["v"][1] == 3.0, \
        "t=5 carries no speed sample of its own — it holds the reading from t=0"
    assert st["hr"] == [150] * 21
    # raw integration reads 300 m; the device's own total (315) wins
    assert st["d"][-1] == 315 and st["d"][0] == 0
    assert all(a <= b for a, b in zip(st["d"], st["d"][1:])), "d non-decreasing"
    assert set(st) == {"t", "d", "hr", "v"}, \
        "cad/elev/gap/pwr/lat/lon/pc are omitted keys, never fabricated"
    assert ib.synth_streams(RUNS[0]) is None, \
        "no speed series → no streams (no honest distance axis exists)"


def test_streams_hold_last_reading_across_interleaved_series():
    # Real Samsung Health data (Max, 2026-07-17): HR and speed are written on
    # SEPARATE ~10 s clocks a few seconds apart — only 19 of 89 timestamps
    # coincided. A union axis filled by exact match left every other point
    # null: 70 of 159 in each series, which drew as a dotted chart and fed
    # _metric_samples a half-empty series. Each axis point now carries the
    # most recent real reading (sample-and-hold — never an invented value).
    run = {"sessionUid": "off", "startTimeLocal": "2026-07-15T07:00:00",
           "durationS": 100, "distanceM": 300, "avgHr": 150,
           "sportType": "running", "source": "x",
           "hrSamples": [{"tSec": t, "bpm": 140 + t // 10} for t in range(1, 100, 10)],
           "speedSamples": [{"tSec": t, "mps": 3.0} for t in range(7, 100, 10)]}
    st = ib.synth_streams(run)
    assert len(set(s["tSec"] for s in run["hrSamples"])
               & set(s["tSec"] for s in run["speedSamples"])) == 0, "fixture is interleaved"
    assert None not in st["hr"], f"HR is continuous across the axis: {st['hr']}"
    # speed only starts at t=7 — points before the first reading stay honest
    lead = st["t"].index(7)
    assert st["v"][:lead] == [None] * lead, "nothing measured yet ≠ a value"
    assert None not in st["v"][lead:], f"speed is continuous once measured: {st['v']}"
    assert st["hr"][0] == 140 and st["hr"][st["t"].index(7)] == 140, \
        "a held point repeats the last real reading, never an interpolated one"


def test_streams_do_not_bridge_a_real_dropout():
    # Holding is bounded: a gap longer than the pause cap is a real sensor
    # dropout and must read as absence, not a flat line across the hole.
    gap = ib.SAMPLE_GAP_CAP_S + 40
    run = {"sessionUid": "drop", "startTimeLocal": "2026-07-15T07:00:00",
           "durationS": 200, "distanceM": 600, "avgHr": 150,
           "sportType": "running", "source": "x",
           "hrSamples": [{"tSec": 0, "bpm": 150}, {"tSec": gap, "bpm": 152}],
           "speedSamples": [{"tSec": t, "mps": 3.0} for t in range(0, 201, 10)]}
    st = ib.synth_streams(run)
    held = st["t"].index(ib.SAMPLE_GAP_CAP_S) if ib.SAMPLE_GAP_CAP_S in st["t"] else None
    assert held is not None and st["hr"][held] == 150, "held up to the cap"
    beyond = [h for t, h in zip(st["t"], st["hr"]) if ib.SAMPLE_GAP_CAP_S < t < gap]
    assert beyond and set(beyond) == {None}, f"dropout stays absent: {beyond}"


def test_archived_distilled_equals_recent_runs_detail():
    # 3.4 — one derivation, two consumers: the archived dict must equal the
    # cockpit's recentRuns[].detail for the same run, byte for byte.
    tmp = _tmpdir()
    cockpit = build_athlete_data([STEADY_RUN, RUNS[0]], PROFILE, TODAY)
    ib.build_archive(tmp, [STEADY_RUN, RUNS[0]], PROFILE)
    conn = _db(tmp)
    stored = conn.execute(
        "SELECT detail_distilled_json FROM activities WHERE activity_id = ?",
        (ib.derive_activity_id("sp"),)).fetchone()[0]
    no_speed = conn.execute(
        "SELECT detail_distilled_json FROM activities WHERE activity_id = ?",
        (ib.derive_activity_id("a"),)).fetchone()[0]
    conn.close()
    steady_row = next(r for r in cockpit["recentRuns"] if r["km"] == 2.1)
    assert json.loads(stored) == steady_row["detail"]
    assert no_speed is None, "no speed series → no distilled detail, honest NULL"


def test_run_metrics_from_the_pure_engines():
    # 3.5 — rows appear at METRICS_VERSION via best_efforts/band_aggregates
    # over the synthesized samples; treadmill flagged; a sample-less run banks
    # an empty row (deterministic absence — no nightly retry loop).
    tmp = _tmpdir()
    tread = dict(STEADY_RUN, sessionUid="tm", sportType="treadmill_running",
                 startTimeLocal="2026-07-14T07:00:00")
    ib.build_archive(tmp, [STEADY_RUN, tread, RUNS[0]], PROFILE)
    conn = _db(tmp)
    rows = {r[0]: r for r in conn.execute(
        "SELECT activity_id, metrics_version, is_treadmill, best_1k_s "
        "FROM run_metrics")}
    conn.close()
    steady = rows[ib.derive_activity_id("sp")]
    assert steady[1] == im.METRICS_VERSION and steady[2] == 0
    assert abs(steady[3] - 1000 / 3.0) <= 1.5, "best 1k at constant 3 m/s"
    assert rows[ib.derive_activity_id("tm")][2] == 1, "treadmill flagged"
    empty = rows[ib.derive_activity_id("a")]
    assert empty[1] == im.METRICS_VERSION and empty[3] is None, \
        "no speed series → empty row at the current version"


def test_zero_runs_leaves_the_instance_unprovisioned():
    # a fresh instance must stay "no archive on this instance" (404 + hidden
    # chrome) until the first run lands — an empty db would flip /api/status's
    # archive flag and reveal empty archive chrome
    tmp = _tmpdir()
    assert ib.build_archive(tmp, [], PROFILE) == 0
    assert not arch.archive_path(tmp).exists()


def test_archive_idempotent_version_bumps_and_self_healing():
    # 3.6 — steady state is write-once; a version bump recomputes; a deleted
    # db regenerates completely with identical ids.
    tmp = _tmpdir()
    runs = [STEADY_RUN, RUNS[0]]
    ib.build_archive(tmp, runs, PROFILE)

    def snapshot():
        conn = _db(tmp)
        acts = conn.execute(
            "SELECT activity_id, updated_at, first_seen_at, summary_json, "
            "detail_streams_json, detail_distilled_json "
            "FROM activities ORDER BY activity_id").fetchall()
        mets = conn.execute(
            "SELECT activity_id, metrics_version, computed_at, best_1k_s "
            "FROM run_metrics ORDER BY activity_id").fetchall()
        conn.close()
        return acts, mets

    first = snapshot()
    import time
    time.sleep(1.1)          # updated_at has 1 s resolution — churn would show
    ib.build_archive(tmp, runs, PROFILE)
    assert snapshot() == first, "second pass is a no-op: no churn anywhere"

    # a distill-version bump recomputes streams + distilled (write-once until)
    conn = _db(tmp)
    conn.execute("UPDATE activities SET detail_streams_json = '{\"t\":[0]}' "
                 "WHERE activity_id = ?", (ib.derive_activity_id("sp"),))
    conn.commit(); conn.close()
    ib.build_archive(tmp, runs, PROFILE)
    conn = _db(tmp)
    tampered = conn.execute(
        "SELECT detail_streams_json FROM activities WHERE activity_id = ?",
        (ib.derive_activity_id("sp"),)).fetchone()[0]
    conn.close()
    assert tampered == '{"t":[0]}', "same version → existing artifact untouched"
    old = ib.INGEST_DISTILL_VERSION
    ib.INGEST_DISTILL_VERSION = old + 1
    try:
        ib.build_archive(tmp, runs, PROFILE)
    finally:
        ib.INGEST_DISTILL_VERSION = old
    conn = _db(tmp)
    healed = json.loads(conn.execute(
        "SELECT detail_streams_json FROM activities WHERE activity_id = ?",
        (ib.derive_activity_id("sp"),)).fetchone()[0])
    conn.close()
    assert len(healed["t"]) > 1, "bumped marker → streams recomputed"

    # a METRICS_VERSION bump recomputes metrics rows (stale row replaced)
    real_mv = im.METRICS_VERSION
    im.METRICS_VERSION = real_mv + 1
    try:
        ib.build_archive(tmp, runs, PROFILE)
    finally:
        im.METRICS_VERSION = real_mv
    conn = _db(tmp)
    versions = [r[0] for r in conn.execute(
        "SELECT DISTINCT metrics_version FROM run_metrics")]
    conn.close()
    assert versions == [real_mv + 1], "stale rows replaced, not duplicated"

    # deleting the file is always safe: full regeneration, identical ids
    ids_before = sorted(r[0] for r in first[0])
    arch.archive_path(tmp).unlink()
    ib.build_archive(tmp, runs, PROFILE)
    conn = _db(tmp)
    ids_after = sorted(r[0] for r in conn.execute(
        "SELECT activity_id FROM activities"))
    streams = conn.execute(
        "SELECT COUNT(*) FROM activities WHERE detail_streams_json IS NOT NULL"
    ).fetchone()[0]
    metrics = conn.execute("SELECT COUNT(*) FROM run_metrics").fetchone()[0]
    conn.close()
    assert ids_after == ids_before, "previously shared /run/:id links keep resolving"
    assert streams == 1 and metrics == 2, "streams, detail and metrics all healed"


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
