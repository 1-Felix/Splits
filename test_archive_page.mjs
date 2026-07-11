// test_archive_page.mjs — the /archive browser end to end (archive-browser 3.7).
//
// Boots serve.mjs over a fixture archive big enough to paginate and drives a
// real browser: rows render newest-first with an honest count, load-more
// appends, the type/year/name filters narrow AND land in the URL (a filtered
// view survives reload), run rows link to /run/:id while other activities stay
// inert, selection drives the compare URL, and the page degrades honestly when
// the archive 503s — at load AND mid-session, without clearing shown rows.
import assert from "node:assert";
import { spawn } from "node:child_process";
import { mkdtemp, rename, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";
import { chromium } from "playwright";

const ROOT = dirname(fileURLToPath(import.meta.url));
const PORT = 8171;
const B = "http://localhost:" + PORT;
const Bmissing = "http://localhost:" + (PORT + 1);

function makeArchive(dir) {
  const db = new DatabaseSync(join(dir, "activity-archive.db"));
  db.exec(`CREATE TABLE activities (
    activity_id INTEGER PRIMARY KEY, start_time_local TEXT NOT NULL, type_key TEXT,
    name TEXT, distance_m REAL, duration_s REAL, avg_hr INTEGER, max_hr INTEGER,
    avg_cadence REAL, elevation_gain_m REAL, summary_json TEXT NOT NULL,
    detail_json TEXT, detail_fetched_at TEXT, first_seen_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, detail_distilled_json TEXT, detail_streams_json TEXT)`);
  const ins = db.prepare(`INSERT INTO activities (activity_id, start_time_local, type_key,
      name, distance_m, duration_s, avg_hr, max_hr, avg_cadence, elevation_gain_m,
      summary_json, detail_json, first_seen_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', null, 'x', 'x')`);
  // 60 activities across 2024–2026 so the default 50-row page paginates:
  // 55 runs (one of them the searchable race) + 5 strength sessions
  let id = 100;
  for (let i = 0; i < 55; i++) {
    const year = 2024 + (i % 3);
    const month = 1 + (i % 12);
    const day = 1 + (i % 27);
    const name = i === 10 ? "Sonthofen Halbmarathon" : "Base Run " + String(i + 1).padStart(2, "0");
    ins.run(id++, `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")} 07:30:00`,
      "running", name, 8000 + i * 100, 2900 + i * 20, 140 + (i % 12), 165, 165, 40);
  }
  for (let i = 0; i < 5; i++) {
    ins.run(id++, `2026-0${i + 1}-15 18:00:00`, "strength_training", "Gym", null, 3600, 110, 140, null, null);
  }
  db.close();
}

function startServer(port, env) {
  const child = spawn(process.execPath, ["serve.mjs"], {
    cwd: ROOT,
    env: { ...process.env, PORT: String(port), SYNC_ON_BOOT: "off", SYNC_AT: "off", ...env },
    stdio: ["ignore", "ignore", "pipe"],
  });
  let err = "";
  child.stderr.on("data", (d) => (err += d));
  child.errRef = () => err;
  return child;
}
async function waitReady(base, errRef) {
  for (let i = 0; i < 60; i++) {
    try { const r = await fetch(base + "/api/status"); if (r.ok) return; } catch {}
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error("server not ready\n" + (errRef ? errRef() : ""));
}

const dataDir = await mkdtemp(join(tmpdir(), "splits-archpage-"));
const emptyDir = await mkdtemp(join(tmpdir(), "splits-archpage-empty-"));
makeArchive(dataDir);
const server = startServer(PORT, { SPLITS_DATA_DIR: dataDir });
const serverMissing = startServer(PORT + 1, { SPLITS_DATA_DIR: emptyDir });

let browser;
let failed = false;
let step = "boot";
try {
  await waitReady(B, server.errRef);
  await waitReady(Bmissing, serverMissing.errRef);
  browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1200, height: 1400 } });
  const pageErrors = [];
  page.on("pageerror", (e) => pageErrors.push(String(e)));
  const rows = () => page.evaluate(() => document.querySelectorAll(".arch-row").length);
  const bodyText = () => page.evaluate(() => document.body.innerText);

  // ── first page: newest-first rows + an honest count + load more ───────────
  step = "first page";
  await page.goto(B + "/archive", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => document.querySelectorAll(".arch-row").length > 0, null, { timeout: 15000 });
  assert.strictEqual(await rows(), 50, "the default page holds 50 rows");
  assert.ok((await bodyText()).includes("Showing 50 of 60"), "the count states shown-of-total");
  const dates = await page.evaluate(() =>
    [...document.querySelectorAll(".arch-row > span:nth-child(2)")].map((e) => e.textContent));
  const sorted = [...dates].sort().reverse();
  assert.deepStrictEqual(dates, sorted, "rows are newest-first");

  step = "load more";
  await page.click("text=Load more");
  await page.waitForFunction(() => document.querySelectorAll(".arch-row").length === 60, null, { timeout: 10000 });
  assert.ok((await bodyText()).includes("Showing 60 of 60"), "load more appends and updates the count");
  assert.strictEqual(await page.evaluate(() => [...document.querySelectorAll("button")].filter((b) => b.textContent === "Load more").length), 0,
    "an exhausted list offers no load-more control");

  // ── filters narrow AND land in the URL ─────────────────────────────────────
  step = "type filter";
  await page.click("button.scope-chip:has-text('Strength')");
  await page.waitForFunction(() => {
    const r = document.querySelectorAll(".arch-row");
    return r.length === 5 && [...r].every((x) => x.textContent.includes("STRENGTH"));
  }, null, { timeout: 10000 });
  assert.ok(page.url().includes("type=strength_training"), "the type filter is mirrored into the URL");
  // strength rows are PLAIN: no link, no compare toggle, nothing focusable
  const inert = await page.evaluate(() => ({
    links: document.querySelectorAll(".arch-row a").length,
    toggles: document.querySelectorAll(".arch-row .cmp-toggle").length,
  }));
  assert.deepStrictEqual(inert, { links: 0, toggles: 0 }, "non-run rows carry no controls");

  step = "name search";
  await page.click("button.scope-chip:has-text('Runs')");
  await page.fill(".arch-search", "sonthofen");
  await page.waitForFunction(() => document.querySelectorAll(".arch-row").length === 1, null, { timeout: 10000 });
  assert.ok((await bodyText()).includes("Sonthofen Halbmarathon"), "name search finds the race");
  assert.ok(page.url().includes("q=sonthofen") && page.url().includes("type=running"),
    "search + type land in the URL: " + page.url());

  // a filtered view survives reload — the URL is the filter state
  step = "reload restores filters";
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => document.querySelectorAll(".arch-row").length === 1, null, { timeout: 15000 });
  assert.strictEqual(await page.inputValue(".arch-search"), "sonthofen", "the search box restores from the URL");
  assert.ok((await bodyText()).includes("Sonthofen Halbmarathon"), "the filtered rows restore from the URL");

  // ── the empty state is explicit and the filters stay usable ───────────────
  step = "empty state";
  await page.fill(".arch-search", "zzz-no-such-run");
  await page.waitForFunction(() => document.body.innerText.includes("No archived activity matches"), null, { timeout: 10000 });
  await page.fill(".arch-search", "");
  await page.click("button.scope-chip:has-text('All years')");
  await page.waitForFunction(() => document.querySelectorAll(".arch-row").length >= 50, null, { timeout: 10000 });

  // ── run rows click through to /run/:id ─────────────────────────────────────
  step = "run click-through";
  await page.click(".arch-row a.arch-link");
  await page.waitForFunction(() => /\/run\/\d+$/.test(window.location.pathname), null, { timeout: 10000 });
  await page.waitForFunction(() => document.body.innerText.includes("Base Run") || document.body.innerText.includes("Sonthofen"),
    null, { timeout: 15000 });

  // ── selection → compare URL, capped at four with a visible refusal ────────
  step = "selection";
  await page.goto(B + "/archive?type=running", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => document.querySelectorAll(".cmp-toggle").length >= 5, null, { timeout: 15000 });
  const clickToggle = (i) => page.evaluate((i) => document.querySelectorAll(".cmp-toggle")[i].click(), i);
  const pickedIds = await page.evaluate(() =>
    [...document.querySelectorAll(".arch-row a.arch-link")].slice(0, 2).map((a) => a.getAttribute("href").split("/").pop()));
  await clickToggle(0);
  await clickToggle(1);
  await page.waitForFunction(() => document.body.innerText.includes("2 selected"), null, { timeout: 5000 });
  await clickToggle(2);
  await clickToggle(3);
  await clickToggle(4); // the fifth is refused, visibly, and the selection stands
  await page.waitForFunction(() => document.body.innerText.includes("comparison limit"), null, { timeout: 5000 });
  assert.ok((await bodyText()).includes("4 selected"), "the fifth selection is refused — still 4");
  await clickToggle(3);
  await clickToggle(2); // back down to the first two
  await page.waitForFunction(() => document.body.innerText.includes("2 selected"), null, { timeout: 5000 });
  step = "compare navigation";
  await page.click("button.cmp-go");
  await page.waitForFunction(() => window.location.pathname === "/compare", null, { timeout: 10000 });
  assert.ok(page.url().includes("ids=" + pickedIds.join("%2C")) || page.url().includes("ids=" + pickedIds.join(",")),
    "compare navigates with the selected ids in order: " + page.url());

  // ── offline at load: chrome + honest state + retry ─────────────────────────
  step = "offline at load";
  await page.goto(Bmissing + "/archive", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => document.body.innerText.includes("Archive offline"), null, { timeout: 15000 });
  const off = await page.evaluate(() => ({
    topbar: !!document.querySelector("header.topbar"),
    retry: [...document.querySelectorAll("button")].some((b) => b.textContent === "Try again"),
  }));
  assert.ok(off.topbar && off.retry, "offline: page chrome + honest message + retry");

  // ── mid-session failure keeps the rows; retry recovers without a reload ───
  step = "mid-session failure";
  await page.goto(B + "/archive", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => document.querySelectorAll(".arch-row").length === 50, null, { timeout: 15000 });
  const dbPath = join(dataDir, "activity-archive.db");
  await rename(dbPath, dbPath + ".away");   // per-request opens → next request 503s
  await page.fill(".arch-search", "base");
  await page.waitForFunction(() => document.body.innerText.includes("Archive unavailable"), null, { timeout: 10000 });
  assert.strictEqual(await rows(), 50, "a failed filter request never clears the shown rows");
  step = "mid-session retry";
  await rename(dbPath + ".away", dbPath);
  await page.click("text=Try again");
  // 54 of the 55 runs are named "Base Run …" — the retry re-runs q=base
  await page.waitForFunction(() => document.body.innerText.includes("Showing 50 of 54")
    && !document.body.innerText.includes("Archive unavailable"), null, { timeout: 10000 });
  assert.ok(page.url().includes("q=base"), "retry re-runs the filters that failed");

  assert.strictEqual(pageErrors.length, 0, "no uncaught page errors: " + JSON.stringify(pageErrors));
  console.log("ALL PASS");
} catch (e) {
  failed = true;
  console.error("FAIL at step '" + step + "':", e.message);
} finally {
  if (browser) await browser.close().catch(() => {});
  server.kill();
  serverMissing.kill();
  await rm(dataDir, { recursive: true, force: true }).catch(() => {});
  await rm(emptyDir, { recursive: true, force: true }).catch(() => {});
}
process.exit(failed ? 1 : 0);
