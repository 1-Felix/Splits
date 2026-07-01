#!/usr/bin/env node
/* plan:pull — fetch the canonical plan-data.js from the homeserver into a local working
 * copy and record its version for a later plan:push. Config from .env / env:
 *   SPLITS_PLAN_URL   base URL of the dashboard (e.g. https://splits.l.mochii.dev) */

import "../load-env.mjs";
import { writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { pullPlan } from "../plan-io.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const url = process.env.SPLITS_PLAN_URL;
if (!url) {
  console.error("✗ SPLITS_PLAN_URL not set (add it to .env).");
  process.exit(1);
}

try {
  const { text, version } = await pullPlan({ url });
  await writeFile(join(ROOT, "plan-data.js"), text, "utf8");
  await writeFile(join(ROOT, ".plan-data.version"), version + "\n", "utf8");
  console.log(`✓ pulled plan-data.js (${Buffer.byteLength(text)} bytes) · version ${version.slice(0, 12)}…`);
} catch (e) {
  console.error("✗ pull failed:", (e && e.message) || e);
  process.exit(1);
}
