// Unit tests for topbar.js — the shared topbar behavior module (progress-views
// design D8). Pure Node: storage is faked, no browser, no server.
import assert from "node:assert";
import {
  THEME_KEY, DEFAULT_THEME, THEMES,
  initialTheme, persistTheme, themePicker,
  navModel, dayBucket, greetingText, syncPillModel,
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
  assert.deepStrictEqual(onCockpit.map((n) => n.label), ["Cockpit", "Progress"]);
  assert.deepStrictEqual(onCockpit.map((n) => n.current), [true, false], "cockpit marked current");
  assert.strictEqual(onCockpit[0].aria, "page");
  assert.strictEqual(onCockpit[1].aria, "false");
  assert.ok(onCockpit[0].style.includes("var(--accentFade)"), "current page visually marked");
  assert.ok(!onCockpit[1].style.includes("var(--accentFade)"));

  const onProgress = navModel("progress");
  assert.deepStrictEqual(onProgress.map((n) => n.current), [false, true], "progress marked current");
  assert.deepStrictEqual(onProgress.map((n) => n.href), ["./", "./progress"],
    "relative hrefs work from /, /progress, and the original file URL");
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

console.log("ALL PASS");
