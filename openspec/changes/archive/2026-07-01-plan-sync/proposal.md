## Why

`plan-data.js` (the coach-owned training plan) is authored on the PC but consumed on the
self-hosted homeserver dashboard, and today it lives as an independent gitignored file on
each machine — so there is no single authoritative copy, a fresh device only has the
shipped default, and the homeserver's volume copy (seeded once) never picks up PC edits.
We want one canonical plan on the homeserver, edited directly at home and safely
read/written from a laptop when away. (`garmin-data.js` is generated per host and is out
of scope.)

Full design: `docs/superpowers/specs/2026-07-01-plan-sync-design.md`.

## What Changes

- **Canonical plan on the homeserver.** The single source of truth is
  `<data volume>/plan-data.js`. Two paths reach it, unified by a content-hash version:
- **Home path (B) — config/docs, no core code.** The PC tower mounts the `/data` volume
  (SMB/NFS/SSHFS) and edits the canonical file directly (via a symlink or by pointing
  `SPLITS_DATA_DIR` at the mount); edits are instantly live. Local `pnpm dev` then also
  reads the canonical plan and real telemetry from the mount. Documented in the README.
- **Away path (A) — the build.** Add an **opt-in** `PUT /api/plan` to `serve.mjs`
  (enabled only when `SPLITS_PLAN_TOKEN` is set): bearer-token auth, an `If-Match`
  content-hash **version guard** (stale → 409), a body size cap, **validation in a
  short-lived child `node` process**, and an **atomic write** (temp + rename). Reading
  reuses the existing static `/plan-data.js` route.
- **Client CLIs.** `pnpm plan:pull` (fetch canonical → local working copy + record its
  hash) and `pnpm plan:push` (validate locally, then `PUT` with `If-Match`; handle
  409/422/401; `--force` to override the guard).
- **Config.** New env vars `SPLITS_PLAN_TOKEN` (both ends) and `SPLITS_PLAN_URL` (laptop),
  loaded from `.env` without overriding shell/compose env. Update `.env.example`.
- **Safety.** Opt-in endpoint, HTTPS-only bearer token, validate-before-write so a bad
  push never touches the live file, atomic replacement.

## Capabilities

### New Capabilities
- `plan-sync`: keep the coach-owned plan as one canonical copy on the homeserver — editable
  directly at home via a mounted volume, and readable/writable from elsewhere via an
  opt-in, token-authed, version-guarded push/pull over HTTPS.

### Modified Capabilities
<!-- none — telemetry sync (dashboard-sync) and the volume seed (containerized-deployment)
     are unchanged; this is an additive capability. -->

## Impact

- **`serve.mjs`** — new `PUT /api/plan` handler; a small `.env` loader (no-override) so
  PC-side env is picked up.
- **New client code** — `plan:pull` / `plan:push` scripts + shared dependency-free helpers
  (`hashPlan` sha-256, `validatePlanText` via child-process load, `pushPlan`/`pullPlan`).
- **`package.json`** — `plan:pull`, `plan:push` scripts (optional `dev:home`).
- **`.env.example`, `README.md`** — new env vars, the away workflow, and the home-mount setup.
- **`.gitignore`** — the `.plan-data.version` sidecar the CLIs use to track the pulled hash.
- **Tests** — `test_plan_validate.mjs` and `test_plan_push.mjs`.
- No change to telemetry sync, the volume seed-once behavior, or how the plan is authored.
