# HANDOFF — add-ingest-archive

The OpenSpec artifacts (`proposal.md` / `design.md` / `specs/**` / `tasks.md`)
are the source of truth; this doc is orientation + operational knowledge that
isn't in them. Last updated 2026-07-17.

## TL;DR

Ingest-fed instances (Max's) now write a **real `activity-archive.db`** —
**two producers, one schema, one read window**: `ingest_builder.py` gained an
archive pass that upserts every banked Health Connect run into the same
schema `sync_garmin.py` writes (`activity_archive.ensure/open_archive` owns
the DDL for both), on the instance's own volume. `serve.mjs` and the pages
needed **zero changes** — the 2026-07-17 instance-aware chrome auto-reverses
via `/api/status`'s `archive` flag the moment the file exists, lighting up
/archive, /run/:id, /compare, the cockpit heatmap day-drill, and the progress
drill panels.

The ingest archive is a **disposable derived cache**: delete the file and the
next build regenerates it completely from `ingested-runs.json`, with identical
ids (stable 48-bit sha256-derived ids from session UIDs, collision-checked
with a deterministic salted rehash).

## What the archive pass writes (per banked run)

- **activities row**: promoted columns (`start_time_local`, `type_key`
  running/treadmill_running, `distance_m`, `duration_s`, `avg_hr`, `max_hr`);
  `summary_json` = the banked payload VERBATIM (sessionUid recoverable);
  `name`/`avg_cadence`/`elevation_gain_m`/`detail_json` stay NULL — honest
  absence. Unchanged rows are skipped so `updated_at` never churns.
- **`detail_streams_json`**: columnar streams synthesized from the banked
  samples — `t` (union of HR/speed sample times), `hr`, `v`, `d` (integrated
  from `v`, pause-capped, normalized to the banked distance). Absent metrics
  (cad/elev/gap/pwr/lat/lon/pc) are OMITTED keys → the run page's existing
  degradations (no basemap, no cadence chart) apply untouched. No speed
  series → no streams (no honest distance axis).
- **`detail_distilled_json`**: the builder's own `run_detail()` — the SAME
  function that fills `recentRuns[].detail`, so cockpit card and archive page
  are structurally identical (parity-tested).
- **`run_metrics`**: `insight_metrics.best_efforts()` + `band_aggregates()`
  over the synthesized samples dict (`_metric_samples`; cadence always None →
  refpace pools honestly empty), upserted at METRICS_VERSION.

## Versioning / idempotency

- `archive_meta.ingest_distill_version` (constant `INGEST_DISTILL_VERSION` in
  ingest_builder.py) — bump when `synth_streams` or the distilled derivation
  changes shape; the next build recomputes every run's streams + detail.
- Metrics self-heal on `insight_metrics.METRICS_VERSION` bumps, exactly like
  the Garmin pipeline.
- Steady state is write-once: a second build with no new runs is a byte-level
  no-op (tested, including `updated_at`/`computed_at` stability).
- Zero banked runs → NO db is created (a fresh instance stays "not
  provisioned", archive chrome hidden, until the first run lands).
- The pass soft-fails: an archive error logs loudly but never sinks the
  telemetry build.

## Tests (all green 2026-07-17, full suite: 7 Python + 20 Node files)

- `test_ingest_builder.py` — new archive section: samples-dict parity pin
  (Garmin `read_stream` vs ingest synthesis feeding the same pure engines),
  id derivation/collision, schema parity vs a Garmin-created db, promoted
  columns + verbatim summary, streams axis/normalization/omitted keys,
  distilled==cockpit parity, metrics rows, idempotency/version-bump/self-heal,
  zero-runs-no-db.
- `test_ingest_e2e.mjs` — pushed run → db exists, `/api/archive/activities`,
  `/activities/:id`, `/:id/streams`, `/run-metrics` all serve it.
- `test_slim_render.mjs` — slim fixture now HAS an archive: `archive:true`,
  Archive nav + heatmap drill BACK (drill navigates to `/run/<derived id>`),
  /archive lists both runs, /run renders charts in no-basemap mode, /compare
  renders with an honest no-streams note. The no-archive shape (404, hidden
  chrome, "No archive on this instance") moved to the Garmin-shaped fullDir.
- Stale-test cleanup while proving 4.4: `test_archive_api.mjs` missing-db
  assertions updated 503→404 (the 2026-07-17 contract this change's
  archive-api delta records); `test_{archive,run,compare}_page.mjs` outage
  fixtures now plant a CORRUPT db (present-but-unopenable = real 503) instead
  of a missing file.

## Deploy notes (NUC)

Ships in the normal image; no compose/env changes. Max's next ingest (or
container boot — boot runs the builder on ingest instances) writes the db on
`splits-max-data` → `archive: true` → surfaces auto-reveal. Felix's instance
untouched (`ingestFed:false`, archive already true). Rollback: previous image
+ delete `activity-archive.db` from the ingest volume (derived cache — nothing
is lost).

## Follow-up candidates (noted in place)

- `plan_snapshots`/`plan_compliance` for ingest instances (run-page
  planned-vs-actual for Max) — comment at the archive-pass section header in
  `ingest_builder.py`; deliberately its own change.
- Archive year chips hardcoded from 2024 (Felix's account start) — comment at
  the chip loop in `archive.dc.html`; derive from MIN(year) later.
