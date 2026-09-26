package com.obieda.fulfillos.domain

data class TaskItem(
    val id: String,
    val productId: String,
    val locationId: String,
    val plannedQty: Int,
    val pickedQty: Int,
    val sequence: Int,
)

data class TaskSnapshot(
    val taskId: String,
    val orderId: String,
    val taskStatus: String,
    val orderStatus: String?,
    val serverVersion: Long,
    val clientHighWaterSeq: Long,
    val expectedUnits: Int,
    val pickedUnits: Int,
    val remainingUnits: Int,
    val recoveryRequired: Boolean,
    val items: List<TaskItem>,
)

data class PendingPickEvent(
    val eventId: String,
    val taskId: String,
    val clientSeq: Long,
    val taskItemId: String,
    val locationId: String,
    val productId: String,
    val qty: Int,
    val barcode: String?,
    val createdAtEpochMs: Long,
    val state: State,
) {
    enum class State { PENDING, SENDING, ACKED, REJECTED }
}

enum class ConnectivityState { ONLINE, OFFLINE, RECONNECTING }
