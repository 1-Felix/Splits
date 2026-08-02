// Computed-style audit for the SPLITS dashboard. Starts its own dev server on
// PORT 8123 (never clashes with `pnpm dev`) and drives headless chromium.
//
//   node tools/style-audit.mjs baseline                 → capture current desktop computed styles → tools/style-baseline.json (the regression baseline)
//   node tools/style-audit.mjs diff                      → print computed-style changes vs baseline (desktop 1200); exits 1 when anything moved
//   node tools/style-audit.mjs read '<sel>' <prop...>    → print computed props for a selector (desktop 1200)
//   node tools/style-audit.mjs layout                    → assert the responsive layout map at 1920/1600/1200/768/390/360 (PASS/FAIL)
//
// DATA (make-mobile-native 1.3): every mode runs against the committed fixture
// in fixtures/layout/ — telemetry with a block lens carrying long week labels,
// a full insights block, and a three-run archive — built into a temp directory
// and served through SPLITS_DATA_DIR / SPLITS_ARCHIVE_DIR. Before this, the
// gate ran against whatever telemetry happened to be present: with none it fell
// back to the pages' demo data, #block-section never rendered, and the gate
// printed ALL PASS while /progress overflowed by 67px at 390. Pass --live to
// audit the repo's own data dir instead (what a developer sees locally).
//
// Requires: pnpm add -D playwright && pnpm exec playwright install chromium

import { chromium } from "playwright";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { writeLayoutFixture } from "../fixtures/layout/fixture.mjs";

const mode = process.argv[2] || "diff";
const LIVE = process.argv.includes("--live");

process.env.PORT = process.env.AUDIT_PORT || "8123";
const PORT = process.env.PORT;
const BASELINE = new URL("./style-baseline.json", import.meta.url);

// Build the fixture BEFORE importing serve.mjs — it reads its data dir at
// module scope.
let fixtureDir = null;
if (!LIVE) {
  fixtureDir = await mkdtemp(join(tmpdir(), "splits-layout-fixture-"));
  await writeLayoutFixture(fixtureDir);
  process.env.SPLITS_DATA_DIR = fixtureDir;
  process.env.SPLITS_ARCHIVE_DIR = fixtureDir;
  process.env.SYNC_ON_BOOT = "off";
  process.env.SYNC_AT = "off";
}

const PAGE = `http://localhost:${PORT}/Running%20Dashboard.dc.html`;
const PROGRESS = `http://localhost:${PORT}/progress`;
const ARCHIVE = `http://localhost:${PORT}/archive`;
const COMPARE = `http://localhost:${PORT}/compare`;
const COURSE = `http://localhost:${PORT}/course`;

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

// The sweep. 1920/1600 exercise the wide tier, 768 the tablet tier, 390/360 the
// phone tier — and 360 is the width the audit found the worst compositions at.
const WIDTHS = [1920, 1600, 1200, 768, 390, 360];
// A phone is not 1600px tall. Measuring the phone tier in a desktop-height
// viewport makes every "is it in the viewport" claim trivially true.
const heightFor = (w) => (w <= 700 ? 844 : 1600);

// Expected grid track COUNTS per width. getComputedStyle resolves fr → px, so we
// count tracks, not template strings. ranges are [min,max] inclusive; numbers
// are exact.
const LAYOUT = {
  "#sec-hero":   { 1920: 3, 1600: 3, 1200: 3, 768: 2, 390: 1, 360: 1 },
  "#sec-stats":  { 1920: 4, 1600: 4, 1200: 4, 768: 2, 390: 2, 360: 2 },
  "#sec-week1":  { 1920: 7, 1600: 7, 1200: 7, 768: [2, 6], 390: 1, 360: 1 },
  "#sec-week2":  { 1920: 7, 1600: 7, 1200: 7, 768: [2, 6], 390: 1, 360: 1 },
  "#sec-charts": { 1920: [2, 5], 1600: [2, 5], 1200: [2, 4], 768: [1, 2], 390: 1, 360: 1 },
  "#sec-split":  { 1920: 2, 1600: 2, 1200: 2, 768: 1, 390: 1, 360: 1 },
};

// /progress (progress-views 8.1): the relocated chart grid reflows like the
// cockpit's. #sec-records and #sec-yoy are insight-fed — the committed fixture
// carries an insights block, so since make-mobile-native 1.4 they are HARD
// assertions rather than "absent is allowed".
const PROGRESS_LAYOUT = {
  "#sec-charts": { 1920: [2, 5], 1600: [2, 5], 1200: [2, 4], 768: [1, 2], 390: 1, 360: 1 },
};
const PROGRESS_REQUIRED = ["#sec-records", "#sec-yoy"];

// Topbar parity (design D8): markup is duplicated per page, so these computed
// styles must stay identical between the cockpit and every other page.
const TOPBAR_PARITY = {
  "header.topbar": ["display", "align-items", "justify-content", "padding", "margin", "border-bottom-width"],
  "header.topbar .topbar-actions": ["display", "align-items", "gap", "flex-wrap"],
  "header.topbar nav": ["display", "gap", "padding", "border-top-left-radius", "font-size"],
  "header.topbar nav a": ["font-size", "font-weight", "padding", "text-decoration-line"],
};

// /archive and /compare are deep views (archive-browser): they render either
// their data or an honest offline/prompt state depending on whether an archive
// db is reachable. Against the fixture both always have data.
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

// /run/:id (sweep-lens-tail N7): resolve the newest run, preferring one that
// carries an interval document (the rep table is the page's widest component).
async function resolveRunId() {
  try {
    const r = await fetch(`http://localhost:${PORT}/api/archive/activities?type=running&limit=25`);
    if (!r.ok) return null;
    const acts = (await r.json()).activities;
    return (acts.find((a) => a.intervalShape) || acts[0])?.activityId ?? null;
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

// responsive-layout: "A failure names its cause". Reports the LEAF elements
// that actually extend the document past the viewport, skipping anything a
// scrollable/clipping ancestor already contains (a 900px-wide table inside an
// `overflow-x: auto` card is by design, not an overflow bug).
async function overflowLeaves(page, width) {
  return page.evaluate((vw) => {
    const CLIPS = new Set(["auto", "scroll", "hidden", "clip"]);
    const clipped = (el) => {
      for (let p = el.parentElement; p; p = p.parentElement) {
        if (CLIPS.has(getComputedStyle(p).overflowX)) return true;
      }
      return false;
    };
    const over = [];
    for (const el of document.querySelectorAll("body *")) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) continue;
      if (r.right + window.scrollX <= vw + 1) continue;
      if (clipped(el)) continue;
      over.push(el);
    }
    // keep only the leaves: an ancestor is wide *because* of its child
    const leaves = new Set(over);
    for (const el of over) for (let p = el.parentElement; p; p = p.parentElement) leaves.delete(p);
    const name = (el) => el.tagName.toLowerCase()
      + (el.id ? "#" + el.id : "")
      + (typeof el.className === "string" && el.className ? "." + el.className.trim().split(/\s+/).join(".") : "");
    return [...leaves].slice(0, 4).map((el) => {
      const r = el.getBoundingClientRect();
      return { sel: name(el), right: Math.round(r.right + window.scrollX), width: Math.round(r.width),
               text: (el.textContent || "").trim().slice(0, 40) };
    });
  }, width);
}

// The one container every page shares (mobile-chrome 2.7). Null when the page
// has not been given one — the wide-tier assertions treat that as a failure.
async function shellWidth(page) {
  return page.evaluate(() => {
    const el = document.querySelector(".page-shell");
    return el ? Math.round(el.getBoundingClientRect().width) : null;
  });
}

async function snapshot(page, width) {
  await page.setViewportSize({ width, height: heightFor(width) });
  await page.goto(PAGE, { waitUntil: "networkidle" });
  await page.waitForSelector("#sec-hero");
  const out = {};
  for (const [sel, props] of Object.entries(TRACK)) out[sel] = await read(page, sel, props);
  return out;
}

const browser = await chromium.launch();
const page = await browser.newPage();
let code = 0;

// One assertion helper so every check reports the same way and no branch can
// forget to move `code` (make-mobile-native 1.7: `diff` could never fail).
function check(ok, line) {
  if (!ok) code = 1;
  console.log(`${ok ? "ok " : "FAIL"} ${line}`);
  return ok;
}

async function assertNoOverflow(page, width, label) {
  const sw = await page.evaluate(() => document.documentElement.scrollWidth);
  const ok = sw <= width + 1;
  check(ok, `${width} ${label} no horizontal overflow (scrollWidth=${sw})`);
  if (!ok) {
    for (const l of await overflowLeaves(page, width)) {
      console.log(`       ↳ ${l.sel} right=${l.right} width=${l.width}${l.text ? ` "${l.text}"` : ""}`);
    }
  }
  return ok;
}

try {
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
    // A diff that printed changes and still exited 0 could never gate anything.
    if (changed) code = 1;
    console.log(changed ? `${changed} change(s) — review against expected nudges.` : "no changes vs baseline.");
  } else if (mode === "read") {
    const sel = process.argv[3];
    const props = process.argv.slice(4).filter((a) => a !== "--live");
    await page.setViewportSize({ width: 1200, height: 1600 });
    await page.goto(PAGE, { waitUntil: "networkidle" });
    await page.waitForSelector("#sec-hero");
    console.log(sel, await read(page, sel, props));
  } else if (mode === "layout") {
    const compareIds = await resolveCompareIds();
    const runId = await resolveRunId();
    if (!compareIds) check(LIVE, "/compare has two streamed runs to compare");
    if (!runId) check(LIVE, "/run has an archived run to render");
    // responsive-layout: "wide displays use the width they are given" — the
    // container must be WIDER at 1920 than at 1440, and the same width on every
    // page at a given viewport.
    const shellWidths = {};

    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: heightFor(width) });
      await page.goto(PAGE, { waitUntil: "networkidle" });
      await page.waitForSelector("#sec-hero");
      for (const [sel, byW] of Object.entries(LAYOUT)) {
        const v = await read(page, sel, ["grid-template-columns"]);
        const n = trackCount(v?.["grid-template-columns"]);
        check(matchCount(n, byW[width]), `${width} ${sel} tracks=${n} expected=${JSON.stringify(byW[width])}`);
      }
      // phone-only component checks
      if (width <= 390) {
        const head = await read(page, ".runs-head", ["display"]);
        const row = await read(page, ".runs-row", ["display"]);
        check(!head || head.display === "none", `${width} .runs-head display=${head?.display} (expect none/absent)`);
        check(!row || row.display !== "grid", `${width} .runs-row display=${row?.display} (expect not grid)`);
      }
      await assertNoOverflow(page, width, "cockpit");
      shellWidths[width] = { cockpit: await shellWidth(page) };

      // /progress at the same widths (progress-views 8.1)
      await page.goto(PROGRESS, { waitUntil: "networkidle" });
      await page.waitForSelector("#sec-charts");
      for (const [sel, byW] of Object.entries(PROGRESS_LAYOUT)) {
        const v = await read(page, sel, ["grid-template-columns"]);
        const n = trackCount(v?.["grid-template-columns"]);
        check(matchCount(n, byW[width]), `${width} /progress ${sel} tracks=${n} expected=${JSON.stringify(byW[width])}`);
      }
      for (const sel of PROGRESS_REQUIRED) {
        check((await page.$(sel)) !== null, `${width} /progress ${sel} present`);
      }
      await assertNoOverflow(page, width, "/progress");
      // the block's week rows must contain themselves EXPANDED too — the
      // collapsed row was never the whole claim
      const weekBtn = await page.$("#block-section button.block-week");
      if (weekBtn) {
        await weekBtn.click();
        await page.waitForFunction(() => document.querySelector("#block-section .block-day") !== null,
          null, { timeout: 5000 }).catch(() => {});
        await assertNoOverflow(page, width, "/progress (block week expanded)");
        await weekBtn.click().catch(() => {});
      } else {
        check(LIVE, `${width} /progress renders a training block`);
      }
      shellWidths[width].progress = await shellWidth(page);

      const deepViews = [
        ["/archive", ARCHIVE, () => document.querySelector(".arch-row") || /Archive offline|No archived activity/.test(document.body.innerText)],
        ["/compare", compareIds ? `${COMPARE}?ids=${compareIds.join(",")}` : COMPARE,
          () => document.querySelector("svg[data-chart='trend']") || /Archive offline|Nothing to compare/.test(document.body.innerText)],
        ["/course", COURSE, () => document.querySelector(".crs-tbl, .card") || /no course/i.test(document.body.innerText)],
        ...(runId ? [[`/run`, `http://localhost:${PORT}/run/${runId}`,
          () => document.querySelector(".rep-table, .card") || /Archive offline|not available/i.test(document.body.innerText)]] : []),
      ];
      for (const [pgName, url, settled] of deepViews) {
        await page.goto(url, { waitUntil: "domcontentloaded" });
        await page.waitForSelector("header.topbar", { timeout: 15000 });
        await page.waitForFunction(settled, null, { timeout: 15000 }).catch(() => {});
        await assertNoOverflow(page, width, pgName);
        shellWidths[width][pgName] = await shellWidth(page);
      }
    }

    // wide tier: the container grows with the display, and every page agrees
    for (const width of WIDTHS) {
      const got = shellWidths[width];
      const vals = Object.entries(got).filter(([, w]) => w != null);
      if (vals.length < 2) { check(false, `${width} .page-shell measured on at least two pages`); continue; }
      const [, first] = vals[0];
      check(vals.every(([, w]) => Math.abs(w - first) <= 1),
        `${width} .page-shell identical across pages (${vals.map(([p, w]) => p + "=" + w).join(", ")})`);
    }
    const wide = shellWidths[1920]?.cockpit, desk = shellWidths[1200]?.cockpit;
    check(wide != null && desk != null && wide > desk,
      `.page-shell wider at 1920 than at 1200 (${desk} → ${wide})`);

    // topbar computed-style parity across every page carrying the shared bar
    // (markup is duplicated per page — the computed styles must not drift)
    await page.setViewportSize({ width: 1200, height: 1600 });
    await page.goto(PAGE, { waitUntil: "networkidle" });
    await page.waitForSelector("header.topbar");
    const cockpitBar = {};
    for (const [sel, props] of Object.entries(TOPBAR_PARITY)) cockpitBar[sel] = await read(page, sel, props);
    for (const [pgName, url] of [["progress", PROGRESS], ["archive", ARCHIVE], ["compare", COMPARE], ["course", COURSE]]) {
      await page.goto(url, { waitUntil: "domcontentloaded" });
      await page.waitForSelector("header.topbar", { timeout: 15000 });
      for (const [sel, props] of Object.entries(TOPBAR_PARITY)) {
        const here = await read(page, sel, props);
        // A selector missing on BOTH pages used to compare undefined to
        // undefined and pass — which is exactly what renaming header.topbar
        // during this work would look like. Presence is now the first claim.
        if (!check(cockpitBar[sel] != null && here != null,
          `topbar parity ${sel} present on cockpit and ${pgName}`)) continue;
        for (const p of props) {
          const a = cockpitBar[sel][p], b = here[p];
          check(a === b, `topbar parity ${sel} { ${p}: cockpit=${a} ${pgName}=${b} }`);
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
      check(trends.length > 0, `${pgName}: trend charts found (${trends.length})`);
      for (const c of trends) {
        const axisOk = c.yticks >= 2 && c.xticks >= 1;
        const legendOk = c.series >= 2 ? c.legend >= 2 : c.legend === 0;
        const gapOk = c.declaredPaths === c.domPaths;
        check(axisOk && legendOk && gapOk,
          `chart ${pgName} "${c.label}" yticks=${c.yticks} xticks=${c.xticks} series=${c.series} legend=${c.legend} paths=${c.domPaths}/${c.declaredPaths}`);
      }
    }
    // /compare chart grammar (archive-browser 6.1): the comparison renders a
    // TRACK STACK — x tick labels live on the LAST track only (multiTrackSpec),
    // so the standalone-chart rule above doesn't apply verbatim. Every track
    // still owes y ticks, a legend exactly when it overlays >= 2 runs, and an
    // honest data-line-paths stamp.
    if (!compareIds) {
      console.log("     /compare charts skipped (no reachable archive with two streamed runs)");
    } else {
      await page.setViewportSize({ width: 1200, height: 1600 });
      await page.goto(`${COMPARE}?ids=${compareIds.join(",")}`, { waitUntil: "domcontentloaded" });
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
      check(tracks.length > 0, "/compare: tracks found");
      let sawXTicks = false;
      for (const c of tracks) {
        if (c.xticks > 0) sawXTicks = true;
        const yOk = c.yticks >= 2;
        const legendOk = c.series >= 2 ? c.legend >= 2 : c.legend === 0;
        const gapOk = c.declaredPaths === c.domPaths;
        check(yOk && legendOk && gapOk,
          `chart /compare "${c.label}" yticks=${c.yticks} series=${c.series} legend=${c.legend} paths=${c.domPaths}/${c.declaredPaths}`);
      }
      if (tracks.length) check(sawXTicks, "/compare shared x axis labelled on the stack's last track");
    }

    // chart-drill 6.1: the contribution panel is a registered interactive
    // surface — a keyboard drill on the first insight chart must open a panel
    // that spans the chart grid (desktop) or the viewport (phone sheet), and
    // never overflows the page.
    for (const width of [1200, 390]) {
      await page.setViewportSize({ width, height: heightFor(width) });
      await page.goto(PROGRESS, { waitUntil: "domcontentloaded" });
      await page.waitForSelector("#sec-charts", { timeout: 15000 });
      const eff = await page.waitForSelector('svg[aria-label^="Pace at reference HR"]', { timeout: 15000 }).catch(() => null);
      if (!check(eff != null, `${width} /progress has an insight chart to drill`)) continue;
      await eff.focus();
      await page.keyboard.press("ArrowRight");
      await page.keyboard.press("Enter");
      const settled = await page.waitForFunction(() => {
        const p = document.querySelector("#drill-panel");
        return p && (p.querySelectorAll("a.drill-run").length > 0
          || p.innerText.includes("Archive offline")
          || p.innerText.includes("No run put time"));
      }, null, { timeout: 15000 }).catch(() => null);
      if (!check(settled != null, `${width} /progress drill panel opened on keyboard drill`)) continue;
      const m = await page.evaluate(() => {
        const p = document.querySelector("#drill-panel");
        const g = document.querySelector("#sec-charts");
        return {
          panelW: p.getBoundingClientRect().width,
          gridW: g ? g.getBoundingClientRect().width : 0,
          top: p.getBoundingClientRect().top,
          scrollW: document.documentElement.scrollWidth,
          focusInPanel: p.contains(document.activeElement),
        };
      });
      // the sheet form spans the viewport, the desktop form spans the grid
      const spanOk = m.panelW >= Math.min(m.gridW, width) * 0.9;
      check(spanOk && m.scrollW <= width + 1 && m.focusInPanel,
        `${width} /progress drill panel spans its frame (${Math.round(m.panelW)}/${Math.round(m.gridW)}px), focus inside=${m.focusInPanel}, no overflow (scrollWidth=${m.scrollW})`);
      // chart-drill: "the evidence view opens where it can be read"
      check(m.top >= -1 && m.top < heightFor(width), `${width} /progress drill panel heading is in the viewport (top=${Math.round(m.top)})`);
    }
    console.log(code ? "LAYOUT: FAIL" : "LAYOUT: ALL PASS");
  } else {
    console.log(`unknown mode: ${mode}`);
    code = 2;
  }
} finally {
  await browser.close();
  if (fixtureDir) await rm(fixtureDir, { recursive: true, force: true }).catch(() => {});
}

process.exit(code);
