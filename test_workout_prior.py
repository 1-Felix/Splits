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


# ── the prior upstream of the branch (design D4) ─────────────────────────────
def build(date: str, workout_payload: dict | None = None,
          laps: list[dict] | None = None) -> dict:
    """A document from the paired fixtures — flat streams (the lap path takes
    everything from the device), real laps, real workout definition."""
    laps = laps_of(date) if laps is None else laps
    summary = dict(LAPS[date]["summary"])
    summary.setdefault("startTimeLocal", f"{date} 08:00:00")
    total_s = int(sum(float(l.get("duration") or 0) for l in laps)) + 60
    t = list(range(0, total_s, 5))
    streams = {"t": t, "v": [3.0] * len(t)}
    return il.build_document(streams, summary, laps, workout_payload)


def test_a_prescribed_set_reports_prescribed_on_the_lap_path():
    """D4: the prior is resolved BEFORE the laps/stream branch, so the lap
    document stops hardcoding prescribed: None — `2026-07-10` prescribes 5×."""
    doc = build("2026-07-10", workout("2026-07-10"))
    assert doc["shape"] == "reps"
    assert doc["set"]["found"] == 5
    assert doc["set"]["prescribed"] == 5


def test_without_a_workout_nothing_changes():
    """The guard for both producers: build_document with no workout is
    byte-identical to before the parameter existed — ingest_builder passes
    none and must be unaffected."""
    assert build("2026-07-10") == build("2026-07-10", None)
    doc = build("2026-07-10")
    assert doc["set"]["prescribed"] is None


def test_two_unprescribed_work_laps_are_not_a_set():
    """The other half of the unified floor (P2.7b retired): WITHOUT a
    prescription, two work laps meet the same 3-rep inference minimum the
    stream path has always had — two unexplained bouts are more often a hill
    and a headwind than a session. With a big surviving lap the shape falls
    to block, exactly as the stream path would read it."""
    real = laps_of("2026-07-10")
    two = real[:4] + [dict(real[11])]           # wu, rep, rec, rep, cooldown
    doc = build("2026-07-10", None, laps=two)   # NO workout
    assert doc["shape"] != "reps"
    # and WITH the prescription the same laps are an honest 2-of-5
    assert build("2026-07-10", workout("2026-07-10"), laps=two)["shape"] == "reps"


def test_a_bailed_session_reports_its_shortfall_not_steady():
    """Spec scenario (P3.1 retired): two executed reps of a prescribed four
    classify as a 2-rep set with prescribed 4 — the session the athlete gave
    up on is exactly the one the guardrail exists for. Synthetic: the first
    two reps of 2026-07-10's five, then a cooldown."""
    real = laps_of("2026-07-10")
    bailed = real[:4] + [dict(real[11])]        # wu, rep, rec, rep, cooldown
    doc = build("2026-07-10", workout("2026-07-10"), laps=bailed)
    assert doc["shape"] == "reps", "a prescribed set cut short is still a set"
    assert doc["set"]["found"] == 2
    assert doc["set"]["prescribed"] == 5


def test_an_abandoned_workout_reports_found_zero(monkeypatch):
    """Design D10: warm-up only — a real training event, not a plain easy
    run. The document reports found: 0 against the prescription."""
    real = laps_of("2026-07-10")
    abandoned = [dict(real[0])]                 # the 2 km warm-up alone
    doc = build("2026-07-10", workout("2026-07-10"), laps=abandoned)
    assert doc["set"] is not None
    assert doc["set"]["found"] == 0
    assert doc["set"]["prescribed"] == 5
