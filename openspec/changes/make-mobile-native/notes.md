# make-mobile-native — implementation notes

Implemented 2026-08-02/03. Every task in `tasks.md` is checked except **5.4**,
which was deliberately not shipped (see *Deviations* below).

## What the numbers say

Measured against the committed fixture (`fixtures/layout/`) at 390×844, which
is deliberately hostile: a block lens whose week labels run to `Wk 13 · deload`,
a coach note that is one 11-sentence text node with no newline in it, a 9-entry
coach log, and a three-run archive with a lap-backed 5×1 km rep document.

| | before | after |
|---|---|---|
| cockpit height at 390px | **18.3** viewport heights | **4.9** |
| `/progress` document width at 390px | **457px** (overflowing) | **390px** |
| `/progress` with a block week **expanded** | 517px (never measured before) | 390px |
| rep card depth on `/run/:id` at 390px | 5th card, **74%** of the document | **37%**, above the route |
| rep deviation-bar track at 360px | **6.0px** (filled 0.0–3.0px) | full card width, own line |
| controls under 44×44 at 390px, six pages | 53 on `/archive` alone | **0** (enforced) |
| rendered text under 11px at 390px, six pages | ~40 sites (`--fs-2xs` was 10px) | **0** (enforced) |
| readiness score displayed | **never**, at any width | yes, at every width |
| y-axis gutter at 360px | 22.5 CSS px against a 9.5px label | ~44 CSS px against an 11px label |
| `/compare` at 390px | every run truncated to `"Lein…"` | one lane per run, names in full |
| legend on a `/compare` stack | 4× the same two runs | once |
| suites run by `pnpm test` | there was no `pnpm test` | **28/28** |
| CI runs the suite before publishing | no | yes |

Full-page slices at 360/390/768/1440/1920 for all six pages:
`node tools/slices.mjs <dir>`. Every page fits its viewport at every width.

## Deviations

**5.4 `@view-transition { navigation: auto }` — not shipped, deliberately.**
The design expected it to be free polish. It is not. With it enabled, a
navigation that INTERRUPTS a still-loading document leaves the incoming
document permanently render-blocked in Chromium. Measured on the cockpit after
a click-navigation to `/run/:id` was interrupted by a second navigation: the
DOM was complete (365 heatmap rects present, the trajectory svg present) and
`requestAnimationFrame` never fired again — still nothing 18 seconds later. It
took four browser suites down with it, but the reason they went down is a
frozen page, not a test artefact: interrupting one's own navigation is exactly
what a swipe followed by a tap produces. The reasoning is recorded in
`dashboard.css` where the rule would have gone. Revisit if Chromium bounds the
render block.

**7.7 — the pinned reading is not itself routed into a sheet.** The spec's
requirement is that the drill "SHALL be a target meeting the minimum touch size
whose activation invokes the drill directly, rather than depending on a second
activation surviving a re-render". That is what shipped: the drill row of a
pinned card is a real `<button>` (44px on a phone) calling
`hover.drill.action()` directly. The *evidence view* it opens — `#drill-panel`
— IS the bottom sheet (task 6.8). Routing the pinned reading itself into a
sheet would open a modal on every placed reading, covering the chart the finger
is scrubbing.

**8.11's chart carousel — not built, as the task's own instruction allows.**
"Build the rail first, then judge whether the chart carousel follows." The block
rail is built and works. The cockpit's chart set is four cards in a single
column at 390px, and putting them on a second horizontal gesture surface
directly below the block rail would make two adjacent horizontal tracks on one
screen. The cockpit is 4.9 screens without it, inside the under-6 budget the
spec asks for, so the carousel buys density the page no longer needs at the
cost of a gesture collision.

**The records FEED navigates to a year, not to a run.** Task 8.6 says "make the
records feed rows navigable like the wall cells". The wall's cells carry
`activityId`; `insights.recordsFeed` emits `{date, distance, oldSec, newSec}`
and no id at all. A `/run/:id` link would have been an invention, so a feed row
opens that year in the archive instead. The wall's cells still open the run.

## Tests changed, and why

- **`test_archive_page.mjs`** — `.arch-row > span:nth-child(2)` →
  `[data-label="date"]`. Child ORDER is a composition detail (the row is a card
  on a phone); the date cell's identity is the contract the assertion is about.
  Renamed *before* the rows were touched (task 8.1).
- **`test_run_page.mjs`** — waits for the desktop chart geometry to be back
  after the test resizes 390 → 1280, because charts now decide their density
  against the width they are rendered at. It waits for "not the narrow render",
  so the coordinate pinned afterwards still asserts.
- **`test_slim_render.mjs`** — settles on two identical text reads rather than
  reading immediately after its ready marker. The markers ("Avg run pace", the
  heatmap cells) are satisfied by the pages' built-in placeholder dataset too,
  so under load the absence assertions were racing the module graph. Not caused
  by this change; exposed by it.
- **`test_offline.mjs`** — the source scan strips `xmlns="http://www.w3.org/…"`
  before looking for absolute URLs (an XML namespace is an identifier, never a
  fetch) and now covers all six pages, `topbar.js` and the manifest instead of
  three pages and the stylesheet. It also gained a **positive** assertion:
  headless Chromium never fetches a manifest or icon lazily, so the manifest and
  every icon it names are requested explicitly, from inside the page, through
  the same interceptor that aborts foreign origins.
- **`tools/style-audit.mjs`** — `trackCount` reads `display` first, so a
  section that legitimately stops being a grid (the block rail) counts 0 rather
  than reporting a meaningless track. `/compare`'s legend rule became a STACK
  rule. Both harness holes from task 1.7 are closed: `diff` can now fail, and
  topbar parity asserts presence before equality.

## Load-bearing facts for whoever comes next

- **`--fs-2xs` is 11px below 700px and 10px above it.** That one token is what
  holds the type floor; ~40 surfaces read it. Do not add a hardcoded 10px.
- **The tab bar and the header's `⋯` control are appended to `document.body`,
  never into `#dc-root`.** React owns only `#dc-root`; nothing is ever inserted
  into a subtree it reconciles. The bar is rebuilt from a `MutationObserver`
  with a signature check, so a no-op re-render costs nothing.
- **Phone-only chrome is toggled with `display`, never `transform`/`opacity`.**
  Several desktop tests assert the ABSENCE of "Archive"/"Progress" via
  `body.innerText`; only `display:none`-family values are excluded from it.
- **`.topbar nav` and `.topbar-actions > *` need `!important`.** Every one of
  them carries an inline `display:flex` from its page's markup, and the six
  header copies are deliberately not rewritten by this change.
- **`chartCssWidth()` is derived, not measured** — from `.app-root`'s
  `clamp(16px,4vw,40px)` plus a card's 16px padding and 1px border. It returns
  the 324px the audit measured at 390. It returns null above the phone tier, and
  `frameScale` clamps k at 1, so desktop chart output is unchanged *by
  construction*: `test_chart_core.mjs` asserts the whole spec is deep-equal to
  the pre-change one at 1066px.
- **`sharedXScale` must be handed the same `cssW` as `multiTrackSpec`**, or the
  page's bisection measures a plot the tracks did not draw.
- **The layout gate runs against `fixtures/layout/`, not live telemetry.**
  `--live` opts back in. It measures the phone tier at 390×844, not in a
  1600px-tall viewport that made every "is it in the viewport" claim trivially
  true.
