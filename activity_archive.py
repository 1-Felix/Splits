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
SCHEMA_VERSION = 1

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
        if get_meta(conn, "schema_version") is None:
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
