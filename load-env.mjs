/* load-env.mjs — minimal, dependency-free .env loader.
 *
 * Reads `.env` (next to this file) if present and copies each KEY=VALUE into process.env,
 * WITHOUT overriding a variable that is already set — so shell / docker-compose env always
 * wins, and a container with no `.env` is unaffected. Runs synchronously on import, so it
 * must be the FIRST import in any entry point that reads process.env at module top. */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const envPath = join(dirname(fileURLToPath(import.meta.url)), ".env");

try {
  const text = readFileSync(envPath, "utf8");
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq < 0) continue;
    const key = line.slice(0, eq).trim();
    if (!key || key in process.env) continue; // never override an already-set var
    let val = line.slice(eq + 1).trim();
    if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
      val = val.slice(1, -1);
    }
    process.env[key] = val;
  }
} catch {
  /* no .env — fine */
}
