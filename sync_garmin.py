#!/usr/bin/env python3
"""
sync_garmin.py — pulls training data from Garmin Connect and writes
`garmin-data.js` (the telemetry half of the SPLITS data contract).

  garmin-data.js  ← THIS SCRIPT (FROM GARMIN telemetry — overwritten each run)
  plan-data.js    ← the AI coach (race / weekPlan / coach — never touched here)
  running-data.js → merges both into `athleteData`, which the dashboard imports

See CLAUDE_CODE_HANDOFF.md for the full data contract (§3), metric→source map
(§2), and the formulas this script computes itself (§4: CTL/ATL, Riegel).

Quick start:
    pip install -r requirements.txt        # or: pip install garminconnect python-dotenv
    cp .env.example .env                    # add GARMIN_EMAIL / GARMIN_PASSWORD
    python sync_garmin.py                   # writes garmin-data.js, then validates

Auth notes:
  • First run does a full email/password login and caches tokens to
    GARMIN_TOKENSTORE (default ./.garmin_tokens); later runs reuse the cache.
  • If your account uses MFA, set GARMIN_MFA=<code> in .env (or run this script
    in an interactive terminal so it can prompt). Tokens are valid ~1 year, so
    you only pay the MFA cost once.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sys
import time
from pathlib import Path
from statistics import mean

from dotenv import load_dotenv
from garminconnect import Garmin

import activity_archive
import coach_briefing
import insight_metrics
import plan_compliance

# Windows consoles default to cp1252, which can't encode the ✓/… glyphs below.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

HERE = Path(__file__).parent

# Where personal data lives. The container sets SPLITS_DATA_DIR=/data (the
# mounted volume); when unset, it falls back to the project dir so a plain
# `python sync_garmin.py` works unchanged. Mirrors the resolution in serve.mjs.
# (No /data auto-detect — that misfires on Windows, where "/data" is C:\data.)
DATA_DIR = Path(os.environ["SPLITS_DATA_DIR"]) if os.environ.get("SPLITS_DATA_DIR") else HERE
DATA_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_PATH = DATA_DIR / "garmin-data.js"
CACHE_DIR = DATA_DIR / ".garmin_cache"
TODAY = dt.date.today()

# How much history each section keeps (matches the dashboard's expectations).
MONTHS = 30      # vo2max / pace / cadence monthly series
WEEKS = 26       # weekly volume + ctl/atl
HEATMAP_DAYS = 365
SLEEP_NIGHTS = 14
RECENT_RUNS = 6

RUN_KEYS = ("running", "treadmill_running", "trail_running", "track_running",
            "indoor_running", "obstacle_run", "ultra_run")

# Garmin's personal-record typeIds. 1–6 are best *times* (seconds) at standard
# run distances; 7 is the longest single run (metres). The rest (cycling, steps)
# aren't running PRs, so we skip them.
PR_TIME_LABELS = {1: "oneK", 2: "oneMile", 3: "fiveK", 4: "tenK",
                  5: "half", 6: "marathon"}


# ──────────────────────────────────────────────────────────────────────────────
# small helpers
# ──────────────────────────────────────────────────────────────────────────────
def log(msg: str) -> None:
    print(msg, flush=True)


def warn(msg: str) -> None:
    print(f"  ! {msg}", file=sys.stderr, flush=True)


def safe(fn, default, label: str):
    """Run a fetch, returning `default` (and warning) if it throws — so one dead
    endpoint can't sink the whole sync."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 — resilience is the point here
        warn(f"{label} failed ({type(e).__name__}: {e}); using fallback")
        return default


def fmt_hms(seconds: float | int | None) -> str:
    if not seconds or seconds <= 0:
        return ""
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def ffill(series: list) -> list:
    """Forward/back-fill Nones so the charts never see a gap. Empty → 0s."""
    out = list(series)
    last = next((v for v in out if v is not None), 0)
    for i, v in enumerate(out):
        if v is None:
            out[i] = last
        else:
            last = out[i]
    return out


# ──────────────────────────────────────────────────────────────────────────────
# 1. CONNECTION
# ──────────────────────────────────────────────────────────────────────────────
def connect() -> Garmin:
    load_dotenv(HERE / ".env")
    email = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")
    tokenstore = os.path.expanduser(os.getenv("GARMIN_TOKENSTORE", str(DATA_DIR / ".garmin_tokens")))

    def prompt_mfa() -> str:
        code = os.getenv("GARMIN_MFA")
        if code:
            return code.strip()
        if sys.stdin and sys.stdin.isatty():
            return input("Garmin MFA code: ").strip()
        raise SystemExit(
            "MFA required but no code available.\n"
            "  → add GARMIN_MFA=<6-digit code> to .env and re-run, or\n"
            "  → run `python sync_garmin.py` directly in an interactive terminal."
        )

    garmin = Garmin(email=email, password=password, prompt_mfa=prompt_mfa)
    # login() loads cached tokens if present (no creds needed), otherwise does a
    # credential login and persists the tokens to `tokenstore` for next time.
    garmin.login(tokenstore)
    who = garmin.full_name or garmin.display_name or email or "athlete"
    log(f"✓ logged in to Garmin as {who}")
    return garmin


# ──────────────────────────────────────────────────────────────────────────────
# 2. RAW ACTIVITY PULL (one call feeds most sections) + tiny per-day cache
# ──────────────────────────────────────────────────────────────────────────────
def load_activities(client) -> list[dict]:
    """Every activity in the lookback window, newest first. The immutable HISTORY
    (older than the recent window) is cached per day so a re-sync doesn't re-pull years
    of activities; the last RECENT_REFETCH_DAYS are ALWAYS re-fetched and merged in, so a
    run added later the same day — or a batch uploaded after the watch wasn't synced for a
    while — shows up on the next sync without clearing any cache.

    A new day means a new cache key, so any longer gap re-pulls the full history on its
    first sync. A failed/empty history pull is never cached (a transient Garmin error can't
    wipe historical data for the rest of the day) and a corrupt cache is re-pulled."""
    RECENT_REFETCH_DAYS = 14
    CACHE_DIR.mkdir(exist_ok=True)
    start = (TODAY - dt.timedelta(days=31 * MONTHS + 20)).isoformat()
    recent_start = (TODAY - dt.timedelta(days=RECENT_REFETCH_DAYS)).isoformat()

    cache = CACHE_DIR / f"activities-history-{TODAY.isoformat()}.json"
    history = None
    if cache.exists():
        try:
            history = json.loads(cache.read_text(encoding="utf-8"))
            log(f"✓ activity history (cached) {cache.name}")
        except Exception:
            history = None                              # corrupt cache → re-pull
    if history is None:
        log(f"… pulling activity history {start} → {recent_start}")
        history = client.get_activities_by_date(start, recent_start) or []
        if history:                                     # never cache a failed/empty pull
            cache.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
        log(f"✓ {len(history)} historical activities pulled")

    log(f"… refreshing recent activities {recent_start} → {TODAY.isoformat()}")
    recent = client.get_activities_by_date(recent_start, TODAY.isoformat()) or []

    # merge newest-first, de-duped by activityId (a fresh recent copy wins over history)
    by_id = {}
    for i, a in enumerate(history + recent):
        aid = a.get("activityId")
        by_id[aid if aid is not None else f"noid-{i}"] = a
    acts = sorted(
        by_id.values(),
        key=lambda a: a.get("startTimeLocal") or a.get("startTimeGMT") or "",
        reverse=True,
    )
    log(f"✓ {len(acts)} activities ({len(recent)} in the fresh {RECENT_REFETCH_DAYS}-day window)")
    return acts


def is_run(a: dict) -> bool:
    t = (a.get("activityType") or {}).get("typeKey", "") or ""
    return any(k in t for k in ("running", "run")) and "cycling" not in t


def act_date(a: dict) -> str:
    s = a.get("startTimeLocal") or a.get("startTimeGMT") or ""
    return s[:10]


def act_km(a: dict) -> float:
    return (a.get("distance") or 0) / 1000.0


def act_dur(a: dict) -> float:
    return a.get("duration") or a.get("movingDuration") or a.get("elapsedDuration") or 0


def act_pace(a: dict) -> int:
    km, dur = act_km(a), act_dur(a)
    return int(round(dur / km)) if km > 0 else 0


def act_hr(a: dict):
    hr = a.get("averageHR")
    return int(round(hr)) if hr else None


def act_cad(a: dict) -> int:
    c = a.get("averageRunningCadenceInStepsPerMinute") or a.get("averageBikingCadenceInRevPerMinute")
    return int(round(c)) if c else 0


def act_vo2(a: dict):
    return a.get("vO2MaxValue")


def _downsample(series, n=30):
    series = [v for v in series if v is not None]
    if len(series) <= n:
        return series
    step = len(series) / n
    result = [series[int(i * step)] for i in range(n)]
    result[-1] = series[-1]
    return result


def _hr_drift(hr):
    hr = [v for v in hr if v is not None]
    if len(hr) < 4:
        return 0
    half = len(hr) // 2
    first = sum(hr[:half]) / half
    second = sum(hr[half:]) / (len(hr) - half)
    return int(round(second - first))


def _split_shape(splits):
    paces = [s["pace"] for s in splits if s.get("pace")]
    if len(paces) < 3:
        return "even"
    third = max(1, len(paces) // 3)
    first = sum(paces[:third]) / third
    last = sum(paces[-third:]) / third
    if first <= 0:
        return "even"
    delta = (last - first) / first
    if delta > 0.04:
        return "positive"   # slowed (pace seconds increased)
    if delta < -0.04:
        return "negative"   # sped up
    return "even"


def _bin_splits(rows, idx):
    iD, iHR, iSpd = idx.get("sumDistance"), idx.get("directHeartRate"), idx.get("directSpeed")
    buckets = {}
    max_dist = 0.0
    for row in rows:
        m = row.get("metrics") or []
        try:
            dist = m[iD]
            hr = m[iHR] if iHR is not None else None
            spd = m[iSpd] if iSpd is not None else None
        except (TypeError, IndexError):
            continue
        if dist is None:
            continue
        if dist > max_dist:
            max_dist = dist
        buckets.setdefault(int(dist // 1000), []).append((hr, spd))
    out = []
    for km in sorted(buckets):
        hrs = [h for h, s in buckets[km] if h is not None]
        spds = [s for h, s in buckets[km] if s]
        avg_spd = sum(spds) / len(spds) if spds else 0
        out.append({
            "km": km + 1,
            "pace": int(round(1000 / avg_spd)) if avg_spd else 0,
            "hr": int(round(sum(hrs) / len(hrs))) if hrs else 0,
        })
    # Drop a trailing partial-km bucket that covers < 600 m — real GPS runs end
    # mid-kilometre, so the final bucket often spans only a sliver of distance and
    # would skew the splits sparkline and _split_shape.
    if len(out) > 1:
        last_bucket_index = sorted(buckets)[-1]
        span = max_dist - (last_bucket_index * 1000)
        if span < 600:
            out = out[:-1]
    return out


def classify(a: dict) -> str:
    """Map an activity to one of the labels the dashboard colour-codes
    ('Tempo Run' / 'Long Run' / 'Recovery'), else a neutral 'Run'."""
    name = (a.get("activityName") or "").lower()
    km = act_km(a)
    if any(w in name for w in ("tempo", "threshold", "interval", "speed", "fartlek")):
        return "Tempo Run"
    if any(w in name for w in ("long", "endurance")) or km >= 14:
        return "Long Run"
    if any(w in name for w in ("recovery", "easy", "shakeout")):
        return "Recovery"
    return "Run"


# ──────────────────────────────────────────────────────────────────────────────
# 3. FETCHERS  (each returns data already shaped to the contract, §3)
# ──────────────────────────────────────────────────────────────────────────────
def fetch_recent_runs(client, acts: list[dict], n: int = RECENT_RUNS) -> list[dict]:
    runs = [a for a in acts if is_run(a) and act_km(a) > 0]
    runs.sort(key=act_date, reverse=True)
    out = []
    for a in runs[:n]:
        out.append({
            "date": act_date(a),
            "type": classify(a),
            "km": round(act_km(a), 1),
            "time": fmt_hms(act_dur(a)),
            "pace": act_pace(a),
            "hr": act_hr(a) or 0,
            "cad": act_cad(a),
            "vo2": round(act_vo2(a), 1) if act_vo2(a) else None,
            "detail": fetch_run_detail(client, a),
        })
    return out


def _fetch_raw_detail(client, aid) -> dict | None:
    """RAW `get_activity_details` payload, cache-first
    (`.garmin_cache/detail-<id>.json`). Shared by the dashboard's recent-run
    drill-down and the archive — the archive stores exactly this payload."""
    if not aid:
        return None
    CACHE_DIR.mkdir(exist_ok=True)
    cache = CACHE_DIR / f"detail-{aid}.json"
    det = None
    if cache.exists():
        det = safe(lambda: json.loads(cache.read_text(encoding="utf-8")), None, f"detail-cache {aid}")
    if not det:                      # cache miss OR corrupt cache
        det = safe(lambda: client.get_activity_details(aid, maxchart=2000, maxpoly=0),
                   None, f"detail {aid}")
        if det:
            cache.write_text(json.dumps(det, ensure_ascii=False), encoding="utf-8")
    return det


def fetch_run_detail(client, activity) -> dict | None:
    """Per-run drill-down detail (splits, HR-drift, zones, temp, TE). Cached per
    activity id so re-syncs only fetch genuinely new runs."""
    det = _fetch_raw_detail(client, activity.get("activityId"))
    return distill_run_detail(det, activity)


def distill_run_detail(det: dict | None, activity: dict) -> dict | None:
    """Distill a RAW `get_activity_details` payload + its raw activity summary
    into the recent-run `detail` contract of garmin-data.js. Pure over its
    inputs — one distiller, two callers: fetch_run_detail (fresh from the API)
    and the archive's distillation pass (stored payloads, no network)."""
    if not det:
        return None

    idx = {d.get("key"): d.get("metricsIndex") for d in (det.get("metricDescriptors") or [])}
    rows = det.get("activityDetailMetrics") or []
    splits = _bin_splits(rows, idx)

    iHR = idx.get("directHeartRate")
    hr_all = []
    for row in rows:
        m = row.get("metrics") or []
        if iHR is not None and iHR < len(m) and m[iHR] is not None:
            hr_all.append(m[iHR])

    zone_min = [math.ceil((activity.get(f"hrTimeInZone_{k}") or 0) / 60) for k in range(1, 6)]
    temp = activity.get("maxTemperature")
    if temp is None:
        temp = activity.get("minTemperature")
    load = activity.get("activityTrainingLoad")
    elev = activity.get("elevationGain")
    return {
        "splits": splits,
        "hrSeries": [int(round(v)) for v in _downsample(hr_all, 30)],
        "driftBpm": _hr_drift(hr_all),
        "zoneMin": zone_min,
        "tempC": int(round(temp)) if temp is not None else None,
        "te": activity.get("aerobicTrainingEffect"),
        "load": round(load) if load else None,
        "elevGain": round(elev) if elev else None,
        "splitShape": _split_shape(splits),
    }


# Columns the stream distiller keeps, with the precision each metric actually
# carries (run-detail design D1). Everything else in the raw payload is
# derivable and deliberately dropped:
#   directTimestamp          — t plus the activity's start time
#   directRunCadence         — SINGLE-SIDE strides/min despite a descriptor
#                              claiming stepsPerMinute (79.8 where the promoted
#                              avg_cadence reads 160.3); directDoubleCadence is
#                              the true steps/min — see insight_metrics.
#                              read_stream's quirk note
#   directFractionalCadence  — folded into directDoubleCadence
#   sumElapsedDuration / sumMovingDuration — sumDuration is the shared axis
#   sumAccumulatedPower      — the integral of directPower
#   directVerticalSpeed      — the derivative of directElevation
_STREAM_COLUMNS = (
    ("t",    "sumDuration",                0),
    ("d",    "sumDistance",                0),
    ("hr",   "directHeartRate",            0),
    ("v",    "directSpeed",                2),
    ("gap",  "directGradeAdjustedSpeed",   2),
    ("cad",  "directDoubleCadence",        0),
    ("elev", "directElevation",            1),
    ("pwr",  "directPower",                0),
    ("lat",  "directLatitude",             5),
    ("lon",  "directLongitude",            5),
    ("pc",   "directPerformanceCondition", 0),
)


def distill_run_streams(det: dict | None) -> dict | None:
    """Reshape a RAW `get_activity_details` payload into rounded columnar
    streams (run-detail design D1): one array per metric, sample-aligned,
    nulls preserved as nulls, at full stored resolution. Pure over its input —
    no network, no clock. The GPS track lives in lat/lon: the sync fetches
    `maxpoly=0`, so `geoPolylineDTO.polyline` is always empty and the stream
    columns are the only (and complete) source of the route."""
    if not det:
        return None
    idx = {d.get("key"): d.get("metricsIndex") for d in (det.get("metricDescriptors") or [])}
    rows = det.get("activityDetailMetrics") or []
    if not rows:
        return None
    out = {}
    for key, source, digits in _STREAM_COLUMNS:
        i = idx.get(source)
        if i is None:
            continue                       # metric absent from this payload
        col = []
        for row in rows:
            m = row.get("metrics") or []
            val = m[i] if i < len(m) else None
            if val is None:
                col.append(None)
            elif digits == 0:
                col.append(int(round(val)))
            else:
                col.append(round(val, digits))
        if any(v is not None for v in col):
            out[key] = col
    if "t" not in out or "d" not in out:
        return None                        # not a stream payload worth serving
    return out


def fetch_heatmap(acts: list[dict]) -> list[float]:
    by_day: dict[str, float] = {}
    for a in acts:
        if is_run(a):
            d = act_date(a)
            if d:
                by_day[d] = by_day.get(d, 0.0) + act_km(a)
    out = []
    for i in range(HEATMAP_DAYS):
        d = (TODAY - dt.timedelta(days=HEATMAP_DAYS - 1 - i)).isoformat()
        out.append(round(by_day.get(d, 0.0), 1))
    return out  # index 364 == today


def fetch_weekly(acts: list[dict], weeks: int = WEEKS) -> tuple[list[float], list[int]]:
    monday = TODAY - dt.timedelta(days=TODAY.weekday())
    starts = [monday - dt.timedelta(weeks=(weeks - 1 - i)) for i in range(weeks)]
    km = [0.0] * weeks
    runs = [0] * weeks
    for a in acts:
        if not is_run(a) or not act_date(a):
            continue
        d = dt.date.fromisoformat(act_date(a))
        for i, ws in enumerate(starts):
            if ws <= d < ws + dt.timedelta(days=7):
                km[i] += act_km(a)
                runs[i] += 1
                break
    return [round(x, 1) for x in km], runs


def month_keys(months: int) -> list[str]:
    keys, y, m = [], TODAY.year, TODAY.month
    for _ in range(months):
        keys.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    keys.reverse()  # oldest → newest
    return keys


def fetch_monthly(client, acts: list[dict], months: int = MONTHS) -> dict:
    keys = month_keys(months)
    pace_acc = {k: [] for k in keys}
    cad_acc = {k: [] for k in keys}
    vo2_acc = {k: [] for k in keys}
    for a in acts:
        if not is_run(a):
            continue
        k = act_date(a)[:7]
        if k not in pace_acc:
            continue
        if act_pace(a):
            pace_acc[k].append(act_pace(a))
        if act_cad(a):
            cad_acc[k].append(act_cad(a))
        if act_vo2(a):
            vo2_acc[k].append(act_vo2(a))

    pace = ffill([round(mean(pace_acc[k])) if pace_acc[k] else None for k in keys])
    cad = ffill([round(mean(cad_acc[k])) if cad_acc[k] else None for k in keys])
    vo2 = [round(mean(vo2_acc[k]), 1) if vo2_acc[k] else None for k in keys]

    # vo2 often isn't on every activity — backfill the gaps from get_max_metrics
    # at each month end (cheap, ~once per missing month).
    if any(v is None for v in vo2):
        for i, k in enumerate(keys):
            if vo2[i] is not None:
                continue
            cdate = _month_end(k)
            v = safe(lambda: _parse_vo2(client.get_max_metrics(cdate)), None, f"get_max_metrics {k}")
            vo2[i] = round(v, 1) if v else None
    vo2 = ffill(vo2)

    return {"vo2maxStartMonth": keys[0], "vo2max": vo2, "paceSecPerKm": pace, "cadenceSpm": cad}


def _month_end(key: str) -> str:
    y, m = (int(x) for x in key.split("-"))
    nxt = dt.date(y + (m == 12), (m % 12) + 1, 1)
    return min(nxt - dt.timedelta(days=1), TODAY).isoformat()


def _parse_vo2(metrics) -> float | None:
    if isinstance(metrics, list):
        metrics = metrics[0] if metrics else {}
    g = (metrics or {}).get("generic") or {}
    return g.get("vo2MaxPreciseValue") or g.get("vo2MaxValue")


def compute_fitness_fatigue(acts: list[dict], max_hr: int, weeks: int = WEEKS) -> tuple[list[float], list[float]]:
    """Daily TSS → EWMA(42) fitness (CTL) and EWMA(7) fatigue (ATL), sampled
    weekly. TSS ≈ duration_hr × IF² × 100 with IF from avg-HR fraction (§4)."""
    start = TODAY - dt.timedelta(days=weeks * 7 + 42)  # 42d warm-up for the EWMA
    tss: dict[dt.date, float] = {}
    for a in acts:
        if not is_run(a) or not act_date(a):
            continue
        d = dt.date.fromisoformat(act_date(a))
        if d < start:
            continue
        dur_hr = act_dur(a) / 3600.0
        avg = a.get("averageHR")
        intensity = max(0.4, min(1.05, avg / max_hr)) if (avg and max_hr) else 0.70
        tss[d] = tss.get(d, 0.0) + dur_hr * intensity * intensity * 100

    ctl = atl = 0.0
    ctl_at: dict[dt.date, float] = {}
    atl_at: dict[dt.date, float] = {}
    day = start
    while day <= TODAY:
        t = tss.get(day, 0.0)
        ctl += (t - ctl) / 42
        atl += (t - atl) / 7
        ctl_at[day], atl_at[day] = ctl, atl
        day += dt.timedelta(days=1)

    monday = TODAY - dt.timedelta(days=TODAY.weekday())
    ctl_w, atl_w = [], []
    for i in range(weeks):
        end = min(monday - dt.timedelta(weeks=(weeks - 1 - i)) + dt.timedelta(days=6), TODAY)
        ctl_w.append(round(ctl_at.get(end, ctl), 1))
        atl_w.append(round(atl_at.get(end, atl), 1))
    return ctl_w, atl_w


# The archive owns the column list; this is the projection that fills it. One
# source of truth, pinned by a test — the two can never drift apart.
WELLNESS_COLUMNS = activity_archive.WELLNESS_PROMOTED_COLUMNS


def promote_wellness(sleep: dict | None, hrv: dict | None) -> dict:
    """Project one night's raw sleep + HRV payloads onto the promoted columns.
    Pure over its inputs: no clock, no network, nothing mutated.

    Absent is None, never 0 — a night the watch sat on the nightstand and a night
    of zero sleep are different facts. Columns are independently nullable: a
    payload can carry no sleep at all while HRV's rolling weeklyAvg and balanced
    range remain populated.

    `resting_hr` can be None even though the sleep payload exists (Garmin returns
    a hollow four-key payload for an unworn night), which is why the caller falls
    back to get_rhr_day on a null VALUE rather than on a missing payload.

    Shape drifts across eras — the 2024 sleep payload has 7 top-level keys, the
    2026 one has 18 — so every read is a tolerant .get() chain. See the fixtures
    in fixtures/wellness/ and their README.
    """
    sleep = sleep or {}
    hrv = hrv or {}
    dto = sleep.get("dailySleepDTO") or {}
    scores = dto.get("sleepScores") or {}
    summary = hrv.get("hrvSummary") or {}
    baseline = summary.get("baseline") or {}   # object, not a pair: {lowUpper, balancedLow, balancedUpper, markerValue}
    secs = dto.get("sleepTimeSeconds")
    return {
        # v1 columns, still populated so nothing downstream has to change
        "hrv": summary.get("lastNightAvg"),
        "sleep_hours": round(secs / 3600, 1) if secs else None,
        "sleep_seconds": secs,
        "deep_seconds": dto.get("deepSleepSeconds"),
        "rem_seconds": dto.get("remSleepSeconds"),
        "light_seconds": dto.get("lightSleepSeconds"),
        "awake_seconds": dto.get("awakeSleepSeconds"),
        "sleep_score": (scores.get("overall") or {}).get("value"),
        "respiration_avg": dto.get("averageRespirationValue"),
        "body_battery_change": sleep.get("bodyBatteryChange"),
        "resting_hr": sleep.get("restingHeartRate"),
        "hrv_last_night": summary.get("lastNightAvg"),
        "hrv_weekly_avg": summary.get("weeklyAvg"),
        "hrv_balanced_low": baseline.get("balancedLow"),
        "hrv_balanced_upper": baseline.get("balancedUpper"),
        "hrv_status": summary.get("status"),
    }


BACKFILL_DELAY_S = 0.4   # ~1,600 calls at this pace is roughly 11 minutes


def _now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _date_span(earliest: str, today: str):
    """ISO dates from `earliest` to `today` inclusive, ascending."""
    a, b = dt.date.fromisoformat(earliest), dt.date.fromisoformat(today)
    while a <= b:
        yield a.isoformat()
        a += dt.timedelta(days=1)


def fetch_wellness_day(client, date: str):
    """One night's raw payloads + their promoted projection.

    Returns `(sleep, hrv, values, complete)`. `complete` is True only when both
    Garmin calls answered — a raised call yields None and leaves the date
    unmarked so a later run retries it. Garmin answers every date with a
    document, however empty, so an empty dict means "the watch recorded nothing"
    and is a perfectly complete fetch.

    Resting HR comes from the sleep payload, and the fallback fires on a **null
    value**, not on a missing payload: an unworn night returns a hollow
    four-key sleep document whose `restingHeartRate` is null, while
    `get_rhr_day` for that same date still answers.
    """
    sleep = safe(lambda: client.get_sleep_data(date), None, f"get_sleep_data {date}")
    hrv = safe(lambda: client.get_hrv_data(date), None, f"get_hrv_data {date}")
    values = promote_wellness(sleep, hrv)
    if values["resting_hr"] is None:
        rhr = safe(lambda: _parse_rhr(client.get_rhr_day(date)), None, f"get_rhr_day {date}")
        values["resting_hr"] = int(rhr) if rhr else None
    return sleep, hrv, values, (sleep is not None and hrv is not None)


def backfill_wellness(conn, client, earliest: str, today: str,
                      since: str | None = None, delay: float = BACKFILL_DELAY_S) -> dict:
    """Bank every night's raw sleep + HRV payload from `earliest` to `today`.

    Resumable by construction: the archive is the cursor. A date already carrying
    `fetched_at` is skipped, so an interrupted run resumes where it stopped and a
    complete run makes no requests at all. Newest-first, so an interrupted
    backfill leaves the most useful history present.
    """
    start = max(earliest, since) if since else earliest
    dates = list(_date_span(start, today))
    already = {r[0] for r in conn.execute(
        "SELECT date FROM daily_wellness WHERE fetched_at IS NOT NULL")}
    todo = [d for d in reversed(dates) if d not in already]

    stats = {"fetched": 0, "skipped": len(dates) - len(todo), "failed": 0}
    for i, date in enumerate(todo):
        sleep, hrv, values, complete = fetch_wellness_day(client, date)
        if not complete:
            stats["failed"] += 1          # no fetched_at → the next run retries it
            continue
        activity_archive.upsert_wellness(
            conn, date, values, sleep_raw=sleep, hrv_raw=hrv, fetched_at=_now_iso())
        stats["fetched"] += 1
        if delay and i < len(todo) - 1:
            time.sleep(delay)
        if stats["fetched"] % 50 == 0:
            log(f"  wellness backfill: {stats['fetched']}/{len(todo)} banked")

    # The marker claims coverage of the WHOLE span, so a --since run cannot set it.
    remaining = [d for d in _date_span(earliest, today)
                 if d not in already and d not in
                 {r[0] for r in conn.execute(
                     "SELECT date FROM daily_wellness WHERE fetched_at IS NOT NULL")}]
    if not remaining:
        activity_archive.set_meta(conn, "wellness_backfill_completed_at", _now_iso())
    return stats


def fetch_sleep(client, nights: int = SLEEP_NIGHTS, raw_out: list | None = None) -> list[dict]:
    # Window ENDS on TODAY, so the most recent slot is last night. Garmin only
    # finalises last night's sleep once you wake, so the sync must run after
    # wake-up (SYNC_AT in the compose) or that slot comes back empty — see the
    # non-zero fallback in fetch_readiness.
    #
    # `raw_out` collects (date, payload) for the archive: these payloads are
    # fetched either way, and throwing them away is what capped wellness history
    # at fourteen nights forever. The history.sleep contract is unchanged.
    out = []
    for i in range(nights):
        d = (TODAY - dt.timedelta(days=nights - 1 - i)).isoformat()
        rec = safe(lambda: client.get_sleep_data(d), {}, f"get_sleep_data {d}") or {}
        if raw_out is not None:
            raw_out.append((d, rec))
        dto = rec.get("dailySleepDTO") or {}
        secs = dto.get("sleepTimeSeconds") or 0
        deep = dto.get("deepSleepSeconds") or 0
        hrv = (rec.get("avgOvernightHrv")
               or (rec.get("hrvSummary") or {}).get("lastNightAvg")
               or dto.get("avgOvernightHrv") or 0)
        out.append({
            "hours": round(secs / 3600, 1) if secs else 0.0,
            "hrv": int(round(hrv)) if hrv else 0,
            "deepPct": round(deep / secs * 100) if secs else 0,
        })
    return out


def fetch_profile(client, vo2_current: float | None) -> dict:
    today = TODAY.isoformat()
    summary = safe(lambda: client.get_user_summary(today), {}, "get_user_summary") or {}
    rhr_doc = safe(lambda: client.get_rhr_day(today), {}, "get_rhr_day") or {}
    rhr = _parse_rhr(rhr_doc) or summary.get("restingHeartRate") or 47
    weight_g = summary.get("weight") or 0
    return {
        "name": os.getenv("ATHLETE_NAME", client.full_name.split(" ")[0] if client.full_name else "Felix"),
        "age": int(os.getenv("ATHLETE_AGE", "31")),
        "restingHR": int(rhr),
        "maxHR": int(os.getenv("ATHLETE_MAX_HR", "197")),
        "weightKg": round(weight_g / 1000.0, 1) if weight_g else 71.0,
        "vo2maxCurrent": round(vo2_current, 1) if vo2_current else 51.3,
    }


def _parse_rhr(doc: dict):
    if not isinstance(doc, dict):
        return None
    vals = doc.get("allMetrics", {}).get("metricsMap", {}).get("WELLNESS_RESTING_HEART_RATE")
    if isinstance(vals, list) and vals:
        return vals[-1].get("value")
    return doc.get("restingHeartRate")


def fetch_readiness(client, sleep: list[dict], max_hr: int) -> dict:
    today = TODAY.isoformat()
    tr_list = safe(lambda: client.get_training_readiness(today), [], "get_training_readiness") or []
    tr = tr_list[0] if isinstance(tr_list, list) and tr_list else (tr_list if isinstance(tr_list, dict) else {})

    # Most recent night that actually has sleep logged: if the sync still runs
    # before Garmin finalises last night, use the latest real night rather than
    # reporting 0 h — readiness must reflect true rest, not sync timing.
    last = next((s for s in reversed(sleep) if s.get("hours")), {})
    hrv = last.get("hrv") or 0
    sleep_h = last.get("hours") or 0.0
    rhr = safe(lambda: _parse_rhr(client.get_rhr_day(today)), None, "rhr(readiness)") or 46

    status_doc = safe(lambda: client.get_training_status(today), {}, "get_training_status") or {}
    load = _parse_acute_load(status_doc)

    score = tr.get("score")
    if not score:
        score = _compute_readiness(hrv, rhr, sleep_h)
    status = tr.get("level") or _readiness_label(score)
    return {
        "score": int(round(score)),
        "status": str(status).title()[:16],
        "hrv": int(hrv),
        "restingHR": int(rhr),
        "sleepHours": round(sleep_h, 1),
        "trainingLoad": int(load) if load else 0,
        "loadStatus": _load_label(status_doc),
    }


def _parse_acute_load(doc: dict):
    try:
        latest = doc.get("mostRecentTrainingStatus", {}).get("latestTrainingStatusData", {})
        for v in latest.values():
            if isinstance(v, dict) and v.get("acuteTrainingLoadDTO"):
                return v["acuteTrainingLoadDTO"].get("acwrPercent") or v["acuteTrainingLoadDTO"].get("dailyAcuteChronicWorkloadRatio")
    except Exception:  # noqa: BLE001
        pass
    return doc.get("acuteTrainingLoad") if isinstance(doc, dict) else None


def _load_label(doc: dict) -> str:
    try:
        latest = doc.get("mostRecentTrainingStatus", {}).get("latestTrainingStatusData", {})
        for v in latest.values():
            fb = (v or {}).get("trainingStatusFeedbackPhrase")
            if fb:
                return str(fb).split("_")[0].title()
    except Exception:  # noqa: BLE001
        pass
    return "Optimal"


def _compute_readiness(hrv, rhr, sleep_h) -> float:
    # Blend normalized HRV (↑good), resting HR (↓good) and sleep into 0-100 (§4).
    hrv_s = max(0.0, min(1.0, (hrv - 30) / 60)) if hrv else 0.6
    rhr_s = max(0.0, min(1.0, (60 - rhr) / 25)) if rhr else 0.6
    slp_s = max(0.0, min(1.0, sleep_h / 8.0)) if sleep_h else 0.6
    return round((0.45 * hrv_s + 0.30 * rhr_s + 0.25 * slp_s) * 100)


def _readiness_label(score) -> str:
    return "Primed" if score >= 75 else "Ready" if score >= 55 else "Strained" if score >= 35 else "Low"


def fetch_hr_zones_this_week(client, acts: list[dict], max_hr: int) -> list[dict]:
    monday = TODAY - dt.timedelta(days=TODAY.weekday())
    secs = [0.0] * 5
    for a in acts:
        if not is_run(a) or not act_date(a):
            continue
        if dt.date.fromisoformat(act_date(a)) < monday:
            continue
        # zone seconds can live on the summary; else ask per-activity.
        got = False
        for z in range(1, 6):
            v = a.get(f"hrTimeInZone_{z}")
            if v:
                secs[z - 1] += v
                got = True
        if not got:
            aid = a.get("activityId")
            tz = safe(lambda: client.get_activity_hr_in_timezones(str(aid)), [], f"hr_zones {aid}") or []
            for row in tz:
                z = row.get("zoneNumber")
                if z and 1 <= z <= 5:
                    secs[z - 1] += row.get("secsInZone", 0)

    labels = ["Recovery", "Endurance", "Tempo", "Threshold", "VO2 max"]
    bounds = [round(max_hr * f) for f in (0.50, 0.60, 0.70, 0.80, 0.90, 1.00)]
    return [
        {"z": z + 1, "label": labels[z], "min": int(round(secs[z] / 60)),
         "lo": bounds[z], "hi": bounds[z + 1]}
        for z in range(5)
    ]


def fetch_personal_bests(client) -> dict:
    """Lifetime running PRs from Garmin (best time at each standard distance,
    plus the longest single run). Time values arrive in seconds; the longest run
    in metres. This is real PB data — the plan's `race.pb` is set from it."""
    prs = safe(lambda: client.get_personal_record(), [], "get_personal_record") or []
    out: dict[str, object] = {}
    for pr in prs:
        if not isinstance(pr, dict):
            continue
        tid, val = pr.get("typeId"), pr.get("value")
        if not val:
            continue
        date = (pr.get("activityStartDateTimeLocalFormatted")
                or pr.get("prStartTimeGmtFormatted") or "")[:10]
        if tid in PR_TIME_LABELS:
            out[PR_TIME_LABELS[tid]] = {"time": fmt_hms(val), "date": date}
        elif tid == 7:
            out["longestRunKm"] = round(val / 1000.0, 1)
    return out


def fetch_raw_predictions(client) -> dict:
    """The raw race-predictor document, fetched once and shared by the
    telemetry block AND the archive's predictor banking (zero extra calls,
    design D7)."""
    doc = safe(lambda: client.get_race_predictions(), {}, "get_race_predictions") or {}
    if isinstance(doc, list):
        doc = doc[-1] if doc else {}
    return doc


def fetch_predictions(pred_doc: dict, planned_goal: str = "1:59:59") -> dict:
    return {
        "fiveK": fmt_hms(pred_doc.get("time5K")),
        "tenK": fmt_hms(pred_doc.get("time10K")),
        "halfNow": fmt_hms(pred_doc.get("timeHalfMarathon")),
        "halfGoal": planned_goal,
        "trend": "",  # filled from the insights trajectory when available
    }


# ──────────────────────────────────────────────────────────────────────────────
# 4. ASSEMBLE + WRITE
# ──────────────────────────────────────────────────────────────────────────────
def fetch_insights() -> dict | None:
    """The assembled insights block from the archive (design D1 phase 2), or
    None — in which case the caller omits the key entirely. Never a partial
    block: assemble_insights raises on any problem and safe() maps that to
    None (design D8)."""
    def assemble():
        conn = activity_archive.open_archive(DATA_DIR)
        try:
            return insight_metrics.assemble_insights(conn, TODAY)
        finally:
            conn.close()
    return safe(assemble, None, "insights assembly")


def fetch_compliance() -> dict | None:
    """The assembled compliance block, or None (key omitted entirely). A fail
    domain INDEPENDENT of insights (coach-loop design D5): a plan problem
    drops this block while insights survives, and vice versa."""
    def assemble():
        loaded = plan_compliance.load_plan(DATA_DIR / "plan-data.js")
        if not loaded:
            return None
        conn = activity_archive.open_archive(DATA_DIR)
        try:
            return plan_compliance.assemble_compliance(conn, loaded[1], TODAY)
        finally:
            conn.close()
    return safe(assemble, None, "compliance assembly")


def build_data(client, acts: list[dict], pred_doc: dict | None = None,
               sleep_raw_out: list | None = None) -> dict:
    # `sleep_raw_out`, when supplied, collects the raw sleep payloads fetch_sleep
    # pulls anyway, so wellness_step can bank them without a second round-trip.
    max_hr = int(os.getenv("ATHLETE_MAX_HR", "197"))

    monthly = fetch_monthly(client, acts)
    weekly_km, weekly_runs = fetch_weekly(acts)
    ctl, atl = compute_fitness_fatigue(acts, max_hr)
    sleep = fetch_sleep(client, raw_out=sleep_raw_out)
    vo2_current = monthly["vo2max"][-1] if monthly["vo2max"] else None

    predictions = fetch_predictions(pred_doc or {})
    insights = fetch_insights()
    if insights:
        trend = insight_metrics.trend_verdict(insights["trajectory"]["weekly"])
        if trend:
            predictions["trend"] = trend
        log(f"✓ insights assembled ({len(insights['efficiency']['monthly'])} months, "
            f"{len(insights['trajectory']['weekly'])} weeks)")
    compliance = fetch_compliance()
    if compliance:
        log(f"✓ compliance assembled ({len(compliance['days'])} days, "
            f"{len(compliance['weeks'])} weeks)")

    data = {
        "profile": fetch_profile(client, vo2_current),
        "today": TODAY.isoformat(),
        "readiness": fetch_readiness(client, sleep, max_hr),
        "hrZones": fetch_hr_zones_this_week(client, acts, max_hr),
        "predictions": predictions,
        "personalBests": fetch_personal_bests(client),
        "recentRuns": fetch_recent_runs(client, acts),
        "history": {
            "vo2maxStartMonth": monthly["vo2maxStartMonth"],
            "vo2max": monthly["vo2max"],
            "paceSecPerKm": monthly["paceSecPerKm"],
            "cadenceSpm": monthly["cadenceSpm"],
            "weeklyKm": weekly_km,
            "weeklyRuns": weekly_runs,
            "ctl": ctl,
            "atl": atl,
            "sleep": sleep,
        },
        "heatmapKm": fetch_heatmap(acts),
    }
    if insights:
        data["insights"] = insights
    if compliance:
        data["compliance"] = compliance
    return data


def validate(data: dict) -> None:
    """Assert the FROM-GARMIN invariants (§3) before writing. weekPlan / race
    invariants belong to plan-data.js and are checked by validate_data.py."""
    h = data["history"]
    assert len(data["heatmapKm"]) == HEATMAP_DAYS, "heatmapKm must be exactly 365 days"
    if h["vo2max"]:
        assert abs(data["profile"]["vo2maxCurrent"] - h["vo2max"][-1]) < 0.05, \
            "profile.vo2maxCurrent must equal history.vo2max[-1]"
    for k in ("vo2max", "paceSecPerKm", "cadenceSpm", "weeklyKm", "weeklyRuns", "ctl", "atl"):
        assert isinstance(h.get(k), list), f"history.{k} must be a list"
        assert all(v is not None for v in h[k]), f"history.{k} has gaps (None values)"
    assert len(h["sleep"]) == SLEEP_NIGHTS, "history.sleep must have 14 nights"
    log("✓ telemetry validation passed")


def build_garmin_data_js(data: dict) -> str:
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    stamp = dt.datetime.now().isoformat(timespec="seconds")
    return (
        "/* AUTO-GENERATED by sync_garmin.py — do not hand-edit. Telemetry only.\n"
        f" * Last sync: {stamp}\n"
        " * The plan (race / weekPlan / coach) lives in plan-data.js and is never\n"
        " * touched here. running-data.js merges the two into `athleteData`.\n"
        " */\n"
        f"export const garminData = {payload};\n\n"
        "export default garminData;\n"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 5. DURABLE ARCHIVE + METRICS  (activity_archive.py / insight_metrics.py).
#    Order per insight-metrics design D8: archive → metrics → build → write.
#    Every step here runs ONLY inside safe() — telemetry keys are written even
#    if archive, metrics and insights all fail.
# ──────────────────────────────────────────────────────────────────────────────
DETAIL_TOPUP_PER_SYNC = 25   # backlog drains over successive nights (design D4)


def archive_step(client, acts: list[dict]) -> None:
    """Bank this sync's activity fetches into the durable archive. Runs BEFORE
    build_data (the insights must include today's run — design D8) and only
    ever inside safe() — an archive problem is a warning, never a failed sync."""
    conn = activity_archive.open_archive(DATA_DIR)
    try:
        added = activity_archive.upsert_activities(conn, acts)
        topped = _archive_detail_topup(client, conn, DETAIL_TOPUP_PER_SYNC)
        distilled = _distill_pass(conn)
        streamed = _streams_pass(conn)
        _record_expectations(conn)
        log(f"✓ archive: +{added} activities, {topped} details topped up"
            + (f", {distilled} runs distilled" if distilled else "")
            + (f", {streamed} runs streamed" if streamed else ""))
    finally:
        conn.close()


def metrics_step(client, pred_doc) -> None:
    """Phase-1 metrics work (insight_metrics design D1/D7): extract run_metrics
    for anything new or stale-versioned, then bank today's race prediction —
    auto-backfilling the whole predictor history the first time the table is
    seen empty. Only ever runs inside safe()."""
    conn = activity_archive.open_archive(DATA_DIR)
    try:
        extracted = insight_metrics.extract_run_metrics(conn)
        backfilled = 0
        if activity_archive.race_predictions_empty(conn):
            earliest = conn.execute(
                "SELECT MIN(start_time_local) FROM activities").fetchone()[0]
            if earliest:
                backfilled = insight_metrics.backfill_predictions(conn, client, earliest)
        banked = insight_metrics.bank_prediction(conn, pred_doc, TODAY)
        parts = [f"+{extracted} runs extracted"]
        if backfilled:
            parts.append(f"predictor history backfilled ({backfilled} days)")
        parts.append("prediction banked" if banked else "no prediction to bank")
        log("✓ metrics: " + ", ".join(parts))
    finally:
        conn.close()


def compliance_step() -> None:
    """Bank today's plan snapshot and rescore compliance (coach-loop design
    D2/D3). Runs AFTER the archive step (it matches against archived
    activities) and BEFORE build_data (the block must land in garmin-data.js);
    only ever inside safe() — a plan problem is a warning, never a failed
    sync."""
    loaded = plan_compliance.load_plan(DATA_DIR / "plan-data.js")
    if not loaded:
        return
    raw, plan = loaded
    max_hr = int(os.getenv("ATHLETE_MAX_HR", "197"))
    conn = activity_archive.open_archive(DATA_DIR)
    try:
        stats = plan_compliance.run_compliance(conn, raw, plan, TODAY, max_hr)
        # Ratchet the coverage expectation --verify-archive checks against:
        # scored weeks only ever accumulate, so a shrink is a regression.
        weeks_now = activity_archive.compliance_coverage(
            conn, plan_compliance.COMPLIANCE_VERSION)["weeks_scored"]
        prev = activity_archive.get_meta(conn, "expected_compliance_weeks")
        if weeks_now > int(prev or 0):
            activity_archive.set_meta(conn, "expected_compliance_weeks", weeks_now)
        parts = [f"{stats['weeks_scored']} weeks scored"]
        if stats["weeks_healed"]:
            parts.append(f"{stats['weeks_healed']} stale weeks healed")
        log("✓ compliance: " + ", ".join(parts))
    finally:
        conn.close()


def briefing_step(data: dict) -> None:
    """Render coach-briefing.md into the data dir (coach-loop design D6).
    Runs strictly AFTER garmin-data.js is written and only ever inside
    safe() — a briefing problem can never affect the contract file."""
    loaded = plan_compliance.load_plan(DATA_DIR / "plan-data.js")
    if not loaded:
        return
    conn = activity_archive.open_archive(DATA_DIR)
    try:
        text = coach_briefing.render_briefing(conn, loaded[1], data, TODAY)
    finally:
        conn.close()
    coach_briefing.write_briefing(DATA_DIR / "coach-briefing.md", text)
    log("✓ coach briefing written")


def wellness_step(client, readiness: dict, sleep_raw: list) -> None:
    """Bank the sync's whole sleep window, not just today.

    `fetch_sleep()` already pulls a raw payload for every night in the window;
    `sleep_raw` is that harvest. HRV is topped up only for nights whose stored
    HRV carries no reading, and resting HR only for nights the sleep payload
    does not report it — so the steady-state call count barely moves while the
    window self-heals any night missed while the container was down.

    Readiness is computed inside build_data, so this runs after the write —
    nothing downstream needs it in the same sync. Only ever inside safe().
    """
    conn = activity_archive.open_archive(DATA_DIR)
    try:
        stored = {r[0]: (r[1], r[2]) for r in conn.execute(
            "SELECT date, hrv_json, hrv_last_night FROM daily_wellness")}
        today_iso = TODAY.isoformat()

        for date, sleep in sleep_raw:
            hrv_json, hrv_last = stored.get(date, (None, None))
            if hrv_last is None:                      # never read, or the night was unworn
                hrv = safe(lambda: client.get_hrv_data(date), None, f"get_hrv_data {date}")
            else:
                hrv = json.loads(hrv_json)
            values = promote_wellness(sleep, hrv)
            if values["resting_hr"] is None:
                rhr = safe(lambda: _parse_rhr(client.get_rhr_day(date)), None, f"get_rhr_day {date}")
                values["resting_hr"] = int(rhr) if rhr else None
            activity_archive.upsert_wellness(
                conn, date, values, raw=readiness if date == today_iso else None,
                sleep_raw=sleep, hrv_raw=hrv, fetched_at=_now_iso())

        # The sleep window normally contains today. If fetch_sleep failed outright,
        # today's readiness snapshot still gets banked — and stays unmarked, because
        # we never actually asked Garmin about it.
        if today_iso not in {d for d, _ in sleep_raw}:
            activity_archive.upsert_wellness(conn, today_iso, {
                "resting_hr": readiness.get("restingHR"),
                "hrv": readiness.get("hrv"),
                "sleep_hours": readiness.get("sleepHours"),
            }, raw=readiness)

        log("✓ archive: wellness banked "
            + (f"({len(sleep_raw)} nights)" if sleep_raw else "(today only — no sleep window)"))
    finally:
        conn.close()


def run_wellness_backfill(client, since: str | None = None) -> None:
    """One-time full-history wellness pull. Idempotent and resumable — the
    archive is the cursor, so interrupting never repeats completed work."""
    conn = activity_archive.open_archive(DATA_DIR)
    try:
        cov = activity_archive.coverage(conn)
        if not cov["earliest"]:
            log("! archive holds no activities — run --backfill first")
            return
        earliest = cov["earliest"][:10]
        today = TODAY.isoformat()
        log(f"… wellness backfill: {earliest} → {today}"
            + (f" (bounded by --since {since})" if since else ""))
        stats = backfill_wellness(conn, client, earliest, today, since=since)
        log(f"✓ wellness backfill: {stats['fetched']} banked, "
            f"{stats['skipped']} already present, {stats['failed']} failed")
        if stats["failed"]:
            log("  re-run to retry the failed dates — they were left unmarked")
        done = activity_archive.get_meta(conn, "wellness_backfill_completed_at")
        log(f"  coverage complete: {done}" if done else "  coverage still incomplete")
    finally:
        conn.close()


def _archive_detail_topup(client, conn, limit: int) -> int:
    """Fetch raw detail for archived activities missing it, newest first,
    capped per sync; the per-activity cache makes re-runs free."""
    topped = 0
    for aid in activity_archive.missing_detail_ids(conn, limit=limit):
        det = _fetch_raw_detail(client, aid)
        if det and activity_archive.write_detail(conn, aid, det):
            topped += 1
    return topped


def _distill_pass(conn) -> int:
    """Distill every archived run holding raw detail but no distilled copy —
    both this sync's topped-up runs and (as the recovery pass) runs archived
    before schema v4. Stored payloads in, no network; idempotent — a second
    pass finds nothing to do. Raw payloads are never modified."""
    done = 0
    for aid in activity_archive.runs_missing_distilled(conn):
        distilled = distill_run_detail(
            activity_archive.detail_payload(conn, aid),
            activity_archive.summary_payload(conn, aid) or {})
        if distilled and activity_archive.write_distilled(conn, aid, distilled):
            done += 1
    return done


def _streams_pass(conn) -> int:
    """Write columnar streams for every archived run holding raw detail but no
    streams — this sync's topped-up runs and (as the recovery pass) the whole
    pre-v6 archive. Stored payloads in, no network; idempotent — a second pass
    finds nothing to do. Raw payloads are never modified."""
    done = 0
    for aid in activity_archive.runs_missing_streams(conn):
        streams = distill_run_streams(activity_archive.detail_payload(conn, aid))
        if streams and activity_archive.write_streams(conn, aid, streams):
            done += 1
    return done


def _record_expectations(conn) -> None:
    """Ratchet the coverage expectations --verify-archive checks against: the
    archive never deletes, so the count can only grow and the earliest date
    can only move back — anything else is a regression."""
    cov = activity_archive.coverage(conn)
    prev = activity_archive.get_meta(conn, "expected_activity_count")
    if cov["total"] > int(prev or 0):
        activity_archive.set_meta(conn, "expected_activity_count", cov["total"])
    prev_earliest = activity_archive.get_meta(conn, "expected_earliest")
    if cov["earliest"] and (not prev_earliest or cov["earliest"] < prev_earliest):
        activity_archive.set_meta(conn, "expected_earliest", cov["earliest"])
    # Distilled runs only ever accumulate (raw detail is never deleted and the
    # pass re-runs each sync), so a shrink is a regression.
    dcov = activity_archive.distilled_coverage(conn)
    prev_distilled = activity_archive.get_meta(conn, "expected_distilled_runs")
    if dcov["distilled"] > int(prev_distilled or 0):
        activity_archive.set_meta(conn, "expected_distilled_runs", dcov["distilled"])
    # Streamed runs accumulate the same way (run-detail design D1).
    scov = activity_archive.streams_coverage(conn)
    prev_streamed = activity_archive.get_meta(conn, "expected_streamed_runs")
    if scov["streamed"] > int(prev_streamed or 0):
        activity_archive.set_meta(conn, "expected_streamed_runs", scov["streamed"])
    activity_archive.set_meta(conn, "last_append_at",
                              dt.datetime.now().astimezone().isoformat(timespec="seconds"))


def run_backfill(client) -> None:
    """One-time full-history pull into the archive: year-walk summaries back to
    the account start (detected by two consecutive empty years, not hardcoded),
    then detail for every row missing it. Idempotent and resumable — commits
    are per activity, so interrupting never repeats completed work."""
    conn = activity_archive.open_archive(DATA_DIR)
    try:
        log("… backfill: walking summaries back to the account start")
        year, empty = TODAY.year, 0
        while empty < 2:
            start, end = f"{year}-01-01", f"{year}-12-31"
            acts = safe(lambda: client.get_activities_by_date(start, end), [], f"backfill {year}") or []
            if acts:
                added = activity_archive.upsert_activities(conn, acts)
                log(f"  {year}: {len(acts)} activities ({added} new)")
                empty = 0
            else:
                log(f"  {year}: none")
                empty += 1
            year -= 1

        missing = activity_archive.missing_detail_ids(conn, newest_first=True)
        log(f"… backfill: fetching detail for {len(missing)} activities (throttled)")
        done = 0
        for i, aid in enumerate(missing, 1):
            was_cached = (CACHE_DIR / f"detail-{aid}.json").exists()
            det = _fetch_raw_detail(client, aid)
            if det and activity_archive.write_detail(conn, aid, det):
                done += 1
            if i % 25 == 0:
                log(f"  … {i}/{len(missing)} details")
            if not was_cached:
                time.sleep(0.7)          # gentle on Garmin during the bulk pull
        log(f"✓ backfill detail pass: {done}/{len(missing)} fetched")

        distilled = _distill_pass(conn)
        if distilled:
            log(f"✓ backfill distill pass: {distilled} runs distilled")

        activity_archive.set_meta(conn, "backfill_completed_at",
                                  dt.datetime.now().astimezone().isoformat(timespec="seconds"))
        _record_expectations(conn)
        cov = activity_archive.coverage(conn)
        log(f"✓ backfill complete: {cov['total']} activities "
            f"({cov['with_detail']} with detail), earliest {cov['earliest']}")
    finally:
        conn.close()


def verify_archive() -> int:
    """Report archive coverage; exit non-zero (naming the reason) when it
    regresses against the expectations recorded at backfill/append time."""
    db = activity_archive.archive_path(DATA_DIR)
    if not db.exists():
        warn(f"no archive at {db} — run a sync or `--backfill` first")
        return 2
    conn = activity_archive.open_archive(DATA_DIR)
    try:
        cov = activity_archive.coverage(conn)
        log(f"Archive: {db}  ({db.stat().st_size / 1e6:.1f} MB)")
        log(f"  activities : {cov['total']}  ({cov['earliest']} → {cov['latest']})")
        log(f"  detail     : {cov['with_detail']} with, {cov['without_detail']} missing")
        wcov = activity_archive.wellness_coverage(conn, TODAY.isoformat())
        log(f"  wellness   : {cov['wellness_rows']} daily rows"
            + (f" — {wcov['fetched']}/{wcov['expected']} dates fetched, "
               f"{wcov['with_data']} with data, {len(wcov['gaps'])} gaps"
               if wcov["expected"] else ""))
        if wcov["gaps"]:
            head = ", ".join(wcov["gaps"][:5])
            more = f" … (+{len(wcov['gaps']) - 5} more)" if len(wcov["gaps"]) > 5 else ""
            log(f"               gaps: {head}{more}")
        log("  by year    : " + (", ".join(f"{y}: {n}" for y, n in sorted(cov["by_year"].items())) or "—"))
        log("  by type    : " + (", ".join(f"{t}: {n}" for t, n in list(cov["by_type"].items())[:8]) or "—"))

        dcov = activity_archive.distilled_coverage(conn)
        log(f"  distilled  : {dcov['distilled']}/{dcov['detailed_runs']} detailed runs"
            + (f", {dcov['missing']} missing" if dcov["missing"] else ""))

        scov = activity_archive.streams_coverage(conn)
        log(f"  streams    : {scov['streamed']}/{scov['detailed_runs']} detailed runs"
            + (f", {scov['missing']} missing" if scov["missing"] else ""))

        mcov = activity_archive.metrics_coverage(conn, insight_metrics.METRICS_VERSION)
        log(f"  metrics    : {mcov['at_version']}/{mcov['detailed_runs']} detailed runs at "
            f"v{insight_metrics.METRICS_VERSION}"
            + (f", {mcov['stale']} stale-version rows" if mcov["stale"] else ""))
        log(f"  predictions: {mcov['prediction_rows']} daily rows"
            + (f"  ({mcov['prediction_earliest']} → {mcov['prediction_latest']})"
               if mcov["prediction_rows"] else ""))

        ccov = activity_archive.compliance_coverage(conn, plan_compliance.COMPLIANCE_VERSION)
        log(f"  compliance : {ccov['snapshots']} plan snapshots, "
            f"{ccov['rows']} rows over {ccov['weeks_scored']} weeks"
            + (f" (latest {ccov['latest_scored']})" if ccov["latest_scored"] else "")
            + (f", {ccov['stale']} stale-version rows" if ccov["stale"] else ""))
        try:
            ins = insight_metrics.assemble_insights(conn, TODAY)
            with_data = sum(1 for m in ins["efficiency"]["monthly"]
                            if m["paceSecPerKm"] is not None)
            log(f"  insights   : {len(ins['efficiency']['monthly'])} months "
                f"({with_data} with data), {len(ins['trajectory']['weekly'])} weeks, "
                f"{len(ins['recordsFeed'])} recent records")
        except Exception as ex:  # noqa: BLE001 — verify reports, it doesn't crash
            log(f"  insights   : not assemblable ({type(ex).__name__}: {ex})")

        for key in ("schema_version", "backfill_completed_at", "last_append_at"):
            val = activity_archive.get_meta(conn, key)
            if val:
                log(f"  {key:<21}: {val}")

        failures = []
        expected = activity_archive.get_meta(conn, "expected_activity_count")
        if expected and cov["total"] < int(expected):
            failures.append(f"activity count regressed: {cov['total']} < expected {expected}")
        exp_earliest = activity_archive.get_meta(conn, "expected_earliest")
        if exp_earliest and (cov["earliest"] is None or cov["earliest"] > exp_earliest):
            failures.append(f"earliest activity regressed: {cov['earliest']} > expected {exp_earliest}")
        # Distilled coverage regressions (progress-views design D5). A fully
        # undistilled archive is pre-v4, not a regression — but a partial pass,
        # or a count below the ratchet, means distillation fell behind the raw
        # detail it derives from.
        if dcov["distilled"] and dcov["missing"] > 0:
            failures.append(f"distilled coverage regressed: {dcov['missing']} detailed runs "
                            f"without distilled detail (sync should have distilled them)")
        exp_distilled = activity_archive.get_meta(conn, "expected_distilled_runs")
        if exp_distilled and dcov["distilled"] < int(exp_distilled):
            failures.append(f"distilled coverage regressed: {dcov['distilled']} distilled "
                            f"runs < expected {exp_distilled}")
        # Stream coverage regressions (run-detail design D1). A fully
        # unstreamed archive is pre-v6, not a regression — but a partial pass,
        # or a count below the ratchet, means the stream distiller fell behind
        # the raw detail it derives from.
        if scov["streamed"] and scov["missing"] > 0:
            failures.append(f"stream coverage regressed: {scov['missing']} detailed runs "
                            f"without streams (sync should have distilled them)")
        exp_streamed = activity_archive.get_meta(conn, "expected_streamed_runs")
        if exp_streamed and scov["streamed"] < int(exp_streamed):
            failures.append(f"stream coverage regressed: {scov['streamed']} streamed "
                            f"runs < expected {exp_streamed}")
        # Wellness coverage regressions (wellness-archive design D3/D4). Ratcheted
        # on the backfill's own completion marker, not on the presence of rows:
        # the nightly sync starts stamping `fetched_at` the moment it deploys, so
        # gating on rows alone would fail every check until the backfill has run.
        # Once the backfill claims full coverage, a gap is a genuine regression.
        if activity_archive.get_meta(conn, "wellness_backfill_completed_at") and wcov["gaps"]:
            failures.append(f"wellness coverage regressed: {len(wcov['gaps'])} dates never "
                            f"fetched (first: {wcov['gaps'][0]})")
        # Metrics coverage regressions (design D11). A completely empty
        # run_metrics table is a pre-engine archive, not a regression — but
        # stale-version leftovers or a partial extraction after a sync are.
        if mcov["stale"]:
            failures.append(f"metrics coverage regressed: {mcov['stale']} run_metrics rows "
                            f"at a stale version (sync should have recomputed them)")
        if mcov["at_version"] and mcov["missing"] > 0:
            failures.append(f"metrics coverage regressed: {mcov['missing']} detailed runs "
                            f"without a v{insight_metrics.METRICS_VERSION} row")
        # Compliance coverage regressions (coach-loop). An empty table is a
        # pre-coach-loop archive, not a regression — but stale-version rows
        # after a sync, or fewer scored weeks than the ratchet, are.
        if ccov["stale"]:
            failures.append(f"compliance coverage regressed: {ccov['stale']} rows at a "
                            f"stale version (sync should have rescored them)")
        exp_weeks = activity_archive.get_meta(conn, "expected_compliance_weeks")
        if exp_weeks and ccov["weeks_scored"] < int(exp_weeks):
            failures.append(f"compliance coverage regressed: {ccov['weeks_scored']} scored "
                            f"weeks < expected {exp_weeks}")
        for f in failures:
            warn(f"VERIFY FAILED — {f}")
        if not failures:
            log("✓ archive verification passed")
        return 1 if failures else 0
    finally:
        conn.close()


def main() -> None:
    p = argparse.ArgumentParser(description="SPLITS Garmin sync")
    p.add_argument("--backfill", action="store_true",
                   help="pull the FULL account history into the activity archive "
                        "(one-time; idempotent and resumable)")
    p.add_argument("--backfill-wellness", action="store_true",
                   help="pull the FULL wellness history (sleep + HRV raw payloads) "
                        "into the archive (one-time; idempotent and resumable)")
    p.add_argument("--since", metavar="YYYY-MM-DD",
                   help="lower bound for --backfill-wellness, so a long backfill "
                        "can be spread across nights")
    p.add_argument("--verify-archive", action="store_true",
                   help="report archive coverage and exit non-zero on regression "
                        "(offline — no Garmin login)")
    args = p.parse_args()

    if args.verify_archive:
        raise SystemExit(verify_archive())

    client = connect()
    if args.backfill:
        run_backfill(client)
        return
    if args.backfill_wellness:
        run_wellness_backfill(client, since=args.since)
        return

    # Order per insight-metrics design D8 + coach-loop design D6: archive,
    # metrics and compliance run BEFORE build_data so insights include today's
    # run and the compliance block lands in the contract; the briefing renders
    # strictly AFTER the write. Every step is safe()-wrapped, so garmin-data.js
    # is written with every existing key even if all of them fail.
    acts = load_activities(client)
    safe(lambda: archive_step(client, acts), None, "archive step")
    pred_doc = fetch_raw_predictions(client)
    safe(lambda: metrics_step(client, pred_doc), None, "metrics step")
    safe(compliance_step, None, "compliance step")
    sleep_raw: list = []
    data = build_data(client, acts, pred_doc, sleep_raw_out=sleep_raw)
    validate(data)
    OUTPUT_PATH.write_text(build_garmin_data_js(data), encoding="utf-8")
    log(f"✓ wrote {OUTPUT_PATH.name} — reload the dashboard to see it.")
    safe(lambda: briefing_step(data), None, "coach briefing")
    safe(lambda: wellness_step(client, data["readiness"], sleep_raw), None, "wellness banking")


if __name__ == "__main__":
    main()
