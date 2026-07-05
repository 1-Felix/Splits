#!/usr/bin/env python3
"""
validate_data.py — asserts every §3 invariant against the MERGED contract.

Unlike the check inside sync_garmin.py (which only sees the telemetry half before
it's written), this evaluates the real `running-data.js` the way the browser does
— merging garmin-data.js + plan-data.js — by handing it to Node and reading back
`athleteData` as JSON. Run it after a sync, or in CI, so a bad data file can never
reach the dashboard.

    python validate_data.py        # exit 0 = all invariants hold

Requires Node.js on PATH (already needed to serve the dashboard).
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

# Windows consoles default to cp1252, which can't encode the ✓/• glyphs below.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = Path(__file__).parent
# Dynamic-import running-data.js and print athleteData as JSON. The base URL for
# a `node --input-type=module -e` eval is the cwd, so the relative specifier
# resolves against this folder.
NODE_EVAL = (
    "import('./running-data.js')"
    ".then(m => { process.stdout.write(JSON.stringify(m.athleteData ?? m.default)); })"
    ".catch(e => { console.error(e); process.exit(3); });"
)


def load_athlete_data() -> dict:
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", NODE_EVAL],
        cwd=HERE, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        sys.exit(f"✗ could not evaluate running-data.js via Node:\n{proc.stderr.strip()}")
    return json.loads(proc.stdout)


def check(cond: bool, msg: str, errors: list[str]) -> None:
    if not cond:
        errors.append(msg)


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate_insights(ins: dict, e: list[str]) -> None:
    """Shape-check the OPTIONAL `insights` block (insight-metrics design D9).
    The block is only ever emitted whole — a failure here means the engine or
    the contract changed, and the message names the offending member."""
    check(_num(ins.get("metricsVersion")), "insights.metricsVersion must be numeric", e)

    for section, band_key, val_key in (("efficiency", "refHrBand", "paceSecPerKm"),
                                       ("cadence", "refPaceBand", "spm")):
        s = ins.get(section)
        if not isinstance(s, dict):
            check(False, f"insights.{section} must be an object", e)
            continue
        band = s.get(band_key)
        check(isinstance(band, list) and len(band) == 2 and all(_num(v) for v in band),
              f"insights.{section}.{band_key} must be [lo, hi]", e)
        monthly = s.get("monthly")
        check(isinstance(monthly, list) and len(monthly) > 0,
              f"insights.{section}.monthly must be a non-empty list", e)
        for m in monthly if isinstance(monthly, list) else []:
            label = m.get("month", "?") if isinstance(m, dict) else "?"
            if not isinstance(m, dict):
                check(False, f"insights.{section}.monthly entries must be objects", e)
                continue
            check(isinstance(m.get("month"), str) and len(m["month"] or "") == 7,
                  f"insights.{section}.monthly {label} month must be 'YYYY-MM'", e)
            check(m.get(val_key) is None or _num(m.get(val_key)),
                  f"insights.{section}.monthly {label} {val_key} must be numeric or null", e)
            check(_num(m.get("inBandMin")),
                  f"insights.{section}.monthly {label} inBandMin must be numeric", e)

    def _check_effort_table(t, label: str, need_activity_id: bool = False) -> None:
        if not isinstance(t, dict):
            check(False, f"insights.bestEfforts.{label} must be an object", e)
            return
        for key in ("oneK", "mile", "fiveK", "tenK", "half"):
            check(key in t, f"insights.bestEfforts.{label} missing '{key}'", e)
            v = t.get(key)
            check(v is None or (isinstance(v, dict) and _num(v.get("sec"))
                                and isinstance(v.get("date"), str)),
                  f"insights.bestEfforts.{label}.{key} must be null or {{sec, date}}", e)
            if need_activity_id and isinstance(v, dict):
                check(v.get("activityId") is not None,
                      f"insights.bestEfforts.{label}.{key} must carry activityId", e)

    be = ins.get("bestEfforts")
    if not isinstance(be, dict):
        check(False, "insights.bestEfforts must be an object", e)
    else:
        for table in ("allTime", "last90d"):
            _check_effort_table(be.get(table), table)
        # byYear (progress-views) — OPTIONAL: pre-3a blocks stay valid, but an
        # emitted table must hold shape AND carry the click-through activityId
        by_year = be.get("byYear")
        if by_year is not None:
            if not isinstance(by_year, dict):
                check(False, "insights.bestEfforts.byYear must be an object", e)
            else:
                for year, t in by_year.items():
                    check(isinstance(year, str) and len(year) == 4 and year.isdigit(),
                          f"insights.bestEfforts.byYear key {year!r} must be 'YYYY'", e)
                    _check_effort_table(t, f"byYear.{year}", need_activity_id=True)

    # yoy (progress-views) — OPTIONAL: pre-3a blocks stay valid
    yoy = ins.get("yoy")
    if yoy is not None:
        if not isinstance(yoy, dict):
            check(False, "insights.yoy must be an object", e)
        else:
            for year, months in yoy.items():
                check(isinstance(year, str) and len(year) == 4 and year.isdigit(),
                      f"insights.yoy key {year!r} must be 'YYYY'", e)
                check(isinstance(months, list) and 1 <= len(months) <= 12,
                      f"insights.yoy.{year} must be a list of 1–12 months", e)
                for m in months if isinstance(months, list) else []:
                    label = m.get("month", "?") if isinstance(m, dict) else "?"
                    ok = (isinstance(m, dict)
                          and isinstance(m.get("month"), int)
                          and not isinstance(m.get("month"), bool)
                          and 1 <= m["month"] <= 12
                          and _num(m.get("km")) and _num(m.get("runs"))
                          and (m.get("paceSecPerKm") is None
                               or _num(m.get("paceSecPerKm"))))
                    check(ok, f"insights.yoy.{year} month {label} must be "
                              "{month 1-12, km, runs, paceSecPerKm: num|null}", e)

    feed = ins.get("recordsFeed")
    check(isinstance(feed, list), "insights.recordsFeed must be a list", e)
    for ev in feed if isinstance(feed, list) else []:
        ok = (isinstance(ev, dict) and isinstance(ev.get("date"), str)
              and isinstance(ev.get("distance"), str)
              and _num(ev.get("oldSec")) and _num(ev.get("newSec")))
        check(ok, f"insights.recordsFeed entry {ev!r} must be {{date, distance, oldSec, newSec}}", e)

    traj = ins.get("trajectory")
    if not isinstance(traj, dict):
        check(False, "insights.trajectory must be an object", e)
        return
    check(_num(traj.get("goalSec")), "insights.trajectory.goalSec must be numeric", e)
    weekly = traj.get("weekly")
    check(isinstance(weekly, list), "insights.trajectory.weekly must be a list", e)
    for w in weekly if isinstance(weekly, list) else []:
        label = w.get("week", "?") if isinstance(w, dict) else "?"
        ok = (isinstance(w, dict) and isinstance(w.get("week"), str)
              and (w.get("riegelSec") is None or _num(w.get("riegelSec")))
              and (w.get("garminSec") is None or _num(w.get("garminSec"))))
        check(ok, f"insights.trajectory.weekly {label} must be "
                  "{week, riegelSec: num|null, garminSec: num|null}", e)


_COMPLIANCE_STATUSES = {"done", "partial", "missed", "swapped", "unplanned", "pending"}


def validate_compliance(comp: dict, e: list[str]) -> None:
    """Shape-check the OPTIONAL `compliance` block (coach-loop design D5).
    Like insights, it is only ever emitted whole — a failure here means the
    engine or the contract changed, and the message names the member."""
    check(_num(comp.get("complianceVersion")),
          "compliance.complianceVersion must be numeric", e)
    days = comp.get("days")
    check(isinstance(days, list) and len(days) > 0,
          "compliance.days must be a non-empty list", e)
    for d in days if isinstance(days, list) else []:
        label = d.get("date", "?") if isinstance(d, dict) else "?"
        if not isinstance(d, dict):
            check(False, "compliance.days entries must be objects", e)
            continue
        check(isinstance(d.get("date"), str) and len(d.get("date") or "") == 10,
              f"compliance.days {label} date must be YYYY-MM-DD", e)
        check(d.get("status") in _COMPLIANCE_STATUSES,
              f"compliance.days {label} invalid status {d.get('status')!r}", e)
        check(d.get("plannedKind") in (None, "run", "strength", "cross"),
              f"compliance.days {label} invalid plannedKind {d.get('plannedKind')!r}", e)
        check(d.get("reason") in (None, "distance", "intensity"),
              f"compliance.days {label} invalid reason {d.get('reason')!r}", e)
        check(d.get("plannedKind") is not None or d.get("status") == "unplanned",
              f"compliance.days {label} without plannedKind must be status unplanned", e)
        for k in ("plannedKm", "actualKm", "actualPaceS", "actualHr"):
            if k in d and d[k] is not None:
                check(_num(d[k]), f"compliance.days {label} {k} must be numeric", e)
    weeks = comp.get("weeks")
    check(isinstance(weeks, list) and len(weeks) > 0,
          "compliance.weeks must be a non-empty list", e)
    for w in weeks if isinstance(weeks, list) else []:
        label = w.get("wk", "?") if isinstance(w, dict) else "?"
        if not isinstance(w, dict):
            check(False, "compliance.weeks entries must be objects", e)
            continue
        for k in ("wk", "mon", "sun"):
            check(isinstance(w.get(k), str), f"compliance.weeks {label} {k} must be a string", e)
        for k in ("plannedKm", "actualKm", "runsPlanned", "runsDone"):
            check(_num(w.get(k)), f"compliance.weeks {label} {k} must be numeric", e)


def validate(d: dict) -> list[str]:
    e: list[str] = []
    h = d.get("history", {})

    # heatmap
    hm = d.get("heatmapKm", [])
    check(len(hm) == 365, f"heatmapKm must be 365 days (got {len(hm)})", e)

    # vo2 consistency
    vo2 = h.get("vo2max", [])
    if vo2:
        check(abs(d["profile"]["vo2maxCurrent"] - vo2[-1]) < 0.05,
              "profile.vo2maxCurrent must equal history.vo2max[-1]", e)

    # goal pace ≈ goalTime ÷ distance
    race = d.get("race", {})
    if race.get("goalTime") and race.get("distanceKm"):
        parts = [int(x) for x in race["goalTime"].split(":")]
        secs = parts[0] * 3600 + parts[1] * 60 + parts[2] if len(parts) == 3 else parts[0] * 60 + parts[1]
        expected = secs / race["distanceKm"]
        check(abs(expected - race["goalPaceSecPerKm"]) <= 3,
              f"race.goalPaceSecPerKm ({race['goalPaceSecPerKm']}) ≠ goalTime÷distance (~{expected:.0f})", e)

    # plan block — one row per week, each optionally carrying a 7-day `days` plan
    block = d.get("block", [])
    check(isinstance(block, list) and len(block) > 0, "block must be a non-empty list of weeks", e)
    for b in block if isinstance(block, list) else []:
        for key in ("wk", "label", "mon", "sun", "phase", "km", "long", "focus"):
            check(key in b, f"block week {b.get('wk', '?')} missing '{key}'", e)
        days = b.get("days")
        check(days is None or (isinstance(days, list) and len(days) == 7),
              f"block week {b.get('wk', '?')} days must be null or 7 entries "
              f"(got {len(days) if isinstance(days, list) else days!r})", e)
        for day in (days or []):
            for key in ("day", "date", "kind", "title", "load", "km"):
                check(key in day, f"{b.get('wk', '?')} {day.get('day', '?')} missing '{key}'", e)
            check(day.get("kind") in ("run", "strength", "cross"),
                  f"{b.get('wk', '?')} {day.get('day', '?')} invalid kind {day.get('kind')!r}", e)
            check(isinstance(day.get("km"), (int, float)),
                  f"{b.get('wk', '?')} {day.get('day', '?')} km must be numeric", e)
            segs = day.get("segments")
            check(segs is None or (isinstance(segs, list) and all("label" in s and "val" in s for s in segs)),
                  f"{b.get('wk', '?')} {day.get('day', '?')} segments must be a list of {{label, val}}", e)

    # flattened weekPlan alias (running-data.js) — coach-read resolves runs to plan days by date
    wp = d.get("weekPlan", [])
    check(isinstance(wp, list), "weekPlan alias must be a list", e)
    check(all(("date" in w and "kind" in w) for w in wp),
          "every weekPlan day needs date + kind for coach-read to resolve", e)

    # history arrays present, numeric, gap-free
    for k in ("vo2max", "paceSecPerKm", "cadenceSpm", "weeklyKm", "weeklyRuns", "ctl", "atl"):
        arr = h.get(k)
        check(isinstance(arr, list) and len(arr) > 0, f"history.{k} must be a non-empty list", e)
        if isinstance(arr, list):
            check(all(isinstance(v, (int, float)) for v in arr), f"history.{k} has non-numeric / null values", e)

    # pace stored as integer seconds, not a formatted string
    for r in d.get("recentRuns", []):
        check(isinstance(r.get("pace"), (int, float)), f"recentRuns pace must be int seconds (got {r.get('pace')!r})", e)

    # insights block (insight-metrics) — OPTIONAL: pre-engine files stay valid,
    # but when the sync emits it, the shape must hold
    ins = d.get("insights")
    if ins is not None:
        if isinstance(ins, dict):
            validate_insights(ins, e)
        else:
            check(False, "insights must be an object when present", e)

    # compliance block (coach-loop) — OPTIONAL and independent of insights:
    # pre-coach-loop files stay valid, but an emitted block must hold shape
    comp = d.get("compliance")
    if comp is not None:
        if isinstance(comp, dict):
            validate_compliance(comp, e)
        else:
            check(False, "compliance must be an object when present", e)

    # per-run drill-down detail (present once the sync has run Task 2)
    for r in d.get("recentRuns", []):
        det = r.get("detail")
        if det is None:
            continue
        check(isinstance(det.get("splits"), list) and len(det["splits"]) > 0,
              "recentRuns detail.splits must be a non-empty list", e)
        check(all(isinstance(s.get("pace"), int) for s in det.get("splits", [])),
              "recentRuns detail.splits pace must be int seconds", e)
        check(isinstance(det.get("zoneMin"), list) and len(det["zoneMin"]) == 5,
              "recentRuns detail.zoneMin must have 5 entries", e)
        check(isinstance(det.get("driftBpm"), (int, float)),
              "recentRuns detail.driftBpm must be numeric", e)
        check(isinstance(det.get("hrSeries"), list) and len(det["hrSeries"]) > 0,
              "recentRuns detail.hrSeries must be a non-empty list", e)
        check(det.get("splitShape") in ("even", "positive", "negative"),
              f"recentRuns detail.splitShape invalid: {det.get('splitShape')!r}", e)

    return e


def main() -> None:
    data = load_athlete_data()
    errors = validate(data)
    if errors:
        print("✗ validation FAILED:")
        for msg in errors:
            print(f"   • {msg}")
        sys.exit(1)
    hm = data["heatmapKm"]
    print("✓ all invariants hold")
    print(f"   athlete={data['profile']['name']}  today={data.get('today')}  "
          f"heatmap={len(hm)}d  vo2={data['history']['vo2max'][-1]}  "
          f"weeks={len(data['history']['weeklyKm'])}")


if __name__ == "__main__":
    main()
