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
