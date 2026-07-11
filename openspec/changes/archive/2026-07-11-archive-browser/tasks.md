# Tasks — archive-browser

## 1. archive-api: name search

- [x] 1.1 Add `q` to `listArchiveActivities` in `serve.mjs`: parameterized
      `name LIKE ? ESCAPE '\'` with `%`/`_`/`\` escaped in the input,
      AND-combined with type/year/from/to, `total` counting the filtered set
- [x] 1.2 Extend `test_archive_api.mjs`: name match, case-insensitivity,
      literal wildcard characters, `q` combined with type+year, filtered
      total/limit/offset, and unchanged behavior when `q` is absent

## 2. Archive page shell

- [x] 2.1 Serve `/archive` from the exact-path page map in `serve.mjs` and
      create `archive.dc.html` on the vendored runtime with the shared topbar
      and persisted theme
- [x] 2.2 Add the Archive entry to `topbar.js` (current-page marking included)
      and extend `test_topbar.mjs` to cover the third entry from every page
- [x] 2.3 Verify reflow at 1200/768/390 px with no horizontal overflow and
      register the page with the style audit

## 3. Archive list: rows, paging, filters

- [x] 3.1 Fetch the list endpoint and render rows newest-first with the
      promoted summary fields, no client-side recomputation
- [x] 3.2 Render the "shown of total" count and a load-more control that
      appends via `nextOffset` and disappears when exhausted
- [x] 3.3 Filter controls — type, year, debounced name search — AND-combined,
      mirrored to the query string via `replaceState`, restored from the URL
      on load, resetting pagination on change
- [x] 3.4 Explicit empty state when the filter combination matches nothing,
      filters remaining usable
- [x] 3.5 Run rows navigate to `/run/<id>`; non-run rows render as plain,
      non-focusable rows
- [x] 3.6 Honest degradation: 503 at load renders chrome plus archive-offline
      state; a failed load-more/filter request reports without clearing shown
      rows; retry works without a full reload
- [x] 3.7 Playwright `test_archive_page.mjs` (domcontentloaded +
      waitForFunction): rows render, filters narrow and survive reload, load
      more appends, run click-through navigates, non-run rows inert, offline
      states honest, empty state renders

## 4. Compare selection flow

- [x] 4.1 Compare toggles on run rows only, with a selection tray showing
      "Compare (n)"; fifth selection refused with a visible hint
- [x] 4.2 Compare action navigates to `/compare?ids=…` in selection order

## 5. Comparison page

- [x] 5.1 Serve `/compare` from the exact-path page map and create
      `compare.dc.html` on the vendored runtime with the shared topbar
- [x] 5.2 Parse `?ids=`: numeric guard per id, dedup, cap at four; fewer than
      two resolvable runs renders the honest prompt state
- [x] 5.3 Fetch each run's by-id payload and stream in parallel from the
      existing endpoints; chrome renders first; independent per-slot
      loading/failed states
- [x] 5.4 Summary grid: one labelled column per run with promoted fields,
      best value per comparable row marked (presentation only)
- [x] 5.5 Splits aligned by kilometre index; the longer run's extra
      kilometres render alone, no truncation or fabricated splits
- [x] 5.6 Overlaid tracks per measure (pace, HR, cadence, elevation):
      `series1…4` colors with a legend consistent across tracks, shared
      0…max-distance x domain via `sharedXScale`, y domains resolved over the
      union of runs through the POLICIES table (pace keeps its quantile clip)
- [x] 5.7 One crosshair indexed by distance across all tracks with per-run
      readouts; a run shorter than the crosshair position reads as ended
- [x] 5.8 Degradation: run missing a measure absent from that track; measure
      missing for all runs omits the track; stream-less run keeps its
      summary/splits column with a legend note; unknown id renders a per-slot
      unknown-run state while the rest compare
- [x] 5.9 Archive-offline chrome when the API is down at load; a single run's
      failed stream reports in its slot with scales computed over the runs
      actually shown
- [x] 5.10 Playwright `test_compare_page.mjs`: two-run compare renders all
      sections, shared scales assert (equal y domains across runs), crosshair
      reads both runs, direct URL works without prior selection, garbage ids
      dropped, one-unknown-id and offline states honest

## 6. Verification

- [x] 6.1 Style audit green for both new pages (chart assertions: axis
      labels, legend iff ≥2 series, data-line-paths stamp)
- [x] 6.2 Full test suite green (`test_archive_api`, `test_topbar`, new page
      tests, existing suites unaffected)
- [x] 6.3 End-to-end against a local archive copy: browse → filter
      "sonthofen"-style query → select two runs → compare renders on shared
      scales; verify `/archive` and `/compare` routes in the container image
- [x] 6.4 Update README route/page documentation if it enumerates pages
