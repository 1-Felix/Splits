# Make the dashboard mobile-native

## Why

The 2026-06-29 styling refactor made SPLITS **fit** a phone; nothing has ever made it **compose**
for one. Two years of feature work then landed on a layout system whose entire phone story is six
grid overrides at `max-width:560px`. An exhaustive audit on 2026-08-02 — six per-page auditors plus
three cross-cutting ones, run live at 360/390/768/1440/1920 — returned **145 findings, 55 critical
or high**.

The cockpit is **18.3 screens tall on a phone** against 2.5 on desktop, because 69.9% of it is two
coach text blocks that lose their `.pin-scroll` containment below 901px. **Nothing on any page is
`sticky` or `fixed`**, so across a 15,456px document there is no way to know where you are or to go
anywhere. **Not one interactive control in the entire app reaches 44px** — `/archive` has 53 under
it, including an 18px compare toggle that physically overlaps the run name on 15 of 18 rows and,
when missed by 14px, navigates away and destroys the selection. The chart engine has **no touch
path at all**: a tap works only via synthesised mouse events, a drag produces zero events, and
chart-drill is provably dead on touch.

Three defects are not mobile-specific and are fixed here because they are wrong at every width: the
**readiness ring has never displayed its score** (SVG `<text>` cannot render the runtime's
interpolation span — both nodes measure 0×0), the **coach note is one unbroken 5,503-character text
node**, and **`tools/style-audit.mjs layout` is already red** — and green against an empty data dir,
so the one responsive gate proves nothing.

## What Changes

- **A persistent chrome.** A fixed bottom tab bar in thumb reach plus a slim sticky header, under a
  new 700px phone tier. The bar is *injected* from `topbar.js` by mirroring the page's own rendered
  nav — **zero edits to the six duplicated page headers**, and tab availability plus `aria-current`
  are correct on every instance for free, including Max's.
- **An installable PWA shell** — manifest, maskable icons, `theme-color` synced to the active theme,
  `viewport-fit=cover` and a published `--tabbar-h` / safe-area contract. No service worker: the app
  ships installable but network-backed.
- **A shared sheet layer.** One `openSheet()` becomes the destination for long-form coach text, the
  progress drill panel, per-day plan detail, chart readouts and the 52 information-carrying `title`
  tooltips that touch can never surface. This is what makes full content parity survivable: the
  cockpit goes **18.3 → ~4.5 screens with nothing deleted**.
- **A size- and pointer-aware chart engine.** Every call site hard-codes `frame:{w:600}` and the SVG
  is then stretched to 0.49×, so tick counts, gutters, hit bands and annotation lanes are all decided
  in 600-unit space. A `frame.cssW` divisor plus `onPointerDown/Move/Up` gated on
  `pointerType !== "mouse"` retires ~8 separately-reported defects across four pages at once, with
  desktop output unchanged.
- **Re-composed dense surfaces** — archive rows become real cards instead of `[data-label]` text
  soup, comparison becomes one lane per run instead of `"Lein…"` truncation, the block-week row
  becomes a two-line grid, the records wall stops hiding 49% of itself.
- **A phone token tier** — a 44px target floor and an 11px type floor in one media query, plus
  `:active` feedback and device-neutral copy (the app currently instructs the reader to *hover*).
- **A wide-screen tier at ≥1600px** — the container has been capped at 1340px (1100px on four
  pages), leaving 580px of dead gutter at 1920 and 1220px at 2560.
- **A test runner and CI.** There is no `pnpm test` and no CI job that runs tests; 27 files are
  invoked by hand. Add the scripts, a deterministic fixture so the layout gate stops depending on
  live data, phone-width coverage, and a CI job that runs both before the image is built.
- **Own the frame** (the prerequisite for all of the above): hoist the 27 theme custom properties to
  `:root`, replace the six hardcoded `body{background:#0E0F12}` declarations that stay black under
  the light theme, add the missing `<title>` on all six pages, and move the container cap and root
  padding out of inline styles into classes so CSS can reach them at all.

Not breaking: every route, URL contract, data file and API stays as it is.

## Capabilities

### New Capabilities

- `mobile-chrome`: persistent navigation chrome (sticky header + fixed bottom tab bar), the
  safe-area and `--tabbar-h` contract, the installable PWA shell, the shared bottom-sheet layer, and
  the gesture-arbitration rules that let a page swipe coexist with charts, rails and scrollers.
- `responsive-layout`: the breakpoint tiers and the layout contracts that hold across every page —
  minimum touch-target size, minimum type size, horizontal-scroller discoverability, the rule that a
  dense surface gets a phone *composition* rather than a squeeze, and the wide-screen tier.

### Modified Capabilities

- `chart-engine`: charts must make density decisions against their **rendered CSS width**, not a
  hard-coded 600-unit frame; and the crosshair must have a real pointer/touch path, not rely on
  synthesised mouse events.
- `chart-drill`: "a pinned reading drills down to its evidence" is currently false on touch — the
  drill needs a touch-reachable affordance.
- `live-dashboard`: the readiness card must actually display its score and status; the cockpit needs
  a phone composition, and long-form coach content must stay contained at every width.
- `progress-views`: the records wall must be fully reachable on a phone (49% is unreachable today
  with no affordance), and the drill panel must open where it can be read.
- `archive-browser`: a run row must be a single unambiguous target, and returning from a run must
  preserve pagination, scroll position and comparison selection.
- `run-detail`: the crosshair readout must be visible when the crosshair is placed, and placing it
  must not move the chart under the finger.
- `run-comparison`: compared runs must stay identifiable — summary headers currently truncate every
  name to `"Lein…"`.
- `course-lens`: the course surface must be inspectable by touch; the elevation crosshair is
  mouse-only today.
- `containerized-deployment`: the image must ship the PWA assets and the server must serve a
  manifest with the correct media type.

## Impact

- **Frontend:** `dashboard.css` (new chrome, sheet and tier layers), `topbar.js` (theme-var hoist,
  tab bar, sheet layer, swipe guard), all six `.dc.html` files (one-line edits each — `<title>`,
  viewport meta, body background, root class, manifest link — plus per-page composition forks using
  `<sc-if>`, which the audit confirmed **is** supported at `support.js:544` and already used 14×).
- **Chart engine:** `chart-core.js` (a `cssW`-derived divisor at every px-threshold comparison),
  `chart-view.js` (constant-px y gutter, in-frame unit label, pointer handlers).
- **Server & packaging:** `serve.mjs` (`.webmanifest` MIME, icon cache headers), `Dockerfile` (ship
  `manifest.webmanifest` and `vendor/icons/`).
- **Tests & CI:** `package.json` (`test`, `test:layout`), `tools/style-audit.mjs` (fixture data dir,
  `/course`, wider width sweep, diagnostic FAIL output, two harness holes closed), a new
  `test_mobile_pages.mjs`, and `.github/workflows/docker-publish.yml` (run the suite before build).
- **Untouched:** `support.js`, the data contract, the sync, every lens engine, all API routes.
- **Deploy:** unchanged path — push `main` → CI builds `:latest` → `docker compose pull && up -d`
  on the NUC, verified on both the `splits` and `splits-max` instances.
