# Design: progress-views (stage 3a — the refactor)

## Context

The dashboard is one Claude Design component (`Running Dashboard.dc.html`,
~1,300 lines) rendered by the `support.js` dc-runtime, fed by one merged
`running-data.js`, served by a zero-dependency `serve.mjs`. The golden rule to
date: the page imports static files and talks to no API. Meanwhile the archive
(`activity-archive.db`, schema v3, DELETE journal mode — deliberately never WAL
because the data dir may sit on SMB) holds 536 activities with full raw detail
for all 158 runs, per-run derived metrics (`run_metrics`, `metrics_version`
discipline), predictions, plan snapshots, and compliance — none of it reachable
from the browser.

The sync already distills a run's raw detail into a small shape
(`fetch_run_detail` → `{splits, hrSeries, driftBpm, zoneMin, tempC, te, load,
elevGain, splitShape}`) for the 6 recent runs in `garmin-data.js`;
`coach-read.js` and the drill-down UI consume exactly that shape.

Constraints: single user on a trusted LAN; race Aug 9 (cockpit must stay
boring-reliable); all derivation lives in deterministic, tested Python; the
homeserver volume is canonical, local archive copies are disposable.

## Goals / Non-Goals

**Goals:**

- Land the architecture the next stages (3b archive browser/comparison, 3c
  block retrospectives) ride on: read-only archive API + multi-page shell.
- Prove it with `/progress`: the relocated long-game sections plus two new
  views (records wall, year-over-year), records clicking through to any
  archived run.
- Slim the cockpit to a true today/this-week/this-block page — subtractive
  only.
- Keep `serve.mjs` zero-dependency and keep every derivation in Python.

**Non-Goals:**

- Archive browser UI, run comparison (3b); block retrospectives (3c).
- Any write endpoint on the archive; any auth beyond the existing LAN posture.
- Server-side rendering, bundlers, frameworks — the `.dc.html` + `support.js`
  model stays.
- Re-deriving anything in JS that Python already derives.

## Decisions

### D1 — The golden rule is rescoped, not deleted

**The cockpit (`/`) renders complete from static files** — no fetch it can't
lose. **API-backed views must degrade honestly**: when the archive API is
unreachable they render whatever static data allows and mark the rest "archive
offline", never a broken page. Alternative — keeping the rule as-is — was
rejected with the roadmap reframe: the rule's *reason* (race-morning
resilience) attaches to the cockpit, not to every future page.

### D2 — The API is a window, not a second brain

`serve.mjs` endpoints only SELECT stored rows, shape field names, and paginate.
No domain formulas (drift, zones, TSS, Riegel), and no domain *policy* (e.g.
records-are-outdoor-only) may live in JS — policy encoded twice is how two
engines drift apart. Consequences: D4 and D5 below.

### D3 — 3a API surface: two endpoints, both feeding "open any run"

- `GET /api/archive/activities` — list over promoted columns only
  (`start_time_local`, `type_key`, distance, duration, HR, cadence, elevation),
  filterable (`type`, `year`, date range), paginated, newest-first. Ships now
  as the 3b foundation; costs nothing extra.
- `GET /api/archive/activities/:id` — promoted summary + the stored distilled
  detail (D5), byte-for-byte the shape `garmin-data.js` uses for recent runs,
  so `coach-read.js` and the existing drill-down UI work on any archived run
  unchanged.

Errors: `404` unknown id, `503 {error: "archive unavailable"}` when the DB is
missing or busy. No records/YoY endpoints — see D4. Raw `summary_json` /
`detail_json` are not exposed (payload size, and nothing in the browser should
grow a dependency on Garmin's raw shapes).

### D4 — Records-by-year and YoY are sync-time insights, not API queries

`insight_metrics.py` gains two derivations, emitted into the existing
`insights` block of `garmin-data.js`:

- `bestEfforts.byYear` — per calendar year, the existing `best_effort_table`
  logic (outdoor-only policy stays in one place), each entry carrying
  `activityId` + date for click-through.
- `yoy` — per-year monthly aggregates (distance km, run count, avg pace) over
  promoted columns.

Both are tiny (a few KB). Consequence: `/progress` renders **fully from static
files**; the API is needed only when a record is clicked through to its run.
Alternative — API-side SQL aggregation (`MIN(best_1k_s) GROUP BY year`) — was
rejected because the outdoor-only records policy would then live in both Python
and SQL-in-JS (violates D2), and static rendering gives `/progress` the same
resilience as the cockpit for everything but drill-down.

### D5 — Distilled detail is pre-computed at sync time into the archive

New column `activities.detail_distilled_json` (schema v3 → v4, additive, the
existing idempotent migration pattern). `fetch_run_detail` is refactored so the
distillation core takes a raw detail payload — the sync path (fresh from the
API) and the archive path (stored `detail_json`) share one implementation. A
one-shot local pass distills the 158 already-archived runs (no network); the
normal sync distills each run as its detail is topped up. The API serves the
stored JSON verbatim.

Alternatives rejected: distill-on-request in JS (puts `driftBpm`/`zoneMin`
formulas in JS — D2 violation and drift risk); serve raw `detail_json`
(~176 KB/run, browser grows a Garmin-raw dependency). Cost accepted: ~2 MB
across the archive, and a superseded line in the proposal ("no schema
migration") — v4 is additive and auto-applied.

### D6 — `node:sqlite`, per-request read-only opens, fail-soft

Base image bumps to `node:24` (stable `node:sqlite` keeps `serve.mjs`
dependency-free; no reason for the 22 pin). Because the archive stays in
DELETE journal mode (SMB constraint — unchanged), the nightly sync's write
transactions take exclusive locks; the API therefore opens the DB **read-only
per request** and treats `SQLITE_BUSY` as `503` rather than holding a
long-lived handle across a writer. `DatabaseSync` being synchronous is an
accepted trade-off: single user, indexed queries over ~10³ rows, ≤ tens-of-KB
payloads.

`node:sqlite` is imported lazily inside the archive routes: on an older local
Node the server still boots and serves the cockpit; only the archive endpoints
503. `package.json` gets `engines.node >= 24` as the documented expectation.

### D7 — Pages as the unit of growth; clean routes in `serve.mjs`

A small route map serves pages directly (no redirect chains):

```
/           → Running Dashboard.dc.html   (cockpit — unchanged URL semantics)
/progress   → progress.dc.html
```

The old `/Running%20Dashboard.dc.html` path keeps working (it's still a static
file). Each page is its own `.dc.html` component mounted by `support.js`;
adding a page (3b `/archive`, 3c `/blocks`) is one file plus one route-map
line and cannot regress existing pages.

### D8 — Topbar: shared behavior module, duplicated markup

New `topbar.js` owns the behavior: theme registry + persistence
(`localStorage` key `splits.theme`, read at component init so there is no
wrong-theme flash), the sync-pill state machine (`/api/status` polling +
`POST /api/sync`), greeting, and the nav model (current page highlighted). The
~25 lines of topbar markup are duplicated per page — the dc-component model has
no cross-page include, and a runtime-injected topbar would fight the renderer.
Drift is guarded by shared `dashboard.css` classes and a `style-audit`
assertion that both pages' topbars match computed styles.

### D9 — Cockpit diet: what moves, what stays

Moves to `/progress` (becoming its long-game backbone, above the two new
views): THE LONG GAME (weekly volume) and the 30-month chart grid (VO₂ · pace
· fitness/fatigue · cadence · pace@HR-band · cadence@ref-pace · records feed).

Stays in the cockpit: hero (race/trajectory · readiness · coach), KPI tiles,
THIS WEEK, ROAD TO SONTHOFEN, **heatmap** (the daily "am I consistent"
pulse — decided in explore), recent activities with drill-down (still fed by
`garmin-data.js` — the cockpit gains no API dependency).

Everything the cockpit keeps is untouched wiring — the diet is deletion plus
relocation, never rework, keeping race-week risk near zero.

### D10 — Archive path and the SMB guard

The API opens `<DATA_DIR>/activity-archive.db` (canonical in the container).
For the documented dev-against-mount workflow (SMB `SPLITS_DATA_DIR`), SQLite
over SMB stays forbidden: new env `SPLITS_ARCHIVE_DIR` points the API at a
local, disposable, `--backfill`-rebuildable copy while plan/garmin files keep
coming from the mount. If the archive file is absent → endpoints 503, nothing
else cares (mirrors the sync's fail-soft archive posture).

## Risks / Trade-offs

- [`SQLITE_BUSY` during the nightly sync window] → per-request read-only opens
  + 503 + honest "archive offline" UI state; the sync's own writes are batched
  and short. Single retry in the handler is acceptable if it proves noisy.
- [Duplicated topbar markup drifts between pages] → shared CSS classes, all
  behavior in `topbar.js`, style-audit parity assertion.
- [Local Node < 24 breaks dev] → lazy `node:sqlite` import (cockpit unaffected,
  archive routes 503), `engines` field + README note.
- [Distillation backfill bug] → additive column only, idempotent and
  re-runnable; raw `detail_json` is never modified, so a bad distill is always
  recomputable.
- [`garmin-data.js` growth from `byYear`/`yoy`] → a few KB against today's
  35 KB; monitored by the existing contract validation.
- [Cockpit regression during taper] → diet is subtractive-only by design (D9);
  new pages are additive; `style-audit layout` re-run on both pages at
  1200/768/390 px.
- [Unauthenticated read API exposes full history on the LAN] → accepted: same
  trust posture as the already-served `garmin-data.js`; README security note
  extended to mention the archive endpoints behind the same reverse-proxy
  advice.

## Migration Plan

1. Ship image: Node 24 base, new routes, new page, slimmed cockpit.
2. First sync on the new image auto-applies schema v4 (additive column) and
   runs the one-shot distillation pass over stored runs; `--verify-archive`
   extends to report distilled coverage.
3. Rollback = previous image: it ignores the extra column, the extra routes
   disappear, the old one-page dashboard renders from the same data files.
   No data migration in either direction.

## Open Questions

- None blocking. (Visual design of the records wall / YoY cards happens in the
  existing Claude Design flow during implementation; `/progress` inherits the
  established tokens in `dashboard.css`.)
