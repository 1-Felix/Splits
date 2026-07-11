#!/usr/bin/env python3
"""
insight_metrics.py — the deterministic metrics engine over the activity archive.

Two phases (openspec/changes/insight-metrics/design.md, D1):

  1. Per-run extraction (expensive, once per activity per METRICS_VERSION):
     parse the raw detail streams → best efforts + reference-band aggregates
     → one `run_metrics` row. A version bump self-heals: stale rows count as
     missing and are recomputed on the next sync.
  2. Series assembly (cheap, every sync): SQL over `run_metrics` +
     `race_predictions` → the `insights` block for garmin-data.js. Raises on
     any problem — the caller omits the block entirely, never emits a partial.

Everything here is deterministic and recomputable from the archive; no AI, no
network. Stdlib only (sqlite3 via activity_archive, json, math, datetime).

Changing ANY algorithm parameter below requires bumping METRICS_VERSION —
that is the whole recompute story.
"""

from __future__ import annotations

import datetime as dt
import sys

import activity_archive

# ──────────────────────────────────────────────────────────────────────────────
# algorithm parameters — all covered by METRICS_VERSION (design D2/D4)
# ──────────────────────────────────────────────────────────────────────────────
# v2 (chart-drill D3): per-run in-band display values become stored columns
# (refhr_pace_s_per_km, refpace_cadence_spm) — the bump self-heals every row.
METRICS_VERSION = 2

# Bands frozen after the task-3.1 density check against the real archive
# (2026-07-05, 162 runs): HR 125–145 yields ≥31 in-band min for every month
# since structured training began (2025-07); the design's pace default
# (5:30–6:00) was near race pace and gap-heavy in 13/21 trained months, so the
# pace band moved to 7:00–8:00 min/km — the bread-and-butter easy pace — which
# leaves only genuinely untrained months (≤2 runs) below threshold.
REF_HR_BAND = (125, 145)       # bpm, inclusive — the aerobic reference band
REF_PACE_BAND = (420, 480)     # sec/km, inclusive — 7:00–8:00 min/km
WARMUP_CUTOFF_S = 480          # first 8 min excluded from band pools (HR lag)
WALKING_FLOOR_MPS = 1.4        # samples slower than this are walking, not running
MAX_SAMPLE_GAP_S = 15          # a longer gap is a recording pause — weighs nothing
MIN_INBAND_MINUTES = 10        # months with less in-band time yield null points

# run_metrics column → target metres (mile is exact; half is 21.0975 km)
BEST_EFFORT_TARGETS = {
    "best_1k_s": 1000.0,
    "best_mile_s": 1609.344,
    "best_5k_s": 5000.0,
    "best_10k_s": 10000.0,
    "best_half_s": 21097.5,
}

RIEGEL_EXPONENT = 1.06         # half = t10k × (21.0975/10)^1.06 (design D6)
RIEGEL_WINDOW_DAYS = 84        # trailing ~12 weeks for the anchoring 10k effort
GOAL_HALF_S = 7199             # sub-2:00 — Sonthofen goal
TREND_WEEKS = 4                # recent Riegel points feeding predictions.trend
TREND_FLAT_S_PER_WK = 2.0      # |slope| below this reads as "flat"


def _warn(msg: str) -> None:
    print(f"  ! {msg}", file=sys.stderr, flush=True)


# ──────────────────────────────────────────────────────────────────────────────
# phase 1 — per-run extraction
# ──────────────────────────────────────────────────────────────────────────────
def read_stream(detail: dict) -> list[tuple]:
    """Monotonic (elapsed_s, cumulative_m, hr, cadence, speed_mps) samples from
    a raw get_activity_details payload.

    Elapsed comes from directTimestamp (GMT epoch ms; wall clock, so recording
    pauses show as jumps — exactly what elapsed-time efforts need) with
    sumElapsedDuration (seconds) as fallback. sumDistance is clamped
    non-decreasing; rows without elapsed or distance are dropped. Speed is
    grade-adjusted (directGradeAdjustedSpeed) falling back to directSpeed;
    hr / cadence / speed may be None within a sample.

    Cadence quirk: Garmin's stream directRunCadence is SINGLE-SIDE strides/min
    (~78) despite its descriptor claiming stepsPerMinute — exactly half the
    summary's averageRunningCadenceInStepsPerMinute (~157) on every archived
    run. It is doubled here so everything downstream speaks steps/min."""
    idx = {d.get("key"): d.get("metricsIndex")
           for d in (detail.get("metricDescriptors") or [])}
    i_ts, i_el = idx.get("directTimestamp"), idx.get("sumElapsedDuration")
    i_dist = idx.get("sumDistance")
    i_hr, i_cad = idx.get("directHeartRate"), idx.get("directRunCadence")
    i_gas, i_spd = idx.get("directGradeAdjustedSpeed"), idx.get("directSpeed")

    samples: list[tuple] = []
    t0 = None
    last_t = None
    last_d = 0.0
    for row in detail.get("activityDetailMetrics") or []:
        m = row.get("metrics") or []

        def at(i):
            return m[i] if i is not None and i < len(m) else None

        ts = at(i_ts)
        if ts is not None:
            if t0 is None:
                t0 = ts
            elapsed = (ts - t0) / 1000.0
        else:
            elapsed = at(i_el)
        d = at(i_dist)
        if elapsed is None or d is None:
            continue
        if last_t is not None and elapsed < last_t:
            continue                       # out-of-order sample — drop
        last_t = elapsed
        last_d = max(last_d, float(d))     # clamp non-decreasing
        speed = at(i_gas)
        if speed is None:
            speed = at(i_spd)
        cad = at(i_cad)
        samples.append((float(elapsed), last_d, at(i_hr),
                        cad * 2 if cad is not None else None, speed))
    return samples


def fastest_window_s(samples: list[tuple], target_m: float) -> float | None:
    """Minimum ELAPSED seconds over any contiguous window covering target_m,
    interpolating the window start at the exact distance (design D3). Two
    pointers, O(n). None when the run is shorter than the target."""
    pts = [(s[0], s[1]) for s in samples]
    if len(pts) < 2 or pts[-1][1] - pts[0][1] < target_m:
        return None
    best = None
    i = 0
    for j in range(len(pts)):
        t_j, d_j = pts[j]
        if d_j - pts[0][1] < target_m:
            continue
        # i → last sample at or before the exact window start (d_j − target);
        # in a flat stretch (pause) this lands on the LATEST equal-distance
        # sample, so a pause just before the window never counts against it.
        while i + 1 < j and pts[i + 1][1] <= d_j - target_m:
            i += 1
        d_start = d_j - target_m
        t_i, d_i = pts[i]
        t_n, d_n = pts[i + 1]
        t_start = t_i + (t_n - t_i) * (d_start - d_i) / (d_n - d_i) if d_n > d_i else t_n
        if best is None or t_j - t_start < best:
            best = t_j - t_start
    return round(best, 1) if best is not None else None


def best_efforts(samples: list[tuple]) -> dict:
    return {col: fastest_window_s(samples, target)
            for col, target in BEST_EFFORT_TARGETS.items()}


def band_aggregates(samples: list[tuple]) -> dict:
    """Time-weighted in-band sums (design D4). Each inter-sample interval is
    weighted by its duration and judged by its endpoint sample; warm-up,
    walking-pace, and recording-gap intervals contribute nothing. The sums are
    additive across runs, so monthly series are plain SQL SUMs.

    The per-run DISPLAY values (chart-drill D3) are the same sums' quotients —
    the run's own in-band pace and time-weighted in-band cadence — stored so
    the contribution panel can show them without anyone deriving downstream.
    NULL when the run has no in-band time, never zero: "no evidence" and
    "slow" must stay distinguishable."""
    refhr_time = refhr_dist = refpace_time = refpace_cxt = 0.0
    for k in range(1, len(samples)):
        t, _d, hr, cad, spd = samples[k]
        gap = t - samples[k - 1][0]
        if gap <= 0 or gap > MAX_SAMPLE_GAP_S:
            continue
        if t < WARMUP_CUTOFF_S:
            continue
        if spd is None or spd < WALKING_FLOOR_MPS:
            continue
        if hr is not None and REF_HR_BAND[0] <= hr <= REF_HR_BAND[1]:
            refhr_time += gap
            refhr_dist += spd * gap
        pace = 1000.0 / spd
        if cad and REF_PACE_BAND[0] <= pace <= REF_PACE_BAND[1]:
            refpace_time += gap
            refpace_cxt += cad * gap
    out = {
        "refhr_time_s": round(refhr_time, 1),
        "refhr_dist_m": round(refhr_dist, 1),
        "refpace_time_s": round(refpace_time, 1),
        "refpace_cadence_x_time": round(refpace_cxt, 1),
    }
    # display values from the STORED (rounded) sums, so a consumer can always
    # reproduce them from the row's own aggregate columns exactly
    out["refhr_pace_s_per_km"] = (
        round(out["refhr_time_s"] / (out["refhr_dist_m"] / 1000.0), 1)
        if out["refhr_time_s"] > 0 and out["refhr_dist_m"] > 0 else None)
    out["refpace_cadence_spm"] = (
        round(out["refpace_cadence_x_time"] / out["refpace_time_s"], 1)
        if out["refpace_time_s"] > 0 and out["refpace_cadence_x_time"] > 0 else None)
    return out


def extract_run_metrics(conn) -> int:
    """Compute + upsert run_metrics for every archived run missing a row at the
    current METRICS_VERSION (no cap — a full recompute is seconds for years of
    data). A per-run parse failure stores an empty row with a warning: the
    failure is deterministic, so retrying it every night would be waste."""
    pending = activity_archive.runs_missing_metrics(conn, METRICS_VERSION)
    for aid, start_local, type_key in pending:
        row = {
            "activity_id": aid,
            "metrics_version": METRICS_VERSION,
            "start_time_local": start_local,
            "is_treadmill": 1 if type_key == "treadmill_running" else 0,
        }
        try:
            samples = read_stream(activity_archive.detail_payload(conn, aid) or {})
            row.update(best_efforts(samples))
            row.update(band_aggregates(samples))
        except Exception as e:  # noqa: BLE001 — one bad stream must not sink the rest
            _warn(f"metrics extraction failed for {aid} "
                  f"({type(e).__name__}: {e}); storing empty row")
        activity_archive.upsert_run_metrics(conn, row)
    return len(pending)


# ──────────────────────────────────────────────────────────────────────────────
# phase 2 — series assembly (cheap SQL over run_metrics + race_predictions)
# ──────────────────────────────────────────────────────────────────────────────
# run_metrics column → contract key (bestEfforts) and feed label (recordsFeed)
EFFORT_KEYS = {"best_1k_s": "oneK", "best_mile_s": "mile", "best_5k_s": "fiveK",
               "best_10k_s": "tenK", "best_half_s": "half"}
FEED_LABELS = {"best_1k_s": "1k", "best_mile_s": "mile", "best_5k_s": "5k",
               "best_10k_s": "10k", "best_half_s": "half"}
RECORDS_FEED_LIMIT = 10


def _month_range(first: str, last: str) -> list[str]:
    """Continuous YYYY-MM keys from first to last inclusive — months without
    runs appear in the series as honest nulls, not silent omissions."""
    y, m = (int(x) for x in first.split("-"))
    out = []
    while f"{y:04d}-{m:02d}" <= last:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def monthly_series(conn, today: dt.date) -> tuple[list[dict], list[dict]]:
    """(efficiency, cadence) monthly lists per design D4/D9: plain SUMs over
    the per-run time-weighted aggregates, null below the in-band threshold."""
    rows = conn.execute(
        """SELECT substr(start_time_local, 1, 7) AS month,
                  SUM(refhr_time_s), SUM(refhr_dist_m),
                  SUM(refpace_time_s), SUM(refpace_cadence_x_time)
           FROM run_metrics WHERE metrics_version = ?
           GROUP BY month ORDER BY month""",
        (METRICS_VERSION,)).fetchall()
    if not rows:
        return [], []
    by_month = {r[0]: r for r in rows}
    efficiency, cadence = [], []
    for month in _month_range(rows[0][0], today.isoformat()[:7]):
        _, hr_t, hr_d, pc_t, pc_cxt = by_month.get(month) or (month, 0, 0, 0, 0)
        hr_t, hr_d, pc_t, pc_cxt = hr_t or 0, hr_d or 0, pc_t or 0, pc_cxt or 0
        hr_ok = hr_t >= MIN_INBAND_MINUTES * 60 and hr_d > 0
        pc_ok = pc_t >= MIN_INBAND_MINUTES * 60 and pc_cxt > 0
        efficiency.append({
            "month": month,
            "paceSecPerKm": round(hr_t / (hr_d / 1000.0)) if hr_ok else None,
            "inBandMin": round(hr_t / 60),
        })
        cadence.append({
            "month": month,
            "spm": round(pc_cxt / pc_t) if pc_ok else None,
            "inBandMin": round(pc_t / 60),
        })
    return efficiency, cadence


def best_effort_table(conn, since: str | None = None,
                      until: str | None = None) -> dict:
    """{oneK: {sec, date, activityId} | None, …} — outdoor only (records
    territory, design D5); `since`/`until` bound it to a window (last90d, a
    calendar year). activityId lets the records wall click through to the run
    the record fell in (progress-views design D4)."""
    out = {}
    for col, key in EFFORT_KEYS.items():
        row = conn.execute(
            f"""SELECT {col}, substr(start_time_local, 1, 10), activity_id
                FROM run_metrics
                WHERE metrics_version = ? AND is_treadmill = 0
                  AND {col} IS NOT NULL
                  AND start_time_local >= ? AND start_time_local < ?
                ORDER BY {col} ASC, start_time_local ASC LIMIT 1""",
            (METRICS_VERSION, since or "", until or "9999")).fetchone()
        out[key] = ({"sec": round(row[0]), "date": row[1], "activityId": row[2]}
                    if row else None)
    return out


def best_efforts_by_year(conn) -> dict:
    """{year: effort table} for every calendar year holding an outdoor run
    with metrics — the same outdoor-only records policy through the same
    table function, so the policy lives in exactly one place (progress-views
    design D4). Distances a year never covered are null, never extrapolated."""
    years = [r[0] for r in conn.execute(
        """SELECT DISTINCT substr(start_time_local, 1, 4) FROM run_metrics
           WHERE metrics_version = ? AND is_treadmill = 0
           ORDER BY 1""", (METRICS_VERSION,))]
    return {y: best_effort_table(conn, since=f"{y}-01-01",
                                 until=f"{int(y) + 1:04d}-01-01")
            for y in years}


def yoy_series(conn, today: dt.date) -> dict:
    """{year: [monthly aggregates]} over the archive's promoted columns
    (progress-views design D4): distance km, run count, and aggregate pace
    (total time over total distance) per calendar month. Months with no runs
    carry zero count/distance and a null pace; the current year carries only
    elapsed months. Volume is volume — treadmill runs count here (the
    outdoor-only policy is records territory)."""
    rows = conn.execute(
        f"""SELECT substr(a.start_time_local, 1, 4) AS y,
                   CAST(substr(a.start_time_local, 6, 2) AS INTEGER) AS m,
                   COUNT(*), SUM(a.distance_m), SUM(a.duration_s)
            FROM activities a
            WHERE {activity_archive._RUN_TYPE_SQL}
            GROUP BY y, m""").fetchall()
    by_month = {(y, m): (cnt, dist or 0.0, dur or 0.0)
                for y, m, cnt, dist, dur in rows}
    if not by_month:
        return {}
    out = {}
    for year in range(min(int(y) for y, _ in by_month), today.year + 1):
        months = []
        for m in range(1, (today.month if year == today.year else 12) + 1):
            cnt, dist, dur = by_month.get((f"{year:04d}", m), (0, 0.0, 0.0))
            months.append({
                "month": m,
                "km": round(dist / 1000.0, 1),
                "runs": cnt,
                "paceSecPerKm": round(dur / (dist / 1000.0)) if dist else None,
            })
        out[str(year)] = months
    return out


def records_feed(conn, limit: int = RECORDS_FEED_LIMIT) -> list[dict]:
    """Newest-first record events (design D5): an outdoor run whose best effort
    at a distance beats every EARLIER outdoor run's best at that distance. The
    first-ever effort at a distance is a baseline, not a fallen record."""
    events = []
    for col, label in FEED_LABELS.items():
        rows = conn.execute(
            f"""SELECT substr(start_time_local, 1, 10), {col},
                       MIN({col}) OVER (ORDER BY start_time_local, activity_id
                                        ROWS BETWEEN UNBOUNDED PRECEDING
                                        AND 1 PRECEDING)
                FROM run_metrics
                WHERE metrics_version = ? AND is_treadmill = 0
                  AND {col} IS NOT NULL
                ORDER BY start_time_local""",
            (METRICS_VERSION,)).fetchall()
        for date, val, prev_best in rows:
            if prev_best is not None and val < prev_best:
                events.append({"date": date, "distance": label,
                               "oldSec": round(prev_best), "newSec": round(val)})
    events.sort(key=lambda e: e["date"], reverse=True)
    return events[:limit]


def _week_end(d: dt.date) -> dt.date:
    return d + dt.timedelta(days=7 - d.isoweekday())  # the ISO week's Sunday


def weekly_trajectory(conn, today: dt.date) -> list[dict]:
    """Weekly Riegel-vs-Garmin series (design D6), from the first qualifying
    10k effort to the current week. No 10k in a week's trailing window ⇒ null
    — never substituted from a shorter distance. Each Riegel week carries the
    anchoring effort's `anchorId` so the dashboard can link the prediction to
    the run that demonstrated it (chart-drill D8); null weeks omit the key
    entirely, so pre-anchor consumers and data files stay untouched."""
    efforts = [(dt.date.fromisoformat(d), s, aid) for d, s, aid in conn.execute(
        """SELECT substr(start_time_local, 1, 10), best_10k_s, activity_id
           FROM run_metrics
           WHERE metrics_version = ? AND is_treadmill = 0
             AND best_10k_s IS NOT NULL
           ORDER BY start_time_local""", (METRICS_VERSION,))]
    if not efforts:
        return []
    preds = [(dt.date.fromisoformat(d), h) for d, h in conn.execute(
        "SELECT date, half_s FROM race_predictions WHERE half_s IS NOT NULL "
        "ORDER BY date")]

    out = []
    wk = _week_end(efforts[0][0])
    last = _week_end(today)
    factor = (21.0975 / 10.0) ** RIEGEL_EXPONENT
    while wk <= last:
        window_start = wk - dt.timedelta(days=RIEGEL_WINDOW_DAYS)
        # min on (seconds, activity_id): the fastest effort anchors; a dead
        # heat resolves deterministically to the lower activity id
        anchor = min(((s, aid) for d, s, aid in efforts
                      if window_start < d <= wk), default=None)
        garmin = None
        for d, h in preds:
            if d > wk:
                break
            garmin = h
        y, w, _ = wk.isocalendar()
        row = {"week": f"{y}-W{w:02d}",
               "riegelSec": round(anchor[0] * factor) if anchor else None,
               "garminSec": round(garmin) if garmin else None}
        if anchor:
            row["anchorId"] = anchor[1]
        out.append(row)
        wk += dt.timedelta(days=7)
    return out


def trend_verdict(weekly: list[dict]) -> str:
    """The predictions.trend verdict from the recent Riegel points: least-
    squares slope over the last TREND_WEEKS weeks → 'closing ≈8s/wk' /
    'opening ≈…' / 'flat'; empty when too few points to say anything."""
    pts = [(i, w["riegelSec"]) for i, w in enumerate(weekly[-TREND_WEEKS:])
           if w.get("riegelSec") is not None]
    if len(pts) < 3:
        return ""
    n = len(pts)
    mx = sum(x for x, _ in pts) / n
    my = sum(y for _, y in pts) / n
    denom = sum((x - mx) ** 2 for x, _ in pts)
    slope = sum((x - mx) * (y - my) for x, y in pts) / denom if denom else 0.0
    if abs(slope) < TREND_FLAT_S_PER_WK:
        return "flat"
    return f"{'closing' if slope < 0 else 'opening'} ≈{abs(round(slope))}s/wk"


def assemble_insights(conn, today: dt.date | None = None) -> dict:
    """The complete `insights` block per design D9, or an exception — the
    caller omits the block entirely rather than emitting a partial one."""
    today = today or dt.date.today()
    efficiency, cadence = monthly_series(conn, today)
    if not efficiency:
        raise ValueError("no run_metrics rows at the current METRICS_VERSION")
    return {
        "metricsVersion": METRICS_VERSION,
        "efficiency": {"refHrBand": list(REF_HR_BAND), "monthly": efficiency},
        "cadence": {"refPaceBand": list(REF_PACE_BAND), "monthly": cadence},
        "bestEfforts": {
            "allTime": best_effort_table(conn),
            "last90d": best_effort_table(
                conn, since=(today - dt.timedelta(days=90)).isoformat()),
            "byYear": best_efforts_by_year(conn),
        },
        "recordsFeed": records_feed(conn),
        "trajectory": {"goalSec": GOAL_HALF_S,
                       "weekly": weekly_trajectory(conn, today)},
        "yoy": yoy_series(conn, today),
    }


# ──────────────────────────────────────────────────────────────────────────────
# predictor banking + backfill (design D7)
# ──────────────────────────────────────────────────────────────────────────────
def _promote_prediction(doc: dict) -> dict:
    return {
        "time_5k_s": doc.get("time5K"),
        "time_10k_s": doc.get("time10K"),
        "half_s": doc.get("timeHalfMarathon"),
        "marathon_s": doc.get("timeMarathon"),
    }


def bank_prediction(conn, doc, today: dt.date | None = None) -> bool:
    """Upsert today's row from the predictor document the sync already fetched
    — zero extra API calls. Returns True when a row was banked."""
    if isinstance(doc, list):
        doc = doc[-1] if doc else None
    if not doc:
        return False
    date = doc.get("calendarDate") or (today or dt.date.today()).isoformat()
    activity_archive.upsert_race_prediction(
        conn, date, _promote_prediction(doc), doc, "sync")
    return True


def backfill_predictions(conn, client, earliest: str,
                         today: dt.date | None = None) -> int:
    """Daily predictor history back to `earliest` (the account's first
    activity), walked newest-first in ≤1-year windows — the endpoint's limit.
    Each window is individually fail-soft: if the unofficial history endpoint
    ever disappears, whatever it still returns is banked and bank-on-sync
    builds the line forward from today. Idempotent (plain upserts)."""
    today = today or dt.date.today()
    start = dt.date.fromisoformat(earliest[:10])
    banked = 0
    win_end = today
    while win_end >= start:
        win_start = max(start, win_end - dt.timedelta(days=364))
        try:
            docs = client.get_race_predictions(
                startdate=win_start.isoformat(), enddate=win_end.isoformat(),
                _type="daily") or []
        except Exception as e:  # noqa: BLE001 — degrade to bank-on-sync only
            _warn(f"prediction backfill {win_start} → {win_end} failed "
                  f"({type(e).__name__}: {e})")
            docs = []
        if isinstance(docs, dict):
            docs = [docs]
        for doc in docs:
            date = (doc or {}).get("calendarDate")
            if not date:
                continue
            activity_archive.upsert_race_prediction(
                conn, date, _promote_prediction(doc), doc, "backfill")
            banked += 1
        win_end = win_start - dt.timedelta(days=1)
    return banked
