/* =============================================================================
 *  plan-data.default.js  —  SAMPLE PLAN (the shipped default / seed).
 *
 *  A generic starter plan. On first container boot the entrypoint copies it to
 *  <data volume>/plan-data.js IF that file does not already exist, then never
 *  touches it again — so replace it with your own plan and it sticks. In local
 *  dev the live plan is just `plan-data.js` next to this file.
 *
 *  THE PLAN is coach-owned (edit it in Claude Code, or by hand). `sync_garmin.py`
 *  NEVER touches the plan, so nightly telemetry syncs can't overwrite it — but
 *  it DOES read it: the sync scores every planned day against what actually
 *  happened (the dashboard's compliance marks) and briefs the coach on it.
 *
 *  STRUCTURE: the whole plan is one `block` — one row per week (Mon→Sun). Each
 *  week carries a summary (km / long / focus / phase) plus a `days` array
 *  holding that week's 7 sessions. The dashboard renders the block as the
 *  "Road to race day" panel; clicking a week loads its `days` into "THIS WEEK"
 *  (a "back to current" control returns to the live week). The current week
 *  auto-highlights from its `mon`/`sun` dates vs today.
 *
 *  THE BLOCK IS FULLY DETAILED TO RACE DAY. Every week has concrete days from
 *  day one; coaching means ADJUSTING them as reality comes in — repricing
 *  paces, swapping sessions — never authoring a week late. `days:null` on a
 *  future week is a plan-integrity gap (the coach briefing will flag it).
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
   * One row per week (Mon→Sun). `km` = planned running volume and matches that
   * week's `days` km sum (race week excludes the race itself — that's the
   * `long`). The whole arc is written out to race day; the weekly review
   * adjusts these days from actuals rather than writing them late. */
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
    {
      wk: "Wk 2", label: "Jul 6", mon: "2026-07-06", sun: "2026-07-12",
      phase: "Build", km: 33, long: "17 km", focus: "Add a 4th easy run",
      days: [
        { day: "Mon", date: "2026-07-06", kind: "run", title: "Easy Run", load: "Easy", km: 4,
          pace: "~6:30", zone: "Z2", detail: "4 km very easy — the new 4th run",
          segments: [{ label: "Easy", val: "4 km @ ~6:30" }] },
        { day: "Tue", date: "2026-07-07", kind: "strength", title: "Strength · Full Body", load: "Moderate", km: 0,
          detail: "Full session" },
        { day: "Wed", date: "2026-07-08", kind: "run", title: "Easy Run", load: "Easy", km: 6,
          pace: "~6:20", zone: "Z2", detail: "6 km easy · Z2",
          segments: [{ label: "Easy", val: "6 km @ ~6:20" }] },
        { day: "Thu", date: "2026-07-09", kind: "strength", title: "Strength · Full Body", load: "Moderate", km: 0,
          detail: "Full session" },
        { day: "Fri", date: "2026-07-10", kind: "run", title: "Threshold Reps", load: "Hard", km: 6,
          pace: "5:35", zone: "Z4", detail: "1.5 wu · 3×1 km @ threshold (60s jog) · 1.5 cd",
          segments: [
            { label: "Warm-up", val: "1.5 km easy" },
            { label: "Reps", val: "3×1 km @ 5:35", rest: "60s jog" },
            { label: "Cool-down", val: "1.5 km easy" },
          ] },
        { day: "Sat", date: "2026-07-11", kind: "strength", title: "Strength · Light", load: "Easy", km: 0,
          detail: "Light / mobility" },
        { day: "Sun", date: "2026-07-12", kind: "run", title: "Long Run", load: "Moderate", km: 17,
          pace: "~6:15", zone: "Z2", detail: "17 km easy · fuel @ 8 km", fuel: "gel @ 8 km",
          segments: [{ label: "Steady", val: "17 km easy @ ~6:15" }] },
      ],
    },
    {
      wk: "Wk 3", label: "Jul 13", mon: "2026-07-13", sun: "2026-07-19",
      phase: "Build", km: 36, long: "18 km", focus: "Threshold reps · long run grows",
      days: [
        { day: "Mon", date: "2026-07-13", kind: "run", title: "Easy Run", load: "Easy", km: 4,
          pace: "~6:30", zone: "Z2", detail: "4 km very easy" },
        { day: "Tue", date: "2026-07-14", kind: "strength", title: "Strength · Full Body", load: "Moderate", km: 0,
          detail: "Full session" },
        { day: "Wed", date: "2026-07-15", kind: "run", title: "Easy Run", load: "Easy", km: 6,
          pace: "~6:20", zone: "Z2", detail: "6 km easy · Z2" },
        { day: "Thu", date: "2026-07-16", kind: "strength", title: "Strength · Full Body", load: "Moderate", km: 0,
          detail: "Full session" },
        { day: "Fri", date: "2026-07-17", kind: "run", title: "Threshold Reps", load: "Hard", km: 8,
          pace: "5:35", zone: "Z4", detail: "1.5 wu · 5×1 km @ threshold (60s jog) · 1.5 cd",
          segments: [
            { label: "Warm-up", val: "1.5 km easy" },
            { label: "Reps", val: "5×1 km @ 5:35", rest: "60s jog" },
            { label: "Cool-down", val: "1.5 km easy" },
          ] },
        { day: "Sat", date: "2026-07-18", kind: "strength", title: "Strength · Light", load: "Easy", km: 0,
          detail: "Light / mobility" },
        { day: "Sun", date: "2026-07-19", kind: "run", title: "Long Run", load: "Moderate", km: 18,
          pace: "~6:15", zone: "Z2", detail: "18 km easy · fuel @ 8 & 14 km", fuel: "gel @ 8 & 14 km" },
      ],
    },
    {
      wk: "Wk 4", label: "Jul 20", mon: "2026-07-20", sun: "2026-07-26",
      phase: "Build", km: 38, long: "19 km", focus: "Cruise intervals · longest run",
      days: [
        { day: "Mon", date: "2026-07-20", kind: "run", title: "Easy Run", load: "Easy", km: 4,
          pace: "~6:30", zone: "Z2", detail: "4 km very easy" },
        { day: "Tue", date: "2026-07-21", kind: "strength", title: "Strength · Full Body", load: "Moderate", km: 0,
          detail: "Full session" },
        { day: "Wed", date: "2026-07-22", kind: "run", title: "Easy Run", load: "Easy", km: 6,
          pace: "~6:20", zone: "Z2", detail: "6 km easy · Z2" },
        { day: "Thu", date: "2026-07-23", kind: "strength", title: "Strength · Full Body", load: "Moderate", km: 0,
          detail: "Full session" },
        { day: "Fri", date: "2026-07-24", kind: "run", title: "Cruise Intervals", load: "Hard", km: 9,
          pace: "5:40", zone: "Z4", detail: "1.5 wu · 3×2 km @ cruise (90s jog) · 1.5 cd",
          segments: [
            { label: "Warm-up", val: "1.5 km easy" },
            { label: "Reps", val: "3×2 km @ 5:40", rest: "90s jog" },
            { label: "Cool-down", val: "1.5 km easy" },
          ] },
        { day: "Sat", date: "2026-07-25", kind: "strength", title: "Strength · Light", load: "Easy", km: 0,
          detail: "Light / mobility" },
        { day: "Sun", date: "2026-07-26", kind: "run", title: "Long Run", load: "Moderate", km: 19,
          pace: "~6:15", zone: "Z2", detail: "19 km easy — longest of the block · fuel @ 8 & 14 km",
          fuel: "gel @ 8 & 14 km" },
      ],
    },
    {
      wk: "Wk 5", label: "Jul 27", mon: "2026-07-27", sun: "2026-08-02",
      phase: "Peak", km: 40, long: "20 km", focus: "Peak volume · race-pace work",
      days: [
        { day: "Mon", date: "2026-07-27", kind: "run", title: "Easy Run", load: "Easy", km: 4,
          pace: "~6:30", zone: "Z2", detail: "4 km very easy" },
        { day: "Tue", date: "2026-07-28", kind: "strength", title: "Strength · Full Body", load: "Moderate", km: 0,
          detail: "Full session" },
        { day: "Wed", date: "2026-07-29", kind: "run", title: "Easy Run", load: "Easy", km: 5,
          pace: "~6:20", zone: "Z2", detail: "5 km easy — biggest week, keep it honest" },
        { day: "Thu", date: "2026-07-30", kind: "strength", title: "Strength · Full Body", load: "Moderate", km: 0,
          detail: "Full session" },
        { day: "Fri", date: "2026-07-31", kind: "run", title: "Goal-Pace Blocks", load: "Hard", km: 11,
          pace: "5:41", zone: "Z3–Z4", detail: "1 wu · 3×3 km @ goal pace (2 min jog) · 1 cd",
          segments: [
            { label: "Warm-up", val: "1 km easy" },
            { label: "Reps", val: "3×3 km @ 5:41", rest: "2 min jog" },
            { label: "Cool-down", val: "1 km easy" },
          ],
          extra: "The race rehearsal — lock the goal rhythm, don't bank time." },
        { day: "Sat", date: "2026-08-01", kind: "strength", title: "Strength · Light", load: "Easy", km: 0,
          detail: "Light / mobility" },
        { day: "Sun", date: "2026-08-02", kind: "run", title: "Long Run · Peak", load: "Moderate", km: 20,
          pace: "~6:15", zone: "Z2", detail: "20 km easy — the peak long run · fuel @ 7 & 14 km",
          fuel: "gel @ 7 & 14 km" },
      ],
    },
    {
      wk: "Wk 6", label: "Aug 3", mon: "2026-08-03", sun: "2026-08-09",
      phase: "Taper", km: 13, long: "Race", focus: "Taper · sharpen · race day",
      days: [
        { day: "Mon", date: "2026-08-03", kind: "run", title: "Easy Run", load: "Easy", km: 4,
          pace: "~6:30", zone: "Z2", detail: "4 km very easy" },
        { day: "Tue", date: "2026-08-04", kind: "strength", title: "Strength · Light", load: "Easy", km: 0,
          detail: "Light / mobility — last strength touch before the race" },
        { day: "Wed", date: "2026-08-05", kind: "run", title: "Easy + Strides", load: "Easy", km: 4,
          pace: "~6:20", zone: "Z2", detail: "4 km easy · 4×20 s strides after",
          segments: [
            { label: "Easy", val: "4 km @ ~6:20" },
            { label: "Strides", val: "4×20 s fast-relaxed", rest: "walk back" },
          ] },
        { day: "Thu", date: "2026-08-06", kind: "strength", title: "Rest · Mobility", load: "Easy", km: 0,
          detail: "Off. 15 min mobility if antsy — no load." },
        { day: "Fri", date: "2026-08-07", kind: "run", title: "Race-Pace Opener", load: "Easy", km: 3,
          pace: "easy + 5:41", zone: "Z2", detail: "3 km easy with 3×400 m @ race pace inside" },
        { day: "Sat", date: "2026-08-08", kind: "run", title: "Shakeout", load: "Easy", km: 2,
          pace: "~6:30", zone: "Z1", detail: "2 km very easy + 2 strides · then feet up" },
        { day: "Sun", date: "2026-08-09", kind: "run", title: "RACE — Half Marathon", load: "Hard", km: 21.1,
          pace: "5:41", zone: "Race", detail: "Settle the first 3 km, hold goal rhythm to 16, race the last 5.",
          segments: [
            { label: "Settle", val: "km 1–3 @ 5:45 — no faster" },
            { label: "Cruise", val: "km 4–16 @ 5:41" },
            { label: "Race", val: "km 17–21.1 — everything left" },
          ],
          fuel: "gel @ 7 & 14 km · drink at every station" },
      ],
    },
  ],

  /* -------------------------------------------------------------- the coach
   * `note` = current focus. `log` = adjustment feed, most-recent first. */
  coach: {
    headline: "Base is in — build volume, keep the speed.",
    note: "This is a sample plan to get you started. Point the sync at your Garmin account, then edit this plan — the race, the weekly sessions, the block arc, and these coach notes — to match your goal. Keep the whole block written out to race day and adjust it as training happens: the nightly sync scores every planned day against your actual runs and briefs the coach on what changed. The dashboard reads it live: change it, reload, done.",
    focus: ["Build weekly volume", "Add a 4th easy run", "Long run → 20 km", "Keep 2–3× strength"],
    log: [
      { date: "2026-06-29", text: "Sample entry — replace with your own coaching notes. Each entry appears in the Plan adjustments timeline, most-recent first." },
    ],
  },
};

export default planData;
