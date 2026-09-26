package com.obieda.fulfillos.data

import com.obieda.fulfillos.domain.PendingPickEvent
import java.util.UUID
import java.util.concurrent.Executors

class PickRepository(
    private val events: PendingEventStore,
    private val api: ApiClient,
    private val connectivity: ConnectivityMonitor,
) {
    private val io = Executors.newSingleThreadExecutor()

    fun createPick(
        taskId: String,
        taskItemId: String,
        locationId: String,
        productId: String,
        qty: Int,
        barcode: String?,
        onResult: (String) -> Unit,
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
        // Critical invariant: durable first, network second.
        events.persistBeforeNetwork(event)
        onResult("Pending sync • ${event.eventId.take(8)}")
        flush(taskId, onResult)
    }

    fun flush(taskId: String? = null, onResult: (String) -> Unit = {}) {
        if (connectivity.state != com.obieda.fulfillos.domain.ConnectivityState.ONLINE) {
            onResult("Offline • events safely queued")
            return
        }
        io.execute {
            for (event in events.pending(taskId)) {
                events.mark(event.eventId, PendingPickEvent.State.SENDING)
                val result = runCatching { api.postPick(event) }.getOrElse {
                    events.mark(event.eventId, PendingPickEvent.State.PENDING)
                    onResult("Network error • will retry")
                    return@execute
                }
                when (result.code) {
                    in 200..299 -> {
                        events.mark(event.eventId, PendingPickEvent.State.ACKED)
                        onResult("Server confirmed • ${event.eventId.take(8)}")
                    }
                    401 -> {
                        events.mark(event.eventId, PendingPickEvent.State.PENDING)
                        onResult("Session refresh required")
                        return@execute
                    }
                    409 -> {
                        events.mark(event.eventId, PendingPickEvent.State.REJECTED)
                        onResult("Reconciliation required • server state wins")
                        return@execute
                    }
                    else -> {
                        events.mark(event.eventId, PendingPickEvent.State.PENDING)
                        onResult("Server unavailable • will retry")
                        return@execute
                    }
                }
            }
        }
    }
}
