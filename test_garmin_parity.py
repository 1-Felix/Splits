"""Pins Felix's Garmin-path output (garmin-data.js sections) so the second-
athlete work cannot move it. The golden may change in exactly one place:
zones[*].lo/hi (Task 6). Regenerate only on purpose: RECORD_GOLDEN=1."""
import json
import os
import tempfile
from pathlib import Path

import pytest

from garmin_fixtures import VO2_GAP_MONTHS, FakeClient, felix_like_acts, load_sync_garmin

REPO = Path(__file__).resolve().parent
GOLDEN = REPO / "fixtures" / "garmin-path" / "felix-golden.json"

def _max_metrics(cdate):
    """Distinct value per month-end; nothing for the last gap month, so the
    interior ffill path is pinned too."""
    if cdate[:7] == VO2_GAP_MONTHS[-1]:
        return None
    return [{"generic": {"vo2MaxPreciseValue": round(
        44.0 + (int(cdate[:4]) - 2024) * 2 + int(cdate[5:7]) / 10, 1)}}]


RESPONSES = {  # canned Garmin answers, fixed values
    "get_max_metrics": _max_metrics,
    "get_user_summary": {"restingHeartRate": 48, "weight": 80500},
    "get_rhr_day": {"restingHeartRate": 48},
    "get_training_readiness": [{"score": 71, "level": "READY"}],
    "get_training_status": {"mostRecentTrainingStatus": {"latestTrainingStatusData": {
        "3456789": {"trainingStatusFeedbackPhrase": "PRODUCTIVE_1",
                    "acuteTrainingLoadDTO": {"acwrPercent": 87,
                                             "dailyAcuteChronicWorkloadRatio": 1.1}}}}},
    "get_sleep_data": {"dailySleepDTO": {"sleepTimeSeconds": 27000, "deepSleepSeconds": 5400}},
    "get_activity_hr_in_timezones": [], "get_personal_record": [],
}


@pytest.fixture(autouse=True)
def _restore_env():
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


def _outputs(sg, client, acts):
    out = {
        "heatmap": sg.fetch_heatmap(acts), "weekly": sg.fetch_weekly(acts),
        "ctl_atl": sg.compute_fitness_fatigue(acts, 197),
        "monthly": sg.fetch_monthly(client, acts),
        "profile": sg.fetch_profile(client, 51.0),
        "readiness": sg.fetch_readiness(client, sg.fetch_sleep(client), 197),
        "zones": sg.fetch_hr_zones_this_week(client, acts, 197),
        "recent": [{k: v for k, v in r.items() if k != "detail"}
                   for r in sg.fetch_recent_runs(client, acts)],
    }
    out["calls_get_max_metrics"] = sorted(
        c[1][0] for c in client.calls if c[0] == "get_max_metrics")
    return out


def test_felix_garmin_path_matches_golden():
    with tempfile.TemporaryDirectory() as tmp:
        sg = load_sync_garmin(Path(tmp))
        acts = felix_like_acts(sg.TODAY)
        got = json.loads(json.dumps(_outputs(sg, FakeClient(RESPONSES), acts)))
    if os.getenv("RECORD_GOLDEN"):
        GOLDEN.write_text(json.dumps(got, indent=1), encoding="utf-8")
    # Text, not parsed equality: key order is part of garmin-data.js's contract
    # and dict == ignores it.
    assert json.dumps(got, indent=1) == GOLDEN.read_text(encoding="utf-8")
