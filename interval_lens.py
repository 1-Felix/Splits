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

from collections import Counter
from collections.abc import Callable

INTERVAL_VERSION = 5   # 2: paceS is raw pace and gapS is real (final review I4);
                       #    ragged pyramid labels collapse to "N reps" (I6)
                       # 3: the laps path applies the same WORK_MIN_S/WORK_MIN_M
                       #    rep floor the stream path always has, and shares its
                       #    labelling logic — a trailing partial lap no longer
                       #    reads as a rep, and a varied lap-sourced set no
                       #    longer loses its label (production defect, 2026-07-27)
                       # 4: the workout STEP decides what is a rep — one-off
                       #    ACTIVE laps demoted, lap blocks meet BLOCK_MIN_*,
                       #    GAP from the device, spread/fade on the raw grid.
                       # 5: fix-lap-confidence — lap confidence is derived
                       #    (corroborated/structured/eliminated), a shape that
                       #    survives only by material size discard is hedged,
                       #    and every document carries the `asserts` verdict.

# ── algorithm parameters — all covered by INTERVAL_VERSION ───────────────────
SMOOTH_WINDOW_S = 15       # rolling median: kills GPS chatter, keeps a 30 s edge
MOVING_MPS_MIN = 0.5       # below this the athlete is stopped, not recovering
MIN_SPAN_S = 60            # shorter than this and there is nothing to segment
SEPARATION_MIN = 0.12      # work must be >=12 % faster than rest to be structure
MIN_MOVING_SAMPLES = 60    # fewer than a minute of moving data decides nothing
ENTER_FRAC = 0.65          # hysteresis: enter work at lo + .65·(hi−lo)
EXIT_FRAC = 0.45           # leave work at lo + .45·(hi−lo)
WORK_MIN_S = 30
WORK_MIN_M = 150
RECOVERY_MIN_S = 20
REPS_MIN_COUNT = 3            # 2 when a prior expects a set (design D3)
BLOCK_MIN_S = 300
BLOCK_MIN_M = 1500
VARIED_TOLERANCE = 0.20       # rep distances differing by >20 % → varied
VARIED_MAX_ENUMERATE = 5      # more unequal reps than this and the list is noise
PROGRESSION_MIN_GAIN = 0.05   # last quintile >=5 % faster than the first
ROUND_DIST_TOLERANCE = 0.12   # relative error within which a rep snaps to a named distance
AUTOLAP_TOLERANCE = 0.05      # laps all within ±5 % of 1 km / 1 mile = auto-lap
AUTOLAP_UNITS = (1000.0, 1609.34)
CONFIDENCE_ASSERT_MIN = 0.5   # below this the document does not assert its
                              # shape. THE single place the comparison happens
                              # (_verdict): the document carries the boolean
                              # and run.dc.html renders it — the page performs
                              # no threshold arithmetic of its own (handoff M2)

# The lap path's confidence levels (fix-lap-confidence D3). No continuous
# evidence exists to interpolate over — the device did not classify by pace —
# so a fabricated score would be false precision. Three named levels instead:
# corroborated (reps share a repeated workout step, no material discard),
# structured (step evidence via the no-repeat fallback, or a device block, no
# material discard) and eliminated (the shape depends on a material size
# discard). Corroborated and structured deliberately share a value: nothing
# observable turns on the distinction until add-workout-prior can corroborate
# against a prescription, and that change decides it (design open question 1).
# Eliminated sits below CONFIDENCE_ASSERT_MIN by construction; its exact
# value is cosmetic — the page renders the verdict, never the number.
_LAP_CONFIDENCE = {"corroborated": 1.0, "structured": 1.0, "eliminated": 0.4}
# Zone boundary fractions — the values ingest_builder has always used, moved
# here as THE definition (Task 11 rewrites ingest_builder._zone_bounds to
# delegate here), so the two producers cannot drift on what "Z4" means. Six
# entries: _zone_of reads bounds[1:5] as the 60/70/80/90 % cut points and the
# trailing 1.00 closes the top.
ZONE_FRACTIONS = (0.50, 0.60, 0.70, 0.80, 0.90, 1.00)

# Cross-run calibration (Task 7b). "Work" is not "faster than the rest of this
# run" — 2-means always yields a fast half, so that definition turns every easy
# run into a workout (measured: 62 % of a real archive). It is "genuinely fast
# FOR THIS ATHLETE", measured against their own history.
WORK_FLOOR_PCT = 0.93         # validated against a real 165-run archive; p90
                              # kept a warm-up fragment, p97 lost real workouts
BASELINE_STRIDE = 5           # 1-in-5 sampling — 100k+ points is ample
WORK_FLOOR_MIN_SAMPLES = 20_000   # ~30 runs; below this the percentile is noise

# Garmin intensityType → our role vocabulary. Anything unrecognised is work:
# an unlabelled lap inside a structured workout is far more likely a rep than
# a rest, and calling it a rest would silently shrink the set.
_LAP_ROLES = {
    "WARMUP": "warmup", "COOLDOWN": "cooldown",
    "REST": "recovery", "RECOVERY": "recovery",
    "ACTIVE": "work", "INTERVAL": "work",
}


def speed_series(streams: dict) -> list[float | None]:
    """The DETECTION signal: a 1 Hz speed grid over the run's elapsed span,
    last-value-held across sample gaps. Grade-adjusted speed wins over raw
    speed when the payload carries it (design D5): on a hill, a rep up and a
    rep down are the same effort, and raw pace would split one set into a
    fade. Samples below MOVING_MPS_MIN become None — a pause is absent data,
    not a slow rep.

    This series decides WHERE the reps are; it is NOT what a rep's reported
    pace should come from. `raw_speed_series` and `gap_speed_series` below are
    the two REPORTING grids — see their docstrings."""
    return _series(streams, streams.get("gap") or streams.get("v") or [])


def raw_speed_series(streams: dict) -> list[float | None]:
    """What the watch actually recorded — the number that belongs in a
    segment's `paceS`. Falls back to `gap` only when a payload carries no raw
    speed at all, which is better than reporting nothing.

    Detection and reporting were the same grid until the final review: 161 of
    165 archived runs carry `gap`, so `paceS` held grade-adjusted pace under a
    raw-pace label while the column labelled GAP was empty on every row of
    every rep table. The two were effectively swapped."""
    return _series(streams, streams.get("v") or streams.get("gap") or [])


def gap_speed_series(streams: dict) -> list[float | None]:
    """Grade-adjusted speed ONLY — the number that belongs in a segment's
    `gapS`. Empty when the payload carries no `gap` (a treadmill, and 4 of the
    archive's 165 runs), and the consumers then report `gapS: None`: a run with
    no grade adjustment has no grade-adjusted pace, and echoing raw pace into
    the GAP column would claim an adjustment that was never made."""
    return _series(streams, streams.get("gap") or [])


def _series(streams: dict, src: list) -> list[float | None]:
    """The shared 1 Hz resampler behind all three grids above: same span, same
    indexing, same hold and same moving floor, so index i means second i in
    every one of them and a caller can read the three side by side."""
    t = streams.get("t") or []
    if len(t) < 2 or len(src) != len(t):
        return []
    t0 = int(t[0])
    span = int(t[-1]) - t0
    if span < MIN_SPAN_S:
        return []
    # Grid size is span + 1: inclusive of the endpoint sample, index i ↔ second i
    # (matches distance_fn's grid sizing so both index the same way)
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


def smooth(series: list, window: int = SMOOTH_WINDOW_S) -> list[float | None]:
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


def distance_fn(streams: dict) -> Callable[[int], float]:
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


def baseline_samples(streams: dict, stride: int = BASELINE_STRIDE) -> list[float]:
    """One run's contribution to the athlete's pace history — the moving speeds
    of its 1 Hz grid, thinned by `stride`. Callers accumulate these across the
    archive; pauses are already excluded by speed_series."""
    series = speed_series(streams)
    return [v for i, v in enumerate(series) if v is not None and i % stride == 0]


def work_floor(samples: list[float], percentile: float = WORK_FLOOR_PCT) -> float | None:
    """The speed above which this athlete is genuinely working, from their own
    history. None when there is too little history to be stable — an unstable
    percentile is worse than none, and the caller must then make no rep claim."""
    if len(samples) < WORK_FLOOR_MIN_SAMPLES:
        return None
    ordered = sorted(samples)
    return ordered[int(percentile * (len(ordered) - 1))]


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


def _pace_s_per_km(mps: float) -> int:
    return int(round(1000.0 / mps)) if mps and mps > 0 else 0


def _window_pace(series: list, a: int, b: int):
    """Mean pace over [a, b) of a 1 Hz speed grid, or None when that grid does
    not exist (an absent `gap` stream) or holds no moving samples there. None,
    not 0 — a missing metric must render as an em dash, never as a number."""
    if not series:
        return None
    mps = _mean(series[a:b])
    return _pace_s_per_km(mps) if mps else None


def _mean(vals) -> float | None:
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
    2 — a prescribed set that was cut short is still a set, and bailing at
    2-of-4 must report `found: 2` rather than collapse to steady (D10, the
    honesty contract). `_reps_min` is the ONE floor both paths share."""
    floor = _reps_min(expect_reps)
    if len(bouts) >= floor:
        return "reps"
    if len(bouts) == 1:
        a, b = bouts[0]
        if b - a >= BLOCK_MIN_S or dist_at(b) - dist_at(a) >= BLOCK_MIN_M:
            return "block"
    if _is_progression(series):
        return "progression"
    return "steady"


def _rep_variation(dists: list) -> tuple[int, bool]:
    """The set's nominal distance and whether it is 'varied' — the ONE
    definition every caller (label_for, set_stats, the laps path) shares, so
    they cannot disagree about a set's uniformity.

    `varied` is decided by the MAXIMUM per-rep deviation from the median, not
    the range (max − min): a range test lets a single outlier rep — most
    often one bout that got clipped early at find_bouts' exit threshold and so
    reads a little short — drag the whole verdict, turning a plainly uniform
    set into a false 'pyramid' on the strength of one under-measured rep.
    Measured on the real archive: this flips four genuinely uniform sets
    (a 5×1 km and three ~180–200 m hill/tempo sessions) to their correct
    label, while a real 1-2-1 km pyramid still reads as varied — the whole
    reason `varied` exists is to catch runs like that pyramid."""
    if not dists:
        return 0, False
    ordered = sorted(dists)
    nominal = ordered[len(ordered) // 2]
    varied = bool(nominal) and max(abs(d - nominal) for d in ordered) / nominal > VARIED_TOLERANCE
    return nominal, varied


def _reps_label(dists: list[float]) -> str:
    """The `reps` half of the one-line session name, given its rep distances
    IN ORDER — the ONE place both producers name a set, so a varied lap-
    sourced set (design D1, ground truth from the watch) cannot be named by
    different rules than a varied stream-detected one. Before this was
    extracted, `build_document`'s laps branch hand-rolled its own `N×D`
    string and returned `None` for every varied set — it never received the
    collapse-to-'N reps' fix below, so a real `5×1 km` with one trailing
    lap-artifact fragment displayed as unlabelled 'reps' on the athlete's own
    dashboard (production defect, 2026-07-27).

    `dists` must be in the reps' own chronological order — `varied` sets are
    enumerated positionally ('1-2-1 km' is a pyramid; '2-1-1 km' is not the
    same session) — so a caller must not sort them first."""
    nominal, varied = _rep_variation(dists)
    if varied:
        # Enumerating every rep is only informative when the set could
        # PLAUSIBLY be a written pyramid: few enough reps to read at a glance,
        # and every one of them landing on a distance a human would prescribe.
        # Otherwise the "label" is just the detector's fragment list, and it is
        # user-facing in three places at once — the /archive chip, the rep-card
        # title and the cockpit sentence. Measured on the real archive before
        # this rule: only 6 of 19 rep detections had a clean label and the rest
        # read like "0.89-0.385-0.333-0.417-0.598-0.894-1.77-0.811 km", which
        # is worse than the thirds verdict it replaced. Display only — the
        # detection, the segments and every `set` number are untouched, so
        # "N reps" never hides a rep the engine found.
        if len(dists) > VARIED_MAX_ENUMERATE or not all(_snaps_to_round(d) for d in dists):
            return f"{len(dists)} reps"
        parts = "-".join(f"{d / 1000:.3g}" for d in dists)
        return f"{parts} km"
    return f"{len(dists)}×{_round_dist(nominal)}"


def label_for(shape: str, bouts, dist_at) -> str | None:
    """The one-line session name — '5×1 km', '20 min block'. None when the run
    has no shape worth naming. The `reps` naming rules live in `_reps_label`,
    shared with the laps path in `build_document` (see its docstring)."""
    if shape == "block" and bouts:
        a, b = bouts[0]
        return f"{int(round((b - a) / 60))} min block"
    if shape != "reps" or not bouts:
        return None
    dists = [dist_at(b) - dist_at(a) for a, b in bouts]
    return _reps_label(dists)


_ROUND_TARGETS = ((200, "200 m"), (300, "300 m"), (400, "400 m"), (500, "500 m"),
                  (600, "600 m"), (800, "800 m"), (1000, "1 km"), (1200, "1.2 km"),
                  (1500, "1500 m"), (1600, "1600 m"), (2000, "2 km"),
                  (3000, "3 km"), (5000, "5 km"))


def _nearest_target(metres: float) -> tuple[int, str, float]:
    """The named distance this measurement is relatively closest to, and how
    far off it is. CLOSEST by relative error, not the first within tolerance:
    880 m sits inside 800's ±12 % band but is relatively nearer 1000, and a
    first-match loop mislabels it. Relative (not absolute) error is what keeps
    one tolerance honest across 200 m and 5 km."""
    target, text = min(_ROUND_TARGETS, key=lambda t: abs(metres - t[0]) / t[0])
    return target, text, abs(metres - target) / target


def _snaps_to_round(metres: float) -> bool:
    """Did the athlete plausibly MEAN this distance? A prescribed session is
    written in round numbers, so a set every one of whose reps snaps is a
    candidate for enumeration; one containing a 155 m or a 688 m fragment is
    the detector cutting continuous running into pieces."""
    return _nearest_target(metres)[2] <= ROUND_DIST_TOLERANCE


def _round_dist(metres: float) -> str:
    """Reps are run to round numbers — snap to the one the athlete meant."""
    _, text, err = _nearest_target(metres)
    return text if err <= ROUND_DIST_TOLERANCE else f"{metres / 1000:.2g} km"


def set_stats(bouts, series, dist_at, hr: list | None,
              raw: list | None = None, gaps: list | None = None) -> dict:
    """The set's own numbers — consistency, fade, and what the recoveries cost.

    `series` is the DETECTION grid (grade-adjusted where the run carries it,
    design D5). `raw` is the raw-speed grid and is what a rep's reported
    `paceS` comes from; `gaps` is the grade-adjusted grid and gives each rep
    its `gapS`. `raw` defaults to `series` so a caller with only one grid (a
    test, a payload with no `v`) keeps the old behaviour.

    `series` decides WHERE the reps are; `raw` decides what every reported
    number says. `paceCvPct` and `fadePct` used to ride `series`, which put
    them on a different signal from the `paceS` printed beside them and from
    the deviation bars drawn from it — a hilly set fanned its bars out under a
    sub-line reading "0.0 % spread". They now ride `raw`, which is also what
    the laps branch has always done, so the two producers agree.

    `found` vs `prescribed` is the honesty contract (design D4): prescribed is
    None while detection is blind, and once Change 2 fills the prior these two
    are allowed to disagree. A bailed session reports 3 of 4."""
    raw = series if raw is None else raw
    reps = []
    for a, b in bouts:
        reps.append({
            "durS": b - a,
            "distM": round(dist_at(b) - dist_at(a)),
            "paceS": _window_pace(raw, a, b) or 0,
            "gapS": _window_pace(gaps, a, b),
            "hr": int(round(_mean(hr[a:b]))) if hr and b <= len(hr) and _mean(hr[a:b]) else None,
        })
    paces = [r["paceS"] for r in reps if r["paceS"]]
    nominal, varied = _rep_variation([r["distM"] for r in reps])

    # Consistency and fade ride the RAW grid — the same signal as the reported
    # `paceS`, the rep table's PACE column and its deviation bars. See
    # test_spread_and_fade_are_measured_on_the_same_signal_as_the_bars for the
    # measurement behind this and what it trades away. DETECTION is unchanged:
    # `series` is still the grade-adjusted grid and still decides the bouts.
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


def laps_are_autolap(laps: list[dict]) -> bool:
    """True when every full lap is one kilometre (or one mile). Garmin's
    auto-lap fires on distance and carries NO intent — treating it as structure
    turns every long easy run into a rep session. The final lap is always a
    partial and is excluded from the test.

    Three matching FULL laps (after dropping the partial) is the floor: two
    full laps landing on 1 km each is exactly what a real 2×1 km session looks
    like, so requiring only two would flag genuine short interval sessions as
    auto-lap and discard real structure. Three is the smallest run of them
    that means "the watch is lapping on distance" rather than "this athlete
    happened to run two even reps."""
    dists = [l.get("distance") for l in laps if l.get("distance")]
    body = dists[:-1]                  # the final lap is always a partial
    if len(body) < 3:
        return False                   # too few full laps to call it a pattern
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


def segments_from_laps(laps: list[dict], gaps: list | None = None) -> list[dict]:
    """Lap DTOs → segments, taken VERBATIM (design D1). The watch is not
    guessing: boundaries, roles and per-lap statistics all come from the
    device, and nothing here re-derives them from the stream.

    `gaps` is a FALLBACK, not the primary source. A lapDTO usually carries
    `avgGradeAdjustedSpeed` (553 of this archive's 565 laps), and the device's
    own number is preferred: it is measured over exactly the lap, whereas the
    windowed lookup indexes the 1 Hz grid by a clock accumulated from lap
    `duration` — MOVING time — so on a paused run it drifts off the stream's
    elapsed axis and reads the wrong slice (handoff M3). `gaps` covers the
    older payloads that have no such field, so the GAP column is not empty on
    precisely the runs that earn a lap-sourced document — the athlete's
    genuine workout days. The lap clock is cumulative from the activity start,
    which is the same origin as the 1 Hz grid, so a lap's [t0, t1) indexes
    straight into it.

    A device value of exactly 0 (a standing-rest lap) is treated as ABSENT,
    not as "zero pace": `_pace_s_per_km(0)` cannot produce a sane number
    either way, so `lap.get(...)` — falsy on 0, None and missing keys alike —
    falls through to the windowed lookup rather than reporting a nonsense
    pace."""
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
            "gapS": _pace_s_per_km(lap["avgGradeAdjustedSpeed"])
                    if lap.get("avgGradeAdjustedSpeed")
                    else _window_pace(gaps, int(round(t0)), int(round(t0 + dur))),
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


def flatten_workout(payload: dict) -> list[dict]:
    """A Connect workout definition's EXECUTABLE steps, flattened depth-first,
    each carrying the `wktStepIndex` the FIT encoding gives it and the
    enclosing repeat group's `numberOfIterations` (add-workout-prior D7).

    The index rule is the whole subtlety: one index position is consumed
    AFTER each repeat group's children, because in FIT the `repeat_steps`
    instruction follows the steps it repeats. Verified to reproduce
    2026-06-05, 2026-07-10 and 2026-07-29 exactly.

    `zoneNumber` is load-bearing and easy to miss — a `heart.rate.zone`
    target carries its intensity there, not in `targetValueOne/Two`; a first
    measurement pass that read only the target values mistook four correct
    HR-Z4 tempo blocks for "no target"."""
    out: list[dict] = []
    idx = 0

    def walk(steps, iterations):
        nonlocal idx
        for s in steps or []:
            if s.get("type") == "RepeatGroupDTO":
                walk(s.get("workoutSteps"), s.get("numberOfIterations"))
                idx += 1        # the repeat instruction follows its children
            else:
                out.append({
                    "index": idx,
                    "stepType": (s.get("stepType") or {}).get("stepTypeKey"),
                    "endCondition": (s.get("endCondition") or {}).get("conditionTypeKey"),
                    "endConditionValue": s.get("endConditionValue"),
                    "targetType": (s.get("targetType") or {}).get("workoutTargetTypeKey"),
                    "targetValueOne": s.get("targetValueOne"),
                    "targetValueTwo": s.get("targetValueTwo"),
                    "zoneNumber": s.get("zoneNumber"),
                    "iterations": iterations,
                })
                idx += 1

    for seg in payload.get("workoutSegments") or []:
        walk(seg.get("workoutSteps"), None)
    return out


def workout_steps_for(laps: list[dict] | None, payload: dict) -> dict | None:
    """`{wktStepIndex: flattened step}` for one activity, or None — the
    all-or-nothing validation (add-workout-prior D7): every index observed on
    the executed laps must land on a flattened step, and when any does not,
    the prior for that activity is discarded ENTIRELY and the run falls back
    to inference. A partial mapping is never used: a half-applied prior is
    worse than none, because it looks authoritative.

    Laps with no indices at all (manual laps) trivially validate — there is
    nothing to contradict, and the prior can still contribute counts and
    targets."""
    flat = flatten_workout(payload)
    if not flat:
        return None
    by_index = {s["index"]: s for s in flat}
    observed = {l.get("wktStepIndex") for l in laps or []
                if l.get("wktStepIndex") is not None}
    if not observed <= set(by_index):
        return None
    return by_index


# Step types that are never work prescriptions, whatever their target says.
_EASY_STEP_TYPES = {"warmup", "cooldown", "rest", "recovery"}
# Pace-band midpoints within this relative distance are "materially the same"
# intensity (design D3): the genuine pyramid's three bands sit within 1.6 %,
# and no real workout in the 85 measured has distinct-but-close work bands.
_BAND_GROUP_TOLERANCE = 0.05


def _pace_band(step: dict) -> tuple | None:
    """(lo, hi) m/s for a pace.zone step, or None."""
    one, two = step.get("targetValueOne"), step.get("targetValueTwo")
    if step.get("targetType") == "pace.zone" and one and two:
        return (min(one, two), max(one, two))
    return None


def _is_vetoed(step: dict) -> bool:
    """Design D2: a step whose target VALUE is HR zone ≤ 2 can never be work,
    whatever its stepTypeKey says — 2026-06-05 types its warm-up `interval`
    and the veto must fire anyway. Z3 is deliberately untouched: 2025-12-14's
    14 km Z3 run reads `progression`, a defensible reading of its execution,
    and vetoing Z3 would suppress a true positive to fix nothing."""
    return (step.get("targetType") == "heart.rate.zone"
            and (step.get("zoneNumber") or 0) <= 2)


def derive_prior(payload: dict | None, laps: list[dict] | None,
                 start_local: str | None = None) -> dict | None:
    """The prescription as the engine consumes it (add-workout-prior D1/D4)
    — derived at build time from the RAW banked payload (D6), versioned by
    INTERVAL_VERSION like every other rule here. None when there is no
    workout or the step mapping fails validation (D7): a partial prior is
    never used.

    The prior CONSTRAINS the existing engine, it does not re-derive: VETO
    (an easy-target step is never work), POINT (a prescribed block says
    where to look), ADMIT (a prescribed rep beats the inference size
    floors). Segment boundaries, paces and HR always come from execution.

    Set membership needs the target's VALUE, not merely its type (D3):
    2025-12-05's three work-typed steps all share `heart.rate.zone`, being
    Z4 / Z2 / Z4 — the Z2 float is vetoed by value, leaving the real 2×2 km.
    Pace-band steps group when their band midpoints are materially the same,
    which keeps the genuine pyramid (2026-06-26) one varied set."""
    if not payload:
        return None
    steps = workout_steps_for(laps, payload)
    if steps is None:
        return None

    flat = sorted(steps.values(), key=lambda s: s["index"])
    vetoed = {s["index"] for s in flat if _is_vetoed(s)}
    work = [s for s in flat
            if s["index"] not in vetoed
            and s["stepType"] not in _EASY_STEP_TYPES]

    # group work steps by target value (D3); repeated steps carry iterations
    groups: list[list[dict]] = []
    for s in work:
        band = _pace_band(s)
        placed = False
        for g in groups:
            gband = _pace_band(g[0])
            if band and gband:
                mid, gmid = sum(band) / 2, sum(gband) / 2
                if abs(mid - gmid) / gmid <= _BAND_GROUP_TOLERANCE:
                    g.append(s)
                    placed = True
                    break
            elif (s.get("targetType"), s.get("zoneNumber")) == \
                    (g[0].get("targetType"), g[0].get("zoneNumber")):
                g.append(s)
                placed = True
                break
        if not placed:
            groups.append([s])

    # the prescribed set is the group expecting the most executions
    set_group = max(groups, key=lambda g: sum(s["iterations"] or 1 for s in g),
                    default=None) if groups else None
    set_steps = {s["index"] for s in set_group} if set_group else set()
    count = sum(s["iterations"] or 1 for s in set_group) if set_group else None
    by_time = bool(set_group) and all(
        s["endCondition"] == "time" for s in set_group)

    block = None
    if count == 1:
        s = set_group[0]
        block = {"endCondition": s["endCondition"],
                 "value": s["endConditionValue"],
                 "band": _pace_band(s),
                 "zone": s.get("zoneNumber")
                 if s.get("targetType") == "heart.rate.zone" else None}

    stale = False
    updated = (payload.get("updatedDate") or "")[:19]
    if updated and start_local:
        stale = updated > start_local.replace(" ", "T")[:19]

    return {
        "steps": steps, "vetoed": vetoed,
        "setSteps": set_steps, "count": count, "byTime": by_time,
        "repValue": set_group[0]["endConditionValue"] if set_group else None,
        "bands": {s["index"]: _pace_band(s) for s in flat if _pace_band(s)},
        "block": block,
        "hard": bool(work),
        "stale": stale,
    }


# POINT (add-workout-prior D1a) — the prescription LOCATES, execution DECIDES.
POINT_BAND_TOLERANCE = 0.05   # ± on the prescribed band's edges: 2026-02-27's
                              # best window is 1 s/km FASTER than its band's
                              # fast end, and refusing an athlete for beating
                              # the prescription by seconds would be absurd
POINT_VARIANCE_MAX = 0.25     # within-window cv above this is a hard/easy rep
                              # pattern, not a block — the variance guard for
                              # a substituted session (design open question 1;
                              # deliberately conservative: a smoothed real
                              # block sits under 10, alternating reps near 30)
POINT_GAP_HEDGE_S = 60        # this much standstill inside the window means
                              # the block was merged across a gap → hedged
_PRIOR_CONFIRMED = 0.9        # prescription-corroborated verdicts (D8)
_PRIOR_HEDGED = 0.4           # prescription and execution disagree — below
                              # CONFIDENCE_ASSERT_MIN by construction


def _point_window(series: list, raw: list, dist_at, total_s: int,
                  block: dict, bouts: list | None = None) -> tuple | None:
    """The best window of exactly the prescribed distance, confirmed against
    the prescribed band — or None, and the caller falls back to inference.

    1. slide a window of the prescribed size over the run,
    2. keep the fastest (the prescription says where to LOOK, and the block,
       if run, is the hardest stretch of its own length),
    3. CONFIRM: its mean pace must fall within the prescribed band — a run
       that plodded the window did not run the workout, and reporting it
       completed would invert the honesty contract,
    4. refuse a window whose within-window variance says rep pattern, not
       block (the substituted-session guard),
    5. flag an INTERRUPTED execution for hedging: a contiguous deep
       interruption (a stop, a walk — well below the band), or a window the
       calibrated bout structure fragments (two or more detected bouts
       inside it: the hysteresis saw the athlete break and resurge).

       Measured against the six real POINT runs, within-window pace CANNOT
       single out the design's named hedge case (2026-01-23's 304 s gap is a
       shallow jog; the 'clean' 2026-01-09 dips below the band for longer),
       so the hedge is decided by evidence of interruption instead — which
       also catches 2026-02-27's genuine 92 s standstill the design's trace
       never examined.

    Never consults the calibration floor for CONFIRMATION (closes handoff
    P2.3): the floor-filtered bouts are only read as fragmentation
    evidence."""
    dist = block.get("value") or 0
    lo, hi = block["band"]
    if dist <= 0 or total_s < 2 or dist_at(total_s) < dist:
        return None
    best = None
    b = 0
    for a in range(total_s):
        if b <= a:
            b = a + 1
        while b < total_s and dist_at(b) - dist_at(a) < dist:
            b += 1
        if dist_at(b) - dist_at(a) < dist:
            break
        mps = dist / (b - a)
        if best is None or mps > best[2]:
            best = (a, b, mps)
    if not best:
        return None
    a, b, mps = best
    if not (lo * (1 - POINT_BAND_TOLERANCE) <= mps
            <= hi * (1 + POINT_BAND_TOLERANCE)):
        return None
    moving = [v for v in raw[a:b] if v]
    m = _mean(moving)
    if m and len(moving) > 1:
        var = sum((v - m) ** 2 for v in moving) / len(moving)
        if (var ** 0.5) / m > POINT_VARIANCE_MAX:
            return None
    deep = longest = 0
    for v in series[a:b]:
        longest = longest + 1 if (v is None or v < lo * 0.8) else 0
        deep = max(deep, longest)
    fragmented = sum(1 for x, y in (bouts or []) if x < b and y > a) >= 2
    return a, b, deep >= POINT_GAP_HEDGE_S or fragmented


def _zero_set(expect: int) -> dict:
    """The bailed-session set (design D10): a workout begun and abandoned is
    a real training event, and the page should be able to say '0 of N
    prescribed reps' rather than presenting the warm-up as a plain easy run."""
    return {"found": 0, "prescribed": expect, "nominalDistM": None,
            "varied": False, "paceS": None, "paceCvPct": None, "fadePct": None,
            "recoveryS": None, "recoveryHrDrop": None, "reps": []}


def _reps_min(expect: int | None) -> int:
    """ONE rep-count floor for both paths (retires handoff P2.7b/P3.1). A
    prescribed set that was cut short is still a set — bailing at 2-of-4 must
    report `found: 2`, not collapse to steady — so any prescription of two or
    more lowers the floor to 2. (The handoff recorded the fix as
    `max(2, min(REPS_MIN_COUNT, expect))`, which still reads 3 at expect 4
    and cannot report the 2-of-4 case it was written for; this is the formula
    that can.) Without a prescription the inference floor stands."""
    if expect and expect >= 2:
        return 2
    return REPS_MIN_COUNT


def _rep_step_indices(laps: list[dict], work_idx: set[int]) -> set | None:
    """Which workout STEP indices identify reps — or None when this activity
    carries no usable step evidence and the caller must keep every work lap.

    `wktStepIndex` is the step of the downloaded workout a lap executed. Reps
    of one set share a single REPEATED step; a warmup, a cooldown or a
    transition occupies its own step, used once. That is the only signal that
    separates them: Garmin tags all of them ACTIVE, and the one-off ones are
    LONGER than the reps, so no size floor can reach them (production defect
    2026-07-28, 8 of 23 lap-sourced documents).

    `work_idx` is the set of lap indices already accepted as work by role and
    by the size floor — counting steps over recovery laps would let a repeated
    RECOVERY step decide which laps are reps.
    """
    if not any(l.get("wktStepIndex") is not None for l in laps):
        return None                       # nothing to go on: keep every rep
    counts = Counter(laps[i].get("wktStepIndex") for i in work_idx
                     if laps[i].get("wktStepIndex") is not None)
    if not counts:
        # A non-work lap (warmup, recovery, cooldown...) carries a step index
        # but no floor-passing WORK lap does — e.g. the athlete abandoned a
        # downloaded workout after its warmup step, then manually lapped a
        # genuine rep set with no steps of its own. This is the same
        # "no usable evidence" answer as the guard above: an activity whose
        # work laps carry no step index tells us nothing about which of them
        # are reps, so the honest response is to keep them all, not to
        # conclude that none of them is a rep.
        return None
    repeated = {step for step, n in counts.items() if n > 1}
    if repeated:
        return repeated
    # every work step distinct — a genuinely varied session (a pyramid). The
    # only thing still disqualifying is carrying no step at all.
    return set(counts)


def _lap_survivors(segments: list[dict], laps: list[dict],
                   size_floor: bool = True) -> tuple[set, set, set]:
    """The survivor selection both filters produce, as bare index sets:
    `(survivors, size_discards, step_discards)` over lap positions.

    Extracted from `_lap_rep_segments` so the materiality check (design D2 of
    fix-lap-confidence) can re-run the SAME selection with the size floor
    lifted and compare survivor sets — a literal statement of "the shape
    depends on the discard" rather than a proxy for it. Pure: no state, and
    the caller's segments and laps are never mutated.

    `size_floor=False` lifts WORK_MIN_S/WORK_MIN_M only; the step rule always
    applies — it is the device's own evidence, not an engine guess."""
    work = {i for i, s in enumerate(segments) if s["role"] == "work"}
    sized = {i for i in work
             if not size_floor
             or (segments[i]["durS"] >= WORK_MIN_S
                 and segments[i]["distM"] >= WORK_MIN_M)}
    steps = _rep_step_indices(laps, sized)
    survivors = sized if steps is None else {
        i for i in sized if laps[i].get("wktStepIndex") in steps}
    return survivors, work - sized, sized - survivors


def _size_discard_is_material(segments: list[dict], laps: list[dict]) -> bool:
    """Did the SIZE floor decide this run's shape? (design D2 of
    fix-lap-confidence)

    'A size discard occurred' is far too weak a trigger — nearly every
    lap-sourced run ends with a sub-floor fragment the athlete's stop press
    produced, and hedging all of them would hedge everything and mean nothing.
    So the question is asked directly: re-run the SAME survivor selection with
    the size floor lifted, and call the discard material only when the
    survivor set changes. Wherever a genuine repeated step exists, a trailing
    fragment carries no step index and the step rule kills it either way, so
    this self-selects the cases that matter.

    Pure: two calls to `_lap_survivors`, microseconds on ≤ 30 laps."""
    with_floor, _, _ = _lap_survivors(segments, laps)
    lifted, _, _ = _lap_survivors(segments, laps, size_floor=False)
    return with_floor != lifted


def _verdict(confidence: float) -> bool:
    """Does a document with this confidence assert its shape? THE one
    comparison against CONFIDENCE_ASSERT_MIN (fix-lap-confidence D4, closing
    handoff M2): the engine decides, the document carries the boolean, and
    the page renders it without threshold arithmetic of its own."""
    return confidence >= CONFIDENCE_ASSERT_MIN


def _lap_confidence(segments: list[dict], laps: list[dict]) -> tuple[str, float]:
    """A lap-sourced document's confidence level and value (design D3).

    `segments` must be the raw `segments_from_laps` output, BEFORE
    `_lap_rep_segments` re-roles anything — the selection here has to see the
    same work-role population both filters saw.

    eliminated    the shape depends on a material size discard (D2) — the
                  engine's own floor removed the alternative, so the verdict
                  must not assert.
    corroborated  the surviving reps share a repeated workout step: the
                  device's own evidence, the case the lap path exists for.
    structured    everything else the device recorded — a block, a varied
                  set on distinct steps, or laps with no step evidence."""
    if _size_discard_is_material(segments, laps):
        return "eliminated", _LAP_CONFIDENCE["eliminated"]
    survivors, _, _ = _lap_survivors(segments, laps)
    counts = Counter(laps[i].get("wktStepIndex") for i in survivors
                     if laps[i].get("wktStepIndex") is not None)
    if any(n > 1 for n in counts.values()):
        return "corroborated", _LAP_CONFIDENCE["corroborated"]
    return "structured", _LAP_CONFIDENCE["structured"]


def _lap_rep_segments(segments: list[dict], laps: list[dict],
                      survivors: set | None = None) -> tuple[list[dict], dict]:
    """Which lap-derived work segments are genuine reps — returns the re-roled
    segments plus the discard bookkeeping `{"size": set, "step": set}` of lap
    indices each filter rejected (design D1 of fix-lap-confidence: the two
    filters are NOT equivalent — a size discard may hedge the document's
    confidence, a step demotion never does, so they must stay distinguishable
    rather than collapse into one 'discarded' set).

    Two filters, one question. The SIZE floor (`WORK_MIN_S` / `WORK_MIN_M`,
    the same one `find_bouts` applies to the stream path) rejects fragments —
    the athlete pressing stop, the watch's own end-of-activity lap. The STEP
    rule rejects the opposite failure: a warmup, cooldown or transition the
    watch tagged ACTIVE, which is bigger than a rep rather than smaller.

    A rejected lap is RE-ROLED, never removed: `segments_from_laps` guarantees
    every segment's `t0/t1/d0/d1` chains to the next with no gap, and
    consumers (the rep-shaded stream chart, `_quality`'s summation) rely on
    that full-span coverage. Deleting would open a hole in the run nothing in
    the contract allows. The new role mirrors the vocabulary
    `_segments_from_bouts` already uses for the stream path's own gaps:
    `warmup` before the first surviving rep, `cooldown` after the last,
    `recovery` in between (and when no rep survives at all there is no
    'between' to speak of, but the caller has already demoted the run to
    `steady` or `block`, so the exact word affects no number).

    `idx` never changes. `rep` renumbers 1..N over the SURVIVING work
    segments only, in order, so a demoted lap mid-set leaves no hole.

    A `warmup`/`recovery`/`cooldown` lap is untouched however short: those
    roles carry no minimum on the stream path either.

    `segments[i]` must correspond to `laps[i]`: `segments_from_laps` emits
    exactly one segment per lap, in order, and this function indexes `laps`
    by segment position on that assumption. If that ever stops holding, this
    must fail loudly rather than silently read the wrong lap's step index.
    """
    assert len(segments) == len(laps), \
        "segments_from_laps must emit exactly one segment per lap, in order"
    if survivors is None:
        survivors, size_discards, step_discards = _lap_survivors(segments, laps)
    else:
        # prescription-selected (add-workout-prior D1): the prior decided
        # which laps are the set — demotions here are corroborated by the
        # workout itself, so they live in the never-hedge bucket, and the
        # size floors were never consulted (ADMIT).
        size_discards = set()
        step_discards = {i for i, s in enumerate(segments)
                         if s["role"] == "work" and i not in survivors}

    ordered = sorted(survivors)
    first = ordered[0] if ordered else None
    last = ordered[-1] if ordered else None

    out = []
    rep = 0
    for i, seg in enumerate(segments):
        seg = dict(seg)
        if seg["role"] == "work":
            if i in survivors:
                rep += 1
                seg["rep"] = rep
            else:
                seg.pop("rep", None)
                if first is None:
                    seg["role"] = "recovery"
                elif i < first:
                    seg["role"] = "warmup"
                elif i > last:
                    seg["role"] = "cooldown"
                else:
                    seg["role"] = "recovery"
        out.append(seg)
    return out, {"size": size_discards, "step": step_discards}


def _segments_from_bouts(bouts, series, dist_at, hr, total_s,
                         raw=None, gaps=None) -> list[dict]:
    """Bouts → the full segment list, with the gaps between them named. The
    first gap is a warmup and the last a cooldown; everything between is a
    recovery, because that is what it was.

    `raw`/`gaps` are the two reporting grids (see `set_stats`): `paceS` comes
    from raw speed, `gapS` from grade-adjusted speed, and `gapS` stays None
    when the run carries no `gap` stream at all."""
    raw = series if raw is None else raw
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
        seg = {
            "idx": idx + 1, "role": role,
            "t0": a, "t1": b,
            "d0": int(round(dist_at(a))), "d1": int(round(dist_at(b))),
            "durS": b - a, "distM": int(round(dist_at(b) - dist_at(a))),
            "paceS": _window_pace(raw, a, b) or 0,
            "gapS": _window_pace(gaps, a, b),
            "hr": int(round(_mean(hr[a:b]))) if hr and _mean(hr[a:b]) else None,
            "cad": None,
        }
        if role == "work":
            seg["rep"] = rep
        segs.append(seg)
    return segs


def _progression_segments(series: list, dist_at, hr: list, total_s: int,
                          raw=None, gaps=None) -> list[dict]:
    """A progression's ramp as five `step` segments, one per detected pace
    tier, in time order — tiling the run's full span edge to edge with no
    gaps, the same property `_segments_from_bouts` guarantees for rep runs, so
    a consumer can read a progression's ramp the way it reads a rep table.

    Quintile boundaries are cut on the raw 1 Hz grid (not the moving-only
    values `_is_progression` measures its monotone rise against) so that t0/t1
    tile the run exactly; the two agree whenever the run has no pauses, which
    `_is_progression`'s own MIN_MOVING_SAMPLES floor already requires close to."""
    raw = series if raw is None else raw
    step = total_s // 5
    edges = [(i * step, total_s if i == 4 else (i + 1) * step) for i in range(5)]
    segs = []
    for idx, (a, b) in enumerate(edges):
        segs.append({
            "idx": idx + 1, "role": "step",
            "t0": a, "t1": b,
            "d0": int(round(dist_at(a))), "d1": int(round(dist_at(b))),
            "durS": b - a, "distM": int(round(dist_at(b) - dist_at(a))),
            "paceS": _window_pace(raw, a, b) or 0,
            "gapS": _window_pace(gaps, a, b),
            "hr": int(round(_mean(hr[a:b]))) if hr and _mean(hr[a:b]) else None,
            "cad": None,
        })
    return segs


def _confidence(separation: float, bouts, series, cv) -> float:
    """Three factors, multiplied and clamped (spec): how far apart the two pace
    classes sit, how crisp the boundaries are, and — for a set — how regular
    the reps were. STREAM path only: lap-sourced documents derive theirs from
    `_lap_confidence`'s named levels instead (fix-lap-confidence D3)."""
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
                   workout: dict | None = None,
                   bounds: list[int] | None = None,
                   work_floor: float | None = None) -> dict | None:
    """The ONE entry point both producers call. Returns the interval document,
    or None when the run carries no usable speed signal at all.

    Order of authority (design D1/D8, add-workout-prior D4): the PRIOR — the
    raw Garmin workout definition this run was started from, when the caller
    has one banked — is resolved BEFORE the laps/stream branch, so both paths
    read one prescription by identical rules. Then structured device laps win
    outright; otherwise the stream decides.

    `work_floor` (Task 7b) is the caller-supplied calibration floor — this
    engine never opens a database, so it cannot derive its own. Device laps
    need no such floor (the watch is not guessing) and are always calibrated."""
    summary = summary or {}
    streams = streams or {}
    series_raw = speed_series(streams)
    if not series_raw:
        return None

    # Three grids over one clock: the DETECTION signal (grade-adjusted where
    # the run carries it, design D5) decides where the reps are; the raw and
    # grade-adjusted grids report what each of them cost. They were one grid
    # until the final review, which is how `paceS` came to hold GAP while the
    # column labelled GAP held nothing at all.
    raw_grid = smooth(raw_speed_series(streams))
    gap_grid = smooth(gap_speed_series(streams))

    # The prior sits UPSTREAM of the branch (add-workout-prior D4) — deriving
    # it after the laps branch returned was how the runs that carry a
    # prescription (overwhelmingly lap-sourced) could never see one.
    prior = derive_prior(workout, laps, summary.get("startTimeLocal"))
    expect = prior["count"] if prior else None

    # `guidedBy` has been null on every document since the lens shipped,
    # reserved for exactly this: which prescription read this run, and
    # whether it can be trusted FOR THIS RUN (corrected D5 — a payload
    # updated after the run's start provably postdates what was executed).
    # A run with no usable workout keeps the explicit null.
    base = {"version": INTERVAL_VERSION,
            "guidedBy": {"workoutId": (workout or {}).get("workoutId"),
                         "stale": prior["stale"]} if prior else None}

    if laps and laps_are_structured(summary, laps):
        raw_segments = segments_from_laps(laps, gap_grid)
        # The prescription decides which laps are the set when it can join
        # (add-workout-prior D1): VETO — a lap executing an easy-target step
        # is never work, whatever its stepTypeKey said; set membership by
        # target VALUE (D3); ADMIT — a lap executing a prescribed rep step is
        # a rep however small (the size floors exist to reject fragments the
        # detector invented, not reps the athlete was told to run). Roles and
        # inference floors stay the fallback for runs with no usable prior.
        prior_joins = bool(prior) and any(
            l.get("wktStepIndex") is not None for l in laps)
        if prior_joins:
            selected = {i for i, l in enumerate(laps)
                        if l.get("wktStepIndex") in prior["setSteps"]}
            segments, discards = _lap_rep_segments(raw_segments, laps, selected)
        else:
            segments, discards = _lap_rep_segments(raw_segments, laps)
        work = [s for s in segments if s["role"] == "work"]
        paces = [s["paceS"] for s in work if s["paceS"]]
        mean_pace = _mean(paces)
        cv = None
        if mean_pace and len(paces) > 1:
            var = sum((p - mean_pace) ** 2 for p in paces) / len(paces)
            cv = round(100.0 * (var ** 0.5) / mean_pace, 1)
        # A single surviving work lap is only a BLOCK if it is big enough to
        # be one — the SAME BLOCK_MIN_S/BLOCK_MIN_M floor, on the SAME `or`
        # basis, that classify() applies for the stream path (see its
        # `if b - a >= BLOCK_MIN_S or dist_at(b) - dist_at(a) >= BLOCK_MIN_M`
        # around line 308): one definition of a block across both producers.
        # Task 2's step rule makes the single-survivor case common, and
        # without this a 205 m fragment of a run/walk asserts "1 min block"
        # (handoff P2.7a). The rep threshold is `_reps_min` — the SAME floor
        # classify() applies on the stream path (add-workout-prior D4 retires
        # handoff P2.7b's two independent floors).
        if len(work) >= _reps_min(expect):
            shape = "reps"
        elif work and (work[0]["durS"] >= BLOCK_MIN_S
                       or work[0]["distM"] >= BLOCK_MIN_M):
            shape = "block"
        else:
            shape = "steady"
        nominal, varied = _rep_variation([s["distM"] for s in work])
        by_time = bool(prior_joins and prior["byTime"] and prior["repValue"])
        if by_time:
            # A set prescribed by TIME is named and compared by time (handoff
            # N3): 2026-02-06's six 90 s hill reps cover different distances
            # precisely because the athlete tires — "6×0.23 km" measured the
            # fatigue, not the set. Uniform by construction: the reps all
            # executed one time-prescribed step.
            nominal, varied = None, False
        # Confidence (D8, on the base fix-lap-confidence laid): a FRESH
        # prescription is the strongest evidence available — execution
        # agreeing with it asserts, disagreeing hedges. A stale prescription
        # (corrected D5) is never evidence either way, and a run with no
        # usable prior keeps the inference levels.
        if prior_joins and not prior["stale"]:
            agreed = ((shape == "reps" and len(work) == expect)
                      or (shape == "block" and prior["count"] == 1))
            confidence = 1.0 if agreed else _PRIOR_HEDGED
        else:
            # reads the RAW segments — _lap_rep_segments re-roles the demoted
            # laps, and the materiality re-run has to see the same work-role
            # population the original selection saw
            _level, confidence = _lap_confidence(raw_segments, laps)
        if shape == "reps":
            label = (f"{len(work)}×{prior['repValue']:g} s" if by_time
                     else _reps_label([s["distM"] for s in work]))
        elif shape == "block":
            # Same wording as label_for's block branch, over the ONE
            # surviving work segment's own duration.
            label = f"{int(round(work[0]['durS'] / 60))} min block"
        else:
            label = None
        # Contract (design): "a steady run still gets a document, no
        # segments" — the same rule the stream path already honours. Before
        # the work floor this branch could only reach "steady" with zero
        # ACTIVE laps in the first place; now a session whose every lap-
        # tagged rep is a sub-floor fragment can land here too, so the rule
        # has to be enforced explicitly rather than falling out for free.
        if shape == "steady":
            segments = []
        if shape != "reps":
            # D10: a prescribed set with NOTHING found is a real training
            # event — the shortfall is reported, never hidden. A block found
            # instead is a disagreement for corroboration (D8), not a zero.
            lap_set = (_zero_set(expect)
                       if shape == "steady" and expect and expect >= 2 else None)
        return {
            **base,
            "shape": shape, "source": "laps", "confidence": confidence,
            "asserts": _verdict(confidence),
            "calibrated": True,
            "label": label,
            "segments": segments,
            "set": lap_set if shape != "reps" else {
                "found": len(work), "prescribed": expect,
                "nominalDistM": None if varied else (nominal or None),
                "varied": varied,
                "paceS": int(round(mean_pace)) if mean_pace else None,
                "paceCvPct": cv, "fadePct":
                    round(100.0 * (paces[-1] - paces[0]) / paces[0], 1)
                    if len(paces) > 1 and paces[0] else None,
                "recoveryS": None, "recoveryHrDrop": None,
                "reps": [{"durS": s["durS"], "distM": s["distM"],
                          "paceS": s["paceS"], "gapS": s["gapS"],
                          "hr": s["hr"]} for s in work],
            },
            "quality": _quality(segments, bounds),
        }

    series = smooth(series_raw)
    dist_at = distance_fn(streams)
    hr = _hr_grid(streams, len(series))
    classes = split_classes(series)
    bouts = find_bouts(series, dist_at, classes[0], classes[1]) if classes else []

    # Cross-run calibration (Task 7b): a bout must be genuinely fast for THIS
    # athlete, not merely faster than the rest of its own run. Without a floor
    # we cannot tell those apart, so we make no rep claim at all.
    calibrated = work_floor is not None
    if calibrated:
        bouts = [(a, b) for a, b in bouts
                 if (_mean(series[a:b]) or 0) >= work_floor]
    else:
        bouts = []
    if prior and not prior["hard"]:
        # VETO, whole-run form (D2): the workout prescribed nothing hard —
        # every step's target value is easy — so a fast half must not be
        # promoted to a set or a block. Progression stays reachable: a
        # negative-split easy run is a reading of pacing, not a quality claim.
        bouts = []
    point = None
    if prior and prior.get("block"):
        blk = prior["block"]
        if blk.get("band") and blk.get("endCondition") == "distance":
            point = _point_window(series, raw_grid, dist_at, len(series), blk,
                                  bouts)
    if point:
        a, b, gap_hedged = point
        bouts = [(a, b)]
        shape = "block"
    else:
        shape = classify(bouts, series, dist_at, expect)
    if shape in ("steady", "progression"):
        bouts = []
    stats = (set_stats(bouts, series, dist_at, hr, raw_grid, gap_grid)
             if shape == "reps" else None)
    if stats:
        stats["prescribed"] = expect
    elif shape == "steady" and expect and expect >= 2:
        # D10: the prescribed set the athlete never started (or abandoned
        # before any rep survived) is reported, not hidden.
        stats = _zero_set(expect)
    if shape == "steady":
        segments = []
    elif shape == "progression":
        # A progression has no discrete work bouts to segment — its ramp is
        # five `step` tiers instead (design contract), not the single
        # whole-run bout-shaped segment `_segments_from_bouts` would produce
        # from an empty bout list.
        segments = _progression_segments(series, dist_at, hr, len(series),
                                         raw_grid, gap_grid)
    else:
        segments = _segments_from_bouts(bouts, series, dist_at, hr, len(series),
                                        raw_grid, gap_grid)
    if point:
        # D8: a POINT block is prescription-corroborated — it asserts, unless
        # its execution was interrupted, in which case the shape is the best
        # reading available but not a certainty.
        confidence = _PRIOR_HEDGED if gap_hedged else _PRIOR_CONFIRMED
    else:
        confidence = _confidence(classes[2] if classes else 0.0, bouts, series,
                                 stats["paceCvPct"] if stats else None)
        if prior and not prior["stale"] and expect and expect >= 2 and stats:
            # D8 on the stream path too: one prescription, one rule.
            confidence = (_PRIOR_CONFIRMED if stats.get("found") == expect
                          else _PRIOR_HEDGED)
    return {
        **base,
        "shape": shape, "source": "stream", "calibrated": calibrated,
        "confidence": confidence,
        "asserts": _verdict(confidence),
        "label": label_for(shape, bouts, dist_at),
        "segments": segments,
        "set": stats,
        "quality": _quality(segments, bounds),
    }


def compact(doc: dict | None) -> dict | None:
    """The document MINUS its segments — what the cockpit and the recent-run
    drill-down need. It rides in garmin-data.js because the cockpit renders
    complete from static files with no API, and an interval label must not be
    the thing that breaks that promise. `/run/:id` fetches the full document."""
    if not doc:
        return None
    return {k: v for k, v in doc.items() if k != "segments"}


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
