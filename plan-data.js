/* =============================================================================
 *  plan-data.js  —  THE PLAN. Owned by the AI coach (you, in Claude Code).
 *
 *  These are the EDITABLE coaching dials. `sync_garmin.py` NEVER touches this
 *  file, so nightly telemetry syncs can never overwrite your training plan.
 *  Edit here, reload the dashboard, done.
 *
 *  `running-data.js` merges this with `garmin-data.js` into `athleteData`.
 *
 *  PB below is the real half-marathon personal record now synced into
 *  garmin-data.js → `personalBests.half` (2:19:07, 2025-12-28).
 * ========================================================================== */

export const planData = {
  /* ------------------------------------------------------------------- race */
  race: {
    name: "Allgäu Panorama Halbmarathon",
    location: "Sonthofen",
    date: "2026-08-09",
    distanceKm: 21.1,
    goalTime: "1:59:59",       // sub-2:00 — "if possible"
    goalPaceSecPerKm: 341,     // 5:41 /km
    pb: "2:19:07",             // real half PB (Garmin PR, 2025-12-28)
    pbDate: "2025-12-28",
  },

  /* ----------------------------------------------------- this week's plan
   * Wk 2 — Mon 2026-06-29 → Sun 2026-07-05. The first week with the 4th run:
   * Monday pairs the 19:00 spin class with an easy shakeout, Fri is the threshold
   * session, Sun the long run (held at 16 — we add frequency this week and grow
   * the long run from Wk 3). Roll the next week in each Monday.
   * status: "done" | "today" | "upcoming"   kind: "run" | "strength" | "cross" */
  weekPlan: [
    { day: "Mon", date: "2026-06-29", kind: "cross", title: "Spin + Easy Run", detail: "1 h spin · level 2 · 19:00 + 4 km easy a.m. shakeout", load: "Easy", status: "today", km: 4 },
    { day: "Tue", date: "2026-06-30", kind: "strength", title: "Strength · Full Body", detail: "Full session", load: "Moderate", status: "upcoming", km: 0 },
    { day: "Wed", date: "2026-07-01", kind: "run", title: "Easy Run", detail: "5 km easy · Z2 (by HR if warm)", load: "Easy", status: "upcoming", km: 5 },
    { day: "Thu", date: "2026-07-02", kind: "strength", title: "Strength · Full Body", detail: "Full session", load: "Moderate", status: "upcoming", km: 0 },
    { day: "Fri", date: "2026-07-03", kind: "run", title: "Threshold + a.m. Spin", detail: "7:00 spin · 1 h · level 2 + threshold: 1.5 wu · 4×1 km @ 5:25–5:35 (60s jog) · 1.5 cd", load: "Hard", status: "upcoming", km: 7 },
    { day: "Sat", date: "2026-07-04", kind: "strength", title: "Strength · Light", detail: "Light / mobility", load: "Easy", status: "upcoming", km: 0 },
    { day: "Sun", date: "2026-07-05", kind: "run", title: "Long Run", detail: "16 km easy @ ~6:10 (run early — heat) · fuel @ 8 km", load: "Moderate", status: "upcoming", km: 16 },
  ],

  /* --------------------------------------------------- next week, pre-loaded
   * Wk 3 (Mon 2026-07-06 → Sun 2026-07-12) — long run grows to 18 km and the
   * threshold session steps up to 5×1 km. On Mon Jul 6, swap this into
   * `weekPlan` (or ask me to) and I'll pre-load Wk 4 here.                    */
  nextWeekPlan: [
    { day: "Mon", date: "2026-07-06", kind: "cross", title: "Spin + Easy Run", detail: "1 h spin · level 2 · 19:00 + 4 km easy a.m. shakeout", load: "Easy", status: "upcoming", km: 4 },
    { day: "Tue", date: "2026-07-07", kind: "strength", title: "Strength · Full Body", detail: "Full session", load: "Moderate", status: "upcoming", km: 0 },
    { day: "Wed", date: "2026-07-08", kind: "run", title: "Easy Run", detail: "5 km easy · Z2", load: "Easy", status: "upcoming", km: 5 },
    { day: "Thu", date: "2026-07-09", kind: "strength", title: "Strength · Full Body", detail: "Full session", load: "Moderate", status: "upcoming", km: 0 },
    { day: "Fri", date: "2026-07-10", kind: "run", title: "Threshold Reps", detail: "1.5 wu · 5×1 km @ 5:25–5:35 (60s jog) · 1.5 cd", load: "Hard", status: "upcoming", km: 8 },
    { day: "Sat", date: "2026-07-11", kind: "strength", title: "Strength · Light", detail: "Light / mobility", load: "Easy", status: "upcoming", km: 0 },
    { day: "Sun", date: "2026-07-12", kind: "run", title: "Long Run", detail: "18 km @ ~6:10 · fuel @ 8 & 14 km", load: "Moderate", status: "upcoming", km: 18 },
  ],

  /* ------------------------------------------------ the 6-week block (arc)
   * The forward plan to race day, one row per week (Mon→Sun). The dashboard's
   * "Road to Sonthofen" panel renders this; the current week auto-highlights
   * from `mon`/`sun` vs garmin-data `today`. `km` = planned RUNNING volume and
   * matches that week's weekPlan sum (race week excludes the race itself —
   * that's the `long`). Peak 40 km ≈ your proven ceiling; ramp ≈ 10%/wk.     */
  block: [
    { wk: "Wk 1", label: "Jun 22", mon: "2026-06-22", sun: "2026-06-28", phase: "Rebuild", km: 28, long: "16 km", focus: "Tempo pyramid + long run back to 16" },
    { wk: "Wk 2", label: "Jun 29", mon: "2026-06-29", sun: "2026-07-05", phase: "Build",   km: 32, long: "16 km", focus: "Add the 4th easy run · hold the long" },
    { wk: "Wk 3", label: "Jul 6",  mon: "2026-07-06", sun: "2026-07-12", phase: "Build",   km: 35, long: "18 km", focus: "Threshold reps · long run grows" },
    { wk: "Wk 4", label: "Jul 13", mon: "2026-07-13", sun: "2026-07-19", phase: "Build",   km: 38, long: "19 km", focus: "Cruise intervals · longest run yet" },
    { wk: "Wk 5", label: "Jul 20", mon: "2026-07-20", sun: "2026-07-26", phase: "Peak",    km: 40, long: "20 km", focus: "Peak volume · 3×3k @ goal pace" },
    { wk: "Wk 6", label: "Jul 27", mon: "2026-07-27", sun: "2026-08-02", phase: "Taper",   km: 31, long: "15 km", focus: "Sharpen · cut volume ~25%, stay fast" },
    { wk: "Wk 7", label: "Aug 3",  mon: "2026-08-03", sun: "2026-08-09", phase: "Race",    km: 13, long: "Race",  focus: "Full taper · RACE Sun Aug 9" },
  ],

  /* -------------------------------------------------------------- the coach
   * `note` = current focus. `log` = adjustment feed, most-recent first.       */
  coach: {
    headline: "6 weeks to Sonthofen — rebuild volume, keep the speed.",
    note: "Half PB is 2:19:07 (Dec 2025), but your spring block pushed fitness well past it — Garmin projects 2:04 right now. The gap to sub-2:00 (5:41/km) is volume: weekly running slipped to the teens–low-20s km off a 35+ km spring, and fitness (CTL) is down near 20. The block rebuilds running to ~40 km/wk by mid-July and the long run to 20 km, holding one threshold session a week, then tapers into Aug 9. Biggest lever: a 4th easy run on top of your steady 3×/week — keep the Monday spin class and all 3 strength days (one light), just layer easy km on, even as a morning double. Hold that and sub-2 is live; drift on volume and it's more like 2:03–2:05.",
    focus: ["Rebuild volume → 40 km/wk", "Add a 4th easy run", "Long run → 20 km", "Keep 3× strength (1 light)"],
    log: [
      { date: "2026-06-29", text: "Plan correction: Monday's cross-training is your standing 1 h level-2 spin class at 19:00 (not a group ride) — same easy aerobic load, so the week's stimulus is unchanged. This week you're also riding a Friday 7 a.m. spin before the threshold session: keep it genuinely easy (level 2) so it stays a bonus aerobic hit and doesn't blunt Friday's quality work." },
      { date: "2026-06-28", text: "Long run logged: 16 km @ 6:12, but 28–30 °C drove it to threshold — avg HR 170 (86% max), +16 bpm cardiac drift, Training Effect 5.0. Pacing was right; the heat repriced the effort. Banking recovery (Monday's shakeout stays truly easy), and from here: on hot days run easy by HR ~150, not pace." },
      { date: "2026-06-27", text: "Mapped the full 6-week block: rebuild to ~40 km/wk by Jul 20 (a 4th easy run joins this week), long run 16 → 20 km, then taper into Aug 9." },
      { date: "2026-06-26", text: "Friday's 1–2–1 km tempo pyramid held Z4 (avg HR 161). Threshold is still sharp — protecting one quality run a week through the build." },
    ],
  },
};

export default planData;
