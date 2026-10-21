# Max on Garmin Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Switch Max's `splits-max` instance from the Health Connect bridge to the nightly Garmin sync. His June–October Health Connect runs stay on the dashboard as one continuous history, and Felix's instance doesn't move.

**Architecture:** His ingest-origin archive rows become a frozen **shelf**, identified by `summary_json.sessionUid`.
- The Garmin sync stops asking Garmin about shelf rows.
- It prunes shelf rows that overlap Garmin runs ("Garmin wins").
- It folds a shelf projection into the cockpit aggregates.
- It heals shelf metrics from stored streams.

Separately, we harden the Garmin path's Felix-shaped defaults: zones, fallbacks, the monthly series, prediction sources. Then the NUC cutover.

**Tech Stack:** Python 3 (stdlib `sqlite3`, `garminconnect`), pytest via the repo venv, Node ≥ 24 + Playwright page tests, Docker Compose on the NUC.

**Spec:** `docs/superpowers/specs/2026-10-21-max-garmin-sync-design.md` (D1–D10). Read it first.

## Global Constraints

- **Felix's `garmin-data.js` stays key-for-key identical on the same inputs, except `hrZones[].lo/hi`** (spec anti-goal 1). Every task touching `sync_garmin.py` must keep `test_garmin_parity.py` green.
- **No Garmin call for an id Garmin never issued**, and no VO2max lookup for a month before the account's first Garmin activity.
- **No Felix number as a fallback:** 51.3, 81.0, 47, 46, "Felix", "1:59:59", "Optimal". Unknown means the key is omitted (the ingest path's convention, which the dashboards already tolerate).
- **The shelf predicate is `json_extract(summary_json, '$.sessionUid') IS NOT NULL`,** owned by `activity_archive`. No schema bump.
- **Zone model:** `ATHLETE_RESTING_HR` set → Karvonen. Unset → %max (today's behaviour). The value is pinned, never a nightly median.
- **Prediction readers** use non-riegel rows whenever any exist, riegel rows only on a riegel-only (ingest) instance. They never splice the two.
- **Tests:**
  - Python: `./.venv/Scripts/python.exe -m pytest <file> -q`
  - JS: `pnpm test <substr>`
  - New page tests use ports 18400–18499 and verify server identity before asserting (the `waitReady` pattern in `test_slim_render.mjs`). SO_REUSEADDR lets a stray server hijack a port.
- **Windows env:** use `python`/`SPLITS_PYTHON=python`, never `python3` (Store alias).
- **Commits:** conventional style (`feat(scope): …`, `fix(scope): …`). **No `Co-Authored-By` line, no Claude attribution** (Felix's global rule overrides the harness default). Work on branch `max-garmin-sync`. Never stage `plan-data.js`, `garmin-data.js`, `.env`, `activity-archive*.db*`.
- **Copy rules:** in `.dc.html`, write real Unicode (–, →, ≈) in JSX text, never `\uXXXX`.

## Review Focus

1. **Felix's live output drifts beyond the zone edges.** The likeliest edges:
   - a leading VO2max month that used to be back-filled
   - a readiness fallback
   - a goal-gap row

   Expected: his live arrays are identical except today's tail. → Task 10, Step 9.
2. **A shelf row and a Garmin row of the same run use different timestamp formats.** Garmin writes `2026-10-19 19:09:04`, the shelf writes `2026-10-19T19:09:04`, plus fractional seconds. Expected: still detected as overlapping. → Task 2 test `test_seam_matches_across_timestamp_formats`.
3. **A shelf row with no streams or distilled detail** (1 of Max's 51). Expected: it still counts in weekly km, heatmap and CTL. It shows in recent runs with `detail` absent and elapsed pace. → Task 3 test `test_projection_tolerates_a_row_without_streams`.
4. **Garmin answers every call with an exception (429 storm).** Expected: `build_data` still emits shelf history, and no exception escapes. → Task 3 test `test_build_data_keeps_shelf_history_when_garmin_fails`.
5. **The first sync on a watch with no sleep logged and no training-readiness score.** Expected: `readiness` omitted, not a fabricated "Ready 60". → Task 5 test `test_readiness_omitted_without_evidence`.

---

### Task 0: Record the Felix parity golden (before any code change)

**Files:**
- Create: `garmin_fixtures.py` (shared test helpers, repo root; not `test_`-prefixed so pytest doesn't collect it)
- Create: `test_garmin_parity.py`
- Create: `fixtures/garmin-path/felix-golden.json` (generated)

**Interfaces:**
- Produces:
  - `garmin_fixtures.load_sync_garmin(data_dir: Path)`: imports `sync_garmin` via importlib with `SPLITS_DATA_DIR=data_dir`, sets `TODAY = dt.date(2026, 10, 21)`, returns the module.
  - `garmin_fixtures.felix_like_acts(today: dt.date) -> list[dict]`
  - `garmin_fixtures.FakeClient(responses: dict | None = None, fail: bool = False)`
  - `garmin_fixtures.shelf_row(conn, aid, uid, start, dur_s, dist_m, source="com.sec.android.app.shealth", streams=True)`
  - `garmin_fixtures.garmin_row(conn, aid, start, dur_s, dist_m)`

- [ ] **Step 1: Write `garmin_fixtures.py`**
  - **`felix_like_acts`**: deterministic, no RNG. Garmin activity-list dicts for 4 runs/week across the 30-month window ending `today`. Each has `activityId` (from 20_000_000_000 up), `startTimeLocal` "YYYY-MM-DD HH:MM:SS", `activityType.typeKey` "running", `distance`, `duration`, `averageHR`, `maxHR`, `averageRunningCadenceInStepsPerMinute`, and `activityName` cycling "Easy Run" / "Tempo Run" / "Long Run". `vO2MaxValue` goes on every 3rd run. `hrTimeInZone_1..5` go on runs in today's ISO week.
  - **`FakeClient`**: answers via `__getattr__`. Each call is recorded in `self.calls` as `(name, args)` and returns `responses.get(name)` (a value or a callable). When `fail=True`, every call raises `RuntimeError("429")`. It has real attributes `full_name = None` and `display_name = None`: `fetch_profile` reads `client.full_name` as an attribute, not a call.
  - **`felix_like_acts`'s first run** falls in the first month of the 30-month window, so the window is exactly full (as Felix's real history is).
  - **`load_sync_garmin`** sets Felix's real container env: `ATHLETE_NAME=Felix`, `ATHLETE_AGE=28`, `ATHLETE_MAX_HR=197`, `ATHLETE_RESTING_HR` unset.
  - **`shelf_row` / `garmin_row`**: insert archive rows with the exact shapes of the live data (spec "Facts").
    - Shelf: `summary_json` = a banked ingest run with `sessionUid`, `source`, `startTimeLocal` (T format), `durationS`, `distanceM`, `avgHr`, `maxHr`, `sportType` "running", and `speedSamples`/`hrSamples` ≥ 60 points. `detail_json` NULL. When `streams=True`, it gets `detail_streams_json` from `ingest_builder.synth_streams` and `detail_distilled_json` from `ingest_builder.run_detail`.
    - Garmin: `summary_json` with `activityId`, a space-format `startTimeLocal`, `distance`, `duration`, `elapsedDuration`, `activityType`, and `detail_json` = `{}`.

- [ ] **Step 2: Write `test_garmin_parity.py`**

```python
GOLDEN = REPO / "fixtures" / "garmin-path" / "felix-golden.json"
RESPONSES = {  # canned Garmin answers, fixed values
    "get_max_metrics": [{"generic": {"vo2MaxPreciseValue": 51.0}}],
    "get_user_summary": {"restingHeartRate": 48, "weight": 80500},
    "get_rhr_day": {"restingHeartRate": 48},
    "get_training_readiness": [{"score": 71, "level": "READY"}],
    "get_training_status": {}, "get_sleep_data": {"dailySleepDTO": {"sleepTimeSeconds": 27000, "deepSleepSeconds": 5400}},
    "get_activity_hr_in_timezones": [], "get_personal_record": [],
}

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
    ...  # build tmp DATA_DIR, sg = load_sync_garmin(tmp), acts = felix_like_acts(sg.TODAY)
    got = json.loads(json.dumps(_outputs(sg, FakeClient(RESPONSES), acts)))
    if os.getenv("RECORD_GOLDEN"):
        GOLDEN.write_text(json.dumps(got, indent=1), encoding="utf-8")
    assert got == json.loads(GOLDEN.read_text(encoding="utf-8"))
```

  Adjust the call signatures in `_outputs` to whatever the current functions accept (read them first). The golden must come from **today's** code.

- [ ] **Step 3: Record and run**

  Run: `RECORD_GOLDEN=1 ./.venv/Scripts/python.exe -m pytest test_garmin_parity.py -q`, then the same without `RECORD_GOLDEN`.
  Expected: PASS twice, and `fixtures/garmin-path/felix-golden.json` exists. Check that `monthly.vo2max`, `zones[*].lo/hi`, `profile.vo2maxCurrent` and `readiness.score` hold non-null values. A null golden key makes parity vacuous.

- [ ] **Step 4: Commit**

```bash
git checkout -b max-garmin-sync
git add garmin_fixtures.py test_garmin_parity.py fixtures/garmin-path/felix-golden.json docs/superpowers/specs/2026-10-21-max-garmin-sync-design.md docs/superpowers/plans/2026-10-21-max-garmin-sync.md
git commit -m "test(sync): pin Felix's Garmin-path output before the second-athlete work"
```

From here on, the golden may change in **exactly one** place, `zones[*].lo/hi` (Task 6). Any other diff is a defect.

---

### Task 1: Shelf identity, and Garmin passes leave it alone

**Files:**
- Modify: `activity_archive.py` (`missing_detail_ids` ~550; add helpers near `_RUN_TYPE_SQL` ~638)
- Test: `test_shelf.py` (create)

**Interfaces:**
- Produces:
  - `activity_archive.shelf_clause(alias: str | None = "a") -> str`: returns `"json_extract(a.summary_json, '$.sessionUid') IS NOT NULL"` (no `a.` prefix when `alias` is None).
  - `activity_archive.is_shelf_summary(summary: dict | None) -> bool`

- [ ] **Step 1: Write the failing tests** in `test_shelf.py`. Use a mixed archive: 2 shelf rows (one with streams, one without) + 2 Garmin rows.

```python
def test_missing_detail_ids_never_lists_the_shelf():
    assert set(arch.missing_detail_ids(conn)) == set()        # garmin rows carry detail_json={}
    conn.execute("UPDATE activities SET detail_json=NULL WHERE activity_id=?", (G1,))
    assert arch.missing_detail_ids(conn) == [G1]

def test_garmin_work_lists_exclude_the_shelf():
    shelf = {S1, S2}
    for ids in (arch.runs_missing_streams(conn),
                arch.runs_missing_distilled(conn, 1),
                arch.runs_missing_laps(conn),
                arch.runs_missing_maps(conn),
                [r[0] for r in arch.runs_missing_metrics(conn, 3)]):
        assert not shelf & set(ids)

def test_streamed_runs_keeps_the_shelf():           # intervals are source-agnostic (spec D3)
    assert S1 in {aid for aid, _ in arch.streamed_runs(conn)}

def test_is_shelf_summary():
    assert arch.is_shelf_summary({"sessionUid": "x"}) and not arch.is_shelf_summary({"activityId": 1})
    assert not arch.is_shelf_summary(None)
```

- [ ] **Step 2: Run** `./.venv/Scripts/python.exe -m pytest test_shelf.py -q`. Expected: FAIL (`missing_detail_ids` lists S1, S2; helpers missing).
- [ ] **Step 3: Implement** `shelf_clause`, `is_shelf_summary`, and add `AND NOT <shelf_clause(None)>` to `missing_detail_ids`'s WHERE. That one change also protects `run_backfill`. Leave the other work lists alone: the tests pin that they already exclude the shelf.
- [ ] **Step 4: Run** `test_shelf.py test_activity_archive.py test_garmin_parity.py`. Expected: PASS.
- [ ] **Step 5: Commit** `fix(archive): never ask Garmin for detail on Health Connect shelf rows`

---

### Task 2: Garmin wins the seam

**Files:**
- Create: `shelf.py`
- Modify: `activity_archive.py` (add `prune_activity`), `ingest_builder.py:868-874` (use it), `sync_garmin.py:1148-1170` (`archive_step`)
- Test: `test_shelf.py`

**Interfaces:**
- Consumes: `activity_archive.shelf_clause`.
- Produces:
  - `activity_archive.prune_activity(conn, activity_id) -> None`: deletes the row from `activities`, `run_metrics`, `run_intervals` and `activity_maps`, then commits.
  - `shelf.GARMIN_CONNECT_SOURCE = "com.garmin.android.apps.connectmobile"`
  - `shelf.resolve_seam(conn) -> list[int]`: prunes, and returns the pruned shelf ids.

- [ ] **Step 1: Write the failing tests**

```python
def test_overlapping_shelf_row_is_pruned_garmin_kept():
    shelf_row(conn, S1, "u1", "2026-10-19T19:09:04", 883, 1350)
    garmin_row(conn, G1, "2026-10-19 19:10:00", 900, 1360)
    assert shelf.resolve_seam(conn) == [S1]
    assert ids(conn) == {G1}
    assert conn.execute("SELECT COUNT(*) FROM run_metrics WHERE activity_id=?", (S1,)).fetchone()[0] == 0

def test_connect_app_shelf_row_goes_without_overlap():
    shelf_row(conn, S2, "u2", "2026-10-12T08:00:00", 1800, 5000, source=shelf.GARMIN_CONNECT_SOURCE)
    assert shelf.resolve_seam(conn) == [S2]

def test_disjoint_shelf_rows_survive_and_seam_is_idempotent():
    shelf_row(conn, S3, "u3", "2026-10-18T11:34:03", 1553, 3710)
    garmin_row(conn, G1, "2026-10-19 19:10:00", 900, 1360)
    assert shelf.resolve_seam(conn) == [] and shelf.resolve_seam(conn) == []
    assert ids(conn) == {S3, G1}

def test_seam_matches_across_timestamp_formats():     # Review Focus 2
    shelf_row(conn, S1, "u1", "2026-10-19T19:09:04.512", 883, 1350)
    garmin_row(conn, G1, "2026-10-19 19:09:04", 883, 1350)
    assert shelf.resolve_seam(conn) == [S1]

def test_archive_step_prunes_before_ratcheting(monkeypatch, tmp_path):
    # sg.archive_step(FakeClient(), [garmin act of 10-19]) on an archive holding S1 (overlapping)
    # → verify_archive() returns 0 afterwards, and expected_activity_count == current total

def test_backfill_prunes_before_ratcheting(monkeypatch, tmp_path):
    # sg.run_backfill(FakeClient({"get_activities_by_date": <callable: the 10-19 act for 2026, [] otherwise>}))
    # on an archive holding S1 → S1 gone, expected_activity_count == current total,
    # and a following sg.archive_step leaves verify_archive() == 0
```

- [ ] **Step 2: Run.** Expected: FAIL (module missing).
- [ ] **Step 3: Implement.**
  - **Spans:** both from `start_time_local` + `duration_s` columns. Parse with `dt.datetime.fromisoformat(s.replace(" ", "T"))`.
  - **Overlap:** `a_start < b_end and b_start < a_end`. Compare against every non-shelf run row.
  - **`archive_step`:** call `shelf.resolve_seam(conn)` right after `upsert_activities`, before every other pass and before `_record_expectations`. Log `– pruned N shelf rows Garmin now owns` when N > 0.
  - **`run_backfill`:** call it right after the summary year-walk, before the detail pass and `_record_expectations`. Otherwise the backfill ratchets `expected_activity_count` over a duplicate the next sync prunes, and verify fails.
  - **Refactor:** `ingest_builder.build_archive`'s inline triple-DELETE becomes `activity_archive.prune_activity`.
- [ ] **Step 4: Run** `./.venv/Scripts/python.exe -m pytest test_shelf.py test_ingest_builder.py test_garmin_parity.py -q` and `pnpm test ingest`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(sync): Garmin wins the seam over Health Connect shelf rows`

---

### Task 3: The cockpit sees the shelf

**Files:**
- Modify: `shelf.py`, `sync_garmin.py` (`act_pace` ~227, `fetch_recent_runs` ~338, `fetch_hr_zones_this_week` ~956, `build_data` ~1032, `main` ~1990)
- Test: `test_shelf.py`

**Interfaces:**
- Consumes: `activity_archive.shelf_clause`, `ingest_builder._effort(run) -> (seconds, km)`.
- Produces:
  - `shelf.shelf_activities(conn) -> list[dict]`: one dict per shelf row, newest first.
    - Garmin-shaped keys: `activityId`, `startTimeLocal`, `activityType: {"typeKey": type_key}`, `distance` (m), `duration` (s, elapsed), `averageHR`, `maxHR`.
    - Shelf markers: `splitsShelf: True`, `splitsPaceSecPerKm: int` (`round(t / km)` from `_effort` on the stored summary), and `splitsDetail: dict | None` (stored `detail_distilled_json`).
  - `sync_garmin.build_data(client, acts, pred_doc=None, sleep_raw_out=None, shelf_acts=None) -> dict`
  - `sync_garmin._load_shelf_acts() -> list[dict]`

- [ ] **Step 1: Write the failing tests**

```python
def test_projection_shape_matches_ingest_pace():
    a = shelf.shelf_activities(conn)[0]
    run = json.loads(summary_json_of(S1))
    t, km = ingest_builder._effort(run)
    assert a["splitsShelf"] is True and a["splitsPaceSecPerKm"] == round(t / km)
    assert a["activityType"]["typeKey"] == "running" and a["distance"] == run["distanceM"]

def test_projection_tolerates_a_row_without_streams():        # Review Focus 3
    a = by_id(shelf.shelf_activities(conn), S2)
    assert a["splitsDetail"] is None and a["splitsPaceSecPerKm"] > 0

def test_recent_runs_mix_shelf_and_garmin_without_calling_garmin_for_shelf():
    client = FakeClient({})
    rows = sg.fetch_recent_runs(client, garmin_acts + shelf_acts)
    assert [r["date"] for r in rows] == sorted((r["date"] for r in rows), reverse=True)
    shelf_rows = [r for r in rows if r["date"] in SHELF_DATES]
    assert shelf_rows[0]["detail"] == stored_distilled(S1) and shelf_rows[0]["cad"] is None
    assert not any(str(S1) in repr(args) for _, args in client.calls)

def test_hr_zones_skip_shelf_runs():
    client = FakeClient({})
    sg.fetch_hr_zones_this_week(client, this_week_shelf_acts, 199)
    assert client.calls == []

def test_build_data_counts_shelf_km_in_weekly_heatmap_and_ctl():
    data = sg.build_data(FakeClient(RESPONSES), [], shelf_acts=shelf_acts)
    assert sum(data["heatmapKm"]) == pytest.approx(sum(a["distance"] for a in shelf_acts) / 1000, abs=0.2)
    assert data["history"]["ctl"][-1] > 0

def test_build_data_keeps_shelf_history_when_garmin_fails():   # Review Focus 4
    data = sg.build_data(FakeClient(fail=True), [], shelf_acts=shelf_acts)
    assert sum(data["heatmapKm"]) > 0
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `act_pace` returns `a["splitsPaceSecPerKm"]` when present.
  - `fetch_recent_runs`: for `splitsShelf` entries, `detail = a.get("splitsDetail")` (omit the key when None, as the ingest path did), `cad = None`, `vo2 = None`, no `fetch_run_detail` call.
  - `fetch_hr_zones_this_week` skips `splitsShelf` entries before any client call.
  - `build_data` computes every history aggregate (heatmap, weekly, monthly, ctl/atl, recent runs, hr zones) over `acts + (shelf_acts or [])`.
  - `main` loads `shelf_acts = safe(_load_shelf_acts, [], "shelf projection")` after `course_lens_step`, and passes it to `build_data`. The projection never reaches `archive_step`.
  - With `shelf_acts=None`, behaviour is byte-identical (parity golden).
- [ ] **Step 4: Run** `test_shelf.py test_garmin_parity.py test_run_detail.py`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(sync): fold the Health Connect shelf into the cockpit's history`

---

### Task 4: Monthly series for a young account (and the pages that draw it)

**Files:**
- Modify: `sync_garmin.py` (`ffill` ~117, `fetch_monthly` ~609, `build_data` vo2 current ~1040, `validate` ~1098)
- Modify: `progress.dc.html` (~1126-1290: VO₂, pace, cadence cards), `Running Dashboard.dc.html` (~974-985: VO₂ KPI tile)
- Test: `test_shelf.py`, `test_young_account_page.mjs` (create)

**Interfaces:**
- Produces:
  - `sync_garmin.lead_null_ffill(series: list) -> list`: values before the first non-None stay None; after it, forward-filled exactly like `ffill`. All-None stays all-None.
  - `fetch_monthly(client, acts, months=MONTHS) -> dict`, same keys as today:
    - The window starts at `max(30-month window start, first month with any run in acts)`.
    - `vo2max` and `cadenceSpm` go through `lead_null_ffill`.
    - `paceSecPerKm` uses `lead_null_ffill`, and since every month after the first has a run or is interior, it is filled.
    - `get_max_metrics` is called only for months ≥ the first **non-shelf** run's month.

- [ ] **Step 1: Write the failing tests**

```python
def test_young_account_window_starts_at_first_run_without_backfill():
    acts = shelf_acts_from("2026-06-10") + garmin_acts_from("2026-10-19", vo2=44.0, cad=162)
    client = FakeClient({"get_max_metrics": [{"generic": {"vo2MaxPreciseValue": 43.7}}]})
    m = sg.fetch_monthly(client, acts)
    assert m["vo2maxStartMonth"] == "2026-06" and len(m["paceSecPerKm"]) == 5
    assert m["vo2max"][:4] == [None] * 4 and m["vo2max"][-1] == 44.0
    assert m["cadenceSpm"][:4] == [None] * 4 and m["cadenceSpm"][-1] == 162
    assert all(name != "get_max_metrics" or args[0] >= "2026-10" for name, args in client.calls)

def test_validate_accepts_leading_nulls_only():
    sg.validate(young_data)                                  # leading None ok
    with pytest.raises(AssertionError): sg.validate(with_interior_none)
    with pytest.raises(AssertionError): sg.validate(with_none_in_weeklyKm)

def test_no_vo2_anywhere_omits_vo2maxCurrent_and_still_validates():
    data = sg.build_data(FakeClient({}), [], shelf_acts=shelf_acts)
    assert "vo2maxCurrent" not in data["profile"]; sg.validate(data)
```

  `test_young_account_page.mjs`: boot `serve.mjs` on port 18431 over a tmp data dir. The `garmin-data.js` there has `vo2maxStartMonth "2026-06"`, `vo2max [null,null,null,null,44]`, `cadenceSpm [null,null,null,null,162]` and `paceSecPerKm` 5 values. Load `/` and `/progress` in Chromium and assert:
  - no `pageerror`
  - the VO₂ card's headline reads `44.0` with no `NaN`/`null` anywhere in `document.body.innerText`
  - the cadence delta does not read `+162`
  - the cockpit's VO₂ tile shows no `Top 5% for age`

- [ ] **Step 2: Run** `./.venv/Scripts/python.exe -m pytest test_shelf.py -q` and `pnpm test young_account`. Expected: FAIL.
- [ ] **Step 3: Implement the Python side.** `build_data` takes `vo2_current` from the last non-None VO₂ value. `fetch_profile` omits `vo2maxCurrent` when it's None (Task 5 removes the 51.3 fallback; do the omission here). `validate` then:
  - asserts the VO₂ equality only when `vo2maxCurrent` is present
  - allows None only as a leading run in `vo2max`/`paceSecPerKm`/`cadenceSpm`
  - never allows None in `weeklyKm`/`weeklyRuns`/`ctl`/`atl`
- [ ] **Step 4: Implement the page side.**
  - **Progress, VO₂/pace/cadence cards:** take `last`, `prev` and `first` from non-null values only. Build hover points only for non-null values (the `insightMonthly` pattern at progress.dc.html ~1319). Show an empty delta when fewer than two non-null values exist.
  - **Cockpit VO₂ tile:** `vo2Now` is the last non-null value, `vo2Prev` the non-null value 3 positions earlier, or no delta. The tile hides when no non-null value exists.
  - Replace the hardcoded sub `'Top 5% for age'` with `'Garmin estimate'`. It's a Felix-specific claim; note it in the hand-off.
- [ ] **Step 5: Run** `test_shelf.py test_garmin_parity.py`, `pnpm test young_account`, `pnpm test progress`, `pnpm test cockpit`, `pnpm test mobile`. Expected: PASS, with the golden unchanged.
- [ ] **Step 6: Commit** `fix(sync): a young account's monthly series starts at its first run, no invented months`

---

### Task 5: No Felix numbers as fallbacks

**Files:**
- Modify: `sync_garmin.py` (`fetch_profile` ~865, `fetch_readiness` ~890, `_load_label` ~932, `fetch_predictions` ~1019, `build_data`, `main` wellness call ~2007)
- Modify: `Running Dashboard.dc.html` only if a reader of `readiness.restingHR` / `profile.weightKg` / `profile.restingHR` breaks on absence (grep; the ingest instance already omits `readiness`)
- Test: `test_shelf.py` (or `test_garmin_defaults.py` if it grows), and the Task 4 page test gains a readiness-less fixture variant

**Interfaces:**
- Produces:
  - `sync_garmin._plan_goal_time() -> str | None`: the plan's `race.goalTime` via `plan_compliance.load_plan(DATA_DIR / "plan-data.js")`, None if absent or unreadable.
  - `fetch_predictions(pred_doc: dict, planned_goal: str | None) -> dict`
  - `fetch_readiness(client, sleep, max_hr) -> dict | None`

- [ ] **Step 1: Write the failing tests**

```python
def test_half_goal_comes_from_the_plan():      # tmp plan-data.js with race.goalTime "2:29:59"
    assert sg.build_data(FakeClient(RESPONSES), acts)["predictions"]["halfGoal"] == "2:29:59"

def test_profile_omits_what_garmin_did_not_say():
    p = sg.fetch_profile(FakeClient({}), None)
    for k in ("restingHR", "weightKg", "vo2maxCurrent"): assert k not in p
    assert p["name"] != "Felix"                 # env unset, client has no name → "Athlete"

def test_readiness_omitted_without_evidence():                 # Review Focus 5
    assert sg.fetch_readiness(FakeClient({}), [{"hours": 0.0, "hrv": 0, "deepPct": 0}] * 14, 199) is None

def test_readiness_without_rhr_omits_the_key_and_load_label_is_honest():
    r = sg.fetch_readiness(FakeClient({"get_training_readiness": [{"score": 64, "level": "READY"}]}),
                           sleep_with_one_night, 199)
    assert "restingHR" not in r and r["loadStatus"] == ""
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - **`fetch_profile`:**
    - Drop the `47` / `81.0` / `51.3` fallbacks; omit the key instead.
    - Name fallback: `client.full_name` first word, else `"Athlete"`.
    - Keep the `ATHLETE_AGE`/`ATHLETE_MAX_HR` env defaults: every instance sets them (spec D5).
  - **`fetch_readiness`:**
    - Return None when Garmin gives no readiness score, no night has `hours`, and no night has `hrv`.
    - The RHR fallback `46` becomes None, and the `restingHR` key is omitted when None.
    - `_load_label` falls back to `""`.
  - **`build_data`:** set `data["readiness"]` only when not None. Pass `_plan_goal_time()` to `fetch_predictions`.
  - **`main`:** pass `data.get("readiness") or {}` to `wellness_step`.
  - Guard any cockpit reader the grep finds. Felix's plan's `race.goalTime` is `"1:59:59"`, so his `halfGoal` is unchanged.
- [ ] **Step 4: Run** `test_garmin_parity.py test_shelf.py test_wellness.py`, `pnpm test young_account`, `pnpm test cockpit`. Expected: PASS, golden unchanged.
- [ ] **Step 5: Commit** `fix(sync): unknown means absent — no Felix numbers as Garmin-path fallbacks`

---

### Task 6: Zones per athlete, and zone-card edges from the watch

**Files:**
- Modify: `sync_garmin.py` (`distill_run_detail` ~485, `derive_intervals` ~1186-1284, `fetch_hr_zones_this_week` ~956, `main` argparse), `activity_archive.py`, `docker-compose.yml` (commented `ATHLETE_RESTING_HR` line in the profile-overrides block of `splits`), `README.md` (env table row)
- Test: `test_shelf.py` (zones section)

**Interfaces:**
- Consumes: `activity_archive.is_shelf_summary`, `interval_lens.zone_bounds(max_hr, rhr=None)`, `interval_lens.compact(doc)`.
- Produces:
  - `sync_garmin.athlete_zone_bounds() -> list[int]`: `zone_bounds(int(ATHLETE_MAX_HR or 197), int(ATHLETE_RESTING_HR) if set else None)`.
  - `activity_archive.patch_distilled_intervals(conn, activity_id, compact) -> bool`: replaces only the `intervals` key of a stored distilled summary.
  - `activity_archive.invalidate_distilled(conn) -> int`: sets `distilled_version = NULL` on every non-shelf row holding a distilled copy, so `_distill_pass` re-derives it.
  - archive_meta key `interval_zone_bounds` (JSON list).
  - CLI flag `sync_garmin.py --rescore-intervals`: one pass that treats the zones as changed. Rescore every document, invalidate distilled, stamp, then exit. It's offline: handle it before `connect()`, like `--verify-archive`.

- [ ] **Step 1: Write the failing tests**

```python
def test_zone_model_follows_resting_hr_env(monkeypatch):
    monkeypatch.setenv("ATHLETE_MAX_HR", "199"); monkeypatch.delenv("ATHLETE_RESTING_HR", raising=False)
    assert sg.athlete_zone_bounds() == [100, 119, 139, 159, 179, 199]
    monkeypatch.setenv("ATHLETE_RESTING_HR", "57")
    assert sg.athlete_zone_bounds() == [128, 142, 156, 171, 185, 199]

def test_first_stamp_does_not_rescore_then_a_change_does():
    sg.derive_intervals(conn)                    # meta absent → stamp only
    before = docs(conn)
    monkeypatch.setenv("ATHLETE_RESTING_HR", "57")
    sg.derive_intervals(conn)
    assert docs(conn) != before                  # every doc rescored under Karvonen
    assert garmin_distilled_versions(conn) == {None}
    assert json.loads(distilled_of(S1))["intervals"] == il.compact(json.loads(doc_of(S1)))

def test_zone_card_edges_come_from_the_watch():
    client = FakeClient({"get_activity_hr_in_timezones": [
        {"zoneNumber": z, "secsInZone": 60, "zoneLowBoundary": lo}
        for z, lo in zip(range(1, 6), (99, 128, 142, 156, 171))]})
    zones = sg.fetch_hr_zones_this_week(client, garmin_acts_this_week_without_summary_zones, 199)
    assert [(z["lo"], z["hi"]) for z in zones] == [(99,128),(128,142),(142,156),(156,171),(171,199)]

def test_zone_card_falls_back_to_athlete_bounds():
    zones = sg.fetch_hr_zones_this_week(FakeClient({}), garmin_acts_this_week, 199)
    assert [z["lo"] for z in zones] == sg.athlete_zone_bounds()[:5]
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Both `zone_bounds(max_hr)` call sites use `athlete_zone_bounds()`.
  - **`derive_intervals`:** compare `athlete_zone_bounds()` with meta `interval_zone_bounds`.
    - Absent: stamp only.
    - Different, or `--rescore-intervals`: `moved = True`, call `invalidate_distilled`, stamp.
    - After each upserted doc of a **shelf** row, call `patch_distilled_intervals(conn, aid, interval_lens.compact(doc))`.
  - **`fetch_hr_zones_this_week`:** after counting minutes, read edges from the newest non-shelf run of the week that has `get_activity_hr_in_timezones` rows carrying `zoneLowBoundary`: `lo` = the boundary, `hi` = the next zone's boundary, Z5 `hi` = `max_hr`. That's one extra call per sync at most. Fall back to `athlete_zone_bounds()`.
- [ ] **Step 4: Run** `test_shelf.py test_interval_lens.py test_run_detail.py test_garmin_parity.py`.
  - Expected: PASS. The parity golden is unchanged: the FakeClient's empty zone rows fall back to %max edges, which equal today's.
  - Then confirm on the real local Felix archive copy that `--rescore-intervals` is NOT needed for him. With `ATHLETE_RESTING_HR` unset, the stamp equals the %max bounds, so nothing rescored.
- [ ] **Step 5: Commit** `feat(sync): per-athlete zone model (ATHLETE_RESTING_HR) and zone-card edges from the watch`

---

### Task 7: Shelf metrics heal from their streams

**Files:**
- Modify: `insight_metrics.py` (`extract_run_metrics` ~227), `activity_archive.py`, `ingest_builder.py:795-805` (`_metric_samples` delegates)
- Test: `test_shelf.py`

**Interfaces:**
- Produces:
  - `insight_metrics.samples_from_streams(streams: dict) -> list[tuple]`, moved verbatim from `ingest_builder._metric_samples`, which now returns `insight_metrics.samples_from_streams(streams)`.
  - `activity_archive.shelf_runs_missing_metrics(conn, version) -> list[tuple]`: `(activity_id, start_time_local, type_key, distance_m)` for shelf runs holding streams without a `run_metrics` row at `version`.

- [ ] **Step 1: Write the failing tests**

```python
def test_metrics_version_bump_heals_shelf_rows(monkeypatch):
    monkeypatch.setattr(im, "METRICS_VERSION", im.METRICS_VERSION + 1)
    im.extract_run_metrics(conn)
    row = metrics_row(conn, S1, im.METRICS_VERSION)
    assert row is not None and row == ingest_computed_metrics(S1)     # same numbers ingest_builder computes
    assert sg.verify_archive() == 0                                    # with sg.DATA_DIR = the fixture dir

def test_samples_from_streams_parity():
    assert ingest_builder._metric_samples(streams) == im.samples_from_streams(streams)
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** `extract_run_metrics` handles `runs_missing_metrics` (Garmin, unchanged) and then `shelf_runs_missing_metrics`. Samples come from `samples_from_streams(streams_payload(...))` with `declared_dist_m=distance_m`. A shelf row without streams is never listed.
- [ ] **Step 4: Run** `test_shelf.py test_insight_metrics.py test_ingest_builder.py test_garmin_parity.py`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(metrics): a METRICS_VERSION bump heals shelf rows from their streams`

---

### Task 8: Prediction sources don't splice; the Block goal gap restarts at the switch

**Files:**
- Modify: `activity_archive.py`, `insight_metrics.py:399-445` (`weekly_trajectory`), `block_lens.py:48` (version) and `:330-355` (`_goal_gap`), `coach_briefing.py:189-196`, `progress.dc.html` (~670 reason map, ~760 GOAL GAP stat)
- Test: `test_shelf.py` (predictions section), `test_block_lens.py`, `test_coach_briefing.py`

**Interfaces:**
- Produces:
  - `activity_archive.half_predictions(conn, until: str | None = None) -> list[tuple[str, float]]`: `(date, half_s)` ordered by date, `half_s` not null, `date <= until`. Non-riegel rows only when any non-riegel row exists in the table, otherwise all rows.
  - `activity_archive.prediction_sources_mixed(conn) -> bool`: both riegel and non-riegel rows exist.
  - `block_lens._goal_gap` output gains `"baseline": "source-change"` when restarted; the key is absent otherwise.
  - `BLOCK_LENS_VERSION = 3`.

- [ ] **Step 1: Write the failing tests**

```python
def test_felix_like_sources_unchanged():          # sync + backfill rows, no riegel
    assert arch.half_predictions(conn_felix) == all_rows(conn_felix)

def test_ingest_only_instance_keeps_riegel():
    assert arch.half_predictions(conn_riegel_only) == all_rows(conn_riegel_only)

def test_mixed_instance_drops_riegel_everywhere():
    rows = arch.half_predictions(conn_mixed)          # riegel 2026-07-30..10-21, sync from 10-21
    assert rows and min(d for d, _ in rows) == "2026-10-21"
    traj = im.weekly_trajectory(conn_mixed, dt.date(2026, 10, 25))
    assert all(w["garminSec"] is None for w in traj if w["week"] < "2026-W43")

def test_goal_gap_restarts_at_the_switch():
    gap = bl._goal_gap(conn_mixed, {"goalTime": "2:29:59"}, dt.date(2026, 7, 20), dt.date(2026, 11, 7))
    assert gap["baseline"] == "source-change" and gap["startDate"] == "2026-10-21"
    assert gap["deltaS"] == round(latest_sync_half - first_sync_half)

def test_goal_gap_unchanged_for_felix_like_block():
    gap = bl._goal_gap(conn_felix, race, start, end)
    assert "baseline" not in gap and gap == RECORDED_BEFORE_CHANGE
    # RECORDED_BEFORE_CHANGE: the literal dict today's _goal_gap returns for this
    # fixture, captured by running it BEFORE Step 3 and pasted in

def test_briefing_names_the_restart():
    line = goal_gap_line(cb.block_report_lines(doc_with_restarted_gap))
    assert "since 2026-10-21 (Garmin predictor)" in line
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Both readers' SQL switches to `half_predictions`.
  - **`_goal_gap`:** after the tolerance check fails, if `prediction_sources_mixed(conn)` and `preds[0][0] > start + tolerance`, anchor on `preds[0]` and set `baseline`. Otherwise keep `no-baseline-prediction`.
  - **Briefing line:** `- goal gap (2:29:59) since 2026-10-21 (Garmin predictor): +X → +Y vs goal — closing`.
  - **Progress card:** the GOAL GAP stat's note reads `since <startDate> · Garmin predictor` when `baseline === 'source-change'`.
  - Bump `BLOCK_LENS_VERSION`.
- [ ] **Step 4: Run** `test_shelf.py test_block_lens.py test_coach_briefing.py test_coach_pass.py test_insight_metrics.py test_garmin_parity.py`, then `pnpm test block` and `pnpm test progress`.
  - Expected: PASS.
  - `test_coach_pass.py`'s golden may need its `blockLens` version field re-recorded. Confirm the only diff is the version number before re-recording.
- [ ] **Step 5: Commit** `feat(lens): prediction readers never splice models; Max's goal gap restarts at the switch`

---

### Task 9: Max's watch checklist

**Files:**
- Create: `docs/onboarding/max-garmin.md`

- [ ] **Step 1: Write the checklist** (English, plain language, the same tone as `openspec/changes/add-max-healthconnect-ingestion/ONBOARDING-PIXEL.md`). Sections from spec D10:
  - **Garmin Connect profile:** birth date / age 23, max HR 199, resting HR auto, then HR zones based on %HRR, then a table **"Enter these exact zone edges (bpm)"** with Z1–Z5 low edges filled at cutover in Task 10 Step 6. Until then the cells hold the literal text `filled at cutover`.
  - **Uninstall SPLITS Bridge.**
  - **Wear the watch overnight;** HRV status takes about 3 weeks.
  - **Record strength and mobility on the watch** (it's why those days start scoring).
  - **Garmin's race predictor runs optimistic early;** the Wk 16 5K on 2026-11-07 is the real re-anchor.
- [ ] **Step 2: Commit** `docs(onboarding): Max's Forerunner checklist`

---

### Task 10: Ship and cut over (NUC)

Every NUC command runs as `ssh felix@192.168.0.37 "cd ~/dev/docker-compose-files/splits && …"`. Abort and report on any unexpected output.

- [ ] **Step 1: Full local suite.** `./.venv/Scripts/python.exe -m pytest -q` and `pnpm test`. Expected: all green, apart from failures that are already red on `main`. Check those by running the same command on `main` first.
- [ ] **Step 2: Merge and publish.** `git checkout main && git merge --no-ff max-garmin-sync && git push`. Then `gh run list --branch main --limit 1` until the docker-publish run is `completed success`.
- [ ] **Step 3: Pre-flip backups on the NUC.**
  - Before anything pulls, tag the running image so a rollback is a retag: `docker tag ghcr.io/1-felix/splits:latest ghcr.io/1-felix/splits:rollback-2026-10-21`.
  - Back up `cp docker-compose.yml docker-compose.yml.bak-2026-10-21`.
  - Back up Felix's live file: `cp volumes/splits-data/garmin-data.js volumes/splits-data/garmin-data.js.bak-2026-10-21`.
  - For Max, inside `splits-max`:
    - a consistent `sqlite3.backup` of `/data/activity-archive.db` to `/data/activity-archive.db.bak-2026-10-21`
    - `cp` of `ingested-runs.json`, `garmin-data.js` and `coach-briefing.md` to `.bak-2026-10-21`
    - `chmod 644` on all of them

  Verify with `ls -la volumes/splits-max-data`.
  - Read-only checks on BOTH archives. The shelf predicate is a `json_extract`, which raises on invalid JSON, and the seam compares naive local start times. Run this in an ssh session on the NUC; its quotes don't survive the `ssh "…"` wrapper:

```bash
for svc in splits splits-max; do
  docker compose exec -T $svc python3 -c "import sqlite3; c=sqlite3.connect('file:/data/activity-archive.db?mode=ro', uri=True); q=lambda s: c.execute(s).fetchone()[0]; print(q('SELECT count(*) FROM activities WHERE json_valid(summary_json)=0'), q(\"SELECT count(*) FROM activities WHERE start_time_local LIKE '%Z' OR start_time_local LIKE '%+%'\"))"
done
```

  Expected: `0 0` for each archive (no invalid `summary_json`, no `start_time_local` with a timezone suffix). Anything else: stop and report.
- [ ] **Step 4: Pull the image.** Run `docker compose pull && docker compose up -d`. Both containers now run the new image, and Max is still ingest-fed. Then:
  - Run Felix's sync once by hand, BEFORE his verify: `docker compose exec -T splits python3 sync_garmin.py`. `BLOCK_LENS_VERSION` 3 makes his stored v2 block rows stale until a sync recomputes them, and the boot sync is skipped while telemetry is fresh, so verify would fail on them until the 08:00 nightly.
  - `docker compose exec -T splits python3 sync_garmin.py --verify-archive` → exit 0.
  - Now do Step 9 (R10): Felix's parity check runs right after this manual sync.
  - `docker logs splits-max --tail 20` → a clean boot build.
- [ ] **Step 5: Read Max's resting HR from Garmin.**

```bash
docker compose exec -T splits-max python3 -c "import datetime,sync_garmin as s; c=s.connect(); d=c.get_user_summary(datetime.date.today().isoformat()) or {}; print(d.get('lastSevenDaysAvgRestingHeartRate'), d.get('restingHeartRate'))"
```

  Use the 7-day average. If it's None, use 57 (his established value) and note a re-check in two weeks.
- [ ] **Step 6: Flip `splits-max`.** Replace its `environment:` and `labels:` in the NUC compose with exactly the block below. `RHR` is the Step 5 value. Then `docker compose config -q`.

```yaml
    environment:
      TZ: ${TZ:-Europe/Berlin}
      # Garmin sync since 2026-10-21 (Forerunner 265S). Health Connect history is
      # kept in the archive as the frozen shelf — see docs/superpowers/specs/2026-10-21-max-garmin-sync-design.md
      GARMIN_EMAIL: ${MAX_GARMIN_EMAIL:-}
      GARMIN_PASSWORD: ${MAX_GARMIN_PASSWORD:-}
      SYNC_AT: "08:15" # after Felix's 08:00 — one IP, Garmin rate-limits logins
      ATHLETE_NAME: "Max"
      ATHLETE_AGE: "23"
      ATHLETE_MAX_HR: "199" # measured 2026-07 on a max spinning effort
      ATHLETE_RESTING_HR: "RHR" # Garmin 7-day avg at cutover; change together with the watch's zones
    labels:
      traefik.http.routers.splits-max.rule: Host(`splits-max.mochii.dev`) || Host(`splits-max.l.mochii.dev`)
      traefik.http.routers.splits-max.middlewares: pocketid-auth-family@file # family-scoped: needs the pocket-id `family` group
      traefik.http.routers.splits-max.entryPoints: https
      traefik.enable: true
```

  `ATHLETE_RESTING_HR` must be an integer (quoted in YAML, e.g. `"57"`).

  Recreate the container so it carries the new env, then check the real env. `exec` reads the running container's env, so this check only means something after the `up -d`:

```bash
docker compose up -d splits-max
docker compose exec -T splits-max python3 -c "import sync_garmin as s; print(s.athlete_zone_bounds())"
```

  It must print the Karvonen edges for the chosen RHR (for 57: `[128, 142, 156, 171, 185, 199]`). The %max edges `[100, 119, 139, 159, 179, 199]`, or a `! ATHLETE_RESTING_HR=… is not a resting HR` warning, mean the value didn't land: fix the compose and `up -d` again before Step 7.

  Fill the zone-edge table in `docs/onboarding/max-garmin.md` from `docker compose exec -T splits-max python3 -c "import interval_lens; print(interval_lens.zone_bounds(199, RHR))"`, then commit `docs(onboarding): Max's zone edges at cutover` and push.
- [ ] **Step 7: First Garmin sync.** The container is up since Step 6's `docker compose up -d splits-max`. Before the first `exec` below, read `docker logs splits-max` until the boot sync reports `boot sync skipped (telemetry is fresh)`, `boot sync ok` or `boot sync failed`, so there's no concurrent archive writer and no second Garmin session.

```bash
docker compose exec -T splits-max python3 sync_garmin.py --backfill
docker compose exec -T splits-max python3 sync_garmin.py --rescore-intervals
docker compose exec -T splits-max python3 sync_garmin.py
docker compose exec -T splits-max python3 sync_garmin.py --backfill-wellness
docker compose exec -T splits-max python3 sync_garmin.py
docker compose exec -T splits-max python3 sync_garmin.py --verify-archive
```

  Expected:
  - the backfill lists 2+ Garmin activities
  - the plain sync logs `– pruned 1 shelf rows Garmin now owns` and `✓ wrote garmin-data.js`
  - `--backfill-wellness` starts at the first Garmin activity on its own (`… wellness backfill: 2026-10-19 → …`), so it costs about 3 days × 3 calls at most, and none when the plain sync before it already banked those nights
  - verify exits 0, with the wellness gate armed (`coverage complete` from the wellness backfill)

  If Garmin answers 429, stop and wait. Never loop logins.
- [ ] **Step 8: Verify Max's instance.** Collect the evidence in the hand-off:
  - `curl -s http://192.168.0.37:5733/api/status` shows `ingestFed: false` and `archive: true`.
  - **Route gone.** `curl -s -X POST https://splits-max.mochii.dev/api/ingest` returns the SSO body (`"title"`), not the app's `"error":"unauthorized"`.
  - **Archive rows**, read-only:
    - 50 shelf rows
    - 2026-10-19 present once (the Garmin row)
    - `run_metrics` at the current version for every run with streams
    - compliance weeks ≥ 14
  - **The page** (logged-in browser; read with `document.body.innerText`, not a navigation snapshot):
    - weekly km spans June → this week
    - today's 4.30 km is in recent runs, alongside shelf runs
    - `halfGoal` 2:29:59
    - no `51.3`, `81`, `Top 5%`
    - the Block card's goal gap says `since 2026-10-21 · Garmin predictor`
- [ ] **Step 9: Verify Felix didn't move** (Review Focus 1). Runs right after Step 4's manual sync (R10), not after the 08:00 nightly. Compare `volumes/splits-data/garmin-data.js` with the `.bak-2026-10-21`:
  - same top-level and `history` key sets
  - same array lengths
  - every history array equal except its last element
  - `hrZones` differs only in `lo`/`hi`
  - the only other expected deltas:
    - `blockLens.lensVersion` 2 → 3 (frozen past blocks are recomputed once)
    - `predictions.halfGoal` now comes from his plan (value unchanged, `"1:59:59"`)
    - a readiness or profile key is omitted only if Garmin returned nothing for it
  - on the pages (copy, not data): the VO₂ tile's sub-label reads "Garmin estimate", the VO₂ delta uses a true minus, and the all-time pace and cadence deltas on /progress carry their real sign

  `--verify-archive` already exited 0 in Step 4. Report the zone edges to Felix so he can confirm they match his watch.
- [ ] **Step 10: Hand-off.**
  - Send Felix the checklist link for Max.
  - Update memory `max-garmin-switch.md` (status → shipped, commits, NUC facts, the RHR value used, follow-ups) and the MEMORY.md line.
  - Follow-ups:
    - per-athlete insight reference bands (spec non-goal)
    - re-check `ATHLETE_RESTING_HR` after two weeks of Garmin nights
    - Max's Wk 16→17 plan seam
