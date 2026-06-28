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

import datetime as dt
import json
import math
import os
import sys
from pathlib import Path
from statistics import mean

from dotenv import load_dotenv
from garminconnect import Garmin

# Windows consoles default to cp1252, which can't encode the ✓/… glyphs below.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

HERE = Path(__file__).parent
OUTPUT_PATH = HERE / "garmin-data.js"
CACHE_DIR = HERE / ".garmin_cache"
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
    tokenstore = os.path.expanduser(os.getenv("GARMIN_TOKENSTORE", str(HERE / ".garmin_tokens")))

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
    """Every activity in the lookback window, newest first. Cached per day so
    re-running the sync doesn't keep hammering Garmin."""
    CACHE_DIR.mkdir(exist_ok=True)
    cache = CACHE_DIR / f"activities-{TODAY.isoformat()}.json"
    if cache.exists():
        log(f"✓ activities (cached) {cache.name}")
        return json.loads(cache.read_text(encoding="utf-8"))

    start = (TODAY - dt.timedelta(days=31 * MONTHS + 20)).isoformat()
    log(f"… pulling activities {start} → {TODAY.isoformat()}")
    acts = client.get_activities_by_date(start, TODAY.isoformat()) or []
    cache.write_text(json.dumps(acts, ensure_ascii=False), encoding="utf-8")
    log(f"✓ {len(acts)} activities pulled")
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
    return [series[int(i * step)] for i in range(n)]


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


def fetch_run_detail(client, activity) -> dict | None:
    """Per-run drill-down detail (splits, HR-drift, zones, temp, TE). Cached per
    activity id so re-syncs only fetch genuinely new runs."""
    aid = activity.get("activityId")
    if not aid:
        return None
    CACHE_DIR.mkdir(exist_ok=True)
    cache = CACHE_DIR / f"detail-{aid}.json"
    if cache.exists():
        det = json.loads(cache.read_text(encoding="utf-8"))
    else:
        det = safe(lambda: client.get_activity_details(aid, maxchart=2000, maxpoly=0),
                   None, f"detail {aid}")
        if not det:
            return None
        cache.write_text(json.dumps(det, ensure_ascii=False), encoding="utf-8")

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


def fetch_sleep(client, nights: int = SLEEP_NIGHTS) -> list[dict]:
    out = []
    for i in range(nights):
        d = (TODAY - dt.timedelta(days=nights - i)).isoformat()
        rec = safe(lambda: client.get_sleep_data(d), {}, f"get_sleep_data {d}") or {}
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

    last = sleep[-1] if sleep else {}
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


def fetch_predictions(client, planned_goal: str = "1:59:59") -> dict:
    doc = safe(lambda: client.get_race_predictions(), {}, "get_race_predictions") or {}
    if isinstance(doc, list):
        doc = doc[-1] if doc else {}
    return {
        "fiveK": fmt_hms(doc.get("time5K")),
        "tenK": fmt_hms(doc.get("time10K")),
        "halfNow": fmt_hms(doc.get("timeHalfMarathon")),
        "halfGoal": planned_goal,
        "trend": "",  # filled by build_data once we have last-vs-now
    }


# ──────────────────────────────────────────────────────────────────────────────
# 4. ASSEMBLE + WRITE
# ──────────────────────────────────────────────────────────────────────────────
def build_data(client) -> dict:
    acts = load_activities(client)
    max_hr = int(os.getenv("ATHLETE_MAX_HR", "197"))

    monthly = fetch_monthly(client, acts)
    weekly_km, weekly_runs = fetch_weekly(acts)
    ctl, atl = compute_fitness_fatigue(acts, max_hr)
    sleep = fetch_sleep(client)
    vo2_current = monthly["vo2max"][-1] if monthly["vo2max"] else None

    predictions = fetch_predictions(client)

    return {
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


def main() -> None:
    client = connect()
    data = build_data(client)
    validate(data)
    OUTPUT_PATH.write_text(build_garmin_data_js(data), encoding="utf-8")
    log(f"✓ wrote {OUTPUT_PATH.name} — reload the dashboard to see it.")


if __name__ == "__main__":
    main()
