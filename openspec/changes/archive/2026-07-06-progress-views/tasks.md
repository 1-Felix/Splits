# Tasks: progress-views (stage 3a)

## 1. Sequencing & runtime baseline

- [x] 1.1 Confirm the three in-flight changes (activity-archive, insight-metrics, coach-loop) passed the 2026-07-06 nightly check and are archived — this change's deltas land on top of them — nightly green (536 activities, distilled 162/162, schema v4, Wk 2 closed 7/7, Wk 3 open, briefing refreshed 04:01), all three archived 2026-07-06
- [x] 1.2 Bump Dockerfile base to `node:24-bookworm-slim`; add `engines.node >= 24` to package.json; verify local Node ≥ 24 (or note the degraded-API caveat for dev) — local is 22.19, but `node:sqlite` is present (experimental) so the archive API works in dev with a warning

## 2. Archive: distilled detail (schema v4, design D5)

- [x] 2.1 Refactor `fetch_run_detail` in sync_garmin.py so the distillation core is a pure function over a raw detail payload (one distiller, two callers: fresh-fetch path and stored-payload path), with a test asserting both paths produce identical output for the same run
- [x] 2.2 Schema v4 in activity_archive.py: additive `activities.detail_distilled_json` column via the existing idempotent migration pattern; bump SCHEMA_VERSION
- [x] 2.3 Sync writes distilled detail whenever a run's raw detail is archived (append and top-up paths), inside the existing fail-soft wrapper
- [x] 2.4 Recovery pass distills already-archived runs from stored raw payloads (no network), idempotent and re-runnable; wire it to run automatically when undistilled runs exist
- [x] 2.5 Extend `--verify-archive` to report distilled coverage vs raw-detail coverage, exit non-zero on regression
- [x] 2.6 Tests in test_activity_archive.py: migration additivity (old reader ignores column), distill-on-topup, recovery pass, raw payloads untouched, verify regression detection; run the recovery pass against the local archive and verify 158/158 — local copy now holds 162 detailed runs (158 `running` + 4 treadmill/trail); 162/162 distilled, verify green

## 3. Insight metrics: byYear + yoy (design D4)

- [x] 3.1 `insight_metrics.py`: per-calendar-year best-effort tables (`bestEfforts.byYear`) reusing the existing outdoor-only `best_effort_table` logic, entries carrying time, date, and activityId; null for uncovered distances — `best_effort_table` itself gained `activityId` (all wall records click through, not just by-year)
- [x] 3.2 `insight_metrics.py`: `insights.yoy` — per-year monthly distance/run-count/avg-pace over promoted columns, zero count/distance + null pace for empty months, only elapsed months for the current year
- [x] 3.3 `validate_data.py`: shape-check `bestEfforts.byYear` and `yoy` when present; pre-3a insights blocks stay valid
- [x] 3.4 Tests in test_insight_metrics.py: year slicing, treadmill exclusion in year tables, yoy sums match archive fixtures, empty-month honesty, validation of malformed members

## 4. Archive API in serve.mjs (designs D3, D6, D10)

- [x] 4.1 Archive DB access helper: lazy `node:sqlite` import (no driver → 503 path, server always boots), per-request read-only open/close, SQLITE_BUSY and missing-file → 503 JSON body; archive path from `SPLITS_ARCHIVE_DIR` falling back to DATA_DIR
- [x] 4.2 `GET /api/archive/activities`: promoted-column rows, filters (type, year, from/to), newest-first, clamped page size + offset/cursor, method guard
- [x] 4.3 `GET /api/archive/activities/:id`: promoted summary + stored `detail_distilled_json` verbatim (null when absent), 404 unknown id, raw `summary_json`/`detail_json` never serialized into any response
- [x] 4.4 New test_archive_api.mjs (patterned on test_plan_push.mjs): list filters/pagination/clamp, id happy path + 404 + null-detail, method rejection, 503 on missing DB, response shape equals the recent-run detail contract, no-writes assertion (db bytes unchanged) — plus SPLITS_ARCHIVE_DIR override coverage and a smoke against the real local archive

## 5. Multi-page shell (designs D7, D8)

- [x] 5.1 Route map in serve.mjs: `/` → cockpit page, `/progress` → progress.dc.html, served directly; old `/Running%20Dashboard.dc.html` path still serves; 404 behavior for unknown clean routes unchanged
- [x] 5.2 New `topbar.js`: theme registry + `localStorage` persistence (`splits.theme`, applied at component init — no default-theme flash), sync-pill state machine (`/api/status` + `POST /api/sync`), greeting, nav model with current-page marking — loaded as a deferred head module so `window.SplitsTopbar` exists before the DOMContentLoaded mount
- [x] 5.3 Wire the cockpit component to topbar.js (behavior only — markup stays in-component); confirm theme now survives reload on the cockpit — verified headless: pick `track` → reload → stored key, ring, and track background all present
- [x] 5.4 test_topbar.mjs: theme persistence round-trip, default-when-unset, nav model current-page logic

## 6. The /progress page (progress-views spec)

- [x] 6.1 Create progress.dc.html: page skeleton with topbar (nav marking Progress), theme wiring, responsive grid per dashboard.css tokens
- [x] 6.2 Relocate from the cockpit component: THE LONG GAME (weekly volume), the monthly chart grid (VO₂ · pace · fitness/fatigue · cadence · pace@HR · cadence@ref-pace), and the records feed — markup + component logic + hover/keyboard behavior intact, insight-absent degradation preserved (HR-zones + sleep cards are this-week surfaces and stay on the cockpit)
- [x] 6.3 Records wall: all-time / last-90d / by-year grid over 1k · mile · 5k · 10k · half from the static insights block; explicit empty cells for uncovered distances; renders fully with the API down — verified headless with a post-3a fixture built offline from the local archive
- [x] 6.4 Year-over-year view from `insights.yoy`: side-by-side years, monthly distance/count/pace, not-yet months distinct from zero months, existing hover interaction pattern
- [x] 6.5 Record click-through: fetch `/api/archive/activities/:id`, render the established drill-down (coach-read line, splits, HR) for any archived run; "archive offline" state on 503/failure without breaking the page — verified headless against the real archive (drill-down) and an empty archive dir (offline state)

## 7. Cockpit diet (design D9)

- [x] 7.1 Remove the relocated sections from Running Dashboard.dc.html — subtractive only; retained sections (hero, KPIs, THIS WEEK, block panel, heatmap, recent runs) untouched in wiring — HR-zones + sleep cards stay in the (now 2-card) chart grid; hero trajectory row stays
- [x] 7.2 Verify the cockpit renders complete with every `/api/*` route failing (static-file resilience scenario) — verified headless with all `/api/*` aborted: every retained section renders real data, zero page errors

## 8. Verification, docs, roadmap

- [x] 8.1 Extend tools/style-audit.mjs: layout assertions for `/progress` at 1200/768/390 px and a topbar computed-style parity check between pages; run green on both pages — also added page-level no-horizontal-overflow checks (caught + fixed a 390 px topbar overflow via the new `.topbar-actions` class)
- [x] 8.2 Full local pass: python test suites, all .mjs tests, `python validate_data.py`, `openspec validate progress-views` — all green
- [x] 8.3 README: multi-page structure, archive API endpoints + read-only/fail-soft posture, `SPLITS_ARCHIVE_DIR` for dev-against-mount (SQLite-over-SMB unsupported), Node 24 requirement, security note extended to the archive endpoints
- [x] 8.4 ROADMAP.md: record the rescoped golden rule (cockpit static / views may use the read API), split stage 3 into 3a/3b/3c, mark 3a shipped when deployed — marked "built 2026-07-05"; flips to shipped after 9.x

## 9. Deploy & live verification

- [x] 9.1 Merge to main → CI publishes the image; pull on the homeserver and recreate the container — commit `087345b`, CI green, container recreated on Node v24.18.0 (2026-07-05 ~21:35)
- [x] 9.2 First server sync: confirm schema v4 applied, distillation pass covered all archived runs (`--verify-archive` in the container), insights block carries byYear + yoy — schema 4, distilled 162/162, verify passed; served garmin-data.js carries byYear/yoy/activityId
- [x] 9.3 Live smoke over the LAN: cockpit slim and complete, `/progress` renders all views, theme persists across pages, a pre-2026 record click-through opens its run's drill-down from the archive — all green headless against 192.168.0.37:5732 (1K · 5:32 on 2025-09-17 opened from the archive)
