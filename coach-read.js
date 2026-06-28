/* coach-read.js — turns a run's stored detail + the plan into one coach sentence.
 * Pure and dependency-free so it can be unit-tested with Node and imported by
 * running-data.js. */

function fmtPace(sec) {
  if (!sec) return "—";
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function coachRead(run, weekPlan, maxHR) {
  const d = run && run.detail;
  if (!d) return "";

  const planDay = (weekPlan || []).find((w) => w.date === run.date && w.kind === "run");
  const load = planDay ? planDay.load : null;
  const type = run.type || "Run";
  const intentEasy = load === "Easy" || load === "Moderate" ||
    ["Recovery", "Long Run", "Run"].includes(type);
  const intentHard = load === "Hard" || type === "Tempo Run";

  const hrPct = maxHR ? run.hr / maxHR : 0;
  const z = d.zoneMin || [0, 0, 0, 0, 0];
  const totalMin = z.reduce((a, b) => a + b, 0) || 1;
  const drift = d.driftBpm || 0;
  const temp = d.tempC;

  if (intentEasy && hrPct >= 0.83 && temp >= 25 && drift >= 10)
    return `Easy on paper — ${temp} °C pushed HR to threshold (${run.hr} avg, +${drift} drift). Bank recovery.`;
  if (drift >= 12)
    return `Big cardiac drift (+${drift}) — heat, dehydration, or too hot a start.`;
  if (d.splitShape === "negative")
    return "Negative split — controlled, finished stronger than you started.";
  if (intentEasy && d.splitShape === "positive")
    return "Faded in the back half — ease the opening pace on easy days.";
  if (intentHard && (z[3] + z[4]) >= 0.4 * totalMin)
    return `Quality threshold work — ${z[3]} min in Z4.`;
  if (intentEasy && hrPct > 0 && hrPct <= 0.75)
    return "Properly easy — exactly the aerobic stimulus intended.";
  return `${run.km} km at ${fmtPace(run.pace)}/km, avg HR ${run.hr}.`;
}

export default coachRead;
