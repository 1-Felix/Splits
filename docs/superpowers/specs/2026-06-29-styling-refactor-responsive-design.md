# SPLITS Dashboard — Styling Refactor + Responsive Design

**Date:** 2026-06-29
**Status:** Approved design, ready for implementation plan
**Goal:** Replace the inline-style soup in `Running Dashboard.dc.html` with a proper, maintainable styling architecture (design tokens → semantic classes → responsive layer) in an external stylesheet, and make the dashboard responsive across phone / tablet / desktop. Maintainability first; responsiveness falls out of the class layer as the payoff.

---

## 1. Context & Constraints

### Why now
The dashboard works on desktop but is broken on mobile: there are **zero media queries**, and every layout is a fixed inline-styled grid (hero 3-col, stats 4-col, two 7-col week strips, a 7-col runs table, a 2-col bottom split). Nothing reflows. Underneath that, the styling is unmaintainable: color is tokenized via per-theme CSS variables, but **everything else is raw inline values, repeated** — the card surface `background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:20px` appears ~15 times; spacing, radii, and type sizes are hand-copied throughout.

### Free to refactor
The frontend was originally imported from a Claude Design project, but on 2026-06-28 Felix confirmed the local `Running Dashboard.dc.html` is now the **source of truth** — diverging from the design source is explicitly fine, and we must **not** re-pull from Claude Design (it would clobber local work). The inline-style soup is a design-tool export artifact, not something to preserve. We can refactor freely.

### Runtime facts (dc-runtime / `support.js`) — must respect
- `support.js` is the **generated runtime — never edit it.**
- The template uses `{{ expr }}` interpolation and `<sc-for list="{{arr}}" as="x">`. There is **no `<sc-if>`**.
- `support.js` maps the `class` attribute to React's `className` (support.js:398) — **semantic classes work.**
- The helmet `<style>` block renders (keyframes/scrollbar styles already work), and the helmet already loads fonts via `<link>` — so a helmet `<link rel="stylesheet" href="./dashboard.css">` is expected to work (verified in Task 0).
- Pseudo-classes use the `style-<pseudo>="<css>"` attribute (e.g. `style-hover`, `style-focus-visible`), which `createPseudoSheet` turns into `.scpN:<pseudo>{...}` rules. These are independent of our semantic classes and stay as-is.
- **Data-driven inline styles must stay inline.** Many elements set values from interpolation (e.g. `style="background:{{ d.bg }};border:1px solid {{ d.border }};opacity:{{ d.opacity }}"` on day cards, `left:{{ cd.left }}` on floating cards). The semantic class carries the *static* structure; the dynamic values remain inline. Class + inline coexist on the same element (they govern different properties, so no `!important` is needed).
- No build step. The stylesheet is plain CSS served statically (`pnpm dev` → Python http.server at `http://localhost:8000/Running%20Dashboard.dc.html`). Per user global rules: use `pnpm`, not `npm`.

### Out of scope (explicitly)
- Component decomposition (splitting the single `.dc.html` into sub-components) — a future, larger effort.
- Any change to data files (`garmin-data.js`, `plan-data.js`, `running-data.js`), `support.js`, or chart/interaction logic.
- Redesign. This is a refactor: the desktop look is preserved except for the small, intentional, reviewed token-rationalization nudges (Section 4).

---

## 2. Architecture — three layers

1. **Design tokens** — CSS custom properties in `:root` for the scales that are currently raw: type, weight, spacing, radius, shadow. Color tokens already exist per-theme and are left untouched (theming keeps swapping only colors).
2. **Semantic component classes** — one class per repeated visual pattern (`.card`, `.stat`, `.day`, `.chart-card`, `.pill`, `.metric`, `.section-head`, …) plus layout-container classes (`.hero-grid`, `.stats-grid`, `.week-grid`, …). Each composes tokens. This is where the duplication dies.
3. **Responsive layer** — desktop-first `@media` blocks that re-flow the layout-container classes for tablet and phone. Only possible *because* layout now lives in classes.

### File structure
```
dashboard.css                 ← NEW. :root tokens → semantic classes → @media. The whole visual language.
Running Dashboard.dc.html     ← structure + {{ interpolation }} + data-driven inline styles only.
                                 helmet gains: <link rel="stylesheet" href="./dashboard.css">
```

---

## 3. The risk to retire first (Task 0)

The chosen approach depends on a helmet-linked external stylesheet applying to the rendered component. This is very likely (fonts already load via helmet `<link>`; Python's http.server serves `.css` as `text/css`), but it is the one unproven assumption.

**Task 0:** Create `dashboard.css` with a single sentinel rule (e.g. `.r-smoke{outline:3px solid magenta}`), add the helmet `<link>`, add `class="r-smoke"` to one element, run `pnpm dev`, and confirm via DOM (`getComputedStyle`) that the rule applied. If it applies → proceed. If it does **not** → fall back to keeping the stylesheet in the existing helmet `<style>` block (co-located); everything else in this spec is unchanged. Remove the sentinel before moving on.

---

## 4. Token scales (rationalized)

Existing values are irregular (19 distinct font sizes, every-integer spacing). We snap them onto clean scales. **Rule:** the snap tables below are **normative** — each existing value maps to the listed token. Values are snapped to the nearest token; where a value sits between two tokens it joins the cluster it visually belongs to (e.g. 22px joins the large-number `--fs-xl` group rather than `--fs-2xl`); signature display sizes are kept exact. The nudges are intentional and get a visual-diff review (Section 8).

### Type — `--fs-*`
| Token | Value | Absorbs (existing px) |
|---|---|---|
| `--fs-2xs` | 10 | 9, 9.5, 10 |
| `--fs-xs` | 11 | 10.5, 11 |
| `--fs-sm` | 12 | 11.5, 12 |
| `--fs-base` | 13 | 12.5, 13 |
| `--fs-md` | 15 | 14, 15 |
| `--fs-lg` | 16 | 16 |
| `--fs-xl` | 20 | 19, 20, 21, 22 |
| `--fs-2xl` | 24 | 24 |
| `--fs-3xl` | 30 | 30 |
| `--fs-display` | 78 | 78 (kept exact — hero countdown) |

### Weight — `--fw-*`
`--fw-normal` 400 · `--fw-medium` 500 · `--fw-semibold` 600 · `--fw-bold` 700 · `--fw-extrabold` 800 · `--fw-black` 900. (All existing weights kept — no rationalization needed.)

### Spacing — `--sp-*` (4px grid)
| Token | Value | Absorbs (existing px) |
|---|---|---|
| `--sp-px` | 1 | 1 (hairline gaps, e.g. zone bars — kept exact) |
| `--sp-1` | 4 | 2, 3, 4, 5 |
| `--sp-2` | 8 | 6, 7, 8, 9 |
| `--sp-3` | 12 | 10, 11, 12, 13 |
| `--sp-4` | 16 | 14, 16, 18 |
| `--sp-5` | 20 | 20, 22 |
| `--sp-6` | 24 | 26 |
| `--sp-8` | 32 | (available for larger gaps) |

### Radius — `--r-*`
| Token | Value | Absorbs (existing px) |
|---|---|---|
| `--r-sm` | 6 | 3, 4, 5, 6 |
| `--r-md` | 10 | 8, 9, 10 |
| `--r-lg` | 14 | 13, 14, 16 |
| `--r-pill` | 99 | 99 |

### Shadow — `--shadow-*`
- `--shadow-pop` — the floating data-point cards: `0 6px 18px rgba(0,0,0,.30)` (the only real shadow in the file, ×10; kept exact, just named). The decorative logo-glyph `box-shadow` (header) is not a token candidate and stays inline.

> The precise current-value → token assignment for each element is mechanical (apply the snap tables). The implementation plan migrates section by section so each assignment is made in context and visually reviewed.

---

## 5. Semantic classes

Each class replaces a repeated inline pattern. Static structure lives in the class; data-driven values stay inline.

**Surfaces**
- `.card` — base panel: `background:var(--panel); border:1px solid var(--line); border-radius:var(--r-lg); padding:var(--sp-5)`. Modifiers: `.card--hero` (gradient background), `.card--sm` (tighter padding / `--r-md`).
- `.stat` — stat card (the 4-up metric tiles).
- `.chart-card` — the chart panels (title row + full-width SVG).
- `.day` — week-strip day card. **Default (desktop/tablet): vertical** (label, dot, icon, title, detail). **Phone: horizontal agenda row** (see Section 6).
- `.pill` — rounded chips (sync status, plan-focus chips, zone labels).
- `.metric` — label + mono numeric value pattern.
- `.section-head` — the "title + sub" baseline-aligned heading row that precedes several sections.
- `.timeline` — the coach-log adjustment feed (dot + connector + text).

**Layout containers**
- `.hero-grid` · `.stats-grid` · `.week-grid` · `.chart-grid` · `.split-grid` · `.runs-table` · `.runs-row` · `.drill-grid`

---

## 6. Responsive design

**Breakpoints (desktop-first):** desktop `> 900px` (base rules, unchanged from today's look), tablet `@media (max-width:900px)`, phone `@media (max-width:560px)`.

| Container | Desktop (base) | Tablet ≤900 | Phone ≤560 |
|---|---|---|---|
| `.hero-grid` | `grid` 3-col `1.55fr 1fr 1.4fr` | countdown spans full width (`grid-column:1/-1`), readiness + coach share row 2 (`1fr 1fr`) | 1-col |
| `.stats-grid` | `repeat(4,1fr)` | `repeat(2,1fr)` | `repeat(2,1fr)` |
| `.week-grid` | `repeat(7,1fr)` | `repeat(auto-fit,minmax(140px,1fr))` | 1-col (agenda) |
| `.chart-grid` | `repeat(auto-fit,minmax(340px,1fr))` (already fluid) | unchanged (→ 2-up) | unchanged (→ 1-col) |
| `.split-grid` | `1.6fr 1fr` | 1-col | 1-col |
| `.runs-table` | 7-col table | table (panel is now full-width → fits) | stacked cards (Section 7) |
| `.drill-grid` | `repeat(3,1fr)` | `repeat(3,1fr)` | 1-col |
| header | flex row, space-between | row | `flex-wrap:wrap`, tighter gaps |

### Agenda mechanism (`.week-grid` + `.day` on phone)
On phone, `.week-grid` becomes a single column. The `.day` card switches from a vertical stack to a **horizontal agenda row**: a fixed-width left rail (day abbreviation + status dot) and a flexible right region (icon + title + detail + km). This reads as a training agenda, Mon→Sun top to bottom. Implemented purely with phone-scoped overrides of `.day`'s flex-direction and child sizing — no DOM change, no markup duplication.

---

## 7. Stacked-cards mechanism (runs table on phone)

Today the runs table is a 7-column grid: a header row (DATE · WORKOUT · DIST · TIME · PACE · HR · CAD) and one `.runs-row` per run with 7 unlabeled cells; expanding a row reveals a 3-column `.drill-grid` of sparklines.

On phone (`@media (max-width:560px)`):
- The header row hides (`.runs-head{display:none}`).
- `.runs-row` switches from `display:grid` (7-col) to a card layout: the WORKOUT cell becomes the heading; the date sits with it; the numeric cells wrap as labeled pairs.
- The numeric cells carry a static `data-label` attribute (`data-label="Dist"`, `"Time"`, `"Pace"`, `"HR"`, `"Cad"`), revealed **only on phone** via `.runs-row [data-label]::before{content:attr(data-label) " ";color:var(--sub)}`. Desktop never shows the labels (they live in the header row there). `data-label` is a plain static attribute — fully supported by the template.
- `.drill-grid` collapses to 1 column so the expanded sparklines stack.

No markup is duplicated; the same DOM renders as a table on desktop/tablet and as cards on phone via CSS alone.

---

## 8. Process & verification (safety rails)

This is a large but mechanical change to a ~700-line file. Discipline matters more than speed.

1. **Baseline first.** Before touching styles, capture the computed styles of a representative element per section at desktop width (≥1200px) via DOM `getComputedStyle`. This is the parity oracle.
2. **Section by section.** Migrate one section at a time: introduce its classes, move static styles into `dashboard.css`, remove them from inline. After each section, re-diff computed styles vs the baseline.
   - Everything **except** the token-rationalization nudges (Section 4 snap tables) must match the baseline exactly.
   - The nudges (e.g. radius 16→14, spacing 18→16, font 11.5→12) are **expected** and confirmed by a **visual review** of that section before moving on.
3. **Responsive last.** Add the `@media` blocks only after the class layer exists and desktop parity is confirmed.
4. **Multi-width verification.** At the end, verify at **390 / 768 / 1200px** by resizing the viewport and asserting the computed `display` / `grid-template-columns` per layout container, plus a user visual check at each width. Screenshots render black on this runtime, so DOM assertions are the automated guard; the user's eyes are the visual guard.
5. **Theme switching still works** at every width (token color vars unchanged).
6. **Console stays at baseline** (no new errors/warnings) after the refactor.

---

## 9. Success criteria

- `dashboard.css` exists and is linked from the helmet; the `.dc.html` no longer carries repeated static style strings for the migrated patterns.
- All spacing / radius / type values flow through tokens; no raw `px` font/spacing/radius literals remain in migrated sections (data-driven values excepted).
- Desktop renders identically to before except the reviewed token nudges.
- Phone (≤560) and tablet (≤900) reflow per the Section 6 map: no horizontal overflow, the week strip is an agenda, the runs table is stacked cards, every section is legible.
- The datapoint-interactivity feature (hover + tap cards, keyboard nav) still works at all widths.
- Theme switching and the console are unaffected.

---

## 10. Testing strategy

- **Parity (automated):** computed-style diff per section vs the captured desktop baseline; only the documented token nudges may differ.
- **Responsive (automated):** at 390 / 768 / 1200px, assert each layout container's computed `display` / `grid-template-columns` matches the Section 6 map.
- **Interaction (automated + manual):** confirm a hover/tap data-point card still opens on a chart at phone width; confirm a runs row still expands.
- **Visual (manual):** user reviews desktop (token nudges) and each mobile width.
