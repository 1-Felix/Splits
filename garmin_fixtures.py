"""Shared test helpers for the Garmin-sync work (not test_-prefixed, so pytest
does not collect it). Everything here is deterministic: no clock, no RNG.

Local safety: tests that use these helpers always point SPLITS_DATA_DIR at a
tmp dir and talk to a FakeClient, never to real Garmin and never to the repo
root's live garmin-data.js / plan-data.js.
"""
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parent

# Interior months whose activities carry no vO2MaxValue, so fetch_monthly must
# back-fill them from get_max_metrics (the first month keeps its values).
VO2_GAP_MONTHS = ("2024-12", "2025-01", "2025-08")

_FELIX_ENV = {"ATHLETE_NAME": "Felix", "ATHLETE_AGE": "28", "ATHLETE_MAX_HR": "197"}


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_sync_garmin(data_dir: Path):
    """Import a fresh copy of sync_garmin with DATA_DIR pointed at `data_dir`,
    Felix's container env, and TODAY pinned to 2026-10-21.

    This mutates os.environ (sync_garmin reads ATHLETE_* at call time), so a
    caller that shares a process with other tests should snapshot and restore
    os.environ around it."""
    os.environ["SPLITS_DATA_DIR"] = str(data_dir)
    os.environ.update(_FELIX_ENV)
    os.environ.pop("ATHLETE_RESTING_HR", None)
    sg = _load("sync_garmin_under_test", REPO / "sync_garmin.py")
    sg.TODAY = dt.date(2026, 10, 21)
    return sg


def felix_like_acts(today: dt.date) -> list[dict]:
    """Garmin activity-list dicts: 4 runs a week (Tue/Thu/Sat/Sun) across the
    30-month window ending `today`. The first run is 2024-05-02, inside the
    window's first month, so the window is exactly full."""
    months = 30
    y, m = today.year, today.month - (months - 1)
    while m <= 0:
        y, m = y - 1, m + 12
    first = dt.date(y, m, 1)
    names = ("Easy Run", "Tempo Run", "Long Run")
    monday = today - dt.timedelta(days=today.weekday())
    acts = []
    day = first
    i = 0
    while day <= today:
        if day.weekday() in (1, 3, 5, 6):
            kind = i % 3
            km = (6.0, 8.0, 16.0)[kind] + (i % 5) * 0.4
            pace = (330, 290, 320)[kind] + (i % 4) * 3  # sec/km
            a = {
                "activityId": 20_000_000_000 + i,
                "startTimeLocal": f"{day.isoformat()} {6 + (i % 3):02d}:{(i * 7) % 60:02d}:00",
                "activityType": {"typeKey": "running"},
                "activityName": names[kind],
                "distance": round(km * 1000.0, 1),
                "duration": round(km * pace, 1),
                "averageHR": 140 + (i % 6) * 4,
                "maxHR": 165 + (i % 5) * 4,
                "averageRunningCadenceInStepsPerMinute": 168.0 + (i % 5),
            }
            if i % 3 == 0 and day.isoformat()[:7] not in VO2_GAP_MONTHS:
                a["vO2MaxValue"] = round(48.0 + (i // 60) * 0.5 + (i % 4) * 0.5, 1)
            if day >= monday:
                for z, share in enumerate((0.10, 0.45, 0.30, 0.12, 0.03), start=1):
                    a[f"hrTimeInZone_{z}"] = round(a["duration"] * share, 1)
            acts.append(a)
            i += 1
        day += dt.timedelta(days=1)
    return acts


class FakeClient:
    """Answers any method call from `responses` ({name: value | callable}).
    Unknown calls return None. Every call is recorded in `self.calls` as
    (name, args). `fail=True` makes every call raise RuntimeError("429").
    `full_name` / `display_name` are plain attributes, as on the real client."""

    def __init__(self, responses: dict | None = None, fail: bool = False):
        self.responses = responses or {}
        self.fail = fail
        self.calls: list[tuple] = []
        self.full_name = None
        self.display_name = None

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def call(*args, **kwargs):
            self.calls.append((name, args))
            if self.fail:
                raise RuntimeError("429")
            resp = self.responses.get(name)
            return resp(*args, **kwargs) if callable(resp) else resp

        return call


def _samples(dur_s: int, dist_m: float, avg_hr: int, n: int = 70):
    step = max(1, int(dur_s) // n)
    mps = round(dist_m / dur_s, 2)
    speed = [{"tSec": 1 + k * step, "mps": mps + (0.1 if k % 2 else -0.1)} for k in range(n)]
    hr = [{"tSec": 1 + k * step, "bpm": avg_hr - 6 + (k * 7) % 13} for k in range(n)]
    return speed, hr


def _iso_t(start) -> str:
    if isinstance(start, dt.datetime):
        return start.strftime("%Y-%m-%dT%H:%M:%S")
    return str(start).replace(" ", "T")


def shelf_row(conn, aid, uid, start, dur_s, dist_m,
              source="com.sec.android.app.shealth", streams=True):
    """Insert an ingest-shaped ('shelf') activity row: summary_json carries
    sessionUid, detail_json is NULL, and with streams=True the columnar streams
    and distilled detail are filled from ingest_builder."""
    ib = _load("ingest_builder_under_test", REPO / "ingest_builder.py")
    start_t = _iso_t(start)
    avg_hr = 143
    speed, hr = _samples(int(dur_s), float(dist_m), avg_hr)
    run = {
        "sessionUid": uid, "startTimeLocal": start_t, "durationS": dur_s,
        "distanceM": dist_m, "avgHr": float(avg_hr), "maxHr": 162,
        "sportType": "running", "avgSpeed": round(dist_m / dur_s, 2),
        "source": source, "hrSamples": hr, "speedSamples": speed,
        "elevationGainM": None, "activeKcal": None, "totalKcal": None, "steps": None,
    }
    st = dis = None
    if streams:
        s = ib.synth_streams(run)
        d = ib.run_detail(run, 199, None)
        st = json.dumps(s, ensure_ascii=False) if s else None
        dis = json.dumps(d, ensure_ascii=False) if d else None
    now = "2026-10-21T08:00:00+02:00"
    conn.execute(
        "INSERT INTO activities (activity_id, start_time_local, type_key, name, "
        "distance_m, duration_s, avg_hr, max_hr, avg_cadence, elevation_gain_m, "
        "summary_json, detail_json, detail_distilled_json, detail_streams_json, "
        "first_seen_at, updated_at) "
        "VALUES (?, ?, 'running', NULL, ?, ?, ?, 162, NULL, NULL, ?, NULL, ?, ?, ?, ?)",
        (aid, start_t, dist_m, dur_s, avg_hr, json.dumps(run, ensure_ascii=False),
         dis, st, now, now),
    )
    conn.commit()


def garmin_row(conn, aid, start, dur_s, dist_m):
    """Insert a Garmin-shaped activity row: summary_json carries activityId and
    a space-format startTimeLocal; detail_json is the empty object."""
    if isinstance(start, dt.datetime):
        start_s = start.strftime("%Y-%m-%d %H:%M:%S")
    else:
        start_s = str(start).replace("T", " ")
    summary = {
        "activityId": aid, "startTimeLocal": start_s,
        "activityType": {"typeKey": "running"}, "activityName": "Run",
        "distance": dist_m, "duration": dur_s, "elapsedDuration": dur_s,
        "averageHR": 150.0, "maxHR": 170.0,
    }
    now = "2026-10-21T08:00:00+02:00"
    conn.execute(
        "INSERT INTO activities (activity_id, start_time_local, type_key, name, "
        "distance_m, duration_s, avg_hr, max_hr, avg_cadence, elevation_gain_m, "
        "summary_json, detail_json, first_seen_at, updated_at) "
        "VALUES (?, ?, 'running', 'Run', ?, ?, 150, 170, NULL, NULL, ?, '{}', ?, ?)",
        (aid, start_s, dist_m, dur_s, json.dumps(summary), now, now),
    )
    conn.commit()
