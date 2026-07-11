# Archive Browser + Run Comparison (Roadmap Stage 3b)

## Why

The archive holds every activity since May 2024 (~540 and growing nightly), but
the dashboard can only reach it through narrow keyholes: record click-throughs
and direct `/run/:id` URLs. There is no way to *see* the archive — to answer
"show me my long runs last winter" or to put two race efforts next to each
other. With Sonthofen on Aug 9 and tune-up races landing before it, building
the browser and comparison view now means the natural first question — "how did
the race compare to the tune-ups?" — has its answer waiting the morning after.

## What Changes

- **A new archive page** (top-level, in the shared topbar navigation): a
  paginated, filterable listing of every archived activity — filter by type,
  year, date range, and name; runs click through to their existing `/run/:id`
  page. Like the run page, it is a deep view: it talks to the read-only archive
  API and degrades to an honest "archive offline" state, never a broken page.
- **Run comparison**: select runs from the browser and see them side by side —
  summary metrics, per-kilometre splits, and stream tracks on a shared,
  comparable basis (reusing the chart engine's synchronized-track seams:
  `multiTrackSpec`, `sharedXScale`, `crosshairAt`). Natural first use:
  Sonthofen vs the tune-up races.
- **Archive list endpoint learns name search**: the existing
  `GET /api/archive/activities` filters (type, year, from/to, bounded
  pagination with total) gain a name-substring filter, so "Sonthofen" is
  findable among ~540 activities without paging through them.
- No sync changes, no schema changes, no new derivation anywhere: the API
  stays a window (SELECT + shape + paginate), and everything the comparison
  shows is already stored per run. Comparison layout/deltas are presentation,
  computed in the page from served rows.

## Capabilities

### New Capabilities

- `archive-browser`: the archive listing page — route, topbar/nav integration,
  filter + pagination behavior over the list endpoint, click-through to run
  pages, and honest degradation when the archive API is unavailable.
- `run-comparison`: selecting archived runs and rendering them side by side —
  selection flow, comparison layout (summary, splits, synchronized stream
  tracks), comparable scales/domains across runs, and offline degradation.

### Modified Capabilities

- `archive-api`: the read-only listing requirement gains name-substring
  filtering as a supported filter dimension (alongside type, year, and date
  range). No other endpoint or contract changes.

## Impact

- **`serve.mjs`**: name filter in `listArchiveActivities`; routes for the new
  page(s) (pattern follows the existing `/run/:id` route handling).
- **New page(s)**: `archive.dc.html` (+ comparison view — same page or a
  sibling `compare.dc.html`, decided in design), rendering via the vendored
  runtime and chart engine like the existing pages.
- **`topbar.js`**: one new navigation entry (shared module — existing pages
  untouched, per the multi-page-shell requirement).
- **Chart engine**: consumed, not modified — comparison reuses the run-detail
  track seams; any gap discovered in design becomes an explicit design note.
- **Tests**: `test_archive_api.mjs` grows name-filter coverage; new Playwright
  page test(s) following `test_run_page.mjs`; style-audit coverage for the new
  page(s).
- **Not affected**: Python sync, archive schema, `garmin-data.js`, the cockpit
  (static-first golden rule untouched — this is a deep view by the rescoped
  architecture principle), coach loop.
