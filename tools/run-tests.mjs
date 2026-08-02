// tools/run-tests.mjs — runs the JavaScript suite.
//
//   pnpm test               → every test_*.mjs in the repo root
//   pnpm test <substr>…     → only the files whose name contains a substring
//
// Before make-mobile-native there was no `pnpm test`: 27 files were invoked by
// hand, and CI built and published an image without running any of them.
//
// Sequential by design. Most of these boot a real server on a FIXED port and
// drive a real browser; running them concurrently makes them fight over ports
// and over the machine's cores, and turns a red suite into a flaky one.

import { spawn } from "node:child_process";
import { readdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("../", import.meta.url));
const filters = process.argv.slice(2);

const files = (await readdir(ROOT))
  .filter((f) => /^test_.*\.mjs$/.test(f))
  .filter((f) => !filters.length || filters.some((q) => f.includes(q)))
  .sort();

if (!files.length) {
  console.error(filters.length ? `no test files match ${filters.join(", ")}` : "no test files found");
  process.exit(1);
}

const run = (file) => new Promise((resolve) => {
  const started = Date.now();
  const child = spawn(process.execPath, [file], {
    cwd: ROOT,
    env: { ...process.env, SYNC_ON_BOOT: "off", SYNC_AT: "off" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let out = "";
  child.stdout.on("data", (d) => (out += d));
  child.stderr.on("data", (d) => (out += d));
  child.on("close", (code) => resolve({ file, code, out, ms: Date.now() - started }));
});

const failures = [];
let i = 0;
for (const file of files) {
  i++;
  process.stdout.write(`[${String(i).padStart(2)}/${files.length}] ${file} … `);
  const r = await run(file);
  if (r.code === 0) {
    console.log(`ok (${(r.ms / 1000).toFixed(1)}s)`);
  } else {
    console.log(`FAIL exit ${r.code} (${(r.ms / 1000).toFixed(1)}s)`);
    failures.push(r);
  }
}

for (const f of failures) {
  console.log(`\n${"─".repeat(72)}\n${f.file} — exit ${f.code}\n${"─".repeat(72)}`);
  console.log(f.out.trimEnd());
}

console.log(`\n${files.length - failures.length}/${files.length} suites passed`);
process.exit(failures.length ? 1 : 0);
