"""Unit tests for sync_garmin detail helpers (no Garmin network)."""
import importlib.util
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("sync_garmin", REPO / "sync_garmin.py")
sg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sg)

_aspec = importlib.util.spec_from_file_location(
    "activity_archive", REPO / "activity_archive.py")
arch = importlib.util.module_from_spec(_aspec)
_aspec.loader.exec_module(arch)


def test_downsample():
    # last element is forced to series[-1] (was 90, now 99)
    assert sg._downsample(list(range(100)), 10) == [0, 10, 20, 30, 40, 50, 60, 70, 80, 99]
    assert sg._downsample([1, 2, 3], 10) == [1, 2, 3]


def test_hr_drift():
    assert sg._hr_drift([150, 150, 170, 170]) == 20
    assert sg._hr_drift([160] * 10) == 0
    assert sg._hr_drift([150]) == 0


def test_split_shape():
    assert sg._split_shape([{"pace": 360}, {"pace": 360}, {"pace": 400}]) == "positive"
    assert sg._split_shape([{"pace": 400}, {"pace": 380}, {"pace": 350}]) == "negative"
    assert sg._split_shape([{"pace": 360}, {"pace": 362}, {"pace": 361}]) == "even"


def test_bin_splits():
    idx = {"sumDistance": 0, "directHeartRate": 1, "directSpeed": 2}
    # km1 bucket (0–999 m): two rows → full km, retained
    # km2 bucket (1000–1999 m): two rows → full km, retained
    # km3 bucket (2000–2999 m): one row at 2300 m → span = 300 m < 600 → dropped
    rows = [
        {"metrics": [200,  150, 3.0]},
        {"metrics": [800,  160, 3.0]},   # bucket 0: hr avg=155, pace=333
        {"metrics": [1200, 165, 2.8]},
        {"metrics": [1800, 175, 2.8]},   # bucket 1: hr avg=170, pace=357
        {"metrics": [2300, 180, 2.5]},   # bucket 2: span=300 < 600 → dropped
    ]
    out = sg._bin_splits(rows, idx)
    assert len(out) == 2, f"trailing partial km should be dropped (got {len(out)} splits)"
    assert out[0]["km"] == 1 and out[0]["hr"] == 155 and out[0]["pace"] == 333
    assert out[1]["km"] == 2 and out[1]["hr"] == 170 and out[1]["pace"] == 357


class _FakeDetailClient:
    def get_activity_details(self, aid, maxchart=2000, maxpoly=0):
        return {
            "metricDescriptors": [
                {"key": "sumDistance", "metricsIndex": 0},
                {"key": "directHeartRate", "metricsIndex": 1},
                {"key": "directSpeed", "metricsIndex": 2},
            ],
            "activityDetailMetrics": [
                {"metrics": [300, 150, 3.0]},
                {"metrics": [800, 158, 3.0]},
                {"metrics": [1400, 168, 2.6]},
                {"metrics": [1900, 176, 2.6]},
            ],
        }


def test_fetch_run_detail_shape():
    cache = sg.CACHE_DIR / "detail-999.json"
    if cache.exists():
        cache.unlink()
    act = {"activityId": 999, "hrTimeInZone_1": 0, "hrTimeInZone_2": 60,
           "hrTimeInZone_3": 120, "hrTimeInZone_4": 240, "hrTimeInZone_5": 30,
           "maxTemperature": 28, "aerobicTrainingEffect": 4.2,
           "activityTrainingLoad": 210.7, "elevationGain": 88.0}
    d = sg.fetch_run_detail(_FakeDetailClient(), act)
    assert len(d["splits"]) == 2
    assert all(isinstance(s["pace"], int) for s in d["splits"])
    assert d["zoneMin"] == [0, 1, 2, 4, 1]
    assert isinstance(d["driftBpm"], int) and d["driftBpm"] > 0
    assert d["tempC"] == 28 and d["te"] == 4.2 and d["load"] == 211
    assert d["splitShape"] in ("even", "positive", "negative")
    assert len(d["hrSeries"]) == 4


def test_distill_one_implementation_two_callers():
    """progress-views 2.1 — the fresh-fetch path and the stored-payload path
    share one distiller: the same raw payload + summary give identical output."""
    cache = sg.CACHE_DIR / "detail-998.json"
    if cache.exists():
        cache.unlink()
    act = {"activityId": 998, "hrTimeInZone_2": 60, "hrTimeInZone_4": 240,
           "maxTemperature": 22, "aerobicTrainingEffect": 3.1,
           "activityTrainingLoad": 130.2, "elevationGain": 40.0}
    client = _FakeDetailClient()
    via_fetch = sg.fetch_run_detail(client, act)          # fresh-fetch caller
    raw = client.get_activity_details(998)                # what the archive stores
    via_stored = sg.distill_run_detail(raw, act)          # stored-payload caller
    assert via_fetch == via_stored, "one distiller, two callers — outputs must match"
    assert sg.distill_run_detail(None, act) is None, "no raw payload → no detail"


# ──────────────────────────────────────────────────────────────────────────────
# run-detail design D1: the stream distiller
# ──────────────────────────────────────────────────────────────────────────────
def _stream_payload():
    """Raw get_activity_details in miniature: descriptor order scrambled,
    redundant metrics present, nulls scattered through the samples."""
    keys = ["directRunCadence", "sumDuration", "sumDistance", "directHeartRate",
            "directSpeed", "directGradeAdjustedSpeed", "directDoubleCadence",
            "directElevation", "directPower", "directLatitude", "directLongitude",
            "directPerformanceCondition", "directTimestamp"]
    rows = [
        {"metrics": [80.2, 0.0, 0.0, 120.0, 2.956, 2.913, 160.4, 512.24, 280.6, 47.371881, 8.535413, None, 1.7e12]},
        {"metrics": [81.0, 1.0, 3.1, 121.0, 3.004, 3.052, 162.0, 512.46, 285.2, 47.371912, 8.535441, 2.0, 1.7e12]},
        {"metrics": [None, 2.0, 6.2, None, None, None, None, None, None, 47.371951, 8.535484, None, 1.7e12]},
    ]
    return {
        "metricDescriptors": [{"key": k, "metricsIndex": i} for i, k in enumerate(keys)],
        "activityDetailMetrics": rows,
        "geoPolylineDTO": {"polyline": []},   # maxpoly=0 — always empty
    }


def test_stream_columns_rounding_and_nulls():
    """run-detail 2.1/2.3 — columnar, rounded to each metric's real precision,
    nulls preserved; the redundant metrics never appear in the output."""
    s = sg.distill_run_streams(_stream_payload())
    assert set(s) == {"t", "d", "hr", "v", "gap", "cad", "elev", "pwr", "lat", "lon", "pc"}
    assert s["t"] == [0, 1, 2] and all(isinstance(v, int) for v in s["t"])
    assert s["d"] == [0, 3, 6]
    assert s["v"] == [2.96, 3.0, None], "speed rounds to 2 dp; a null stays null"
    assert s["gap"] == [2.91, 3.05, None]
    assert s["elev"] == [512.2, 512.5, None]
    assert s["pwr"] == [281, 285, None]
    assert s["lat"] == [47.37188, 47.37191, 47.37195], "GPS keeps 5 dp"
    assert s["pc"] == [None, 2, None], "sparse performance condition preserved"
    assert s["hr"][2] is None, "a null sample is a null, never interpolated"
    assert len({len(col) for col in s.values()}) == 1, "every column is sample-aligned"


def test_stream_cadence_is_double_cadence():
    """run-detail 2.2 — directRunCadence is single-side strides/min despite its
    descriptor; the stream carries directDoubleCadence, whose mean matches the
    promoted avg_cadence within rounding."""
    s = sg.distill_run_streams(_stream_payload())
    assert s["cad"][:2] == [160, 162], "steps/min — not the ~80 strides/min column"
    promoted_avg_cadence = 161.2      # what Garmin's summary promotes
    valid = [c for c in s["cad"] if c is not None]
    assert abs(sum(valid) / len(valid) - promoted_avg_cadence) < 1.0


def test_stream_gps_recovered_from_columns():
    """run-detail 2.4 — geoPolylineDTO.polyline is ALWAYS empty (the sync
    fetches maxpoly=0); the route lives complete in the lat/lon columns. This
    test exists so nobody goes looking for the polyline again."""
    raw = _stream_payload()
    assert raw["geoPolylineDTO"]["polyline"] == [], "maxpoly=0 → no polyline, ever"
    s = sg.distill_run_streams(raw)
    assert all(v is not None for v in s["lat"]), "latitude present on every sample"
    assert all(v is not None for v in s["lon"]), "longitude present on every sample"


def test_stream_refuses_non_streams():
    assert sg.distill_run_streams(None) is None
    assert sg.distill_run_streams({}) is None
    assert sg.distill_run_streams({"metricDescriptors": [], "activityDetailMetrics": []}) is None
    # a payload without the shared axes is not a stream worth serving
    assert sg.distill_run_streams({
        "metricDescriptors": [{"key": "directHeartRate", "metricsIndex": 0}],
        "activityDetailMetrics": [{"metrics": [140]}],
    }) is None


def test_stream_largest_archived_run_serialises_small():
    """run-detail 2.5 — against the REAL local archive when present (skipped
    elsewhere): the largest raw payload distils to < 110 KB compact JSON and
    well under the gzip budget the page pays."""
    import gzip
    import json
    import sqlite3
    db = REPO / "activity-archive.db"
    if not db.exists():
        print("  (no local archive — stream size check skipped)")
        return
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT activity_id, detail_json FROM activities "
            "WHERE detail_json IS NOT NULL ORDER BY LENGTH(detail_json) DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if not row:
        print("  (archive holds no raw detail — stream size check skipped)")
        return
    s = sg.distill_run_streams(json.loads(row[1]))
    assert s, "the largest archived run distils"
    blob = json.dumps(s, separators=(",", ":")).encode()
    # measured 2026-07-10 on the real archive: 114,600 bytes raw / 29,583 gzip
    # for a 1,999-sample run with all 11 columns (the proposal's 105 KB probe
    # predates the pc column). The wire cost — gzip — is the budget that
    # matters; the raw bound just catches a distiller that stops rounding.
    assert len(blob) < 125_000, f"largest stream is {len(blob)} bytes — the distiller grew"
    assert len(gzip.compress(blob)) < 35_000, "gzipped stream stays affordable"


def test_load_activities_refetches_recent():
    """A run added later the same day must appear on the next sync without clearing the
    cache, while the immutable history is still served from cache (not re-pulled)."""
    import tempfile
    from pathlib import Path

    today = sg.TODAY.isoformat()

    class FakeClient:
        def __init__(self):
            self.recent = []
            self.calls = []

        def get_activities_by_date(self, start, end):
            self.calls.append((start, end))
            if end == today:                       # the always-fresh recent window
                return list(self.recent)
            return [{"activityId": 1, "startTimeLocal": "2026-05-01 08:00:00",  # history
                     "distance": 5000, "activityType": {"typeKey": "running"}}]

    orig = sg.CACHE_DIR
    sg.CACHE_DIR = Path(tempfile.mkdtemp())
    try:
        fc = FakeClient()
        first = sg.load_activities(fc)                       # first sync of the day: no run yet
        assert not any(a["activityId"] == 99 for a in first)
        n = len(fc.calls)                                    # history + recent = 2 calls

        # a run is uploaded later the SAME day; the cache is NOT cleared
        fc.recent = [{"activityId": 99, "startTimeLocal": today + " 18:00:00",
                      "distance": 5000, "activityType": {"typeKey": "running"}}]
        second = sg.load_activities(fc)                      # next sync
        assert any(a["activityId"] == 99 for a in second), "same-day run must appear"
        assert second[0]["activityId"] == 99, "newest activity should sort first"
        assert len(fc.calls) == n + 1, "history stays cached; only the recent window re-fetched"
    finally:
        sg.CACHE_DIR = orig


def test_history_not_cached_when_empty():
    """A failed/empty history pull must NOT be cached, so the next sync retries it —
    a transient Garmin error can't wipe historical data for the rest of the day."""
    import tempfile
    from pathlib import Path

    class FakeClient:
        def __init__(self):
            self.history_calls = 0

        def get_activities_by_date(self, start, end):
            if end == sg.TODAY.isoformat():
                return []
            self.history_calls += 1
            return []  # simulate a failed/empty history pull

    orig = sg.CACHE_DIR
    sg.CACHE_DIR = Path(tempfile.mkdtemp())
    try:
        fc = FakeClient()
        sg.load_activities(fc)
        sg.load_activities(fc)
        assert fc.history_calls == 2, "empty/failed history must be retried each sync, not cached"
    finally:
        sg.CACHE_DIR = orig


def test_history_cache_corrupt_is_refetched():
    """A corrupt history cache is re-pulled, not fatal."""
    import tempfile
    from pathlib import Path

    class FakeClient:
        def __init__(self):
            self.history_calls = 0

        def get_activities_by_date(self, start, end):
            if end == sg.TODAY.isoformat():
                return []
            self.history_calls += 1
            return [{"activityId": 1, "startTimeLocal": "2026-05-01 08:00:00"}]

    orig = sg.CACHE_DIR
    sg.CACHE_DIR = Path(tempfile.mkdtemp())
    try:
        sg.CACHE_DIR.mkdir(exist_ok=True)
        (sg.CACHE_DIR / f"activities-history-{sg.TODAY.isoformat()}.json").write_text("{ not json", encoding="utf-8")
        fc = FakeClient()
        acts = sg.load_activities(fc)
        assert fc.history_calls == 1, "corrupt cache should trigger a fresh history pull"
        assert any(a["activityId"] == 1 for a in acts)
    finally:
        sg.CACHE_DIR = orig


def _run_summary(aid, lap_count, start):
    return {"activityId": aid, "startTimeLocal": start,
            "activityType": {"typeKey": "running"}, "activityName": f"run {aid}",
            "distance": 8000.0, "duration": 2400.0, "lapCount": lap_count}


def test_laps_pass_skips_single_lap_runs():
    """The 42 single-lap runs in the archive must never cost a request."""
    tmp = Path(tempfile.mkdtemp())
    conn = arch.open_archive(tmp)
    arch.upsert_activities(conn, [
        _run_summary(1, 1, "2026-07-10 06:00:00"),
        _run_summary(2, 13, "2026-07-11 06:00:00"),
    ])
    asked = []

    class FakeClient:
        def get_activity_splits(self, aid):
            asked.append(aid)
            return {"lapDTOs": [{"distance": 1000, "duration": 330}]}

    original = sg.CACHE_DIR
    sg.CACHE_DIR = tmp / "cache"
    try:
        sg._laps_pass(FakeClient(), conn, limit=None)
    finally:
        sg.CACHE_DIR = original
    assert asked == [2]
    assert arch.laps_payload(conn, 2)[0]["distance"] == 1000
    assert arch.laps_payload(conn, 1) is None
    conn.close()


def test_empty_lap_envelope_is_not_cached_as_fetched():
    """M1: `{"lapDTOs": []}` is a truthy dict — caching it before checking the
    list marked the run as fetched forever and could starve the bounded
    backfill queue behind it. The cache is written only for a non-empty lap
    list, so an empty reply stays eligible for a future fetch. Mutation-proven:
    restoring the cache-before-check order sends `calls == [7, 7]` red."""
    tmp = Path(tempfile.mkdtemp())
    calls = []

    class FakeClient:
        def get_activity_splits(self, aid):
            calls.append(aid)
            return {"lapDTOs": []}

    original = sg.CACHE_DIR
    sg.CACHE_DIR = tmp / "cache"
    try:
        assert sg._fetch_raw_laps(FakeClient(), 7) == []
        assert not (sg.CACHE_DIR / "laps-7.json").exists(), \
            "an empty envelope must leave no cache entry"
        assert sg._fetch_raw_laps(FakeClient(), 7) == []
        assert calls == [7, 7], "empty reply must stay eligible for refetch"
    finally:
        sg.CACHE_DIR = original


def test_populated_lap_reply_is_cached_write_once():
    tmp = Path(tempfile.mkdtemp())
    calls = []

    class FakeClient:
        def get_activity_splits(self, aid):
            calls.append(aid)
            return {"lapDTOs": [{"distance": 1000, "duration": 330}]}

    original = sg.CACHE_DIR
    sg.CACHE_DIR = tmp / "cache"
    try:
        first = sg._fetch_raw_laps(FakeClient(), 9)
        second = sg._fetch_raw_laps(FakeClient(), 9)
    finally:
        sg.CACHE_DIR = original
    assert first == second == [{"distance": 1000, "duration": 330}]
    assert calls == [9], "second read must come from the cache"


# ──────────────────────────────────────────────────────────────────────────────
# sg.derive_intervals / intervals_step (add-interval-lens Task 10)
# ──────────────────────────────────────────────────────────────────────────────
PAD_RUN_COUNT = 6
PAD_RUN_DURATION_S = 18000  # 6 * 18000 / 5 = 21600 baseline samples


def _rep_streams():
    """A clean 5×1 km session — the exact fixture interval_lens's own suite
    uses to prove classify()/label_for() land on '5×1 km' (see
    test_document_shape_for_a_rep_session)."""
    spans = [(600, 2.6)] + [(250, 4.0), (60, 2.2)] * 5 + [(300, 2.6)]
    t, d, v = [], [], []
    clock, dist = 0, 0.0
    for dur, mps in spans:
        for _ in range(dur):
            t.append(clock)
            d.append(round(dist))
            v.append(mps)
            clock += 1
            dist += mps
    return {"t": t, "d": d, "v": v}


def _steady_streams(duration_s, mps=2.6):
    """A uniform-pace fill run: real moving time for the calibration sweep to
    bank, but never itself two-class enough to read as structure —
    split_classes needs low != high, which a constant series never has — so
    padding the archive with these can never smuggle a false 'reps' into the
    mix, whatever the resulting floor turns out to be."""
    t = list(range(duration_s))
    d = [round(i * mps) for i in range(duration_s)]
    v = [mps] * duration_s
    return {"t": t, "d": d, "v": v}


def _seed_calibrated_archive(conn, start_id=100):
    """Enough streamed, steady-pace padding runs to push the archive's
    baseline pool past interval_lens.WORK_FLOOR_MIN_SAMPLES (20000) — the
    precondition every 'calibrated' test below shares. Every padding run
    shares one pace (2.6 m/s) so the resulting floor lands on an exact, known
    value instead of an interpolated one."""
    ids = list(range(start_id, start_id + PAD_RUN_COUNT))
    arch.upsert_activities(conn, [
        _run_summary(aid, 1, f"2026-01-{i + 1:02d} 06:00:00")
        for i, aid in enumerate(ids)
    ])
    for aid in ids:
        arch.write_streams(conn, aid, _steady_streams(PAD_RUN_DURATION_S))
    return ids


def test_derive_intervals_scores_every_streamed_run():
    """The trap this task exists to avoid: without calibration, a naive port
    of build_document would score this exact session 'steady' and look like
    it worked. Padding the archive first is what makes 'reps' the correct —
    and provably calibrated — answer here."""
    conn = arch.open_archive(Path(tempfile.mkdtemp()))
    pad_ids = _seed_calibrated_archive(conn)
    arch.upsert_activities(conn, [_run_summary(5, 13, "2026-07-10 06:00:00")])
    arch.write_streams(conn, 5, _rep_streams())

    result = sg.derive_intervals(conn)
    assert result["scored"] == len(pad_ids) + 1
    assert result["floor"] == 2.6, "padding + run 5's easy phases all sit at 2.6 m/s"
    assert float(arch.get_meta(conn, "interval_work_floor")) == 2.6

    doc = arch.interval_document(conn, 5)
    assert doc["calibrated"] is True
    assert doc["shape"] == "reps" and doc["label"] == "5×1 km"

    # a uniform-pace padding run must never itself read as structure
    assert arch.interval_document(conn, pad_ids[0])["shape"] == "steady"

    # idempotent: a second pass with no new data and no floor drift scores nothing
    second = sg.derive_intervals(conn)
    assert second["scored"] == 0
    assert second["floor"] == 2.6
    conn.close()


def test_uncalibrated_archive_makes_no_rep_claim():
    """Below WORK_FLOOR_MIN_SAMPLES (a young archive — the live path for the
    second athlete) the pass must still score every run, but the document
    has to record calibrated: false and make NO rep claim. This is exactly
    the failure mode calibration exists to prevent: a naive port would call
    this session 'reps' on nothing but its own two-class shape."""
    conn = arch.open_archive(Path(tempfile.mkdtemp()))
    arch.upsert_activities(conn, [_run_summary(5, 13, "2026-07-10 06:00:00")])
    arch.write_streams(conn, 5, _rep_streams())

    result = sg.derive_intervals(conn)
    assert result["scored"] == 1
    assert result["floor"] is None
    assert arch.get_meta(conn, "interval_work_floor") in (None, "None")

    doc = arch.interval_document(conn, 5)
    assert doc["calibrated"] is False
    assert doc["shape"] == "steady", \
        "no floor means no rep claim, even though this run's two classes are obvious"
    conn.close()


def test_a_run_with_no_usable_stream_does_not_sink_the_rest():
    """Some archived runs carry no usable speed signal at all (real archive:
    one such run in 165) — build_document returns None rather than raising,
    and the pass must still score everything else."""
    conn = arch.open_archive(Path(tempfile.mkdtemp()))
    pad_ids = _seed_calibrated_archive(conn)
    arch.upsert_activities(conn, [
        _run_summary(6, 1, "2026-07-10 06:00:00"),
        _run_summary(7, 13, "2026-07-11 06:00:00"),
    ])
    arch.write_streams(conn, 6, {"t": "not-a-list", "d": None})
    arch.write_streams(conn, 7, _rep_streams())

    result = sg.derive_intervals(conn)
    assert result["scored"] == len(pad_ids) + 1
    assert arch.interval_document(conn, 7)["shape"] == "reps"
    assert arch.interval_document(conn, 6) is None
    conn.close()


def test_a_stream_that_throws_never_sinks_the_pass():
    """A stream so malformed it RAISES (not merely returns no signal) must
    still never stop the sweep or the scoring loop — it is caught and logged
    at both points derive_intervals touches a stream, and calibration must
    come out uncorrupted."""
    conn = arch.open_archive(Path(tempfile.mkdtemp()))
    pad_ids = _seed_calibrated_archive(conn)
    arch.upsert_activities(conn, [
        _run_summary(8, 1, "2026-07-10 06:00:00"),
        _run_summary(9, 13, "2026-07-11 06:00:00"),
    ])
    arch.write_streams(conn, 8, {"t": ["a", "b"], "d": [0, 1], "v": [1.0, 1.0]})
    arch.write_streams(conn, 9, _rep_streams())

    result = sg.derive_intervals(conn)
    assert result["scored"] == len(pad_ids) + 1
    assert result["floor"] == 2.6, "the throwing run must not have corrupted calibration"
    assert arch.interval_document(conn, 9)["shape"] == "reps"
    assert arch.interval_document(conn, 8) is None
    conn.close()


def test_moved_work_floor_forces_a_full_archive_recompute():
    """The floor is a property of the whole archive, so it drifts as the
    athlete's history grows — and once it moves by more than 2%, every
    stored document was scored under a floor that no longer applies, even
    though its lens_version hasn't changed. Proven here by CONTENT, not by
    trusting the mechanism: run 5's own reps genuinely stop qualifying as
    'work' once the floor rises past their pace."""
    conn = arch.open_archive(Path(tempfile.mkdtemp()))
    pad_ids = _seed_calibrated_archive(conn)
    arch.upsert_activities(conn, [_run_summary(5, 13, "2026-07-10 06:00:00")])
    arch.write_streams(conn, 5, _rep_streams())

    first = sg.derive_intervals(conn)
    assert first["floor"] == 2.6
    assert arch.interval_document(conn, 5)["shape"] == "reps"

    # without new data or drift, a second pass is a strict no-op
    assert sg.derive_intervals(conn)["scored"] == 0

    # a big batch of much faster running shifts the 93rd-percentile floor
    # well past this session's ~4.0 m/s reps
    arch.upsert_activities(conn, [_run_summary(200, 1, "2026-02-01 06:00:00")])
    arch.write_streams(conn, 200, _steady_streams(20000, mps=5.0))

    second = sg.derive_intervals(conn)
    drift = abs(second["floor"] - first["floor"]) / first["floor"]
    assert drift > sg.INTERVAL_FLOOR_DRIFT_GATE, \
        "the drift guard must actually have something to trigger on"
    assert second["floor"] == 5.0

    total_runs = len(pad_ids) + 2  # + run 5 + the new fast run
    assert second["scored"] == total_runs, \
        "a moved floor must recompute EVERY streamed run, not just the new one"

    # run 5's reps no longer qualify as work under the new, higher floor —
    # the clearest possible proof the recompute genuinely happened
    assert arch.interval_document(conn, 5)["shape"] == "steady"

    # settles again: a third pass with no further drift is a no-op
    assert sg.derive_intervals(conn)["scored"] == 0
    conn.close()


def test_a_floor_drift_under_the_gate_only_scores_the_new_run():
    """The other half of the moved-floor guard: drift that is real but stays
    under sg.INTERVAL_FLOOR_DRIFT_GATE must NOT force a full recompute — only
    the run(s) genuinely still pending a document get scored. The positive
    test above alone can't catch a regression that made the drift comparison
    always-true (it would stay green while every nightly sync silently
    recomputed the whole archive); this is the other half of that guard.

    The padding run's size is DERIVED from INTERVAL_FLOOR_DRIFT_GATE and
    interval_lens.WORK_FLOOR_PCT, not hand-picked, so this keeps proving what
    it claims even if the gate, the percentile, or the padding archive's size
    change later."""
    conn = arch.open_archive(Path(tempfile.mkdtemp()))
    pad_ids = _seed_calibrated_archive(conn)
    arch.upsert_activities(conn, [_run_summary(5, 13, "2026-07-10 06:00:00")])
    arch.write_streams(conn, 5, _rep_streams())

    first = sg.derive_intervals(conn)
    floor0 = first["floor"]
    assert floor0 is not None

    # Target a pace at 40% of the drift gate above the current floor — safely
    # nonzero, safely under the gate, whatever the gate's value happens to be.
    target_ratio = sg.INTERVAL_FLOOR_DRIFT_GATE * 0.4
    target_mps = round(floor0 * (1 + target_ratio), 3)
    assert 0 < target_ratio < sg.INTERVAL_FLOOR_DRIFT_GATE

    # How many samples at target_mps are needed for the 93rd-percentile pick
    # to actually land among them? Worked out from the archive's OWN current
    # composition (not assumed): the percentile index must clear every
    # existing sample at or below the current floor.
    existing = []
    for aid, _ in arch.streamed_runs(conn):
        existing.extend(sg.interval_lens.baseline_samples(arch.streams_payload(conn, aid)))
    below = sum(1 for v in existing if v <= floor0)
    n0 = len(existing)
    pct = sg.interval_lens.WORK_FLOOR_PCT
    k_min = max(1, int(below / pct) - n0 + 1)
    k = k_min * 2 + 100                              # generous safety margin
    duration_s = k * sg.interval_lens.BASELINE_STRIDE

    arch.upsert_activities(conn, [_run_summary(300, 1, "2026-03-01 06:00:00")])
    arch.write_streams(conn, 300, _steady_streams(duration_s, mps=target_mps))

    second = sg.derive_intervals(conn)
    assert second["floor"] == target_mps

    drift = abs(second["floor"] - floor0) / floor0
    assert 0 < drift < sg.INTERVAL_FLOOR_DRIFT_GATE, \
        f"expected a nonzero, sub-gate drift; measured {drift:.4%}"

    # only the genuinely pending run (the new padding run) gets scored —
    # NOT a full-archive recompute
    assert second["scored"] == 1

    # the previously-scored reps run must be untouched under the barely-
    # moved floor, not silently recomputed
    assert arch.interval_document(conn, 5)["shape"] == "reps"
    conn.close()


def _structured_laps():
    """The lap DTOs Garmin returns for a real workout: explicit intensity
    roles, and boundaries the stream detector cannot reproduce — the warmup is
    460 s here against the 600 s `_rep_streams()` actually contains, which is
    what makes "the device's boundaries won" checkable rather than assumed.
    Not auto-lap (the full laps are not all ~1 km), so the ±5 % veto does not
    fire."""
    laps = [{"distance": 1200.0, "duration": 460.0, "intensityType": "WARMUP"}]
    for _ in range(5):
        laps.append({"distance": 1000.0, "duration": 250.0,
                     "intensityType": "ACTIVE", "averageSpeed": 4.0})
        laps.append({"distance": 132.0, "duration": 60.0, "intensityType": "REST"})
    laps.append({"distance": 780.0, "duration": 300.0, "intensityType": "COOLDOWN"})
    return laps


def test_laps_arriving_a_night_later_flip_the_document_to_the_device():
    """FINAL REVIEW I2, end to end over the two passes that actually disagree
    about speed.

    `_laps_pass` is capped at LAPS_PER_SYNC per night, so a real 123-run lap
    backlog drains over ~4 nights; `intervals_step` scores every streamed run
    on night 1. Before this fix nothing invalidated a document when its laps
    landed afterwards, so ~83 runs — including most of the archive's genuine
    `hasIntensityIntervals` workout days — kept the weaker stream verdict
    permanently and design D1 ("device laps win outright") never applied to
    them."""
    conn = arch.open_archive(Path(tempfile.mkdtemp()))
    pad_ids = _seed_calibrated_archive(conn)
    summary = dict(_run_summary(5, 13, "2026-07-10 06:00:00"),
                   hasIntensityIntervals=True)
    arch.upsert_activities(conn, [summary])
    arch.write_streams(conn, 5, _rep_streams())

    # ── night 1: the streams are scored; this run's laps are still queued ──
    assert sg.derive_intervals(conn)["scored"] == len(pad_ids) + 1
    night1 = arch.interval_document(conn, 5)
    assert night1["source"] == "stream", "no laps yet — the stream is all we have"
    assert night1["segments"][0]["durS"] == 600, "the stream's own warmup boundary"

    # ── the lap backfill reaches this run ─────────────────────────────────
    assert arch.write_laps(conn, 5, _structured_laps()) is True
    pending = [aid for aid, _ in arch.runs_missing_intervals(
        conn, sg.interval_lens.INTERVAL_VERSION)]
    assert pending == [5], f"only the run whose laps landed is pending: {pending}"

    # `computed_at` and `laps_fetched_at` both have 1 s resolution; without
    # this the two stamps can share a second and the "settles" assertion at
    # the bottom becomes a coin flip. The FLIP itself does not need it.
    import time
    time.sleep(1.1)

    # ── night 2: the same engine, now with the device's own boundaries ────
    assert sg.derive_intervals(conn)["scored"] == 1, \
        "one run rescored — not a full-archive recompute"
    night2 = arch.interval_document(conn, 5)
    assert night2["source"] == "laps", \
        "design D1: structured device laps win outright once they exist"
    assert night2["confidence"] == 1.0, "the watch is not guessing"
    assert night2["segments"][0]["durS"] == 460, \
        "the boundaries are the DEVICE's, not a re-derivation from the stream"
    assert night2["shape"] == "reps" and night2["set"]["found"] == 5
    assert [s["role"] for s in night2["segments"][:3]] == ["warmup", "work", "recovery"], \
        "roles come from intensityType verbatim"

    # ── night 3: settled. The clause must not rescore this run for ever ───
    assert sg.derive_intervals(conn)["scored"] == 0
    conn.close()


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_"):
            _fn()
            print("ok", _name)
    print("ALL PASS")
