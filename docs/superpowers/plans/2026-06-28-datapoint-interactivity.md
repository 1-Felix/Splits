# Universal Datapoint Interactivity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every chart, graph, and diagram on the SPLITS dashboard surface the detail behind each datapoint — hover (desktop) or tap (touch) reveals a crosshair, a highlighted dot, and a floating card with the point's label, value, and one line of context — across all nine surfaces.

**Architecture:** A single `hover` state field drives a shared inspection layer. Each chart renders transparent `<rect>` hit-bands (the same declarative `onMouseEnter`/`onClick` pattern the run-rows already use); a reusable `hoverLayer()` method turns a chart's `points` array into those bands plus, when that chart is hovered, an overlay (SVG crosshair + dot and an **HTML card** positioned by percentage over a `position:relative` wrapper). Two pure, unit-tested helpers in a new `chart-hover.js` (`bandRects`, `cardPlace`) carry the only fiddly geometry. No backend changes.

**Tech Stack:** Vanilla ES-module JS (`chart-hover.js`), the `dc-runtime` React render of `Running Dashboard.dc.html`, Node for the JS unit test, Playwright/devtools MCP for live render verification.

## Global Constraints

- Use **pnpm**, never npm. Static server: `pnpm dev` (→ http://localhost:8000/Running%20Dashboard.dc.html).
- Node JS unit tests run with `node <file>.mjs` (matches `test_coach_read.mjs`).
- `support.js` is a **generated runtime — do not edit it.** It already binds camelCase `on*` attributes to React handlers (`collectProps`, line 401) and maps `onmouseenter`/`onmouseleave`/`onclick`/`onkeydown` (EVENT_MAP, lines 308-324).
- The `dc-runtime` template has **no `<sc-if>`** — conditional rendering is done with a 0-or-1-length array fed to `<sc-for>` (the run-drilldown `detailRows` pattern). Every conditional overlay piece is a 0/1-length array.
- Transparent SVG hit targets must use `fill="transparent"`, **never `fill="none"`** (`none` is not hit-tested).
- No TypeScript; plain JS, no casting. Flat repo layout (files at root, like `coach-read.js`).
- Text content uses literal Unicode characters (`⚡ → ° · ₂ ✕`), never escape sequences like `·`.
- Commit messages: **no Co-Authored-By line, no Claude attribution.**
- `garmin-data.js`, `.env`, `.garmin_cache/`, `.garmin_tokens/` are **gitignored — never commit them.**
- This feature touches **no backend**: `sync_garmin.py`, `garmin-data.js`, `plan-data.js`, `validate_data.py` are untouched.

---

## File Structure

- `chart-hover.js` (create) — pure `bandRects()` + `cardPlace()`. No DOM, no framework.
- `test_chart_hover.mjs` (create) — Node unit tests for both functions.
- `Running Dashboard.dc.html` (modify) — `hover` state; `hoverPoint`/`leaveChart`/`pinPoint`/`dismissHover`/`chartKey`/`heatKey` handlers; `line()` returns `pts`; `hoverLayer()` + `attachOverlay()` + `monthLabel()`/`relLabel()` helpers; per-surface points + overlay in `renderVals`; bands/crosshair/dot/HTML-card + a11y attributes in the template; import `chart-hover.js`.
- `README.md` (modify) — one line documenting datapoint interactivity.

The `dc.html` is the established home for all chart/render logic (it already holds `line()`, `runDetail()`, the theme machinery). The two geometry primitives are extracted to `chart-hover.js` purely for unit-testability, mirroring the existing `coach-read.js` + `test_coach_read.mjs` split.

---

## Shared verification recipe (used by Tasks 2-7)

Each UI task verifies against the **live dev server**, because screenshots render black on this runtime (it keeps hidden placeholder DOM). Use Playwright/devtools MCP:

1. Ensure the server runs: `pnpm dev` (background). Confirm `http://localhost:8000/Running%20Dashboard.dc.html` returns 200.
2. Navigate to the page; wait for real data (the page imports `running-data.js`; if absent it uses `buildData()` demo data — either is fine, both have the series).
3. Drive interaction with `browser_evaluate` and read the result back from the DOM. Click is the **reliable** path (React delegates `click`); use it to pin and assert. Example shape:

```js
() => {
  const band = document.querySelectorAll('[data-hb="vo2"]')[5];   // 6th VO2 hit-band
  band.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  const card = document.querySelector('[data-card="vo2"]');
  return card ? card.innerText.replace(/\n/g, ' | ') : 'NO CARD';
}
```

4. For hover specifically, dispatch `new MouseEvent('mouseover', { bubbles: true })` on a band (React synthesises `onMouseEnter` from `mouseover`) and assert the card appears; dispatch `mouseout` on the chart and assert it clears.
5. Assert **no console errors** beyond the benign SVG-placeholder baseline (~40-46 errors already present before this feature — count them first on an unmodified load so you can subtract).

Each task names the `data-hb` / `data-card` hook to target and the exact text to expect. The hooks (`data-hb="<chartId>"` on every band, `data-card="<chartId>"` on every card) are added in Task 2 and reused.

---

### Task 1: Pure geometry module `chart-hover.js`

**Files:**
- Create: `chart-hover.js`
- Test: `test_chart_hover.mjs`

**Interfaces:**
- Produces:
  - `bandRects(points, vbW, chartH) -> [{ x, y, w, h }]` — `points` is `[{ x }]` (only `x` read). Bands tile `[0, vbW]`; boundaries at neighbour midpoints; first/last reach the edges. `n===1` → one full band; `n===0` → `[]`.
  - `cardPlace(x, y, vbW, vbH) -> { leftPct, topPct, anchorX, place }` — `anchorX ∈ {'left','center','right'}` (x zones <20% / mid / >80%), `place ∈ {'above','below'}` (`below` when `y/vbH < 0.33`, else `above`).

- [ ] **Step 1: Write the failing test**

Create `test_chart_hover.mjs`:

```js
import assert from "node:assert";
import { bandRects, cardPlace } from "./chart-hover.js";

// bandRects — even 3-point row over width 600
let b = bandRects([{ x: 100 }, { x: 300 }, { x: 500 }], 600, 150);
assert.strictEqual(b.length, 3);
assert.strictEqual(b[0].x, 0);                       // first band starts at edge
assert.strictEqual(b[0].w, 200);                     // boundary at midpoint (100+300)/2=200
assert.strictEqual(b[1].x, 200);
assert.strictEqual(b[1].w, 200);                     // 200..400
assert.strictEqual(b[2].x, 400);
assert.strictEqual(b[2].w, 200);                     // 400..600 reaches the edge
assert.strictEqual(b[0].y, 0);
assert.strictEqual(b[0].h, 150);

// bandRects — single point covers the whole width
b = bandRects([{ x: 42 }], 600, 30);
assert.deepStrictEqual(b, [{ x: 0, y: 0, w: 600, h: 30 }]);

// bandRects — empty
assert.deepStrictEqual(bandRects([], 600, 150), []);

// cardPlace — left zone, lower half -> anchor left, card above
let p = cardPlace(60, 120, 600, 150);
assert.strictEqual(p.anchorX, "left");               // 60/600 = 0.1 < 0.2
assert.strictEqual(p.place, "above");                // 120/150 = 0.8 >= 0.33
assert.strictEqual(p.leftPct, 10);
assert.strictEqual(p.topPct, 80);

// cardPlace — right zone, near top -> anchor right, card below
p = cardPlace(540, 20, 600, 150);
assert.strictEqual(p.anchorX, "right");              // 540/600 = 0.9 > 0.8
assert.strictEqual(p.place, "below");                // 20/150 = 0.133 < 0.33

// cardPlace — middle zone -> centered
p = cardPlace(300, 75, 600, 150);
assert.strictEqual(p.anchorX, "center");

console.log("ALL PASS");
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `node test_chart_hover.mjs`
Expected: FAIL — `Cannot find module './chart-hover.js'` (or similar import error).

- [ ] **Step 3: Write the implementation**

Create `chart-hover.js`:

```js
/* chart-hover.js — pure geometry for datapoint hover interaction.
 * No DOM, no framework. Unit-tested in test_chart_hover.mjs. */

/** Hit-band spans tiling [0, vbW]. Each band owns the territory nearest its
 *  point (boundaries at neighbour midpoints); first/last reach the edges.
 *  points: [{ x }] (only x read). n<=1 -> one full band; n===0 -> []. */
export function bandRects(points, vbW, chartH) {
  const n = points.length;
  if (n === 0) return [];
  if (n === 1) return [{ x: 0, y: 0, w: vbW, h: chartH }];
  const xs = points.map((p) => p.x);
  const edges = [0];
  for (let i = 0; i < n - 1; i++) edges.push((xs[i] + xs[i + 1]) / 2);
  edges.push(vbW);
  const out = [];
  for (let i = 0; i < n; i++) {
    out.push({
      x: +edges[i].toFixed(2),
      y: 0,
      w: +(edges[i + 1] - edges[i]).toFixed(2),
      h: chartH,
    });
  }
  return out;
}

/** Placement descriptor for the HTML card, from the point's viewBox coords.
 *  Measurement-free: percentages + an x anchor zone and a vertical flip so the
 *  card never grossly overflows. */
export function cardPlace(x, y, vbW, vbH) {
  const fx = vbW ? x / vbW : 0;
  const fy = vbH ? y / vbH : 0;
  const anchorX = fx < 0.2 ? "left" : fx > 0.8 ? "right" : "center";
  const place = fy < 0.33 ? "below" : "above";
  return {
    leftPct: +(fx * 100).toFixed(2),
    topPct: +(fy * 100).toFixed(2),
    anchorX,
    place,
  };
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `node test_chart_hover.mjs`
Expected: `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add chart-hover.js test_chart_hover.mjs
git commit -m "feat: pure bandRects + cardPlace geometry for datapoint hover"
```

---

### Task 2: Hover mechanism + VO₂ wired end-to-end

Build the whole inspection mechanism and prove it on one line chart (VO₂). Later tasks reuse it verbatim.

**Files:**
- Modify: `Running Dashboard.dc.html`
  - import (top of `<script type="text/x-dc">`, alongside the existing module usage — the component reads `chart-hover` functions)
  - `state` (line 400), handlers (after `toggleRun`, ~line 409), `line()` (line 488-502), `renderVals` (the VO₂ block ~line 583 and the return object ~line 647), template VO₂ block (lines 218-229)

**Interfaces:**
- Consumes: `bandRects`, `cardPlace` from `./chart-hover.js` (Task 1), loaded via **dynamic** `import()` into `this._ch` (the dc.html script runs inside `new Function`, where a static `import` is a SyntaxError; `componentDidMount` already uses dynamic `import('./running-data.js')` the same way).
- Produces (reused by Tasks 3-7):
  - `this.line(vals, h, opt)` now also returns `pts` (array of `[x, y]`).
  - `this.hoverLayer(chartId, points, opt) -> { bands, overlay }` where `points` is `[{ x, y, dots?, dotColor?, lines:[{t, em}], aria? }]`, `opt` is `{ vbW=600, vbH=150, crosshair=true }`; `bands` is `[{ x,y,w,h, onEnter, onClick, aria }]`; `overlay` is `null` or `{ cross:[{x,top,bot}], dots:[{x,y,color}], card:{ left, top, transform, rows:[{t,color,weight}] } }`.
  - `this.attachOverlay(obj, hl)` spreads `hl.bands` → `obj.bands` and the overlay (or empties) → `obj.cross` (0/1), `obj.odots` (0..n), `obj.card` (0/1).
  - `this.monthLabel(D, i) -> 'MMM YYYY'` from `D.history.vo2maxStartMonth`.
  - State `hover = null | { chart, i, pinned }`; handlers `hoverPoint`, `leaveChart`, `pinPoint`, `dismissHover`.
  - Template hooks: every band carries `data-hb="<chartId>"`, every card `data-card="<chartId>"`.

- [ ] **Step 1: Extend `state`**

A static `import` is impossible here: `evalDcLogic` (support.js:713) runs this script through `new Function(...)`, whose body cannot contain top-level `import` (SyntaxError → the whole component falls back to props-only render). The geometry module is therefore loaded with a **dynamic** `import()` in `componentDidMount` (Step 2) and cached on `this._ch` — instance fields persist across re-renders, exactly as `this._builtin` already does (line 432).

Change `state` (line 400) from:

```js
  state = { theme: 'volt', data: null, expandedRun: null };
```
to:
```js
  state = { theme: 'volt', data: null, expandedRun: null, hover: null };
```

- [ ] **Step 2: Add hover handlers and clear hover on theme/run/data changes**

Replace the existing `setTheme`/`toggleRun` (lines 408-409) with versions that also clear hover, and add the four hover handlers immediately after:

```js
  setTheme = (name) => { this.setState({ theme: name, hover: null }); };
  toggleRun = (id) => { this.setState({ expandedRun: this.state.expandedRun === id ? null : id, hover: null }); };

  // ---- datapoint hover/tap ----
  hoverPoint = (chart, i) => { const h = this.state.hover; if (h && h.pinned) return; this.setState({ hover: { chart, i, pinned: false } }); };
  leaveChart = (chart) => { const h = this.state.hover; if (h && !h.pinned && h.chart === chart) this.setState({ hover: null }); };
  pinPoint = (chart, i, e) => { if (e && e.stopPropagation) e.stopPropagation(); const h = this.state.hover; if (h && h.pinned && h.chart === chart && h.i === i) { this.setState({ hover: null }); return; } this.setState({ hover: { chart, i, pinned: true } }); };
  dismissHover = () => { if (this.state.hover && this.state.hover.pinned) this.setState({ hover: null }); };
```

In `componentDidMount` (line 427) add the dynamic load of `chart-hover.js` (cache on `this._ch`, then re-render so bands appear) and add `hover: null` to the data setState so a reload drops any stale hover:

```js
  componentDidMount() {
    import('./chart-hover.js').then((m) => { this._ch = m; this.setState({}); }).catch(() => {});
    import('./running-data.js').then((m) => { if (m && m.athleteData) this.setState({ data: m.athleteData, hover: null }); }).catch(() => {});
  }
```

- [ ] **Step 3: `line()` returns `pts`**

In `line()` (line 501) change the return to also expose the vertices:

```js
    return { d, area, grid, lastX:+pts[n-1][0].toFixed(1), lastY:+pts[n-1][1].toFixed(1), Y, pts };
```

- [ ] **Step 4: Add `hoverLayer`, `attachOverlay`, `monthLabel` helpers**

Add these methods right after `line()` (after line 502):

```js
  hoverLayer(chartId, points, opt) {
    const ch = this._ch;
    if (!ch) return { bands: [], overlay: null };   // geometry module not loaded yet
    opt = opt || {};
    const vbW = opt.vbW != null ? opt.vbW : 600;
    const vbH = opt.vbH != null ? opt.vbH : 150;
    const bands = ch.bandRects(points, vbW, vbH).map((b, i) => ({
      x: b.x, y: b.y, w: b.w, h: b.h,
      onEnter: () => this.hoverPoint(chartId, i),
      onClick: (e) => this.pinPoint(chartId, i, e),
      aria: points[i].aria || ''
    }));
    const h = this.state.hover;
    let overlay = null;
    if (h && h.chart === chartId && h.i >= 0 && h.i < points.length) {
      const p = points[h.i];
      const pl = ch.cardPlace(p.x, p.y, vbW, vbH);
      const tx = pl.anchorX === 'left' ? '0' : pl.anchorX === 'right' ? '-100%' : '-50%';
      const ty = pl.place === 'above' ? 'calc(-100% - 9px)' : '9px';
      overlay = {
        cross: opt.crosshair === false ? [] : [{ x:+p.x.toFixed(2), top:0, bot:vbH }],
        dots: p.dots || [{ x:+p.x.toFixed(2), y:+p.y.toFixed(2), color:p.dotColor || 'var(--accent)' }],
        card: {
          left: pl.leftPct + '%', top: pl.topPct + '%', transform: 'translate(' + tx + ', ' + ty + ')',
          rows: p.lines.map(r => ({ t: r.t, color: r.em ? 'var(--ink)' : 'var(--sub)', weight: r.em ? '800' : '600' }))
        }
      };
    }
    return { bands, overlay };
  }

  attachOverlay(obj, hl) {
    obj.bands = hl.bands;
    if (hl.overlay) { obj.cross = hl.overlay.cross; obj.odots = hl.overlay.dots; obj.card = [hl.overlay.card]; }
    else { obj.cross = []; obj.odots = []; obj.card = []; }
    return obj;
  }

  monthLabel(D, i) {
    const sm = (D.history && D.history.vo2maxStartMonth) || '2024-01';
    const parts = sm.split('-'); const y = +parts[0], m = +parts[1];
    const idx = (m - 1) + i; const yr = y + Math.floor(idx / 12); const mo = ((idx % 12) + 12) % 12;
    const M = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    return M[mo] + ' ' + yr;
  }
```

- [ ] **Step 5: Build VO₂ points + overlay in `renderVals`**

Replace the VO₂ line (line 583):

```js
    const vo2 = this.line(H.vo2max, 150); vo2.last = vo2Now.toFixed(1); vo2.delta = '+'+(vo2Now-vo2Prev).toFixed(1)+' / 3mo';
```
with:
```js
    const vo2 = this.line(H.vo2max, 150); vo2.last = vo2Now.toFixed(1); vo2.delta = '+'+(vo2Now-vo2Prev).toFixed(1)+' / 3mo';
    const vo2pts = vo2.pts.map((p, i) => ({
      x: p[0], y: p[1], dotColor: 'var(--accent)',
      aria: 'VO2 ' + H.vo2max[i].toFixed(1) + ', ' + this.monthLabel(D, i),
      lines: [
        { t: this.monthLabel(D, i), em: false },
        { t: 'VO₂ ' + H.vo2max[i].toFixed(1), em: true },
        { t: i > 0 ? ((H.vo2max[i] - H.vo2max[i-1] >= 0 ? '+' : '') + (H.vo2max[i] - H.vo2max[i-1]).toFixed(1) + ' vs prev') : 'first month', em: false }
      ]
    }));
    this.attachOverlay(vo2, this.hoverLayer('vo2', vo2pts));
```

(`vo2` is already in the returned object at line 651, so its new `bands`/`cross`/`odots`/`card` ride along.)

- [ ] **Step 6: Render bands + overlay in the VO₂ template**

Replace the VO₂ chart block (lines 223-228) — wrap the `<svg>` in a `position:relative` div, add `onMouseLeave`, the bands, the crosshair, the hover dots, and the HTML card:

```html
      <div style="position:relative">
      <svg viewBox="0 0 600 150" style="width:100%;height:130px;display:block;margin-top:6px" onMouseLeave="{{ vo2.onLeave }}">
        <sc-for list="{{ vo2.grid }}" as="g" hint-placeholder-count="3"><line x1="0" y1="{{ g }}" x2="600" y2="{{ g }}" stroke="var(--grid)" stroke-width="1"></line></sc-for>
        <path d="{{ vo2.area }}" style="fill:var(--accentFade)"></path>
        <path d="{{ vo2.d }}" fill="none" style="stroke:var(--accent);vector-effect:non-scaling-stroke" stroke-width="2.4" stroke-linejoin="round"></path>
        <circle cx="{{ vo2.lastX }}" cy="{{ vo2.lastY }}" r="4" style="fill:var(--accent)"></circle>
        <sc-for list="{{ vo2.bands }}" as="b" hint-placeholder-count="30"><rect data-hb="vo2" x="{{ b.x }}" y="{{ b.y }}" width="{{ b.w }}" height="{{ b.h }}" fill="transparent" style="cursor:pointer" onMouseEnter="{{ b.onEnter }}" onClick="{{ b.onClick }}" aria-label="{{ b.aria }}"></rect></sc-for>
        <sc-for list="{{ vo2.cross }}" as="c" hint-placeholder-count="0"><line x1="{{ c.x }}" y1="{{ c.top }}" x2="{{ c.x }}" y2="{{ c.bot }}" style="stroke:var(--sub);pointer-events:none" stroke-width="1" stroke-dasharray="3 3"></line></sc-for>
        <sc-for list="{{ vo2.odots }}" as="d" hint-placeholder-count="0"><circle cx="{{ d.x }}" cy="{{ d.y }}" r="4.5" style="fill:{{ d.color }};pointer-events:none" stroke="var(--bg)" stroke-width="1.5"></circle></sc-for>
      </svg>
      <sc-for list="{{ vo2.card }}" as="cd" hint-placeholder-count="0">
        <div data-card="vo2" style="position:absolute;left:{{ cd.left }};top:{{ cd.top }};transform:{{ cd.transform }};pointer-events:none;background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:6px 9px;font-size:11px;line-height:1.35;white-space:nowrap;box-shadow:0 6px 18px rgba(0,0,0,.30);z-index:6">
          <sc-for list="{{ cd.rows }}" as="row" hint-placeholder-count="3"><div style="color:{{ row.color }};font-weight:{{ row.weight }};font-family:'JetBrains Mono',monospace">{{ row.t }}</div></sc-for>
        </div>
      </sc-for>
      </div>
```

Add `vo2.onLeave` in `renderVals` (right after the `attachOverlay` call in Step 5):

```js
    vo2.onLeave = () => this.leaveChart('vo2');
```

- [ ] **Step 7: Verify live (hover, tap, leave, dismiss)**

Start `pnpm dev` (background) and confirm 200. Using the shared verification recipe, with `browser_evaluate`:

```js
() => {
  const out = {};
  const bands = document.querySelectorAll('[data-hb="vo2"]');
  out.bandCount = bands.length;                                   // expect 30
  bands[5].dispatchEvent(new MouseEvent('click', { bubbles: true }));
  const card = document.querySelector('[data-card="vo2"]');
  out.cardText = card ? card.innerText.replace(/\n/g, ' | ') : 'NONE';  // expect "MMM YYYY | VO₂ <n> | ...vs prev"
  out.crosshair = !!document.querySelector('#root line[stroke-dasharray="3 3"]');
  // tap-away dismiss:
  document.body.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  out.afterDismiss = document.querySelector('[data-card="vo2"]') ? 'STILL' : 'GONE';
  return out;
}
```

Expected: `bandCount` 30; `cardText` shows a month, `VO₂` value, and a `vs prev` line for the 6th point; `crosshair` true; `afterDismiss` `GONE`. Also dispatch `mouseover` on a band and confirm a card appears, then `mouseout` on the `<svg>` clears it. Confirm console errors stay at the pre-feature baseline.

- [ ] **Step 8: Commit**

```bash
git add "Running Dashboard.dc.html"
git commit -m "feat: datapoint hover mechanism, proven on the VO2 chart"
```

---

### Task 3: Wire the pace, cadence, and fitness line charts

Reuse the Task 2 mechanism on the three remaining line charts. Pace and cadence are structurally identical to VO₂ (monthly labels). Fitness shows two series at one x, so its point carries **two** dots (CTL + ATL) and a three-value card.

**Files:**
- Modify: `Running Dashboard.dc.html` — `renderVals` (pace ~line 587, fitness ~line 593, cadence ~line 599) and the template blocks (pace 237-243, fitness 254-259, cadence 268-273).

**Interfaces:**
- Consumes: `hoverLayer`, `attachOverlay`, `monthLabel`, `line().pts`, the four hover handlers (Task 2).

- [ ] **Step 1: Pace points + overlay**

After the existing pace setup (after line 590, `pace.goalY = ...`), add:

```js
    const pacePts = pace.pts.map((p, i) => ({
      x: p[0], y: p[1], dotColor: 'var(--accent2)',
      aria: 'Pace ' + this.fmtPace(H.paceSecPerKm[i]) + ' per km, ' + this.monthLabel(D, i),
      lines: [
        { t: this.monthLabel(D, i), em: false },
        { t: this.fmtPace(H.paceSecPerKm[i]) + ' /km', em: true },
        { t: (() => { const g = H.paceSecPerKm[i] - goalP; return g === 0 ? 'on goal' : (g > 0 ? '+' : '−') + this.fmtPace(Math.abs(g)) + ' vs goal'; })(), em: false }
      ]
    }));
    this.attachOverlay(pace, this.hoverLayer('pace', pacePts));
    pace.onLeave = () => this.leaveChart('pace');
```

- [ ] **Step 2: Cadence points + overlay**

After the cadence setup (after line 599), add:

```js
    const cadPts = cad.pts.map((p, i) => ({
      x: p[0], y: p[1], dotColor: 'var(--accent)',
      aria: 'Cadence ' + H.cadenceSpm[i] + ' steps per minute, ' + this.monthLabel(D, i),
      lines: [
        { t: this.monthLabel(D, i), em: false },
        { t: H.cadenceSpm[i] + ' spm', em: true },
        { t: i > 0 ? ((H.cadenceSpm[i] - H.cadenceSpm[i-1] >= 0 ? '+' : '') + (H.cadenceSpm[i] - H.cadenceSpm[i-1]) + ' vs prev') : 'first month', em: false }
      ]
    }));
    this.attachOverlay(cad, this.hoverLayer('cad', cadPts));
    cad.onLeave = () => this.leaveChart('cad');
```

- [ ] **Step 3: Fitness points + overlay (two dots, weekly labels)**

The fitness chart draws CTL (`fit.d`) and ATL (`fit.atl`). Points sit on the CTL vertices; each point also carries the ATL dot. Labels are weekly (26 weeks ending this week). After the fitness setup (after line 596, `const formObj = ...`), add:

```js
    const fitN = H.ctl.length;
    const fitPts = fit.pts.map((p, i) => {
      const tsb = Math.round(H.ctl[i] - H.atl[i]);
      return {
        x: p[0], y: p[1],
        dots: [
          { x: +p[0].toFixed(2), y: +p[1].toFixed(2), color: 'var(--accent)' },
          { x: +fitAtl.pts[i][0].toFixed(2), y: +fitAtl.pts[i][1].toFixed(2), color: 'var(--accent2)' }
        ],
        aria: 'Week ' + this.relLabel(i, fitN, 'wk') + ', fitness ' + Math.round(H.ctl[i]) + ', fatigue ' + Math.round(H.atl[i]),
        lines: [
          { t: this.relLabel(i, fitN, 'wk'), em: false },
          { t: 'CTL ' + Math.round(H.ctl[i]) + ' / ATL ' + Math.round(H.atl[i]), em: true },
          { t: 'Form ' + (tsb >= 0 ? '+' : '') + tsb, em: false }
        ]
      };
    });
    this.attachOverlay(fit, this.hoverLayer('fit', fitPts));
    fit.onLeave = () => this.leaveChart('fit');
```

Add the `relLabel` helper next to `monthLabel` (after the `monthLabel` method from Task 2):

```js
  relLabel(i, n, unit) {
    const back = n - 1 - i;
    if (unit === 'wk') return back === 0 ? 'this week' : back === 1 ? 'last week' : back + ' wks ago';
    return back === 0 ? 'last night' : back + ' nights ago';
  }
```

- [ ] **Step 4: Pace template**

Replace the pace `<svg>` block (lines 237-243) with the relative-wrapped version (bands/cross/odots/card, `data-hb="pace"` / `data-card="pace"`), keeping the existing grid, goal line, area, path, and last dot:

```html
      <div style="position:relative">
      <svg viewBox="0 0 600 150" style="width:100%;height:130px;display:block;margin-top:6px" onMouseLeave="{{ pace.onLeave }}">
        <sc-for list="{{ pace.grid }}" as="g" hint-placeholder-count="3"><line x1="0" y1="{{ g }}" x2="600" y2="{{ g }}" stroke="var(--grid)" stroke-width="1"></line></sc-for>
        <line x1="0" y1="{{ pace.goalY }}" x2="600" y2="{{ pace.goalY }}" style="stroke:var(--accent)" stroke-width="1.4" stroke-dasharray="5 5"></line>
        <path d="{{ pace.area }}" style="fill:var(--accentFade)"></path>
        <path d="{{ pace.d }}" fill="none" style="stroke:var(--accent2);vector-effect:non-scaling-stroke" stroke-width="2.4" stroke-linejoin="round"></path>
        <circle cx="{{ pace.lastX }}" cy="{{ pace.lastY }}" r="4" style="fill:var(--accent2)"></circle>
        <sc-for list="{{ pace.bands }}" as="b" hint-placeholder-count="30"><rect data-hb="pace" x="{{ b.x }}" y="{{ b.y }}" width="{{ b.w }}" height="{{ b.h }}" fill="transparent" style="cursor:pointer" onMouseEnter="{{ b.onEnter }}" onClick="{{ b.onClick }}" aria-label="{{ b.aria }}"></rect></sc-for>
        <sc-for list="{{ pace.cross }}" as="c" hint-placeholder-count="0"><line x1="{{ c.x }}" y1="{{ c.top }}" x2="{{ c.x }}" y2="{{ c.bot }}" style="stroke:var(--sub);pointer-events:none" stroke-width="1" stroke-dasharray="3 3"></line></sc-for>
        <sc-for list="{{ pace.odots }}" as="d" hint-placeholder-count="0"><circle cx="{{ d.x }}" cy="{{ d.y }}" r="4.5" style="fill:{{ d.color }};pointer-events:none" stroke="var(--bg)" stroke-width="1.5"></circle></sc-for>
      </svg>
      <sc-for list="{{ pace.card }}" as="cd" hint-placeholder-count="0">
        <div data-card="pace" style="position:absolute;left:{{ cd.left }};top:{{ cd.top }};transform:{{ cd.transform }};pointer-events:none;background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:6px 9px;font-size:11px;line-height:1.35;white-space:nowrap;box-shadow:0 6px 18px rgba(0,0,0,.30);z-index:6">
          <sc-for list="{{ cd.rows }}" as="row" hint-placeholder-count="3"><div style="color:{{ row.color }};font-weight:{{ row.weight }};font-family:'JetBrains Mono',monospace">{{ row.t }}</div></sc-for>
        </div>
      </sc-for>
      </div>
```

- [ ] **Step 5: Cadence template**

Replace the cadence `<svg>` block (lines 268-273) the same way (`data-hb="cad"` / `data-card="cad"`, `onMouseLeave="{{ cad.onLeave }}"`), keeping its grid, area, path, last dot, then the four `sc-for` overlay loops and the card `sc-for` — identical structure to the pace template but with `cad.` bindings and `data-hb="cad"`/`data-card="cad"`.

- [ ] **Step 6: Fitness template**

Replace the fitness `<svg>` block (lines 254-259) the same way (`data-hb="fit"` / `data-card="fit"`, `onMouseLeave="{{ fit.onLeave }}"`), keeping its grid, area, CTL path, and the dashed ATL path. It has **no** existing last-point circle, and its `odots` loop renders the two dots from `fit.odots`:

```html
      <div style="position:relative">
      <svg viewBox="0 0 600 150" style="width:100%;height:130px;display:block;margin-top:6px" onMouseLeave="{{ fit.onLeave }}">
        <sc-for list="{{ fit.grid }}" as="g" hint-placeholder-count="3"><line x1="0" y1="{{ g }}" x2="600" y2="{{ g }}" stroke="var(--grid)" stroke-width="1"></line></sc-for>
        <path d="{{ fit.area }}" style="fill:var(--accentFade)"></path>
        <path d="{{ fit.d }}" fill="none" style="stroke:var(--accent);vector-effect:non-scaling-stroke" stroke-width="2.4" stroke-linejoin="round"></path>
        <path d="{{ fit.atl }}" fill="none" style="stroke:var(--accent2);vector-effect:non-scaling-stroke" stroke-width="2" stroke-dasharray="4 4" stroke-linejoin="round"></path>
        <sc-for list="{{ fit.bands }}" as="b" hint-placeholder-count="26"><rect data-hb="fit" x="{{ b.x }}" y="{{ b.y }}" width="{{ b.w }}" height="{{ b.h }}" fill="transparent" style="cursor:pointer" onMouseEnter="{{ b.onEnter }}" onClick="{{ b.onClick }}" aria-label="{{ b.aria }}"></rect></sc-for>
        <sc-for list="{{ fit.cross }}" as="c" hint-placeholder-count="0"><line x1="{{ c.x }}" y1="{{ c.top }}" x2="{{ c.x }}" y2="{{ c.bot }}" style="stroke:var(--sub);pointer-events:none" stroke-width="1" stroke-dasharray="3 3"></line></sc-for>
        <sc-for list="{{ fit.odots }}" as="d" hint-placeholder-count="0"><circle cx="{{ d.x }}" cy="{{ d.y }}" r="4.5" style="fill:{{ d.color }};pointer-events:none" stroke="var(--bg)" stroke-width="1.5"></circle></sc-for>
      </svg>
      <sc-for list="{{ fit.card }}" as="cd" hint-placeholder-count="0">
        <div data-card="fit" style="position:absolute;left:{{ cd.left }};top:{{ cd.top }};transform:{{ cd.transform }};pointer-events:none;background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:6px 9px;font-size:11px;line-height:1.35;white-space:nowrap;box-shadow:0 6px 18px rgba(0,0,0,.30);z-index:6">
          <sc-for list="{{ cd.rows }}" as="row" hint-placeholder-count="3"><div style="color:{{ row.color }};font-weight:{{ row.weight }};font-family:'JetBrains Mono',monospace">{{ row.t }}</div></sc-for>
        </div>
      </sc-for>
      </div>
```

- [ ] **Step 7: Verify live**

Per the shared recipe, for each of `pace`, `cad`, `fit`: click the 6th band, read `[data-card="..."]` innerText. Expect: pace → month / `m:ss /km` / `vs goal`; cad → month / `<n> spm` / `vs prev`; fit → `<n> wks ago` / `CTL <n> / ATL <n>` / `Form ±<n>`, and assert **two** hover dots render for fitness (`document.querySelectorAll('#root circle[r="4.5"]').length` ≥ 2 while fit is pinned). Console errors at baseline.

- [ ] **Step 8: Commit**

```bash
git add "Running Dashboard.dc.html"
git commit -m "feat: datapoint hover on pace, cadence, and fitness charts"
```

---

### Task 4: Wire the weekly-volume bars and the sleep chart

Bars and the sleep chart are not line vertices — points sit at bar centres. Volume is one value per week; sleep shows hours **and** HRV per night.

**Files:**
- Modify: `Running Dashboard.dc.html` — `renderVals` (volume ~line 576, sleep ~line 612) and the templates (volume 208-211, sleep 299-303).

**Interfaces:**
- Consumes: `hoverLayer`, `attachOverlay`, `relLabel`, the hover handlers.

- [ ] **Step 1: Volume points + overlay**

In the `vol` object build (lines 576-580), the bars already have `x`, `w`, `y`. After the `vol` object is assigned (after line 580), add points at each bar centre (top of the bar):

```js
    const volN = H.weeklyKm.length;
    const volPts = vol.bars.map((b, i) => ({
      x: b.x + b.w / 2, y: b.y, dotColor: 'var(--accent2)',
      aria: 'Week ' + this.relLabel(i, volN, 'wk') + ', ' + H.weeklyKm[i].toFixed(1) + ' km',
      lines: [
        { t: this.relLabel(i, volN, 'wk'), em: false },
        { t: H.weeklyKm[i].toFixed(1) + ' km', em: true },
        { t: i > 0 ? ((H.weeklyKm[i] - H.weeklyKm[i-1] >= 0 ? '+' : '−') + Math.abs(Math.round(H.weeklyKm[i] - H.weeklyKm[i-1])) + ' vs prev') : 'first week', em: false }
      ]
    }));
    this.attachOverlay(vol, this.hoverLayer('vol', volPts));
    vol.onLeave = () => this.leaveChart('vol');
```

- [ ] **Step 2: Sleep points + overlay**

The sleep chart uses its own scales (`sbw`, `sslot`, bars + `hX`/`hY` for HRV). Points sit at each night's bar centre. After `sleepObj` is built (after line 615), add:

```js
    const sleepPts = sleepBars.map((b, i) => ({
      x: b.x + b.w / 2, y: sDots[i].y,
      dots: [
        { x: +(b.x + b.w / 2).toFixed(2), y: +b.y.toFixed(2), color: 'var(--accentFade)' },
        { x: +sDots[i].x.toFixed(2), y: +sDots[i].y.toFixed(2), color: 'var(--accent2)' }
      ],
      aria: 'Night ' + this.relLabel(i, sN, 'night') + ', ' + sl[i].hours.toFixed(1) + ' hours, HRV ' + sl[i].hrv,
      lines: [
        { t: this.relLabel(i, sN, 'night'), em: false },
        { t: sl[i].hours.toFixed(1) + ' h', em: true },
        { t: 'HRV ' + sl[i].hrv + ' ms', em: false }
      ]
    }));
    this.attachOverlay(sleepObj, this.hoverLayer('sleep', sleepPts));
    sleepObj.onLeave = () => this.leaveChart('sleep');
```

- [ ] **Step 3: Volume template**

Replace the volume chart block (lines 208-211) with the relative-wrapped version — keep the grid + bars, add a brightened-bar highlight (the hovered bar re-drawn from `vol.odots` is just a dot; for bars, the crosshair at the bar centre is the highlight). Use `data-hb="vol"` / `data-card="vol"`:

```html
    <div style="position:relative">
    <svg viewBox="0 0 600 150" style="width:100%;height:140px;display:block" onMouseLeave="{{ vol.onLeave }}">
      <sc-for list="{{ vol.grid }}" as="g" hint-placeholder-count="3"><line x1="0" y1="{{ g }}" x2="600" y2="{{ g }}" stroke="var(--grid)" stroke-width="1"></line></sc-for>
      <sc-for list="{{ vol.bars }}" as="b" hint-placeholder-count="26"><rect x="{{ b.x }}" y="{{ b.y }}" width="{{ b.w }}" height="{{ b.h }}" rx="2" style="fill:{{ b.fill }}"></rect></sc-for>
      <sc-for list="{{ vol.bands }}" as="b" hint-placeholder-count="26"><rect data-hb="vol" x="{{ b.x }}" y="{{ b.y }}" width="{{ b.w }}" height="{{ b.h }}" fill="transparent" style="cursor:pointer" onMouseEnter="{{ b.onEnter }}" onClick="{{ b.onClick }}" aria-label="{{ b.aria }}"></rect></sc-for>
      <sc-for list="{{ vol.cross }}" as="c" hint-placeholder-count="0"><line x1="{{ c.x }}" y1="{{ c.top }}" x2="{{ c.x }}" y2="{{ c.bot }}" style="stroke:var(--ink);pointer-events:none;opacity:.5" stroke-width="1.5"></line></sc-for>
      <sc-for list="{{ vol.odots }}" as="d" hint-placeholder-count="0"><circle cx="{{ d.x }}" cy="{{ d.y }}" r="4.5" style="fill:{{ d.color }};pointer-events:none" stroke="var(--bg)" stroke-width="1.5"></circle></sc-for>
    </svg>
    <sc-for list="{{ vol.card }}" as="cd" hint-placeholder-count="0">
      <div data-card="vol" style="position:absolute;left:{{ cd.left }};top:{{ cd.top }};transform:{{ cd.transform }};pointer-events:none;background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:6px 9px;font-size:11px;line-height:1.35;white-space:nowrap;box-shadow:0 6px 18px rgba(0,0,0,.30);z-index:6">
        <sc-for list="{{ cd.rows }}" as="row" hint-placeholder-count="3"><div style="color:{{ row.color }};font-weight:{{ row.weight }};font-family:'JetBrains Mono',monospace">{{ row.t }}</div></sc-for>
      </div>
    </sc-for>
    </div>
```

- [ ] **Step 4: Sleep template**

Replace the sleep `<svg>` block (lines 299-303) the same way (`data-hb="sleep"` / `data-card="sleep"`, `onMouseLeave="{{ sleep.onLeave }}"`), keeping its bars, HRV path, and HRV dots, then the bands / cross / odots / card loops (same structure as the volume template, with `sleep.` bindings and `hint-placeholder-count="14"` on the bands).

- [ ] **Step 5: Verify live**

Per the recipe: click the 6th `vol` band → card shows `<n> wks ago` / `<n> km` / `vs prev`; click the 6th `sleep` band → card shows `<n> nights ago` / `<n> h` / `HRV <n> ms`, and assert sleep renders **two** hover dots. Volume crosshair uses the brighter `--ink` stroke. Console errors at baseline.

- [ ] **Step 6: Commit**

```bash
git add "Running Dashboard.dc.html"
git commit -m "feat: datapoint hover on weekly-volume bars and sleep chart"
```

---

### Task 5: Wire the heatmap and the readiness ring

The heatmap has 365 discrete cells (the cells **are** the hit targets — no bands); the ring is a single composite target. Both reuse `cardPlace` for the HTML card; neither uses `bandRects`.

**Files:**
- Modify: `Running Dashboard.dc.html` — `renderVals` (heatmap ~line 618-627, ring ~line 534-535) and the templates (heatmap 319-324, ring 93-98).

**Interfaces:**
- Consumes: `cardPlace`, `hoverLayer` (ring only), the hover handlers.

- [ ] **Step 1: Heatmap cells get handlers + date/label, plus the hovered-cell outline and card**

In the heatmap loop (lines 620-626), give each pushed cell its index, date label, km, and handlers, and build the overlay from `state.hover`. Replace the cells loop body and the `heat` assembly (lines 620-627) with:

```js
    const cells=[]; const months=[]; let col=0, lastMonth=-1; const CELL=13, TOP=14;
    const WD=['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
    for(let i=0;i<km.length;i++){ const dt=new Date(start); dt.setDate(start.getDate()+i); const dow=dt.getDay(); const row=(dow+6)%7;
      if(i>0 && row===0) col++;
      const v=km[i]; const lvl = v===0?0 : v<6?1 : v<9?2 : v<14?3 : 4;
      const cx = col*CELL, cy = TOP+row*CELL;
      cells.push({ x:cx, y:cy, fill:'var(--hm'+lvl+')',
        onEnter: () => this.hoverPoint('heat', i),
        onClick: (e) => this.pinPoint('heat', i, e),
        aria: WD[dow]+' '+M[dt.getMonth()]+' '+dt.getDate()+', '+(v>0?v.toFixed(1)+' km':'rest') });
      if(dt.getMonth()!==lastMonth && row<=1){ lastMonth=dt.getMonth(); months.push({ x:col*CELL, label:M[dt.getMonth()] }); }
    }
    const heatW=(col+1)*CELL+4, heatH=TOP+7*CELL;
    const heat = { cells, months, w:heatW, h:heatH, totalKm:Math.round(km.reduce((a,b)=>a+b,0)), runDays:km.filter(v=>v>0).length };
    const hh = this.state.hover;
    if (this._ch && hh && hh.chart === 'heat' && hh.i >= 0 && hh.i < cells.length) {
      const c = cells[hh.i]; const dt = new Date(start); dt.setDate(start.getDate()+hh.i); const v = km[hh.i];
      const pl = this._ch.cardPlace(c.x + CELL/2, c.y + CELL/2, heatW, heatH);
      const tx = pl.anchorX === 'left' ? '0' : pl.anchorX === 'right' ? '-100%' : '-50%';
      const ty = pl.place === 'above' ? 'calc(-100% - 9px)' : '9px';
      heat.outline = [{ x:c.x-1, y:c.y-1 }];
      heat.card = [{ left: pl.leftPct+'%', top: pl.topPct+'%', transform:'translate('+tx+', '+ty+')',
        rows: [
          { t: WD[dt.getDay()]+' '+M[dt.getMonth()]+' '+dt.getDate(), color:'var(--sub)', weight:'600' },
          { t: v>0 ? v.toFixed(1)+' km' : 'rest', color:'var(--ink)', weight:'800' }
        ] }];
    } else { heat.outline = []; heat.card = []; }
    heat.onLeave = () => this.leaveChart('heat');
```

(Note: `M` is the month-name array already defined at line 619; `WD` is new. `start` is defined at line 618.)

- [ ] **Step 2: Heatmap template**

Replace the heatmap block (lines 319-324) — wrap the scroll container's `<svg>` in `position:relative`, wire `onMouseEnter`/`onClick` on each cell, add the outline rect and the card. The card lives **inside** the relative wrapper (so it scrolls with the heatmap):

```html
    <div style="overflow-x:auto;padding-bottom:4px">
      <div style="position:relative;width:{{ heat.w }}px">
      <svg width="{{ heat.w }}" height="{{ heat.h }}" style="display:block" onMouseLeave="{{ heat.onLeave }}">
        <sc-for list="{{ heat.months }}" as="m" hint-placeholder-count="12"><text x="{{ m.x }}" y="9" fill="var(--sub)" style="font:600 9px 'Archivo'">{{ m.label }}</text></sc-for>
        <sc-for list="{{ heat.cells }}" as="c" hint-placeholder-count="200"><rect data-hb="heat" x="{{ c.x }}" y="{{ c.y }}" width="11" height="11" rx="2.5" style="fill:{{ c.fill }};cursor:pointer" onMouseEnter="{{ c.onEnter }}" onClick="{{ c.onClick }}" aria-label="{{ c.aria }}"></rect></sc-for>
        <sc-for list="{{ heat.outline }}" as="o" hint-placeholder-count="0"><rect x="{{ o.x }}" y="{{ o.y }}" width="13" height="13" rx="3" fill="none" style="stroke:var(--ink);pointer-events:none" stroke-width="1.5"></rect></sc-for>
      </svg>
      <sc-for list="{{ heat.card }}" as="cd" hint-placeholder-count="0">
        <div data-card="heat" style="position:absolute;left:{{ cd.left }};top:{{ cd.top }};transform:{{ cd.transform }};pointer-events:none;background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:6px 9px;font-size:11px;line-height:1.35;white-space:nowrap;box-shadow:0 6px 18px rgba(0,0,0,.30);z-index:6">
          <sc-for list="{{ cd.rows }}" as="row" hint-placeholder-count="2"><div style="color:{{ row.color }};font-weight:{{ row.weight }};font-family:'JetBrains Mono',monospace">{{ row.t }}</div></sc-for>
        </div>
      </sc-for>
      </div>
    </div>
```

- [ ] **Step 3: Ring points + overlay**

The ring is one target. After the `ring` object (line 535), add a single-point hover layer over the 120×120 ring viewBox (no crosshair, no dot — `dots: []`, `crosshair:false`):

```js
    const rd = D.readiness;
    const ringPts = [{
      x: 60, y: 60, dots: [],
      aria: 'Readiness ' + rd.score + ', ' + rd.status,
      lines: [
        { t: 'Readiness ' + rd.score + ' · ' + rd.status, em: true },
        { t: 'HRV ' + rd.hrv + ' · RHR ' + rd.restingHR, em: false },
        { t: 'Sleep ' + rd.sleepHours + ' h · Load ' + rd.trainingLoad, em: false }
      ]
    }];
    const ringHL = this.hoverLayer('ring', ringPts, { vbW: 120, vbH: 120, crosshair: false });
    const ringObj = {}; this.attachOverlay(ringObj, ringHL); ringObj.onLeave = () => this.leaveChart('ring');
```

Add `ring: ringObj` (the overlay holder) to the returned object (line 649, next to `ring`). Keep the existing `ring` (the dasharray geometry) under its current name — rename the new holder to avoid the collision: call it `ringHover` in the return and template. Update the return object: add `ringHover: ringObj`.

- [ ] **Step 4: Ring template**

In the readiness block (lines 93-98), wrap the ring `<svg>` in `position:relative`, add an invisible hit-circle (`fill="transparent"`) wired to the single band, and the card. The ring has one band (`ringHover.bands[0]`):

```html
        <div style="position:relative;flex:none">
        <svg viewBox="0 0 120 120" style="width:108px;height:108px;display:block" onMouseLeave="{{ ringHover.onLeave }}">
          <circle cx="60" cy="60" r="50" fill="none" stroke="var(--line)" stroke-width="11"></circle>
          <circle cx="60" cy="60" r="50" fill="none" stroke="var(--accent)" stroke-width="11" stroke-linecap="round" stroke-dasharray="{{ ring.c }}" stroke-dashoffset="{{ ring.off }}" transform="rotate(-90 60 60)"></circle>
          <text x="60" y="58" text-anchor="middle" fill="var(--ink)" style="font:900 30px 'JetBrains Mono'">{{ readiness.score }}</text>
          <text x="60" y="76" text-anchor="middle" fill="var(--accent)" style="font:700 11px 'Archivo';letter-spacing:.12em">{{ readiness.status }}</text>
          <sc-for list="{{ ringHover.bands }}" as="b" hint-placeholder-count="1"><circle data-hb="ring" cx="60" cy="60" r="58" fill="transparent" style="cursor:pointer" onMouseEnter="{{ b.onEnter }}" onClick="{{ b.onClick }}" aria-label="{{ b.aria }}"></circle></sc-for>
        </svg>
        <sc-for list="{{ ringHover.card }}" as="cd" hint-placeholder-count="0">
          <div data-card="ring" style="position:absolute;left:{{ cd.left }};top:{{ cd.top }};transform:{{ cd.transform }};pointer-events:none;background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:6px 9px;font-size:11px;line-height:1.35;white-space:nowrap;box-shadow:0 6px 18px rgba(0,0,0,.30);z-index:6">
            <sc-for list="{{ cd.rows }}" as="row" hint-placeholder-count="3"><div style="color:{{ row.color }};font-weight:{{ row.weight }};font-family:'JetBrains Mono',monospace">{{ row.t }}</div></sc-for>
          </div>
        </sc-for>
        </div>
```

(The band uses a `<circle>` rather than a `<rect>`, so `bandRects`' rect output is ignored for the ring — only `bands[0].onEnter`/`onClick`/`aria` are used. The single full band from `bandRects` maps 1:1 to this circle.)

- [ ] **Step 5: Verify live**

Per the recipe: click a heatmap cell (`document.querySelectorAll('[data-hb="heat"]')[200]`) → `[data-card="heat"]` shows `Wkd Mon DD` / `<n> km` or `rest`; assert the outline rect renders. Click the ring band (`[data-hb="ring"]`) → `[data-card="ring"]` shows the three readiness rows. Confirm the heatmap card scrolls with the grid (it's inside the relative wrapper). Console errors at baseline.

- [ ] **Step 6: Commit**

```bash
git add "Running Dashboard.dc.html"
git commit -m "feat: datapoint hover on heatmap cells and readiness ring"
```

---

### Task 6: Wire the drill-down sparklines

The two 26 px sparklines inside an expanded run row (per-km splits, HR drift) get the same treatment. Because the card is HTML it is not clipped by the 26 px `<svg>` — it sits above the spark in the detail strip via the normal `place` flip.

**Files:**
- Modify: `Running Dashboard.dc.html` — `runDetail()` (lines 410-424) and the detail-strip template (lines 350-356).

**Interfaces:**
- Consumes: `hoverLayer`, `attachOverlay`, `line().pts`, `fmtPace`, the hover handlers. Chart ids `'splits'` and `'drift'` (unique because only one run is expanded at a time).

- [ ] **Step 1: Build sparkline points + overlays in `runDetail`**

Extend `runDetail` (lines 410-424). After computing `hs` and `sp`, build the two hover layers and attach them. Replace the `return { ... }` with one that includes `splits*`/`drift*` overlay fields:

```js
  runDetail = (r) => {
    const d = r.detail;
    const hs = (d.hrSeries && d.hrSeries.length) ? d.hrSeries : [0, 0];
    const sp = (d.splits && d.splits.length) ? d.splits.map(s => s.pace) : [0, 0];
    const zsum = (d.zoneMin || []).reduce((a, b) => a + b, 0) || 1;
    const spL = this.line(sp, 30, { padT: 2, padB: 2 });
    const hsL = this.line(hs, 30, { padT: 2, padB: 2 });
    const spPts = spL.pts.map((p, i) => ({
      x: p[0], y: p[1], dotColor: 'var(--accent)',
      aria: 'Km ' + (i + 1) + ', ' + this.fmtPace(sp[i]) + ' per km',
      lines: [ { t: 'km ' + (i + 1), em: false }, { t: this.fmtPace(sp[i]) + ' /km', em: true } ]
    }));
    const hsPts = hsL.pts.map((p, i) => ({
      x: p[0], y: p[1], dotColor: 'var(--accent2)',
      aria: 'Segment ' + (i + 1) + ', ' + hs[i] + ' bpm',
      lines: [ { t: 'seg ' + (i + 1), em: false }, { t: hs[i] + ' bpm', em: true } ]
    }));
    const splits = {}; this.attachOverlay(splits, this.hoverLayer('splits', spPts, { vbW: 600, vbH: 30 })); splits.onLeave = () => this.leaveChart('splits');
    const drift = {}; this.attachOverlay(drift, this.hoverLayer('drift', hsPts, { vbW: 600, vbH: 30 })); drift.onLeave = () => this.leaveChart('drift');
    return {
      read: r.read || (r.km + ' km'),
      drift: d.driftBpm != null ? ((d.driftBpm >= 0 ? '+' : '') + d.driftBpm + ' bpm') : '—',
      hrStart: hs[0], hrEnd: hs[hs.length - 1],
      hrPath: hsL.d,
      spPath: spL.d,
      zones: (d.zoneMin || []).map((m, i) => ({ pct: Math.round(m / zsum * 100), color: 'var(--z' + (i + 1) + ')' })),
      te: d.te != null ? (+d.te).toFixed(1) : '—', temp: d.tempC != null ? d.tempC : '—',
      sp: splits, dr: drift
    };
  };
```

- [ ] **Step 2: Sparkline templates in the detail strip**

In the detail strip (lines 350-356), wrap each sparkline `<svg>` in `position:relative`, add bands + crosshair + dot + the HTML card. Splits block (lines 350-352) becomes:

```html
                <div>
                  <div style="font-size:9.5px;color:var(--sub);font-weight:700;margin-bottom:4px">SPLITS /km</div>
                  <div style="position:relative">
                  <svg viewBox="0 0 600 30" style="width:100%;height:26px;display:block;overflow:visible" onMouseLeave="{{ dv.sp.onLeave }}">
                    <path d="{{ dv.spPath }}" fill="none" style="stroke:var(--accent);vector-effect:non-scaling-stroke" stroke-width="2" stroke-linejoin="round"></path>
                    <sc-for list="{{ dv.sp.bands }}" as="b" hint-placeholder-count="20"><rect data-hb="splits" x="{{ b.x }}" y="{{ b.y }}" width="{{ b.w }}" height="{{ b.h }}" fill="transparent" style="cursor:pointer" onMouseEnter="{{ b.onEnter }}" onClick="{{ b.onClick }}" aria-label="{{ b.aria }}"></rect></sc-for>
                    <sc-for list="{{ dv.sp.cross }}" as="c" hint-placeholder-count="0"><line x1="{{ c.x }}" y1="{{ c.top }}" x2="{{ c.x }}" y2="{{ c.bot }}" style="stroke:var(--sub);pointer-events:none" stroke-width="1" stroke-dasharray="3 3"></line></sc-for>
                    <sc-for list="{{ dv.sp.odots }}" as="d" hint-placeholder-count="0"><circle cx="{{ d.x }}" cy="{{ d.y }}" r="3.5" style="fill:{{ d.color }};pointer-events:none" stroke="var(--bg)" stroke-width="1.2"></circle></sc-for>
                  </svg>
                  <sc-for list="{{ dv.sp.card }}" as="cd" hint-placeholder-count="0">
                    <div data-card="splits" style="position:absolute;left:{{ cd.left }};top:{{ cd.top }};transform:{{ cd.transform }};pointer-events:none;background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:5px 8px;font-size:10.5px;line-height:1.3;white-space:nowrap;box-shadow:0 6px 18px rgba(0,0,0,.30);z-index:7">
                      <sc-for list="{{ cd.rows }}" as="row" hint-placeholder-count="2"><div style="color:{{ row.color }};font-weight:{{ row.weight }};font-family:'JetBrains Mono',monospace">{{ row.t }}</div></sc-for>
                    </div>
                  </sc-for>
                  </div>
                </div>
```

Apply the same structure to the HR-drift block (lines 353-356) with `dv.dr` bindings, `data-hb="drift"`, `data-card="drift"`, and the existing `hrPath`/header (`HR {{ dv.hrStart }} → {{ dv.hrEnd }} ({{ dv.drift }})`).

- [ ] **Step 3: Verify live**

Per the recipe: click a run row to expand it (`document.querySelectorAll('[role="button"]')` — the run rows; click index 0), then click the 4th `splits` band → `[data-card="splits"]` shows `km 4` / `m:ss /km`; click a `drift` band → `[data-card="drift"]` shows `seg <n>` / `<n> bpm`. Confirm the card escapes above the 26 px spark (not clipped). Collapse the run and confirm no stale card. Console errors at baseline.

- [ ] **Step 4: Commit**

```bash
git add "Running Dashboard.dc.html"
git commit -m "feat: datapoint hover on the drill-down sparklines"
```

---

### Task 7: Keyboard navigation + screen-reader readout

One tab stop per chart; arrow keys move the datapoint; Enter pins, Escape dismisses; an `aria-live` region announces the focused point.

**Files:**
- Modify: `Running Dashboard.dc.html` — add `chartKey`/`heatKey` handlers; add `tabIndex`/`role`/`aria-label`/`onKeyDown` to each chart `<svg>` (or ring/heatmap wrapper); add `liveText` to `renderVals` and an `aria-live` region to the template.

**Interfaces:**
- Consumes: `state.hover`, all per-chart point arrays (their lengths). Each chart's view-model object gains `navN` (point count) so the template can pass it to the key handler — but handlers are wired as closures, so instead expose `obj.onKey` per chart.

- [ ] **Step 1: Add key handlers**

After `dismissHover` (Task 2), add:

```js
  chartKey = (chart, n, e) => {
    const k = e.key; const h = this.state.hover;
    const cur = (h && h.chart === chart) ? h.i : -1;
    if (k === 'ArrowRight' || k === 'ArrowUp') { if (e.preventDefault) e.preventDefault(); this.setState({ hover: { chart, i: Math.min(n - 1, cur + 1), pinned: true } }); }
    else if (k === 'ArrowLeft' || k === 'ArrowDown') { if (e.preventDefault) e.preventDefault(); this.setState({ hover: { chart, i: cur <= 0 ? 0 : cur - 1, pinned: true } }); }
    else if (k === 'Escape') { this.setState({ hover: null }); }
    else if (k === 'Enter' || k === ' ') { if (e.preventDefault) e.preventDefault(); this.setState({ hover: { chart, i: cur < 0 ? 0 : cur, pinned: true } }); }
  };
  heatKey = (n, e) => {
    const k = e.key; const h = this.state.hover;
    const cur = (h && h.chart === 'heat') ? h.i : -1;
    const step = (k === 'ArrowUp' || k === 'ArrowDown') ? 7 : 1;
    if (k === 'ArrowRight' || k === 'ArrowDown') { if (e.preventDefault) e.preventDefault(); this.setState({ hover: { chart: 'heat', i: Math.min(n - 1, (cur < 0 ? 0 : cur) + step), pinned: true } }); }
    else if (k === 'ArrowLeft' || k === 'ArrowUp') { if (e.preventDefault) e.preventDefault(); this.setState({ hover: { chart: 'heat', i: Math.max(0, (cur < 0 ? 0 : cur) - step), pinned: true } }); }
    else if (k === 'Escape') { this.setState({ hover: null }); }
  };
```

- [ ] **Step 2: Expose per-chart `onKey` + `navLabel` and the live readout**

For each chart object in `renderVals`, set `onKey` and an `aria-label` summary. Add right after each `attachOverlay(...)` call (one line each):

```js
    vo2.onKey = (e) => this.chartKey('vo2', vo2pts.length, e); vo2.navLabel = 'VO2 max over 30 months, ' + vo2pts.length + ' points. Arrow keys to inspect.';
    pace.onKey = (e) => this.chartKey('pace', pacePts.length, e); pace.navLabel = 'Average run pace over 30 months. Arrow keys to inspect.';
    cad.onKey = (e) => this.chartKey('cad', cadPts.length, e); cad.navLabel = 'Cadence over 30 months. Arrow keys to inspect.';
    fit.onKey = (e) => this.chartKey('fit', fitPts.length, e); fit.navLabel = 'Fitness and fatigue over 26 weeks. Arrow keys to inspect.';
    vol.onKey = (e) => this.chartKey('vol', volPts.length, e); vol.navLabel = 'Weekly volume over 26 weeks. Arrow keys to inspect.';
    sleepObj.onKey = (e) => this.chartKey('sleep', sleepPts.length, e); sleepObj.navLabel = 'Sleep and HRV over 14 nights. Arrow keys to inspect.';
    ringObj.onKey = (e) => this.chartKey('ring', 1, e); ringObj.navLabel = 'Readiness ring. Enter to read the breakdown.';
    heat.onKey = (e) => this.heatKey(heat.cells.length, e); heat.navLabel = 'Running heatmap, 365 days. Arrow keys by day, up and down by week.';
```

Add a `liveText` to the returned object — the current hovered point's first two card rows, joined — computed near the end of `renderVals` (before the `return`):

```js
    let liveText = '';
    { const h = this.state.hover; const reg = { vo2:vo2, pace:pace, cad:cad, fit:fit, vol:vol, sleep:sleepObj, heat:heat, ring:ringObj };
      if (h && reg[h.chart] && reg[h.chart].card && reg[h.chart].card.length) liveText = reg[h.chart].card[0].rows.map(r => r.t).join(', '); }
```

Add `liveText` to the return object (line ~651).

- [ ] **Step 3: Add a11y attributes to each chart + the live region in the template**

On each chart `<svg>` (vo2, pace, cad, fit, vol, sleep) add: `tabIndex="0" role="img" aria-label="{{ <obj>.navLabel }}" onKeyDown="{{ <obj>.onKey }}"`. On the heatmap `<svg>` add the same with `heat.navLabel`/`heat.onKey`. On the ring `<svg>` add `tabIndex="0" role="img" aria-label="{{ ringHover.navLabel }}" onKeyDown="{{ ringHover.onKey }}"` (note: the ring overlay holder is `ringHover` in the template; expose `navLabel`/`onKey` on `ringObj`).

Add a visually-hidden live region once, just inside the root container (after the opening of the outermost styled `<div>`, near line 91 or at the top of the dashboard body):

```html
  <div aria-live="polite" style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap">{{ liveText }}</div>
```

- [ ] **Step 4: Verify live (keyboard + SR)**

Per the recipe, drive keys with `browser_evaluate`:

```js
() => {
  const svg = document.querySelector('svg[aria-label^="VO2 max"]');
  svg.focus();
  svg.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
  svg.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
  const card = document.querySelector('[data-card="vo2"]');
  const live = document.querySelector('[aria-live="polite"]').innerText;
  return { card: card ? card.innerText.replace(/\n/g,' | ') : 'NONE', live };
}
```

Expected: after two ArrowRight the VO₂ card shows index 1's content and `live` mirrors it; `Escape` clears; the heatmap ArrowDown jumps 7 days. Confirm each chart `<svg>` is reachable by Tab (one stop per chart). Console errors at baseline.

- [ ] **Step 5: Commit**

```bash
git add "Running Dashboard.dc.html"
git commit -m "feat: keyboard navigation and SR readout for datapoint hover"
```

---

### Task 8: Document and final sweep

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the README**

In the file table (around `coach-read.js`'s row, line 16), add a row after it:

```markdown
| `chart-hover.js` | **The inspection layer.** Pure `bandRects` + `cardPlace` geometry behind the hover/tap crosshair-and-card that every chart, the heatmap, and the ring show for each datapoint. |
```

And under the dashboard description (after the themes line, ~line 52), add one sentence:

```markdown
Every chart is **interactive**: hover (or tap) any point — on a line, a bar, the
heatmap, the ring, or a run's sparkline — for a crosshair and a card with that
point's date, value, and context. Charts are keyboard-navigable (Tab to a chart,
arrow keys to inspect).
```

- [ ] **Step 2: Full regression sweep**

- Run `node test_chart_hover.mjs` → `ALL PASS`.
- Run `node test_coach_read.mjs` → `ALL PASS` (unchanged, confirms no collateral breakage).
- Live: load the dashboard, and for each of the 10 chart ids (`vo2 pace cad fit vol sleep heat ring splits drift`) confirm a card appears on hover/click and clears on leave/dismiss. Confirm theme switching clears any open card. Confirm console errors remain at the pre-feature baseline count.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document datapoint interactivity in the README"
```

---

## Self-Review

**1. Spec coverage:**
- Trigger hover+tap → Task 2 handlers (`hoverPoint`/`pinPoint`/`leaveChart`/`dismissHover`). ✓
- All 9 surfaces → Tasks 2 (vo2), 3 (pace/cad/fit), 4 (vol/sleep), 5 (heat/ring), 6 (splits/drift). ✓
- Crosshair + dot + card → Task 2 overlay + every wiring task. ✓
- HTML card, percentage-positioned, `cardPlace` → Task 1 + Task 2 `hoverLayer`. ✓
- `bandRects`/`cardPlace` pure + tested → Task 1. ✓
- `line()` returns `pts` → Task 2 Step 3. ✓
- Labels exact (monthly/daily/per-run) + relative (weekly/nightly) → `monthLabel` (Task 2), heatmap date (Task 5), `relLabel` (Tasks 3/4), km/seg (Task 6). ✓
- Edge cases: `pointer-events:none` overlay (every card + cross/odot), paint order (data→bands→overlay), n≤1 (`bandRects`), rest days (Task 5 `rest`), index bounds (`hoverLayer` guard `h.i < points.length`, heatmap guard), clear-on-change (Task 2). ✓
- Accessibility one-tab-stop + arrows + aria-live → Task 7. ✓
- Testing unit + live-`evaluate` → Task 1 + shared recipe. ✓
- No backend change → no task touches Python/data files. ✓

**2. Placeholder scan:** No TBD/TODO. Every code step shows full code; the repeated template (pace/cad/sleep) is fully written for at least one instance and the deltas are explicit (binding prefix + `data-hb`/`data-card` id). Cadence/sleep Steps say "same structure as <the one shown> with these exact substitutions" — the full structure is shown in the same task, so the engineer has it in front of them.

**3. Type consistency:** `points` item shape `{x,y,dots?,dotColor?,lines:[{t,em}],aria?}` is identical across Tasks 2-6. `hoverLayer` return `{bands, overlay}` and `attachOverlay` outputs (`bands`/`cross`/`odots`/`card`) are consumed identically in every template. `cardPlace`/`bandRects` signatures match Task 1 ⇄ Task 2 usage. Chart ids (`vo2 pace cad fit vol sleep heat ring splits drift`) are consistent between handlers, view-model, `data-hb`/`data-card`, and verification. The ring's overlay holder is consistently `ringObj` in JS / `ringHover` in the template (the one rename, called out in Tasks 5 & 7).
