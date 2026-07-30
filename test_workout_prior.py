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


def make_streams(spans, hr=150):
    """spans: [(duration_s, mps)] → columnar streams at 1 Hz (the shape
    test_interval_lens uses; duplicated because test modules stay standalone)."""
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
    return {"t": t, "d": d, "v": v, "hr": hrs}


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


# ── VETO: a prescribed easy step is never work (design D2) ───────────────────
def test_the_mistyped_warmup_is_vetoed_by_its_target_value():
    """`2026-06-05` types its warm-up `interval`, but its target VALUE is HR
    Z2 — the veto reads the value and fires anyway. The document stops
    pairing a warm-up with a tempo as `"2 reps"`: one prescribed 4 km block,
    warm-up demoted."""
    doc = build("2026-06-05", workout("2026-06-05"))
    assert doc["shape"] == "block"
    assert doc["segments"][0]["role"] == "warmup"
    work = [s for s in doc["segments"] if s["role"] == "work"]
    assert len(work) == 1 and work[0]["distM"] == 4000


def test_a_single_prescribed_rep_between_easy_bookends_is_not_a_pyramid():
    """`2026-01-16`: Z2 2 km / paced 1 km / Z2 2 km read `"2-1-2 km", found 3,
    conf 1.00` — one prescribed rep rendered as a three-rep pyramid, with
    nothing on the page suggesting it was wrong. The bookends' Z2 value
    vetoes them; the one paced kilometre is an honest small block."""
    doc = build("2026-01-16", workout("2026-01-16"))
    assert doc["shape"] == "block"
    assert doc["label"] != "2-1-2 km"
    work = [s for s in doc["segments"] if s["role"] == "work"]
    assert len(work) == 1 and work[0]["distM"] == 1000


def test_a_z2_only_prescription_reads_steady_on_the_stream_path():
    """`2025-12-24` / `2026-04-29` / `2026-04-01` are stream-sourced runs
    whose single prescribed step is HR Z2 — nothing hard was prescribed, so
    inference must not promote a fast half into a set or block. Synthetic
    streams that WOULD read as reps prove the veto does the work."""
    spans = [(300, 2.5)]
    for _ in range(5):
        spans += [(240, 4.0), (120, 2.0)]
    spans += [(300, 2.5)]
    streams = make_streams(spans)
    with_veto = il.build_document(streams, {"startTimeLocal": "2026-04-29 08:00:00"},
                                  None, workout("2026-04-29"), work_floor=3.0)
    without = il.build_document(streams, {}, None, None, work_floor=3.0)
    assert without["shape"] == "reps", "inference alone would call this a set"
    assert with_veto["shape"] in ("steady", "progression")
    assert with_veto["shape"] == "steady"


def test_z3_is_deliberately_not_vetoed():
    """`2025-12-14` (14 km @ HR Z3) reads `progression` today — a defensible
    reading of how it was executed. Z3 is not easy; vetoing it would suppress
    a true positive to fix nothing."""
    spans = [(2400, 2.6), (2400, 2.9), (1200, 3.2)]
    streams = make_streams(spans)
    doc = il.build_document(streams, {"startTimeLocal": "2025-12-14 08:00:00"},
                            None, workout("2025-12-14"), work_floor=3.4)
    plain = il.build_document(streams, {}, None, None, work_floor=3.4)
    assert plain["shape"] == "progression", "the fixture must be a progression"
    assert doc["shape"] == "progression", "a Z3 prescription changes nothing"
    # the mechanism, pinned directly: Z3 counts as HARD in the prior contract
    # (the shape assertion alone cannot catch a widened veto — progression
    # stays reachable through _is_progression with or without bouts)
    prior = il.derive_prior(workout("2025-12-14"), None)
    assert prior["hard"] is True, "a Z3 step is a work prescription"
    assert prior["vetoed"] == set()


# ── set membership by target VALUE, not type (design D3) ─────────────────────
def test_the_recovery_float_is_not_a_third_rep():
    """`2025-12-05`: three work-typed steps all on `heart.rate.zone`, being
    Z4 / Z2 / Z4 — 2×2 km with a 3-minute float, which the lens reads today
    as `"2-0.32-2 km", found 3`. The type-only rule the design first drafted
    calls this a 3-rep set; the value rule does not."""
    doc = build("2025-12-05", workout("2025-12-05"))
    assert doc["shape"] == "reps"
    assert doc["set"]["found"] == 2
    assert doc["set"]["prescribed"] == 2
    assert doc["label"] != "2-0.32-2 km"
    roles = [s["role"] for s in doc["segments"]]
    assert roles.count("work") == 2
    # the float sits BETWEEN the reps and reads as their recovery
    w1, w2 = [i for i, r in enumerate(roles) if r == "work"]
    assert "recovery" in roles[w1 + 1:w2]


def test_the_genuine_pyramid_survives_the_value_rule():
    """`2026-06-26`: three differently-sized efforts whose pace bands are
    materially the same — all three stay one varied set."""
    doc = build("2026-06-26", workout("2026-06-26"))
    assert doc["shape"] == "reps"
    assert doc["set"]["found"] == 3
    assert doc["set"]["prescribed"] == 3
    assert doc["set"]["varied"] is True
    assert doc["label"] == "1-2-1 km"


def _synth_workout(steps):
    """A minimal Connect-shaped payload for value-grouping edge cases the
    real 85 workouts do not contain."""
    return {"workoutId": 1, "updatedDate": "2026-01-01T00:00:00.0",
            "workoutSegments": [{"workoutSteps": steps}]}


def _pace_step(order, dist, lo_mps, hi_mps, key="interval"):
    return {"type": "ExecutableStepDTO", "stepOrder": order,
            "stepType": {"stepTypeKey": key},
            "endCondition": {"conditionTypeKey": "distance"},
            "endConditionValue": float(dist),
            "targetType": {"workoutTargetTypeKey": "pace.zone"},
            "targetValueOne": hi_mps, "targetValueTwo": lo_mps}


def test_materially_different_pace_bands_do_not_group():
    """Spec: steps sharing a TYPE but prescribing materially different
    intensities are not one set. Two fast 1 km reps at ~4:30/km plus a slow
    'interval'-typed kilometre at ~6:30/km: the type-only rule the design
    first drafted calls all three one set of 3; the value rule keeps the set
    at the two that share a band. No real workout in the 85 exercises this —
    the fixture is synthetic by necessity."""
    w = _synth_workout([
        _pace_step(1, 1000, 3.6, 3.8),
        _pace_step(2, 1000, 2.5, 2.6),
        _pace_step(3, 1000, 3.6, 3.8),
    ])
    prior = il.derive_prior(w, None)
    assert prior["count"] == 2, "the slow kilometre is not a third rep"
    assert prior["setSteps"] == {0, 2}


# ── ADMIT: a prescribed rep is a rep regardless of size (handoff N4) ──────────
def test_prescribed_twenty_second_strides_are_found_not_filtered():
    """`2026-07-29` (`5km easy + 4x20s strides`): all four strides sit below
    WORK_MIN_S, the floor dropped every one, and the easy 5 km was promoted
    to `"32 min block"` — asserted at 1.00 until fix-lap-confidence hedged
    it. The prescription admits them: the size floors exist to reject
    fragments the detector invented, not reps the athlete was told to run."""
    doc = build("2026-07-29", workout("2026-07-29"))
    assert doc["shape"] == "reps"
    assert doc["set"]["found"] == 4
    assert doc["set"]["prescribed"] == 4
    assert doc["label"] != "32 min block"
    # the easy 5 km is the warm-up it always was
    assert doc["segments"][0]["role"] == "warmup"
    assert doc["segments"][0]["distM"] == 5000


def test_prescribed_thirty_second_reps_are_found_not_filtered():
    """`2025-12-26` fails identically at 4×30 s → `"24 min block"`."""
    doc = build("2025-12-26", workout("2025-12-26"))
    assert doc["shape"] == "reps"
    assert doc["set"]["found"] == 4
    assert doc["set"]["prescribed"] == 4
    assert doc["label"] != "24 min block"


# ── POINT: locate from the prescription, confirm from execution (D1a) ────────
def _tempo_workout(dist_m, lo_mps, hi_mps):
    """A Z2-warmup / paced-block / Z2-cooldown prescription — the shape of
    all six POINT cases."""
    z2 = {"type": "ExecutableStepDTO", "stepOrder": 1,
          "stepType": {"stepTypeKey": "interval"},
          "endCondition": {"conditionTypeKey": "distance"},
          "endConditionValue": 2000.0,
          "targetType": {"workoutTargetTypeKey": "heart.rate.zone"},
          "zoneNumber": 2}
    return _synth_workout([
        dict(z2, stepOrder=1),
        _pace_step(2, dist_m, lo_mps, hi_mps),
        dict(z2, stepOrder=3),
    ])


def test_point_confirms_a_prescribed_block_the_floor_missed():
    """The prescription locates a window of exactly the prescribed size; the
    window's mean pace falls in the band; the document reads `block` with the
    window's boundaries — even though the calibration floor would have
    dropped every bout (8.6, closing handoff P2.3)."""
    streams = make_streams([(800, 2.5), (1379, 2.9), (700, 2.5)])
    w = _tempo_workout(4000, 2.86, 2.95)
    doc = il.build_document(streams, {"startTimeLocal": "2026-02-13 08:00:00"},
                            None, w, work_floor=3.4)
    plain = il.build_document(streams, {}, None, None, work_floor=3.4)
    assert plain["shape"] == "steady", "the floor alone misses this block"
    assert doc["shape"] == "block"
    work = [s for s in doc["segments"] if s["role"] == "work"]
    assert len(work) == 1
    assert abs(work[0]["distM"] - 4000) <= 120
    assert doc["asserts"] is True


def test_point_refuses_a_run_that_plodded_the_window():
    """Step 3 of D1a is the entire safety property: the athlete who skipped
    the workout must not have the prescribed block reported as completed."""
    streams = make_streams([(800, 2.4), (1680, 2.38), (700, 2.4)])
    w = _tempo_workout(4000, 2.86, 2.95)
    doc = il.build_document(streams, {"startTimeLocal": "2026-02-13 08:00:00"},
                            None, w, work_floor=3.4)
    assert doc["shape"] == "steady", "out of band → the athlete did not run it"


def test_point_refuses_a_substituted_rep_session_via_the_variance_guard():
    """Design open question 1: a rep set run over the prescribed stretch can
    AVERAGE into the band. A true block is flat; a hard/easy pattern is not —
    the conservative variance guard refuses to call it the prescribed block."""
    spans = [(400, 2.5)]
    for _ in range(5):
        spans += [(180, 4.2), (120, 1.2)]
    spans += [(400, 2.5)]
    streams = make_streams(spans)
    # measured: the fastest 4000 m window over this pattern averages
    # 3.086 m/s — INSIDE this band with tolerance — at cv 0.47, so the
    # variance guard is the only thing standing between the rep session and
    # a false 'prescribed block completed'
    w = _tempo_workout(4000, 2.7, 3.1)
    doc = il.build_document(streams, {"startTimeLocal": "2026-02-13 08:00:00"},
                            None, w, work_floor=3.0)
    assert doc["shape"] == "reps", \
        "the real structure survives; the substituted session is not erased"


def test_point_merged_across_a_gap_is_hedged_not_asserted():
    """`2026-01-23`'s shape in miniature: the prescribed block with a long
    standstill inside. Merging is right — '4 reps' is plainly worse — but the
    result must be hedged, which is what fix-lap-confidence's verdict exists
    to carry (D1a note, D8)."""
    streams = make_streams([(800, 2.5), (700, 2.9), (90, 0.0), (679, 2.9),
                            (700, 2.5)])
    w = _tempo_workout(4000, 2.6, 2.95)
    doc = il.build_document(streams, {"startTimeLocal": "2026-01-23 08:00:00"},
                            None, w, work_floor=3.4)
    assert doc["shape"] == "block"
    assert doc["asserts"] is False, "merged across a gap → possible, not certain"


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


# ── POINT against the six real runs (local archive streams; skips without) ───
import sqlite3

_DB = Path(__file__).parent / "activity-archive.db"
_HAS_ARCHIVE = _DB.exists()

# (date, prescribed metres) — the three tempos the lens missed entirely and
# the three it fragmented into fake sets, per the 2026-07-29 exploration.
_POINT_CASES = [
    ("2026-01-09", 2000), ("2026-02-13", 4000), ("2026-02-27", 2000),
    ("2026-01-23", 3000), ("2026-03-13", 5000), ("2026-04-03", 7000),
]


def _archive_streams(date: str):
    conn = sqlite3.connect(f"file:{_DB.as_posix()}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT summary_json, detail_streams_json FROM activities "
            "WHERE start_time_local LIKE ? AND detail_streams_json IS NOT NULL "
            "AND type_key LIKE '%run%' AND type_key NOT LIKE '%cycling%'",
            (f"{date}%",)).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1, f"{date}: expected exactly one streamed run"
    return json.loads(rows[0][0] or "{}"), json.loads(rows[0][1])


@pytest.mark.skipif(not _HAS_ARCHIVE, reason="no local activity-archive.db")
@pytest.mark.parametrize("date,dist", _POINT_CASES)
def test_point_recovers_the_six_prescribed_tempos(date, dist):
    """8.1 + 8.2, measured on the real streams: the three missed tempos and
    the three fragmented ones all read `block`, boundaries within a few
    percent of the prescribed size, with no second mechanism. The local
    archive HAS streams (it lacks only laps), so this is a legitimate
    stream-path truth test. Uses the archive-wide floor 2.7 the way
    production does — POINT must win regardless (8.6)."""
    summary, streams = _archive_streams(date)
    doc = il.build_document(streams, summary, None, workout(date),
                            work_floor=2.7)
    assert doc["shape"] == "block", f"{date}: {doc['shape']} ({doc['label']})"
    work = [s for s in doc["segments"] if s["role"] == "work"]
    assert len(work) == 1
    assert abs(work[0]["distM"] - dist) / dist <= 0.05, \
        f"{date}: window {work[0]['distM']} m vs prescribed {dist} m"


# The hedge verdicts, MEASURED rather than taken from the design: within-
# window pace cannot single out 2026-01-23 (its 304 s "gap" is a shallow jog;
# the design's clean 2026-01-09 dips below the band for longer), so hedging
# follows evidence of interruption — a deep stop or a bout-fragmented window.
# That hedges the three fragmented executions AND 2026-02-27, whose genuine
# 92 s standstill the design's trace never examined. The two uninterrupted
# tempos assert.
_POINT_VERDICTS = {
    "2026-01-09": True,      # the one uninterrupted execution of the six
    "2026-02-13": False,     # a real ~98 s break mid-tempo (two bouts, measured)
    "2026-02-27": False,     # a real 92 s stop mid-tempo (measured)
    "2026-01-23": False,     # the design's own hedge case: 4 fragments
    "2026-03-13": False,     # fragmented execution
    "2026-04-03": False,     # fragmented execution
}


@pytest.mark.skipif(not _HAS_ARCHIVE, reason="no local activity-archive.db")
@pytest.mark.parametrize("date", sorted(_POINT_VERDICTS))
def test_point_hedges_interrupted_executions_and_asserts_clean_ones(date):
    summary, streams = _archive_streams(date)
    doc = il.build_document(streams, summary, None, workout(date),
                            work_floor=2.7)
    assert doc["shape"] == "block"
    assert doc["asserts"] is _POINT_VERDICTS[date], \
        f"{date}: asserts must be {_POINT_VERDICTS[date]}"
