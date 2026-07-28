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


def make_dual_streams(spans, hr=150):
    """spans: [(duration_s, raw_mps, gap_mps)] — a run whose raw and
    grade-adjusted speeds genuinely DIFFER, which is the normal case: 161 of
    the archive's 165 runs carry a `gap` stream and it is not a copy of `v`.
    `make_streams(gap=True)` copies `v` into `gap`, so it cannot tell the two
    apart and cannot catch a producer that reports one under the other's
    name."""
    t, d, v, g, hrs = [], [], [], [], []
    clock, dist = 0, 0.0
    for dur, raw, gap in spans:
        for _ in range(dur):
            t.append(clock)
            d.append(round(dist))
            v.append(raw)
            g.append(gap)
            hrs.append(hr)
            clock += 1
            dist += raw          # distance follows the RAW speed, as on a watch
    return {"t": t, "d": d, "v": v, "gap": g, "hr": hrs}


def test_detection_reads_gap_but_reporting_reads_both_grids():
    """FINAL REVIEW I4: `speed_series` prefers `gap` (design D5, correct), and
    the segment builders then reported that same series as `paceS` while
    hardcoding `gapS: None`. So `paceS` held grade-adjusted pace under a raw
    label and the column labelled GAP was empty on every row of every rep
    table — the two were effectively swapped. Three grids now, one clock."""
    s = make_streams([(100, 3.0)], gap=True)
    s["gap"] = [4.0] * 100
    assert il.speed_series(s)[50] == 4.0, "detection: grade-adjusted wins (D5)"
    assert il.raw_speed_series(s)[50] == 3.0, "reporting: paceS is what the watch saw"
    assert il.gap_speed_series(s)[50] == 4.0, "reporting: gapS is the adjustment"


def test_gap_grid_is_empty_without_a_gap_stream():
    """A treadmill, and 4 of the archive's 165 runs. No grade adjustment
    exists, so none is reported — echoing raw pace into the GAP column would
    claim an adjustment that never happened."""
    s = make_streams([(100, 3.0)])
    assert il.gap_speed_series(s) == []
    assert il.raw_speed_series(s)[50] == 3.0
    assert il.speed_series(s)[50] == 3.0, "detection falls back to raw speed"


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


# ── FINAL REVIEW I6: enumeration is for pyramids, not for fragment lists ────
# `varied` is decided by the algorithm and is right; what it produced as a
# LABEL was not. Measured on the real archive: 13 of 19 rep detections read
# like "0.89-0.385-0.333-0.417-0.598-0.894-1.77-0.811 km", and that string is
# user-facing in three places at once (the /archive chip, the rep-card title
# and — via coach-read.js — the cockpit sentence). Display only: nothing below
# changes which bouts the engine found or what `set` reports about them.

def test_a_readable_pyramid_still_enumerates_its_reps():
    """The real archive's `pYRAMIDE: 1-2-1K Tempo` session detects five bouts
    at 987/958/530/495/296 m. It is the one detection in the archive worth
    enumerating, so the rule is tuned to keep it: few enough reps to read, and
    every one of them lands on a distance a human would prescribe."""
    edges = [0, 987, 1945, 2475, 2970, 3266]
    bouts = list(zip(edges, edges[1:]))
    assert il.label_for("reps", bouts, _flat_dist_at) == "0.987-0.958-0.53-0.495-0.296 km"


def test_too_many_unequal_reps_collapse_to_a_count():
    """Eight fragments are not a pyramid anybody wrote down. The real
    detection this is taken from is the archive's W13 HM2-Training run."""
    dists = [890, 385, 333, 417, 598, 894, 1770, 811]
    edges = [0]
    for d in dists:
        edges.append(edges[-1] + d)
    bouts = list(zip(edges, edges[1:]))
    assert len(bouts) > il.VARIED_MAX_ENUMERATE
    assert il.label_for("reps", bouts, _flat_dist_at) == "8 reps"


def test_a_short_set_of_unprescribable_reps_also_collapses():
    """The count ceiling alone is not enough: this set has only three reps but
    a 153 m and a 168 m one, and nobody prescribes those. Taken from the
    archive's 2024-05-24 run, which used to read '0.153-0.238-0.168 km'."""
    edges = [0, 153, 391, 559]
    bouts = list(zip(edges, edges[1:]))
    assert len(bouts) <= il.VARIED_MAX_ENUMERATE, \
        "this must fail on the ROUNDNESS rule, not the count one"
    assert il.label_for("reps", bouts, _flat_dist_at) == "3 reps"


def test_a_uniform_set_is_untouched_by_the_collapse_rule():
    """The rule only ever fires on `varied` sets — a clean 6×200 m keeps its
    real name however many reps it has."""
    edges = [i * 200 for i in range(7)]
    bouts = list(zip(edges, edges[1:]))
    assert len(bouts) > il.VARIED_MAX_ENUMERATE
    assert il.label_for("reps", bouts, _flat_dist_at) == "6×200 m"


def test_snaps_to_round_is_the_prescribable_distance_test():
    assert il._snaps_to_round(987) and il._snaps_to_round(296)
    assert il._snaps_to_round(1580), "1580 m is a 1600 m rep measured short"
    assert not il._snaps_to_round(153), "nobody prescribes 153 m"
    assert not il._snaps_to_round(688), "…nor 688 m — that is a fragment"


# ── varied: max deviation from the median, not the range (fix round) ────────
# `set_stats`, `label_for` and the laps path in `build_document` all used to
# compute this independently as (max - min) / nominal — a RANGE test, fragile
# because a single outlier rep (most often one bout clipped early at
# find_bouts' exit threshold, reading a little short) drags the whole
# verdict. The real archive's known '2km wu, 5x1km @ 5:40' session detects
# reps [968, 907, 959, 981, 782] m: (981 - 782) / 959 = 0.207, a hair over
# VARIED_TOLERANCE (0.20), so a plainly uniform 5x1 km set degraded to the
# label '0.968-0.907-0.959-0.981-0.782 km'. `_rep_variation` is now the ONE
# place all three callers compute this, using the maximum per-rep deviation
# from the median instead.

def test_rep_variation_one_clipped_rep_stays_uniform_under_the_new_rule():
    """THE POINT OF THE FIX ROUND. Distances derived from VARIED_TOLERANCE
    (T), not hardcoded, so a retune cannot silently rot this: a low tail at
    0.9*T below nominal (the clipped rep) and a mildly long natural high tail
    at 0.6*T above it, with three reps sitting exactly at nominal. Their SUM
    (1.5*T) exceeds T for any positive T, so the OLD range rule
    ((max-min)/nominal) always calls this varied; neither deviation alone
    exceeds T, so the NEW max-deviation rule always calls it uniform."""
    T = il.VARIED_TOLERANCE
    nominal = 1000
    low = round(nominal * (1 - 0.9 * T))     # the clipped rep
    high = round(nominal * (1 + 0.6 * T))    # a mildly long natural rep
    dists = [nominal, nominal, nominal, low, high]

    old_range_frac = (max(dists) - min(dists)) / nominal
    assert old_range_frac > T, "fixture must reproduce the old rule's false positive"

    result_nominal, varied = il._rep_variation(dists)
    assert result_nominal == nominal
    assert varied is False


def test_rep_variation_a_genuine_pyramid_stays_varied():
    """Pyramids must survive the fix — that is the whole reason `varied`
    exists. Sized off VARIED_TOLERANCE (T) rather than hardcoded so a retune
    cannot silently rot this: the middle rep is `1 + 3*T` times the flanking
    reps, comfortably over tolerance under either rule for any reasonable T."""
    T = il.VARIED_TOLERANCE
    flank = 1000
    middle = round(flank * (1 + 3 * T))       # the pyramid's long middle rep
    dists = [flank, middle, flank]            # the 1-2-1 km pyramid's shape

    nominal, varied = il._rep_variation(dists)
    assert nominal == flank
    assert varied is True


def test_document_label_survives_one_clipped_rep():
    """End-to-end regression, through find_bouts → set_stats → label_for:
    the same qualitative shape as the real '2km wu, 5x1km' archive session
    (three reps at nominal, one mildly long, one clipped short), built from
    full streams so the WIRING is what is under test, not just the pure
    helper — using the same VARIED_TOLERANCE-derived distances as
    test_rep_variation_one_clipped_rep_stays_uniform_under_the_new_rule."""
    T = il.VARIED_TOLERANCE
    speed = 4.0
    nominal_s = 250                                   # 250 s @ 4.0 m/s = 1000 m
    low_s = round(nominal_s * (1 - 0.9 * T))          # the clipped rep
    high_s = round(nominal_s * (1 + 0.6 * T))         # a mildly long natural rep
    work = [nominal_s, nominal_s, nominal_s, low_s, high_s]

    spans = [(600, 2.6)]
    for d in work:
        spans += [(d, speed), (60, 2.2)]
    spans += [(300, 2.6)]

    doc = il.build_document(make_streams(spans), work_floor=3.0)
    assert doc["shape"] == "reps"
    assert doc["set"]["found"] == 5
    assert doc["set"]["varied"] is False
    assert doc["label"] == "5×1 km"


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


def test_workout_run_with_varied_intensities_is_structured():
    """Fix round 1, finding 1: D1's SECOND route to structure — a workout run
    with varied lap intensities but NO explicit hasIntensityIntervals flag —
    had no positive test. `test_structured_needs_intensity_or_the_flag` sets
    hasIntensityIntervals and short-circuits before ever reaching the
    workoutId/intensity-count line. Distances here are deliberately
    non-uniform (2000/1000/200) so laps_are_autolap does not veto."""
    summary = {"workoutId": 99}
    laps = [_lap(2000, 700, "WARMUP"), _lap(1000, 330, "ACTIVE"),
            _lap(200, 90, "REST"), _lap(1000, 332, "ACTIVE")]
    assert il.laps_are_structured(summary, laps) is True


def test_short_real_session_is_not_flagged_autolap():
    """Fix round 1, finding 4 (design fix): a genuine 2-rep session — two 1 km
    reps plus a partial recovery lap — must NOT be vetoed as auto-lap just
    because its only two FULL laps happen to agree on distance. Requiring
    three full laps (not two) before calling it a pattern is what lets this
    stay structured."""
    laps = [_lap(1000, 330, "ACTIVE"), _lap(1000, 330, "ACTIVE"),
            _lap(200, 90, "REST")]
    assert il.laps_are_autolap(laps) is False
    assert il.laps_are_structured({"workoutId": 5}, laps) is True


def test_segments_from_laps_chain_cumulative_boundaries():
    """Fix round 1, finding 2: the cumulative t0/t1/d0/d1 bookkeeping in
    segments_from_laps was entirely unasserted — removing both accumulator
    updates (`t0 += dur`, `d0 += dist`) still left the suite green. Assert the
    chain directly: each segment's t0/d0 must equal the previous segment's
    t1/d1, and the final d1/t1 must equal the summed lap distance/duration.
    All lap durations and distances below are whole numbers so the sums are
    exact, with no rounding drift to account for."""
    laps = [_lap(600, 200, "WARMUP"), _lap(1000, 330, "ACTIVE"),
            _lap(200, 90, "REST"), _lap(1000, 332, "ACTIVE"),
            _lap(500, 180, "COOLDOWN")]
    segs = il.segments_from_laps(laps)
    for prev, cur in zip(segs, segs[1:]):
        assert cur["t0"] == prev["t1"]
        assert cur["d0"] == prev["d1"]
    assert segs[-1]["d1"] == sum(l["distance"] for l in laps)
    assert segs[-1]["t1"] == sum(l["duration"] for l in laps)


def test_unrecognised_intensity_defaults_to_work():
    """Fix round 1, finding 3: only the ABSENT intensityType case exercised
    the _LAP_ROLES default; a real-but-unmapped label (e.g. a Garmin variant
    not in our map) was never tried. It must default to 'work', not
    'recovery' — mapping an unrecognised label to recovery would silently
    shrink the rep set."""
    laps = [_lap(1000, 330, "SPRINT")]
    segs = il.segments_from_laps(laps)
    assert segs[0]["role"] == "work"


# ── build_document — the one entry point ─────────────────────────────────────

def test_document_shape_for_a_rep_session():
    s = make_streams([(600, 2.6)] + [(250, 4.0), (60, 2.2)] * 5 + [(300, 2.6)])
    doc = il.build_document(s, work_floor=3.0)
    assert doc["version"] == il.INTERVAL_VERSION
    assert doc["shape"] == "reps"
    assert doc["source"] == "stream"
    assert doc["label"] == "5×1 km"
    assert doc["guidedBy"] is None            # blind in Change 1 (design D8)
    assert doc["set"]["found"] == 5
    assert doc["quality"]["workDistM"] > 4500


_PROGRESSION_SPANS = [(400, 2.8), (400, 2.87), (400, 2.94), (400, 3.01), (400, 3.08)]

_DUAL_REP_SPANS = ([(600, 2.6, 2.6)] + [(250, 4.0, 4.4), (60, 2.2, 2.2)] * 5
                   + [(300, 2.6, 2.6)])


def test_every_segment_carries_a_real_gap_distinct_from_its_pace():
    """FINAL REVIEW I4: `gapS` was hardcoded None at all three producing
    sites, and nothing populated it — measured on the real archive, 229
    segments and 0 with a non-null `gapS`, so the GAP column rendered an em
    dash on every row of every rep table, permanently. Meanwhile `paceS`
    carried the grade-adjusted number.

    Both values are pinned to the fixture's OWN streams (4.0 m/s raw = 250
    s/km, 4.4 m/s adjusted = 227 s/km), so reporting one under the other's
    name fails here rather than looking plausible."""
    doc = il.build_document(make_dual_streams(_DUAL_REP_SPANS), work_floor=3.0)
    assert doc["shape"] == "reps" and doc["set"]["found"] == 5
    work = [s for s in doc["segments"] if s["role"] == "work"]
    assert len(work) == 5
    for seg in work:
        assert seg["paceS"] == 250, f"raw pace, from v=4.0 m/s: {seg['paceS']}"
        assert seg["gapS"] == 227, f"grade-adjusted, from gap=4.4 m/s: {seg['gapS']}"
    # every OTHER segment too — a warmup with no GAP is just as much a hole
    assert all(s["gapS"] is not None for s in doc["segments"]), \
        "every segment the run has data for reports GAP, not only the work ones"
    # and the set's reps carry the same pair
    assert [r["paceS"] for r in doc["set"]["reps"]] == [250] * 5
    assert [r["gapS"] for r in doc["set"]["reps"]] == [227] * 5
    assert doc["set"]["paceS"] == 250, "the set's headline pace is the RAW one"


def test_a_run_without_a_gap_stream_reports_no_gap_rather_than_a_copy():
    """The honest fallback (4 of 165 archived runs, and every treadmill run,
    and every one of the second athlete's — Health Connect carries no grade
    adjustment). `gapS` must be null, not a duplicate of `paceS`: the run page
    renders null as an em dash, and a duplicated number would silently claim
    the run was flat."""
    spans = [(600, 2.6)] + [(250, 4.0), (60, 2.2)] * 5 + [(300, 2.6)]
    doc = il.build_document(make_streams(spans), work_floor=3.0)
    assert doc["shape"] == "reps"
    work = [s for s in doc["segments"] if s["role"] == "work"]
    assert all(s["paceS"] == 250 for s in work), "raw pace still reported"
    assert all(s["gapS"] is None for s in doc["segments"]), \
        "no gap stream → no grade-adjusted pace, not a copy of the raw one"
    assert all(r["gapS"] is None for r in doc["set"]["reps"])


def test_spread_and_fade_are_measured_on_the_same_signal_as_the_bars():
    """CHANGED 2026-07-28, deliberately, and this reverses design D5's
    reporting half. `fadePct`/`paceCvPct` rode the grade-adjusted DETECTION
    signal while the rep table's deviation bars and PACE column were raw, so a
    hilly set fanned its bars out above a sub-line reading '0.0 % spread'.

    Measured before choosing: on the archive's one uncontaminated hill-repeat
    set (2025-11-21, eight genuine 90 s reps) RAW is TIGHTER — cv 9.1 % vs
    GAP 14.7 %. Fixed-duration reps cover less ground as the athlete tires, so
    each samples a different slice of the gradient and its grade adjustment
    varies; GAP there measures the hill, not the athlete. On the stream path
    the two bases differ by under 1.5 points and split both ways across 11
    sets.

    The cost this fixture now pins: a set climbing a CONTINUOUS drag at
    constant effort reads as a fade, which is exactly what D5 warned about.
    No such session exists in 168 runs — every hill session runs each rep up
    the same hill and recovers back down — so successive reps share terrain
    and raw pace compares them honestly. Revisit if one ever appears.

    DETECTION is untouched: the bouts are still found on the grade-adjusted
    signal, so this set is still detected as ONE set."""
    spans = [(600, 2.6, 2.6)]
    for raw in (4.4, 4.2, 4.0, 3.8, 3.6):
        spans += [(250, raw, 4.2), (60, 2.2, 2.2)]
    spans += [(300, 2.6, 2.6)]
    doc = il.build_document(make_dual_streams(spans), work_floor=3.0)
    assert doc["shape"] == "reps" and doc["set"]["found"] == 5, \
        "detection still rides the grade-adjusted signal — one set, not five"
    st = doc["set"]
    assert st["fadePct"] > 15, \
        f"the raw slowdown is now reported as the fade it looks like: {st['fadePct']}%"
    assert st["paceCvPct"] > 5, f"…and as real spread: {st['paceCvPct']}"
    assert all(abs(r["gapS"] - 238) <= 2 for r in st["reps"]), \
        "GAP stays per-rep and unchanged — the terrain read lives in that column"


def test_progression_steps_carry_both_paces_too():
    """`_progression_segments` was the third site hardcoding `gapS: None`.
    The ramp is the suite's own `_PROGRESSION_SPANS` (below) — a fixture
    already proven to classify as `progression` — with a grade adjustment
    added on top, so this test only introduces the one variable it is about."""
    spans = [(dur, mps, round(mps * 1.1, 3)) for dur, mps in _PROGRESSION_SPANS]
    doc = il.build_document(make_dual_streams(spans), work_floor=3.0)
    assert doc["shape"] == "progression"
    for seg in doc["segments"]:
        assert seg["paceS"] and seg["gapS"]
        assert seg["gapS"] < seg["paceS"], \
            "grade-adjusted is faster here by construction — the two are not the same number"


def test_lap_sourced_segments_gain_gap_from_the_stream():
    """A lapDTO carries no grade-adjusted speed, so taking laps VERBATIM (D1)
    left the GAP column empty on exactly the runs that earn a lap-sourced
    document — the athlete's real workout days. The lap clock shares its
    origin with the 1 Hz grid, so the adjustment is read from the stream over
    each lap's own window while `paceS` still comes from the DTO."""
    s = make_dual_streams(_DUAL_REP_SPANS)
    laps = [_lap(1560, 600, "WARMUP"), _lap(1000, 250, "ACTIVE"),
            _lap(132, 60, "REST"), _lap(1000, 250, "ACTIVE"),
            _lap(1000, 360, "COOLDOWN")]
    doc = il.build_document(s, {"hasIntensityIntervals": True}, laps)
    assert doc["source"] == "laps"
    work = [seg for seg in doc["segments"] if seg["role"] == "work"]
    assert [seg["paceS"] for seg in work] == [250, 250], \
        "pace still comes from the DTO's own averageSpeed, not re-derived"
    assert all(seg["gapS"] == 227 for seg in work), \
        f"GAP read from the stream over each lap's window: {[s['gapS'] for s in work]}"
    assert all(r["gapS"] == 227 for r in doc["set"]["reps"])


def test_lap_gap_comes_from_the_device_when_it_carries_one():
    """`segments_from_laps` derived gapS by windowing the stream's gap grid,
    on the docstring's claim that "a lapDTO carries no grade-adjusted speed".
    It does: avgGradeAdjustedSpeed is present on 553 of the archive's 565
    laps. The device value is also immune to M3 — lap `duration` is MOVING
    time, so on a paused run the accumulated t0 drifts off the stream's
    elapsed axis and the windowed lookup reads the wrong slice."""
    lap = _lap(1000, 300, "ACTIVE")
    lap["avgGradeAdjustedSpeed"] = 4.0          # 250 s/km
    segs = il.segments_from_laps([lap], gaps=[2.0] * 400)   # 500 s/km if windowed
    assert segs[0]["gapS"] == 250, "the device's own number, not the stream's"


def test_lap_gap_falls_back_to_the_stream_grid():
    lap = _lap(1000, 300, "ACTIVE")              # no avgGradeAdjustedSpeed
    segs = il.segments_from_laps([lap], gaps=[4.0] * 400)
    assert segs[0]["gapS"] == 250


def test_lap_gap_is_none_when_neither_source_has_one():
    lap = _lap(1000, 300, "ACTIVE")
    assert il.segments_from_laps([lap], gaps=None)[0]["gapS"] is None


def test_lap_gap_of_exactly_zero_falls_back_rather_than_reporting_zero():
    """A standing-rest lap can legitimately average 0 m/s grade-adjusted
    speed, but `_pace_s_per_km(0)` cannot turn that into a sane pace — it is
    the sentinel for "no data" everywhere else in this module. So a device
    value of exactly 0 is treated as ABSENT, and the lookup falls back to the
    windowed stream grid, same as a missing field would."""
    lap = _lap(1000, 300, "ACTIVE")
    lap["avgGradeAdjustedSpeed"] = 0.0
    segs = il.segments_from_laps([lap], gaps=[4.0] * 400)
    assert segs[0]["gapS"] == 250, "zero is not a usable device pace; the stream wins"


def test_steady_run_still_gets_a_document():
    """'Looked, found nothing' must never look like 'never looked'."""
    doc = il.build_document(make_streams([(2400, 3.0)]))
    assert doc["shape"] == "steady"
    assert doc["segments"] == []
    assert doc["set"] is None


def test_no_streams_means_no_document():
    """Some of Max's runs carry no SpeedRecord at all."""
    assert il.build_document(None) is None
    assert il.build_document({"t": [], "d": []}) is None


def test_structured_laps_win_over_the_stream():
    s = make_streams([(600, 2.6)] + [(250, 4.0), (60, 2.2)] * 5 + [(300, 2.6)])
    laps = [_lap(2000, 700, "WARMUP"), _lap(1000, 250, "ACTIVE"),
            _lap(150, 60, "REST"), _lap(1000, 250, "ACTIVE"),
            _lap(1000, 360, "COOLDOWN")]
    doc = il.build_document(s, {"hasIntensityIntervals": True}, laps)
    assert doc["source"] == "laps"
    assert doc["confidence"] == 1.0
    assert doc["set"]["found"] == 2        # the laps say 2, and the laps win


def test_autolap_falls_through_to_the_stream():
    s = make_streams([(600, 2.6)] + [(250, 4.0), (60, 2.2)] * 5 + [(300, 2.6)])
    laps = [_lap(1000, 330) for _ in range(8)]
    doc = il.build_document(s, {"workoutId": 9}, laps, work_floor=3.0)
    assert doc["source"] == "stream"
    assert doc["set"]["found"] == 5


def test_segments_cover_warmup_reps_and_cooldown():
    s = make_streams([(600, 2.6)] + [(250, 4.0), (60, 2.2)] * 3 + [(300, 2.6)])
    roles = [seg["role"] for seg in il.build_document(s, work_floor=3.0)["segments"]]
    assert roles[0] == "warmup"
    assert roles[-1] == "cooldown"
    assert roles.count("work") == 3
    assert roles.count("recovery") == 2


def test_quality_zone_is_time_weighted():
    """A 4 km rep must not be outvoted by two 400 m ones.

    FIXTURE FIX: the brief's original fixture applied a single uniform HR
    (175) across the WHOLE stream via make_streams' one hr= argument, so
    every segment — work, recovery, warmup, cooldown alike — read the same
    HR. That can't distinguish time-weighting from a naive per-segment vote
    (there was only ever one candidate zone), and worse, its expected answer
    was arithmetically wrong: zone_bounds(195) == [98, 117, 136, 156, 176,
    195] (verified directly — round(195*0.90) is 176 under Python's actual
    float rounding, not 175), so hr=175 sits ONE beat under the Z4/Z5 cut at
    176 and lands in Z4, never Z5.

    Rebuilt so the property is real: one long rep (600 s) at a Z5 heart rate
    outweighs two short reps (60 s each) at a Z3 heart rate. A segment-count
    vote would read Z3 (2 segments beat 1); the time-weighted vote must read
    Z5 (600 s beats 120 s) — which is also the brief's original expected
    value, so only the fixture changed, not the assertion.
    """
    spans = [(300, 2.6), (600, 4.0), (60, 2.2), (60, 4.0), (60, 2.2), (60, 4.0), (300, 2.6)]
    s = make_streams(spans)
    bounds = il.zone_bounds(195)
    edges, cursor = [], 0
    for dur, _ in spans:
        edges.append((cursor, cursor + dur))
        cursor += dur
    (_, _), (w1a, w1b), (_, _), (w2a, w2b), (_, _), (w3a, w3b), (_, _) = edges
    for i in range(w1a, w1b):
        s["hr"][i] = 185                       # Z5 — the dominant-duration rep
    for i in range(w2a, w2b):
        s["hr"][i] = 145                       # Z3 — short
    for i in range(w3a, w3b):
        s["hr"][i] = 145                       # Z3 — short
    doc = il.build_document(s, bounds=bounds, work_floor=3.0)
    assert doc["set"]["found"] == 3
    assert doc["quality"]["zone"] == "Z5"


def test_quality_zone_is_null_without_bounds():
    """A guessed zone is worse than no zone.

    FIXTURE NOTE (Task 7b): without an explicit `work_floor` this document is
    uncalibrated, so `bouts` is forced empty, the shape is "steady", and there
    are no "work" segments at all — the assertion would then hold vacuously
    for a reason unrelated to `bounds`. Passing `work_floor=3.0` restores real
    "reps" shape and real work segments, so the missing-bounds guard in
    `_quality` is what the assertion actually exercises."""
    s = make_streams([(600, 2.6)] + [(250, 4.0), (60, 2.2)] * 5 + [(300, 2.6)])
    assert il.build_document(s, work_floor=3.0)["quality"]["zone"] is None


def test_zone_bounds_use_hr_reserve_when_resting_hr_is_known():
    """Karvonen when rhr is known, plain %max otherwise — the beginner-honest
    model. (ingest_builder delegates here, so this is the only definition.)"""
    assert il.zone_bounds(190) == [95, 114, 133, 152, 171, 190]
    assert il.zone_bounds(190, 48) == [119, 133, 147, 162, 176, 190]


def test_confidence_is_higher_for_a_crisp_set():
    crisp = il.build_document(
        make_streams([(600, 2.6)] + [(250, 4.2), (60, 2.2)] * 5 + [(300, 2.6)]),
        work_floor=3.0)
    ragged = il.build_document(
        make_streams([(600, 2.8)] + [(250, 3.3), (60, 2.6)] * 5 + [(300, 2.8)]),
        work_floor=3.0)
    assert crisp["confidence"] > ragged["confidence"]
    assert 0.0 <= ragged["confidence"] <= 1.0


# ── cross-run calibration (Task 7b) ──────────────────────────────────────────

def test_baseline_samples_subsamples_the_moving_grid():
    """One run contributes a thinned sample of its moving speeds — thinned
    because a full-resolution accumulation over years of runs is needless."""
    s = make_streams([(600, 3.0)])
    out = il.baseline_samples(s, stride=5)
    assert 100 < len(out) < 140          # ~600/5, allowing for the grid's +1
    assert all(v == 3.0 for v in out)


def test_baseline_samples_excludes_pauses():
    """A pause is absent data — it must not drag the athlete's baseline down."""
    s = make_streams([(300, 3.0), (300, 0.0), (300, 3.0)])
    assert all(v >= il.MOVING_MPS_MIN for v in il.baseline_samples(s))


def test_work_floor_is_the_percentile_of_the_history():
    """FIXTURE FIX: the brief's 1..1000 sample (assert ≈ 930) never reaches the
    percentile arithmetic at all — it is 1000 samples against
    WORK_FLOOR_MIN_SAMPLES = 20_000, so `work_floor` returns None at the
    history-size gate before `sorted`/indexing ever runs (verified directly:
    `work_floor([float(i) for i in range(1, 1001)], 0.93) is None`). Scaled to
    1..100000 — comfortably past the 20_000 floor and disentangled from the
    boundary itself, which `test_work_floor_needs_enough_history` already
    covers — the same 0.93 percentile of a 1..N run is (about) 0.93·N."""
    samples = [float(i) for i in range(1, 100_001)]      # 1..100000
    assert abs(il.work_floor(samples, 0.93) - 93_000) <= 1


def test_work_floor_needs_enough_history():
    """An unstable percentile is worse than none — Max's archive starts small."""
    assert il.work_floor([3.0] * (il.WORK_FLOOR_MIN_SAMPLES - 1)) is None
    assert il.work_floor([3.0] * il.WORK_FLOOR_MIN_SAMPLES) is not None


def test_calibration_rejects_a_bout_that_is_merely_faster_than_its_own_run():
    """THE POINT OF THIS TASK. A warm-up surge inside an easy run is faster
    than that run's average but is not fast for this athlete. Unfiltered it
    becomes a rep; calibrated it does not.

    GUARD-TRACE: verified directly that this fixture's three bouts are real —
    split_classes finds separation 0.128 (clears SEPARATION_MIN's 0.12), and
    find_bouts locates exactly three bouts at mean speed 2.62 m/s, each
    250 s / ~655 m (clears WORK_MIN_S=30 and WORK_MIN_M=150). The floor (2.70)
    is what removes them — not an earlier gate — because 2.62 < 2.70.

    FIXTURE FIX: the brief's `uncalibrated = il.build_document(s)` (no
    `work_floor`) cannot assert `shape == "reps"` — under this task's own
    "honest silence" rule, `build_document` with `work_floor=None` makes NO
    rep claim at all regardless of what find_bouts found (bouts forced to
    `[]`, `calibrated: False` — see test_uncalibrated_documents_make_no_rep_claim
    for that behaviour, same fixture). Verified directly:
    `il.build_document(s)["shape"] == "steady"`, not `"reps"` as the brief's
    text asserts — the brief's own Step 3 implementation contradicts its own
    Step 1 test. "The old, wrong behaviour" this test wants to contrast
    against is what `classify` returns on the RAW, unfiltered bouts (the
    pre-Task-7b engine, before any calibration concept existed), so that is
    what is asserted instead, preserving the test's stated intent without
    relying on a build_document call the new contract makes impossible."""
    spans = [(600, 2.30)] + [(250, 2.62), (60, 2.20)] * 3 + [(300, 2.30)]
    s = make_streams(spans)
    floor = 2.70                                    # this athlete's p93

    series = il.smooth(il.speed_series(s))
    dist_at = il.distance_fn(s)
    classes = il.split_classes(series)
    assert classes is not None, "fixture should be structured"
    raw_bouts = il.find_bouts(series, dist_at, classes[0], classes[1])
    assert il.classify(raw_bouts, series, dist_at, None) == "reps"  # the old, wrong behaviour

    calibrated = il.build_document(s, work_floor=floor)
    assert calibrated["shape"] == "steady"          # nothing here is genuinely fast
    assert calibrated["calibrated"] is True


def test_calibration_keeps_a_genuine_set():
    """The same floor must not eat real reps — 4.0 m/s is well above it."""
    spans = [(600, 2.30)] + [(250, 4.0), (60, 2.20)] * 5 + [(300, 2.30)]
    doc = il.build_document(make_streams(spans), work_floor=2.70)
    assert doc["shape"] == "reps"
    assert doc["set"]["found"] == 5


def test_uncalibrated_documents_make_no_rep_claim():
    """Without a baseline the engine cannot tell fast from merely-faster, so it
    must not claim a set at all. Honest silence beats a confident lie."""
    spans = [(600, 2.30)] + [(250, 2.62), (60, 2.20)] * 3 + [(300, 2.30)]
    doc = il.build_document(make_streams(spans))     # no work_floor
    assert doc["calibrated"] is False


def test_lap_sourced_documents_are_always_calibrated():
    """Device laps need no baseline — the watch is not guessing."""
    s = make_streams([(600, 2.6)] + [(250, 4.0), (60, 2.2)] * 5 + [(300, 2.6)])
    laps = [_lap(2000, 700, "WARMUP"), _lap(1000, 250, "ACTIVE"),
            _lap(150, 60, "REST"), _lap(1000, 250, "ACTIVE"),
            _lap(1000, 360, "COOLDOWN")]
    doc = il.build_document(s, {"hasIntensityIntervals": True}, laps)
    assert doc["source"] == "laps"
    assert doc["calibrated"] is True


# ── progression segments (Task 7b, Part B) ───────────────────────────────────
# The same monotone-ramp fixture as test_progression_is_detected_without_bouts:
# a shallow enough ramp that split_classes finds no two-class structure
# (separation 0.057, well under SEPARATION_MIN) but _is_progression's quintile
# check finds the monotone rise (end-to-end gain 0.10, over PROGRESSION_MIN_GAIN's
# 0.05). At the document level, before this fix, this run's ramp emitted ONE
# segment spanning the whole run with role "steady" and no `step` role at all
# — verified directly. The design contract requires a `step` segment per
# detected pace tier so a consumer can read the ramp the way it reads a rep
# table.

def test_progression_emits_five_step_segments_in_time_order():
    doc = il.build_document(make_streams(_PROGRESSION_SPANS))
    assert doc["shape"] == "progression"
    segs = doc["segments"]
    assert len(segs) == 5
    assert [seg["role"] for seg in segs] == ["step"] * 5
    assert [seg["idx"] for seg in segs] == [1, 2, 3, 4, 5]
    for prev, cur in zip(segs, segs[1:]):
        assert cur["t0"] >= prev["t0"]
    # a progression has no discrete work bouts — this is correct, not a bug
    assert doc["quality"]["workDistM"] == 0
    assert doc["quality"]["workDurS"] == 0


def test_progression_paces_decrease_monotonically():
    """Speed rises quintile over quintile (that is what makes it a
    progression), so paceS — seconds per km — must fall in step."""
    doc = il.build_document(make_streams(_PROGRESSION_SPANS))
    paces = [seg["paceS"] for seg in doc["segments"]]
    assert len(paces) == 5
    assert all(paces[i] > paces[i + 1] for i in range(len(paces) - 1))


def test_progression_segments_tile_without_gaps():
    """The same tiling property _segments_from_bouts already guarantees for
    rep runs: each segment starts exactly where the previous one ended, no
    gap and no overlap, and the run's full span is covered edge to edge."""
    s = make_streams(_PROGRESSION_SPANS)
    doc = il.build_document(s)
    segs = doc["segments"]
    assert segs[0]["t0"] == 0
    for prev, cur in zip(segs, segs[1:]):
        assert cur["t0"] == prev["t1"]
        assert cur["d0"] == prev["d1"]
    assert segs[-1]["t1"] == len(il.speed_series(s))


# ── lap-derived rep floor (production defect fix, 2026-07-27) ───────────────
# `segments_from_laps` maps every ACTIVE/INTERVAL lap to a `work` rep
# verbatim. The stream path has always required a bout to clear WORK_MIN_S
# (30 s) *and* WORK_MIN_M (150 m) to exist at all (`find_bouts`); the laps
# path applied no floor whatsoever, so a trailing partial lap — the athlete
# pressing stop, or the watch's own end-of-activity lap — became a "rep".
# Measured on the live archive: 32 of 122 lap-derived reps were under 150 m,
# affecting 17 of 22 sets, and a 9 m fragment beside five genuine 1 km reps
# made the whole set read `varied`, which nulled its label.

def _pace_lap(dist_m, pace_s_per_km=300, intensity="ACTIVE"):
    """A lap at a plausible, constant pace — duration and distance move
    together, unlike a bare `_lap(dist, dur)` call where a test could
    accidentally clear one floor while failing to exercise the other."""
    return _lap(dist_m, dist_m * pace_s_per_km / 1000.0, intensity)


def test_lap_work_floor_reroles_a_trailing_fragment_as_cooldown():
    """The exact shape of the live defect: two real reps then a lap-clock
    fragment with no more work after it. `_lap_rep_segments` must demote
    it, not count it, and — since nothing follows it — call it `cooldown`,
    not `recovery` (there is no more work to recover FOR)."""
    laps = [_lap(600, 180, "WARMUP"), _pace_lap(1000), _pace_lap(1000),
            _pace_lap(9)]
    segs = il._lap_rep_segments(il.segments_from_laps(laps), laps)
    assert [s["role"] for s in segs] == ["warmup", "work", "work", "cooldown"]
    assert segs[1]["rep"] == 1 and segs[2]["rep"] == 2
    assert "rep" not in segs[3]


def test_lap_work_floor_reroles_leading_fragments_as_warmup():
    """The Lagrasse case: four short bouts BEFORE the one real block. Demoted
    laps that precede every surviving rep read as `warmup`, not `recovery` —
    there is nothing yet to have recovered from."""
    laps = [_pace_lap(93, 150), _pace_lap(118, 150), _pace_lap(112, 150),
            _pace_lap(105, 150), _pace_lap(3040, 260)]
    segs = il._lap_rep_segments(il.segments_from_laps(laps), laps)
    assert [s["role"] for s in segs] == ["warmup"] * 4 + ["work"]
    assert segs[4]["rep"] == 1
    assert all("rep" not in s for s in segs[:4])


def test_lap_work_floor_reroles_a_mid_set_fragment_as_recovery_and_renumbers():
    """A demoted lap BETWEEN two surviving reps reads as `recovery` — the
    established word for a gap between real work. Its removal from the rep
    count must not leave a hole in `rep` numbering: the third real rep is
    still numbered 3, not 4."""
    laps = [_pace_lap(1000), _pace_lap(1000), _pace_lap(9), _pace_lap(1000)]
    segs = il._lap_rep_segments(il.segments_from_laps(laps), laps)
    assert [s["role"] for s in segs] == ["work", "work", "recovery", "work"]
    assert [s.get("rep") for s in segs] == [1, 2, None, 3]
    # idx is untouched — segments are re-roled in place, never deleted
    assert [s["idx"] for s in segs] == [1, 2, 3, 4]


def test_lap_work_floor_leaves_short_warmup_recovery_cooldown_alone():
    """A short warmup/recovery/cooldown lap is legitimate however brief — only
    `work`-role laps carry a minimum, exactly as on the stream path (a 20 s
    recovery there is still a recovery, never dropped or re-roled)."""
    laps = [_lap(50, 15, "WARMUP"), _pace_lap(1000), _pace_lap(1000),
            _lap(20, 8, "REST"), _pace_lap(1000), _lap(30, 10, "COOLDOWN")]
    segs = il._lap_rep_segments(il.segments_from_laps(laps), laps)
    assert [s["role"] for s in segs] == \
        ["warmup", "work", "work", "recovery", "work", "cooldown"]
    assert [s.get("rep") for s in segs] == [None, 1, 2, None, 3, None]


def test_lap_work_floor_never_touches_a_non_work_role_even_by_position():
    """The floor's own contract: only `role == 'work'` segments are ever
    re-roled. A short REST lap that sits BEFORE the first real rep must stay
    `recovery` — not get relabelled `warmup` by the same position rule that
    demoted `work` laps go through, which would fire on it too if the code
    ever stopped checking the role first."""
    laps = [_lap(10, 5, "REST"), _pace_lap(1000), _pace_lap(1000)]
    segs = il._lap_rep_segments(il.segments_from_laps(laps), laps)
    assert segs[0]["role"] == "recovery"


def test_lap_work_floor_needs_both_distance_and_duration_not_either_alone():
    """The floor is an AND, exactly like `find_bouts`'s (the handoff's own M12
    notes no fixture ever separated the two there — closing that gap here
    too). A fast 200 m sprint lap clears WORK_MIN_M but not WORK_MIN_S; a
    slow, dawdling 100 m lap clears WORK_MIN_S but not WORK_MIN_M. Neither
    alone is a rep."""
    fast_sprint = _lap(200, 20)          # clears 150 m, fails 30 s
    slow_stroll = _lap(100, 60)          # clears 30 s, fails 150 m
    laps = [fast_sprint, slow_stroll]
    segs = il._lap_rep_segments(il.segments_from_laps(laps), laps)
    assert [s["role"] for s in segs] == ["recovery", "recovery"]


def test_lap_work_floor_falls_back_to_recovery_when_nothing_survives():
    """No surviving rep at all: there is no 'before the first' or 'after the
    last' to speak of, so the demoted laps read as `recovery` — moot for any
    number in the document, since the caller demotes the whole run to
    `steady` or `block` in this case (see test_all_sub_floor_laps_read_
    steady_with_no_segments) and neither counts a `recovery` segment."""
    laps = [_pace_lap(9), _pace_lap(8)]
    segs = il._lap_rep_segments(il.segments_from_laps(laps), laps)
    assert [s["role"] for s in segs] == ["recovery", "recovery"]
    assert all("rep" not in s for s in segs)


def _laps_doc(dists, summary=None, pace_s_per_km=300, laps=None):
    """A structured-laps `build_document` call for a work-rep distance list —
    the shape the live archive's buggy documents are described in.

    Pads a leading warmup lap and a short (200 m) recovery lap between each
    ACTIVE rep — a real Garmin interval workout's laps always alternate this
    way, and skipping the padding would make an all-1-km-reps fixture (like
    the '5x1km' case below) trip `laps_are_autolap`'s uniform-1-km veto for a
    reason that has nothing to do with what this test is about: that veto
    reads EVERY lap's distance regardless of role, so five bare 1000 m ACTIVE
    laps back to back look exactly like a 19 km easy run auto-lapping at
    1 km. `laps` lets a caller override with an exact lap sequence (Lagrasse's
    strides) for fixtures that need more than one pace or no padding at all."""
    if laps is None:
        laps = [_lap(2000, 2000 * 400 / 1000.0, "WARMUP")]
        for i, d in enumerate(dists):
            laps.append(_pace_lap(d, pace_s_per_km))
            if i < len(dists) - 1:
                laps.append(_lap(200, 200 * 400 / 1000.0, "REST"))
    total_s = int(sum(l["duration"] for l in laps)) + 60
    s = make_streams([(total_s, 3.0)])
    return il.build_document(s, summary or {"hasIntensityIntervals": True}, laps)


def test_five_km_reps_plus_a_trailing_fragment_recovers_five_and_the_label():
    """THE production symptom, end to end: '2km wu, 5x1km @ 5:40' — [1000,
    1000, 1000, 1000, 1000, 9]. Before this fix: found 6, varied True, label
    None. After: found 5, varied False, label '5×1 km'."""
    doc = _laps_doc([1000, 1000, 1000, 1000, 1000, 9])
    assert doc["shape"] == "reps"
    assert doc["set"]["found"] == 5
    assert doc["set"]["varied"] is False
    assert doc["label"] == "5×1 km"
    assert doc["quality"]["workDistM"] == 5000, "the fragment must not count"


def test_pyramid_survives_the_floor_with_its_shape_intact():
    """'pYRAMIDE: 1-2-1K' — [1000, 2000, 1000, 27]. The real pyramid (varied
    by design) must not be confused with the fragment that used to sit beside
    it: 3 reps, still varied, label '1-2-1 km'."""
    doc = _laps_doc([1000, 2000, 1000, 27])
    assert doc["shape"] == "reps"
    assert doc["set"]["found"] == 3
    assert doc["set"]["varied"] is True
    assert doc["label"] == "1-2-1 km"


def test_five_two_km_reps_plus_a_trailing_fragment():
    """'W14 - HM2-Training' — [2000, 2000, 2000, 2000, 2000, 3]."""
    doc = _laps_doc([2000, 2000, 2000, 2000, 2000, 3])
    assert doc["shape"] == "reps"
    assert doc["set"]["found"] == 5
    assert doc["set"]["varied"] is False
    assert doc["label"] == "5×2 km"


def test_uniform_hill_reps_recover_a_clean_label():
    """'W7 - HM-Training' — [178, 200, 176, 151, 159, 154, 160, 185, 3]. Eight
    real ~180 m hill reps plus a trailing 3 m fragment; every real rep clears
    BOTH 150 m and 30 s (230 s/km — a hard uphill effort, but not so fast
    that a 151 m rep dips under the 30 s duration floor at 27 s the way a
    naive 180 s/km pace would) so all eight survive and read as one clean
    uniform set."""
    doc = _laps_doc([178, 200, 176, 151, 159, 154, 160, 185, 3], pace_s_per_km=230)
    assert doc["shape"] == "reps"
    assert doc["set"]["found"] == 8
    assert doc["set"]["varied"] is False
    assert doc["label"] == "8×200 m"


def test_all_sub_floor_laps_read_steady_with_no_segments():
    """When every lap-tagged 'rep' fails the floor, the run is not a rep
    session at all — the contract's own rule ('a steady run still gets a
    document... no segments') must hold here too, not just on the stream
    path. Before this fix this could only happen with zero ACTIVE laps in
    the first place; the floor makes it reachable from real ACTIVE laps that
    are simply too short, so the rule needs enforcing explicitly."""
    doc = _laps_doc([9, 8, 7])
    assert doc["shape"] == "steady"
    assert doc["segments"] == []
    assert doc["set"] is None


def test_lagrasse_strides_reclassify_as_a_block_not_five_reps():
    """'Lagrasse - W12 HM-Training: Tempo' — [93, 118, 112, 105, 3040]. Four
    short bouts (~15-25 s each) too brief to be reps under the SAME floor the
    stream path has always used, then one real ~13 min tempo effort. Judged
    as warm-up strides, not noise: reclassifying this run from a false
    '5 reps' to 'block' is the correct outcome of applying one consistent
    floor everywhere, even though it costs the strides their own visibility
    as reps (see the fix report for the full discussion)."""
    laps = [_pace_lap(93, 150), _pace_lap(118, 150), _pace_lap(112, 150),
            _pace_lap(105, 150), _pace_lap(3040, 260)]
    doc = _laps_doc(None, laps=laps)
    assert doc["shape"] == "block"
    assert doc["label"] == "13 min block"
    assert doc["quality"]["workDistM"] == 3040
    # the strides are not lost from the document — just no longer counted as
    # reps or work; they are demoted to warmup ahead of the real effort
    work_roles = [s["role"] for s in doc["segments"]]
    assert work_roles == ["warmup", "warmup", "warmup", "warmup", "work"]


def test_run_walk_run_partially_survives_the_floor_a_known_limitation():
    """'Run Walk Run®' — [205, 106, 81, 145, 52, 94, 66, 118, 52, 97, 50, 111,
    42, 173, 914]. This is a Galloway run/walk, not an interval session, but
    three of its run segments (205, 173 and 914 m) happen to clear 150 m by
    chance while the rest do not, so the floor alone does NOT fix this case
    — it reads as `reps: found 3, varied` where the honest answer is neither
    'reps' nor any of these three numbers. Pinned here as a KNOWN, REPORTED
    limitation (see the fix report) rather than silently accepted: a uniform
    floor cannot distinguish 'this rep was a lap-clock artifact' from 'this
    run/walk cycle happened to be long enough,' and fixing it properly needs
    a run/walk-aware shape this change does not add."""
    doc = _laps_doc([205, 106, 81, 145, 52, 94, 66, 118, 52, 97, 50, 111, 42, 173, 914],
                     pace_s_per_km=320)
    assert doc["shape"] == "reps"
    assert doc["set"]["found"] == 3
    assert doc["set"]["varied"] is True


def test_a_single_short_work_lap_is_not_a_block():
    """The stream path has always required BLOCK_MIN_S/BLOCK_MIN_M before
    calling something a block; the laps branch called ANY surviving work lap
    one. Task 2 makes the single-survivor case common, so the asymmetry
    started mattering. 'Run Walk Run®' (2024-07-22) asserted a '1 min block'
    over a 205 m fragment of a 25 minute run/walk."""
    laps = [_step_lap(2000, 800, "WARMUP", 0),
            _step_lap(205, 62, "ACTIVE", 1),
            _step_lap(2000, 900, "COOLDOWN", 2)]
    doc = _laps_doc(None, laps=laps)
    assert doc["shape"] == "steady"
    assert doc["label"] is None
    assert doc["segments"] == [], "a steady run gets a document, no segments"
    assert doc["set"] is None


def test_a_single_long_work_lap_is_still_a_block():
    laps = [_step_lap(2000, 800, "WARMUP", 0),
            _step_lap(3000, 1118, "ACTIVE", 1),
            _step_lap(1000, 450, "COOLDOWN", 2)]
    doc = _laps_doc(None, laps=laps)
    assert doc["shape"] == "block"
    assert doc["label"] == "19 min block"


def test_a_single_work_lap_clearing_only_the_distance_arm_is_still_a_block():
    """The block test is an `or`: EITHER arm alone is enough. Every real
    fixture that reaches `block` clears BOTH arms or clears duration alone
    (2024-07-13, 801 m / 300 s) — nothing in this athlete's archive clears
    distance while failing duration, because no run over 1.5 km in the
    archive is run at a ~3:01/km pace or faster. That absence of real-data
    coverage is exactly why this synthetic case has to exist: 1600 m in
    290 s clears BLOCK_MIN_M (1600 >= 1500) while FAILING BLOCK_MIN_S
    (290 < 300), and must still read block through the distance arm alone."""
    laps = [_step_lap(2000, 800, "WARMUP", 0),
            _step_lap(1600, 290, "ACTIVE", 1),
            _step_lap(1000, 450, "COOLDOWN", 2)]
    doc = _laps_doc(None, laps=laps)
    assert doc["shape"] == "block"
    assert doc["label"] == "5 min block"


def test_a_single_work_lap_just_under_both_floors_is_not_a_block():
    """The block test is an `or` (parity with classify(), the stream path's
    version of this same rule): a work lap is a block if it clears EITHER
    the duration floor OR the distance floor. This fixture sits just under
    BOTH — 299 s (< BLOCK_MIN_S) and 1499 m (< BLOCK_MIN_M) — so it fails
    both arms and must read steady. Both arms stay separately meaningful:
    weakening either one (or dropping the floor entirely) would wrongly
    call this a block."""
    laps = [_step_lap(2000, 800, "WARMUP", 0),
            _step_lap(1499, 299, "ACTIVE", 1),
            _step_lap(1000, 450, "COOLDOWN", 2)]
    doc = _laps_doc(None, laps=laps)
    assert doc["shape"] == "steady"
    assert doc["label"] is None


def test_laps_and_stream_paths_share_the_same_reps_labelling_rule():
    """Fix 2: the laps branch must name a varied set through the SAME rule as
    the stream path (`_reps_label`, shared by both), not a second hand-rolled
    formula. Before this fix the laps branch returned `None` for every
    varied set — this pins the two paths to agree on an equivalent input so
    they cannot drift apart again."""
    dists = [1000, 2000, 1000]
    bouts = [(0, 1000), (1000, 3000), (3000, 4000)]
    assert il.label_for("reps", bouts, _flat_dist_at) == il._reps_label(dists)


def test_lap_sourced_varied_set_gets_a_label_not_none():
    """The exact user-visible symptom: before Fix 2, `build_document`'s laps
    branch returned `label: None` for every varied lap-sourced set — 21 of
    23 lap-sourced documents on the live archive had no label at all."""
    doc = _laps_doc([1000, 2000, 1000, 27])
    assert doc["set"]["varied"] is True
    assert doc["label"] is not None
    assert doc["label"] == "1-2-1 km"


def _step_lap(dist, dur, intensity, step, pace_s_per_km=300):
    """A lap carrying a workout STEP index — what a structured workout
    downloaded to the watch produces, and what `_lap` deliberately omits."""
    lap = _lap(dist, dur, intensity)
    lap["wktStepIndex"] = step
    return lap


def test_one_off_active_steps_are_not_reps():
    """The production defect of 2026-07-28. Garmin tags a warmup, a cooldown
    and a mid-workout transition ACTIVE whenever the athlete built them that
    way, and no size floor reaches them — they are LONGER than the reps.
    Only the repeated step is the set."""
    laps = [
        _step_lap(2000, 800, "ACTIVE", 0),      # warmup, tagged ACTIVE
        _step_lap(1000, 310, "ACTIVE", 1),
        _step_lap(300, 150, "RECOVERY", 2),
        _step_lap(1000, 313, "ACTIVE", 1),
        _step_lap(300, 150, "RECOVERY", 2),
        _step_lap(1000, 316, "ACTIVE", 1),
        _step_lap(2000, 1000, "ACTIVE", 4),     # cooldown, tagged ACTIVE
    ]
    doc = _laps_doc(None, laps=laps)
    assert doc["shape"] == "reps"
    assert doc["set"]["found"] == 3, "the two 2 km bookends are not reps"
    assert doc["label"] == "3×1 km"
    assert [s["role"] for s in doc["segments"]] == [
        "warmup", "work", "recovery", "work", "recovery", "work", "cooldown"]
    assert doc["quality"]["workDistM"] == 3000


def test_a_demoted_step_keeps_its_span():
    """Demotion re-roles in place — deleting would open a hole in the run that
    `_quality` and the rep-shaded chart both assume cannot exist."""
    laps = [
        _step_lap(2000, 800, "ACTIVE", 0),
        _step_lap(1000, 310, "ACTIVE", 1),
        _step_lap(300, 150, "RECOVERY", 2),
        _step_lap(1000, 313, "ACTIVE", 1),
    ]
    doc = _laps_doc(None, laps=laps)
    segs = doc["segments"]
    assert len(segs) == 4, "nothing is dropped"
    for a, b in zip(segs, segs[1:]):
        assert a["t1"] == b["t0"], f"gap in the time span: {a} -> {b}"
        assert a["d1"] == b["d0"], f"gap in the distance span: {a} -> {b}"
    assert segs[0]["distM"] == 2000, "the demoted lap keeps its own numbers"
    assert "rep" not in segs[0]
    assert [s["rep"] for s in segs if s["role"] == "work"] == [1, 2]


def test_a_varied_set_with_no_repeated_step_survives_intact():
    """'pYRAMIDE: 1-2-1K' — three distinct steps, each used once. There is no
    repeat block, so the rule must not fire and eat two thirds of the set."""
    laps = [
        _step_lap(2000, 800, "WARMUP", 0),
        _step_lap(1000, 310, "ACTIVE", 1),
        _step_lap(300, 150, "RECOVERY", 2),
        _step_lap(2000, 640, "ACTIVE", 3),
        _step_lap(300, 150, "RECOVERY", 4),
        _step_lap(1000, 315, "ACTIVE", 5),
    ]
    doc = _laps_doc(None, laps=laps)
    assert doc["set"]["found"] == 3
    assert doc["label"] == "1-2-1 km"


def test_a_lap_with_no_step_among_stepped_laps_is_demoted():
    """2026-05-29: a manual lap pressed AFTER the cooldown. It has no step
    index at all, so it was never part of the workout."""
    laps = [
        _step_lap(2000, 800, "WARMUP", 0),
        _step_lap(1000, 310, "ACTIVE", 1),
        _step_lap(300, 150, "RECOVERY", 2),
        _step_lap(1000, 313, "ACTIVE", 1),
        _step_lap(1300, 700, "COOLDOWN", 4),
        _lap(926, 420, "ACTIVE"),               # no wktStepIndex
    ]
    doc = _laps_doc(None, laps=laps)
    assert doc["set"]["found"] == 2
    assert doc["segments"][-1]["role"] == "cooldown"


def test_laps_with_no_steps_anywhere_are_untouched():
    """An unstructured run manually lapped carries no step index on any lap.
    The rule has no evidence to act on and must keep today's behaviour."""
    laps = [_lap(2000, 800, "WARMUP")] + [
        l for d in (1000, 1000, 1000)
        for l in (_pace_lap(d, 300), _lap(300, 150, "REST"))][:-1]
    doc = _laps_doc(None, laps=laps)
    assert doc["set"]["found"] == 3


def test_two_repeated_steps_are_one_alternating_set():
    """4 x [1 km hard, 1 km moderate] is ONE set with TWO repeated steps."""
    laps = [_step_lap(2000, 800, "WARMUP", 0)]
    for _ in range(3):
        laps.append(_step_lap(1000, 300, "ACTIVE", 1))
        laps.append(_step_lap(1000, 360, "ACTIVE", 2))
    doc = _laps_doc(None, laps=laps)
    assert doc["set"]["found"] == 6


def test_a_repeated_recovery_step_does_not_promote_a_one_off_work_lap():
    """`_rep_step_indices` only counts steps over WORK laps that already
    cleared the size floor (`work_idx`) — never over recovery/warmup/cooldown
    laps. Here the recovery step (2) happens to repeat twice, and a one-off
    ACTIVE transition lap coincidentally reuses that same step number (2). If
    step-counting ever looked at every lap instead of just `work_idx`, step 2
    would read as 'repeated' from the recovery laps alone and wrongly pull
    the one-off work lap into the set alongside the three genuine step-1
    reps, inflating found from 3 to 4."""
    laps = [
        _step_lap(2000, 800, "WARMUP", 0),
        _step_lap(1000, 310, "ACTIVE", 1),
        _step_lap(300, 150, "RECOVERY", 2),
        _step_lap(1000, 313, "ACTIVE", 1),
        _step_lap(300, 150, "RECOVERY", 2),
        _step_lap(1000, 316, "ACTIVE", 1),
        _step_lap(1000, 400, "ACTIVE", 2),      # one-off, reuses the RECOVERY step
        _step_lap(2000, 1000, "COOLDOWN", 4),
    ]
    doc = _laps_doc(None, laps=laps)
    assert doc["set"]["found"] == 3
    assert doc["segments"][6]["role"] != "work"


def test_no_step_on_any_work_lap_keeps_them_all_even_when_other_laps_have_one():
    """Regression (fix round 1, finding 1): the no-evidence guard tested
    `any(...)` over ALL laps, but `counts` is built over WORK laps only. When
    a non-work lap carries a `wktStepIndex` and no floor-passing work lap
    does, `counts` was empty, so `repeated` was empty too, and the old code
    fell through to `return set(counts)` — an empty set — which demoted every
    work lap and reported zero reps. Realistic trigger: the athlete starts a
    downloaded workout, abandons it after the warmup step, then manually laps
    a genuine rep set of its own with no steps at all.

    This is the same 'no usable evidence' answer branch 1 gives: an activity
    whose work laps carry no step index tells us nothing about which of them
    are reps, so the honest response is to keep them all."""
    laps = [
        _lap(1000, 300, "ACTIVE"),              # no wktStepIndex
        _step_lap(300, 150, "RECOVERY", 5),
        _lap(1000, 305, "ACTIVE"),               # no wktStepIndex
        _step_lap(300, 150, "RECOVERY", 5),
        _lap(1000, 310, "ACTIVE"),               # no wktStepIndex
    ]
    doc = _laps_doc(None, laps=laps)
    work = [s for s in doc["segments"] if s["role"] == "work"]
    assert [s["rep"] for s in work] == [1, 2, 3]


def test_interval_version_is_current():
    """A stored document is only trustworthy if its version moved whenever the
    rules that produced it did. Tasks 2-5 changed which laps are reps, what a
    lap-sourced block must clear, where GAP comes from, and the basis of
    spread and fade — every stored document must be recomputed."""
    assert il.INTERVAL_VERSION == 4
    assert il.build_document(make_streams([(600, 3.0)]), work_floor=3.0)["version"] == 4
