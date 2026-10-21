"""Pins Felix's Garmin-path output (garmin-data.js sections) so the second-
athlete work cannot move it. The golden may change in exactly one place:
zones[*].lo/hi (Task 6). Regenerate only on purpose: RECORD_GOLDEN=1."""
import json
import os
import tempfile
from pathlib import Path

import pytest

from garmin_fixtures import FakeClient, felix_like_acts, load_sync_garmin

REPO = Path(__file__).resolve().parent
GOLDEN = REPO / "fixtures" / "garmin-path" / "felix-golden.json"

RESPONSES = {  # canned Garmin answers, fixed values
    "get_max_metrics": [{"generic": {"vo2MaxPreciseValue": 51.0}}],
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
    return {
        "heatmap": sg.fetch_heatmap(acts), "weekly": sg.fetch_weekly(acts),
        "ctl_atl": sg.compute_fitness_fatigue(acts, 197),
        "monthly": sg.fetch_monthly(client, acts),
        "profile": sg.fetch_profile(client, 51.0),
        "readiness": sg.fetch_readiness(client, sg.fetch_sleep(client), 197),
        "zones": sg.fetch_hr_zones_this_week(client, acts, 197),
        "recent": [{k: v for k, v in r.items() if k != "detail"}
                   for r in sg.fetch_recent_runs(client, acts)],
    }


def test_felix_garmin_path_matches_golden():
    with tempfile.TemporaryDirectory() as tmp:
        sg = load_sync_garmin(Path(tmp))
        acts = felix_like_acts(sg.TODAY)
        got = json.loads(json.dumps(_outputs(sg, FakeClient(RESPONSES), acts)))
    if os.getenv("RECORD_GOLDEN"):
        GOLDEN.write_text(json.dumps(got, indent=1), encoding="utf-8")
    assert got == json.loads(GOLDEN.read_text(encoding="utf-8"))
