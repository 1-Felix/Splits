#!/usr/bin/env node
/* plan:push — validate the local plan-data.js and push it to the homeserver's canonical
 * copy, guarded by the version recorded at pull time. Config from .env / env:
 *   SPLITS_PLAN_URL     base URL of the dashboard
 *   SPLITS_PLAN_TOKEN   shared secret (must match the server's)
 * Flags: --force  push without the version guard (If-Match:*). */

import "../load-env.mjs";
import { readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { pushPlan, validatePlanText, hashPlan } from "../plan-io.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const force = process.argv.includes("--force");
const url = process.env.SPLITS_PLAN_URL;
const token = process.env.SPLITS_PLAN_TOKEN;
if (!url) { console.error("✗ SPLITS_PLAN_URL not set (add it to .env)."); process.exit(1); }
if (!token) { console.error("✗ SPLITS_PLAN_TOKEN not set (add it to .env)."); process.exit(1); }

const text = await readFile(join(ROOT, "plan-data.js"), "utf8").catch(() => null);
if (text == null) { console.error("✗ no local plan-data.js to push."); process.exit(1); }

// fail fast: validate locally before the network round-trip
const v = await validatePlanText(text);
if (!v.ok) { console.error("✗ local plan is invalid:", v.error); process.exit(1); }

const ifMatch = force ? undefined : await readFile(join(ROOT, ".plan-data.version"), "utf8").then((s) => s.trim()).catch(() => null);
if (!force && !ifMatch) {
  console.error("✗ no .plan-data.version — run `pnpm plan:pull` first, or push with --force.");
  process.exit(1);
}

const r = await pushPlan({ url, token, text, ifMatch, force });
if (r.ok) {
  const version = (r.body && r.body.version) || hashPlan(text);
  await writeFile(join(ROOT, ".plan-data.version"), version + "\n", "utf8");
  console.log(`✓ pushed plan-data.js · ${(r.body && r.body.weeks) ?? "?"} weeks · version ${version.slice(0, 12)}…`);
} else if (r.status === 409) {
  console.error("✗ conflict: the canonical plan changed since your last pull.\n  Run `pnpm plan:pull`, reapply your edits, then push again (or `--force` to override).");
  process.exit(1);
} else if (r.status === 428) {
  console.error("✗ the server needs a version — run `pnpm plan:pull` first, or push with `--force`.");
  process.exit(1);
} else if (r.status === 422) {
  console.error("✗ server rejected the plan:", (r.body && r.body.error) || "invalid");
  process.exit(1);
} else if (r.status === 401) {
  console.error("✗ unauthorized — check SPLITS_PLAN_TOKEN matches the server.");
  process.exit(1);
} else if (r.status === 404) {
  console.error("✗ endpoint not found — is plan push enabled on the server (SPLITS_PLAN_TOKEN set)?");
  process.exit(1);
} else {
  console.error(`✗ push failed: HTTP ${r.status}`, (r.body && r.body.error) || "");
  process.exit(1);
}
