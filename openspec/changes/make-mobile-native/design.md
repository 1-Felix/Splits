## Context

The full design study — including every measurement quoted here, the per-page target compositions
and the audit method — lives at
[`docs/superpowers/specs/2026-08-02-mobile-native-design.md`](../../../docs/superpowers/specs/2026-08-02-mobile-native-design.md).
This document records the technical decisions that shape implementation.

SPLITS is six `.dc.html` pages rendered by a **generated** runtime (`support.js`, never edited),
with React 18.3.1 vendored as a UMD global, no build step and no runtime dependencies. Behaviour
shared across pages lives once in `topbar.js`; the ~25 lines of topbar markup are duplicated per
page, deliberately, because the dc-component model has no cross-page include. Styling is
tokens → semantic classes → a desktop-first `@media` layer in `dashboard.css`.

The audit established four facts that changed the design, all verified by experiment rather than
inference:

1. **React owns only `#dc-root`.** `document.body`'s children are exactly `[div#dc-root, script]`.
   Nodes appended to `body` are outside reconciliation *by construction* — verified to survive a
   theme change plus six subsequent state changes.
2. **The page's own nav is mirrorable at t=41ms**, against a first-contentful-paint of 120ms. Chrome
   built from it paints in the first frame, and inherits tab availability and `aria-current` for
   free — which matters because Max's instance has no course tab.
3. **`<sc-if>` is supported** (`support.js:454` dispatches it, `:544` implements `walkIf`) and
   already used 14× across two pages. The "no conditionals" rule recorded in the 2026-06-29 design
   is a convention, not a runtime limitation.
4. **`chart-core.js` is already width-aware.** Run in node at `frame.w=324` it emits 3 x-ticks
   instead of 10. It is simply being fed a constant at every call site.

## Goals / Non-Goals

**Goals:**

- Full content parity on a phone — nothing removed, everything re-composed for touch and thumb reach.
- Persistent navigation, an installable shell, and a sheet layer that makes parity survivable.
- Charts that decide density against their rendered width and respond to real pointer events.
- Desktop rendering **unchanged** except where the audit found a defect at every width.
- A test runner, a data-independent responsive gate, and phone-width coverage — before the refactor,
  not after.

**Non-Goals:**

- An offline service worker. Explicitly declined: it adds cache invalidation to the Docker deploy,
  the single riskiest item on the list. The app ships installable but network-backed.
- Any change to `support.js`, the data contract, the sync, the lens engines, or any API route.
- Re-pulling from Claude Design. The local `.dc.html` files are the source of truth.
- Consolidating the six duplicated topbar copies. They have drifted into five variants, but this
  design deliberately avoids *needing* that refactor.
- Fixing the course basemap 404s. Investigated: the repo-root archive is schema 11 with 27 tiles
  while the NUC is schema 14 with 208 — a local data gap, not a bug.

## Decisions

### D1. The bottom tab bar is injected from `topbar.js`, not authored six times

**Chosen:** `topbar.js` mirrors `#dc-root header.topbar nav[aria-label="Pages"] a` into a
`<nav class="tabbar">` appended to `document.body`, re-running from a `MutationObserver` with a
signature check.

**Alternatives:** (a) author the bar in all six `.dc.html` files — the existing convention, but six
files to keep in sync forever and they have already drifted into five variants; (b) render it inside
the React tree per page — same cost, plus every page's `renderVals()` gains chrome concerns.

**Why:** the prototype measured header 122→62px, first content top 168→**96px**, each tab
97.5×56px = **3.6× today's nav-link area**, on four pages, with zero page-markup edits. Four
implementation rules the experiments proved load-bearing: scope the mirror to `#dc-root` (unscoped,
it matches the raw un-mounted `<x-dc>` template and returns `href="{{ n.href }}"`); copy `a.href`
absolute, because `run.dc.html:9` carries `<base href="/">`; give the bar a **different**
`aria-label` than `"Pages"` (two landmarks with one name is an a11y smell, *and*
`test_course_page.mjs:211` asserts over `nav[aria-label="Pages"] a`); and give it its own
`:focus-visible` ring, since it lives outside the themed root.

**Fallback if it regresses:** author the bar inside the themed root per page. `position: fixed` is
verified safe there — no ancestor sets `transform`, `filter`, `perspective`, `contain` or
`will-change`.

### D2. Theme custom properties are hoisted to `:root`

The 27 theme tokens are written onto the JS-built root `<div>`; `getComputedStyle(documentElement)`
returns the empty string for `--accent`. Any body-level bar or sheet therefore renders unthemed, on
a body whose background is hardcoded `#0E0F12` in all six helmets — visibly wrong under the light
`track` theme.

**Chosen:** `applyThemeVars(name, el = document.documentElement)` in `topbar.js`, called at module
load from `initialTheme()` and inside `persistTheme()`. Every page already calls `persistTheme()` in
its `setTheme`, so this is **zero page edits**. The vars stay on the root div as well — `:root` is
additive, so the cascade is unchanged for existing rules. Verified necessary: without
re-application the hoisted values go stale after a theme switch.

### D3. Tab icons are CSS `mask-image` with an inline `data:` URI

Not inline SVG: `test_course_page.mjs:206-208` asserts `querySelectorAll("svg").length === 0`
document-wide on a course-less `/course`, and an inline icon would break an unrelated page's test.
Not text glyphs: platform-dependent rendering. A `mask-image` creates no `<svg>` element, contacts
no origin (so `test_offline.mjs` stays green), and takes the theme accent via `currentColor`.

### D4. The phone tier is 700px, and phone-only chrome is toggled with `display`

**700, not 560:** the archive has a *backwards cliff* — 561–700px renders measurably worse than
560px, because the phone rules stop applying while the desktop grid still does not fit. 700 is also
the largest value that leaves `style-audit`'s LAYOUT map intact (`#sec-hero` must be 2 columns at
768). The existing 560px block stays for the grid collapses it already owns.

**`display`, not `transform`/`opacity`:** several tests assert *absence* via
`body.innerText.includes(...)`. Measured in Chromium: `display:none`, `visibility:hidden`,
`[hidden]` and `content-visibility:hidden` are excluded from `innerText`; `opacity:0`, `transform`,
off-screen positioning and `clip-path` are **all included**. A tab bar parked off-canvas would make
the desktop tests read "Archive"/"Progress" and fail.

### D5. Charts gain a `cssW` divisor, not a rewrite

Add optional `frame.cssW` to `buildSpec` and `sharedX.cssW` to `multiTrackSpec`; derive
`k = frame.cssW ? w / frame.cssW : 1` once and divide by `k` at every place a pixel threshold is
compared (`chart-core.js:316`, `:331`, `:324`/`:338`, `:580`, `:472`). The y-gutter, currently a
percentage of SVG width (81.7px at 1440, **22.5px at 360**, against a 9.5px font), becomes a
constant CSS-pixel column.

**Desktop is provably unchanged:** `min(6,…)` binds once `plot.w ≥ 480` and `min(7,…)` once
`plot.w ≥ 560`; desktop renders at 1022–1066 CSS px, so the caps still bind and the tick counts do
not move. `style-audit diff` plus `test_chart_core.mjs` / `test_chart_view.mjs` gate it.

**Alternative rejected:** a `ResizeObserver` re-render loop. It would introduce the project's first
layout-measurement dependency into a render path that is currently pure, for no gain the divisor
does not already provide.

### D6. Touch is a separate path, gated on `pointerType !== "mouse"`

Add `onPointerDown` / `onPointerMove` / `onPointerUp` / `onPointerCancel` to `renderChart`, reusing
the `(clientX - r.left) / r.width * W` math already at `chart-view.js:235`, with
`touch-action: pan-y` so vertical scrolling survives. Gating on pointer type leaves the existing
mouse handlers as the only desktop path, so desktop interaction cannot regress.

Where points are spaced under the touch minimum (measured 9.3–11.4px), switch to the engine's
*other* primitive rather than widening bands — `crosshairAt` snaps to the nearest sample by
bisection and is already what the run page uses for 1,673 samples. Widening `bandRects` is
impossible: it tiles the full width by construction.

**The drill is not patched, it is re-routed.** Chart-drill's second activation is provably dead on
touch (A/B'd at the same viewport: mouse@390 opens the panel, +771 chars; touch@390 dismisses the
pin, +0). On phones the pinned reading routes into the sheet, where the drill is a real ≥44px button
calling `hover.drill.action()` directly.

### D7. Swipe is passive, and ends in a real navigation

Three listeners at module scope, all `{ passive: true }` — so the handler *can never*
`preventDefault` and therefore can never break native scrolling or pinch-zoom. It bails when
`touches.length !== 1`, when a selection is active, or when any ancestor up to `<body>` is an `svg`
/ inside an `svg` / a form field / carries `data-no-swipe` / has a non-`auto` `touch-action` /
satisfies `scrollWidth > clientWidth + 1 && overflow-x is auto|scroll`. Disarms at
`|dy| > 8 && |dy| > |dx|`; locks horizontal only at `|dx| > 12 && |dx| > 2*|dy|`; navigates at
`touchend` past 25% of viewport width or 0.5 px/ms.

**It must not be a moving track.** Five pages assert `documentElement.scrollWidth <= width + 1` at
three widths; a carousel or any `100vw` element fails 15 assertions outright. Because it is passive
there is no rubber-band follow — the page changes at `touchend`. Polish comes free from
`@view-transition { navigation: auto }` (support verified): these are full document navigations, so
there is no client-side router to build. Targets come from `navModel(...).map(n => n.href)`, so
swipe order and tab order can never disagree.

### D8. The sheet is a restyling of `#drill-panel`, not a replacement

`test_progress_page.mjs:180-233` and `style-audit:331-363` assert that `#drill-panel` is exactly one
node, at least 90% of `#sec-charts` width, that focus lands on `#drill-panel-heading`, and that
Escape closes panel-then-pin. The sheet keeps the same id and children and uses
`left:0; right:0; bottom:0; width:100%` — never `100vw`. The existing state machine transfers
unchanged; only the container changes.

One caveat to honour: the cockpit and progress root divs carry `onClick="{{ onDismiss }}"`, which
dismisses pinned chart popovers. A tap inside a body-level sheet does not bubble there, so
`openSheet` calls `onDismiss` explicitly.

### D9. Move 0 comes first, and its new assertions are allowed to fail

`tools/style-audit.mjs layout` exits 1 today (two FAILs, `scrollWidth=457` on `/progress` at 390),
and prints `LAYOUT: ALL PASS` against an empty data dir because the pages fall back to demo data and
`#block-section` never renders. There is no `pnpm test` and no CI job that runs tests.

So Move 0 fixes `.block-week` and `.chart-grid`'s `minmax(340px,1fr)` floor, commits a fixture data
dir, adds `test` / `test:layout` scripts and a CI job, extends the width sweep and adds `/course`,
and closes two harness holes (`style-audit diff` can never fail — `code` is only assigned in the
`layout` branch; `TOPBAR_PARITY` asserts nothing when a selector is missing on *both* pages, which
is exactly the failure mode of renaming `header.topbar` during this work).

The new phone-width assertions in `test_mobile_pages.mjs` — the 44px target floor and the 11px type
floor — are **authored in Move 0 and expected to fail until the moves that satisfy them land**. They
are the specification of done, kept in a marked pending block that flips to enforcing at Move 6.
Writing a weaker assertion that passes today would catch nothing.

### D10. Per-file edits are one-liners only

Six files must each change in five places: `<title>`, `viewport-fit=cover` (the meta is parsed before
any script, so it cannot be injected in time for first layout), `body{background:var(--bg)}`, the
root `className`, and the manifest link. Every one is a single line. All behaviour lands in
`topbar.js` and `dashboard.css`, so the six copies cannot drift on this change.

## Risks / Trade-offs

- **The injected tab bar is the load-bearing bet** → prototyped end to end on four live pages
  including theme changes, reconciliation survival and paint timing; D1 records the per-page
  fallback.
- **Hoisting theme vars could alter the global cascade** → the vars remain on the root div as well,
  so `:root` is purely additive; `style-audit baseline` before Move 1 and `diff` after each move
  catches any computed-style change.
- **The chart `k` divisor could silently change desktop output** → verified arithmetically that the
  tick caps still bind at desktop widths, and gated by `style-audit diff` plus both chart suites.
- **Sheets could hide content behind an interaction nobody discovers** → the summarised form always
  states what the sheet contains and how much is behind it; content parity is asserted by spec.
- **Swipe could fight a local gesture** → the guard's decision function was tested against real
  elements on the live pages; it refused inside every chart, hit-band, ring, scroller and input, and
  armed only on plain card content.
- **Max's instance differs** (no course, historically no archive) → the bar is driven by
  `navModel(page, {archive, course})`, which already yields 2/3/4 entries, and `test_topbar.mjs`
  covers all three shapes. Both instances are verified at deploy.
- ~~The rep-table measurements are synthetic~~ → **retired 2026-08-02.** The local archive was
  refreshed from a consistent NUC snapshot (schema 11 → 14, 562 activities, **171 `run_intervals`**,
  208 map tiles), and the numbers were re-measured against the real lap-backed 5×1 km run
  `23543309396`. Both audit claims hold: the deviation bar's track is **6.0px at 360px** (fills
  0.0–3.0px; 36px at 390, 73.6px at 430, 275px at 1440), and the rep card sits **5th at y=1765 of a
  2393px document** — below a 410px route card and the best-efforts list. Note that `run.dc.html`'s
  helmet already carries a component-scoped `@media (max-width:430px)` block compressing the five
  fixed columns (34+48+40+44+44+30 = 240px plus five gaps); it is not enough, so the row must wrap
  or the bar must take its own line. The same refresh means the course basemap now renders locally.

## Migration Plan

No data migration; no schema change; no route or URL contract changes. Deployment is the existing
path: push `main` → CI builds `ghcr.io/1-felix/splits:latest` → on the NUC
`docker compose pull && up -d`.

New assets (`manifest.webmanifest`, `vendor/icons/`) must be added to the image — verify with a
container-side request, not only locally, since `test_offline.mjs` runs headless and headless
Chromium never fetches a manifest or icon lazily. That is why the offline test gains an explicit
**positive** assertion (`fetch('./manifest.webmanifest')` → 200, one per icon).

Rollback is `docker compose` to the previous image tag; because nothing outside the image changes,
rollback is complete and instant.

Verification runs on both instances (`splits` and `splits-max`) on a real phone: install to home
screen, safe-area clearance, tab bar, sheets, chart scrubbing, and that the course basemap renders
where it cannot locally.

## Open Questions

- **Cockpit chart carousel vs. stack.** The design proposes the cockpit's four charts as one
  horizontally-paged carousel. It is the right density answer, but it adds a second horizontal
  gesture surface next to the block strip. Resolve by building the block strip rail first and
  judging the result before committing the charts to the same pattern.
- **Whether the wide tier raises the cap for all six pages or only the two dense ones.** Four pages
  cap at 1100px and two at 1340px with no recorded reason; the spec requires one shared width, but
  which value is a judgement to make against a real 1920px screen.
