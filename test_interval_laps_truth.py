#!/usr/bin/env python3
"""The lap path against REAL Garmin lap payloads.

The local activity-archive.db carries no lap data at all — the backfill ran on
the NUC and was never copied down — so test_interval_truth.py cannot reach this
code path. These twelve workouts are the archive's entire lap-sourced
population as of 2026-07-28, trimmed to the fields the engine reads, and they
pin both the sessions this change corrects and the ones it must leave alone.
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
