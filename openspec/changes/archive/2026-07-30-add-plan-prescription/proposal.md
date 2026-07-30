# Proposal: add-plan-prescription

## Why

The coach's intent lives in `plan-data.js` as prose (`4×1 km @ 5:25–5:35`), and
compliance scores hard sessions on distance alone — "rep quality is the coach's
call" — while the interval lens has known exactly what was executed since v1.
This is the handoff's P3.2, the last open roadmap item of the interval-lens
arc: parse the plan's structured core and answer, per quality day, *did the
prescribed set happen, and inside its band?* The engine's prior stays the
watch's workout (decided 2026-07-30 with Felix: **compliance only** — no
engine or `INTERVAL_VERSION` change); the plan route is the coach's-intent
layer, and on Max's instance — a watch that can never carry a Garmin workout —
it is the only prescription source there is.

## What Changes

- **`plan_prescription.py` (new, pure)** — parses one day's `segments[]` into
  at most one prescription: a rep set (`count`, `repDistM`|`repDurS`, optional
  `paceBandS`, optional `zone`) or a steady pace target (`paceS`, approx).
  Deliberately tiny grammar (decided: Approach A): rep sets — including
  time-based, zone/effort-based, and the embedded `… · 3×400 m @ 5:41 inside`
  form — and `@ ~pace` steady targets. Everything else (HR bands, race-km
  rows, prose) is REFUSED (`None`) and the day keeps distance-only scoring.
  Every one of the live plan's 29 distinct `val` strings is a fixture, pinned
  either to its parsed shape or to refusal.
- **Rep-level verdict in `plan_compliance`** — for a scored run day with a
  parsed prescription and an activity holding an interval document: found vs
  prescribed count and per-rep in-band counts (pace sets judge work segments'
  `paceS` against the band; zone sets judge the document's `quality.zone`;
  steady targets judge the day's overall pace, ±10 s/km). Stored as
  `quality_json` on the compliance row. **Annotate-only** (decided): the
  day's status and reason are untouched — the verdict rides alongside.
- **Schema v14** — `plan_compliance.quality_json TEXT` (guarded ALTER).
  `COMPLIANCE_VERSION` 1→2; the existing rescore machinery recomputes
  scoreable weeks on the next sync.
- **Surfaces** — the briefing's compliance section speaks the verdict on
  quality days; `serve.mjs` carries `quality` through the by-id `plan` object;
  `run.dc.html`'s plan card renders it beside the executed rep table.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `coach-loop`: compliance rows on parseable quality days carry a rep-level
  verdict (annotation, never a status change); the parser refuses what it
  cannot read and the briefing speaks the verdict.
- `run-detail`: the plan card shows the planned session's prescription and its
  verdict beside the executed structure.

## Impact

- New `plan_prescription.py`; `plan_compliance.py` (verdict + version 2);
  `activity_archive.py` (v14 column); `sync_garmin.py` briefing section;
  `serve.mjs` plan object; `run.dc.html` plan card.
- Tests: new `test_plan_prescription.py` (29-string fixture sweep + grammar),
  `test_coach_pass.py`/compliance tests (verdict + rescore), page test for the
  plan card.
- No engine change: `interval_lens.py`, `INTERVAL_VERSION`, `run_intervals`
  and all documents untouched. Race-safe by construction.
