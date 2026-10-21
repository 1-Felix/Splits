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
