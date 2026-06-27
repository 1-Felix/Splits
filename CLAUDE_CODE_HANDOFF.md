# SPLITS — Backend Handoff for Claude Code

This document is the brief for building the data backend behind the **SPLITS**
running dashboard. Hand it to Claude Code at the start of your planning session.

The frontend already exists and is **done**. It is a single self-contained file
(`Running Dashboard.dc.html`) that renders entirely in the browser. It has exactly
one external dependency: a file called **`running-data.js`**. Your job on the
backend is to **produce and keep that file up to date** from real data.

> **The golden rule:** the dashboard never talks to Garmin, a database, or an API.
> It imports `running-data.js`. If the backend writes a correct `running-data.js`,
> the dashboard works. That's the entire contract.

---

## 1. Architecture at a glance

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐     ┌────────────────┐
│  Garmin     │     │  sync_garmin.py  │     │ transform layer │     │ running-data.js│
│  Connect    │───▶ │  (pull raw data) │───▶ │ raw → schema    │───▶ │ (the contract) │
│  + Health   │     │                  │     │                 │     │                │
│  Connect    │     └──────────────────┘     └─────────────────┘     └───────┬────────┘
└─────────────┘                                                              │
                                                                             ▼
                                              ┌───────────────────────────────────────┐
                                              │  Running Dashboard.dc.html (frontend)   │
                                              │  imports running-data.js, renders.      │
                                              └───────────────────────────────────────┘
                                                                             ▲
                                              ┌──────────────────────────────┴──────────┐
                                              │  AI coach (you, in Claude Code) edits the │
                                              │  EDITABLE fields of running-data.js only. │
                                              └───────────────────────────────────────────┘
```

Two writers touch `running-data.js`:

1. **The sync script** — owns everything marked `FROM GARMIN` (telemetry/history).
2. **The AI coach** — owns everything marked `EDITABLE` (the plan, goals, notes).

These two must not clobber each other. See §5 "Open decisions".

---

## 2. Data sources & how each metric maps

| Dashboard metric            | Primary source (Garmin Connect)        | Fallback                          |
|-----------------------------|----------------------------------------|-----------------------------------|
| VO₂ max trend               | `get_max_metrics` / user summary       | Garmin FIT files                  |
| Avg run pace (monthly)      | Activities list → aggregate by month   | Strava export                     |
| Cadence                     | Activity detail → `averageRunningCadenceInStepsPerMinute` | —              |
| Weekly volume (km)          | Activities list → sum distance by week | Health Connect `ExerciseSession`  |
| Fitness/Fatigue (CTL/ATL)   | **Computed** — not given by Garmin     | see §4 (TSS → CTL/ATL formula)    |
| HR zones (minutes this week)| Activity detail → `hrTimeInZone_1..5`  | compute from HR stream + bounds   |
| Resting HR / HRV            | `get_rhr_day`, `get_hrv_data`          | Apple Health / Health Connect     |
| Sleep (hours, HRV, deep %)  | `get_sleep_data`                       | Health Connect `SleepSession`     |
| Readiness score             | Garmin "Body Battery" / Training Readiness | **Computed** (see §4)         |
| Activity heatmap (365 days) | Activities list → daily distance       | —                                 |
| Race predictions            | Garmin race predictor                  | **Computed** (Riegel formula)     |

Recommended library: [`garminconnect`](https://github.com/cyberjunky/python-garminconnect)
(unofficial). Health Connect (Android) and Apple HealthKit are good secondary
sources for sleep/HRV if Garmin gaps appear.

---

## 3. The data contract (the `running-data.js` schema)

The script must emit a JS module that does `export const athleteData = { … }`.
Below is every field the dashboard reads, with **units** and **owner**.
(`Running Dashboard.dc.html` contains a built-in copy of this exact shape as a
fallback, so you can diff against it.)

```js
export const athleteData = {
  // ── profile ─────────────────────────────────  owner: FROM GARMIN
  profile: {
    name: "Alex",            // string, first name used for the avatar initial
    age: 31,                 // int, years — used for max-HR sanity checks
    restingHR: 47,           // int, bpm
    maxHR: 188,              // int, bpm — defines HR-zone bounds if you compute them
    weightKg: 71,            // float
    vo2maxCurrent: 51.3,     // float, ml/kg/min — should equal history.vo2max[last]
  },

  // ── race goal ───────────────────────────────  owner: EDITABLE (coach)
  race: {
    name: "Half Marathon",
    location: "Lakeside Half",
    date: "2026-08-09",          // ISO date — drives the countdown
    distanceKm: 21.1,            // float
    goalTime: "1:59:59",         // "H:MM:SS"
    goalPaceSecPerKm: 341,       // int seconds/km — must match goalTime ÷ distance
    pb: "2:17:30",               // "H:MM:SS" personal best
    pbDate: "2025-04-13",        // ISO date
  },

  today: "2026-06-27",           // ISO date — set to the sync run date. owner: SYNC

  // ── today's readiness ───────────────────────  owner: FROM GARMIN
  readiness: {
    score: 82,                   // int 0-100
    status: "Primed",            // short string label
    hrv: 68,                     // int ms (rMSSD or Garmin's value)
    restingHR: 46,               // int bpm (today)
    sleepHours: 7.8,             // float, last night
    trainingLoad: 412,           // int — acute 7-day load
    loadStatus: "Optimal",       // short label
  },

  // ── this week's plan ────────────────────────  owner: EDITABLE (coach)
  // 7 entries, Mon→Sun. status ∈ "done" | "today" | "upcoming"
  // kind   ∈ "run" | "strength" | "cross"  (drives the icon + color)
  // load   ∈ "Easy" | "Moderate" | "Hard"
  weekPlan: [
    { day:"Mon", date:"2026-06-22", kind:"cross",    title:"Spin / Bike",
      detail:"45 min Z2 indoor cycling", load:"Easy", status:"done", km:0 },
    // …Tue…Sun
  ],

  // ── HR zones this week ──────────────────────  owner: FROM GARMIN
  // min = minutes accumulated in that zone across the week.
  // lo/hi = bpm bounds for that zone (optional but nice to show).
  hrZones: [
    { z:1, label:"Recovery",  min:95,  lo:94,  hi:113 },
    { z:2, label:"Endurance", min:182, lo:113, hi:132 },
    { z:3, label:"Tempo",     min:64,  lo:132, hi:151 },
    { z:4, label:"Threshold", min:28,  lo:151, hi:169 },
    { z:5, label:"VO2 max",   min:9,   lo:169, hi:188 },
  ],

  // ── race predictions ────────────────────────  owner: FROM GARMIN or computed
  predictions: {
    fiveK:    "24:40",
    tenK:     "51:20",
    halfNow:  "2:03:40",   // current model prediction for the half
    halfGoal: "1:59:59",
    trend:    "-1:55 / 4wks",  // human-readable improvement string
  },

  // ── recent activities (most-recent first) ───  owner: FROM GARMIN
  // pace = int seconds/km. hr/cad = int. km = float. time = "MM:SS" or "H:MM:SS".
  recentRuns: [
    { date:"2026-06-26", type:"Tempo Run", km:9.1, time:"50:12",
      pace:331, hr:162, cad:178, vo2:51.3 },
    // …
  ],

  // ── the AI coach ────────────────────────────  owner: EDITABLE (coach)
  coach: {
    headline: "6 weeks out — sharpen, don't pile on.",
    note: "…paragraph of current focus…",
    focus: ["Threshold pace → 5:30/km", "Long run fueling rehearsal", "…"],
    log: [   // adjustment feed, most-recent first
      { date:"2026-06-26", text:"Bumped Friday tempo 4→5 km @ 5:35 — HRV recovered." },
    ],
  },

  // ── history (long time-series) ──────────────  owner: FROM GARMIN
  // Plain arrays, OLDEST → NEWEST. Lengths shown are what the demo uses;
  // the charts adapt to any length, but keep them self-consistent.
  history: {
    vo2maxStartMonth: "2024-01", // ISO month of vo2max[0] (for axis labels)
    vo2max:        [/* 30 floats, monthly */],
    paceSecPerKm:  [/* 30 ints, monthly avg run pace, sec/km */],
    cadenceSpm:    [/* 30 ints, monthly avg cadence */],
    weeklyKm:      [/* 26 floats, weekly volume */],
    weeklyRuns:    [/* 26 ints, runs per week */],
    ctl:           [/* 26 floats, fitness (chronic load) */],
    atl:           [/* 26 floats, fatigue (acute load) */],
    sleep:         [/* 14 objects: { hours:float, hrv:int, deepPct:int } */],
  },

  // ── activity heatmap ────────────────────────  owner: FROM GARMIN
  // EXACTLY the last 365 days, oldest → newest. heatmapKm[364] = today.
  // 0 = rest day. Units = km that day.
  heatmapKm: [/* 365 floats */],
};

export default athleteData;
```

### Hard invariants (validate these before writing the file)
- `heatmapKm.length === 365`, last element is **today**.
- `profile.vo2maxCurrent === history.vo2max[history.vo2max.length - 1]`.
- `race.goalPaceSecPerKm` ≈ `goalTime` seconds ÷ `distanceKm`.
- `weekPlan` has 7 entries Mon→Sun; exactly one `status:"today"` (the current day).
- All `history.*` arrays are oldest → newest. Never reverse them silently.
- Pace fields are **seconds per km as integers** (e.g. 5:41/km → `341`). The
  frontend formats them; do not pre-format pace as a string.

---

## 4. Things Garmin does NOT give you (compute these)

- **CTL / ATL (fitness & fatigue):** derive a daily Training Stress Score
  (TSS ≈ `duration_hr × IF² × 100`, where Intensity Factor `IF = avgHR_frac` or
  pace-based), then exponentially weight it:
  `CTL_today = CTL_yesterday + (TSS_today − CTL_yesterday)/42`,
  `ATL_today = ATL_yesterday + (TSS_today − ATL_yesterday)/7`.
  Form/TSB = `CTL − ATL`. Roll up to weekly points for the chart.
- **Readiness score** (if not using Garmin Training Readiness): blend normalized
  HRV (↑good), resting HR (↓good), sleep hours, and yesterday's load into 0-100.
- **Race prediction** (fallback): Riegel — `T2 = T1 × (D2/D1)^1.06` from a recent
  race or hard effort.

---

## 5. Open decisions to settle in your planning session

1. **Auth & secrets** — Garmin login is email/password (no official OAuth via the
   unofficial lib). Where do credentials live? (`.env` + `keyring`? a token cache
   the lib supports?) Plan for MFA prompts.
2. **Sync cadence** — cron/launchd nightly, or a manual `python sync_garmin.py`
   you run before opening the dashboard? Incremental (since last sync) vs full.
3. **Historical backfill** — first run pulls 2–3 years; later runs pull only new
   activities. Cache raw responses so you're not re-hitting Garmin.
4. **The two-writer problem** — the sync owns `FROM GARMIN` fields, the coach owns
   `EDITABLE` fields. Cleanest fix: **split the file**. Have the sync write
   `garmin-data.js` (telemetry only) and keep a hand/coach-edited `plan-data.js`;
   a tiny `running-data.js` merges them: `export const athleteData = { ...garmin, ...plan }`.
   Then the sync can overwrite freely and never touches your plan. *(The dashboard
   only cares that the final `running-data.js` exports `athleteData`.)*
5. **Validation/CI** — a `validate_data.py` that asserts every invariant in §3
   before the file is committed, so a bad sync can't break the dashboard.
6. **Where the dashboard is hosted** — local file open, a static server, or
   bundled. The data file must sit next to the HTML either way.

---

## 6. First task for Claude Code

> Read `running-data.js` and `sync_garmin.py` in this project. Flesh out
> `sync_garmin.py` so it logs into Garmin Connect, pulls the metrics in §2, maps
> them to the schema in §3, validates the §3 invariants, and writes a valid
> `running-data.js`. Start with `recentRuns`, `weeklyKm`, and `heatmapKm` (all
> straight from the activities list), then add the computed series (§4) last.

`sync_garmin.py` already contains the function skeleton and a `build_running_data_js()`
writer that emits the correct shape — so this is "fill in the pulls", not "design
from scratch".
