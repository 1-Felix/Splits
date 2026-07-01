/* plan-io.mjs — shared, dependency-free helpers for plan sync.
 *
 * Server (serve.mjs) uses hashPlan + validatePlanText; the plan:pull / plan:push CLIs use
 * hashPlan + validatePlanText + pullPlan / pushPlan. No third-party deps. */

import { createHash } from "node:crypto";
import { writeFile, unlink } from "node:fs/promises";
import { spawn } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";

// sha-256 hex of the plan text — the content "version" both ends compare.
export function hashPlan(text) {
  return createHash("sha256").update(text, "utf8").digest("hex");
}

// Loaded in a child `node` so a throwing/looping/oversized plan can't crash the caller.
// Asserts a NAMED `planData` export (the dashboard's `import { planData }` needs it) whose
// `block` is a well-formed array of weeks (same fields validate_data.py checks), then prints
// the week count. Exit 0 = valid; nonzero + stderr = the reason.
const CHECK_SCRIPT = `
const { pathToFileURL } = await import('node:url');
try {
  const m = await import(pathToFileURL(process.env.PLAN_CHECK_FILE).href);
  const pd = m.planData;
  if (pd === undefined) throw new Error("missing a named 'export const planData' (the dashboard imports it by name)");
  if (!pd || !Array.isArray(pd.block) || pd.block.length === 0) throw new Error('planData.block must be a non-empty array');
  for (const w of pd.block) {
    for (const k of ['wk','label','mon','sun','phase','km','long','focus'])
      if (!(k in w)) throw new Error('block week ' + (w.wk || '?') + " missing '" + k + "'");
    const days = w.days;
    if (days != null && (!Array.isArray(days) || days.length !== 7))
      throw new Error('block week ' + (w.wk || '?') + ' days must be null or 7 entries');
    for (const d of (days || []))
      for (const k of ['day','date','kind','title','load','km'])
        if (!(k in d)) throw new Error((w.wk || '?') + ' ' + (d.day || '?') + " day missing '" + k + "'");
  }
  process.stdout.write(String(pd.block.length));
  process.exit(0);
} catch (e) {
  process.stderr.write(String((e && e.message) || e));
  process.exit(2);
}
`;

let _seq = 0;
// Wall-clock cap on the validator child (overridable for tests). Catches a busy-loop plan
// that keeps the event loop spinning; an unsettled top-level await is caught by node itself.
const validateTimeoutMs = () => Number(process.env.SPLITS_PLAN_VALIDATE_MS) || 5000;

// Env handed to the validator child: the temp path plus only the OS-essential vars `node`
// needs to start (Windows needs SystemRoot/PATH). Deliberately NOT process.env — the pushed
// plan's top-level code runs on import, so this keeps secrets (SPLITS_PLAN_TOKEN, GARMIN_*)
// out of reach even if the push token is misused.
const SAFE_ENV_KEYS = ["PATH", "SystemRoot", "SYSTEMROOT", "windir", "TEMP", "TMP", "TMPDIR", "HOME", "LANG", "LC_ALL"];
function childEnv(tempPath) {
  const env = { PLAN_CHECK_FILE: tempPath };
  for (const k of SAFE_ENV_KEYS) if (process.env[k] != null) env[k] = process.env[k];
  return env;
}

// Validate plan TEXT by loading it as an ES module in a short-lived, minimally-privileged
// child process (killed after VALIDATE_TIMEOUT_MS so an infinite loop can't hang the caller).
// Writes a self-cleaning temp file in the OS temp dir. Returns { ok, weeks } or { ok, error }.
export async function validatePlanText(text) {
  const tempPath = join(tmpdir(), `plan-check-${process.pid}-${_seq++}.mjs`);
  await writeFile(tempPath, text, "utf8");
  try {
    return await new Promise((resolve) => {
      const child = spawn(process.execPath, ["--input-type=module", "-e", CHECK_SCRIPT], {
        env: childEnv(tempPath),
        timeout: validateTimeoutMs(),
        killSignal: "SIGKILL",
      });
      let out = "";
      let err = "";
      child.stdout.on("data", (d) => (out += d));
      child.stderr.on("data", (d) => (err += d));
      child.on("close", (code, signal) => {
        if (code === 0) resolve({ ok: true, weeks: parseInt(out, 10) || 0 });
        // a timeout kill reports via child.killed (cross-platform) and/or a signal
        else if (child.killed || signal) resolve({ ok: false, error: "validation timed out (plan loads too slowly or loops)" });
        else resolve({ ok: false, error: (err || "invalid plan").trim() });
      });
      child.on("error", (e) => resolve({ ok: false, error: String((e && e.message) || e) }));
    });
  } finally {
    await unlink(tempPath).catch(() => {});
  }
}

// ── client (CLI) ─────────────────────────────────────────────────────────────
const base = (url) => String(url).replace(/\/+$/, "");

// Read the canonical plan from the dashboard's static route; version = its hash.
export async function pullPlan({ url }) {
  const res = await fetch(base(url) + "/plan-data.js");
  if (!res.ok) throw new Error("HTTP " + res.status);
  const text = await res.text();
  return { text, version: hashPlan(text) };
}

// Push local plan text to PUT /api/plan with the version guard.
// ifMatch = the hash last pulled; force sends If-Match:* (skip the guard).
export async function pushPlan({ url, token, text, ifMatch, force }) {
  const headers = { "Content-Type": "application/javascript" };
  if (token) headers.Authorization = "Bearer " + token;
  if (force) headers["If-Match"] = "*";
  else if (ifMatch) headers["If-Match"] = ifMatch;
  const res = await fetch(base(url) + "/api/plan", { method: "PUT", headers, body: text });
  let body = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON response */
  }
  return { status: res.status, ok: res.ok, body };
}
