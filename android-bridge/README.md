# android-bridge — Health Connect verification spike (Phase 0)

Throwaway Android app whose **only** job is to prove what running-workout data we
can pull out of **Android Health Connect** on a real phone. It reads recent
running `ExerciseSessionRecord`s, joins the heart-rate / distance / speed samples
inside each session, and dumps everything as pretty JSON.

Target device: **Samsung Galaxy S24, Android 16** (sideloaded via Android Studio).
Not a product. No architecture, no tests — a probe.

## The decision gate

Samsung Health 7.00.0.107 is installed on the device. The question this spike
exists to answer:

> Does any `ExerciseSessionRecord` show up with
> `metadata.dataOrigin.packageName == com.sec.android.app.shealth`?

If yes, Samsung Health writes runs into Health Connect and we can read them —
green light for the bridge. If no runs from that package appear, Samsung Health
is not exporting sessions and we need another route (e.g. Garmin, or Samsung's
own SDK). The app flags this explicitly in the on-screen summary and in Logcat
(`GATE: YES` / `GATE: NO`).

## What it reads

- `ExerciseSessionRecord` over the last **60 days**, newest first, filtered to
  `EXERCISE_TYPE_RUNNING` + `EXERCISE_TYPE_RUNNING_TREADMILL`, capped at 20 runs.
- For each run, within its `[startTime, endTime]`: `HeartRateRecord` samples,
  `DistanceRecord`, `SpeedRecord` (all paged — HR easily exceeds one page).

Per run it emits: `metadataId`, `clientRecordId`, **`sourcePackage`** (+
`isSamsungHealth`), `sportType`, local + UTC start time, `durationSec`,
`totalDistanceMeters`, `avgHeartRateBpm`, a downsampled `heartRate` series
(`{tSec, bpm}`, ~1 sample / 5 s), `avgSpeedMps`, and raw sample counts.

## Toolchain / versions

| Thing | Version |
|-------|---------|
| Health Connect client | `androidx.health.connect:connect-client:1.1.0` (latest stable) |
| Android Gradle Plugin | 9.2.0 |
| Kotlin | 2.4.10 |
| Gradle wrapper | 9.4.1 |
| compileSdk / targetSdk | 36 (Android 16) |
| minSdk | 26 |

## Open in Android Studio

1. **File → Open** and pick this `android-bridge/` folder (open the folder, not a
   file). Use a recent Android Studio (one that supports AGP 9.2 / compileSdk 36).
2. On first sync Android Studio writes `local.properties` (your SDK path) and
   downloads Gradle 9.4.1, the Android SDK 36 platform, and build-tools. Let it.
3. **Run ▶** onto the S24 (USB debugging on). Sideloads and launches the app.
   - The bundled `gradle/wrapper/gradle-wrapper.jar` lets `./gradlew` work from a
     terminal too, but Android Studio's Run button is the intended path.

## Grant permissions (required — do this once)

Health Connect permissions are **not** granted from a normal Android dialog; the
first read routes you into the Health Connect permission screen.

1. Tap **"Read running workouts"**. If permissions are missing, the app launches
   the Health Connect permission request.
2. In Health Connect, allow: Exercise, Heart rate, Distance, Speed. The two
   special grants (**"Access past data" / history** and **background** reads) may
   need to be toggled separately in
   **Settings → Security & privacy → Health Connect → App permissions → Splits HC Spike**
   (or Health Connect → Manage data → Splits HC Spike). Grant those too.
3. Tap the button again — it now reads and dumps.

If you ever need to re-test the request flow, revoke the app's access in Health
Connect settings and tap the button again.

## See the output

**On screen:** a scrolling summary — SDK status, permission counts, per-run one
liners, the sources seen, and the `GATE: YES/NO` verdict.

**Logcat** (full JSON), filter by tag:

```
adb logcat -s SPLITS_SPIKE
```

The JSON is logged between `===== BEGIN RUNS JSON =====` / `===== END =====`,
chunked (Logcat truncates ~4 KB lines), so reassemble the `[0] [1] …` chunks if
you copy from Logcat.

**File** (cleanest — full pretty JSON in one piece):

```
adb pull /sdcard/Android/data/com.splits.healthspike/files/splits_spike_runs.json
```

The app prints the exact absolute path (and the ready-to-paste `adb pull` line)
after each read.

## API caveats worth knowing

- **Availability first.** `HealthConnectClient.getSdkStatus(context)` must return
  `SDK_AVAILABLE` before `getOrCreate`. On Android 14+ Health Connect is part of
  the OS, so it should be available on the S24.
- **Permission flow is Health-Connect-mediated**, via
  `PermissionController.createRequestPermissionResultContract()` +
  `registerForActivityResult` — not `ActivityCompat.requestPermissions`. Granted
  state is checked with `permissionController.getGrantedPermissions()`.
- **Manifest requirements** (all present here): the `android.permission.health.*`
  `<uses-permission>` entries; a `<queries>` block so the app can see the Health
  Connect provider; an `activity-alias` with the
  `android.intent.action.VIEW_PERMISSION_USAGE` +
  `android.intent.category.HEALTH_PERMISSIONS` intent filter (the privacy-policy /
  permission-usage screen Health Connect links to on Android 14+); and a
  `SHOW_PERMISSIONS_RATIONALE` intent filter for pre-14 providers. Missing the
  usage/rationale filter makes the permission grant screen refuse the request.
- **History + background are special permissions.** `READ_HEALTH_DATA_HISTORY`
  (data older than 30 days) and `READ_HEALTH_DATA_IN_BACKGROUND` are declared and
  requested, but the OS may gate them behind an extra toggle and they can be
  denied independently. The app reads with whatever was granted and reports the
  gap — for this spike a same-window read still works even if these two are off.
- **Paging matters.** `ReadRecordsRequest` defaults to `pageSize = 1000`. A single
  run's heart-rate stream can exceed that, so the app loops on `pageToken`.
- **Empty distance/speed is a real signal, not a bug.** Some writers only store
  the session + HR and omit `DistanceRecord` / `SpeedRecord`. That's exactly the
  kind of gap this spike is meant to surface.
