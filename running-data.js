/* running-data.js — merges telemetry (garmin-data.js, sync-owned) and the plan
 * (plan-data.js, coach-owned) into `athleteData`. The plan spread is last so any
 * coaching dial (weekPlan, race, coach) always wins over telemetry on key collisions. */
import { garminData } from "./garmin-data.js";
import { planData } from "./plan-data.js";
import { coachRead } from "./coach-read.js";
import { migrateLegacyPlan } from "./plan-migrate.js";

export const athleteData = { ...garminData, ...planData };

// Upgrade a legacy plan in place: a self-host volume seeded before the block carried
// per-week `days` still holds top-level weekPlan/nextWeekPlan + a block without days, and
// the entrypoint never overwrites it. Map that onto block[i].days so it renders as day cards.
migrateLegacyPlan(athleteData);

// The plan lives as block[i].days now. Flatten every detailed day into one list so
// coach-read can match a run to its planned day even when the run is from an earlier
// week, and any legacy `weekPlan` consumer keeps working. (Which week is "current" is
// a live-clock question, so the dashboard derives the active week itself from block dates.)
athleteData.weekPlan = (athleteData.block || []).flatMap((w) => w.days || []);

// Attach a plan-aware coach-read to each recent run that has drill-down detail.
const _maxHR = (athleteData.profile && athleteData.profile.maxHR) || 0;
athleteData.recentRuns = (athleteData.recentRuns || []).map((r) =>
  r.detail ? { ...r, read: coachRead(r, athleteData.weekPlan, _maxHR) } : r
);

export default athleteData;
