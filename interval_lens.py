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

INTERVAL_VERSION = 3   # 2: paceS is raw pace and gapS is real (final review I4);
                       #    ragged pyramid labels collapse to "N reps" (I6)
                       # 3: the laps path applies the same WORK_MIN_S/WORK_MIN_M
                       #    rep floor the stream path always has, and shares its
                       #    labelling logic — a trailing partial lap no longer
                       #    reads as a rep, and a varied lap-sourced set no
                       #    longer loses its label (production defect, 2026-07-27)

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
CONFIDENCE_ASSERT_MIN = 0.5   # below this the UI says "possible", never asserts
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

    The split matters for `fadePct` and `paceCvPct`, which stay on the
    DETECTION signal: a set of reps run up and back down a drag is not a fade,
    and saying so is the whole reason D5 exists. The reported paces are the raw
    ones because that is what the athlete ran and what the rep table shows next
    to them.

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

    # consistency and fade ride on the detection signal, the reported mean on
    # the raw one — see the docstring
    effort = [p for p in (_window_pace(series, a, b) for a, b in bouts) if p]
    mean_pace = _mean(paces)
    cv = None
    mean_effort = _mean(effort)
    if mean_effort and len(effort) > 1:
        var = sum((p - mean_effort) ** 2 for p in effort) / len(effort)
        cv = round(100.0 * (var ** 0.5) / mean_effort, 1)

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
        "fadePct": round(100.0 * (effort[-1] - effort[0]) / effort[0], 1)
                   if len(effort) > 1 and effort[0] else None,
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

    `gaps` is the one exception, and it is an addition rather than a
    re-derivation: a lapDTO carries no grade-adjusted speed, so without it the
    GAP column is empty on precisely the runs that earn a lap-sourced document
    — the athlete's genuine workout days. The lap clock is cumulative from the
    activity start, which is the same origin as the 1 Hz grid, so a lap's
    [t0, t1) indexes straight into it."""
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
            "gapS": _window_pace(gaps, int(round(t0)), int(round(t0 + dur))),
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


def _lap_rep_segments(segments: list[dict], laps: list[dict]) -> list[dict]:
    """Which lap-derived work segments are genuine reps.

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
    sized = {i for i, s in enumerate(segments)
             if s["role"] == "work"
             and s["durS"] >= WORK_MIN_S and s["distM"] >= WORK_MIN_M}
    steps = _rep_step_indices(laps, sized)
    survivors = sized if steps is None else {
        i for i in sized if laps[i].get("wktStepIndex") in steps}

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
    return out


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
                   bounds: list[int] | None = None,
                   work_floor: float | None = None) -> dict | None:
    """The ONE entry point both producers call. Returns the interval document,
    or None when the run carries no usable speed signal at all.

    Order of authority (design D1/D8): structured device laps win outright;
    otherwise the stream decides, optionally sharpened by a plan prior. In this
    change `prior` is always None — the parameter exists so Change 2 can fill
    it without reshaping the contract.

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

    base = {"version": INTERVAL_VERSION, "guidedBy": None}

    if laps and laps_are_structured(summary, laps):
        segments = _lap_rep_segments(segments_from_laps(laps, gap_grid), laps)
        work = [s for s in segments if s["role"] == "work"]
        paces = [s["paceS"] for s in work if s["paceS"]]
        mean_pace = _mean(paces)
        cv = None
        if mean_pace and len(paces) > 1:
            var = sum((p - mean_pace) ** 2 for p in paces) / len(paces)
            cv = round(100.0 * (var ** 0.5) / mean_pace, 1)
        shape = "reps" if len(work) >= 2 else ("block" if work else "steady")
        nominal, varied = _rep_variation([s["distM"] for s in work])
        if shape == "reps":
            label = _reps_label([s["distM"] for s in work])
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
        return {
            **base,
            "shape": shape, "source": "laps", "confidence": 1.0,
            "calibrated": True,
            "label": label,
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
    expect = (prior or {}).get("count")

    # Cross-run calibration (Task 7b): a bout must be genuinely fast for THIS
    # athlete, not merely faster than the rest of its own run. Without a floor
    # we cannot tell those apart, so we make no rep claim at all.
    calibrated = work_floor is not None
    if calibrated:
        bouts = [(a, b) for a, b in bouts
                 if (_mean(series[a:b]) or 0) >= work_floor]
    else:
        bouts = []
    shape = classify(bouts, series, dist_at, expect)
    if shape in ("steady", "progression"):
        bouts = []
    stats = (set_stats(bouts, series, dist_at, hr, raw_grid, gap_grid)
             if shape == "reps" else None)
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
    return {
        **base,
        "shape": shape, "source": "stream", "calibrated": calibrated,
        "confidence": _confidence(classes[2] if classes else 0.0, bouts, series,
                                  stats["paceCvPct"] if stats else None),
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
