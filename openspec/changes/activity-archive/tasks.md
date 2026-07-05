# Tasks: activity-archive

## 1. Archive store module

- [x] 1.1 Create `activity_archive.py`: open-or-create the database at
      `<DATA_DIR>/activity-archive.db` with schema v1 (`activities`,
      `daily_wellness`, `archive_meta` per design D2/D9), default journal mode,
      and `schema_version` recorded in `archive_meta`
- [x] 1.2 Implement `upsert_activities(rows)`: promoted-field extraction from
      the raw summary dict, `INSERT … ON CONFLICT(activity_id) DO UPDATE`
      (fresh summary wins, `first_seen_at` preserved, `updated_at` bumped),
      no DELETE path anywhere in the module
- [x] 1.3 Implement `write_detail(activity_id, payload)`: store the raw detail
      JSON with `detail_fetched_at`; refuse to overwrite existing detail with
      empty/None; `missing_detail_ids(limit, newest_first)` query helper
- [x] 1.4 Implement `upsert_wellness(date, values, raw)`: one row per local
      date, later write wins
- [x] 1.5 Implement corrupt-database handling: on `sqlite3.DatabaseError` at
      open, rename to `activity-archive.db.corrupt-<date>` and create fresh
- [x] 1.6 Unit tests (`test_activity_archive.py`, temp dir, no network): dedupe
      on double-upsert, fresh-summary-wins on rename, detail write-once,
      wellness same-day refresh, corrupt-file quarantine-and-recreate

## 2. Sync integration (append-on-sync)

- [x] 2.1 In `sync_garmin.py`, after `garmin-data.js` is written: wrap an
      archive step in the existing `safe()` pattern — upsert all summaries
      from the already-fetched `acts` list (zero extra API calls)
- [x] 2.2 Detail top-up in the same step: fetch raw detail for archived
      activities missing it, newest first, capped (default 25/sync), reusing
      `.garmin_cache/detail-<id>.json` before hitting the API; store the RAW
      response (not the trimmed coach-read dict)
- [x] 2.3 Wellness snapshot: upsert today's row from the readiness values the
      sync already fetched (RHR, HRV, sleep hours + raw payload)
- [x] 2.4 Log lines for the archive step (`✓ archive: +N activities, M details
      topped up, wellness banked`) and a warning path that provably cannot
      fail the sync (verify exit code stays 0 when archive write is blocked)

## 3. Backfill mode

- [x] 3.1 Add `--backfill` flag: walk `get_activities_by_date` year by year
      backwards until two consecutive empty years (account start detected, not
      hardcoded), upserting summaries as it goes
- [x] 3.2 Backfill detail pass: fetch raw detail for every row missing it, no
      cap, gentle throttle between API calls, committing per activity so
      interrupt-and-resume never repeats completed work
- [x] 3.3 Record `backfill_completed_at` and expected coverage (activity count,
      earliest date) in `archive_meta` on completion

## 4. Verify mode

- [x] 4.1 Add `--verify-archive` flag: print total activities, counts by year
      and type, detail coverage, wellness row count, date bounds, db size
- [x] 4.2 Exit non-zero (with a named reason) when coverage regresses against
      the `archive_meta` expectations recorded at backfill/append time

## 5. Housekeeping

- [x] 5.1 `.gitignore`: add `activity-archive.db*` (covers journal files and
      `.corrupt-<date>` quarantines)
- [x] 5.2 README: archive section — what it is, where it lives, the backfill
      ritual (local + `docker compose exec` variants), verify mode, and the
      "server copy is canonical, local copies are disposable" rule
- [x] 5.3 ROADMAP: mark stage 1 shipped, note the archive file name and entry
      points for stage 2 to build on

## 6. End-to-end verification

- [x] 6.1 Run the existing test suite (`test_*.py`, `test_*.mjs`) — no
      regressions from the sync changes
- [x] 6.2 Local smoke: real `python sync_garmin.py` writes `garmin-data.js`
      exactly as before AND creates the local archive with today's activities
      + wellness row; `--verify-archive` reports sanely
- [x] 6.3 Local backfill dress rehearsal: `--backfill` against the real
      account, then `--verify-archive` — expect ≥536 activities, earliest
      2024-05-12, detail coverage ~100%; interrupt mid-run once and confirm
      resume works

## 7. Deploy to the homeserver

- [ ] 7.1 Merge to `main` → CI publishes the image; pull + recreate the
      container with the same volume
- [ ] 7.2 Run the canonical backfill in the container
      (`docker compose exec splits python3 sync_garmin.py --backfill`) and
      verify (`… --verify-archive`)
- [ ] 7.3 After the next nightly sync, confirm the archive appended (activity
      count unchanged or grown, new wellness row, dashboard untouched)
