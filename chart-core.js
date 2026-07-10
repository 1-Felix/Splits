/* chart-core.js — pure chart geometry and domain policy (chart-engine D3/D4/D6).
 *
 * No DOM, no React, no side effects: everything here is testable in node
 * (test_chart_core.mjs). This module owns the OPINIONS d3 refuses to have —
 * domain policy (minimum spans, zero-anchoring, forced goal inclusion), honest
 * null segmentation, rolling-median baseline bands, confidence weighting, and
 * annotation placement. Its output is a ChartSpec; chart-view.js is the only
 * file that turns one into elements. The hover geometry that already shipped
 * (chart-hover.js) is consumed unchanged, never reimplemented.
 *
 * Everything here is presentation over data the sync already derived. No
 * training metric is computed in this file — that stays in insight_metrics.py.
 */

import {
  scaleLinear, scaleUtc, scaleBand, scalePoint,
  line as d3line, area as d3area,
  extent, quantile, bisector, mean, utcFormat,
} from "./vendor/d3-lite.js";
import { bandRects, cardPlace } from "./chart-hover.js";

// ── formatters (tick labels; pages format hover text themselves) ─────────────
const z2 = (n) => String(n).padStart(2, "0");
export const fmt = {
  int: (v) => String(Math.round(v)),
  n1: (v) => (Math.round(v * 10) / 10).toFixed(1),
  pace: (v) => Math.floor(v / 60) + ":" + z2(Math.round(v % 60)),          // s/km → m:ss
  hm: (v) => Math.floor(v / 3600) + ":" + z2(Math.round((v % 3600) / 60)), // s → h:mm
  clock: (v) => { v = Math.round(v); const h = Math.floor(v / 3600), m = Math.floor((v % 3600) / 60), s = v % 60;
    return h ? h + ":" + z2(m) + ":" + z2(s) : m + ":" + z2(s); },
};

// ── the domain-policy table (design D3) ───────────────────────────────────────
// One table, all twelve arguments together, so they can be argued with and
// changed together. Minimum spans are judgement calls, not physics:
//   trajectory  15 min — a 30 s wobble in a 2 h projection must look small
//   vo2         5.0 pt — the +0.3 month stops sweeping the frame
//   pace        60 s/km, cadence 20 spm, hrv 20 ms, cadence@ref 10 spm
// `steps` are candidate tick intervals for time-valued y axes (seconds);
// `weights` is the confidence encoding for the pooled inBandMin series;
// `ref` names the reference layer buildSpec derives (presentation only).
export const POLICIES = {
  trajectory: { minSpan: 15 * 60, steps: [300, 600, 900, 1800, 3600], fmt: fmt.hm },
  vo2: { minSpan: 5, tickCount: 4, fmt: fmt.int, ref: { type: "medianBand", window: 12 } },
  pace: { minSpan: 60, steps: [15, 30, 60, 120], fmt: fmt.pace, dirLabel: "faster ↓" },
  cadence: { minSpan: 20, tickCount: 4, fmt: fmt.int, ref: { type: "medianBand", window: 12 } },
  weeklyVolume: { zero: true, tickCount: 4, fmt: fmt.int, ref: { type: "meanLine", window: 4 } },
  fitnessFatigue: { zero: true, tickCount: 4, fmt: fmt.int },
  sleepHours: { zero: true, max: 10, tickCount: 5, fmt: fmt.int, ref: { type: "span", lo: 7, hi: 9 } },
  hrv: { minSpan: 20, tickCount: 4, fmt: fmt.int, ref: { type: "medianBand", window: 7 } },
  efficiency: { minSpan: 60, steps: [15, 30, 60, 120], fmt: fmt.pace, dirLabel: "faster ↓",
    ref: { type: "medianBand", window: 7 }, weights: { floor: 20, max: 300 } },
  cadenceAtRefPace: { minSpan: 10, tickCount: 4, fmt: fmt.int,
    ref: { type: "medianBand", window: 7 }, weights: { floor: 20, max: 300 } },
  yoy: { zero: true, tickCount: 4, fmt: fmt.int },
  heatmap: { ramp: ["hm0", "hm1", "hm2", "hm3", "hm4"] }, // sequential single hue via theme tokens
};

// ── domain policy (design D3) ─────────────────────────────────────────────────
// nice-extent → forced inclusions → minimum-span expansion about the midpoint →
// zero-anchor / hard bounds. Returns the resolved domain plus ticks with
// formatted labels, so no caller ever invents its own scale.
export function resolveDomain(values, policy = {}, include = []) {
  const valid = (values || []).filter((v) => v != null && Number.isFinite(v));
  const inc = (include || []).filter((v) => v != null && Number.isFinite(v));
  if (!valid.length && !inc.length) return { min: 0, max: 1, ticks: [] };
  const count = policy.tickCount || 4;

  // 1. nice extent of the data itself. policy.clip = [loQ, hiQ] resolves the
  //    domain from quantiles instead — for sample streams whose GPS start-up
  //    spikes would otherwise own the whole scale (the spike then draws off
  //    the clipped plot edge, visibly exceeding the scale rather than lying)
  let a, b;
  if (policy.clip && valid.length > 4) {
    const sorted = [...valid].sort((x, y) => x - y);
    a = quantile(sorted, policy.clip[0]);
    b = quantile(sorted, policy.clip[1]);
  } else {
    [a, b] = extent(valid.length ? valid : inc);
  }
  if (a === b) { a -= 1; b += 1; }
  [a, b] = scaleLinear().domain([a, b]).nice(count).domain();

  // 2. forced inclusions (goals, comparison rules) — padded off the frame edge
  for (const v of inc) { if (v < a) a = v; if (v > b) b = v; }
  const edgePad = (b - a) * 0.04 || 0.5;
  if (inc.some((v) => v === a)) a -= edgePad;
  if (inc.some((v) => v === b)) b += edgePad;

  // 3. minimum span, expanded symmetrically about the midpoint — the
  //    anti-exaggeration rule: a +0.3 month must LOOK like +0.3
  if (policy.minSpan && b - a < policy.minSpan) {
    const mid = (a + b) / 2;
    a = mid - policy.minSpan / 2;
    b = mid + policy.minSpan / 2;
  }

  // 4. zero anchor (magnitude metrics) and hard bounds
  if (policy.zero) a = Math.min(0, a);
  if (policy.min != null) a = policy.min;
  if (policy.max != null) b = Math.max(b, policy.max);

  const f = policy.fmt || fmt.int;
  let tks;
  if (policy.steps) tks = stepTicks(a, b, policy.steps);
  if (!tks || tks.length < 2) tks = scaleLinear().domain([a, b]).ticks(count);
  return { min: a, max: b, ticks: tks.map((v) => ({ v, label: f(v) })) };
}

// Ticks at human intervals (0:15 / 0:30 / 1:00 …) for time-valued y axes, where
// d3's decimal ticks would land on ugly values. `steps` ascend; the smallest
// step that still fits within maxN ticks wins.
function stepTicks(a, b, steps, maxN = 5) {
  for (const s of steps) {
    const out = [];
    for (let v = Math.ceil(a / s) * s; v <= b + 1e-9; v += s) out.push(v);
    if (out.length >= 2 && out.length <= maxN) return out;
  }
  return null;
}

// ── honest gaps (design D4) ───────────────────────────────────────────────────
// Split a series into contiguous non-null runs of [index, value]. A line drawn
// from these segments can never bridge a null month.
export function segmentNulls(points, isNull) {
  const nul = isNull || ((p) => p == null || (typeof p === "object" && p.v == null));
  const segs = [];
  let seg = [];
  (points || []).forEach((p, i) => {
    if (nul(p)) { if (seg.length) segs.push(seg); seg = []; return; }
    seg.push({ i, p });
  });
  if (seg.length) segs.push(seg);
  return segs.map((s) => s.map(({ p }) => p));
}
// Same split, but keeping indices — buildSpec needs x positions per point.
function segmentIndices(values, excluded) {
  const segs = [];
  let seg = [];
  values.forEach((v, i) => {
    if (v == null || !Number.isFinite(v) || (excluded && excluded(i))) { if (seg.length > 0) segs.push(seg); seg = []; return; }
    seg.push(i);
  });
  if (seg.length > 0) segs.push(seg);
  return segs;
}

// ── baseline bands (design D4) ────────────────────────────────────────────────
// Rolling median with an interquartile ribbon, computed over a centered window
// that CLAMPS at the series edges (asymmetric, never extrapolated). Null months
// simply don't contribute; an index whose window holds fewer than two valid
// values gets no band. Presentation over shipped data — not a new metric.
export function bandFromSeries(values, window = 12) {
  const n = (values || []).length;
  const half = Math.floor(window / 2);
  const mid = [], lower = [], upper = [];
  for (let i = 0; i < n; i++) {
    const w = values
      .slice(Math.max(0, i - half), Math.min(n, i + half + 1))
      .filter((v) => v != null && Number.isFinite(v))
      .sort((x, y) => x - y);
    if (w.length < 2) { mid.push(null); lower.push(null); upper.push(null); continue; }
    mid.push(quantile(w, 0.5));
    lower.push(quantile(w, 0.25));
    upper.push(quantile(w, 0.75));
  }
  return { mid, lower, upper };
}

// Rolling mean over the same clamped centered window (weekly volume's 4-week
// reference line).
export function rollingMean(values, window = 4) {
  const n = (values || []).length;
  const half = Math.floor(window / 2);
  const out = [];
  for (let i = 0; i < n; i++) {
    const w = values
      .slice(Math.max(0, i - half), Math.min(n, i + half + 1))
      .filter((v) => v != null && Number.isFinite(v));
    out.push(w.length ? w.reduce((a, b) => a + b, 0) / w.length : null);
  }
  return out;
}

// ── confidence weighting (design D4) ─────────────────────────────────────────
// Mark radius from a per-point sample weight (inBandMin), through a sqrt scale
// clamped to [1.5, 4.5] px. Whether a point is confident enough to join the
// line at all is the same policy's floor.
export function confidenceRadius(weight, policy = {}) {
  const rMin = policy.rMin != null ? policy.rMin : 1.5;
  const rMax = policy.rMax != null ? policy.rMax : 4.5;
  const wFloor = policy.floor != null ? policy.floor : 20;
  const wMax = policy.max != null ? policy.max : 300;
  if (weight == null || !Number.isFinite(weight)) return rMin;
  const t = (Math.sqrt(Math.max(weight, 0)) - Math.sqrt(wFloor)) / (Math.sqrt(wMax) - Math.sqrt(wFloor));
  return +Math.min(rMax, Math.max(rMin, rMin + t * (rMax - rMin))).toFixed(2);
}
export function isConfident(weight, policy = {}) {
  const wFloor = (policy && policy.floor != null) ? policy.floor : 20;
  return weight != null && Number.isFinite(weight) && weight >= wFloor;
}

// ── annotations (design D4) ───────────────────────────────────────────────────
// Deterministic lane assignment so flags near each other never collide: sort by
// x then label, greedily take the lowest lane whose previous flag is at least
// minGap away. Lanes are CAPPED — a flag that would need a fourth lane is
// dropped rather than drawn into the card head; the data it marks stays
// reachable in the hover card and the records feed.
export function placeAnnotations(anns, xScale, width, minGap = 60, maxLanes = 3) {
  const placed = (anns || [])
    .map((a) => ({ label: a.label, x: +(+xScale(a.at)).toFixed(1) }))
    .filter((a) => Number.isFinite(a.x) && a.x >= -1 && a.x <= width + 1)
    .sort((p, q) => p.x - q.x || (p.label < q.label ? -1 : p.label > q.label ? 1 : 0));
  const laneEnds = [];
  const out = [];
  for (const a of placed) {
    let lane = 0;
    while (lane < maxLanes && lane < laneEnds.length && a.x - laneEnds[lane] < minGap) lane++;
    if (lane >= maxLanes) continue; // crowded out — dropped, not stacked off-frame
    laneEnds[lane] = a.x;
    out.push({ x: a.x, label: a.label, lane });
  }
  return out;
}

// ── x-axis helpers ────────────────────────────────────────────────────────────
export function monthKeyToDate(key) {          // '2024-02' → Date (UTC month start)
  const [y, m] = key.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, 1));
}
export function isoWeekToDate(key) {           // '2025-W32' → Date (UTC Monday)
  const m = /^(\d{4})-W(\d{2})$/.exec(key);
  if (!m) return null;
  const y = +m[1], w = +m[2];
  const jan4 = new Date(Date.UTC(y, 0, 4));
  const monW1 = new Date(jan4.getTime() - ((jan4.getUTCDay() + 6) % 7) * 86400000);
  return new Date(monW1.getTime() + (w - 1) * 7 * 86400000);
}
export function datesBackFrom(todayISO, n, stepDays = 7) {  // series ending "now"
  const end = new Date(todayISO + "T00:00:00Z");
  return Array.from({ length: n }, (_, i) => new Date(end.getTime() - (n - 1 - i) * stepDays * 86400000));
}

const fmtMon = utcFormat("%b");
const fmtYr = utcFormat("%y");
function timeTickLabel(d, first) {
  const mon = fmtMon(d);
  if (d.getUTCDate() !== 1) return d.getUTCDate() + " " + mon; // day-level tick (short spans)
  return first || d.getUTCMonth() === 0 ? mon + " ’" + fmtYr(d) : mon;
}

// ── buildSpec (design D6): descriptor → ChartSpec ────────────────────────────
// The descriptor is data + policy + page-supplied hover payloads; the ChartSpec
// is pure px geometry plus opaque handlers. chart-view.js renders it verbatim.
//
// descriptor = {
//   id, ariaLabel, kind: 'trend' | 'spark',
//   frame?: { w, h, pad:{l,r,t,b} },
//   x: { kind:'time'|'band'|'point', dates?: Date[], n?, label? },
//   y: { policy, include?: number[], label? },
//   series: [{ key, name, color, values, marks:['line'|'bars'|'dots'...],
//              width?, dash?, weights? }],
//   ref?: policy.ref override | null to suppress,
//   ribbon?: [keyA, keyB],                  // shaded gap between two series
//   rules?: [{ v, label?, color?, dash? }], // horizontal reference rules
//   annotations?: [{ at: Date, label }],
//   hoverPoints?: [{ i, aria, lines:[{t,em}] }],   // hoverable indices, in order
//   hover?: { index, pinned, onEnter(bi), onPin(bi,e), onKey(e), onLeave() },
//   extraLayers?: [...]                     // pre-built layers (heatmap cells)
// }
export function buildSpec(desc) {
  const kindName = desc.kind || "trend";
  const spark = kindName !== "trend";   // 'spark' and 'cells' both drop axis/legend chrome
  const frame = desc.frame || {};
  const w = frame.w != null ? frame.w : 600;
  const h = frame.h != null ? frame.h : 150;
  const series = desc.series || [];
  const anns0 = desc.annotations || [];
  const basePad = frame.pad || (spark
    ? { l: 2, r: 2, t: 2, b: 2 }
    : { l: 44, r: 10, t: 10, b: 18 });
  // annotation lanes and the y unit/direction label live above the plot —
  // reserve headroom so neither collides with the top tick
  const laneCap = anns0.length ? Math.min(3, anns0.length) : 0;
  const yLabelPad = !spark && ((desc.y && desc.y.label) || ((desc.y && desc.y.policy) || {}).dirLabel) ? 10 : 0;
  const pad = { ...basePad, t: basePad.t + laneCap * 10 + yLabelPad };
  const plot = { x: pad.l, y: pad.t, w: w - pad.l - pad.r, h: h - pad.t - pad.b };

  // ── y: one policy-resolved domain across every series ──
  const policy = (desc.y && desc.y.policy) || {};
  const include = [...((desc.y && desc.y.include) || []), ...(desc.rules || []).map((r) => r.v)];
  const allVals = series.flatMap((s) => s.values || []);
  const dom = resolveDomain(allVals, policy, include);
  const ys = scaleLinear().domain([dom.min, dom.max]).range([plot.y + plot.h, plot.y]);
  const yTicks = spark ? [] : dom.ticks.map((t) => ({ y: +ys(t.v).toFixed(1), label: t.label, v: t.v }));

  // ── x: time / band / point ──
  const xk = desc.x || {};
  const n = xk.n != null ? xk.n : Math.max(0, ...series.map((s) => (s.values || []).length));
  const dates = xk.dates || null;
  let xAt, xTicks = [], band = null, xScaleForAnns = null;
  if (xk.kind === "linear" && xk.values && xk.values.length > 1) {
    // numeric x (elapsed seconds / metres) — the run page's shared axis
    const ls = scaleLinear().domain(extent(xk.values.filter((v) => v != null))).range([plot.x, plot.x + plot.w]);
    xAt = (i) => ls(xk.values[i]);
    if (!spark && !xk.noTicks) {
      const xf = xk.fmt || fmt.int;
      xTicks = ls.ticks(Math.min(7, Math.max(2, Math.floor(plot.w / 70))))
        .map((v) => ({ x: +ls(v).toFixed(1), label: xf(v) }));
    }
    xScaleForAnns = ls;
  } else if (xk.kind === "band") {
    const bs = scaleBand().domain(Array.from({ length: n }, (_, i) => i)).range([plot.x, plot.x + plot.w]).paddingInner(0.35).paddingOuter(0.15);
    band = { x: (i) => bs(i), w: bs.bandwidth() };
    xAt = (i) => bs(i) + bs.bandwidth() / 2;
    if (xk.labels && !spark) xTicks = thinLabels(xk.labels, xAt, plot.w);
    else if (dates && !spark) xTicks = monthChangeTicks(dates, xAt);
    if (dates) xScaleForAnns = (d) => xAt(nearestIndex(dates, d));
  } else if (xk.kind === "time" && dates && dates.length > 1) {
    const ts = scaleUtc().domain(extent(dates)).range([plot.x, plot.x + plot.w]);
    xAt = (i) => ts(dates[i]);
    if (!spark) {
      const tks = ts.ticks(Math.min(6, Math.max(2, Math.floor(plot.w / 80))));
      xTicks = tks.map((d, ti) => ({ x: +ts(d).toFixed(1), label: timeTickLabel(d, ti === 0) }));
    }
    xScaleForAnns = ts;
  } else {
    const ps = scalePoint().domain(Array.from({ length: n }, (_, i) => i)).range([plot.x, plot.x + plot.w]);
    xAt = (i) => ps(i);
    if (xk.labels && !spark) xTicks = thinLabels(xk.labels, xAt, plot.w);
    else if (dates && !spark) xTicks = monthChangeTicks(dates, xAt);
    if (dates) xScaleForAnns = (d) => xAt(nearestIndex(dates, d));
  }

  const layers = [];

  // ── reference layer (bottom): median band / target span / rolling mean ──
  const ref = desc.ref !== undefined ? desc.ref : policy.ref;
  if (ref && series.length) {
    const src = (ref.of ? series.find((s) => s.key === ref.of) : series[0]) || series[0];
    if (ref.type === "medianBand") {
      const bd = bandFromSeries(src.values, ref.window);
      const gen = d3area()
        .x((_, i) => xAt(i))
        .y0((_, i) => ys(bd.lower[i]))
        .y1((_, i) => ys(bd.upper[i]))
        .defined((_, i) => bd.lower[i] != null);
      const mgen = d3line().x((_, i) => xAt(i)).y((_, i) => ys(bd.mid[i])).defined((_, i) => bd.mid[i] != null);
      layers.push({ kind: "band", d: gen(src.values), role: "baseline" });
      layers.push({ kind: "line", paths: [mgen(src.values)], color: "var(--sub)", width: 1, dash: "2 3", role: "baseline-mid" });
    } else if (ref.type === "span") {
      const y1 = ys(ref.hi), y0 = ys(ref.lo);
      layers.push({ kind: "band", d: `M${plot.x} ${y1.toFixed(1)} H${(plot.x + plot.w).toFixed(1)} V${y0.toFixed(1)} H${plot.x} Z`, role: "target" });
    } else if (ref.type === "meanLine") {
      const rm = rollingMean(src.values, ref.window);
      const mgen = d3line().x((_, i) => xAt(i)).y((_, i) => ys(rm[i])).defined((_, i) => rm[i] != null);
      layers.push({ kind: "line", paths: [mgen(src.values)], color: "var(--sub)", width: 1.5, dash: "2 3", role: "baseline-mid" });
    }
  }

  // ── ribbon: the shaded gap between two series (trajectory) ──
  if (desc.ribbon) {
    const A = series.find((s) => s.key === desc.ribbon[0]);
    const B = series.find((s) => s.key === desc.ribbon[1]);
    if (A && B) {
      const gen = d3area()
        .x((_, i) => xAt(i))
        .y0((_, i) => ys(A.values[i]))
        .y1((_, i) => ys(B.values[i]))
        .defined((_, i) => A.values[i] != null && B.values[i] != null);
      layers.push({ kind: "band", d: gen(A.values), role: "ribbon" });
    }
  }

  // ── horizontal value spans (HR zone bands behind the heart-rate track) ──
  for (const sp of desc.spans || []) {
    const yHi = ys(Math.min(dom.max, sp.hi));
    const yLo = ys(Math.max(dom.min, sp.lo));
    if (yLo <= yHi) continue; // span entirely outside the domain
    layers.push({
      kind: "band", role: "span", fill: sp.color, opacity: sp.opacity != null ? sp.opacity : 0.14,
      d: `M${plot.x} ${yHi.toFixed(1)} H${(plot.x + plot.w).toFixed(1)} V${yLo.toFixed(1)} H${plot.x} Z`,
    });
  }

  // ── horizontal rules (goals) ──
  for (const r of desc.rules || []) {
    layers.push({ kind: "rule", y: +ys(r.v).toFixed(1), label: r.label, color: r.color || "var(--accent)", dash: r.dash || "5 5" });
  }

  // ── series marks ──
  const nBarSeries = series.filter((s) => (s.marks || ["line"]).includes("bars")).length;
  let barSeriesSeen = 0;
  for (const s of series) {
    const marks = s.marks || ["line"];
    const weights = s.weights || null;
    const wpol = policy.weights || {};
    const excluded = weights ? (i) => !isConfident(weights[i], wpol) : null;

    if (marks.includes("bars") && band) {
      const gap = 1; // surface gap between grouped bars
      const bw = nBarSeries > 1 ? band.w / nBarSeries : band.w;
      const si = barSeriesSeen++;
      const bars = [];
      (s.values || []).forEach((v, i) => {
        if (v == null || !Number.isFinite(v)) return; // absent month: no bar at all
        const x = band.x(i) + si * bw;
        const y0 = ys(Math.max(0, dom.min));
        const y = ys(v);
        bars.push({
          x: +(x + (nBarSeries > 1 ? gap / 2 : 0)).toFixed(1),
          y: +Math.min(y, y0).toFixed(1),
          w: +(bw - (nBarSeries > 1 ? gap : 0)).toFixed(1),
          h: +Math.max(1, Math.abs(y0 - y)).toFixed(1),
          color: s.color,
        });
      });
      layers.push({ kind: "bars", bars, name: s.name });
    }

    if (marks.includes("line")) {
      const gen = d3line().x((i) => xAt(i)).y((i) => ys(s.values[i]));
      const paths = segmentIndices(s.values, excluded)
        .filter((seg) => seg.length > 1)
        .map((seg) => gen(seg));
      layers.push({ kind: "line", paths, color: s.color, width: s.width != null ? s.width : 2, dash: s.dash, name: s.name });
    }

    if (marks.includes("dots")) {
      const dots = [];
      (s.values || []).forEach((v, i) => {
        if (v == null || !Number.isFinite(v)) return;
        const hollow = excluded ? excluded(i) : false;
        dots.push({
          x: +xAt(i).toFixed(1), y: +ys(v).toFixed(1),
          r: weights ? confidenceRadius(weights[i], wpol) : 2.6,
          color: s.color, hollow,
        });
      });
      layers.push({ kind: "dots", dots, name: s.name });
    }
  }

  // ── annotations (race day, records) ──
  if (anns0.length && xScaleForAnns) {
    const flags = placeAnnotations(anns0, xScaleForAnns, w).map((f) => ({
      ...f,
      labelY: +(pad.t - 4 - f.lane * 10).toFixed(1),
      y0: pad.t, y1: plot.y + plot.h,
    }));
    if (flags.length) layers.push({ kind: "annotations", flags });
  }

  if (desc.extraLayers) layers.push(...desc.extraLayers);

  // ── hover: chart-hover.js geometry, unchanged ──
  const hp = desc.hoverPoints || [];
  const hoverPts = hp.map((p) => {
    const dots = p.dots || series
      .map((s) => (s.values && s.values[p.i] != null && Number.isFinite(s.values[p.i]))
        ? { x: +xAt(p.i).toFixed(2), y: +ys(s.values[p.i]).toFixed(2), color: s.color } : null)
      .filter(Boolean);
    const anchor = (p.x != null && p.y != null) ? { x: p.x, y: p.y }
      : dots.length ? dots[0]
      : { x: +xAt(p.i).toFixed(2), y: plot.y + plot.h / 2 };
    return { i: p.i, x: anchor.x, y: anchor.y, aria: p.aria || "", lines: p.lines || [], dots };
  });
  const hstate = desc.hover || {};
  // cells mode (heatmap): the cells carry their own hit targets, so no band
  // rects tile the frame and no crosshair tracks the x — only the card
  const cellsMode = desc.hoverMode === "cells";
  const bands = cellsMode ? [] : bandRects(hoverPts, w, h).map((b, bi) => ({ ...b, i: bi }));
  let card = null, cross = null, activeDots = [];
  if (hstate.index != null && hstate.index >= 0 && hstate.index < hoverPts.length) {
    const p = hoverPts[hstate.index];
    const pl = cardPlace(p.x, p.y, w, h);
    card = { ...pl, rows: p.lines };
    if (!cellsMode) cross = { x: p.x, top: 0, bot: h };
    activeDots = p.dots;
  }
  // continuous crosshair (run-detail D3): a page-computed sample index — used
  // by the multi-track stack where band rects would be sub-pixel
  if (desc.cross && desc.cross.i != null && xAt) {
    const ci = Math.max(0, Math.min(n - 1, desc.cross.i));
    const cx = xAt(ci);
    if (Number.isFinite(cx)) {
      cross = { x: +cx.toFixed(2), top: plot.y, bot: plot.y + plot.h };
      activeDots = series
        .map((s) => (s.values && s.values[ci] != null && Number.isFinite(s.values[ci]))
          ? { x: cross.x, y: +ys(s.values[ci]).toFixed(2), color: s.color } : null)
        .filter(Boolean);
    }
  }

  if (desc.xTicks) xTicks = desc.xTicks;   // precomputed ticks (heatmap months)

  return {
    id: desc.id,
    kind: kindName,
    frame: { w, h, pad },
    height: desc.height || null,   // CSS render height for the view (e.g. '130px')
    clipPlot: !!desc.clipPlot,     // clip mark layers to the plot rect (streams)
    plot,
    x: { ticks: xTicks, label: (desc.x && desc.x.label) || null },
    y: { ticks: yTicks, label: (desc.y && desc.y.label) || policy.dirLabel || null, domain: [dom.min, dom.max] },
    layers,
    legend: !spark && series.length >= 2
      ? series.map((s) => ({ name: s.name, color: s.color, mark: (s.marks || ["line"]).includes("bars") ? "square" : "line" }))
      : null,
    hover: {
      id: desc.id,
      bands, points: hoverPts,
      index: hstate.index != null ? hstate.index : null,
      pinned: !!hstate.pinned,
      onEnter: hstate.onEnter, onPin: hstate.onPin, onKey: hstate.onKey, onLeave: hstate.onLeave,
      onMove: hstate.onMove,
      card, cross, activeDots,
    },
    a11y: { role: "img", label: desc.ariaLabel || "", keyboard: true },
  };
}

// explicit per-index labels (year-over-year month row), thinned to fit
function thinLabels(labels, xAt, plotW) {
  const n = labels.length;
  const step = Math.max(1, Math.ceil(n * 34 / Math.max(1, plotW)));
  const out = [];
  for (let i = 0; i < n; i += step) out.push({ x: +xAt(i).toFixed(1), label: labels[i] });
  return out;
}

// ticks where the month changes (band/point x-scales), thinned to a readable count
function monthChangeTicks(dates, xAt) {
  const out = [];
  let lastMonth = -1, lastYear = -1, lastX = -Infinity;
  dates.forEach((d, i) => {
    if (!(d instanceof Date)) return;
    const m = d.getUTCMonth(), y = d.getUTCFullYear();
    if (m === lastMonth && y === lastYear) return;
    const x = +xAt(i).toFixed(1);
    lastMonth = m; lastYear = y;
    if (x - lastX < 44) return; // don't crowd
    lastX = x;
    out.push({ x, label: timeTickLabel(d, out.length === 0) });
  });
  return out;
}
function nearestIndex(dates, d) {
  const t = d instanceof Date ? d.getTime() : new Date(d).getTime();
  let best = 0, bd = Infinity;
  dates.forEach((dt, i) => { const dd = Math.abs(dt.getTime() - t); if (dd < bd) { bd = dd; best = i; } });
  return best;
}

// ── continuous crosshair (run-detail D3) ─────────────────────────────────────
// Pointer x (in viewBox units) → nearest sample index, by bisection over the
// shared x column, clamped at both ends. This is the hover primitive for
// 1,670-sample tracks; bandRects stays the primitive for thirty monthly
// points — two primitives, each correct for its density.
export function crosshairAt(xScale, xs, pointerPx) {
  if (!xs || !xs.length) return null;
  const xVal = xScale.invert(pointerPx);
  const i = Math.max(0, Math.min(xs.length - 1, bisector((d) => d).center(xs, xVal)));
  return { i, x: +(+xScale(xs[i])).toFixed(2) };
}

// ── GPS trace projection (run-detail D2) ─────────────────────────────────────
// Equirectangular with a cos(lat₀) correction on longitude, fitted into a
// w×h viewport with ONE scale for both axes (aspect preserved). No tiles, no
// third-party origin — the trace is the shape of the run, not a basemap.
// Null samples stay null so the polyline can gap honestly.
export function projectTrack(lat, lon, w, h, pad = 8) {
  const n = Math.min((lat || []).length, (lon || []).length);
  const valid = [];
  for (let i = 0; i < n; i++) if (lat[i] != null && lon[i] != null) valid.push(i);
  if (valid.length < 2) return null;
  const lat0 = mean(valid, (i) => lat[i]) * Math.PI / 180;
  const kx = Math.cos(lat0);
  const xsAll = valid.map((i) => lon[i] * kx);
  const ysAll = valid.map((i) => -lat[i]);            // north up
  const [x0, x1] = extent(xsAll);
  const [y0, y1] = extent(ysAll);
  const spanX = (x1 - x0) || 1e-9;
  const spanY = (y1 - y0) || 1e-9;
  const s = Math.min((w - 2 * pad) / spanX, (h - 2 * pad) / spanY);
  const ox = (w - s * spanX) / 2;
  const oy = (h - s * spanY) / 2;
  const points = [];
  for (let i = 0; i < n; i++) {
    if (lat[i] == null || lon[i] == null) { points.push(null); continue; }
    points.push([
      +(ox + (lon[i] * kx - x0) * s).toFixed(2),
      +(oy + (-lat[i] - y0) * s).toFixed(2),
    ]);
  }
  return { points, scale: s };
}

// The x scale multiTrackSpec builds each track with — exported so the page's
// pointer handler bisects against EXACTLY the geometry the tracks rendered.
export function sharedXScale(values, w = 600, padL = 46, padR = 10) {
  return scaleLinear()
    .domain(extent((values || []).filter((v) => v != null)))
    .range([padL, w - padR]);
}

// ── multi-track stack (run-detail D4) ────────────────────────────────────────
// One x domain shared by every track, one y domain per track from the policy
// table. tracks: [{ id, ariaLabel, series, policy, unit?, spans?, h?, height?,
// hover? }]; sharedX: { values (the stored t or d column), fmt, label?, w?,
// cross? ({i} from crosshairAt) }. Returns one ChartSpec per track; the last
// track carries the x tick labels for the whole stack.
export function multiTrackSpec(tracks, sharedX) {
  const nT = tracks.length;
  return tracks.map((tr, ti) => buildSpec({
    id: tr.id,
    ariaLabel: tr.ariaLabel,
    height: tr.height,
    frame: {
      w: sharedX.w != null ? sharedX.w : 600,
      h: tr.h != null ? tr.h : 90,
      pad: { l: 46, r: 10, t: 6, b: ti === nT - 1 ? 18 : 6 },
    },
    x: {
      kind: "linear", values: sharedX.values, fmt: sharedX.fmt,
      noTicks: ti !== nT - 1,
      label: ti === nT - 1 ? sharedX.label : null,
    },
    y: { policy: tr.policy || {}, label: tr.unit },
    series: tr.series,
    spans: tr.spans,
    cross: sharedX.cross,
    clipPlot: true,   // stream spikes draw off the plot edge, never own the scale
    hover: tr.hover || {},
    hoverPoints: [],
  }));
}

// Re-exported so pages and chart-view consume hover geometry through the core
// (chart-hover.js stays the single implementation).
export { bandRects, cardPlace };
