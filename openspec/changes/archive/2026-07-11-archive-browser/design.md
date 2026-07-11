# Design — archive-browser (Roadmap Stage 3b)

## Context

The archive (SQLite, ~540 activities since 2024-05) is reachable only through
keyholes: the records wall's click-throughs and direct `/run/:id` URLs. The
read-only API already lists activities with type/year/date-range filters,
bounded offset pagination, and a total count (`serve.mjs
listArchiveActivities`); the by-id and streams endpoints already serve
everything a run's page needs. The chart engine ships the exact seams a
comparison needs: `multiTrackSpec`, `sharedXScale`, `crosshairAt`,
`segmentNulls`, validated `series1…4` tokens, and the pace clip policy.

Page conventions this change inherits: `<name>.dc.html` component pages served
by exact-path map (only `/run/:id` is pattern-routed and needs `<base
href="/">`), shared `topbar.js` (nav, theme, sync pill), vendored runtime (no
third-party origin), Playwright page tests (`domcontentloaded` +
`waitForFunction` — `networkidle` hangs against a missing archive), and the
style audit asserting chart grammar.

Architecture principle (rescoped 3a): the cockpit is static-only; deep views
may talk to the archive API but must degrade to an honest "archive offline"
state. The archive browser and comparison view are deep views.

## Goals / Non-Goals

**Goals:**

- A browsable, filterable window onto the whole archive at `/archive`, in the
  topbar nav, honest when the API is away.
- Side-by-side run comparison driven purely by ids in the URL — shareable,
  bookmarkable, reachable both from the browser's selection flow and directly.
- Name search in the list endpoint (`q`), so "Sonthofen" is findable without
  paging.
- Zero new derivation: the API stays a window; every compared number is
  already stored per run; comparison layout/deltas are page-side presentation.

**Non-Goals:**

- No sync or schema changes; no new endpoints.
- No GPS-trace overlay in the comparison — two different routes on one
  projection is misleading; the trace stays on each run's own page.
- No plan-compliance columns in the comparison (visible on each run's page).
- No time-basis toggle in the comparison — runs are compared by distance,
  which is the basis on which races align.
- No comparison of non-run activities; no saved/named comparison sets.
- The cockpit, coach loop, and Python sync are untouched.

## Decisions

### D1 — Two pages: `/archive` and `/compare` (exact-path routes)

The browser and the comparison are separate `.dc.html` pages behind exact
paths in the existing page map. The comparison reads its runs from the query
string (`/compare?ids=123,456`), not a pattern route — no `<base>` hack, a
natural home for a variable-length id list, and a comparison is a URL you can
send someone. Alternative considered: comparison inline on the archive page —
rejected because it couples the two views' states and makes comparisons
non-shareable.

### D2 — Selection is a tray on the archive page; the URL is the only state

Run rows (only runs) carry a compare toggle. Selecting ≥1 run raises a tray
("Compare (n)"); activating it navigates to `/compare?ids=…` in selection
order. No selection persistence beyond the navigation — the compare URL *is*
the saved state. Cap: 4 runs (the palette's validated `series1…4` and the
legibility of a splits grid; a 5th toggle is refused with a visible hint).

### D3 — Browser filters: type, year, name search; reflected in the URL

The UI exposes the three filters people actually reach for — type, year, and
a name search box (debounced → `q`) — and mirrors them into the page's query
string via `replaceState`, so a filtered view survives reload and back
navigation. `from`/`to` remain API-level parameters without browser UI.
Filters combine (AND), matching the API. Changing any filter resets paging.

### D4 — Pagination: "Load more" over the existing offset contract

The list renders a page (server default 50), shows "N of total", and a Load
more control appends the next offset while `nextOffset` is non-null.
Alternatives: infinite scroll (surprising with keyboard nav, hides the total)
and numbered pages (over-UI for one table) — rejected.

### D5 — `q` is a wildcard-safe, case-insensitive substring filter

`listArchiveActivities` gains `q`: parameterized `name LIKE '%…%' ESCAPE '\'`
with `%`/`_`/`\` escaped in the input; SQLite LIKE gives ASCII
case-insensitivity. It composes with type/year/from/to under the same AND
semantics and the same COUNT for `total`. This is the only API change.

### D6 — Comparison layout: metric grid → overlaid tracks → aligned splits

Top: one column per run (date-labelled), rows for distance, duration, avg
pace (presented as duration ÷ distance), avg HR, avg cadence, elevation gain —
the promoted summary, no domain recomputation; the best value per row is
visually marked (presentation only). Middle: one track per measure (pace, HR,
cadence, elevation), each overlaying up to 4 runs as `series1…4`-colored lines
with a legend naming each run — the tracks sit directly under the summary so
the crosshair readout reads beside the numbers it contextualises. Bottom:
per-km splits aligned by km index, one bar group per km; a longer run's extra
kms render solo — honest tails, no truncation.

### D7 — Comparable scales via the existing policy machinery

All tracks share one x domain, 0…max(distance) across the compared runs
(`sharedXScale`). Each measure's y domain is resolved over the *union* of the
compared runs' series through the existing POLICIES table — pace keeps its
quantile clip (`[0.02, 0.98]`, pooled over the concatenated series) so one
run's GPS spike cannot own every run's scale. One crosshair indexes all runs
at the same distance — `crosshairAt` bisects the shared grid once and each
run's resampled columns are read at that index — with a per-run readout; a run
that has already finished at that distance reads as ended, not as a value.

### D8 — Missing data degrades per run, silently per track

A run missing a measure (no power, no cadence) is simply absent from that
track; a measure missing for *all* compared runs omits the track entirely
(run-detail's established rule). A run without a stored stream still occupies
its summary/splits column, with the track legend noting it has no stream. An
unknown id gets an honest per-slot "unknown run" state; fewer than two
resolvable runs collapses the page to an honest prompt state. Any archive 503
→ the established archive-offline chrome.

### D9 — Non-run rows are not interactive

Only run rows navigate to `/run/:id` and offer the compare toggle; other
activity types render as plain rows — no focusable no-op buttons (the exact
trap the records wall's verification flagged).

### D10 — Data fetching: existing endpoints, parallel, chrome-first

The comparison fetches each run's by-id payload and stream in parallel from
the existing endpoints (gz ~30 KB per stream; 4 runs is well inside budget).
The page chrome renders before any fetch resolves; per-run slots carry
loading → resolved/failed states independently. No server-side downsampling —
the run page already renders full-resolution streams.

## Risks / Trade-offs

- [Union y-domains squash detail when runs differ wildly (trail vs road)] →
  quantile clip absorbs spikes; the comparison's job is honest contrast, and a
  visibly compressed fast run *is* the contrast. No per-run axes — two scales
  on one plot is the lie the run-detail spec already forbids.
- [LIKE on user input] → parameterized statement plus `%`/`_`/`\` escaping;
  never string-interpolated SQL.
- [Garbage in `?ids=`] → client-side `^\d+$` guard per id before any fetch
  (mirrors the server's numeric-id guard); non-numeric ids are dropped, the
  dedup'd first four kept.
- [Topbar nav gains a third entry; phone width] → nav already reflows at the
  standard breakpoints; the style audit and `test_topbar.mjs` extend to the
  new entry.
- [Playwright `networkidle` hang] → new page tests follow `test_run_page.mjs`:
  `domcontentloaded` + `waitForFunction`.
- [Filter UI drifting from URL state] → single source of truth: state is read
  from the URL at load and written back on change; tests assert reload
  restores the view.

## Migration Plan

Purely additive: two new pages, one nav entry, one query parameter. Deploy is
the existing CI → NUC image flow; rollback is a revert (no data, schema, or
sync migration). `/archive` 404s on an old image and nothing else regresses.

## Open Questions

None blocking — comparison entry flow, filter surface, and scale policy are
settled above; anything cosmetic falls to implementation within the existing
style audit's constraints.
