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
