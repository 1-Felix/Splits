package com.splits.healthspike

import android.os.Bundle
import android.util.Log
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.PermissionController
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.ActiveCaloriesBurnedRecord
import androidx.health.connect.client.records.DistanceRecord
import androidx.health.connect.client.records.ElevationGainedRecord
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.Record
import androidx.health.connect.client.records.RestingHeartRateRecord
import androidx.health.connect.client.records.SpeedRecord
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.records.TotalCaloriesBurnedRecord
import androidx.health.connect.client.records.metadata.DataOrigin
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.time.Duration
import java.time.Instant
import java.time.ZoneId
import kotlin.reflect.KClass

/**
 * SPLITS Health Connect verification spike (Phase 0).
 *
 * Reads recent running ExerciseSessionRecords from Health Connect, joins the
 * heart-rate / distance / speed samples that fall inside each session window,
 * and dumps the result as pretty JSON to Logcat (tag SPLITS_SPIKE) and to a
 * file in the app's external files dir for `adb pull`.
 *
 * Throwaway. Single Activity, programmatic UI, no architecture.
 */
class MainActivity : AppCompatActivity() {

    private companion object {
        const val TAG = "SPLITS_SPIKE"
        const val OUTPUT_FILE = "splits_spike_runs.json"
        const val LOOKBACK_DAYS = 60L
        const val MAX_RUNS = 20
        const val HR_DOWNSAMPLE_SEC = 5L
        // Samsung Health package — the decision gate for this spike.
        const val SHEALTH_PKG = "com.sec.android.app.shealth"
    }

    // All permissions this spike wants. Record-type reads + the two special grants.
    private val permissions: Set<String> = setOf(
        HealthPermission.getReadPermission(ExerciseSessionRecord::class),
        HealthPermission.getReadPermission(HeartRateRecord::class),
        HealthPermission.getReadPermission(DistanceRecord::class),
        HealthPermission.getReadPermission(SpeedRecord::class),
        // scope-expansion probes (Health Connect data-types research)
        HealthPermission.getReadPermission(ElevationGainedRecord::class),
        HealthPermission.getReadPermission(ActiveCaloriesBurnedRecord::class),
        HealthPermission.getReadPermission(TotalCaloriesBurnedRecord::class),
        HealthPermission.getReadPermission(StepsRecord::class),
        HealthPermission.getReadPermission(RestingHeartRateRecord::class),
        HealthPermission.PERMISSION_READ_HEALTH_DATA_HISTORY,
        HealthPermission.PERMISSION_READ_HEALTH_DATA_IN_BACKGROUND,
    )

    private lateinit var statusView: TextView

    // Registered before the Activity is STARTED, per the ActivityResult contract rules.
    private val permissionLauncher =
        registerForActivityResult(PermissionController.createRequestPermissionResultContract()) { granted ->
            val missing = permissions - granted
            if (missing.isEmpty()) {
                append("All ${permissions.size} permissions granted.")
            } else {
                append("Granted ${granted.size}/${permissions.size}. Missing:")
                missing.forEach { append("   - $it") }
                append("Reading anyway with whatever was granted…")
            }
            readAndDump()
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(buildUi())
        append("SPLITS Health Connect spike")
        append("Output file tag: $TAG")

        when (val sdk = HealthConnectClient.getSdkStatus(this)) {
            HealthConnectClient.SDK_AVAILABLE ->
                append("Health Connect SDK: AVAILABLE")
            HealthConnectClient.SDK_UNAVAILABLE -> {
                append("Health Connect SDK: UNAVAILABLE on this device. Cannot continue.")
                Log.e(TAG, "SDK unavailable")
            }
            HealthConnectClient.SDK_UNAVAILABLE_PROVIDER_UPDATE_REQUIRED ->
                append("Health Connect SDK: needs a provider update. Update Health Connect first.")
            else ->
                append("Health Connect SDK status: unknown ($sdk)")
        }
        append("Tap the button to grant permissions (if needed) and read runs.")
    }

    private fun buildUi(): ViewGroup {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 48, 32, 32)
        }
        val button = Button(this).apply {
            text = "Read running workouts"
            setOnClickListener { onReadClicked() }
        }
        statusView = TextView(this).apply {
            textSize = 12f
            setTextIsSelectable(true)
            setPadding(0, 24, 0, 0)
        }
        val scroll = ScrollView(this).apply {
            addView(
                statusView,
                LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT
                )
            )
        }
        root.addView(
            button,
            LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
            )
        )
        root.addView(
            scroll,
            LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                0,
                1f
            )
        )
        root.gravity = Gravity.TOP
        return root
    }

    private fun onReadClicked() {
        lifecycleScope.launch {
            val client = clientOrNull() ?: return@launch
            val granted = client.permissionController.getGrantedPermissions()
            append("Currently granted: ${granted.size}/${permissions.size}")
            if (granted.containsAll(permissions)) {
                readAndDump()
            } else {
                append("Requesting permissions from Health Connect…")
                permissionLauncher.launch(permissions)
            }
        }
    }

    private fun clientOrNull(): HealthConnectClient? {
        return if (HealthConnectClient.getSdkStatus(this) == HealthConnectClient.SDK_AVAILABLE) {
            HealthConnectClient.getOrCreate(this)
        } else {
            append("Health Connect not available; aborting read.")
            null
        }
    }

    private fun readAndDump() {
        lifecycleScope.launch {
            try {
                val (json, summary) = withContext(Dispatchers.IO) { readRuns() }
                append(summary)
                dumpJson(json)
            } catch (e: Exception) {
                Log.e(TAG, "Read failed", e)
                append("ERROR: ${e.javaClass.simpleName}: ${e.message}")
            }
        }
    }

    /** Core read. Returns ({runs, restingHeartRate}, humanSummary). Runs on IO. */
    private suspend fun readRuns(): Pair<JSONObject, String> {
        val client = HealthConnectClient.getOrCreate(this)
        val now = Instant.now()
        val since = now.minus(Duration.ofDays(LOOKBACK_DAYS))
        val window = TimeRangeFilter.between(since, now)

        Log.i(TAG, "Reading ExerciseSessionRecords for the last $LOOKBACK_DAYS days")
        val sessions = client.readRecords(
            ReadRecordsRequest(
                recordType = ExerciseSessionRecord::class,
                timeRangeFilter = window,
                ascendingOrder = false, // newest first
                pageSize = 50,
            )
        ).records

        val runs = sessions
            .filter { it.exerciseType == ExerciseSessionRecord.EXERCISE_TYPE_RUNNING ||
                    it.exerciseType == ExerciseSessionRecord.EXERCISE_TYPE_RUNNING_TREADMILL }
            .take(MAX_RUNS)

        Log.i(TAG, "Sessions in window: ${sessions.size}; running sessions kept: ${runs.size}")

        val out = JSONArray()
        val sourceCounts = linkedMapOf<String, Int>()
        var withMax = 0; var withElev = 0; var withActiveCal = 0
        var withTotalCal = 0; var withSteps = 0; var withSpeed = 0

        for (run in runs) {
            val range = TimeRangeFilter.between(run.startTime, run.endTime)
            // Read metrics ONLY from the session's own writer — several apps passively
            // write into the same window (steps especially), so an unfiltered delta read
            // double-counts. Filter by the session's dataOrigin.
            val sourcePkg = run.metadata.dataOrigin.packageName
            val origin = setOf(DataOrigin(sourcePkg))

            val hrSamples = readAll(client, HeartRateRecord::class, range, origin)
                .flatMap { it.samples }
                .sortedBy { it.time }
            val distanceRecords = readAll(client, DistanceRecord::class, range, origin)
            val speedSamples = readAll(client, SpeedRecord::class, range, origin)
                .flatMap { it.samples }
                .sortedBy { it.time }
            // DELTA records — summed over the session window; count kept so we can
            // tell "not written" (count 0) apart from "written as 0" (flat run etc.).
            val elevRecs = readAll(client, ElevationGainedRecord::class, range, origin)
            val activeRecs = readAll(client, ActiveCaloriesBurnedRecord::class, range, origin)
            val totalRecs = readAll(client, TotalCaloriesBurnedRecord::class, range, origin)
            val stepRecs = readAll(client, StepsRecord::class, range, origin)

            val durationSec = Duration.between(run.startTime, run.endTime).seconds
            val totalMeters = distanceRecords.sumOf { it.distance.inMeters }
            val avgBpm = if (hrSamples.isEmpty()) null
                else hrSamples.map { it.beatsPerMinute }.average()
            val maxBpm = hrSamples.maxOfOrNull { it.beatsPerMinute } // observed max → real zone calibration
            val avgSpeedMps = if (speedSamples.isEmpty()) null
                else speedSamples.map { it.speed.inMetersPerSecond }.average()

            sourceCounts[sourcePkg] = (sourceCounts[sourcePkg] ?: 0) + 1

            // Downsample HR + speed to ~1 sample / HR_DOWNSAMPLE_SEC s, t relative to session start.
            val hrSeries = JSONArray()
            var lastHr = Long.MIN_VALUE
            for (s in hrSamples) {
                val tSec = s.time.epochSecond - run.startTime.epochSecond
                if (lastHr == Long.MIN_VALUE || tSec - lastHr >= HR_DOWNSAMPLE_SEC) {
                    hrSeries.put(JSONObject().put("tSec", tSec).put("bpm", s.beatsPerMinute)); lastHr = tSec
                }
            }
            val speedSeries = JSONArray()
            var lastSpd = Long.MIN_VALUE
            for (s in speedSamples) {
                val tSec = s.time.epochSecond - run.startTime.epochSecond
                if (lastSpd == Long.MIN_VALUE || tSec - lastSpd >= HR_DOWNSAMPLE_SEC) {
                    speedSeries.put(JSONObject().put("tSec", tSec).put("mps", round2(s.speed.inMetersPerSecond))); lastSpd = tSec
                }
            }

            if (maxBpm != null) withMax++
            if (elevRecs.isNotEmpty()) withElev++
            if (activeRecs.isNotEmpty()) withActiveCal++
            if (totalRecs.isNotEmpty()) withTotalCal++
            if (stepRecs.isNotEmpty()) withSteps++
            if (speedSeries.length() > 0) withSpeed++

            val obj = JSONObject().apply {
                put("metadataId", run.metadata.id)
                put("clientRecordId", run.metadata.clientRecordId ?: JSONObject.NULL)
                put("sourcePackage", sourcePkg)
                put("isSamsungHealth", sourcePkg == SHEALTH_PKG)
                put("sportType", exerciseTypeName(run.exerciseType))
                put("exerciseTypeInt", run.exerciseType)
                put("title", run.title ?: JSONObject.NULL)
                put("startTimeLocal", localStart(run))
                put("startTimeUtc", run.startTime.toString())
                put("durationSec", durationSec)
                put("totalDistanceMeters", round1(totalMeters))
                put("avgHeartRateBpm", avgBpm?.let { round1(it) } ?: JSONObject.NULL)
                put("maxHeartRateBpm", maxBpm ?: JSONObject.NULL)
                put("hrSampleCountRaw", hrSamples.size)
                put("avgSpeedMps", avgSpeedMps?.let { round2(it) } ?: JSONObject.NULL)
                put("speedSampleCountRaw", speedSamples.size)
                put("elevationGainMeters", round1(elevRecs.sumOf { it.elevation.inMeters }))
                put("elevationRecordCount", elevRecs.size)
                put("activeCaloriesKcal", round1(activeRecs.sumOf { it.energy.inKilocalories }))
                put("activeCalRecordCount", activeRecs.size)
                put("totalCaloriesKcal", round1(totalRecs.sumOf { it.energy.inKilocalories }))
                put("totalCalRecordCount", totalRecs.size)
                put("stepsTotal", stepRecs.sumOf { it.count })
                put("stepsRecordCount", stepRecs.size)
                put("heartRate", hrSeries)
                put("speed", speedSeries)
            }
            out.put(obj)

            Log.i(TAG, "run ${run.metadata.id} src=$sourcePkg dur=${durationSec}s dist=${round1(totalMeters)}m " +
                "hr=${hrSamples.size}(max=$maxBpm) spd=${speedSamples.size} elev=${elevRecs.size} " +
                "aCal=${activeRecs.size} tCal=${totalRecs.size} steps=${stepRecs.size}")
        }

        // Resting HR is a DAILY wellness record, not per-session — read across the whole window.
        val rhrRecs = readAll(client, RestingHeartRateRecord::class, window).sortedBy { it.time }
        val rhr = JSONArray()
        for (r in rhrRecs) {
            rhr.put(JSONObject().put("timeUtc", r.time.toString()).put("bpm", r.beatsPerMinute))
        }

        val root = JSONObject().put("runs", out).put("restingHeartRate", rhr)

        val summary = buildString {
            appendLine("Done. Running sessions: ${runs.size} (of ${sessions.size} sessions in window).")
            appendLine("Sources seen:")
            if (sourceCounts.isEmpty()) appendLine("   (none)")
            sourceCounts.forEach { (pkg, n) ->
                val flag = if (pkg == SHEALTH_PKG) "  <-- SAMSUNG HEALTH (decision gate!)" else ""
                appendLine("   $pkg : $n$flag")
            }
            val shealthCount = sourceCounts[SHEALTH_PKG] ?: 0
            appendLine(
                if (shealthCount > 0)
                    "GATE: YES — $shealthCount Samsung Health run(s) visible via Health Connect."
                else
                    "GATE: NO Samsung Health runs found in this window."
            )
            appendLine("Coverage (runs with data / ${out.length()}):")
            appendLine("   maxHR $withMax · elev $withElev · activeCal $withActiveCal · totalCal $withTotalCal · steps $withSteps · speedSeries $withSpeed")
            appendLine("Resting HR records in window: ${rhr.length()}" +
                (if (rhr.length() > 0) " (latest ${rhrRecs.last().beatsPerMinute} bpm)" else ""))
        }.trimEnd()

        return root to summary
    }

    /** Reads every page of [recordType] in [range] (default pageSize is 1000, so HR needs paging). */
    private suspend fun <T : Record> readAll(
        client: HealthConnectClient,
        recordType: KClass<T>,
        range: TimeRangeFilter,
        dataOrigins: Set<DataOrigin> = emptySet(),
    ): List<T> {
        val all = mutableListOf<T>()
        var pageToken: String? = null
        do {
            val response = client.readRecords(
                ReadRecordsRequest(
                    recordType = recordType,
                    timeRangeFilter = range,
                    dataOriginFilter = dataOrigins,
                    pageSize = 1000,
                    pageToken = pageToken,
                )
            )
            all += response.records
            pageToken = response.pageToken
        } while (pageToken != null)
        return all
    }

    private fun localStart(run: ExerciseSessionRecord): String {
        val offset = run.startZoneOffset
        return if (offset != null) {
            run.startTime.atOffset(offset).toString()
        } else {
            // No stored offset: fall back to the device's current zone.
            run.startTime.atZone(ZoneId.systemDefault()).toOffsetDateTime().toString()
        }
    }

    private fun exerciseTypeName(type: Int): String = when (type) {
        ExerciseSessionRecord.EXERCISE_TYPE_RUNNING -> "RUNNING"
        ExerciseSessionRecord.EXERCISE_TYPE_RUNNING_TREADMILL -> "RUNNING_TREADMILL"
        else -> "OTHER_$type"
    }

    private fun dumpJson(root: JSONObject) {
        val pretty = root.toString(2)
        val runsCount = root.getJSONArray("runs").length()

        // 1) Logcat — chunked, because Logcat truncates long single lines (~4 KB).
        Log.i(TAG, "===== BEGIN JSON ($runsCount runs) =====")
        pretty.chunked(3500).forEachIndexed { i, chunk -> Log.i(TAG, "[$i] $chunk") }
        Log.i(TAG, "===== END JSON =====")

        // 2) File for `adb pull`.
        val dir: File? = getExternalFilesDir(null)
        if (dir == null) {
            append("External files dir unavailable; JSON only in Logcat.")
            return
        }
        val file = File(dir, OUTPUT_FILE)
        file.writeText(pretty)
        Log.i(TAG, "Wrote ${file.length()} bytes to ${file.absolutePath}")
        append("Wrote JSON ($runsCount runs + RHR) to:")
        append("   ${file.absolutePath}")
        append("Pull with:  adb pull ${file.absolutePath}")
    }

    // --- tiny helpers ---

    private fun round1(v: Double) = Math.round(v * 10.0) / 10.0
    private fun round2(v: Double) = Math.round(v * 100.0) / 100.0

    private fun append(line: String) {
        Log.i(TAG, line)
        runOnUiThread { statusView.append(line + "\n") }
    }
}
