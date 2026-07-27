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
    """Hysteresis earns its place here: without it, a wobbling rep fragments.

    The dip is DERIVED from the live thresholds, not hardcoded: it must sit
    above `leave` (so a real rep never reads as ending) and below `enter` (so
    a naive single-threshold walk re-triggers on the up-swing and fragments
    the rep). A literal here silently rots — ENTER_FRAC/EXIT_FRAC are
    versioned tunables, and a fix-round review caught a hardcoded 3.30 mps
    that sat only 0.025 mps above `leave`: retuning EXIT_FRAC from 0.45 to
    0.47 alone flipped that version of this test.

    Deriving is two passes, not one. Pass 1: a plain two-block PROBE fixture
    (no dip at all) bootstraps a candidate from clean (lo, hi) = (2.6, 4.0).
    Pass 2: the dip's own samples change what split_classes finds on the REAL
    fixture below (here they join the *high* cluster and pull hi down from
    4.0), so the precondition is asserted against the REAL, post-embedding
    (lo, hi) split_classes returns for the actual wobble — not the probe's —
    because that is what find_bouts will actually use. A single short dip
    block flanked by two long peak blocks (rather than several short
    alternations) keeps that perturbation small and the margin wide: this
    construction holds across EXIT_FRAC 0.30-0.58 (verified separately), well
    past the 0.40-0.55 band a future retune is likely to land in.

    Note the brief's original i%7 single-sample dip was vacuous: a period-7
    dip is exactly what SMOOTH_WINDOW_S=15's rolling median erases, so it
    never reached find_bouts and passed with hysteresis on or off.
    """
    peak_s, dip_s = 100, 40
    probe = [(600, 2.6), (2 * peak_s, 4.0), (300, 2.6)]
    lo0, hi0, _ = il.split_classes(il.smooth(il.speed_series(make_streams(probe))))
    enter0 = lo0 + il.ENTER_FRAC * (hi0 - lo0)
    leave0 = lo0 + il.EXIT_FRAC * (hi0 - lo0)
    dip = (enter0 + leave0) / 2

    spans = [(600, 2.6), (peak_s, 4.0), (dip_s, dip), (peak_s, 4.0), (300, 2.6)]
    s = make_streams(spans)
    series = il.smooth(il.speed_series(s))
    classes = il.split_classes(series)
    assert classes is not None, "fixture should be structured"
    lo, hi, _ = classes
    enter, leave = lo + il.ENTER_FRAC * (hi - lo), lo + il.EXIT_FRAC * (hi - lo)
    assert leave < dip < enter, "dip must sit strictly between the REAL thresholds"

    assert len(_bouts(spans)) == 1


def test_bouts_shorter_than_the_minimum_are_dropped():
    """A 20 s surge to a traffic light is not a rep."""
    spans = [(600, 2.6), (20, 4.5), (600, 2.6), (250, 4.0), (300, 2.6)]
    assert len(_bouts(spans)) == 1


def test_bouts_closer_than_the_minimum_recovery_merge():
    spans = [(600, 2.6), (200, 4.0), (10, 2.4), (200, 4.0), (300, 2.6)]
    assert len(_bouts(spans)) == 1


def test_open_bout_auto_closes_at_the_last_sample():
    """An athlete who stops their watch mid-rep must not lose the rep: the
    recording ends while still inside a work bout, with no trailing recovery
    to close it via a `leave` crossing — the walk must auto-close the bout at
    the final sample instead of discarding it."""
    spans = [(600, 2.6), (250, 4.0)]
    assert _bouts(spans) == [(600, 849)]


def _classify(spans, expect_reps=None):
    s = make_streams(spans)
    series = il.smooth(il.speed_series(s))
    dist_at = il.distance_fn(s)
    classes = il.split_classes(series)
    bouts = il.find_bouts(series, dist_at, classes[0], classes[1]) if classes else []
    return il.classify(bouts, series, dist_at, expect_reps), bouts, s


def test_five_reps_classify_as_reps():
    shape, bouts, _ = _classify([(600, 2.6)] + [(250, 4.0), (60, 2.2)] * 5 + [(300, 2.6)])
    assert shape == "reps"
    assert len(bouts) == 5


def test_one_long_bout_is_a_block():
    """2 km wu · 5 km @ threshold · 1 km cd — the classic tempo shape."""
    shape, _, _ = _classify([(700, 2.9), (1100, 3.6), (350, 2.9)])
    assert shape == "block"


def test_two_bouts_are_not_reps_without_a_prior():
    """Two unexplained bouts are more likely noise than a session."""
    shape, _, _ = _classify([(600, 2.6), (250, 4.0), (60, 2.2), (250, 4.0), (300, 2.6)])
    assert shape != "reps"


def test_two_bouts_are_reps_when_a_prior_expects_a_set():
    """A prescribed 2×2 km is a real session (spec D3 / Change 2 fills this)."""
    shape, _, _ = _classify(
        [(600, 2.6), (250, 4.0), (60, 2.2), (250, 4.0), (300, 2.6)], expect_reps=2)
    assert shape == "reps"


def test_steady_run_is_steady():
    shape, bouts, _ = _classify([(2400, 3.0)])
    assert shape == "steady"
    assert bouts == []


def test_progression_is_detected_without_bouts():
    """No discrete work bouts, but a monotone ramp — its own shape (spec D2).

    FIXTURE FIX: the brief's original spans — (2.7, 2.85, 3.0, 3.15, 3.35)
    across 5×400 s blocks — measure at split_classes separation 0.1231, just
    OVER SEPARATION_MIN (0.12). split_classes finds structure, find_bouts
    then reports a single 799 s / ~2597 m bout, and classify reads that as a
    "block", never reaching _is_progression at all — this was verified by
    direct execution, not just arithmetic. The shallower ramp below keeps the
    same shape (5 equal blocks, monotone increase) but measures separation
    0.057 (52 % below the 0.12 gate, so a plausible retune upward doesn't
    resurrect the trap) while the end-to-end gain is 0.10 (100 % over
    PROGRESSION_MIN_GAIN's 0.05) — comfortable margin on both floors so this
    exercises _is_progression itself rather than the structure gate."""
    spans = [(400, 2.8), (400, 2.87), (400, 2.94), (400, 3.01), (400, 3.08)]
    shape, bouts, _ = _classify(spans)
    assert bouts == []
    assert shape == "progression"


def test_label_reads_as_the_session():
    _, bouts, s = _classify([(600, 2.6)] + [(250, 4.0), (60, 2.2)] * 5 + [(300, 2.6)])
    assert il.label_for("reps", bouts, il.distance_fn(s)) == "5×1 km"


def test_unequal_reps_are_varied_not_averaged():
    """The pyramid: labelling this '3×1.3 km' would be a lie."""
    spans = [(600, 2.6), (250, 4.0), (60, 2.2), (500, 4.0), (60, 2.2),
             (250, 4.0), (300, 2.6)]
    _, bouts, s = _classify(spans)
    stats = il.set_stats(bouts, il.smooth(il.speed_series(s)), il.distance_fn(s), s["hr"])
    assert stats["varied"] is True
    assert stats["nominalDistM"] is None


def test_set_stats_report_consistency_and_fade():
    spans = [(600, 2.6)] + [(250, 4.0), (60, 2.2)] * 4 + [(250, 3.6), (300, 2.6)]
    _, bouts, s = _classify(spans)
    stats = il.set_stats(bouts, il.smooth(il.speed_series(s)), il.distance_fn(s), s["hr"])
    assert stats["found"] == 5
    assert stats["prescribed"] is None      # blind detection in Change 1
    assert stats["fadePct"] > 5             # the last rep really was slower
    assert stats["paceCvPct"] > 0


def test_round_dist_names_short_common_distances():
    """200/300/500/1500 m are common prescribed rep distances that the old
    target list omitted entirely, falling through to the wrong register
    ('0.2 km' instead of '200 m') or a misnamed neighbour (1500 -> '1600 m')."""
    assert il._round_dist(200) == "200 m"
    assert il._round_dist(300) == "300 m"
    assert il._round_dist(500) == "500 m"
    assert il._round_dist(1500) == "1500 m"


def test_round_dist_picks_the_nearest_target_not_the_first_match():
    """Ordering bug: a first-match loop over ascending targets finds 800's
    ±12 % band (704-896) before ever comparing to 1000, even where the value
    is relatively closer to 1000.

    FIXTURE NOTE: the crossover between "closer to 800" and "closer to 1000"
    by relative error is at 800*1000/(800+1000) = 888.89 m, verified directly
    against both the old first-match code and the new closest-by-relative-
    error code across the full 860-900 m range. The true divergence zone is
    [889, 896] m. 884 m (as originally suggested) sits BELOW the crossover —
    it is genuinely closer to 800 under both implementations and does not
    exercise the bug at all; 890 m does."""
    assert il._round_dist(960) == "1 km"
    assert il._round_dist(1040) == "1 km"
    assert il._round_dist(890) == "1 km"          # inside 800's band, but closer to 1000


def test_round_dist_890_fails_under_the_old_first_match_logic():
    """Direct regression guard for the ordering bug, independent of the live
    implementation: reproduces the OLD first-match loop verbatim and asserts
    it actually mislabels 890 m as '800 m' — proving the bug was real before
    trusting the fix above."""
    def old_round_dist(metres):
        for target, text in ((400, "400 m"), (600, "600 m"), (800, "800 m"),
                              (1000, "1 km"), (1200, "1.2 km"), (1600, "1600 m"),
                              (2000, "2 km"), (3000, "3 km"), (5000, "5 km")):
            if abs(metres - target) / target <= 0.12:
                return text
        return f"{metres / 1000:.2g} km"

    assert old_round_dist(890) == "800 m"
    assert il._round_dist(890) == "1 km"


def test_round_dist_falls_through_for_a_genuinely_odd_distance():
    """700 m sits in the true gap between 600's band (528-672) and 800's band
    (704-896) — no target's ±12 % tolerance covers it, so it renders as a
    plain km fallback rather than being force-snapped to a named distance.

    FIXTURE NOTE: the brief's suggested 1750 m does NOT demonstrate this —
    1750 m sits inside 1600's band at a relative error of 0.094 (<= 0.12), so
    it snaps to '1600 m' under the fixed closest-by-relative-error logic too,
    verified directly. 700 m is a genuine gap between adjacent bands."""
    assert il._round_dist(700) == "0.7 km"


def _flat_dist_at(seconds):
    """1 m/s so elapsed seconds double as metres — enough to drive label_for
    directly without building full streams."""
    return float(seconds)


def test_label_for_pyramid_reads_as_the_pyramid():
    """Direct coverage of label_for's own varied branch: the existing suite
    (test_unequal_reps_are_varied_not_averaged) only reaches varied-ness
    through set_stats, never asserting on label_for's own pyramid string."""
    bouts = [(0, 1000), (1000, 3000), (3000, 4000)]     # 1 km, 2 km, 1 km
    assert il.label_for("reps", bouts, _flat_dist_at) == "1-2-1 km"


def _lap(dist, dur, intensity=None, hr=150):
    lap = {"distance": dist, "duration": dur, "averageHR": hr,
           "averageSpeed": dist / dur if dur else 0}
    if intensity:
        lap["intensityType"] = intensity
    return lap


def test_kilometre_autolap_is_not_structure():
    """19 laps on a 19 km easy run is auto-lap, not a 19-rep session."""
    laps = [_lap(1000, 330) for _ in range(18)] + [_lap(420, 140)]
    assert il.laps_are_autolap(laps) is True


def test_mile_autolap_is_not_structure():
    laps = [_lap(1609.34, 530) for _ in range(6)] + [_lap(300, 100)]
    assert il.laps_are_autolap(laps) is True


def test_real_reps_are_not_autolap():
    laps = [_lap(2000, 700), _lap(1000, 330), _lap(200, 90), _lap(1000, 332)]
    assert il.laps_are_autolap(laps) is False


def test_structured_needs_intensity_or_the_flag():
    summary = {"hasIntensityIntervals": True, "workoutId": 42}
    laps = [_lap(2000, 700, "WARMUP"), _lap(1000, 330, "ACTIVE"),
            _lap(200, 90, "REST"), _lap(1000, 332, "ACTIVE")]
    assert il.laps_are_structured(summary, laps) is True


def test_autolap_beats_the_workout_flag():
    """A workout run whose laps are all 1 km still carries no rep structure.

    FIXTURE FIX: the brief's original laps carried no intensityType at all, so
    `intensities` was empty and `len(intensities) > 1` was already False —
    this passed even with the auto-lap veto deleted entirely, verified
    directly. Alternating ACTIVE/REST on the same uniform 1 km laps gives two
    distinct intensities, so the workout-flag branch would read True without
    the veto; only the veto firing first makes this False, confirmed by
    running both versions of laps_are_structured against this exact fixture."""
    summary = {"workoutId": 42}
    laps = [_lap(1000, 330, "ACTIVE" if i % 2 == 0 else "REST") for i in range(8)]
    assert il.laps_are_structured(summary, laps) is False


def test_uniform_intensity_is_not_structure():
    summary = {"workoutId": 7}
    laps = [_lap(1200, 400, "ACTIVE"), _lap(1300, 430, "ACTIVE")]
    assert il.laps_are_structured(summary, laps) is False


def test_segments_from_laps_carry_roles():
    laps = [_lap(2000, 700, "WARMUP"), _lap(1000, 330, "ACTIVE"),
            _lap(200, 90, "REST"), _lap(1000, 332, "ACTIVE"),
            _lap(1000, 360, "COOLDOWN")]
    segs = il.segments_from_laps(laps)
    assert [s["role"] for s in segs] == \
        ["warmup", "work", "recovery", "work", "cooldown"]
    assert segs[1]["rep"] == 1 and segs[3]["rep"] == 2
    assert segs[1]["paceS"] == 330
