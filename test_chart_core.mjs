// test_chart_core.mjs — pure geometry and policy, no DOM, no React (chart-engine 3.8).
import assert from "node:assert";
import { readFile } from "node:fs/promises";
import {
  resolveDomain, segmentNulls, bandFromSeries, rollingMean,
  confidenceRadius, isConfident, placeAnnotations, buildSpec,
  monthKeyToDate, isoWeekToDate, datesBackFrom, POLICIES, fmt,
  crosshairAt, projectTrack, multiTrackSpec,
} from "./chart-core.js";
import { scaleLinear } from "./vendor/d3-lite.js";

// ── vendor surface (task 2.3): every symbol chart-core imports from the bundle
//    must be exported by the checked-in artifact — a stale d3-lite.js fails
//    HERE, not at runtime in a browser.
{
  const src = await readFile(new URL("./chart-core.js", import.meta.url), "utf8");
  const m = src.match(/import\s*\{([\s\S]*?)\}\s*from\s*["']\.\/vendor\/d3-lite\.js["']/);
  assert.ok(m, "chart-core.js imports from ./vendor/d3-lite.js");
  const imported = m[1].split(",").map((s) => s.trim().split(/\s+as\s+/)[0].trim()).filter(Boolean);
  const bundle = await import("./vendor/d3-lite.js");
  for (const sym of imported) {
    assert.ok(sym in bundle, `vendor/d3-lite.js exports '${sym}' (re-run the esbuild recipe in vendor/README.md)`);
  }
}

// ── resolveDomain: minimum-span expansion (the anti-exaggeration rule) ────────
{
  // a 3.6-point VO₂ range yields a domain of at least the declared 5.0 span
  const vals = [43.6, 44.1, 44.9, 45.8, 46.4, 47.2];
  const d = resolveDomain(vals, POLICIES.vo2);
  assert.ok(d.max - d.min >= 5.0, `vo2 span ${d.max - d.min} >= 5.0`);
  // expansion is about the midpoint: data stays centered
  const mid = (d.max + d.min) / 2;
  assert.ok(mid > 44.5 && mid < 46.5, "expansion centered on the data midpoint");
  // and the data itself is inside the domain
  assert.ok(d.min <= 43.6 && d.max >= 47.2);
}

// ── resolveDomain: zero anchoring for magnitude metrics ───────────────────────
{
  const d = resolveDomain([18, 25, 31, 44], POLICIES.weeklyVolume);
  assert.strictEqual(d.min, 0, "weekly volume domain starts at zero");
  assert.ok(d.max >= 44);
}

// ── resolveDomain: forced goal inclusion ──────────────────────────────────────
{
  // every value far slower than the goal — the goal is still inside the domain
  const d = resolveDomain([420, 431, 445], POLICIES.pace, [341]);
  assert.ok(d.min < 341, `pace domain min ${d.min} < goal 341`);
  assert.ok(d.min < 341 - 0.5, "included goal is padded off the frame edge");
}

// ── resolveDomain: nice ticks with formatted labels ───────────────────────────
{
  const d = resolveDomain([43.6, 47.2], { tickCount: 4, fmt: fmt.int });
  assert.ok(d.ticks.length >= 2, "at least two ticks");
  for (const t of d.ticks) {
    assert.ok(t.v >= d.min - 1e-9 && t.v <= d.max + 1e-9, "tick inside domain");
    assert.strictEqual(typeof t.label, "string");
  }
  const vs = d.ticks.map((t) => t.v);
  assert.deepStrictEqual([...vs].sort((a, b) => a - b), vs, "ticks ascend");
}
{
  // time-valued y axis picks human steps (15/30/60 s), not decimal ones
  const d = resolveDomain([400, 470], POLICIES.pace);
  const step = d.ticks[1].v - d.ticks[0].v;
  assert.ok([15, 30, 60, 120].includes(step), `pace tick step ${step} is a time step`);
  assert.ok(/^\d+:\d{2}$/.test(d.ticks[0].label), "pace tick label is m:ss");
}
{
  // trajectory: goal always in frame, min span 15 min, h:mm labels
  const weekly = [8100, 8068, 8010];
  const d = resolveDomain(weekly, POLICIES.trajectory, [7199]);
  assert.ok(d.min < 7199, "goal inside the trajectory domain");
  assert.ok(d.max - d.min >= 900, "trajectory span >= 15 min");
  assert.ok(/^\d+:\d{2}$/.test(d.ticks[0].label), "trajectory labels are h:mm");
}

// ── resolveDomain: degenerate inputs ─────────────────────────────────────────
{
  assert.deepStrictEqual(resolveDomain([], {}), { min: 0, max: 1, ticks: [] });
  const d = resolveDomain([5, 5, 5], { tickCount: 3, fmt: fmt.int });
  assert.ok(d.max > d.min, "constant series still yields a real span");
}

// ── segmentNulls: a line never bridges a null ────────────────────────────────
{
  assert.deepStrictEqual(segmentNulls([1, 2, null, 3, 4]), [[1, 2], [3, 4]]);
  assert.deepStrictEqual(segmentNulls([null, 1, null]), [[1]]);
  assert.deepStrictEqual(segmentNulls([null, null]), []);
  assert.deepStrictEqual(segmentNulls([]), []);
  // object points: null-ness is the value, zero is NOT null
  assert.deepStrictEqual(
    segmentNulls([{ v: 0 }, { v: null }, { v: 2 }]),
    [[{ v: 0 }], [{ v: 2 }]]
  );
}

// ── bandFromSeries: median + IQR, clamped windows, no extrapolation ──────────
{
  const vals = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
  const b = bandFromSeries(vals, 4);        // half=2 → window [i-2, i+2]
  assert.strictEqual(b.mid.length, 10);
  // interior: window [2..6] → median 5, q1 4, q3 6
  assert.strictEqual(b.mid[4], 5);
  assert.strictEqual(b.lower[4], 4);
  assert.strictEqual(b.upper[4], 6);
  // left edge: window clamps to [0..2] = [1,2,3] — asymmetric, never extrapolated
  assert.strictEqual(b.mid[0], 2);
  assert.strictEqual(b.lower[0], 1.5);
  assert.strictEqual(b.upper[0], 2.5);
  // right edge clamps too
  assert.strictEqual(b.mid[9], 9);
  // band respects order: lower <= mid <= upper everywhere
  for (let i = 0; i < 10; i++) {
    assert.ok(b.lower[i] <= b.mid[i] && b.mid[i] <= b.upper[i]);
  }
}
{
  // nulls don't contribute; a window with fewer than 2 valid values has no band
  const b = bandFromSeries([null, 5, null], 2);
  assert.strictEqual(b.mid[0], null);
  assert.strictEqual(b.mid[1], null);
  const b2 = bandFromSeries([4, null, 6], 4);
  assert.strictEqual(b2.mid[1], 5, "median skips the null");
}
{
  const rm = rollingMean([2, 4, 6, 8], 2);   // half=1, centered
  assert.strictEqual(rm[0], 3);               // (2+4)/2 — clamped at the edge
  assert.strictEqual(rm[1], 4);               // (2+4+6)/3
}

// ── confidenceRadius: sqrt scale, monotone, clamped to [1.5, 4.5] ────────────
{
  const pol = POLICIES.efficiency.weights;   // floor 20, max 300
  const r21 = confidenceRadius(21, pol);
  const r120 = confidenceRadius(120, pol);
  const r338 = confidenceRadius(338, pol);
  assert.ok(r21 < r120 && r120 < r338, "radius is monotone in weight");
  assert.ok(r21 >= 1.5 && r338 <= 4.5, "radius clamped to [1.5, 4.5]");
  assert.strictEqual(confidenceRadius(0, pol), 1.5, "below-floor clamps to rMin");
  assert.strictEqual(confidenceRadius(10000, pol), 4.5, "huge weight clamps to rMax");
  assert.strictEqual(confidenceRadius(null, pol), 1.5, "null weight = minimum");
  // the floor decides hollow-vs-solid
  assert.strictEqual(isConfident(19, pol), false);
  assert.strictEqual(isConfident(21, pol), true);
  assert.strictEqual(isConfident(null, pol), false);
}

// ── placeAnnotations: collision-free lanes, deterministic ────────────────────
{
  const xs = (v) => v;                        // identity scale
  const a = placeAnnotations(
    [{ at: 300, label: "5K record" }, { at: 310, label: "race day" }, { at: 500, label: "10K record" }],
    xs, 600
  );
  assert.strictEqual(a.length, 3);
  assert.strictEqual(a[0].lane, 0);
  assert.strictEqual(a[1].lane, 1, "overlapping flags take separate lanes");
  assert.strictEqual(a[2].lane, 0, "distant flag reuses lane 0");
  // deterministic: same input, same output
  assert.deepStrictEqual(a, placeAnnotations(
    [{ at: 300, label: "5K record" }, { at: 310, label: "race day" }, { at: 500, label: "10K record" }],
    xs, 600
  ));
  // out-of-range annotations are dropped, not drawn at the edge
  const b = placeAnnotations([{ at: -50, label: "x" }, { at: 700, label: "y" }], xs, 600);
  assert.strictEqual(b.length, 0);
}

// ── x helpers ────────────────────────────────────────────────────────────────
{
  assert.strictEqual(monthKeyToDate("2024-02").toISOString().slice(0, 10), "2024-02-01");
  assert.strictEqual(isoWeekToDate("2025-W32").toISOString().slice(0, 10), "2025-08-04"); // Monday
  assert.strictEqual(isoWeekToDate("2026-W01").getUTCDay(), 1, "ISO weeks start Monday");
  const ds = datesBackFrom("2026-07-10", 3, 7);
  assert.strictEqual(ds.length, 3);
  assert.strictEqual(ds[2].toISOString().slice(0, 10), "2026-07-10");
  assert.strictEqual(ds[0].toISOString().slice(0, 10), "2026-06-26");
}

// ── buildSpec: the ChartSpec contract (design D6) ────────────────────────────
{
  const months = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"];
  const dates = months.map(monthKeyToDate);
  const values = [430, 425, null, 428, 420, 418];
  const weights = [120, 15, null, 200, 25, 338];
  const spec = buildSpec({
    id: "eff", ariaLabel: "Pace at reference heart rate",
    x: { kind: "time", dates },
    y: { policy: POLICIES.efficiency },
    series: [{ key: "pace", name: "Pace", color: "var(--series1)", values, marks: ["line", "dots"], weights }],
    hoverPoints: values.map((v, i) => (v == null ? null : { i, aria: "m" + i, lines: [{ t: "m" + i, em: true }] })).filter(Boolean),
    hover: { index: null },
  });

  // frame + axes
  assert.strictEqual(spec.kind, "trend");
  assert.ok(spec.y.ticks.length >= 2, "y ticks exist");
  assert.ok(spec.x.ticks.length >= 2, "x ticks exist");
  for (const t of spec.y.ticks) assert.ok(/^\d+:\d{2}$/.test(t.label), "pace y labels are m:ss");

  // the line layer breaks at the null AND at the below-floor points
  const line = spec.layers.find((l) => l.kind === "line" && l.color === "var(--series1)");
  assert.ok(line, "series line layer exists");
  // values with null at i=2 and below-floor at i=1 (15) and i=4 (25 is >= 20 → kept):
  // segments: [0], [3,4,5] → only runs of >1 point survive as paths
  assert.strictEqual(line.paths.length, 1, "one drawable segment (single points draw no path)");

  // dots: one per non-null value; below-floor points are hollow
  const dots = spec.layers.find((l) => l.kind === "dots");
  assert.strictEqual(dots.dots.length, 5, "one dot per valid point");
  const hollow = dots.dots.filter((d) => d.hollow);
  assert.strictEqual(hollow.length, 1, "exactly the below-floor point is hollow");
  // weighted radii differ (21 min vs 338 min must be visibly different)
  const rs = dots.dots.map((d) => d.r);
  assert.ok(Math.max(...rs) > Math.min(...rs), "dot radii encode the weight");

  // baseline band renders behind the series (layer order)
  const bandIdx = spec.layers.findIndex((l) => l.kind === "band" && l.role === "baseline");
  const lineIdx = spec.layers.indexOf(line);
  assert.ok(bandIdx !== -1 && bandIdx < lineIdx, "median band sits beneath the line");

  // single series → no legend
  assert.strictEqual(spec.legend, null);

  // hover: bands tile the full frame width (chart-hover.js geometry)
  assert.strictEqual(spec.hover.bands.length, 5);
  assert.strictEqual(spec.hover.bands[0].x, 0);
  const last = spec.hover.bands[4];
  assert.strictEqual(+(last.x + last.w).toFixed(0), 600);
  assert.strictEqual(spec.hover.card, null, "no card without a hover index");

  // a11y contract is present without per-chart code
  assert.strictEqual(spec.a11y.role, "img");
  assert.strictEqual(spec.a11y.label, "Pace at reference heart rate");
  assert.strictEqual(spec.a11y.keyboard, true);
}

{
  // two series → legend; ribbon between them; goal rule inside the domain
  const weeks = ["2026-W20", "2026-W21", "2026-W22", "2026-W23"];
  const dates = weeks.map(isoWeekToDate);
  const riegel = [8300, 8200, 8150, 8068];
  const garmin = [7500, 7450, 7400, 7270];
  const spec = buildSpec({
    id: "traj", ariaLabel: "Race trajectory",
    x: { kind: "time", dates },
    y: { policy: POLICIES.trajectory, include: [7199] },
    series: [
      { key: "riegel", name: "Demonstrated (Riegel)", color: "var(--series1)", values: riegel },
      { key: "garmin", name: "Garmin model", color: "var(--series2)", values: garmin },
    ],
    ribbon: ["riegel", "garmin"],
    rules: [{ v: 7199, label: "goal 1:59:59" }],
    hoverPoints: weeks.map((_, i) => ({ i, aria: "w" + i, lines: [] })),
    hover: { index: 1 },
  });
  assert.ok(spec.legend && spec.legend.length === 2, "two series carry a legend");
  assert.ok(spec.layers.some((l) => l.role === "ribbon"), "gap ribbon layer exists");
  const rule = spec.layers.find((l) => l.kind === "rule");
  assert.ok(rule, "goal rule layer exists");
  assert.ok(rule.y > spec.plot.y && rule.y < spec.plot.y + spec.plot.h + 1, "goal rule sits inside the plot");
  // active hover: card + crosshair + one dot per series
  assert.ok(spec.hover.card, "hover card present at index 1");
  assert.strictEqual(spec.hover.activeDots.length, 2, "one hover dot per series");
  assert.ok(spec.hover.cross && spec.hover.cross.x > 0);
}

{
  // bars: zero-anchored, absent months get no bar, band x-scale
  const dates = datesBackFrom("2026-07-10", 4, 7);
  const spec = buildSpec({
    id: "vol", ariaLabel: "Weekly volume",
    x: { kind: "band", dates },
    y: { policy: POLICIES.weeklyVolume },
    series: [{ key: "km", name: "km", color: "var(--series1)", values: [20, null, 30, 40], marks: ["bars"] }],
    hoverPoints: [{ i: 0 }, { i: 2 }, { i: 3 }].map((p) => ({ ...p, aria: "", lines: [] })),
  });
  const bars = spec.layers.find((l) => l.kind === "bars");
  assert.strictEqual(bars.bars.length, 3, "null week draws no bar");
  const y0 = Math.max(...bars.bars.map((b) => +(b.y + b.h).toFixed(0)));
  for (const b of bars.bars) assert.strictEqual(+(b.y + b.h).toFixed(0), y0, "all bars share the zero baseline");
  assert.strictEqual(spec.y.domain[0], 0);
}

{
  // spark charts carry no axes and no legend but keep hover geometry
  const spec = buildSpec({
    id: "sp", ariaLabel: "splits", kind: "spark",
    frame: { w: 600, h: 30 },
    x: { kind: "point", n: 5 },
    y: { policy: {} },
    series: [{ key: "s", name: "s", color: "var(--series1)", values: [300, 310, 305, 320, 300] }],
    hoverPoints: [0, 1, 2, 3, 4].map((i) => ({ i, aria: "", lines: [] })),
  });
  assert.strictEqual(spec.kind, "spark");
  assert.strictEqual(spec.y.ticks.length, 0);
  assert.strictEqual(spec.x.ticks.length, 0);
  assert.strictEqual(spec.legend, null);
  assert.strictEqual(spec.hover.bands.length, 5);
}

{
  // annotations land in the layer stack with collision-free lanes
  const dates = datesBackFrom("2026-07-10", 30, 7);
  const spec = buildSpec({
    id: "a", ariaLabel: "annotated",
    x: { kind: "time", dates },
    y: { policy: POLICIES.vo2 },
    series: [{ key: "v", name: "v", color: "var(--series1)", values: dates.map((_, i) => 44 + i * 0.05) }],
    annotations: [
      { at: dates[10], label: "5K record" },
      { at: dates[11], label: "10K record" },
      { at: dates[25], label: "race day" },
    ],
  });
  const ann = spec.layers.find((l) => l.kind === "annotations");
  assert.strictEqual(ann.flags.length, 3);
  assert.notStrictEqual(ann.flags[0].lane, ann.flags[1].lane, "adjacent flags separate lanes");
}

// ── drill descriptor (chart-drill 3.1): pure pass-through, no DOM ────────────
{
  const months = ["2026-01", "2026-02", "2026-03", "2026-04"];
  const dates = months.map(monthKeyToDate);
  const values = [430, 425, 428, 420];
  const actions = [];
  // per-hoverPoint entries; the null entry models a point with no evidence
  const drill = [
    { label: "view evidence →", action: () => actions.push(0) },
    null,
    { label: "view evidence →", action: () => actions.push(2) },
    { label: "view evidence →", action: () => actions.push(3) },
  ];
  const base = {
    id: "eff", ariaLabel: "efficiency",
    x: { kind: "time", dates },
    y: { policy: POLICIES.efficiency },
    series: [{ key: "p", name: "Pace", color: "var(--series2)", values }],
    hoverPoints: values.map((v, i) => ({ i, aria: "m" + i, lines: [{ t: "m" + i, em: true }] })),
    drill,
  };

  // pinned on a drillable point: the affordance row joins the card and the
  // action is exposed — the engine renders/announces, the PAGE acts
  const pinned = buildSpec({ ...base, hover: { index: 0, pinned: true, drilled: false } });
  assert.ok(pinned.hover.drillDeclared, "the spec knows a drill was declared");
  assert.ok(pinned.hover.drill, "active pinned point exposes its drill entry");
  assert.strictEqual(pinned.hover.drill.label, "view evidence →");
  const lastRow = pinned.hover.card.rows[pinned.hover.card.rows.length - 1];
  assert.strictEqual(lastRow.t, "view evidence →", "the card's last row is the affordance");
  assert.strictEqual(lastRow.drill, true, "…marked as the drill row");
  pinned.hover.drill.action();
  assert.deepStrictEqual(actions, [0], "the exposed action is the declared one");

  // merely hovered (not pinned): no affordance, no action — reading first
  const hovered = buildSpec({ ...base, hover: { index: 0, pinned: false } });
  assert.strictEqual(hovered.hover.drill, null, "hover without pin exposes no drill");
  assert.ok(!hovered.hover.card.rows.some((r) => r.drill), "no affordance row on a hover card");

  // a null entry (no action for this point) is inert even when pinned
  const nullPoint = buildSpec({ ...base, hover: { index: 1, pinned: true } });
  assert.strictEqual(nullPoint.hover.drill, null, "a point without an action carries none");
  assert.ok(!nullPoint.hover.card.rows.some((r) => r.drill), "…and no affordance row");

  // drilled state + exit handler thread through untouched
  const exits = [];
  const drilled = buildSpec({ ...base, hover: { index: 2, pinned: true, drilled: true, onDrillExit: () => exits.push(1) } });
  assert.strictEqual(drilled.hover.drilled, true);
  drilled.hover.onDrillExit();
  assert.deepStrictEqual(exits, [1]);

  // a chart WITHOUT a descriptor is byte-identical in the hover contract
  const { drill: _d, ...noDrillBase } = base;
  const plain = buildSpec({ ...noDrillBase, hover: { index: 0, pinned: true } });
  assert.strictEqual(plain.hover.drillDeclared, false);
  assert.strictEqual(plain.hover.drill, null);
  assert.deepStrictEqual(plain.hover.card.rows, [{ t: "m0", em: true }],
    "no descriptor → the pinned card rows are exactly the point's lines");
}

// ── crosshairAt (run-detail D3): bisection, clamped at both ends ─────────────
{
  const xs = Array.from({ length: 101 }, (_, i) => i * 10);   // 0..1000 m
  const scale = scaleLinear().domain([0, 1000]).range([0, 600]);
  assert.deepStrictEqual(crosshairAt(scale, xs, 300), { i: 50, x: 300 }, "midpoint maps to its sample");
  assert.deepStrictEqual(crosshairAt(scale, xs, 0), { i: 0, x: 0 }, "left edge");
  assert.deepStrictEqual(crosshairAt(scale, xs, 600), { i: 100, x: 600 }, "right edge");
  assert.strictEqual(crosshairAt(scale, xs, -75).i, 0, "beyond the left edge clamps");
  assert.strictEqual(crosshairAt(scale, xs, 999).i, 100, "beyond the right edge clamps");
  // nearest, not floor: 304px = 506.7m sits nearer sample 51 (510) than 50 (500)
  assert.strictEqual(crosshairAt(scale, xs, 304).i, 51);
  assert.strictEqual(crosshairAt(scale, [], 100), null, "no samples → null");
}

// ── projectTrack (run-detail D2): aspect preserved, lon-shift invariant ──────
{
  // a square on the ground at lat 47°: dLat = 0.01°, dLon = 0.01°/cos(47°)
  const k = 1 / Math.cos(47 * Math.PI / 180);
  const lat = [47.0, 47.01, 47.01, 47.0, 47.0];
  const lon = [8.0, 8.0, 8.0 + 0.01 * k, 8.0 + 0.01 * k, 8.0];
  const pr = projectTrack(lat, lon, 300, 300, 10);
  assert.ok(pr && pr.points.length === 5);
  const px = pr.points.map((p) => p[0]);
  const py = pr.points.map((p) => p[1]);
  const spanX = Math.max(...px) - Math.min(...px);
  const spanY = Math.max(...py) - Math.min(...py);
  assert.ok(Math.abs(spanX - spanY) < 1, `ground square projects square (x ${spanX} vs y ${spanY})`);
  // north is up: the higher latitude gets the SMALLER y
  assert.ok(pr.points[1][1] < pr.points[0][1], "north up");
  // translation in longitude changes nothing (same shape, same fit)
  const pr2 = projectTrack(lat, lon.map((v) => v + 3), 300, 300, 10);
  assert.deepStrictEqual(pr2.points, pr.points, "lon-shifted track projects identically");
  // null samples stay null (an honest gap in the polyline)
  const pr3 = projectTrack([47.0, null, 47.01], [8.0, 8.0, 8.01], 300, 300);
  assert.strictEqual(pr3.points[1], null);
  // fewer than two valid points is no track
  assert.strictEqual(projectTrack([47], [8], 300, 300), null);
}

// ── multiTrackSpec (run-detail D4): one x domain, n y domains ────────────────
{
  const t = Array.from({ length: 200 }, (_, i) => i * 5);      // shared seconds axis
  const hr = t.map((_, i) => 130 + (i % 40));
  const v = t.map((_, i) => 2.5 + (i % 10) / 20);
  const elev = t.map((_, i) => 400 + i / 10);
  const specs = multiTrackSpec([
    { id: "pace", ariaLabel: "Pace", series: [{ key: "v", name: "Pace", color: "var(--series1)", values: v }], policy: {} },
    { id: "hr", ariaLabel: "Heart rate", series: [{ key: "hr", name: "HR", color: "var(--series2)", values: hr }], policy: {},
      spans: [{ lo: 140, hi: 155, color: "var(--z2)" }] },
    { id: "elev", ariaLabel: "Elevation", series: [{ key: "e", name: "Elev", color: "var(--series3)", values: elev }], policy: {} },
  ], { values: t, fmt: (s) => s + "s", cross: { i: 100 } });

  assert.strictEqual(specs.length, 3);
  // the crosshair lands on the same x in every track — one index, every track
  const xsAt = specs.map((s) => s.hover.cross.x);
  assert.ok(xsAt.every((x) => Math.abs(x - xsAt[0]) < 0.01), "one crosshair x across the stack");
  assert.ok(specs.every((s) => s.hover.activeDots.length === 1), "each track pins its own sample");
  // each track resolves its own y domain
  assert.notDeepStrictEqual(specs[0].y.domain, specs[1].y.domain);
  assert.notDeepStrictEqual(specs[1].y.domain, specs[2].y.domain);
  // only the last track carries the x tick labels for the stack
  assert.strictEqual(specs[0].x.ticks.length, 0);
  assert.strictEqual(specs[1].x.ticks.length, 0);
  assert.ok(specs[2].x.ticks.length >= 2, "shared axis labels on the bottom track");
  assert.ok(specs[2].x.ticks[0].label.endsWith("s"), "shared axis uses the caller's format");
  // the zone span renders as a band layer beneath the HR series
  const span = specs[1].layers.find((l) => l.role === "span");
  assert.ok(span && span.fill === "var(--z2)", "zone band present with its zone colour");
}

console.log("ALL PASS");
