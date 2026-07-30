# Design: add-course-lens

## Context

The race is 2026-08-09. The course exists in Garmin Connect as course
`493447940` — `Allgäu Panorama Marathon - Halbmarathon`, 1 196 geo points,
0 → 21 114.2 m, every point carrying `latitude`, `longitude`, `elevation` and
cumulative `distance`. Probed 2026-07-26 through the sync's own cached tokens.

Its shape, per-kilometre (raw, unsmoothed):

| km | elev | Δ | grade |
|---|---|---|---|
| 0–12 | 741.6 → 786.1 | +44.5 total | ≈ +0.37 % — effectively flat |
| 12→13 | 786.1 → 868.6 | **+82.5** | **+8.25 %** |
| 13→14 | → 827.2 | −41.4 | −4.14 % |
| 14→15 | → 766.7 | −60.4 | −6.04 % |
| 15–21 | → 739.2 | −27.5 total | ≈ −0.46 % |

Garmin totals 197.4 m gain / 200.0 m loss; outdooractive reports 143/143 for the
same route. Different elevation models — the **shape** is authoritative, the
magnitude is a range.

Two facts shape everything below. First, the decisive 3 km sit in the middle,
not at the end, so a pacing model that only reports totals is useless. Second,
the athlete is two and a half weeks out of an MTSS episode with a longest run of
10 km, which makes the −6 % kilometre a health question and not merely a pacing
one — the model must never present a steep descent as free speed.

## Goals / Non-Goals

**Goals**
- Store the course once, deterministically, without the browser fetching it.
- Produce per-kilometre pace targets whose grade model is calibrated to this
  athlete rather than assumed.
- After the race, attribute time lost and gained to specific gradients.

**Non-Goals** — as listed in the proposal: no course registry, no GPX import, no
modelled HR, no coach-briefing surface.

## Decisions

### D1 — Course identity is one optional field on the race

`planData.race.courseId` (integer) names the Garmin course. Absent → the whole
feature is dark: no fetch, no `courseLens`, no `/course` link.

*Why not a courses registry:* a registry is machinery for a problem that does not
exist — there is one race at a time, and the plan already models exactly one
`race`. A future race carries its own id and everything works, which is the
entirety of the generality actually needed.

*Consequence:* `plan-io.mjs` validation must accept and type-check the field, so
a coach edit cannot write a plan the lens will choke on.

### D2 — Schema v10: `courses` + `course_maps`, columnar points

```sql
CREATE TABLE courses (
  course_id       INTEGER PRIMARY KEY,
  course_name     TEXT NOT NULL,
  race_date       TEXT,
  distance_m      REAL NOT NULL,
  gain_m          REAL,
  loss_m          REAL,
  bbox_json       TEXT NOT NULL,
  points_json     TEXT NOT NULL,   -- columnar {d, lat, lon, elev, elevSmooth}
  lens_version    INTEGER NOT NULL,
  lens_json       TEXT NOT NULL,   -- derived: profile + pace plan + comparison
  update_date     TEXT,
  fetched_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL
);
```

`points_json` follows the `detail_streams_json` convention exactly — one rounded
array per column, not an array of objects. Four columns × 1 196 points ≈ 40 KB,
the size of a single run's streams.

`course_maps` mirrors `activity_maps` (z, x0/y0/x1/y1, crop box). `map_tiles` is
reused **unchanged** — it is already globally deduped by (z, x, y), so the
Sonthofen tiles simply join the pool.

`lens_json` is a disposable derived cache keyed by `COURSE_LENS_VERSION`, with
the same self-heal-on-version-bump semantics as `block_lens` and `run_metrics`.
Raw `points_json` is the source of truth; the lens is always recomputable.

### D3 — Smoothing happens in Python, and both series are stored

Raw DEM elevation over ~17 m point spacing produces meaningless
point-to-point grades — noise of ±20 % on flat ground. Every grade number in
this feature therefore derives from a **smoothed** elevation series (rolling
mean over a distance window, not a sample window, because point spacing varies).

Smoothing runs in Python at sync time and **both** series are stored: raw for
fidelity and future re-derivation, smoothed for display and all grade maths.

*Why not smooth in the browser:* `chart-core.js` exports `rollingMean`, so it is
possible — but then the pace model (Python) and the chart (JS) could disagree
about what the grade at km 13 is. Deriving once, server-side, makes that class
of bug unrepresentable, and matches the ROADMAP's rule that the archive API is a
window and not an engine.

### D4 — Analytic cost curve, calibrated by one scalar from the athlete's own data

The grade→pace model is the heart of the feature and the easiest thing to get
embarrassingly wrong.

A linear rule ("+12 s/km per 1 %") fails at both ends of *this* course: it would
report the −6.0 % kilometre as free speed, when braking and eccentric load make
very steep descents cost energy again. Presenting that descent as a place to
gain time would be actively harmful given the athlete's tibia.

So: an analytic energy-cost-of-running curve (a published polynomial in
gradient, coefficients pinned against the source at implementation time)
supplies the **shape**, including the descent reversal. Pure metabolic cost
overstates real slowdown, because runners exceed steady-state power on a climb
rather than holding it — off a 5:41 base the raw curve implies roughly 8:40/km
for the 8.25 % wall.

The archive supplies the correction. Every run stores `v`
(`directSpeed`), `gap` (`directGradeAdjustedSpeed`) and `elev` per sample;
across 500+ activities those are a large empirical record of how this athlete
actually slows on a grade. Fit **one scalar damping factor** over that data and
report the residual.

*Why one parameter and not a fitted curve:* one scalar cannot overfit, is
trivially testable, and keeps the physiologically-sound shape intact. A
free-form fit would chase GPS noise and produce a curve nobody could defend at
km 13.

*Consequence:* the model states its own accuracy. If the residual is poor, the
page says so rather than projecting false precision.

### D5 — Store the calibrated model, not baked tables; HR stays prose

The sync stores the **profile plus the calibrated cost parameters** (the curve's
identity, the fitted damping scalar, the residual). The per-kilometre pace table
for a given target finish is then arithmetic the page performs on stored
numbers.

Three named targets — the goal (1:59:59), Garmin's prediction, the honest Riegel
projection — ship as presets, but they are *presets over a model*, not three
precomputed tables.

*Why this way round:* baking N tables at sync time makes every new question a
sync change, and it does not scale to the question actually worth asking — *"I
am on for X at km 12, what does the wall cost me?"* — which wants a continuous
target, not three. Storing parameters makes that a slider later, with no schema
or sync change at all.

*Why this does not violate the architecture principle:* the rule that the archive
API is "a window, not an engine" constrains the **server** — no derivation at
request time, no writes. A browser evaluating a stored cost curve is not
deriving truth; it is rendering, exactly as `chart-core.js` already computes
scales, bands and rolling means at draw time. The truth — the profile, the
calibration, the residual — is derived once in Python and stored, which is the
part the principle exists to protect.

HR is deliberately **not** modelled (see Non-Goals): a computed cap would be
wrong exactly where it matters.

### D6 — The overlay aligns on distance, not time — and aligns in the SYNC

Course and activity both carry cumulative distance, so the actual run resamples
onto the course's distance grid. Actual distance is **normalised** first — scaled
so its total equals the course total — because GPS totals drift by tens of
metres over 21 km and an unnormalised alignment would smear the wall across two
kilometres.

*Why not time:* the two series share no time base at all. Distance is the only
axis on which "km 13" means the same thing in both.

*Where it runs:* in Python, at sync time, stored on the document. Matching an
activity, normalising its axis and resampling it establish **what happened** —
that is derivation, and the ROADMAP puts derivation in the deterministic sync.
The D5 carve-out that lets the browser evaluate a stored cost curve is scoped to
the profile, the calibration and the residual; it does not stretch to cover
this. What is stored is deliberately target-independent — the seconds actually
spent on each kilometre — so deltas against a chosen target stay arithmetic the
page performs, and switching target still costs no sync.

*Boundaries come from the row, never from its label.* Kilometre marks snap to
the nearest stored point (km 1 ends at 991 m on this course) and the final row
is a 113 m stub labelled "km 22". Reconstructing bounds as `km × 1000` drifts by
metres and puts the stub past the finish, dropping the closing stretch from
every attribution — so `startM`/`endM` are carried through the pace table.

### D7 — Activity matching is automatic and silent when it fails

A course matches an activity when the activity falls on the race date, is a run,
and its distance is within tolerance of the course. No match → the page shows
profile and pace plan only. No empty state, no error, no manual picker.

*Why no manual override:* one race, one obvious activity. A picker is UI for a
case that will not occur, and if it somehow does, the fix is one field.

### D8 — Everything degrades dark

No `courseId` → invisible. Fetch fails or offline → last stored copy, sync
continues. Elevation missing beyond a threshold fraction of points → the profile
is marked degraded rather than quietly drawing a lie. Archive away → the deep
view fails soft exactly like every other deep view.

### D9 — Determinism is asserted, as with tile rects

Same stored course plus same `COURSE_LENS_VERSION` in → byte-identical document
out. This mirrors the `route-basemap` requirement that the same streams always
yield the same zoom and rect, and it is what makes the derived cache safe to
throw away.

## Risks / Trade-offs

- **The calibration could be poor.** Garmin's `gap` is itself a model, so fitting
  to it inherits its assumptions. Mitigation: report the residual, and treat the
  analytic curve as the fallback when the fit is weak. The number on screen is
  never presented as more certain than it is.
- **Elevation-model disagreement** (197 m vs 143 m) means absolute gain is
  uncertain by ~40 %. Mitigation: the feature leads with *shape* and per-km
  grade, and presents total gain as a range with its source named.
- **Tile fetching for a new region** adds first-sync latency under the existing
  throttle policy. Mitigation: the map is the last thing rendered and the page is
  useful without it; tile acquisition failure degrades to a profile-only page.
- **Scope against the race date.** The overlay produces nothing until Aug 10,
  and building it first would risk arriving at race day with no pace plan.
  Mitigation: task ordering below delivers profile → pace plan → overlay, so the
  pre-race value lands first even if the change is not finished.

## Migration Plan

Schema v10 is additive and guarded (two `CREATE TABLE IF NOT EXISTS`), matching
how v6–v9 each landed. No backfill: the first sync after deploy fetches the
course and derives the lens. Rollback is dropping the `courseId` field — the
tables become inert and nothing else changes.
