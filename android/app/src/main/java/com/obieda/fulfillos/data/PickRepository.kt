package com.obieda.fulfillos.data

import com.obieda.fulfillos.domain.ConnectivityState
import com.obieda.fulfillos.domain.PendingPickEvent
import com.obieda.fulfillos.domain.TaskSnapshot
import java.util.UUID
import java.util.concurrent.Executors

sealed interface PickSyncResult {
    data class Acked(val snapshot: TaskSnapshot, val eventId: String) : PickSyncResult
    data class Queued(val eventId: String, val reason: String) : PickSyncResult
    data class Conflict(val snapshot: TaskSnapshot?, val message: String) : PickSyncResult
    data object AuthenticationRequired : PickSyncResult
}

class PickRepository(
    private val events: PendingEventStore,
    private val api: ApiClient,
    private val connectivity: ConnectivityMonitor,
    private val sessions: SessionManager,
) {
    private val io = Executors.newSingleThreadExecutor()

    fun createPick(
        taskId: String,
        taskItemId: String,
        locationId: String,
        productId: String,
        qty: Int,
        barcode: String?,
        onResult: (PickSyncResult) -> Unit,
    ) {
        val event = PendingPickEvent(
            eventId = UUID.randomUUID().toString(),
            taskId = taskId,
            clientSeq = events.nextClientSeq(taskId),
            taskItemId = taskItemId,
            locationId = locationId,
            productId = productId,
            qty = qty,
            barcode = barcode,
            createdAtEpochMs = System.currentTimeMillis(),
            state = PendingPickEvent.State.PENDING,
        )
        events.persistBeforeNetwork(event)
        if (connectivity.state != ConnectivityState.ONLINE) {
            onResult(PickSyncResult.Queued(event.eventId, "Offline • scan safely queued"))
            return
        }
        flush(taskId, onResult)
    }

    fun flush(taskId: String? = null, onResult: (PickSyncResult) -> Unit = {}) {
        if (connectivity.state != ConnectivityState.ONLINE) return
        io.execute {
            for (event in events.pending(taskId)) {
                events.mark(event.eventId, PendingPickEvent.State.SENDING)
                var response = runCatching { api.postPick(event) }.getOrElse {
                    events.mark(event.eventId, PendingPickEvent.State.PENDING)
                    onResult(PickSyncResult.Queued(event.eventId, "Network error • retry pending"))
                    return@execute
                }

                if (response.code == 401 && sessions.refreshBlocking()) {
                    response = runCatching { api.postPick(event) }.getOrElse {
                        events.mark(event.eventId, PendingPickEvent.State.PENDING)
                        onResult(PickSyncResult.Queued(event.eventId, "Reconnect succeeded but send failed"))
                        return@execute
                    }
                }

                when (response.code) {
                    in 200..299 -> {
                        events.mark(event.eventId, PendingPickEvent.State.ACKED)
                        val snapshot = api.parsePickSnapshot(response.body)
                        onResult(PickSyncResult.Acked(snapshot, event.eventId))
                    }
                    401 -> {
                        events.mark(event.eventId, PendingPickEvent.State.PENDING)
                        onResult(PickSyncResult.AuthenticationRequired)
                        return@execute
                    }
                    409 -> {
                        events.mark(event.eventId, PendingPickEvent.State.REJECTED)
                        onResult(
                            PickSyncResult.Conflict(
                                snapshot = api.parseConflictSnapshot(response.body),
                                message = api.parseConflictMessage(response.body),
                            )
                        )
                        return@execute
                    }
                    else -> {
                        events.mark(event.eventId, PendingPickEvent.State.PENDING)
                        onResult(PickSyncResult.Queued(event.eventId, "Server unavailable (${response.code}) • retry pending"))
                        return@execute
                    }
                }
            }
        }
    }
}
