package com.obieda.fulfillos.domain

data class PickLine(
    val id: String,
    val sequence: Int,
    val sku: String,
    val title: String,
    val locationCode: String,
    val requiredQty: Int,
    val pickedQty: Int,
    val shortQty: Int,
) {
    val remainingQty: Int
        get() = (requiredQty - pickedQty - shortQty).coerceAtLeast(0)
}

data class PickTask(
    val id: String,
    val state: String,
    val version: Int,
    val associateId: String?,
    val lines: List<PickLine>,
) {
    val totalUnits: Int get() = lines.sumOf { it.requiredQty }
    val pickedUnits: Int get() = lines.sumOf { it.pickedQty }
    val nextLine: PickLine? get() = lines.firstOrNull { it.remainingQty > 0 }
}

data class PendingScan(
    val eventId: String,
    val taskId: String,
    val taskLineId: String,
    val associateId: String,
    val deviceId: String,
    val clientSequence: Int,
    val clientTaskVersion: Int,
    val locationCode: String,
    val barcode: String,
    val quantity: Int,
    val createdAtEpochMs: Long,
)

enum class ConnectivityState {
    ONLINE,
    RECONNECTING,
    OFFLINE,
}

sealed interface UiMode {
    data object Waiting : UiMode
    data class Offered(val task: PickTask, val secondsRemaining: Int) : UiMode
    data class Picking(val task: PickTask) : UiMode
    data class Recovery(val message: String, val task: PickTask?) : UiMode
}
