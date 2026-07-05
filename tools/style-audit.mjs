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
  }

  // topbar computed-style parity between the two pages (desktop)
  await page.setViewportSize({ width: 1200, height: 1600 });
  await page.goto(PAGE, { waitUntil: "networkidle" });
  await page.waitForSelector("header.topbar");
  const cockpitBar = {};
  for (const [sel, props] of Object.entries(TOPBAR_PARITY)) cockpitBar[sel] = await read(page, sel, props);
  await page.goto(PROGRESS, { waitUntil: "networkidle" });
  await page.waitForSelector("header.topbar");
  for (const [sel, props] of Object.entries(TOPBAR_PARITY)) {
    const here = await read(page, sel, props);
    for (const p of props) {
      const a = cockpitBar[sel]?.[p], b = here?.[p];
      const ok = a === b;
      if (!ok) code = 1;
      console.log(`${ok ? "ok " : "FAIL"} topbar parity ${sel} { ${p}: cockpit=${a} progress=${b} }`);
    }
  }
  console.log(code ? "LAYOUT: FAIL" : "LAYOUT: ALL PASS");
}

await browser.close();
process.exit(code);
