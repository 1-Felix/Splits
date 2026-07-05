#!/usr/bin/env python3
"""
coach_briefing.py — renders `coach-briefing.md`, the pre-digested state a
/coach session reads (coach-loop design D6).

Deterministic markdown from already-computed inputs: compliance rows and
run_metrics from the archive, the plan JSON, and the telemetry dict the sync
just wrote to garmin-data.js. Fixed section order, pre-formatted numbers, no
AI — the section list was specced empirically from the 2026-07-05 hand-run of
the coaching ritual (whatever the coach reached for is what's in here).

The two derived signal sections:
  • plan staleness — quality-session pace targets (parsed defensively from the
    plan's free-form pace strings; unparseable → skipped silently) compared to
    demonstrated fitness: the best trailing-84-day outdoor 10k for threshold
    intent, the race block's own goal pace for goal-pace intent;
  • plan integrity — `days: null` on a future week, week-header km that
    disagree with the day sum, a race date in the past.

Written by the sync via temp-file + rename, strictly AFTER garmin-data.js —
a briefing failure is a warning, never a broken contract file.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import tempfile
from pathlib import Path

import activity_archive
import insight_metrics
import plan_compliance

STALENESS_TOLERANCE_S = 10  # s/km deviation before a staleness note fires
FITNESS_WINDOW_DAYS = 84    # same trailing window the trajectory's Riegel uses
GOAL_INTENT_BAND_S = 5      # target within this of goal pace → goal-pace intent
KM_SUM_TOLERANCE = 0.5      # week header km vs day sum
LOG_TAIL = 5
THIN_SAMPLE_MIN = 30        # in-band minutes below which a trend month is thin

_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_PACE_RE = re.compile(r"(\d{1,2}):(\d{2})")


# ──────────────────────────────────────────────────────────────────────────────
# small format helpers (no locale — output must be byte-stable)
# ──────────────────────────────────────────────────────────────────────────────
def _fmt_pace(sec) -> str:
    if not sec:
        return "—"
    return f"{int(sec // 60)}:{int(round(sec % 60)):02d}"


def _fmt_hms(sec) -> str:
    if not sec:
        return "—"
    sec = int(round(sec))
    h, rest = divmod(sec, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _day_name(date_iso: str) -> str:
    return _DAYS[dt.date.fromisoformat(date_iso).weekday()]


def parse_pace_target(s) -> float | None:
    """Seconds/km from a plan pace string — '5:25–5:35' → midpoint, '~6:10' /
    'easy + 5:41' → the value; anything without an m:ss token → None (design
    D6: skip silently, never fail the briefing over authoring style)."""
    if not isinstance(s, str):
        return None
    tokens = [int(m.group(1)) * 60 + int(m.group(2)) for m in _PACE_RE.finditer(s)]
    return sum(tokens) / len(tokens) if tokens else None


def best_10k_pace(conn, today: dt.date) -> float | None:
    """Demonstrated threshold-ish fitness: pace of the best outdoor 10k effort
    in the trailing window, from run_metrics at the current version."""
    since = (today - dt.timedelta(days=FITNESS_WINDOW_DAYS)).isoformat()
    row = conn.execute(
        "SELECT MIN(best_10k_s) FROM run_metrics WHERE is_treadmill = 0 "
        "AND metrics_version = ? AND substr(start_time_local, 1, 10) >= ?",
        (insight_metrics.METRICS_VERSION, since)).fetchone()
    return row[0] / 10.0 if row and row[0] else None


# ──────────────────────────────────────────────────────────────────────────────
# signal sections (design D6)
# ──────────────────────────────────────────────────────────────────────────────
def staleness_notes(conn, plan: dict, today: dt.date) -> list[str]:
    goal_pace = (plan.get("race") or {}).get("goalPaceSecPerKm")
    implied = best_10k_pace(conn, today)
    today_iso = today.isoformat()
    notes = []
    for week in plan.get("block") or []:
        for day in week.get("days") or []:
            if day.get("date", "") < today_iso or day.get("load") != "Hard":
                continue
            target = parse_pace_target(day.get("pace"))
            if target is None:
                continue
            if goal_pace and abs(target - goal_pace) <= GOAL_INTENT_BAND_S:
                if abs(target - goal_pace) > STALENESS_TOLERANCE_S:
                    notes.append(f"{day['date']} {day.get('title')}: target "
                                 f"{_fmt_pace(target)} vs goal pace {_fmt_pace(goal_pace)}")
                continue
            if implied and abs(target - implied) > STALENESS_TOLERANCE_S:
                direction = "slower" if target > implied else "faster"
                notes.append(
                    f"{day['date']} {day.get('title')}: target {_fmt_pace(target)}/km is "
                    f"{abs(round(target - implied))} s/km {direction} than the demonstrated "
                    f"best-10k pace ({_fmt_pace(implied)}/km, trailing {FITNESS_WINDOW_DAYS}d)")
    return notes


def integrity_warnings(plan: dict, today: dt.date) -> list[str]:
    today_iso = today.isoformat()
    race_date = (plan.get("race") or {}).get("date")
    warnings = []
    if race_date and race_date < today_iso:
        warnings.append(f"race date {race_date} is in the past — plan a new block")
    for week in plan.get("block") or []:
        if week.get("sun", "") < today_iso:
            continue  # past weeks may legitimately have retired detail
        days = week.get("days")
        if days is None:
            warnings.append(f"{week.get('wk')} ({week.get('mon')}) has no days — "
                            "the plan must stay detailed to race day")
            continue
        day_sum = sum((d.get("km") or 0) for d in days if d.get("date") != race_date)
        if week.get("km") is not None and abs(day_sum - week["km"]) > KM_SUM_TOLERANCE:
            warnings.append(f"{week.get('wk')}: header says {week['km']} km but its days "
                            f"sum to {round(day_sum, 1)} km")
    return warnings


# ──────────────────────────────────────────────────────────────────────────────
# rendering
# ──────────────────────────────────────────────────────────────────────────────
def _planned_cell(r: dict) -> str:
    if r["planned_kind"] is None:
        return "—"
    km = f" {r['planned_km']:g} km" if r["planned_km"] else ""
    return f"{r['planned_kind']}{km} {r['planned_load'] or ''} ({r['planned_title']})".strip()


def _actual_cell(r: dict, run_notes: dict) -> str:
    if r["actual_km"] is None:
        return "—"
    out = f"{r['actual_km']:g} km"
    if r["actual_pace_s"]:
        out += f" @ {_fmt_pace(r['actual_pace_s'])}/km"
    if r["actual_hr"]:
        out += f" · HR {r['actual_hr']}"
    note = run_notes.get(r["date"])
    if note:
        out += note
    return out


def _status_cell(r: dict) -> str:
    return f"{r['status']} ({r['reason']})" if r.get("reason") else r["status"]


def _week_table(rows: list[dict], run_notes: dict) -> list[str]:
    out = ["| Date | Day | Planned | Actual | Status |",
           "|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['date']} | {_day_name(r['date'])} | {_planned_cell(r)} "
                   f"| {_actual_cell(r, run_notes)} | {_status_cell(r)} |")
    return out


def render_briefing(conn, plan: dict, data: dict, today: dt.date) -> str:
    """The complete briefing text. Raises on missing essentials — the caller
    (sync briefing_step) is safe()-wrapped, so a raise is a warning."""
    race = plan.get("race") or {}
    block = plan.get("block") or []
    insights = data.get("insights")
    L: list[str] = []

    L.append(f"# Coach Briefing — {today.isoformat()}")
    L.append("")
    L.append("Generated by the nightly sync (deterministic — no AI). Read by `/coach`;")
    L.append("numbers match the `garmin-data.js` written in the same sync.")

    # ── race countdown ────────────────────────────────────────────────────
    L.append("")
    L.append("## Race countdown")
    L.append("")
    if race.get("date"):
        days_to = (dt.date.fromisoformat(race["date"]) - today).days
        L.append(f"- **{race.get('name', 'Race')}** ({race.get('location', '—')}): "
                 f"{race['date']} — **{days_to} days**")
        L.append(f"- Goal: {race.get('goalTime', '—')} "
                 f"({_fmt_pace(race.get('goalPaceSecPerKm'))}/km) · PB {race.get('pb', '—')}")
    current = next((w for w in block
                    if w.get("mon", "") <= today.isoformat() <= w.get("sun", "")), None)
    if current:
        L.append(f"- Current week: **{current.get('wk')}** ({current.get('phase')}) — "
                 f"{current.get('focus')}")

    # ── plan vs actual ────────────────────────────────────────────────────
    run_notes = {}
    for r in data.get("recentRuns") or []:
        det = r.get("detail") or {}
        bits = []
        if det.get("tempC") is not None:
            bits.append(f"{det['tempC']} °C")
        if det.get("driftBpm") is not None:
            bits.append(f"drift {det['driftBpm']:+d}")
        if bits:
            run_notes[r["date"]] = " · " + " · ".join(bits)

    all_rows = activity_archive.compliance_rows(conn)
    L.append("")
    L.append("## Plan vs actual")
    scored_any = False
    for week in plan_compliance.weeks_to_score(block, today):
        rows = [r for r in all_rows if r["wk"] == week.get("wk")]
        if not rows:
            continue
        scored_any = True
        closed = week.get("sun", "") < today.isoformat()
        L.append("")
        L.append(f"### {week.get('wk')} ({week.get('mon')} → {week.get('sun')}) — "
                 f"{'closed' if closed else 'open'}")
        L.append("")
        L.extend(_week_table(rows, run_notes))
    if not scored_any:
        L.append("")
        L.append("No compliance rows yet — first sync after deploy, or the plan has no")
        L.append("scoreable weeks.")

    # ── records & best efforts ────────────────────────────────────────────
    L.append("")
    L.append("## Records & best efforts")
    L.append("")
    if insights:
        feed = insights.get("recordsFeed") or []
        if feed:
            for ev in feed[:5]:
                L.append(f"- {ev['date']}: **{ev['distance']}** "
                         f"{_fmt_hms(ev['oldSec'])} → **{_fmt_hms(ev['newSec'])}**")
        else:
            L.append("- no records fell recently")
        be = insights.get("bestEfforts") or {}
        line = []
        for key, label in (("oneK", "1k"), ("mile", "mile"), ("fiveK", "5k"),
                           ("tenK", "10k"), ("half", "half")):
            v = (be.get("allTime") or {}).get(key)
            if v:
                line.append(f"{label} {_fmt_hms(v['sec'])}")
        if line:
            L.append(f"- all-time in-run bests: {' · '.join(line)}")
    else:
        L.append("- insights unavailable this sync")

    # ── trajectory ────────────────────────────────────────────────────────
    L.append("")
    L.append("## Trajectory")
    L.append("")
    if insights:
        traj = insights.get("trajectory") or {}
        weekly = [w for w in traj.get("weekly") or [] if w.get("riegelSec")]
        goal = traj.get("goalSec")
        if weekly and goal:
            last = weekly[-1]
            L.append(f"- honest (Riegel from best efforts): **{_fmt_hms(last['riegelSec'])}** — "
                     f"gap to goal {_fmt_hms(goal)}: "
                     f"{_fmt_hms(last['riegelSec'] - goal)}")
            if last.get("garminSec"):
                L.append(f"- Garmin's predictor: {_fmt_hms(last['garminSec'])}")
        trend = (data.get("predictions") or {}).get("trend")
        if trend:
            L.append(f"- trend: **{trend}**")
    else:
        L.append("- insights unavailable this sync")

    # ── progress trends ───────────────────────────────────────────────────
    L.append("")
    L.append("## Progress trends")
    L.append("")
    if insights:
        for section, val_key, unit in (("efficiency", "paceSecPerKm", "/km"),
                                       ("cadence", "spm", " spm")):
            monthly = (insights.get(section) or {}).get("monthly") or []
            tail = [m for m in monthly if m.get(val_key) is not None][-3:]
            if not tail:
                continue
            parts = []
            for m in tail:
                val = (_fmt_pace(m[val_key]) if val_key == "paceSecPerKm"
                       else f"{m[val_key]:g}")
                caveat = (" (thin sample)" if m.get("inBandMin", 0) < THIN_SAMPLE_MIN
                          else "")
                parts.append(f"{m['month']}: {val}{unit}{caveat}")
            L.append(f"- {section}: " + " → ".join(parts))
    else:
        L.append("- insights unavailable this sync")

    # ── readiness ─────────────────────────────────────────────────────────
    r = data.get("readiness") or {}
    L.append("")
    L.append("## Readiness today")
    L.append("")
    L.append(f"- score {r.get('score', '—')} ({r.get('status', '—')}) · "
             f"HRV {r.get('hrv', '—')} · RHR {r.get('restingHR', '—')} · "
             f"sleep {r.get('sleepHours', '—')} h · load: {r.get('loadStatus', '—')}")

    # ── plan staleness ────────────────────────────────────────────────────
    L.append("")
    L.append("## Plan staleness")
    L.append("")
    notes = staleness_notes(conn, plan, today)
    if notes:
        L.extend(f"- {n}" for n in notes)
    else:
        L.append("- future quality targets are consistent with demonstrated fitness")

    # ── plan integrity ────────────────────────────────────────────────────
    L.append("")
    L.append("## Plan integrity")
    L.append("")
    warnings = integrity_warnings(plan, today)
    if warnings:
        L.extend(f"- ⚠ {w}" for w in warnings)
    else:
        L.append("- plan is fully detailed to race day; week headers match their days")

    # ── coach log tail ────────────────────────────────────────────────────
    L.append("")
    L.append(f"## Coach log (last {LOG_TAIL})")
    L.append("")
    log_entries = ((plan.get("coach") or {}).get("log") or [])[:LOG_TAIL]
    if log_entries:
        for entry in log_entries:
            L.append(f"- **{entry.get('date')}**: {entry.get('text')}")
    else:
        L.append("- no log entries")

    # ── profile constants ─────────────────────────────────────────────────
    p = data.get("profile") or {}
    L.append("")
    L.append("## Profile")
    L.append("")
    L.append(f"- max HR {p.get('maxHR', '—')} · resting HR {p.get('restingHR', '—')} · "
             f"VO2max {p.get('vo2maxCurrent', '—')} · {p.get('weightKg', '—')} kg")
    L.append("")
    return "\n".join(L)


def write_briefing(path, text: str) -> None:
    """Atomic publish: temp file in the same dir, then rename over the target —
    a reader (or a crash) can never observe a half-written briefing."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".coach-briefing-",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
