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
 *  TIP: add a `date: "YYYY-MM-DD"` to each weekPlan row and the dashboard will
 *  auto-highlight "today" and roll the week over on its own; without dates it
 *  falls back to the `status` flags below. The block's `mon`/`sun` dates drive
 *  the current-week highlight the same way.
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

  /* ----------------------------------------------------- this week's plan
   * status: "done" | "today" | "upcoming"   kind: "run" | "strength" | "cross"
   * Add a `date: "YYYY-MM-DD"` per row to switch to automatic day highlighting. */
  weekPlan: [
    { day: "Mon", kind: "cross",    title: "Cross-Training",       detail: "45 min easy spin / bike · Z2",                    load: "Easy",     status: "done",     km: 0 },
    { day: "Tue", kind: "strength", title: "Strength · Full Body", detail: "Full session",                                    load: "Moderate", status: "done",     km: 0 },
    { day: "Wed", kind: "run",      title: "Easy Run",             detail: "6 km easy · Z2",                                  load: "Easy",     status: "today",    km: 6 },
    { day: "Thu", kind: "strength", title: "Strength · Full Body", detail: "Full session",                                    load: "Moderate", status: "upcoming", km: 0 },
    { day: "Fri", kind: "run",      title: "Threshold Reps",       detail: "1.5 wu · 4×1 km @ threshold (60s jog) · 1.5 cd",  load: "Hard",     status: "upcoming", km: 7 },
    { day: "Sat", kind: "strength", title: "Strength · Light",     detail: "Light / mobility",                                load: "Easy",     status: "upcoming", km: 0 },
    { day: "Sun", kind: "run",      title: "Long Run",             detail: "16 km easy · fuel @ 8 km",                        load: "Moderate", status: "upcoming", km: 16 },
  ],

  /* ------------------------------------------------ the multi-week block (arc)
   * One row per week (Mon→Sun). The dashboard's "Road to race day" panel renders
   * this; with real `mon`/`sun` dates the current week auto-highlights vs today.
   * `km` = planned running volume for the week; `long` = that week's long run. */
  block: [
    { wk: "Wk 1", label: "Jun 29", mon: "2026-06-29", sun: "2026-07-05", phase: "Rebuild", km: 29, long: "16 km", focus: "Rebuild base · easy volume" },
    { wk: "Wk 2", label: "Jul 6",  mon: "2026-07-06", sun: "2026-07-12", phase: "Build",   km: 33, long: "17 km", focus: "Add a 4th easy run" },
    { wk: "Wk 3", label: "Jul 13", mon: "2026-07-13", sun: "2026-07-19", phase: "Build",   km: 36, long: "18 km", focus: "Threshold reps · long run grows" },
    { wk: "Wk 4", label: "Jul 20", mon: "2026-07-20", sun: "2026-07-26", phase: "Build",   km: 38, long: "19 km", focus: "Cruise intervals · longest run" },
    { wk: "Wk 5", label: "Jul 27", mon: "2026-07-27", sun: "2026-08-02", phase: "Peak",    km: 40, long: "20 km", focus: "Peak volume · race-pace work" },
    { wk: "Wk 6", label: "Aug 3",  mon: "2026-08-03", sun: "2026-08-09", phase: "Taper",   km: 22, long: "Race",  focus: "Taper · sharpen · race day" },
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
