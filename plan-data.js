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
   * Mon 2026-06-22 → Sun 2026-06-28. Days marked "done" mirror what Garmin
   * actually logged this week (3× strength, 1× indoor cycling, 2 runs);
   * Sunday's long run is the one prescribed session.
   * status: "done" | "today" | "upcoming"   kind: "run" | "strength" | "cross" */
  weekPlan: [
    { day: "Mon", date: "2026-06-22", kind: "cross", title: "Indoor Cycling", detail: "66 min · Z2–Z3, avg HR 145", load: "Moderate", status: "done", km: 0 },
    { day: "Tue", date: "2026-06-23", kind: "strength", title: "Strength · Full Body", detail: "43 min · avg HR 103", load: "Moderate", status: "done", km: 0 },
    { day: "Wed", date: "2026-06-24", kind: "run", title: "Recovery Run", detail: "4.5 km easy · HR 124 (Z2)", load: "Easy", status: "done", km: 4.5 },
    { day: "Thu", date: "2026-06-25", kind: "strength", title: "Strength · Full Body", detail: "44 min · avg HR 99", load: "Moderate", status: "done", km: 0 },
    { day: "Fri", date: "2026-06-26", kind: "run", title: "Tempo Pyramid", detail: "1–2–1 km @ threshold · HR 161 (Z4)", load: "Hard", status: "done", km: 7.3 },
    { day: "Sat", date: "2026-06-27", kind: "strength", title: "Strength · Full Body", detail: "56 min · avg HR 102", load: "Moderate", status: "today", km: 0 },
    { day: "Sun", date: "2026-06-28", kind: "run", title: "Long Run", detail: "16 km easy @ ~6:15 · practice race fuel @ 8 km", load: "Moderate", status: "upcoming", km: 16 },
  ],

  /* --------------------------------------------------- next week, pre-loaded
   * Wk 2 (Mon 2026-06-29 → Sun 2026-07-05) — the first week with the 4th run.
   * On Monday Jun 29, this becomes the live `weekPlan` (swap it in / ask me to).
   * Mon doubles the group ride with an easy shakeout; one strength day is light;
   * Fri is the threshold session, Sun the long run (held at 16 — we add the run
   * this week, then grow the long run from Wk 3).                            */
  nextWeekPlan: [
    { day: "Mon", date: "2026-06-29", kind: "cross", title: "Ride + Easy Run", detail: "Z2 group ride + 4 km easy a.m. shakeout", load: "Easy", status: "today", km: 4 },
    { day: "Tue", date: "2026-06-30", kind: "strength", title: "Strength · Full Body", detail: "Full session", load: "Moderate", status: "upcoming", km: 0 },
    { day: "Wed", date: "2026-07-01", kind: "run", title: "Easy Run", detail: "5 km easy · Z2", load: "Easy", status: "upcoming", km: 5 },
    { day: "Thu", date: "2026-07-02", kind: "strength", title: "Strength · Full Body", detail: "Full session", load: "Moderate", status: "upcoming", km: 0 },
    { day: "Fri", date: "2026-07-03", kind: "run", title: "Threshold Reps", detail: "1.5 wu · 4×1 km @ 5:25–5:35 (60s jog) · 1.5 cd", load: "Hard", status: "upcoming", km: 7 },
    { day: "Sat", date: "2026-07-04", kind: "strength", title: "Strength · Light", detail: "Light / mobility", load: "Easy", status: "upcoming", km: 0 },
    { day: "Sun", date: "2026-07-05", kind: "run", title: "Long Run", detail: "16 km easy @ ~6:10 · fuel @ 8 km", load: "Moderate", status: "upcoming", km: 16 },
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
    note: "Half PB is 2:19:07 (Dec 2025), but your spring block pushed fitness well past it — Garmin projects 2:04 right now. The gap to sub-2:00 (5:41/km) is volume: weekly running slipped to the teens–low-20s km off a 35+ km spring, and fitness (CTL) is down near 20. The block rebuilds running to ~40 km/wk by mid-July and the long run to 20 km, holding one threshold session a week, then tapers into Aug 9. Biggest lever: a 4th easy run on top of your steady 3×/week — keep the Monday group ride and all 3 strength days (one light), just layer easy km on, even as a morning double. Hold that and sub-2 is live; drift on volume and it's more like 2:03–2:05.",
    focus: ["Rebuild volume → 40 km/wk", "Add a 4th easy run", "Long run → 20 km", "Keep 3× strength (1 light)"],
    log: [
      { date: "2026-06-27", text: "Mapped the full 6-week block: rebuild to ~40 km/wk by Jul 20 (a 4th easy run joins from next week), long run 16 → 20 km, then taper into Aug 9. Bumped this Sunday's long run to 16 km — you're recovered and ready." },
      { date: "2026-06-26", text: "Friday's 1–2–1 km tempo pyramid held Z4 (avg HR 161). Threshold is still sharp — protecting one quality run a week through the build." },
      { date: "2026-06-24", text: "You're consistent at 3 runs/week — the build adds a 4th easy run on top (an easy morning double with the Monday group ride, or paired with your light strength day). The ride and all 3 strength sessions stay; we layer running on, not instead." },
    ],
  },
};

export default planData;
