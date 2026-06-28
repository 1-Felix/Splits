import { garminData } from "./garmin-data.js";
import { planData } from "./plan-data.js";
import { coachRead } from "./coach-read.js";

export const athleteData = { ...garminData, ...planData };

// Attach a plan-aware coach-read to each recent run that has drill-down detail.
const _maxHR = (athleteData.profile && athleteData.profile.maxHR) || 0;
athleteData.recentRuns = (athleteData.recentRuns || []).map((r) =>
  r.detail ? { ...r, read: coachRead(r, athleteData.weekPlan, _maxHR) } : r
);

export default athleteData;
