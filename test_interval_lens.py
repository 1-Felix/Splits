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


def _bouts(spans):
    s = make_streams(spans)
    series = il.smooth(il.speed_series(s))
    classes = il.split_classes(series)
    assert classes is not None, "fixture should be structured"
    lo, hi, _ = classes
    return il.find_bouts(series, il.distance_fn(s), lo, hi)


def test_finds_five_reps():
    spans = [(600, 2.6)] + [(250, 4.0), (60, 2.2)] * 5 + [(300, 2.6)]
    assert len(_bouts(spans)) == 5


def test_rep_boundaries_land_near_the_truth():
    spans = [(600, 2.6), (250, 4.0), (60, 2.2), (250, 4.0), (300, 2.6)]
    first = _bouts(spans)[0]
    assert abs(first[0] - 600) <= 10
    assert abs(first[1] - 850) <= 10


def test_chatter_does_not_shred_one_rep():
    """Hysteresis earns its place here: without it, a wobbling rep becomes 3.

    The original i%7 dip-to-3.2 fixture from the brief was vacuous: a period-7,
    single-sample dip is exactly the impulsive noise SMOOTH_WINDOW_S=15's
    rolling median is built to erase (fewer than half the samples in any
    15-wide window are the dip), so it never survives to reach find_bouts —
    the smoothed series is a flat 4.0 throughout, and even a single threshold
    (no entry/exit gap at all) produces the same one bout. This version dips
    to a speed long enough (40 s blocks, so the median preserves it) and
    tuned (3.30 mps) to sit strictly between `leave` and `enter` for this
    lo/hi — above leave, so a real rep never reads as ending, but below
    enter, so a naive single-threshold walk re-triggers on every up-swing and
    fragments the one rep into three.
    """
    wobble = [(40, 4.0), (40, 3.30)] * 3
    spans = [(600, 2.6)] + wobble + [(300, 2.6)]
    assert len(_bouts(spans)) == 1


def test_bouts_shorter_than_the_minimum_are_dropped():
    """A 20 s surge to a traffic light is not a rep."""
    spans = [(600, 2.6), (20, 4.5), (600, 2.6), (250, 4.0), (300, 2.6)]
    assert len(_bouts(spans)) == 1


def test_bouts_closer_than_the_minimum_recovery_merge():
    spans = [(600, 2.6), (200, 4.0), (10, 2.4), (200, 4.0), (300, 2.6)]
    assert len(_bouts(spans)) == 1
