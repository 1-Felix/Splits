package com.splits.healthspike

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/**
 * POSTs payloads to a SPLITS instance's /api/ingest (serve.mjs), bearer-token
 * authed. Two payload forms ride the endpoint: a single run (has sessionUid)
 * and a daily resting-HR series (has restingHeartRate) — both idempotent
 * server-side (upsert by UID / by date), so re-pushing is always safe.
 */
class IngestClient(serverBase: String, private val token: String) {

    sealed class PushResult {
        data object Ok : PushResult()
        /** 4xx — the payload itself was refused; retrying the same bytes won't help. */
        data class Rejected(val code: Int, val error: String) : PushResult()
        /** Network failure or 5xx — retry on a later sync, nothing is lost. */
        data class Transient(val reason: String) : PushResult()
    }

    private val endpoint = serverBase.trimEnd('/') + "/api/ingest"

    suspend fun pushRun(run: BridgeRun): PushResult = post(runPayload(run))

    suspend fun pushRhr(days: List<RhrDay>): PushResult = post(JSONObject().put(
        "restingHeartRate",
        JSONArray().apply { days.forEach { put(JSONObject().put("date", it.date).put("bpm", it.bpm)) } },
    ))

    /** Maps a BridgeRun onto the ingest run contract (validateRunPayload's whitelist). */
    private fun runPayload(run: BridgeRun): JSONObject = JSONObject().apply {
        put("sessionUid", run.sessionUid)
        put("startTimeLocal", run.startTimeLocal())
        put("durationS", run.durationS)
        put("distanceM", run.distanceM)
        put("sportType", run.sportType)
        put("source", run.sourcePackage)
        // optional metrics: omitted when null (the server treats absent == null)
        run.avgHr?.let { put("avgHr", it) }
        run.maxHr?.let { put("maxHr", it) }
        run.avgSpeedMps?.let { put("avgSpeed", it) }
        run.elevationGainM?.let { put("elevationGainM", it) }
        run.activeKcal?.let { put("activeKcal", it) }
        run.totalKcal?.let { put("totalKcal", it) }
        run.steps?.let { put("steps", it) }
        put("hrSamples", JSONArray().apply {
            run.hrSeries.forEach { put(JSONObject().put("tSec", it.tSec).put("bpm", it.bpm)) }
        })
        put("speedSamples", JSONArray().apply {
            run.speedSeries.forEach { put(JSONObject().put("tSec", it.tSec).put("mps", it.mps)) }
        })
    }

    // Blocking I/O — confined to the IO dispatcher so callers on Main are safe.
    private suspend fun post(payload: JSONObject): PushResult = withContext(Dispatchers.IO) {
        val body = payload.toString().toByteArray(Charsets.UTF_8)
        try {
            val conn = URL(endpoint).openConnection() as HttpURLConnection
            try {
                conn.requestMethod = "POST"
                conn.connectTimeout = 15_000
                conn.readTimeout = 30_000
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json")
                conn.setRequestProperty("Authorization", "Bearer $token")
                conn.setFixedLengthStreamingMode(body.size)
                conn.outputStream.use { it.write(body) }
                val code = conn.responseCode
                when {
                    code in 200..299 -> PushResult.Ok
                    code in 400..499 -> PushResult.Rejected(code, errorBody(conn))
                    else -> PushResult.Transient("HTTP $code")
                }
            } finally {
                conn.disconnect()
            }
        } catch (e: IOException) {
            PushResult.Transient(e.message ?: e.javaClass.simpleName)
        }
    }

    private fun errorBody(conn: HttpURLConnection): String = try {
        val raw = conn.errorStream?.bufferedReader()?.use { it.readText() } ?: ""
        JSONObject(raw).optString("error", raw.take(200))
    } catch (_: Exception) {
        ""
    }
}
