package com.obieda.fulfillos.domain

data class SessionInfo(
    val accessToken: String,
    val refreshToken: String,
    val userId: String,
    val username: String,
    val role: String,
    val deviceId: String,
)

data class TaskItem(
    val id: String,
    val productId: String,
    val asin: String?,
    val title: String,
    val barcodes: List<String>,
    val temperatureClass: String?,
    val handlingClass: String?,
    val locationId: String,
    val plannedQty: Int,
    val pickedQty: Int,
    val remainingQty: Int,
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
    val shortedUnits: Int,
    val processedUnits: Int,
    val remainingUnits: Int,
    val recoveryRequired: Boolean,
    val offerExpiresAt: String? = null,
    val items: List<TaskItem>,
) {
    val currentItem: TaskItem?
        get() = items.firstOrNull { it.remainingQty > 0 }
}

data class PendingPickEvent(
    val eventId: String,
    val taskId: String,
    val clientSeq: Long,
    val taskItemId: String,
    val locationId: String,
    val productId: String,
    val qty: Int,
    val barcode: String?,
    val kind: Kind,
    val reason: String?,
    val createdAtEpochMs: Long,
    val state: State,
) {
    enum class Kind { PICK, SHORT }
    enum class State { PENDING, SENDING, ACKED, REJECTED }
}

data class InventoryRow(
    val primary: String,
    val secondary: String,
    val quantity: Int,
)

data class InventoryLookup(
    val heading: String,
    val subheading: String,
    val total: Int?,
    val rows: List<InventoryRow>,
)

enum class ConnectivityState { ONLINE, OFFLINE, RECONNECTING }
enum class AppScreen { HOME, PICK, INVENTORY }
enum class PickScanPhase { BIN, ITEM, SYNCING, DONE }


data class PendingOperationEvent(
    val eventId: String,
    val kind: Kind,
    val resourceId: String?,
    val productId: String,
    val qty: Int,
    val sourceLocationId: String?,
    val destinationLocationId: String?,
    val reason: String?,
    val createdAtEpochMs: Long,
    val state: State,
) {
    enum class Kind { UNPACK_SCAN, BOH_MOVE, DAMAGE, RECOVERY_STOW }
    enum class State { PENDING, SENDING, ACKED, REJECTED }
}

data class UnpackItemRecommendation(
    val productId: String,
    val qty: Int,
    val compatibleDestinations: List<String>,
)

data class UnpackSummary(
    val sessionId: String,
    val status: String,
    val temperatureClass: String,
    val toteLocationId: String,
    val items: List<UnpackItemRecommendation>,
)

data class BarcodeProduct(
    val barcode: String,
    val productId: String,
    val asin: String,
    val title: String,
    val temperatureClass: String,
    val handlingClass: String,
)

enum class OperationMode { UNPACK, BOH, DAMAGE }
