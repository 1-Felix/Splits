// test_palette.mjs — palettes are validated by script, not by eye (chart-engine 6.3/6.4).
//
// Runs the vendored validator (tools/validate-palette.mjs — the dataviz skill's
// six-checks script) over every theme's series palette and zone ramp, against
// that theme's OWN panel surface. Also asserts the token-role separation: no
// theme reuses a status token (good/warn) or a zone token as a series token,
// and no theme's accent doubles as its warn (the original `track` defect).
import assert from "node:assert";
import { THEMES } from "./topbar.js";
import { validate, validateOrdinal, contrast } from "./tools/validate-palette.mjs";

const MODE = { volt: "dark", track: "light", sunset: "dark" };

for (const [name, t] of Object.entries(THEMES)) {
  const mode = MODE[name];
  assert.ok(mode, `theme '${name}' has a declared mode in this test — add it`);
  const surface = t.panel;

  // series tokens exist and are a validated categorical palette
  const series = [t.series1, t.series2, t.series3, t.series4];
  for (const s of series) assert.ok(/^#[0-9a-fA-F]{6}$/.test(s || ""), `${name}: series tokens are hex`);
  const r = validate(series, { mode, surface });
  for (const [check, state, detail] of r.report) {
    assert.ok(state !== false && state !== "fail", `${name} series ${check}: ${detail}`);
  }

  // zone ramp is ordinal: one hue, monotone lightness, visible steps
  const zones = [t.z1, t.z2, t.z3, t.z4, t.z5];
  const rz = validateOrdinal(zones, { mode, surface });
  for (const [check, state, detail] of rz.report) {
    assert.ok(state !== false && state !== "fail", `${name} zones ${check}: ${detail}`);
  }

  // token-role separation: a status colour is never a series colour, a zone
  // colour is never a series colour, and series slots don't repeat
  const norm = (c) => String(c).toLowerCase();
  const status = new Set([t.good, t.warn].map(norm));
  const zoneSet = new Set(zones.map(norm));
  for (const s of series.map(norm)) {
    assert.ok(!status.has(s), `${name}: series token ${s} reuses a status token`);
    assert.ok(!zoneSet.has(s), `${name}: series token ${s} reuses a zone token`);
  }
  assert.strictEqual(new Set(series.map(norm)).size, 4, `${name}: series tokens are distinct`);

  // the original track defect, as a rule for every theme: accent !== warn
  assert.notStrictEqual(norm(t.accent), norm(t.warn), `${name}: accent must not double as warn`);

  // status text must be readable on the panel it annotates (icon+label pairing
  // still applies; this guards the label's ink)
  for (const [role, c] of [["good", t.good], ["warn", t.warn]]) {
    assert.ok(contrast(c, surface) >= 3, `${name}: ${role} ${c} >= 3:1 on panel (got ${contrast(c, surface).toFixed(2)})`);
  }
}

console.log("ALL PASS");
