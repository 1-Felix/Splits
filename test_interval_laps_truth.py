#!/usr/bin/env python3
"""The lap path against REAL Garmin lap payloads.

The local activity-archive.db carries no lap data at all — the backfill ran on
the NUC and was never copied down — so test_interval_truth.py cannot reach this
code path. This fixture is the archive's entire lap-sourced population as of
2026-07-28 — every activity whose laps read as structured under
`laps_are_structured` itself, not a hand-picked list of dates — trimmed to the
fields the engine reads: 23 workouts, of which 8 are the known defects this
change corrects and the rest are controls it must leave alone. (An earlier cut
of this fixture hardcoded 12 dates — the 8 defects plus 4 controls — which
made the two whole-population tests below iterate a curated subset while
reading as exhaustive; extending the fixture to the genuine population is what
makes them honest.)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import interval_lens as il

FIXTURE = Path(__file__).parent / "tests" / "fixtures" / "lap_workouts.json"
WORKOUTS = json.loads(FIXTURE.read_text(encoding="utf-8"))


def load_workout(date: str) -> tuple[dict, list[dict]]:
    """`(summary, laps)` for one archived workout, by its local date."""
    w = WORKOUTS[date]
    return w["summary"], w["laps"]


def build(date: str) -> dict:
    """The document this workout's laps produce. Streams are a flat 3.0 m/s
    grid over the run's whole elapsed span: the lap path takes boundaries,
    roles and per-lap statistics from the device, so the stream only has to be
    long enough to index into. `speed_series` (via `_series`) requires parallel
    `t` and `v` lists, not `[t, speed]` pairs."""
    summary, laps = load_workout(date)
    total_s = int(sum(float(l.get("duration") or 0) for l in laps)) + 60
    t = list(range(0, total_s, 5))
    streams = {"t": t, "v": [3.0] * len(t)}
    return il.build_document(streams, summary, laps)


def test_every_fixture_workout_is_read_as_structured():
    """The gate before any of the rules below: if laps_are_structured stopped
    firing, every assertion in this file would pass against a stream-derived
    document and prove nothing."""
    for date in WORKOUTS:
        summary, laps = load_workout(date)
        assert il.laps_are_structured(summary, laps) is True, \
            f"{date} must take the lap path"


@pytest.mark.parametrize("date,found,label", [
    ("2026-04-10", 3, "3×2 km"),      # was 5×2 km — warmup and cooldown counted
    ("2026-03-20", 5, "5×1 km"),      # was "7 reps" — both 2 km bookends counted
    ("2025-12-12", 6, "6×300 m"),     # was 7×300 m — a jog-in counted
    ("2026-05-29", 4, "4×1 km"),      # was 5×1 km — a post-cooldown lap counted
    ("2025-10-17", 6, None),          # was "8 reps"; label asserted separately
    ("2026-02-06", 6, "6×0.23 km"),   # was "8 reps" — a 1500 m ACTIVE warmup,
                                       # a 1500 m ACTIVE cooldown and a
                                       # transition all counted. Label reads
                                       # a sub-km distance in km rather than
                                       # m; that is existing label-formatting
                                       # behaviour, out of scope here — pinned
                                       # as-is, not fixed.
])
def test_real_workouts_recover_their_true_rep_count(date, found, label):
    doc = build(date)
    assert doc["shape"] == "reps"
    assert doc["set"]["found"] == found, f"{date}: {WORKOUTS[date]['name']}"
    if label is not None:
        assert doc["label"] == label


@pytest.mark.parametrize("date,found,label", [
    ("2025-11-21", 8, "8×200 m"),     # eight genuine 90 s hill reps
    ("2026-06-26", 3, "1-2-1 km"),    # the pyramid: no repeated step
    ("2026-07-10", 5, "5×1 km"),      # already correct before this change
])
def test_correct_workouts_are_left_alone(date, found, label):
    doc = build(date)
    assert doc["set"]["found"] == found, f"{date} must not change"
    assert doc["label"] == label


@pytest.mark.parametrize("date,shape", [
    ("2024-07-22", "steady"),   # Run Walk Run® — 205 m / 62 s, fails BOTH
                                 # arms; handoff P2.7a
    ("2024-07-13", "block"),    # Einstufungslauf — 801 m / exactly 300 s;
                                 # fails the distance arm (801 < 1500) but
                                 # clears the duration arm (>= BLOCK_MIN_S)
                                 # on the boundary itself, so the `or` makes
                                 # it a block
    ("2025-12-19", "block"),    # W11 HM-Training: Tempo — 1500 m / 828 s;
                                 # sits exactly on BLOCK_MIN_M, the only
                                 # archived workout that reads "block"
    ("2026-06-26", "reps"),     # the pyramid is untouched
])
def test_real_blocks_meet_the_block_floor(date, shape):
    assert build(date)["shape"] == shape


def test_real_reps_carry_a_device_gap():
    """Every fixture lap has avgGradeAdjustedSpeed, so no real rep should be
    falling back — the GAP column was empty on precisely the athlete's genuine
    workout days before it was filled at all."""
    doc = build("2026-07-10")
    work = [s for s in doc["segments"] if s["role"] == "work"]
    assert work and all(s["gapS"] is not None for s in work)


def test_lifting_the_size_floor_flips_the_strides_run_survivors():
    """Design D2 of fix-lap-confidence, the MATERIAL case. '5km easy + 4x20s
    strides': the four prescribed 20 s strides all sit below WORK_MIN_S, so
    the size floor leaves only the easy 5 km standing (lap 0) and it becomes
    the reported '32 min block'. Lift the floor and the repeated stride step
    takes over — the survivor set flips to the four strides. The shape
    depends on the discard, so the discard is material and the document must
    hedge."""
    summary, laps = load_workout("2026-07-29")
    segs = il.segments_from_laps(laps)
    with_floor, _, _ = il._lap_survivors(segs, laps)
    lifted, _, _ = il._lap_survivors(segs, laps, size_floor=False)
    assert with_floor == {0}, "the easy 5 km is the sole survivor today"
    assert lifted == {2, 4, 6, 8}, "the four prescribed strides"
    assert il._size_discard_is_material(segs, laps) is True


def test_lifting_the_size_floor_flips_the_lagrasse_survivors():
    """The same failure a season earlier: 'W12 HM-Training: Tempo' prescribed
    4×30 s; the floor drops all four and the 3 km tempo bookend becomes a
    '24 min block'."""
    summary, laps = load_workout("2025-12-26")
    segs = il.segments_from_laps(laps)
    with_floor, _, _ = il._lap_survivors(segs, laps)
    lifted, _, _ = il._lap_survivors(segs, laps, size_floor=False)
    assert with_floor == {9}, "the tempo bookend is the sole survivor today"
    assert lifted == {1, 3, 5, 7}, "the four prescribed 30 s reps"
    assert il._size_discard_is_material(segs, laps) is True


@pytest.mark.parametrize("date", ["2026-07-10", "2026-06-05"])
def test_a_routine_trailing_fragment_is_immaterial(date):
    """Design D2, the IMMATERIAL case: both runs end with a metres-long lap
    the athlete's stop press produced. It carries no `wktStepIndex`, so the
    STEP rule drops it whether or not the size floor exists — the survivor
    set is identical with the floor lifted, the discard decided nothing, and
    the document may keep asserting."""
    summary, laps = load_workout(date)
    segs = il.segments_from_laps(laps)
    with_floor, size_disc, _ = il._lap_survivors(segs, laps)
    lifted, _, _ = il._lap_survivors(segs, laps, size_floor=False)
    assert size_disc, f"{date} must actually have a size discard to test"
    assert with_floor == lifted
    assert il._size_discard_is_material(segs, laps) is False


def test_no_real_workout_loses_span_coverage():
    """Across every fixture: demotion never deletes."""
    for date in WORKOUTS:
        doc = build(date)
        segs = doc["segments"]
        if not segs:
            continue
        assert len(segs) == len(load_workout(date)[1]), f"{date}: a lap vanished"
        for a, b in zip(segs, segs[1:]):
            assert a["t1"] == b["t0"] and a["d1"] == b["d0"], f"{date}: gap"


def test_set_stats_agrees_with_the_laps_branch_on_the_same_rep_paces():
    """Both producers must land on the same cv/fade for the same rep paces —
    not merely be internally consistent with themselves.

    The laps branch computes `paceCvPct`/`fadePct` with its own inline
    formula, straight from each surviving lap's own `paceS` (raw averageSpeed,
    since §5). `set_stats` is the stream path's equivalent — its own formula,
    over whatever `raw` grid the caller hands it. This test reconstructs a
    synthetic stream-path run whose RAW grid holds exactly `2026-04-10`'s
    lap-derived rep paces, and whose DETECTION grid (`series`/`gaps`) is
    deliberately something else — a run that never happened, at a pace no rep
    here has — so the two producers can only agree if `set_stats` really is
    computing cv/fade from `raw`, not from `series`. That is the exact
    regression this guards: `set_stats` used to ride the detection grid for
    cv/fade (design D5's pre-Task-5 basis), which this fixture's real
    `2026-04-10` document was itself corrupted by — see the module docstring's
    Task 5 note.

    (`test_spread_and_fade_are_measured_on_the_same_signal_as_the_bars` in
    test_interval_lens.py covers the stream half of this same basis from a
    hand-built fixture; this test is what proves the laps branch agrees with
    it on real rep numbers.)"""
    doc = build("2026-04-10")
    reps = doc["set"]["reps"]
    assert len(reps) >= 2

    raw, series, gaps, bouts = [], [], [], []
    t = 0
    for r in reps:
        mps = 1000.0 / r["paceS"]
        for _ in range(r["durS"]):
            raw.append(mps)
            series.append(9.9)   # a detection pace no real rep here ran at
            gaps.append(9.9)
        bouts.append((t, t + r["durS"]))
        t += r["durS"]

    stats = il.set_stats(bouts, series, lambda s: 0.0, hr=None, raw=raw, gaps=gaps)
    assert [rr["paceS"] for rr in stats["reps"]] == [r["paceS"] for r in reps], \
        "sanity: the synthetic bouts reproduce the laps branch's own rep paces"
    assert stats["paceCvPct"] == doc["set"]["paceCvPct"]
    assert stats["fadePct"] == doc["set"]["fadePct"]


@pytest.mark.parametrize("date,max_cv,max_abs_fade", [
    ("2026-04-10", 3.0, 2.0),    # 3x2 km, was cv 14.8 / fade +17.5
    ("2026-03-20", 4.0, 4.0),    # 5x1 km, was cv 19.5 / fade +18.0
    ("2025-12-12", 6.0, 6.0),    # 6x300 m, was fade +37.1
    ("2026-05-29", 4.0, 2.0),    # 4x1 km, was cv 10.6 / fade +30.5
])
def test_corrected_sets_report_sane_spread(date, max_cv, max_abs_fade):
    """The fabricated spread and fade were the visible damage — a genuine
    tempo set does not fade 17% across its reps."""
    st = build(date)["set"]
    assert st["paceCvPct"] <= max_cv, f"{date}: {st['paceCvPct']}%"
    assert abs(st["fadePct"]) <= max_abs_fade, f"{date}: {st['fadePct']}%"
