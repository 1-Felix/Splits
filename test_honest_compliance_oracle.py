#!/usr/bin/env python3
"""Real-data regression for honest-compliance, against local archive copies.

This is the gate that matters, and it cuts both ways: the fix must be visible
on Max's instance and near-invisible on Felix's. Skips when the copies are
absent, like the other oracle tests.

Refresh them with a CONSISTENT snapshot (never copy a live SQLite file):

  ssh felix@192.168.0.37 "cd ~/dev/docker-compose-files/splits && \\
    docker compose exec -T splits-max python3 -c \\
    \"import sqlite3,os; s=sqlite3.connect('/data/activity-archive.db'); \\
      d=sqlite3.connect('/data/_snap.db'); s.backup(d); d.close(); \\
      os.chmod('/data/_snap.db',0o644)\""
  scp felix@192.168.0.37:'~/dev/docker-compose-files/splits/volumes/splits-max-data/_snap.db' \\
      ./activity-archive-max.db
  ssh felix@192.168.0.37 "rm ~/dev/docker-compose-files/splits/volumes/splits-max-data/_snap.db"

Both .db files are gitignored.
"""
from __future__ import annotations

import datetime as dt
import shutil
import tempfile
from pathlib import Path

import pytest

import activity_archive as arch
import plan_compliance as pc

REPO = Path(__file__).parent
MAX_DB = REPO / "activity-archive-max.db"
FELIX_DB = REPO / "activity-archive.db"
TODAY = dt.date(2026, 8, 5)
MAX_HR_MAX, MAX_HR_FELIX = 199, 197


def _scratch(db: Path):
    """Open a THROWAWAY copy — an oracle test never writes the real file."""
    d = Path(tempfile.mkdtemp())
    shutil.copy(db, d / "activity-archive.db")
    return arch.open_archive(d)


def _rescore(conn, max_hr: int, today: dt.date) -> list[dict]:
    """Rescore every banked week under the current engine, against the
    snapshot each week originally referenced — exactly what the
    COMPLIANCE_VERSION bump will do on the next sync."""
    conn.execute("UPDATE plan_compliance SET compliance_version = 0")
    conn.commit()
    pc._rescore_stale(conn, today, max_hr)
    return arch.compliance_rows(conn)


def _planned(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["planned_kind"] is not None]


@pytest.mark.skipif(not MAX_DB.exists(), reason="no Max archive copy")
def test_max_stops_being_told_he_failed():
    """Measured 2026-08-05 before the fix: 10 missed (6 rest, 3 strength, 1
    real), 2 partial, 35% executed — against a true adherence of 7 of 8
    sessions. Every one of those nine false negatives must be gone, and the
    one real miss must survive."""
    conn = _scratch(MAX_DB)
    rows = _planned(_rescore(conn, MAX_HR_MAX, TODAY))
    by_status: dict[str, list[dict]] = {}
    for r in rows:
        by_status.setdefault(r["status"], []).append(r)

    missed = by_status.get("missed", [])
    assert all(r["planned_kind"] == "run" for r in missed), \
        "only a RUN can be missed now: " \
        + str([(r["date"], r["planned_kind"]) for r in missed])
    assert len(missed) == 1 and missed[0]["date"] == "2026-07-20", \
        "his first planned day is the one genuinely skipped run in the block"
    assert by_status.get("partial", []) == [], \
        "both partials were duration sessions he completed"
    assert len(by_status.get("rest", [])) >= 6
    assert len(by_status.get("untracked", [])) >= 3
    conn.close()


@pytest.mark.skipif(not MAX_DB.exists(), reason="no Max archive copy")
def test_max_time_sessions_are_scored_in_minutes():
    """The two sessions that read 'partial — shorter than planned'. Both were
    completed in full; both were scored against a km figure that is only the
    prescribed minutes times an assumed pace.

    `swapped` counts as completed here: 2026-07-30's run is banked on
    2026-07-29 (he moved the session a day), so the swap pass credits it. The
    question this test asks is whether the session was CREDITED and measured
    in minutes, not which calendar day carried it."""
    conn = _scratch(MAX_DB)
    rows = {r["date"]: r for r in _planned(_rescore(conn, MAX_HR_MAX, TODAY))}
    for date, planned_min in (("2026-07-30", 22), ("2026-08-01", 26)):
        r = rows[date]
        assert r["status"] in ("done", "swapped"), \
            f"{date} was completed in full, got {r['status']}"
        assert r["planned_s"] == planned_min * 60
        assert r["actual_s"] >= r["planned_s"], \
            f"{date} ran at least the minutes it was asked for"
    conn.close()


@pytest.mark.skipif(not MAX_DB.exists(), reason="no Max archive copy")
def test_every_run_walk_session_reads_its_prescribed_minutes():
    """The run/walk grammar end to end on real plan text: '8×1 min jog' with
    a '1 min walk' recovery is 8 work + 7 recovery = 15 min, which is what
    'Run/Walk 1:1' means. Mutation: count 8 recoveries → red."""
    conn = _scratch(MAX_DB)
    rows = {r["date"]: r for r in _planned(_rescore(conn, MAX_HR_MAX, TODAY))}
    for date, planned_min in (("2026-07-22", 15),   # 8×1 min jog, 1 min walk
                              ("2026-07-25", 19),   # 10×1 min jog, 1 min walk
                              ("2026-07-27", 20)):  # 7×2 min jog, 1 min walk
        assert rows[date]["planned_s"] == planned_min * 60, \
            f"{date}: got {rows[date]['planned_s']}s"
    conn.close()


@pytest.mark.skipif(not MAX_DB.exists(), reason="no Max archive copy")
def test_max_execute_rate_reflects_the_sessions_he_ran():
    """The headline. 8 run slots to date, 7 credited, 1 genuinely skipped."""
    conn = _scratch(MAX_DB)
    rows = _planned(_rescore(conn, MAX_HR_MAX, TODAY))
    scored = [r for r in rows
              if r["status"] not in ("pending", "rest", "untracked")]
    credited = [r for r in scored if r["status"] in ("done", "swapped")]
    assert len(scored) == 8, [r["date"] for r in scored]
    assert len(credited) == 7
    assert round(100.0 * len(credited) / len(scored)) == 88
    conn.close()


@pytest.mark.skipif(not MAX_DB.exists(), reason="no Max archive copy")
def test_no_rep_verdict_quotes_a_zero_on_an_uncalibrated_archive():
    conn = _scratch(MAX_DB)
    for r in _rescore(conn, MAX_HR_MAX, TODAY):
        q = r.get("quality_json") or ""
        assert "0/" not in q, f"{r['date']} still quotes an uncounted zero: {q}"
    conn.close()


@pytest.mark.skipif(not FELIX_DB.exists(), reason="no local archive")
def test_felixs_instance_barely_moves():
    """The other half of the gate. His plan authors no rest days and his watch
    logs strength, so his genuinely missed strength days must STAY missed —
    the capability check must not become a blanket amnesty."""
    conn = _scratch(FELIX_DB)
    rows = _planned(_rescore(conn, MAX_HR_FELIX, TODAY))
    assert not any(r["status"] == "rest" for r in rows), \
        "his plan authors no rest days"
    assert not any(r["status"] == "untracked" for r in rows), \
        "his archive sees every kind his plan prescribes"
    assert any(r["status"] == "missed" and r["planned_kind"] == "strength"
               for r in rows), \
        "a skipped strength day on a tracking instance is still a skipped day"
    conn.close()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
