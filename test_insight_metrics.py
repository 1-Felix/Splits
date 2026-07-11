"""Unit tests for insight_metrics.py (synthetic streams, no network).

The oracle test at the bottom additionally reads the LOCAL activity-archive.db
(the 100 MB dress-rehearsal copy) and cross-validates our best efforts against
Garmin's own fastestSplit_* values; it skips silently when the archive is
absent — CI has no personal data and no GPS-bearing fixtures get committed.
"""
import importlib.util
import json
import sqlite3
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


arch = _load("activity_archive")
im = _load("insight_metrics")

T0_MS = 1_700_000_000_000  # arbitrary GMT epoch base for synthetic timestamps


def _tmp() -> Path:
    return Path(tempfile.mkdtemp())


def _detail(samples, keys=("directTimestamp", "sumDistance", "directHeartRate",
                           "directRunCadence", "directGradeAdjustedSpeed")):
    """Wrap (ts_s, dist_m, hr, cad, speed) tuples as a raw detail payload."""
    rows = []
    for s in samples:
        vals = list(s) + [None] * (len(keys) - len(s))
        if "directTimestamp" in keys:
            vals[keys.index("directTimestamp")] = T0_MS + s[0] * 1000
        rows.append({"metrics": vals})
    return {
        "metricDescriptors": [{"key": k, "metricsIndex": i} for i, k in enumerate(keys)],
        "activityDetailMetrics": rows,
    }


def _steady(seconds, speed, hr=135, cad=85, t_start=0, d_start=0.0, step=1):
    """(t, d, hr, cad, speed) samples at constant speed, `step`-second sampling.
    cad is the RAW stream value (single-side strides/min, Garmin quirk) —
    read_stream doubles it, so the default 85 reads back as 170 spm."""
    return [(t_start + i, d_start + speed * i, hr, cad, speed)
            for i in range(0, seconds + 1, step)]


# ──────────────────────────────────────────────────────────────────────────────
# 2.1 stream reader
# ──────────────────────────────────────────────────────────────────────────────
def test_read_stream_clamps_and_drops():
    det = _detail([(0, 0.0, 130, 170, 3.0),
                   (1, 3.0, 131, 170, 3.0),
                   (2, None, 132, 170, 3.0),   # no distance → dropped
                   (3, 2.0, 133, 170, 3.0),    # GPS wobble backwards → clamped
                   (4, 12.0, None, None, None)])
    s = im.read_stream(det)
    assert [x[0] for x in s] == [0.0, 1.0, 3.0, 4.0], "elapsed from timestamps, row without distance dropped"
    assert [x[1] for x in s] == [0.0, 3.0, 3.0, 12.0], "distance clamped non-decreasing"
    assert s[1][2:] == (131, 340, 3.0) and s[3][2:] == (None, None, None), \
        "stream cadence is single-side strides/min — doubled to steps/min"


def test_read_stream_elapsed_fallback_and_gas_fallback():
    det = _detail([(0, 0.0, 130, 170, 3.1), (10, 30.0, 131, 171, 3.2)],
                  keys=("sumElapsedDuration", "sumDistance", "directHeartRate",
                        "directRunCadence", "directSpeed"))
    s = im.read_stream(det)
    assert [x[0] for x in s] == [0.0, 10.0], "sumElapsedDuration fallback when no timestamps"
    assert s[1][4] == 3.2, "directSpeed fallback when no grade-adjusted speed"


# ──────────────────────────────────────────────────────────────────────────────
# 2.2 best efforts
# ──────────────────────────────────────────────────────────────────────────────
def test_fastest_window_finds_the_fast_segment():
    # 3 m/s cruise with a 250 s surge at 4 m/s (exactly 1 km) in the middle.
    surge_start = 600
    samples = []
    t, d = 0, 0.0
    while t <= 1600:
        speed = 4.0 if surge_start <= t < surge_start + 250 else 3.0
        samples.append((t, d, 135, 170, speed))
        d += speed
        t += 1
    det = _detail(samples)
    s = im.read_stream(det)
    best = im.fastest_window_s(s, 1000.0)
    assert best is not None and abs(best - 250.0) <= 1.0, \
        f"fastest 1k must be the surge (~250 s), got {best}"


def test_pause_counts_against_the_effort():
    # 1200 m at 4 m/s with a 60 s recording pause at the 600 m mark: every
    # possible 1 km window spans the pause, so best = 250 + 60 s of wall clock.
    first = _steady(150, 4.0)                                   # 0–600 m
    second = _steady(150, 4.0, t_start=210, d_start=600.0)      # after +60 s gap
    s = im.read_stream(_detail(first + second))
    best = im.fastest_window_s(s, 1000.0)
    assert best is not None and abs(best - 310.0) <= 1.0, \
        f"elapsed time must include the pause (expect ~310 s), got {best}"


def test_pause_before_window_does_not_count():
    # Pause at 100 m, then 1000 m of running: the fastest 1k starts after the
    # pause and must NOT include it.
    first = _steady(25, 4.0)                                    # 0–100 m
    second = _steady(275, 4.0, t_start=85, d_start=100.0)       # +60 s gap, → 1200 m
    s = im.read_stream(_detail(first + second))
    best = im.fastest_window_s(s, 1000.0)
    assert best is not None and abs(best - 250.0) <= 1.0, \
        f"a pause before the window must not count, got {best}"


def test_edge_interpolation_between_samples():
    # 5 s sampling at 4.7 m/s: 1000 m never lands on a sample boundary.
    s = im.read_stream(_detail(_steady(300, 4.7, step=5)))
    best = im.fastest_window_s(s, 1000.0)
    expected = 1000.0 / 4.7  # 212.77
    assert best is not None and abs(best - expected) <= 0.5, \
        f"interpolated edge should give ~{expected:.1f}, got {best}"


def test_short_run_yields_nulls():
    s = im.read_stream(_detail(_steady(1000, 4.0)))  # 4 km
    eff = im.best_efforts(s)
    assert eff["best_1k_s"] is not None and eff["best_mile_s"] is not None
    assert eff["best_5k_s"] is None and eff["best_10k_s"] is None and eff["best_half_s"] is None, \
        "distances longer than the run must be NULL, never extrapolated"


# ──────────────────────────────────────────────────────────────────────────────
# 2.3 band aggregates
# ──────────────────────────────────────────────────────────────────────────────
def test_band_sums_warmup_and_floor_exclusions():
    # 20 min at 2.2 m/s (pace ~455 s/km, in band), HR 135 (in band), cad 170.
    run = _steady(1200, 2.2)
    # then 5 min walking at 1.0 m/s — below the floor, must weigh nothing
    walk = _steady(300, 1.0, t_start=1201, d_start=2643.0)
    agg = im.band_aggregates(im.read_stream(_detail(run + walk)))
    # warm-up excludes the first 480 s → 720 s of in-band running remain
    assert abs(agg["refhr_time_s"] - 720.0) <= 2, agg
    assert abs(agg["refhr_dist_m"] - 720.0 * 2.2) <= 6, agg
    assert abs(agg["refpace_time_s"] - 720.0) <= 2, agg
    assert abs(agg["refpace_cadence_x_time"] - 720.0 * 170) <= 400, agg


def test_band_sums_out_of_band_excluded():
    # HR 160 (out of band) and pace 250 s/km (4.0 m/s, out of pace band):
    # both pools must stay empty.
    agg = im.band_aggregates(im.read_stream(_detail(_steady(1200, 4.0, hr=160))))
    assert agg["refhr_time_s"] == 0.0 and agg["refpace_time_s"] == 0.0, agg


def test_band_sums_recording_gap_weighs_nothing():
    first = _steady(600, 3.0)
    second = _steady(600, 3.0, t_start=900, d_start=1800.0)  # 300 s gap
    agg = im.band_aggregates(im.read_stream(_detail(first + second)))
    # in-band time: (600−480) after warm-up + 600 in the second block = 720,
    # the 300 s pause itself contributing nothing
    assert abs(agg["refhr_time_s"] - 720.0) <= 2, agg


def test_band_sums_none_hr_or_cadence_skipped():
    det = _detail([(t, 3.0 * t, None, None, 3.0) for t in range(0, 1201)])
    agg = im.band_aggregates(im.read_stream(det))
    assert agg["refhr_time_s"] == 0.0 and agg["refpace_time_s"] == 0.0, \
        "samples without HR/cadence must not enter the pools"


def test_per_run_display_values_consistent_with_aggregates():
    # 20 min at 2.2 m/s: in both bands after the warm-up cutoff — the stored
    # display values must be exactly the stored aggregates' quotients
    # (chart-drill 1.2: derivation lives here, the server serves verbatim).
    agg = im.band_aggregates(im.read_stream(_detail(_steady(1200, 2.2))))
    assert agg["refhr_pace_s_per_km"] == round(
        agg["refhr_time_s"] / (agg["refhr_dist_m"] / 1000.0), 1), \
        "per-run pace is exactly reproducible from the row's own aggregates"
    assert agg["refpace_cadence_spm"] == round(
        agg["refpace_cadence_x_time"] / agg["refpace_time_s"], 1), \
        "per-run cadence is exactly reproducible from the row's own aggregates"


def test_per_run_display_values_null_when_out_of_band():
    # HR 160 / pace 250 s/km: zero in-band time in both pools — the display
    # values must be NULL, never zero, so "no evidence" ≠ "slow" (chart-drill 1.2)
    agg = im.band_aggregates(im.read_stream(_detail(_steady(1200, 4.0, hr=160))))
    assert agg["refhr_time_s"] == 0.0 and agg["refpace_time_s"] == 0.0
    assert agg["refhr_pace_s_per_km"] is None
    assert agg["refpace_cadence_spm"] is None


# ──────────────────────────────────────────────────────────────────────────────
# 2.4 extraction driver
# ──────────────────────────────────────────────────────────────────────────────
def _seed_run(conn, aid, detail, start="2026-07-01 08:00:00", type_key="running"):
    arch.upsert_activities(conn, [{
        "activityId": aid, "activityName": f"run {aid}", "startTimeLocal": start,
        "activityType": {"typeKey": type_key}, "distance": 5000.0, "duration": 1800.0,
    }])
    if detail is not None:
        arch.write_detail(conn, aid, detail)


def test_extract_run_metrics_driver():
    conn = arch.open_archive(_tmp())
    _seed_run(conn, 1, _detail(_steady(1500, 4.0)))                       # 6 km outdoor
    _seed_run(conn, 2, _detail(_steady(1200, 3.0)),
              start="2026-07-02 08:00:00", type_key="treadmill_running")
    _seed_run(conn, 3, None, start="2026-07-03 08:00:00")                 # no detail yet
    _seed_run(conn, 4, {"metricDescriptors": "corrupt"},                  # unparseable
              start="2026-07-04 08:00:00")

    n = im.extract_run_metrics(conn)
    assert n == 3, "runs 1, 2 and 4 extracted; detail-less run 3 skipped"

    rows = {r[0]: r for r in conn.execute(
        "SELECT activity_id, metrics_version, is_treadmill, best_1k_s, best_5k_s,"
        " refhr_time_s FROM run_metrics").fetchall()}
    assert set(rows) == {1, 2, 4}
    assert rows[1][1] == im.METRICS_VERSION and rows[1][2] == 0
    assert abs(rows[1][3] - 250.0) <= 1.0 and rows[1][4] is not None
    assert rows[2][2] == 1, "treadmill flagged from type_key"
    assert rows[4][3] is None and rows[4][5] is None, \
        "corrupt stream → empty row banked (no nightly retry loop)"

    assert im.extract_run_metrics(conn) == 0, "second pass finds nothing to do"
    conn.close()


def test_version_bump_recomputes():
    conn = arch.open_archive(_tmp())
    _seed_run(conn, 1, _detail(_steady(1500, 4.0)))
    assert im.extract_run_metrics(conn) == 1
    orig_version = im.METRICS_VERSION
    im.METRICS_VERSION = orig_version + 1
    try:
        assert im.extract_run_metrics(conn) == 1, "stale row counts as missing"
        rows = conn.execute("SELECT metrics_version FROM run_metrics").fetchall()
        assert rows == [(orig_version + 1,)], "stale row replaced, not duplicated"
    finally:
        im.METRICS_VERSION = orig_version
    conn.close()


def test_extraction_stores_per_run_display_columns():
    # chart-drill 1.1/1.2: the columns exist in the schema, the extraction
    # writes them, and a version bump self-heals them onto a pre-bump row.
    conn = arch.open_archive(_tmp())
    # in-band run (2.2 m/s ⇒ pace ~455 s/km, HR 135) + an out-of-band run
    _seed_run(conn, 1, _detail(_steady(1200, 2.2)))
    _seed_run(conn, 2, _detail(_steady(1200, 4.0, hr=160)),
              start="2026-07-02 08:00:00")
    assert im.extract_run_metrics(conn) == 2
    rows = {r[0]: r for r in conn.execute(
        "SELECT activity_id, refhr_pace_s_per_km, refpace_cadence_spm,"
        " refhr_time_s, refhr_dist_m FROM run_metrics")}
    pace, spm, t, d = rows[1][1:]
    assert pace == round(t / (d / 1000.0), 1), \
        "stored per-run pace = stored aggregates' quotient, exactly"
    assert spm is not None and abs(spm - 170) <= 1, "cadence 85 doubled → 170 spm"
    assert rows[2][1] is None and rows[2][2] is None, \
        "out-of-band run stores NULL display values, never zero"

    # a row extracted at the PREVIOUS version has no display values; the bump
    # (already applied in this checkout) recomputes it with them on next sync
    conn.execute("UPDATE run_metrics SET metrics_version = ?,"
                 " refhr_pace_s_per_km = NULL, refpace_cadence_spm = NULL"
                 " WHERE activity_id = 1", (im.METRICS_VERSION - 1,))
    conn.commit()
    assert im.extract_run_metrics(conn) == 1, "pre-bump row self-heals"
    healed = conn.execute(
        "SELECT metrics_version, refhr_pace_s_per_km FROM run_metrics"
        " WHERE activity_id = 1").fetchone()
    assert healed[0] == im.METRICS_VERSION and healed[1] is not None
    conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# 4. series assembly — seeded run_metrics / race_predictions rows, no streams
# ──────────────────────────────────────────────────────────────────────────────
import datetime as dtm

TODAY = dtm.date(2026, 7, 5)


def _seed_metrics(conn, aid, start, *, treadmill=0, version=None, **cols):
    row = {
        "activity_id": aid, "metrics_version": version or im.METRICS_VERSION,
        "start_time_local": start, "is_treadmill": treadmill,
        "best_1k_s": None, "best_mile_s": None, "best_5k_s": None,
        "best_10k_s": None, "best_half_s": None,
        "refhr_time_s": 0.0, "refhr_dist_m": 0.0,
        "refpace_time_s": 0.0, "refpace_cadence_x_time": 0.0,
    }
    row.update(cols)
    arch.upsert_run_metrics(conn, row)


def test_monthly_series_sums_and_null_months():
    conn = arch.open_archive(_tmp())
    # 2026-04: two runs pooling 20 min in both bands
    _seed_metrics(conn, 1, "2026-04-03 08:00:00",
                  refhr_time_s=700, refhr_dist_m=1540.0,       # 2.2 m/s
                  refpace_time_s=700, refpace_cadence_x_time=700 * 168)
    _seed_metrics(conn, 2, "2026-04-20 08:00:00",
                  refhr_time_s=500, refhr_dist_m=1150.0,       # 2.3 m/s
                  refpace_time_s=500, refpace_cadence_x_time=500 * 172)
    # 2026-06: below the 10-minute threshold → null point, minutes still shown
    _seed_metrics(conn, 3, "2026-06-10 08:00:00",
                  refhr_time_s=300, refhr_dist_m=690.0,
                  refpace_time_s=300, refpace_cadence_x_time=300 * 170)

    eff, cad = im.monthly_series(conn, TODAY)
    assert [m["month"] for m in eff] == ["2026-04", "2026-05", "2026-06", "2026-07"], \
        "continuous months from first row to today"
    # pooled: 1200 s over 2690 m → 446 s/km
    assert eff[0]["paceSecPerKm"] == 446 and eff[0]["inBandMin"] == 20
    assert eff[1]["paceSecPerKm"] is None and eff[1]["inBandMin"] == 0, "no-run month is a gap"
    assert eff[2]["paceSecPerKm"] is None and eff[2]["inBandMin"] == 5, \
        "sparse month is a gap, not a noisy point"
    # cadence time-weighted: (700×168 + 500×172) / 1200 ≈ 170
    assert cad[0]["spm"] == 170 and cad[2]["spm"] is None
    conn.close()


def test_stale_version_rows_do_not_pollute_series():
    conn = arch.open_archive(_tmp())
    _seed_metrics(conn, 1, "2026-04-03 08:00:00", version=im.METRICS_VERSION + 7,
                  refhr_time_s=8000, refhr_dist_m=20000.0)
    eff, cad = im.monthly_series(conn, TODAY)
    assert eff == [] and cad == [], "other-version rows are invisible"
    conn.close()


def test_records_progression_and_treadmill_exclusion():
    conn = arch.open_archive(_tmp())
    _seed_metrics(conn, 1, "2026-01-05 08:00:00", best_5k_s=1700.0)   # baseline
    _seed_metrics(conn, 2, "2026-02-10 08:00:00", best_5k_s=1650.0)   # record falls
    _seed_metrics(conn, 3, "2026-03-01 08:00:00", best_5k_s=1690.0)   # slower: nothing
    _seed_metrics(conn, 4, "2026-03-20 08:00:00", best_5k_s=1600.0,   # treadmill best:
                  treadmill=1,                                        # no record,
                  refhr_time_s=900, refhr_dist_m=2000.0)              # trends still fed
    _seed_metrics(conn, 5, "2026-04-05 08:00:00", best_5k_s=1620.0)   # record falls

    feed = im.records_feed(conn)
    assert feed == [
        {"date": "2026-04-05", "distance": "5k", "oldSec": 1650, "newSec": 1620},
        {"date": "2026-02-10", "distance": "5k", "oldSec": 1700, "newSec": 1650},
    ], "newest first; baseline and treadmill runs never appear"

    best = im.best_effort_table(conn)
    assert best["fiveK"] == {"sec": 1620, "date": "2026-04-05", "activityId": 5}, \
        "treadmill 1600 must not hold the record"
    assert best["half"] is None, "no half effort yet → null"

    last90 = im.best_effort_table(conn, since=(TODAY - dtm.timedelta(days=90)).isoformat())
    assert last90["fiveK"] is None, \
        "the 2026-04-05 best is 91 days old — outside the rolling 90d window"

    eff, _cad = im.monthly_series(conn, TODAY)
    march = next(m for m in eff if m["month"] == "2026-03")
    assert march["inBandMin"] == 15, "treadmill run still feeds the trend pools"
    conn.close()


def test_weekly_trajectory_riegel_vs_garmin():
    conn = arch.open_archive(_tmp())
    # one qualifying 10k effort; a faster one five weeks later
    _seed_metrics(conn, 1, "2026-05-03 09:00:00", best_10k_s=3600.0)   # Sunday W18
    _seed_metrics(conn, 2, "2026-06-07 09:00:00", best_10k_s=3480.0)   # Sunday W23
    arch.upsert_race_prediction(conn, "2026-05-20", {"half_s": 7300.0}, {}, "backfill")
    arch.upsert_race_prediction(conn, "2026-06-25", {"half_s": 7255.0}, {}, "sync")

    weekly = im.weekly_trajectory(conn, TODAY)
    assert weekly[0]["week"] == "2026-W18" and weekly[-1]["week"] == "2026-W27"
    assert len(weekly) == 10

    factor = (21.0975 / 10.0) ** im.RIEGEL_EXPONENT
    assert weekly[0]["riegelSec"] == round(3600 * factor), "anchored on the only effort"
    assert weekly[0]["garminSec"] is None, "no banked prediction yet"
    assert weekly[2]["garminSec"] is None, "week ends 05-17, before the first banked row"
    assert weekly[3]["garminSec"] == 7300, "last banked value on or before the week end"
    assert weekly[5]["riegelSec"] == round(3480 * factor), "faster effort takes over"
    assert weekly[-1]["garminSec"] == 7255
    # chart-drill 1.3: each Riegel week names the run that demonstrated it
    assert weekly[0]["anchorId"] == 1, "week anchored on effort 1 carries its id"
    assert weekly[5]["anchorId"] == 2, "the faster effort's id takes over with it"
    conn.close()


def test_riegel_null_over_substitution_and_aging_out():
    conn = arch.open_archive(_tmp())
    # a 10k effort in January and a 1k-only run in June: after 84 days the
    # January anchor ages out and June must be NULL, not estimated from the 1k
    _seed_metrics(conn, 1, "2026-01-04 09:00:00", best_10k_s=3600.0)
    _seed_metrics(conn, 2, "2026-06-10 09:00:00", best_1k_s=290.0)
    weekly = im.weekly_trajectory(conn, TODAY)
    assert weekly[0]["riegelSec"] is not None
    assert weekly[-1]["riegelSec"] is None, \
        "no 10k in the trailing 84 days → null, never a 1k-based estimate"
    # chart-drill 1.3: a null-Riegel week carries NO anchor key at all —
    # older consumers and validation must never see anchorId: null
    assert "anchorId" not in weekly[-1], "null week omits anchorId entirely"
    assert weekly[0]["anchorId"] == 1
    # treadmill 10k must not anchor either
    _seed_metrics(conn, 3, "2026-06-28 09:00:00", best_10k_s=3400.0, treadmill=1)
    weekly = im.weekly_trajectory(conn, TODAY)
    assert weekly[-1]["riegelSec"] is None, "treadmill efforts never anchor Riegel"
    conn.close()


def test_trend_verdict_wording():
    def wk(*vals):
        return [{"week": f"2026-W{20 + i:02d}", "riegelSec": v, "garminSec": None}
                for i, v in enumerate(vals)]
    assert im.trend_verdict(wk(7600, 7592, 7584, 7576)) == "closing ≈8s/wk"
    assert im.trend_verdict(wk(7500, 7512, 7524, 7536)) == "opening ≈12s/wk"
    assert im.trend_verdict(wk(7500, 7501, 7500, 7499)) == "flat"
    assert im.trend_verdict(wk(7500, None, None, 7500)) == "", "too few points → no verdict"
    assert im.trend_verdict([]) == ""


def test_assemble_insights_shape_and_no_partials():
    conn = arch.open_archive(_tmp())
    try:
        im.assemble_insights(conn, TODAY)
        raise AssertionError("empty archive must raise, not emit a partial block")
    except ValueError:
        pass
    _seed_metrics(conn, 1, "2026-05-03 09:00:00", best_10k_s=3600.0, best_1k_s=300.0,
                  refhr_time_s=700, refhr_dist_m=1540.0,
                  refpace_time_s=700, refpace_cadence_x_time=700 * 168)
    ins = im.assemble_insights(conn, TODAY)
    assert ins["metricsVersion"] == im.METRICS_VERSION
    assert ins["efficiency"]["refHrBand"] == list(im.REF_HR_BAND)
    assert ins["cadence"]["refPaceBand"] == list(im.REF_PACE_BAND)
    assert ins["bestEfforts"]["allTime"]["tenK"]["sec"] == 3600
    assert ins["bestEfforts"]["byYear"]["2026"]["tenK"]["activityId"] == 1
    assert ins["recordsFeed"] == []
    assert ins["trajectory"]["goalSec"] == 7199
    assert ins["trajectory"]["weekly"][0]["riegelSec"] is not None
    assert ins["yoy"] == {}, "no archived activities in this fixture → empty yoy"
    conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# progress-views 3.1/3.2 — by-year best efforts + year-over-year aggregates
# ──────────────────────────────────────────────────────────────────────────────
def test_best_efforts_by_year_slicing_and_treadmill_exclusion():
    conn = arch.open_archive(_tmp())
    _seed_metrics(conn, 1, "2024-06-01 08:00:00", best_1k_s=305.0)
    _seed_metrics(conn, 2, "2025-03-01 08:00:00", best_1k_s=298.0, best_5k_s=1700.0)
    _seed_metrics(conn, 3, "2025-09-01 08:00:00", best_1k_s=290.0, treadmill=1)
    _seed_metrics(conn, 4, "2026-04-05 08:00:00", best_5k_s=1650.0)

    by = im.best_efforts_by_year(conn)
    assert sorted(by) == ["2024", "2025", "2026"], "one table per year with outdoor runs"
    assert by["2024"]["oneK"] == {"sec": 305, "date": "2024-06-01", "activityId": 1}
    assert by["2024"]["fiveK"] is None, "distance never covered in a year → null"
    assert by["2025"]["oneK"] == {"sec": 298, "date": "2025-03-01", "activityId": 2}, \
        "the treadmill 290 must not hold the year record"
    assert by["2026"]["oneK"] is None
    assert by["2026"]["fiveK"]["activityId"] == 4, "entries carry the click-through id"
    conn.close()


def test_yoy_series_sums_and_honesty():
    conn = arch.open_archive(_tmp())
    arch.upsert_activities(conn, [
        {"activityId": 1, "startTimeLocal": "2025-01-05 08:00:00",
         "activityType": {"typeKey": "running"}, "distance": 10000.0, "duration": 3000.0},
        {"activityId": 2, "startTimeLocal": "2025-01-20 08:00:00",
         "activityType": {"typeKey": "treadmill_running"}, "distance": 5000.0,
         "duration": 1500.0},
        {"activityId": 3, "startTimeLocal": "2025-03-10 08:00:00",
         "activityType": {"typeKey": "strength_training"}, "distance": 0.0,
         "duration": 3600.0},
        {"activityId": 4, "startTimeLocal": "2026-02-14 08:00:00",
         "activityType": {"typeKey": "running"}, "distance": 21100.0, "duration": 7200.0},
    ])
    yoy = im.yoy_series(conn, TODAY)
    assert sorted(yoy) == ["2025", "2026"]
    assert len(yoy["2025"]) == 12, "a past year carries all 12 months"
    assert len(yoy["2026"]) == 7, "the current year carries only elapsed months"
    assert yoy["2025"][0] == {"month": 1, "km": 15.0, "runs": 2, "paceSecPerKm": 300}, \
        "sums match the archive; treadmill counts toward volume (records ≠ volume)"
    assert yoy["2025"][2] == {"month": 3, "km": 0.0, "runs": 0, "paceSecPerKm": None}, \
        "a strength session is not a run; an empty month is zero/zero/null"
    assert yoy["2026"][1] == {"month": 2, "km": 21.1, "runs": 1,
                              "paceSecPerKm": round(7200 / 21.1)}
    assert im.yoy_series(arch.open_archive(_tmp()), TODAY) == {}, \
        "an archive without runs → empty yoy"
    conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# 5. predictor banking + backfill — mocked client, no network
# ──────────────────────────────────────────────────────────────────────────────
class _PredClient:
    """get_race_predictions mock: one doc per window edge, or a hard failure."""

    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def get_race_predictions(self, startdate=None, enddate=None, _type=None):
        self.calls.append((startdate, enddate, _type))
        if self.fail:
            raise RuntimeError("history endpoint gone")
        return [
            {"calendarDate": startdate, "time5K": 1500.0, "time10K": 3200.0,
             "timeHalfMarathon": 7300.0, "timeMarathon": 15600.0},
            {"calendarDate": enddate, "time5K": 1490.0, "timeHalfMarathon": 7280.0},
        ]


def test_bank_prediction_and_same_day_refresh():
    conn = arch.open_archive(_tmp())
    doc = {"calendarDate": "2026-07-05", "time5K": 1500.0, "time10K": 3200.0,
           "timeHalfMarathon": 7255.0, "timeMarathon": 15600.0}
    assert im.bank_prediction(conn, doc) is True
    assert im.bank_prediction(conn, [dict(doc, timeHalfMarathon=7240.0)]) is True, \
        "list-shaped documents are unwrapped"
    rows = conn.execute(
        "SELECT date, time_5k_s, half_s, source FROM race_predictions").fetchall()
    assert rows == [("2026-07-05", 1500.0, 7240.0, "sync")], "same-day refresh, one row"
    assert im.bank_prediction(conn, None) is False and im.bank_prediction(conn, []) is False
    conn.close()


def test_backfill_walks_one_year_windows():
    conn = arch.open_archive(_tmp())
    client = _PredClient()
    banked = im.backfill_predictions(conn, client, "2024-05-12 09:00:00", today=TODAY)
    assert client.calls == [
        ("2025-07-06", "2026-07-05", "daily"),
        ("2024-07-06", "2025-07-05", "daily"),
        ("2024-05-12", "2024-07-05", "daily"),
    ], "newest-first, contiguous, non-overlapping ≤1-year windows to the account start"
    assert banked == 6
    n, earliest, latest = conn.execute(
        "SELECT COUNT(*), MIN(date), MAX(date) FROM race_predictions").fetchone()
    assert (n, earliest, latest) == (6, "2024-05-12", "2026-07-05")
    assert conn.execute(
        "SELECT COUNT(*) FROM race_predictions WHERE source = 'backfill'"
    ).fetchone()[0] == 6
    conn.close()


def test_backfill_failure_is_soft_and_banks_what_it_can():
    conn = arch.open_archive(_tmp())
    banked = im.backfill_predictions(conn, _PredClient(fail=True),
                                     "2024-05-12", today=TODAY)
    assert banked == 0, "dead endpoint → nothing banked, no exception"
    assert arch.race_predictions_empty(conn) is True
    # bank-on-sync still works afterwards — the line builds forward from today
    assert im.bank_prediction(conn, {"calendarDate": "2026-07-05",
                                     "timeHalfMarathon": 7255.0}) is True
    assert arch.race_predictions_empty(conn) is False
    conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# 7. contract validation — validate_data.validate_insights
# ──────────────────────────────────────────────────────────────────────────────
vd = _load("validate_data")


def _valid_block():
    conn = arch.open_archive(_tmp())
    _seed_metrics(conn, 1, "2026-05-03 09:00:00", best_10k_s=3600.0, best_5k_s=1700.0,
                  refhr_time_s=700, refhr_dist_m=1540.0,
                  refpace_time_s=700, refpace_cadence_x_time=700 * 168)
    _seed_metrics(conn, 2, "2026-06-07 09:00:00", best_5k_s=1650.0)
    arch.upsert_race_prediction(conn, "2026-06-25", {"half_s": 7255.0}, {}, "sync")
    ins = im.assemble_insights(conn, TODAY)
    conn.close()
    return ins


def test_validate_pre_engine_file_passes():
    errors = vd.validate({"history": {}, "recentRuns": [], "block": [{}],
                          "weekPlan": [], "heatmapKm": [0.0] * 365})
    assert not any(m.startswith("insights") for m in errors), \
        "a file without an insights block must raise no insights errors"


def test_validate_well_formed_block_passes():
    e = []
    vd.validate_insights(_valid_block(), e)
    assert e == [], f"the engine's own output must validate: {e}"


def test_validate_truncated_block_names_the_member():
    ins = _valid_block()
    del ins["bestEfforts"]["allTime"]["tenK"]
    ins["efficiency"]["monthly"][0]["paceSecPerKm"] = "391"
    ins["trajectory"]["weekly"][0]["riegelSec"] = "fast"
    e = []
    vd.validate_insights(ins, e)
    assert any("bestEfforts.allTime missing 'tenK'" in m for m in e), e
    assert any("paceSecPerKm must be numeric or null" in m for m in e), e
    assert any("trajectory.weekly" in m for m in e), e


def test_validate_pre_3a_block_stays_valid():
    ins = _valid_block()
    del ins["bestEfforts"]["byYear"]
    del ins["yoy"]
    e = []
    vd.validate_insights(ins, e)
    assert e == [], f"a pre-3a block (no byYear/yoy) must stay valid: {e}"


def test_validate_anchor_id_optional_and_typed():
    # a pre-anchor trajectory (no anchorId anywhere) stays valid
    ins = _valid_block()
    for w in ins["trajectory"]["weekly"]:
        w.pop("anchorId", None)
    e = []
    vd.validate_insights(ins, e)
    assert e == [], f"a trajectory without anchorId must stay valid: {e}"

    # a present anchorId must be numeric — a string is named and rejected
    ins = _valid_block()
    ins["trajectory"]["weekly"][0]["anchorId"] = "19790873891"
    e = []
    vd.validate_insights(ins, e)
    assert any("anchorId" in m for m in e), \
        f"a non-numeric anchorId must fail naming the member: {e}"


def test_validate_malformed_byyear_and_yoy_named():
    ins = _valid_block()
    ins["bestEfforts"]["byYear"] = {"2026": {
        "oneK": {"sec": 290, "date": "2026-05-03"},   # activityId missing
        "mile": None, "fiveK": None, "tenK": None, "half": None}}
    e = []
    vd.validate_insights(ins, e)
    assert any("byYear.2026.oneK must carry activityId" in m for m in e), e

    ins = _valid_block()
    ins["bestEfforts"]["byYear"] = "2026"
    e = []
    vd.validate_insights(ins, e)
    assert any("byYear must be an object" in m for m in e), e

    ins = _valid_block()
    ins["yoy"] = {"2026": [{"month": 13, "km": 1.0, "runs": 1, "paceSecPerKm": None}]}
    e = []
    vd.validate_insights(ins, e)
    assert any("insights.yoy.2026 month 13" in m for m in e), e

    ins = _valid_block()
    ins["yoy"] = {"26": [{"month": 1, "km": 1.0, "runs": 1, "paceSecPerKm": None}]}
    e = []
    vd.validate_insights(ins, e)
    assert any("insights.yoy key '26' must be 'YYYY'" in m for m in e), e

    ins = _valid_block()
    ins["yoy"] = "not-a-dict"
    e = []
    vd.validate_insights(ins, e)
    assert any("insights.yoy must be an object" in m for m in e), e


# ──────────────────────────────────────────────────────────────────────────────
# 2.6 oracle — cross-validate against Garmin's fastestSplit_* on the REAL
# archive (skips when the local dress-rehearsal db is absent)
# ──────────────────────────────────────────────────────────────────────────────
ORACLE_MAP = {"fastestSplit_1000": 1000.0, "fastestSplit_1609": 1609.344,
              "fastestSplit_5000": 5000.0, "fastestSplit_10000": 10000.0}
ORACLE_TOLERANCE = 0.03   # ours may read slightly slower (elapsed vs on-device)
ORACLE_PASS_FRACTION = 0.90


def test_oracle_against_real_archive():
    db = REPO / "activity-archive.db"
    if not db.exists():
        print("   (skipped — no local activity-archive.db)")
        return
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    cur = conn.execute(
        "SELECT activity_id, summary_json, detail_json FROM activities "
        "WHERE detail_json IS NOT NULL AND type_key LIKE '%run%' "
        "AND type_key NOT LIKE '%cycling%'")
    checked, within, worst = 0, 0, (0.0, None, None)
    for aid, summary_json, detail_json in cur:
        summary = json.loads(summary_json)
        oracle = {k: summary.get(k) for k in ORACLE_MAP if summary.get(k)}
        if not oracle:
            continue
        samples = im.read_stream(json.loads(detail_json))
        for key, target in ORACLE_MAP.items():
            garmin = oracle.get(key)
            if not garmin:
                continue
            ours = im.fastest_window_s(samples, target)
            if ours is None:
                continue   # stream shorter than the split (rare truncation)
            rel = (ours - garmin) / garmin
            checked += 1
            if abs(rel) <= ORACLE_TOLERANCE:
                within += 1
            if abs(rel) > abs(worst[0]):
                worst = (rel, aid, key)
    conn.close()
    assert checked > 100, f"expected a real archive with >100 oracle values, got {checked}"
    frac = within / checked
    print(f"   oracle: {within}/{checked} within ±{ORACLE_TOLERANCE:.0%} "
          f"(worst {worst[0]:+.1%} on {worst[2]} of {worst[1]})")
    assert frac >= ORACLE_PASS_FRACTION, \
        f"only {frac:.0%} of best efforts within ±{ORACLE_TOLERANCE:.0%} of Garmin's splits"


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_"):
            _fn()
            print("ok", _name)
    print("ALL PASS")
