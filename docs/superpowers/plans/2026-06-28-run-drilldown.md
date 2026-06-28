# Per-Run Drill-Down with Plan-Aware Coach-Read — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make each run in the dashboard's Recent Activities table click-to-expand into an inline detail strip (per-km splits, HR-drift, zone breakdown) topped by a plan-aware one-line coach-read.

**Architecture:** The sync (Python) pre-computes each recent run's objective `detail` (splits, drift, zones, temp, TE) into `garmin-data.js`. A pure, unit-tested `coach-read.js` module turns those numbers + the plan into one sentence; `running-data.js` attaches that sentence as `recentRuns[i].read` at merge time (this is where telemetry + plan meet — a small refinement of the spec's "in the dashboard", chosen for testability). The `dc.html` component adds an `expandedRun` state and renders the detail strip from stored data, reusing the existing `this.line()` sparkline helper.

**Tech Stack:** Python 3 + garminconnect (sync), vanilla ES-module JS (data layer), the `dc-runtime` React-render of `Running Dashboard.dc.html`, Node for JS unit tests, Playwright MCP for render verification.

## Global Constraints

- Python is run via the project venv: `& ".\.venv\Scripts\python.exe" <script>` (PowerShell).
- Node is on PATH; the static server is `pnpm dev` (→ http://localhost:8000/Running%20Dashboard.dc.html). Use pnpm, never npm.
- `garmin-data.js` is **gitignored** (real health telemetry) — never commit it. `.env` and `.garmin_cache/` likewise.
- Commit messages: **no Co-Authored-By line, no Claude attribution.**
- Text content uses literal Unicode characters (`⚡ → ° ·`), never escape sequences.
- No TypeScript; plain JS. Follow the flat repo layout (scripts at root, like `validate_data.py`).
- `support.js` is a generated runtime — do not edit it.

---

## File Structure

- `sync_garmin.py` (modify) — add detail helpers + `fetch_run_detail()`; thread `client` into `fetch_recent_runs()`.
- `coach-read.js` (create) — pure `coachRead(run, weekPlan, maxHR)` heuristics.
- `running-data.js` (modify) — import `coachRead`, attach `read` to runs with detail.
- `Running Dashboard.dc.html` (modify) — `expandedRun` state, `toggleRun`, `runDetail`, runs view-model, clickable rows + inline detail template.
- `validate_data.py` (modify) — assert `detail` shape when present.
- `test_run_detail.py` (create) — Python unit tests for the detail helpers + `fetch_run_detail`.
- `test_coach_read.mjs` (create) — Node unit tests for `coachRead`.
- `README.md` (modify) — one line documenting the drill-down.

---

### Task 1: Python detail helpers

**Files:**
- Modify: `sync_garmin.py` (add helpers near the other `act_*` helpers, before the FETCHERS section)
- Test: `test_run_detail.py` (create at repo root)

**Interfaces:**
- Produces:
  - `_downsample(series: list, n: int = 30) -> list`
  - `_hr_drift(hr: list) -> int` (2nd-half avg − 1st-half avg, rounded)
  - `_split_shape(splits: list[dict]) -> str` (`"even"|"positive"|"negative"`)
  - `_bin_splits(rows: list, idx: dict) -> list[dict]` (each `{"km": int, "pace": int, "hr": int}`)

- [ ] **Step 1: Write the failing test**

Create `test_run_detail.py`:

```python
"""Unit tests for sync_garmin detail helpers (no Garmin network)."""
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("sync_garmin", REPO / "sync_garmin.py")
sg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sg)


def test_downsample():
    assert sg._downsample(list(range(100)), 10) == [0, 10, 20, 30, 40, 50, 60, 70, 80, 90]
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
    rows = [{"metrics": [500, 150, 3.0]}, {"metrics": [900, 160, 3.0]}, {"metrics": [1500, 170, 2.5]}]
    out = sg._bin_splits(rows, idx)
    assert out[0]["km"] == 1 and out[0]["hr"] == 155 and out[0]["pace"] == 333
    assert out[1]["km"] == 2 and out[1]["hr"] == 170


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_"):
            _fn()
            print("ok", _name)
    print("ALL PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& ".\.venv\Scripts\python.exe" test_run_detail.py`
Expected: FAIL — `AttributeError: module 'sync_garmin' has no attribute '_downsample'`

- [ ] **Step 3: Write minimal implementation**

In `sync_garmin.py`, add after `act_vo2()` (before `classify()`):

```python
def _downsample(series, n=30):
    series = [v for v in series if v is not None]
    if len(series) <= n:
        return series
    step = len(series) / n
    return [series[int(i * step)] for i in range(n)]


def _hr_drift(hr):
    hr = [v for v in hr if v is not None]
    if len(hr) < 4:
        return 0
    half = len(hr) // 2
    first = sum(hr[:half]) / half
    second = sum(hr[half:]) / (len(hr) - half)
    return int(round(second - first))


def _split_shape(splits):
    paces = [s["pace"] for s in splits if s.get("pace")]
    if len(paces) < 3:
        return "even"
    third = max(1, len(paces) // 3)
    first = sum(paces[:third]) / third
    last = sum(paces[-third:]) / third
    if first <= 0:
        return "even"
    delta = (last - first) / first
    if delta > 0.04:
        return "positive"   # slowed (pace seconds increased)
    if delta < -0.04:
        return "negative"   # sped up
    return "even"


def _bin_splits(rows, idx):
    iD, iHR, iSpd = idx.get("sumDistance"), idx.get("directHeartRate"), idx.get("directSpeed")
    buckets = {}
    for row in rows:
        m = row.get("metrics") or []
        try:
            dist = m[iD]
            hr = m[iHR] if iHR is not None else None
            spd = m[iSpd] if iSpd is not None else None
        except (TypeError, IndexError):
            continue
        if dist is None:
            continue
        buckets.setdefault(int(dist // 1000), []).append((hr, spd))
    out = []
    for km in sorted(buckets):
        hrs = [h for h, s in buckets[km] if h is not None]
        spds = [s for h, s in buckets[km] if s]
        avg_spd = sum(spds) / len(spds) if spds else 0
        out.append({
            "km": km + 1,
            "pace": int(round(1000 / avg_spd)) if avg_spd else 0,
            "hr": int(round(sum(hrs) / len(hrs))) if hrs else 0,
        })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `& ".\.venv\Scripts\python.exe" test_run_detail.py`
Expected: PASS — prints `ok test_downsample` … `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add test_run_detail.py sync_garmin.py
git commit -m "feat: add per-km split / HR-drift / shape helpers to sync"
```

---

### Task 2: `fetch_run_detail()` + wire into recent runs

**Files:**
- Modify: `sync_garmin.py` (add `fetch_run_detail`; change `fetch_recent_runs` signature to take `client`; update its `build_data` call)
- Test: `test_run_detail.py` (add a `FakeClient` shape test)

**Interfaces:**
- Consumes: `_downsample`, `_hr_drift`, `_split_shape`, `_bin_splits` (Task 1), existing `safe`, `CACHE_DIR`.
- Produces:
  - `fetch_run_detail(client, activity) -> dict | None` returning keys `splits, hrSeries, driftBpm, zoneMin, tempC, te, load, elevGain, splitShape`.
  - `fetch_recent_runs(client, acts, n=RECENT_RUNS)` — now first-param `client`; each run dict gains `"detail"`.

- [ ] **Step 1: Write the failing test**

Append to `test_run_detail.py` (before the `__main__` block):

```python
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
                {"metrics": [2100, 176, 2.6]},
            ],
        }


def test_fetch_run_detail_shape():
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
```

Note: this writes a cache file `.garmin_cache/detail-999.json` (already gitignored).

- [ ] **Step 2: Run test to verify it fails**

Run: `& ".\.venv\Scripts\python.exe" test_run_detail.py`
Expected: FAIL — `AttributeError: module 'sync_garmin' has no attribute 'fetch_run_detail'`

- [ ] **Step 3: Write minimal implementation**

In `sync_garmin.py`, add `fetch_run_detail` in the FETCHERS section (after `fetch_recent_runs`):

```python
def fetch_run_detail(client, activity) -> dict | None:
    """Per-run drill-down detail (splits, HR-drift, zones, temp, TE). Cached per
    activity id so re-syncs only fetch genuinely new runs."""
    aid = activity.get("activityId")
    if not aid:
        return None
    CACHE_DIR.mkdir(exist_ok=True)
    cache = CACHE_DIR / f"detail-{aid}.json"
    if cache.exists():
        det = json.loads(cache.read_text(encoding="utf-8"))
    else:
        det = safe(lambda: client.get_activity_details(aid, maxchart=2000, maxpoly=0),
                   None, f"detail {aid}")
        if not det:
            return None
        cache.write_text(json.dumps(det, ensure_ascii=False), encoding="utf-8")

    idx = {d.get("key"): d.get("metricsIndex") for d in (det.get("metricDescriptors") or [])}
    rows = det.get("activityDetailMetrics") or []
    splits = _bin_splits(rows, idx)

    iHR = idx.get("directHeartRate")
    hr_all = []
    for row in rows:
        m = row.get("metrics") or []
        if iHR is not None and iHR < len(m) and m[iHR] is not None:
            hr_all.append(m[iHR])

    zone_min = [int(round((activity.get(f"hrTimeInZone_{k}") or 0) / 60)) for k in range(1, 6)]
    temp = activity.get("maxTemperature")
    if temp is None:
        temp = activity.get("minTemperature")
    load = activity.get("activityTrainingLoad")
    elev = activity.get("elevationGain")
    return {
        "splits": splits,
        "hrSeries": [int(round(v)) for v in _downsample(hr_all, 30)],
        "driftBpm": _hr_drift(hr_all),
        "zoneMin": zone_min,
        "tempC": int(round(temp)) if temp is not None else None,
        "te": activity.get("aerobicTrainingEffect"),
        "load": round(load) if load else None,
        "elevGain": round(elev) if elev else None,
        "splitShape": _split_shape(splits),
    }
```

Change `fetch_recent_runs` to accept `client` and attach detail. Replace its signature line and the appended dict:

```python
def fetch_recent_runs(client, acts: list[dict], n: int = RECENT_RUNS) -> list[dict]:
    runs = [a for a in acts if is_run(a) and act_km(a) > 0]
    runs.sort(key=act_date, reverse=True)
    out = []
    for a in runs[:n]:
        out.append({
            "date": act_date(a),
            "type": classify(a),
            "km": round(act_km(a), 1),
            "time": fmt_hms(act_dur(a)),
            "pace": act_pace(a),
            "hr": act_hr(a) or 0,
            "cad": act_cad(a),
            "vo2": round(act_vo2(a), 1) if act_vo2(a) else None,
            "detail": fetch_run_detail(client, a),
        })
    return out
```

In `build_data`, update the call:

```python
        "recentRuns": fetch_recent_runs(client, acts),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `& ".\.venv\Scripts\python.exe" test_run_detail.py`
Expected: PASS — `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add test_run_detail.py sync_garmin.py
git commit -m "feat: fetch and store per-run drill-down detail in recentRuns"
```

---

### Task 3: Validate `detail` shape

**Files:**
- Modify: `validate_data.py` (add to `validate()` before `return e`)

**Interfaces:**
- Consumes: existing `check(cond, msg, errors)`; the merged `recentRuns[i].detail` shape from Task 2.

- [ ] **Step 1: Write the failing test**

In `validate_data.py`, inside `validate(d)`, just before `return e`, add:

```python
    # per-run drill-down detail (present once the sync has run Task 2)
    for r in d.get("recentRuns", []):
        det = r.get("detail")
        if det is None:
            continue
        check(isinstance(det.get("splits"), list) and len(det["splits"]) > 0,
              "recentRuns detail.splits must be a non-empty list", e)
        check(all(isinstance(s.get("pace"), int) for s in det.get("splits", [])),
              "recentRuns detail.splits pace must be int seconds", e)
        check(isinstance(det.get("zoneMin"), list) and len(det["zoneMin"]) == 5,
              "recentRuns detail.zoneMin must have 5 entries", e)
        check(isinstance(det.get("driftBpm"), (int, float)),
              "recentRuns detail.driftBpm must be numeric", e)
```

- [ ] **Step 2: Run to verify current data still validates**

Run: `& ".\.venv\Scripts\python.exe" validate_data.py`
Expected: PASS — `✓ all invariants hold` (current `garmin-data.js` has no `detail` yet, so the new block is skipped; nothing breaks).

- [ ] **Step 3: (implementation already written in Step 1 — no separate impl step)**

This task's "implementation" is the assertion block itself; it is exercised for real after the sync regenerates `detail` in Task 8.

- [ ] **Step 4: Commit**

```bash
git add validate_data.py
git commit -m "test: assert recentRuns detail shape in validate_data"
```

---

### Task 4: `coach-read.js` engine

**Files:**
- Create: `coach-read.js` (repo root)
- Test: `test_coach_read.mjs` (repo root)

**Interfaces:**
- Produces: `export function coachRead(run, weekPlan, maxHR) -> string`. `run` has `date, type, km, pace, hr, detail{zoneMin[5], driftBpm, tempC, splitShape, te}`. `weekPlan` is the array from `plan-data.js` (entries `{date, kind, load, title}`). Returns one sentence (empty string if no `detail`).

- [ ] **Step 1: Write the failing test**

Create `test_coach_read.mjs`:

```javascript
import assert from "node:assert";
import { coachRead } from "./coach-read.js";

const maxHR = 197;
const wp = [{ date: "2026-06-28", kind: "run", load: "Moderate", title: "Long Run" }];

// rule 1 — easy intent, hot, high HR + drift -> heat/threshold
let r = { date: "2026-06-28", type: "Long Run", km: 16, pace: 372, hr: 170,
  detail: { zoneMin: [0, 6, 32, 55, 5], driftBpm: 16, tempC: 28, splitShape: "positive", te: 5.0 } };
assert.match(coachRead(r, wp, maxHR), /pushed HR to threshold/);

// rule 2 — big drift, not hot
r = { date: "x", type: "Run", km: 10, pace: 400, hr: 150,
  detail: { zoneMin: [2, 20, 20, 5, 0], driftBpm: 14, tempC: 14, splitShape: "even" } };
assert.match(coachRead(r, [], maxHR), /cardiac drift/);

// rule 3 — negative split
r = { date: "x", type: "Run", km: 8, pace: 360, hr: 150,
  detail: { zoneMin: [5, 20, 10, 2, 0], driftBpm: 3, tempC: 15, splitShape: "negative" } };
assert.match(coachRead(r, [], maxHR), /Negative split/);

// rule 6 — properly easy
r = { date: "x", type: "Run", km: 6, pace: 600, hr: 140,
  detail: { zoneMin: [10, 8, 0, 0, 0], driftBpm: 2, tempC: 15, splitShape: "even" } };
assert.match(coachRead(r, [], maxHR), /Properly easy/);

// fallback — mid HR, nothing notable
r = { date: "x", type: "Run", km: 5, pace: 360, hr: 155,
  detail: { zoneMin: [2, 8, 6, 0, 0], driftBpm: 2, tempC: 15, splitShape: "even" } };
assert.match(coachRead(r, [], maxHR), /5 km at/);

// no detail -> empty string
assert.strictEqual(coachRead({ km: 5 }, [], maxHR), "");

console.log("ALL PASS");
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node test_coach_read.mjs`
Expected: FAIL — `ERR_MODULE_NOT_FOUND` (`coach-read.js` does not exist)

- [ ] **Step 3: Write minimal implementation**

Create `coach-read.js`:

```javascript
/* coach-read.js — turns a run's stored detail + the plan into one coach sentence.
 * Pure and dependency-free so it can be unit-tested with Node and imported by
 * running-data.js. */

function fmtPace(sec) {
  if (!sec) return "—";
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function coachRead(run, weekPlan, maxHR) {
  const d = run && run.detail;
  if (!d) return "";

  const planDay = (weekPlan || []).find((w) => w.date === run.date && w.kind === "run");
  const load = planDay ? planDay.load : null;
  const type = run.type || "Run";
  const intentEasy = load === "Easy" || load === "Moderate" ||
    ["Recovery", "Long Run", "Run"].includes(type);
  const intentHard = load === "Hard" || type === "Tempo Run";

  const hrPct = maxHR ? run.hr / maxHR : 0;
  const z = d.zoneMin || [0, 0, 0, 0, 0];
  const totalMin = z.reduce((a, b) => a + b, 0) || 1;
  const drift = d.driftBpm || 0;
  const temp = d.tempC;

  if (intentEasy && hrPct >= 0.83 && temp >= 25 && drift >= 10)
    return `Easy on paper — ${temp} °C pushed HR to threshold (${run.hr} avg, +${drift} drift). Bank recovery.`;
  if (drift >= 12)
    return `Big cardiac drift (+${drift}) — heat, dehydration, or too hot a start.`;
  if (d.splitShape === "negative")
    return "Negative split — controlled, finished stronger than you started.";
  if (intentEasy && d.splitShape === "positive")
    return "Faded in the back half — ease the opening pace on easy days.";
  if (intentHard && (z[3] + z[4]) >= 0.4 * totalMin)
    return `Quality threshold work — ${z[3]} min in Z4.`;
  if (intentEasy && hrPct > 0 && hrPct <= 0.75)
    return "Properly easy — exactly the aerobic stimulus intended.";
  return `${run.km} km at ${fmtPace(run.pace)}/km, avg HR ${run.hr}.`;
}

export default coachRead;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node test_coach_read.mjs`
Expected: PASS — `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add coach-read.js test_coach_read.mjs
git commit -m "feat: add plan-aware coach-read heuristics module"
```

---

### Task 5: Attach `read` in `running-data.js`

**Files:**
- Modify: `running-data.js`

**Interfaces:**
- Consumes: `coachRead` (Task 4), merged `athleteData` (`profile.maxHR`, `weekPlan`, `recentRuns`).
- Produces: `athleteData.recentRuns[i].read` (string) for runs that have `detail`.

- [ ] **Step 1: Write the failing test**

Run (this asserts the wiring through Node, exactly as the browser loads it). First confirm current behavior — there is no `read` yet:

Run: `node --input-type=module -e "import('./running-data.js').then(m=>{const r=(m.athleteData.recentRuns||[]).find(x=>x.detail);console.log('read=',r?r.read:'no-detail-run');})"`
Expected (before change): prints `read= undefined` for a detail run, or `no-detail-run` if the sync hasn't added detail yet. Either way, no `read` field.

(There is no standalone unit test file for this 3-line wiring; `test_coach_read.mjs` already covers the logic, and Task 8's validate + render exercise the integration. The Node one-liners here are the verification.)

- [ ] **Step 2: Write minimal implementation**

Replace the contents of `running-data.js` with:

```javascript
import { garminData } from "./garmin-data.js";
import { planData } from "./plan-data.js";
import { coachRead } from "./coach-read.js";

export const athleteData = { ...garminData, ...planData };

// Attach a plan-aware coach-read to each recent run that has drill-down detail.
const _maxHR = (athleteData.profile && athleteData.profile.maxHR) || 0;
athleteData.recentRuns = (athleteData.recentRuns || []).map((r) =>
  r.detail ? { ...r, read: coachRead(r, athleteData.weekPlan, _maxHR) } : r
);

export default athleteData;
```

- [ ] **Step 3: Verify it loads and attaches `read`**

Run: `node --input-type=module -e "import('./running-data.js').then(m=>{const r=(m.athleteData.recentRuns||[]).find(x=>x.detail);console.log(r?('read: '+r.read):'no detail runs yet (run sync in Task 8)');}).catch(e=>{console.error(e);process.exit(1)})"`
Expected: either `no detail runs yet …` (if sync not yet re-run) or a real read sentence — and **no import/exception**. (A missing `coach-read.js` or syntax error would throw here.)

- [ ] **Step 4: Commit**

```bash
git add running-data.js
git commit -m "feat: attach plan-aware coach-read to recent runs at merge"
```

---

### Task 6: Dashboard state, handler, and runs view-model

**Files:**
- Modify: `Running Dashboard.dc.html` (component `<script data-dc-script>` only — the `state`, a `toggleRun` handler, a `runDetail` method, and the `runs` map in `renderVals`)

**Interfaces:**
- Consumes: `this.line(series, height) -> {d, ...}` (existing helper), `this.state`, `this.setState`, `this.mDate`, `this.fmtPace`, `D.recentRuns` with `detail`/`read`.
- Produces: `runs[i]` view-model with `id, expandable, expanded, chevron, cursor, toggle, detailRows` (0-or-1 element) plus the existing display fields. `runDetail(r) -> {read, drift, hrStart, hrEnd, spPath, hrPath, zones[], te, temp}`.

- [ ] **Step 1: Add `expandedRun` to state**

Find:

```javascript
  state = { theme: 'volt', data: null };
```

Replace with:

```javascript
  state = { theme: 'volt', data: null, expandedRun: null };
```

- [ ] **Step 2: Add the `toggleRun` handler and `runDetail` method**

Find:

```javascript
  setTheme = (name) => { this.setState({ theme: name }); };
```

Replace with:

```javascript
  setTheme = (name) => { this.setState({ theme: name }); };
  toggleRun = (id) => { this.setState({ expandedRun: this.state.expandedRun === id ? null : id }); };
  runDetail = (r) => {
    const d = r.detail;
    const hs = (d.hrSeries && d.hrSeries.length) ? d.hrSeries : [0, 0];
    const sp = (d.splits && d.splits.length) ? d.splits.map(s => s.pace) : [0, 0];
    const zsum = (d.zoneMin || []).reduce((a, b) => a + b, 0) || 1;
    return {
      read: r.read || (r.km + ' km'),
      drift: (d.driftBpm >= 0 ? '+' : '') + d.driftBpm + ' bpm',
      hrStart: hs[0], hrEnd: hs[hs.length - 1],
      hrPath: this.line(hs, 30).d,
      spPath: this.line(sp, 30).d,
      zones: (d.zoneMin || []).map((m, i) => ({ pct: Math.round(m / zsum * 100), color: 'var(--z' + (i + 1) + ')' })),
      te: d.te, temp: d.tempC
    };
  };
```

- [ ] **Step 3: Extend the `runs` map in `renderVals`**

Find:

```javascript
    const runs = D.recentRuns.map(r=>({ date:this.mDate(r.date), type:r.type, km:r.km.toFixed(1), time:r.time, pace:this.fmtPace(r.pace), hr:r.hr, cad:r.cad, dot:rdot[r.type]||'var(--accent)' }));
```

Replace with:

```javascript
    const expandedId = this.state.expandedRun;
    const runs = D.recentRuns.map((r,i)=>{
      const expandable = !!r.detail;
      const expanded = expandedId === i;
      return { id:i, date:this.mDate(r.date), type:r.type, km:r.km.toFixed(1), time:r.time,
        pace:this.fmtPace(r.pace), hr:r.hr, cad:r.cad, dot:rdot[r.type]||'var(--accent)',
        chevron: expandable ? (expanded ? '▾' : '▸') : '',
        cursor: expandable ? 'pointer' : 'default',
        toggle: expandable ? (() => this.toggleRun(i)) : (() => {}),
        detailRows: (expanded && expandable) ? [this.runDetail(r)] : [] };
    });
```

- [ ] **Step 4: Verify the dashboard still renders without error**

Start the server if needed: `pnpm dev` (background). Then load and check the console for crashes:

Run via Playwright MCP: navigate to `http://localhost:8000/Running%20Dashboard.dc.html`, then `browser_console_messages` at level `error`.
Expected: the same ~43 benign transient SVG-placeholder/favicon errors as before — **no** new `TypeError`/`ReferenceError` (e.g. no "this.runDetail is not a function" or "Cannot read properties"). The dashboard renders fully (Recent Activities still shows the 6 rows). The template still renders the old non-clickable rows (template changes come in Task 7), so visually unchanged.

- [ ] **Step 5: Commit**

```bash
git add "Running Dashboard.dc.html"
git commit -m "feat: add expandedRun state and run-detail view-model"
```

---

### Task 7: Dashboard template — clickable rows + inline detail strip

**Files:**
- Modify: `Running Dashboard.dc.html` (the Recent Activities `<sc-for list="{{ runs }}">` block in the `<x-dc>` template)

**Interfaces:**
- Consumes: the `runs[i]` view-model from Task 6 (`toggle, cursor, chevron, detailRows` + display fields); `detailRows` items have `read, drift, hrStart, hrEnd, spPath, hrPath, zones, te, temp`.

- [ ] **Step 1: Replace the run-row template**

Find the block:

```html
      <sc-for list="{{ runs }}" as="r" hint-placeholder-count="6">
        <div style="display:grid;grid-template-columns:1fr 1.3fr .8fr .9fr .9fr .7fr .7fr;gap:6px;font-size:12px;padding:10px 0;border-bottom:1px solid var(--line);align-items:center">
          <span style="color:var(--sub);font-weight:600">{{ r.date }}</span>
          <span style="display:flex;align-items:center;gap:7px;font-weight:700"><span style="width:7px;height:7px;border-radius:50%;background:{{ r.dot }}"></span>{{ r.type }}</span>
          <span style="text-align:right;font-family:'JetBrains Mono';font-weight:600">{{ r.km }}</span>
          <span style="text-align:right;font-family:'JetBrains Mono'">{{ r.time }}</span>
          <span style="text-align:right;font-family:'JetBrains Mono';color:var(--accent)">{{ r.pace }}</span>
          <span style="text-align:right;font-family:'JetBrains Mono';color:var(--sub)">{{ r.hr }}</span>
          <span style="text-align:right;font-family:'JetBrains Mono';color:var(--sub)">{{ r.cad }}</span>
        </div>
      </sc-for>
```

Replace with:

```html
      <sc-for list="{{ runs }}" as="r" hint-placeholder-count="6">
        <div>
          <div onClick="{{ r.toggle }}" style="display:grid;grid-template-columns:1fr 1.3fr .8fr .9fr .9fr .7fr .7fr;gap:6px;font-size:12px;padding:10px 0;border-bottom:1px solid var(--line);align-items:center;cursor:{{ r.cursor }}">
            <span style="color:var(--sub);font-weight:600">{{ r.date }}</span>
            <span style="display:flex;align-items:center;gap:7px;font-weight:700"><span style="width:7px;height:7px;border-radius:50%;background:{{ r.dot }}"></span>{{ r.type }}<span style="margin-left:auto;color:var(--sub);font-size:11px">{{ r.chevron }}</span></span>
            <span style="text-align:right;font-family:'JetBrains Mono';font-weight:600">{{ r.km }}</span>
            <span style="text-align:right;font-family:'JetBrains Mono'">{{ r.time }}</span>
            <span style="text-align:right;font-family:'JetBrains Mono';color:var(--accent)">{{ r.pace }}</span>
            <span style="text-align:right;font-family:'JetBrains Mono';color:var(--sub)">{{ r.hr }}</span>
            <span style="text-align:right;font-family:'JetBrains Mono';color:var(--sub)">{{ r.cad }}</span>
          </div>
          <sc-for list="{{ r.detailRows }}" as="dv" hint-placeholder-count="0">
            <div style="padding:11px 2px 15px;border-bottom:1px solid var(--line)">
              <div style="font-size:11.5px;font-weight:600;color:var(--accent);margin-bottom:10px;line-height:1.4">⚡ {{ dv.read }}</div>
              <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;align-items:end">
                <div>
                  <div style="font-size:9.5px;color:var(--sub);font-weight:700;margin-bottom:4px">SPLITS /km</div>
                  <svg viewBox="0 0 600 30" style="width:100%;height:26px;display:block"><path d="{{ dv.spPath }}" fill="none" style="stroke:var(--accent);vector-effect:non-scaling-stroke" stroke-width="2" stroke-linejoin="round"></path></svg>
                </div>
                <div>
                  <div style="font-size:9.5px;color:var(--sub);font-weight:700;margin-bottom:4px">HR {{ dv.hrStart }} → {{ dv.hrEnd }} ({{ dv.drift }})</div>
                  <svg viewBox="0 0 600 30" style="width:100%;height:26px;display:block"><path d="{{ dv.hrPath }}" fill="none" style="stroke:var(--accent2);vector-effect:non-scaling-stroke" stroke-width="2" stroke-linejoin="round"></path></svg>
                </div>
                <div>
                  <div style="font-size:9.5px;color:var(--sub);font-weight:700;margin-bottom:4px">ZONES · TE {{ dv.te }} · {{ dv.temp }} °C</div>
                  <div style="display:flex;height:14px;border-radius:4px;overflow:hidden;gap:1px">
                    <sc-for list="{{ dv.zones }}" as="z" hint-placeholder-count="5"><div style="width:{{ z.pct }}%;background:{{ z.color }}"></div></sc-for>
                  </div>
                </div>
              </div>
            </div>
          </sc-for>
        </div>
      </sc-for>
```

- [ ] **Step 2: Verify click-to-expand works (render test)**

Ensure `pnpm dev` is running and `garmin-data.js` currently has no `detail` yet (Task 8 adds it). To verify the interaction *now*, temporarily confirm with the demo guard instead: load the page, click the first run row.

Run via Playwright MCP: navigate to the dashboard; `browser_click` on the first Recent Activities row (the row showing the most recent run); `browser_take_screenshot`.
Expected (before Task 8 sync — rows not yet expandable because no `detail`): clicking does nothing, no chevrons, **no console error**, dashboard intact. (Full expand is verified after Task 8 regenerates `detail`.)

- [ ] **Step 3: Commit**

```bash
git add "Running Dashboard.dc.html"
git commit -m "feat: clickable run rows with inline drill-down detail strip"
```

---

### Task 8: Regenerate data, full validation, README, end-to-end render

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Regenerate `garmin-data.js` with detail (real sync)**

Run: `& ".\.venv\Scripts\python.exe" sync_garmin.py`
Expected: `✓ logged in`, `✓ telemetry validation passed`, `✓ wrote garmin-data.js`. `recentRuns[i].detail` now populated (per-activity detail cached under `.garmin_cache/detail-*.json`).

- [ ] **Step 2: Validate the merged contract (now exercises the detail assertions)**

Run: `& ".\.venv\Scripts\python.exe" validate_data.py`
Expected: PASS — `✓ all invariants hold`. The Task 3 assertions now run against real `detail` and must hold.

- [ ] **Step 3: Confirm reads are attached**

Run: `node --input-type=module -e "import('./running-data.js').then(m=>{m.athleteData.recentRuns.slice(0,3).forEach(r=>console.log(r.date, '|', r.read||'(none)'));})"`
Expected: each recent run prints a coach-read sentence (the most recent long run should mention the heat/threshold read).

- [ ] **Step 4: End-to-end render verification**

Ensure `pnpm dev` is running. Via Playwright MCP: navigate to the dashboard; `browser_click` the most recent run row; `browser_take_screenshot`; then `browser_click` it again; `browser_take_screenshot`.
Expected: first click expands the row into the detail strip (⚡ coach-read in accent, SPLITS sparkline, HR drift sparkline with `start → end (+N bpm)`, zone bars, TE · °C); second click collapses it; chevron toggles `▸`/`▾`; no console errors beyond the benign baseline.

- [ ] **Step 5: Update the README**

In `README.md`, in the "What's in this project" area or the dashboard description, add one line:

```markdown
- **Run drill-down:** click any run in *Recent Activities* to expand its per-km splits, HR-drift sparkline, zone breakdown, and a plan-aware one-line coach-read (computed in `coach-read.js`).
```

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs: document run drill-down in README"
```

---

## Self-Review

**Spec coverage:**
- Data layer / `fetch_run_detail` + caching → Tasks 1–2. ✓
- Coach-read engine (7 ordered rules, plan-aware) → Task 4 (`coach-read.js`) + Task 5 (attach at merge). ✓ (Refinement vs. spec: read lives in `coach-read.js`/`running-data.js` rather than a component method — same inputs, same plan-awareness, now unit-testable. Noted in Architecture.)
- Inline-expand UI (`expandedRun` state, sparklines, zone bars, read) → Tasks 6–7. ✓
- Scope (6 runs, runs-only) → inherited from existing `recentRuns`; no table change. ✓
- Edge cases (no detail / demo / no HR) → guarded by `!!r.detail` (Task 6) and `coachRead` returning `""` (Task 4); demo runs have no `detail` so rows aren't expandable. ✓
- Testing (validate detail shape, offline transform test, Playwright) → Task 3, Tasks 1–2, Tasks 7–8. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every run step has an exact command + expected output.

**Type consistency:** `fetch_run_detail` keys (`splits, hrSeries, driftBpm, zoneMin, tempC, te, load, elevGain, splitShape`) match the `detail` shape consumed by `coachRead` (Task 4), `runDetail` (Task 6), the template (Task 7), and `validate_data.py` (Task 3). `coachRead(run, weekPlan, maxHR)` signature is identical in Task 4 (definition), Task 5 (call), and the tests. `fetch_recent_runs(client, acts, n)` new signature is updated at its one call site in `build_data` (Task 2).
