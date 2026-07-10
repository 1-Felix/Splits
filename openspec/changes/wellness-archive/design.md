# Design: wellness-archive

## Context

`activity_archive.py` is at `SCHEMA_VERSION = 4`. Migrations are forward-only and
purely additive: `CREATE TABLE IF NOT EXISTS` for tables, and for columns a
guarded `ALTER` because SQLite has no `ADD COLUMN IF NOT EXISTS`:

```python
def _apply_schema_v4(conn):
    cols = {row[1] for row in conn.execute("PRAGMA table_info(activities)")}
    if "detail_distilled_json" not in cols:
        conn.execute("ALTER TABLE activities ADD COLUMN detail_distilled_json TEXT")
```

`daily_wellness` today is `(date, resting_hr, hrv, sleep_hours, raw_json,
updated_at)` with one row, upserted by `wellness_step()` from the readiness dict
that `build_data()` already computed. The archive lives in the homeserver volume,
`journal_mode=DELETE` (never WAL — the data dir may sit on SMB).

The sync's steady-state wellness work is already substantial and already wasteful:

```python
def fetch_sleep(client, nights=SLEEP_NIGHTS):        # SLEEP_NIGHTS = 14
    for i in range(nights):
        rec = safe(lambda: client.get_sleep_data(d), {}, …) or {}
        out.append({"hours": …, "hrv": …, "deepPct": …})   # rec is then discarded
```

Fourteen full payloads fetched per sync; three scalars kept.

Constraints: no agent API — everything quantitative is deterministic Python;
race Aug 9, so the sync must stay fail-soft and must never block
`garmin-data.js`; the archive is rebuildable from Garmin, but only for data
Garmin still serves.

## Goals / Non-Goals

**Goals**

- Wellness history that reaches the archive's own horizon (2024-05-12).
- Raw payloads stored, so tomorrow's derivation is not limited by today's.
- "The watch was off" and "we never asked" are different rows.
- Steady-state sync gets no more expensive.

**Non-Goals**

- Any dashboard payload or UI change (`history-depth` follows).
- Reconstructing five-minute HRV readings, which Garmin no longer serves.
- A wellness *metrics* engine — derivation stays where it lives, and nothing
  here is a training truth.
- Backfilling anything Garmin will not return for a historical date.

## Decisions

### D1 — Store the raw payloads; promote what we index on

Mirror `activities`: `sleep_json` and `hrv_json` hold the fetched payloads
verbatim. Promoted columns are derived from them and are freely recomputable.

**Raw payloads are upgrade-only, not write-once.** The obvious rule — "a
re-fetch never overwrites a stored payload, because Garmin's answer for a past
date can only get thinner" — is false for the newest night, and this repo already
knows it. `fetch_sleep()` re-fetches the same fourteen nights on every sync
precisely because *"Garmin only finalises last night's sleep once you wake"*, which
is why `SYNC_AT` moved to 08:00. A literal write-once would freeze the hollow
payload Garmin returns for a night it has not finalised, permanently.

So: a stored payload is replaced only when the stored one carries **no** device
data and the incoming one does. Concretely, the promoted `sleep_seconds` column
doubles as the substantive-payload flag:

```sql
sleep_json = CASE WHEN daily_wellness.sleep_seconds IS NULL
                  THEN excluded.sleep_json
                  ELSE daily_wellness.sleep_json END
```

Data can be filled in; it can never be overwritten or thinned. A genuinely unworn
night stays replaceable forever, which is harmless — Garmin keeps returning the
same hollow payload for it.

Promoted: `sleep_seconds`, `deep_seconds`, `rem_seconds`, `light_seconds`,
`awake_seconds`, `sleep_score`, `respiration_avg`, `body_battery_change`,
`resting_hr`, `hrv_last_night`, `hrv_weekly_avg`, `hrv_balanced_low`,
`hrv_balanced_upper`, `hrv_status`.

`hrvSummary.baseline` is an **object**, not a pair of bounds:
`{lowUpper, balancedLow, balancedUpper, markerValue}`. `balancedLow` and
`balancedUpper` are the band a chart draws, and are what the promoted columns
carry. (Corrected from `hrv_baseline_low`/`_high` after the fixtures were
captured — the original names described a shape Garmin does not return.)

`resting_hr` is read from the **sleep** payload's top-level `restingHeartRate`,
which is present historically and halves the per-date call count.
**`get_rhr_day` is the fallback when that value is null, not when the payload is
absent** — the `empty-night` fixture (2024-09-02) is a sleep payload that exists,
carries four keys, and has `restingHeartRate: null`, while `get_rhr_day` for the
same date returns 56.0. A payload-presence check would have silently lost resting
HR on every night the watch was off the wrist.

Consequently the per-date cost is two calls on a normal night and three on an
unworn one, rather than a flat two.

### D2 — `raw_json` keeps its meaning; the spec is corrected instead

The existing column holds the readiness snapshot. Renaming it churns the one
production row and the code that reads it for nothing. Keep it, rename it in
*documentation* to what it is (`readiness_json` is a comment, not a migration),
and fix the spec sentence that calls it "the raw fetched payload." The lie was in
the spec, not the column.

### D3 — `fetched_at` makes absence honest

Three states must be distinguishable:

| state | `fetched_at` | metrics |
|---|---|---|
| never asked | `NULL` | `NULL` |
| asked, watch had no data | set | `NULL` |
| asked, data present | set | populated |

"No device data" is **per-metric**, not per-row. The `empty-night` fixture has
every sleep metric null while HRV's rolling `weeklyAvg` and `baseline` remain
populated — only `lastNightAvg` goes null. Promoted columns are therefore
independently nullable, and `fetched_at` is the row-level fact.

Without this, `chart-engine`'s "a line SHALL never bridge a null" requirement is
unenforceable on wellness — a gap could mean either thing, and a chart drawn over
"never asked" is a chart drawn over a lie. This is one column and it is the
reason the whole change is worth doing carefully.

**The verify gate is ratcheted on the backfill's completion marker, not on the
presence of rows.** The moment this ships, the nightly sync starts stamping
`fetched_at` on fourteen nights — at which point every date back to 2024-05-12
is technically an unfetched gap, and a naive gate would fail
`--verify-archive` on the very first run, taking the nightly health check down
before the backfill has had a chance to execute. So gaps are *reported* always
and *fatal* only once `wellness_backfill_completed_at` is set. This mirrors how
`expected_activity_count` and `expected_distilled_runs` already work: an archive
that has not reached a state cannot regress from it.

### D4 — Backfill in the shape of the one that already works

`--backfill-wellness` walks dates from the archive's earliest activity to today,
skipping dates whose row already has `fetched_at`. Resumable by construction:
the archive *is* the cursor, so a crashed run resumes where it stopped and a
complete run is a no-op. Per date: `get_sleep_data`, then `get_hrv_data`. Each
call goes through the existing `safe()` wrapper; a failed date leaves
`fetched_at` NULL and is retried on the next run.

Rate limiting: a fixed inter-request delay and a `--since` bound, so the operator
can spread ~1,600 calls across nights if Garmin objects. Ordering is newest-first
so an interrupted backfill leaves the *most useful* history present.

*Rejected:* folding this into `--backfill`. The activity backfill is done and its
`backfill_completed_at` meta is a claim about activities. Wellness gets its own
flag and its own completion marker, so "which backfills have run?" stays a
question the archive can answer.

### D5 — Steady state banks what it already fetches

`fetch_sleep()` gains a callback (or returns the raw payloads alongside its
distilled trio) so `wellness_step()` can upsert fourteen rows instead of one. Net
new API calls per sync: only `get_hrv_data` for nights whose HRV is still
missing, which after the first week is typically one. The fourteen-night window
also self-heals: a night the sync missed while the container was down gets banked
on the next run that still sees it in the window.

Fail-soft and ordered exactly as today — after `garmin-data.js` is written, inside
`safe()`, never able to fail a sync.

### D6 — Fixtures for both payload eras

The 2024 sleep payload has 7 top-level keys; the 2026 one has 18. Promoted-column
extraction must handle both, and must not silently write NULL for a field that
merely moved. Two checked-in fixtures — one captured from a 2024 date, one from a
recent date — are the regression net. This is the concrete reason D1 stores raw:
the extraction logic will keep changing, and re-deriving from stored payloads must
stay possible without touching the network.

## Risks / Trade-offs

- **~1,600 API calls may trip an undocumented rate limit.** Mitigated by the
  delay, `--since`, and full resumability. Worst case the backfill takes several
  nights, which is fine — nothing depends on it synchronously.
- **Garmin may thin its historical responses over time.** This is the argument
  for doing it *now* rather than after the race. The probe shows what is
  available today; it will not get better.
- **Storage grows by tens of megabytes** of raw JSON in a database already at
  100 MB, over half of which is raw activity detail. Consistent with the
  existing trade and cheap against the volume.
- **The one existing row's `raw_json` stays anomalous** (readiness, not payload)
  while every new row's `sleep_json`/`hrv_json` are payloads. Accepted, and
  documented in the column comment; that row's date will also be re-fetched by
  the backfill, so it gains real payloads alongside.
- **HRV baseline / status is null for the first weeks of 2024** (`status: NONE`,
  `ONBOARDING_1`). Stored as null, which is correct — Garmin had not established
  a baseline. Charts will show a gap, which is the truth.

## Open Questions

- **Should `--backfill-wellness` also bank `get_training_readiness` per date?**
  It is a third call and the probe did not test its historical horizon. Deferred:
  readiness is already derivable from the stored sleep and HRV payloads, which is
  the whole point of D1.
- **Does anything want `sleepLevels` (the hypnogram)?** It is in the raw payload
  and therefore preserved for free. No promoted column until a view asks.
