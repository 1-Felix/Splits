## 1. Shared helpers (dependency-free, testable)

- [x] 1.1 Add a `hashPlan(text)` helper (sha-256 hex of the plan text) used by both server and client for the content version. (`plan-io.mjs`)
- [x] 1.2 Add a `validatePlanText(text)` helper that loads the text as a plan in a short-lived child `node` process and asserts `planData.block` is a well-formed array of weeks (block/day fields match `validate_data.py`). Returns `{ ok, weeks }` or `{ ok:false, error }`. (`plan-io.mjs`)
- [x] 1.3 Add a tiny `.env` loader that reads `.env` if present and sets only keys not already in `process.env` (shell/compose env wins; container without `.env` unaffected). (`load-env.mjs`)

## 2. Server — `PUT /api/plan`

- [x] 2.1 In `serve.mjs`, read `SPLITS_PLAN_TOKEN`; when unset the route is gated off and falls through to the static handler (404). Load `.env` first via the no-override loader.
- [x] 2.2 Auth: require `Authorization: Bearer <token>`, constant-time compared → 401 on miss.
- [x] 2.3 Size cap: reject bodies over 512 KB → 413 (drain-then-reject so the response is sent cleanly).
- [x] 2.4 Version guard: compare `If-Match` to `hashPlan(current plan-data.js)` → 409 on mismatch; 428 when `If-Match` is absent; `If-Match: *` forces.
- [x] 2.5 Validate: run `validatePlanText` on the body → 422 + error on failure (live file untouched).
- [x] 2.6 Atomic write: write a temp in `DATA_DIR`, `rename` → `plan-data.js`; respond 200 `{ ok, bytes, weeks, version }`.
- [x] 2.7 Reading stays on the existing static `/plan-data.js` route (no `GET /api/plan` added).

## 3. Client CLIs

- [x] 3.1 `pushPlan` / `pullPlan` helpers in `plan-io.mjs`: `pullPlan` = `GET /plan-data.js` (version = hash); `pushPlan` = `PUT /api/plan` with `If-Match` + bearer token.
- [x] 3.2 `tools/plan-pull.mjs` (`pnpm plan:pull`): fetch canonical → write local `plan-data.js` → record its hash in the gitignored `.plan-data.version` sidecar.
- [x] 3.3 `tools/plan-push.mjs` (`pnpm plan:push`): validate locally (fail fast), push with `If-Match` = sidecar hash; on 200 update the sidecar; distinct messages for 409/428/422/401/404; `--force` sends `If-Match:*`.
- [x] 3.4 `package.json`: add `plan:pull`, `plan:push`. (`dev:home` left as a documented `SPLITS_DATA_DIR=<mount> pnpm dev` command in the README rather than a script — avoids a cross-platform env-setting dependency.)

## 4. Config, ignore, docs

- [x] 4.1 `.env.example`: document `SPLITS_PLAN_TOKEN` (both ends) and `SPLITS_PLAN_URL` (client).
- [x] 4.2 `.gitignore`: ignore `.plan-data.version`.
- [x] 4.3 `README.md`: add "Keeping your plan in sync" — the home-mount path (edit the file directly; real-telemetry-in-dev bonus) and the away path (opt-in token, pull/edit/push), plus the trust model and a config-knobs row.

## 5. Tests

- [x] 5.1 `test_plan_validate.mjs`: valid (summary-only + detailed weeks), minimal valid, and invalid cases (missing `block`, non-array, week missing a field, days ≠ 7, day missing a field, syntax error); plus `hashPlan` stability/sensitivity.
- [x] 5.2 `test_plan_push.mjs`: boot `serve.mjs` on a temp `DATA_DIR` and exercise `PUT /api/plan` — disabled→404, no/wrong token→401, POST→405, oversized→413, missing `If-Match`→428, stale→409, bad plan→422 (live file byte-for-byte unchanged), good plan→200 (updated, atomic, new version), and `If-Match:*` force→200.

## 6. Verify

- [x] 6.1 Ran the full suite — new `test_plan_validate.mjs` + `test_plan_push.mjs` and existing `test_coach_read.mjs`, `test_plan_migrate.mjs`, `validate_data.py`, `test_run_detail.py` all pass; the endpoint is confirmed absent (404) when `SPLITS_PLAN_TOKEN` is unset. `node --check` clean on the new modules.
