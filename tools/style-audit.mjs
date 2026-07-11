// Computed-style audit for the SPLITS dashboard. Starts its own dev server on
// PORT 8123 (never clashes with `pnpm dev`) and drives headless chromium.
//
//   node tools/style-audit.mjs baseline                 → capture current desktop computed styles → tools/style-baseline.json (the regression baseline)
//   node tools/style-audit.mjs diff                      → print computed-style changes vs baseline (desktop 1200)
//   node tools/style-audit.mjs read '<sel>' <prop...>    → print computed props for a selector (desktop 1200)
//   node tools/style-audit.mjs layout                    → assert the responsive layout map at 1200/768/390 (PASS/FAIL)
//
// Requires: pnpm add -D playwright && pnpm exec playwright install chromium

import { chromium } from "playwright";
import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

process.env.PORT = process.env.AUDIT_PORT || "8123";
const PORT = process.env.PORT;
const PAGE = `http://localhost:${PORT}/Running%20Dashboard.dc.html`;
const PROGRESS = `http://localhost:${PORT}/progress`;
const ARCHIVE = `http://localhost:${PORT}/archive`;
const COMPARE = `http://localhost:${PORT}/compare`;
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

// /progress (progress-views 8.1): the relocated chart grid reflows like the
// cockpit's; the records wall and yoy sections are insight-fed, so they are
// asserted only when the served data file carries them (pre-3a data hides
// them by design — graceful absence, not a layout failure).
const PROGRESS_LAYOUT = {
  "#sec-charts": { 1200: [2, 4], 768: [1, 2], 390: 1 },
};
const PROGRESS_OPTIONAL = ["#sec-records", "#sec-yoy"];

// Topbar parity (design D8): markup is duplicated per page, so these computed
// styles must stay identical between the cockpit and /progress.
const TOPBAR_PARITY = {
  "header.topbar": ["display", "align-items", "justify-content", "padding", "margin", "border-bottom-width"],
  "header.topbar .topbar-actions": ["display", "align-items", "gap", "flex-wrap"],
  "header.topbar nav": ["display", "gap", "padding", "border-top-left-radius", "font-size"],
  "header.topbar nav a": ["font-size", "font-weight", "padding", "text-decoration-line"],
};

// /archive and /compare are deep views (archive-browser): they render either
// their data or an honest offline/prompt state depending on whether an archive
// db is reachable in the audit environment (point SPLITS_ARCHIVE_DIR at a
// local copy for the full assertions). Two streamed runs make /compare render
// its track stack; when the archive is away the audit still asserts the
// offline chrome at every width.
async function resolveCompareIds() {
  try {
    const r = await fetch(`http://localhost:${PORT}/api/archive/activities?type=running&limit=25`);
    if (!r.ok) return null;
    const ids = [];
    for (const a of (await r.json()).activities) {
      const s = await fetch(`http://localhost:${PORT}/api/archive/activities/${a.activityId}/streams`);
      if (s.ok) ids.push(a.activityId);
      if (ids.length === 2) return ids;
    }
  } catch { /* archive away */ }
  return null;
}

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
  await writeFile(BASELINE, JSON.stringify(snap, null, 2) + "\n");
  console.log("baseline written:", fileURLToPath(BASELINE));
} else if (mode === "diff") {
  const base = JSON.parse(await readFile(BASELINE, "utf8"));
  const snap = await snapshot(page, 1200);
  let changed = 0;
  for (const sel of Object.keys(TRACK)) {
    if (!snap[sel]) { console.log(`MISSING: ${sel} (selector not found)`); changed++; continue; }
    for (const p of TRACK[sel]) {
      const a = base[sel]?.[p], b = snap[sel][p];
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
    const cockpitScrollW = await page.evaluate(() => document.documentElement.scrollWidth);
    const cockpitNoOverflow = cockpitScrollW <= width + 1;
    if (!cockpitNoOverflow) code = 1;
    console.log(`${cockpitNoOverflow ? "ok " : "FAIL"} ${width} cockpit no horizontal overflow (scrollWidth=${cockpitScrollW})`);

    // /progress at the same widths (progress-views 8.1)
    await page.goto(PROGRESS, { waitUntil: "networkidle" });
    await page.waitForSelector("#sec-charts");
    for (const [sel, byW] of Object.entries(PROGRESS_LAYOUT)) {
      const v = await read(page, sel, ["grid-template-columns"]);
      const n = trackCount(v?.["grid-template-columns"]);
      const ok = matchCount(n, byW[width]);
      if (!ok) code = 1;
      console.log(`${ok ? "ok " : "FAIL"} ${width} /progress ${sel} tracks=${n} expected=${JSON.stringify(byW[width])}`);
    }
    for (const sel of PROGRESS_OPTIONAL) {
      const present = (await page.$(sel)) !== null;
      console.log(`     ${width} /progress ${sel} ${present ? "present" : "absent (insight data not in the served file — allowed)"}`);
    }
    // the page body must never scroll horizontally (wide content scrolls in
    // its own overflow container)
    const scrollW = await page.evaluate(() => document.documentElement.scrollWidth);
    const noOverflow = scrollW <= width + 1;
    if (!noOverflow) code = 1;
    console.log(`${noOverflow ? "ok " : "FAIL"} ${width} /progress no horizontal overflow (scrollWidth=${scrollW})`);

    // /archive and /compare (archive-browser 2.3): whatever state the archive
    // is in — rows, offline, or the compare prompt — the page never overflows
    const compareIds = await resolveCompareIds();
    const deepViews = [
      ["/archive", ARCHIVE, () => document.querySelector(".arch-row") || /Archive offline|No archived activity/.test(document.body.innerText)],
      ["/compare", compareIds ? `${COMPARE}?ids=${compareIds.join(",")}` : COMPARE,
        () => document.querySelector("svg[data-chart='trend']") || /Archive offline|Nothing to compare/.test(document.body.innerText)],
    ];
    for (const [pgName, url, settled] of deepViews) {
      await page.goto(url, { waitUntil: "domcontentloaded" });
      await page.waitForSelector("header.topbar", { timeout: 15000 });
      await page.waitForFunction(settled, null, { timeout: 15000 }).catch(() => {});
      const sw = await page.evaluate(() => document.documentElement.scrollWidth);
      const ok = sw <= width + 1;
      if (!ok) code = 1;
      console.log(`${ok ? "ok " : "FAIL"} ${width} ${pgName} no horizontal overflow (scrollWidth=${sw})`);
    }
  }

  // topbar computed-style parity across every page carrying the shared bar
  // (markup is duplicated per page — the computed styles must not drift)
  await page.setViewportSize({ width: 1200, height: 1600 });
  await page.goto(PAGE, { waitUntil: "networkidle" });
  await page.waitForSelector("header.topbar");
  const cockpitBar = {};
  for (const [sel, props] of Object.entries(TOPBAR_PARITY)) cockpitBar[sel] = await read(page, sel, props);
  for (const [pgName, url] of [["progress", PROGRESS], ["archive", ARCHIVE], ["compare", COMPARE]]) {
    await page.goto(url, { waitUntil: "domcontentloaded" });
    await page.waitForSelector("header.topbar", { timeout: 15000 });
    for (const [sel, props] of Object.entries(TOPBAR_PARITY)) {
      const here = await read(page, sel, props);
      for (const p of props) {
        const a = cockpitBar[sel]?.[p], b = here?.[p];
        const ok = a === b;
        if (!ok) code = 1;
        console.log(`${ok ? "ok " : "FAIL"} topbar parity ${sel} { ${p}: cockpit=${a} ${pgName}=${b} }`);
      }
    }
  }

  // chart-engine 9.1: every trend chart carries y-axis tick labels and x-axis
  // labels; a legend exists wherever >= 2 series render; and no chart bridges
  // a null — the svg's data-line-paths stamp is the spec's own post-split
  // segment count, checked against the paths actually in the DOM.
  for (const [pgName, url] of [["cockpit", PAGE], ["/progress", PROGRESS]]) {
    await page.setViewportSize({ width: 1200, height: 1600 });
    await page.goto(url, { waitUntil: "networkidle" });
    await page.waitForSelector("svg.chart-svg", { timeout: 15000 });
    const charts = await page.evaluate(() =>
      [...document.querySelectorAll("svg.chart-svg")].map((svg) => {
        const frame = svg.closest(".chart-frame");
        return {
          kind: svg.getAttribute("data-chart"),
          label: (svg.getAttribute("aria-label") || "").slice(0, 44),
          yticks: frame ? frame.querySelectorAll(".chart-ytick").length : 0,
          xticks: frame ? frame.querySelectorAll(".chart-xtick").length : 0,
          legend: frame ? frame.querySelectorAll(".chart-legend-item").length : 0,
          series: Number(svg.getAttribute("data-series") || 0),
          declaredPaths: Number(svg.getAttribute("data-line-paths") || 0),
          domPaths: svg.querySelectorAll("path[data-series-line]").length,
        };
      })
    );
    const trends = charts.filter((c) => c.kind === "trend");
    if (!trends.length) { console.log(`FAIL ${pgName}: no trend charts found`); code = 1; }
    for (const c of trends) {
      const axisOk = c.yticks >= 2 && c.xticks >= 1;
      const legendOk = c.series >= 2 ? c.legend >= 2 : c.legend === 0;
      const gapOk = c.declaredPaths === c.domPaths;
      if (!axisOk || !legendOk || !gapOk) code = 1;
      console.log(`${axisOk && legendOk && gapOk ? "ok " : "FAIL"} chart ${pgName} "${c.label}" yticks=${c.yticks} xticks=${c.xticks} series=${c.series} legend=${c.legend} paths=${c.domPaths}/${c.declaredPaths}`);
    }
  }
  // /compare chart grammar (archive-browser 6.1): the comparison renders a
  // TRACK STACK — x tick labels live on the LAST track only (multiTrackSpec),
  // so the standalone-chart rule above doesn't apply verbatim. Every track
  // still owes y ticks, a legend exactly when it overlays >= 2 runs, and an
  // honest data-line-paths stamp. Runs only when the audit's archive serves
  // two streamed runs; otherwise the offline chrome was asserted above.
  {
    const ids = await resolveCompareIds();
    if (!ids) {
      console.log("     /compare charts skipped (no reachable archive with two streamed runs — point SPLITS_ARCHIVE_DIR at a local copy)");
    } else {
      await page.setViewportSize({ width: 1200, height: 1600 });
      await page.goto(`${COMPARE}?ids=${ids.join(",")}`, { waitUntil: "domcontentloaded" });
      await page.waitForFunction(() => document.querySelectorAll("svg[data-chart='trend']").length >= 2, null, { timeout: 20000 });
      const tracks = await page.evaluate(() =>
        [...document.querySelectorAll("svg[data-chart='trend']")].map((svg) => {
          const frame = svg.closest(".chart-frame");
          return {
            label: (svg.getAttribute("aria-label") || "").slice(0, 44),
            yticks: frame ? frame.querySelectorAll(".chart-ytick").length : 0,
            xticks: frame ? frame.querySelectorAll(".chart-xtick").length : 0,
            legend: frame ? frame.querySelectorAll(".chart-legend-item").length : 0,
            series: Number(svg.getAttribute("data-series") || 0),
            declaredPaths: Number(svg.getAttribute("data-line-paths") || 0),
            domPaths: svg.querySelectorAll("path[data-series-line]").length,
          };
        }));
      if (!tracks.length) { console.log("FAIL /compare: no tracks found"); code = 1; }
      let sawXTicks = false;
      for (const c of tracks) {
        if (c.xticks > 0) sawXTicks = true;
        const yOk = c.yticks >= 2;
        const legendOk = c.series >= 2 ? c.legend >= 2 : c.legend === 0;
        const gapOk = c.declaredPaths === c.domPaths;
        if (!yOk || !legendOk || !gapOk) code = 1;
        console.log(`${yOk && legendOk && gapOk ? "ok " : "FAIL"} chart /compare "${c.label}" yticks=${c.yticks} series=${c.series} legend=${c.legend} paths=${c.domPaths}/${c.declaredPaths}`);
      }
      if (tracks.length && !sawXTicks) { console.log("FAIL /compare: the track stack carries no x axis labels at all"); code = 1; }
      else if (tracks.length) console.log("ok  /compare shared x axis labelled on the stack's last track");
    }
  }

  // chart-drill 6.1: the contribution panel is a registered interactive
  // surface — a keyboard drill on the first insight chart must open a panel
  // that spans the chart grid and never overflows the page, desktop and phone.
  // Skips gracefully when the served data carries no insight charts or the
  // archive is away (the panel then settles on its offline state, also valid).
  for (const width of [1200, 390]) {
    await page.setViewportSize({ width, height: 1600 });
    await page.goto(PROGRESS, { waitUntil: "domcontentloaded" });
    await page.waitForSelector("#sec-charts", { timeout: 15000 });
    // the insight charts mount only after the data module resolves — wait for
    // them, and only a real absence (pre-insights data) skips
    const eff = await page.waitForSelector('svg[aria-label^="Pace at reference HR"]', { timeout: 15000 }).catch(() => null);
    if (!eff) { console.log(`     ${width} /progress drill panel skipped (no insight charts in the served data)`); continue; }
    await eff.focus();
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("Enter");
    const settled = await page.waitForFunction(() => {
      const p = document.querySelector("#drill-panel");
      return p && (p.querySelectorAll("a.drill-run").length > 0
        || p.innerText.includes("Archive offline")
        || p.innerText.includes("No run put time"));
    }, null, { timeout: 15000 }).catch(() => null);
    if (!settled) { console.log(`FAIL ${width} /progress drill panel did not open on keyboard drill`); code = 1; continue; }
    const m = await page.evaluate(() => {
      const p = document.querySelector("#drill-panel");
      const g = document.querySelector("#sec-charts");
      return {
        panelW: p.getBoundingClientRect().width,
        gridW: g ? g.getBoundingClientRect().width : 0,
        scrollW: document.documentElement.scrollWidth,
        focusInPanel: p.contains(document.activeElement),
      };
    });
    const spanOk = m.panelW >= m.gridW * 0.9;
    const overflowOk = m.scrollW <= width + 1;
    if (!spanOk || !overflowOk || !m.focusInPanel) code = 1;
    console.log(`${spanOk && overflowOk && m.focusInPanel ? "ok " : "FAIL"} ${width} /progress drill panel spans the grid (${Math.round(m.panelW)}/${Math.round(m.gridW)}px), focus inside=${m.focusInPanel}, no overflow (scrollWidth=${m.scrollW})`);
  }
  console.log(code ? "LAYOUT: FAIL" : "LAYOUT: ALL PASS");
}

await browser.close();
process.exit(code);
