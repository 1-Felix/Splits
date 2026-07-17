#!/usr/bin/env python3
"""ingest_builder.py — build the telemetry half of the SPLITS data contract for an
INGEST-FED instance (a runner with no Garmin; runs arrive via POST /api/ingest and
are banked in ingested-runs.json). Produces the same `garmin-data.js` the Garmin
sync would, but only the "Slim + HR zones" field set (design D3/D7).

  ingested-runs.json  → THIS SCRIPT → garmin-data.js       (telemetry)
                                    → activity-archive.db  (archive — same schema
                                      as the Garmin pipeline's, own volume)
  plan-data.js        ← the coach (race / weekPlan / coach — untouched)
  running-data.js     → merges both into `athleteData`

Derived fields reuse the pipeline's formulas verbatim so a non-Garmin instance is
consistent with a Garmin one:
  • CTL/ATL  — daily TSS → EWMA(42)/EWMA(7)      (sync_garmin.compute_fitness_fatigue)
  • HR zones — bounds = [.50 .60 .70 .80 .90 1.00]×maxHR (sync_garmin.fetch_hr_zones_this_week)
  • Riegel   — T2 = T1 × (D2/D1)^1.06            (insight_metrics.RIEGEL_EXPONENT)

Explicitly OMITTED (design D7 — not emitted, not empty): profile.vo2maxCurrent,
history.vo2max, readiness, history.sleep. Health Connect gives no route/cadence.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path

import activity_archive
import insight_metrics

# Windows consoles default to cp1252, which can't encode the ✓ glyph below
# (mirrors sync_garmin.py). Without this the build's success print raises.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

RIEGEL_EXPONENT = 1.06            # mirror insight_metrics
HALF_KM = 21.0975
ZONE_FRACTIONS = (0.50, 0.60, 0.70, 0.80, 0.90, 1.00)
ZONE_LABELS = ["Recovery", "Endurance", "Tempo", "Threshold", "VO2 max"]
SAMPLE_GAP_CAP_S = 30            # a gap between HR samples longer than this is a pause
MOVING_MPS_MIN = 1.7             # slower than ≈9:48/km = a standing/walking pause (D10)
WEEKS = 26
RECENT = 6
HEATMAP_DAYS = 365

_TYPE_LABELS = {"running": "Run", "treadmill_running": "Treadmill Run",
                "trail_running": "Trail Run", "track_running": "Track Run"}


# ── small helpers ─────────────────────────────────────────────────────────────
def _run_date(run: dict) -> dt.date:
    return dt.date.fromisoformat(run["startTimeLocal"][:10])


def _pace(distance_m: float, duration_s: float) -> int:
    return round(duration_s / (distance_m / 1000.0))


def _fmt_hms(sec: float) -> str:
    sec = round(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _type_label(sport: str) -> str:
    sport = sport.lower()
    return _TYPE_LABELS.get(sport, sport.replace("_", " ").title())


def observed_max_hr(runs: list[dict]):
    """Highest per-run max HR across the banked set (design D9) — real evidence
    for zone bounds and load intensity, replacing the 220−age guess."""
    vals = [r.get("maxHr") for r in runs if isinstance(r.get("maxHr"), (int, float))]
    return max(vals) if vals else None


def recent_resting_hr(rhr_days: dict | None):
    """Median of the last ≤7 banked daily resting-HR records (design D12) —
    stable against a single odd night."""
    if not rhr_days:
        return None
    vals = sorted(bpm for _, bpm in sorted(rhr_days.items())[-7:]
                  if isinstance(bpm, (int, float)))
    if not vals:
        return None
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2


def _zone_bounds(max_hr: int, rhr=None) -> list[int]:
    # Karvonen HR-reserve bounds when resting HR is known (design D12 — the
    # honest model for a beginner); plain %max otherwise.
    if rhr and 0 < rhr < max_hr:
        return [round(rhr + f * (max_hr - rhr)) for f in ZONE_FRACTIONS]
    return [round(max_hr * f) for f in ZONE_FRACTIONS]


def _zone_of(bpm: float, bounds: list[int]) -> int:
    # zone 1..5; bounds[1:5] are the 60/70/80/90% cut points
    z = 1 + sum(1 for c in bounds[1:5] if bpm >= c)
    return max(1, min(5, z))


# ── per-run derivations from the sample series (design D10/D11) ──────────────
def _sorted_samples(run: dict, key: str) -> list[dict]:
    return sorted(run.get(key) or [], key=lambda s: s["tSec"])


def moving_effort(run: dict):
    """(moving_s, moving_km) with standing/walking pauses stripped from BOTH time
    and distance via the speed series (design D10 — elapsed pace biases a
    walk-break beginner slow). None when there is no usable series."""
    samples = _sorted_samples(run, "speedSamples")
    if len(samples) < 2:
        return None
    t = dist = 0.0
    for i in range(len(samples) - 1):
        gap = samples[i + 1]["tSec"] - samples[i]["tSec"]
        if gap <= 0:
            continue
        gap = min(gap, SAMPLE_GAP_CAP_S)
        mps = samples[i]["mps"]
        if mps >= MOVING_MPS_MIN:
            t += gap
            dist += mps * gap
    return (t, dist / 1000.0) if t > 0 and dist > 0 else None


def _effort(run: dict):
    """(duration_s, km) for all pace math — moving when derivable, elapsed otherwise."""
    return moving_effort(run) or (run["durationS"], run["distanceM"] / 1000.0)


def run_splits(run: dict) -> list[dict]:
    """Per-km splits integrated from the speed series (design D11 — the app's
    namesake, independent of ExerciseLap which Samsung doesn't write). Mirrors
    the Garmin distiller's binning: per-km average speed → pace, per-km average
    HR, and a trailing sliver (<600 m) dropped."""
    samples = _sorted_samples(run, "speedSamples")
    if len(samples) < 2:
        return []
    hrs = _sorted_samples(run, "hrSamples")
    cum = max_dist = 0.0
    spd: dict[int, list] = {}
    span: dict[int, list] = {}
    for i in range(len(samples) - 1):
        gap = samples[i + 1]["tSec"] - samples[i]["tSec"]
        if gap <= 0:
            continue
        gap = min(gap, SAMPLE_GAP_CAP_S)
        km_idx = int(cum // 1000)
        mps = samples[i]["mps"]
        if mps > 0:
            spd.setdefault(km_idx, []).append(mps)
        sp = span.setdefault(km_idx, [samples[i]["tSec"], samples[i]["tSec"]])
        sp[1] = samples[i]["tSec"] + gap
        cum += mps * gap
        max_dist = max(max_dist, cum)
    out = []
    for km in sorted(spd):
        avg_spd = sum(spd[km]) / len(spd[km])
        lo, hi = span[km]
        in_hr = [h["bpm"] for h in hrs if lo <= h["tSec"] < hi]
        out.append({"km": km + 1,
                    "pace": int(round(1000 / avg_spd)) if avg_spd else 0,
                    "hr": int(round(sum(in_hr) / len(in_hr))) if in_hr else 0})
    if len(out) > 1 and max_dist - sorted(spd)[-1] * 1000 < 600:
        out = out[:-1]
    return out


def _split_shape(splits: list[dict]) -> str:
    # mirrors sync_garmin._split_shape so both pipelines agree on the verdict
    paces = [s["pace"] for s in splits if s.get("pace")]
    if len(paces) < 3:
        return "even"
    third = max(1, len(paces) // 3)
    first = sum(paces[:third]) / third
    last = sum(paces[-third:]) / third
    if first <= 0:
        return "even"
    delta = (last - first) / first
    return "positive" if delta > 0.04 else "negative" if delta < -0.04 else "even"


def _downsample(series: list, n: int = 30) -> list:
    # mirrors sync_garmin._downsample
    series = [v for v in series if v is not None]
    if len(series) <= n:
        return series
    step = len(series) / n
    result = [series[int(i * step)] for i in range(n)]
    result[-1] = series[-1]
    return result


def _hr_drift(hr: list) -> int:
    # mirrors sync_garmin._hr_drift
    hr = [v for v in hr if v is not None]
    if len(hr) < 4:
        return 0
    half = len(hr) // 2
    return int(round(sum(hr[half:]) / (len(hr) - half) - sum(hr[:half]) / half))


def _zone_seconds(hr_samples: list[dict], bounds: list[int]) -> list[float]:
    secs = [0.0] * 5
    for i in range(len(hr_samples) - 1):
        gap = hr_samples[i + 1]["tSec"] - hr_samples[i]["tSec"]
        if gap <= 0:
            continue
        secs[_zone_of(hr_samples[i]["bpm"], bounds) - 1] += min(gap, SAMPLE_GAP_CAP_S)
    return secs


def run_detail(run: dict, max_hr: int, rhr=None):
    """The recent-run drill-down `detail`, shaped exactly like the Garmin
    distiller's contract (splits / hrSeries / driftBpm / zoneMin / splitShape;
    tempC / te / load stay null — Health Connect doesn't carry them). Only runs
    with a speed series get one — without it there are no splits to show."""
    if len(run.get("speedSamples") or []) < 2:
        return None
    splits = run_splits(run)
    hr_vals = [s["bpm"] for s in _sorted_samples(run, "hrSamples")]
    zone_secs = _zone_seconds(_sorted_samples(run, "hrSamples"), _zone_bounds(max_hr, rhr))
    elev = run.get("elevationGainM")
    return {
        "splits": splits,
        "hrSeries": [int(round(v)) for v in _downsample(hr_vals)],
        "driftBpm": _hr_drift(hr_vals),
        "zoneMin": [math.ceil(s / 60) for s in zone_secs],
        "tempC": None,
        "te": None,
        "load": None,
        "elevGain": round(elev) if elev is not None else None,
        "splitShape": _split_shape(splits),
    }


def _cadence(run: dict):
    """steps ÷ moving minutes (design; stays null when the provider — Samsung —
    doesn't write steps)."""
    steps = run.get("steps")
    if not isinstance(steps, (int, float)) or steps <= 0:
        return None
    t, _ = _effort(run)
    return round(steps / (t / 60.0)) if t > 0 else None


# ── contract sections ─────────────────────────────────────────────────────────
def recent_runs(runs: list[dict], max_hr: int, rhr=None, n: int = RECENT) -> list[dict]:
    ordered = sorted(runs, key=lambda r: r["startTimeLocal"], reverse=True)[:n]
    out = []
    for r in ordered:
        avg = r.get("avgHr")
        t, km_eff = _effort(r)
        row = {
            "date": r["startTimeLocal"][:10],
            "type": _type_label(r.get("sportType", "running")),
            "km": round(r["distanceM"] / 1000.0, 2),
            "time": _fmt_hms(r["durationS"]),
            "pace": round(t / km_eff),
            "hr": round(avg) if avg else None,
            "cad": _cadence(r),
        }
        det = run_detail(r, max_hr, rhr)
        if det:
            row["detail"] = det
        out.append(row)
    return out


def weekly_volume(runs: list[dict], today: dt.date, weeks: int = WEEKS):
    monday = today - dt.timedelta(days=today.weekday())
    km = [0.0] * weeks
    cnt = [0] * weeks
    for r in runs:
        d = _run_date(r)
        rmon = d - dt.timedelta(days=d.weekday())
        idx = weeks - 1 - (monday - rmon).days // 7
        if 0 <= idx < weeks:
            km[idx] += r["distanceM"] / 1000.0
            cnt[idx] += 1
    return [round(v, 1) for v in km], cnt


def fitness_fatigue(runs: list[dict], max_hr: int, today: dt.date, weeks: int = WEEKS):
    """Daily TSS → EWMA(42) CTL and EWMA(7) ATL, sampled weekly — mirrors
    sync_garmin.compute_fitness_fatigue so both instances read the same scale."""
    start = today - dt.timedelta(days=weeks * 7 + 42)
    tss: dict[dt.date, float] = {}
    for r in runs:
        d = _run_date(r)
        if d < start:
            continue
        dur_hr = r["durationS"] / 3600.0
        avg = r.get("avgHr")
        intensity = max(0.4, min(1.05, avg / max_hr)) if (avg and max_hr) else 0.70
        tss[d] = tss.get(d, 0.0) + dur_hr * intensity * intensity * 100

    ctl = atl = 0.0
    ctl_at: dict[dt.date, float] = {}
    atl_at: dict[dt.date, float] = {}
    day = start
    while day <= today:
        t = tss.get(day, 0.0)
        ctl += (t - ctl) / 42
        atl += (t - atl) / 7
        ctl_at[day], atl_at[day] = ctl, atl
        day += dt.timedelta(days=1)

    monday = today - dt.timedelta(days=today.weekday())
    ctl_w, atl_w = [], []
    for i in range(weeks):
        end = min(monday - dt.timedelta(weeks=(weeks - 1 - i)) + dt.timedelta(days=6), today)
        ctl_w.append(round(ctl_at.get(end, ctl), 1))
        atl_w.append(round(atl_at.get(end, atl), 1))
    return ctl_w, atl_w


def hr_zones_this_week(runs: list[dict], max_hr: int, today: dt.date, rhr=None) -> list[dict]:
    """Minutes-in-zone this week, binned from each run's HR samples against
    maxHR-derived bounds (design D5 — zone policy lives here, not in the app)."""
    monday = today - dt.timedelta(days=today.weekday())
    bounds = _zone_bounds(max_hr, rhr)
    secs = [0.0] * 5
    for r in runs:
        if _run_date(r) < monday:
            continue
        rs = _zone_seconds(_sorted_samples(r, "hrSamples"), bounds)
        secs = [a + b for a, b in zip(secs, rs)]
    return [
        {"z": z + 1, "label": ZONE_LABELS[z], "min": int(round(secs[z] / 60)),
         "lo": bounds[z], "hi": bounds[z + 1]}
        for z in range(5)
    ]


def monthly_pace(runs: list[dict]):
    """Aggregate pace per calendar month (total time / total distance), oldest→
    newest. The array is DENSE from the first to the last active month — a gap
    month emits None rather than being dropped, since the chart labels months by
    position from the start month (task 10.2). Returns (start_month, paceSecPerKm,
    cadenceSpm) — cadence is all-None because Health Connect carries no cadence
    from Samsung."""
    by_month: dict[str, list] = {}
    for r in runs:
        key = r["startTimeLocal"][:7]
        acc = by_month.setdefault(key, [0.0, 0.0, []])
        t, km = _effort(r)                       # moving effort when derivable (D10)
        acc[0] += t
        acc[1] += km
        cad = _cadence(r)
        if cad is not None:
            acc[2].append(cad)
    if not by_month:
        return None, [], []
    months = sorted(by_month)
    y, m = map(int, months[0].split("-"))
    pace: list[int | None] = []
    cads: list[int | None] = []
    key = months[0]
    while True:
        acc = by_month.get(key)
        pace.append(round(acc[0] / acc[1]) if acc else None)
        cads.append(round(sum(acc[2]) / len(acc[2])) if acc and acc[2] else None)
        if key == months[-1]:
            break
        m += 1
        if m > 12:
            y, m = y + 1, 1
        key = f"{y:04d}-{m:02d}"
    return months[0], pace, cads


def energy_this_week(runs: list[dict], today: dt.date):
    """This week's burned kcal (totalKcal preferred, activeKcal as fallback) for
    the energy tile (design D13). None when NO banked run carries calories at
    all — the key is then omitted and the tile hides (one-image degradation)."""
    def kcal(r):
        v = r.get("totalKcal")
        return v if isinstance(v, (int, float)) else (
            r.get("activeKcal") if isinstance(r.get("activeKcal"), (int, float)) else None)
    if not any(kcal(r) is not None for r in runs):
        return None
    monday = today - dt.timedelta(days=today.weekday())
    return {"weekKcal": round(sum(kcal(r) or 0 for r in runs if _run_date(r) >= monday))}


def rhr_trend(rhr_days: dict | None, today: dt.date, window_days: int = 90):
    """Daily resting-HR series over the trailing window, oldest→newest (design
    D12 — a falling RHR is a beginner's clearest fitness signal). None when
    nothing is banked — the key is then omitted."""
    if not rhr_days:
        return None
    start = (today - dt.timedelta(days=window_days)).isoformat()
    days = [{"date": d, "bpm": bpm} for d, bpm in sorted(rhr_days.items())
            if d >= start and isinstance(bpm, (int, float))]
    return days or None


def heatmap(runs: list[dict], today: dt.date, days: int = HEATMAP_DAYS) -> list[float]:
    hm = [0.0] * days
    for r in runs:
        idx = days - 1 - (today - _run_date(r)).days
        if 0 <= idx < days:
            hm[idx] += r["distanceM"] / 1000.0
    return [round(v, 2) for v in hm]


def predictions(runs: list[dict], plan_goal: str | None) -> dict:
    """Riegel projections from the best recent effort (fastest run ≥ 2 km),
    anchored on the MOVING effort when a speed series exists (design D10)."""
    eligible = [r for r in runs if r["distanceM"] >= 2000]
    if not eligible:
        return {"fiveK": None, "tenK": None, "halfNow": None, "halfGoal": plan_goal, "trend": None}
    anchor = min(eligible, key=lambda r: (lambda e: e[0] / e[1])(_effort(r)))
    t1, d1 = _effort(anchor)
    riegel = lambda d2: t1 * (d2 / d1) ** RIEGEL_EXPONENT  # noqa: E731
    return {
        "fiveK": _fmt_hms(riegel(5)),
        "tenK": _fmt_hms(riegel(10)),
        "halfNow": _fmt_hms(riegel(HALF_KM)),
        "halfGoal": plan_goal,
        "trend": None,
    }


# ── assembly ──────────────────────────────────────────────────────────────────
def _usable(run) -> bool:
    """One poisoned banked row (calendar-invalid date, zero distance, non-object)
    must never wedge every future rebuild — skip it, keep the rest (task 10.1)."""
    try:
        _run_date(run)
        return run["durationS"] > 0 and run["distanceM"] > 0
    except Exception:  # noqa: BLE001
        return False


def _calibration(runs: list[dict], profile: dict, rhr_days: dict | None = None):
    """(max_hr, rhr) shared by the telemetry build and the archive pass — the
    zone bounds inside a run's distilled detail must come out identical on both
    surfaces (design D6), so the calibration lives in exactly one place.

    maxHR = the best evidence available (design D9): the highest of the
    explicit profile setting and the observed per-run max (an observation is
    a lower bound on the true max); 220−age only when neither exists."""
    explicit = int(profile["maxHR"]) if profile.get("maxHR") else None
    observed = observed_max_hr(runs)
    cands = [v for v in (explicit, observed) if v]
    max_hr = int(max(cands)) if cands else (220 - int(profile.get("age", 30)))
    return max_hr, recent_resting_hr(rhr_days)


def build_athlete_data(runs: list[dict], profile: dict, today: dt.date,
                       plan_goal: str | None = None,
                       rhr_days: dict | None = None) -> dict:
    runs = [r for r in runs if _usable(r)]
    max_hr, rhr = _calibration(runs, profile, rhr_days)
    week_km, week_runs = weekly_volume(runs, today)
    ctl, atl = fitness_fatigue(runs, max_hr, today)
    start_month, pace, cad = monthly_pace(runs)

    prof = {"name": profile.get("name", "Athlete"),
            "age": int(profile["age"]) if profile.get("age") is not None else None,
            "maxHR": max_hr}
    if prof["age"] is None:
        del prof["age"]
    if rhr is not None:
        prof["restingHR"] = round(rhr)

    history = {                                  # NO vo2max, NO sleep (D7)
        "vo2maxStartMonth": start_month,         # kept: anchors the pace/cadence x-axis
        "paceSecPerKm": pace,
        "cadenceSpm": cad,
        "weeklyKm": week_km,
        "weeklyRuns": week_runs,
        "ctl": ctl,
        "atl": atl,
    }
    trend = rhr_trend(rhr_days, today)
    if trend:
        history["restingHr"] = trend             # D12 — omitted entirely when unknown

    data = {
        "profile": prof,                         # NO vo2maxCurrent (D7)
        "today": today.isoformat(),
        "recentRuns": recent_runs(runs, max_hr, rhr),
        "hrZones": hr_zones_this_week(runs, max_hr, today, rhr),
        "predictions": predictions(runs, plan_goal),
        "history": history,
        "heatmapKm": heatmap(runs, today),       # NO readiness block (D7)
    }
    energy = energy_this_week(runs, today)
    if energy:
        data["energy"] = energy                  # D13 — omitted entirely when unknown
    return data


# ── the archive pass (add-ingest-archive design D1–D8) ───────────────────────
# Every banked run additionally lands in activity-archive.db — the SAME schema
# the Garmin pipeline writes (activity_archive owns it), on this instance's own
# volume. The db is a disposable derived cache: delete it and the next build
# fully regenerates it from ingested-runs.json, with identical ids.
#
# FOLLOW-UP (deliberately out of scope, add-ingest-archive design non-goals):
# plan_snapshots/plan_compliance rows — the run page's planned-vs-actual chip
# stays empty on ingest instances until a pass here banks snapshots and scores
# weeks the way sync_garmin does via plan_compliance.py. Worth its own change.

# Bump when synth_streams or the distilled-detail derivation changes shape —
# the marker in archive_meta makes the next build recompute every run's
# derived artifacts (mirrors insight_metrics.METRICS_VERSION for metrics rows).
INGEST_DISTILL_VERSION = 1
_DISTILL_MARKER = "ingest_distill_version"


def derive_activity_id(session_uid: str, salt: int = 0) -> int:
    """Stable numeric archive id for a Health Connect session UID (design D3):
    first 12 hex chars of sha256 → 48-bit int — stateless, deterministic, and
    JS-safe (< 2^53; the API serializes ids into JSON and /run/:id parses \\d+).
    `salt` is the collision escape hatch: salt N hashes `uid#N` instead."""
    key = session_uid if salt == 0 else f"{session_uid}#{salt}"
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:12], 16)


def _resolve_activity_id(conn, session_uid: str) -> int:
    """The id a run may occupy: its derived id, unless another run's row already
    sits there (the stored summary_json embeds the owner's sessionUid, so a
    collision is observable, never silent) — then the deterministic salted
    rehash, with a loud warning. Runs are processed in start-time order, so a
    rebuild resolves collisions identically and ids stay stable."""
    salt = 0
    while True:
        aid = derive_activity_id(session_uid, salt)
        row = conn.execute("SELECT summary_json FROM activities WHERE activity_id = ?",
                           (aid,)).fetchone()
        if row is None:
            return aid
        try:
            stored_uid = (json.loads(row[0]) or {}).get("sessionUid")
        except (json.JSONDecodeError, AttributeError):
            stored_uid = None
        if stored_uid == session_uid:
            return aid
        salt += 1
        print(f"  ! archive id collision: {session_uid!r} hashes onto row {aid} "
              f"(owned by {stored_uid!r}) — re-deriving with salt #{salt}",
              file=sys.stderr, flush=True)


def synth_streams(run: dict):
    """detail_streams_json in the archive's columnar contract, synthesized from
    the banked samples (design D5): `t` = the union of HR/speed sample times,
    `hr` / `v` aligned to it with nulls where a metric has no sample at that
    instant, `d` = cumulative integration of the speed series (pause-capped like
    every other integration in this builder) normalized so its final value
    equals the banked distance. Metrics the source does not supply (cad, elev,
    gap, pwr, lat/lon, pc) are OMITTED keys — the run page's existing
    absent-metric degradation applies. None without a usable speed series —
    there is no honest distance axis to chart."""
    spds = _sorted_samples(run, "speedSamples")
    if len(spds) < 2:
        return None
    hrs = _sorted_samples(run, "hrSamples")
    v_at = {s["tSec"]: s["mps"] for s in spds}
    hr_at = {s["tSec"]: s["bpm"] for s in hrs}
    axis = sorted(set(v_at) | set(hr_at))

    # cumulative distance: each interval weighs the last seen speed, gaps
    # capped so a watch pause never fabricates distance; then scaled so the
    # final value equals the banked total (the device's own measurement).
    d_raw = [0.0]
    cum = 0.0
    last_v = v_at.get(axis[0])
    for i in range(1, len(axis)):
        gap = min(axis[i] - axis[i - 1], SAMPLE_GAP_CAP_S)
        if last_v and gap > 0:
            cum += last_v * gap
        d_raw.append(cum)
        if axis[i] in v_at:
            last_v = v_at[axis[i]]
    scale = run["distanceM"] / cum if cum > 0 else 0.0

    out = {"t": [int(round(t)) for t in axis],
           "d": [int(round(v * scale)) for v in d_raw],
           "v": [round(v_at[t], 2) if t in v_at else None for t in axis]}
    if hrs:
        out["hr"] = [int(round(hr_at[t])) if t in hr_at else None for t in axis]
    return out


def _metric_samples(streams: dict) -> list[tuple]:
    """The insight-metrics samples dict — (elapsed_s, cumulative_m, hr, cadence,
    speed_mps) tuples, exactly read_stream's contract — built from the SAME
    synthesized columns the archive serves, so metrics and charts can never
    disagree. Cadence is always None (Samsung writes no per-sample cadence):
    the refpace pools stay empty and refpace_cadence_spm stays NULL — pinned
    by the samples-dict parity test."""
    hr = streams.get("hr") or [None] * len(streams["t"])
    return [(float(t), float(d), h, None, v)
            for t, d, h, v in zip(streams["t"], streams["d"], hr, streams["v"])]


def _upsert_archive_row(conn, aid: int, run: dict) -> None:
    """One archive row per banked run: promoted columns mapped from the banked
    payload, summary_json = that payload VERBATIM (design D4 — the banked run
    IS this pipeline's raw source payload; its sessionUid keeps the id mapping
    recoverable). name / avg_cadence / elevation_gain_m / detail_json stay NULL
    — honest absence, never fabrication. A row whose content is unchanged is
    left untouched so updated_at only moves when something did (design D8)."""
    summary = json.dumps(run, ensure_ascii=False)
    avg_hr = run.get("avgHr")
    max_hr = run.get("maxHr")
    vals = (run["startTimeLocal"], run.get("sportType", "running").lower(),
            run["distanceM"], run["durationS"],
            int(round(avg_hr)) if avg_hr else None,
            int(round(max_hr)) if max_hr else None,
            summary)
    prior = conn.execute(
        """SELECT start_time_local, type_key, distance_m, duration_s,
                  avg_hr, max_hr, summary_json
           FROM activities WHERE activity_id = ?""", (aid,)).fetchone()
    if prior is not None and tuple(prior) == vals:
        return
    now = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    conn.execute(activity_archive._UPSERT_SQL, (
        aid, vals[0], vals[1], None, vals[2], vals[3], vals[4], vals[5],
        None, None, summary, now, now))
    conn.commit()


def build_archive(data_dir: Path, runs: list[dict], profile: dict,
                  rhr_days: dict | None = None) -> int:
    """The archive build pass: upsert every usable banked run into
    activity-archive.db and bring its derived artifacts (columnar streams,
    distilled detail, run_metrics) to the current versions. Write-once in the
    steady state — derived artifacts are recomputed only when missing or when
    a version marker moved (design D8). Returns the number of archived runs."""
    runs = sorted((r for r in runs if _usable(r) and r.get("sessionUid")),
                  key=lambda r: r["startTimeLocal"])
    if not runs:
        # nothing banked yet — leave the instance unprovisioned (no db file)
        # rather than creating an empty archive that would flip /api/status's
        # `archive` flag and reveal empty archive chrome on a fresh instance
        return 0
    max_hr, rhr = _calibration(runs, profile, rhr_days)
    conn = activity_archive.open_archive(Path(data_dir))
    try:
        stale = (activity_archive.get_meta(conn, _DISTILL_MARKER)
                 != str(INGEST_DISTILL_VERSION))
        for run in runs:
            aid = _resolve_activity_id(conn, run["sessionUid"])
            _upsert_archive_row(conn, aid, run)
            missing = conn.execute(
                """SELECT detail_streams_json IS NULL, detail_distilled_json IS NULL
                   FROM activities WHERE activity_id = ?""", (aid,)).fetchone()
            streams = None
            if stale or missing[0]:
                streams = synth_streams(run)
                if streams:
                    activity_archive.write_streams(conn, aid, streams)
            if stale or missing[1]:
                det = run_detail(run, max_hr, rhr)
                if det:
                    activity_archive.write_distilled(conn, aid, det)
            has_metrics = conn.execute(
                "SELECT 1 FROM run_metrics WHERE activity_id = ? AND metrics_version = ?",
                (aid, insight_metrics.METRICS_VERSION)).fetchone()
            if not has_metrics:
                mrow = {
                    "activity_id": aid,
                    "metrics_version": insight_metrics.METRICS_VERSION,
                    "start_time_local": run["startTimeLocal"],
                    "is_treadmill": 1 if run.get("sportType", "").lower()
                                    == "treadmill_running" else 0,
                }
                streams = streams or synth_streams(run)
                if streams:
                    samples = _metric_samples(streams)
                    mrow.update(insight_metrics.best_efforts(samples))
                    mrow.update(insight_metrics.band_aggregates(samples))
                # a sample-less run banks an empty row — the absence is
                # deterministic, so recomputing it every build would be waste
                activity_archive.upsert_run_metrics(conn, mrow)
        if stale:
            activity_archive.set_meta(conn, _DISTILL_MARKER,
                                      str(INGEST_DISTILL_VERSION))
        return len(runs)
    finally:
        conn.close()


# ── file I/O (used by the ingest trigger and on boot) ────────────────────────
def _plan_goal(data_dir: Path) -> str | None:
    """Best-effort read of race.goalTime from plan-data.js for predictions.halfGoal.
    Tolerant regex — never parses JS, never fails the build."""
    try:
        text = (data_dir / "plan-data.js").read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"goalTime:\s*[\"']([^\"']+)[\"']", text)
    return m.group(1) if m else None


def build_garmin_data_js(data: dict) -> str:
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    stamp = dt.datetime.now().isoformat(timespec="seconds")
    return (
        "/* AUTO-GENERATED by ingest_builder.py — do not hand-edit. Telemetry only.\n"
        f" * Built: {stamp} from ingested-runs.json (Health Connect ingest).\n"
        " * The plan (race / weekPlan / coach) lives in plan-data.js and is never\n"
        " * touched here. running-data.js merges the two into `athleteData`.\n"
        " */\n"
        f"export const garminData = {payload};\n\n"
        "export default garminData;\n"
    )


def main() -> None:
    data_dir = Path(os.environ["SPLITS_DATA_DIR"]) if os.environ.get("SPLITS_DATA_DIR") else Path(__file__).parent
    store = data_dir / "ingested-runs.json"
    try:
        raw = json.loads(store.read_text(encoding="utf-8"))
        runs = list(raw.values()) if isinstance(raw, dict) else []
    except (OSError, json.JSONDecodeError):
        runs = []
    try:
        raw_rhr = json.loads((data_dir / "ingested-rhr.json").read_text(encoding="utf-8"))
        rhr_days = raw_rhr if isinstance(raw_rhr, dict) else None
    except (OSError, json.JSONDecodeError):
        rhr_days = None
    profile = {
        "name": os.environ.get("ATHLETE_NAME", "Athlete"),
        "age": os.environ.get("ATHLETE_AGE"),
        "maxHR": os.environ.get("ATHLETE_MAX_HR"),
    }
    profile = {k: v for k, v in profile.items() if v not in (None, "")}
    data = build_athlete_data(runs, profile, dt.date.today(), _plan_goal(data_dir),
                              rhr_days=rhr_days)
    tmp = data_dir / f".garmin-data.{os.getpid()}.tmp.js"
    tmp.write_text(build_garmin_data_js(data), encoding="utf-8")
    tmp.replace(data_dir / "garmin-data.js")
    print(f"✓ built garmin-data.js from {len(runs)} ingested run(s)", flush=True)
    try:
        n = build_archive(data_dir, runs, profile, rhr_days)
        print(f"✓ archived {n} run(s) → {activity_archive.DB_NAME}", flush=True)
    except Exception as e:  # noqa: BLE001 — the archive is a derived cache; a
        # failure here must never sink the telemetry build (task 3.7)
        print(f"  ! archive pass failed ({type(e).__name__}: {e}) — "
              f"telemetry build unaffected", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
