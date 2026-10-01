package com.obieda.fulfillos.domain

data class SessionInfo(
    val accessToken: String,
    val refreshToken: String,
    val userId: String,
    val username: String,
    val role: String,
    val deviceId: String,
    val mustChangePassword: Boolean = false,
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
    enum class Kind { PICK, SHORT, SKIP, DAMAGED }
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
enum class AppScreen { HOME, ACTIVITY, PICK, INVENTORY, UNPACK, BOH, DAMAGE, CYCLE_COUNT, RECOVERY, RECEIVE, REPLENISHMENT }
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

data class UnpackManifestItem(
    val productId: String,
    val asin: String?,
    val title: String,
    val expectedQty: Int,
    val verifiedQty: Int,
    val missingQty: Int,
)

data class UnpackSummary(
    val sessionId: String,
    val status: String,
    val temperatureClass: String,
    val toteLocationId: String,
    val sourceRef: String?,
    val manifestLocked: Boolean,
    val expectedUnits: Int,
    val verifiedUnits: Int,
    val remainingUnits: Int,
    val completeReady: Boolean,
    val manifest: List<UnpackManifestItem>,
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

enum class OperationMode { UNPACK, BOH, DAMAGE, CYCLE_COUNT, RECOVERY, RECEIVE, REPLENISHMENT }
enum class OperationScanPhase { SOURCE, ITEM, DESTINATION, SYNCING }


data class PickOfferSummary(
    val task: TaskSnapshot,
    val expiresAt: String?,
)

data class ClosedBagSummary(
    val bagNo: Int,
    val spooLast4: String,
)

data class CompletionItem(
    val title: String,
    val requestedQty: Int,
    val pickedQty: Int,
    val shortedQty: Int,
)

data class OrderCompletionSummary(
    val orderId: String,
    val externalRef: String?,
    val pickerUsername: String?,
    val items: List<CompletionItem>,
    val bagCount: Int,
    val bags: List<ClosedBagSummary>,
    val pickedUnits: Int,
    val shortedUnits: Int,
)

data class WorkerOperationalState(
    val state: String,
    val activityRef: String?,
    val dispatchBlocked: Boolean,
)


data class RecoveryItem(
    val productId: String,
    val asin: String?,
    val title: String,
    val qty: Int,
    val sourceLocationId: String,
    val compatibleDestinations: List<String>,
)

data class RecoverySummary(
    val taskId: String,
    val orderId: String,
    val recoveryType: String,
    val sourceLocationId: String?,
    val items: List<RecoveryItem>,
)

data class CycleCountEntrySummary(
    val entryId: String,
    val productId: String,
    val systemQty: Int,
    val countedQty: Int,
    val variance: Int,
)

data class ShipmentLineSummary(
    val id: String,
    val productId: String,
    val expectedQty: Int,
    val receivedQty: Int,
    val damagedQty: Int,
    val missingQty: Int,
    val recommendedStow: List<String>,
    val title: String = productId,
    val barcode: String? = null,
)

data class ShipmentIssueSummary(
    val id: String,
    val issueType: String,
    val qty: Int,
    val notes: String,
    val status: String,
    val title: String?,
    val reportedBy: String,
)

data class StowTaskSummary(
    val id: String,
    val productId: String,
    val qty: Int,
    val status: String,
    val destinationLocationId: String?,
)

data class ShipmentSummary(
    val id: String,
    val label: String,
    val shipmentType: String,
    val storageDomain: String,
    val status: String,
    val expectedUnits: Int,
    val receivedUnits: Int,
    val damagedUnits: Int,
    val missingUnits: Int,
    val targetStowMinutes: Int,
    val elapsedMinutes: Int?,
    val stowOverdue: Boolean,
    val lines: List<ShipmentLineSummary>,
    val stowTasks: List<StowTaskSummary>,
    val supplierName: String? = null,
    val purchaseOrderRef: String? = null,
    val openingTemperatureC: Double? = null,
    val issues: List<ShipmentIssueSummary> = emptyList(),
    val receivingUsers: List<String> = emptyList(),
)

data class ReplenishmentSummary(
    val id: String,
    val productId: String,
    val asin: String?,
    val title: String,
    val sourceLocationId: String,
    val destinationLocationId: String,
    val qty: Int,
    val actualQty: Int,
    val status: String,
    val priority: Int,
    val sourceAvailableQty: Int,
    val destinationOnHand: Int,
)

enum class ReplenishmentScanPhase { SOURCE, ITEM, DESTINATION, COMPLETE }
