package com.splits.healthspike

import android.os.Bundle
import android.text.InputType
import android.util.Log
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.PermissionController
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.time.Duration
import java.time.Instant

/**
 * SPLITS Health Connect bridge — setup + status UI.
 *
 * One-time setup: enter server URL + ingest token + backfill start date, grant
 * the Health Connect permissions, hit "Sync now" once. That schedules the
 * recurring background sync (SyncWorker); afterwards the app never needs to be
 * opened again (set-and-forget).
 *
 * "Diagnostic dump" keeps the original spike behavior — reads the last 60 days
 * and reports the Samsung Health GATE verdict (task 1.4) + writes the JSON file
 * for adb pull.
 */
class MainActivity : AppCompatActivity() {

    private companion object {
        const val TAG = "SPLITS_BRIDGE"
        const val OUTPUT_FILE = "splits_spike_runs.json"
        const val DIAGNOSTIC_LOOKBACK_DAYS = 60L
    }

    private lateinit var config: BridgeConfig
    private lateinit var urlInput: EditText
    private lateinit var tokenInput: EditText
    private lateinit var backfillInput: EditText
    private lateinit var statusView: TextView

    // Registered before the Activity is STARTED, per the ActivityResult contract rules.
    private val permissionLauncher =
        registerForActivityResult(PermissionController.createRequestPermissionResultContract()) { granted ->
            val missing = BridgePermissions.ALL - granted
            if (missing.isEmpty()) {
                append("All ${BridgePermissions.ALL.size} permissions granted.")
            } else {
                append("Granted ${granted.size}/${BridgePermissions.ALL.size}. Missing:")
                missing.forEach { append("   - $it") }
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        config = BridgeConfig(this)
        setContentView(buildUi())

        when (HealthConnectClient.getSdkStatus(this)) {
            HealthConnectClient.SDK_AVAILABLE -> append("Health Connect SDK: AVAILABLE")
            HealthConnectClient.SDK_UNAVAILABLE_PROVIDER_UPDATE_REQUIRED ->
                append("Health Connect needs a provider update — update it first.")
            else -> append("Health Connect SDK: UNAVAILABLE on this device.")
        }
        if (config.lastSyncSummary.isNotEmpty()) append("Last sync — ${config.lastSyncSummary}")
        if (!config.isConfigured()) append("Setup: fill in URL, token, backfill date, grant permissions, then Sync now.")
    }

    private fun buildUi(): ViewGroup {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 48, 32, 32)
        }
        fun input(hint: String, value: String, password: Boolean = false) = EditText(this).apply {
            this.hint = hint
            setText(value)
            textSize = 14f
            inputType = InputType.TYPE_CLASS_TEXT or
                (if (password) InputType.TYPE_TEXT_VARIATION_PASSWORD else InputType.TYPE_TEXT_VARIATION_URI)
            root.addView(this, wrap())
        }
        urlInput = input("Server URL (https://…)", config.serverBase)
        tokenInput = input("Ingest token", config.token, password = true)
        backfillInput = input("Backfill start (YYYY-MM-DD)", config.backfillStart)

        fun button(label: String, onClick: () -> Unit) = Button(this).apply {
            text = label
            setOnClickListener { onClick() }
            root.addView(this, wrap())
        }
        button("Grant Health Connect permissions") { onGrantClicked() }
        button("Sync now") { onSyncClicked() }
        button("Diagnostic dump (gate check)") { onDiagnosticClicked() }
        button("Reset delivery state") {
            config.resetSyncState()
            append("Delivery state cleared — next sync re-pushes the whole backfill window (server dedups by UID).")
        }

        statusView = TextView(this).apply {
            textSize = 12f
            setTextIsSelectable(true)
            setPadding(0, 24, 0, 0)
        }
        val scroll = ScrollView(this).apply { addView(statusView, wrap()) }
        root.addView(scroll, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        return root
    }

    private fun wrap() = LinearLayout.LayoutParams(
        ViewGroup.LayoutParams.MATCH_PARENT,
        ViewGroup.LayoutParams.WRAP_CONTENT,
    )

    /** Persists the three config fields; reports whether the config is usable. */
    private fun saveConfig(): Boolean {
        config.serverBase = urlInput.text.toString()
        config.token = tokenInput.text.toString()
        config.backfillStart = backfillInput.text.toString()
        return if (config.isConfigured()) true else {
            append("Config incomplete: need an http(s) URL, a token, and a YYYY-MM-DD backfill date.")
            false
        }
    }

    private fun onGrantClicked() {
        lifecycleScope.launch {
            val client = clientOrNull() ?: return@launch
            val granted = client.permissionController.getGrantedPermissions()
            if (granted.containsAll(BridgePermissions.ALL)) {
                append("All ${BridgePermissions.ALL.size} permissions already granted.")
            } else {
                append("Requesting permissions from Health Connect…")
                permissionLauncher.launch(BridgePermissions.ALL)
            }
        }
    }

    private fun onSyncClicked() {
        if (!saveConfig()) return
        append("Syncing…")
        lifecycleScope.launch {
            val outcome = try {
                SyncEngine(applicationContext).sync { line -> runOnUiThread { append("   $line") } }
            } catch (e: Exception) {
                Log.e(TAG, "sync failed", e)
                append("ERROR: ${e.javaClass.simpleName}: ${e.message}")
                return@launch
            }
            append(outcome.summary)
            if (outcome.ok || outcome.retry) {
                SyncWorker.schedule(applicationContext)
                append("Background sync scheduled (every 6 h, on network).")
            }
        }
    }

    // ── diagnostic dump: the original spike read, kept for the 1.4 Samsung gate ──

    private fun onDiagnosticClicked() {
        lifecycleScope.launch {
            val client = clientOrNull() ?: return@launch
            val granted = client.permissionController.getGrantedPermissions()
            if (!granted.containsAll(BridgePermissions.ALL)) {
                append("Grant permissions first (${granted.size}/${BridgePermissions.ALL.size}).")
                return@launch
            }
            append("Reading the last $DIAGNOSTIC_LOOKBACK_DAYS days…")
            try {
                val (json, summary) = withContext(Dispatchers.IO) { diagnosticRead(client) }
                summary.lines().forEach { append(it) }
                dumpJson(json)
            } catch (e: Exception) {
                Log.e(TAG, "diagnostic read failed", e)
                append("ERROR: ${e.javaClass.simpleName}: ${e.message}")
            }
        }
    }

    private suspend fun diagnosticRead(client: HealthConnectClient): Pair<JSONObject, String> {
        val now = Instant.now()
        val since = now.minus(Duration.ofDays(DIAGNOSTIC_LOOKBACK_DAYS))
        val reader = RunReader(client)

        val sessions = reader.readSessions(since, now)
        val runs = sessions.map { reader.readRun(it) }
        val rhr = reader.readRestingHr(since, now)

        val out = JSONArray()
        val sourceCounts = linkedMapOf<String, Int>()
        for (run in runs) {
            sourceCounts[run.sourcePackage] = (sourceCounts[run.sourcePackage] ?: 0) + 1
            out.put(JSONObject().apply {
                put("sessionUid", run.sessionUid)
                put("sourcePackage", run.sourcePackage)
                put("isSamsungHealth", run.isSamsungHealth())
                put("sportType", run.sportType)
                put("startTimeLocal", run.startTimeLocal())
                put("durationS", run.durationS)
                put("distanceM", run.distanceM)
                put("avgHr", run.avgHr ?: JSONObject.NULL)
                put("maxHr", run.maxHr ?: JSONObject.NULL)
                put("avgSpeed", run.avgSpeedMps ?: JSONObject.NULL)
                put("elevationGainM", run.elevationGainM ?: JSONObject.NULL)
                put("activeKcal", run.activeKcal ?: JSONObject.NULL)
                put("totalKcal", run.totalKcal ?: JSONObject.NULL)
                put("steps", run.steps ?: JSONObject.NULL)
                put("hrSampleCount", run.hrSeries.size)
                put("speedSampleCount", run.speedSeries.size)
                put("delivered", run.sessionUid in config.pushedUids)
            })
        }
        val root = JSONObject()
            .put("runs", out)
            .put("restingHeartRate", JSONArray().apply {
                rhr.forEach { put(JSONObject().put("date", it.date).put("bpm", it.bpm)) }
            })

        val shealthCount = sourceCounts[RunReader.SHEALTH_PKG] ?: 0
        val summary = buildString {
            appendLine("Running sessions: ${runs.size}. Sources:")
            if (sourceCounts.isEmpty()) appendLine("   (none)")
            sourceCounts.forEach { (pkg, n) ->
                appendLine("   $pkg : $n" + if (pkg == RunReader.SHEALTH_PKG) "  <-- SAMSUNG HEALTH" else "")
            }
            appendLine(
                if (shealthCount > 0)
                    "GATE: YES — $shealthCount Samsung Health run(s) visible via Health Connect."
                else
                    "GATE: NO Samsung Health runs found in this window."
            )
            appendLine("Resting HR days: ${rhr.size}" +
                (if (rhr.isNotEmpty()) " (latest ${rhr.last().bpm} bpm on ${rhr.last().date})" else ""))
        }.trimEnd()

        return root to summary
    }

    private fun dumpJson(root: JSONObject) {
        val pretty = root.toString(2)
        Log.i(TAG, "===== BEGIN JSON =====")
        pretty.chunked(3500).forEachIndexed { i, chunk -> Log.i(TAG, "[$i] $chunk") }
        Log.i(TAG, "===== END JSON =====")

        val dir: File? = getExternalFilesDir(null)
        if (dir == null) {
            append("External files dir unavailable; JSON only in Logcat.")
            return
        }
        val file = File(dir, OUTPUT_FILE)
        file.writeText(pretty)
        append("Wrote JSON to ${file.absolutePath}")
        append("Pull with:  adb pull ${file.absolutePath}")
    }

    private fun clientOrNull(): HealthConnectClient? {
        return if (HealthConnectClient.getSdkStatus(this) == HealthConnectClient.SDK_AVAILABLE) {
            HealthConnectClient.getOrCreate(this)
        } else {
            append("Health Connect not available.")
            null
        }
    }

    private fun append(line: String) {
        Log.i(TAG, line)
        runOnUiThread { statusView.append(line + "\n") }
    }
}
