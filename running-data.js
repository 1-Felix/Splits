/* =============================================================================
 *  running-data.js  —  THE CONTRACT. This is the only file the dashboard imports.
 *
 *  It merges two sources, each with a single owner so they can never clobber
 *  each other (see CLAUDE_CODE_HANDOFF.md §5.4):
 *
 *    • garmin-data.js  →  telemetry, OVERWRITTEN by sync_garmin.py   (FROM GARMIN)
 *    • plan-data.js    →  race / weekPlan / coach, hand-edited       (EDITABLE)
 *
 *  The plan is spread last, so a coaching dial always wins over telemetry if a
 *  key ever collides. To wire real data: fill in sync_garmin.py and run it —
 *  garmin-data.js updates, and the dashboard picks it up on reload.
 * ========================================================================== */

import { garminData } from "./garmin-data.js";
import { planData } from "./plan-data.js";

export const athleteData = { ...garminData, ...planData };

export default athleteData;
