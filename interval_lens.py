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

from collections.abc import Callable

INTERVAL_VERSION = 1

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
PROGRESSION_MIN_GAIN = 0.05   # last quintile >=5 % faster than the first
ROUND_DIST_TOLERANCE = 0.12   # relative error within which a rep snaps to a named distance
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
    """Reps are run to round numbers — snap to the one the athlete meant.

    Picks the CLOSEST target by relative error, not the first within tolerance:
    880 m sits inside 800's ±12 % band but is relatively nearer 1000, and a
    first-match loop mislabels it. Relative (not absolute) error is what keeps
    one tolerance honest across 200 m and 5 km.
    """
    targets = ((200, "200 m"), (300, "300 m"), (400, "400 m"), (500, "500 m"),
               (600, "600 m"), (800, "800 m"), (1000, "1 km"), (1200, "1.2 km"),
               (1500, "1500 m"), (1600, "1600 m"), (2000, "2 km"),
               (3000, "3 km"), (5000, "5 km"))
    target, text = min(targets, key=lambda t: abs(metres - t[0]) / t[0])
    if abs(metres - target) / target <= ROUND_DIST_TOLERANCE:
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
