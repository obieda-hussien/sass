package com.obieda.fulfillos.data

import android.content.Context
import androidx.work.Worker
import androidx.work.WorkerParameters
import com.obieda.fulfillos.FulfillApplication

class SyncWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        val graph = (applicationContext as FulfillApplication).graph
        val recovered = graph.sessions.recoverBlocking().getOrNull()
        if (recovered == null) return Result.retry()
        graph.picks.flush()
        graph.operations.flush()
        return Result.success()
    }
}
