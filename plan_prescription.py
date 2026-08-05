"""The plan's structured prescriptions, parsed — and everything else refused.

add-plan-prescription (P3.2, design D1): a pure parser over a planned day's
`segments[].val` strings. The coach writes prose; a deliberately TINY grammar
reads the structured core out of it:

  rep sets        4×1 km @ 5:25–5:35 · 3×1 km @ 5:41 · 4×20 s fast-relaxed
                  6×3 min hard (Z4 effort) · 5×1 km by effort · Z4
                  …and the embedded form: 3 km easy · 3×400 m @ 5:41 inside
  steady targets  16 km easy @ ~6:10   (the `~` is the marker — a race-plan
                  row like `km 5–12 @ 5:41–5:45` has no `~` and is refused)

Everything else — HR bands, race-km rows, prose — returns None. Refusal is
the safe state: the day keeps distance-only compliance scoring, and nothing
downstream guesses. The whole grammar is pinned by the live plan's own corpus
(tests/fixtures/plan_vals.json): every distinct `val` string either parses to
an exact shape or is explicitly refused, and a currency test fails when the
live plan introduces a string the fixture does not pin.

The engine's prior is NOT fed from here (decided 2026-07-30): the watch's own
workout definition owns that. This module serves the COMPLIANCE layer — the
coach's intent — and, on the Health Connect instance, is the only
prescription source that exists.
"""
from __future__ import annotations

import re

# A prescribed single pace (`@ 5:41`) widens to a symmetric band: the coach
# named a point, not a corridor, and holding a rep within ±5 s/km of a named
# point is compliance by any honest reading.
SINGLE_PACE_BAND_S = 5

# `4×1 km @ 5:25–5:35` / `3×400 m @ 5:41` / `4×20 s` / `6×3 min` — the rep
# mark is × or x; the range dash – or -. The pace clause is optional and must
# NOT carry the steady marker `~`.
_REPS_RE = re.compile(
    r"(\d+)\s*[×x]\s*(\d+(?:\.\d+)?)\s*(km|m|min|s)\b"
    r"(?:[^@]*@\s*(\d):(\d{2})(?:\s*[–-]\s*(\d):(\d{2}))?)?")

# `16 km easy @ ~6:10` — the `~` is load-bearing: it is what separates a
# steady TARGET from a race-plan split (`km 1–4 @ 5:50`), which is refused.
_STEADY_RE = re.compile(r"@\s*~\s*(\d):(\d{2})\b")

_ZONE_RE = re.compile(r"\bZ(\d)\b")


def _pace_s(m_min: str, m_sec: str) -> int:
    return int(m_min) * 60 + int(m_sec)


def _parse_reps(val: str) -> dict | None:
    m = _REPS_RE.search(val)
    if not m:
        return None
    count = int(m.group(1))
    size = float(m.group(2))
    unit = m.group(3)
    out: dict = {"kind": "reps", "count": count, "paceBandS": None,
                 "zone": None, "text": val}
    if unit == "km":
        out["repDistM"] = int(round(size * 1000))
    elif unit == "m":
        out["repDistM"] = int(round(size))
    elif unit == "min":
        out["repDurS"] = int(round(size * 60))
    else:  # "s"
        out["repDurS"] = int(round(size))
    if m.group(4):
        lo = _pace_s(m.group(4), m.group(5))
        if m.group(6):
            hi = _pace_s(m.group(6), m.group(7))
        else:
            lo, hi = lo - SINGLE_PACE_BAND_S, lo + SINGLE_PACE_BAND_S
        out["paceBandS"] = [min(lo, hi), max(lo, hi)]
    zm = _ZONE_RE.search(val)
    if zm:
        out["zone"] = int(zm.group(1))
    return out


def _parse_steady(val: str) -> dict | None:
    m = _STEADY_RE.search(val)
    if not m:
        return None
    return {"kind": "steady", "paceS": _pace_s(m.group(1), m.group(2)),
            "text": val}


def prescription_for_day(segments: list | None) -> dict | None:
    """At most ONE prescription per planned day (design D1): segments are
    scanned in order and the first rep set wins — the plan never prescribes
    two sets in one day, and the embedded `3 km easy · 3×400 m @ 5:41 inside`
    form yields its rep set, not its warm-up. With no rep set anywhere, the
    first steady target wins. Nothing parseable → None, and the caller must
    treat that as "the coach prescribed nothing this grammar can read"."""
    if not segments:
        return None
    vals = [s.get("val") or "" for s in segments if isinstance(s, dict)]
    for val in vals:
        reps = _parse_reps(val)
        if reps:
            return reps
    for val in vals:
        steady = _parse_steady(val)
        if steady:
            return steady
    return None


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
