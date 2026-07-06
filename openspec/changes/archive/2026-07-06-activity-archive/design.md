# Design: activity-archive

## Context

`sync_garmin.py` already pulls every activity summary in a 30-month window on
each sync (`load_activities`, cached per day) and fetches the raw
`get_activity_details` payload for the 6 most recent runs (`fetch_run_detail`,
cached per activity in `.garmin_cache/detail-<id>.json`). Nothing durable exists:
`garmin-data.js` is a windowed view overwritten nightly, and the caches are
fetch optimizations with no schema or retention guarantees.

The account's history begins 2024-05-12 — 536 activities as of 2026-07-05
(~160 runs, ~300 strength sessions, the rest cycling/walking/other). ROADMAP
stage 2 (`insight-metrics`) will read this archive to compute efficiency
trends, in-run best efforts, and records; stage 4 (`coach-loop`) will read it
for plan-vs-actual. The archive schema is therefore a long-lived contract.

Deployment reality: the canonical data directory is the Docker volume on the
homeserver (`SPLITS_DATA_DIR=/data` in the container). Local dev on Windows
resolves the data dir to the repo folder; the repo's `garmin-data.js` /
`plan-data.js` are SMB symlinks into the server volume.

## Goals / Non-Goals

**Goals:**
- Every activity Garmin has ever recorded for this account, stored durably with
  its raw summary and raw detail payload, deduplicated by Garmin activity id.
- One-time, idempotent, resumable backfill of the full account history.
- Every future sync (boot / nightly / manual) appends new activities and their
  detail automatically.
- Archiving is fail-soft: it can never break or block the telemetry sync that
  feeds the dashboard.
- Verifiable completeness (counts by year/type, detail coverage).

**Non-Goals:**
- No dashboard or `garmin-data.js` changes — nothing reads the archive yet.
- No derived-metric tables (efficiency, best efforts) — that is stage 2, and it
  will define its own derived tables on top of the raw archive.
- No GPS routes (`maxpoly=0` stays) — see Open Questions.
- No historical wellness backfill: daily wellness rows accrue from now on (D9);
  reconstructing past days would need hundreds of per-day API calls of dubious
  availability.
- No multi-user, no remote access to the archive, no Garmin-side deletion sync.

## Decisions

### D1 — SQLite, one file in the data directory
`<DATA_DIR>/activity-archive.db`, created with stdlib `sqlite3`.

- *Why not JSONL append-only?* Dedupe/upsert and stage-2 queries (e.g. "all
  steady runs ≥ 30 min with avg HR") get awkward fast; SQLite gives both for free.
- *Why not Postgres or a service?* Single user, single writer, self-hosted; a
  file in the existing volume inherits the backup/upgrade story of the other
  personal data for zero operational cost.
- Journal mode stays at the SQLite default (`DELETE`), not WAL: WAL is unsafe on
  network filesystems, and local dev may point the data dir at an SMB mount.
  With one writer (the sync lock in `serve.mjs` already serializes syncs) the
  default is sufficient.

### D2 — Raw-first schema: JSON payloads are the source of truth, columns are an index
Two content-bearing tables plus metadata:

```sql
CREATE TABLE activities (
  activity_id      INTEGER PRIMARY KEY,   -- Garmin's activityId
  start_time_local TEXT NOT NULL,         -- ISO, promoted for range queries
  type_key         TEXT,                  -- activityType.typeKey
  name             TEXT,
  distance_m       REAL,
  duration_s       REAL,
  avg_hr           INTEGER,
  max_hr           INTEGER,
  avg_cadence      REAL,
  elevation_gain_m REAL,
  summary_json     TEXT NOT NULL,         -- full raw activity-list entry
  detail_json      TEXT,                  -- full raw get_activity_details payload
  detail_fetched_at TEXT,                 -- NULL ⇒ detail still missing
  first_seen_at    TEXT NOT NULL,
  updated_at       TEXT NOT NULL
);
CREATE INDEX idx_activities_start ON activities(start_time_local);
CREATE INDEX idx_activities_type  ON activities(type_key);

CREATE TABLE archive_meta (               -- schema_version, backfill_completed_at,
  key TEXT PRIMARY KEY, value TEXT        -- last_append_at, …
);
```

- Promoted columns exist only for indexing/queries; anything not promoted is
  still in `summary_json`. Garmin's schema is undocumented and shifts — a raw
  copy means a lossy mapping can never destroy data, and stage 2 can promote
  more columns later by re-reading the JSON already on disk.
- `detail_json` stores the **raw** `get_activity_details` response (the same
  payload `fetch_run_detail` already caches), *not* the trimmed dict used for
  the dashboard coach-read. The trim is a view; the archive keeps the source.
- Detail stays plain TEXT, not compressed BLOBs: ~500 activities × a few hundred
  KB ≈ low hundreds of MB worst case — irrelevant on the volume, and plain JSON
  keeps stage 2 and ad-hoc `sqlite3` sessions friction-free. Compression is a
  reversible later optimization.
- Schema versioning via `archive_meta.schema_version` (starts at `1`),
  forward-only migrations applied on open.

### D3 — Upsert semantics: fresh summary wins, detail is write-once, nothing is ever deleted
`INSERT … ON CONFLICT(activity_id) DO UPDATE` mirroring the existing merge rule
in `load_activities` (a fresh Garmin copy wins for summary fields — this also
propagates Garmin-side edits like renamed activities). `detail_json` is only
written when a fetch succeeds and is never overwritten with NULL. The sync
never issues DELETEs; an activity deleted on Garmin's side simply stops being
refreshed but remains archived.

### D4 — Append-on-sync rides the existing fetch, then tops up missing detail
After `load_activities` returns (the same list the dashboard build consumes),
the sync upserts all summaries — the 30-month window means even multi-week sync
gaps are covered with no extra API calls. Then it fetches detail for archived
activities where `detail_json IS NULL`, newest first, capped per sync run
(e.g. 25) so a normal night does 0–3 detail calls and a post-vacation batch
catches up over a few nights instead of hammering Garmin. The existing
`detail-<id>.json` cache is consulted first, so already-cached payloads cost
nothing.

### D5 — Backfill is a mode of the sync script, idempotent and resumable
`python sync_garmin.py --backfill` (same auth, cache, logging, and data-dir
resolution as a normal sync):

1. Walk `get_activities_by_date` year by year from today back to the account
   start, detected by consecutive empty years — **not** a hardcoded 2024-05 —
   and upsert all summaries.
2. Fetch detail for every row with `detail_json IS NULL` (no per-run cap in
   backfill mode), seeding from existing cache files, committing per activity
   with a gentle throttle between API calls.

Interrupting and re-running is safe: step 1 upserts, step 2 only targets
missing rows. Expected one-time cost: ~540 detail calls ≈ minutes.

### D6 — Fail-soft: archive errors are logged warnings, never sync failures
All archive work is wrapped in the script's existing `safe()` pattern and runs
**after** `garmin-data.js` is written, so dashboard freshness is never delayed
or endangered by an archive problem (locked file, corrupt db, full disk). A
corrupt database is quarantined by rename (`activity-archive.db.corrupt-<date>`)
and recreated on the next sync; the archive is rebuildable from Garmin via
`--backfill` by construction.

### D7 — The canonical archive lives on the server; local archives are disposable
The container's nightly sync appends to the volume copy — that is *the*
archive. A local `python sync_garmin.py` without `SPLITS_DATA_DIR` creates a
separate local db in the repo dir (gitignored: `activity-archive.db*`). No sync
protocol between the two: unlike `plan-data.js` (hand-authored, precious), the
archive is entirely derived from Garmin and any copy can be rebuilt with
`--backfill`. Running SQLite across the SMB mount is explicitly not recommended
(locking on network shares is unreliable); tooling that wants the canonical
archive should copy the file or run on the server.

### D8 — Verification is a first-class mode
`python sync_garmin.py --verify-archive` prints counts by year and type, detail
coverage (rows with/without `detail_json`), wellness row count, date bounds,
and db size, and exits non-zero if coverage regresses against `archive_meta`
expectations. This is the acceptance check after backfill (compare against the
probed 536/2024-05-12 baseline) and the periodic health check thereafter.

### D9 — Daily wellness snapshot rides every sync *(decided 2026-07-05)*
The sync already fetches today's readiness inputs and discards everything
outside the dashboard's 14-night window. Each sync now also upserts one row:

```sql
CREATE TABLE daily_wellness (
  date        TEXT PRIMARY KEY,   -- local ISO date the values describe
  resting_hr  INTEGER,
  hrv         INTEGER,
  sleep_hours REAL,
  raw_json    TEXT NOT NULL,      -- everything the sync fetched for that day
  updated_at  TEXT NOT NULL
);
```

Raw-first like D2: promoted columns for the obvious queries, `raw_json` keeps
whatever the readiness fetch returned (body battery, sleep phases, …). Upsert
by date — a later sync the same day refreshes the row. Same fail-soft wrapper
as all archive writes (D6). No backfill (see Non-Goals): the table simply
starts accruing on the first deployed sync, which is the cheapest possible day
to start.

## Risks / Trade-offs

- [Garmin throttles/blocks bulk detail fetches during backfill] → per-activity
  commits + resume-on-rerun + throttle; a partial backfill is a valid state
  that the nightly top-up (D4) also continues to repair.
- [Unofficial API changes payload shapes] → raw-first storage (D2) means we
  archive whatever Garmin returns; only the thin promoted columns would need a
  code fix, and they are re-derivable from `summary_json`.
- [Two archives (server + local dev) drift] → accepted by design (D7); only the
  server copy is canonical, all copies are rebuildable, and no other component
  reads the local one.
- [SQLite file corruption on the volume] → single writer + default journal;
  quarantine-and-rebuild path (D6); worst case is one `--backfill` away from
  whole again.
- [Detail payloads bloat the db over years] → at current volume (~150 runs/yr)
  growth is tens of MB/year; compression and pruning of non-run detail remain
  available later without schema change.

## Migration Plan

1. Ship the change (image rebuild via existing CI on merge to `main`).
2. On the homeserver: `docker compose exec splits python3 sync_garmin.py --backfill`.
3. `… --verify-archive` — expect ≥536 activities, earliest 2024-05-12, detail
   coverage ~100%.
4. Done — nightly syncs keep appending. No dashboard deploy steps; nothing else
   changed.

Rollback: delete `activity-archive.db` from the volume and revert the image.
Nothing reads the archive yet, so rollback risk is nil.

## Open Questions

1. **GPS routes**: `maxpoly=0` keeps payloads lean but means no map/route data
   in the archive. Progress metrics don't need it; a future map view would.
   Deferred — flipping it later only affects *new* fetches, though old rows
   would need a detail re-fetch to gain routes.

*(Resolved 2026-07-05: daily wellness snapshots are in scope — see D9.)*
