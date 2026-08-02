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
      await page.evaluate(() => window.scrollTo(0, 1200));
      await page.waitForTimeout(120);
      const after = await page.evaluate(() => {
        const h = document.querySelector("header.topbar");
        const bar = document.querySelector("nav.tabbar");
        return { headerTop: Math.round(h.getBoundingClientRect().top),
                 y: Math.round(window.scrollY),
                 barBottom: bar ? Math.round(bar.getBoundingClientRect().bottom) : null,
                 vh: window.innerHeight };
      });
      if (after.y > 400) {   // only meaningful where the document is long enough
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
