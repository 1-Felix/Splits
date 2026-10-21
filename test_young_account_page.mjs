// test_young_account_page.mjs — a young account's monthly series (Max, 4
// leading null months) draws on the cockpit and /progress without NaN, a fake
// delta, or Felix's "Top 5% for age" claim. Boots serve.mjs over a fixture
// data dir on its own port and verifies server identity before asserting.
import assert from "node:assert";
import { spawn } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const ROOT = dirname(fileURLToPath(import.meta.url));
const PORT = 18431;
const B = "http://localhost:" + PORT;
const heatmapKm = Array.from({ length: 365 }, () => 0);

const GARMIN_DATA = `export const garminData = ${JSON.stringify({
  today: "2026-10-21",
  profile: { name: "Testa", maxHR: 190, restingHR: 47, vo2maxCurrent: 44 },
  race: { name: "Half Marathon", location: "Sonthofen", date: "2026-08-09",
          distanceKm: 21.1, goalTime: "1:59:59", goalPaceSecPerKm: 341, pb: "2:17:30" },
  readiness: { score: 80, status: "Primed", hrv: 60, restingHR: 47,
               sleepHours: 7.5, trainingLoad: 400, loadStatus: "Optimal" },
  block: [{ wk: "Wk 1", label: "Jul 6", mon: "2026-07-06", sun: "2026-07-12",
            phase: "Build", km: 30, long: "18 km", focus: "Fixture week", days: null }],
  hrZones: [
    { z: 1, label: "Recovery", min: 90 }, { z: 2, label: "Endurance", min: 180 },
    { z: 3, label: "Tempo", min: 60 }, { z: 4, label: "Threshold", min: 25 },
    { z: 5, label: "VO2 max", min: 8 },
  ],
  predictions: { halfNow: "2:03:40", halfGoal: "1:59:59", trend: "closing ≈8s/wk" },
  recentRuns: [],
  coach: { headline: "Fixture", note: "Fixture note.", focus: ["Focus"],
           log: [{ date: "2026-07-01", text: "Fixture log." }] },
  history: {
    vo2maxStartMonth: "2026-06",
    vo2max: [null, null, null, null, 44],
    paceSecPerKm: [360, 360, 360, 360, 330],
    cadenceSpm: [null, null, null, null, 162],
    weeklyKm: [20, 22, 25, 24, 26, 28],
    ctl: [30, 32, 34, 36, 38, 40],
    atl: [28, 33, 32, 37, 36, 41],
    sleep: Array.from({ length: 14 }, (_, i) => ({ hours: 7 + (i % 3) * 0.4, hrv: 55 + (i % 5) })),
  },
  heatmapKm,
  insights: {
    metricsVersion: 2,
    efficiency: { refHrBand: [125, 145], monthly: [{ month: "2026-06", paceSecPerKm: 450, inBandMin: 90 }] },
    cadence: { refPaceBand: [420, 480], monthly: [{ month: "2026-06", spm: 168, inBandMin: 90 }] },
    recordsFeed: [],
    trajectory: {
      goalSec: 7199,
      weekly: [
        { week: "2026-W20", riegelSec: 8200, garminSec: 7300, anchorId: 777 },
        { week: "2026-W21", riegelSec: null, garminSec: 7280 },
        { week: "2026-W22", riegelSec: 8100, garminSec: 7250, anchorId: 778 },
        { week: "2026-W23", riegelSec: 8068, garminSec: 7230, anchorId: 778 },
      ],
    },
    yoy: {},
  },
}, null, 1)};\n`;

const PLAN_DATA = "export const planData = {};\n";

function startServer(dataDir) {
  const child = spawn(process.execPath, ["serve.mjs"], {
    cwd: ROOT,
    env: { ...process.env, PORT: String(PORT), SYNC_ON_BOOT: "off", SYNC_AT: "off",
           SPLITS_DATA_DIR: dataDir },
    stdio: ["ignore", "ignore", "pipe"],
  });
  let err = "";
  child.stderr.on("data", (d) => (err += d));
  child.errRef = () => err;
  return child;
}
async function waitReady(child) {
  for (let i = 0; i < 60; i++) {
    if (child.exitCode !== null) throw new Error("server died\n" + child.errRef());
    try {
      const r = await fetch(B + "/garmin-data.js");
      if (r.ok) {
        const t = await r.text();
        if (t.includes('"vo2maxStartMonth": "2026-06"')) return;
        throw new Error("wrong data on :" + PORT + " - port hijacked?");
      }
    } catch (e) {
      if (String(e.message || e).includes("hijacked")) throw e;
    }
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error("server not ready\n" + child.errRef());
}

const dataDir = await mkdtemp(join(tmpdir(), "splits-young-"));
await writeFile(join(dataDir, "garmin-data.js"), GARMIN_DATA);
await writeFile(join(dataDir, "plan-data.js"), PLAN_DATA);
const server = startServer(dataDir);

let browser;
let failed = false;
let step = "boot";
async function render(path, ready) {
  const page = await browser.newPage({ viewport: { width: 1200, height: 1600 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(B + path, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(ready, null, { timeout: 15000 });
  await page.waitForFunction(() => {
    const t = document.body.innerText;
    if (window.__settle === t) return true;
    window.__settle = t;
    return false;
  }, null, { timeout: 15000, polling: 300 });
  const text = await page.evaluate(() => document.body.innerText);
  await page.close();
  return { text, errors };
}
try {
  await waitReady(server);
  browser = await chromium.launch();

  step = "progress";
  const prog = await render("/progress", () => document.body.innerText.includes("Avg run pace"));
  assert.deepStrictEqual(prog.errors, [], "no pageerror on /progress");
  assert.ok(/VO₂ max/i.test(prog.text), "the VO2 card is present: " + prog.text.slice(0, 400));
  assert.ok(prog.text.includes("44.0"), "VO2 headline reads 44.0");
  assert.ok(!/NaN|null|undefined/.test(prog.text), "no NaN/null/undefined on /progress: " +
    (prog.text.match(/.{0,30}(NaN|null|undefined).{0,30}/) || [""])[0]);
  assert.ok(!prog.text.includes("+162"), "cadence delta must not read +162");
  assert.ok(!/\+44\.0/.test(prog.text), "VO2 delta must not read +44.0");

  step = "cockpit";
  const cock = await render("/", () => document.querySelectorAll('rect[data-hb="heat"]').length > 300);
  assert.deepStrictEqual(cock.errors, [], "no pageerror on /");
  assert.ok(!/NaN|null|undefined/.test(cock.text), "no NaN/null/undefined on /");
  assert.ok(cock.text.includes("44.0"), "the VO2 tile shows 44.0");
  assert.ok(!cock.text.includes("Top 5% for age"), "no Felix-specific claim");
  assert.ok(cock.text.includes("Garmin estimate"), "neutral sub-label");
  console.log("PASS test_young_account_page");
} catch (e) {
  failed = true;
  console.error("FAIL at step '" + step + "':", e && e.stack || e);
} finally {
  if (browser) await browser.close();
  server.kill();
  await rm(dataDir, { recursive: true, force: true });
}
process.exit(failed ? 1 : 0);
