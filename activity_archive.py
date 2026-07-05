#!/usr/bin/env python3
"""
activity_archive.py — the durable activity archive behind sync_garmin.py.

`garmin-data.js` is a rolling window that forgets; this module remembers.
Every synced Garmin activity is stored once (keyed by Garmin's activityId)
in a SQLite database in the data directory, raw-first: the promoted columns
exist only for indexing/queries, the JSON payloads are the source of truth.

Rules (openspec/changes/activity-archive/design.md):
  • upsert semantics — a fresh summary wins, `first_seen_at` is preserved,
    nothing is ever deleted;
  • detail is write-once — only stored on a successful fetch, never
    overwritten (and never with an empty/failed result);
  • default journal mode (DELETE), never WAL — the data dir may sit on an
    SMB mount where WAL is unsafe; the sync lock in serve.mjs is the single
    writer;
  • a corrupt database is quarantined (renamed aside) and recreated — the
    archive is always rebuildable from Garmin via `sync_garmin.py --backfill`.

Stdlib only (sqlite3, json) — no new dependencies in requirements.txt.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import sys
from pathlib import Path

DB_NAME = "activity-archive.db"
SCHEMA_VERSION = 2

# Raw-first schema: summary_json / detail_json / raw_json carry everything
# Garmin returned; the columns are just an index over them (design D2/D9).
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS activities (
  activity_id       INTEGER PRIMARY KEY,
  start_time_local  TEXT NOT NULL,
  type_key          TEXT,
  name              TEXT,
  distance_m        REAL,
  duration_s        REAL,
  avg_hr            INTEGER,
  max_hr            INTEGER,
  avg_cadence       REAL,
  elevation_gain_m  REAL,
  summary_json      TEXT NOT NULL,
  detail_json       TEXT,
  detail_fetched_at TEXT,
  first_seen_at     TEXT NOT NULL,
  updated_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activities_start ON activities(start_time_local);
CREATE INDEX IF NOT EXISTS idx_activities_type  ON activities(type_key);

CREATE TABLE IF NOT EXISTS daily_wellness (
  date        TEXT PRIMARY KEY,
  resting_hr  INTEGER,
  hrv         INTEGER,
  sleep_hours REAL,
  raw_json    TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS archive_meta (
  key   TEXT PRIMARY KEY,
  value TEXT
);
"""

# Schema v2 (insight-metrics, design D2): derived tables only — the raw v1
# tables above are untouched. `run_metrics` rows are a disposable cache of
# deterministic computation keyed by the engine's METRICS_VERSION;
# `race_predictions` banks Garmin's daily race-predictor document.
SCHEMA_V2_SQL = """
CREATE TABLE IF NOT EXISTS run_metrics (
  activity_id      INTEGER PRIMARY KEY REFERENCES activities(activity_id),
  metrics_version  INTEGER NOT NULL,
  start_time_local TEXT NOT NULL,
  is_treadmill     INTEGER NOT NULL,
  best_1k_s REAL, best_mile_s REAL, best_5k_s REAL,
  best_10k_s REAL, best_half_s REAL,
  refhr_time_s REAL, refhr_dist_m REAL,
  refpace_time_s REAL, refpace_cadence_x_time REAL,
  computed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_run_metrics_start ON run_metrics(start_time_local);

CREATE TABLE IF NOT EXISTS race_predictions (
  date TEXT PRIMARY KEY,
  time_5k_s REAL, time_10k_s REAL, half_s REAL, marathon_s REAL,
  raw_json TEXT NOT NULL,
  source TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def archive_path(data_dir: Path) -> Path:
    return Path(data_dir) / DB_NAME


def open_archive(data_dir: Path) -> sqlite3.Connection:
    """Open (or create) the archive, applying schema v1. A corrupt file is
    quarantined by rename and a fresh database created in its place — the
    caller never has to care which happened."""
    db = archive_path(data_dir)
    try:
        return _open(db)
    except sqlite3.DatabaseError:
        quarantine = _quarantine_name(db)
        db.rename(quarantine)
        print(f"  ! archive was corrupt — quarantined as {quarantine.name}, created fresh "
              f"(rebuild history with: python sync_garmin.py --backfill)",
              file=sys.stderr, flush=True)
        return _open(db)


def _open(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db)
    try:
        conn.execute("PRAGMA journal_mode=DELETE")  # trips early on a corrupt file
        conn.executescript(SCHEMA_SQL)
        conn.executescript(SCHEMA_V2_SQL)
        # Forward-only migration: v1→v2 is purely additive (CREATE IF NOT EXISTS
        # above), so "migrating" is just stamping the version. Never downgrade.
        current = get_meta(conn, "schema_version")
        if current is None or int(current) < SCHEMA_VERSION:
            set_meta(conn, "schema_version", str(SCHEMA_VERSION))
        return conn
    except Exception:
        conn.close()
        raise


def _quarantine_name(db: Path) -> Path:
    stamp = dt.date.today().isoformat()
    candidate = db.with_name(f"{db.name}.corrupt-{stamp}")
    if candidate.exists():  # second corruption the same day — disambiguate
        stamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
        candidate = db.with_name(f"{db.name}.corrupt-{stamp}")
    return candidate


# ──────────────────────────────────────────────────────────────────────────────
# activities
# ──────────────────────────────────────────────────────────────────────────────
_UPSERT_SQL = """
INSERT INTO activities (activity_id, start_time_local, type_key, name,
  distance_m, duration_s, avg_hr, max_hr, avg_cadence, elevation_gain_m,
  summary_json, first_seen_at, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(activity_id) DO UPDATE SET
  start_time_local = excluded.start_time_local,
  type_key         = excluded.type_key,
  name             = excluded.name,
  distance_m       = excluded.distance_m,
  duration_s       = excluded.duration_s,
  avg_hr           = excluded.avg_hr,
  max_hr           = excluded.max_hr,
  avg_cadence      = excluded.avg_cadence,
  elevation_gain_m = excluded.elevation_gain_m,
  summary_json     = excluded.summary_json,
  updated_at       = excluded.updated_at
"""


def upsert_activities(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """Upsert raw activity summaries; returns how many were NEW to the archive.
    Fresh summary wins (Garmin-side edits propagate), first_seen_at and any
    stored detail are preserved. Rows without an activityId are skipped."""
    now = _now()
    new = 0
    for a in rows:
        aid = a.get("activityId")
        if aid is None:
            continue
        exists = conn.execute(
            "SELECT 1 FROM activities WHERE activity_id = ?", (aid,)
        ).fetchone() is not None
        atype = (a.get("activityType") or {}).get("typeKey")
        avg_hr = a.get("averageHR")
        max_hr = a.get("maxHR")
        cad = (a.get("averageRunningCadenceInStepsPerMinute")
               or a.get("averageBikingCadenceInRevPerMinute"))
        conn.execute(_UPSERT_SQL, (
            aid,
            a.get("startTimeLocal") or a.get("startTimeGMT") or "",
            atype,
            a.get("activityName"),
            a.get("distance"),
            a.get("duration") or a.get("movingDuration") or a.get("elapsedDuration"),
            int(round(avg_hr)) if avg_hr else None,
            int(round(max_hr)) if max_hr else None,
            cad,
            a.get("elevationGain"),
            json.dumps(a, ensure_ascii=False),
            now,
            now,
        ))
        if not exists:
            new += 1
    conn.commit()
    return new


def write_detail(conn: sqlite3.Connection, activity_id, payload) -> bool:
    """Store the RAW get_activity_details payload, write-once: an empty/failed
    payload is refused, and existing detail is never overwritten. Commits per
    call so an interrupted backfill never loses completed work."""
    if not payload:
        return False
    cur = conn.execute(
        "UPDATE activities SET detail_json = ?, detail_fetched_at = ? "
        "WHERE activity_id = ? AND detail_json IS NULL",
        (json.dumps(payload, ensure_ascii=False), _now(), activity_id),
    )
    conn.commit()
    return cur.rowcount == 1


def missing_detail_ids(conn: sqlite3.Connection, limit: int | None = None,
                       newest_first: bool = True) -> list:
    order = "DESC" if newest_first else "ASC"
    sql = ("SELECT activity_id FROM activities WHERE detail_json IS NULL "
           f"ORDER BY start_time_local {order}")
    if limit is not None:
        rows = conn.execute(sql + " LIMIT ?", (limit,)).fetchall()
    else:
        rows = conn.execute(sql).fetchall()
    return [r[0] for r in rows]


# ──────────────────────────────────────────────────────────────────────────────
# daily wellness
# ──────────────────────────────────────────────────────────────────────────────
def upsert_wellness(conn: sqlite3.Connection, date: str, values: dict, raw) -> None:
    """One row per local date; a later sync the same day refreshes it."""
    conn.execute(
        """INSERT INTO daily_wellness (date, resting_hr, hrv, sleep_hours, raw_json, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(date) DO UPDATE SET
             resting_hr  = excluded.resting_hr,
             hrv         = excluded.hrv,
             sleep_hours = excluded.sleep_hours,
             raw_json    = excluded.raw_json,
             updated_at  = excluded.updated_at""",
        (date, values.get("resting_hr"), values.get("hrv"),
         values.get("sleep_hours"), json.dumps(raw, ensure_ascii=False), _now()),
    )
    conn.commit()


# ──────────────────────────────────────────────────────────────────────────────
# run metrics + race predictions (schema v2 — owned by the insight-metrics
# engine; see insight_metrics.py for the algorithms that fill these tables)
# ──────────────────────────────────────────────────────────────────────────────

# What counts as a run, in SQL — mirrors sync_garmin.is_run() (typeKey contains
# a run word but isn't cycling; covers running/treadmill/trail/track/indoor/
# obstacle/ultra).
_RUN_TYPE_SQL = "(a.type_key LIKE '%run%' AND a.type_key NOT LIKE '%cycling%')"

_RUN_METRICS_COLS = (
    "activity_id", "metrics_version", "start_time_local", "is_treadmill",
    "best_1k_s", "best_mile_s", "best_5k_s", "best_10k_s", "best_half_s",
    "refhr_time_s", "refhr_dist_m", "refpace_time_s", "refpace_cadence_x_time",
)


def runs_missing_metrics(conn: sqlite3.Connection, version: int) -> list[tuple]:
    """(activity_id, start_time_local, type_key) of every archived run that has
    a detail payload but no run_metrics row at `version` — rows at a stale
    version count as missing, which is how a METRICS_VERSION bump self-heals."""
    return conn.execute(
        f"""SELECT a.activity_id, a.start_time_local, a.type_key
            FROM activities a
            LEFT JOIN run_metrics m
              ON m.activity_id = a.activity_id AND m.metrics_version = ?
            WHERE a.detail_json IS NOT NULL
              AND {_RUN_TYPE_SQL}
              AND m.activity_id IS NULL
            ORDER BY a.start_time_local""",
        (version,),
    ).fetchall()


def detail_payload(conn: sqlite3.Connection, activity_id):
    """The parsed raw detail payload for one activity, or None. Fetched one at
    a time — payloads run to hundreds of KB, never load the whole table."""
    row = conn.execute(
        "SELECT detail_json FROM activities WHERE activity_id = ?", (activity_id,)
    ).fetchone()
    return json.loads(row[0]) if row and row[0] else None


def upsert_run_metrics(conn: sqlite3.Connection, row: dict) -> None:
    """INSERT OR REPLACE keyed by activity_id — derived rows are disposable
    (design D2), so a recompute at a newer version simply replaces the stale
    row. Commits per call: an interrupted extraction never repeats done work."""
    conn.execute(
        f"INSERT OR REPLACE INTO run_metrics ({', '.join(_RUN_METRICS_COLS)}, computed_at) "
        f"VALUES ({', '.join('?' * len(_RUN_METRICS_COLS))}, ?)",
        tuple(row.get(c) for c in _RUN_METRICS_COLS) + (_now(),),
    )
    conn.commit()


def upsert_race_prediction(conn: sqlite3.Connection, date: str, values: dict,
                           raw, source: str) -> None:
    """One row per local date; a later sync the same day refreshes it. `values`
    carries the promoted seconds (time_5k_s/time_10k_s/half_s/marathon_s); the
    raw document is kept so a parse fix can re-promote columns later."""
    conn.execute(
        """INSERT INTO race_predictions (date, time_5k_s, time_10k_s, half_s,
                                         marathon_s, raw_json, source, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(date) DO UPDATE SET
             time_5k_s  = excluded.time_5k_s,
             time_10k_s = excluded.time_10k_s,
             half_s     = excluded.half_s,
             marathon_s = excluded.marathon_s,
             raw_json   = excluded.raw_json,
             source     = excluded.source,
             updated_at = excluded.updated_at""",
        (date, values.get("time_5k_s"), values.get("time_10k_s"),
         values.get("half_s"), values.get("marathon_s"),
         json.dumps(raw, ensure_ascii=False), source, _now()),
    )
    conn.commit()


def race_predictions_empty(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM race_predictions LIMIT 1").fetchone() is None


def metrics_coverage(conn: sqlite3.Connection, version: int) -> dict:
    """The metrics section --verify-archive reports: detailed-run vs extracted
    counts, stale-version leftovers, and race_predictions bounds."""
    detailed_runs = conn.execute(
        f"SELECT COUNT(*) FROM activities a WHERE a.detail_json IS NOT NULL AND {_RUN_TYPE_SQL}"
    ).fetchone()[0]
    at_version = conn.execute(
        "SELECT COUNT(*) FROM run_metrics WHERE metrics_version = ?", (version,)
    ).fetchone()[0]
    stale = conn.execute(
        "SELECT COUNT(*) FROM run_metrics WHERE metrics_version != ?", (version,)
    ).fetchone()[0]
    pred_count, pred_earliest, pred_latest = conn.execute(
        "SELECT COUNT(*), MIN(date), MAX(date) FROM race_predictions"
    ).fetchone()
    return {
        "detailed_runs": detailed_runs,
        "at_version": at_version,
        "missing": detailed_runs - at_version,
        "stale": stale,
        "prediction_rows": pred_count,
        "prediction_earliest": pred_earliest,
        "prediction_latest": pred_latest,
    }


# ──────────────────────────────────────────────────────────────────────────────
# meta + coverage (for --verify-archive)
# ──────────────────────────────────────────────────────────────────────────────
def get_meta(conn: sqlite3.Connection, key: str):
    row = conn.execute("SELECT value FROM archive_meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value) -> None:
    conn.execute(
        "INSERT INTO archive_meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
    conn.commit()


def coverage(conn: sqlite3.Connection) -> dict:
    """Everything --verify-archive reports: totals, per-year/type counts,
    detail coverage, wellness rows, date bounds."""
    total = conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
    by_year = dict(conn.execute(
        "SELECT substr(start_time_local, 1, 4) AS y, COUNT(*) FROM activities "
        "GROUP BY y ORDER BY y").fetchall())
    by_type = dict(conn.execute(
        "SELECT COALESCE(type_key, '?'), COUNT(*) FROM activities "
        "GROUP BY type_key ORDER BY COUNT(*) DESC").fetchall())
    with_detail = conn.execute(
        "SELECT COUNT(*) FROM activities WHERE detail_json IS NOT NULL").fetchone()[0]
    wellness = conn.execute("SELECT COUNT(*) FROM daily_wellness").fetchone()[0]
    earliest, latest = conn.execute(
        "SELECT MIN(start_time_local), MAX(start_time_local) FROM activities").fetchone()
    return {
        "total": total,
        "by_year": by_year,
        "by_type": by_type,
        "with_detail": with_detail,
        "without_detail": total - with_detail,
        "wellness_rows": wellness,
        "earliest": earliest,
        "latest": latest,
    }
