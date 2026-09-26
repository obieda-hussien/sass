package com.obieda.fulfillos.recovery

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.obieda.fulfillos.data.PendingEventStore
import com.obieda.fulfillos.data.SecureSessionStore

/**
 * Boot recovery intentionally does not invent task state locally.
 *
 * Once authenticated networking is wired in, this worker calls reconcile with the
 * durable pending IDs and only removes IDs confirmed by the server.
 */
class RecoveryWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result {
        val token = SecureSessionStore(applicationContext).readRefreshToken()
            ?: return Result.success()

        // Touch the durable store so the database is opened/recovered after an unclean reboot.
        val pending = PendingEventStore(applicationContext).list()
        if (token.isBlank()) return Result.success()

        // Network reconciliation is delegated to the repository in the next milestone.
        return if (pending.size >= 0) Result.success() else Result.retry()
    }
}
