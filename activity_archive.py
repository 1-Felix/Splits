#!/usr/bin/env python3
"""
activity_archive.py — the durable activity archive. TWO producers, ONE schema:

  • sync_garmin.py (Garmin instances): every synced activity, keyed by
    Garmin's activityId — the original and still the primary producer;
  • ingest_builder.py (ingest-fed instances, add-ingest-archive): every
    banked Health Connect run, keyed by a derived 48-bit hash of its session
    UID, written on the instance's OWN volume. That file is a disposable
    derived cache — deleting it is always safe, the next build regenerates
    it completely (with identical ids) from ingested-runs.json.

This module owns the schema for both; serve.mjs's archive API is the single
read window over either file and never knows which pipeline wrote it.

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
import hashlib
import json
import math
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

DB_NAME = "activity-archive.db"
SCHEMA_VERSION = 9

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
  refhr_pace_s_per_km REAL, refpace_cadence_spm REAL,
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

# Schema v3 (coach-loop, design D2/D3): plan snapshots + compliance — derived
# tables only, raw v1/v2 tables untouched. `plan_snapshots` is append-only and
# content-deduped so a later plan edit can never rewrite what a past day was
# scored against; `plan_compliance` rows are a disposable cache keyed by the
# engine's COMPLIANCE_VERSION (like run_metrics), always recomputable from
# snapshots + activities.
SCHEMA_V3_SQL = """
CREATE TABLE IF NOT EXISTS plan_snapshots (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  sha256          TEXT NOT NULL UNIQUE,
  first_seen_date TEXT NOT NULL,
  plan_json       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plan_compliance (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  date               TEXT NOT NULL,
  wk                 TEXT,
  snapshot_id        INTEGER NOT NULL REFERENCES plan_snapshots(id),
  compliance_version INTEGER NOT NULL,
  planned_kind       TEXT,
  planned_km         REAL,
  planned_load       TEXT,
  planned_title      TEXT,
  status             TEXT NOT NULL,
  reason             TEXT,
  actual_km          REAL,
  actual_pace_s      REAL,
  actual_hr          INTEGER,
  activity_id        INTEGER,
  updated_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plan_compliance_date ON plan_compliance(date);
"""


# Schema v4 (progress-views, design D5): ONE additive column on activities —
# the run's distilled detail, byte-for-byte the recent-run `detail` contract of
# garmin-data.js, pre-computed by the sync's distiller so the archive API can
# serve it verbatim. detail_json stays the untouched source of truth; the
# distilled copy is derived and always recomputable from it. SQLite has no
# "ADD COLUMN IF NOT EXISTS", so idempotency comes from the pragma check.
def _apply_schema_v4(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(activities)")}
    if "detail_distilled_json" not in cols:
        conn.execute("ALTER TABLE activities ADD COLUMN detail_distilled_json TEXT")


# Schema v5 (wellness-archive, design D1/D3): additive columns on daily_wellness.
# `sleep_json` / `hrv_json` are the raw Garmin payloads (upgrade-only — a night
# holding device data is never overwritten, a hollow one may be filled in later);
# the rest are the promoted projection of them, all independently nullable.
# `fetched_at` separates "we asked and the watch recorded nothing" from "we never
# asked" — without it a chart cannot tell a real gap from a missing fetch.
# NOTE: `raw_json` predates this and holds the sync's COMPUTED READINESS snapshot,
# not a Garmin payload. It keeps that meaning; see design D2.
_WELLNESS_V5_COLUMNS = (
    ("sleep_json", "TEXT"), ("hrv_json", "TEXT"), ("fetched_at", "TEXT"),
    ("sleep_seconds", "INTEGER"), ("deep_seconds", "INTEGER"),
    ("rem_seconds", "INTEGER"), ("light_seconds", "INTEGER"),
    ("awake_seconds", "INTEGER"), ("sleep_score", "INTEGER"),
    ("respiration_avg", "REAL"), ("body_battery_change", "INTEGER"),
    ("hrv_last_night", "INTEGER"), ("hrv_weekly_avg", "INTEGER"),
    ("hrv_balanced_low", "INTEGER"), ("hrv_balanced_upper", "INTEGER"),
    ("hrv_status", "TEXT"),
)


def _apply_schema_v5(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(daily_wellness)")}
    for name, decl in _WELLNESS_V5_COLUMNS:
        if name not in cols:
            conn.execute(f"ALTER TABLE daily_wellness ADD COLUMN {name} {decl}")


# Schema v6 (run-detail, design D1): ONE additive column on activities — the
# run's full sample stream reshaped to rounded COLUMNS (t/d/hr/v/gap/cad/elev/
# pwr/lat/lon/pc), written by the sync's stream distiller and served verbatim by
# the archive API's /streams endpoint. Like detail_distilled_json it is derived
# and disposable: detail_json stays the untouched source of truth and a
# recompute simply replaces the streams. (v5 belongs to wellness-archive; both
# migrations are additive and guarded, so either lands first without conflict.)
def _apply_schema_v6(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(activities)")}
    if "detail_streams_json" not in cols:
        conn.execute("ALTER TABLE activities ADD COLUMN detail_streams_json TEXT")


# Schema v7 (chart-drill, design D3): TWO additive NULL-able columns on
# run_metrics — the run's own reference-band display values, written by the
# insight engine at its METRICS_VERSION bump so the archive API can serve them
# verbatim (derivation stays in Python). Like every run_metrics column they are
# derived and disposable; the version bump's self-heal fills them with no
# manual step. The CREATE above carries them for fresh databases; this guarded
# ALTER upgrades existing ones.
def _apply_schema_v7(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(run_metrics)")}
    for name in ("refhr_pace_s_per_km", "refpace_cadence_spm"):
        if name not in cols:
            conn.execute(f"ALTER TABLE run_metrics ADD COLUMN {name} REAL")


# Schema v8 (route-basemap, design D2/D8): map tiles for the run-detail trace.
# `map_tiles` is deduped GLOBALLY — one row per unique OSM tile, shared by
# every run through the same neighbourhood; blobs are the tile PNGs verbatim.
# `activity_maps` records each run's tile rect plus its crop box (world pixels
# at the row's zoom) so the client never re-derives the framing heuristics.
# A run's row exists only when its rect is COMPLETE in map_tiles (design D6);
# both tables are additive, raw v1 tables untouched.
SCHEMA_V8_SQL = """
CREATE TABLE IF NOT EXISTS map_tiles (
  z          INTEGER NOT NULL,
  x          INTEGER NOT NULL,
  y          INTEGER NOT NULL,
  png        BLOB NOT NULL,
  fetched_at TEXT NOT NULL,
  PRIMARY KEY (z, x, y)
);

CREATE TABLE IF NOT EXISTS activity_maps (
  activity_id INTEGER PRIMARY KEY REFERENCES activities(activity_id),
  z           INTEGER NOT NULL,
  x0          INTEGER NOT NULL,
  y0          INTEGER NOT NULL,
  x1          INTEGER NOT NULL,
  y1          INTEGER NOT NULL,
  crop_x      REAL NOT NULL,
  crop_y      REAL NOT NULL,
  crop_size   REAL NOT NULL,
  updated_at  TEXT NOT NULL
);
"""


# Schema v9 (add-block-lens, design D2): ONE derived table — one row per
# training block, keyed by its race date. `block_json` is the FULL lens
# document (weeks, drill rows, adaptation metrics, forward tilt); the promoted
# columns are just the index over it. Disposable-cache semantics like
# run_metrics / plan_compliance: always recomputable from plan_snapshots ×
# plan_compliance × run_metrics × race_predictions, keyed by the engine's
# BLOCK_LENS_VERSION (see block_lens.py).
SCHEMA_V9_SQL = """
CREATE TABLE IF NOT EXISTS block_lens (
  race_date    TEXT PRIMARY KEY,
  race_name    TEXT NOT NULL,
  lens_version INTEGER NOT NULL,
  is_complete  INTEGER NOT NULL,
  block_json   TEXT NOT NULL,
  updated_at   TEXT NOT NULL
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
        conn.executescript(SCHEMA_V3_SQL)
        _apply_schema_v4(conn)
        _apply_schema_v5(conn)
        _apply_schema_v6(conn)
        _apply_schema_v7(conn)
        conn.executescript(SCHEMA_V8_SQL)
        conn.executescript(SCHEMA_V9_SQL)
        # Forward-only migration: v1→…→v9 is purely additive (CREATE IF
        # NOT EXISTS / guarded ALTER above), so "migrating" is just stamping
        # the version. Never downgrade.
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
# Every column of daily_wellness that is a derived projection of the raw payloads.
# `resting_hr` / `hrv` / `sleep_hours` are the v1 columns, still populated.
# This tuple is the single source of truth for the projection: sync_garmin's
# promote_wellness() returns exactly these keys, and a test pins the two together.
WELLNESS_PROMOTED_COLUMNS = (
    "resting_hr", "hrv", "sleep_hours",
    "sleep_seconds", "deep_seconds", "rem_seconds", "light_seconds",
    "awake_seconds", "sleep_score", "respiration_avg", "body_battery_change",
    "hrv_last_night", "hrv_weekly_avg", "hrv_balanced_low",
    "hrv_balanced_upper", "hrv_status",
)


def upsert_wellness(conn: sqlite3.Connection, date: str, values: dict, raw=None,
                    sleep_raw=None, hrv_raw=None, fetched_at: str | None = None) -> None:
    """One row per local date; a later sync the same day refreshes it.

    Three storage rules, each load-bearing:

    * **Promoted columns** (`values`) are derived from the raw payloads and are
      always refreshed — they are recomputable, so they are never authoritative.
    * **`raw_json`** holds the sync's COMPUTED READINESS snapshot, not a Garmin
      payload (design D2). A backfill has no readiness for a past date and must
      not erase one that exists, so it is only replaced when `raw` is supplied.
    * **`sleep_json` / `hrv_json`** are the raw Garmin payloads, stored
      **upgrade-only**: a stored payload that carries device data is never
      replaced, but a hollow one may be filled in later. Garmin does not finalise
      last night's sleep until you wake, and `fetch_sleep()` re-fetches the same
      fourteen nights every sync — a literal write-once would freeze the hollow
      payload for the newest night forever.

    `fetched_at` records that the date was ASKED about. A row with a timestamp and
    null metrics means the watch recorded nothing; no row (or no timestamp) means
    the date was never fetched. Nothing else can tell those apart.
    """
    prior = conn.execute(
        "SELECT raw_json, sleep_json, hrv_json, fetched_at, sleep_seconds, hrv_last_night "
        "FROM daily_wellness WHERE date = ?", (date,)).fetchone()
    p_raw, p_sleep, p_hrv, p_fetched, p_sleep_secs, p_hrv_last = prior or (None,) * 6

    def _upgrade(stored, incoming, stored_has_data):
        """Keep a night that has data; fill in one that does not."""
        if incoming is None:
            return stored
        if stored is not None and stored_has_data:
            return stored
        return json.dumps(incoming, ensure_ascii=False)

    cols = ("date", *WELLNESS_PROMOTED_COLUMNS,
            "raw_json", "sleep_json", "hrv_json", "fetched_at", "updated_at")
    row = (
        date,
        *(values.get(c) for c in WELLNESS_PROMOTED_COLUMNS),
        json.dumps(raw, ensure_ascii=False) if raw is not None else (p_raw or "{}"),
        _upgrade(p_sleep, sleep_raw, p_sleep_secs is not None),
        _upgrade(p_hrv, hrv_raw, p_hrv_last is not None),
        fetched_at or p_fetched,
        _now(),
    )
    conn.execute(
        f"INSERT OR REPLACE INTO daily_wellness ({', '.join(cols)}) "
        f"VALUES ({', '.join('?' * len(cols))})", row)
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
    "refhr_pace_s_per_km", "refpace_cadence_spm",
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


# ──────────────────────────────────────────────────────────────────────────────
# plan snapshots + compliance (schema v3 — owned by the coach-loop engine;
# see plan_compliance.py for the matcher/scoring that fills these tables)
# ──────────────────────────────────────────────────────────────────────────────
def bank_plan_snapshot(conn: sqlite3.Connection, raw_text: str,
                       plan_json: dict, seen_date: str) -> int:
    """Bank the plan append-only, deduped on the raw file text's SHA-256:
    an unchanged plan across many syncs stays one row. Returns the snapshot id
    (existing or new) — compliance rows reference it so a later edit can never
    change what a scored day was measured against."""
    sha = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    row = conn.execute("SELECT id FROM plan_snapshots WHERE sha256 = ?", (sha,)).fetchone()
    if row:
        return row[0]
    cur = conn.execute(
        "INSERT INTO plan_snapshots (sha256, first_seen_date, plan_json) VALUES (?, ?, ?)",
        (sha, seen_date, json.dumps(plan_json, ensure_ascii=False)))
    conn.commit()
    return cur.lastrowid


def snapshot_plan(conn: sqlite3.Connection, snapshot_id: int) -> dict | None:
    row = conn.execute(
        "SELECT plan_json FROM plan_snapshots WHERE id = ?", (snapshot_id,)).fetchone()
    return json.loads(row[0]) if row else None


_COMPLIANCE_COLS = (
    "date", "wk", "snapshot_id", "compliance_version", "planned_kind",
    "planned_km", "planned_load", "planned_title", "status", "reason",
    "actual_km", "actual_pace_s", "actual_hr", "activity_id",
)


def replace_compliance_week(conn: sqlite3.Connection, mon: str, sun: str,
                            rows: list[dict]) -> None:
    """Idempotent week rescore: drop every row in [mon, sun] and insert the
    fresh scoring in one transaction — recomputing a week twice with the same
    inputs yields byte-identical rows (modulo updated_at)."""
    now = _now()
    conn.execute("DELETE FROM plan_compliance WHERE date >= ? AND date <= ?", (mon, sun))
    conn.executemany(
        f"INSERT INTO plan_compliance ({', '.join(_COMPLIANCE_COLS)}, updated_at) "
        f"VALUES ({', '.join('?' * len(_COMPLIANCE_COLS))}, ?)",
        [tuple(r.get(c) for c in _COMPLIANCE_COLS) + (now,) for r in rows])
    conn.commit()


def compliance_rows(conn: sqlite3.Connection, since_date: str | None = None) -> list[dict]:
    """Stored compliance rows as dicts, oldest first (unplanned rows sort after
    the planned row of the same date)."""
    sql = (f"SELECT {', '.join(_COMPLIANCE_COLS)} FROM plan_compliance "
           "WHERE date >= ? ORDER BY date, planned_kind IS NULL, id")
    rows = conn.execute(sql, (since_date or "",)).fetchall()
    return [dict(zip(_COMPLIANCE_COLS, r)) for r in rows]


def stale_compliance_weeks(conn: sqlite3.Connection, version: int) -> list[tuple]:
    """(snapshot_id, wk) of every scored week holding rows at a stale version —
    how a COMPLIANCE_VERSION bump self-heals, rescoring each frozen week
    against the snapshot it originally referenced."""
    return conn.execute(
        "SELECT DISTINCT snapshot_id, wk FROM plan_compliance "
        "WHERE compliance_version != ? ORDER BY wk", (version,)).fetchall()


def compliance_coverage(conn: sqlite3.Connection, version: int) -> dict:
    """The compliance section --verify-archive reports: snapshot count, scored
    rows/weeks, stale-version leftovers, latest scored date."""
    snapshots = conn.execute("SELECT COUNT(*) FROM plan_snapshots").fetchone()[0]
    rows, latest = conn.execute(
        "SELECT COUNT(*), MAX(date) FROM plan_compliance").fetchone()
    weeks = conn.execute(
        "SELECT COUNT(DISTINCT wk) FROM plan_compliance").fetchone()[0]
    stale = conn.execute(
        "SELECT COUNT(*) FROM plan_compliance WHERE compliance_version != ?",
        (version,)).fetchone()[0]
    return {"snapshots": snapshots, "rows": rows, "weeks_scored": weeks,
            "stale": stale, "latest_scored": latest}


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
# block lens (schema v9 — owned by the block-lens engine; see block_lens.py
# for the derivation that fills this table)
# ──────────────────────────────────────────────────────────────────────────────
def upsert_block_lens(conn: sqlite3.Connection, race_date: str, race_name: str,
                      lens_version: int, is_complete: bool, doc: dict) -> None:
    """INSERT OR REPLACE keyed by race_date — derived rows are disposable
    (design D2), so a recompute simply replaces the stale row. Commits per
    call: an interrupted derivation never repeats done work."""
    conn.execute(
        "INSERT OR REPLACE INTO block_lens "
        "(race_date, race_name, lens_version, is_complete, block_json, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (race_date, race_name, lens_version, 1 if is_complete else 0,
         json.dumps(doc, ensure_ascii=False), _now()))
    conn.commit()


def block_lens_row(conn: sqlite3.Connection, race_date: str) -> tuple | None:
    """(lens_version, is_complete) for one block, or None — the derivation
    driver's skip check (a complete row at the current version is frozen)."""
    return conn.execute(
        "SELECT lens_version, is_complete FROM block_lens WHERE race_date = ?",
        (race_date,)).fetchone()


def block_lens_rows(conn: sqlite3.Connection) -> list[tuple]:
    """(race_date, race_name, is_complete, block_json) of every stored block,
    newest race first — the assembly order the data contract promises."""
    return conn.execute(
        "SELECT race_date, race_name, is_complete, block_json "
        "FROM block_lens ORDER BY race_date DESC").fetchall()


def block_lens_coverage(conn: sqlite3.Connection, version: int) -> dict:
    """The block-lens section --verify-archive reports: block count, complete
    count, stale-version leftovers, the latest race date."""
    blocks, latest = conn.execute(
        "SELECT COUNT(*), MAX(race_date) FROM block_lens").fetchone()
    complete = conn.execute(
        "SELECT COUNT(*) FROM block_lens WHERE is_complete = 1").fetchone()[0]
    stale = conn.execute(
        "SELECT COUNT(*) FROM block_lens WHERE lens_version != ?",
        (version,)).fetchone()[0]
    return {"blocks": blocks, "complete": complete, "stale": stale,
            "latest_race": latest}


# ──────────────────────────────────────────────────────────────────────────────
# distilled run detail (schema v4 — filled by sync_garmin's distiller; the
# archive API serves detail_distilled_json verbatim, never the raw payloads)
# ──────────────────────────────────────────────────────────────────────────────
def write_distilled(conn: sqlite3.Connection, activity_id, distilled) -> bool:
    """Store a run's distilled detail. Unlike raw detail (write-once), the
    distilled copy is derived and disposable — a recompute simply replaces it.
    Empty payloads are refused; commits per call so an interrupted pass never
    loses completed work."""
    if not distilled:
        return False
    cur = conn.execute(
        "UPDATE activities SET detail_distilled_json = ? WHERE activity_id = ?",
        (json.dumps(distilled, ensure_ascii=False), activity_id),
    )
    conn.commit()
    return cur.rowcount == 1


def runs_missing_distilled(conn: sqlite3.Connection) -> list:
    """activity_ids of archived runs holding raw detail but no distilled copy —
    the distillation pass's work list, oldest first."""
    rows = conn.execute(
        f"""SELECT a.activity_id FROM activities a
            WHERE a.detail_json IS NOT NULL
              AND a.detail_distilled_json IS NULL
              AND {_RUN_TYPE_SQL}
            ORDER BY a.start_time_local""").fetchall()
    return [r[0] for r in rows]


def summary_payload(conn: sqlite3.Connection, activity_id):
    """The parsed raw summary payload for one activity, or None — the
    distiller needs it alongside the detail payload (zones, temp, TE, load)."""
    row = conn.execute(
        "SELECT summary_json FROM activities WHERE activity_id = ?", (activity_id,)
    ).fetchone()
    return json.loads(row[0]) if row and row[0] else None


def distilled_coverage(conn: sqlite3.Connection) -> dict:
    """The distilled section --verify-archive reports: runs holding raw detail
    vs runs holding the distilled copy."""
    detailed_runs = conn.execute(
        f"SELECT COUNT(*) FROM activities a "
        f"WHERE a.detail_json IS NOT NULL AND {_RUN_TYPE_SQL}").fetchone()[0]
    distilled = conn.execute(
        f"SELECT COUNT(*) FROM activities a "
        f"WHERE a.detail_distilled_json IS NOT NULL AND {_RUN_TYPE_SQL}").fetchone()[0]
    return {"detailed_runs": detailed_runs, "distilled": distilled,
            "missing": detailed_runs - distilled}


# ──────────────────────────────────────────────────────────────────────────────
# columnar run streams (schema v6 — filled by sync_garmin's stream distiller;
# the archive API serves detail_streams_json verbatim, never the raw payloads)
# ──────────────────────────────────────────────────────────────────────────────
def write_streams(conn: sqlite3.Connection, activity_id, streams) -> bool:
    """Store a run's columnar sample streams. Like the distilled detail they
    are derived and disposable — a recompute simply replaces them. Empty
    payloads are refused; commits per call so an interrupted pass never loses
    completed work."""
    if not streams:
        return False
    cur = conn.execute(
        "UPDATE activities SET detail_streams_json = ? WHERE activity_id = ?",
        (json.dumps(streams, ensure_ascii=False, separators=(",", ":")), activity_id),
    )
    conn.commit()
    return cur.rowcount == 1


def runs_missing_streams(conn: sqlite3.Connection) -> list:
    """activity_ids of archived runs holding raw detail but no stream columns —
    the stream pass's work list (and the recovery pass over a pre-v6 archive),
    oldest first."""
    rows = conn.execute(
        f"""SELECT a.activity_id FROM activities a
            WHERE a.detail_json IS NOT NULL
              AND a.detail_streams_json IS NULL
              AND {_RUN_TYPE_SQL}
            ORDER BY a.start_time_local""").fetchall()
    return [r[0] for r in rows]


def streams_coverage(conn: sqlite3.Connection) -> dict:
    """The streams section --verify-archive reports: runs holding raw detail
    vs runs holding the columnar streams."""
    detailed_runs = conn.execute(
        f"SELECT COUNT(*) FROM activities a "
        f"WHERE a.detail_json IS NOT NULL AND {_RUN_TYPE_SQL}").fetchone()[0]
    streamed = conn.execute(
        f"SELECT COUNT(*) FROM activities a "
        f"WHERE a.detail_streams_json IS NOT NULL AND {_RUN_TYPE_SQL}").fetchone()[0]
    return {"detailed_runs": detailed_runs, "streamed": streamed,
            "missing": detailed_runs - streamed}


# ──────────────────────────────────────────────────────────────────────────────
# route-basemap tile math (schema v8 — pure and deterministic; the fetch step
# below is the only place in this module that ever touches the network)
# ──────────────────────────────────────────────────────────────────────────────
TILE_MAX_ZOOM = 16     # OSM standard tiles stay crisp enough for a fitted card
TILE_MAX_SPAN = 3      # crop side, in tiles, at the chosen zoom
TILE_PAD_FRAC = 0.08   # breathing room around the route bbox
# Floor on the normalized crop side so a near-stationary track (GPS warm-up
# in the garden) still frames ~250 m of world instead of a degenerate sliver.
_TILE_MIN_SPAN_NORM = 6e-6


def merc_world_px(lat: float, lon: float, z: int) -> tuple[float, float]:
    """Web Mercator world-pixel coordinates at zoom z — THE tile-alignment
    formula, mirrored verbatim by chart-core's projectTrackMercator. Both
    sides are pinned to the same known values by their tests."""
    world = 256 * (2 ** z)
    x = (lon + 180.0) / 360.0 * world
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * world
    return x, y


def compute_tile_rect(lat, lon):
    """A run's map coverage from its stored lat/lon columns (design D3):
    bbox → ~8% pad → squarify → highest zoom ≤ 16 whose crop spans ≤ 3 tiles
    → covering tile rect. Returns {z, x0, y0, x1, y1, crop_x, crop_y,
    crop_size} with the crop in world pixels at z, or None when the streams
    carry fewer than two GPS fixes. Pure: same columns, same answer."""
    n = min(len(lat or []), len(lon or []))
    pts = [(lat[i], lon[i]) for i in range(n) if lat[i] is not None and lon[i] is not None]
    if len(pts) < 2:
        return None
    # normalized [0,1] Mercator space is zoom-independent; scale once at the end
    xs = [(lo + 180.0) / 360.0 for _, lo in pts]
    ys = [(1.0 - math.asinh(math.tan(math.radians(la))) / math.pi) / 2.0 for la, _ in pts]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    span = max(x1 - x0, y1 - y0, _TILE_MIN_SPAN_NORM)
    side = span * (1 + 2 * TILE_PAD_FRAC)                 # pad, then squarify
    z = min(TILE_MAX_ZOOM, int(math.floor(math.log2(TILE_MAX_SPAN / side))))
    z = max(z, 0)
    scale = 256 * (2 ** z)
    crop_size = side * scale
    crop_x = (x0 + x1) / 2 * scale - crop_size / 2
    crop_y = (y0 + y1) / 2 * scale - crop_size / 2
    last = 2 ** z - 1
    return {
        "z": z,
        "x0": max(0, math.floor(crop_x / 256)),
        "y0": max(0, math.floor(crop_y / 256)),
        "x1": min(last, math.floor((crop_x + crop_size) / 256)),
        "y1": min(last, math.floor((crop_y + crop_size) / 256)),
        "crop_x": round(crop_x, 2),
        "crop_y": round(crop_y, 2),
        "crop_size": round(crop_size, 2),
    }


# ── the fetch step (route-basemap D5/D6): sync-side only — the browser never
#    learns the tile host exists. Throttled, identified, complete-or-absent. ──
TILE_URL_TEMPLATE = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
# OSM tile usage policy asks bulk users to identify the app and a contact.
TILE_USER_AGENT = ("SPLITS-training-dashboard/1.0 "
                   "(personal self-hosted dashboard; felixkeller98@gmail.com)")


def _tile_request(z: int, x: int, y: int) -> urllib.request.Request:
    return urllib.request.Request(
        TILE_URL_TEMPLATE.format(z=z, x=x, y=y),
        headers={"User-Agent": TILE_USER_AGENT})


def fetch_tile(z: int, x: int, y: int, timeout: int = 30) -> bytes:
    with urllib.request.urlopen(_tile_request(z, x, y), timeout=timeout) as r:
        return r.read()


def ensure_activity_map(conn: sqlite3.Connection, activity_id, streams,
                        fetch=None, pace_s: float = 1.0, _sleep=None) -> str:
    """Bring one run's basemap to complete-or-absent (design D6). Probes the
    deduped tile store first and fetches only the gap, one pause between
    consecutive fetches (design D5). The per-run row lands only after the
    whole rect is stored; tiles fetched before a failure stay (they are
    globally useful), so a retry fetches only what is still missing.

    Returns 'exists' (row already there), 'skipped' (no usable GPS),
    'done' (rect completed and row written), or 'failed' (a fetch died;
    no row written)."""
    if conn.execute("SELECT 1 FROM activity_maps WHERE activity_id = ?",
                    (activity_id,)).fetchone():
        return "exists"
    rect = compute_tile_rect((streams or {}).get("lat"), (streams or {}).get("lon"))
    if rect is None:
        return "skipped"
    fetch = fetch or fetch_tile
    sleep = _sleep if _sleep is not None else time.sleep
    missing = [
        (rect["z"], x, y)
        for x in range(rect["x0"], rect["x1"] + 1)
        for y in range(rect["y0"], rect["y1"] + 1)
        if conn.execute("SELECT 1 FROM map_tiles WHERE z = ? AND x = ? AND y = ?",
                        (rect["z"], x, y)).fetchone() is None
    ]
    for i, (z, x, y) in enumerate(missing):
        if i:
            sleep(pace_s)
        try:
            png = fetch(z, x, y)
        except Exception:
            png = None
        if not png:
            return "failed"
        # commit per tile: an interrupted pass keeps every tile it landed
        conn.execute("INSERT OR IGNORE INTO map_tiles (z, x, y, png, fetched_at) "
                     "VALUES (?, ?, ?, ?, ?)", (z, x, y, png, _now()))
        conn.commit()
    conn.execute(
        "INSERT OR REPLACE INTO activity_maps "
        "(activity_id, z, x0, y0, x1, y1, crop_x, crop_y, crop_size, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (activity_id, rect["z"], rect["x0"], rect["y0"], rect["x1"], rect["y1"],
         rect["crop_x"], rect["crop_y"], rect["crop_size"], _now()))
    conn.commit()
    return "done"


def runs_missing_maps(conn: sqlite3.Connection) -> list:
    """activity_ids of archived runs whose stored streams carry GPS but which
    have no activity_maps row — the map step's work list, oldest first. The
    LIKE probe keeps treadmill runs (no lat column at all) off the list, so
    they cost nothing sync after sync."""
    rows = conn.execute(
        f"""SELECT a.activity_id FROM activities a
            LEFT JOIN activity_maps m ON m.activity_id = a.activity_id
            WHERE a.detail_streams_json IS NOT NULL
              AND a.detail_streams_json LIKE '%"lat":%'
              AND m.activity_id IS NULL
              AND {_RUN_TYPE_SQL}
            ORDER BY a.start_time_local""").fetchall()
    return [r[0] for r in rows]


def streams_payload(conn: sqlite3.Connection, activity_id):
    """The parsed columnar streams for one activity, or None — the map step
    needs the lat/lon columns. Fetched one at a time, like detail_payload."""
    row = conn.execute(
        "SELECT detail_streams_json FROM activities WHERE activity_id = ?",
        (activity_id,)).fetchone()
    return json.loads(row[0]) if row and row[0] else None


def maps_coverage(conn: sqlite3.Connection) -> dict:
    """The maps section --verify-archive reports: runs holding GPS streams vs
    runs holding a map row, plus the deduped tile store's size. Treadmill runs
    (no lat column) are out of the denominator — they never get maps."""
    streamed_runs = conn.execute(
        f"""SELECT COUNT(*) FROM activities a
            WHERE a.detail_streams_json IS NOT NULL
              AND a.detail_streams_json LIKE '%"lat":%'
              AND {_RUN_TYPE_SQL}""").fetchone()[0]
    mapped = conn.execute("SELECT COUNT(*) FROM activity_maps").fetchone()[0]
    tiles, tile_bytes = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(LENGTH(png)), 0) FROM map_tiles").fetchone()
    return {"streamed_runs": streamed_runs, "mapped": mapped,
            "tiles": tiles, "tile_bytes": tile_bytes}


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


def wellness_coverage(conn: sqlite3.Connection, today: str) -> dict:
    """Wellness coverage over the archive's own span (earliest activity → today).

    A date is COVERED once it has been asked about (`fetched_at`), whether or not
    the watch recorded anything. A date the sync never requested is a GAP. Those
    are different facts, and a chart that cannot tell them apart draws a lie —
    which is the whole reason `fetched_at` exists.
    """
    earliest = conn.execute("SELECT MIN(start_time_local) FROM activities").fetchone()[0]
    if not earliest:
        return {"expected": 0, "rows": 0, "fetched": 0, "with_data": 0,
                "gaps": [], "earliest": None, "today": today}

    start = dt.date.fromisoformat(earliest[:10])
    end = dt.date.fromisoformat(today)
    expected = []
    while start <= end:
        expected.append(start.isoformat())
        start += dt.timedelta(days=1)

    fetched = {r[0] for r in conn.execute(
        "SELECT date FROM daily_wellness WHERE fetched_at IS NOT NULL")}
    with_data = conn.execute(
        "SELECT COUNT(*) FROM daily_wellness WHERE fetched_at IS NOT NULL "
        "AND (sleep_seconds IS NOT NULL OR hrv_last_night IS NOT NULL)").fetchone()[0]
    rows = conn.execute("SELECT COUNT(*) FROM daily_wellness").fetchone()[0]

    return {
        "expected": len(expected),
        "rows": rows,
        "fetched": len(fetched & set(expected)),
        "with_data": with_data,
        "gaps": [d for d in expected if d not in fetched],
        "earliest": expected[0],
        "today": today,
    }


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
