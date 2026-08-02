## 1. Green the gate (Move 0 — prerequisite)

- [x] 1.1 Fix `.block-week` so its children cannot escape the button: phone-tier two-line grid (line 1 = `Wk N` + phase + THIS-WK tag + chevron pinned right; line 2 = 7 day glyphs as `repeat(7,1fr)` + km right-aligned), drop the `minWidth` floors under the phone tier, add `overflow:hidden` as a guard. Verify `/progress` `scrollWidth` at 390 drops 457 → 390, collapsed *and* expanded.
- [x] 1.2 Change `.chart-grid` to `minmax(min(340px,100%),1fr)`; verify chart cards align with every other card at 320/360/372px.
- [x] 1.3 Commit a deterministic fixture data dir (block lens with long week labels, an insights block, a 3-run archive) and point `style-audit layout` at it by default, so the gate stops depending on live telemetry.
- [x] 1.4 Move `#sec-records` / `#sec-yoy` out of `PROGRESS_OPTIONAL` into hard assertions, now that the fixture guarantees them.
- [x] 1.5 Add `/course` to `style-audit`'s page list (loaded at no width today) and extend the width sweep to `[1920, 1600, 1200, 768, 390, 360]` with wide-tier expectations.
- [x] 1.6 Make a layout FAIL diagnostic: report the offending leaf via a clipping-aware walk (skip anything with an `overflow-x: auto|scroll|hidden|clip` ancestor), not just the measured width.
- [x] 1.7 Close two harness holes: `style-audit diff` currently can never fail (`code` is only assigned in the `layout` branch); `TOPBAR_PARITY` asserts nothing when a selector is missing on *both* pages.
- [x] 1.8 Add `pnpm test` and `pnpm test:layout` scripts covering all 27 `test_*.mjs` plus the layout gate.
- [x] 1.9 Add `test_mobile_pages.mjs`: all six routes at 360/390 — no document overflow, no page errors, key content present; plus the 44px target floor and 11px type floor in a marked **pending** block that flips to enforcing at task 8.4.
- [x] 1.10 Add a CI job running `test` + `test:layout` before `build-and-push` (needs `pnpm exec playwright install chromium`).
- [x] 1.11 Capture `style-audit baseline` as the desktop non-regression reference, and record the current suite result (27/27) in the change notes.
- [x] 1.12 **Gate:** `pnpm test` and `pnpm test:layout` both green against real data.

## 2. Own the frame (Move 1)

- [x] 2.1 Add `applyThemeVars(name, el = document.documentElement)` to `topbar.js`; call it at module load from `initialTheme()` and inside `persistTheme()`. Verify `:root` reports the active theme's `--accent` and does not go stale across two theme switches.
- [x] 2.2 Replace the hardcoded `body{background:#0E0F12}` with `background:var(--bg)` in all six helmets; verify the body is light under the `track` theme.
- [x] 2.3 Add a `<title>` to all six pages and promote the existing per-page label to the page's single `<h1>`.
- [x] 2.4 Add `viewport-fit=cover` to the six viewport metas; verify `env(safe-area-inset-bottom)` resolves non-zero on a device that reports one.
- [x] 2.5 Add a `.app-root` class to the root div in all six `render()` returns and move `padding` / `minHeight` out of `rootStyle` into `dashboard.css`, with `100dvh` and a `100vh` fallback.
- [x] 2.6 Publish the chrome contract in `dashboard.css`: `--tabbar-h` (0 above the phone tier, `56px + env(safe-area-inset-bottom)` below) and `--safe-b`.
- [x] 2.7 Introduce one `.page-shell` container class replacing the inline `max-width:1340px` / `1100px` on the six pages, so the chrome does not change width between pages.
- [x] 2.8 Add a themed `:focus-visible` rule covering the topbar, the tab bar and sheet controls (today only two selectors have one, and the UA ring is invisible against the dark background).
- [x] 2.9 Run `style-audit diff` — expect no desktop computed-style changes beyond the intentional container reconciliation.

## 3. Persistent chrome (Move 2)

- [x] 3.1 Add `PHONE_MAX = 700` and a pure, unit-testable `tabModel(entries)` to `topbar.js`.
- [x] 3.2 Implement `mountTabBar(doc)`: mirror `#dc-root header.topbar nav[aria-label="Pages"] a` (scoped selector; copy absolute `a.href`), render `<nav class="tabbar" aria-label="Sections">`, append to `document.body`, re-run from a `MutationObserver` with a signature check.
- [x] 3.3 Build the tab icons as CSS `mask-image` with inline `data:` URIs coloured by `currentColor`; confirm `test_course_page.mjs`'s document-wide `svg.length === 0` stays green.
- [x] 3.4 Style the bar: `display:none` above the phone tier (never `transform`/`opacity` — the `innerText` absence tests), 56px tabs, safe-area padding, `z-index:60`, its own focus ring.
- [x] 3.5 Turn `.topbar` into the slim sticky header under the phone tier: `position:sticky`, `nowrap`, nav pill hidden, greeting truncated, full-bleed via negative inline margin + matching padding.
- [x] 3.6 Move the sync pill and theme picker behind one ≥44px header control; give each theme swatch an explicit `aria-label` (today they are three unlabelled circles named only by `title`).
- [x] 3.7 Point `.cmp-tray` at `bottom: calc(var(--sp-3) + var(--tabbar-h))` and give the root the matching bottom clearance.
- [x] 3.8 Extend `test_topbar.mjs` to cover `tabModel` for the 2-, 3- and 4-entry nav shapes.
- [x] 3.9 Verify on all six pages at 390: header ≤62px, first content top ≈96px, header still pinned after scrolling to y=1200, no page errors.

## 4. The PWA shell (Move 2)

- [x] 4.1 Add `'.webmanifest': 'application/manifest+json; charset=utf-8'` to `serve.mjs`'s MIME map.
- [x] 4.2 Author `manifest.webmanifest` (relative `start_url: './'`, `display: standalone`, background and theme colour) plus 192/512 maskable icons under `vendor/icons/`, which already carries immutable cache headers.
- [x] 4.3 Add `<link rel="manifest">`, `apple-touch-icon` and a `theme-color` meta to all six heads; keep `theme-color` in sync with the active theme from `topbar.js`.
- [ ] 4.4 Ship the manifest and icons in the image (`Dockerfile`), and verify by requesting them from inside a running container.
- [x] 4.5 Add a **positive** manifest/icon assertion to `test_offline.mjs` (headless never fetches them lazily), and widen its source scan to the manifest, `archive`/`compare`/`course` and `topbar.js`.

## 5. Gestures (Move 2)

- [x] 5.1 Implement `armSwipe()` in `topbar.js`: three `{ passive: true }` listeners, active only under `PHONE_MAX`, targets from `navModel(...).map(n => n.href)`.
- [x] 5.2 Implement the refusal guard — multi-touch, active selection, or an ancestor that is an `svg` / inside an `svg` / a form field / `data-no-swipe` / non-`auto` `touch-action` / horizontally scrollable.
- [x] 5.3 Implement the thresholds: disarm at `|dy| > 8 && |dy| > |dx|`; lock at `|dx| > 12 && |dx| > 2*|dy|`; navigate at 25% of viewport width or 0.5 px/ms.
- [ ] 5.4 Add `@view-transition { navigation: auto }`.
- [x] 5.5 Test the guard against real elements on every page: charts, hit-bands, the readiness ring, the heatmap and block scrollers, and the search field must all refuse; plain card content must arm. Re-assert `scrollWidth <= width + 1` on all five asserted pages.

## 6. The sheet layer and containment (Move 3)

- [ ] 6.1 Implement `openSheet({ title, node })` in `topbar.js`: body-level, `z-index:70`, focus trap, Escape / backdrop / drag-down dismissal, `overscroll-behavior: contain`, safe-area padding, and an explicit `onDismiss` call so pinned popovers do not survive it.
- [ ] 6.2 Un-gate `.card--pin .pin-scroll` from `min-width:901px` so containment exists at every width; keep the absolute `inset:0` layout desktop-only. Verify the 768px readiness-card stretch (2,889px) is gone.
- [x] 6.3 Add `align-items:start` to `.hero-grid` in the tablet tier so a short card is never stretched by a tall partner.
- [ ] 6.4 Split `coach.note` on its own separators into an array in `renderVals()` and render it via `<sc-for>` so paragraphs exist — this fixes desktop legibility too.
- [ ] 6.5 Clamp the coach note to its headline plus ~4 lines on phones with a "Read the full note" control opening the sheet.
- [ ] 6.6 Split the coach log into `visibleLog` (newest 1–2, collapsed) and `fullLog` behind a "Plan adjustments" sheet.
- [ ] 6.7 Fix the readiness ring: delete the two SVG `<text>` nodes and centre an HTML block in the existing `position:relative` wrapper (the pattern `chart-view.js` already uses). Verify the score and status render at every width.
- [ ] 6.8 Restyle `#drill-panel` as a sheet under the phone tier — same id, same children, `left:0;right:0;bottom:0;width:100%`, `max-height:75dvh`. Keep `test_progress_page.mjs`'s panel contract green.
- [ ] 6.9 Route the progress week drill into a sheet, removing the accordion's jump-scroll.
- [ ] 6.10 Retire the 52 hover-only `title` attributes: fold day statuses into the week row's accessible name, make the phase strip real buttons, and turn the `insufficient data` chip into a button that opens its reason.
- [ ] 6.11 Verify the cockpit at 390px is under 6 viewport heights with all coach content still reachable.

## 7. Charts on touch (Move 4)

- [ ] 7.1 Add `frame.cssW` / `sharedX.cssW` and derive `k`; divide by `k` at `chart-core.js:316`, `:331`, `:324`/`:338`, `:580` and `:472`. Pass the measured width from every call site.
- [ ] 7.2 Make the y-gutter a constant CSS-pixel column (`chart-view.js:70`/`:83`) instead of a percentage of SVG width.
- [ ] 7.3 Fix the unit-label placement to sit inside the frame (`top: py(plot.y - 10)`, drop the `translateY(-100%)`) — this also fixes desktop's `bpm`-over-`HEART RATE`; promote the unit into the track caption on phones.
- [ ] 7.4 Add `onPointerDown`/`Move`/`Up`/`Cancel` to `renderChart`, gated on `pointerType !== "mouse"`, with `touch-action: pan-y`.
- [ ] 7.5 Switch phone-width dense charts from `bandRects` to `crosshairAt` nearest-point resolution.
- [ ] 7.6 Reserve the readout row unconditionally with placeholders, and render it on phones as a bar at `bottom: var(--tabbar-h)` shown only while a reading is placed. Verify the run page's 104px tap-shift and 186px off-screen readout are both gone.
- [ ] 7.7 Route the pinned reading into the sheet on phones, with the drill as a real ≥44px button calling `hover.drill.action()` directly; verify touch drill now matches mouse drill at the same viewport.
- [ ] 7.8 Make `placeAnnotations` lane by the label's projected extent in CSS px, and group annotations that still collide.
- [ ] 7.9 Emit the legend once per multi-track stack instead of per track.
- [ ] 7.10 Give the phone tier `.chart-ytick`/`.chart-xtick`/`.chart-flag` an 11px floor, and make each scoped chart default to the narrowest useful scope on phones with the full range one tap away.
- [ ] 7.11 Show the shared x-axis while scrubbing a stack taller than the viewport.
- [ ] 7.12 Run `style-audit diff` plus `test_chart_core.mjs` and `test_chart_view.mjs` — desktop chart output must be unchanged.

## 8. Re-composition and the token tier (Moves 5 and 6)

- [x] 8.1 Rename `test_archive_page.mjs`'s `.arch-row > span:nth-child(2)` selector to `[data-label="date"]` *before* touching the archive rows.
- [x] 8.2 Re-compose archive rows as bounded two-line cards with the whole row as one ≥56px target; move the compare toggle to a dedicated ≥44px leading control that cannot overlap the run name; omit absent measures instead of rendering em-dashes.
- [x] 8.3 Preserve pagination, scroll position and selection across back-navigation from a run; make the Compare button honestly disabled; raise the search field to 16px; fix the tray's multi-line state.
- [x] 8.4 Add the phone token tier: 44px target floor (`.scope-chip`, `.wk-back`, `.cmp-go`, `.cmp-toggle`, `.block-week`, archive rows), 11px type floor, `:active` feedback, device-neutral copy. **Flip `test_mobile_pages.mjs`'s pending block to enforcing.**
- [ ] 8.5 Re-compose `/compare` as one lane per run for the summary and per-kilometre rows for splits, keeping every measure and the best-per-measure marks; add navigation so a shared link is not a dead end.
- [ ] 8.6 Re-compose the records wall as one unit per distance with by-year detail behind a disclosure; make the records feed rows navigable like the wall cells.
- [x] 8.7 Re-compose `.block-day` as a stacked card and fix `.section-head` wrapping at phone widths.
- [ ] 8.8 Give `.run-lower` explicit mobile `order:` so the interval lens precedes the route and best-efforts. Measured on the real 5×1 km lap-backed run `23543309396` at 390px: the rep card sits **5th at y=1765 of a 2393px document (74% depth)**, below the 410px route card and best-efforts. Target order: reps → splits → route → bests.
- [ ] 8.9 Re-compose the rep row so the deviation bar survives phone width. Measured on the same real run, the bar's track is **6.0px at 360px** (fills 0.0–3.0px), 36px at 390, 73.6px at 430, 275px at 1440 — the interval lens's whole point is invisible on a phone. The existing `@media (max-width:430px)` override in `run.dc.html`'s helmet already compresses the five fixed columns (34+48+40+44+44+30 = 240px + 5 gaps) and still leaves only 6px; the columns must wrap or the bar must move to its own line.
- [ ] 8.10 Re-compose the course pace table with persistent column meaning, and make the decisive-segment chips real controls.
- [ ] 8.11 Compose the cockpit for a phone: merged *today* card, the block strip as a horizontal snap rail acting as the week switcher, KPIs 2-up, recent activities with sheets. Build the rail first, then judge whether the chart carousel follows (design open question).
- [ ] 8.12 Give every horizontal scroller an edge affordance that paints only while it overflows, plus `scroll-snap` and `overscroll-behavior-x: contain`; open the heatmap on today rather than the oldest half of the year.

## 9. Wide screens (Move 7)

- [x] 9.1 Add the ≥1600px tier: raise `.page-shell` to a shared clamp and let the topbar frame the display.
- [x] 9.2 Use the reclaimed width for denser composition rather than wider whitespace; verify the container is wider at 1920 than at 1440 and identical across all six pages.

## 10. Verification and deploy

- [ ] 10.1 `pnpm test` — all suites green, including the updated `test_topbar.mjs`, `test_offline.mjs`, `test_archive_page.mjs` and the new `test_mobile_pages.mjs`.
- [ ] 10.2 `pnpm test:layout` green at all six widths on all six pages.
- [ ] 10.3 `style-audit diff` — no unintended desktop computed-style change.
- [ ] 10.4 Capture the visual slice harness at 360/390/768/1440/1920 for all six pages and review against the pre-change captures.
- [ ] 10.5 Record the measured before/after: cockpit screens, sub-44px target counts, sub-12px text counts, `/progress` overflow.
- [ ] 10.6 Push `main`, let CI build, then `docker compose pull && up -d` on the NUC.
- [ ] 10.7 Verify on a real phone against both `splits` and `splits-max`: install to home screen, safe-area clearance, tab bar, sheets, chart scrubbing, swipe, themes — and confirm the course basemap tiles render on the NUC (schema 14, 208 tiles) where they cannot locally.
- [ ] 10.8 Write `notes.md` with the deployed result, anything deferred, and any test left legitimately updated.
