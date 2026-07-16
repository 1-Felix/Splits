package com.splits.healthspike

import android.content.Context
import java.time.LocalDate

/**
 * Bridge configuration + sync bookkeeping, SharedPreferences-backed so the
 * server URL / token / backfill window are settable without rebuilding the app
 * (healthconnect-bridge requirement). Delivery state:
 *  - pushedUids: session UIDs the server has acknowledged — every sync re-scans
 *    the whole backfill window and pushes only unseen UIDs, so late-syncing
 *    watch workouts can never be skipped and a failed push (UID never marked)
 *    is retried on the next sync. The server upserts by UID, so an overlap
 *    re-push is harmless by construction.
 *  - rhrSyncedThrough: last date the daily resting-HR series is delivered up
 *    to; each sync re-reads a 7-day overlap because RHR rows can be written late.
 */
class BridgeConfig(context: Context) {

    private val prefs = context.applicationContext
        .getSharedPreferences("splits-bridge", Context.MODE_PRIVATE)

    var serverBase: String
        get() = prefs.getString("serverBase", "") ?: ""
        set(v) = prefs.edit().putString("serverBase", v.trim()).apply()

    var token: String
        get() = prefs.getString("token", "") ?: ""
        set(v) = prefs.edit().putString("token", v.trim()).apply()

    /** YYYY-MM-DD — first-run backfill reaches back to this date. */
    var backfillStart: String
        get() = prefs.getString("backfillStart", "") ?: ""
        set(v) = prefs.edit().putString("backfillStart", v.trim()).apply()

    var rhrSyncedThrough: String
        get() = prefs.getString("rhrSyncedThrough", "") ?: ""
        set(v) = prefs.edit().putString("rhrSyncedThrough", v).apply()

    var lastSyncSummary: String
        get() = prefs.getString("lastSyncSummary", "") ?: ""
        set(v) = prefs.edit().putString("lastSyncSummary", v).apply()

    val pushedUids: Set<String>
        get() = prefs.getStringSet("pushedUids", emptySet()) ?: emptySet()

    /** Persisted immediately after each acknowledged push — a crash loses nothing. */
    fun markPushed(uid: String) {
        prefs.edit().putStringSet("pushedUids", pushedUids + uid).apply()
    }

    fun resetSyncState() {
        prefs.edit().remove("pushedUids").remove("rhrSyncedThrough").apply()
    }

    fun backfillStartDate(): LocalDate? = try {
        LocalDate.parse(backfillStart)
    } catch (_: Exception) {
        null
    }

    fun isConfigured(): Boolean =
        (serverBase.startsWith("http://") || serverBase.startsWith("https://")) &&
            token.isNotEmpty() && backfillStartDate() != null
}
