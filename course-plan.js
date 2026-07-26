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
      // The row's REAL span, carried through. `km` is a label: kilometre marks
      // snap to the nearest stored point, so km 1 can end at 991 m, and the
      // final row is a stub whose label (22) times 1000 lands far past the
      // finish. Anything reconstructing bounds from the label drifts by metres
      // and drops the stub entirely.
      startM: r.startM,
      endM: r.endM,
      partial: !!r.partial,
      grade: r.grade,
      lengthM: r.lengthM,
      // Rounded to 1 dp exactly as course_lens.pace_table() does. The mirror
      // claim is only worth making if the two agree to the last digit, and
      // test_course_parity.mjs holds both to a shared fixture.
      paceSecPerKm: Math.round(base * r.factor * 1000 * 10) / 10,
      secondsForKm: Math.round(secs * 10) / 10,
      cumulativeSeconds: Math.round(elapsed * 10) / 10,
    };
  });
}

// The flat-equivalent base pace a target implies — the number the athlete
// actually holds on level ground, which is NOT the average pace once the course
// has taken its cut.
//
// Computed the way the pace table itself derives it: target ÷ the cost-weighted
// profile. Picking a "near-flat" kilometre's pace instead would be off by
// whatever grade that kilometre still carries (0.7 s/km on this course, enough
// to flip the displayed 5:40 to 5:41), and falling back to distance-average
// pace would return precisely the quantity this comment says it is not.
export function basePaceSecPerKm(lens, targetSeconds, declineSteeperThan = null) {
  const rows = ((lens && lens.perKm) || []).filter((r) => r && r.factor);
  if (!rows.length || !(targetSeconds > 0)) return null;
  let weighted = 0;
  for (const r of rows) {
    let f = r.factor;
    if (declineSteeperThan != null && r.grade != null && r.grade <= declineSteeperThan) {
      f = Math.max(f, 1);
    }
    weighted += f * r.lengthM;
  }
  if (!(weighted > 0)) return null;
  return (targetSeconds / weighted) * 1000;
}

// What declining descent benefit costs against one target, in seconds.
//
// Both tables hit the same finish by construction, so the cost cannot be read
// off their finish times. It is the extra time the DECLINED profile would take
// if it held the optimal plan's base pace — i.e. the ratio of the two weighted
// profiles. Computed from `perKm` at the threshold actually passed, rather than
// read off the course-level fraction, which is baked at one fixed threshold and
// would return the same answer for every argument.
export function cautionCostSeconds(lens, targetSeconds, declineSteeperThan = -0.02) {
  const rows = ((lens && lens.perKm) || []).filter((r) => r && r.factor);
  if (!rows.length || !(targetSeconds > 0)) return null;
  let optimal = 0, declined = 0;
  for (const r of rows) {
    optimal += r.factor * r.lengthM;
    const take = (r.grade != null && r.grade <= declineSteeperThan)
      ? Math.max(r.factor, 1) : r.factor;
    declined += take * r.lengthM;
  }
  if (!(optimal > 0)) return null;
  return targetSeconds * (declined / optimal - 1);
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
