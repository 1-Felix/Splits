// Unit tests for topbar.js — the shared topbar behavior module (progress-views
// design D8). Pure Node: storage is faked, no browser, no server.
import assert from "node:assert";
import {
  THEME_KEY, DEFAULT_THEME, THEMES,
  initialTheme, persistTheme, themePicker,
  navModel, dayBucket, greetingText, syncPillModel,
  PHONE_MAX, tabModel, applyThemeVars,
} from "./topbar.js";

function fakeStorage(entries = {}) {
  const m = new Map(Object.entries(entries));
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), m };
}

// ── theme persistence ─────────────────────────────────────────────────────────
// default when unset
assert.strictEqual(initialTheme(fakeStorage()), DEFAULT_THEME, "no stored theme → default");
// round-trip: persist then read back
{
  const s = fakeStorage();
  persistTheme("track", s);
  assert.strictEqual(s.m.get(THEME_KEY), "track", "persist writes the splits.theme key");
  assert.strictEqual(initialTheme(s), "track", "round-trip: the persisted theme is read back");
}
// unknown or corrupt stored values fall back to the default, never break render
assert.strictEqual(initialTheme(fakeStorage({ [THEME_KEY]: "neon-nonsense" })), DEFAULT_THEME, "unknown theme → default");
{
  const s = fakeStorage();
  persistTheme("neon-nonsense", s);
  assert.strictEqual(s.m.has(THEME_KEY), false, "an unknown theme name is never persisted");
}
// a throwing/absent storage degrades to the default (privacy modes)
assert.strictEqual(initialTheme(null), DEFAULT_THEME, "no storage → default");
assert.strictEqual(
  initialTheme({ getItem: () => { throw new Error("blocked"); } }),
  DEFAULT_THEME, "throwing storage → default");
assert.doesNotThrow(() => persistTheme("volt", { setItem: () => { throw new Error("full"); } }));

// ── theme picker model ────────────────────────────────────────────────────────
{
  const picked = [];
  const sw = themePicker("track", (n) => picked.push(n));
  assert.deepStrictEqual(sw.map((t) => t.name), Object.keys(THEMES), "one swatch per registry theme");
  for (const t of sw) {
    assert.strictEqual(t.swatch, THEMES[t.name].accent, "swatch = the theme's accent");
    assert.strictEqual(t.ring, t.name === "track" ? THEMES.track.accent : "transparent",
      "only the current theme carries the ring");
  }
  sw[2].pick();
  assert.deepStrictEqual(picked, ["sunset"], "pick handler passes the theme name through");
}

// ── nav model ─────────────────────────────────────────────────────────────────
{
  const onCockpit = navModel("cockpit");
  assert.deepStrictEqual(onCockpit.map((n) => n.label), ["Cockpit", "Progress", "Archive"]);
  assert.deepStrictEqual(onCockpit.map((n) => n.current), [true, false, false], "cockpit marked current");
  assert.strictEqual(onCockpit[0].aria, "page");
  assert.strictEqual(onCockpit[1].aria, "false");
  assert.strictEqual(onCockpit[2].aria, "false");
  assert.ok(onCockpit[0].style.includes("var(--accentFade)"), "current page visually marked");
  assert.ok(!onCockpit[1].style.includes("var(--accentFade)"));
  assert.ok(!onCockpit[2].style.includes("var(--accentFade)"));

  const onProgress = navModel("progress");
  assert.deepStrictEqual(onProgress.map((n) => n.current), [false, true, false], "progress marked current");
  assert.deepStrictEqual(onProgress.map((n) => n.href), ["./", "./progress", "./archive"],
    "relative hrefs work from /, /progress, /archive, and the original file URL");

  const onArchive = navModel("archive");
  assert.deepStrictEqual(onArchive.map((n) => n.current), [false, false, true], "archive marked current");
  assert.strictEqual(onArchive[2].aria, "page");
  assert.ok(onArchive[2].style.includes("var(--accentFade)"), "archive entry visually marked when current");

  // pages OUTSIDE the nav (run detail, compare) mark nothing current
  const onRun = navModel("run");
  assert.deepStrictEqual(onRun.map((n) => n.current), [false, false, false], "non-nav page marks nothing current");

  // archive: false drops the Archive tab (instance without an archive db);
  // anything else — true, undefined, or no opts — keeps the full nav
  const noArchive = navModel("cockpit", { archive: false });
  assert.deepStrictEqual(noArchive.map((n) => n.label), ["Cockpit", "Progress"], "archive:false drops the tab");
  assert.deepStrictEqual(noArchive.map((n) => n.current), [true, false], "current survives the filter");
  assert.deepStrictEqual(navModel("cockpit", { archive: true }).map((n) => n.label),
    ["Cockpit", "Progress", "Archive"], "archive:true keeps the tab");
  assert.deepStrictEqual(navModel("cockpit", {}).map((n) => n.label),
    ["Cockpit", "Progress", "Archive"], "unknown availability keeps the tab");

  // course is opt-IN (the mirror of archive): a race names a course or it does
  // not, so an unknown/absent course must NOT advertise an empty page.
  assert.deepStrictEqual(navModel("cockpit", { course: true }).map((n) => n.label),
    ["Cockpit", "Progress", "Archive", "Course"], "course:true adds the tab");
  assert.deepStrictEqual(navModel("cockpit", { course: false }).map((n) => n.label),
    ["Cockpit", "Progress", "Archive"], "course:false hides it");
  assert.deepStrictEqual(navModel("cockpit").map((n) => n.label),
    ["Cockpit", "Progress", "Archive"], "unknown course availability hides it");
  const onCourse = navModel("course", { course: true });
  assert.deepStrictEqual(onCourse.map((n) => n.current), [false, false, false, true],
    "course marked current");
  assert.strictEqual(onCourse[3].href, "./course");
  // both filters compose
  assert.deepStrictEqual(navModel("cockpit", { archive: false, course: true }).map((n) => n.label),
    ["Cockpit", "Progress", "Course"], "archive:false and course:true compose");
}

// ── greeting ──────────────────────────────────────────────────────────────────
assert.strictEqual(dayBucket(new Date(2026, 6, 5, 3)), "night");
assert.strictEqual(dayBucket(new Date(2026, 6, 5, 9)), "morning");
assert.strictEqual(dayBucket(new Date(2026, 6, 5, 14)), "afternoon");
assert.strictEqual(dayBucket(new Date(2026, 6, 5, 21)), "evening");
assert.strictEqual(greetingText(new Date(2026, 6, 5, 9)), "Good morning");

// ── sync pill model ───────────────────────────────────────────────────────────
const base = { syncState: "idle", syncError: null, lastSync: "2026-07-05T04:00:00Z",
               lastResult: { ok: true }, syncedOn: "2026-07-05", today: "2026-07-05" };
{
  const p = syncPillModel(base);
  assert.strictEqual(p.label, "Garmin · today");
  assert.ok(p.dotStyle.includes("var(--good)"), "fresh telemetry → good dot");
  assert.ok(p.title.includes("click to sync now"));
}
{
  const p = syncPillModel({ ...base, today: "2026-07-08" });
  assert.strictEqual(p.label, "Garmin · 3 days ago");
  assert.ok(p.dotStyle.includes("var(--warn)"), "stale telemetry (≥2 days) → warn dot");
}
{
  const p = syncPillModel({ ...base, syncState: "syncing" });
  assert.strictEqual(p.label, "Syncing…");
  assert.ok(p.dotStyle.includes("animation:pulse"), "syncing → pulsing accent dot");
}
{
  const p = syncPillModel({ ...base, syncState: "error", syncError: "MFA required" });
  assert.strictEqual(p.label, "Sync failed — retry");
  assert.ok(p.title.includes("MFA required"), "error detail lands in the title");
}
{
  // background sync failed before any telemetry existed → first-run prompt
  const p = syncPillModel({ ...base, lastSync: null, lastResult: { ok: false, error: "bad credentials\nmore" } });
  assert.strictEqual(p.label, "Connect Garmin");
  assert.ok(p.title.includes("bad credentials") && !p.title.includes("more"),
    "first error line only");
  assert.ok(p.dotStyle.includes("var(--warn)"));
}
assert.strictEqual(syncPillModel(base).dateLabel, "Jul 5", "date label feeds the history caption");

// ── the bottom tab bar's model (make-mobile-native 3.1) ──────────────────────
// tabModel is the pure half of the injected chrome: nav entries in, tabs out.
// The bar is built by MIRRORING the page's own rendered nav, so it must be
// correct for every shape navModel yields — 2 entries (an ingest-fed instance
// with no archive db and no course), 3 (the common case), and 4 (a race with a
// course). It must also cope with what the DOM mirror actually hands it:
// { label, href, current } with no `key`, and text nodes carrying whitespace.
assert.strictEqual(PHONE_MAX, 700, "the phone tier boundary is published for the swipe/tab logic");

{
  const two = tabModel(navModel("cockpit", { archive: false }));
  assert.deepStrictEqual(two.map((t) => t.key), ["cockpit", "progress"],
    "no archive db and no course → two tabs");
  assert.deepStrictEqual(two.map((t) => t.icon), ["home", "chart"], "each tab names its own icon");
  assert.deepStrictEqual(two.map((t) => t.current), [true, false], "the current page is marked");
}
{
  const three = tabModel(navModel("archive"));
  assert.deepStrictEqual(three.map((t) => t.key), ["cockpit", "progress", "archive"],
    "course is opt-in → three tabs");
  assert.strictEqual(three.filter((t) => t.current).length, 1, "exactly one tab is current");
  assert.strictEqual(three.find((t) => t.current).key, "archive");
}
{
  const four = tabModel(navModel("course", { course: true }));
  assert.deepStrictEqual(four.map((t) => t.key), ["cockpit", "progress", "archive", "course"],
    "a race with a course → four tabs");
  assert.deepStrictEqual(four.map((t) => t.icon), ["home", "chart", "archive", "route"]);
  assert.deepStrictEqual(four.map((t) => t.href), ["./", "./progress", "./archive", "./course"],
    "hrefs come from the nav model, so swipe order and tab order cannot disagree");
}
{
  // the DOM mirror's shape: absolute hrefs, whitespace-padded labels, no key,
  // aria-current rather than a boolean, and an un-mounted template entry that
  // must be dropped rather than rendered as a tab to "{{ n.href }}"
  const mirrored = tabModel([
    { label: "\n  Cockpit ", href: "http://x/", current: false },
    { label: "Progress", href: "http://x/progress", aria: "page" },
    { label: "", href: "http://x/archive" },
    { label: "Course", href: "" },
  ]);
  assert.deepStrictEqual(mirrored.map((t) => t.label), ["Cockpit", "Progress"],
    "entries without a label or an href are not tabs");
  assert.deepStrictEqual(mirrored.map((t) => t.current), [false, true],
    'aria-current="page" is read as current');
  assert.strictEqual(mirrored[0].key, "cockpit", "the key is derived from the label when absent");
}
assert.deepStrictEqual(tabModel(undefined), [], "no nav at all yields no bar");
assert.deepStrictEqual(tabModel([]), [], "an empty nav yields no bar");

// ── theme variables (make-mobile-native 2.1) ─────────────────────────────────
// applyThemeVars writes onto whatever element it is handed, so the module's
// contract is testable without a document.
{
  const el = { style: { _m: new Map(), setProperty(k, v) { this._m.set(k, v); } } };
  applyThemeVars("track", el);
  assert.strictEqual(el.style._m.get("--accent"), THEMES.track.accent, "the accent lands on the target");
  assert.strictEqual(el.style._m.get("--bg"), THEMES.track.bg, "so does the surface colour");
  applyThemeVars("sunset", el);
  assert.strictEqual(el.style._m.get("--accent"), THEMES.sunset.accent,
    "a second switch overwrites — the hoisted values never go stale");
  applyThemeVars("nonesuch", el);
  assert.strictEqual(el.style._m.get("--accent"), THEMES[DEFAULT_THEME].accent,
    "an unknown theme falls back to the default rather than leaving the root unthemed");
}

console.log("ALL PASS");
