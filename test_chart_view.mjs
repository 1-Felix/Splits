// test_chart_view.mjs — renderChart against a STUB React (chart-engine 4.4).
// No react dependency: createElement returns a plain tree; the assertions walk
// it. This proves structure, ARIA and keyboard wiring; pixels stay covered by
// the Playwright style audit.
import assert from "node:assert";
import { renderChart } from "./chart-view.js";
import { buildSpec, POLICIES, monthKeyToDate } from "./chart-core.js";

const React = {
  createElement: (type, props, ...children) => ({ type, props: props || {}, children: children.flat().filter((c) => c != null) }),
};

// depth-first collect of nodes matching a predicate (descends into strings too)
function collect(node, pred, out = []) {
  if (node == null || typeof node !== "object") return out;
  if (pred(node)) out.push(node);
  for (const c of node.children || []) collect(c, pred, out);
  return out;
}
const text = (node) => (node.children || []).filter((c) => typeof c === "string" || typeof c === "number").join("");

function demoSpec(overrides = {}) {
  const months = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"];
  const dates = months.map(monthKeyToDate);
  const values = [44.1, 44.4, null, 44.9, 45.2, 45.0];
  return buildSpec({
    id: "vo2", ariaLabel: "VO2 max, monthly. Arrow keys to inspect.",
    height: "130px",
    x: { kind: "time", dates },
    y: { policy: POLICIES.vo2 },
    series: [{ key: "vo2", name: "VO₂", color: "var(--series1)", values }],
    hoverPoints: values.map((v, i) => (v == null ? null : { i, aria: "month " + i, lines: [{ t: "m" + i, em: false }, { t: String(v), em: true }] })).filter(Boolean),
    hover: { index: null, onEnter: () => {}, onPin: () => {}, onKey: () => {}, onLeave: () => {} },
    ...overrides,
  });
}

// ── axis text nodes exist (labels are HTML overlays, crisp at any width) ─────
{
  const el = renderChart(demoSpec(), React);
  const yticks = collect(el, (n) => n.props.className === "chart-ytick");
  const xticks = collect(el, (n) => n.props.className === "chart-xtick");
  assert.ok(yticks.length >= 2, "y tick labels render");
  assert.ok(xticks.length >= 2, "x tick labels render");
  for (const t of [...yticks, ...xticks]) assert.ok(text(t).length > 0, "tick label carries text");
  // gridlines exist per y tick, at tick positions — not fixed-pixel decoration
  const grid = collect(el, (n) => n.type === "line" && n.props.stroke === "var(--grid)");
  assert.strictEqual(grid.length, yticks.length, "one gridline per y tick");
}

// ── a null month yields separate paths, never a bridge ───────────────────────
{
  const el = renderChart(demoSpec(), React);
  const seriesPaths = collect(el, (n) => n.type === "path" && n.props.style && n.props.style.stroke === "var(--series1)");
  assert.strictEqual(seriesPaths.length, 2, "the gap splits the line into two paths");
}

// ── legend appears only at ≥ 2 series, and its text wears ink tokens ─────────
{
  const one = renderChart(demoSpec(), React);
  assert.strictEqual(collect(one, (n) => n.props.className === "chart-legend").length, 0, "single series: no legend");

  const months = ["2026-01", "2026-02", "2026-03"];
  const dates = months.map(monthKeyToDate);
  const two = renderChart(buildSpec({
    id: "fit", ariaLabel: "Fitness and fatigue",
    x: { kind: "time", dates },
    y: { policy: POLICIES.fitnessFatigue },
    series: [
      { key: "ctl", name: "Fitness", color: "var(--series1)", values: [30, 32, 34] },
      { key: "atl", name: "Fatigue", color: "var(--series2)", values: [28, 35, 30] },
    ],
  }), React);
  const legends = collect(two, (n) => n.props.className === "chart-legend");
  assert.strictEqual(legends.length, 1, "two series: legend renders");
  const items = collect(two, (n) => n.props.className === "chart-legend-item");
  assert.strictEqual(items.length, 2);
  for (const it of items) {
    assert.ok(!(it.props.style && it.props.style.color), "legend text is not coloured with the series colour");
    const swatch = collect(it, (n) => n.props.style && n.props.style.background && String(n.props.style.background).startsWith("var(--series"));
    assert.strictEqual(swatch.length, 1, "identity is carried by the swatch beside the name");
  }
}

// ── ARIA + keyboard wiring (the inherited accessibility contract) ────────────
{
  const spec = demoSpec();
  const el = renderChart(spec, React);
  const svgs = collect(el, (n) => n.type === "svg");
  assert.strictEqual(svgs.length, 1);
  const svg = svgs[0];
  assert.strictEqual(svg.props.role, "img");
  assert.strictEqual(svg.props["aria-label"], "VO2 max, monthly. Arrow keys to inspect.");
  assert.strictEqual(svg.props.tabIndex, 0, "chart is focusable");
  assert.strictEqual(typeof svg.props.onKeyDown, "function", "arrow-key navigation is wired");
  assert.strictEqual(typeof svg.props.onMouseLeave, "function");
  assert.strictEqual(svg.props.className, "chart-svg", "focus outline hooks on .chart-svg");
  assert.strictEqual(svg.props["data-chart"], "trend", "audit hook present");

  // hover hit bands: one per hoverable point, with handlers and aria
  const bands = collect(el, (n) => n.props["data-hb"] === "vo2");
  assert.strictEqual(bands.length, 5, "one hit band per valid point");
  for (const b of bands) {
    assert.strictEqual(typeof b.props.onMouseEnter, "function");
    assert.strictEqual(typeof b.props.onClick, "function");
    assert.ok(b.props["aria-label"].startsWith("month"));
  }
}

// ── active hover renders crosshair, dot and the floating card ────────────────
{
  const spec = demoSpec({ hover: { index: 1, pinned: true, onEnter: () => {}, onPin: () => {}, onKey: () => {}, onLeave: () => {} } });
  const el = renderChart(spec, React);
  const cross = collect(el, (n) => n.type === "line" && n.props.strokeDasharray === "3 3" && n.props.style && n.props.style.pointerEvents === "none");
  assert.strictEqual(cross.length, 1, "crosshair renders at the hovered point");
  const cards = collect(el, (n) => n.props["data-card"] === "vo2");
  assert.strictEqual(cards.length, 1, "floating card renders");
  const rows = collect(cards[0], (n) => n.type === "div" && n.props.style && n.props.style.fontFamily);
  assert.strictEqual(rows.length, 2, "card carries the point's rows");
  assert.strictEqual(text(rows[1]), "44.4");
  assert.strictEqual(rows[1].props.style.fontWeight, "800", "emphasised row is bold ink");
}

// ── spark charts: no axis text, no legend, hover intact ──────────────────────
{
  const spec = buildSpec({
    id: "sp", ariaLabel: "splits", kind: "spark",
    frame: { w: 600, h: 30 }, height: "26px",
    x: { kind: "point", n: 4 },
    y: { policy: {} },
    series: [{ key: "s", name: "s", color: "var(--series1)", values: [300, 310, 305, 300] }],
    hoverPoints: [0, 1, 2, 3].map((i) => ({ i, aria: "km " + (i + 1), lines: [] })),
    hover: { index: null, onEnter: () => {}, onPin: () => {} },
  });
  const el = renderChart(spec, React);
  assert.strictEqual(collect(el, (n) => n.props.className === "chart-ytick").length, 0);
  assert.strictEqual(collect(el, (n) => n.props.className === "chart-xtick").length, 0);
  assert.strictEqual(collect(el, (n) => n.props.className === "chart-legend").length, 0);
  assert.strictEqual(collect(el, (n) => n.props["data-hb"] === "sp").length, 4);
  const svg = collect(el, (n) => n.type === "svg")[0];
  assert.strictEqual(svg.props["data-chart"], "spark");
  assert.strictEqual(svg.props.style.height, "26px");
}

// ── weighted dots render as HTML (round at any stretch), hollow below floor ──
{
  const months = ["2026-01", "2026-02", "2026-03", "2026-04"];
  const dates = months.map(monthKeyToDate);
  const spec = buildSpec({
    id: "eff", ariaLabel: "efficiency",
    x: { kind: "time", dates },
    y: { policy: POLICIES.efficiency },
    series: [{ key: "p", name: "Pace", color: "var(--series2)", values: [430, 425, 428, 420], marks: ["line", "dots"], weights: [120, 10, 200, 338] }],
  });
  const el = renderChart(spec, React);
  const dots = collect(el, (n) => n.type === "span" && n.props.style && n.props.style.borderRadius === "50%");
  assert.strictEqual(dots.length, 4, "one dot per point");
  const hollow = dots.filter((d) => d.props.style.background === "var(--panel)");
  assert.strictEqual(hollow.length, 1, "the below-floor point renders hollow");
  const sizes = new Set(dots.map((d) => d.props.style.width));
  assert.ok(sizes.size >= 2, "weights produce visibly different dot sizes");
}

// ── drill affordance (chart-drill 3.2/3.3): rendered + key ladder from the engine ──
{
  const months = ["2026-01", "2026-02", "2026-03", "2026-04"];
  const dates = months.map(monthKeyToDate);
  const values = [430, 425, 428, 420];
  const makeSpec = (hover, log) => buildSpec({
    id: "eff", ariaLabel: "efficiency",
    x: { kind: "time", dates },
    y: { policy: POLICIES.efficiency },
    series: [{ key: "p", name: "Pace", color: "var(--series2)", values }],
    hoverPoints: values.map((v, i) => ({ i, aria: "m" + i, lines: [{ t: "m" + i, em: true }] })),
    drill: values.map((_, i) => (i === 1 ? null : { label: "view evidence →", action: () => log.push("drill" + i) })),
    hover,
  });
  const key = (k) => ({ key: k, preventDefault: () => {}, stopPropagation: () => {} });

  // pinned on a drillable point: the card carries the visible affordance row,
  // the card is clickable, and Enter invokes the action (not a re-pin)
  {
    const log = [];
    const spec = makeSpec({ index: 0, pinned: true, drilled: false,
      onKey: (e) => log.push("pageKey:" + e.key), onDrillExit: () => log.push("exit") }, log);
    const el = renderChart(spec, React);
    const card = collect(el, (n) => n.props["data-card"] === "eff")[0];
    assert.ok(card, "pinned card renders");
    const aff = collect(card, (n) => text(n) === "view evidence →");
    assert.ok(aff.length >= 1, "the affordance row is visible on the card");
    assert.strictEqual(typeof card.props.onClick, "function", "the pinned card is clickable");
    // .pop ships pointer-events: none (hover cards must stay transparent to
    // the mouse) — a DRILL card must override it or every click lands on the
    // chart behind the card
    assert.strictEqual(card.props.style.pointerEvents, "auto",
      "a drillable card accepts the pointer (overrides .pop's pointer-events: none)");
    card.props.onClick({ stopPropagation: () => {} });
    assert.deepStrictEqual(log, ["drill0"], "card click invokes the point's action");

    const svg = collect(el, (n) => n.type === "svg")[0];
    svg.props.onKeyDown(key("Enter"));
    assert.deepStrictEqual(log, ["drill0", "drill0"], "Enter on the pinned point drills");
    // arrows still belong to the page handler
    svg.props.onKeyDown(key("ArrowRight"));
    assert.deepStrictEqual(log, ["drill0", "drill0", "pageKey:ArrowRight"]);
    // Escape while NOT drilled falls through to the page (dismiss ladder)
    svg.props.onKeyDown(key("Escape"));
    assert.deepStrictEqual(log[log.length - 1], "pageKey:Escape");
  }

  // drilled state: Escape steps back to the pinned reading, not all the way out
  {
    const log = [];
    const spec = makeSpec({ index: 0, pinned: true, drilled: true,
      onKey: (e) => log.push("pageKey:" + e.key), onDrillExit: () => log.push("exit") }, log);
    const svg = collect(renderChart(spec, React), (n) => n.type === "svg")[0];
    svg.props.onKeyDown(key("Escape"));
    assert.deepStrictEqual(log, ["exit"], "Escape while drilled exits the drill only");
  }

  // a pinned point whose descriptor yields no action is inert: no affordance,
  // Enter falls through to the page handler (today's re-pin semantics)
  {
    const log = [];
    const spec = makeSpec({ index: 1, pinned: true, drilled: false,
      onKey: (e) => log.push("pageKey:" + e.key) }, log);
    const el = renderChart(spec, React);
    const card = collect(el, (n) => n.props["data-card"] === "eff")[0];
    assert.strictEqual(collect(card, (n) => text(n) === "view evidence →").length, 0, "no affordance on a null point");
    assert.strictEqual(card.props.onClick, undefined, "null-point card is not clickable");
    assert.strictEqual(card.props.style.pointerEvents, undefined,
      "a non-drill card keeps .pop's pointer transparency");
    const svg = collect(el, (n) => n.type === "svg")[0];
    svg.props.onKeyDown(key("Enter"));
    assert.deepStrictEqual(log, ["pageKey:Enter"], "Enter on a null point keeps page semantics");
  }
}

// ── a chart without a descriptor is untouched (chart-drill 3.3) ──────────────
{
  const pageKey = () => {};
  const spec = demoSpec({ hover: { index: 1, pinned: true, onEnter: () => {}, onPin: () => {}, onKey: pageKey, onLeave: () => {} } });
  const el = renderChart(spec, React);
  const svg = collect(el, (n) => n.type === "svg")[0];
  assert.strictEqual(svg.props.onKeyDown, pageKey, "no descriptor → the page's key handler is wired UNWRAPPED");
  const card = collect(el, (n) => n.props["data-card"] === "vo2")[0];
  assert.strictEqual(card.props.onClick, undefined, "no descriptor → the card is not clickable");
}

// ── rules + annotations reach the DOM tree ────────────────────────────────────
{
  const months = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"];
  const dates = months.map(monthKeyToDate);
  const spec = buildSpec({
    id: "pace", ariaLabel: "pace",
    x: { kind: "time", dates },
    y: { policy: POLICIES.pace },
    series: [{ key: "p", name: "Pace", color: "var(--series2)", values: [430, 425, 428, 421, 419, 417] }],
    rules: [{ v: 341, label: "goal 5:41" }],
    annotations: [{ at: dates[2], label: "5K record" }],
  });
  const el = renderChart(spec, React);
  const rule = collect(el, (n) => n.type === "line" && n.props.strokeDasharray === "5 5");
  assert.strictEqual(rule.length, 1, "goal rule renders");
  const flags = collect(el, (n) => n.props.className === "chart-flag");
  assert.ok(flags.some((f) => text(f) === "5K record"), "annotation label renders");
  assert.ok(flags.some((f) => text(f) === "goal 5:41"), "rule label renders");
}

console.log("ALL PASS");
