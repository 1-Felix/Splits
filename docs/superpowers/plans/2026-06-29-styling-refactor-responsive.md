# SPLITS Styling Refactor + Responsive — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the inline-style duplication in `Running Dashboard.dc.html` with a tokenized external stylesheet (`dashboard.css`: design tokens → semantic classes → responsive `@media`), preserving the desktop look except small reviewed token nudges, and making the dashboard reflow cleanly on tablet and phone.

**Architecture:** A new `dashboard.css` is linked from the helmet. Static design tokens live in `:root`; the existing per-theme color vars stay dynamic on the root div (`renderVals`, line 704) and are untouched. Repeated inline patterns become semantic classes; data-driven inline styles (`{{ d.bg }}`, `left:{{ cd.left }}`, etc.) stay inline. Layout becomes class-driven, so responsiveness is added last as `@media` blocks. A Playwright-based `tools/style-audit.mjs` harness gives computed-style parity diffs and responsive layout assertions.

**Tech Stack:** Plain CSS (no build step), the `dc-runtime` (`support.js`, generated — never edit), the Node static server `serve.mjs` (`pnpm dev`, port 8000), Playwright (new dev dependency) for computed-style verification, Node `.mjs` test scripts.

## Global Constraints

Copied from the spec (`docs/superpowers/specs/2026-06-29-styling-refactor-responsive-design.md`) and the user's global rules. Every task implicitly includes these.

- **Never edit `support.js`** — it is generated runtime.
- **Never re-pull from Claude Design** — the local `.dc.html` is the source of truth.
- **Never commit** `garmin-data.js`, `.env`, `.garmin_cache/`, `.garmin_tokens/` (gitignored). There are uncommitted edits in `plan-data.js` from prior work — **do not stage `plan-data.js`** in any commit here; stage only the files each task names.
- **Use `pnpm`, never `npm`.** New deps install at their latest version.
- **No TypeScript casting.** (Not applicable here — CSS/JS only.)
- **In `.dc.html` text, use literal Unicode** (`ä ö ü ß § é – · → ° ₂ × ⚡`), never `\uXXXX` escapes.
- **Commit messages:** no `Co-Authored-By`, no Claude attribution.
- **Data-driven inline styles stay inline.** A semantic class governs static structure; any property whose value contains `{{ … }}` interpolation stays inline on the element. Class + inline coexist (they govern different properties), so **no `!important` is ever needed**.
- **`class` works:** `support.js:398` maps `class` → `className`. `data-*` attributes pass through unchanged.
- **Breakpoints (desktop-first):** desktop `>900px` (base rules), tablet `@media (max-width:900px)`, phone `@media (max-width:560px)`.

### Token snap tables (normative)

Each existing raw value maps to exactly one token. Nudges are intentional and visually reviewed.

```
TYPE     9,9.5,10 → --fs-2xs(10) | 10.5,11 → --fs-xs(11) | 11.5,12 → --fs-sm(12) |
         12.5,13 → --fs-base(13) | 14,15 → --fs-md(15) | 16 → --fs-lg(16) |
         19,20,21,22 → --fs-xl(20) | 24 → --fs-2xl(24) | 30 → --fs-3xl(30) | 78 → --fs-display(78)
WEIGHT   400→--fw-normal 500→--fw-medium 600→--fw-semibold 700→--fw-bold 800→--fw-extrabold 900→--fw-black
SPACING  1 → --sp-px(1) | 2,3 → --sp-0(2) | 4,5 → --sp-1(4) | 6,7,8,9 → --sp-2(8) |
         10,11,12,13 → --sp-3(12) | 14,16,18 → --sp-4(16) | 20,22 → --sp-5(20) | 26 → --sp-6(24) | (32 → --sp-8)
RADIUS   3,4,5,6 → --r-sm(6) | 8,9,10 → --r-md(10) | 13,14,16 → --r-lg(14) | 99 → --r-pill(99)
SHADOW   0 6px 18px rgba(0,0,0,.30) → --shadow-pop
```

> **Spec refinement (flag to user):** the spec's spacing table had `2,3 → --sp-1(4)`. This plan adds a `--sp-0: 2px` half-step and maps `2,3 → --sp-0`, because a pure 4px grid would visibly loosen the dashboard's dense 2–3px micro-gaps. Everything else matches the spec. If the user prefers the strict 4px grid, drop `--sp-0` and remap `2,3 → --sp-1`.

> **Grid-gap exception (note):** the SPACING table governs *content* margins/padding. Layout-container `gap`s are chosen per-container for visual density and may take a tighter token than the generic nearest-snap — e.g. `.week-grid`'s original `gap:10px` became `--sp-2`(8px) for a snug day-card rhythm rather than the table's `--sp-3`(12px). These are deliberate, reviewed per-grid choices, not table violations.

### Section migration procedure (used by Tasks 3–8)

Each section-migration task follows the same recipe (its task body gives the concrete classes, elements, and expected values):

1. Add the section's class rules to `dashboard.css` (authored from current values via the snap tables).
2. In the markup, add the `class="…"` attribute to each named element and **delete only the now-duplicated static declarations** from its inline `style`. Keep every declaration whose value contains `{{ … }}`, plus `style-hover`/`style-focus-visible`/`tabIndex`/`role`/`aria-*`/`onKeyDown`/`data-*` attributes.
3. Verify desktop parity: `pnpm dev` running, then `node tools/style-audit.mjs read '<selector>' <props…>` — confirm each property computes to the expected token value (stated in the task).
4. `node tools/style-audit.mjs diff` — confirm no section-level grid change crept in (only the intended per-element nudges appear).
5. Visual review at desktop width: the section looks identical except the documented nudges.
6. Commit only `dashboard.css` and `Running Dashboard.dc.html`.

### Deviations from the spec's class list (intentional, DRY)

The spec §5 list is indicative. This plan folds/skips three entries to avoid thin abstractions:
- **`.stat` and `.chart-card` → `.card`.** Stat tiles and chart panels are the same surface as `.card` (panel/line/`--r-lg`/pad); they reuse `.card` (+ `.card-head/.card-title/.card-sub` for chart headers) rather than getting near-duplicate classes. Layout still gets `.stats-grid` / `.chart-grid`.
- **`.pill` skipped.** Its two uses (header sync status, coach focus chips) are visually different and not real duplication (the focus chips are already DRY via `<sc-for>`). Their styling stays inline, tokenized in place. Add a `.pill` later only if a third pill appears.

---

## Task 1: Link an external stylesheet + define tokens (prove the mechanism)

**Files:**
- Create: `dashboard.css`
- Modify: `Running Dashboard.dc.html` (helmet, lines 14–21; one element for the sentinel)

**Interfaces:**
- Produces: `dashboard.css` linked and applying; the full `:root` token block (consumed by every later task).

- [ ] **Step 1: Create `dashboard.css` with the token block + a sentinel rule**

```css
/* dashboard.css — SPLITS visual language: tokens → components → responsive.
   Loaded via the helmet <link>. Theme COLOR vars (--accent, --panel, …) are set
   dynamically on the root div by renderVals(); they are intentionally NOT here. */

:root {
  /* type */
  --fs-2xs: 10px; --fs-xs: 11px; --fs-sm: 12px; --fs-base: 13px; --fs-md: 15px;
  --fs-lg: 16px; --fs-xl: 20px; --fs-2xl: 24px; --fs-3xl: 30px; --fs-display: 78px;
  /* weight */
  --fw-normal: 400; --fw-medium: 500; --fw-semibold: 600;
  --fw-bold: 700; --fw-extrabold: 800; --fw-black: 900;
  /* spacing — 4px grid + a 2px half-step for dense micro-gaps */
  --sp-px: 1px; --sp-0: 2px; --sp-1: 4px; --sp-2: 8px; --sp-3: 12px;
  --sp-4: 16px; --sp-5: 20px; --sp-6: 24px; --sp-8: 32px;
  /* radius */
  --r-sm: 6px; --r-md: 10px; --r-lg: 14px; --r-pill: 99px;
  /* shadow */
  --shadow-pop: 0 6px 18px rgba(0,0,0,.30);
}

/* TASK-1 SENTINEL — remove at end of Task 1 */
.r-smoke { outline: 3px solid magenta; }
```

- [ ] **Step 2: Link the stylesheet from the helmet and add the sentinel class**

In `Running Dashboard.dc.html`, inside `<helmet>` add the link just before the existing `<style>` (line 14):

```html
<link rel="stylesheet" href="./dashboard.css">
```

Add `class="r-smoke"` to the outer container at line 26 (`<div style="max-width:1340px;margin:0 auto">` → `<div class="r-smoke" style="max-width:1340px;margin:0 auto">`).

- [ ] **Step 3: Verify the stylesheet applies**

Playwright isn't installed yet (Task 2), so verify with the already-available **chrome-devtools MCP** (no install): start `pnpm dev`, `navigate_page` to `http://localhost:8000/Running%20Dashboard.dc.html`, then `evaluate_script`:

```js
() => getComputedStyle(document.querySelector('.r-smoke')).outlineColor
```

Expected: `rgb(255, 0, 255)` → the external stylesheet loads and applies. (No MCP available? Defer this exact check to the end of Task 2 and run it via `tools/style-audit.mjs read '.r-smoke' outline-color`, treating the link as provisional until then.)

**Fallback (only if it did NOT apply):** move the `dashboard.css` contents into the existing helmet `<style>` block (lines 14–21), drop the `<link>`, and continue — every later task is unchanged except "add to `dashboard.css`" becomes "add to the helmet `<style>`".

- [ ] **Step 4: Remove the sentinel**

Delete the `.r-smoke` rule from `dashboard.css` and the `class="r-smoke"` from line 26.

- [ ] **Step 5: Commit**

```bash
git add dashboard.css "Running Dashboard.dc.html"
git commit -m "build: link external dashboard.css and define design tokens"
```

---

## Task 2: Style-audit harness + section anchors + baseline

**Files:**
- Modify: `package.json` (devDependency)
- Create: `tools/style-audit.mjs`, `tools/style-baseline.json` (generated)
- Modify: `Running Dashboard.dc.html` (add `id` anchors — additive, zero visual change)

**Interfaces:**
- Produces: `node tools/style-audit.mjs <baseline|diff|read|layout>` — the verification harness used by every later task. Stable selectors: `#sec-hero #sec-stats #sec-week1 #sec-week2 #sec-charts #sec-heat #sec-split #card-hero #card-ready`.

- [ ] **Step 1: Install Playwright**

```bash
pnpm add -D playwright
pnpm exec playwright install chromium
```

Expected: `playwright` appears under `devDependencies` in `package.json`; chromium downloads.

- [ ] **Step 2: Add `id` anchors to the section containers (additive only — no style change)**

In `Running Dashboard.dc.html`, add an `id` to each (do not touch `style`):
- line 54 `<section …1.55fr 1fr 1.4fr…>` → add `id="sec-hero"`
- line 57 countdown card `<div …linear-gradient…>` → add `id="card-hero"`
- line 91 readiness card `<div …padding:20px…>` → add `id="card-ready"`
- line 138 `<section …repeat(4,1fr)…>` → add `id="sec-stats"`
- line 160 `<section …repeat(7,1fr)…>` (this week) → add `id="sec-week1"`
- line 181 `<section …repeat(7,1fr)…>` (road block) → add `id="sec-week2"`
- line 234 `<section …auto-fit,minmax(340px…>` → add `id="sec-charts"`
- line 377 heatmap `<div …border-radius:14px;padding:18px;margin-bottom:14px>` → add `id="sec-heat"`
- line 405 `<section …1.6fr 1fr…>` → add `id="sec-split"`

- [ ] **Step 3: Write the harness `tools/style-audit.mjs`**

```js
// Computed-style audit for the SPLITS dashboard. Starts its own dev server on
// PORT 8123 (never clashes with `pnpm dev`) and drives headless chromium.
//
//   node tools/style-audit.mjs baseline                 → write tools/style-baseline.json (run once, pre-refactor)
//   node tools/style-audit.mjs diff                      → print computed-style changes vs baseline (desktop 1200)
//   node tools/style-audit.mjs read '<sel>' <prop...>    → print computed props for a selector (desktop 1200)
//   node tools/style-audit.mjs layout                    → assert the responsive layout map at 1200/768/390 (PASS/FAIL)
//
// Requires: pnpm add -D playwright && pnpm exec playwright install chromium

import { chromium } from "playwright";
import { readFile, writeFile } from "node:fs/promises";

process.env.PORT = process.env.AUDIT_PORT || "8123";
const PORT = process.env.PORT;
const PAGE = `http://localhost:${PORT}/Running%20Dashboard.dc.html`;
const BASELINE = new URL("./style-baseline.json", import.meta.url);

await import("../serve.mjs"); // side-effect: server.listen(PORT)

// Section-level selectors that exist throughout the refactor (stable ids).
const TRACK = {
  "#sec-hero":   ["display", "grid-template-columns", "gap"],
  "#sec-stats":  ["display", "grid-template-columns", "gap"],
  "#sec-week1":  ["display", "grid-template-columns", "gap"],
  "#sec-week2":  ["display", "grid-template-columns", "gap"],
  "#sec-charts": ["display", "grid-template-columns"],
  "#sec-split":  ["display", "grid-template-columns"],
  "#card-hero":  ["border-radius", "padding", "background-image"],
  "#card-ready": ["border-radius", "padding"],
};

// Expected grid track COUNTS per width. getComputedStyle resolves fr → px, so we
// count tracks, not template strings. "card" = not a grid (display != grid).
// ranges are [min,max] inclusive; numbers are exact.
const LAYOUT = {
  "#sec-hero":   { 1200: 3, 768: 2, 390: 1 },
  "#sec-stats":  { 1200: 4, 768: 2, 390: 2 },
  "#sec-week1":  { 1200: 7, 768: [2, 6], 390: 1 },
  "#sec-week2":  { 1200: 7, 768: [2, 6], 390: 1 },
  "#sec-charts": { 1200: [2, 4], 768: [1, 2], 390: 1 },
  "#sec-split":  { 1200: 2, 768: 1, 390: 1 },
};

function trackCount(v) {
  if (!v || v === "none") return 0;
  return v.trim().split(/\s+/).length;
}
function matchCount(actual, expected) {
  if (Array.isArray(expected)) return actual >= expected[0] && actual <= expected[1];
  return actual === expected;
}

async function read(page, sel, props) {
  return page.$eval(sel, (el, props) => {
    const cs = getComputedStyle(el);
    const out = {};
    for (const p of props) out[p] = cs.getPropertyValue(p).trim();
    return out;
  }, props).catch(() => null);
}

async function snapshot(page, width) {
  await page.setViewportSize({ width, height: 1600 });
  await page.goto(PAGE, { waitUntil: "networkidle" });
  await page.waitForSelector("#sec-hero");
  const out = {};
  for (const [sel, props] of Object.entries(TRACK)) out[sel] = await read(page, sel, props);
  return out;
}

const mode = process.argv[2] || "diff";
const browser = await chromium.launch();
const page = await browser.newPage();
let code = 0;

if (mode === "baseline") {
  const snap = await snapshot(page, 1200);
  await writeFile(BASELINE, JSON.stringify(snap, null, 2));
  console.log("baseline written:", BASELINE.pathname);
} else if (mode === "diff") {
  const base = JSON.parse(await readFile(BASELINE, "utf8"));
  const snap = await snapshot(page, 1200);
  let changed = 0;
  for (const sel of Object.keys(TRACK)) {
    for (const p of TRACK[sel]) {
      const a = base[sel]?.[p], b = snap[sel]?.[p];
      if (a !== b) { console.log(`Δ ${sel} { ${p}: ${a} → ${b} }`); changed++; }
    }
  }
  console.log(changed ? `${changed} change(s) — review against expected nudges.` : "no changes vs baseline.");
} else if (mode === "read") {
  const sel = process.argv[3];
  const props = process.argv.slice(4);
  await page.setViewportSize({ width: 1200, height: 1600 });
  await page.goto(PAGE, { waitUntil: "networkidle" });
  await page.waitForSelector("#sec-hero");
  console.log(sel, await read(page, sel, props));
} else if (mode === "layout") {
  for (const width of [1200, 768, 390]) {
    await page.setViewportSize({ width, height: 1600 });
    await page.goto(PAGE, { waitUntil: "networkidle" });
    await page.waitForSelector("#sec-hero");
    for (const [sel, byW] of Object.entries(LAYOUT)) {
      const v = await read(page, sel, ["grid-template-columns"]);
      const n = trackCount(v?.["grid-template-columns"]);
      const ok = matchCount(n, byW[width]);
      if (!ok) code = 1;
      console.log(`${ok ? "ok " : "FAIL"} ${width} ${sel} tracks=${n} expected=${JSON.stringify(byW[width])}`);
    }
    // phone-only component checks
    if (width === 390) {
      const head = await read(page, ".runs-head", ["display"]);
      const row = await read(page, ".runs-row", ["display"]);
      const headOk = !head || head.display === "none";
      const rowOk = !row || row.display !== "grid";
      if (!headOk || !rowOk) code = 1;
      console.log(`${headOk ? "ok " : "FAIL"} 390 .runs-head display=${head?.display} (expect none/absent)`);
      console.log(`${rowOk ? "ok " : "FAIL"} 390 .runs-row display=${row?.display} (expect not grid)`);
    }
  }
  console.log(code ? "LAYOUT: FAIL" : "LAYOUT: ALL PASS");
}

await browser.close();
process.exit(code);
```

- [ ] **Step 4: Capture the pre-refactor baseline and prove the harness**

```bash
node tools/style-audit.mjs baseline
node tools/style-audit.mjs diff
```

Expected: baseline written; `diff` prints `no changes vs baseline.` (nothing refactored yet). Spot-check a known original value:

```bash
node tools/style-audit.mjs read "#card-hero" border-radius padding
```

Expected: `{ border-radius: '16px', padding: '22px' }` (the original hero values — confirms the harness reads true computed styles).

- [ ] **Step 5: Commit**

```bash
git add package.json pnpm-lock.yaml tools/style-audit.mjs tools/style-baseline.json "Running Dashboard.dc.html"
git commit -m "test: add computed-style audit harness, section anchors, and baseline"
```

---

## Task 3: Core component classes + Hero migration

**Files:** `dashboard.css`, `Running Dashboard.dc.html` (lines 54–134)

**Interfaces:**
- Produces classes consumed everywhere later: `.card .card--hero .card--roomy .card-head .card-title .card-sub .eyebrow .metric .hero-grid`.

- [ ] **Step 1: Add the core classes to `dashboard.css`**

```css
/* ---- surfaces ---- */
.card        { background: var(--panel); border: 1px solid var(--line); border-radius: var(--r-lg); padding: var(--sp-4); }
.card--roomy { padding: var(--sp-5); }
.card--hero  { background: linear-gradient(150deg, var(--panel2), var(--panel)); padding: var(--sp-5); }

/* ---- card header pattern ---- */
.card-head  { display: flex; justify-content: space-between; align-items: flex-start; }
.card-title { font-size: var(--fs-base); font-weight: var(--fw-extrabold); }
.card-sub   { font-size: var(--fs-sm); color: var(--sub); font-weight: var(--fw-medium); margin-top: var(--sp-0); }

/* ---- small repeated text patterns ---- */
.eyebrow { font-size: var(--fs-xs); color: var(--sub); font-weight: var(--fw-bold); }  /* letter-spacing stays inline (expressive, per-use) */
.metric  { font-family: 'JetBrains Mono', monospace; font-weight: var(--fw-bold); }     /* size/color stay inline */

/* ---- hero layout ---- */
.hero-grid { display: grid; grid-template-columns: 1.55fr 1fr 1.4fr; gap: var(--sp-4); margin-bottom: var(--sp-4); }
```

- [ ] **Step 2: Apply classes to the hero and delete redundant inline**

- Line 54 `<section id="sec-hero" …>`: add `class="hero-grid"`; delete `display:grid;grid-template-columns:1.55fr 1fr 1.4fr;gap:14px;margin-bottom:14px` from inline (keep nothing — the class covers all of it; the `style` attribute can be removed if empty).
- Line 57 countdown `<div id="card-hero" …>`: add `class="card card--hero"`; delete `background:linear-gradient(150deg,var(--panel2),var(--panel));border:1px solid var(--line);border-radius:16px;padding:22px`. Keep `position:relative;overflow:hidden;display:flex;flex-direction:column;justify-content:space-between`.
- Line 91 readiness `<div id="card-ready" …>` and line 121 coach `<div …>`: add `class="card card--roomy"`; delete `background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:20px`. Keep `display:flex;flex-direction:column`.
- Eyebrows — lines 60 (`NEXT RACE`), 92 (`TODAY · READINESS`), 124 (`COACH`): add `class="eyebrow"`; delete `font-size:11px;color:var(--sub);font-weight:700`. Keep `letter-spacing:.18em` (60, 92) / `.16em` (124).
- Card-head rows — line 58 add `class="card-head"` delete `display:flex;justify-content:space-between;align-items:flex-start`. (The coach header line 122 differs — `align-items:center` — leave it inline; not the same pattern.)
- `.metric` — every mono value in the hero: lines 66, 71, 84, 85, 86, 109, 110, 111: add `class="metric"`; delete `font-family:'JetBrains Mono';font-weight:700`. Keep the per-element `font-size`/`color` but **swap raw px → token** per the snap table (e.g. line 66 `font-size:22px` → `font-size:var(--fs-xl)`; line 84/85/86 `font-size:16px` → `var(--fs-lg)`; line 109–111 `font-size:16px` → `var(--fs-lg)`). Line 71 day-count `font-size:78px` → `var(--fs-display)` (keep `font-weight:900` inline → it's `--fw-black`; you may tokenize or leave — leave the one-off `900` inline).
- Coach focus chips (line 131) and the rest of the hero's raw px: as you touch each line, swap raw font/spacing/radius px to tokens via the snap tables (e.g. `border-radius:99px` → `var(--r-pill)`, `margin-top:6px` → `var(--sp-2)`, `gap:14px` → `var(--sp-4)`). This is the per-section tokenization; the class extraction above handles the big duplicated blocks.

- [ ] **Step 3: Verify desktop parity**

```bash
node tools/style-audit.mjs read "#card-hero" border-radius padding background-image
node tools/style-audit.mjs read "#card-ready" border-radius padding
node tools/style-audit.mjs diff
```

Expected: `#card-hero` → `border-radius: 14px`, `padding: 20px`, `background-image` still the gradient. `#card-ready` → `14px` / `20px`. `diff` reports exactly: `#card-hero border-radius 16px→14px`, `padding 22px→20px`; `#card-ready border-radius 16px→14px`, `padding 20px→20px`(no change) — i.e. only the documented radius/padding nudges, and **`#sec-hero` grid unchanged (still 3 tracks)**.

- [ ] **Step 4: Visual review** at desktop — hero identical except the ~2px radius/padding tightening.

- [ ] **Step 5: Commit**

```bash
git add dashboard.css "Running Dashboard.dc.html"
git commit -m "refactor: tokenize hero section and add core component classes"
```

---

## Task 4: Unify the 10 floating data-point cards into `.pop`

**Files:** `dashboard.css`, `Running Dashboard.dc.html` (the 10 `data-card="…"` divs: lines 103, 226, 253, 278, 304, 328, 368, 396, 436, 452)

**Interfaces:** Produces `.pop` (the floating hover/tap card surface).

- [ ] **Step 1: Add `.pop` to `dashboard.css`**

```css
/* floating data-point card (hover/tap). position/left/top/transform stay inline (dynamic). */
.pop {
  background: var(--panel2); border: 1px solid var(--line); border-radius: var(--r-md);
  padding: var(--sp-2) var(--sp-2); font-size: var(--fs-xs); line-height: 1.35;
  white-space: nowrap; box-shadow: var(--shadow-pop); pointer-events: none;
}
```

> The originals are `border-radius:8px` (→ `--r-md` 10) and `padding:6px 9px` (→ `--sp-2` 8 / `--sp-2` 8). The two drill-down pops (lines 436, 452) use `padding:5px 8px` (→ also `--sp-2`) and `border-radius:8px`; `z-index:7` vs `6` stays inline. These are reviewed micro-nudges.

- [ ] **Step 2: Apply `.pop` to each floating card**

For each `data-card="…"` div, add `class="pop"` and delete `background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:6px 9px;font-size:11px;line-height:1.35;white-space:nowrap;box-shadow:0 6px 18px rgba(0,0,0,.30);pointer-events:none` (and the `padding:5px 8px;font-size:10.5px` variant on 436/452). **Keep** `position:absolute;left:{{ cd.left }};top:{{ cd.top }};transform:{{ cd.transform }};z-index:6` (or `7`).

- [ ] **Step 3: Verify**

```bash
node tools/style-audit.mjs diff
```

Expected: no section-level changes (pops aren't tracked selectors). Then visually trigger a card: with `pnpm dev`, hover/focus a chart and confirm the floating card still renders with the same look. (Optional scripted check: `node tools/style-audit.mjs read '[data-card="vo2"]' border-radius` only resolves while a card is open, so rely on visual here.)

- [ ] **Step 4: Commit**

```bash
git add dashboard.css "Running Dashboard.dc.html"
git commit -m "refactor: unify the 10 floating data-point cards into .pop"
```

---

## Task 5: Stat tiles (KPI section)

**Files:** `dashboard.css`, `Running Dashboard.dc.html` (lines 138–152)

**Interfaces:** Produces `.stats-grid`.

- [ ] **Step 1: Add to `dashboard.css`**

```css
.stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--sp-4); margin-bottom: var(--sp-5); }
```

- [ ] **Step 2: Apply classes + tokenize**

- Line 138 `<section id="sec-stats" …>`: add `class="stats-grid"`; delete `display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:22px`.
- Line 140 tile `<div … style-hover="border-color:var(--accent)">`: add `class="card"`; delete `background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px 16px 14px`. **Keep** `style-hover`. (The class gives `padding:16px` uniform — the `14px` bottom → `16px` nudge.)
- Line 142 label: add `class="eyebrow"`; delete `font-size:11px;color:var(--sub);font-weight:700`; keep `letter-spacing:.1em`.
- Line 146 value: add `class="metric"`; delete `font-family:'JetBrains Mono';font-weight:700`; change `font-size:30px` → `font-size:var(--fs-3xl)`; keep `letter-spacing:-.03em`.
- Lines 143, 147, 149: swap raw px to tokens (`font-size:11px`→`var(--fs-xs)`, `13px`→`var(--fs-base)`, `margin-top:9px`→`var(--sp-2)`, `margin-top:4px`→`var(--sp-1)`, `gap:5px`→`var(--sp-1)`).

- [ ] **Step 3: Verify**

```bash
node tools/style-audit.mjs read "#sec-stats" grid-template-columns gap
node tools/style-audit.mjs diff
```

Expected: `#sec-stats` still 4 tracks; `diff` shows only `#sec-stats gap 14px→16px` (and `margin` isn't tracked). Visual: tiles identical bar the 2px paddings.

- [ ] **Step 4: Commit**

```bash
git add dashboard.css "Running Dashboard.dc.html"
git commit -m "refactor: tokenize KPI stat tiles"
```

---

## Task 6: Section headings + week strips (this week + road block)

**Files:** `dashboard.css`, `Running Dashboard.dc.html` (lines 155–200, plus headings at 203, 376-area)

**Interfaces:** Produces `.section-head`, `.week-grid`, `.day`.

- [ ] **Step 1: Add to `dashboard.css`**

```css
.section-head { display: flex; align-items: baseline; gap: var(--sp-3); margin-bottom: var(--sp-3); }
.section-head h2 { font-size: var(--fs-md); font-weight: var(--fw-extrabold); letter-spacing: .02em; }
.section-head .rule { height: 1px; flex: 1; background: var(--line); }
.section-head .meta { font-size: var(--fs-sm); color: var(--sub); font-weight: var(--fw-semibold); }

.week-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: var(--sp-2); margin-bottom: var(--sp-6); }

.day { display: flex; flex-direction: column; border-radius: var(--r-lg); padding: var(--sp-3); min-height: 128px; position: relative; }
```

- [ ] **Step 2: Apply to the two week headings + the two strips**

- Heading rows lines 155, 176 (and 203 "THE LONG GAME"): add `class="section-head"` to the wrapper; delete `display:flex;align-items:baseline;gap:12px;margin-bottom:12px`. Inside: `<h2>` keep text, delete inline `font-size:15px;font-weight:800;letter-spacing:.02em` (now from `.section-head h2`); the `<div style="height:1px;flex:1;background:var(--line)">` → `class="rule"` delete inline; the trailing `<span>` → `class="meta"` delete `font-size:12px;color:var(--sub);font-weight:600`.
- Strips lines 160, 181 `<section id="sec-week1|sec-week2" …>`: add `class="week-grid"`; delete `display:grid;grid-template-columns:repeat(7,1fr);gap:10px;margin-bottom:26px`.
- Day card line 162 (`{{ d.bg }}`) and line 183 (`{{ w.bg }}`): add `class="day"`; delete `border-radius:13px;padding:13px 12px;min-height:128px;display:flex;flex-direction:column;position:relative`. **Keep** `background:{{ d.bg }};border:1px solid {{ d.border }};opacity:{{ d.opacity }}` (dynamic). Line 183 `min-height:132px` → the class sets 128; set `min-height:var(--sp...)`? 132 and 128 differ — keep `.day` at 128 and accept 132→128 (−4) on the road block, OR add `style="min-height:132px"` back. Keep them unified at 128 (reviewed). Border stays inline (dynamic color).
- Tokenize the day-card inner text (lines 164–170, 185–197): `font-size:12px`→`var(--fs-sm)`, `12.5px`→`var(--fs-sm)`, `10.5px`→`var(--fs-xs)`, `10px`→`var(--fs-2xs)`, `9px`/`9.5px`→`var(--fs-2xs)`, `21px`→`var(--fs-xl)`; `border-radius:8px`(icon)→`var(--r-md)`, `border-radius:99px`→`var(--r-pill)`, `border-radius:50%` stays; margins/gaps to spacing tokens.

- [ ] **Step 3: Verify**

```bash
node tools/style-audit.mjs read "#sec-week1" grid-template-columns
node tools/style-audit.mjs read "#sec-week2" grid-template-columns
node tools/style-audit.mjs diff
```

Expected: both strips still 7 tracks; `diff` shows week gap `10px→8px`. Visual: weeks identical bar minor spacing.

- [ ] **Step 4: Commit**

```bash
git add dashboard.css "Running Dashboard.dc.html"
git commit -m "refactor: tokenize section headings and week strips"
```

---

## Task 7: Charts grid + volume card + heatmap card

**Files:** `dashboard.css`, `Running Dashboard.dc.html` (lines 203–402)

**Interfaces:** Produces `.chart-grid`. Reuses `.card`, `.card-head`, `.card-title`, `.card-sub`, `.metric`, `.section-head`.

- [ ] **Step 1: Add to `dashboard.css`**

```css
.chart-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: var(--sp-4); margin-bottom: var(--sp-4); }
```

- [ ] **Step 2: Apply across the chart cards, volume card, heatmap card**

- Line 234 `<section id="sec-charts" …>`: add `class="chart-grid"`; delete `display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:14px;margin-bottom:14px`.
- Each chart panel (237, 261, 286, 312, 336, 353), the volume card (209), the heatmap card (377): add `class="card"`; delete `background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px` (and the volume's trailing `;margin-bottom:14px` → keep as inline `style="margin-bottom:var(--sp-4)"` or move to a `.card + .stack` — simplest: keep `margin-bottom:var(--sp-4)` inline on those two).
- Each card's title row (238, 262, 287, 313, 354, 210, 378): add `class="card-head"`; delete `display:flex;justify-content:space-between;align-items:flex-start` (heatmap 378 uses `align-items:center` — keep that inline; just don't use `.card-head` there, or override `align-items` inline).
- Title `<div>font 13/800` → `class="card-title"`; sub `<div>font 11.5/500/sub/margin-top:2px` → `class="card-sub"`; delete their inline.
- Right-side big values (240, 264, 315, 356, 215, 212-area): add `class="metric"`; delete `font-family:'JetBrains Mono';font-weight:700`; `font-size:24px`→`var(--fs-2xl)`.
- HR-zones card inner (337–346) and sleep have one-off bits — tokenize raw px (`font-size:11px`→`var(--fs-xs)`, `border-radius:5px`→`var(--r-sm)`, `gap:9px`→`var(--sp-2)`, `gap:10px`→`var(--sp-3)`) and leave structural flex inline.
- Heatmap legend swatches (381–385 `border-radius:3px`→`var(--r-sm)`), month text and cells are SVG (leave). The `overflow-x:auto` scroll wrapper (388) stays — it already makes the heatmap mobile-safe.

- [ ] **Step 3: Verify**

```bash
node tools/style-audit.mjs read "#sec-charts" grid-template-columns
node tools/style-audit.mjs read "#sec-heat" border-radius padding
node tools/style-audit.mjs diff
```

Expected: charts grid still auto-fit (2–3 tracks at 1200); `#sec-heat` → `border-radius:14px` (unchanged), `padding:16px` (18→16). `diff`: charts gap `14px→16px`. Visual: all charts/heatmap identical bar paddings.

- [ ] **Step 4: Commit**

```bash
git add dashboard.css "Running Dashboard.dc.html"
git commit -m "refactor: tokenize charts grid, volume and heatmap cards"
```

---

## Task 8: Bottom split — runs table + drill-down + coach-log timeline

**Files:** `dashboard.css`, `Running Dashboard.dc.html` (lines 405–493)

**Interfaces:** Produces `.split-grid`, `.runs-head`, `.runs-row`, `.runs-cell`, `.drill-grid`, `.timeline`, `.timeline-item`. The `data-label` attributes (added here) are consumed by Task 10's phone CSS.

- [ ] **Step 1: Add to `dashboard.css`**

```css
.split-grid { display: grid; grid-template-columns: 1.6fr 1fr; gap: var(--sp-4); }

.runs-head, .runs-row { display: grid; grid-template-columns: 1fr 1.3fr .8fr .9fr .9fr .7fr .7fr; gap: var(--sp-2); }
.runs-head { font-size: var(--fs-2xs); letter-spacing: .06em; color: var(--sub); font-weight: var(--fw-bold); padding-bottom: var(--sp-2); border-bottom: 1px solid var(--line); }
.runs-row  { font-size: var(--fs-sm); padding: var(--sp-3) 0; border-bottom: 1px solid var(--line); align-items: center; }

.drill-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: var(--sp-4); align-items: end; }

.timeline { display: flex; flex-direction: column; gap: 0; }
.timeline-item { display: flex; gap: var(--sp-3); padding-bottom: var(--sp-4); }
```

- [ ] **Step 2: Apply classes + add `data-label`s**

- Line 405 `<section id="sec-split" …>`: add `class="split-grid"`; delete `display:grid;grid-template-columns:1.6fr 1fr;gap:14px`.
- Runs panel (406) + coach panel (471): add `class="card"`; delete the panel surface inline; keep `margin-bottom` if any (none here).
- Header row 408: add `class="runs-head"`; delete its grid/font inline.
- Data row 413: add `class="runs-row"`; delete `display:grid;grid-template-columns:…;gap:6px;font-size:12px;padding:10px 0;border-bottom:1px solid var(--line);align-items:center`. **Keep** `cursor:{{ r.cursor }}` and all `role/tabIndex/aria-expanded/onKeyDown/onClick`.
- Add `data-label` to the five numeric cells (416–420) for Task 10's phone cards: `data-label="Dist"` (416), `"Time"` (417), `"Pace"` (418), `"HR"` (419), `"Cad"` (420). Tokenize their `font-size` where present; keep `font-family:'JetBrains Mono'` (or apply `.metric`).
- Drill-down grid 425: add `class="drill-grid"`; delete `display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;align-items:end`.
- Timeline 476: add `class="timeline"`; delete `display:flex;flex-direction:column;gap:0`. Item 478: add `class="timeline-item"`; delete `display:flex;gap:11px;padding-bottom:16px`. Tokenize the dashed footnote (490: `border-radius:10px`→`var(--r-md)`, paddings/fonts to tokens).

- [ ] **Step 3: Verify desktop parity (table stays a table)**

```bash
node tools/style-audit.mjs read "#sec-split" grid-template-columns
node tools/style-audit.mjs read ".runs-row" display grid-template-columns
node tools/style-audit.mjs diff
```

Expected: `#sec-split` 2 tracks; `.runs-row` `display:grid` with 7 tracks. Visual: bottom section identical; expand a run → drill-down still 3 sparklines.

- [ ] **Step 4: Commit**

```bash
git add dashboard.css "Running Dashboard.dc.html"
git commit -m "refactor: tokenize runs table, drill-down and coach-log timeline"
```

---

## Task 9: Responsive layout reflows (tablet + phone grids)

**Files:** `dashboard.css` (append `@media` blocks), `Running Dashboard.dc.html` (header only)

**Interfaces:** Consumes all layout-container classes. The `layout` audit mode starts passing here.

- [ ] **Step 1: Confirm the layout assertions currently FAIL (no media queries yet)**

```bash
node tools/style-audit.mjs layout
```

Expected: `LAYOUT: FAIL` — at 768/390 the grids still report desktop track counts.

- [ ] **Step 2: Append responsive blocks to `dashboard.css`**

```css
/* ============ tablet ============ */
@media (max-width: 900px) {
  .hero-grid   { grid-template-columns: 1fr 1fr; }
  #card-hero   { grid-column: 1 / -1; }            /* countdown spans full width */
  .stats-grid  { grid-template-columns: repeat(2, 1fr); }
  .week-grid   { grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); }
  .split-grid  { grid-template-columns: 1fr; }
}
/* ============ phone ============ */
@media (max-width: 560px) {
  .hero-grid   { grid-template-columns: 1fr; }
  .stats-grid  { grid-template-columns: repeat(2, 1fr); }
  .week-grid   { grid-template-columns: 1fr; }
  .drill-grid  { grid-template-columns: 1fr; }
  .topbar      { flex-wrap: wrap; gap: var(--sp-3); }   /* header wraps; class added in step 3 */
}
```

> `.hero-grid` at tablet uses `1fr 1fr` with `#card-hero` spanning both columns, so readiness + coach share row 2 (spec §6). `.chart-grid` already reflows via `auto-fit` — no rule needed.

- [ ] **Step 3: Let the header wrap on phone**

The header is line 29 `<header style="display:flex;…">`. Add `class="topbar"` to it (no other change). The phone rule above then lets `space-between` + wrap drop the right cluster (sync pill · theme swatches · avatar) below the logo on narrow widths without losing anything.

- [ ] **Step 4: Verify the layout assertions now PASS**

```bash
node tools/style-audit.mjs layout
```

Expected: `LAYOUT: ALL PASS` for `#sec-hero/#sec-stats/#sec-week1/#sec-week2/#sec-charts/#sec-split` at 1200/768/390. (The phone `.runs-*` checks still FAIL — those are Task 10.) If only the runs checks fail, that's expected at this stage; the grid lines must all be `ok`.

- [ ] **Step 5: Visual review** at 390 / 768 / 1200 — no horizontal overflow; hero/stats/week/split reflow as mapped.

- [ ] **Step 6: Commit**

```bash
git add dashboard.css "Running Dashboard.dc.html"
git commit -m "feat: responsive layout reflows for tablet and phone"
```

---

## Task 10: Responsive components — agenda week + stacked runs cards

**Files:** `dashboard.css` (extend phone block), `Running Dashboard.dc.html` (no structural change — `data-label`s already added in Task 8)

**Interfaces:** Consumes `.day`, `.runs-head`, `.runs-row`, `[data-label]`.

- [ ] **Step 1: Add the phone component rules to `dashboard.css` (inside `@media (max-width:560px)`)**

```css
@media (max-width: 560px) {
  /* week strip → horizontal agenda rows */
  .day { flex-direction: row; align-items: center; gap: var(--sp-3); min-height: 0; padding: var(--sp-3) var(--sp-4); }
  .day > :first-child { flex: 0 0 64px; }      /* day label + dot rail */
  .day .day-body { flex: 1; }                  /* see step 2 */

  /* runs table → stacked cards */
  .runs-head { display: none; }
  .runs-row  { display: block; padding: var(--sp-3) 0; }
  .runs-row > * { text-align: left !important; }
  .runs-row [data-label] { display: inline-block; margin-right: var(--sp-4); }
  .runs-row [data-label]::before { content: attr(data-label) " "; color: var(--sub); font-weight: var(--fw-semibold); }
}
```

> `!important` here is the single justified exception: the runs cells carry inline `text-align:right` (dynamic-adjacent, on many cells); overriding to left on phone is cleaner than editing 5 inline strings. (If preferred, instead delete `text-align:right` from the 5 cells in Task 8 and move it into `.runs-row > *` desktop rule — then no `!important`. Implementer's choice; note which was taken.)

- [ ] **Step 2: Give the day card a body wrapper (only if needed for the agenda rail)**

The `.day` children are: header row (day+dot), icon, title, detail, load. For the agenda row, wrap the non-header children so the rail (`:first-child` = header row) sits left and the rest flows right. Minimal approach: leave the existing children and rely on `flex-direction:row` + `flex-wrap` — but cleaner is a body wrapper. If the simple `flex-direction:row` already reads well in the visual check, **skip the wrapper** (YAGNI). Only add a `<div class="day-body">` around lines 167–170 (icon/title/detail/load) if the visual review shows the agenda row needs it. Verify by eye at 390px.

- [ ] **Step 3: Verify layout + components**

```bash
node tools/style-audit.mjs layout
```

Expected: `LAYOUT: ALL PASS` including the phone `.runs-head display:none` and `.runs-row display != grid` checks.

Interaction check at 390px (manual, `pnpm dev` + narrow window or chrome-devtools resize): a chart tap opens a `.pop` card; a runs card taps to expand its drill-down (now 1-column).

- [ ] **Step 4: Visual review** at 390px — week is a clean agenda; runs are labeled cards; nothing overflows.

- [ ] **Step 5: Commit**

```bash
git add dashboard.css "Running Dashboard.dc.html"
git commit -m "feat: phone agenda week strip and stacked runs cards"
```

---

## Task 11: Cleanup, README, full regression

**Files:** `README.md`, possibly `Running Dashboard.dc.html` (remove empty `style=""`), `dashboard.css`

- [ ] **Step 1: Sweep for leftovers**

```bash
node tools/style-audit.mjs diff
```

Review the full diff vs baseline: every change must be an expected token nudge (radius 16→14, paddings 18/22→16/20, gaps 14/10→16/8). Grep for empty style attributes and stray raw values in migrated sections:

```bash
rg 'style=""' "Running Dashboard.dc.html"
rg 'border-radius:1[346]px|font-family:.JetBrains Mono.;font-weight:700' "Running Dashboard.dc.html"
```

Expected: no empty `style=""`; the surviving `border-radius`/mono matches are only on data-driven or intentionally-inline elements. Remove any empty `style=""`.

- [ ] **Step 2: Update README**

In `README.md`, add a `dashboard.css` row to the file table and a line noting the dashboard is now responsive (phone/tablet/desktop) and styled via design tokens in `dashboard.css`, with `tools/style-audit.mjs` as the layout-regression harness.

- [ ] **Step 3: Full regression**

```bash
node tools/style-audit.mjs layout        # → LAYOUT: ALL PASS
node test_chart_hover.mjs                 # → ALL PASS
node test_coach_read.mjs                  # → ALL PASS
```

Manual: at 1200/768/390 confirm — theme switch (all 3 themes) still recolors everything at every width; the browser console has no new errors/warnings; the datapoint hover/tap cards and keyboard nav still work.

- [ ] **Step 4: Commit**

```bash
git add README.md dashboard.css "Running Dashboard.dc.html"
git commit -m "docs: document dashboard.css and responsive layout; final cleanup"
```

---

## Notes for the executor

- **Order matters only loosely** for Tasks 4–8 (independent sections); Tasks 1–2 must come first, Task 9 before 10, Task 11 last.
- **Parity oracle:** the baseline JSON captures the *original* desktop values. After each section, `diff` should surface only that section's documented nudges — anything else (especially a changed grid track count at 1200) is an accidental regression to fix before committing.
- **If Playwright can't install** in the execution environment, fall back to driving the same `getComputedStyle` reads via the chrome-devtools MCP (`navigate_page` → `resize_page` → `evaluate_script`); the assertions and expected values are identical.
- **`!important` budget:** exactly one allowed (Task 10 runs-cell text-align), and even that has a no-`!important` alternative noted. Nowhere else.
