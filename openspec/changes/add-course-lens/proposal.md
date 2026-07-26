# Proposal: add-course-lens

## Why

The block lens answers "what is this block doing to me?". Nothing answers **"what
is the race actually going to ask of me?"** — the one question that matters most
in the fortnight before Aug 9.

The gap is not cosmetic. On 2026-07-26 the race plan was written from a course
*summary* (143 m up / 143 m down plus a prose description) and was wrong in the
two ways that decide a race: it placed the climb at km 15–17 when the real climb
is km 12→13, and it priced that climb at 20–40 s when a kilometre at 8.25 %
costs 90–120 s. The correction only became possible because the athlete imported
the official route into Garmin Connect, where course `493447940` carries 1 196
geo points, every one with distance and elevation.

That course is reachable through the credentials the sync already holds
(`connectapi("/course-service/course/{id}")`) — sync-time acquisition, nothing
fetched by the browser, exactly the policy `route-basemap` established for
tiles. Once stored, the same data answers all three questions the athlete asked
for: *show me the hill*, *tell me what each kilometre should cost*, and — after
the race — *where did I actually lose the time?*

The archive already holds the ingredient that makes the pace model honest rather
than textbook: every run stores `v` (actual speed), `gap`
(`directGradeAdjustedSpeed`) and `elev` per sample, which is a large empirical
record of how **this athlete** slows down on a grade.

## What Changes

- **Course acquisition** in the deterministic sync: fetch the course named by
  `race.courseId` (one HTTP call per sync — the course service has no cheaper
  metadata probe), then skip the derivation and the database write when the
  returned `updateDate` matches what is stored. No-op offline.
- **Course lens derivation** — a new engine step computing, per course:
  - *Profile* — smoothed elevation over distance, per-kilometre grade, and the
    decisive segments (sustained climbs and descents) detected rather than
    hand-listed.
  - *Grade-cost calibration* — an analytic energy-cost curve as backbone, scaled
    by a **single** damping factor fitted from the athlete's own `v`/`gap`/`elev`
    samples, with the fit residual reported so the model states its own accuracy.
  - *Pace model* — the calibrated cost parameters and the course's elevation
    cost versus flat, stored so that a per-kilometre table (target pace,
    cumulative elapsed) is computable for **any** target finish without a sync
    or schema change. Three named targets ship as presets over that model: the
    goal, Garmin's prediction, and the honest Riegel projection.
  - *Race comparison* (once a matching activity exists) — actual pace and HR
    resampled onto the course distance grid, per-kilometre deltas against
    target, and time lost/gained attributed to climb, descent and flat.
- **Data contract**: an additive `courseLens` object in `garmin-data.js` (the
  upcoming race's course in full), fail-soft absent when the race carries no
  `courseId`.
- **`/course` page**: elevation profile over distance with the decisive segments
  annotated and crosshair readout, the route on the existing basemap, the
  per-kilometre pace table with a target switcher, and — after race day — the
  actual-versus-target overlay.
- **Read-only archive endpoint** `GET /api/archive/course/:courseId` serving the
  stored document for deep views, keeping `garmin-data.js` bounded.

## Capabilities

### New Capabilities

- `course-lens`: course acquisition from Garmin's course service, the derived
  profile/pace-plan/comparison document, the additive `courseLens` data-contract
  object, and the `/course` surface (profile, map, pace table, post-race
  overlay).

### Modified Capabilities

- `archive-api`: gains a read-only course endpoint — SELECT-and-shape only, no
  derivation at request time, fail-soft 503.
- `plan-sync`: `planData.race` gains an optional `courseId`; validation accepts
  it and rejects a malformed value, so a coach edit can never write a plan the
  lens will choke on.

## Impact

- **Python sync**: new `course_lens.py` (acquisition + derivation) invoked from
  `sync_garmin.py`; fail-soft — the sync never breaks on a course error.
- **Schema**: v10, additive — `courses` plus `course_maps`; `map_tiles` reused
  unchanged.
- **Data contract**: additive `courseLens` in `garmin-data.js`; absent without a
  `courseId`.
- **Server**: one new read-only route in `serve.mjs` beside the archive
  endpoints; `/course` added to the page table.
- **Dashboard**: new `course.dc.html`; chart engine and basemap helpers reused,
  not extended.
- **Tests**: `test_course_lens.py` over a captured fixture of the real course,
  `test_archive_api.mjs` extension, `test_course_page.mjs` render test,
  `test_plan_validate.mjs` extension for the new race field.

## Non-Goals

- **No multi-race course registry.** One optional `courseId` per race is the
  whole mechanism; a second race works by carrying its own id, and no course
  management UI is built.
- **No coach-briefing integration.** The lens could feed `coach-briefing.md`,
  but that is a separate change against `coach-loop` and is deliberately out of
  scope here.
- **No modelled HR targets.** Heart rate on an 8 % climb legitimately spikes;
  per-kilometre HR guidance stays coach-authored prose in `plan-data.js`.
- **No course editing, import, or GPX parsing.** Garmin Connect is the single
  source; the athlete imports there.
