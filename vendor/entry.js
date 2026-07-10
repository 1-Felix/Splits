// vendor/entry.js — the declared symbol surface of vendor/d3-lite.js.
//
// This file is the SOURCE of the checked-in bundle, not runtime code. It names
// every d3 symbol the chart engine is allowed to use; nothing else is bundled.
// Adding a symbol means editing this file and re-running the documented esbuild
// one-liner (see vendor/README.md), so the dependency surface stays visible in
// review instead of growing silently.
export { scaleLinear, scaleUtc, scaleBand, scalePoint } from "d3-scale";
export { line, area, curveMonotoneX, curveStepAfter } from "d3-shape";
export { extent, bisector, quantile, ticks, max, min, mean, group, rollup } from "d3-array";
export { timeFormat, utcFormat } from "d3-time-format";
