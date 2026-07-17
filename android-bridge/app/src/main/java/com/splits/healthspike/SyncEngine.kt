package com.splits.healthspike

import android.content.Context
import android.util.Log
import androidx.health.connect.client.HealthConnectClient
import java.time.Duration
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

/**
 * One sync pass: scan the backfill window for running sessions, push every one
 * the server hasn't acknowledged yet (idempotent by session UID), then push the
 * resting-HR window. Shared by the foreground "Sync now" button and the
 * background SyncWorker.
 */
class SyncEngine(private val context: Context) {

    companion object {
        private const val TAG = "SPLITS_BRIDGE"
        // A session that ended moments ago may still be receiving samples from
        // the watch sync — leave it for the next pass.
        private val SESSION_SETTLE: Duration = Duration.ofMinutes(10)
        private val RHR_OVERLAP_DAYS = 7L
    }

    /** [completed] = the pass ran to the end (even with rejected runs) — as
     *  opposed to the preflight failures (unconfigured / SDK / permissions)
     *  where scheduling background sync would be pointless. */
    data class Outcome(val ok: Boolean, val retry: Boolean, val summary: String,
                       val completed: Boolean = false)

    suspend fun sync(log: (String) -> Unit = {}): Outcome {
        val config = BridgeConfig(context)
        if (!config.isConfigured()) {
            return Outcome(false, retry = false, summary = "Not configured (need server URL, token, backfill date).")
        }
        if (HealthConnectClient.getSdkStatus(context) != HealthConnectClient.SDK_AVAILABLE) {
            return Outcome(false, retry = false, summary = "Health Connect SDK unavailable.")
        }
        val client = HealthConnectClient.getOrCreate(context)
        val granted = client.permissionController.getGrantedPermissions()
        if (!granted.containsAll(BridgePermissions.ALL)) {
            return Outcome(false, retry = false,
                summary = "Missing ${BridgePermissions.ALL.size - granted.intersect(BridgePermissions.ALL).size} Health Connect permission(s) — open the app and grant.")
        }

        val zone = ZoneId.systemDefault()
        val backfillStart = config.backfillStartDate()!!.atStartOfDay(zone).toInstant()
        val now = Instant.now()
        val reader = RunReader(client)
        val ingest = IngestClient(config.serverBase, config.token)

        val sessions = reader.readSessions(backfillStart, now)
        val settled = sessions.filter { Duration.between(it.endTime, now) >= SESSION_SETTLE }
        val pending = settled.filter { it.metadata.id !in config.pushedUids }
        log("Sessions in window: ${sessions.size}, settled: ${settled.size}, to push: ${pending.size}")

        var pushed = 0
        var rejected = 0
        var skipped = 0
        for (session in pending) {
            val run = reader.readRun(session)
            if (run.durationS <= 0 || run.distanceM <= 0.0) {
                skipped++
                log("skip ${run.sessionUid.take(8)}… (${run.startTimeLocal()}): zero duration/distance")
                continue
            }
            when (val result = ingest.pushRun(run)) {
                is IngestClient.PushResult.Ok -> {
                    config.markPushed(run.sessionUid)
                    pushed++
                    log("pushed ${run.startTimeLocal()} ${"%.1f".format(run.distanceM / 1000)} km (${run.sourcePackage})")
                }
                is IngestClient.PushResult.Rejected -> {
                    rejected++
                    Log.w(TAG, "run ${run.sessionUid} rejected ${result.code}: ${result.error}")
                    log("REJECTED ${run.startTimeLocal()}: ${result.code} ${result.error}")
                }
                is IngestClient.PushResult.Transient -> {
                    val summary = "Server unreachable (${result.reason}) after $pushed push(es) — will retry."
                    config.lastSyncSummary = stamped(summary)
                    return Outcome(false, retry = true, summary = summary)
                }
            }
        }

        // Daily resting-HR series (feeds Karvonen zones + the RHR trend card).
        var rhrDays = 0
        val rhrFrom = maxOf(
            backfillStart,
            rhrSyncedFrom(config, zone) ?: backfillStart,
        )
        val rhr = reader.readRestingHr(rhrFrom, now)
        if (rhr.isNotEmpty()) {
            when (val result = ingest.pushRhr(rhr)) {
                is IngestClient.PushResult.Ok -> {
                    rhrDays = rhr.size
                    config.rhrSyncedThrough = LocalDate.now(zone).toString()
                }
                is IngestClient.PushResult.Rejected ->
                    log("RHR REJECTED: ${result.code} ${result.error}")
                is IngestClient.PushResult.Transient -> {
                    val summary = "Runs done ($pushed pushed) but RHR push failed (${result.reason}) — will retry."
                    config.lastSyncSummary = stamped(summary)
                    return Outcome(false, retry = true, summary = summary)
                }
            }
        }

        val summary = buildString {
            append("Pushed $pushed run(s)")
            if (rejected > 0) append(", $rejected rejected")
            if (skipped > 0) append(", $skipped skipped")
            append(", $rhrDays RHR day(s). ")
            append("${config.pushedUids.size} run(s) delivered in total.")
        }
        config.lastSyncSummary = stamped(summary)
        Log.i(TAG, summary)
        return Outcome(ok = rejected == 0, retry = false, summary = summary, completed = true)
    }

    private fun rhrSyncedFrom(config: BridgeConfig, zone: ZoneId): Instant? = try {
        LocalDate.parse(config.rhrSyncedThrough)
            .minusDays(RHR_OVERLAP_DAYS)
            .atStartOfDay(zone)
            .toInstant()
    } catch (_: Exception) {
        null
    }

    private fun stamped(s: String) = "${Instant.now().atZone(ZoneId.systemDefault()).toLocalDateTime().withNano(0)}: $s"
}
