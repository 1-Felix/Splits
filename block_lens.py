#!/usr/bin/env python3
"""
block_lens.py — the deterministic block-summary engine over the archive.

One engine, three surfaces (openspec/changes/add-block-lens/design.md): the
"The Block" section on /progress, the additive `blockLens` object in
garmin-data.js, and the "Block report" section of coach-briefing.md — all
rendered from the SAME per-block lens document this module derives and stores
in the `block_lens` table (schema v9).

A block is a race, enumerated from `plan_snapshots` (design D1): identity =
`(race.name, race.date)`, window = earliest `week.mon` seen across that race's
snapshots → `race.date`, planned shape from the race's LATEST snapshot. The
block whose race key matches the newest snapshot overall — the live plan — and
whose race date is on or after sync-today is *current*; every sync recomputes
it. Completed blocks freeze at their derived document and recompute only on a
BLOCK_LENS_VERSION bump (self-heal, like run_metrics / plan_compliance).

Rules:
  • rollup, never re-scoring — compliance verdicts are consumed as stored,
    grouped into weeks by date window (labels may drift across snapshots);
  • honesty over extrapolation — any adaptation metric whose window holds
    fewer than MIN_QUALIFYING_RUNS qualifying runs is null with a
    machine-readable reason, never a fabricated value;
  • race-day rows follow the established convention ("race week km excludes
    the race"): they appear in the day drill but stay out of every aggregate;
  • fail-soft — one bad block warns and skips, the driver never raises past
    the sync's safe() wrapper.

Changing ANY algorithm parameter below requires bumping BLOCK_LENS_VERSION —
that is the whole recompute story. Stdlib only.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from statistics import median

import activity_archive
import insight_metrics

# v2 (code-review fixes): a block younger than the adaptation window yields
# null deltas (insufficient-span) instead of a structurally-zero comparison;
# weeks retired from the latest snapshot rejoin the rollup as retired entries;
# an undetailed week's remaining km prorates by its remaining days.
BLOCK_LENS_VERSION = 2

# ──────────────────────────────────────────────────────────────────────────────
# algorithm parameters — all covered by BLOCK_LENS_VERSION
# ──────────────────────────────────────────────────────────────────────────────
ADAPT_WINDOW_DAYS = 14        # EF/cadence: median over the block's first/last 14 days
MIN_QUALIFYING_RUNS = 3       # fewer in a window → null + reason, never a delta
PARTIAL_CREDIT = 0.5          # a partial day's weight in percent-executed
GOAL_ANCHOR_TOLERANCE_DAYS = 14  # predictor row this far from block start still anchors
# A completed block keeps recomputing this long past race day before it
# freezes, so a late-syncing race upload still lands in the retrospective —
# the same rationale as compliance's nightly rescore of the last closed week.
# Lifecycle-only (recompute timing, never document content), so changing it
# needs no version bump.
COMPLETE_GRACE_DAYS = 3

# insight_metrics owns the records vocabulary; reuse it verbatim so the block's
# records feed speaks the same distance labels as insights.recordsFeed
_EFFORT_COLS = insight_metrics.FEED_LABELS  # {"best_5k_s": "5k", …}


def _warn(msg: str) -> None:
    print(f"  ! {msg}", file=sys.stderr, flush=True)


def _fmt_date(d: dt.date) -> str:
    return d.isoformat()


def parse_goal_seconds(goal_time) -> int | None:
    """'1:59:59' → 7199; '59:30' → 3570; anything unparseable → None."""
    if not isinstance(goal_time, str):
        return None
    parts = goal_time.strip().split(":")
    if not (2 <= len(parts) <= 3):
        return None
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if any(n < 0 for n in nums):
        return None
    if len(nums) == 2:
        nums = [0] + nums
    return nums[0] * 3600 + nums[1] * 60 + nums[2]


# ──────────────────────────────────────────────────────────────────────────────
# block enumeration (design D1)
# ──────────────────────────────────────────────────────────────────────────────
def enumerate_blocks(conn) -> list[dict]:
    """One entry per race DATE across all plan snapshots, oldest race first —
    the same key the block_lens table and the archive API use, so a renamed
    race stays one block (the name is an attribute; only a race-date edit
    spawns a new identity). `start` is the earliest week.mon EVER seen for
    the date (weeks may retire from later snapshots); `race_name`/`race`/
    `weeks` come from the date's latest snapshot. The entry the newest
    snapshot overall belongs to is the live plan's block."""
    rows = conn.execute(
        "SELECT id, plan_json FROM plan_snapshots ORDER BY id").fetchall()
    blocks: dict[str, dict] = {}
    last_key = None
    for sid, plan_json in rows:
        try:
            plan = json.loads(plan_json)
        except ValueError:
            continue
        race = plan.get("race") or {}
        date, name = race.get("date"), race.get("name") or ""
        weeks = [w for w in (plan.get("block") or [])
                 if w.get("mon") and w.get("sun")]
        if not date or not weeks:
            continue
        start = min(w["mon"] for w in weeks)
        b = blocks.get(date)
        if b is None:
            blocks[date] = {"race_name": name, "race_date": date, "start": start,
                            "race": race, "weeks": weeks}
        else:
            b["start"] = min(b["start"], start)
            b["race_name"], b["race"], b["weeks"] = name, race, weeks
        last_key = date
    out = sorted(blocks.values(), key=lambda b: b["race_date"])
    for b in out:
        b["is_live"] = last_key == b["race_date"]
    return out


# ──────────────────────────────────────────────────────────────────────────────
# execution rollup (design D3) — grouped by week window, verdicts as stored
# ──────────────────────────────────────────────────────────────────────────────
_STATUSES = ("done", "partial", "missed", "swapped", "unplanned")


def _day_row(r: dict) -> dict:
    d = {"date": r["date"], "plannedKind": r["planned_kind"],
         "plannedKm": r["planned_km"], "plannedLoad": r["planned_load"],
         "title": r["planned_title"], "status": r["status"]}
    if r["reason"]:
        d["reason"] = r["reason"]
    if r["actual_km"] is not None:
        d["actualKm"] = r["actual_km"]
        d["actualPaceS"] = r["actual_pace_s"]
        d["actualHr"] = r["actual_hr"]
    if r["activity_id"] is not None:
        d["activityId"] = r["activity_id"]
    return d


def _planned_day_row(day: dict) -> dict:
    """A drill row for an unscored (future) week, straight from the plan —
    the compliance engine's own no-verdict status keeps consumers uniform."""
    return {"date": day.get("date"), "plannedKind": day.get("kind"),
            "plannedKm": day.get("km"), "plannedLoad": day.get("load"),
            "title": day.get("title"), "status": "pending"}


def build_execution(block: dict, comp_rows: list[dict]) -> tuple[list[dict], dict]:
    """(weeks, execution) for one block. Weeks carry the phase strip fields,
    per-week verdict counts, km and the day-level drill; execution is the
    block-level rollup. Compliance rows keep their stored planned_* fields —
    execution is always measured against what the plan said at the time.

    Verdicts whose dates no snapshot week covers anymore (a week retired by a
    mid-block restructure) still happened inside the block window: they rejoin
    the story as `retired` week entries grouped by calendar week, so nothing
    the athlete ran ever silently vanishes from the rollup or the drill."""
    race_date = block["race_date"]
    totals = {"counts": {s: 0 for s in _STATUSES}, "scored_days": 0,
              "weighted": 0.0, "quality_hit": 0, "quality_of": 0,
              "km_planned_to_date": 0.0, "km_actual": 0.0}

    def score_entry(entry: dict, rows: list[dict]) -> dict:
        counts = {s: 0 for s in _STATUSES}
        actual_km = 0.0
        for r in rows:
            if r["date"] == race_date:  # drill yes, aggregates no
                continue
            if r["status"] in counts:
                counts[r["status"]] += 1
                totals["counts"][r["status"]] += 1
            actual_km += r["actual_km"] or 0
            if r["planned_kind"] is not None and r["status"] != "pending":
                totals["km_planned_to_date"] += r["planned_km"] or 0
                totals["scored_days"] += 1
                if r["status"] in ("done", "swapped"):
                    totals["weighted"] += 1.0
                elif r["status"] == "partial":
                    totals["weighted"] += PARTIAL_CREDIT
                if r["planned_load"] == "Hard":
                    totals["quality_of"] += 1
                    if r["status"] in ("done", "swapped"):
                        totals["quality_hit"] += 1
        totals["km_actual"] += actual_km
        entry.update(scored=True, counts=counts, actualKm=round(actual_km, 1),
                     days=[_day_row(r) for r in rows])
        return entry

    weeks_out = []
    claimed: set[int] = set()
    for w in block["weeks"]:
        idxs = [i for i, r in enumerate(comp_rows)
                if w["mon"] <= r["date"] <= w["sun"]]
        claimed.update(idxs)
        entry = {"wk": w.get("wk"), "mon": w["mon"], "sun": w["sun"],
                 "phase": w.get("phase"), "label": w.get("label"),
                 "focus": w.get("focus"), "plannedKm": w.get("km"),
                 "scored": False}
        if idxs:
            score_entry(entry, [comp_rows[i] for i in idxs])
        else:  # unscored (future) week: planned shape only, no verdicts
            entry["days"] = [_planned_day_row(d) for d in (w.get("days") or [])]
        weeks_out.append(entry)

    retired = [r for i, r in enumerate(comp_rows) if i not in claimed]
    by_week: dict[str, list[dict]] = {}
    for r in retired:
        d = dt.date.fromisoformat(r["date"])
        by_week.setdefault((d - dt.timedelta(days=d.weekday())).isoformat(),
                           []).append(r)
    for mon, rows in by_week.items():
        sun = (dt.date.fromisoformat(mon) + dt.timedelta(days=6)).isoformat()
        weeks_out.append(score_entry(
            {"wk": rows[0].get("wk"), "mon": mon, "sun": sun, "phase": None,
             "label": None, "focus": None, "plannedKm": None, "retired": True},
            rows))
    weeks_out.sort(key=lambda w: w["mon"])

    execution = {
        "percentExecuted": (round(100.0 * totals["weighted"] / totals["scored_days"])
                            if totals["scored_days"] else None),
        "scoredDays": totals["scored_days"],
        "qualityHitRate": {"hit": totals["quality_hit"], "of": totals["quality_of"]},
        "kmPlanned": round(sum(w.get("km") or 0 for w in block["weeks"]), 1),
        "kmPlannedToDate": round(totals["km_planned_to_date"], 1),
        "kmActual": round(totals["km_actual"], 1),
        "counts": totals["counts"],
    }
    return weeks_out, execution


# ──────────────────────────────────────────────────────────────────────────────
# adaptation metrics (design D3) — window-scoped, honest nulls
# ──────────────────────────────────────────────────────────────────────────────
def _window_medians(conn, col: str, since: str, until: str) -> tuple[float | None, int]:
    vals = [r[0] for r in conn.execute(
        f"""SELECT {col} FROM run_metrics
            WHERE metrics_version = ? AND {col} IS NOT NULL
              AND substr(start_time_local, 1, 10) >= ?
              AND substr(start_time_local, 1, 10) <= ?""",
        (insight_metrics.METRICS_VERSION, since, until))]
    if len(vals) < MIN_QUALIFYING_RUNS:
        return None, len(vals)
    return median(vals), len(vals)


def _delta_metric(conn, col: str, start: dt.date, end: dt.date,
                  key_start: str, key_end: str, key_delta: str,
                  ndigits: int) -> dict:
    """Median of `col` over [start, start+13] vs [end-13, end]; null + reason
    when either window is thin. A block whose whole span fits inside one
    window would compare identical medians and report a structurally-zero
    delta — that is no comparison at all, so it is null too, never a fake
    'no change'."""
    first_to = min(start + dt.timedelta(days=ADAPT_WINDOW_DAYS - 1), end)
    last_from = max(end - dt.timedelta(days=ADAPT_WINDOW_DAYS - 1), start)
    m_start, n_start = _window_medians(conn, col, _fmt_date(start), _fmt_date(first_to))
    m_end, n_end = _window_medians(conn, col, _fmt_date(last_from), _fmt_date(end))
    out = {"startRuns": n_start, "endRuns": n_end}
    if m_start is None:
        out.update({key_delta: None, "reason": "insufficient-baseline"})
    elif m_end is None:
        out.update({key_delta: None, "reason": "insufficient-current"})
    elif (end - start).days < ADAPT_WINDOW_DAYS:  # both windows identical
        out.update({key_delta: None, "reason": "insufficient-span"})
    else:
        out.update({key_start: round(m_start, ndigits),
                    key_end: round(m_end, ndigits),
                    key_delta: round(m_end - m_start, ndigits)})
    return out


def _records_in_window(conn, since: str, until: str) -> list[dict]:
    """Per-distance best INSIDE the window beating the all-time best BEFORE it
    — outdoor only (records territory, same policy as insights.recordsFeed).
    Each distance appears at most once: the best in-block effort, deduped by
    construction. A distance with no pre-window history is a baseline, not a
    fallen record."""
    records = []
    for col, label in _EFFORT_COLS.items():
        best = conn.execute(
            f"""SELECT {col}, substr(start_time_local, 1, 10), activity_id
                FROM run_metrics
                WHERE metrics_version = ? AND is_treadmill = 0
                  AND {col} IS NOT NULL
                  AND substr(start_time_local, 1, 10) >= ?
                  AND substr(start_time_local, 1, 10) <= ?
                ORDER BY {col} ASC, start_time_local ASC LIMIT 1""",
            (insight_metrics.METRICS_VERSION, since, until)).fetchone()
        if not best:
            continue
        prev = conn.execute(
            f"""SELECT MIN({col}) FROM run_metrics
                WHERE metrics_version = ? AND is_treadmill = 0
                  AND {col} IS NOT NULL
                  AND substr(start_time_local, 1, 10) < ?""",
            (insight_metrics.METRICS_VERSION, since)).fetchone()[0]
        if prev is not None and best[0] < prev:
            records.append({"distance": label, "sec": round(best[0]),
                            "prevSec": round(prev), "date": best[1],
                            "activityId": best[2]})
    return records


def _goal_gap(conn, race: dict, start: dt.date, end: dt.date) -> dict:
    """Predictor half time nearest block start vs latest in window, against
    the race's goal seconds. The start anchor must sit within the pinned
    tolerance of block start — a months-old row is no baseline."""
    goal_s = parse_goal_seconds(race.get("goalTime"))
    if goal_s is None:
        return {"deltaS": None, "reason": "no-goal-time"}
    preds = [(d, h) for d, h in conn.execute(
        "SELECT date, half_s FROM race_predictions "
        "WHERE half_s IS NOT NULL AND date <= ? ORDER BY date",
        (_fmt_date(end),))]
    if not preds:
        return {"goalS": goal_s, "deltaS": None, "reason": "no-predictions"}
    anchor = min(preds, key=lambda p: abs(
        (dt.date.fromisoformat(p[0]) - start).days))
    if abs((dt.date.fromisoformat(anchor[0]) - start).days) > GOAL_ANCHOR_TOLERANCE_DAYS:
        return {"goalS": goal_s, "deltaS": None, "reason": "no-baseline-prediction"}
    latest = preds[-1]
    gap_start = round(anchor[1] - goal_s)
    gap_now = round(latest[1] - goal_s)
    return {"goalS": goal_s,
            "startDate": anchor[0], "startHalfS": round(anchor[1]),
            "nowDate": latest[0], "nowHalfS": round(latest[1]),
            "gapStartS": gap_start, "gapNowS": gap_now,
            "deltaS": gap_now - gap_start}


def build_adaptation(conn, block: dict, today: dt.date) -> dict:
    start = dt.date.fromisoformat(block["start"])
    race_day = dt.date.fromisoformat(block["race_date"])
    end = min(today, race_day)
    return {
        "ef": _delta_metric(conn, "refhr_pace_s_per_km", start, end,
                            "startPaceSPerKm", "endPaceSPerKm", "deltaSPerKm", 1),
        "cadence": _delta_metric(conn, "refpace_cadence_spm", start, end,
                                 "startSpm", "endSpm", "deltaSpm", 1),
        "records": _records_in_window(conn, block["start"], _fmt_date(end)),
        "goalGap": _goal_gap(conn, block["race"], start, end),
    }


# ──────────────────────────────────────────────────────────────────────────────
# forward tilt (design D3) — current block only
# ──────────────────────────────────────────────────────────────────────────────
def build_forward(block: dict, today: dt.date) -> dict:
    today_iso = today.isoformat()
    race_date = block["race_date"]
    remaining = [w for w in block["weeks"] if w.get("sun", "") >= today_iso]
    km_remaining = 0.0
    for w in remaining:
        days = w.get("days")
        if days is None:
            # undetailed — the header km is all the plan says; prorate a
            # partially-elapsed week by its remaining days so mid-week the
            # already-gone share doesn't inflate what is still runnable
            left = min(7, (dt.date.fromisoformat(w["sun"]) - today).days + 1)
            km_remaining += (w.get("km") or 0) * left / 7.0
        else:
            km_remaining += sum((d.get("km") or 0) for d in days
                                if (d.get("date") or "") >= today_iso
                                and d.get("date") != race_date)
    return {
        "weeksRemaining": len(remaining),
        "kmRemaining": round(km_remaining, 1),
        "silhouette": [{"wk": w.get("wk"), "mon": w.get("mon"),
                        "km": w.get("km"), "phase": w.get("phase")}
                       for w in remaining],
        # same rule as coach_briefing.integrity_warnings: a future week with
        # no days is a plan-integrity gap. Fall back to the week's Monday so
        # an unlabeled week never puts a None into consumers' joins.
        "undetailedWeeks": [w.get("wk") or w.get("mon") for w in remaining
                            if w.get("days") is None],
    }


# ──────────────────────────────────────────────────────────────────────────────
# document assembly + persistence (design D2/D4)
# ──────────────────────────────────────────────────────────────────────────────
def _week_now(weeks: list[dict], today_iso: str) -> int:
    """1-based index of the week containing today; clamped to the block's
    edges so 'week N of M' never reads 0 or M+1 around the boundaries."""
    for i, w in enumerate(weeks):
        if w.get("mon", "") <= today_iso <= w.get("sun", ""):
            return i + 1
    if weeks and today_iso < weeks[0].get("mon", ""):
        return 1
    return len(weeks)


def build_block_document(conn, block: dict, today: dt.date,
                         is_current: bool) -> dict:
    today_iso = today.isoformat()
    is_complete = block["race_date"] < today_iso
    comp_rows = [r for r in activity_archive.compliance_rows(
        conn, since_date=block["start"]) if r["date"] <= block["race_date"]]
    weeks, execution = build_execution(block, comp_rows)
    adaptation = build_adaptation(conn, block, today)

    doc = {
        "raceName": block["race_name"],
        "raceDate": block["race_date"],
        "goalTime": block["race"].get("goalTime"),
        "window": {"start": block["start"], "end": block["race_date"]},
        "isComplete": is_complete,
        "weeksTotal": len(weeks),
        "weeks": weeks,
        "execution": execution,
        "adaptation": adaptation,
    }
    if is_current:
        # over the BUILT list (retired entries included) so "week N of M"
        # counts the same weeks the card renders
        doc["weekNow"] = _week_now(weeks, today_iso)
        doc["forward"] = build_forward(block, today)
    # the headline slice — embedded so the archive API and the past-block list
    # can lift it verbatim (SELECT-and-shape, no derivation downstream)
    doc["summary"] = {
        "raceName": block["race_name"],
        "raceDate": block["race_date"],
        "window": doc["window"],
        "isComplete": is_complete,
        "weeksTotal": len(weeks),
        "percentExecuted": execution["percentExecuted"],
        "kmPlanned": execution["kmPlanned"],
        "kmActual": execution["kmActual"],
        "efDeltaSPerKm": adaptation["ef"].get("deltaSPerKm"),
        "cadenceDeltaSpm": adaptation["cadence"].get("deltaSpm"),
        "goalGapDeltaS": adaptation["goalGap"].get("deltaS"),
        "recordsCount": len(adaptation["records"]),
    }
    return doc


def derive_block_lens(conn, today: dt.date) -> dict:
    """One sync's lens work: recompute the current block always, completed
    blocks only while their race day is inside the grace window (so a
    late-syncing race upload still lands in the retrospective) or when the
    stored row is missing, stale-versioned (a BLOCK_LENS_VERSION bump heals
    every row) or carries an outdated race name. A not-yet-complete block
    that is no longer the live plan (race-date edit) keeps recomputing until
    its own race date passes and it freezes. Per-block failures warn and
    skip — one bad snapshot can never sink the others."""
    blocks = enumerate_blocks(conn)
    today_iso = today.isoformat()
    freeze_before = (today - dt.timedelta(days=COMPLETE_GRACE_DAYS)).isoformat()
    recomputed = 0
    for b in blocks:
        is_current = b["is_live"] and b["race_date"] >= today_iso
        row = activity_archive.block_lens_row(conn, b["race_date"])
        if (row and not is_current and row[0] == BLOCK_LENS_VERSION
                and row[1] == 1 and row[2] == b["race_name"]
                and b["race_date"] < freeze_before):
            continue  # complete, grace over, current version — frozen
        try:
            doc = build_block_document(conn, b, today, is_current)
            activity_archive.upsert_block_lens(
                conn, b["race_date"], b["race_name"], BLOCK_LENS_VERSION,
                doc["isComplete"], doc)
            recomputed += 1
        except Exception as e:  # noqa: BLE001 — fail-soft per block
            _warn(f"block lens derivation failed for {b['race_date']} "
                  f"({type(e).__name__}: {e}); skipping this block")
    return {"blocks": len(blocks), "recomputed": recomputed}


# ──────────────────────────────────────────────────────────────────────────────
# contract assembly (design D4)
# ──────────────────────────────────────────────────────────────────────────────
def assemble_block_lens(conn, today: dt.date) -> dict:
    """The complete `blockLens` object for garmin-data.js, or an exception —
    the caller omits the key entirely rather than emitting a partial one.
    `current` is the live plan's block (full document) when its race is still
    ahead; everything else is a summary in `past`, newest race first."""
    rows = activity_archive.block_lens_rows(conn)
    if not rows:
        raise ValueError("no block lens rows derived yet")
    live = next((b for b in enumerate_blocks(conn) if b["is_live"]), None)
    today_iso = today.isoformat()
    current = None
    past = []
    for race_date, _race_name, _is_complete, doc_json in rows:
        doc = json.loads(doc_json)
        # identity is the race DATE (design D1) — the stored name may lag one
        # derive behind a rename and must not disqualify the current block
        if (current is None and live
                and race_date == live["race_date"]
                and race_date >= today_iso):
            current = doc
        else:
            past.append(doc.get("summary") or {})
    out = {"lensVersion": BLOCK_LENS_VERSION, "past": past}
    if current:
        out["current"] = current
    return out
