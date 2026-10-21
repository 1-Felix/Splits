"""The Health Connect shelf's seam with Garmin (spec D2): when Garmin issues a
run the shelf also holds, Garmin wins and the shelf row is pruned. Runs on every
sync and every backfill, before the archive's verify ratchet counts rows."""
import datetime as dt
import json

import activity_archive

GARMIN_CONNECT_SOURCE = "com.garmin.android.apps.connectmobile"

_RUN_TYPE = "(a.type_key LIKE '%run%' AND a.type_key NOT LIKE '%cycling%')"


def _span(start_time_local, duration_s):
    """(start, end) from the archive columns, or None for an unparseable start.
    A missing duration is a zero-length span at the start."""
    try:
        start = dt.datetime.fromisoformat(str(start_time_local).replace(" ", "T"))
    except ValueError:
        return None
    return start, start + dt.timedelta(seconds=float(duration_s or 0))


def _source(summary_json):
    try:
        return (json.loads(summary_json) or {}).get("source")
    except (TypeError, ValueError):
        return None


def resolve_seam(conn) -> list[int]:
    """Prune every shelf row that Garmin owns: it overlaps a non-shelf run, or
    it was written by the Garmin Connect app itself (Garmin has that run by
    construction). Returns the pruned ids, oldest first."""
    garmin = []
    for start, dur in conn.execute(
            "SELECT a.start_time_local, a.duration_s FROM activities a "
            f"WHERE NOT ({activity_archive.shelf_clause()}) AND {_RUN_TYPE}"):
        span = _span(start, dur)
        if span:
            garmin.append(span)
    pruned = []
    rows = conn.execute(
        "SELECT a.activity_id, a.start_time_local, a.duration_s, a.summary_json "
        f"FROM activities a WHERE {activity_archive.shelf_clause()} "
        "ORDER BY a.start_time_local, a.activity_id").fetchall()
    for aid, start, dur, summary_json in rows:
        span = _span(start, dur)
        overlaps = span is not None and any(
            span[0] < g_end and g_start < span[1] for g_start, g_end in garmin)
        # a zero-length span has no interior: count a start inside a Garmin run
        if span is not None and not overlaps and span[0] == span[1]:
            overlaps = any(g_start <= span[0] < g_end for g_start, g_end in garmin)
        if overlaps or _source(summary_json) == GARMIN_CONNECT_SOURCE:
            activity_archive.prune_activity(conn, aid)
            pruned.append(aid)
    return pruned


def shelf_activities(conn) -> list[dict]:
    """A Garmin-shaped projection of every shelf row, newest first, so the
    cockpit's history aggregates can count Health Connect runs (spec D4). Built
    from the archive alone; the splits* keys mark an entry as shelf-sourced so
    the recent-runs and zones fetchers never ask Garmin about it. Never fed to
    the archive's upserts."""
    import ingest_builder  # local: keeps this module's import graph light

    out = []
    rows = conn.execute(
        "SELECT a.activity_id, a.start_time_local, a.type_key, a.distance_m, "
        "a.duration_s, a.avg_hr, a.max_hr, a.summary_json, a.detail_distilled_json "
        f"FROM activities a WHERE {activity_archive.shelf_clause()} "
        "ORDER BY a.start_time_local DESC, a.activity_id DESC").fetchall()
    for aid, start, type_key, dist_m, dur_s, avg_hr, max_hr, summary_json, distilled in rows:
        try:
            run = json.loads(summary_json) or {}
        except (TypeError, ValueError):
            run = {}
        dist = run.get("distanceM", dist_m) or 0
        dur = run.get("durationS", dur_s) or 0
        pace = 0
        try:
            t, km = ingest_builder._effort({**run, "distanceM": dist, "durationS": dur})
            pace = round(t / km) if km > 0 else 0
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            if dist > 0:
                pace = round(dur / (dist / 1000.0))
        try:
            detail = json.loads(distilled) if distilled else None
        except (TypeError, ValueError):
            detail = None
        out.append({
            "activityId": aid,
            "startTimeLocal": run.get("startTimeLocal") or start,
            "activityType": {"typeKey": type_key},
            "distance": dist, "duration": dur,
            "averageHR": run.get("avgHr", avg_hr), "maxHR": run.get("maxHr", max_hr),
            "splitsShelf": True,
            "splitsPaceSecPerKm": pace,
            "splitsType": ingest_builder._type_label(run.get("sportType") or "running"),
            "splitsDetail": detail,
        })
    return out
