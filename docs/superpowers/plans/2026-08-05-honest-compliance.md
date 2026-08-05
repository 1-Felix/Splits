# Honest Compliance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the compliance engine from scoring rest days, unrecordable work, and time-prescribed sessions as failures, without hiding a single real miss from the coach.

**Architecture:** Two new terminal statuses (`rest`, `untracked`) plus a third scoring unit (duration) inside the existing `plan_compliance` scorer. Capability — "can this instance see this kind of work?" — is derived from the archive by the caller and passed into the pure `score_week()`. `COMPLIANCE_VERSION` 3 → 4 makes every frozen week rescore itself against its original snapshot on the next sync, so no data migration is needed. Consumers (validator, block lens, briefing, three dashboards) are widened to accept the new vocabulary **before** the engine emits it.

**Tech Stack:** Python 3 stdlib only (no new dependencies), SQLite, vanilla React-via-`h()` in `.dc.html` files, pytest, node `.mjs` test scripts.

**Design doc:** `docs/superpowers/specs/2026-08-05-honest-compliance-design.md` — read it first.

## Global Constraints

- **Stdlib only.** `plan_compliance.py`, `plan_prescription.py` and `activity_archive.py` take no new dependencies.
- **`score_week()` stays pure.** No I/O, no clock reads, fully deterministic for a closed week. Anything derived from the database is computed by the caller and passed in as a parameter.
- **Annotate-only quality verdicts.** `_annotate_quality` / `_quality_verdict` write `quality_json` and nothing else. They may never change `status` or `reason`.
- **Refusal is the safe state.** Any prescription the grammar cannot read returns `None` and the day keeps today's distance scoring. Never guess.
- **No Co-Authored-By or Claude attribution in commit messages.**
- **Unicode direct in JSX/HTML text**, never `\uXXXX` escapes: use `–`, `·`, `✓`, `—`, `×` literally.
- **Test runner:** `./.venv/Scripts/python.exe -m pytest <file> -v` for Python, `node <file>.mjs` for the `.mjs` suites.
- Every task ends with a commit. Commit only the files that task names.

---

## File Structure

| File | Responsibility | Touched by |
|---|---|---|
| `plan_prescription.py` | Plan-text grammar. Gains `duration_for_day()` — the only place that reads minutes out of the coach's prose. | Task 1 |
| `tests/fixtures/plan_vals.json` | Pins every distinct `val` string in both live plans to its exact parse or explicit refusal. | Task 1 |
| `validate_data.py` | Contract shape-check. Widened to accept the new statuses/kind/reason before anything emits them. | Task 2 |
| `plan_compliance.py` | The scorer. All four scoring decisions land here. | Tasks 3, 4, 5, 6, 7, 11 |
| `activity_archive.py` | Storage. Two new nullable columns, schema v15. | Task 5 |
| `block_lens.py` | Block rollup. Denominator and status vocabulary. | Task 8 |
| `coach_briefing.py` | Deterministic markdown for `/coach`. Status wording + the unverifiable-days line. | Task 9 |
| `Running Dashboard.dc.html`, `progress.dc.html`, `run.dc.html` | The three glyph maps and their reason words. | Task 10 |

---

## Task 1: Duration reading in the plan grammar

**Files:**
- Modify: `plan_prescription.py` (append after `prescription_for_day`, currently ends at line 108)
- Modify: `tests/fixtures/plan_vals.json`
- Test: `test_plan_prescription.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `plan_prescription.duration_for_day(segments: list | None) -> int | None` — total prescribed **work seconds** for a planned day, or `None` when the day is not time-shaped. Task 5 is its only caller.

**Background — the real corpus.** These are the actual `val` strings from the live beginner plan (extracted 2026-08-05, 101 distinct). The grammar below was derived from them, not invented:

| form | example | reads as |
|---|---|---|
| plain minutes | `20 min jog @ ~9:20` | 20 min |
| minute range | `30–40 min easy, HR 130–150` | 30 min (**lower bound**) |
| rep set | `8×1 min jog` + `rest: "1 min walk"` | 8×1 + 7×1 = 15 min |
| **asymmetric blocks** | `2×15/10 min jog` + `rest: "2 min walk between"` | 15 + 10 + 2 = **27 min** |
| distance | `6 km @ conversational`, `13 km easy` | **not time-shaped** |
| strides on a km day | `4×20 s relaxed fast` | irrelevant — the day has a km segment |

The asymmetric form is the trap: `2×15/10 min` is **15 min then 10 min**, *not* 2 × 15. The leading number counts the slash-separated blocks. Reading it as `count × size` would over-state the target by 5 minutes and re-create the bug this change exists to fix.

**Rules, in order, applied per segment:**

1. Segments labelled `Warm-up` or `Cool-down` (case-insensitive) are **excluded** — they are not the session, and in practice are not recorded.
2. A remaining segment naming a **distance** (`km`, or `m` not part of `min`) makes the whole day **not time-shaped** → `None`.
3. `N×A/B[/C…] min|s` → sum of the slash-separated blocks, and `N` must equal the number of blocks.
4. `N×M min|s` → `N × M`.
5. `A–B min|s` → `A` (the lower bound; the plan says 30–40, so 30 satisfies it).
6. Exactly one duration token → that duration.
7. Anything else → `None`, and the whole day refuses.

For rules 3 and 4 a parseable `rest` field adds `(blocks − 1) × rest`. **An unparseable `rest` contributes 0** — under-counting recovery makes the target smaller and therefore easier to satisfy, which is the direction this whole change deliberately errs in.

- [ ] **Step 1: Write the failing tests**

Append to `test_plan_prescription.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest test_plan_prescription.py -v -k duration`
Expected: FAIL — `AttributeError: module 'plan_prescription' has no attribute 'duration_for_day'`

- [ ] **Step 3: Implement `duration_for_day`**

Append to `plan_prescription.py`:

```python
# ──────────────────────────────────────────────────────────────────────────────
# duration reading (honest-compliance D3)
# ──────────────────────────────────────────────────────────────────────────────
# A day the coach wrote in MINUTES must be judged in minutes. The km on such a
# day is a byproduct of an assumed pace, and scoring against it marks a slower
# athlete down for ground he was never asked to cover.
#
# Warm-up and cool-down are excluded on purpose: they are not the session, and
# the watch is usually started when the running starts, so counting them
# fabricates a shortfall out of nothing.

# Segment labels whose duration is not part of the session.
_SKIP_LABELS = {"warm-up", "warmup", "cool-down", "cooldown"}

# A distance token: `km`, or `m` NOT continuing into a word (so `min` is safe).
_DIST_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:km|m)(?![a-z])", re.IGNORECASE)

# `2×15/10 min` — the leading number COUNTS the slash-separated blocks; it does
# not multiply the first one. `2×15/10` is 15 then 10, never 2 × 15.
_BLOCKS_RE = re.compile(r"(\d+)\s*[×x]\s*(\d+(?:/\d+)+)\s*(min|s)\b")

# `8×1 min` / `4×20 s`
_REP_DUR_RE = re.compile(r"(\d+)\s*[×x]\s*(\d+(?:\.\d+)?)\s*(min|s)\b")

# `30–40 min` — the lower bound is what the day asks for.
_RANGE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[–-]\s*(\d+(?:\.\d+)?)\s*(min|s)\b")

# a single bare duration
_ONE_DUR_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(min|s)\b")

_UNIT_S = {"min": 60, "s": 1}


def _rest_seconds(rest) -> int:
    """A recovery's length, or 0 when it has none we can read (`walk back`).
    Zero is the deliberate direction: a smaller target is easier to satisfy,
    and this module exists to stop manufacturing shortfalls."""
    if not isinstance(rest, str):
        return 0
    m = _RANGE_RE.search(rest)
    if m:
        return int(float(m.group(1)) * _UNIT_S[m.group(3)])
    m = _ONE_DUR_RE.search(rest)
    return int(float(m.group(1)) * _UNIT_S[m.group(2)]) if m else 0


def _segment_seconds(seg: dict) -> int | None:
    """One scoring segment's work seconds, or None if this grammar cannot read
    it — in which case the whole day refuses."""
    val = seg.get("val") or ""
    if _DIST_RE.search(val):
        return None            # a distance session: not a time question at all
    rest_s = _rest_seconds(seg.get("rest"))

    m = _BLOCKS_RE.search(val)
    if m:
        blocks = [float(b) for b in m.group(2).split("/")]
        if int(m.group(1)) != len(blocks):
            return None        # "3×10/10" announces three blocks and writes two
        unit = _UNIT_S[m.group(3)]
        return int(sum(blocks) * unit) + (len(blocks) - 1) * rest_s

    m = _REP_DUR_RE.search(val)
    if m:
        count = int(m.group(1))
        return int(count * float(m.group(2)) * _UNIT_S[m.group(3)]) + (count - 1) * rest_s

    m = _RANGE_RE.search(val)
    if m:
        return int(float(m.group(1)) * _UNIT_S[m.group(3)])

    m = _ONE_DUR_RE.search(val)
    if m:
        return int(float(m.group(1)) * _UNIT_S[m.group(2)])
    return None


def duration_for_day(segments: list | None) -> int | None:
    """Total prescribed WORK seconds for a planned day, or None when the day
    is not time-shaped (it names a distance, or carries a segment this grammar
    cannot read). Warm-up and cool-down segments are excluded.

    None is not a failure — it means "score this day on distance, as before"."""
    if not segments:
        return None
    total, seen = 0, False
    for seg in segments:
        if not isinstance(seg, dict):
            return None
        if (seg.get("label") or "").strip().lower() in _SKIP_LABELS:
            continue
        secs = _segment_seconds(seg)
        if secs is None:
            return None        # one unreadable segment refuses the whole day
        total += secs
        seen = True
    return total if seen else None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest test_plan_prescription.py -v`
Expected: PASS — the 13 new tests plus all pre-existing ones (the existing grammar is untouched).

- [ ] **Step 5: Extend the corpus fixture with the beginner plan's strings**

`tests/fixtures/plan_vals.json` currently pins 29 strings, all from the km-based plan. `test_corpus_is_current_with_the_live_plan` only checks the plan symlinked into *this* checkout, so the beginner plan's strings are unpinned. Add these entries (all refuse under `prescription_for_day` except where noted — they are duration-shaped, which is the *other* reader's job):

```json
  "5 min brisk walk": null,
  "3 min walk": null,
  "5 min walk": null,
  "8×1 min jog": {"kind": "reps", "count": 8, "paceBandS": null, "zone": null, "text": "8×1 min jog", "repDurS": 60},
  "10×1 min jog": {"kind": "reps", "count": 10, "paceBandS": null, "zone": null, "text": "10×1 min jog", "repDurS": 60},
  "7×2 min jog": {"kind": "reps", "count": 7, "paceBandS": null, "zone": null, "text": "7×2 min jog", "repDurS": 120},
  "2×10/10 min jog": {"kind": "reps", "count": 2, "paceBandS": null, "zone": null, "text": "2×10/10 min jog", "repDurS": 10},
  "20 min jog @ ~9:20": {"kind": "steady", "paceS": 560, "text": "20 min jog @ ~9:20"},
  "30–40 min easy, HR 130–150": null,
  "6 km @ conversational": null,
  "4×20 s relaxed fast": {"kind": "reps", "count": 4, "paceBandS": null, "zone": null, "text": "4×20 s relaxed fast", "repDurS": 20},
  "6×45 s uphill, easy effort": {"kind": "reps", "count": 6, "paceBandS": null, "zone": null, "text": "6×45 s uphill, easy effort", "repDurS": 45}
```

**Verify each pinned value by running the parser rather than trusting this table** — `prescription_for_day` is the authority:

```bash
./.venv/Scripts/python.exe -c "
import json, plan_prescription as pp
for v in ['8×1 min jog','2×10/10 min jog','20 min jog @ ~9:20','30–40 min easy, HR 130–150','4×20 s relaxed fast','6×45 s uphill, easy effort','6 km @ conversational','5 min brisk walk']:
    print(repr(v), '->', json.dumps(pp.prescription_for_day([{'label':'x','val':v}]), ensure_ascii=False))
"
```

Correct any entry above that disagrees with the parser's real output, then re-run:

Run: `./.venv/Scripts/python.exe -m pytest test_plan_prescription.py -v`
Expected: PASS, including `test_corpus_refuses_more_than_it_parses` (refusals must stay the majority — count them if it goes red and add the remaining refused strings from the corpus listing in the design doc).

- [ ] **Step 6: Commit**

```bash
git add plan_prescription.py test_plan_prescription.py tests/fixtures/plan_vals.json
git commit -m "feat(plan): read prescribed work minutes out of a planned day

duration_for_day() answers 'how long was this session meant to be' for a day
the coach wrote in minutes, excluding the walk warm-up and cool-down — which
are not the session and are usually not recorded.

The asymmetric block form is the one that had to be got right: 2×15/10 min is
15 then 10, not 2 × 15. The leading number counts the blocks. Reading it the
other way over-states the target by 5 minutes.

A day naming any distance is not time-shaped and refuses, so a 6 km easy run
with strides is never scored on the strides."
```

---

## Task 2: Widen the contract validator

Done before anything emits the new vocabulary — a validator must accept a value before a producer writes it, or the first sync after deploy fails validation.

**Files:**
- Modify: `validate_data.py:175`, `:196`, `:198`, `:202`
- Test: `test_plan_compliance.py` (the existing `test_validate_data_compliance_shape`)

**Interfaces:**
- Consumes: nothing.
- Produces: `validate_data.validate_compliance` accepts statuses `rest` / `untracked`, `plannedKind` `rest`, `reason` `duration`, and numeric `plannedS` / `actualS`.

- [ ] **Step 1: Write the failing test**

In `test_plan_compliance.py`, replace the body of `test_validate_data_compliance_shape` (currently at line 451) with this version — it keeps every existing assertion and adds the new vocabulary:

```python
def test_validate_data_compliance_shape():
    import validate_data as vd
    good = {"complianceVersion": 1,
            "days": [{"date": "2026-07-01", "wk": "Wk 2", "plannedKind": "run",
                      "plannedKm": 5, "plannedLoad": "Easy", "title": "Easy Run",
                      "status": "done", "actualKm": 5.1, "actualPaceS": 411,
                      "actualHr": 145},
                     {"date": "2026-07-02", "wk": "Wk 2", "plannedKind": None,
                      "plannedKm": None, "plannedLoad": None, "title": None,
                      "status": "unplanned", "actualKm": 4.0},
                     # honest-compliance: a rest day is satisfied by resting,
                     # work this instance cannot see is neither done nor missed,
                     # and a time-scored day carries seconds beside its km
                     {"date": "2026-07-03", "wk": "Wk 2", "plannedKind": "rest",
                      "plannedKm": 0, "plannedLoad": "Easy", "title": "Rest",
                      "status": "rest"},
                     {"date": "2026-07-04", "wk": "Wk 2", "plannedKind": "strength",
                      "plannedKm": 0, "plannedLoad": "Easy", "title": "Mobility",
                      "status": "untracked"},
                     {"date": "2026-07-05", "wk": "Wk 2", "plannedKind": "run",
                      "plannedKm": 3.4, "plannedLoad": "Easy", "title": "2 × 10 min",
                      "status": "partial", "reason": "duration",
                      "plannedS": 1320, "actualS": 900,
                      "actualKm": 2.4, "actualPaceS": 578, "actualHr": 151}],
            "weeks": [{"wk": "Wk 2", "mon": "2026-06-29", "sun": "2026-07-05",
                       "plannedKm": 32, "actualKm": 9.1, "runsPlanned": 4,
                       "runsDone": 1}]}
    e = []
    vd.validate_compliance(good, e)
    assert e == [], f"well-formed block must validate: {e}"

    for mutate, expect in (
        (lambda c: c["days"][0].update(status="acing_it"), "invalid status"),
        (lambda c: c["days"][0].update(reason="vibes"), "invalid reason"),
        (lambda c: c["days"][1].update(status="done"), "must be status unplanned"),
        (lambda c: c["days"][4].update(plannedS="twenty"), "must be numeric"),
        (lambda c: c["weeks"][0].update(runsDone="one"), "must be numeric"),
    ):
        bad = json.loads(json.dumps(good))
        mutate(bad)
        e = []
        vd.validate_compliance(bad, e)
        assert any(expect in msg for msg in e), f"expected '{expect}' in {e}"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest test_plan_compliance.py::test_validate_data_compliance_shape -v`
Expected: FAIL — `well-formed block must validate` listing invalid status `'rest'`, invalid plannedKind `'rest'`, invalid reason `'duration'`.

- [ ] **Step 3: Widen the validator**

In `validate_data.py`, line 175:

```python
# honest-compliance: `rest` (a rest day is satisfied by resting) and
# `untracked` (this instance cannot see that kind of work) are terminal
# verdicts like the rest — neither is a failure.
_COMPLIANCE_STATUSES = {"done", "partial", "missed", "swapped", "unplanned",
                        "pending", "rest", "untracked"}
```

Line 196:

```python
        check(d.get("plannedKind") in (None, "run", "strength", "cross", "rest"),
              f"compliance.days {label} invalid plannedKind {d.get('plannedKind')!r}", e)
```

Line 198:

```python
        check(d.get("reason") in (None, "distance", "intensity", "duration"),
              f"compliance.days {label} invalid reason {d.get('reason')!r}", e)
```

Line 202:

```python
        for k in ("plannedKm", "actualKm", "actualPaceS", "actualHr",
                  "plannedS", "actualS"):
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest test_plan_compliance.py::test_validate_data_compliance_shape -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add validate_data.py test_plan_compliance.py
git commit -m "feat(validate): accept the honest-compliance vocabulary

rest and untracked statuses, a rest plannedKind, a duration reason, and the
plannedS/actualS pair. Widened before any producer emits them so the first
sync after deploy cannot fail validation on its own output."
```

---

## Task 3: A rest day is satisfied by resting

**Files:**
- Modify: `plan_compliance.py:212-236` (the day loop in `score_week`)
- Test: `test_plan_compliance.py`

**Interfaces:**
- Consumes: nothing.
- Produces: status `"rest"` on any past-dated `kind: "rest"` slot. Task 8 excludes it from the block-lens denominator; Task 10 renders it.

- [ ] **Step 1: Write the failing test**

Append to `test_plan_compliance.py`, after `test_strength_presence_and_absence`:

```python
# ── honest-compliance: rest, capability, duration ────────────────────────────
def _rest_week():
    """Max's real Wk 1 shape: three run/walk days around four rest days."""
    return {
        "wk": "Wk 1", "mon": "2026-07-20", "sun": "2026-07-26", "km": 8,
        "label": "Jul 20", "phase": "Base", "long": "3 km", "focus": "start",
        "days": [
            _day("Mon", "2026-07-20", "run", "Run/Walk 1:1", "Easy", 2.5),
            _day("Tue", "2026-07-21", "rest", "Rest", "Easy", 0),
            _day("Wed", "2026-07-22", "run", "Run/Walk 1:1", "Easy", 2.5),
            _day("Thu", "2026-07-23", "rest", "Rest", "Easy", 0),
            _day("Fri", "2026-07-24", "rest", "Rest", "Easy", 0),
            _day("Sat", "2026-07-25", "run", "Run/Walk 1:1 · Long", "Easy", 3.0),
            _day("Sun", "2026-07-26", "rest", "Rest", "Easy", 0),
        ],
    }


REST_TODAY = dt.date(2026, 7, 29)  # the week is closed


def test_a_past_rest_day_is_rest_never_missed():
    """Found live on Max's dashboard 2026-08-05: six of his ten ✕ marks were
    rest days. A rest slot falls through _is_run_slot, looks for an activity
    of kind 'rest' that kind_for_type can never return, and was marked missed
    — unsatisfiable by construction. Mutation: drop the rest branch → red."""
    rows = pc.score_week(_rest_week(), [], REST_TODAY, MAX_HR, SNAP)
    for date in ("2026-07-21", "2026-07-23", "2026-07-24", "2026-07-26"):
        r = _by_date(rows, date)
        assert r["status"] == "rest", f"{date} is a rest day, not a failure"
        assert r["reason"] is None


def test_a_future_rest_day_is_still_pending():
    rows = pc.score_week(_rest_week(), [], dt.date(2026, 7, 22), MAX_HR, SNAP)
    assert _by_date(rows, "2026-07-23")["status"] == "pending"


def test_running_on_a_rest_day_keeps_both_facts():
    """The slot is still satisfied — resting was never required of the run —
    and the run itself still surfaces as unplanned. Neither is suppressed."""
    rows = pc.score_week(_rest_week(), [_a(1, "2026-07-23", "run", 1.0)],
                         REST_TODAY, MAX_HR, SNAP)
    assert _by_date(rows, "2026-07-23")["status"] == "rest"
    assert any(r["status"] == "unplanned" and r["date"] == "2026-07-23"
               for r in rows), "the run he did is still reported"


def test_rest_days_are_not_run_slots_in_the_week_aggregate():
    """A rest day carries km 0, so it must never inflate runsPlanned."""
    d = _tmp()
    conn = arch.open_archive(d)
    plan = {"race": {"date": "2027-04-25"}, "block": [_rest_week()]}
    pc.run_compliance(conn, "raw", plan, REST_TODAY, MAX_HR)
    block = pc.assemble_compliance(conn, plan, REST_TODAY)
    assert block["weeks"][0]["runsPlanned"] == 3
    conn.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest test_plan_compliance.py -v -k "rest_day or rest_days or rest_week"`
Expected: FAIL — `'missed' != 'rest'` on the four rest dates.

- [ ] **Step 3: Add the rest branch**

In `plan_compliance.py`, replace the `else:` arm of the day loop (currently lines 229-235):

```python
        else:
            if day.get("kind") == "rest":
                # A rest day is satisfied by RESTING. It has no activity to
                # match and never could: kind_for_type cannot return "rest".
                # Scoring it against an absent activity made every rest day a
                # red ✕ — six of them on Max's board (found 2026-08-05).
                if day["date"] < today_iso:
                    row["status"] = "rest"
            else:
                act = take(day["date"], day["kind"], absorb=True)
                if act:
                    row["status"] = "done"
                    row["activity_id"] = act["id"]
                elif day["date"] < today_iso:
                    row["status"] = "missed"
        rows.append(row)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest test_plan_compliance.py -v`
Expected: PASS — all new tests plus the full pre-existing suite (the km-based fixture week has no rest days, so nothing else moves).

- [ ] **Step 5: Commit**

```bash
git add plan_compliance.py test_plan_compliance.py
git commit -m "fix(compliance): a rest day is satisfied by resting

A kind:'rest' slot fell through _is_run_slot, searched for an activity of a
kind the matcher can never produce, and was marked missed. Six of the ten ✕
marks on Max's dashboard were rest days — days on which nothing whatsoever
was asked of him.

Rest is now its own terminal status. Running on a rest day still reports the
run as unplanned; both facts stay true."
```

---

## Task 4: Work this instance cannot see is `untracked`

**Files:**
- Modify: `plan_compliance.py` — new constants + `tracked_kinds()`, new `score_week` parameter, the else-branch, both `score_week` call sites in `run_compliance` and `_rescore_stale`
- Test: `test_plan_compliance.py`

**Interfaces:**
- Consumes: the `rest` branch from Task 3.
- Produces:
  - `plan_compliance.tracked_kinds(conn, today: dt.date) -> set[str]` — the kinds this archive can currently see.
  - `plan_compliance.score_week(week, acts, today, max_hr, snapshot_id, tracked=None)` — **new trailing optional parameter**. `None` means "every kind is tracked", which preserves every existing caller and test verbatim.

- [ ] **Step 1: Write the failing test**

Append to `test_plan_compliance.py`:

```python
def _hc_week():
    """Max's real Wk 2: run days plus strength days his phone cannot record."""
    return {
        "wk": "Wk 2", "mon": "2026-07-27", "sun": "2026-08-02", "km": 10.3,
        "label": "Jul 27", "phase": "Base", "long": "3.9 km", "focus": "build",
        "days": [
            _day("Mon", "2026-07-27", "run", "Run/Walk 2:1", "Easy", 3.0),
            _day("Tue", "2026-07-28", "rest", "Rest", "Easy", 0),
            _day("Wed", "2026-07-29", "strength", "Calf & Core", "Moderate", 0),
            _day("Thu", "2026-07-30", "run", "2 × 10 min", "Easy", 3.4),
            _day("Fri", "2026-07-31", "rest", "Rest", "Easy", 0),
            _day("Sat", "2026-08-01", "run", "Long · 2 × 12 min", "Moderate", 3.9),
            _day("Sun", "2026-08-02", "strength", "Mobility · Calves", "Easy", 0),
        ],
    }


HC_TODAY = dt.date(2026, 8, 5)


def test_untracked_kind_is_neither_done_nor_missed():
    """Max's bridge pushes running sessions only, so a strength slot is
    unsatisfiable by construction — exactly like a rest day was. Marking it
    missed accuses him of skipping work nothing on earth records.
    Mutation: drop the tracked check → red."""
    rows = pc.score_week(_hc_week(), [], HC_TODAY, MAX_HR, SNAP,
                         tracked={"run"})
    for date in ("2026-07-29", "2026-08-02"):
        assert _by_date(rows, date)["status"] == "untracked"


def test_a_tracked_kind_with_no_evidence_is_still_missed():
    """The honesty half. On an instance that DOES record strength, a skipped
    strength day is a skipped strength day. Mutation: always untracked → red."""
    rows = pc.score_week(_hc_week(), [], HC_TODAY, MAX_HR, SNAP,
                         tracked={"run", "strength"})
    for date in ("2026-07-29", "2026-08-02"):
        assert _by_date(rows, date)["status"] == "missed"


def test_evidence_outranks_capability():
    """One logged session scores done whatever the capability set says — the
    check only ever governs the ABSENCE of evidence."""
    rows = pc.score_week(_hc_week(), [_a(7, "2026-07-29", "strength", 0.0)],
                         HC_TODAY, MAX_HR, SNAP, tracked={"run"})
    assert _by_date(rows, "2026-07-29")["status"] == "done"


def test_a_run_slot_is_never_untracked():
    """Running is the one kind every instance records. A missed run is the
    signal this whole engine exists to carry and must survive every filter."""
    rows = pc.score_week(_hc_week(), [], HC_TODAY, MAX_HR, SNAP, tracked=set())
    assert _by_date(rows, "2026-07-27")["status"] == "missed"


def test_default_tracked_is_everything_so_old_callers_are_unchanged():
    rows_default = pc.score_week(_hc_week(), [], HC_TODAY, MAX_HR, SNAP)
    rows_all = pc.score_week(_hc_week(), [], HC_TODAY, MAX_HR, SNAP,
                             tracked={"run", "strength", "cross"})
    assert rows_default == rows_all


def test_tracked_kinds_reads_the_archive_inside_the_window():
    """Two of a kind inside 90 days makes it visible; one stray log does not,
    so a single accidental entry cannot condemn every later day."""
    d = _tmp()
    conn = arch.open_archive(d)
    arch.upsert_activities(conn, [
        _garmin_act(1, "2026-08-01", 5.0, 1800),                      # run
        _garmin_act(2, "2026-08-02", 5.0, 1800),                      # run
        _garmin_act(3, "2026-07-30", 0.0, 2400, tk="strength_training"),
        _garmin_act(4, "2026-01-05", 0.0, 2400, tk="indoor_cycling"),  # too old
        _garmin_act(5, "2026-01-06", 0.0, 2400, tk="indoor_cycling"),  # too old
    ])
    tracked = pc.tracked_kinds(conn, HC_TODAY)
    assert "run" in tracked
    assert "strength" not in tracked, "one session is not a habit"
    assert "cross" not in tracked, "outside the 90-day window"
    conn.close()


def test_tracked_kinds_always_contains_run_even_on_an_empty_archive():
    d = _tmp()
    conn = arch.open_archive(d)
    assert pc.tracked_kinds(conn, HC_TODAY) == {"run"}
    conn.close()


def test_run_compliance_derives_capability_from_the_archive():
    """End to end: an archive of runs only must produce untracked strength
    days, with no parameter passed by the caller."""
    d = _tmp()
    conn = arch.open_archive(d)
    arch.upsert_activities(conn, [
        _garmin_act(1, "2026-07-27", 2.6, 1417, hr=143),
        _garmin_act(2, "2026-07-30", 2.4, 1387, hr=151),
        _garmin_act(3, "2026-08-01", 3.0, 1656, hr=157),
    ])
    plan = {"race": {"date": "2027-04-25"}, "block": [_hc_week()]}
    pc.run_compliance(conn, "raw", plan, HC_TODAY, MAX_HR)
    rows = arch.compliance_rows(conn)
    assert _by_date(rows, "2026-07-29")["status"] == "untracked"
    assert _by_date(rows, "2026-08-02")["status"] == "untracked"
    assert _by_date(rows, "2026-07-28")["status"] == "rest"
    conn.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest test_plan_compliance.py -v -k "untracked or tracked or capability"`
Expected: FAIL — `TypeError: score_week() got an unexpected keyword argument 'tracked'`

- [ ] **Step 3: Implement capability**

In `plan_compliance.py`, add beside the other scoring constants (after `STEADY_TOLERANCE_S` on line 51):

```python
# Capability (honest-compliance D2): a slot kind is scoreable only if this
# instance can actually SEE that kind of work. Two activities rather than one
# so a single stray log cannot condemn every later day; a trailing window
# rather than all-time so the answer tracks what the instance can currently do.
TRACKED_MIN_ACTIVITIES = 2
TRACKED_WINDOW_DAYS = 90
```

Add `tracked_kinds` after `kind_for_type` (i.e. after line 137):

```python
def tracked_kinds(conn, today: dt.date) -> set[str]:
    """The activity kinds this archive can currently see — the instance's own
    answer to 'is there any evidence path for this kind of work?'.

    Derived, never configured, so it self-heals in both directions: the day a
    Health Connect athlete's phone starts logging strength, strength days
    start scoring for him with no code change; an athlete whose watch has
    always logged strength keeps being told, honestly, when he skipped one.

    `run` is always included — running is the one kind every instance records,
    and a missed run is the signal this engine exists to carry."""
    since = (today - dt.timedelta(days=TRACKED_WINDOW_DAYS)).isoformat()
    counts: dict[str, int] = {}
    for (type_key,) in conn.execute(
            "SELECT type_key FROM activities "
            "WHERE substr(start_time_local, 1, 10) >= ?", (since,)):
        kind = kind_for_type(type_key)
        if kind:
            counts[kind] = counts.get(kind, 0) + 1
    return {k for k, n in counts.items() if n >= TRACKED_MIN_ACTIVITIES} | {"run"}
```

Change the `score_week` signature (line 190) and docstring:

```python
def score_week(week: dict, acts: list[dict], today: dt.date,
               max_hr: int, snapshot_id: int,
               tracked: set[str] | None = None) -> list[dict]:
    """Compliance rows for one plan week against its archived actuals.
    Pure — no I/O, fully deterministic for a closed week.

    `tracked` is the set of kinds this instance can see (see tracked_kinds).
    It is computed by the CALLER and passed in so this function stays pure.
    None means "every kind is tracked" — the honest default for a caller that
    has not asked the archive."""
```

Replace the non-rest arm of the else-branch from Task 3:

```python
            else:
                act = take(day["date"], day["kind"], absorb=True)
                if act:
                    row["status"] = "done"
                    row["activity_id"] = act["id"]
                elif day["date"] < today_iso:
                    # No evidence — but "he skipped it" and "nothing here can
                    # record it" are different claims, and only one of them is
                    # ever true on a running-only ingest.
                    row["status"] = ("missed" if tracked is None
                                     or day["kind"] in tracked else "untracked")
```

In `run_compliance`, derive the set once before the week loop (after `today_iso` is set, around line 387):

```python
    tracked = tracked_kinds(conn, today)
```

and pass it at the `score_week` call (line 401):

```python
        rows = score_week(week, acts, today, max_hr, week_snapshot, tracked)
```

In `_rescore_stale`, do the same — derive once before the loop:

```python
    tracked = tracked_kinds(conn, today)
```

and pass it (line 435):

```python
        rows = score_week(week, acts, today, max_hr, snapshot_id, tracked)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest test_plan_compliance.py -v`
Expected: PASS. Note `test_strength_presence_and_absence` still passes: its archive-free `score_week` call passes no `tracked`, so the default keeps every kind tracked.

- [ ] **Step 5: Commit**

```bash
git add plan_compliance.py test_plan_compliance.py
git commit -m "feat(compliance): score a kind only if this instance can see it

Max's Health Connect bridge pushes running sessions only, so every strength
and mobility slot on his plan was unsatisfiable and scored missed — three
more of his ten ✕ marks, for work nothing on his setup records.

A kind is tracked when the archive holds >= 2 activities of it inside 90
days. Absent capability and absent evidence now reads 'untracked' instead of
accusing him. Present capability still reads 'missed', so a genuinely skipped
strength day on a Garmin instance is still called what it is.

Derived from the archive, never configured, so it self-heals both ways.
score_week stays pure — the caller computes the set and passes it in."
```

---

## Task 5: Score a time-prescribed day on time

**Files:**
- Modify: `activity_archive.py:48` (SCHEMA_VERSION), after `:395` (new `_apply_schema_v15`), `:440` (call it), `:944` (`_COMPLIANCE_COLS`)
- Modify: `plan_compliance.py` — `_acts_for_range`, `_score_run`, the run branch of `score_week`, `assemble_compliance`
- Test: `test_plan_compliance.py`

**Interfaces:**
- Consumes: `plan_prescription.duration_for_day` (Task 1); the widened validator (Task 2).
- Produces: rows carrying `planned_s` / `actual_s` (integers, seconds) and `reason: "duration"`; contract keys `plannedS` / `actualS`. Tasks 8, 9, 10 read them.

- [ ] **Step 1: Write the failing test**

Append to `test_plan_compliance.py`:

```python
def _time_week():
    """Max's real Wk 2 run days, with the segments the live plan carries."""
    w = _hc_week()
    for day in w["days"]:
        if day["date"] == "2026-07-30":
            day["segments"] = [
                {"label": "Warm-up", "val": "5 min brisk walk"},
                {"label": "Blocks", "val": "2×10/10 min jog",
                 "rest": "2 min walk between"},
                {"label": "Cool-down", "val": "3 min walk"}]
        elif day["date"] == "2026-08-01":
            day["segments"] = [
                {"label": "Warm-up", "val": "5 min brisk walk"},
                {"label": "Blocks", "val": "2×12/12 min jog",
                 "rest": "2 min walk between"},
                {"label": "Cool-down", "val": "3 min walk"}]
    return w


def _at(aid, date, kind, km, dur_s, hr=140):
    """An activity carrying its duration, the way _acts_for_range builds it."""
    return {"id": aid, "date": date, "kind": kind, "km": km, "dur_s": dur_s,
            "pace_s": (dur_s / km) if km else None, "hr": hr}


def test_a_time_prescribed_day_is_scored_on_time():
    """Max's real Thursday: '2 × 10 min', 22 min of prescribed work, 23 min
    recorded — a completed session. Scored on the plan's 3.4 km (which is
    just 20 min × an assumed 8:00 pace he was never asked to hold) it read
    71% and 'partial — shorter than planned'.
    Mutation: keep scoring on km → red."""
    rows = pc.score_week(_time_week(), [_at(1, "2026-07-30", "run", 2.4, 1387)],
                         HC_TODAY, MAX_HR, SNAP, tracked={"run"})
    r = _by_date(rows, "2026-07-30")
    assert r["status"] == "done" and r["reason"] is None
    assert r["planned_s"] == 22 * 60 and r["actual_s"] == 1387


def test_the_second_real_partial_also_lands():
    rows = pc.score_week(_time_week(), [_at(1, "2026-08-01", "run", 3.0, 1656)],
                         HC_TODAY, MAX_HR, SNAP, tracked={"run"})
    r = _by_date(rows, "2026-08-01")
    assert r["status"] == "done"
    assert r["planned_s"] == 26 * 60


def test_a_genuinely_cut_short_time_session_is_still_partial():
    """The thresholds still bite — this is a correction, not an amnesty.
    12 of 22 min is 55%: past the 50% floor, short of the 85% bar."""
    rows = pc.score_week(_time_week(), [_at(1, "2026-07-30", "run", 1.3, 720)],
                         HC_TODAY, MAX_HR, SNAP, tracked={"run"})
    r = _by_date(rows, "2026-07-30")
    assert r["status"] == "partial" and r["reason"] == "duration"


def test_an_abandoned_time_session_is_missed():
    rows = pc.score_week(_time_week(), [_at(1, "2026-07-30", "run", 0.5, 300)],
                         HC_TODAY, MAX_HR, SNAP, tracked={"run"})
    assert _by_date(rows, "2026-07-30")["status"] == "missed"


def test_a_km_shaped_day_keeps_distance_scoring():
    """The km-based plan must not move at all. Mutation: score every day on
    duration → red here."""
    rows = pc.score_week(_closed_week(), [_a(1, "2026-07-01", "run", 3.0)],
                         TODAY, MAX_HR, SNAP)
    r = _by_date(rows, "2026-07-01")
    assert r["status"] == "partial" and r["reason"] == "distance"
    assert r["planned_s"] is None and r["actual_s"] is None


def test_a_time_day_without_a_recorded_duration_falls_back_to_km():
    """An activity with no duration cannot answer a time question. Falling
    back to km is today's behaviour, which is the safe state."""
    act = {"id": 1, "date": "2026-07-30", "kind": "run", "km": 2.4,
           "dur_s": None, "pace_s": None, "hr": 140}
    rows = pc.score_week(_time_week(), [act], HC_TODAY, MAX_HR, SNAP,
                         tracked={"run"})
    r = _by_date(rows, "2026-07-30")
    assert r["reason"] == "distance" and r["planned_s"] is None


def test_intensity_still_outranks_a_satisfied_duration():
    """An Easy day run at 90% of max HR is still flagged, time or no time."""
    hot = int(0.9 * MAX_HR)
    rows = pc.score_week(_time_week(),
                         [_at(1, "2026-07-30", "run", 2.4, 1387, hr=hot)],
                         HC_TODAY, MAX_HR, SNAP, tracked={"run"})
    r = _by_date(rows, "2026-07-30")
    assert r["status"] == "partial" and r["reason"] == "intensity"


def test_acts_for_range_carries_duration():
    d = _tmp()
    conn = arch.open_archive(d)
    arch.upsert_activities(conn, [_garmin_act(1, "2026-07-30", 2.4, 1387)])
    acts = pc._acts_for_range(conn, "2026-07-27", "2026-08-02")
    assert acts[0]["dur_s"] == 1387
    conn.close()


def test_seconds_survive_the_round_trip_and_reach_the_contract():
    d = _tmp()
    conn = arch.open_archive(d)
    arch.upsert_activities(conn, [_garmin_act(1, "2026-07-30", 2.4, 1387, hr=151)])
    plan = {"race": {"date": "2027-04-25"}, "block": [_time_week()]}
    pc.run_compliance(conn, "raw", plan, HC_TODAY, MAX_HR)
    stored = _by_date(arch.compliance_rows(conn), "2026-07-30")
    assert stored["planned_s"] == 1320 and stored["actual_s"] == 1387
    block = pc.assemble_compliance(conn, plan, HC_TODAY)
    day = next(dd for dd in block["days"] if dd["date"] == "2026-07-30")
    assert day["plannedS"] == 1320 and day["actualS"] == 1387
    conn.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest test_plan_compliance.py -v -k "time_prescribed or cut_short or duration or seconds"`
Expected: FAIL — `KeyError: 'planned_s'`

- [ ] **Step 3: Add the storage columns**

In `activity_archive.py`, line 48:

```python
SCHEMA_VERSION = 15
```

After `_apply_schema_v14` (line 396), add:

```python
def _apply_schema_v15(conn: sqlite3.Connection) -> None:
    """v15 (honest-compliance): a time-prescribed day is scored on seconds,
    so the row carries both sides of that comparison. Null on every day
    scored on distance — which is every day of a km-based plan."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(plan_compliance)")}
    for name in ("planned_s", "actual_s"):
        if name not in cols:
            conn.execute(f"ALTER TABLE plan_compliance ADD COLUMN {name} INTEGER")
```

In `_open`, after the `_apply_schema_v14(conn)` line (440):

```python
        _apply_schema_v15(conn)
```

and update the comment on line 441 to read `v1→…→v15`.

Extend `_COMPLIANCE_COLS` (line 944):

```python
_COMPLIANCE_COLS = (
    "date", "wk", "snapshot_id", "compliance_version", "planned_kind",
    "planned_km", "planned_load", "planned_title", "status", "reason",
    "actual_km", "actual_pace_s", "actual_hr", "activity_id", "quality_json",
    "planned_s", "actual_s",
)
```

- [ ] **Step 4: Carry duration through the matcher and score on it**

In `plan_compliance.py`, add the import beside the others (after line 41):

```python
import plan_prescription
```

*(already imported — confirm it is there and do not duplicate).*

In `_acts_for_range`, add `dur_s` to each built dict (line 153):

```python
        acts.append({"id": aid, "date": date, "kind": kind, "km": km,
                     "dur_s": dur_s,
                     "pace_s": (dur_s / km) if km and dur_s else None,
                     "hr": hr})
```

Replace `_score_run` entirely:

```python
def _score_run(row: dict, day: dict, act: dict, max_hr: int,
               planned_s: int | None = None) -> None:
    """Coarse scoring per design D4. Intent (load) comes from the plan; Hard
    sessions are scored on distance alone — rep quality is the coach's call.

    A day the coach wrote in MINUTES is judged in minutes (honest-compliance
    D3). Its planned km is a byproduct of an assumed pace, so scoring against
    it marks a slower athlete down for ground nobody asked him to cover — the
    live failure that produced 'partial — shorter than planned' on sessions
    Max completed in full."""
    actual_s = act.get("dur_s")
    if planned_s and actual_s:
        ratio = actual_s / planned_s
        short_reason = "duration"
        row["planned_s"] = int(planned_s)
        row["actual_s"] = int(actual_s)
    else:
        planned_km = day.get("km") or 0
        ratio = (act["km"] / planned_km) if planned_km else 1.0
        short_reason = "distance"
    intensity_ok = True
    if day.get("load") in EASY_LOADS and act.get("hr") and max_hr:
        intensity_ok = act["hr"] <= EASY_HR_CEILING * max_hr
    if ratio >= DIST_DONE_RATIO and intensity_ok:
        status, reason = "done", None
    elif ratio < DIST_PARTIAL_RATIO:
        status, reason = "missed", short_reason
    elif ratio < DIST_DONE_RATIO:
        status, reason = "partial", short_reason
    else:
        status, reason = "partial", "intensity"
    row.update(status=status, reason=reason,
               actual_km=round(act["km"], 1),
               actual_pace_s=round(act["pace_s"]) if act["pace_s"] else None,
               actual_hr=act["hr"], activity_id=act["id"])
```

**Note:** the pre-existing `missed` case carried `reason: "distance"`; it now carries the reason matching the unit actually used. `test_under_half_distance_is_missed_with_actuals` does not assert on reason, so it stays green.

Seed both new keys in the row template inside `score_week` (line 216-219) so every row has them:

```python
        row = {"date": day["date"], "wk": week.get("wk"),
               "snapshot_id": snapshot_id,
               "compliance_version": COMPLIANCE_VERSION,
               "planned_kind": day.get("kind"), "planned_km": day.get("km"),
               "planned_load": day.get("load"), "planned_title": day.get("title"),
               "status": "pending", "reason": None, "actual_km": None,
               "actual_pace_s": None, "actual_hr": None, "activity_id": None,
               "planned_s": None, "actual_s": None}
```

In the run branch of `score_week`, read the prescribed duration and pass it:

```python
        if _is_run_slot(day):
            planned_s = plan_prescription.duration_for_day(day.get("segments"))
            act = take(day["date"], "run")
            if day.get("kind") != "run":  # hybrid day: absorb its own-kind acts
                take(day["date"], day["kind"], absorb=True)
            if act:
                _score_run(row, day, act, max_hr, planned_s)
            elif day["date"] < today_iso:
                row["status"] = "missed"
                swap_candidates.append((day, row))
```

In the swap pass, pass it there too (line 259):

```python
            _score_run(row, day, a, max_hr,
                       plan_prescription.duration_for_day(day.get("segments")))
```

In the `unmatched` leftover-run block (line 266), add the two keys to the unplanned row dict:

```python
                     "actual_hr": a["hr"], "activity_id": a["id"],
                     "planned_s": None, "actual_s": None})
```

In `assemble_compliance`, surface them (after the `actual_km` block, line 468):

```python
        if r["planned_s"] is not None:
            d["plannedS"] = r["planned_s"]
            d["actualS"] = r["actual_s"]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest test_plan_compliance.py -v`
Expected: PASS — the whole suite. `test_run_compliance_idempotent` compares stored rows for equality and exercises the new columns end to end.

- [ ] **Step 6: Verify the archive opens and migrates cleanly**

Run: `./.venv/Scripts/python.exe -c "import activity_archive as a, pathlib, tempfile; c=a.open_archive(pathlib.Path(tempfile.mkdtemp())); print(sorted(r[1] for r in c.execute('PRAGMA table_info(plan_compliance)')))"`
Expected: the column list includes `actual_s` and `planned_s`.

Then verify the migration is additive on the real local archive (a copy — never the file itself):

```bash
cp activity-archive.db /tmp/ac-test.db && ./.venv/Scripts/python.exe -c "
import sqlite3, activity_archive as a, pathlib, shutil, tempfile
d = pathlib.Path(tempfile.mkdtemp()); shutil.copy('/tmp/ac-test.db', d / 'activity-archive.db')
c = a.open_archive(d)
print('schema', a.get_meta(c, 'schema_version'))
print('rows', c.execute('SELECT COUNT(*) FROM plan_compliance').fetchone()[0])
print('integrity', c.execute('PRAGMA integrity_check').fetchone()[0])
"
```
Expected: `schema 15`, the pre-existing row count unchanged, `integrity ok`.

- [ ] **Step 7: Commit**

```bash
git add activity_archive.py plan_compliance.py test_plan_compliance.py
git commit -m "feat(compliance): judge a time-prescribed session in minutes

'2 × 10 min' was scored against 3.4 km — a number that is nothing but 20 min
times an assumed 8:00 pace. Running the full 22 minutes of prescribed work at
his own pace covered less ground, so Max got 'partial — shorter than planned'
for a session he completed. Both of his partials were this.

A day whose segments resolve to minutes is now scored on the activity's
duration against the prescribed work, warm-up and cool-down excluded. Every
other day keeps distance scoring unchanged, so the km-based plan does not
move. Thresholds are untouched: a genuinely cut-short session still lands
partial, on reason 'duration'.

Schema v15 adds planned_s / actual_s, null on every distance-scored day."
```

---

## Task 6: The swap pass runs mid-week

**Files:**
- Modify: `plan_compliance.py:238` (drop the `closed` guard)
- Test: `test_plan_compliance.py:142` (rewrite `test_open_week_no_swap_and_pending` — it pins the old behaviour deliberately)

**Interfaces:**
- Consumes: nothing new.
- Produces: no signature change. A run done on the wrong day is credited from the next sync rather than at week close.

- [ ] **Step 1: Rewrite the test that pins the old behaviour**

This is an intentional behaviour change. Replace `test_open_week_no_swap_and_pending` (line 142) with:

```python
def test_open_week_swaps_and_pends():
    """A run done a day late used to show ✕ missed on the planned day AND
    + unplanned on the day it happened — for up to six days, twice punished
    for one completed session. The swap pass now runs over the open week's
    PAST days too; future days stay pending.

    Safe by construction: every sync rescores the whole week from scratch and
    replaces its rows wholesale, so a provisional pairing is never sticky.
    Mutation: restore the `if closed:` guard → red."""
    week = _closed_week()
    week.update(wk="Wk open", mon="2026-07-06", sun="2026-07-12")
    for i, d in enumerate(week["days"]):
        d["date"] = f"2026-07-{6 + i:02d}"
    # today = Wed Jul 8: Monday's 4 km slot was run on Tuesday instead
    rows = pc.score_week(week, [_a(1, "2026-07-07", "run", 4.0)],
                         dt.date(2026, 7, 8), MAX_HR, SNAP)
    assert _by_date(rows, "2026-07-06")["status"] == "swapped", \
        "the run he actually did is credited without waiting for week close"
    assert all(r["status"] != "unplanned" for r in rows), \
        "…and is not ALSO reported as an extra run"
    for date in ("2026-07-08", "2026-07-10", "2026-07-12"):
        assert _by_date(rows, date)["status"] == "pending", \
            "the future is still the future"


def test_a_future_day_is_never_swap_rescued():
    """Only PAST days become swap candidates, so tomorrow's session can never
    be marked done by today's run."""
    week = _closed_week()
    week.update(wk="Wk open", mon="2026-07-06", sun="2026-07-12")
    for i, d in enumerate(week["days"]):
        d["date"] = f"2026-07-{6 + i:02d}"
    rows = pc.score_week(week, [_a(1, "2026-07-06", "run", 16.0)],
                         dt.date(2026, 7, 6), MAX_HR, SNAP)
    assert _by_date(rows, "2026-07-12")["status"] == "pending"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest test_plan_compliance.py -v -k "open_week or future_day"`
Expected: FAIL — `'missed' != 'swapped'`

- [ ] **Step 3: Drop the guard**

In `plan_compliance.py`, replace line 238's condition. The block currently opens:

```python
    if closed:  # swap pass (design D3): rescue missed run slots at week close
```

Replace with:

```python
    # Swap pass (design D3, widened by honest-compliance D4): rescue missed run
    # slots wherever the athlete moved a session. It runs on the OPEN week too —
    # `swap_candidates` only ever holds past-dated slots, so tomorrow can never
    # be rescued, and every sync rescores the whole week from scratch, so a
    # provisional pairing is never sticky. Waiting for week close meant a run
    # done on Tuesday showed ✕ missed on Monday AND + unplanned on Tuesday for
    # the rest of the week.
    if True:
```

Then de-indent is unnecessary — but `if True:` is a code smell. Instead, **delete the `if closed:` line entirely and de-indent its body by four spaces**, placing the comment above it:

```python
    # Swap pass (design D3, widened by honest-compliance D4): rescue missed run
    # slots wherever the athlete moved a session. It runs on the OPEN week too —
    # `swap_candidates` only ever holds past-dated slots, so tomorrow can never
    # be rescued, and every sync rescores the whole week from scratch, so a
    # provisional pairing is never sticky.
    #
    # Pairs are assigned globally by date proximity (ties: earlier actual, then
    # earlier planned day) so a far missed slot can never steal a run from a
    # nearer one. A run under half the slot's km is no pairing.
    leftover_runs = [a for a in unmatched if a["kind"] == "run"]
    pairs = []
    for day, row in swap_candidates:
        planned_km = day.get("km") or 0
        for a in leftover_runs:
            if planned_km and a["km"] / planned_km < DIST_PARTIAL_RATIO:
                continue
            pairs.append((abs(_days_apart(a["date"], day["date"])),
                          a["date"], day["date"], day, row, a))
    pairs.sort(key=lambda p: (p[0], p[1], p[2]))
    used_slots, used_acts = set(), set()
    for _, _, _, day, row, a in pairs:
        if id(row) in used_slots or a["id"] in used_acts:
            continue
        used_slots.add(id(row))
        used_acts.add(a["id"])
        unmatched.remove(a)
        _score_run(row, day, a, max_hr,
                   plan_prescription.duration_for_day(day.get("segments")))
        if row["status"] == "done":
            row["status"] = "swapped"
```

The local `closed` variable (line 198) becomes unused — **delete it** (`closed = week["sun"] < today_iso`).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest test_plan_compliance.py -v`
Expected: PASS — including `test_swap_at_week_close` and `test_missed_and_unplanned`, which exercise closed weeks and are unaffected.

- [ ] **Step 5: Commit**

```bash
git add plan_compliance.py test_plan_compliance.py
git commit -m "fix(compliance): credit a moved session without waiting for week close

The swap pass only ran once the week was over, so a run done on Tuesday
instead of Monday showed ✕ missed on Monday AND + unplanned on Tuesday, for
up to six days — twice punished for one completed session.

Only past-dated slots ever become swap candidates, so a future day can still
never be rescued, and every sync replaces the week's rows wholesale, so a
provisional pairing self-corrects as the week fills in."
```

---

## Task 7: An uncalibrated lens makes no rep claim

**Files:**
- Modify: `plan_compliance.py:301-311` (inside `_quality_verdict`)
- Test: `test_plan_compliance.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `quality_json` carrying `found: null` and an explanatory verdict when the interval document is uncalibrated.

**Background.** `interval_lens.work_floor()` returns `None` below `WORK_FLOOR_MIN_SAMPLES = 20_000` (≈30 runs), and the engine then sets `calibrated: False` with the comment *"Without a floor we cannot tell those apart, so we make no rep claim at all."* Max has 6 runs, so every document he has is uncalibrated — and `_quality_verdict` printed `0/8 reps, no structured set detected` onto sessions where he did all eight. `/run` already honours the flag (`run.dc.html:641`); compliance did not. Default the flag to `True` so lap-sourced documents (the watch is not guessing) and every existing test fixture behave exactly as today.

- [ ] **Step 1: Write the failing test**

Append to `test_plan_compliance.py`:

```python
def test_an_uncalibrated_document_makes_no_rep_claim():
    """Max ran 8×1 min and the row said '0/8 reps'. His archive holds 6 runs,
    far under the lens's ~30-run work floor, so the engine explicitly declines
    to make a rep claim (calibrated: false) — and compliance quoted the
    silence as a zero. Mutation: ignore the flag → red."""
    doc = {"shape": "steady", "calibrated": False, "set": None,
           "segments": [], "quality": {"zone": None}}
    r = _annotated(_quality_week("8×1 min jog"), doc,
                   _a(1, "2026-07-03", "run", 3.2))
    q = json.loads(r["quality_json"])
    assert q["found"] is None, "no count was made, so none is reported"
    assert "not verifiable" in q["verdict"]
    assert "0/8" not in q["verdict"]


def test_a_calibrated_document_still_reports_a_bailed_set():
    """The honesty half: where the lens CAN count, a short set is still told.
    Mutation: suppress every rep verdict → red."""
    doc = dict(_REPS_DOC, calibrated=True, set={"found": 2},
               segments=[{"role": "work", "paceS": 330}] * 2)
    r = _annotated(_quality_week("4×1 km @ 5:25–5:35"), doc,
                   _a(1, "2026-07-03", "run", 7.0))
    assert json.loads(r["quality_json"])["verdict"].startswith("2/4 reps")


def test_a_document_without_the_flag_is_treated_as_calibrated():
    """Lap-sourced documents are always calibrated — the watch is not
    guessing — and older banked documents predate the flag."""
    r = _annotated(_quality_week("4×1 km @ 5:25–5:35"), _REPS_DOC,
                   _a(1, "2026-07-03", "run", 7.2))
    assert json.loads(r["quality_json"])["found"] == 4


def test_a_steady_verdict_needs_no_calibration():
    """Comparing an average pace to a target makes no rep claim, so the work
    floor is irrelevant to it."""
    doc = {"shape": "steady", "calibrated": False, "set": None,
           "segments": [], "quality": {"zone": None}}
    r = _annotated(_quality_week("16 km easy @ ~6:10"), doc,
                   _a(1, "2026-07-03", "run", 16.0, pace_s=373.0))
    q = json.loads(r["quality_json"])
    assert q["kind"] == "steady" and q["onTarget"] is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest test_plan_compliance.py -v -k "uncalibrated or calibrated"`
Expected: FAIL — `assert '0/8 reps, no structured set detected'` where `found is None` was expected.

- [ ] **Step 3: Honour the flag**

In `plan_compliance.py`, inside `_quality_verdict`, immediately after the `if not doc:` early return (currently lines 307-309) and before `doc_set = doc.get("set") or {}`:

```python
    if not doc.get("calibrated", True):
        # The lens itself declines to make a rep claim below its work floor
        # (~30 runs of history): without it, "faster than the athlete" and
        # "faster than the rest of this run" are indistinguishable. Quoting
        # that silence as "0/8 reps" told Max he had done none of the eight
        # reps he had just run. Lap-sourced and pre-flag documents default to
        # calibrated — the watch is not guessing.
        out["found"] = None
        out["verdict"] = ("reps not verifiable — the interval lens needs "
                          "~30 runs of history")
        return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest test_plan_compliance.py -v`
Expected: PASS — every pre-existing quality test stays green because `_REPS_DOC` carries no `calibrated` key and defaults to `True`.

- [ ] **Step 5: Commit**

```bash
git add plan_compliance.py test_plan_compliance.py
git commit -m "fix(compliance): do not quote an uncalibrated lens as a zero

Below ~30 runs of history the interval lens has no work floor and explicitly
declines to make a rep claim (calibrated: false). Compliance printed that
silence as '0/8 reps, no structured set detected' — on sessions where Max ran
all eight. /run already honoured the flag; this makes compliance agree.

Calibrated documents still report a short set: where the lens can count, it
still says what it counted."
```

---

## Task 8: The block lens counts required, visible work

**Files:**
- Modify: `block_lens.py:139` (`_STATUSES`), `:142-154` (`_day_row`), `:190` (the denominator)
- Test: `test_block_lens.py`

**Interfaces:**
- Consumes: statuses `rest` / `untracked` (Tasks 3, 4) and `planned_s` / `actual_s` (Task 5).
- Produces: `execution.percentExecuted` over required, visible days only; `counts` carrying the two new statuses; day rows carrying `plannedS` / `actualS`.

- [ ] **Step 1: Write the failing test**

Append to `test_block_lens.py` (match the file's existing fixture helpers — read the top of the file first and reuse its archive-seeding helper rather than writing a new one):

```python
def test_percent_executed_ignores_rest_and_untracked_days():
    """Max's live headline read 35% EXECUTED while he had run 7 of his 8
    sessions, because every rest day sat in the denominator as a failed day.
    A day that asked nothing of him, or that nothing here can see, is not a
    day he failed to execute. Mutation: restore the old denominator → red."""
    rows = [
        {"date": "2026-07-27", "wk": "Wk 2", "planned_kind": "run",
         "planned_km": 3.0, "planned_load": "Easy", "planned_title": "Run/Walk",
         "status": "swapped", "reason": None, "actual_km": 2.6,
         "actual_pace_s": 545, "actual_hr": 143, "activity_id": 1,
         "planned_s": None, "actual_s": None},
        {"date": "2026-07-28", "wk": "Wk 2", "planned_kind": "rest",
         "planned_km": 0.0, "planned_load": "Easy", "planned_title": "Rest",
         "status": "rest", "reason": None, "actual_km": None,
         "actual_pace_s": None, "actual_hr": None, "activity_id": None,
         "planned_s": None, "actual_s": None},
        {"date": "2026-07-29", "wk": "Wk 2", "planned_kind": "strength",
         "planned_km": 0.0, "planned_load": "Moderate", "planned_title": "Calf",
         "status": "untracked", "reason": None, "actual_km": None,
         "actual_pace_s": None, "actual_hr": None, "activity_id": None,
         "planned_s": None, "actual_s": None},
        {"date": "2026-07-30", "wk": "Wk 2", "planned_kind": "run",
         "planned_km": 3.4, "planned_load": "Easy", "planned_title": "2 × 10 min",
         "status": "done", "reason": None, "actual_km": 2.4,
         "actual_pace_s": 578, "actual_hr": 151, "activity_id": 2,
         "planned_s": 1320, "actual_s": 1387},
    ]
    block = {"race_date": "2027-04-25", "race_name": "First Half",
             "weeks": [{"wk": "Wk 2", "mon": "2026-07-27", "sun": "2026-08-02",
                        "phase": "Base", "label": "Jul 27", "focus": "build",
                        "km": 10.3}]}
    weeks, execution = bl.build_execution(block, rows)
    assert execution["scoredDays"] == 2, "only the two run slots were scoreable"
    assert execution["percentExecuted"] == 100
    assert execution["counts"]["rest"] == 1
    assert execution["counts"]["untracked"] == 1
    day = next(d for d in weeks[0]["days"] if d["date"] == "2026-07-30")
    assert day["plannedS"] == 1320 and day["actualS"] == 1387
```

**Before writing this,** read `test_block_lens.py` and `block_lens.build_execution`'s expected `block` shape — the dict above mirrors `build_execution`'s contract (`race_date`, `race_name`, `weeks[]`), but confirm the exact key names against the file and adjust rather than assuming.

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest test_block_lens.py -v -k percent_executed`
Expected: FAIL — `KeyError: 'rest'` in `counts`, or `scoredDays == 4`.

- [ ] **Step 3: Widen the vocabulary and the denominator**

In `block_lens.py`, line 139:

```python
# honest-compliance: `rest` and `untracked` are terminal verdicts that are not
# execution — one asked nothing of the athlete, the other cannot be seen from
# here. They are counted (the drill still shows them) but never scored.
_STATUSES = ("done", "partial", "missed", "swapped", "unplanned",
             "rest", "untracked")
_UNSCORED = ("pending", "rest", "untracked")
```

Line 190, inside `score_entry`:

```python
            if r["planned_kind"] is not None and r["status"] not in _UNSCORED:
```

In `_day_row` (line 142), surface the seconds:

```python
def _day_row(r: dict) -> dict:
    d = {"date": r["date"], "plannedKind": r["planned_kind"],
         "plannedKm": r["planned_km"], "plannedLoad": r["planned_load"],
         "title": r["planned_title"], "status": r["status"]}
    if r["reason"]:
        d["reason"] = r["reason"]
    if r["actual_km"] is not None:
        d["actualKm"] = r["actual_km"]
        d["actualPaceS"] = r["actual_pace_s"]
        d["actualHr"] = r["actual_hr"]
    if r.get("planned_s") is not None:
        d["plannedS"] = r["planned_s"]
        d["actualS"] = r.get("actual_s")
    if r["activity_id"] is not None:
        d["activityId"] = r["activity_id"]
    return d
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest test_block_lens.py -v`
Expected: PASS — the whole file.

- [ ] **Step 5: Commit**

```bash
git add block_lens.py test_block_lens.py
git commit -m "feat(block-lens): execute-rate counts required, visible work

Every rest day sat in the percentExecuted denominator as a failed day, so
Max's headline read 35% while he had run 7 of his 8 sessions. rest and
untracked are counted in the drill and excluded from the rate.

Day rows carry plannedS/actualS so a time-scored session can be read in the
unit it was prescribed in."
```

---

## Task 9: The briefing names what it cannot see

**Files:**
- Modify: `coach_briefing.py:242` (`_status_cell`), and the "Plan vs actual" section around `:307-325`
- Test: `test_coach_briefing.py`

**Interfaces:**
- Consumes: statuses `rest` / `untracked` (Tasks 3, 4).
- Produces: a `**Not tracked on this instance:**` line in the briefing when any scored day is `untracked`.

The coach must never read silence as compliance. Nothing is concealed — it just stops being shouted at the athlete.

- [ ] **Step 1: Write the failing test**

Append to `test_coach_briefing.py` (read the file first and reuse its existing briefing-rendering helper and archive fixture; the assertions below are what matters):

```python
def test_briefing_names_untracked_work_as_unverifiable():
    """The coach must never read silence as compliance. An untracked day is
    not evidence of a skipped session and the briefing must say so in words.
    Mutation: drop the note → red."""
    rows = [
        {"date": "2026-07-29", "wk": "Wk 2", "planned_kind": "strength",
         "planned_km": 0.0, "planned_load": "Moderate",
         "planned_title": "Calf & Core", "status": "untracked", "reason": None,
         "actual_km": None, "actual_pace_s": None, "actual_hr": None,
         "activity_id": None, "planned_s": None, "actual_s": None,
         "quality_json": None},
        {"date": "2026-08-02", "wk": "Wk 2", "planned_kind": "strength",
         "planned_km": 0.0, "planned_load": "Easy",
         "planned_title": "Mobility · Calves", "status": "untracked",
         "reason": None, "actual_km": None, "actual_pace_s": None,
         "actual_hr": None, "activity_id": None, "planned_s": None,
         "actual_s": None, "quality_json": None},
    ]
    note = cb._untracked_note(rows)
    assert note, "an untracked day must be named"
    text = " ".join(note)
    assert "2 planned strength" in text
    assert "not evidence of a skipped session" in text


def test_no_untracked_days_means_no_note():
    rows = [{"date": "2026-07-29", "wk": "Wk 2", "planned_kind": "strength",
             "planned_km": 0.0, "planned_load": "Moderate",
             "planned_title": "Calf", "status": "done", "reason": None,
             "actual_km": None, "actual_pace_s": None, "actual_hr": None,
             "activity_id": 5, "planned_s": None, "actual_s": None,
             "quality_json": None}]
    assert cb._untracked_note(rows) == []


def test_status_cell_spells_out_the_new_verdicts():
    base = {"reason": None, "quality_json": None}
    assert cb._status_cell(dict(base, status="rest")) == "rest"
    assert cb._status_cell(dict(base, status="untracked")) == \
        "untracked (not recorded on this instance)"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest test_coach_briefing.py -v -k "untracked or status_cell"`
Expected: FAIL — `AttributeError: module 'coach_briefing' has no attribute '_untracked_note'`

- [ ] **Step 3: Implement the note and the wording**

In `coach_briefing.py`, extend `_status_cell` (line 242):

```python
def _status_cell(r: dict) -> str:
    if r["status"] == "untracked":
        # Said in full every time: "untracked" alone could read as a data bug
        # rather than a statement about what this instance can see.
        return "untracked (not recorded on this instance)"
    out = f"{r['status']} ({r['reason']})" if r.get("reason") else r["status"]
    # add-plan-prescription D5: the rep-level verdict rides BESIDE the status
    # (annotate-only) — counts and bands, never a grade; judgment is /coach's.
    q = r.get("quality_json")
    if q:
        try:
            verdict = json.loads(q).get("verdict")
        except (ValueError, TypeError):
            verdict = None
        if verdict:
            out += f" · {verdict}"
    return out
```

Add `_untracked_note` immediately after `_week_table` (line 263):

```python
def _untracked_note(rows: list[dict]) -> list[str]:
    """Name the work this instance cannot see (honest-compliance D7).

    An untracked day is not evidence of a skipped session, and the coach must
    never read the silence as compliance. Nothing is hidden here — it simply
    stops being stated as a failure on the athlete's dashboard."""
    untracked = [r for r in rows if r["status"] == "untracked"]
    if not untracked:
        return []
    kinds = sorted({r["planned_kind"] for r in untracked if r["planned_kind"]})
    n = len(untracked)
    return ["",
            f"**Not tracked on this instance:** {n} planned "
            f"{'/'.join(kinds)} day{'' if n == 1 else 's'} could not be "
            "verified — this athlete's device does not record that kind of "
            "work. Absence here is not evidence of a skipped session."]
```

In `render_briefing`, after the week-table loop and the `scored_any` fallback (after line 325), add:

```python
    L.extend(_untracked_note(all_rows))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest test_coach_briefing.py -v`
Expected: PASS — the whole file.

- [ ] **Step 5: Commit**

```bash
git add coach_briefing.py test_coach_briefing.py
git commit -m "feat(briefing): name the work this instance cannot see

The dashboard stops calling an unrecordable day a failure; the coach must
still know the day was never verified. The briefing now names how many
planned days of which kind could not be seen, and says in words that absence
is not evidence of a skipped session.

Nothing is hidden from the coach. It stops being shouted at the athlete."
```

---

## Task 10: The three dashboards speak the new vocabulary

**Files:**
- Modify: `Running Dashboard.dc.html:1015-1032`
- Modify: `progress.dc.html:651-668`, `:700-713` (`renderBlockWeekDrill`)
- Modify: `run.dc.html:423-431`
- Test: `test_run_page.mjs`, plus whichever `.mjs` suite covers `/progress` (find it with `ls test_*.mjs`)

**Interfaces:**
- Consumes: statuses `rest` / `untracked`, reason `duration`, contract keys `plannedS` / `actualS`.
- Produces: no JS API — rendering only.

**Shared vocabulary, identical in all three files:**

```js
rest:      { t: '✓', fg: 'var(--sub)', word: 'rest' },
untracked: { t: '—', fg: 'var(--sub)', word: 'not tracked' },
```

`var(--sub)` and not `var(--good)` is deliberate: resting on a rest day is compliance, not an achievement, and green would make a week of pure rest look like a week of training. `var(--warn)` stays reserved for `missed` and `partial` on a slot that was both required and trackable.

Every map already falls back with `MAP[d.status] || MAP.pending`, so an unhandled status degrades to a neutral dot rather than breaking a page.

- [ ] **Step 1: Write the failing test**

Read `test_run_page.mjs` first to match its harness. Add a case asserting that a `rest` plan row renders the word `rest` and no `✕`, and that a `duration`-reason row reads *"shorter than the prescribed time"*. Follow the file's existing pattern for building a fixture `run.plan` object — do not invent a new harness.

- [ ] **Step 2: Run the test to verify it fails**

Run: `node test_run_page.mjs`
Expected: FAIL on the new assertions.

- [ ] **Step 3: `Running Dashboard.dc.html`**

Replace the `compGlyph` / `compReason` block (lines 1015-1021):

```js
    const compGlyph = {
      done:      { t:'✓', fg:'var(--good)', word:'done' },
      swapped:   { t:'⇄', fg:'var(--good)', word:'swapped — done on another day' },
      partial:   { t:'◐', fg:'var(--warn)', word:'partial' },
      missed:    { t:'✕', fg:'var(--warn)', word:'missed' },
      // honest-compliance: neither of these is a failure, so neither is amber.
      // Rest is compliance, not an achievement — hence --sub, not --good.
      rest:      { t:'✓', fg:'var(--sub)',  word:'rest' },
      untracked: { t:'—', fg:'var(--sub)',  word:'not tracked' }
    };
    const compReason = { distance:'shorter than planned',
                         duration:'shorter than the prescribed time',
                         intensity:'ran too hard for the intent' };
```

In `compRowFor` (line 1026), append the recorded minutes when the day was time-scored:

```js
      if (cd.actualKm != null) {
        t += ': ' + cd.actualKm + ' km';
        if (cd.actualS) t += ' · ' + Math.round(cd.actualS / 60) + ' min';
        if (cd.actualPaceS) t += ' @ ' + this.fmtPace(cd.actualPaceS) + '/km';
        if (cd.actualHr) t += ' · HR ' + cd.actualHr;
      }
```

- [ ] **Step 4: `progress.dc.html`**

Replace `BLOCK_GLYPH` (line 651) and `BLOCK_DAY_REASON` (line 668):

```js
  BLOCK_GLYPH = {
    done:      { t: '✓', fg: 'var(--good)',    word: 'done' },
    swapped:   { t: '⇄', fg: 'var(--good)',    word: 'swapped' },
    partial:   { t: '◐', fg: 'var(--warn)',    word: 'partial' },
    missed:    { t: '✕', fg: 'var(--warn)',    word: 'missed' },
    unplanned: { t: '+', fg: 'var(--accent2)', word: 'unplanned' },
    // honest-compliance: a rest day is satisfied by resting, and work this
    // instance cannot record is neither done nor missed. Calm, never amber.
    rest:      { t: '✓', fg: 'var(--sub)',     word: 'rest' },
    untracked: { t: '—', fg: 'var(--sub)',     word: 'not tracked' },
    pending:   { t: '·', fg: 'var(--sub)',     word: 'planned' },
  };
```

```js
  BLOCK_DAY_REASON = { distance: 'shorter than planned',
                       duration: 'shorter than the prescribed time',
                       intensity: 'ran too hard for the intent' };
```

In `renderBlockWeekDrill` (lines 701-706), read a time day in minutes:

```js
        const planned = d.plannedS
          ? Math.round(d.plannedS / 60) + ' min'
              + (d.plannedLoad ? ' · ' + d.plannedLoad : '')
          : d.plannedKind
            ? (d.plannedKm ? d.plannedKm + ' km' : d.plannedKind)
                + (d.plannedLoad ? ' · ' + d.plannedLoad : '')
            : 'not planned';
        const actual = d.actualKm != null
          ? d.actualKm + ' km'
              + (d.actualS ? ' · ' + Math.round(d.actualS / 60) + ' min' : '')
              + (d.actualPaceS ? ' @ ' + this.fmtPace(d.actualPaceS) + '/km' : '')
              + (d.actualHr ? ' · HR ' + d.actualHr : '')
          : '';
```

- [ ] **Step 5: `run.dc.html`**

Replace lines 423-431:

```js
        const glyph = { done: ['✓', 'var(--good)', 'done'], swapped: ['⇄', 'var(--good)', 'swapped'],
                        partial: ['◐', 'var(--warn)', 'partial'], missed: ['✕', 'var(--warn)', 'missed'],
                        // honest-compliance: calm, never amber — neither is a failure
                        rest: ['✓', 'var(--sub)', 'rest'], untracked: ['—', 'var(--sub)', 'not tracked'] }[P.status] || ['·', 'var(--sub)', P.status];
        const reasonWord = { distance: 'shorter than planned', duration: 'shorter than the prescribed time', intensity: 'ran too hard for the intent' }[P.reason] || P.reason;
        pg.plan = [{
          sub: (P.wk ? P.wk + ' · ' : '') + P.date + (P.status === 'swapped' ? ' — matched to a different day than planned' : ''),
          statusGlyph: glyph[0], statusColor: glyph[1], statusWord: glyph[2],
          planned: (P.plannedTitle || P.plannedKind || 'session') + (P.plannedS ? ' · ' + Math.round(P.plannedS / 60) + ' min' : P.plannedKm ? ' · ' + P.plannedKm + ' km' : '') + (P.plannedLoad ? ' · ' + P.plannedLoad : ''),
          actual: km.toFixed(1) + ' km @ ' + this.fmtPace(paceS) + '/km' + (run.avgHr ? ' · HR ' + run.avgHr : ''),
          reason: P.reason ? [{ t: reasonWord }] : [],
```

- [ ] **Step 6: Run the frontend tests**

Run: `node test_run_page.mjs`
Expected: PASS

Run the rest of the `.mjs` suite to catch regressions:
```bash
for f in test_*.mjs; do echo "== $f"; node "$f" || echo "FAILED $f"; done
```
Expected: no `FAILED` lines. (`node:sqlite` experimental warnings are normal noise.)

- [ ] **Step 7: Commit**

```bash
git add "Running Dashboard.dc.html" progress.dc.html run.dc.html test_run_page.mjs
git commit -m "feat(ui): render rest and untracked days without alarm

Both new statuses land in all three glyph maps in --sub, never --warn: amber
is now reserved for a slot that was genuinely required, genuinely trackable,
and genuinely short. Rest reads ✓ rest rather than green — resting on a rest
day is compliance, not an achievement.

A time-scored day is read in the unit it was prescribed in: '20 min' planned,
'2.4 km · 23 min' actual, and 'shorter than the prescribed time' when short."
```

---

## Task 11: Bump the version, prove it on real data, deploy

**Files:**
- Modify: `plan_compliance.py:43` (`COMPLIANCE_VERSION`)
- Create: `test_honest_compliance_oracle.py`
- Test: the full suite, then both NUC containers

**Interfaces:**
- Consumes: everything above.
- Produces: `COMPLIANCE_VERSION = 4`, which makes `_rescore_stale` heal every frozen week against its original snapshot on the next sync.

- [ ] **Step 1: Bump the version**

In `plan_compliance.py`, line 43:

```python
COMPLIANCE_VERSION = 4   # 2: rep-level quality verdicts (add-plan-prescription);
                         # 3: non-run slots carry none (the bike-intervals seam);
                         # 4: honest compliance — rest is satisfied by resting,
                         #    unrecordable kinds are untracked, time-prescribed
                         #    days are scored on time, the swap pass runs
                         #    mid-week, an uncalibrated lens makes no rep claim
```

- [ ] **Step 2: Write the real-data oracle test**

This is the gate that matters: the fix must be visible on Max's instance and near-invisible on Felix's. It reads local archive copies and **skips** when they are absent, mirroring the existing oracle-test pattern.

Create `test_honest_compliance_oracle.py`:

```python
#!/usr/bin/env python3
"""Real-data regression for honest-compliance, against local archive copies.

Skips when the copies are absent, like the other oracle tests. Refresh them
with a CONSISTENT snapshot (never copy a live SQLite file):

  ssh felix@192.168.0.37 "cd ~/dev/docker-compose-files/splits && \\
    docker compose exec -T splits-max python3 -c \\
    \"import sqlite3,os; s=sqlite3.connect('/data/activity-archive.db'); \\
      d=sqlite3.connect('/data/_snap.db'); s.backup(d); d.close(); \\
      os.chmod('/data/_snap.db',0o644)\""
  scp felix@192.168.0.37:'~/dev/docker-compose-files/splits/volumes/splits-max-data/_snap.db' \\
      ./activity-archive-max.db
  ssh felix@192.168.0.37 "rm ~/dev/docker-compose-files/splits/volumes/splits-max-data/_snap.db"

Both files are gitignored.
"""
from __future__ import annotations

import datetime as dt
import shutil
import tempfile
from pathlib import Path

import pytest

import activity_archive as arch
import plan_compliance as pc

REPO = Path(__file__).parent
MAX_DB = REPO / "activity-archive-max.db"
FELIX_DB = REPO / "activity-archive.db"
TODAY = dt.date(2026, 8, 5)
MAX_HR_MAX, MAX_HR_FELIX = 199, 197


def _scratch(db: Path):
    """Open a THROWAWAY copy — an oracle test never writes the real file."""
    d = Path(tempfile.mkdtemp())
    shutil.copy(db, d / "activity-archive.db")
    return arch.open_archive(d)


def _rescore(conn, max_hr: int, today: dt.date) -> list[dict]:
    """Rescore every banked week under the current engine, against the
    snapshot each week originally referenced."""
    conn.execute("UPDATE plan_compliance SET compliance_version = 0")
    conn.commit()
    pc._rescore_stale(conn, today, max_hr)
    return arch.compliance_rows(conn)


@pytest.mark.skipif(not MAX_DB.exists(), reason="no Max archive copy")
def test_max_stops_being_told_he_failed():
    """Measured 2026-08-05 before the fix: 10 missed (6 rest, 3 strength, 1
    real), 2 partial, 35% executed — against a true adherence of 7 of 8
    sessions. Every one of those nine false negatives must be gone, and the
    one real miss must survive."""
    conn = _scratch(MAX_DB)
    rows = [r for r in _rescore(conn, MAX_HR_MAX, TODAY)
            if r["planned_kind"] is not None]
    by_status = {}
    for r in rows:
        by_status.setdefault(r["status"], []).append(r)

    missed = by_status.get("missed", [])
    assert all(r["planned_kind"] == "run" for r in missed), \
        f"only a RUN can be missed now: {[(r['date'], r['planned_kind']) for r in missed]}"
    assert len(missed) == 1 and missed[0]["date"] == "2026-07-20", \
        "his first planned day is the one genuinely skipped run in the block"
    assert by_status.get("partial", []) == [], \
        "both partials were duration sessions he completed"
    assert len(by_status.get("rest", [])) >= 6
    assert len(by_status.get("untracked", [])) >= 3
    assert all(r["planned_kind"] != "rest" for r in missed)
    conn.close()


@pytest.mark.skipif(not MAX_DB.exists(), reason="no Max archive copy")
def test_max_time_sessions_are_scored_in_minutes():
    conn = _scratch(MAX_DB)
    rows = {r["date"]: r for r in _rescore(conn, MAX_HR_MAX, TODAY)
            if r["planned_kind"] is not None}
    for date, planned_min in (("2026-07-30", 22), ("2026-08-01", 26)):
        r = rows[date]
        assert r["status"] == "done", f"{date} was completed in full"
        assert r["planned_s"] == planned_min * 60
    conn.close()


@pytest.mark.skipif(not MAX_DB.exists(), reason="no Max archive copy")
def test_no_rep_verdict_quotes_a_zero_on_an_uncalibrated_archive():
    conn = _scratch(MAX_DB)
    for r in _rescore(conn, MAX_HR_MAX, TODAY):
        q = r.get("quality_json") or ""
        assert "0/" not in q, f"{r['date']} still quotes an uncounted zero: {q}"
    conn.close()


@pytest.mark.skipif(not FELIX_DB.exists(), reason="no local archive")
def test_felixs_instance_barely_moves():
    """The other half of the gate. His plan authors no rest days and his watch
    logs strength, so his genuinely missed strength days must STAY missed —
    the capability check must not become a blanket amnesty."""
    conn = _scratch(FELIX_DB)
    rows = [r for r in _rescore(conn, MAX_HR_FELIX, TODAY)
            if r["planned_kind"] is not None]
    assert not any(r["status"] == "rest" for r in rows), \
        "his plan authors no rest days"
    assert not any(r["status"] == "untracked" for r in rows), \
        "his archive sees every kind his plan prescribes"
    assert any(r["status"] == "missed" and r["planned_kind"] == "strength"
               for r in rows), \
        "a skipped strength day on a tracking instance is still a skipped day"
    conn.close()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
```

- [ ] **Step 3: Fetch Max's archive copy and run the oracle**

```bash
ssh felix@192.168.0.37 "cd ~/dev/docker-compose-files/splits && docker compose exec -T splits-max python3 -c \"import sqlite3,os; s=sqlite3.connect('/data/activity-archive.db'); d=sqlite3.connect('/data/_snap.db'); s.backup(d); d.close(); os.chmod('/data/_snap.db',0o644)\""
scp felix@192.168.0.37:'~/dev/docker-compose-files/splits/volumes/splits-max-data/_snap.db' ./activity-archive-max.db
ssh felix@192.168.0.37 "rm ~/dev/docker-compose-files/splits/volumes/splits-max-data/_snap.db"
echo "activity-archive-max.db" >> .gitignore
```

Run: `./.venv/Scripts/python.exe -m pytest test_honest_compliance_oracle.py -v`
Expected: PASS, no skips.

**If a test fails, the fix is wrong — not the test.** These numbers were measured on the live archive on 2026-08-05 and are the whole point of the change. Debug the engine.

- [ ] **Step 4: Run the entire suite**

```bash
./.venv/Scripts/python.exe -m pytest -q
for f in test_*.mjs; do echo "== $f"; node "$f" || echo "FAILED $f"; done
```
Expected: all green, no `FAILED` lines.

- [ ] **Step 5: Commit**

```bash
git add plan_compliance.py test_honest_compliance_oracle.py .gitignore
git commit -m "feat(compliance): COMPLIANCE_VERSION 4 — honest compliance

Bumping the version makes _rescore_stale heal every frozen week against the
snapshot it originally referenced, so Max's whole history re-scores itself on
the next sync with no manual step and no risk of a later plan edit rewriting
what a scored day was measured against.

The oracle test pins both halves of the gate on real archives: Max loses all
nine false negatives and keeps his one real missed run; Felix's instance
gains no rest or untracked days and keeps his genuinely missed strength days
missed. Fails loudly if the capability check ever becomes a blanket amnesty."
```

- [ ] **Step 6: Deploy and verify on the NUC**

Push, let CI build `:latest`, then:

```bash
ssh felix@192.168.0.37 "cd ~/dev/docker-compose-files/splits && docker compose pull && docker compose up -d"
ssh felix@192.168.0.37 "cd ~/dev/docker-compose-files/splits && docker compose exec -T splits python3 sync_garmin.py --verify-archive"
ssh felix@192.168.0.37 "cd ~/dev/docker-compose-files/splits && docker compose exec -T splits-max python3 sync_garmin.py --verify-archive"
```
Expected: exit 0 on both.

Then confirm the healed numbers on Max's instance:

```bash
ssh felix@192.168.0.37 "cd ~/dev/docker-compose-files/splits && docker compose exec -T splits-max python3 -c \"
import sqlite3, json
c = sqlite3.connect('file:/data/activity-archive.db?mode=ro', uri=True)
print('status counts:', [tuple(r) for r in c.execute('select status, count(*) from plan_compliance group by 1 order by 2 desc')])
print('version:', c.execute('select distinct compliance_version from plan_compliance').fetchall())
d = json.loads(c.execute('select block_json from block_lens order by rowid desc limit 1').fetchone()[0])
print('percentExecuted:', d['execution']['percentExecuted'])
\""
```

Expected: `compliance_version` is `4` everywhere; `missed` is `1`; `partial` is `0`; `rest` ≥ 6; `untracked` ≥ 3; `percentExecuted` ≈ 88.

**Note:** the block lens recomputes on the next sync, so `percentExecuted` may still read the stale 35 until the nightly 08:00 CEST run. To confirm immediately, run a full sync on Max's container (`docker compose exec -T splits-max python3 sync_garmin.py`) and re-read.

Finally, open `https://splits-max.mochii.dev` and confirm the week reads the way the approved mockup does — rest days calm, mobility days `— not tracked`, both Thursday and Saturday `✓ done`.

- [ ] **Step 7: Report the verification honestly**

State the actual observed numbers from Step 6, not the expected ones. If anything differs, say so and stop — do not paper over a discrepancy.

---

## Self-Review

**Spec coverage:** D1 → Task 3. D2 → Task 4. D3 → Tasks 1, 5. D4 → Task 6. D5 → Task 7. D6 → Task 8. D7 → Task 9. Contract changes (statuses, reasons, new columns, version, glyphs) → Tasks 2, 5, 10, 11. Testing section → tests embedded in every task plus the Task 11 oracle. **Gap found and closed:** the spec's blast-radius table omitted `validate_data.py`, whose `_COMPLIANCE_STATUSES` / `plannedKind` / `reason` whitelists would have rejected the new vocabulary on the first sync — now Task 2, deliberately ordered before any producer.

**Type consistency:** `duration_for_day(segments) -> int | None` (Task 1) is called only in Task 5, with `day.get("segments")`. `tracked_kinds(conn, today) -> set[str]` (Task 4) feeds `score_week(..., tracked)` in both `run_compliance` and `_rescore_stale`. `planned_s` / `actual_s` are snake_case in Python rows and `plannedS` / `actualS` in the JS contract throughout — the boundary is `assemble_compliance` (Task 5) and `_day_row` (Task 8).

**Known behaviour changes to pre-existing tests, both intentional and both rewritten in-plan:** `test_open_week_no_swap_and_pending` (Task 6) and `test_validate_data_compliance_shape` (Task 2). No other existing test changes.
