package com.splits.healthspike

import android.content.Context
import android.util.Log
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import java.util.concurrent.TimeUnit

/**
 * Background recurring sync (set-and-forget). WorkManager runs it roughly every
 * 6 hours when the network is up; a transient push failure returns retry() so
 * WorkManager backs off and re-runs — combined with the pushed-UID bookkeeping
 * in SyncEngine, an unreachable server never loses a run.
 */
class SyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val outcome = try {
            SyncEngine(applicationContext).sync()
        } catch (e: Exception) {
            Log.e(TAG, "sync crashed", e)
            return Result.retry()
        }
        Log.i(TAG, "background sync: ${outcome.summary}")
        return when {
            outcome.retry -> Result.retry()
            else -> Result.success()
        }
    }

    companion object {
        private const val TAG = "SPLITS_BRIDGE"
        private const val UNIQUE_NAME = "splits-bridge-sync"

        fun schedule(context: Context) {
            val request = PeriodicWorkRequestBuilder<SyncWorker>(6, TimeUnit.HOURS)
                .setConstraints(
                    Constraints.Builder()
                        .setRequiredNetworkType(NetworkType.CONNECTED)
                        .build()
                )
                .build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                UNIQUE_NAME,
                ExistingPeriodicWorkPolicy.UPDATE,
                request,
            )
        }
    }
}
