// test_mobile_pages.mjs — the phone contract, asserted (make-mobile-native).
//
// Before this file, nothing in the suite loaded a page below 900px. The
// responsive gate (tools/style-audit.mjs) measures the LAYOUT map; this
// measures what a thumb and an eye meet:
//
//   • every route renders at 360 and 390 with no document overflow, no page
//     error, and its key content present;
//   • the persistent chrome is there and behaves — a bottom tab bar mirroring
//     the page's own nav, a header that stays pinned through a long scroll;
//   • the swipe guard refuses on every element that owns the horizontal axis
//     and arms only on plain content;
//   • the touch-target floor (44px) and the type floor (11px) hold.
//
// The two floors were authored BEFORE the moves that satisfy them, in the
// pending block below, because an assertion weakened until it passes today
// catches nothing. They are enforcing now.
import assert from "node:assert";
import { spawn } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { writeLayoutFixture } from "./fixtures/layout/fixture.mjs";

const ROOT = dirname(fileURLToPath(import.meta.url));
const PORT = 8145;
const B = "http://localhost:" + PORT;

// The floors are the specification of done. Flipped to enforcing in Move 6
// (task 8.4), after the token tier and the re-compositions landed.
const FLOORS_ENFORCED = true;

const WIDTHS = [360, 390];
const PHONE = { width: 390, height: 844 };

function startServer(dataDir) {
  const child = spawn(process.execPath, ["serve.mjs"], {
    cwd: ROOT,
    env: { ...process.env, PORT: String(PORT), SYNC_ON_BOOT: "off", SYNC_AT: "off",
           SPLITS_DATA_DIR: dataDir, SPLITS_ARCHIVE_DIR: dataDir },
    stdio: ["ignore", "ignore", "pipe"],
  });
  let err = "";
  child.stderr.on("data", (d) => (err += d));
  child.errRef = () => err;
  return child;
}
async function waitReady(errRef) {
  for (let i = 0; i < 80; i++) {
    try { const r = await fetch(B + "/api/status"); if (r.ok) return; } catch { /* booting */ }
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error("server not ready\n" + (errRef ? errRef() : ""));
}

const dataDir = await mkdtemp(join(tmpdir(), "splits-mobile-"));
await writeLayoutFixture(dataDir);
const server = startServer(dataDir);

// the newest fixture run carries the rep document — the run page's widest card
const RUN_ID = 9101;
const ROUTES = [
  ["cockpit", "/", "#sec-hero"],
  ["progress", "/progress", "#sec-charts"],
  ["archive", "/archive", ".arch-row, .card"],
  ["compare", "/compare", ".card"],
  ["course", "/course", ".card"],
  ["run", "/run/" + RUN_ID, ".card"],
];

let browser;
let failed = false;
let step = "boot";
try {
  await waitReady(server.errRef);
  browser = await chromium.launch();

  // ── every route, at both phone widths ─────────────────────────────────────
  for (const width of WIDTHS) {
    const ctx = await browser.newContext({ viewport: { width, height: 844 } });
    const page = await ctx.newPage();
    const pageErrors = [];
    page.on("pageerror", (e) => pageErrors.push(String(e)));

    for (const [name, path, key] of ROUTES) {
      step = `${name} @ ${width}`;
      await page.goto(B + path, { waitUntil: "domcontentloaded" });
      await page.waitForSelector("header.topbar", { timeout: 20000 });
      await page.waitForSelector(key, { timeout: 20000 });

      const sw = await page.evaluate(() => document.documentElement.scrollWidth);
      assert.ok(sw <= width + 1, `${name} @ ${width}: document must not scroll horizontally (scrollWidth=${sw})`);

      // the page names itself (mobile-chrome: "every page identifies itself")
      const id = await page.evaluate(() => ({
        title: document.title,
        h1: [...document.querySelectorAll("h1")].map((h) => h.innerText.trim()),
      }));
      assert.ok(id.title && id.title.length > 3, `${name}: document.title names the page; got ${JSON.stringify(id.title)}`);
      assert.strictEqual(id.h1.length, 1, `${name}: exactly one <h1>; got ${JSON.stringify(id.h1)}`);

      // The chrome mirrors the page's own nav, and marks the current page. The
      // page's nav is itself late-bound (the archive probe and the course lens
      // both resolve after first paint), so the contract is that the bar
      // CONVERGES on it — asserted by waiting for agreement, then reading.
      await page.waitForFunction(() => {
        const nav = document.querySelector("nav.tabbar");
        const own = [...document.querySelectorAll('#dc-root header.topbar nav[aria-label="Pages"] a')];
        if (!nav || !own.length) return false;
        const mine = [...nav.querySelectorAll("a")].map((a) => a.textContent.trim()).join("|");
        return mine === own.map((a) => a.textContent.trim()).join("|");
      }, null, { timeout: 10000 });

      const bar = await page.evaluate(() => {
        const nav = document.querySelector("nav.tabbar");
        if (!nav) return null;
        const own = [...document.querySelectorAll('#dc-root header.topbar nav[aria-label="Pages"] a')];
        return {
          display: getComputedStyle(nav).display,
          position: getComputedStyle(nav).position,
          tabs: [...nav.querySelectorAll("a")].map((a) => ({
            label: a.innerText.trim(), href: a.getAttribute("href"),
            current: a.getAttribute("aria-current") === "page",
            h: Math.round(a.getBoundingClientRect().height),
            w: Math.round(a.getBoundingClientRect().width),
          })),
          ownCount: own.length,
          ownLabels: own.map((a) => a.textContent.trim()),
        };
      });
      assert.ok(bar, `${name} @ ${width}: a bottom tab bar exists`);
      assert.notStrictEqual(bar.display, "none", `${name}: the tab bar renders below the phone tier`);
      assert.strictEqual(bar.position, "fixed", `${name}: the tab bar is fixed`);
      assert.strictEqual(bar.tabs.length, bar.ownCount,
        `${name}: the bar offers exactly what the page's own nav offers (${bar.tabs.length} vs ${bar.ownCount})`);
      assert.deepStrictEqual(bar.tabs.map((t) => t.label), bar.ownLabels,
        `${name}: the bar's destinations are the page's own, in order`);
      for (const t of bar.tabs) {
        assert.ok(t.h >= 44 && t.w >= 44, `${name}: tab "${t.label}" is ${t.w}×${t.h}, under the 44px floor`);
      }
      // the current page is marked wherever the page's own nav marks one
      const ownCurrent = await page.evaluate(() =>
        [...document.querySelectorAll('#dc-root header.topbar nav[aria-label="Pages"] a')]
          .filter((a) => a.getAttribute("aria-current") === "page").length);
      assert.strictEqual(bar.tabs.filter((t) => t.current).length, ownCurrent,
        `${name}: aria-current is mirrored, not invented`);

      // no <svg> was introduced by the icons — test_course_page asserts on that
      const svgInBar = await page.evaluate(() => document.querySelectorAll("nav.tabbar svg").length);
      assert.strictEqual(svgInBar, 0, `${name}: tab icons are masks, not <svg> elements`);
    }
    assert.deepStrictEqual(pageErrors, [], `page errors at ${width}: ${JSON.stringify(pageErrors)}`);
    await ctx.close();
  }

  // ── the header is a slim, pinned bar (mobile-chrome 3.9) ──────────────────
  {
    const ctx = await browser.newContext({ viewport: PHONE });
    const page = await ctx.newPage();
    const pageErrors = [];
    page.on("pageerror", (e) => pageErrors.push(String(e)));
    for (const [name, path, key] of ROUTES) {
      step = `header @ ${name}`;
      await page.goto(B + path, { waitUntil: "domcontentloaded" });
      await page.waitForSelector("header.topbar", { timeout: 20000 });
      await page.waitForSelector(key, { timeout: 20000 });
      const m = await page.evaluate(() => {
        const h = document.querySelector("header.topbar");
        const r = h.getBoundingClientRect();
        const shell = document.querySelector(".page-shell");
        const first = [...shell.children].find((el) => el !== h && el.getBoundingClientRect().height > 0);
        return { h: Math.round(r.height), top: Math.round(r.top),
                 position: getComputedStyle(h).position,
                 firstTop: first ? Math.round(first.getBoundingClientRect().top) : null };
      });
      assert.strictEqual(m.position, "sticky", `${name}: the header is sticky on a phone`);
      assert.ok(m.h <= 62, `${name}: the header is ${m.h}px, over the 62px budget`);
      assert.ok(m.firstTop == null || m.firstTop <= 120,
        `${name}: first content starts at ${m.firstTop}px, too far down`);
      // Below the phone tier the DOCUMENT is frozen and .app-root is the
      // scroller — that is what keeps the fixed chrome from riding a real
      // phone browser's collapsing toolbar. The scroll goes to the scroller,
      // and the document refusing to move is itself part of the contract.
      await page.evaluate(() => {
        window.scrollTo(0, 300);
        window.SplitsTopbar.pageScroller(document).scrollTo(0, 1200);
      });
      await page.waitForTimeout(120);
      const after = await page.evaluate(() => {
        const h = document.querySelector("header.topbar");
        const bar = document.querySelector("nav.tabbar");
        return { headerTop: Math.round(h.getBoundingClientRect().top),
                 y: Math.round(window.SplitsTopbar.pageScroller(document).scrollTop),
                 docY: Math.round(window.scrollY),
                 barBottom: bar ? Math.round(bar.getBoundingClientRect().bottom) : null,
                 vh: window.innerHeight };
      });
      assert.strictEqual(after.docY, 0,
        `${name}: the document itself does not scroll on a phone (scrollY=${after.docY})`);
      if (after.y > 400) {   // only meaningful where the content is long enough
        assert.ok(Math.abs(after.headerTop) <= 1,
          `${name}: the header is still pinned after scrolling to ${after.y} (top=${after.headerTop})`);
        assert.ok(after.barBottom != null && Math.abs(after.barBottom - after.vh) <= 1,
          `${name}: the tab bar is still on the viewport floor (bottom=${after.barBottom}, vh=${after.vh})`);
      }
    }
    assert.deepStrictEqual(pageErrors, [], "no page errors while scrolling: " + JSON.stringify(pageErrors));
    await ctx.close();
  }

  // ── the swipe guard yields to anything that owns the horizontal axis ──────
  // (mobile-chrome: "a page swipe never competes with a local gesture")
  {
    const ctx = await browser.newContext({ viewport: PHONE, hasTouch: true });
    const page = await ctx.newPage();
    step = "swipe guard";
    const refuse = (sel) => page.evaluate((s) => {
      const el = document.querySelector(s);
      if (!el) return "MISSING";
      return window.SplitsTopbar.swipeRefused(el);
    }, sel);

    await page.goto(B + "/progress", { waitUntil: "domcontentloaded" });
    await page.waitForSelector("#sec-charts", { timeout: 20000 });
    await page.waitForSelector("svg.chart-svg", { timeout: 20000 });
    for (const sel of ["svg.chart-svg", "svg.chart-svg rect", ".block-week", ".card"]) {
      const r = await refuse(sel);
      assert.notStrictEqual(r, "MISSING", `swipe guard: ${sel} exists on /progress`);
    }
    assert.strictEqual(await refuse("svg.chart-svg"), true, "a chart refuses the page swipe");
    assert.strictEqual(await refuse("svg.chart-svg rect"), true, "a chart's hit band refuses the page swipe");
    // plain card content arms it
    assert.strictEqual(await page.evaluate(() => {
      const t = [...document.querySelectorAll(".card .card-title")][0];
      return window.SplitsTopbar.swipeRefused(t);
    }), false, "plain card content arms the page swipe");

    await page.goto(B + "/", { waitUntil: "domcontentloaded" });
    await page.waitForSelector("#sec-hero", { timeout: 20000 });
    // the readiness ring and the heatmap's scroller both own their axis
    const ringRefused = await page.evaluate(() => {
      const svg = document.querySelector('#card-ready svg') || document.querySelector("svg");
      return svg ? window.SplitsTopbar.swipeRefused(svg) : "MISSING";
    });
    assert.strictEqual(ringRefused, true, "the readiness ring refuses the page swipe");
    const scrollerRefused = await page.evaluate(() => {
      const el = [...document.querySelectorAll("*")].find((n) => {
        const ox = getComputedStyle(n).overflowX;
        return (ox === "auto" || ox === "scroll") && n.scrollWidth > n.clientWidth + 1;
      });
      return el ? window.SplitsTopbar.swipeRefused(el.firstElementChild || el) : "NONE";
    });
    assert.ok(scrollerRefused === true || scrollerRefused === "NONE",
      "a horizontal scroller refuses the page swipe");

    await page.goto(B + "/archive", { waitUntil: "domcontentloaded" });
    await page.waitForSelector(".arch-search", { timeout: 20000 });
    assert.strictEqual(await refuse(".arch-search"), true, "the search field refuses the page swipe");

    // and the document still never widens, at every asserted width
    for (const width of [360, 390, 768, 1200]) {
      await page.setViewportSize({ width, height: 844 });
      for (const [name, path, key] of ROUTES) {
        await page.goto(B + path, { waitUntil: "domcontentloaded" });
        await page.waitForSelector(key, { timeout: 20000 });
        const sw = await page.evaluate(() => document.documentElement.scrollWidth);
        assert.ok(sw <= width + 1, `${name} @ ${width}: scrollWidth ${sw} exceeds the viewport`);
      }
    }
    await ctx.close();
  }

  // ── charts respond to a finger (chart-engine D6) ─────────────────────────
  // Before this, a tap worked only because the browser synthesises a mouse
  // event afterwards, a drag produced no events at all, and the chart-drill's
  // second activation was provably dead on touch. These drive real
  // PointerEvents with pointerType "touch", which is the path a finger takes.
  {
    const ctx = await browser.newContext({ viewport: PHONE, hasTouch: true });
    const page = await ctx.newPage();
    const pageErrors = [];
    page.on("pageerror", (e) => pageErrors.push(String(e)));

    // dispatch a press / scrub / release across a fraction of an element
    const touch = (sel, from, to) => page.evaluate(([s, f0, f1]) => {
      const el = document.querySelector(s);
      if (!el) return false;
      const r = el.getBoundingClientRect();
      const at = (f) => ({
        bubbles: true, cancelable: true, pointerType: "touch", pointerId: 1,
        isPrimary: true, clientX: r.left + r.width * f, clientY: r.top + r.height / 2,
      });
      el.dispatchEvent(new PointerEvent("pointerdown", { ...at(f0), buttons: 1, pressure: 0.5 }));
      if (f1 != null) el.dispatchEvent(new PointerEvent("pointermove", { ...at(f1), buttons: 1, pressure: 0.5 }));
      el.dispatchEvent(new PointerEvent("pointerup", { ...at(f1 == null ? f0 : f1), buttons: 0, pressure: 0 }));
      return true;
    }, [sel, from, to]);

    // ── a stream stack: press places a reading, drag scrubs it ────────────
    step = "chart touch: run stack";
    await page.goto(B + "/run/" + RUN_ID, { waitUntil: "domcontentloaded" });
    await page.waitForSelector("svg[data-chart='trend']", { timeout: 20000 });
    await page.waitForSelector(".chart-readout", { state: "attached", timeout: 20000 });

    const idle = await page.evaluate(() => {
      const ro = document.querySelector(".chart-readout");
      const svg = document.querySelectorAll("svg[data-chart='trend']")[0];
      return { cls: ro.className, visible: ro.getBoundingClientRect().height > 0,
               chartTop: Math.round(svg.getBoundingClientRect().top + window.scrollY) };
    });
    assert.ok(idle.cls.includes("chart-readout--idle"), "the readout is reserved but idle before any reading");
    assert.strictEqual(idle.visible, false, "and takes no phone screen while it has nothing to say");

    assert.ok(await touch("svg[data-chart='trend']", 0.3), "the first track exists to be touched");
    await page.waitForFunction(() => {
      const ro = document.querySelector(".chart-readout");
      return ro && ro.className.includes("--live");
    }, null, { timeout: 5000 });
    const placed = await page.evaluate(() => {
      const ro = document.querySelector(".chart-readout");
      const svg = document.querySelectorAll("svg[data-chart='trend']")[0];
      const bar = ro.getBoundingClientRect();
      return { text: ro.innerText.replace(/\s+/g, " ").trim(),
               chartTop: Math.round(svg.getBoundingClientRect().top + window.scrollY),
               barBottom: Math.round(bar.bottom), vh: window.innerHeight,
               crosshairs: document.querySelectorAll("svg[data-chart='trend'] line[stroke-dasharray='3 3']").length };
    });
    assert.ok(/\d/.test(placed.text), "the reading names values: " + placed.text);
    // chart-engine: "a stack of tracks shows its shared axis" — the x tick
    // labels live on the stack's LAST track, which is off-screen while an
    // upper track is being scrubbed, so the reading states the shared-axis
    // position itself and stays on the viewport floor while it does
    assert.ok(/^at\b/.test(placed.text) && /km|\d+:\d\d/.test(placed.text),
      "the reading states where on the shared axis it is: " + placed.text);
    assert.ok(placed.crosshairs > 0, "a crosshair is drawn where the finger pressed");
    // "placing a reading does not move the chart"
    assert.strictEqual(placed.chartTop, idle.chartTop,
      `the chart stays where it was (${idle.chartTop} → ${placed.chartTop})`);
    // "the reading is visible where it is placed" — a bar on the viewport
    // floor, above the tab bar, not 186px below the end of the stack
    assert.ok(placed.barBottom <= placed.vh + 1 && placed.barBottom > placed.vh - 120,
      `the reading sits on the viewport floor (bottom=${placed.barBottom}, vh=${placed.vh})`);

    // a drag scrubs it continuously
    const first = placed.text;
    await touch("svg[data-chart='trend']", 0.3, 0.75);
    await page.waitForFunction((prev) => {
      const ro = document.querySelector(".chart-readout");
      return ro && ro.innerText.replace(/\s+/g, " ").trim() !== prev;
    }, first, { timeout: 5000 });
    const scrubbed = await page.evaluate(() =>
      document.querySelector(".chart-readout").innerText.replace(/\s+/g, " ").trim());
    assert.notStrictEqual(scrubbed, first, "the reading follows the finger: " + first + " → " + scrubbed);

    // ── a dense band chart: the nearest point is read, not a 9px target ────
    step = "chart touch: dense band chart";
    await page.goto(B + "/progress", { waitUntil: "domcontentloaded" });
    const eff = 'svg[aria-label^="Pace at reference HR"]';
    await page.waitForSelector(eff, { timeout: 20000 });
    const beforeTap = await page.evaluate((s) =>
      Math.round(document.querySelector(s).getBoundingClientRect().top + window.scrollY), eff);
    await touch(eff, 0.42);
    await page.waitForFunction(() => document.querySelector('[data-card]') !== null, null, { timeout: 5000 });
    const afterTap = await page.evaluate((s) => ({
      top: Math.round(document.querySelector(s).getBoundingClientRect().top + window.scrollY),
      card: document.querySelector("[data-card]").innerText.replace(/\s+/g, " ").trim(),
      drill: document.querySelectorAll(".pop-drill").length,
      drillBox: [...document.querySelectorAll(".pop-drill")].map((b) => {
        const r = b.getBoundingClientRect();
        return [Math.round(r.width), Math.round(r.height)];
      }),
    }), eff);
    assert.ok(/\d/.test(afterTap.card), "pressing anywhere reads the nearest point: " + afterTap.card);
    assert.strictEqual(afterTap.top, beforeTap, "and the chart did not move under the finger");

    // ── the drill is reachable by touch (chart-drill) ─────────────────────
    step = "chart touch: drill";
    assert.strictEqual(afterTap.drill, 1, "a pinned reading offers its drill as a control");
    assert.ok(afterTap.drillBox[0][1] >= 44,
      `the drill affordance meets the touch floor (${afterTap.drillBox[0].join("×")})`);
    await page.click(".pop-drill");
    await page.waitForFunction(() => {
      const p = document.querySelector("#drill-panel");
      return p && (p.querySelectorAll("a.drill-run").length > 0 || p.innerText.includes("No run put time"));
    }, null, { timeout: 15000 });
    const panel = await page.evaluate(() => {
      const p = document.querySelector("#drill-panel");
      const r = p.getBoundingClientRect();
      return { top: Math.round(r.top), vh: window.innerHeight, w: Math.round(r.width),
               position: getComputedStyle(p).position,
               scrollW: document.documentElement.scrollWidth };
    });
    assert.strictEqual(panel.position, "fixed", "the evidence view is a bottom sheet on a phone");
    assert.ok(panel.top >= 0 && panel.top < panel.vh,
      `its heading is in the viewport (top=${panel.top}, vh=${panel.vh})`);
    assert.ok(panel.scrollW <= PHONE.width + 1, "and it does not widen the document");

    assert.deepStrictEqual(pageErrors, [], "no page errors on the touch path: " + JSON.stringify(pageErrors));
    await ctx.close();
  }

  // ── every record in the wall is reachable (progress-views) ───────────────
  {
    const ctx = await browser.newContext({ viewport: PHONE });
    const page = await ctx.newPage();
    step = "records wall";
    await page.goto(B + "/progress", { waitUntil: "domcontentloaded" });
    await page.waitForSelector("#sec-records", { timeout: 20000 });
    await page.waitForSelector(".rec-unit", { timeout: 20000 });

    const wall = await page.evaluate(() => {
      const sec = document.querySelector("#sec-records");
      const clipped = [...sec.querySelectorAll("*")].filter((el) => {
        const cs = getComputedStyle(el);
        return (cs.overflowX === "auto" || cs.overflowX === "scroll")
          && el.scrollWidth > el.clientWidth + 1
          && !el.hasAttribute("data-overflow");
      }).length;
      return {
        units: document.querySelectorAll(".rec-unit").length,
        wide: document.querySelectorAll("#sec-records .scroller").length,
        primary: document.querySelectorAll(".rec-unit-primary .rec-cell").length,
        disclosures: document.querySelectorAll(".rec-years-btn").length,
        yearsShown: document.querySelectorAll(".rec-cell--year").length,
        undisclosed: clipped,
      };
    });
    assert.strictEqual(wall.wide, 0, "only the phone composition is in the document");
    assert.ok(wall.units >= 5, `one unit per distance (${wall.units})`);
    assert.strictEqual(wall.primary, wall.units * 2, "all-time and last-90-days lead every unit");
    assert.ok(wall.disclosures >= 1, "the by-year bests are behind a disclosure that says how many");
    assert.strictEqual(wall.yearsShown, 0, "and start closed");
    assert.strictEqual(wall.undisclosed, 0, "nothing is hidden behind a scroller that does not say so");

    // opening a disclosure reveals every year it named
    const label = await page.locator(".rec-years-btn").first().innerText();
    const claimed = Number((label.match(/\d+/) || [0])[0]);
    await page.locator(".rec-years-btn").first().click();
    await page.waitForFunction(() => document.querySelectorAll(".rec-cell--year").length > 0,
      null, { timeout: 5000 });
    const revealed = await page.evaluate(() => document.querySelectorAll(".rec-cell--year").length);
    assert.strictEqual(revealed, claimed, `the disclosure holds what it claimed (${revealed} vs ${claimed})`);

    // and a record still opens the run it was set in
    const target = page.locator('.rec-unit-primary .rec-cell[aria-label*="Open the run"]').first();
    assert.ok(await target.count() > 0, "at least one record knows the run it was set in");
    await target.click();
    await page.waitForFunction(() => /^\/run\/\d+$/.test(window.location.pathname), null, { timeout: 10000 });
    await ctx.close();
  }

  // ── a comparison is one lane per run, with nothing dropped (run-comparison) ─
  {
    const ctx = await browser.newContext({ viewport: PHONE });
    const page = await ctx.newPage();
    step = "compare lanes";
    const CMP = B + "/compare?ids=9101,9102,9103";
    await page.goto(CMP, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(".cmp-lane", { timeout: 20000 });

    const phoneSide = await page.evaluate(() => ({
      lanes: [...document.querySelectorAll(".cmp-lane")].map((l) => ({
        name: l.querySelector(".cmp-lane-name").innerText.trim(),
        cells: [...l.querySelectorAll(".cmp-lane-cell")].map((c) => [
          c.querySelector(".cmp-lane-k").innerText.trim(),
          c.querySelector(".cmp-lane-v").innerText.trim(),
        ]),
        best: l.querySelectorAll('.cmp-lane-cell[data-mark="best"]').length,
      })),
      wide: document.querySelectorAll(".cmp-summary").length,
      scrollW: document.documentElement.scrollWidth,
    }));
    assert.strictEqual(phoneSide.wide, 0, "only ONE composition is in the document at a time");
    assert.strictEqual(phoneSide.lanes.length, 3, "one lane per compared run");
    // "a run's identity is not reduced to a truncation" — every name is whole
    const names = phoneSide.lanes.map((l) => l.name);
    assert.strictEqual(new Set(names).size, names.length, "the runs can be told apart: " + JSON.stringify(names));
    assert.ok(names.every((n) => !n.includes("…")), "no name is truncated: " + JSON.stringify(names));
    assert.ok(phoneSide.lanes.every((l) => l.cells.length >= 6),
      "every measure the wide composition shows is present per lane");
    assert.ok(phoneSide.lanes.some((l) => l.best > 0), "the best-per-measure marking survives");
    assert.ok(phoneSide.scrollW <= PHONE.width + 1, "and the comparison does not widen the document");

    // splits keep enough width to convey a length
    const bar = await page.evaluate(() => {
      const t = document.querySelector(".cmp-split-track");
      return t ? Math.round(t.getBoundingClientRect().width) : null;
    });
    assert.ok(bar != null && bar >= 180, `each per-kilometre bar keeps real width (${bar}px)`);

    // "the comparison offers a way back" — from a shared link, without the
    // browser's back control
    const ways = await page.evaluate(() => ({
      tabs: document.querySelectorAll("nav.tabbar a").length,
      hrefs: [...document.querySelectorAll("nav.tabbar a")].map((a) => new URL(a.href).pathname),
    }));
    assert.ok(ways.tabs >= 2, "navigation to the rest of the app is present: " + JSON.stringify(ways.hrefs));

    // and above the phone tier the WIDE composition is the only one present
    await page.setViewportSize({ width: 1200, height: 1400 });
    await page.waitForFunction(() => document.querySelectorAll(".cmp-summary").length === 1
      && document.querySelectorAll(".cmp-lane").length === 0, null, { timeout: 5000 });
    await ctx.close();
  }

  // ── the run page leads with what the run WAS (run-detail) ────────────────
  {
    const ctx = await browser.newContext({ viewport: PHONE });
    const page = await ctx.newPage();
    step = "run page order";
    await page.goto(B + "/run/" + RUN_ID, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(".rep-table", { timeout: 20000 });
    await page.waitForSelector(".run-card--trace", { timeout: 20000 });

    const order = await page.evaluate(() => {
      const y = (s) => {
        const el = document.querySelector(s);
        return el ? Math.round(el.getBoundingClientRect().top + window.scrollY) : null;
      };
      return { reps: y(".rep-table"), splits: y(".run-card--splits"),
               trace: y(".run-card--trace"), bests: y(".run-card--bests"),
               // the page's full height lives on the phone-tier scroller, not
               // the (frozen, one-viewport) document
               docH: window.SplitsTopbar.pageScroller(document).scrollHeight };
    });
    assert.ok(order.reps != null && order.trace != null,
      "the run carries both a rep table and a route: " + JSON.stringify(order));
    assert.ok(order.reps < order.trace,
      `the detected structure is above the route trace (${order.reps} vs ${order.trace})`);
    if (order.splits != null) assert.ok(order.reps < order.splits, "reps precede the splits table");
    if (order.bests != null) assert.ok(order.trace < order.bests, "best efforts come last");
    // it sat 5th at 74% of the document before this change; the cards above it
    // now are the ones that answer the run first — the headline, planned vs
    // actual, and the sample stack
    const depth = order.reps / order.docH;
    assert.ok(depth < 0.5,
      `the rep card is in the first half of the document, not 74% down (${(depth * 100).toFixed(0)}%)`);
    console.log(`run page at 390px: rep card at ${(depth * 100).toFixed(0)}% depth (was 74%)`);

    // the deviation bar survives phone width — it measured 6.0px at 360
    for (const width of [360, 390]) {
      await page.setViewportSize({ width, height: 844 });
      await page.waitForTimeout(300);
      const bar = await page.evaluate(() => {
        const b = document.querySelector(".rep-table .rep-row .rep-bar");
        return b ? Math.round(b.getBoundingClientRect().width) : null;
      });
      assert.ok(bar != null && bar >= 180,
        `the deviation bar has room to mean something at ${width}px (track=${bar}px)`);
    }
    await ctx.close();
  }

  // ── the cockpit's content contract (live-dashboard) ──────────────────────
  {
    const ctx = await browser.newContext({ viewport: PHONE });
    const page = await ctx.newPage();
    step = "cockpit content";
    await page.goto(B + "/", { waitUntil: "domcontentloaded" });
    await page.waitForSelector("#sec-hero", { timeout: 20000 });
    await page.waitForSelector("#card-ready", { timeout: 20000 });

    // the readiness card displays its score — it never had, at any width: the
    // runtime wraps interpolations in a <span>, and a <span> inside <svg> is
    // not an SVG element, so both <text> nodes measured 0×0
    const ring = await page.evaluate(() => {
      const s = document.querySelector(".ring-score"), t = document.querySelector(".ring-status");
      const box = (el) => (el ? el.getBoundingClientRect() : null);
      const rs = box(s), ts = box(t);
      return { score: s && s.innerText.trim(), status: t && t.innerText.trim(),
               scoreBox: rs && [Math.round(rs.width), Math.round(rs.height)],
               statusBox: ts && [Math.round(ts.width), Math.round(ts.height)] };
    });
    assert.ok(ring.score && /\d/.test(ring.score), "the readiness score renders as text: " + JSON.stringify(ring));
    assert.ok(ring.status && ring.status.length > 1, "the readiness status renders as text: " + JSON.stringify(ring));
    assert.ok(ring.scoreBox[0] > 0 && ring.scoreBox[1] > 0, "the score has a non-zero box: " + JSON.stringify(ring.scoreBox));
    assert.ok(ring.statusBox[0] > 0 && ring.statusBox[1] > 0, "the status has a non-zero box: " + JSON.stringify(ring.statusBox));

    // coach prose is paragraphs, not one text node
    const paras = await page.evaluate(() => document.querySelectorAll("#card-coach .coach-p").length);
    assert.ok(paras >= 2, `the coach note renders as paragraphs (got ${paras})`);

    // and both long-form blocks are one activation from complete
    const noteBtn = await page.$("#card-coach .more-btn");
    assert.ok(noteBtn, "the coach note offers its full text");
    await noteBtn.click();
    await page.waitForSelector(".sheet-backdrop .sheet", { timeout: 5000 });
    const sheet = await page.evaluate(() => {
      const s = document.querySelector(".sheet");
      const full = [...document.querySelectorAll(".sheet-body .sheet-p")].map((p) => p.textContent).join(" ");
      const clamped = [...document.querySelectorAll("#card-coach .coach-p")].map((p) => p.textContent).join(" ");
      return { title: s.querySelector(".sheet-title").innerText.trim(),
               modal: s.getAttribute("aria-modal"),
               focusInside: s.contains(document.activeElement),
               fullLen: full.length, clampedLen: clamped.length,
               scrollW: document.documentElement.scrollWidth };
    });
    assert.strictEqual(sheet.modal, "true", "the sheet is a modal dialog");
    assert.ok(sheet.focusInside, "focus moves into the sheet");
    assert.ok(sheet.fullLen >= sheet.clampedLen, "the sheet carries the whole note, nothing removed");
    assert.ok(sheet.scrollW <= PHONE.width + 1, "the sheet does not widen the document");
    // Escape closes it and gives focus back
    await page.keyboard.press("Escape");
    await page.waitForFunction(() => !document.querySelector(".sheet-backdrop"), null, { timeout: 5000 });

    // the coach log shows its newest entries and offers the rest complete
    const logState = await page.evaluate(() => {
      const items = [...document.querySelectorAll("#card-planlog .timeline-item")];
      const shown = items.filter((el) => el.getBoundingClientRect().height > 0);
      const btn = document.querySelector("#card-planlog .more-btn");
      return { total: items.length, shown: shown.length, label: btn && btn.innerText.trim() };
    });
    assert.ok(logState.total > 2, "the fixture's log is deep enough to exercise the collapse");
    assert.ok(logState.shown <= 2, `the log shows its newest entries only (${logState.shown} of ${logState.total})`);
    assert.ok(logState.label && logState.label.includes(String(logState.total)),
      "the control states how much is behind it: " + JSON.stringify(logState.label));
    await page.click("#card-planlog .more-btn");
    await page.waitForSelector(".sheet-backdrop .sheet", { timeout: 5000 });
    const inSheet = await page.evaluate(() => document.querySelectorAll(".sheet-body .sheet-log").length);
    assert.strictEqual(inSheet, logState.total, "the sheet carries every adjustment");
    await page.keyboard.press("Escape");
    await page.waitForFunction(() => !document.querySelector(".sheet-backdrop"), null, { timeout: 5000 });

    // "today is answered first": the countdown, readiness WITH ITS SCORE, and
    // the coach's current instruction are all on the first screen
    const first = await page.evaluate(() => {
      const y = (s) => {
        const el = document.querySelector(s);
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return r.height > 0 ? Math.round(r.bottom) : null;
      };
      return { countdown: y("#card-hero"), score: y(".ring-score"),
               coach: y(".coach-headline"), vh: window.innerHeight };
    });
    for (const [what, bottom] of Object.entries(first)) {
      if (what === "vh" || bottom == null) continue;
      assert.ok(bottom <= first.vh,
        `${what} is on the first screen (bottom=${bottom}, viewport=${first.vh})`);
    }

    // a planned day's detail opens in the sheet, not as an accordion whose
    // own first line can land below the fold
    const dayCard = page.locator("#sec-week1 .day--wk").first();
    if (await dayCard.count()) {
      const beforeH = await page.evaluate(() => document.documentElement.scrollHeight);
      await dayCard.click();
      await page.waitForSelector(".sheet-backdrop .sheet", { timeout: 5000 });
      const day = await page.evaluate(() => ({
        title: document.querySelector(".sheet-title").innerText.trim(),
        body: document.querySelector(".sheet-body").innerText.trim().length,
        top: Math.round(document.querySelector(".sheet").getBoundingClientRect().top),
        vh: window.innerHeight,
        docH: document.documentElement.scrollHeight,
      }));
      assert.ok(day.body > 0, "the day's detail is in the sheet: " + day.title);
      assert.ok(day.top < day.vh, "and the sheet's head is in the viewport");
      assert.strictEqual(day.docH, beforeH, "the week below it did not move");
      await page.keyboard.press("Escape");
      await page.waitForFunction(() => !document.querySelector(".sheet-backdrop"), null, { timeout: 5000 });
    }

    // the block's weeks stay comparable — a rail, not seven screens
    const rail = await page.evaluate(() => {
      const el = document.getElementById("sec-week2");
      const box = el.getBoundingClientRect();
      const cards = [...el.children].filter((c) => c.getBoundingClientRect().width > 0);
      return { h: Math.round(box.height), cards: cards.length,
               inView: cards.filter((c) => {
                 const r = c.getBoundingClientRect();
                 return r.left < box.right - 1 && r.right > box.left + 1;
               }).length,
               scrolls: getComputedStyle(el).overflowX };
    });
    assert.ok(rail.inView >= 2, `more than one block week is visible (${rail.inView} of ${rail.cards})`);
    assert.ok(rail.h < 400, `the block occupies a strip, not a stack (${rail.h}px for ${rail.cards} weeks)`);

    // the whole cockpit fits in a handful of screens, with nothing deleted
    const screens = await page.evaluate(() =>
      document.documentElement.scrollHeight / window.innerHeight);
    assert.ok(screens < 6, `the cockpit is ${screens.toFixed(1)} viewport heights at 390px (budget: under 6)`);
    console.log(`cockpit at 390px: ${screens.toFixed(1)} viewport heights`);
    await ctx.close();
  }

  // ── the floors (responsive-layout) ────────────────────────────────────────
  {
    const ctx = await browser.newContext({ viewport: PHONE });
    const page = await ctx.newPage();
    const problems = [];
    for (const [name, path, key] of ROUTES) {
      step = `floors @ ${name}`;
      await page.goto(B + path, { waitUntil: "domcontentloaded" });
      await page.waitForSelector("header.topbar", { timeout: 20000 });
      await page.waitForSelector(key, { timeout: 20000 });
      await page.waitForTimeout(300);   // let the charts finish mounting

      const found = await page.evaluate(() => {
        const out = { small: [], tiny: [], inputs: [] };
        const label = (el) => el.tagName.toLowerCase()
          + (el.id ? "#" + el.id : "")
          + (typeof el.className === "string" && el.className ? "." + el.className.trim().split(/\s+/).slice(0, 2).join(".") : "")
          + ' "' + (el.innerText || el.textContent || "").trim().slice(0, 24) + '"';
        const visible = (el) => {
          const cs = getComputedStyle(el);
          if (cs.display === "none" || cs.visibility === "hidden" || cs.opacity === "0") return false;
          const r = el.getBoundingClientRect();
          return r.width > 0 && r.height > 0;
        };
        // touch targets: anchors, buttons and anything with role=button
        for (const el of document.querySelectorAll('a[href],button,input,select,[role="button"]')) {
          if (!visible(el)) continue;
          if (el.closest("nav.tabbar") === null && el.getAttribute("aria-hidden") === "true") continue;
          const r = el.getBoundingClientRect();
          // a control inside a bigger activation area counts as that area
          const host = el.closest('[data-target-host]');
          const hr = host ? host.getBoundingClientRect() : r;
          if (Math.min(hr.width, hr.height) < 44 && Math.min(r.width, r.height) < 44) {
            out.small.push(label(el) + " " + Math.round(r.width) + "×" + Math.round(r.height));
          }
          if (el.matches('input:not([type="checkbox"]):not([type="radio"]),select,textarea')) {
            const fs = parseFloat(getComputedStyle(el).fontSize);
            if (fs < 16) out.inputs.push(label(el) + " " + fs + "px");
          }
        }
        // type floor: every element that renders its own text
        const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        const seen = new Set();
        for (let n = walk.nextNode(); n; n = walk.nextNode()) {
          if (!n.nodeValue || !n.nodeValue.trim()) continue;
          const el = n.parentElement;
          if (!el || seen.has(el) || !visible(el)) continue;
          seen.add(el);
          const fs = parseFloat(getComputedStyle(el).fontSize);
          if (fs < 11) out.tiny.push(label(el) + " " + fs + "px");
        }
        return out;
      });
      if (found.small.length) problems.push(`${name}: sub-44px targets → ` + found.small.slice(0, 8).join("; "));
      if (found.tiny.length) problems.push(`${name}: sub-11px text → ` + found.tiny.slice(0, 8).join("; "));
      if (found.inputs.length) problems.push(`${name}: sub-16px entry fields → ` + found.inputs.join("; "));
    }
    await ctx.close();
    if (FLOORS_ENFORCED) {
      assert.deepStrictEqual(problems, [], "the phone floors hold:\n  " + problems.join("\n  "));
    } else if (problems.length) {
      console.log("PENDING (floors not yet enforced):\n  " + problems.join("\n  "));
    }
  }

  console.log("ALL PASS");
} catch (e) {
  failed = true;
  console.error("FAIL at step '" + step + "':", e.message);
} finally {
  if (browser) await browser.close().catch(() => {});
  server.kill();
  await rm(dataDir, { recursive: true, force: true }).catch(() => {});
}
process.exit(failed ? 1 : 0);
