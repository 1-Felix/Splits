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
