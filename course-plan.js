// course-plan.js — pace-table arithmetic over a stored course document
// (add-course-lens design D5).
//
// The sync stores the PROFILE and the calibrated model PARAMETERS, never baked
// per-target tables. That is what lets the athlete ask for any target finish
// rather than one of three presets — but it means the table has to be computed
// somewhere, and the somewhere is here, in the browser.
//
// This is not a violation of "the archive API is a window, not an engine": the
// truth (profile, damping, residual) is derived once in Python and stored. This
// module only multiplies stored factors by a base pace, exactly as chart-core
// computes scales and bands at draw time.
//
// It deliberately MIRRORS course_lens.pace_table() in Python. The two are kept
// honest by test_course_page.mjs, which asserts this implementation against the
// same fixture the Python tests use.

// Per-kilometre targets for one finish time.
//
//   lens                 the stored course document (needs perKm[].factor)
//   targetSeconds        the finish time being planned for
//   declineSteeperThan   null  → take every descent's benefit (model-optimal)
//                        -0.02 → refuse benefit on descents at or beyond -2 %
//                        0     → refuse benefit on every descent
//
// The target is always met: declining descent benefit does not slow the finish,
// it moves the effort elsewhere — which is precisely the trade worth showing.
export function paceTable(lens, targetSeconds, declineSteeperThan = null) {
  const src = (lens && lens.perKm) || [];
  const rows = src.filter((r) => r && r.factor).map((r) => ({ ...r }));
  if (!rows.length || !(targetSeconds > 0)) return [];
  if (declineSteeperThan != null) {
    for (const r of rows) {
      if (r.grade != null && r.grade <= declineSteeperThan) r.factor = Math.max(r.factor, 1);
    }
  }
  const weighted = rows.reduce((a, r) => a + r.factor * r.lengthM, 0);
  if (!(weighted > 0)) return [];
  const base = targetSeconds / weighted;          // flat-equivalent sec per metre
  let elapsed = 0;
  return rows.map((r) => {
    const secs = base * r.factor * r.lengthM;
    elapsed += secs;
    return {
      km: r.km,
      partial: !!r.partial,
      grade: r.grade,
      lengthM: r.lengthM,
      paceSecPerKm: base * r.factor * 1000,
      secondsForKm: secs,
      cumulativeSeconds: elapsed,
    };
  });
}

// The flat-equivalent base pace a target implies — the number the athlete
// actually holds on level ground, which is NOT the average pace once the course
// has taken its cut.
export function basePaceSecPerKm(lens, targetSeconds) {
  const t = paceTable(lens, targetSeconds);
  if (!t.length) return null;
  const flat = t.find((r) => r.grade != null && Math.abs(r.grade) < 0.002);
  return flat ? flat.paceSecPerKm
              : targetSeconds / ((lens.distanceM || 0) / 1000);
}

// What declining descent benefit costs against one target, in seconds. Returns
// null when the course has no descent to decline.
export function cautionCostSeconds(lens, targetSeconds, declineSteeperThan = -0.02) {
  const optimal = paceTable(lens, targetSeconds);
  if (!optimal.length) return null;
  const declined = paceTable(lens, targetSeconds, declineSteeperThan);
  if (!declined.length) return null;
  // Both tables hit the same finish, so the cost is expressed as the extra time
  // the DECLINED plan would take if it kept the optimal plan's base pace.
  const frac = lens.steepDescentGiveawayFraction;
  if (frac == null) return null;
  return frac * targetSeconds;
}

// mm:ss for a pace or a duration under an hour; h:mm:ss beyond.
export function fmtDuration(seconds) {
  if (seconds == null || !isFinite(seconds)) return "—";
  const s = Math.round(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
}

export function fmtPace(secPerKm) {
  if (secPerKm == null || !isFinite(secPerKm)) return "—";
  return fmtDuration(secPerKm) + "/km";
}

export function fmtGrade(grade) {
  if (grade == null) return "—";
  const pct = grade * 100;
  return (pct >= 0 ? "+" : "") + pct.toFixed(2) + "%";
}

// "1:59:59" / "2:01:48" → seconds. Returns null on anything unparseable, so a
// typed target can never produce a NaN table.
export function parseTarget(text) {
  const m = /^\s*(\d{1,2}):([0-5]\d)(?::([0-5]\d))?\s*$/.exec(String(text || ""));
  if (!m) return null;
  const a = Number(m[1]), b = Number(m[2]), c = m[3] == null ? null : Number(m[3]);
  const secs = c == null ? a * 60 + b : a * 3600 + b * 60 + c;
  return secs > 0 ? secs : null;
}

// The kilometres worth calling out on screen: the steepest climb and the
// steepest descent the engine detected, mapped to the km rows they touch.
export function decisiveKm(lens) {
  const segs = (lens && lens.segments) || [];
  const out = new Map();
  const climb = segs.filter((s) => s.kind === "climb")
    .sort((a, b) => b.changeM - a.changeM)[0];
  const descent = segs.filter((s) => s.kind === "descent")
    .sort((a, b) => a.changeM - b.changeM)[0];
  for (const [seg, kind] of [[climb, "climb"], [descent, "descent"]]) {
    if (!seg) continue;
    for (let km = Math.ceil(seg.startKm); km <= Math.ceil(seg.endKm); km++) out.set(km, kind);
  }
  return out;
}
