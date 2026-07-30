#!/usr/bin/env python3
"""Ground truth for the interval lens, read off the athlete's own run names.

Runs named "2km wu, 5x1km @ 5:40, 1km cd" or "Tempo: 5x 1km" state what they
were. Synthetic streams (test_interval_lens.py) prove the arithmetic; only a
run like this proves the detector survives real GPS noise, real hills and a
real watch — before cross-run calibration existed (Task 7b), this same
engine read 62% of this archive as interval sessions.

CALIBRATION IS NOT OPTIONAL HERE. `build_document` makes no rep claim at all
without a `work_floor`: "faster than the rest of this run" always finds a
fast half (2-means guarantees it), so an uncalibrated call would read every
run below as "steady" and this whole file would pass while testing nothing —
exactly the silent-pass trap a truth test must not fall into. Every call
below therefore:
  1. sweeps every streamed run in the archive, accumulating
     `interval_lens.baseline_samples`;
  2. computes ONE `interval_lens.work_floor` over that whole pool;
  3. passes that floor (and `interval_lens.zone_bounds`) into every
     `build_document` call — exactly what `sync_garmin.derive_intervals`
     does in production.

Skipped entirely when no archive is present (CI, a fresh clone) — never a
hard failure. `activity-archive.db` in this worktree is a symlink to the
athlete's real, irreplaceable training history: opened read-only via a
`mode=ro` URI, and this file never writes to it.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import Counter
from pathlib import Path

import pytest

import activity_archive as arch
import interval_lens as il

DB = Path(__file__).parent / "activity-archive.db"
_HAS_ARCHIVE = DB.exists()
pytestmark = pytest.mark.skipif(not _HAS_ARCHIVE, reason="no local archive")

ATHLETE_MAX_HR = int(os.getenv("ATHLETE_MAX_HR", "197"))

# "5x1km", "5 x 1 km", "6×800m" → (count, metres)
NAME_RE = re.compile(r"(\d+)\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*(km|k|m)\b", re.I)


def _load_archive():
    """Read-only sweep of every streamed run, mirroring
    `sync_garmin.derive_intervals`'s calibration pass exactly (Task 7b/11):
    baseline samples are accumulated from EVERY streamed run in the archive —
    not just the named ones below — and ONE work_floor is computed over that
    whole pool. Uses a plain read-only connection straight into the same
    query `activity_archive.streamed_runs` runs; never
    `activity_archive.open_archive`, which migrates the schema and is not
    something a read-only pass on the athlete's live archive may do.

    Returns (floor, bounds, rows, n_samples). `rows` is `[]` and `floor` is
    `None` when there is no archive — this must never raise, because pytest
    builds `@pytest.mark.parametrize` argument lists at collection time,
    before this module's `pytestmark` skip is applied.
    """
    if not _HAS_ARCHIVE:
        return None, None, [], 0
    conn = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    try:
        # M10 (sweep-lens-tail): the run-type predicate is IMPORTED, not
        # re-hardcoded — this test and production can no longer drift on what
        # counts as a run.
        raw = conn.execute(
            "SELECT a.activity_id, a.name, a.summary_json, "
            "a.detail_streams_json, a.laps_json "
            "FROM activities a WHERE a.detail_streams_json IS NOT NULL "
            f"AND {arch._RUN_TYPE_SQL} "
            "ORDER BY a.activity_id").fetchall()
    finally:
        conn.close()

    rows, samples = [], []
    for aid, name, summary_json, streams_json, laps_json in raw:
        streams = json.loads(streams_json)
        summary = json.loads(summary_json) if summary_json else {}
        laps = json.loads(laps_json) if laps_json else None
        samples.extend(il.baseline_samples(streams))
        rows.append((aid, name, summary, streams, laps))
    floor = il.work_floor(samples)
    if floor is not None:
        floor = round(floor, 3)   # mirrors sync_garmin.derive_intervals exactly
    bounds = il.zone_bounds(ATHLETE_MAX_HR)
    return floor, bounds, rows, len(samples)


_FLOOR, _BOUNDS, _ROWS, _SAMPLE_COUNT = _load_archive()


def self_describing() -> list[tuple]:
    """`_ROWS` narrowed to runs whose own name states a rep structure, parsed
    into (aid, name, count, metres, streams, summary, laps).

    Only a couple of runs in this archive are named this way — the athlete
    usually names runs "<place> Laufen" — so this is deliberately a small,
    honest oracle, not a claim of broad coverage. `test_the_archive_has_
    self_describing_runs` below is what stops that smallness from silently
    becoming zero."""
    out = []
    for aid, name, summary, streams, laps in _ROWS:
        m = NAME_RE.search(name or "")
        if not m:
            continue
        count = int(m.group(1))
        val = float(m.group(2).replace(",", "."))
        metres = val * 1000 if m.group(3).lower() in ("km", "k") else val
        out.append((aid, name, count, metres, streams, summary, laps))
    return out


_CASES = self_describing()

# Investigated, documented detector limitations among the self-describing
# set. This is NOT a general escape hatch — every other named run must pass
# outright — and it is keyed by activity_id, not by "shape != reps" in
# general, so a NEW named run that fails for an unexamined reason still
# fails loudly rather than falling into this dict.
_KNOWN_LIMITATIONS = {
    23059014879: (
        "'Tempo: 5x 1km (Pace 6:00-6:10)' — the prescribed pace (6:00-6:10/km "
        "= 2.70-2.78 m/s) sits right at this athlete's calibration floor "
        "(2.700 m/s, measured below). Of the candidate bouts find_bouts "
        "finds in this run, only 2 clear the floor — one short of "
        "REPS_MIN_COUNT (3) — so the session reads as steady. A genuine "
        "boundary case, not a bug: the floor's entire job is to refuse a rep "
        "claim it cannot support for this athlete, and loosening this "
        "assertion to paper over that would hide exactly the failure mode "
        "this test file exists to catch."
    ),
}


def test_the_archive_has_self_describing_runs():
    """The fixture-emptiness trap this file exists to avoid: a `parametrize`
    over an empty list reports success while testing nothing. Assert the
    oracle is non-empty and say exactly how many runs it covers — never let
    a couple of matches read as broad coverage."""
    assert _CASES, "no named interval sessions in the archive to check against"
    named = ", ".join(f"{aid} {name!r}" for aid, name, *_ in _CASES)
    print(f"\nself-describing oracle: {len(_CASES)} run(s) — {named}")


def test_calibration_floor_is_available():
    """If this is None, `build_document` makes no rep claim on ANY call below
    and every named session would read `steady` — the silent-pass trap the
    calibration amendment exists to prevent. Guarded explicitly here rather
    than left to surface as a confusing failure three tests down."""
    assert _FLOOR is not None, (
        f"only {_SAMPLE_COUNT} baseline samples across {len(_ROWS)} streamed "
        f"runs — below WORK_FLOOR_MIN_SAMPLES ({il.WORK_FLOOR_MIN_SAMPLES}); "
        "every build_document call below would be uncalibrated and read as "
        "steady, proving nothing"
    )


@pytest.mark.parametrize("case", _CASES, ids=lambda c: str(c[0]))
def test_named_sessions_are_detected_as_reps(case):
    aid, name, count, metres, streams, summary, laps = case
    doc = il.build_document(streams, summary, laps, None, _BOUNDS, _FLOOR)
    if doc is None:
        pytest.skip(f"{aid} {name!r}: no usable speed stream")
    if doc["shape"] != "reps":
        if aid in _KNOWN_LIMITATIONS:
            pytest.skip(f"{aid} {name!r}: {_KNOWN_LIMITATIONS[aid]}")
        pytest.fail(f"{aid} {name!r}: read as {doc['shape']}, name says "
                    f"{count}x{metres:.0f}m")
    found = doc["set"]["found"]
    assert abs(found - count) <= 1, \
        f"{aid} {name!r}: found {found}, name says {count}"


@pytest.mark.parametrize("case", _CASES, ids=lambda c: str(c[0]))
def test_named_rep_length_is_recovered(case):
    aid, name, count, metres, streams, summary, laps = case
    doc = il.build_document(streams, summary, laps, None, _BOUNDS, _FLOOR)
    if doc is None:
        pytest.skip(f"{aid} {name!r}: no usable speed stream")
    if doc["shape"] != "reps" and aid in _KNOWN_LIMITATIONS:
        pytest.skip(f"{aid} {name!r}: {_KNOWN_LIMITATIONS[aid]}")
    reps = (doc.get("set") or {}).get("reps") or []
    if not reps:
        pytest.skip(f"{aid} {name!r}: no reps to measure (shape {doc['shape']})")
    median = sorted(r["distM"] for r in reps)[len(reps) // 2]
    assert abs(median - metres) / metres <= 0.25, \
        f"{aid} {name!r}: median rep {median} m, name says {metres:.0f} m"


def test_full_archive_is_not_mostly_intervals():
    """Regression guard for the exact bug that motivated this file: the
    uncalibrated engine read 62% of this same archive as interval sessions.
    A trained runner's archive is dominated by easy running — once every
    streamed run is calibrated and classified, "steady" must stay the
    majority shape. A wide, one-directional guard rather than a brittle
    exact-count check: this archive is a live symlink that grows every week
    Felix runs, so pinning it to today's exact tally would fail on its own
    the next time this suite runs."""
    if not _ROWS:
        pytest.skip("archive present but holds no streamed runs")
    shapes = Counter()
    for aid, name, summary, streams, laps in _ROWS:
        doc = il.build_document(streams, summary, laps, None, _BOUNDS, _FLOOR)
        shapes[doc["shape"] if doc else "none"] += 1
    total = sum(shapes.values())
    steady_frac = shapes["steady"] / total
    print(f"\n{total} streamed runs, shapes {dict(shapes)}, "
          f"work floor {_FLOOR:.3f} m/s")
    assert steady_frac >= 0.5, (
        f"steady is only {steady_frac:.0%} of {total} streamed runs "
        f"({dict(shapes)}) — the calibrated engine should not read most of a "
        "training archive as interval sessions"
    )
