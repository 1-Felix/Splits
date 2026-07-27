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
