# Plan sync — server-canonical `plan-data.js`, B-first

**Date:** 2026-07-01
**Status:** Approved (design) — ready for implementation plan
**Author:** Felix (with Claude Code)

## Context

`plan-data.js` is the coach-owned training plan. It's authored on Felix's PC (often
with Claude Code editing it) and consumed on a self-hosted homeserver dashboard
(`splits.l.mochii.dev`). Today the plan is a gitignored file that lives independently on
each machine, so:

- there is no single authoritative copy — whatever machine last edited it "wins";
- a fresh checkout / second device has only the shipped default, not the real plan;
- the homeserver's volume copy is seeded once and never updated from the PC.

The two data files differ in nature and must be treated differently:

- `plan-data.js` — hand-authored. **This is the artifact to keep in sync.**
- `garmin-data.js` — generated from Garmin by `sync_garmin.py`; regenerable on any host.
  The homeserver already syncs it nightly, so it does not need to travel.

Felix works ~90% at his PC tower (home, on the LAN/VPN) and ~10% from a laptop while
away (only public HTTPS to the dashboard).

## Goals / Non-Goals

**Goals**
- One canonical `plan-data.js`, living on the homeserver's `/data` volume (persistent,
  already where nightly telemetry lands).
- Home (tower): edit the canonical file directly, zero ceremony — no push/pull.
- Away (laptop): a safe way to read and write the canonical plan over HTTPS.
- No accidental clobbering of a newer canonical copy.
- A bad or partial write can never corrupt the live plan.

**Non-Goals (YAGNI)**
- Live-reload of an already-open dashboard tab (refresh to see a change).
- Bidirectional auto-sync or syncing `garmin-data.js` (each host owns its telemetry).
- Multi-user / RBAC — a single shared token.
- Any change to how the coach *authors* the plan (still a plain JS module).

## Model: server-canonical, B-first

```
  canonical (single truth):  homeserver:/data/plan-data.js  (+ garmin-data.js)
  ┌───────────────────────────────────────────────────────────────────────┐
  │ HOME · PC tower (~90%)                   AWAY · laptop (~10%)           │
  │ mounts /data over LAN/VPN                no mount                       │
  │ edits the file directly (you/Claude)     plan:pull → edit → plan:push  │
  │   → writes canonical, instantly live       (API, If-Match hash guard)  │
  │ pnpm dev reads canonical via the mount   dev reads a local working copy │
  └───────────────────────────────────────────────────────────────────────┘
```

Both paths write the **same** file. The away path's conflict guard is a hash of that
file, so it is agnostic to who last wrote it (home direct-edit, or the API from any
device). That is what lets the two paths coexist safely.

## Home path (B) — the ~90%, configuration not code

Realized through infra + docs, with no new server feature:

1. Mount the homeserver's `/data` on the tower (SMB / NFS / SSHFS over LAN/VPN).
2. Make the repo see the canonical files — either:
   - **symlink** `plan-data.js` (and optionally `garmin-data.js`) in the repo to the
     mounted files, so editing `plan-data.js` as usual writes canonical transparently; or
   - run `SPLITS_DATA_DIR=<mount> pnpm dev`, so `serve.mjs` serves the plan (and telemetry)
     straight from the mount.
3. Editing the plan (Felix or Claude Code) writes the canonical file directly — the
   homeserver dashboard and local dev both reflect it on refresh.

Bonus: because `garmin-data.js` sits in the same mounted volume, local `pnpm dev` shows
**real** telemetry on the tower with no local Garmin sync. The tower is effectively always
home, so mount-availability caveats don't bite here.

## Away path (A) — the ~10%, the actual build

### Write endpoint — `PUT /api/plan` (in `serve.mjs`)
Opt-in: present only when `SPLITS_PLAN_TOKEN` is set (otherwise the route 404s, so a
self-host that doesn't opt in never exposes a write endpoint). On each request, in order:

1. **Auth** — `Authorization: Bearer <token>`, constant-time compared to
   `SPLITS_PLAN_TOKEN`; miss → **401**.
2. **Size cap** — body > ~512 KB → **413**.
3. **Version guard** — `If-Match: <hash>` compared to the hash of the *current*
   `/data/plan-data.js`; mismatch → **409** ("pull first"). Absent `If-Match` → **428**
   (precondition required) unless an explicit force header/param is set.
4. **Validate** — write the body to a uniquely-named temp file in `DATA_DIR`, then load it
   in a short-lived child `node` process (isolation — no growth of the long-lived server's
   module cache, and a throwing plan can't crash the server) and assert `planData` exists
   and `planData.block` is a well-formed array of weeks (shared validator). Invalid →
   **422** + error; the live file is untouched.
5. **Atomic write** — `rename(temp → plan-data.js)` on the same filesystem (the volume).
6. **200** `{ ok, bytes, weeks, version }` (new hash).

Reading needs no new endpoint: the existing static route already serves the canonical
`/plan-data.js` from `DATA_DIR`. The "version" is simply `hash(file)`, computed on both
ends.

### Client CLIs (used from the laptop)
- **`pnpm plan:pull`** — `GET /plan-data.js` → write the laptop's local working copy and
  record its hash in a gitignored `.plan-data.version` sidecar.
- **`pnpm plan:push`** — read local `plan-data.js`; locally validate (fail fast, no
  network); `PUT /api/plan` with `If-Match` = the recorded sidecar hash. On **409** →
  advise `plan:pull`; on **422** → show the validation error; on **200** → update the
  sidecar to the new hash. `--force` sends without `If-Match` for the rare override.
- The laptop's `pnpm dev` reads its local working copy — works offline.

## Components

New / changed files:

- `serve.mjs` — add the `PUT /api/plan` handler (auth, version guard, size cap, validate,
  atomic write); add a small `.env` loader so PC-side env (token/URL) is picked up without
  overriding shell/compose env.
- shared, dependency-free helpers (exact module layout decided in the plan): `hashPlan(text)`
  (sha-256 hex), `validatePlanText(text)` (via the child-process load above), and the client
  `pushPlan` / `pullPlan`.
- `scripts/plan-pull.mjs`, `scripts/plan-push.mjs` — the two CLIs.
- `package.json` — `plan:pull`, `plan:push` scripts; optional `dev:home` convenience.
- `.env.example`, `README.md` — new env vars + the home-mount setup + the away workflow.
- `.gitignore` — `.plan-data.version` sidecar.
- Tests — `test_plan_validate.mjs`, `test_plan_push.mjs` (see Testing).

## Data flow

**Home (direct):** edit mounted `plan-data.js` → canonical updated → dashboard(s) reflect
on refresh. No protocol.

**Away (pull / edit / push):**
```
laptop  --GET /plan-data.js-->  server        (plan:pull; record hash h0)
edit locally
laptop  --PUT /api/plan If-Match: h0 + body-->  server
        server: hash(current) == h0 ?  yes -> validate -> atomic write -> 200 {version: h1}
                                        no  -> 409 (canonical changed; pull first)
```

## Auth & trust model

The plan is executed as an ES module by the dashboard and Node, so a push writes
**runnable code**. The token is the gate: whoever holds it can run code in the server's
context — equivalent to editing the volume file. Therefore:

- HTTPS only (the bearer token travels in the header);
- treat `SPLITS_PLAN_TOKEN` like a password;
- the endpoint is opt-in (absent token → no endpoint).

This is acceptable for a single-user self-host where the token holder already controls the
server.

## Error handling

| Status | When |
|---|---|
| 401 | missing/wrong bearer token |
| 404 | endpoint disabled (`SPLITS_PLAN_TOKEN` unset) |
| 409 | `If-Match` doesn't match current canonical hash (stale — pull first) |
| 413 | body exceeds the size cap |
| 422 | body fails validation (not a loadable plan / bad `block`) — live file untouched |
| 428 | `If-Match` absent and not forced |
| 200 | written; returns new `version` |

## Config

| Var | Where | Purpose |
|---|---|---|
| `SPLITS_PLAN_TOKEN` | homeserver **and** laptop | shared secret — server accepts it, client presents it; enables the endpoint |
| `SPLITS_PLAN_URL` | laptop | base URL of the dashboard (e.g. `https://splits.l.mochii.dev`) |

`.env` is loaded without overriding already-set vars, so shell / docker-compose env wins.

## Testing

- `test_plan_validate.mjs` — valid and invalid plan shapes (missing `block`, non-array,
  malformed week, minimal-but-valid day).
- `test_plan_push.mjs` — boot `serve.mjs` on a temp `DATA_DIR`; exercise `PUT /api/plan`:
  disabled→404, no/wrong token→401, oversized→413, stale `If-Match`→409, missing
  `If-Match`→428, bad plan→422 (live file byte-for-byte untouched), good plan→200 (file
  updated, atomic, new version returned). A round-trip `plan:pull` → edit → `plan:push`
  happy path.

## Open questions

None blocking. The home-side wiring choice (symlink vs `SPLITS_DATA_DIR`) is an
operational detail to settle during setup, not a code decision.
