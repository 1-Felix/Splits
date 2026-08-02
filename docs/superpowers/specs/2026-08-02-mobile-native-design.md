# SPLITS — Mobile-Native Dashboard

**Date:** 2026-08-02
**Status:** Approved design, ready for implementation plan
**Goal:** Make every SPLITS page feel *made for* a phone — persistent chrome, touch-first
interaction, compositions designed for a 390px column — at **full content parity**, while the
desktop experience stays identical where it is good and gets better where it is measurably broken.

---

## 1. Context

### Where we are

The 2026-06-29 styling refactor gave the dashboard its first responsive layer: tokens → semantic
classes → three `@media` blocks. It made the dashboard **fit** a phone. It never made it
**compose** for one. Two years of feature work (progress views, archive browser, run detail, run
comparison, the course page, four lens engines) then landed on top of a layout system whose entire
phone story is six grid overrides at `max-width:560px`.

An exhaustive audit was run on 2026-08-02 against a live dev server at 360 / 390 / 768 / 1440 /
1920 px — six per-page auditors plus three cross-cutting ones (shared chrome, chart engine on
touch, guardrails), then a synthesis pass that deduplicated the results and re-verified the
contradictions. **145 findings, 55 of them critical or high.** The numbers below are measured, not
estimated.

| | cockpit | progress | archive | run | compare | course |
|---|---|---|---|---|---|---|
| screens of scroll @390 | **18.3** | 4.1 | 3.9 | 2.7 | 2.2 | 2.6 |
| same @1440 | 2.5 | 2.9 | 2.8 | 1.9 | 1.7 | 2.9 |
| interactive elements < 44px | 8 | 33 | **53** | 8 | 6 | 10 |
| text nodes < 12px | 209 | 241 | 116 | 80 | 126 | 31 |
| `sticky` / `fixed` elements | 0 | 0 | 0 | 0 | 0 | 0 |

### The four root causes

Nearly every finding traces to one of these. Fixing symptoms individually would be dozens of edits
that never add up to a different feeling; fixing the causes retires them in blocks.

**A. Long-form content has no containment below 901px.** `.card--pin .pin-scroll` — the rule that
bounds unbounded coach text to a scroll region — lives inside `@media (min-width:901px)`
(`dashboard.css:77-83`). Below that it simply does not apply. Measured on the cockpit at 390px:
`#card-coach` = 2,760px and `#card-planlog` = 8,051px, together **10,811px = 69.9% of the page**.
The coach log alone is 25,153 characters and 9.5 screens. The same rule stretches `#card-ready` to
**2,889px at 768px** — a 2.8-screen empty black rectangle beside the coach text, because the two
cards are grid row partners and the tall one sets the row height.

**B. There is no chrome.** `.topbar` is a normal in-flow block that wraps to three rows on a phone,
occupies **168px — 20% of an 844px viewport — before a single pixel of content**, and then scrolls
away permanently. Across documents up to 15,456px there is no way to know where you are or to go
anywhere without scrolling back to the top. Nothing on any page is `position:sticky` or `fixed`.

**C. The chart engine is width-blind and mouse-only.** Every call site hard-codes `frame:{w:600}`
(`progress.dc.html:1001,1027,1057,1085,1113,1165,1282`) or lets `multiTrackSpec` default
`sharedX.w` to 600 (`chart-core.js:694`); the SVG is then stretched with
`preserveAspectRatio="none"` (`chart-view.js:225`). Measured scaleX: **0.490 at 360px, 0.540 at
390px, 1.777 at 1440px.** Every tick-density, gutter-width, hit-band and annotation-lane decision
is therefore made for a 600px chart and squashed. Hit bands measure **9.3–11.4px**. Separately, a
repo-wide grep for `pointerdown|touchstart|onPointer|onTouch|ResizeObserver|matchMedia` returns
**zero hits in app code**: a tap works only because browsers synthesise mouse events, a touch-drag
produces literally zero events, and chart-drill's second activation is provably dead on touch
(A/B'd at the same viewport: mouse@390 opens the panel, +771 chars; touch@390 dismisses the pin,
+0 chars).

**D. The frame is inline styles.** The 27 theme custom properties are written onto the JS-built
root `<div>` (`rootStyle`), **not** `:root` — `getComputedStyle(documentElement).getPropertyValue('--accent')`
returns the empty string. `body{background:#0E0F12}` is hardcoded in all six helmets, so the body
stays black under the light `track` theme. The page container caps (`max-width:1340px` on two
pages, `1100px` on four) and the root's `padding:'22px clamp(16px,4vw,40px) 64px'` are inline
attributes and JS-written objects. **No media query can touch any of it without `!important`.**

### Defects that are not mobile-specific (in scope by decision)

- **The readiness ring renders no score and no status, at every width.** The dc-runtime wraps
  `{{ }}` in an HTML `<span class="sc-interp">`, which has no rendering inside an SVG `<text>`;
  both nodes measure `getBBox()` = 0×0 (`Running Dashboard.dc.html:133-134`). The cockpit's
  second-most-prominent number has been invisible on desktop too.
- **The coach note is one unbroken text node** — 5,503 characters, zero `<br>`, zero `<p>` — a
  2,067px wall at 390px and a 1,535px wall at 1440px.
- **There is no test runner and no CI that runs tests.** 27 `test_*.mjs` files invoked by hand;
  `.github/workflows/docker-publish.yml` only builds the image.
- **The responsive gate is already RED.** `node tools/style-audit.mjs layout` exits 1 with two FAIL
  lines (`scrollWidth=457` on `/progress` at 390) — and against an empty data dir the same command
  prints `LAYOUT: ALL PASS`, because the pages fall back to demo data and `#block-section` never
  renders. The gate is data-dependent and currently unreliable.

**Investigated and dismissed:** the course page's six 404ing basemap tiles are a *local archive
gap*, not a production bug. The repo-root archive copy is schema 11 with 27 tiles; the NUC is
schema 14 with 208. No fix is in scope; the deploy step verifies tiles render on the NUC.

---

## 2. Verified runtime facts and guardrails

These were established by experiment during the audit. Several correct long-standing assumptions.

### Runtime

- **`<sc-if>` IS supported.** `support.js:454` dispatches it, `support.js:544` implements `walkIf`
  with `value` + `hint-placeholder-val` attributes. It is already used 8× in `progress.dc.html` and
  6× in `Running Dashboard.dc.html`. *The "no conditionals, use empty arrays" rule recorded in the
  2026-06-29 design is a convention, not a runtime limitation.* This is load-bearing here: phone and
  desktop compositions can be **forked** so only one exists in the DOM, rather than both-rendered-
  and-CSS-hidden — which is also what the `innerText`-based tests require.
- **`support.js` is generated and must never be edited.** Unchanged.
- **React owns only `#dc-root`.** `support.js:161-193` does `ReactDOM.createRoot(hostEl)` where
  `hostEl` is `div#dc-root`; `document.body`'s children are exactly `[div#dc-root, script]`. Nodes
  appended to `body` are untouched by reconciliation *by construction* — verified to survive a theme
  pick plus six further state-changing clicks.
- **The page's own nav is mirrorable.** `#dc-root header.topbar nav[aria-label="Pages"] a` exists at
  **t=41ms** while first-contentful-paint is at **120ms**, so chrome built from it paints in the
  first frame with no flash. Mirroring yields correct tab availability *and* `aria-current` on every
  page without the module knowing anything about routing. Two rules the experiments proved
  load-bearing: scope the selector to `#dc-root` (an unscoped selector matches the raw un-mounted
  `<x-dc>` template and returns `href="{{ n.href }}"`), and copy `a.href` (absolute) rather than
  `getAttribute('href')`, because `run.dc.html:9` carries `<base href="/">`.
- **`position:fixed` is safe inside the themed root** — no ancestor sets `transform`, `filter`,
  `perspective`, `contain` or `will-change`. Sticky was verified to hold at `top:0` after scrolling
  to y=1200 on all four top-level pages.

### Test contracts the design must not break

| Contract | Where | Design consequence |
|---|---|---|
| `documentElement.scrollWidth <= width + 1` on 5 pages × 3 widths | `tools/style-audit.mjs:179-226`, `test_run_page.mjs:675-681` | Swipe must be a **passive gesture ending in a normal navigation**, never a wide track. No `100vw` anywhere. |
| Absence asserted via `innerText` (`!includes("Archive")`, …) | `test_slim_render.mjs:220-228`, cockpit/archive/compare tests | Phone-only chrome must be hidden with **`display:none`** — measured: `opacity:0`, `transform`, off-screen and `clip-path` all leave text in `innerText`. |
| `querySelectorAll("svg").length === 0` on a course-less `/course` | `test_course_page.mjs:206-208` | **Tab icons must be text glyphs or CSS `mask-image`**, not inline SVG. |
| `navModel` yields 2 / 3 / 4 entries by instance; `style` is read as a string | `test_topbar.mjs:55-104` | Drive the tab bar from `navModel(page,{archive,course})` so Max's archive-less instance is correct. Keep `style` populated if a class API is added. |
| `#drill-panel` is exactly one node, ≥90% of `#sec-charts` width, focus lands on `#drill-panel-heading`, Escape closes panel-then-pin | `test_progress_page.mjs:180-233`, `style-audit:331-363` | The sheet is a **restyling of `#drill-panel`** — same id, same children, `left:0;right:0;bottom:0;width:100%`. |
| LAYOUT map pins `#sec-stats` to 2 cols at 390, `#sec-hero` to 2 at 768 | `tools/style-audit.mjs:40-56` | Phone tier caps at **700px**; KPIs stay 2-up on phones. |
| `test_offline.mjs` forbids all non-same-origin requests and same-origin 4xx outside an allowlist | `test_offline.mjs:143-148` | Manifest and icons are served from our own origin and must not 404. Headless Chromium never fetches them, so add a **positive** assertion (`fetch('./manifest.webmanifest').then(r => r.status)` === 200). |

**Known-legitimate test updates:** the LAYOUT map if breakpoints move (same commit, with a comment
naming the reason); the `/course` svg-count assertion; `test_topbar.mjs` if `navModel` gains a class
API; and `test_archive_page.mjs:112`'s `.arch-row > span:nth-child(2)` should become
`[data-label="date"]` *before* the archive rows are re-composed.

### Deploy

Edit repo → push `main` → CI builds `ghcr.io/1-felix/splits:latest` → on the NUC
`docker compose pull && up -d`. Two instances run from the same image: `splits` and `splits-max`
(Max's has no course and, historically, an archive-less period). Host port 5732→8000.

---

## 3. Architecture

### Breakpoint system

```
≤ 700px   PHONE    bottom tab bar, sticky header, sheets, 44px targets,
                   phone type tier, re-composed lists/tables, compact charts
701–900   TABLET   existing rules, plus align-items:start so a short card
                   is never stretched by a tall partner
≥ 901     DESKTOP  unchanged
≥ 1600    WIDE     new: raised container cap, denser composition
```

**Why 700 and not 560.** The archive has a *backwards cliff*: 561–700px renders measurably worse
than 560px, because the phone rules stop applying while the desktop grid still does not fit. 700 is
also the largest value that leaves style-audit's LAYOUT map intact (`#sec-hero` must be 2 columns at
768). The existing `max-width:560px` block stays for the grid collapses it already owns.

### Layer order

```
dashboard.css   :root tokens ─▶ semantic classes ─▶ @media tiers ─▶ NEW: chrome + sheet layer
topbar.js       theme registry + nav model + sync ─▶ NEW: applyThemeVars, tabModel/mountTabBar,
                                                          openSheet, armSwipe
chart-core.js   NEW: frame.cssW ─▶ k divisor at every px-threshold comparison
chart-view.js   NEW: pointer handlers gated on pointerType !== "mouse"
*.dc.html       structure + {{ }} + data-driven inline styles
                NEW: <sc-if> phone/desktop composition forks where a fork is genuinely needed
```

### Design principle

**Parity of content, not parity of layout.** Nothing is removed on a phone. What changes is *where
it lives*: long-form and secondary detail move behind sheets and disclosures reachable in one tap,
so the primary column stays short and every screen has a job. The cockpit target is **18.3 → ~4.5
screens with nothing deleted.**

---

## 4. The eight moves

### Move 0 — Green the gate (prerequisite)

There is no acceptance signal today, and the one responsive gate is red for a reason unrelated to
this work. Before any refactor:

1. **Fix `.block-week`.** The `/progress` overflow culprit is *not* the records wall (that is
   correctly clipped inside `overflow-x:auto` and cannot contribute to `documentElement.scrollWidth`
   — one auditor got this wrong and the synthesis re-measured it). A clipping-aware walk returns
   exactly two leaves, both children of `.block-week`: the km span at right=434.7 and the `▸`
   chevron at right=456.7, matching `scrollWidth`=457 to within rounding. `<button>` does not clip
   its children. Fix: re-compose `.block-week` on phones from one flex line into a two-line grid
   (line 1 = `Wk N` + phase + THIS-WK tag + chevron pinned right; line 2 = the 7 day glyphs as a
   `repeat(7,1fr)` grid + the km value right-aligned), drop the `minWidth` floors under the phone
   tier, and add `overflow:hidden` to the button as a guard.
   Pull one more one-liner forward with it, because it is the *other* frame break and the new
   360px assertions depend on it: `.chart-grid`'s `minmax(340px,1fr)` floor exceeds the content box
   below 372px → `minmax(min(340px,100%),1fr)`, which fixes 320px too.
2. **Make the gate data-independent.** Commit a small deterministic fixture data dir (a `blockLens`
   with long week labels, an insights block, a 3-run archive — `test_progress_page.mjs` and
   `test_block_section.mjs` already build theirs with `mkdtemp` + `DatabaseSync`) and default
   `layout` mode to it, so `#sec-records` / `#sec-yoy` move out of `PROGRESS_OPTIONAL` into hard
   assertions.
3. **Add a runner and CI.** `pnpm test` and `pnpm test:layout` scripts, and a CI job that runs both
   before `build-and-push` (needs `pnpm exec playwright install chromium`).
4. **Extend coverage where the refactor lands.** Add `/course` to style-audit's page list (it is
   loaded at *no* width today); extend the width loop to `[1920, 1600, 1200, 768, 390, 360]`; add
   `test_mobile_pages.mjs` loading all six routes at 360/390, asserting no overflow, no page errors
   and key content present.
5. **Close two harness holes.** `style-audit diff` can never fail (`code` is only assigned in the
   `layout` branch). `TOPBAR_PARITY` asserts nothing when a selector is missing on *both* pages
   (`a` and `b` are both `undefined`, `ok` is true, 44 green lines) — which is exactly the failure
   mode of renaming `header.topbar` during this work. Add a presence guard.
6. **Make FAIL output diagnostic.** Print the offending leaf via the clipping-aware walk, not just
   the number.

**Exit criterion for Move 0:** `pnpm test` and `pnpm test:layout` both green against real data, at
the widths asserted today. The *new* phone-width assertions in `test_mobile_pages.mjs` (44px targets,
11px type floor) are **authored in Move 0 but expected to fail until the moves that satisfy them
land** — they are the specification of done, not a gate on Move 0. Keep them in a clearly-marked
pending block that flips to enforcing at Move 6, rather than writing a weak assertion that passes
today and never catches anything.

### Move 1 — Own the frame

The architectural unlock. Nothing else in this design is reachable from CSS until this lands.

- **`applyThemeVars(name, el = document.documentElement)`** in `topbar.js`, writing the 27
  `THEMES[name]` entries onto the element's style. Called at module load from `initialTheme()` and
  inside `persistTheme()`. Every page already calls `persistTheme(name)` in its `setTheme`, so this
  is **zero page edits**. Verified necessary: without re-application the hoisted vars go stale
  (after picking `sunset`, the themed div read `#FF7A3D` while `:root` still read `#E8472B`).
- **`body{background:var(--bg)}`** replacing the hardcoded `#0E0F12` in all six helmets — safe only
  once the vars are on `:root`.
- **`<title>` per page** (six one-line edits; `document.title` is `""` on every page today), and
  promote the existing per-page label to an `<h1>` — there are zero `h1` elements in the mounted
  tree.
- **`viewport-fit=cover`** on the six viewport metas. Unavoidably per-file: the meta is parsed
  before any script, so `topbar.js` cannot inject it in time for first layout. Verified today
  `env(safe-area-inset-bottom)` resolves to `0px` while `CSS.supports` is true — the page simply
  never opts in.
- **`.app-root` class** on the root div in all six `render()` returns, moving `padding` / `minHeight`
  out of `rootStyle` into `dashboard.css`, so the phone override needs no `!important` and
  `minHeight` can become `100dvh` with a `100vh` fallback.
- **Publish the chrome contract** as tokens, so every consumer reads one source of truth:
  ```css
  :root { --tabbar-h: 0px; --safe-b: env(safe-area-inset-bottom, 0px); }
  @media (max-width: 700px) { :root { --tabbar-h: calc(56px + var(--safe-b)); } }
  ```
  `.cmp-tray` becomes `bottom: calc(var(--sp-3) + var(--tabbar-h))` — measured today it sits at
  `bottom:12px`, exactly where the bar goes.
- **Reconcile the container caps.** Two pages cap at 1340px, four at 1100px, with no stated reason,
  so the chrome changes width as you navigate. One `.page-shell` class; at ≥1600px it opens up.
- **One focus-visible rule.** Today only `.chart-svg` and `.arch-search` have one; every topbar
  control shows the UA ring at `rgb(16,16,16)` against a `rgb(14,15,18)` background — invisible.

### Move 2 — Persistent chrome + the PWA shell

**The bottom tab bar is injected, not authored.** Verified end to end against the live server on
four pages: a `<nav class="tabbar">` appended to `document.body`, built by mirroring the page's own
rendered nav. **Zero edits to the six duplicated headers.** Measured result: header 122→62px, first
content top 168→**96px**, each tab **97.5×56px = 3.6× today's nav-link area**, bar at y=787..844,
zero page errors.

New in `topbar.js`, keeping the module's pure-function style so `test_topbar.mjs` can cover the
logic in Node:

```js
export const PHONE_MAX = 700;
export function applyThemeVars(name, el)   // Move 1
export function tabModel(entries)          // PURE: [{href,label,current}] -> tab descriptors
function mountTabBar(doc)                  // mirrors #dc-root nav, re-runs from a MutationObserver
```

Rules the experiments proved load-bearing: scope the mirror to `#dc-root`; copy `a.href` absolute;
give the bar a **different** `aria-label` than `"Pages"` (two landmarks with one name is an a11y
smell *and* `test_course_page.mjs:211` asserts over `nav[aria-label="Pages"] a`); the bar lives
outside the themed root so it needs its own `:focus-visible` ring off the hoisted `:root` vars.

**Tab icons are CSS `mask-image` with an inline `data:` URI**, coloured by `background-color:
currentColor`. This is decisive, not a choice left open: a `mask-image` creates **no `<svg>`
element**, so `test_course_page.mjs`'s document-wide `querySelectorAll("svg").length === 0` stays
green untouched; a `data:` URI contacts no origin, so `test_offline.mjs` stays green; and unlike a
text glyph it renders identically across platforms and inherits the theme accent for free.

**The header becomes a slim sticky bar in pure CSS** — no new markup. Under the phone tier:
`position:sticky; top:0; z-index:50; flex-wrap:nowrap`, its nav pill `display:none`, brand + the
per-page label + a single ≥44px overflow button that opens sync and theme in a sheet. Two details
the prototype exposed: the greeting block is 306.7px wide at 360 and must truncate
(`min-width:0; overflow:hidden; text-overflow:ellipsis`) or it forces the actions off-screen under
`nowrap`; and the header needs `margin-inline: calc(-1 * clamp(16px,4vw,40px))` with matching
padding for a true full-bleed background, or content scrolls visibly through the 16px gutters.

**PWA shell.** `serve.mjs` MIME map gains `'.webmanifest': 'application/manifest+json; charset=utf-8'`
(verified: unlisted extensions fall back to `application/octet-stream`). Icons go under
`/vendor/icons/`, which already gets the 1-year immutable `Cache-Control`. Root
`manifest.webmanifest` with a **relative `start_url: './'`**, `display: standalone`, and
`theme_color` kept in sync with `THEMES[name].bg` by `topbar.js`. `<link rel=manifest>` +
`apple-touch-icon` are authored in each real `<head>` — technically injectable, but head-authored is
the honest, testable form. Icons must ship in the Docker image.

**Swipe** is a passive, `touchstart`-anchored guard — ~45 lines, three listeners, all
`{ passive: true }` so the handler *can never* `preventDefault` and therefore can never break native
scrolling or pinch-zoom. It bails when: `touches.length !== 1`; a selection is active; or any
ancestor up to `<body>` is an `svg` / inside an `svg` / a form field / carries `data-no-swipe` / has
a non-`auto` `touch-action` / satisfies `scrollWidth > clientWidth + 1 && overflow-x is auto|scroll`.
It disarms as soon as `|dy| > 8 && |dy| > |dx|`; it locks horizontal only at
`|dx| > 12 && |dx| > 2*|dy|`; it navigates at `touchend` only past 25% of viewport width or
0.5 px/ms. The decision function was tested against real elements on the live pages: it correctly
refused inside every `svg.chart-svg`, its hit-band rects, the readiness ring, both horizontal
scrollers and the search input, and armed on plain card content. **Targets come from
`navModel(...).map(n => n.href)`, so swipe order and tab order can never disagree.** Because it is
passive there is no rubber-band follow — the page changes at `touchend`. Polish is free via
`@view-transition { navigation: auto }` (support verified): these are full document navigations,
so there is no router to build.

### Move 3 — The sheet layer

One shared `openSheet({ title, node })` in `topbar.js`, appended at body level above the tab bar
(z-index 70; the only competing z-indexes in the whole codebase are 5 and 6). Focus-trapped, closes
on Escape / backdrop tap / downward drag reusing the swipe guard's touch logic, with
`overscroll-behavior: contain` on its scroll region so a fling inside cannot chain to the page
behind. **Caveat to honour:** the cockpit and progress root divs carry `onClick="{{ onDismiss }}"`,
which dismisses pinned chart popovers; a tap inside a body-level sheet does not bubble there, so
`openSheet` calls `onDismiss` explicitly.

It becomes the destination for everything currently dumped inline:

- **Un-gate `.card--pin .pin-scroll`** from `min-width:901px` so containment exists at every width
  (keep the absolute `inset:0` layout desktop-only). This alone stops the 2,889px tablet stretch.
- **Coach note:** split on its own `----` / double-newline separators into an array in
  `renderVals()` and render via `<sc-for>` so paragraphs exist at all — this fixes desktop
  legibility too. On phones show the headline plus ~4 lines with a real "Read the full note"
  control opening the sheet.
- **Coach log:** newest 1–2 entries collapsed, full timeline behind a "Plan adjustments" sheet. The
  entry list is already an `sc-for` over `coachLog`, so a `visibleLog` / `fullLog` split needs no
  new runtime feature.
- **`#drill-panel`** (progress's evidence panel) is *restyled* as a sheet below 700px — same id,
  same children, `left:0;right:0;bottom:0;width:100%`, `max-height:75dvh`. It already stops click
  propagation and handles Escape, so the state machine transfers unchanged. Today it opens with its
  top at y=751 in an 844px viewport — 343px below the fold, and nothing scrolls.
- **Progress's week drill**, which also removes the accordion's jump-scroll problem.
- **Hover-only content.** 52 information-carrying `title` attributes on non-interactive elements
  with no `tabindex` and no `aria-label` (9 phase-strip segments, 43 day glyphs — which are also
  `aria-hidden="true"`, so screen readers get nothing either). Day statuses fold into the week row's
  `aria-label`; the phase strip becomes real buttons; the `insufficient data` reason becomes a
  button opening the sheet.
- **Fix the readiness ring** while here: delete the two SVG `<text>` nodes and centre an HTML block
  inside the existing `position:relative` wrapper — the same pattern `chart-view.js` already uses
  for all chart text.

### Move 4 — Size- and pointer-aware charts

`chart-core.js` is **already width-aware** — run directly in node at `frame.w=324` it emits 3 x-ticks
instead of 10, and `multiTrackSpec` emits 3 instead of 7. It is simply being fed a constant. So the
fix is a divisor, not a rewrite:

- Add optional **`frame.cssW`** (measured CSS px) to `buildSpec` and `sharedX.cssW` to
  `multiTrackSpec`; derive `k = frame.cssW ? w / frame.cssW : 1` once, and divide by `k` at every
  place a px threshold is compared: `chart-core.js:316` (`plot.w/70`), `:331` (`plot.w/80`),
  `:324`/`:338` (`thinLabels`), `:580` (the 44-unit month-tick gap), `:472` (`placeAnnotations`).
  **Desktop output is unchanged** — verified arithmetically: `min(6,…)` binds once `plot.w ≥ 480`
  and `min(7,…)` once `plot.w ≥ 560`; desktop renders at 1022–1066 CSS px, so the caps still bind.
- **Constant-px y gutter.** `chart-view.js:70` emits `calc(<percentage> - 5px)`, so the label column
  is 81.7px at 1440 and **22.5px at 360** while the font stays 9.5px — tick text is painted into the
  plot. With `cssW` present, make the gutter a constant ~46–52 CSS px at every viewport.
- **The CADENCE collision** is two composing bugs. Vertically, `chart-core.js` reserves 10 *viewBox*
  units of headroom in `pad.t` but `chart-view.js:83` places the label at
  `calc(<percentage of height> - 9px)` with `translateY(-100%)` — different unit systems, so the
  reservation never holds. Fix at the source by placing the label *inside* the frame
  (`top: py(plot.y - 10)`, drop the transform); this also fixes desktop's `bpm`-over-`HEART RATE`.
  On phones, promote the unit out of the chart into the track caption entirely.
- **A real touch path.** Add `onPointerDown` (setPointerCapture + the same
  `(clientX - r.left) / r.width * W` math already at `chart-view.js:235`), `onPointerMove` (scrub),
  `onPointerUp`/`onPointerCancel`. **Gate the whole block on `e.pointerType !== "mouse"`** so the
  existing mouse handlers remain the only desktop path. Add `touch-action: pan-y` so vertical
  scrolling still works while horizontal is claimed locally.
- **Hit bands.** Widening them is impossible — `bandRects` tiles the full width by construction. On
  phones switch these charts to the engine's *other* primitive: `crosshairAt` (`chart-core.js:598`)
  snaps to the nearest sample by bisection regardless of spacing, which is what the run page already
  uses for 1,673 samples. Tap anywhere, get the nearest point.
- **Never move the chart under the finger.** Reserve the readout row unconditionally with em-dash
  placeholders (exactly as `compare.dc.html` already documents), then on phones render it as a
  fixed bar at `bottom: calc(var(--tabbar-h))` that appears only while a crosshair is placed. Today
  a single tap shifts the run's track stack **104px** down, and tapping the bottom track puts the
  answer **186px above the viewport**.
- **Route the pinned card into the sheet on phones** rather than patching the two-tap-through-a-
  re-render dance that makes chart-drill unreachable on touch; the drill becomes a real ≥44px button
  calling `hover.drill.action()` directly.
- **Phone chart typography and density:** `.chart-ytick` / `.chart-xtick` / `.chart-flag` → **11px**
  (11px is the floor everywhere, with no exceptions — the flags can afford it because the lane fix
  below stops them overlapping);
  emit the legend **once** per stack instead of per track (measured 136px of duplicated text on
  `/compare`); make `placeAnnotations` measure the label's projected right edge instead of its
  anchor, in CSS px (today `MILE PB` and `10K PB` overprint by 34.3px of a 39px label — at *every*
  width); default each chart to the **narrowest** useful scope on phones rather than `all`, keeping
  `all` one tap away.

### Move 5 — Re-compose the dense surfaces

Each of these needs a real phone composition, not a tuned breakpoint. `<sc-if>` makes them forks
rather than duplicate-and-hide.

- **Archive** — the worst page. Today's phone rule (`display:block` + `[data-label]::before`) is not
  a card list; it is 50 rows of run-together text with 59 em-dash placeholders. Become real
  two-line cards: primary line (date · name · headline metric), secondary line (chips), the whole
  row one ≥56px target. The 18×18px compare toggle **physically overlaps the run name on 15 of 18
  rows at 360px**, and a tap 14px off navigates away and destroys the selection — move it to a
  dedicated ≥44px leading control, and preserve pagination + scroll + selection across
  back-navigation. Make the Compare button honestly disabled. Raise the search input off 12px (iOS
  zooms the page on focus below 16px). Give the tray safe-area padding and a sane multi-line state.
- **Compare** — summary headers truncate to `"Lein…"`, making every run unidentifiable, and at four
  runs the numbers collide in 34px columns while split bars collapse to 0.5px. Re-compose as **one
  lane per run** (a stacked card per run for the summary; per-kilometre rows for splits).
- **Progress** — `.block-week` (Move 0) and `.block-day` as a stacked card; the records wall is 49%
  unreachable with no affordance, so on phones it becomes one card per distance with the by-year
  rows behind a disclosure; `.section-head`'s rule measures 0px and headings wrap — wrap the meta to
  its own line. (`.chart-grid`'s floor is fixed in Move 0, since the 360px assertions depend on it.)
- **Run** — give `.run-lower` explicit mobile `order:` so the interval lens (the page's whole point)
  is not fifth, below the route and best-efforts, purely because the desktop grid's source order is
  inherited. **Verified 2026-08-02 against real lap data** (local archive refreshed from a NUC
  snapshot — schema 14, 171 `run_intervals`): on the 5×1 km run `23543309396` at 390px the rep card
  sits 5th at y=1765 of a 2393px document, and the rep row's deviation bar — the whole point of the
  lens — has a **6.0px track at 360px** with 0.0–3.0px of ink (36px at 390, 73.6px at 430, 275px at
  1440). `run.dc.html`'s helmet already carries a component-scoped `@media (max-width:430px)` block
  compressing the five fixed columns; it is not enough. Target order: reps → splits → route → bests.
- **Course** — the elevation crosshair is mouse-only (fixed by Move 4); 22 numeric rows become a
  shape plus the few decisions that matter, with sticky table headers.
- **Cockpit** — the composition that turns 18.3 screens into ~4.5: screen 1 a merged *today* card
  (countdown + readiness *with its number restored* + coach headline + today's agenda); screen 2
  this-week with the block strip as a horizontal snap rail acting as the week switcher (~150px
  instead of ~1,000px, and it *preserves* the comparison that stacking destroys); screen 3 KPIs
  2-up then the charts as one horizontally-paged carousel; screen 4 recent activities with sheets.
  Every rail sets `overscroll-behavior-x: contain` and `touch-action` so it claims the horizontal
  axis locally and the swipe guard stays out of its way.
- **Discoverability** — every horizontal scroller gets an edge fade that paints only while
  `scrollWidth > clientWidth`, plus scroll-snap. The heatmap additionally opens on the *oldest* half
  of the year; it should open on today.

### Move 6 — The phone token tier

One `@media (max-width:700px)` block rather than dozens of per-use edits: raise `--fs-2xs` / `--fs-xs`
/ `--fs-sm` to a 11/12/13px floor, and give `.scope-chip`, `.wk-back`, `.cmp-go`, `.cmp-toggle`,
`.block-week` and the archive row a **44px minimum target**. Desktop rules are untouched. Add
`:active` feedback — today no control except two has any, so every tap feels dead. Replace
hover-instructing copy ("hover a month…", "click a time…") with device-neutral verbs.

### Move 7 — The wide tier

At ≥1600px the container has been capped at 1340px (or 1100px on four pages), leaving **580px of
dead gutter at 1920 and 1220px at 2560**, while the chart y-gutter balloons to 81.7px of empty space
and the tick text stays 9.5px. Raise the cap to a clamp such as `min(1600px, 92vw)`, let the topbar
frame the display, and use the reclaimed width for genuinely denser composition rather than wider
whitespace. `.chart-grid`'s `auto-fit` already turns extra width into more columns for free.

---

## 5. Testing strategy

Evidence before assertions, at every stage:

1. **`pnpm test`** — all 27 `test_*.mjs`. Current baseline: **27/27 pass** (~26s wall clock).
2. **`pnpm test:layout`** — `tools/style-audit.mjs layout` against the committed fixture, extended
   to `[1920, 1600, 1200, 768, 390, 360]` and to `/course`. Currently red; green from Move 0 onward.
3. **`test_mobile_pages.mjs`** (new) — all six routes at 360/390: no document overflow, no page
   errors, key content present, **no interactive element under 44px**, **no text under 11px**.
4. **`test_offline.mjs`** extended with a positive manifest/icon assertion (headless never fetches
   them lazily) and a source scan widened to the manifest, `archive`/`compare`/`course` and
   `topbar.js`.
5. **Visual diff** — the slice harness used for this audit, re-run per stage at 360/390/768/1440/1920.
6. **Desktop non-regression** — `style-audit baseline` before Move 1, `style-audit diff` after each
   move; the chart `k` divisor is expected to produce **zero** desktop change.
7. **NUC verification** — deploy and confirm on the real phone: install to home screen, safe-area
   clearance, tab bar, sheets, chart scrubbing, and that the course basemap tiles render (schema 14,
   208 tiles) where they cannot locally.

---

## 6. Out of scope

- **Offline service worker.** Explicitly declined: it adds cache-invalidation to the Docker deploy,
  the one genuinely risky item. The PWA ships installable but network-backed.
- **Any change to `support.js`**, the data contract, the sync, or the lens engines.
- **Re-pulling from Claude Design** — the local `.dc.html` files are the source of truth.
- **Fixing the course basemap 404s** — investigated, not a bug (local archive gap).
- **Deduplicating the six topbar copies.** They have drifted into five variants, and the audit
  recorded the differences, but consolidating them is a separate refactor. This design deliberately
  *avoids* needing it, by injecting the bar instead of authoring it six times.

## 7. Risks

| Risk | Mitigation |
|---|---|
| The injected tab bar is the load-bearing bet | Already prototyped end to end on four live pages, incl. theme changes, reconciliation survival and paint timing. Fallback: author it per page inside the themed root, where `position:fixed` is verified safe. |
| Hoisting theme vars to `:root` changes global cascade | The vars stay on the root div *as well*; `:root` is additive. `style-audit diff` catches any computed-style change. |
| The chart `k` divisor silently alters desktop | Verified arithmetically that tick caps still bind at desktop widths; `style-audit diff` + the chart test suites (`test_chart_core.mjs`, `test_chart_view.mjs`) gate it. |
| Six-file edits drift again | Every per-file edit in this design is a **one-liner** (`<title>`, viewport meta, body background, root class, manifest link). All behaviour lands in `topbar.js`/`dashboard.css`. |
| Max's instance differs (no course, possibly no archive) | The tab bar is driven by `navModel(page,{archive,course})`, which already yields 2/3/4 entries; `test_topbar.mjs` covers all three shapes. |
| ~~Rep-table measurements are synthetic~~ | **Retired.** Local archive refreshed from a consistent NUC snapshot; both claims re-measured on real lap data and confirmed. |
