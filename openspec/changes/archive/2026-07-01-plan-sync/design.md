## Context

`plan-data.js` is coach-owned and consumed by the dashboard (`serve.mjs` serves the data
files from `DATA_DIR`; the container mounts a `/data` volume, the entrypoint seeds the plan
once). Telemetry (`garmin-data.js`) is generated per host and out of scope. Felix works
~90% at a home PC tower (LAN/VPN) and ~10% from a laptop (public HTTPS only).

The full design is `docs/superpowers/specs/2026-07-01-plan-sync-design.md`; this captures
the key decisions.

## Goals / Non-Goals

**Goals:** one canonical plan on the homeserver; zero-ceremony home editing; a safe
read/write path from away; no clobbering a newer canonical; no corruption from a bad write.

**Non-Goals:** live-reload of an open dashboard; bidirectional/telemetry sync; multi-user;
any change to how the plan is authored.

## Decisions

### D1 — Server-canonical, B-first
The single source of truth is `<data volume>/plan-data.js`. Home edits it directly through
a mounted volume (no protocol); away uses the API. Both target the same file, so a
content-hash version reconciles them regardless of which path wrote last.
- **Alternative rejected:** PC-authoritative push (two copies, PC wins) — a fresh device
  never has the real plan, and the server copy can drift.

### D2 — Home path is configuration, not a feature
Mount `/data` on the tower and either symlink the repo's `plan-data.js` to the mounted file
or run `SPLITS_DATA_DIR=<mount> pnpm dev`. Editing the file writes canonical; local dev
reads canonical (and real telemetry) from the mount. Shipped as README docs only.

### D3 — Away write endpoint: `PUT /api/plan`, opt-in + guarded
Enabled only when `SPLITS_PLAN_TOKEN` is set (else 404 — no endpoint exposed by default).
Per request: bearer-token auth (constant-time) → size cap (Content-Length fast-reject +
streaming fallback) → `If-Match` content-hash guard (mismatch → 409; absent → 428 unless
forced) → validate → atomic write → 200 with the new version. The guard-to-write section is
**serialized behind a mutex**, so concurrent pushes can't interleave (no TOCTOU lost-update)
and at most one validator child runs at a time. Reading reuses the existing static
`/plan-data.js` route; the version is `hash(file)`, computed on both ends, so no
`GET /api/plan` is needed.
- **Alternative rejected:** last-write-wins with no guard — silently clobbers a newer
  canonical when the laptop pushes a stale edit.

### D4 — Validate in a child process, then atomic write
Load the pushed text in a short-lived child `node` process and assert a NAMED `planData`
export (the dashboard's `import { planData }` requires it) whose `block` is a well-formed
array of weeks. Invalid → 422, live file untouched. Valid → `rename(temp → plan-data.js)`
(atomic on the same filesystem); the temp is unlinked if the rename fails.
- **Why child process:** a throwing/looping/huge plan can't crash the long-lived server.
- **Hardening (from review):** the child runs with a **minimal env allow-list** (only the
  OS-essential vars `node` needs to start — never `process.env`), so a pushed plan's
  top-level code can't read secrets (`SPLITS_PLAN_TOKEN`, `GARMIN_*`); and a **kill-timeout**
  bounds a busy-loop plan (an unsettled top-level await is caught by node itself).
- **Alternative rejected:** in-process `import()` — executes pushed code in the server and
  accumulates cached modules.

### D5 — Client tracks the pulled hash in a sidecar
`plan:pull` writes the working copy and records the fetched hash in a gitignored
`.plan-data.version`. `plan:push` validates locally (fail fast), then sends `If-Match` =
that hash; on 200 it updates the sidecar; on 409 it advises pulling; `--force` omits
`If-Match`. Reads use `GET /plan-data.js`.

### D6 — Config via `.env`, no-override loader
`SPLITS_PLAN_TOKEN` (server accepts + client presents) and `SPLITS_PLAN_URL` (laptop
target). A tiny dependency-free loader reads `.env` if present but never overrides
already-set vars, so shell/compose env still wins and the container (no `.env`) is
unaffected.

## Risks / Trade-offs

- **[Pushed plan is runnable code]** → token-gated + HTTPS + opt-in; the trust model is
  documented (token holder ≈ can edit the volume file). Acceptable for single-user self-host.
- **[Home edit via non-atomic editor save]** → rely on editors' atomic save (VS Code/vim);
  the dashboard reads on load, so a mid-save partial read is rare and self-correcting.
- **[Two write paths]** → reconciled by the content-hash guard; the guard keys off the
  canonical file, so it catches a home edit exactly like an away edit from another device.
- **[Away edit while mount changed canonical]** → 409 forces a pull; no silent clobber.

## Migration Plan

Purely additive. No data migration. Endpoint is off until `SPLITS_PLAN_TOKEN` is set;
existing deployments are unaffected until they opt in and (optionally) set up the mount.

## Open Questions

None blocking. Home-side wiring (symlink vs `SPLITS_DATA_DIR`) is an operational choice
settled at setup, documented both ways.
