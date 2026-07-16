package com.splits.healthspike

import androidx.health.connect.client.HealthConnectClient
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
import java.time.Duration
import java.time.Instant
import java.time.ZoneId
import java.time.ZoneOffset
import kotlin.reflect.KClass

data class HrSample(val tSec: Long, val bpm: Long)
data class SpeedSample(val tSec: Long, val mps: Double)

/** One running session, fully read and normalized — the ingest payload's source of truth. */
data class BridgeRun(
    val sessionUid: String,
    val sourcePackage: String,
    val sportType: String, // "running" | "treadmill_running" (builder label keys)
    val startTime: Instant,
    val startOffset: ZoneOffset?,
    val endTime: Instant,
    val durationS: Long,
    val distanceM: Double,
    val avgHr: Double?,
    val maxHr: Long?,
    val avgSpeedMps: Double?,
    // Delta metrics: null = the provider wrote no records at all (Samsung writes
    // neither elevation nor steps) — distinct from a written 0 on a flat run.
    val elevationGainM: Double?,
    val activeKcal: Double?,
    val totalKcal: Double?,
    val steps: Long?,
    val hrSeries: List<HrSample>,
    val speedSeries: List<SpeedSample>,
) {
    /** Local wall time, no offset suffix — the ingest contract's startTimeLocal. */
    fun startTimeLocal(): String {
        val offset = startOffset ?: ZoneId.systemDefault().rules.getOffset(startTime)
        return startTime.atOffset(offset).toLocalDateTime().withNano(0).toString()
    }

    fun isSamsungHealth() = sourcePackage == RunReader.SHEALTH_PKG
}

data class RhrDay(val date: String, val bpm: Long)

/**
 * All Health Connect reads for the bridge. Every per-session metric read is
 * filtered by the session's own dataOrigin (design D14, MANDATORY): multiple
 * apps write into the same window and unfiltered delta reads double-count.
 */
class RunReader(private val client: HealthConnectClient) {

    companion object {
        const val SHEALTH_PKG = "com.sec.android.app.shealth"
        const val SERIES_DOWNSAMPLE_SEC = 5L
    }

    /** Every exercise session in [since, until) regardless of type, oldest first (diagnostics). */
    suspend fun readAllSessions(since: Instant, until: Instant): List<ExerciseSessionRecord> =
        readAll(ExerciseSessionRecord::class, TimeRangeFilter.between(since, until))
            .sortedBy { it.endTime }

    /** Running sessions in [since, until), oldest first. */
    suspend fun readSessions(since: Instant, until: Instant): List<ExerciseSessionRecord> =
        readAllSessions(since, until)
            .filter {
                it.exerciseType == ExerciseSessionRecord.EXERCISE_TYPE_RUNNING ||
                    it.exerciseType == ExerciseSessionRecord.EXERCISE_TYPE_RUNNING_TREADMILL
            }

    /** Reads and joins every metric for one session (origin-filtered). */
    suspend fun readRun(run: ExerciseSessionRecord): BridgeRun {
        val range = TimeRangeFilter.between(run.startTime, run.endTime)
        val origin = setOf(DataOrigin(run.metadata.dataOrigin.packageName))

        val hrSamples = readAll(HeartRateRecord::class, range, origin)
            .flatMap { it.samples }
            .sortedBy { it.time }
        val distanceRecords = readAll(DistanceRecord::class, range, origin)
        val speedSamples = readAll(SpeedRecord::class, range, origin)
            .flatMap { it.samples }
            .sortedBy { it.time }
        val elevRecs = readAll(ElevationGainedRecord::class, range, origin)
        val activeRecs = readAll(ActiveCaloriesBurnedRecord::class, range, origin)
        val totalRecs = readAll(TotalCaloriesBurnedRecord::class, range, origin)
        val stepRecs = readAll(StepsRecord::class, range, origin)

        val start = run.startTime.epochSecond
        val hrSeries = mutableListOf<HrSample>()
        var lastHr = Long.MIN_VALUE
        for (s in hrSamples) {
            val tSec = s.time.epochSecond - start
            if (tSec < 0) continue
            if (lastHr == Long.MIN_VALUE || tSec - lastHr >= SERIES_DOWNSAMPLE_SEC) {
                hrSeries.add(HrSample(tSec, s.beatsPerMinute)); lastHr = tSec
            }
        }
        val speedSeries = mutableListOf<SpeedSample>()
        var lastSpd = Long.MIN_VALUE
        for (s in speedSamples) {
            val tSec = s.time.epochSecond - start
            if (tSec < 0) continue
            if (lastSpd == Long.MIN_VALUE || tSec - lastSpd >= SERIES_DOWNSAMPLE_SEC) {
                speedSeries.add(SpeedSample(tSec, round2(s.speed.inMetersPerSecond))); lastSpd = tSec
            }
        }

        return BridgeRun(
            sessionUid = run.metadata.id,
            sourcePackage = run.metadata.dataOrigin.packageName,
            sportType = if (run.exerciseType == ExerciseSessionRecord.EXERCISE_TYPE_RUNNING_TREADMILL)
                "treadmill_running" else "running",
            startTime = run.startTime,
            startOffset = run.startZoneOffset,
            endTime = run.endTime,
            durationS = Duration.between(run.startTime, run.endTime).seconds,
            distanceM = round1(distanceRecords.sumOf { it.distance.inMeters }),
            avgHr = if (hrSamples.isEmpty()) null
                else round1(hrSamples.map { it.beatsPerMinute }.average()),
            maxHr = hrSamples.maxOfOrNull { it.beatsPerMinute },
            avgSpeedMps = if (speedSamples.isEmpty()) null
                else round2(speedSamples.map { it.speed.inMetersPerSecond }.average()),
            elevationGainM = if (elevRecs.isEmpty()) null else round1(elevRecs.sumOf { it.elevation.inMeters }),
            activeKcal = if (activeRecs.isEmpty()) null else round1(activeRecs.sumOf { it.energy.inKilocalories }),
            totalKcal = if (totalRecs.isEmpty()) null else round1(totalRecs.sumOf { it.energy.inKilocalories }),
            steps = if (stepRecs.isEmpty()) null else stepRecs.sumOf { it.count },
            hrSeries = hrSeries,
            speedSeries = speedSeries,
        )
    }

    /** Daily resting-HR records in the window as local YYYY-MM-DD days (last write per day wins). */
    suspend fun readRestingHr(since: Instant, until: Instant): List<RhrDay> {
        val recs = readAll(RestingHeartRateRecord::class, TimeRangeFilter.between(since, until))
            .sortedBy { it.time }
        val byDate = LinkedHashMap<String, Long>()
        for (r in recs) {
            val offset = r.zoneOffset ?: ZoneId.systemDefault().rules.getOffset(r.time)
            byDate[r.time.atOffset(offset).toLocalDate().toString()] = r.beatsPerMinute
        }
        return byDate.map { (date, bpm) -> RhrDay(date, bpm) }
    }

    /** Reads every page of [recordType] in [range] (default pageSize is 1000, so HR needs paging). */
    private suspend fun <T : Record> readAll(
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

    private fun round1(v: Double) = Math.round(v * 10.0) / 10.0
    private fun round2(v: Double) = Math.round(v * 100.0) / 100.0
}
