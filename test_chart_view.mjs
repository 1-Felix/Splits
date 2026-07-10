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
