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


def split_classes(series: list):
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
