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


_NOTATION_RE = re.compile(r"[×x]\s*\d+(?:\.\d+)?\s*(?:km|m|min|s)\b|@\s*~")


def test_the_grammar_never_parses_a_string_carrying_no_notation():
    """The honesty property in aggregate: this grammar is a narrow reader of a
    prose corpus, not a prose parser. Every string it accepts must carry an
    explicit prescription mark — a rep set (`N×M unit`) or a steady target
    (`@ ~`). Prose alone must never yield a prescription.

    This replaced a "refusals must stay the majority" ratio on 2026-08-05.
    That ratio was a proxy for the same property, and the second live plan
    falsified it without the grammar changing a byte: the beginner plan
    generates one `N min jog @ ~pace` string per week per pace, so ~40
    legitimately parseable strings landed at once and refusals fell to
    66/139. Corpus composition, not a widening grammar. This states the
    property directly, so it cannot drift with the corpus."""
    for val, parsed in CORPUS.items():
        if parsed is not None:
            assert _NOTATION_RE.search(val), \
                f"parsed a string with no prescription notation: {val!r}"


def test_refusals_remain_a_substantial_share_of_the_corpus():
    """The weaker aggregate guard the ratio was reaching for: a grammar that
    started swallowing prose would refuse almost nothing. A third is far below
    where either live plan sits (66/139 = 47% on 2026-08-05) and far above
    where a guessing grammar would land."""
    refused = sum(1 for v in CORPUS.values() if v is None)
    assert refused > len(CORPUS) / 3


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


# ── duration reading (honest-compliance D3) ──────────────────────────────────

def _seg(label, val, rest=None):
    s = {"label": label, "val": val}
    if rest:
        s["rest"] = rest
    return s


def test_duration_plain_minutes_ignores_warmup_and_cooldown():
    """The walk warm-up and cool-down are not the session — and are usually
    not even recorded, because the watch starts when the running starts.
    Mutation: include them (28 min instead of 20) → red."""
    day = [_seg("Warm-up", "5 min brisk walk"),
           _seg("Continuous", "20 min jog @ ~9:20"),
           _seg("Cool-down", "3 min walk")]
    assert pp.duration_for_day(day) == 20 * 60


def test_duration_rep_set_adds_the_recoveries_between_reps():
    """8×1 min jog with 1 min walk between is 8 work + 7 recovery = 15 min —
    never 8 recoveries. Mutation: count × rest → red."""
    day = [_seg("Warm-up", "5 min brisk walk"),
           _seg("Reps", "8×1 min jog", rest="1 min walk"),
           _seg("Cool-down", "3 min walk")]
    assert pp.duration_for_day(day) == (8 * 60) + (7 * 60)


def test_duration_asymmetric_blocks_are_summed_not_multiplied():
    """`2×15/10 min` is 15 then 10 — the leading number COUNTS the blocks.
    Reading it as 2×15 over-states the target by 5 min and re-creates the
    exact false negative this change exists to remove. Mutation: treat it as
    count × first block → red."""
    day = [_seg("Warm-up", "5 min brisk walk"),
           _seg("Blocks", "2×15/10 min jog", rest="2 min walk between"),
           _seg("Cool-down", "3 min walk")]
    assert pp.duration_for_day(day) == (15 + 10 + 2) * 60


def test_duration_symmetric_blocks_still_sum_correctly():
    day = [_seg("Blocks", "2×10/10 min jog", rest="2 min walk between")]
    assert pp.duration_for_day(day) == (10 + 10 + 2) * 60


def test_duration_block_count_must_match_the_blocks_written():
    """`3×10/10 min` is self-contradictory — three blocks were announced and
    two written. Refuse rather than pick one reading."""
    assert pp.duration_for_day([_seg("Blocks", "3×10/10 min jog")]) is None


def test_duration_range_takes_the_lower_bound():
    """`30–40 min` asks for at least 30. The HR range in the same string must
    not be mistaken for a duration. Mutation: take the upper bound → red."""
    assert pp.duration_for_day(
        [_seg("Aerobic", "30–40 min easy, HR 130–150")]) == 30 * 60


def test_a_day_naming_a_distance_is_not_time_shaped():
    """A 6 km easy run with strides is a DISTANCE session that happens to
    contain seconds. Scoring it on the strides' 80 s would be absurd.
    Mutation: drop the distance guard → red."""
    day = [_seg("Warm-up", "5 min brisk walk"),
           _seg("Easy", "6 km @ conversational"),
           _seg("Strides", "4×20 s relaxed fast"),
           _seg("Cool-down", "3 min walk")]
    assert pp.duration_for_day(day) is None


def test_metres_are_a_distance_but_minutes_are_not():
    """`m` is a distance unit; the `m` inside `min` is not."""
    assert pp.duration_for_day([_seg("Reps", "3×400 m @ 5:41")]) is None
    assert pp.duration_for_day([_seg("Reps", "3×4 min @ 5:41")]) == 12 * 60


def test_unparseable_rest_contributes_zero_rather_than_refusing():
    """`walk back` is a real recovery with no readable length. Counting it as
    zero makes the target smaller — the athlete-favouring direction — while
    still scoring the day on time."""
    assert pp.duration_for_day(
        [_seg("Hills", "6×45 s uphill, easy effort", rest="walk back")]) == 6 * 45


def test_a_range_rest_takes_its_lower_bound_too():
    assert pp.duration_for_day(
        [_seg("Reps", "3×3 min", rest="2–3 min jog")]) == (3 * 180) + (2 * 120)


def test_one_unreadable_scoring_segment_refuses_the_whole_day():
    """Partial arithmetic over a half-understood day is worse than falling
    back to km. Mutation: sum only the readable segments → red."""
    day = [_seg("Continuous", "20 min jog @ ~9:20"),
           _seg("Finish", "then whatever feels right")]
    assert pp.duration_for_day(day) is None


def test_no_segments_and_no_scoring_segments_refuse():
    assert pp.duration_for_day(None) is None
    assert pp.duration_for_day([]) is None
    assert pp.duration_for_day([_seg("Warm-up", "5 min brisk walk"),
                                _seg("Cool-down", "3 min walk")]) is None


def test_duration_reading_never_disturbs_the_prescription_reading():
    """The two readers are independent: a day can be time-shaped AND carry a
    steady prescription, and neither answer changes the other."""
    day = [_seg("Continuous", "20 min jog @ ~9:20")]
    assert pp.duration_for_day(day) == 1200
    assert pp.prescription_for_day(day) == {
        "kind": "steady", "paceS": 560, "text": "20 min jog @ ~9:20"}
