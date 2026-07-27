#!/usr/bin/env python3
"""Tests for the interval-lens engine (add-interval-lens).

Synthetic streams are built from (duration, speed) spans so every expected
boundary is known exactly; the real-archive ground truth lives in Task 15.
"""
from __future__ import annotations

import interval_lens as il


def make_streams(spans, hr=150, gap=False):
    """spans: [(duration_s, mps)] → columnar streams at 1 Hz, like the archive's."""
    t, d, v, hrs = [], [], [], []
    clock, dist = 0, 0.0
    for dur, mps in spans:
        for _ in range(dur):
            t.append(clock)
            d.append(round(dist))
            v.append(mps)
            hrs.append(hr)
            clock += 1
            dist += mps
    out = {"t": t, "d": d, "v": v, "hr": hrs}
    if gap:
        out["gap"] = list(v)
    return out


def test_speed_series_is_one_hz_over_the_span():
    s = make_streams([(100, 3.0)])
    assert len(il.speed_series(s)) == 100


def test_speed_series_prefers_grade_adjusted():
    """D5: GAP wins over raw speed — on hills it is the honest effort signal."""
    s = make_streams([(100, 3.0)], gap=True)
    s["gap"] = [4.0] * 100
    assert il.speed_series(s)[50] == 4.0


def test_speed_series_holds_across_sample_gaps():
    """Garmin samples every ~2 s; the grid must hold the last reading, not hole.
    The span must clear MIN_SPAN_S or the guard returns [] and this proves
    nothing — `all()` over an empty list is vacuously true."""
    n = 31                                   # 0,2,…,60 → span 60, clears the guard
    s = {"t": [i * 2 for i in range(n)],
         "d": [round(i * 2 * 3.0) for i in range(n)],
         "v": [3.0] * n}
    out = il.speed_series(s)
    assert len(out) == 61                    # one entry per second, endpoint included
    assert all(v == 3.0 for v in out)        # every in-between second was held


def test_standing_still_is_none_not_zero():
    """A pause is absent data, not a very slow rep — it must not join a class."""
    s = make_streams([(30, 3.0), (30, 0.0), (30, 3.0)])
    assert il.speed_series(s)[45] is None


def test_short_activity_yields_nothing():
    assert il.speed_series(make_streams([(30, 3.0)])) == []


def test_smooth_kills_a_single_sample_spike():
    series = [3.0] * 41
    series[20] = 9.0
    assert il.smooth(series)[20] == 3.0


def test_smooth_preserves_a_real_edge():
    """A 15 s median must not blur a 30 s rep into its recovery."""
    series = [2.5] * 60 + [4.0] * 60
    out = il.smooth(series)
    assert out[30] == 2.5 and out[90] == 4.0


def test_distance_fn_reads_cumulative_metres():
    at = il.distance_fn(make_streams([(100, 3.0)]))
    assert at(100) - at(0) == 297  # 99 whole-second steps of 3 m, rounded


def test_split_classes_finds_two_speeds():
    s = il.smooth(il.speed_series(make_streams([(300, 2.5), (300, 4.0)])))
    lo, hi, sep = il.split_classes(s)
    assert 2.4 < lo < 2.7
    assert 3.8 < hi < 4.1


def test_near_steady_run_falls_below_the_separation_floor():
    """The guard that keeps an ordinary easy run from reading as a workout.
    Real variance (so 2-means actually partitions and we reach the threshold
    comparison), but nowhere near a work/rest gap."""
    spans = [(1, 3.0 + (0.06 if i % 2 else -0.06)) for i in range(1800)]
    s = il.smooth(il.speed_series(make_streams(spans)))
    classes = il.split_classes(s)
    assert classes is None


def test_a_perfectly_flat_series_cannot_be_partitioned():
    """The degenerate bailout: with zero variation there are not two classes to
    find. Distinct from the separation floor above — this returns at the
    empty-partition guard, before any threshold is compared."""
    assert il.split_classes([3.0] * 600) is None


def test_gentle_drift_is_not_structure():
    """A run that drifts 5 % over an hour is not an interval session."""
    spans = [(600, 3.0), (600, 2.95), (600, 2.9)]
    s = il.smooth(il.speed_series(make_streams(spans)))
    assert il.split_classes(s) is None


def test_separation_is_the_relative_speed_gap():
    s = il.smooth(il.speed_series(make_streams([(300, 2.0), (300, 4.0)])))
    _, _, sep = il.split_classes(s)
    assert 0.45 < sep < 0.55  # (4 − 2) / 4
