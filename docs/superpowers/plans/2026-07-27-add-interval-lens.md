# Interval Lens (Change 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect the interval/tempo/progression structure of every archived run — for both the Garmin and the Health Connect pipeline — and render its reps on `/run/:id`.

**Architecture:** A new pure Python engine (`interval_lens.py`) turns a run's columnar streams (plus Garmin lap DTOs when they encode real structure) into one versioned document per run, stored in a new `run_intervals` table with the same disposable-cache semantics as `run_metrics`. `serve.mjs` serves the document verbatim; `run.dc.html` renders it. Detection runs **blind** in this change — the plan-prior interface exists but is always `None` (spec D8).

**Tech Stack:** Python 3.12 stdlib only (no new runtime dependencies), Node 24 (`node:sqlite`), React 18.3.1 UMD via `vendor/`, Playwright for page specs.

## Global Constraints

- **Stdlib only** in Python — nothing added to `requirements.txt`. `pytest` goes in a new `requirements-dev.txt`, never the runtime file.
- **Zero-dependency `serve.mjs`** — the API is a window, not an engine. It SELECTs stored rows, renames fields, and returns them. No domain formulas.
- **The archive is additive-only.** Schema v11 is `CREATE TABLE IF NOT EXISTS` plus a guarded `ALTER`. Never drop, never rewrite raw payloads.
- **Write-once for raw payloads.** `laps_json` follows `detail_json`: only stored on a successful fetch, never overwritten with an empty result.
- **Derived rows are disposable.** Every algorithm parameter lives under `INTERVAL_VERSION`; changing one means bumping it, never a migration.
- **Fail-soft sync.** Every new sync step runs inside `safe()`. An interval problem is a warning; `garmin-data.js` is still written.
- **The cockpit renders from static files alone.** Anything the cockpit shows must land in `garmin-data.js`, never require the archive API.
- **Unicode literals in JSX/`.dc.html` text** — `ä`, `×`, `–` typed directly, never `\uXXXX`.
- **No TypeScript casting.** (Not applicable to this change's files, but holds if any `.ts` is touched.)
- **`INTERVAL_VERSION = 1`** for this change. Change 2 bumps it to 2 when the plan prior starts being filled.

---

### Task 1: Establish the Python test runner

Eight of the nine Python test files are pytest-style plain functions, but `pytest` is installed in neither `.venv` nor the global interpreter — only `test_course_lens.py` (unittest-style) runs today. Every later task in this plan depends on being able to watch a test fail, so this comes first.

**Files:**
- Create: `requirements-dev.txt`
- Modify: `README.md` (test-running section)

- [ ] **Step 1: Create the dev requirements file**

```
# SPLITS — development-only dependencies (never installed in the image).
# Install:  .venv/Scripts/python -m pip install -r requirements-dev.txt
pytest>=8.4        # the Python suite is pytest-style plain functions
```

- [ ] **Step 2: Install it**

Run: `.venv/Scripts/python.exe -m pip install -r requirements-dev.txt`
Expected: pytest installs; no change to `requirements.txt`.

- [ ] **Step 3: Verify the existing suite runs**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: the existing Python tests collect and pass. If any pre-existing failure appears, record it in the commit message — do **not** fix unrelated failures in this task.

- [ ] **Step 4: Document it in the README**

Add to the README's project-layout table region, after the `tools/style-audit.mjs` row:

```markdown
| `requirements-dev.txt` | **Development-only dependencies** — `pytest` for the Python suite. Never installed into the image; the runtime stays on `requirements.txt` alone. Run the suite with `python -m pytest -q`. |
```

- [ ] **Step 5: Commit**

```bash
git add requirements-dev.txt README.md
git commit -m "chore(test): pin pytest as a dev-only dependency

The Python suite is pytest-style but pytest was installed nowhere, so most
of it could not be run. Dev deps stay out of requirements.txt so the image
is unchanged."
```

---

### Task 2: Engine — signal preparation

**Files:**
- Create: `interval_lens.py`
- Create: `test_interval_lens.py`

**Interfaces:**
- Produces: `INTERVAL_VERSION: int`, `speed_series(streams: dict) -> list[float | None]`, `smooth(series: list, window: int = SMOOTH_WINDOW_S) -> list[float | None]`, `distance_fn(streams: dict) -> Callable[[int], float]`, and the module constants below. All later tasks consume these.

- [ ] **Step 1: Write the failing tests**

```python
#!/usr/bin/env python3
"""Tests for the interval-lens engine (add-interval-lens).

Synthetic streams are built from (duration, speed) spans so every expected
boundary is known exactly; the real-archive ground truth lives in Task 15.
"""
from __future__ import annotations

import interval_lens as il


def make_streams(spans, hr=150, gap=False):
    """spans: [(duration_s, mps)] → columnar streams at 1 Hz, like the archive's."""
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
    out = {"t": t, "d": d, "v": v, "hr": hrs}
    if gap:
        out["gap"] = list(v)
    return out


def test_speed_series_is_one_hz_over_the_span():
    s = make_streams([(100, 3.0)])
    assert len(il.speed_series(s)) == 100


def test_speed_series_prefers_grade_adjusted():
    """D5: GAP wins over raw speed — on hills it is the honest effort signal."""
    s = make_streams([(100, 3.0)], gap=True)
    s["gap"] = [4.0] * 100
    assert il.speed_series(s)[50] == 4.0


def test_speed_series_holds_across_sample_gaps():
    """Garmin samples every ~2 s; the grid must hold the last reading, not hole.

    The span MUST clear MIN_SPAN_S or the guard returns [] and this test proves
    nothing — `all()` over an empty list is vacuously true, and the assertion
    passes even with the hold-forward step deleted."""
    n = 31                                   # 0,2,…,60 → span 60, clears the guard
    s = {"t": [i * 2 for i in range(n)],
         "d": [round(i * 2 * 3.0) for i in range(n)],
         "v": [3.0] * n}
    out = il.speed_series(s)
    assert len(out) == 61                    # one entry per second, endpoint included
    assert all(v == 3.0 for v in out)        # every in-between second was held


def test_standing_still_is_none_not_zero():
    """A pause is absent data, not a very slow rep — it must not join a class."""
    s = make_streams([(30, 3.0), (30, 0.0), (30, 3.0)])
    assert il.speed_series(s)[45] is None


def test_short_activity_yields_nothing():
    assert il.speed_series(make_streams([(30, 3.0)])) == []


def test_smooth_kills_a_single_sample_spike():
    series = [3.0] * 41
    series[20] = 9.0
    assert il.smooth(series)[20] == 3.0


def test_smooth_preserves_a_real_edge():
    """A 15 s median must not blur a 30 s rep into its recovery."""
    series = [2.5] * 60 + [4.0] * 60
    out = il.smooth(series)
    assert out[30] == 2.5 and out[90] == 4.0


def test_distance_fn_reads_cumulative_metres():
    at = il.distance_fn(make_streams([(100, 3.0)]))
    assert at(100) - at(0) == 297  # 99 whole-second steps of 3 m, rounded
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest test_interval_lens.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'interval_lens'`

- [ ] **Step 3: Write the implementation**

```python
#!/usr/bin/env python3
"""interval_lens.py — the interval lens: what STRUCTURE did this run have?

`splits` in this project has always meant per-kilometre averages, which smear a
rep and its recovery into one number. This engine answers the other question:
where were the work bouts, how fast were they, and how much did they cost.

ONE engine, TWO producers — sync_garmin.py (Garmin: streams + lap DTOs) and
ingest_builder.py (Health Connect: streams only, no laps ever). Pure over its
inputs: no clock, no network, no database. Testable like chart-core.js.

Design: docs/superpowers/specs/2026-07-27-interval-lens-design.md
Changing ANY parameter below requires bumping INTERVAL_VERSION — stored
documents are a disposable cache and the bump self-heals every row.
"""
from __future__ import annotations

INTERVAL_VERSION = 1

# ── algorithm parameters — all covered by INTERVAL_VERSION ───────────────────
SMOOTH_WINDOW_S = 15       # rolling median: kills GPS chatter, keeps a 30 s edge
MOVING_MPS_MIN = 0.5       # below this the athlete is stopped, not recovering
MIN_SPAN_S = 60            # shorter than this and there is nothing to segment


def speed_series(streams: dict) -> list[float | None]:
    """A 1 Hz speed grid over the run's elapsed span, last-value-held across
    sample gaps. Grade-adjusted speed wins over raw speed when the payload
    carries it (design D5): on a hill, a rep up and a rep down are the same
    effort, and raw pace would read the set as a fade. Samples below
    MOVING_MPS_MIN become None — a pause is absent data, not a slow rep."""
    t = streams.get("t") or []
    src = streams.get("gap") or streams.get("v") or []
    if len(t) < 2 or len(src) != len(t):
        return []
    t0 = int(t[0])
    span = int(t[-1]) - t0
    if span < MIN_SPAN_S:
        return []
    # span + 1 — inclusive of the endpoint sample, matching distance_fn's grid,
    # so index i means second i in BOTH. Later tasks cross-reference the two by
    # index; sizing this at `span` would let distance_fn accept an index the
    # speed grid does not have.
    grid: list = [None] * (span + 1)
    for i, ts in enumerate(t):
        k = int(ts) - t0
        if 0 <= k <= span and src[i] is not None:
            grid[k] = float(src[i])
    held = None
    for k in range(span + 1):
        if grid[k] is None:
            grid[k] = held
        else:
            held = grid[k]
    return [v if (v is not None and v >= MOVING_MPS_MIN) else None for v in grid]


def smooth(series: list, window: int = SMOOTH_WINDOW_S) -> list:
    """Rolling median over the 1 Hz grid. A median (not a mean) because one
    GPS spike must not drag the window, and the window is sized against the
    30 s minimum bout so a real rep edge survives it."""
    if not series:
        return []
    half = window // 2
    out = []
    for i in range(len(series)):
        vals = [v for v in series[max(0, i - half): i + half + 1] if v is not None]
        out.append(sorted(vals)[len(vals) // 2] if vals else None)
    return out


def distance_fn(streams: dict):
    """second → cumulative metres, on the same 1 Hz grid as speed_series. Used
    to enforce the minimum-distance rule on a bout and to measure reps."""
    t = streams.get("t") or []
    d = streams.get("d") or []
    if len(t) < 2 or len(d) != len(t):
        return lambda s: 0.0
    t0 = int(t[0])
    span = int(t[-1]) - t0
    grid: list = [None] * (span + 1)
    for i, ts in enumerate(t):
        k = int(ts) - t0
        if 0 <= k <= span and d[i] is not None:
            grid[k] = float(d[i])
    held = 0.0
    for k in range(span + 1):
        if grid[k] is None:
            grid[k] = held
        else:
            held = grid[k]
    return lambda s: grid[min(max(int(s), 0), span)]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest test_interval_lens.py -q`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add interval_lens.py test_interval_lens.py
git commit -m "feat(interval-lens): 1 Hz signal preparation from columnar streams

GAP over raw speed (design D5), last-value-held across sample gaps, pauses
as None rather than very slow reps, and a rolling median sized against the
30 s minimum bout."
```

---

### Task 3: Engine — two-class separation

The load-bearing decision: is there structure here at all? Thresholding against the run's own median fails on a session that is half reps, because the median sits *between* work and rest.

**Files:**
- Modify: `interval_lens.py`
- Modify: `test_interval_lens.py`

**Interfaces:**
- Consumes: `speed_series`, `smooth` (Task 2)
- Produces: `split_classes(series: list) -> tuple[float, float, float] | None` returning `(lo_mps, hi_mps, separation)`, and `SEPARATION_MIN`.

- [ ] **Step 1: Write the failing tests**

```python
def test_split_classes_finds_two_speeds():
    s = il.smooth(il.speed_series(make_streams([(300, 2.5), (300, 4.0)])))
    lo, hi, sep = il.split_classes(s)
    assert 2.4 < lo < 2.7
    assert 3.8 < hi < 4.1


def test_near_steady_run_falls_below_the_separation_floor():
    """The guard that keeps an ordinary easy run from reading as a workout.

    The fixture needs REAL variance: a perfectly flat series returns at the
    empty-partition guard on iteration 1 and never reaches the SEPARATION_MIN
    comparison at all, so it would pass with the threshold check deleted."""
    spans = [(1, 3.0 + (0.06 if i % 2 else -0.06)) for i in range(1800)]
    s = il.smooth(il.speed_series(make_streams(spans)))
    assert il.split_classes(s) is None          # observed separation ≈ 0.039


def test_a_perfectly_flat_series_cannot_be_partitioned():
    """The OTHER bailout: with zero variation there are not two classes to
    find. Returns before any threshold is compared — a different guard from
    the separation floor above, so both need their own test."""
    assert il.split_classes([3.0] * 600) is None


def test_gentle_drift_is_not_structure():
    """A run that drifts 5 % over an hour is not an interval session."""
    spans = [(600, 3.0), (600, 2.95), (600, 2.9)]
    s = il.smooth(il.speed_series(make_streams(spans)))
    assert il.split_classes(s) is None


def test_separation_is_the_relative_speed_gap():
    s = il.smooth(il.speed_series(make_streams([(300, 2.0), (300, 4.0)])))
    _, _, sep = il.split_classes(s)
    assert 0.45 < sep < 0.55  # (4 − 2) / 4
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest test_interval_lens.py -q -k "split_classes or steady or drift or separation"`
Expected: FAIL — `AttributeError: module 'interval_lens' has no attribute 'split_classes'`

- [ ] **Step 3: Write the implementation**

Append to `interval_lens.py` (and add the constants beside the others at the top):

```python
SEPARATION_MIN = 0.12      # work must be >=12 % faster than rest to be structure
MIN_MOVING_SAMPLES = 60    # fewer than a minute of moving data decides nothing
```

```python
def split_classes(series: list) -> tuple[float, float, float] | None:
    """1-D 2-means over the moving samples → (lo_mps, hi_mps, separation), or
    None when the run has no two-class structure at all.

    Two means rather than a threshold on the median because on a session that
    is half reps the median sits BETWEEN work and rest and belongs to neither.
    `separation` is the relative speed gap; below SEPARATION_MIN the run is
    steady and detection stops here — this is the guard that keeps an easy run
    from reading as fartlek."""
    vals = sorted(v for v in series if v is not None)
    if len(vals) < MIN_MOVING_SAMPLES:
        return None
    lo, hi = vals[0], vals[-1]
    if hi <= 0:
        return None
    for _ in range(25):
        mid = (lo + hi) / 2
        low = [v for v in vals if v <= mid]
        high = [v for v in vals if v > mid]
        if not low or not high:
            return None
        new_lo, new_hi = sum(low) / len(low), sum(high) / len(high)
        converged = abs(new_lo - lo) < 1e-6 and abs(new_hi - hi) < 1e-6
        lo, hi = new_lo, new_hi
        if converged:
            break
    sep = (hi - lo) / hi
    return (lo, hi, sep) if sep >= SEPARATION_MIN else None
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest test_interval_lens.py -q`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add interval_lens.py test_interval_lens.py
git commit -m "feat(interval-lens): two-class separation as the structure gate

1-D 2-means rather than a median threshold — on a half-reps session the
median belongs to neither class. Below SEPARATION_MIN the run is steady and
detection stops, which is what keeps an easy run from reading as fartlek."
```

---

> **Measured after Task 3 — read before touching Task 4 or 5's constants.**
> `SEPARATION_MIN = 0.12` is a WEAK filter against continuous, non-bimodal
> variance. Observed separations: noisy easy run → `None` (correctly rejected);
> smooth "hilly" sinusoid over 2 h → 0.19; uniform GPS noise 2.0–4.0 m/s → 0.29;
> easy run plus a single 40 s surge → 0.31; a real 5×1 km → 0.375.
> Everything from 0.19 up **clears the structure gate**. So `split_classes` does
> not reject wide-variance unstructured runs on its own — the minimum-bout
> floors below (work ≥ 30 s AND ≥ 150 m, recovery ≥ 20 s) and the ≥ 3-bout rule
> in Task 5 carry the entire false-positive burden. Relaxing any of them
> re-opens "an easy run reads as a workout", which is this feature's worst
> failure mode.

### Task 4: Engine — bout finding with hysteresis

**Files:**
- Modify: `interval_lens.py`
- Modify: `test_interval_lens.py`

**Interfaces:**
- Consumes: `split_classes`, `distance_fn` (Tasks 2–3)
- Produces: `find_bouts(series: list, dist_at, lo: float, hi: float) -> list[tuple[int, int]]` — work bouts as `(start_s, end_s)` on the 1 Hz grid.

- [ ] **Step 1: Write the failing tests**

```python
def _bouts(spans):
    s = make_streams(spans)
    series = il.smooth(il.speed_series(s))
    classes = il.split_classes(series)
    assert classes is not None, "fixture should be structured"
    lo, hi, _ = classes
    return il.find_bouts(series, il.distance_fn(s), lo, hi)


def test_finds_five_reps():
    spans = [(600, 2.6)] + [(250, 4.0), (60, 2.2)] * 5 + [(300, 2.6)]
    assert len(_bouts(spans)) == 5


def test_rep_boundaries_land_near_the_truth():
    spans = [(600, 2.6), (250, 4.0), (60, 2.2), (250, 4.0), (300, 2.6)]
    first = _bouts(spans)[0]
    assert abs(first[0] - 600) <= 10
    assert abs(first[1] - 850) <= 10


def test_chatter_does_not_shred_one_rep():
    """Hysteresis earns its place here: without it, a wobbling rep becomes 3.

    Two traps this fixture had to escape, both found in review:
    (a) a period-7 single-sample dip is EXACTLY what SMOOTH_WINDOW_S=15's
        rolling median erases — it never reaches find_bouts, and the test then
        passes with hysteresis on or off;
    (b) a hardcoded dip value rots. The dip must sit between `leave` and
        `enter`, and the margin is set by EXIT_FRAC alone (the 4.0 peaks clear
        any plausible ENTER_FRAC), so a retune from 0.45 to 0.47 flipped the
        result. Derive the dip and assert the precondition, so a future retune
        fails loudly and diagnostically instead of silently or spuriously.
    Verified to hold across EXIT_FRAC 0.25–0.56.
    """
    probe = [(600, 2.6), (240, 4.0), (300, 2.6)]     # same lo/hi as the wobble
    lo, hi, _ = il.split_classes(il.smooth(il.speed_series(make_streams(probe))))
    enter = lo + il.ENTER_FRAC * (hi - lo)
    leave = lo + il.EXIT_FRAC * (hi - lo)
    dip = (leave + enter) / 2                        # centred: max margin both ways
    assert leave < dip < enter, "dip must sit strictly between the REAL thresholds"

    wobble = [(40, 4.0), (40, dip)] * 3
    assert len(_bouts([(600, 2.6)] + wobble + [(300, 2.6)])) == 1


def test_open_bout_auto_closes_at_the_last_sample():
    """The athlete stops the watch the instant the last rep ends — the bout is
    still open when the series runs out and must be closed at the final sample,
    not dropped."""
    spans = [(600, 2.6), (250, 4.0)]                 # no cooldown tail
    assert len(_bouts(spans)) == 1


def test_bouts_shorter_than_the_minimum_are_dropped():
    """A 20 s surge to a traffic light is not a rep."""
    spans = [(600, 2.6), (20, 4.5), (600, 2.6), (250, 4.0), (300, 2.6)]
    assert len(_bouts(spans)) == 1


def test_bouts_closer_than_the_minimum_recovery_merge():
    spans = [(600, 2.6), (200, 4.0), (10, 2.4), (200, 4.0), (300, 2.6)]
    assert len(_bouts(spans)) == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest test_interval_lens.py -q -k "bout or rep or chatter"`
Expected: FAIL — `AttributeError: module 'interval_lens' has no attribute 'find_bouts'`

- [ ] **Step 3: Write the implementation**

Constants beside the others:

```python
ENTER_FRAC = 0.65          # hysteresis: enter work at lo + .65·(hi−lo)
EXIT_FRAC = 0.45           # leave work at lo + .45·(hi−lo)
WORK_MIN_S = 30
WORK_MIN_M = 150
RECOVERY_MIN_S = 20
```

```python
def find_bouts(series: list, dist_at, lo: float, hi: float) -> list[tuple[int, int]]:
    """Walk the smoothed grid with HYSTERESIS → work bouts as (start_s, end_s).

    Entering work needs more speed than staying in it. With a single threshold
    a rep that wobbles across the line becomes three reps and the whole set
    reads wrong; the gap between ENTER_FRAC and EXIT_FRAC is what makes one rep
    stay one rep.

    Then two filters, in this order: bouts separated by less than
    RECOVERY_MIN_S are one bout (a momentary let-up is not a recovery), and a
    bout must clear BOTH a duration and a distance floor to exist at all — a
    20 s surge to a crossing is not a rep."""
    enter = lo + ENTER_FRAC * (hi - lo)
    leave = lo + EXIT_FRAC * (hi - lo)
    bouts: list[tuple[int, int]] = []
    start = None
    for i, v in enumerate(series):
        if v is None:
            continue
        if start is None and v >= enter:
            start = i
        elif start is not None and v < leave:
            bouts.append((start, i))
            start = None
    if start is not None:
        bouts.append((start, len(series) - 1))

    merged: list[list[int]] = []
    for a, b in bouts:
        if merged and a - merged[-1][1] < RECOVERY_MIN_S:
            merged[-1][1] = b
        else:
            merged.append([a, b])

    return [(a, b) for a, b in merged
            if b - a >= WORK_MIN_S and dist_at(b) - dist_at(a) >= WORK_MIN_M]
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest test_interval_lens.py -q`
Expected: 17 passed

- [ ] **Step 5: Commit**

```bash
git add interval_lens.py test_interval_lens.py
git commit -m "feat(interval-lens): hysteresis bout walk with minimum-bout floors

Entering work costs more speed than staying in it, so a wobbling rep stays
one rep. Sub-minimum bouts and sub-minimum recoveries are folded away."
```

---

### Task 5: Engine — classification, labels and set statistics

**Files:**
- Modify: `interval_lens.py`
- Modify: `test_interval_lens.py`

**Interfaces:**
- Consumes: `find_bouts`, `distance_fn`, `speed_series` (Tasks 2–4)
- Produces: `classify(bouts, series, dist_at, expect_reps: int | None = None) -> str` returning one of `"reps" | "block" | "progression" | "steady"`; `set_stats(bouts, series, dist_at, hr) -> dict`; `label_for(shape, bouts, dist_at) -> str | None`.

- [ ] **Step 1: Write the failing tests**

```python
def _classify(spans, expect_reps=None):
    s = make_streams(spans)
    series = il.smooth(il.speed_series(s))
    dist_at = il.distance_fn(s)
    classes = il.split_classes(series)
    bouts = il.find_bouts(series, dist_at, classes[0], classes[1]) if classes else []
    return il.classify(bouts, series, dist_at, expect_reps), bouts, s


def test_five_reps_classify_as_reps():
    shape, bouts, _ = _classify([(600, 2.6)] + [(250, 4.0), (60, 2.2)] * 5 + [(300, 2.6)])
    assert shape == "reps"
    assert len(bouts) == 5


def test_one_long_bout_is_a_block():
    """2 km wu · 5 km @ threshold · 1 km cd — the classic tempo shape."""
    shape, _, _ = _classify([(700, 2.9), (1100, 3.6), (350, 2.9)])
    assert shape == "block"


def test_two_bouts_are_not_reps_without_a_prior():
    """Two unexplained bouts are more likely noise than a session."""
    shape, _, _ = _classify([(600, 2.6), (250, 4.0), (60, 2.2), (250, 4.0), (300, 2.6)])
    assert shape != "reps"


def test_two_bouts_are_reps_when_a_prior_expects_a_set():
    """A prescribed 2×2 km is a real session (spec D3 / Change 2 fills this)."""
    shape, _, _ = _classify(
        [(600, 2.6), (250, 4.0), (60, 2.2), (250, 4.0), (300, 2.6)], expect_reps=2)
    assert shape == "reps"


def test_steady_run_is_steady():
    shape, bouts, _ = _classify([(2400, 3.0)])
    assert shape == "steady"
    assert bouts == []


def test_progression_is_detected_without_bouts():
    """No discrete work bouts, but a monotone ramp — its own shape (spec D2)."""
    spans = [(400, 2.7), (400, 2.85), (400, 3.0), (400, 3.15), (400, 3.35)]
    shape, _, _ = _classify(spans)
    assert shape == "progression"


def test_label_reads_as_the_session():
    _, bouts, s = _classify([(600, 2.6)] + [(250, 4.0), (60, 2.2)] * 5 + [(300, 2.6)])
    assert il.label_for("reps", bouts, il.distance_fn(s)) == "5×1 km"


def test_unequal_reps_are_varied_not_averaged():
    """The pyramid: labelling this '3×1.3 km' would be a lie."""
    spans = [(600, 2.6), (250, 4.0), (60, 2.2), (500, 4.0), (60, 2.2),
             (250, 4.0), (300, 2.6)]
    _, bouts, s = _classify(spans)
    stats = il.set_stats(bouts, il.smooth(il.speed_series(s)), il.distance_fn(s), s["hr"])
    assert stats["varied"] is True
    assert stats["nominalDistM"] is None


def test_set_stats_report_consistency_and_fade():
    spans = [(600, 2.6)] + [(250, 4.0), (60, 2.2)] * 4 + [(250, 3.6), (300, 2.6)]
    _, bouts, s = _classify(spans)
    stats = il.set_stats(bouts, il.smooth(il.speed_series(s)), il.distance_fn(s), s["hr"])
    assert stats["found"] == 5
    assert stats["prescribed"] is None      # blind detection in Change 1
    assert stats["fadePct"] > 5             # the last rep really was slower
    assert stats["paceCvPct"] > 0
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest test_interval_lens.py -q -k "classify or label or varied or set_stats or progression"`
Expected: FAIL — `AttributeError: module 'interval_lens' has no attribute 'classify'`

- [ ] **Step 3: Write the implementation**

Constants beside the others:

```python
REPS_MIN_COUNT = 3            # 2 when a prior expects a set (design D3)
BLOCK_MIN_S = 300
BLOCK_MIN_M = 1500
VARIED_TOLERANCE = 0.20       # rep distances differing by >20 % → varied
PROGRESSION_MIN_GAIN = 0.05   # last quintile >=5 % faster than the first
```

```python
def _pace_s_per_km(mps: float) -> int:
    return int(round(1000.0 / mps)) if mps and mps > 0 else 0


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _is_progression(series: list) -> bool:
    """No discrete bouts, but speed rising monotonically across quintiles. This
    replaces splitShape's first-third-vs-last-third guess with something that
    has to hold all the way through."""
    vals = [v for v in series if v is not None]
    if len(vals) < 5 * MIN_MOVING_SAMPLES:
        return False
    step = len(vals) // 5
    means = [_mean(vals[i * step:(i + 1) * step]) for i in range(5)]
    if any(m is None or m <= 0 for m in means):
        return False
    if any(means[i + 1] < means[i] for i in range(4)):
        return False
    return (means[-1] - means[0]) / means[0] >= PROGRESSION_MIN_GAIN


def classify(bouts, series, dist_at, expect_reps: int | None = None) -> str:
    """reps / block / progression / steady (design D2).

    The rep floor is 3 rather than 2: two unexplained bouts are more often a
    hill and a headwind than a session. A prior that expects a set lowers it to
    2 — a prescribed 2×2 km is real — which is the ONLY thing the prior relaxes
    about existence (design D4)."""
    floor = 2 if expect_reps and expect_reps <= 2 else REPS_MIN_COUNT
    if len(bouts) >= floor:
        return "reps"
    if len(bouts) == 1:
        a, b = bouts[0]
        if b - a >= BLOCK_MIN_S or dist_at(b) - dist_at(a) >= BLOCK_MIN_M:
            return "block"
    if _is_progression(series):
        return "progression"
    return "steady"


def label_for(shape: str, bouts, dist_at) -> str | None:
    """The one-line session name — '5×1 km', '20 min block'. None when the run
    has no shape worth naming."""
    if shape == "block" and bouts:
        a, b = bouts[0]
        return f"{int(round((b - a) / 60))} min block"
    if shape != "reps" or not bouts:
        return None
    dists = sorted(dist_at(b) - dist_at(a) for a, b in bouts)
    nominal = dists[len(dists) // 2]
    spread = (dists[-1] - dists[0]) / nominal if nominal else 1.0
    if spread > VARIED_TOLERANCE:
        parts = "-".join(f"{(dist_at(b) - dist_at(a)) / 1000:.3g}" for a, b in bouts)
        return f"{parts} km"
    return f"{len(bouts)}×{_round_dist(nominal)}"


def _round_dist(metres: float) -> str:
    """Reps are run to round numbers — snap to the one the athlete meant."""
    for target, text in ((400, "400 m"), (600, "600 m"), (800, "800 m"),
                         (1000, "1 km"), (1200, "1.2 km"), (1600, "1600 m"),
                         (2000, "2 km"), (3000, "3 km"), (5000, "5 km")):
        if abs(metres - target) / target <= 0.12:
            return text
    return f"{metres / 1000:.2g} km"


def set_stats(bouts, series, dist_at, hr: list | None) -> dict:
    """The set's own numbers — consistency, fade, and what the recoveries cost.

    `found` vs `prescribed` is the honesty contract (design D4): prescribed is
    None while detection is blind, and once Change 2 fills the prior these two
    are allowed to disagree. A bailed session reports 3 of 4."""
    reps = []
    for a, b in bouts:
        mps = _mean(series[a:b])
        reps.append({
            "durS": b - a,
            "distM": round(dist_at(b) - dist_at(a)),
            "paceS": _pace_s_per_km(mps or 0),
            "hr": int(round(_mean(hr[a:b]))) if hr and b <= len(hr) and _mean(hr[a:b]) else None,
        })
    paces = [r["paceS"] for r in reps if r["paceS"]]
    dists = sorted(r["distM"] for r in reps)
    nominal = dists[len(dists) // 2] if dists else 0
    varied = bool(nominal) and (dists[-1] - dists[0]) / nominal > VARIED_TOLERANCE

    mean_pace = _mean(paces)
    cv = None
    if mean_pace and len(paces) > 1:
        var = sum((p - mean_pace) ** 2 for p in paces) / len(paces)
        cv = round(100.0 * (var ** 0.5) / mean_pace, 1)

    recoveries = [bouts[i + 1][0] - bouts[i][1] for i in range(len(bouts) - 1)]
    drops = []
    if hr:
        for i in range(len(bouts) - 1):
            work_hr = _mean(hr[bouts[i][0]:bouts[i][1]])
            rest_hr = _mean(hr[bouts[i][1]:bouts[i + 1][0]])
            if work_hr and rest_hr:
                drops.append(work_hr - rest_hr)

    return {
        "found": len(bouts),
        "prescribed": None,
        "nominalDistM": None if varied else (nominal or None),
        "varied": varied,
        "paceS": int(round(mean_pace)) if mean_pace else None,
        "paceCvPct": cv,
        "fadePct": round(100.0 * (paces[-1] - paces[0]) / paces[0], 1)
                   if len(paces) > 1 and paces[0] else None,
        "recoveryS": int(round(_mean(recoveries))) if recoveries else None,
        "recoveryHrDrop": int(round(_mean(drops))) if drops else None,
        "reps": reps,
    }
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest test_interval_lens.py -q`
Expected: 26 passed

- [ ] **Step 5: Commit**

```bash
git add interval_lens.py test_interval_lens.py
git commit -m "feat(interval-lens): shape classification, labels and set statistics

Rep floor of 3 (2 only when a prior expects a set), varied reps labelled as
the pyramid they are rather than averaged into a lie, and found/prescribed
kept separate so a bailed session can say so."
```

---

### Task 6: Engine — the lap path and the auto-lap guard

The archive holds a 19-lap run that is simply a 19 km easy run. Without the guard it reads as a 19-rep session.

**Files:**
- Modify: `interval_lens.py`
- Modify: `test_interval_lens.py`

**Interfaces:**
- Produces: `laps_are_autolap(laps: list[dict]) -> bool`, `laps_are_structured(summary: dict, laps: list[dict]) -> bool`, `segments_from_laps(laps: list[dict]) -> list[dict]`.

- [ ] **Step 1: Write the failing tests**

```python
def _lap(dist, dur, intensity=None, hr=150):
    lap = {"distance": dist, "duration": dur, "averageHR": hr,
           "averageSpeed": dist / dur if dur else 0}
    if intensity:
        lap["intensityType"] = intensity
    return lap


def test_kilometre_autolap_is_not_structure():
    """19 laps on a 19 km easy run is auto-lap, not a 19-rep session."""
    laps = [_lap(1000, 330) for _ in range(18)] + [_lap(420, 140)]
    assert il.laps_are_autolap(laps) is True


def test_mile_autolap_is_not_structure():
    laps = [_lap(1609.34, 530) for _ in range(6)] + [_lap(300, 100)]
    assert il.laps_are_autolap(laps) is True


def test_real_reps_are_not_autolap():
    laps = [_lap(2000, 700), _lap(1000, 330), _lap(200, 90), _lap(1000, 332)]
    assert il.laps_are_autolap(laps) is False


def test_structured_needs_intensity_or_the_flag():
    summary = {"hasIntensityIntervals": True, "workoutId": 42}
    laps = [_lap(2000, 700, "WARMUP"), _lap(1000, 330, "ACTIVE"),
            _lap(200, 90, "REST"), _lap(1000, 332, "ACTIVE")]
    assert il.laps_are_structured(summary, laps) is True


def test_autolap_beats_the_workout_flag():
    """A workout run whose laps are all 1 km still carries no rep structure."""
    summary = {"workoutId": 42}
    laps = [_lap(1000, 330) for _ in range(8)]
    assert il.laps_are_structured(summary, laps) is False


def test_uniform_intensity_is_not_structure():
    summary = {"workoutId": 7}
    laps = [_lap(1200, 400, "ACTIVE"), _lap(1300, 430, "ACTIVE")]
    assert il.laps_are_structured(summary, laps) is False


def test_segments_from_laps_carry_roles():
    laps = [_lap(2000, 700, "WARMUP"), _lap(1000, 330, "ACTIVE"),
            _lap(200, 90, "REST"), _lap(1000, 332, "ACTIVE"),
            _lap(1000, 360, "COOLDOWN")]
    segs = il.segments_from_laps(laps)
    assert [s["role"] for s in segs] == \
        ["warmup", "work", "recovery", "work", "cooldown"]
    assert segs[1]["rep"] == 1 and segs[3]["rep"] == 2
    assert segs[1]["paceS"] == 330
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest test_interval_lens.py -q -k lap`
Expected: FAIL — `AttributeError: module 'interval_lens' has no attribute 'laps_are_autolap'`

- [ ] **Step 3: Write the implementation**

Constants and role map beside the others:

```python
AUTOLAP_TOLERANCE = 0.05      # laps all within ±5 % of 1 km / 1 mile = auto-lap
AUTOLAP_UNITS = (1000.0, 1609.34)

# Garmin intensityType → our role vocabulary. Anything unrecognised is work:
# an unlabelled lap inside a structured workout is far more likely a rep than
# a rest, and calling it a rest would silently shrink the set.
_LAP_ROLES = {
    "WARMUP": "warmup", "COOLDOWN": "cooldown",
    "REST": "recovery", "RECOVERY": "recovery",
    "ACTIVE": "work", "INTERVAL": "work",
}
```

```python
def laps_are_autolap(laps: list[dict]) -> bool:
    """True when every full lap is one kilometre (or one mile). Garmin's
    auto-lap fires on distance and carries NO intent — treating it as structure
    turns every long easy run into a rep session. The final lap is always a
    partial and is excluded from the test."""
    dists = [l.get("distance") for l in laps if l.get("distance")]
    if len(dists) < 3:
        return False
    body = dists[:-1]
    return any(all(abs(d - unit) / unit <= AUTOLAP_TOLERANCE for d in body)
               for unit in AUTOLAP_UNITS)


def laps_are_structured(summary: dict, laps: list[dict]) -> bool:
    """Do these laps encode real structure (design D1)? Either Garmin says so
    outright, or the run came from a workout AND its laps carry more than one
    intensity. Auto-lap vetoes both — a 1 km-lapped workout run still tells us
    nothing about where the reps were."""
    if not laps or len(laps) < 2 or laps_are_autolap(laps):
        return False
    if summary.get("hasIntensityIntervals"):
        return True
    intensities = {l.get("intensityType") for l in laps if l.get("intensityType")}
    return bool(summary.get("workoutId")) and len(intensities) > 1


def segments_from_laps(laps: list[dict]) -> list[dict]:
    """Lap DTOs → segments, taken VERBATIM (design D1). The watch is not
    guessing: boundaries, roles and per-lap statistics all come from the
    device, and nothing here re-derives them from the stream."""
    segs = []
    t0 = 0.0
    d0 = 0.0
    rep = 0
    for idx, lap in enumerate(laps):
        dur = float(lap.get("duration") or 0)
        dist = float(lap.get("distance") or 0)
        role = _LAP_ROLES.get(lap.get("intensityType"), "work")
        if role == "work":
            rep += 1
        speed = lap.get("averageSpeed") or (dist / dur if dur else 0)
        seg = {
            "idx": idx + 1, "role": role,
            "t0": int(round(t0)), "t1": int(round(t0 + dur)),
            "d0": int(round(d0)), "d1": int(round(d0 + dist)),
            "durS": int(round(dur)), "distM": int(round(dist)),
            "paceS": _pace_s_per_km(speed),
            "gapS": None,
            "hr": int(lap["averageHR"]) if lap.get("averageHR") else None,
            "cad": int(round(lap["averageRunCadence"] * 2))
                   if lap.get("averageRunCadence") else None,
        }
        if role == "work":
            seg["rep"] = rep
        segs.append(seg)
        t0 += dur
        d0 += dist
    return segs
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest test_interval_lens.py -q`
Expected: 33 passed

- [ ] **Step 5: Commit**

```bash
git add interval_lens.py test_interval_lens.py
git commit -m "feat(interval-lens): lap path with the auto-lap veto

Structured laps are taken verbatim — the watch is not guessing. Auto-lap at
1 km/1 mile vetoes the lap path entirely, including on workout runs: the
archive holds a 19-lap run that is simply 19 km easy."
```

---

### Task 7: Engine — document assembly and confidence

**Files:**
- Modify: `interval_lens.py`
- Modify: `test_interval_lens.py`

**Interfaces:**
- Consumes: everything from Tasks 2–6
- Produces: `build_document(streams: dict | None, summary: dict | None = None, laps: list[dict] | None = None, prior: dict | None = None) -> dict | None` — the whole contract from the spec. This is the ONLY function the two producers call.

- [ ] **Step 1: Write the failing tests**

```python
def test_document_shape_for_a_rep_session():
    s = make_streams([(600, 2.6)] + [(250, 4.0), (60, 2.2)] * 5 + [(300, 2.6)])
    doc = il.build_document(s)
    assert doc["version"] == il.INTERVAL_VERSION
    assert doc["shape"] == "reps"
    assert doc["source"] == "stream"
    assert doc["label"] == "5×1 km"
    assert doc["guidedBy"] is None            # blind in Change 1 (design D8)
    assert doc["set"]["found"] == 5
    assert doc["quality"]["workDistM"] > 4500


def test_steady_run_still_gets_a_document():
    """'Looked, found nothing' must never look like 'never looked'."""
    doc = il.build_document(make_streams([(2400, 3.0)]))
    assert doc["shape"] == "steady"
    assert doc["segments"] == []
    assert doc["set"] is None


def test_no_streams_means_no_document():
    """Some of Max's runs carry no SpeedRecord at all."""
    assert il.build_document(None) is None
    assert il.build_document({"t": [], "d": []}) is None


def test_structured_laps_win_over_the_stream():
    s = make_streams([(600, 2.6)] + [(250, 4.0), (60, 2.2)] * 5 + [(300, 2.6)])
    laps = [_lap(2000, 700, "WARMUP"), _lap(1000, 250, "ACTIVE"),
            _lap(150, 60, "REST"), _lap(1000, 250, "ACTIVE"),
            _lap(1000, 360, "COOLDOWN")]
    doc = il.build_document(s, {"hasIntensityIntervals": True}, laps)
    assert doc["source"] == "laps"
    assert doc["confidence"] == 1.0
    assert doc["set"]["found"] == 2        # the laps say 2, and the laps win


def test_autolap_falls_through_to_the_stream():
    s = make_streams([(600, 2.6)] + [(250, 4.0), (60, 2.2)] * 5 + [(300, 2.6)])
    laps = [_lap(1000, 330) for _ in range(8)]
    doc = il.build_document(s, {"workoutId": 9}, laps)
    assert doc["source"] == "stream"
    assert doc["set"]["found"] == 5


def test_segments_cover_warmup_reps_and_cooldown():
    s = make_streams([(600, 2.6)] + [(250, 4.0), (60, 2.2)] * 3 + [(300, 2.6)])
    roles = [seg["role"] for seg in il.build_document(s)["segments"]]
    assert roles[0] == "warmup"
    assert roles[-1] == "cooldown"
    assert roles.count("work") == 3
    assert roles.count("recovery") == 2


def test_quality_zone_is_time_weighted():
    """A 4 km rep must not be outvoted by two 400 m ones."""
    s = make_streams([(600, 2.6)] + [(250, 4.0), (60, 2.2)] * 5 + [(300, 2.6)], hr=175)
    doc = il.build_document(s, bounds=il.zone_bounds(195))
    assert doc["quality"]["zone"] == "Z5"


def test_quality_zone_is_null_without_bounds():
    """A guessed zone is worse than no zone."""
    s = make_streams([(600, 2.6)] + [(250, 4.0), (60, 2.2)] * 5 + [(300, 2.6)])
    assert il.build_document(s)["quality"]["zone"] is None


def test_zone_bounds_use_hr_reserve_when_resting_hr_is_known():
    """Karvonen when rhr is known, plain %max otherwise — the beginner-honest
    model. (ingest_builder delegates here, so this is the only definition.)"""
    assert il.zone_bounds(190) == [95, 114, 133, 152, 171, 190]
    assert il.zone_bounds(190, 48) == [119, 133, 147, 162, 176, 190]


def test_confidence_is_higher_for_a_crisp_set():
    crisp = il.build_document(
        make_streams([(600, 2.6)] + [(250, 4.2), (60, 2.2)] * 5 + [(300, 2.6)]))
    ragged = il.build_document(
        make_streams([(600, 2.8)] + [(250, 3.3), (60, 2.6)] * 5 + [(300, 2.8)]))
    assert crisp["confidence"] > ragged["confidence"]
    assert 0.0 <= ragged["confidence"] <= 1.0
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest test_interval_lens.py -q -k document`
Expected: FAIL — `AttributeError: module 'interval_lens' has no attribute 'build_document'`

- [ ] **Step 3: Write the implementation**

Constants beside the others:

```python
CONFIDENCE_ASSERT_MIN = 0.5   # below this the UI says "possible", never asserts
# Zone boundary fractions — the values ingest_builder has always used, moved
# here as THE definition (Task 11 rewrites ingest_builder._zone_bounds to
# delegate), so the two producers cannot drift on what "Z4" means. Six entries:
# _zone_of reads bounds[1:5] as the 60/70/80/90 % cut points and the trailing
# 1.00 closes the top.
ZONE_FRACTIONS = (0.50, 0.60, 0.70, 0.80, 0.90, 1.00)
```

```python
def _segments_from_bouts(bouts, series, dist_at, hr, total_s) -> list[dict]:
    """Bouts → the full segment list, with the gaps between them named. The
    first gap is a warmup and the last a cooldown; everything between is a
    recovery, because that is what it was."""
    edges = []
    cursor = 0
    for i, (a, b) in enumerate(bouts):
        if a > cursor:
            role = "warmup" if i == 0 else "recovery"
            edges.append((cursor, a, role))
        edges.append((a, b, "work"))
        cursor = b
    if cursor < total_s:
        edges.append((cursor, total_s, "cooldown" if bouts else "steady"))

    segs, rep = [], 0
    for idx, (a, b, role) in enumerate(edges):
        if b - a < 1:
            continue
        if role == "work":
            rep += 1
        mps = _mean(series[a:b])
        seg = {
            "idx": idx + 1, "role": role,
            "t0": a, "t1": b,
            "d0": int(round(dist_at(a))), "d1": int(round(dist_at(b))),
            "durS": b - a, "distM": int(round(dist_at(b) - dist_at(a))),
            "paceS": _pace_s_per_km(mps or 0),
            "gapS": None,
            "hr": int(round(_mean(hr[a:b]))) if hr and _mean(hr[a:b]) else None,
            "cad": None,
        }
        if role == "work":
            seg["rep"] = rep
        segs.append(seg)
    return segs


def _confidence(separation: float, bouts, series, cv) -> float:
    """Three factors, multiplied and clamped (spec): how far apart the two pace
    classes sit, how crisp the boundaries are, and — for a set — how regular
    the reps were. Lap-sourced documents skip this entirely at 1.0."""
    sep_factor = min(1.0, max(0.0, (separation - SEPARATION_MIN) / 0.25 + 0.4))
    crisp = 1.0
    if bouts:
        widths = [b - a for a, b in bouts]
        shortest = min(widths)
        crisp = min(1.0, shortest / (2.0 * WORK_MIN_S))
    regular = 1.0 if cv is None else min(1.0, max(0.3, 1.0 - cv / 15.0))
    return round(min(1.0, max(0.0, sep_factor * crisp * regular)), 2)


def zone_bounds(max_hr: int, rhr=None) -> list[int]:
    """The six zone boundaries — Karvonen HR-reserve when resting HR is known,
    plain %max otherwise. THE single definition: `ingest_builder._zone_bounds`
    is rewritten in Task 11 to delegate here, so the two producers cannot drift
    apart on what "Z4" means and the formula exists exactly once."""
    if rhr and 0 < rhr < max_hr:
        return [round(rhr + f * (max_hr - rhr)) for f in ZONE_FRACTIONS]
    return [round(max_hr * f) for f in ZONE_FRACTIONS]


def _zone_of(bpm: float, bounds: list[int]) -> int:
    z = 1 + sum(1 for c in bounds[1:5] if bpm >= c)
    return max(1, min(5, z))


def _quality(segments: list[dict], bounds: list[int] | None) -> dict:
    """What the coaching layer consumes (Change 2): how much genuinely hard
    running this session contained. Consumers depend on this and on `set` —
    never on `segments`.

    `zone` is the TIME-WEIGHTED modal zone across the work segments: a 4 km rep
    must not be outvoted by two 400 m ones. Null without HR or without bounds —
    a guessed zone is worse than no zone."""
    work = [s for s in segments if s["role"] == "work"]
    zone = None
    if bounds:
        weight: dict[int, float] = {}
        for s in work:
            if s.get("hr"):
                z = _zone_of(s["hr"], bounds)
                weight[z] = weight.get(z, 0) + s["durS"]
        if weight:
            zone = "Z" + str(max(weight, key=lambda k: weight[k]))
    return {
        "workDistM": sum(s["distM"] for s in work),
        "workDurS": sum(s["durS"] for s in work),
        "zone": zone,
    }


def build_document(streams: dict | None, summary: dict | None = None,
                   laps: list[dict] | None = None,
                   prior: dict | None = None,
                   bounds: list[int] | None = None) -> dict | None:
    """The ONE entry point both producers call. Returns the interval document,
    or None when the run carries no usable speed signal at all.

    Order of authority (design D1/D8): structured device laps win outright;
    otherwise the stream decides, optionally sharpened by a plan prior. In this
    change `prior` is always None — the parameter exists so Change 2 can fill
    it without reshaping the contract."""
    summary = summary or {}
    series_raw = speed_series(streams or {})
    if not series_raw:
        return None

    base = {"version": INTERVAL_VERSION, "guidedBy": None}

    if laps and laps_are_structured(summary, laps):
        segments = segments_from_laps(laps)
        work = [s for s in segments if s["role"] == "work"]
        paces = [s["paceS"] for s in work if s["paceS"]]
        mean_pace = _mean(paces)
        cv = None
        if mean_pace and len(paces) > 1:
            var = sum((p - mean_pace) ** 2 for p in paces) / len(paces)
            cv = round(100.0 * (var ** 0.5) / mean_pace, 1)
        shape = "reps" if len(work) >= 2 else ("block" if work else "steady")
        dists = sorted(s["distM"] for s in work)
        nominal = dists[len(dists) // 2] if dists else 0
        varied = bool(nominal) and (dists[-1] - dists[0]) / nominal > VARIED_TOLERANCE
        return {
            **base,
            "shape": shape, "source": "laps", "confidence": 1.0,
            "label": (f"{len(work)}×{_round_dist(nominal)}"
                      if shape == "reps" and not varied else None),
            "segments": segments,
            "set": None if shape != "reps" else {
                "found": len(work), "prescribed": None,
                "nominalDistM": None if varied else (nominal or None),
                "varied": varied,
                "paceS": int(round(mean_pace)) if mean_pace else None,
                "paceCvPct": cv, "fadePct":
                    round(100.0 * (paces[-1] - paces[0]) / paces[0], 1)
                    if len(paces) > 1 and paces[0] else None,
                "recoveryS": None, "recoveryHrDrop": None,
                "reps": [{"durS": s["durS"], "distM": s["distM"],
                          "paceS": s["paceS"], "hr": s["hr"]} for s in work],
            },
            "quality": _quality(segments, bounds),
        }

    series = smooth(series_raw)
    dist_at = distance_fn(streams or {})
    hr = _hr_grid(streams or {}, len(series))
    classes = split_classes(series)
    bouts = find_bouts(series, dist_at, classes[0], classes[1]) if classes else []
    expect = (prior or {}).get("count")
    shape = classify(bouts, series, dist_at, expect)
    if shape in ("steady", "progression"):
        bouts = []
    stats = set_stats(bouts, series, dist_at, hr) if shape == "reps" else None
    segments = (_segments_from_bouts(bouts, series, dist_at, hr, len(series))
                if shape != "steady" else [])
    return {
        **base,
        "shape": shape, "source": "stream",
        "confidence": _confidence(classes[2] if classes else 0.0, bouts, series,
                                  stats["paceCvPct"] if stats else None),
        "label": label_for(shape, bouts, dist_at),
        "segments": segments,
        "set": stats,
        "quality": _quality(segments, bounds),
    }


def _hr_grid(streams: dict, length: int) -> list:
    """HR on the same 1 Hz grid as the speed series, last-value-held."""
    t = streams.get("t") or []
    hr = streams.get("hr") or []
    if len(t) < 2 or len(hr) != len(t):
        return []
    t0 = int(t[0])
    grid: list = [None] * length
    for i, ts in enumerate(t):
        k = int(ts) - t0
        if 0 <= k < length and hr[i] is not None:
            grid[k] = float(hr[i])
    held = None
    for k in range(length):
        if grid[k] is None:
            grid[k] = held
        else:
            held = grid[k]
    return grid
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest test_interval_lens.py -q`
Expected: 43 passed

- [ ] **Step 5: Commit**

```bash
git add interval_lens.py test_interval_lens.py
git commit -m "feat(interval-lens): document assembly, confidence and the one entry point

build_document() is the only function the two producers call. Structured
laps win outright at confidence 1.0; otherwise the stream decides. A steady
run still gets a document so 'looked, found nothing' stays distinguishable
from 'never looked'."
```

---

### Task 8: Storage — schema v11

**Files:**
- Modify: `activity_archive.py:48` (`SCHEMA_VERSION`), after `SCHEMA_V10_SQL` (new schema block), `_open` (apply), and the derived-table function region near `runs_missing_metrics:548`
- Modify: `test_activity_archive.py`

**Interfaces:**
- Produces: `write_laps(conn, activity_id, payload) -> bool`, `laps_payload(conn, activity_id) -> list | None`, `runs_missing_laps(conn, limit=None) -> list`, `runs_missing_intervals(conn, version) -> list[tuple]`, `upsert_run_intervals(conn, row: dict) -> None`, `interval_document(conn, activity_id) -> dict | None`, `intervals_coverage(conn, version) -> dict`.

- [ ] **Step 1: Write the failing tests**

Append to `test_activity_archive.py`. That file imports the module via importlib as `arch` and builds fixtures with its own `_tmp()` / `_act()` helpers — no pytest fixtures — so these follow the same shape. `_seeded()` is a new local helper: an archive holding one streamed run.

```python
def _seeded():
    """An archive with one archived, streamed run — the precondition every
    interval test shares."""
    conn = arch.open_archive(_tmp())
    arch.upsert_activities(conn, [_act(1, start="2026-07-10 06:00:00")])
    arch.write_streams(conn, 1, {"t": [0, 1, 2], "d": [0, 3, 6], "v": [3.0, 3.0, 3.0]})
    return conn


def _interval_row(**over):
    row = {"activity_id": 1, "lens_version": 1,
           "start_time_local": "2026-07-10 06:00:00", "shape": "reps",
           "label": "5×1 km", "confidence": 0.8, "source": "stream",
           "work_dist_m": 5000, "work_dur_s": 1250,
           "doc_json": '{"shape":"reps","label":"5×1 km"}'}
    row.update(over)
    return row


def test_schema_v11_tables_exist():
    conn = arch.open_archive(_tmp())
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "run_intervals" in names
    cols = {r[1] for r in conn.execute("PRAGMA table_info(activities)")}
    assert "laps_json" in cols
    assert arch.get_meta(conn, "schema_version") == "11"
    conn.close()


def test_laps_are_write_once():
    conn = _seeded()
    assert arch.write_laps(conn, 1, [{"distance": 1000}]) is True
    assert arch.write_laps(conn, 1, [{"distance": 5}]) is False
    assert arch.laps_payload(conn, 1)[0]["distance"] == 1000
    conn.close()


def test_empty_laps_are_refused():
    conn = _seeded()
    assert arch.write_laps(conn, 1, []) is False
    assert arch.laps_payload(conn, 1) is None
    conn.close()


def test_stale_interval_rows_count_as_missing():
    """A version bump must self-heal without a migration."""
    conn = _seeded()
    arch.upsert_run_intervals(conn, _interval_row())
    assert arch.runs_missing_intervals(conn, 1) == []
    assert len(arch.runs_missing_intervals(conn, 2)) == 1
    conn.close()


def test_interval_document_round_trips():
    conn = _seeded()
    arch.upsert_run_intervals(conn, _interval_row(
        shape="block", label="20 min block",
        doc_json='{"shape":"block","label":"20 min block"}'))
    assert arch.interval_document(conn, 1)["label"] == "20 min block"
    conn.close()


def test_single_lap_runs_are_never_queued_for_lap_fetch():
    """The archive's 42 single-lap runs must never cost a Garmin request."""
    conn = arch.open_archive(_tmp())
    solo = _act(1, start="2026-07-10 06:00:00")
    solo["lapCount"] = 1
    many = _act(2, start="2026-07-11 06:00:00")
    many["lapCount"] = 13
    arch.upsert_activities(conn, [solo, many])
    assert arch.runs_missing_laps(conn) == [2]
    conn.close()
```

**Note for the implementer:** `_act()` does not currently emit `lapCount`, and `runs_missing_laps` reads it out of `summary_json` via `json_extract`. `upsert_activities` stores the whole summary dict, so setting `lapCount` on the fixture dict (as above) is sufficient — no change to `_act()` itself.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest test_activity_archive.py -q -k "interval or laps or v11"`
Expected: FAIL — `assert 'run_intervals' in names`

- [ ] **Step 3: Write the implementation**

Bump `SCHEMA_VERSION = 11`, add after `SCHEMA_V10_SQL`:

```python
# Schema v11 (add-interval-lens, design D6): the run's STRUCTURE — which parts
# of it were work. `run_intervals` is one row per run holding the full document
# (`doc_json`); the promoted columns are the index over it, exactly as
# `block_lens.block_json` and `course_lens.lens_json` work. Disposable-cache
# semantics like run_metrics: always recomputable from streams + laps, keyed by
# the engine's INTERVAL_VERSION, so a threshold change is a version bump and
# never a migration. `activities.laps_json` is the raw Garmin lap payload,
# write-once like detail_json — Health Connect never produces one.
SCHEMA_V11_SQL = """
CREATE TABLE IF NOT EXISTS run_intervals (
  activity_id      INTEGER PRIMARY KEY REFERENCES activities(activity_id),
  lens_version     INTEGER NOT NULL,
  start_time_local TEXT NOT NULL,
  shape            TEXT NOT NULL,
  label            TEXT,
  confidence       REAL,
  source           TEXT NOT NULL,
  work_dist_m      REAL,
  work_dur_s       REAL,
  doc_json         TEXT NOT NULL,
  computed_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_run_intervals_start
  ON run_intervals(start_time_local);
CREATE INDEX IF NOT EXISTS idx_run_intervals_shape ON run_intervals(shape);
"""


def _apply_schema_v11(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(activities)")}
    if "laps_json" not in cols:
        conn.execute("ALTER TABLE activities ADD COLUMN laps_json TEXT")
        conn.execute("ALTER TABLE activities ADD COLUMN laps_fetched_at TEXT")
```

In `_open`, after the `SCHEMA_V10_SQL` line:

```python
        conn.executescript(SCHEMA_V11_SQL)
        _apply_schema_v11(conn)
```

…and update the forward-only migration comment from `v1→…→v10` to `v1→…→v11`.

Add the access functions beside `runs_missing_metrics`:

```python
_RUN_INTERVALS_COLS = (
    "activity_id", "lens_version", "start_time_local", "shape", "label",
    "confidence", "source", "work_dist_m", "work_dur_s", "doc_json",
)


def write_laps(conn: sqlite3.Connection, activity_id, payload) -> bool:
    """Store the RAW lap DTO list, write-once — same rule as write_detail: an
    empty or failed fetch is refused, and existing laps are never overwritten.
    Commits per call so an interrupted backfill keeps its completed work."""
    if not payload:
        return False
    cur = conn.execute(
        "UPDATE activities SET laps_json = ?, laps_fetched_at = ? "
        "WHERE activity_id = ? AND laps_json IS NULL",
        (json.dumps(payload, ensure_ascii=False), _now(), activity_id),
    )
    conn.commit()
    return cur.rowcount == 1


def laps_payload(conn: sqlite3.Connection, activity_id):
    row = conn.execute(
        "SELECT laps_json FROM activities WHERE activity_id = ?",
        (activity_id,)).fetchone()
    return json.loads(row[0]) if row and row[0] else None


def runs_missing_laps(conn: sqlite3.Connection, limit: int | None = None) -> list:
    """Runs whose summary claims more than one lap but whose laps we have never
    fetched. A one-lap run has nothing to fetch, which is why the archive's 42
    single-lap runs never cost a request."""
    sql = f"""SELECT a.activity_id FROM activities a
              WHERE a.laps_json IS NULL AND {_RUN_TYPE_SQL}
                AND json_extract(a.summary_json, '$.lapCount') > 1
              ORDER BY a.start_time_local DESC"""
    rows = (conn.execute(sql + " LIMIT ?", (limit,)).fetchall()
            if limit is not None else conn.execute(sql).fetchall())
    return [r[0] for r in rows]


def runs_missing_intervals(conn: sqlite3.Connection, version: int) -> list[tuple]:
    """(activity_id, start_time_local) of every archived run holding streams but
    no run_intervals row at `version` — rows at a stale version count as
    missing, which is how an INTERVAL_VERSION bump self-heals."""
    return conn.execute(
        f"""SELECT a.activity_id, a.start_time_local
            FROM activities a
            LEFT JOIN run_intervals i
              ON i.activity_id = a.activity_id AND i.lens_version = ?
            WHERE a.detail_streams_json IS NOT NULL
              AND {_RUN_TYPE_SQL}
              AND i.activity_id IS NULL
            ORDER BY a.start_time_local""",
        (version,),
    ).fetchall()


def upsert_run_intervals(conn: sqlite3.Connection, row: dict) -> None:
    """INSERT OR REPLACE keyed by activity_id — derived rows are disposable, so
    a recompute at a newer version simply replaces the stale row."""
    conn.execute(
        f"INSERT OR REPLACE INTO run_intervals "
        f"({', '.join(_RUN_INTERVALS_COLS)}, computed_at) "
        f"VALUES ({', '.join('?' * len(_RUN_INTERVALS_COLS))}, ?)",
        tuple(row.get(c) for c in _RUN_INTERVALS_COLS) + (_now(),),
    )
    conn.commit()


def interval_document(conn: sqlite3.Connection, activity_id) -> dict | None:
    row = conn.execute(
        "SELECT doc_json FROM run_intervals WHERE activity_id = ?",
        (activity_id,)).fetchone()
    return json.loads(row[0]) if row and row[0] else None


def intervals_coverage(conn: sqlite3.Connection, version: int) -> dict:
    """The intervals section --verify-archive reports: streamed runs vs runs
    holding a document at the current version, and the shape mix."""
    streamed = conn.execute(
        f"""SELECT COUNT(*) FROM activities a
            WHERE a.detail_streams_json IS NOT NULL AND {_RUN_TYPE_SQL}"""
    ).fetchone()[0]
    scored = conn.execute(
        "SELECT COUNT(*) FROM run_intervals WHERE lens_version = ?",
        (version,)).fetchone()[0]
    shapes = {r[0]: r[1] for r in conn.execute(
        "SELECT shape, COUNT(*) FROM run_intervals WHERE lens_version = ? "
        "GROUP BY shape", (version,))}
    lapped = conn.execute(
        "SELECT COUNT(*) FROM activities WHERE laps_json IS NOT NULL").fetchone()[0]
    return {"streamed_runs": streamed, "scored": scored,
            "shapes": shapes, "lapped": lapped}
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest test_activity_archive.py -q`
Expected: all pass, including the 5 new tests

- [ ] **Step 5: Commit**

```bash
git add activity_archive.py test_activity_archive.py
git commit -m "feat(archive): schema v11 — run_intervals + write-once laps_json

Additive as always: one derived table with disposable-cache semantics keyed
by INTERVAL_VERSION, plus the raw lap payload under detail_json's write-once
rule. Stale-version rows count as missing, so a bump self-heals."
```

---

### Task 9: Sync — lap acquisition and backfill

**Files:**
- Modify: `sync_garmin.py` — new fetcher beside `_fetch_raw_detail:355`, new pass beside `_streams_pass:1336`, `archive_step:1102`, the arg parser at `:1622`, `main:1640`
- Modify: `test_run_detail.py` (it already covers sync-side distillation helpers)

**Interfaces:**
- Consumes: `activity_archive.write_laps`, `runs_missing_laps` (Task 8)
- Produces: `_fetch_raw_laps(client, aid) -> list | None`, `_laps_pass(client, conn, limit) -> int`, `run_laps_backfill()` behind `--backfill-laps`.

- [ ] **Step 1: Write the failing test**

Append to `test_run_detail.py`. That file loads `sync_garmin` via importlib as `sg` and uses no pytest fixtures, so add an `arch` handle the same way at the top of the file:

```python
_aspec = importlib.util.spec_from_file_location(
    "activity_archive", REPO / "activity_archive.py")
arch = importlib.util.module_from_spec(_aspec)
_aspec.loader.exec_module(arch)
```

Then the test — `CACHE_DIR` is redirected by plain attribute assignment and restored in `finally`, matching the file's fixture-free style:

```python
def _run_summary(aid, lap_count, start):
    return {"activityId": aid, "startTimeLocal": start,
            "activityType": {"typeKey": "running"}, "activityName": f"run {aid}",
            "distance": 8000.0, "duration": 2400.0, "lapCount": lap_count}


def test_laps_pass_skips_single_lap_runs():
    """The 42 single-lap runs in the archive must never cost a request."""
    tmp = Path(tempfile.mkdtemp())
    conn = arch.open_archive(tmp)
    arch.upsert_activities(conn, [
        _run_summary(1, 1, "2026-07-10 06:00:00"),
        _run_summary(2, 13, "2026-07-11 06:00:00"),
    ])
    asked = []

    class FakeClient:
        def get_activity_splits(self, aid):
            asked.append(aid)
            return {"lapDTOs": [{"distance": 1000, "duration": 330}]}

    original = sg.CACHE_DIR
    sg.CACHE_DIR = tmp / "cache"
    try:
        sg._laps_pass(FakeClient(), conn, limit=None)
    finally:
        sg.CACHE_DIR = original
    assert asked == [2]
    assert arch.laps_payload(conn, 2)[0]["distance"] == 1000
    assert arch.laps_payload(conn, 1) is None
    conn.close()
```

`test_run_detail.py` will need `import tempfile` added to its imports.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest test_run_detail.py -q -k laps_pass`
Expected: FAIL — `AttributeError: module 'sync_garmin' has no attribute '_laps_pass'`

- [ ] **Step 3: Write the implementation**

Add a constant beside the other per-sync caps (near `DETAIL_TOPUP_PER_SYNC`):

```python
LAPS_PER_SYNC = 40           # bounded so a nightly sync stays polite to Garmin
```

Add beside `_fetch_raw_detail`:

```python
def _fetch_raw_laps(client, aid) -> list | None:
    """RAW lap DTOs for one activity, cache-first (`.garmin_cache/laps-<id>.json`).
    Garmin returns {'lapDTOs': [...]}; we bank the list itself — the envelope
    carries nothing the lens needs."""
    if not aid:
        return None
    CACHE_DIR.mkdir(exist_ok=True)
    cache = CACHE_DIR / f"laps-{aid}.json"
    doc = None
    if cache.exists():
        doc = safe(lambda: json.loads(cache.read_text(encoding="utf-8")),
                   None, f"laps-cache {aid}")
    if not doc:
        doc = safe(lambda: client.get_activity_splits(aid), None, f"laps {aid}")
        if doc:
            cache.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    if not doc:
        return None
    return doc.get("lapDTOs") if isinstance(doc, dict) else doc
```

Add beside `_streams_pass`:

```python
def _laps_pass(client, conn, limit: int | None = None) -> int:
    """Fetch lap DTOs for archived runs whose summary claims more than one lap
    and that we have never fetched (add-interval-lens D1). Bounded per nightly
    sync so the backlog drains over nights; `--backfill-laps` runs it unbounded.
    A single-lap run is skipped entirely — there is nothing to fetch."""
    done = 0
    for aid in activity_archive.runs_missing_laps(conn, limit=limit):
        laps = _fetch_raw_laps(client, aid)
        if laps and activity_archive.write_laps(conn, aid, laps):
            done += 1
    return done
```

Wire into `archive_step` after `_streams_pass`:

```python
        lapped = _laps_pass(client, conn, limit=LAPS_PER_SYNC)
```

…and extend the log line with `+ (f", {lapped} runs lapped" if lapped else "")`.

Add the backfill entry point beside `run_maps_backfill`:

```python
def run_laps_backfill(client) -> None:
    """Unbounded lap sweep — the one-time catch-up for an archive that predates
    schema v11. Idempotent: the per-activity cache makes a re-run free."""
    conn = activity_archive.open_archive(DATA_DIR)
    try:
        done = _laps_pass(client, conn, limit=None)
        log(f"✓ laps backfill: {done} runs lapped")
    finally:
        conn.close()
```

Argument + dispatch:

```python
    p.add_argument("--backfill-laps", action="store_true",
                   help="fetch lap DTOs for every multi-lap archived run "
                        "(one-time catch-up for a pre-v11 archive)")
```

```python
    if args.backfill_laps:
        run_laps_backfill(client)
        return
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest test_run_detail.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add sync_garmin.py test_run_detail.py
git commit -m "feat(sync): lap acquisition, cached and bounded

Only multi-lap runs cost a request, so the archive's single-lap runs are
free. Capped per nightly sync with --backfill-laps as the one-time sweep."
```

---

### Task 10: Sync — the intervals pass, wiring and verification

**Files:**
- Modify: `sync_garmin.py` — new step beside `block_lens_step:1175`, `main:1661`, `verify_archive` near `:1523`
- Modify: `test_run_detail.py`

**Interfaces:**
- Consumes: `interval_lens.build_document` (Task 7), `activity_archive.runs_missing_intervals` / `upsert_run_intervals` (Task 8)
- Produces: `intervals_step() -> None`, `derive_intervals(conn) -> dict` (returns `{"scored": int}`)

- [ ] **Step 1: Write the failing test**

```python
def _rep_streams():
    spans = [(600, 2.6)] + [(250, 4.0), (60, 2.2)] * 5 + [(300, 2.6)]
    t, d, v = [], [], []
    clock, dist = 0, 0.0
    for dur, mps in spans:
        for _ in range(dur):
            t.append(clock)
            d.append(round(dist))
            v.append(mps)
            clock += 1
            dist += mps
    return {"t": t, "d": d, "v": v}


def test_derive_intervals_scores_every_streamed_run():
    conn = arch.open_archive(Path(tempfile.mkdtemp()))
    arch.upsert_activities(conn, [_run_summary(5, 13, "2026-07-10 06:00:00")])
    arch.write_streams(conn, 5, _rep_streams())

    assert sg.derive_intervals(conn)["scored"] == 1
    doc = arch.interval_document(conn, 5)
    assert doc["shape"] == "reps" and doc["label"] == "5×1 km"
    # idempotent: a second pass finds nothing to do
    assert sg.derive_intervals(conn)["scored"] == 0
    conn.close()


def test_a_bad_stream_does_not_sink_the_rest():
    """One unparseable run must never stop the pass."""
    conn = arch.open_archive(Path(tempfile.mkdtemp()))
    arch.upsert_activities(conn, [
        _run_summary(6, 1, "2026-07-10 06:00:00"),
        _run_summary(7, 13, "2026-07-11 06:00:00"),
    ])
    arch.write_streams(conn, 6, {"t": "not-a-list", "d": None})
    arch.write_streams(conn, 7, _rep_streams())
    # the good run is still scored — the bad one is logged and skipped
    assert sg.derive_intervals(conn)["scored"] == 1
    assert arch.interval_document(conn, 7)["shape"] == "reps"
    assert arch.interval_document(conn, 6) is None
    conn.close()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest test_run_detail.py -q -k "derive_intervals or bad_stream"`
Expected: FAIL — `AttributeError: module 'sync_garmin' has no attribute 'derive_intervals'`

- [ ] **Step 3: Write the implementation**

Add `import interval_lens` beside the other engine imports (`:42–44`), then:

```python
def derive_intervals(conn) -> dict:
    """Score every archived run holding streams but no interval document at the
    current INTERVAL_VERSION (add-interval-lens D6). Stored payloads in, no
    network; a version bump self-heals the whole archive on the next sync.
    A per-run failure is deterministic, so it is logged and skipped rather than
    retried every night."""
    scored = 0
    for aid, start_local in activity_archive.runs_missing_intervals(
            conn, interval_lens.INTERVAL_VERSION):
        try:
            doc = interval_lens.build_document(
                activity_archive.streams_payload(conn, aid),
                activity_archive.summary_payload(conn, aid) or {},
                activity_archive.laps_payload(conn, aid))
        except Exception as e:  # noqa: BLE001 — one bad stream must not sink the rest
            warn(f"interval detection failed for {aid} ({type(e).__name__}: {e})")
            continue
        if not doc:
            continue
        activity_archive.upsert_run_intervals(conn, {
            "activity_id": aid,
            "lens_version": interval_lens.INTERVAL_VERSION,
            "start_time_local": start_local,
            "shape": doc["shape"], "label": doc.get("label"),
            "confidence": doc.get("confidence"), "source": doc["source"],
            "work_dist_m": (doc.get("quality") or {}).get("workDistM"),
            "work_dur_s": (doc.get("quality") or {}).get("workDurS"),
            "doc_json": json.dumps(doc, ensure_ascii=False),
        })
        scored += 1
    return {"scored": scored}


def intervals_step() -> None:
    """Derive the interval documents (add-interval-lens D6). Runs AFTER the
    archive step (it reads the streams that step wrote) and BEFORE build_data
    (the compact summary must land in garmin-data.js); only ever inside safe()
    — a detection problem is a warning, never a failed sync."""
    conn = activity_archive.open_archive(DATA_DIR)
    try:
        stats = derive_intervals(conn)
        log(f"✓ intervals: {stats['scored']} runs scored"
            if stats["scored"] else "✓ intervals: nothing new to score")
    finally:
        conn.close()
```

Wire into `main` between the archive and metrics steps:

```python
    safe(intervals_step, None, "intervals step")
```

Extend `verify_archive` beside the block-lens coverage block:

```python
        icov = activity_archive.intervals_coverage(conn, interval_lens.INTERVAL_VERSION)
        log(f"  intervals: {icov['scored']}/{icov['streamed_runs']} streamed runs "
            f"scored at v{interval_lens.INTERVAL_VERSION}, "
            f"{icov['lapped']} with laps; shapes {icov['shapes']}")
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest test_run_detail.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add sync_garmin.py test_run_detail.py
git commit -m "feat(sync): the intervals pass, fail-soft and self-healing

Scores every streamed run missing a document at the current version, so an
INTERVAL_VERSION bump repairs the archive on the next sync. One bad stream
is logged and skipped, never fatal."
```

---

### Task 11: The contract — compact summary and Max's pipeline

The cockpit renders from static files alone, so its label cannot come from the API.

**Files:**
- Modify: `sync_garmin.py` — `distill_run_detail:381`
- Modify: `ingest_builder.py` — `run_detail:225`, and the archive write path
- Modify: `test_ingest_builder.py`, `validate_data.py` (contract assertion)

**Interfaces:**
- Consumes: `interval_lens.build_document` (Task 7)
- Produces: each recent run's `detail.intervals` = `{shape, label, confidence, set, quality}` — the document **without** `segments`, which only `/run/:id` needs.

- [ ] **Step 1: Write the failing tests**

Append to `test_ingest_builder.py`:

```python
def _interval_run():
    """A Health Connect run with a real 4×1 km inside it."""
    spans = [(600, 2.6)] + [(250, 4.0), (60, 2.2)] * 4 + [(300, 2.6)]
    speed, hr, clock = [], [], 0
    for dur, mps in spans:
        for _ in range(dur):
            speed.append({"tSec": clock, "mps": mps})
            hr.append({"tSec": clock, "bpm": 150 if mps > 3 else 130})
            clock += 1
    total_m = sum(dur * mps for dur, mps in spans)
    return {"sessionUid": "iv", "startTimeLocal": "2026-07-15T07:00:00",
            "durationS": clock, "distanceM": total_m, "avgHr": 145,
            "sportType": "running", "avgSpeed": total_m / clock,
            "source": "shealth", "speedSamples": speed, "hrSamples": hr}


def test_max_gets_interval_structure():
    """One engine, both athletes — Samsung writes no laps, so this is stream-only."""
    detail = ingest_builder.run_detail(_interval_run(), max_hr=190)
    assert detail["intervals"]["shape"] == "reps"
    assert detail["intervals"]["label"] == "4×1 km"
    assert detail["intervals"]["set"]["found"] == 4


def test_compact_summary_omits_segments():
    """The cockpit reads this from a static file — segments belong to /run/:id."""
    detail = ingest_builder.run_detail(_interval_run(), max_hr=190)
    assert "segments" not in detail["intervals"]


def test_steady_run_reports_steady_not_missing():
    run = {"sessionUid": "s", "startTimeLocal": "2026-07-15T07:00:00",
           "durationS": 1800, "distanceM": 5400, "avgHr": 140,
           "sportType": "running", "avgSpeed": 3.0, "source": "shealth",
           "speedSamples": [{"tSec": t, "mps": 3.0} for t in range(1800)],
           "hrSamples": [{"tSec": t, "bpm": 140} for t in range(0, 1800, 5)]}
    assert ingest_builder.run_detail(run, max_hr=190)["intervals"]["shape"] == "steady"


def test_no_speed_series_means_no_intervals_key():
    run = {"sessionUid": "n", "startTimeLocal": "2026-07-15T07:00:00",
           "durationS": 1800, "distanceM": 5000, "avgHr": 140,
           "sportType": "running", "avgSpeed": 2.8, "source": "shealth",
           "speedSamples": [], "hrSamples": []}
    assert ingest_builder.run_detail(run, max_hr=190) is None


def test_both_pipelines_agree_on_the_same_run():
    """PARITY: one engine, two producers. Reshape the same physical run through
    each pipeline's input format and the documents must match — otherwise
    Felix's runs and Max's are being read by different rules, which is the one
    thing this design exists to prevent. Mirrors test_course_parity.mjs."""
    import interval_lens as il
    hc = _interval_run()
    garmin_streams = ingest_builder._columnar(hc)
    from_garmin = il.compact(il.build_document(garmin_streams))
    from_hc = ingest_builder.run_detail(hc, max_hr=190)["intervals"]
    assert from_garmin["shape"] == from_hc["shape"]
    assert from_garmin["label"] == from_hc["label"]
    assert from_garmin["set"]["found"] == from_hc["set"]["found"]
    assert from_garmin["quality"]["workDistM"] == from_hc["quality"]["workDistM"]
```

`test_ingest_builder.py` currently imports only `build_athlete_data`; add `import ingest_builder` for these.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest test_ingest_builder.py -q -k "interval or compact or steady"`
Expected: FAIL — `KeyError: 'intervals'`

- [ ] **Step 3: Write the implementation**

Add to `interval_lens.py` — the one shared reducer, so both producers cannot drift:

```python
def compact(doc: dict | None) -> dict | None:
    """The document MINUS its segments — what the cockpit and the recent-run
    drill-down need. It rides in garmin-data.js because the cockpit renders
    complete from static files with no API, and an interval label must not be
    the thing that breaks that promise. `/run/:id` fetches the full document."""
    if not doc:
        return None
    return {k: v for k, v in doc.items() if k != "segments"}
```

In `sync_garmin.distill_run_detail`, build the streams once and add the key:

```python
    streams = distill_run_streams(det)
    intervals = interval_lens.compact(
        interval_lens.build_document(streams, activity, None, bounds=bounds))
```

…and add `"intervals": intervals,` to the returned dict.

In `ingest_builder.run_detail`, mirror it exactly. Health Connect samples need reshaping to the columnar contract first — add beside the other derivations:

```python
def _columnar(run: dict) -> dict:
    """Health Connect samples → the SAME columnar shape the Garmin streams use,
    so interval_lens sees one input format from both pipelines (design: one
    engine, two producers). No laps: Samsung does not write ExerciseLap."""
    speeds = _sorted_samples(run, "speedSamples")
    if len(speeds) < 2:
        return {}
    hrs = _sorted_samples(run, "hrSamples")
    t = [s["tSec"] for s in speeds]
    v = [s["mps"] for s in speeds]
    cum, d = 0.0, []
    for i, s in enumerate(speeds):
        d.append(round(cum))
        if i + 1 < len(speeds):
            gap = min(speeds[i + 1]["tSec"] - s["tSec"], SAMPLE_GAP_CAP_S)
            cum += s["mps"] * max(0, gap)
    hr_by_t = {h["tSec"]: h["bpm"] for h in hrs}
    held, hr_col = None, []
    for ts in t:
        held = hr_by_t.get(ts, held)
        hr_col.append(held)
    return {"t": t, "d": d, "v": v, "hr": hr_col}
```

…then in `run_detail` add this beside `"splitShape"` — passing the athlete's own zone bounds so `quality.zone` is real rather than null:

```python
        "intervals": interval_lens.compact(interval_lens.build_document(
            _columnar(run), bounds=_zone_bounds(max_hr, rhr))),
```

**And collapse the duplicated zone formula.** `interval_lens.zone_bounds` is now the single definition, so `ingest_builder._zone_bounds` becomes a delegation and `ZONE_FRACTIONS` moves out of `ingest_builder`:

```python
def _zone_bounds(max_hr: int, rhr=None) -> list[int]:
    # Karvonen HR-reserve bounds when resting HR is known (design D12 — the
    # honest model for a beginner); plain %max otherwise. The formula lives in
    # interval_lens so BOTH pipelines score zones by one rule; this stays as the
    # name the rest of this module already calls.
    return interval_lens.zone_bounds(max_hr, rhr)
```

Delete `ingest_builder.ZONE_FRACTIONS` and update its remaining references (`_zone_bounds` at `:99`, and the `bounds` use at `:334`) — `_zone_of` and `_zone_seconds` keep taking the bounds list and are unchanged. Existing zone assertions in `test_ingest_builder.py` must still pass untouched: the numbers do not change, only where they are computed.

For the Garmin side, `distill_run_detail` passes bounds derived from the athlete's configured max HR:

```python
    bounds = interval_lens.zone_bounds(int(os.getenv("ATHLETE_MAX_HR", "197")))
```

Finally, extend `validate_data.py`'s §3 assertions so a recent run's `detail`, when it carries `intervals`, has a `shape` in the four-value vocabulary — the contract check the other keys already get.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest test_ingest_builder.py test_interval_lens.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add interval_lens.py sync_garmin.py ingest_builder.py test_ingest_builder.py validate_data.py
git commit -m "feat(contract): interval summary in both pipelines' recent-run detail

One shared compact() so the two producers cannot drift, and Health Connect
samples reshaped to the same columnar input the Garmin streams use — one
engine really does serve both athletes. Segments stay out of the static
file; only /run/:id needs them."
```

---

### Task 12: Archive API

**Files:**
- Modify: `serve.mjs` — `ARCHIVE_SUMMARY_COLS:258`, `archiveSummaryRow:261`, `listArchiveActivities:275`, `getArchiveActivity:406`
- Modify: `test_archive_api.mjs`

**Interfaces:**
- Produces: `GET /api/archive/activities/:id` gains `intervals` (full document, omitted when absent); list rows gain `intervalShape` and `intervalLabel`.

- [ ] **Step 1: Write the failing test**

First extend the file's fixture archive. `makeArchive` builds the tables by hand, so it needs the new table and two known ids — `REP_RUN_ID` is a run with a document, `PLAIN_RUN_ID` is one without (reuse an existing fixture activity for the latter rather than adding one):

```js
const REP_RUN_ID = 9001;
const PLAIN_RUN_ID = 9002;   // an activity row with NO run_intervals row

db.exec(`CREATE TABLE run_intervals (
  activity_id INTEGER PRIMARY KEY, lens_version INTEGER NOT NULL,
  start_time_local TEXT NOT NULL, shape TEXT NOT NULL, label TEXT,
  confidence REAL, source TEXT NOT NULL, work_dist_m REAL, work_dur_s REAL,
  doc_json TEXT NOT NULL, computed_at TEXT NOT NULL)`);
db.prepare(`INSERT INTO run_intervals VALUES (?,?,?,?,?,?,?,?,?,?,?)`).run(
  REP_RUN_ID, 1, "2026-07-10 06:51:15", "reps", "5×1 km", 0.86, "stream",
  5000, 1250, JSON.stringify({
    version: 1, shape: "reps", source: "stream", confidence: 0.86,
    label: "5×1 km", guidedBy: null,
    segments: [{ idx: 1, role: "warmup", t0: 0, t1: 600, d0: 0, d1: 1560,
                 durS: 600, distM: 1560, paceS: 385, gapS: null, hr: 132, cad: null }],
    set: { found: 5, prescribed: null, nominalDistM: 1000, varied: false,
           paceS: 334, paceCvPct: 1.8, fadePct: 2.4, recoveryS: 60,
           recoveryHrDrop: 24, reps: [] },
    quality: { workDistM: 5000, workDurS: 1250, zone: "Z4" },
  }), "2026-07-27T09:00:00");
```

Then the assertions:

```js
// add-interval-lens: the document is served VERBATIM and the list carries
// enough to label a page of rows without N fetches
{
  const r = await get(`/api/archive/activities/${REP_RUN_ID}`);
  assert.equal(r.status, 200);
  assert.equal(r.body.intervals.shape, "reps");
  assert.equal(r.body.intervals.label, "5×1 km");
  assert.ok(Array.isArray(r.body.intervals.segments), "segments survive the API");
}
{
  const r = await get("/api/archive/activities?limit=5");
  const row = r.body.activities.find((a) => a.activityId === REP_RUN_ID);
  assert.equal(row.intervalShape, "reps");
  assert.equal(row.intervalLabel, "5×1 km");
}
{
  // a run with no document: the field is OMITTED, not null — same rule as map
  const r = await get(`/api/archive/activities/${PLAIN_RUN_ID}`);
  assert.equal("intervals" in r.body, false);
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `node test_archive_api.mjs`
Expected: FAIL — `Cannot read properties of undefined (reading 'shape')`

- [ ] **Step 3: Write the implementation**

The list query joins the promoted columns only:

```js
// add-interval-lens: shape + label ride on the list so /archive can chip a
// page of rows without N document fetches. LEFT JOIN — a run with no document
// is a run with no structure detected yet, not a missing row.
const ARCHIVE_LIST_SQL = `SELECT ${ARCHIVE_SUMMARY_COLS},
  i.shape AS interval_shape, i.label AS interval_label
  FROM activities a LEFT JOIN run_intervals i ON i.activity_id = a.activity_id`;
```

`archiveSummaryRow` gains, guarded so the pre-v11 path still works:

```js
    ...(r.interval_shape ? { intervalShape: r.interval_shape } : {}),
    ...(r.interval_label ? { intervalLabel: r.interval_label } : {}),
```

`getArchiveActivity` gains the document, in the same guarded style as `map`:

```js
  // the run's interval document (add-interval-lens): stored TEXT parsed once
  // and returned as the object it is. A pre-v11 archive has no table — that
  // means no structure, not an outage. OMITTED (not null) when absent.
  let intervals;
  try {
    const iv = db.prepare(
      "SELECT doc_json FROM run_intervals WHERE activity_id = ?").get(id);
    if (iv && iv.doc_json) intervals = JSON.parse(iv.doc_json);
  } catch { /* no run_intervals table in this archive */ }
```

…and `...(intervals ? { intervals } : {}),` in the returned object.

Note: `ARCHIVE_SUMMARY_COLS` must be qualified with `a.` for the join. Update the constant to `a.activity_id, a.start_time_local, …` and the plain `FROM activities` count query accordingly.

- [ ] **Step 4: Run to verify it passes**

Run: `node test_archive_api.mjs`
Expected: PASS, all assertions

- [ ] **Step 5: Commit**

```bash
git add serve.mjs test_archive_api.mjs
git commit -m "feat(api): serve the interval document and list-row shape chips

Verbatim as always — the API stays a window, not an engine. A pre-v11
archive means no structure, not an outage."
```

---

### Task 13: The rep table on /run/:id

**Files:**
- Modify: `run.dc.html` — markup after the splits card at `:185–203`, builder beside `pg.splits` at `:469–489`
- Modify: `test_run_page.mjs`

**Interfaces:**
- Consumes: `run.intervals` from `/api/archive/activities/:id` (Task 12)
- Produces: `pg.reps` — `[{ label, sub, rows: [{ n, dist, time, pace, gap, hr, rec, left, width, color }] }]`

- [ ] **Step 1: Write the failing test**

`test_run_page.mjs` builds its own fixture archive in `makeArchive`. Add the same `run_intervals` table and a five-rep document for `REP_RUN_ID` as in Task 12 — this time with all five `work` segments and the four `recovery` segments between them populated, since the page renders them:

```js
const REP_SEGMENTS = [];
let t = 600, d = 1560, rep = 0;
REP_SEGMENTS.push({ idx: 1, role: "warmup", t0: 0, t1: 600, d0: 0, d1: 1560,
                    durS: 600, distM: 1560, paceS: 385, gapS: null, hr: 132, cad: null });
for (let i = 0; i < 5; i++) {
  rep += 1;
  REP_SEGMENTS.push({ idx: REP_SEGMENTS.length + 1, role: "work", rep,
    t0: t, t1: t + 250, d0: d, d1: d + 1000, durS: 250, distM: 1000,
    paceS: 330 + i * 3, gapS: null, hr: 168 + i, cad: null });
  t += 250; d += 1000;
  if (i < 4) {
    REP_SEGMENTS.push({ idx: REP_SEGMENTS.length + 1, role: "recovery",
      t0: t, t1: t + 60, d0: d, d1: d + 140, durS: 60, distM: 140,
      paceS: 430, gapS: null, hr: 144, cad: null });
    t += 60; d += 140;
  }
}
```

Then the assertions:

```js
// add-interval-lens: reps render as reps, measured against the SET's median
await page.goto(`${B}/run/${REP_RUN_ID}`);
await page.waitForSelector(".rep-table");
assert.equal(await page.locator(".rep-row").count(), 5, "five reps render");
assert.match(await page.locator(".rep-title").innerText(), /5×1 km/);
assert.match(await page.locator(".rep-row").first().innerText(), /5:3\d/);
// the recovery between reps is shown, and there is one fewer of them
assert.equal(await page.locator(".rep-rec").count(), 4);
// a steady run shows no rep table at all — and the km splits still do
await page.goto(`${B}/run/${PLAIN_RUN_ID}`);
await page.waitForSelector(".card");
assert.equal(await page.locator(".rep-table").count(), 0);
assert.ok(await page.locator("text=Splits").count() > 0);
```

- [ ] **Step 2: Run to verify it fails**

Run: `node test_run_page.mjs`
Expected: FAIL — timeout waiting for `.rep-table`

- [ ] **Step 3: Write the implementation**

Markup, inserted **before** the existing splits `<sc-for>` so reps lead and km splits follow:

```html
    <sc-for list="{{ pg.reps }}" as="rp" hint-placeholder-count="0">
      <div class="card rep-table">
        <div class="card-title rep-title" style="margin-bottom:var(--sp-1)">{{ rp.label }}</div>
        <div class="card-sub" style="margin-bottom:var(--sp-3)">{{ rp.sub }}</div>
        <div style="display:flex;flex-direction:column;gap:var(--sp-1)">
          <sc-for list="{{ rp.rows }}" as="r" hint-placeholder-count="5">
            <div>
              <div class="rep-row" style="display:flex;align-items:center;gap:var(--sp-3);font-size:var(--fs-sm)">
                <span style="width:34px;color:var(--sub);font-weight:700;font-size:var(--fs-xs)">{{ r.n }}</span>
                <span style="width:56px;font-family:'JetBrains Mono';font-size:var(--fs-xs);color:var(--sub)">{{ r.dist }}</span>
                <div style="flex:1;position:relative;height:16px">
                  <div style="position:absolute;left:50%;top:-2px;bottom:-2px;width:1px;background:var(--line)"></div>
                  <div style="position:absolute;top:2px;height:12px;border-radius:2px;left:{{ r.left }}%;width:{{ r.width }}%;background:{{ r.color }}"></div>
                </div>
                <span style="width:52px;text-align:right;font-family:'JetBrains Mono';font-weight:600">{{ r.pace }}</span>
                <span style="width:44px;text-align:right;font-family:'JetBrains Mono';color:var(--sub)">{{ r.hr }}</span>
              </div>
              <sc-for list="{{ r.rec }}" as="rc" hint-placeholder-count="0">
                <div class="rep-rec" style="display:flex;gap:var(--sp-2);padding:2px 0 6px 34px;font-size:var(--fs-2xs);color:var(--sub)">
                  <span>↓ {{ rc.time }} recovery</span>
                  <span>{{ rc.drop }}</span>
                </div>
              </sc-for>
            </div>
          </sc-for>
        </div>
      </div>
    </sc-for>
```

Builder, beside `pg.splits`:

```js
      // reps against the SET's own median (add-interval-lens) — the run median
      // is meaningless when half the run is warmup and cooldown
      pg.reps = [];
      const iv = run.intervals;
      if (iv && iv.shape !== 'steady' && iv.segments && iv.segments.length) {
        const work = iv.segments.filter((s) => s.role === 'work');
        const recs = iv.segments.filter((s) => s.role === 'recovery');
        if (work.length) {
          const paces = work.map((s) => s.paceS).filter((p) => p).sort((a, b) => a - b);
          const median = paces.length ? paces[Math.floor(paces.length / 2)] : 0;
          const maxDev = Math.max(5, ...work.map((s) => Math.abs((s.paceS || median) - median)));
          const set = iv.set || {};
          const bits = [];
          if (set.paceCvPct != null) bits.push(set.paceCvPct.toFixed(1) + '% spread');
          if (set.fadePct != null) bits.push((set.fadePct > 0 ? '+' : '') + set.fadePct.toFixed(1) + '% fade');
          if (set.recoveryHrDrop != null) bits.push('−' + set.recoveryHrDrop + ' bpm recovery');
          if (iv.confidence != null && iv.confidence < 0.5) bits.push('possible structure');
          if (set.prescribed != null && set.found !== set.prescribed) {
            bits.unshift(set.found + ' of ' + set.prescribed + ' reps');
          }
          pg.reps = [{
            label: iv.label || 'Reps',
            sub: bits.length ? bits.join(' · ') : "Bars against this set's own median rep",
            rows: work.map((s, i) => {
              const dev = (s.paceS || median) - median;
              const half = Math.min(50, Math.abs(dev) / maxDev * 50);
              const rc = recs[i];
              return {
                n: 'rep ' + (s.rep || i + 1),
                dist: s.distM >= 1000 ? (s.distM / 1000).toFixed(2) + ' km' : s.distM + ' m',
                time: this.fmtHms ? this.fmtHms(s.durS) : s.durS + 's',
                pace: this.fmtPace(s.paceS),
                gap: s.gapS ? this.fmtPace(s.gapS) : '—',
                hr: s.hr != null ? s.hr : '—',
                left: dev < 0 ? +(50 - half).toFixed(1) : 50,
                width: +half.toFixed(1) || 0.5,
                color: dev <= 0 ? 'var(--series1)' : 'var(--sub)',
                rec: rc ? [{
                  time: Math.round(rc.durS) + ' s',
                  drop: rc.hr != null && s.hr != null ? '−' + (s.hr - rc.hr) + ' bpm' : '',
                }] : [],
              };
            }),
          }];
        }
      }
```

Also update the existing splits card's `card-sub` to read `Per-kilometre averages — blunt through a rep set, honest on a steady run` so the two cards explain themselves.

- [ ] **Step 4: Run to verify it passes**

Run: `node test_run_page.mjs`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add run.dc.html test_run_page.mjs
git commit -m "feat(run-page): the rep table

Reps measured against the set's own median, recoveries shown between them,
low confidence rendered as 'possible structure' rather than asserted. The
km splits card stays below — blunt, not wrong."
```

---

### Task 14: Rep shading on the stream tracks

The spec's other half of the run-page promise: the crosshair should tell you which rep you are in. The chart engine already has an annotation-lane concept; this adds shaded bands behind the tracks.

**Files:**
- Modify: `chart-core.js` — the descriptor → `ChartSpec` path, alongside the existing band handling
- Modify: `chart-view.js` — render the bands beneath the marks
- Modify: `run.dc.html` — pass rep windows into the stream descriptors
- Modify: `test_chart_core.mjs`, `test_chart_view.mjs`, `test_run_page.mjs`

**Interfaces:**
- Consumes: `run.intervals.segments` (Task 12)
- Produces: descriptors accept `repBands: [{ x0, x1, rep }]` in the SAME x-units as the track's domain (seconds when the axis is time, metres when it is distance); `ChartSpec` gains `repBands: [{ x, width, rep }]` in px.

- [ ] **Step 1: Write the failing tests**

In `test_chart_core.mjs`:

```js
// add-interval-lens: rep windows become px bands in the spec, and are clipped
// to the plot area so a rep that starts before the visible domain still reads
{
  const spec = buildSpec({
    ...baseDescriptor,
    xDomain: [0, 1000],
    repBands: [{ x0: 100, x1: 300, rep: 1 }, { x0: 400, x1: 600, rep: 2 }],
  });
  assert.equal(spec.repBands.length, 2);
  assert.ok(spec.repBands[0].width > 0, "a band has width");
  assert.ok(spec.repBands[0].x < spec.repBands[1].x, "bands keep their order");
  assert.equal(spec.repBands[0].rep, 1);
}
{
  // no rep windows → no bands, and nothing else about the spec changes
  const spec = buildSpec({ ...baseDescriptor, xDomain: [0, 1000] });
  assert.deepEqual(spec.repBands, []);
}
{
  // a band running past the domain is clipped, never drawn outside the plot
  const spec = buildSpec({
    ...baseDescriptor, xDomain: [0, 1000],
    repBands: [{ x0: 900, x1: 5000, rep: 1 }],
  });
  assert.ok(spec.repBands[0].x + spec.repBands[0].width <= spec.plot.x + spec.plot.width + 0.01);
}
```

In `test_chart_view.mjs`:

```js
// bands render BENEATH the marks — a rep highlight must never hide the line
{
  const el = renderChart({ ...specWithBands }, StubReact);
  const svg = findByTag(el, "svg");
  const bandIdx = svg.children.findIndex((c) => c.props.className === "rep-band");
  const lineIdx = svg.children.findIndex((c) => c.props.className === "series-line");
  assert.ok(bandIdx >= 0, "bands render");
  assert.ok(bandIdx < lineIdx, "bands come before the line in paint order");
}
```

In `test_run_page.mjs`:

```js
// the tracks carry the rep shading, and the crosshair names the rep
await page.goto(`${B}/run/${REP_RUN_ID}`);
await page.waitForSelector(".rep-band");
assert.equal(await page.locator(".rep-band").count() >= 5, true, "one band per rep");
```

- [ ] **Step 2: Run to verify they fail**

Run: `node test_chart_core.mjs`
Expected: FAIL — `spec.repBands` is undefined

- [ ] **Step 3: Write the implementation**

In `chart-core.js`, beside the existing band logic, add to the spec builder:

```js
  // add-interval-lens: rep windows → px bands. The descriptor supplies them in
  // the track's own x-units (seconds on a time axis, metres on a distance one)
  // so the caller never has to know the scale; clipping to the plot is done
  // here, once, rather than by every renderer.
  const repBands = (descriptor.repBands || []).map((b) => {
    const x0 = Math.max(xScale(b.x0), plot.x);
    const x1 = Math.min(xScale(b.x1), plot.x + plot.width);
    return { x: x0, width: Math.max(0, x1 - x0), rep: b.rep };
  }).filter((b) => b.width > 0);
```

…and include `repBands` in the returned `ChartSpec`.

In `chart-view.js`, emit them as the **first** SVG children so every mark paints over them:

```js
    ...spec.repBands.map((b, i) => h("rect", {
      key: "repband-" + i, className: "rep-band",
      x: b.x, y: spec.plot.y, width: b.width, height: spec.plot.height,
      fill: "var(--accentFade)", "aria-hidden": "true",
    })),
```

In `run.dc.html`, derive the windows once and pass them to each stream descriptor, in whichever unit the current axis uses:

```js
      // rep windows for the track shading, in the axis's own units — the
      // distance⇄time toggle already swaps the domain, so this must follow it
      const repWindows = (iv && iv.segments || [])
        .filter((s) => s.role === 'work')
        .map((s) => (pg.axis === 'distance'
          ? { x0: s.d0, x1: s.d1, rep: s.rep }
          : { x0: s.t0, x1: s.t1, rep: s.rep }));
```

…then `repBands: repWindows,` on each stream descriptor.

- [ ] **Step 4: Run to verify they pass**

Run: `node test_chart_core.mjs && node test_chart_view.mjs && node test_run_page.mjs`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add chart-core.js chart-view.js run.dc.html test_chart_core.mjs test_chart_view.mjs test_run_page.mjs
git commit -m "feat(chart): rep bands behind the stream tracks

Windows arrive in the track's own x-units and are clipped to the plot once,
in the core. Bands paint first so a rep highlight never hides its line."
```

---

### Task 15: Session labels on the cockpit and the archive

**Files:**
- Modify: `coach-read.js`, `test_coach_read.mjs`
- Modify: `archive.dc.html`, `test_archive_page.mjs`

**Interfaces:**
- Consumes: `detail.intervals` (Task 11) on the cockpit; `intervalShape` / `intervalLabel` list fields (Task 12) on `/archive`

- [ ] **Step 1: Write the failing tests**

In `test_coach_read.mjs`:

```js
// add-interval-lens: the read names the session instead of guessing from thirds
{
  const read = coachRead({
    date: "2026-07-10", type: "Tempo Run", km: 9.1, pace: 345, hr: 158,
    detail: {
      splits: [], splitShape: "even",
      intervals: { shape: "reps", label: "5×1 km", confidence: 0.9,
                   set: { found: 5, prescribed: null, paceS: 334, fadePct: 2.4 } },
    },
  }, null, 197);
  assert.match(read, /5×1 km/);
  assert.match(read, /5:34/);
}
{
  // a steady run keeps the old shape language — nothing regresses
  const read = coachRead({
    date: "2026-07-11", type: "Recovery", km: 6, pace: 400, hr: 132,
    detail: { splits: [], splitShape: "even", intervals: { shape: "steady" } },
  }, null, 197);
  assert.doesNotMatch(read, /×/);
}
```

In `test_archive_page.mjs`:

```js
// shape chips let you find your interval sessions by eye
await page.goto(`${B}/archive`);
await page.waitForSelector(".arch-row");
assert.ok(await page.locator(".arch-shape").count() > 0, "shape chips render");
assert.match(await page.locator(".arch-shape").first().innerText(), /×|block|progression/);
```

- [ ] **Step 2: Run to verify they fail**

Run: `node test_coach_read.mjs` then `node test_archive_page.mjs`
Expected: FAIL — the read has no `5×1 km`; no `.arch-shape` element

- [ ] **Step 3: Write the implementation**

In `coach-read.js`, ahead of the existing `splitShape` branch:

```js
  // add-interval-lens: when the run had real structure, name it. splitShape's
  // first-third-vs-last-third guess is meaningless on a rep session — warmup
  // and cooldown cancel out and every interval workout reads "even".
  const iv = run.detail && run.detail.intervals;
  if (iv && iv.shape === 'reps' && iv.set) {
    const parts = [iv.label || (iv.set.found + ' reps')];
    if (iv.set.paceS) parts.push('@ ' + fmtPace(iv.set.paceS));
    if (iv.set.prescribed != null && iv.set.found !== iv.set.prescribed) {
      parts.push('(' + iv.set.found + ' of ' + iv.set.prescribed + ')');
    } else if (iv.set.fadePct != null && Math.abs(iv.set.fadePct) >= 3) {
      parts.push(iv.set.fadePct > 0 ? 'fading ' + iv.set.fadePct.toFixed(1) + '%'
                                    : 'negative ' + Math.abs(iv.set.fadePct).toFixed(1) + '%');
    }
    return parts.join(' ') + '.';
  }
  if (iv && iv.shape === 'block' && iv.label) {
    return 'Sustained ' + iv.label + '.';
  }
```

In `archive.dc.html`, add the chip to the row markup beside the existing type badge:

```html
              <sc-for list="{{ r.shape }}" as="sh" hint-placeholder-count="0">
                <span class="arch-shape" style="font-size:var(--fs-2xs);font-weight:800;letter-spacing:.04em;padding:2px 7px;border-radius:var(--r-pill);background:var(--accentFade);color:var(--accent)">{{ sh.t }}</span>
              </sc-for>
```

…and in its row builder:

```js
        shape: a.intervalLabel ? [{ t: a.intervalLabel }]
             : (a.intervalShape && a.intervalShape !== 'steady'
                ? [{ t: a.intervalShape }] : []),
```

- [ ] **Step 4: Run to verify they pass**

Run: `node test_coach_read.mjs && node test_archive_page.mjs`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add coach-read.js test_coach_read.mjs archive.dc.html test_archive_page.mjs
git commit -m "feat(cockpit,archive): name the session instead of guessing from thirds

splitShape reads 'even' for every interval workout because warmup and
cooldown cancel out. When real structure exists, the read names it."
```

---

### Task 16: Ground truth, full suite, and the README

The archive is a free labelled test set: runs named `2km wu, 5x1km @ 5:40, 1km cd` state their own truth.

**Files:**
- Create: `test_interval_truth.py`
- Modify: `README.md`

- [ ] **Step 1: Write the ground-truth test**

```python
#!/usr/bin/env python3
"""Ground truth for the interval lens, read off the athlete's own run names.

Runs named '2km wu, 5x1km @ 5:40, 1km cd' or 'pYRAMIDE: 1-2-1K Tempo' state
what they were. Synthetic streams prove the arithmetic; only these prove the
detector survives real GPS noise, real hills and a real watch.

Skipped when no archive is present (CI, a fresh clone) — never a hard failure.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest

import interval_lens as il

DB = Path(__file__).parent / "activity-archive.db"
pytestmark = pytest.mark.skipif(not DB.exists(), reason="no local archive")

# '5x1km', '5 x 1 km', '6×800m' → (count, metres)
NAME_RE = re.compile(r"(\d+)\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*(km|k|m)\b", re.I)


def self_describing():
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT activity_id, name, summary_json, detail_streams_json, laps_json "
        "FROM activities WHERE detail_streams_json IS NOT NULL "
        "AND type_key LIKE '%run%'").fetchall()
    out = []
    for aid, name, summary, streams, laps in rows:
        m = NAME_RE.search(name or "")
        if not m:
            continue
        count = int(m.group(1))
        val = float(m.group(2).replace(",", "."))
        metres = val * 1000 if m.group(3).lower() in ("km", "k") else val
        out.append((aid, name, count, metres, json.loads(streams),
                    json.loads(summary), json.loads(laps) if laps else None))
    return out


def test_the_archive_has_self_describing_runs():
    assert len(self_describing()) >= 1, "no named interval sessions to check"


@pytest.mark.parametrize("case", self_describing(), ids=lambda c: str(c[0]))
def test_named_sessions_are_detected_as_reps(case):
    aid, name, count, metres, streams, summary, laps = case
    doc = il.build_document(streams, summary, laps)
    assert doc is not None, f"{aid} {name}: no document"
    assert doc["shape"] == "reps", f"{aid} {name}: read as {doc['shape']}"
    found = doc["set"]["found"]
    assert abs(found - count) <= 1, f"{aid} {name}: found {found}, name says {count}"


@pytest.mark.parametrize("case", self_describing(), ids=lambda c: str(c[0]))
def test_named_rep_length_is_recovered(case):
    aid, name, count, metres, streams, summary, laps = case
    doc = il.build_document(streams, summary, laps)
    reps = (doc.get("set") or {}).get("reps") or []
    if not reps:
        pytest.skip("no reps to measure")
    median = sorted(r["distM"] for r in reps)[len(reps) // 2]
    assert abs(median - metres) / metres <= 0.25, \
        f"{aid} {name}: median rep {median} m, name says {metres} m"
```

- [ ] **Step 2: Run it — this is the real acceptance gate**

Run: `.venv/Scripts/python.exe -m pytest test_interval_truth.py -q`
Expected: the named sessions in the archive detect as `reps` with the right count and rep length. **If a case fails, that is a genuine detector finding — tune the constants in `interval_lens.py` and re-run, do not weaken the assertion.** Record any run that legitimately cannot be detected (e.g. no speed stream) as a skip with its reason.

- [ ] **Step 3: Run the whole suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Then: `node test_chart_core.mjs && node test_chart_view.mjs && node test_archive_api.mjs && node test_run_page.mjs && node test_coach_read.mjs && node test_archive_page.mjs && node test_offline.mjs && node test_slim_render.mjs`
Expected: everything green. Two of these earn their place specifically here: `test_offline.mjs` (the rep table must not introduce a network dependency — the pages still render with every non-same-origin request aborted) and `test_slim_render.mjs` (Max's instance has no `run_intervals` rows until his first ingest build, and the pages must not care).

- [ ] **Step 4: Document it**

Add to the README's file table:

```markdown
| `interval_lens.py` | **The interval lens.** What structure did this run have — reps, a sustained block, a progression, or nothing? Pure over its inputs: columnar streams in (plus Garmin lap DTOs when they encode real structure), one versioned document out. One engine, two producers — `sync_garmin.py` and `ingest_builder.py` both call `build_document()`, so Felix's runs and Max's are read by the same rules. Tested in `test_interval_lens.py`, and against the athlete's own self-describing run names in `test_interval_truth.py`. |
```

And a short section after the chart-engine section explaining the auto-lap veto and the `found`/`prescribed` honesty rule, since both are surprising and load-bearing.

- [ ] **Step 5: Commit**

```bash
git add test_interval_truth.py README.md
git commit -m "test(interval-lens): ground truth from the athlete's own run names

Synthetic streams prove the arithmetic; a run named '5x1km' proves the
detector survives real GPS noise and real hills. Skipped when no archive is
present, so a fresh clone stays green."
```

---

## Deployment note

After the suite is green, the NUC needs a one-time `sync_garmin.py --backfill-laps`
(~120 Garmin requests) followed by a normal sync, which scores every streamed run through
the new pass. Verify with `sync_garmin.py --verify-archive` — the intervals line should
report near-complete coverage and a shape mix dominated by `steady`, with `reps` on the
sessions you know were interval sessions. Max's instance needs only a normal ingest build;
his documents come from the same engine with no laps and no backfill.
