# Max's Pixel — Onboarding Kit (tasks 1.4 residue + 6.5)

Everything server-side is live. This checklist takes Max's Pixel from zero to
set-and-forget syncing. APK: `splits-bridge.apk` in this folder (debug build,
applicationId `com.splits.bridge`, **versionName 0.2**, 2026-07-17: schedules
background sync even when some runs were rejected + input fields no longer sit
under the status bar). Updating from 0.1-spike: just install over the old app
(`adb install -r` or open the file) — config, permissions and delivery state
survive; no uninstall.

Plan: Max runs today → do Part A ideally **before** his run (Samsung Health
backfills historic workouts into Health Connect once Write is granted, so
after-the-run also works — the S24 backfilled 4 old workouts that way — but
before is the sure path).

---

## Part A — Samsung Health must write to Health Connect (the 1.4 root cause)

1. **Samsung Health version ≥ 7.00.5.009.** Samsung Health → profile icon →
   About. Max had `7.00.0.107`, which never wrote sessions — update via Play
   Store if still on it.
2. **Enable the Write toggles** (this was the silent killer on the S24):
   Settings → Health Connect (or the Health Connect app) → App permissions →
   Samsung Health → turn ON the **Write** toggles (exercise at minimum; all is
   fine). Health Connect denies Samsung Health write access **by default** —
   without this, Max's feed stays empty with no error anywhere.
3. Make sure Samsung Health ↔ Health Connect sync is on: Samsung Health →
   Settings → Health Connect → sync enabled.

## Part B — Install the bridge app

4. Get `splits-bridge.apk` onto the Pixel (Drive/Quick Share/cable). With a
   cable: `adb install -r splits-bridge.apk`.
5. Open it after allowing install-from-unknown-source for the transfer app.
   App shows as **SPLITS Bridge**.
6. Tap **GRANT PERMISSIONS** → approve everything in the Health Connect sheet
   (11 read permissions incl. history + background access).

## Part C — The gate check (task 1.4)

Max records his run today **on the Galaxy Watch** (phone-recorded and
auto-detected sessions carry **no HR** — the watch path is the real test).

7. After the run has synced to Samsung Health, open SPLITS Bridge → tap
   **DIAGNOSTIC DUMP (GATE CHECK)**.
8. Want: **GATE: YES**, the run listed with source
   `com.sec.android.app.shealth` and **hrSampleCount > 0**.
   - The dump also lists ALL sessions (any type/source) — if the run is
     missing entirely, Part A step 2 is almost certainly the cause.
   - GATE: YES but hrSampleCount 0 → it was a phone/auto-detected session;
     record a short watch run and re-dump.

## Part D — Configure and first sync (task 6.5)

9. Fetch the ingest token (from your dev box):
   ```bash
   ssh felix@192.168.0.37 "grep SPLITS_INGEST_TOKEN_MAX ~/dev/docker-compose-files/splits/.env"
   ```
   Use the value only (no `SPLITS_INGEST_TOKEN_MAX=` prefix, no quotes).
10. In SPLITS Bridge fill in:
    - **Server URL**: `https://splits-max.mochii.dev`
    - **Token**: the value from step 9
    - **Backfill start**: `YYYY-MM-DD` — how far back Max's Samsung Health
      history should count (e.g. `2026-01-01`; his plan starts 2026-07-20, so
      anything before that just seeds the volume/heatmap history).
11. Tap **SYNC NOW** → status should report the pushed runs + RHR days.
12. Verify the dashboard: open `https://splits-max.mochii.dev` → pocket-id
    login (Max's passkey) → today's run should show with pace, HR zones,
    energy tile, resting-HR card. A second **SYNC NOW** should push 0
    (idempotency).

Optional server-side cross-check:
```bash
ssh felix@192.168.0.37
python3 -c "import json;d=json.load(open('dev/docker-compose-files/splits/volumes/splits-max-data/ingested-runs.json'));print(len(d),'runs banked')"
docker compose -f ~/dev/docker-compose-files/splits/docker-compose.yml logs --tail 50 splits-max
```

## Part E — Set-and-forget (the rest of 6.5)

13. **Exempt the app from battery optimization** (Pixels throttle background
    jobs): Settings → Apps → SPLITS Bridge → Battery → **Unrestricted**.
14. Leave it alone. The WorkManager job syncs every ~6 h; every pass re-scans
    the whole backfill window and pushes only unseen session UIDs, so
    late-syncing watch workouts can't be skipped and retries lose nothing.
15. Over the next days: Max just runs with the watch. Verify on the dashboard
    that new runs appear **without anyone opening the bridge app** — that's
    the 6.5 completion criterion. Then tick 1.4 + 6.5 and the change is
    archive-ready.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Run absent from diagnostic dump | Samsung Health Write toggles off (Part A step 2) or SH < 7.00.5.009 |
| Run listed, hrSampleCount 0 | Phone-recorded/auto-detected session — record on the watch |
| "Server unreachable … will retry" | Network/URL typo; nothing is lost, next sync re-pushes |
| HTTP 401 on sync | Token mismatch — re-copy from the NUC `.env` |
| Dashboard 403 after login | Max's pocket-id account not in the `family` group |
| Weird sync state during testing | **RESET DELIVERY STATE** re-pushes the whole window; the server dedups by UID, so it's always safe |
| Deep debugging with a cable | `adb logcat -s SPLITS_BRIDGE` |
