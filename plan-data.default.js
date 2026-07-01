/* =============================================================================
 *  plan-data.default.js  —  SAMPLE PLAN (the shipped default / seed).
 *
 *  A generic starter plan. On first container boot the entrypoint copies it to
 *  <data volume>/plan-data.js IF that file does not already exist, then never
 *  touches it again — so replace it with your own plan and it sticks. In local
 *  dev the live plan is just `plan-data.js` next to this file.
 *
 *  THE PLAN is coach-owned (edit it in Claude Code, or by hand). `sync_garmin.py`
 *  NEVER touches the plan, so nightly telemetry syncs can't overwrite it. Edit
 *  the live plan-data.js, reload the dashboard, done.
 *
 *  STRUCTURE: the whole plan is one `block` — one row per week (Mon→Sun). Each
 *  week carries a summary (km / long / focus / phase) plus an optional `days`
 *  array holding that week's 7 sessions. The dashboard renders the block as the
 *  "Road to race day" panel; clicking a week loads its `days` into "THIS WEEK"
 *  (a "back to current" control returns to the live week). Weeks with `days:null`
 *  aren't detailed yet — the dashboard shows their summary as a placeholder, so
 *  you flesh out each week (add its `days`) as it approaches. The current week
 *  auto-highlights from its `mon`/`sun` dates vs today.
 *
 *  DAY SHAPE:
 *    { day, date, kind, title, load, km,   // always
 *      pace, zone,                         // run target — surfaced as a chip
 *      segments:[{label,val,rest?}],       // warm-up / reps / cool-down
 *      extra, fuel,                        // optional notes
 *      detail }                            // prose fallback / summary line
 *    kind: "run" | "strength" | "cross"    load: "Easy" | "Moderate" | "Hard"
 *    A minimal day is just { day, date, kind, title, load, km }.
 * ========================================================================== */

export const planData = {
  /* ------------------------------------------------------------------- race */
  race: {
    name: "Half Marathon",
    location: "Lakeside Half",
    date: "2026-08-09",          // ISO date — drives the countdown
    distanceKm: 21.1,
    goalTime: "1:59:59",         // sub-2:00
    goalPaceSecPerKm: 341,       // 5:41 /km — must match goalTime ÷ distance
    pb: "2:08:00",               // personal best (sample)
    pbDate: "2025-10-05",
  },

  /* ------------------------------------------------ the multi-week block (arc)
   * One row per week (Mon→Sun). `km` = planned running volume; `long` = that
   * week's long run. Add a `days` array to detail a week's sessions; leave it
   * null until you're ready to write that week. */
  block: [
    {
      wk: "Wk 1", label: "Jun 29", mon: "2026-06-29", sun: "2026-07-05",
      phase: "Rebuild", km: 29, long: "16 km", focus: "Rebuild base · easy volume",
      days: [
        { day: "Mon", date: "2026-06-29", kind: "cross", title: "Cross-Training", load: "Easy", km: 0,
          detail: "45 min easy spin / bike · Z2", extra: "Keep it genuinely easy — this is recovery aerobic work." },
        { day: "Tue", date: "2026-06-30", kind: "strength", title: "Strength · Full Body", load: "Moderate", km: 0,
          detail: "Full session" },
        { day: "Wed", date: "2026-07-01", kind: "run", title: "Easy Run", load: "Easy", km: 6,
          pace: "~6:20", zone: "Z2", detail: "6 km easy · Z2",
          segments: [{ label: "Easy", val: "6 km @ ~6:20" }] },
        { day: "Thu", date: "2026-07-02", kind: "strength", title: "Strength · Full Body", load: "Moderate", km: 0,
          detail: "Full session" },
        { day: "Fri", date: "2026-07-03", kind: "run", title: "Threshold Reps", load: "Hard", km: 7,
          pace: "5:35", zone: "Z4", detail: "1.5 wu · 4×1 km @ threshold (60s jog) · 1.5 cd",
          segments: [
            { label: "Warm-up", val: "1.5 km easy" },
            { label: "Reps", val: "4×1 km @ 5:35", rest: "60s jog" },
            { label: "Cool-down", val: "1.5 km easy" },
          ] },
        { day: "Sat", date: "2026-07-04", kind: "strength", title: "Strength · Light", load: "Easy", km: 0,
          detail: "Light / mobility" },
        { day: "Sun", date: "2026-07-05", kind: "run", title: "Long Run", load: "Moderate", km: 16,
          pace: "~6:15", zone: "Z2", detail: "16 km easy · fuel @ 8 km", fuel: "gel @ 8 km",
          segments: [{ label: "Steady", val: "16 km easy @ ~6:15" }] },
      ],
    },
    { wk: "Wk 2", label: "Jul 6",  mon: "2026-07-06", sun: "2026-07-12", phase: "Build", km: 33, long: "17 km", focus: "Add a 4th easy run", days: null },
    { wk: "Wk 3", label: "Jul 13", mon: "2026-07-13", sun: "2026-07-19", phase: "Build", km: 36, long: "18 km", focus: "Threshold reps · long run grows", days: null },
    { wk: "Wk 4", label: "Jul 20", mon: "2026-07-20", sun: "2026-07-26", phase: "Build", km: 38, long: "19 km", focus: "Cruise intervals · longest run", days: null },
    { wk: "Wk 5", label: "Jul 27", mon: "2026-07-27", sun: "2026-08-02", phase: "Peak", km: 40, long: "20 km", focus: "Peak volume · race-pace work", days: null },
    { wk: "Wk 6", label: "Aug 3",  mon: "2026-08-03", sun: "2026-08-09", phase: "Taper", km: 22, long: "Race", focus: "Taper · sharpen · race day", days: null },
  ],

  /* -------------------------------------------------------------- the coach
   * `note` = current focus. `log` = adjustment feed, most-recent first. */
  coach: {
    headline: "Base is in — build volume, keep the speed.",
    note: "This is a sample plan to get you started. Point the sync at your Garmin account, then edit this plan — the race, the weekly sessions, the block arc, and these coach notes — to match your goal. The dashboard reads it live: change it, reload, done.",
    focus: ["Build weekly volume", "Add a 4th easy run", "Long run → 20 km", "Keep 2–3× strength"],
    log: [
      { date: "2026-06-29", text: "Sample entry — replace with your own coaching notes. Each entry appears in the Plan adjustments timeline, most-recent first." },
    ],
  },
};

export default planData;
