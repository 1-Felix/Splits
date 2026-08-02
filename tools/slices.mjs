// tools/slices.mjs — visual slices of every page at every tier.
//
//   node tools/slices.mjs [outDir]
//
// Boots the dev server over the committed layout fixture (so the captures are
// reproducible and carry no personal telemetry) and writes one full-page PNG
// per page per width. Pass --live to capture the repo's own data instead.
//
// This is a review aid, not a gate: tools/style-audit.mjs asserts the layout
// map and test_mobile_pages.mjs asserts the phone contract. Slices are for the
// judgements neither of those can make.

import { chromium } from "playwright";
import { mkdir, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { writeLayoutFixture } from "../fixtures/layout/fixture.mjs";

const LIVE = process.argv.includes("--live");
const outDir = resolve(process.argv.slice(2).find((a) => !a.startsWith("--"))
  || join(tmpdir(), "splits-slices"));

process.env.PORT = process.env.SLICE_PORT || "8124";
const PORT = process.env.PORT;

let fixtureDir = null;
if (!LIVE) {
  fixtureDir = await mkdtemp(join(tmpdir(), "splits-slice-fixture-"));
  await writeLayoutFixture(fixtureDir);
  process.env.SPLITS_DATA_DIR = fixtureDir;
  process.env.SPLITS_ARCHIVE_DIR = fixtureDir;
}
process.env.SYNC_ON_BOOT = "off";
process.env.SYNC_AT = "off";

await import("../serve.mjs");

const B = `http://localhost:${PORT}`;
const WIDTHS = [360, 390, 768, 1440, 1920];
const PAGES = [
  ["cockpit", "/", "#sec-hero"],
  ["progress", "/progress", "#sec-charts"],
  ["archive", "/archive", ".arch-row, .card"],
  ["compare", "/compare?ids=9101,9102,9103", ".card"],
  ["course", "/course", ".card"],
  ["run", "/run/9101", ".card"],
];

await mkdir(outDir, { recursive: true });
const browser = await chromium.launch();
for (const width of WIDTHS) {
  const ctx = await browser.newContext({ viewport: { width, height: width <= 700 ? 844 : 1000 } });
  const page = await ctx.newPage();
  for (const [name, path, ready] of PAGES) {
    await page.goto(B + path, { waitUntil: "domcontentloaded" });
    await page.waitForSelector("header.topbar", { timeout: 20000 }).catch(() => {});
    await page.waitForSelector(ready, { timeout: 20000 }).catch(() => {});
    await page.waitForTimeout(500);   // charts finish mounting
    const file = join(outDir, `${name}-${width}.png`);
    await page.screenshot({ path: file, fullPage: true });
    const m = await page.evaluate((w) => ({
      scrollW: document.documentElement.scrollWidth,
      screens: +(document.documentElement.scrollHeight / window.innerHeight).toFixed(1),
      over: document.documentElement.scrollWidth > w + 1,
    }), width);
    console.log(`${name.padEnd(9)} ${String(width).padStart(4)}  ${m.screens} screens  ` +
                `${m.over ? "OVERFLOW " + m.scrollW : "fits"}  → ${file}`);
  }
  await ctx.close();
}
await browser.close();
if (fixtureDir) await rm(fixtureDir, { recursive: true, force: true }).catch(() => {});
console.log("\nslices written to", outDir);
process.exit(0);
