/* =============================================================================
 *  plan-data.js  —  THE PLAN. Owned by the AI coach (you, in Claude Code).
 *
 *  These are the EDITABLE coaching dials. `sync_garmin.py` NEVER touches this
 *  file, so nightly telemetry syncs can never overwrite your training plan.
 *  Edit here, reload the dashboard, done.
 *
 *  `running-data.js` merges this with `garmin-data.js` into `athleteData`.
 * ========================================================================== */

export const planData = {
  /* ------------------------------------------------------------------- race */
  race: {
    name: "Half Marathon",
    location: "Lakeside Half",
    date: "2026-08-09",
    distanceKm: 21.1,
    goalTime: "1:59:59",       // sub-2:00
    goalPaceSecPerKm: 341,     // 5:41 /km
    pb: "2:17:30",
    pbDate: "2025-04-13",
  },

  /* ----------------------------------------------------- this week's plan
   * status: "done" | "today" | "upcoming"   kind: "run" | "strength" | "cross"
   * The coach rewrites these to reshape the week.                            */
  weekPlan: [
    { day: "Mon", date: "2026-06-22", kind: "cross", title: "Spin / Bike", detail: "45 min Z2 indoor cycling", load: "Easy", status: "done", km: 0 },
    { day: "Tue", date: "2026-06-23", kind: "strength", title: "Strength · Push", detail: "Bench, OHP, dips — 4×8", load: "Moderate", status: "done", km: 0 },
    { day: "Wed", date: "2026-06-24", kind: "run", title: "Recovery Run", detail: "6 km easy · HR < 145", load: "Easy", status: "done", km: 6.2 },
    { day: "Thu", date: "2026-06-25", kind: "strength", title: "Strength · Pull", detail: "Deadlift, rows, chin-ups", load: "Moderate", status: "done", km: 0 },
    { day: "Fri", date: "2026-06-26", kind: "run", title: "Tempo Run", detail: "2 km wu · 5 km @ 5:35 · 2 km cd", load: "Hard", status: "done", km: 9.1 },
    { day: "Sat", date: "2026-06-27", kind: "strength", title: "Strength · Legs", detail: "Squat, lunges, calves", load: "Moderate", status: "today", km: 0 },
    { day: "Sun", date: "2026-06-28", kind: "run", title: "Long Run", detail: "18 km @ 6:05 · fuel @ 8/14 km", load: "Hard", status: "upcoming", km: 18 },
  ],

  /* -------------------------------------------------------------- the coach
   * `note` = current focus. `log` = adjustment feed, most-recent first.       */
  coach: {
    headline: "6 weeks out — sharpen, don't pile on.",
    note: "You're tracking ~2:03 on current fitness. To break 2:00 we need threshold pace under 5:35/km and a confident 18–20 km long run. This week holds volume but adds quality on Friday. We start the taper in week 4.",
    focus: ["Threshold pace → 5:30/km", "Long run fueling rehearsal", "Protect sleep (HRV dipped mid-week)"],
    log: [
      { date: "2026-06-26", text: "Bumped Friday tempo from 4→5 km @ 5:35 — HRV recovered, you can absorb it." },
      { date: "2026-06-22", text: "Cut Sunday long run to 18 km (was 20). Avg HR drift last week suggested under-recovery." },
      { date: "2026-06-15", text: "Added a second strength-pull day; left knee niggle resolved." },
    ],
  },
};

export default planData;
