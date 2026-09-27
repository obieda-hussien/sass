package com.obieda.fulfillos.data

import com.obieda.fulfillos.domain.ConnectivityState
import com.obieda.fulfillos.domain.PendingOperationEvent
import java.util.UUID
import java.util.concurrent.Executors

sealed interface OperationSyncResult {
    data class Acked(
        val eventId: String,
        val kind: PendingOperationEvent.Kind,
        val responseBody: String,
    ) : OperationSyncResult

    data class Queued(val eventId: String, val reason: String) : OperationSyncResult
    data class Rejected(val eventId: String, val message: String) : OperationSyncResult
    data object AuthenticationRequired : OperationSyncResult
}

class OperationsRepository(
    private val events: PendingOperationStore,
    private val api: ApiClient,
    private val connectivity: ConnectivityMonitor,
    private val sessions: SessionManager,
) {
    private val io = Executors.newSingleThreadExecutor()

    fun enqueue(
        kind: PendingOperationEvent.Kind,
        resourceId: String? = null,
        productId: String,
        qty: Int,
        sourceLocationId: String? = null,
        destinationLocationId: String? = null,
        reason: String? = null,
        onResult: (OperationSyncResult) -> Unit = {},
    ) {
        val event = PendingOperationEvent(
            eventId = UUID.randomUUID().toString(),
            kind = kind,
            resourceId = resourceId,
            productId = productId,
            qty = qty,
            sourceLocationId = sourceLocationId,
            destinationLocationId = destinationLocationId,
            reason = reason,
            createdAtEpochMs = System.currentTimeMillis(),
            state = PendingOperationEvent.State.PENDING,
        )
        // Same invariant as picking: make the event durable before the first packet leaves the PDA.
        events.persistBeforeNetwork(event)
        if (connectivity.state != ConnectivityState.ONLINE) {
            onResult(OperationSyncResult.Queued(event.eventId, "Offline • operation safely queued"))
            return
        }
        flush(onResult)
    }

    fun flush(onResult: (OperationSyncResult) -> Unit = {}) {
        if (connectivity.state != ConnectivityState.ONLINE) return
        io.execute {
            for (event in events.pending()) {
                events.mark(event.eventId, PendingOperationEvent.State.SENDING)
                var response = runCatching { api.postOperation(event) }.getOrElse {
                    events.mark(event.eventId, PendingOperationEvent.State.PENDING)
                    onResult(OperationSyncResult.Queued(event.eventId, "Network error • retry pending"))
                    return@execute
                }

                if (response.code == 401 && sessions.refreshBlocking()) {
                    response = runCatching { api.postOperation(event) }.getOrElse {
                        events.mark(event.eventId, PendingOperationEvent.State.PENDING)
                        onResult(OperationSyncResult.Queued(event.eventId, "Session restored • retry pending"))
                        return@execute
                    }
                }

                when (response.code) {
                    in 200..299 -> {
                        events.mark(event.eventId, PendingOperationEvent.State.ACKED)
                        onResult(OperationSyncResult.Acked(event.eventId, event.kind, response.body))
                    }
                    401 -> {
                        events.mark(event.eventId, PendingOperationEvent.State.PENDING)
                        onResult(OperationSyncResult.AuthenticationRequired)
                        return@execute
                    }
                    409, 400, 404 -> {
                        events.mark(event.eventId, PendingOperationEvent.State.REJECTED)
                        onResult(
                            OperationSyncResult.Rejected(
                                event.eventId,
                                api.parseConflictMessage(response.body),
                            )
                        )
                    }
                    else -> {
                        events.mark(event.eventId, PendingOperationEvent.State.PENDING)
                        onResult(OperationSyncResult.Queued(event.eventId, "Server unavailable (${response.code}) • retry pending"))
                        return@execute
                    }
                }
            }
        }
    }
}
