#!/usr/bin/env python3
"""The plan-prescription grammar against the live plan's own corpus.

The fixture (tests/fixtures/plan_vals.json) pins every distinct `val` string
the live plan contained when this change shipped — each either parses to an
exact shape or is explicitly refused (null). The currency test then holds the
fixture to the LIVE plan file: a new string the fixture does not pin fails
with its text, so the grammar can never silently drift behind the coach.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import plan_prescription as pp

FIXTURE = Path(__file__).parent / "tests" / "fixtures" / "plan_vals.json"
CORPUS = json.loads(FIXTURE.read_text(encoding="utf-8"))
PLAN = Path(__file__).parent / "plan-data.js"


def _day(*vals):
    return [{"label": "x", "val": v} for v in vals]


def test_every_corpus_string_parses_or_is_refused_exactly_as_pinned():
    for val, expected in CORPUS.items():
        got = pp.prescription_for_day(_day(val))
        assert got == expected, f"{val!r}: {got!r} != pinned {expected!r}"


def test_corpus_refuses_more_than_it_parses():
    """The honesty property in aggregate: this grammar is a narrow reader of
    a prose corpus, not a prose parser. If refusals stop being the majority,
    the grammar has started guessing."""
    refused = sum(1 for v in CORPUS.values() if v is None)
    assert refused > len(CORPUS) / 2


def test_corpus_is_current_with_the_live_plan():
    """Re-extract the distinct val strings from plan-data.js (READ-ONLY — the
    file is a live symlink) and demand every one is pinned. New coach wording
    lands here first, by name, instead of silently refusing forever."""
    if not PLAN.exists():
        import pytest
        pytest.skip("no plan-data.js in this checkout")
    live = set(re.findall(r'val:\s*"([^"]*)"', PLAN.read_text(encoding="utf-8")))
    unpinned = live - set(CORPUS)
    assert not unpinned, \
        "live plan strings the corpus does not pin: " + " | ".join(sorted(unpinned))


# ── targeted grammar cases (each mutation-proven, see notes.md) ──────────────

def test_single_pace_widens_to_a_symmetric_band():
    """`@ 5:41` is a named point, not a corridor — the band is ±5 s/km.
    Mutation: drop the widening (band [341, 341]) → red."""
    p = pp.prescription_for_day(_day("3×1 km @ 5:41"))
    assert p["paceBandS"] == [336, 346]


def test_explicit_band_is_taken_verbatim():
    p = pp.prescription_for_day(_day("4×1 km @ 5:25–5:35"))
    assert p["paceBandS"] == [325, 335]
    assert p["count"] == 4 and p["repDistM"] == 1000


def test_ascii_x_and_hyphen_range_parse_too():
    """The coach types on a phone sometimes: `x` for × and `-` for –."""
    p = pp.prescription_for_day(_day("4x1 km @ 5:25-5:35"))
    assert p and p["count"] == 4 and p["paceBandS"] == [325, 335]


def test_embedded_rep_set_wins_over_its_warmup():
    """`3 km easy · 3×400 m @ 5:41 inside` prescribes the 400s, not the 3 km.
    Mutation: parse only the string's head → red."""
    p = pp.prescription_for_day(_day("3 km easy · 3×400 m @ 5:41 inside"))
    assert p["kind"] == "reps" and p["repDistM"] == 400 and p["count"] == 3


def test_the_first_rep_set_wins_across_segments():
    """A day with warm-up / reps / cool-down segments yields the reps —
    regardless of segment order relative to steady-parseable strings."""
    p = pp.prescription_for_day(_day(
        "2 km easy @ ~6:30", "4×1 km @ 5:25–5:35", "1 km easy"))
    assert p["kind"] == "reps" and p["count"] == 4


def test_time_based_sets_carry_durations_not_distances():
    p = pp.prescription_for_day(_day("6×3 min hard (Z4 effort)"))
    assert p["repDurS"] == 180 and "repDistM" not in p
    assert p["zone"] == 4
    s = pp.prescription_for_day(_day("4×20 s fast-relaxed"))
    assert s["repDurS"] == 20 and s["paceBandS"] is None


def test_steady_target_requires_the_approx_marker():
    """`@ ~6:10` is a steady target; `@ 5:50` without `~` is a race-plan
    split and MUST be refused — the `~` is the whole discriminator.
    Mutation: accept `@` without `~` → red."""
    assert pp.prescription_for_day(_day("16 km easy @ ~6:10")) == \
        {"kind": "steady", "paceS": 370, "text": "16 km easy @ ~6:10"}
    assert pp.prescription_for_day(
        _day("km 1–4 @ 5:50 — flat, and full of people. No faster.")) is None


def test_hr_bands_are_refused_not_misread_as_pace():
    assert pp.prescription_for_day(_day("60–75 min steady @ HR ~140–150")) is None
    assert pp.prescription_for_day(_day("5 km @ conversation pace · HR ≤150")) is None


def test_empty_and_missing_segments_refuse():
    assert pp.prescription_for_day(None) is None
    assert pp.prescription_for_day([]) is None
    assert pp.prescription_for_day([{"label": "Easy"}]) is None
