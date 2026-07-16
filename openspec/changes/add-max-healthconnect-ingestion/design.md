## Context

SPLITS is single-athlete by design: one container, one data volume holding
`garmin-data.js` (telemetry, sync-owned), `plan-data.js` (coach-owned), and the
archive DB. Every page does `import('./running-data.js') → athleteData`, and the
data import is a **relative path**, so the same image serving a different volume
is already a complete, isolated instance — no multi-tenant code required.

Max has a Galaxy Watch + Pixel (Samsung Health), no Garmin. Empirical recon this
session (adb against a Galaxy S24, Samsung Health `7.00.0.107`, Android 16)
confirmed at the OS permission level that Samsung Health declares
`WRITE_EXERCISE / WRITE_HEART_RATE / WRITE_DISTANCE / WRITE_SPEED` to Health
Connect — but **not** `WRITE_EXERCISE_ROUTE` (no workout GPS) and not cadence.
Garmin Connect writes the same set, so Felix's own Health Connect is already
populated with real runs we can build against immediately.

The telemetry contract the dashboard reads (`athleteData`, per
`CLAUDE_CODE_HANDOFF.md §3`) splits cleanly into fields **derivable from a run**
(recentRuns, weekly volume, CTL/ATL, monthly pace, heatmap, predictions, HR
zones) and fields that are **Garmin-wearable-native** (VO₂max, readiness, sleep,
HRV) or need data Health Connect withholds (route). The scope boundary
("Slim + HR zones") lands exactly on the derivable seam.

## Goals / Non-Goals

**Goals:**
- Max sees his coach-authored plan scored against his real runs, plus basic
  pace/volume/load trends and weekly HR zones, on his own SPLITS instance.
- Ingestion we own end to end — no third-party cloud that can paywall or revoke.
- Set-and-forget for Max after a one-time permission grant.
- **One image, config-only differences** between the two instances. No
  Max-specific code branch in the app; all divergence via env + volume +
  graceful degradation.
- Complete isolation of Max's data from Felix's.

**Non-Goals:**
- VO₂max, readiness/Body Battery, sleep/HRV/resting-HR (wellness; unavailable
  and unwanted).
- Route basemap and per-run stream drill-downs (Health Connect carries no
  workout GPS; HR/pace *series* are out of scope beyond what HR-zone binning
  needs).
- A combined "both brothers" view or any multi-tenant refactor.
- Changing the `athleteData` contract, the plan format, or Felix's instance.

## Decisions

### D1 — Self-built Health Connect reader, not a cloud relay
Read runs from Health Connect on Max's device and push them to his instance.
*Rationale:* every cloud path was tested and rejected — Strava API is
subscription-gated (confirmed live), Garmin refuses inbound writes, Samsung has
no server API. Health Connect is the only source we can reach without a
gatekeeper, and building the reader ourselves means no external dependency to
rot. *Alternatives:* Strava→API (paywalled), Garmin-account relay (write-blocked),
manual entry (kept as the pre-automation fallback, not the target).

### D2 — Two instances, not multi-tenant
Max runs the same image with his own volume, plan, and config; Felix's instance
is untouched. *Rationale:* strongest possible separation (OS-level) for ~zero
code; the app was built single-user and a multi-tenant refactor would re-plumb
the whole system for an audience of one beginner. *Alternative:* athlete-
partitioned single app (`/felix`, `/max`) — rejected: touches routing, every
page's relative import, the archive SQL, and the sync; high blast radius, no
benefit here (combined view is a non-goal).

### D3 — Builder derives the contract from banked runs (reuse existing formulas)
The server banks each pushed run, then a **builder** (Python, alongside
`sync_garmin.py`) rebuilds Max's `garmin-data.js` from the banked set — mirroring
how the Garmin sync banks activities then builds. It reuses the CTL/ATL EWMA and
Riegel logic already in `insight_metrics` / `sync_garmin` (`§4`). *Rationale:*
the derived fields are exactly the formulas we already own; the builder is a
thin re-aggregation, not a reimplementation. *Alternative:* compute everything
in the Node ingest handler — rejected: would duplicate the Python metric code in
JS and drift from Felix's pipeline.

### D4 — Bank runs in a dedicated store, decoupled from the Garmin archive
Store pushed runs in a small purpose-built table (start time, duration,
distance, avg HR, HR samples, sport type, HC session UID). *Rationale:* the
`activity-archive` schema is Garmin-shaped (summary/detail/streams/maps JSON,
Garmin activity IDs) and its value is the stream/route drill-downs Max doesn't
have; forcing his simpler runs into it buys nothing. *Alternative:* reuse
`activity-archive` to light up `/archive` for free — rejected: those pages need
streams/maps Max lacks, so they'd be empty anyway.

### D5 — Push a normalized run payload; bin HR zones server-side
The app pushes per run: `startTimeLocal`, `durationS`, `distanceM`, `avgHr`,
`sportType`, a downsampled `hrSamples[]` (≈1 sample / 5 s), and the Health
Connect **session UID** as an idempotency key. The server builder bins HR
minutes-in-zone using `profile.maxHR` bounds. *Rationale:* zone bounds are a
coaching policy that belongs server-side (single source of truth; re-binnable if
maxHR changes) — consistent with "the server owns derived policy." Dedup by
session UID makes re-pushes safe. *Alternative:* bin on device (less payload) —
rejected: bakes zone policy into the app and can't re-derive.

### D6 — `/api/ingest` mirrors the existing plan-push auth, gated by a token
Add `POST /api/ingest` guarded by `SPLITS_INGEST_TOKEN` (Bearer), size-capped,
with an atomic write to the run store — the exact pattern as `PUT /api/plan`.
When the token is unset the route 404s like any unknown path, so Felix's
instance never exposes it. *Rationale:* reuse a proven, reviewed auth path;
opt-in by construction. Builder runs single-flight after a successful ingest
(plus a boot rebuild), since ingests are infrequent (a few runs/week).

### D7 — Resolve the VO₂ invariant by *omitting* VO₂ entirely
The invariant `profile.vo2maxCurrent === history.vo2max[last]` only binds when
VO₂ is present. Max's builder emits **neither** `profile.vo2maxCurrent` nor
`history.vo2max` (omit the keys, not empty arrays), keeping the invariant
vacuously satisfied. *Requirement this creates:* verify the VO₂ hero panel and
progress views render an empty/hidden state when the keys are absent, and add a
guard if they don't. Same treatment for `readiness`, `history.sleep`.

### D8 — `/run/:id`, `/archive`, `/compare` degrade to empty states (no code branch)
Max's instance doesn't populate the Garmin archive DB, so those routes render
their empty/degraded state — which the app already does when archive tables are
missing (the archive API 404s / omits). We do **not** add per-instance routing
to hide them. *Rationale:* preserves the one-image principle (D-goal); the run
*cards* on the main dashboard (from `recentRuns`) are Max's run view, and a run
card without `detail` simply isn't a drill-down link. *Requirement this creates:*
confirm `run.dc.html` and the archive pages tolerate the empty state rather than
erroring.

## Risks / Trade-offs

- **Samsung `7.00.0.107` may not actually emit `ExerciseSession` to Health
  Connect** (a regression was reported for this exact build). → *Mitigation:*
  Phase 0 on-device spike verifies real extraction **before** building anything
  else; if broken, fall back to manual entry until Samsung fixes it. This is the
  single biggest unknown.
- **No GPS route, no cadence** from Samsung. → Accepted per scope; dashboard
  degrades (D8); `recentRuns.cad` is `null`.
- **Phone → home-server reachability.** Max's Pixel must reach the NUC over the
  internet. → *Mitigation:* Tailscale (or an existing TLS reverse proxy); treat
  as a deployment prerequisite, not app logic. Token auth assumes a private/TLS
  transport.
- **Google Health Connect Developer Declaration** is required even for a
  sideloaded app reading health data types. → *Mitigation:* start the
  declaration early (parallel to the build); risk is schedule, not feasibility.
- **HR-sample volume / battery.** → *Mitigation:* downsample to ~1/5 s; runs are
  short; background job runs on a relaxed cadence (WorkManager, not real-time).
- **One-image discipline.** Every Max-specific behavior must be config +
  graceful degradation, never a code branch. → *Mitigation:* enforce in review;
  the ingest route and builder ship in the image and activate on env/data.

## Migration Plan

- **Phase 0 — extraction spike (verify first).** Minimal Kotlin reader → `adb
  install` on the Galaxy S24 → grant permissions → dump recent `ExerciseSession`
  + HR samples as JSON. Confirms the read path and payload shape on real,
  Garmin-populated Health Connect; ideally repeat on Max's Pixel to test the
  Samsung `7.00.0.107` write path specifically.
- **Phase 1 — server side.** `POST /api/ingest` + run store + builder + a second
  compose service/volume; seed Max's `plan-data.js` (beginner→half). Drive it
  with the spike app or curl-simulated payloads; verify the dashboard renders
  the Slim + HR-zones set and degrades cleanly on the non-goals (D7, D8).
- **Phase 2 — finish the app.** Background scheduling, permission + history
  backfill, config (server URL + token), Developer Declaration; sideload to
  Max's Pixel.
- **Rollback.** Max's instance is fully isolated — tear down its container +
  volume; Felix is unaffected. The app is sideloaded — uninstall.

## Open Questions

- **Network path** phone → NUC: Tailscale vs the existing reverse proxy? (Deploy
  decision; doesn't block Phase 0/1.)
- **Does Samsung `7.00.0.107` actually write `ExerciseSession` to Health
  Connect?** Phase 0 answers this decisively.
- **Backfill window:** how far back does Max's first sync reach
  (`READ_HEALTH_DATA_HISTORY` covers >30 days)? Likely "since he started running,"
  set as a config date.

## Addendum — data-types research & scope expansion (2026-07-15, empirically verified)

A Health Connect data-types sweep (the alpha10plus data-types doc + the workouts
doc + what Samsung/Garmin actually write + a completeness critic) plus an
**extended on-device spike on Felix's Galaxy S24** (14 real Garmin runs) expanded
the scope. Everything below was confirmed against real data.

### Adopted additions (were null slots / non-goals → now in scope)
- **D9 — HR-zone calibration from observed max HR.** The reader already reads the
  HR series; harvest per-run **max** (verified 14/14, 138–186 bpm) → real zone
  bounds *and* CTL/ATL intensity, replacing the `220−age` fallback (used only when
  max is absent). Highest-ROI fix; the flagship HR-zone feature was mis-calibrated.
- **D10 — Moving pace.** Derive moving time by thresholding the `SpeedRecord`
  series (verified 14/14) to strip standing/walk pauses; use it for `recentRuns`
  pace, monthly pace, and the **Riegel anchor**. Elapsed-time pace biases a
  walk-break beginner slow.
- **D11 — Per-km splits** derived from the cumulative distance / speed series
  (verified) — the app's namesake — independent of `ExerciseLap` (which Samsung
  likely doesn't write).
- **D12 — RestingHR → Karvonen zones + fitness trend.** *Relaxes the wellness
  non-goal.* RHR verified present (59 daily records, 47–58 bpm). Enables HR-reserve
  zones (the correct model for a beginner) + a falling-RHR trend line.
- **D13 — Elevation + calories** per run (elevation verified 40–121 m; active/
  total calories verified) → the existing `elevation_gain_m` column + an energy
  tile. Degrade to null when absent.

### D14 — dataOrigin filtering is MANDATORY (empirically proven)
Felix's Health Connect has Garmin + Samsung Health + Google Fit + Fitbit all
writing. **Unfiltered** metric reads double-counted: steps → **302 spm**
(impossible), total calories → 8 overlapping records. Filtering every metric read
by the session's `dataOrigin` fixed both (cadence → 149–159 spm; calories → one
Garmin record). The reader MUST filter by the session's origin; the ingest builder
should also treat delta metrics as single-origin.

### Provider reality (binding for Max)
- **Samsung** writes: session, HR, distance, speed, TotalCalories, Power, VO2max,
  RestingHR; **NOT** cadence, **NOT** elevation, **NOT** route. Steps sync
  unverified.
- **Garmin** (verified on-device): session, HR, distance, speed, elevation,
  active/total calories, steps; not running cadence/power/VO2max.
- Therefore **for Max**: cadence & elevation are unavailable (leave null); calories,
  RHR, and all the calibration/pace/splits derivations work. Cadence stays null for
  Max (Samsung) but is derivable-from-steps for a Garmin source.

### Time-sensitive risk (carries into the gate, task 1.4)
**Samsung Health 7.00.0.107 (Max's likely build) broke exercise-session writes to
Health Connect ~July 1 2026** (fix 7.00.5.009: sideload-only, not broadly rolled
out, no backfill). A `GATE: NO` may be this regression, not a config error —
verify Max's build actually lands runs in HC before trusting the feed.
