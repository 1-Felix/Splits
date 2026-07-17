#!/usr/bin/env python3
"""
plan_compliance.py — deterministic plan-vs-actual compliance over the archive.

The coach-loop's quantitative half (openspec/changes/coach-loop/design.md):
reads the coach-owned `plan-data.js` through a node child (`tools/
plan-dump.mjs`), banks content-deduped plan snapshots, matches archived
activities to planned days, and scores them coarsely — the deterministic layer
reports, the AI coach judges.

Rules:
  • fail-soft — `load_plan` returns None on ANY problem (unreadable file,
    throwing/looping plan, garbage output); callers skip compliance and the
    briefing, `garmin-data.js` is never at risk (design D1);
  • snapshots are append-only and deduped on the raw file text's SHA-256, and
    scored rows reference the snapshot they were measured against, so a later
    plan edit can never rewrite history (design D2);
  • intent comes from the plan, never re-classified: a planned day's kind /
    load / km decide how its match is scored (design D3/D4);
  • a closed week's targets freeze at its first post-close scoring — nightly
    rescoring of the last closed week (which exists to catch late-syncing
    activities) reuses the snapshot its rows already reference;
  • rows are a disposable cache keyed by COMPLIANCE_VERSION: a bump rescores
    every frozen week against its ORIGINAL snapshot (design D2).

Stdlib only — no new dependencies.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import activity_archive

COMPLIANCE_VERSION = 1

# Scoring constants (design D4) — coarse by design.
DIST_DONE_RATIO = 0.85     # matched km ≥ 85% of planned → distance satisfied
DIST_PARTIAL_RATIO = 0.50  # ≥ 50% → partial; below → missed (and no swap pairing)
EASY_HR_CEILING = 0.85     # Easy/Moderate intent: avg HR above this × max HR → flagged
EASY_LOADS = {"Easy", "Moderate"}

PLAN_DUMP_TIMEOUT_S = float(os.environ.get("SPLITS_PLAN_DUMP_TIMEOUT_S", "10"))

# Env allow-list for the dump child — mirrors plan-io.mjs SAFE_ENV_KEYS: just
# enough for node to start, never the sync's secrets (GARMIN_*, plan token).
SAFE_ENV_KEYS = ("PATH", "SystemRoot", "SYSTEMROOT", "windir",
                 "TEMP", "TMP", "TMPDIR", "HOME", "LANG", "LC_ALL")

_DUMP_SCRIPT = Path(__file__).parent / "tools" / "plan-dump.mjs"


def _warn(msg: str) -> None:
    print(f"  ! {msg}", file=sys.stderr, flush=True)


# ──────────────────────────────────────────────────────────────────────────────
# plan ingestion (design D1)
# ──────────────────────────────────────────────────────────────────────────────
def load_plan(plan_path) -> tuple[str, dict] | None:
    """(raw_text, plan_dict) from the coach-owned plan file, or None on any
    problem — the caller skips compliance + briefing, never raises.

    The plan text is dumped from a temp `.mjs` copy, not the file itself: the
    live plan sits in the data volume, which has no package.json, so node
    would otherwise parse a bare `.js` path as CommonJS and reject the export
    (the same reason plan-io.mjs validates a `.mjs` temp file)."""
    path = Path(plan_path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as ex:
        _warn(f"plan unreadable ({ex}) — skipping compliance")
        return None
    node = shutil.which(os.environ.get("SPLITS_NODE", "node"))
    if not node:
        _warn("node not found on PATH — skipping compliance")
        return None
    env = {k: os.environ[k] for k in SAFE_ENV_KEYS if k in os.environ}
    fd, tmp = tempfile.mkstemp(prefix="plan-dump-", suffix=".mjs")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(raw)
        proc = subprocess.run(
            [node, str(_DUMP_SCRIPT), tmp],
            capture_output=True, text=True, encoding="utf-8", env=env,
            timeout=PLAN_DUMP_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        _warn("plan dump timed out (plan loads too slowly or loops) — skipping compliance")
        return None
    except OSError as ex:
        _warn(f"plan dump failed ({ex}) — skipping compliance")
        return None
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    if proc.returncode != 0:
        _warn(f"plan dump failed: {(proc.stderr or 'unknown reason').strip()} "
              "— skipping compliance")
        return None
    try:
        plan = json.loads(proc.stdout)
    except ValueError:
        _warn("plan dump printed non-JSON — skipping compliance")
        return None
    if not isinstance(plan, dict) or not isinstance(plan.get("block"), list):
        _warn("plan has no block array — skipping compliance")
        return None
    return raw, plan


# ──────────────────────────────────────────────────────────────────────────────
# matcher (design D3)
# ──────────────────────────────────────────────────────────────────────────────
def kind_for_type(type_key) -> str | None:
    """Archived Garmin type_key → plan kind. Cycling is checked first so
    'indoor_cycling' never falls into the run bucket; anything unmapped is
    invisible to the matcher."""
    t = (type_key or "").lower()
    if "cycling" in t or "biking" in t:
        return "cross"
    if "run" in t:
        return "run"
    if "strength" in t:
        return "strength"
    return None


def _acts_for_range(conn, mon: str, sun: str) -> list[dict]:
    """Matchable activities (mapped kind only) in [mon, sun], oldest first."""
    rows = conn.execute(
        "SELECT activity_id, substr(start_time_local, 1, 10), type_key, "
        "       distance_m, duration_s, avg_hr "
        "FROM activities WHERE substr(start_time_local, 1, 10) BETWEEN ? AND ? "
        "ORDER BY start_time_local", (mon, sun)).fetchall()
    acts = []
    for aid, date, tk, dist_m, dur_s, hr in rows:
        kind = kind_for_type(tk)
        if not kind:
            continue
        km = (dist_m or 0) / 1000.0
        acts.append({"id": aid, "date": date, "kind": kind, "km": km,
                     "pace_s": (dur_s / km) if km and dur_s else None,
                     "hr": hr})
    return acts


def _is_run_slot(day: dict) -> bool:
    """A planned day whose compliance is a running question: kind 'run', or a
    hybrid day (cross/strength) that carries planned running km — the live
    plan's 'Spin + Easy Run' Mondays. Hybrid days are scored on their run
    component; same-day activities of the day's own kind are absorbed
    silently so the spin never shows up as noise."""
    return day.get("kind") == "run" or (day.get("km") or 0) > 0


def _score_run(row: dict, day: dict, act: dict, max_hr: int) -> None:
    """Coarse scoring per design D4. Intent (load) comes from the plan; Hard
    sessions are scored on distance alone — rep quality is the coach's call."""
    planned_km = day.get("km") or 0
    ratio = (act["km"] / planned_km) if planned_km else 1.0
    intensity_ok = True
    if day.get("load") in EASY_LOADS and act.get("hr") and max_hr:
        intensity_ok = act["hr"] <= EASY_HR_CEILING * max_hr
    if ratio >= DIST_DONE_RATIO and intensity_ok:
        status, reason = "done", None
    elif ratio < DIST_PARTIAL_RATIO:
        status, reason = "missed", "distance"
    elif ratio < DIST_DONE_RATIO:
        status, reason = "partial", "distance"
    else:
        status, reason = "partial", "intensity"
    row.update(status=status, reason=reason,
               actual_km=round(act["km"], 1),
               actual_pace_s=round(act["pace_s"]) if act["pace_s"] else None,
               actual_hr=act["hr"], activity_id=act["id"])


def score_week(week: dict, acts: list[dict], today: dt.date,
               max_hr: int, snapshot_id: int) -> list[dict]:
    """Compliance rows for one plan week against its archived actuals.
    Pure — no I/O, fully deterministic for a closed week."""
    days = week.get("days") or []
    if not days:
        return []  # undetailed week — the briefing's integrity warning covers it
    today_iso = today.isoformat()
    closed = week["sun"] < today_iso
    unmatched = list(acts)
    rows, swap_candidates = [], []

    def take(date: str, kind: str, absorb: bool = False):
        cands = [a for a in unmatched if a["date"] == date and a["kind"] == kind]
        if not cands:
            return None
        best = max(cands, key=lambda a: a["km"])
        removed = cands if absorb else [best]
        for a in removed:
            unmatched.remove(a)
        return best

    for day in days:
        row = {"date": day["date"], "wk": week.get("wk"),
               "snapshot_id": snapshot_id,
               "compliance_version": COMPLIANCE_VERSION,
               "planned_kind": day.get("kind"), "planned_km": day.get("km"),
               "planned_load": day.get("load"), "planned_title": day.get("title"),
               "status": "pending", "reason": None, "actual_km": None,
               "actual_pace_s": None, "actual_hr": None, "activity_id": None}
        if _is_run_slot(day):
            act = take(day["date"], "run")
            if day.get("kind") != "run":  # hybrid day: absorb its own-kind acts
                take(day["date"], day["kind"], absorb=True)
            if act:
                _score_run(row, day, act, max_hr)
            elif day["date"] < today_iso:
                row["status"] = "missed"
                swap_candidates.append((day, row))
        else:
            act = take(day["date"], day["kind"], absorb=True)
            if act:
                row["status"] = "done"
                row["activity_id"] = act["id"]
            elif day["date"] < today_iso:
                row["status"] = "missed"
        rows.append(row)

    if closed:  # swap pass (design D3): rescue missed run slots at week close
        # Pairs are assigned globally by date proximity (ties: earlier actual,
        # then earlier planned day) so a far missed slot can never steal a run
        # from a nearer one. A run under half the slot's km is no pairing.
        leftover_runs = [a for a in unmatched if a["kind"] == "run"]
        pairs = []
        for day, row in swap_candidates:
            planned_km = day.get("km") or 0
            for a in leftover_runs:
                if planned_km and a["km"] / planned_km < DIST_PARTIAL_RATIO:
                    continue
                pairs.append((abs(_days_apart(a["date"], day["date"])),
                              a["date"], day["date"], day, row, a))
        pairs.sort(key=lambda p: (p[0], p[1], p[2]))
        used_slots, used_acts = set(), set()
        for _, _, _, day, row, a in pairs:
            if id(row) in used_slots or a["id"] in used_acts:
                continue
            used_slots.add(id(row))
            used_acts.add(a["id"])
            unmatched.remove(a)
            _score_run(row, day, a, max_hr)
            if row["status"] == "done":
                row["status"] = "swapped"

    for a in unmatched:  # leftover RUNS are reported; extra rides/strength are life
        if a["kind"] != "run":
            continue
        rows.append({"date": a["date"], "wk": week.get("wk"),
                     "snapshot_id": snapshot_id,
                     "compliance_version": COMPLIANCE_VERSION,
                     "planned_kind": None, "planned_km": None,
                     "planned_load": None, "planned_title": None,
                     "status": "unplanned", "reason": None,
                     "actual_km": round(a["km"], 1),
                     "actual_pace_s": round(a["pace_s"]) if a["pace_s"] else None,
                     "actual_hr": a["hr"], "activity_id": a["id"]})
    return rows


def _days_apart(a: str, b: str) -> int:
    return (dt.date.fromisoformat(a) - dt.date.fromisoformat(b)).days


# ──────────────────────────────────────────────────────────────────────────────
# driver (design D2/D3): bank snapshot, score open + last closed, heal stale
# ──────────────────────────────────────────────────────────────────────────────
def weeks_to_score(block: list[dict], today: dt.date) -> list[dict]:
    """The open week (mon ≤ today ≤ sun) and the most recently closed week —
    the latter is rescored nightly while it lasts to catch late-syncing
    activities, against its frozen snapshot."""
    today_iso = today.isoformat()
    out = []
    closed = [w for w in block if w.get("sun", "") < today_iso]
    if closed:
        out.append(max(closed, key=lambda w: w["sun"]))
    out.extend(w for w in block
               if w.get("mon", "") <= today_iso <= w.get("sun", ""))
    return out


def run_compliance(conn, raw_text: str, plan: dict, today: dt.date,
                   max_hr: int) -> dict:
    """One sync's compliance work. Returns a stats dict for the sync log."""
    snapshot_id = activity_archive.bank_plan_snapshot(
        conn, raw_text, plan, today.isoformat())
    scored = 0
    today_iso = today.isoformat()
    for week in weeks_to_score(plan.get("block") or [], today):
        week_snapshot = snapshot_id
        if week.get("sun", "") < today_iso:  # closed → freeze at first post-close scoring
            week_snapshot = _existing_week_snapshot(conn, week) or snapshot_id
            if week_snapshot != snapshot_id:
                frozen = activity_archive.snapshot_plan(conn, week_snapshot) or {}
                match = next((w for w in frozen.get("block", [])
                              if w.get("mon") == week.get("mon")), None)
                if match is not None:
                    week = match
                else:  # stored rows predate this week's shape — score fresh
                    week_snapshot = snapshot_id
        acts = _acts_for_range(conn, week["mon"], week["sun"])
        rows = score_week(week, acts, today, max_hr, week_snapshot)
        if rows:
            activity_archive.replace_compliance_week(conn, week["mon"], week["sun"], rows)
            scored += 1
    healed = _rescore_stale(conn, today, max_hr)
    return {"snapshot_id": snapshot_id, "weeks_scored": scored,
            "weeks_healed": healed}


def _existing_week_snapshot(conn, week) -> int | None:
    """The snapshot the week's stored rows already reference — looked up by
    the week's DATE WINDOW, never its label: block-local labels ("Wk 1")
    recur across blocks, so a label lookup would freeze a new block's week
    against a previous block's snapshot and rescore the wrong dates."""
    row = conn.execute(
        "SELECT snapshot_id FROM plan_compliance "
        "WHERE date >= ? AND date <= ? LIMIT 1",
        (week.get("mon"), week.get("sun"))).fetchone()
    return row[0] if row else None


def _rescore_stale(conn, today: dt.date, max_hr: int) -> int:
    """COMPLIANCE_VERSION self-heal: every frozen week holding stale-version
    rows is rescored against the snapshot it originally referenced."""
    healed = 0
    for snapshot_id, wk in activity_archive.stale_compliance_weeks(
            conn, COMPLIANCE_VERSION):
        plan = activity_archive.snapshot_plan(conn, snapshot_id)
        week = next((w for w in (plan or {}).get("block", [])
                     if w.get("wk") == wk), None)
        if not week:
            continue  # unknown label — verify-archive keeps flagging the stale rows
        acts = _acts_for_range(conn, week["mon"], week["sun"])
        rows = score_week(week, acts, today, max_hr, snapshot_id)
        activity_archive.replace_compliance_week(conn, week["mon"], week["sun"], rows)
        healed += 1
    return healed


# ──────────────────────────────────────────────────────────────────────────────
# contract assembly (design D5)
# ──────────────────────────────────────────────────────────────────────────────
def assemble_compliance(conn, plan: dict, today: dt.date | None = None) -> dict:
    """The complete `compliance` block for garmin-data.js, or an exception —
    the caller omits the block entirely rather than emitting a partial one.
    Race-day rows are excluded from week aggregates, matching the plan's own
    'race week km excludes the race' convention."""
    block = plan.get("block") or []
    if not block:
        raise ValueError("plan has no block")
    first_mon = min(w["mon"] for w in block if w.get("mon"))
    rows = activity_archive.compliance_rows(conn, since_date=first_mon)
    if not rows:
        raise ValueError("no compliance rows scored yet")
    race_date = (plan.get("race") or {}).get("date")

    days, by_wk = [], {}
    for r in rows:
        d = {"date": r["date"], "wk": r["wk"], "plannedKind": r["planned_kind"],
             "plannedKm": r["planned_km"], "plannedLoad": r["planned_load"],
             "title": r["planned_title"], "status": r["status"]}
        if r["reason"]:
            d["reason"] = r["reason"]
        if r["actual_km"] is not None:
            d["actualKm"] = r["actual_km"]
            d["actualPaceS"] = r["actual_pace_s"]
            d["actualHr"] = r["actual_hr"]
        days.append(d)
        by_wk.setdefault(r["wk"], []).append(r)

    weeks = []
    for w in block:
        rws = by_wk.get(w.get("wk"))
        if not rws:
            continue
        scoreable = [r for r in rws if r["date"] != race_date]
        run_slots = [r for r in scoreable
                     if r["planned_kind"] == "run" or (r["planned_km"] or 0) > 0]
        weeks.append({
            "wk": w["wk"], "mon": w["mon"], "sun": w["sun"],
            "plannedKm": w.get("km"),
            "actualKm": round(sum(r["actual_km"] or 0 for r in scoreable), 1),
            "runsPlanned": len(run_slots),
            "runsDone": sum(1 for r in run_slots
                            if r["status"] in ("done", "swapped")),
        })
    return {"complianceVersion": COMPLIANCE_VERSION, "days": days, "weeks": weeks}
