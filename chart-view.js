/* chart-view.js — ChartSpec → React element (chart-engine D2/D6).
 *
 * The ONLY file that turns chart geometry into elements. It computes no
 * geometry of its own: every position in here was resolved by chart-core.js
 * (including the hover card's placement, via chart-hover.js's cardPlace).
 * Rendered through the dc-runtime's template interpolation — `{{ vo2.chart }}`
 * in a template mounts the element tree returned here.
 *
 * Split of duties inside one chart: the SVG stretches to the card
 * (preserveAspectRatio="none" + non-scaling strokes) and carries only the
 * stretch-safe marks — grid, areas, bars, lines, rules, hit bands, crosshair.
 * TEXT and DOTS are HTML, absolutely positioned at percentage coordinates over
 * the same frame, so tick labels stay crisp at any card width and dots stay
 * round. The floating card already worked exactly this way.
 *
 * The accessibility contract every chart inherits: the svg is focusable,
 * role="img" with a descriptive aria-label, arrow keys traverse points,
 * Enter/Space pins, Escape dismisses, and the focus outline comes from the
 * .chart-svg rule in dashboard.css. No individual chart can omit any of it.
 */

export function renderChart(spec, React) {
  const h = React.createElement;
  const { frame, plot, hover } = spec;
  const W = frame.w, H = frame.h;

  // drill key ladder (chart-drill D1) — wrapped ONLY when the chart declared a
  // descriptor, so every other chart keeps its page handler byte-identical.
  // Enter on a pinned drillable point invokes the action; Escape steps
  // drilled → pinned before the page's Escape dismisses the pin. The engine
  // never fetches or navigates — the action is the chart's.
  const onChartKey = hover.drillDeclared
    ? (e) => {
        if (e.key === "Escape" && hover.drilled) {
          if (e.preventDefault) e.preventDefault();
          if (hover.onDrillExit) hover.onDrillExit();
          return;
        }
        if (e.key === "Enter" && hover.pinned && hover.drill) {
          if (e.preventDefault) e.preventDefault();
          hover.drill.action();
          return;
        }
        if (hover.onKey) hover.onKey(e);
      }
    : hover.onKey;
  const px = (v) => +(v / W * 100).toFixed(3) + "%";
  const py = (v) => +(v / H * 100).toFixed(3) + "%";
  const svgKids = [];
  const html = [];

  // ── rep bands (add-interval-lens): FIRST children, so grid, baseline
  //    bands, series lines and dots all paint over them — a rep highlight
  //    must never obscure the line it highlights. Geometry (x/width, already
  //    clipped to the plot) comes from chart-core.js; this file draws it,
  //    nothing more ──
  (spec.repBands || []).forEach((b, i) => {
    svgKids.push(h("rect", {
      key: "repband-" + i, className: "rep-band",
      x: b.x, y: plot.y, width: b.width, height: plot.h,
      fill: "var(--accentFade)", "aria-hidden": "true",
    }));
  });

  // ── grid + axes (ticks only — never fixed-pixel decoration) ──
  spec.y.ticks.forEach((t, i) => {
    svgKids.push(h("line", { key: "gy" + i, x1: plot.x, x2: plot.x + plot.w, y1: t.y, y2: t.y, stroke: "var(--grid)", strokeWidth: 1, vectorEffect: "non-scaling-stroke" }));
    html.push(h("span", {
      key: "gyl" + i, className: "chart-ytick",
      style: { position: "absolute", left: 0, width: "calc(" + px(plot.x) + " - 5px)", top: py(t.y), transform: "translateY(-50%)", textAlign: "right" },
    }, t.label));
  });
  spec.x.ticks.forEach((t, i) => {
    html.push(h("span", {
      key: "gxl" + i, className: "chart-xtick",
      style: { position: "absolute", left: px(t.x), top: py(plot.y + plot.h), transform: "translateX(-50%)", paddingTop: "3px" },
    }, t.label));
  });
  if (spec.y.label) {
    // INSIDE the reserved headroom, not above it. `top: py(plot.y) - 9px` with
    // translateY(-100%) put the label its own height ABOVE that band, which on
    // a stack landed it on top of the track caption of the track above — the
    // "bpm" over "HEART RATE" collision, visible at every width, not only on a
    // phone. buildSpec reserves 10 frame units of headroom for exactly this,
    // so sit in them.
    html.push(h("span", {
      key: "ydir", className: "chart-ytick",
      style: { position: "absolute", left: 0, width: "calc(" + px(plot.x) + " - 5px)", top: py(plot.y - 10), textAlign: "right", opacity: 0.85 },
    }, spec.y.label));
  }

  // ── layers, in the z-order chart-core emitted them ──
  spec.layers.forEach((l, li) => {
    if (l.kind === "band") {
      svgKids.push(h("path", {
        key: "L" + li, d: l.d,
        style: { fill: l.fill || (l.role === "ribbon" ? "var(--accentFade)" : "var(--grid)") },
        opacity: l.opacity != null ? l.opacity : (l.role === "ribbon" ? 1 : 0.9),
      }));
    } else if (l.kind === "rule") {
      svgKids.push(h("line", { key: "L" + li, x1: plot.x, x2: plot.x + plot.w, y1: l.y, y2: l.y, style: { stroke: l.color }, strokeWidth: 1.4, strokeDasharray: l.dash, vectorEffect: "non-scaling-stroke" }));
      if (l.label) {
        html.push(h("span", {
          key: "Ll" + li, className: "chart-flag",
          style: { position: "absolute", right: px(frame.w - plot.x - plot.w), top: py(l.y), transform: "translateY(-100%)", paddingBottom: "2px" },
        }, l.label));
      }
    } else if (l.kind === "line") {
      l.paths.forEach((d, pi) => {
        if (!d) return;
        svgKids.push(h("path", {
          key: "L" + li + "p" + pi, d, fill: "none",
          "data-series-line": l.role ? undefined : "",   // reference lines carry a role; series lines don't
          style: { stroke: l.color, vectorEffect: "non-scaling-stroke" },
          strokeWidth: l.width != null ? l.width : 2,
          strokeDasharray: l.dash, strokeLinejoin: "round", strokeLinecap: "round",
        }));
      });
    } else if (l.kind === "bars") {
      l.bars.forEach((b, bi) => {
        svgKids.push(h("rect", { key: "L" + li + "b" + bi, x: b.x, y: b.y, width: b.w, height: b.h, rx: 1.5, style: { fill: b.color } }));
      });
    } else if (l.kind === "dots") {
      l.dots.forEach((d, di) => {
        const size = d.r * 2;
        html.push(h("span", {
          key: "L" + li + "d" + di,
          style: {
            position: "absolute", left: px(d.x), top: py(d.y),
            width: size + "px", height: size + "px", borderRadius: "50%",
            transform: "translate(-50%,-50%)", pointerEvents: "none",
            background: d.hollow ? "var(--panel)" : d.color,
            border: d.hollow ? "1.5px solid " + d.color : "1px solid var(--panel)",
          },
        }));
      });
    } else if (l.kind === "annotations") {
      l.flags.forEach((f, fi) => {
        svgKids.push(h("line", { key: "L" + li + "a" + fi, x1: f.x, x2: f.x, y1: f.y0, y2: f.y1, stroke: "var(--sub)", strokeWidth: 1, strokeDasharray: "2 3", opacity: 0.55, vectorEffect: "non-scaling-stroke" }));
        const atEnd = f.x > W * 0.85;
        html.push(h("span", {
          key: "L" + li + "al" + fi, className: "chart-flag",
          // a grouped flag names what it stands for, so nothing the data
          // carries is lost to crowding
          title: f.grouped ? f.grouped.join(" · ") : undefined,
          "aria-label": f.grouped ? f.grouped.join(", ") : undefined,
          style: {
            position: "absolute", left: px(f.x), top: py(f.labelY),
            transform: atEnd ? "translate(-100%,-100%)" : "translateY(-100%)",
            paddingLeft: atEnd ? 0 : "3px", paddingRight: atEnd ? "3px" : 0,
            whiteSpace: "nowrap",
          },
        }, f.label));
      });
    } else if (l.kind === "labels") {
      // free-positioned text (heatmap month row) — HTML, crisp at any width
      l.labels.forEach((t, ti) => {
        html.push(h("span", {
          key: "L" + li + "t" + ti, className: "chart-xtick",
          style: { position: "absolute", left: px(t.x), top: py(t.y), transform: t.anchor === "middle" ? "translateX(-50%)" : undefined },
        }, t.label));
      });
    } else if (l.kind === "cells") {
      // heatmap cells are their OWN hit targets (no band rects in cells mode)
      l.cells.forEach((c, ci) => {
        svgKids.push(h("rect", {
          key: "L" + li + "c" + ci, x: c.x, y: c.y, width: c.w, height: c.h,
          rx: c.rx != null ? c.rx : 2.5,
          style: { fill: c.fill, cursor: c.onEnter ? "pointer" : undefined },
          stroke: c.stroke, strokeWidth: c.stroke ? (c.strokeWidth != null ? c.strokeWidth : 1.5) : undefined,
          "data-hb": c.onEnter ? hover.id : undefined,
          onMouseEnter: c.onEnter, onClick: c.onClick,
          "aria-label": c.aria,
        }));
      });
    }
  });

  // ── hover: hit bands, crosshair (svg) + active dots (html) — geometry from core ──
  hover.bands.forEach((b) => {
    const p = hover.points[b.i] || {};
    svgKids.push(h("rect", {
      key: "hb" + b.i, "data-hb": hover.id,
      x: b.x, y: b.y, width: b.w, height: b.h, fill: "transparent",
      style: { cursor: "pointer" },
      onMouseEnter: hover.onEnter ? () => hover.onEnter(b.i) : undefined,
      onClick: hover.onPin ? (e) => hover.onPin(b.i, e) : undefined,
      "aria-label": p.aria || "",
    }));
  });
  if (hover.cross) {
    svgKids.push(h("line", { key: "hcross", x1: hover.cross.x, x2: hover.cross.x, y1: hover.cross.top, y2: hover.cross.bot, style: { stroke: "var(--sub)", pointerEvents: "none" }, strokeWidth: 1, strokeDasharray: "3 3", vectorEffect: "non-scaling-stroke" }));
  }
  (hover.activeDots || []).forEach((d, di) => {
    html.push(h("span", {
      key: "hdot" + di,
      style: {
        position: "absolute", left: px(d.x), top: py(d.y), width: "9px", height: "9px",
        borderRadius: "50%", transform: "translate(-50%,-50%)", pointerEvents: "none",
        background: d.color, border: "1.5px solid var(--bg)", zIndex: 3,
      },
    }));
  });

  // audit stamps: the spec's own expectations, verifiable against the DOM —
  // data-line-paths is the SEGMENT count after null-splitting, so a bridged
  // gap (one path where the spec says two) fails tools/style-audit.mjs
  const lineSegments = spec.layers
    .filter((l) => l.kind === "line" && !l.role)
    .reduce((a, l) => a + l.paths.filter(Boolean).length, 0);
  const seriesCount = new Set(spec.layers
    .filter((l) => (l.kind === "line" || l.kind === "bars" || l.kind === "dots") && !l.role && l.name)
    .map((l) => l.name)).size;

  // stream tracks clip their mark layers to the plot rect, so a GPS spike
  // beyond the quantile-resolved domain runs off the edge instead of lying
  let svgBody = svgKids;
  if (spec.clipPlot) {
    const clipId = "clip-" + (spec.id || "plot");
    svgBody = [
      h("defs", { key: "defs" }, h("clipPath", { key: "cp", id: clipId },
        h("rect", { x: plot.x, y: 0, width: plot.w, height: frame.h }))),
      h("g", { key: "clipped", clipPath: `url(#${clipId})` }, ...svgKids),
    ];
  }

  // ── the touch path (chart-engine D6) ──────────────────────────────────────
  // A tap used to work only because the browser synthesises a mouse event
  // afterwards, and a DRAG produced no events at all: the whole engine hung
  // off onMouseEnter on per-point hit bands. Pointer events give touch and pen
  // a real path — press places the reading, drag scrubs it, release keeps it —
  // and every handler bails on `pointerType === "mouse"`, so the existing
  // mouse handlers stay the ONLY path a mouse takes and desktop cannot regress.
  //
  // Resolution is by NEAREST BAND rather than by hitting one: at 390px the
  // points on a 30-month chart are spaced 9–11px apart, well under any usable
  // touch target, and bandRects tile the full width by construction so they
  // cannot simply be widened. This is chart-core's crosshairAt reasoning
  // applied to the band primitive.
  const xUnits = (e, el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 ? (e.clientX - r.left) / r.width * W : null;
  };
  const nearestBand = (x) => {
    let best = null, bd = Infinity;
    for (const b of hover.bands) {
      if (x >= b.x && x <= b.x + b.w) return b.i;
      const d = Math.min(Math.abs(x - b.x), Math.abs(x - (b.x + b.w)));
      if (d < bd) { bd = d; best = b.i; }
    }
    return best;
  };
  const touchAt = (e, pin) => {
    const x = xUnits(e, e.currentTarget);
    if (x == null) return;
    if (hover.onMove) hover.onMove(x, e);            // continuous crosshair tracks
    if (!hover.bands.length) return;
    const i = nearestBand(x);
    if (i == null) return;
    if (hover.onEnter) hover.onEnter(i);
    if (pin && hover.onPin) hover.onPin(i, e);
  };
  const isTouch = (e) => e.pointerType && e.pointerType !== "mouse";
  const pointerProps = (hover.onMove || hover.bands.length) ? {
    onPointerDown: (e) => {
      if (!isTouch(e)) return;
      if (e.currentTarget.setPointerCapture && e.pointerId != null) {
        try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* released already */ }
      }
      touchAt(e, false);
    },
    onPointerMove: (e) => {
      if (!isTouch(e)) return;
      if (e.buttons === 0 && e.pressure === 0) return;   // a hovering pen, not a scrub
      touchAt(e, false);
    },
    onPointerUp: (e) => { if (isTouch(e)) touchAt(e, true); },
    onPointerCancel: (e) => { if (isTouch(e) && hover.onLeave) hover.onLeave(e); },
  } : {};

  const svg = h("svg", {
    key: "svg",
    viewBox: `0 0 ${W} ${H}`,
    className: "chart-svg",
    "data-chart": spec.kind,
    "data-line-paths": lineSegments,
    "data-series": seriesCount,
    preserveAspectRatio: "none",
    // pan-y so a vertical drag still scrolls the page over a chart, while the
    // horizontal axis belongs to the chart (which is also what the page-swipe
    // guard reads to refuse here)
    style: { width: "100%", height: spec.height || "auto", display: "block", overflow: "visible", touchAction: "pan-y" },
    role: spec.a11y.role,
    "aria-label": spec.a11y.label,
    tabIndex: spec.a11y.keyboard ? 0 : undefined,
    onKeyDown: onChartKey,
    onMouseLeave: hover.onLeave,
    // continuous crosshair (run-detail): normalise the pointer to viewBox x
    // and hand it to the page, which bisects via chart-core's crosshairAt
    onMouseMove: hover.onMove ? (e) => {
      const r = e.currentTarget.getBoundingClientRect();
      if (r.width > 0) hover.onMove((e.clientX - r.left) / r.width * W, e);
    } : undefined,
    ...pointerProps,
  }, ...svgBody);

  // ── legend: present exactly when the chart carries ≥ 2 series; ink text,
  //    identity carried by the mark beside the name, never by coloring text ──
  const legend = spec.legend
    ? h("div", { key: "legend", className: "chart-legend" },
        ...spec.legend.map((s, si) => h("span", { key: "lg" + si, className: "chart-legend-item" },
          h("span", {
            key: "sw",
            style: s.mark === "square"
              ? { width: "8px", height: "8px", borderRadius: "2px", background: s.color, display: "inline-block", marginRight: "5px" }
              : { width: "12px", height: "3px", borderRadius: "2px", background: s.color, display: "inline-block", marginRight: "5px", verticalAlign: "middle" },
          }),
          s.name)))
    : null;

  // ── floating card (placement computed by chart-core via cardPlace) ──
  // A pinned card with a drill becomes the second activation target: clicking
  // it invokes the action (stopPropagation so the page's dismiss-on-click
  // never races the drill), and the affordance row renders visibly distinct.
  let card = null;
  if (hover.card) {
    const c = hover.card;
    const tx = c.anchorX === "left" ? "0" : c.anchorX === "right" ? "-100%" : "-50%";
    const ty = c.place === "above" ? "calc(-100% - 9px)" : "9px";
    card = h("div", {
      key: "card", "data-card": hover.id, className: "pop",
      onClick: hover.drill ? (e) => {
        if (e.stopPropagation) e.stopPropagation();
        // a mouse drill mirrors the keyboard one: the chart svg takes focus
        // BEFORE the action, so whoever opens an evidence view and closes it
        // gets focus back on the chart (the card itself is not focusable and
        // the mousedown just blurred whatever was)
        const svgEl = e.currentTarget && e.currentTarget.parentElement
          && e.currentTarget.parentElement.querySelector("svg.chart-svg");
        if (svgEl && svgEl.focus) svgEl.focus();
        hover.drill.action();
      } : undefined,
      style: {
        position: "absolute", left: c.leftPct + "%", top: c.topPct + "%",
        transform: `translate(${tx}, ${ty})`, zIndex: 6,
        cursor: hover.drill ? "pointer" : undefined,
        // .pop is pointer-transparent so hover cards never steal the mouse
        // from the chart; a DRILL card is a click target and must override
        // that, or every click lands on the chart behind it
        pointerEvents: hover.drill ? "auto" : undefined,
      },
    }, ...c.rows.map((r, ri) => (r.drill
      // The drill affordance is a real BUTTON, not a line of text inside a
      // card whose activation depended on a second click surviving a
      // re-render. A/B'd at the same viewport before this change: mouse@390
      // opened the panel, touch@390 dismissed the pin and opened nothing.
      // A button calls hover.drill.action() directly, and the phone tier gives
      // it the 44px it owes a thumb.
      ? h("button", {
          key: "r" + ri, type: "button", className: "pop-drill",
          onClick: (e) => {
            if (e.stopPropagation) e.stopPropagation();
            const svgEl = e.currentTarget.closest
              && e.currentTarget.closest("div").parentElement
              && e.currentTarget.closest("div").parentElement.querySelector("svg.chart-svg");
            if (svgEl && svgEl.focus) svgEl.focus();
            if (hover.drill) hover.drill.action();
          },
        }, r.t)
      : h("div", {
          key: "r" + ri,
          style: { color: r.em ? "var(--ink)" : "var(--sub)", fontWeight: r.em ? "800" : "600", fontFamily: "'JetBrains Mono',monospace" },
        }, r.t))));
  }

  const overlay = h("div", { key: "overlay", style: { position: "absolute", inset: 0, pointerEvents: "none" }, "aria-hidden": "true" }, ...html);

  // legend sits above the plot box; % coordinates are relative to the svg frame
  const plotBox = h("div", { key: "plotbox", style: { position: "relative" } },
    svg, overlay, ...(card ? [card] : []));

  return h("div", { className: "chart-frame" },
    ...(legend ? [legend] : []), plotBox);
}

// ── the GPS trace (run-detail D2 + route-basemap): a projected polyline, with
// an optional basemap behind it. proj comes from chart-core's projectTrack or
// projectTrackMercator; null samples gap the line honestly. opts.tiles
// ({href, px, py} from tileLayout, hrefs SAME-ORIGIN) paints a single
// dark-treatable <g> before the route — the route, markers and pin never
// depend on it: a tile that fails to load is a bare patch, not an error.
export function renderTrace(proj, React, opts = {}) {
  const h = React.createElement;
  const W = opts.w || 300, H = opts.h || 300;
  const segs = [];
  let seg = [];
  for (const p of proj.points) {
    if (!p) { if (seg.length > 1) segs.push(seg); seg = []; continue; }
    seg.push(p);
  }
  if (seg.length > 1) segs.push(seg);
  const kids = segs.map((s, i) => h("path", {
    key: "s" + i,
    d: "M" + s.map((p) => p[0] + " " + p[1]).join(" L"),
    fill: "none",
    style: { stroke: "var(--series1)", vectorEffect: "non-scaling-stroke" },
    strokeWidth: 2, strokeLinejoin: "round", strokeLinecap: "round",
  }));
  const flat = proj.points.filter(Boolean);
  if (flat.length) {
    kids.push(h("circle", { key: "start", cx: flat[0][0], cy: flat[0][1], r: 4, style: { fill: "var(--good)" }, stroke: "var(--panel)", strokeWidth: 1.5 }));
    kids.push(h("circle", { key: "fin", cx: flat[flat.length - 1][0], cy: flat[flat.length - 1][1], r: 4, style: { fill: "var(--warn)" }, stroke: "var(--panel)", strokeWidth: 1.5 }));
  }
  if (opts.pin) {
    kids.push(h("circle", { key: "pin", cx: opts.pin[0], cy: opts.pin[1], r: 5, style: { fill: "var(--ink)", pointerEvents: "none" }, stroke: "var(--bg)", strokeWidth: 2 }));
  }
  if (opts.tiles && opts.tiles.length) {
    kids.unshift(h("g", { key: "basemap", className: "trace-basemap", "aria-hidden": "true" },
      ...opts.tiles.map((t) => h("image", {
        key: t.href, href: t.href, x: t.px, y: t.py, width: 256, height: 256,
        preserveAspectRatio: "none",
      }))));
  }
  return h("svg", {
    viewBox: `0 0 ${W} ${H}`,
    role: "img", "aria-label": opts.ariaLabel || "GPS trace of the run",
    className: "chart-svg", "data-chart": "trace",
    style: { width: "100%", height: opts.height || "auto", display: "block" },
  }, ...kids);
}

// Browser global for dc-component inline scripts (same pattern as topbar.js).
if (typeof window !== "undefined") {
  window.SplitsChartView = { renderChart, renderTrace };
}
