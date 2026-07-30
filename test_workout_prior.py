#!/usr/bin/env python3
"""The workout prior against REAL Garmin workout definitions.

`tests/fixtures/workouts.json` holds 28 real Connect payloads keyed by run
date, trimmed to the fields the reader consumes; `tests/fixtures/
lap_workouts.json` holds the matching executed laps. Together they pin the
step-tree reader (flattening, the FIT index rule, per-activity validation)
and every prior operation against what the athlete's own account contains —
the local activity-archive.db has NO lap payloads at all, so none of this
can lean on it.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import interval_lens as il

FIXTURES = Path(__file__).parent / "tests" / "fixtures"
WORKOUTS = json.loads((FIXTURES / "workouts.json").read_text(encoding="utf-8"))
LAPS = json.loads((FIXTURES / "lap_workouts.json").read_text(encoding="utf-8"))


def workout(date: str) -> dict:
    return WORKOUTS[date]


def laps_of(date: str) -> list[dict]:
    return LAPS[date]["laps"]


# ── the flattener and the FIT index rule (design D7) ─────────────────────────
def test_a_repeat_group_consumes_its_trailing_index():
    """Spec scenario: warm-up, a repeat of (interval, recovery), cool-down →
    positions 0, 1, 2, and 4 — position 3 is the repeat instruction itself,
    which follows the steps it repeats in the FIT encoding. `2026-07-10` is
    exactly this workout."""
    flat = il.flatten_workout(workout("2026-07-10"))
    assert [(s["index"], s["stepType"]) for s in flat] == [
        (0, "warmup"), (1, "interval"), (2, "recovery"), (4, "cooldown")]
    rep = flat[1]
    assert rep["iterations"] == 5
    assert rep["endCondition"] == "distance" and rep["endConditionValue"] == 1000.0
    assert rep["targetType"] == "pace.zone"
    assert rep["targetValueOne"] == pytest.approx(3.0303, abs=1e-3)
    assert rep["targetValueTwo"] == pytest.approx(2.8571, abs=1e-3)


def test_a_no_repeat_workout_maps_consecutive_from_zero():
    """Spec scenario: every step executable, none repeats — `2026-06-05`
    (the ACTIVE-typed-warmup trap: its warm-up step is TYPED `interval`)."""
    flat = il.flatten_workout(workout("2026-06-05"))
    assert [s["index"] for s in flat] == [0, 1, 2]
    assert all(s["iterations"] is None for s in flat)
    # the mistyping the veto has to survive: step 0 is Z2 but typed interval
    assert flat[0]["stepType"] == "interval"
    assert flat[0]["targetType"] == "heart.rate.zone"
    assert flat[0]["zoneNumber"] == 2


def test_the_strides_workout_reproduces_its_lap_indices():
    """`2026-07-29`: easy 5 km (0), rest (1), repeat of (stride 2, recovery 3)
    consuming 4, cooldown (5) — the executed laps carry exactly {0,1,2,3,5}."""
    flat = il.flatten_workout(workout("2026-07-29"))
    assert [s["index"] for s in flat] == [0, 1, 2, 3, 5]
    observed = {l.get("wktStepIndex") for l in laps_of("2026-07-29")
                if l.get("wktStepIndex") is not None}
    assert observed <= {s["index"] for s in flat}
    strides = flat[2]
    assert strides["iterations"] == 4
    assert strides["endCondition"] == "time" and strides["endConditionValue"] == 20.0


# The one legitimately unmappable pair in the fixture population, and it is
# the STALE-EDIT case D5 exists for: workout 1357916773 was edited on
# 2025-11-14 (its first one-off interval step removed), so the stored payload
# has four executable steps where 2025-10-17's execution observed five
# ({0,1,2,3,5}). The all-or-nothing validation catches the edit STRUCTURALLY
# — the run falls back to inference — while 2025-11-14, run after the edit,
# maps cleanly against the very same payload.
STALE_EDIT = {"2025-10-17"}


@pytest.mark.parametrize("date", sorted(set(WORKOUTS) & set(LAPS)))
def test_every_fixture_workout_maps_all_observed_lap_indices(date):
    """The whole paired population: every wktStepIndex the watch recorded
    lands on a flattened step — except the known stale edit, where refusing
    the prior is the correct answer."""
    steps = il.workout_steps_for(laps_of(date), workout(date))
    if date in STALE_EDIT:
        assert steps is None, f"{date}: an edited workout must not half-apply"
        return
    assert steps is not None, f"{date}: the mapping must validate"
    observed = {l.get("wktStepIndex") for l in laps_of(date)
                if l.get("wktStepIndex") is not None}
    assert observed <= set(steps)


def test_the_stale_edit_pair_shares_one_workout():
    """The same banked payload validates for the run after the edit and is
    refused for the run before it — per-run trust, not per-workout."""
    assert workout("2025-10-17")["workoutId"] == workout("2025-11-14")["workoutId"]
    assert il.workout_steps_for(laps_of("2025-10-17"), workout("2025-10-17")) is None
    assert il.workout_steps_for(laps_of("2025-11-14"), workout("2025-11-14")) is not None


def test_an_unmappable_index_discards_the_prior_entirely():
    """Spec scenario (D7): a lap carrying an index no flattened step has means
    NO prior for that activity — a partial or best-guess mapping is never
    used, because a half-applied prior looks authoritative."""
    broken = [dict(l) for l in laps_of("2026-07-10")]
    broken[1]["wktStepIndex"] = 99
    assert il.workout_steps_for(broken, workout("2026-07-10")) is None


def test_laps_with_no_indices_still_get_no_step_mapping_but_not_a_veto():
    """No observed index at all: the mapping trivially validates (there is
    nothing to contradict) and returns the steps — the prior can still
    contribute counts and targets even when the watch recorded manual laps."""
    bare = [{k: v for k, v in l.items() if k != "wktStepIndex"}
            for l in laps_of("2026-07-10")]
    steps = il.workout_steps_for(bare, workout("2026-07-10"))
    assert steps is not None and 1 in steps
