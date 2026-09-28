package com.obieda.fulfillos.ui

import android.os.Handler
import android.os.Looper
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import com.obieda.fulfillos.BuildConfig
import com.obieda.fulfillos.data.ApiClient
import com.obieda.fulfillos.data.AppGraph
import com.obieda.fulfillos.data.PickSyncResult
import com.obieda.fulfillos.data.OperationSyncResult
import com.obieda.fulfillos.data.ScanBus
import com.obieda.fulfillos.domain.AppScreen
import com.obieda.fulfillos.domain.UnpackSummary
import com.obieda.fulfillos.domain.ShipmentSummary
import com.obieda.fulfillos.domain.ReplenishmentSummary
import com.obieda.fulfillos.domain.ReplenishmentScanPhase
import com.obieda.fulfillos.domain.RecoverySummary
import com.obieda.fulfillos.domain.PendingOperationEvent
import com.obieda.fulfillos.domain.OperationScanPhase
import com.obieda.fulfillos.domain.CycleCountEntrySummary
import com.obieda.fulfillos.domain.BarcodeProduct
import com.obieda.fulfillos.domain.ConnectivityState
import com.obieda.fulfillos.domain.ClosedBagSummary
import com.obieda.fulfillos.domain.OrderCompletionSummary
import com.obieda.fulfillos.domain.InventoryLookup
import com.obieda.fulfillos.domain.LocationParser
import com.obieda.fulfillos.domain.PickScanPhase
import com.obieda.fulfillos.domain.SessionInfo
import com.obieda.fulfillos.domain.TaskSnapshot
import java.util.UUID
import java.util.concurrent.Executors

class AppViewModel(private val graph: AppGraph) : ViewModel() {
    private val worker = Executors.newSingleThreadExecutor()
    private val main = Handler(Looper.getMainLooper())

    var booting by mutableStateOf(true)
        private set
    var busy by mutableStateOf(false)
        private set
    var authenticated by mutableStateOf(false)
        private set
    var session by mutableStateOf<SessionInfo?>(null)
        private set

    var usernameInput by mutableStateOf(graph.secureSession.getUsername().orEmpty())
    var passwordInput by mutableStateOf("")
    var newPinInput by mutableStateOf("")
    var confirmPinInput by mutableStateOf("")
    var connectivity by mutableStateOf(graph.connectivity.state)
        private set
    var message by mutableStateOf("Starting…")
        private set
    var errorMessage by mutableStateOf<String?>(null)
        private set
    var scannedValue by mutableStateOf("")
        private set
    var appForeground by mutableStateOf(false)
        private set
    var cameraRequestId by mutableStateOf(0)
        private set
    var cameraRequestHint by mutableStateOf("Scan barcode")
        private set

    var screen by mutableStateOf(AppScreen.HOME)
        private set
    var workerState by mutableStateOf("AVAILABLE")
        private set
    var activityReasonInput by mutableStateOf("")
    var currentTask by mutableStateOf<TaskSnapshot?>(null)
        private set
    var scanPhase by mutableStateOf(PickScanPhase.BIN)
        private set

    var closedBags by mutableStateOf<List<ClosedBagSummary>>(emptyList())
        private set
    var completionSummary by mutableStateOf<OrderCompletionSummary?>(null)
        private set

    var inventoryQuery by mutableStateOf("")
    var inventoryResult by mutableStateOf<InventoryLookup?>(null)
        private set
    var inventoryLoading by mutableStateOf(false)
        private set

    var operationSourceInput by mutableStateOf("")
    var operationDestinationInput by mutableStateOf("")
    var operationQtyInput by mutableStateOf("1")
    var operationReasonInput by mutableStateOf("DAMAGED")
    var operationProduct by mutableStateOf<BarcodeProduct?>(null)
        private set
    var operationScanPhase by mutableStateOf(OperationScanPhase.SOURCE)
        private set
    var operationAwaitingConfirmation by mutableStateOf(false)
        private set

    var unpackTemperature by mutableStateOf("AMBIENT")
    var unpackSummary by mutableStateOf<UnpackSummary?>(null)
        private set

    var cycleCountSessionId by mutableStateOf<String?>(null)
        private set
    var cycleCountLocation by mutableStateOf("")
    var cycleCountProduct by mutableStateOf<BarcodeProduct?>(null)
        private set
    var cycleCountQtyInput by mutableStateOf("0")
    var cycleCountEntries by mutableStateOf<List<CycleCountEntrySummary>>(emptyList())
        private set

    var recoveryTaskIdInput by mutableStateOf("")
    var recoverySummary by mutableStateOf<RecoverySummary?>(null)
        private set

    var shipments by mutableStateOf<List<ShipmentSummary>>(emptyList())
        private set
    var selectedShipment by mutableStateOf<ShipmentSummary?>(null)
        private set
    var receiveProduct by mutableStateOf<BarcodeProduct?>(null)
        private set
    var receiveGoodQtyInput by mutableStateOf("1")
    var receiveDamagedQtyInput by mutableStateOf("0")
    var receiveLotInput by mutableStateOf("")
    var receiveExpiryInput by mutableStateOf("")
    var selectedStowTaskId by mutableStateOf<String?>(null)
        private set
    var stowDestinationInput by mutableStateOf("")

    var replenishmentTasks by mutableStateOf<List<ReplenishmentSummary>>(emptyList())
        private set
    var activeReplenishment by mutableStateOf<ReplenishmentSummary?>(null)
        private set
    var replenishmentPhase by mutableStateOf(ReplenishmentScanPhase.SOURCE)
        private set
    var replenishmentQtyInput by mutableStateOf("1")

    private var submittingItemId: String? = null
    private var lastLocationId: String? = null
    private val heartbeatIntervalMs = 5_000L
    private val offerPollIntervalMs = 3_000L

    private val heartbeatRunnable = object : Runnable {
        override fun run() {
            if (appForeground && authenticated && session?.mustChangePassword != true) sendHeartbeat()
            main.postDelayed(this, heartbeatIntervalMs)
        }
    }

    private val offerPollRunnable = object : Runnable {
        override fun run() {
            val waitingSurface = screen == AppScreen.HOME || screen == AppScreen.PICK
            val eligibleLocalState = currentTask != null || workerState == "AVAILABLE"
            if (
                appForeground &&
                authenticated &&
                session?.mustChangePassword != true &&
                connectivity == ConnectivityState.ONLINE &&
                !busy &&
                waitingSurface &&
                eligibleLocalState
            ) {
                pollWaitingOrders()
            }
            main.postDelayed(this, offerPollIntervalMs)
        }
    }

    private val scannerListener: (String) -> Unit = { value ->
        ui { onScan(value) }
    }

    init {
        graph.connectivity.observe { state ->
            ui {
                connectivity = state
                if (state == ConnectivityState.OFFLINE) {
                    message = "Offline • confirmed state preserved"
                }
            }
            if (state == ConnectivityState.ONLINE) {
                val taskId = currentTask?.taskId
                graph.picks.flush(taskId, ::handlePickSync)
            }
        }
        ScanBus.subscribe(scannerListener)
        main.post(heartbeatRunnable)
        main.postDelayed(offerPollRunnable, 1_000L)
        recoverSession()
    }

    private fun recoverSession() {
        worker.execute {
            val recovered = graph.sessions.recoverBlocking().getOrNull()
            var task: TaskSnapshot? = null
            var recoveredWorkerState = "AVAILABLE"
            if (recovered != null && !recovered.mustChangePassword) {
                val response = callWithRefresh { graph.api.getActiveTask() }
                if (response.ok) task = runCatching { graph.api.parseTaskEnvelope(response.body) }.getOrNull()
                val stateResponse = callWithRefresh { graph.api.getWorkerState() }
                if (stateResponse.ok) recoveredWorkerState = graph.api.parseWorkerState(stateResponse.body)
            }
            ui {
                session = recovered
                authenticated = recovered != null
                booting = false
                busy = false
                workerState = recoveredWorkerState
                if (recovered == null) {
                    message = "Sign in to this trusted PDA"
                } else {
                    message = if (task != null) "Active order restored" else "Online • waiting for orders"
                    if (task != null) installTask(task)
                }
            }
        }
    }

    fun onAppForegrounded() {
        appForeground = true
        if (!authenticated || session?.mustChangePassword == true) return
        sendHeartbeat(forceConnectivity = "ONLINE", activityOverride = currentPresenceActivity())
        if (connectivity == ConnectivityState.ONLINE && !busy) {
            pollWaitingOrders()
        }
        requestCameraForCurrentContext()
    }

    fun onAppBackgrounded() {
        if (!appForeground) return
        appForeground = false
        if (authenticated && session?.mustChangePassword != true) {
            sendHeartbeat(forceConnectivity = "OFFLINE", activityOverride = "APP_BACKGROUND")
        }
    }

    fun requestCameraScan(hint: String) {
        if (!authenticated || session?.mustChangePassword == true || !appForeground) return
        cameraRequestHint = hint
        cameraRequestId += 1
    }

    private fun requestCameraForCurrentContext() {
        val task = currentTask
        when (screen) {
            AppScreen.PICK -> when {
                task == null || task.taskStatus == "OFFERED" || task.recoveryRequired -> Unit
                task.taskStatus == "PICKED" || scanPhase == PickScanPhase.DONE ->
                    requestCameraScan("Scan bag / SPOO barcode")
                scanPhase == PickScanPhase.BIN ->
                    requestCameraScan("Scan bin " + (task.currentItem?.locationId ?: ""))
                scanPhase == PickScanPhase.ITEM ->
                    requestCameraScan("Scan " + (task.currentItem?.title ?: "item") + " barcode")
                else -> Unit
            }
            AppScreen.INVENTORY -> requestCameraScan("Scan a bin or item barcode")
            AppScreen.UNPACK -> unpackSummary?.let { unpack ->
                when {
                    unpack.status != "OPEN" -> Unit
                    !unpack.manifestLocked -> requestCameraScan("Scan return bag / SPOO")
                    !unpack.completeReady -> requestCameraScan("Scan unpack item barcode")
                    else -> Unit
                }
            }
            AppScreen.BOH -> if (!operationAwaitingConfirmation) {
                when (operationScanPhase) {
                    OperationScanPhase.SOURCE -> requestCameraScan("Scan source bin")
                    OperationScanPhase.ITEM -> requestCameraScan("Scan item barcode")
                    OperationScanPhase.DESTINATION -> requestCameraScan("Scan destination bin")
                    OperationScanPhase.SYNCING -> Unit
                }
            }
            AppScreen.DAMAGE -> when (operationScanPhase) {
                OperationScanPhase.SOURCE -> requestCameraScan("Scan source bin")
                OperationScanPhase.ITEM -> requestCameraScan("Scan damaged item barcode")
                else -> Unit
            }
            AppScreen.CYCLE_COUNT -> when {
                cycleCountSessionId == null -> requestCameraScan("Scan bin to start count")
                cycleCountProduct == null -> requestCameraScan("Scan item barcode to count")
                else -> Unit
            }
            AppScreen.RECOVERY -> when {
                recoverySummary == null -> requestCameraScan("Scan recovery task ID")
                recoverySummary?.items?.isNotEmpty() == true -> requestCameraScan("Scan recovery destination bin")
                else -> Unit
            }
            AppScreen.RECEIVE -> when {
                selectedShipment == null -> requestCameraScan("Scan shipment label or ID")
                selectedShipment?.status == "RECEIVING" && receiveProduct == null ->
                    requestCameraScan("Scan received product barcode")
                selectedShipment?.status == "STOWING" || selectedStowTaskId != null ->
                    requestCameraScan("Scan stow destination bin")
                else -> Unit
            }
            AppScreen.REPLENISHMENT -> when (replenishmentPhase) {
                ReplenishmentScanPhase.SOURCE -> if (activeReplenishment != null) requestCameraScan("Scan replenishment source bin")
                ReplenishmentScanPhase.ITEM -> if (activeReplenishment != null) requestCameraScan("Scan replenishment item")
                ReplenishmentScanPhase.DESTINATION -> if (activeReplenishment != null) requestCameraScan("Scan replenishment destination")
                ReplenishmentScanPhase.COMPLETE -> Unit
            }
            AppScreen.HOME, AppScreen.ACTIVITY -> Unit
        }
    }

    private fun currentPresenceActivity(): String = when {
        currentTask != null -> "ORDER_" + (currentTask?.taskStatus ?: "ACTIVE")
        workerState != "AVAILABLE" && workerState != "OFFLINE" -> workerState
        screen == AppScreen.INVENTORY -> "INVENTORY_VIEW"
        screen == AppScreen.UNPACK -> "UNPACK"
        screen == AppScreen.BOH -> "BOH_MOVE"
        screen == AppScreen.DAMAGE -> "DAMAGE"
        screen == AppScreen.CYCLE_COUNT -> "CYCLE_COUNT"
        screen == AppScreen.RECOVERY -> "RECOVERY"
        screen == AppScreen.RECEIVE -> "RECEIVE"
        screen == AppScreen.REPLENISHMENT -> "REPLENISHMENT"
        screen == AppScreen.ACTIVITY -> "ACTIVITY_RECORDER"
        else -> "WAITING_FOR_ORDER"
    }

    fun openActivityRecorder() {
        screen = AppScreen.ACTIVITY
        refreshWorkerState()
    }

    fun refreshWorkerState() {
        if (!authenticated || busy) return
        worker.execute {
            val response = callWithRefresh { graph.api.getWorkerState() }
            ui {
                if (response.ok) {
                    workerState = graph.api.parseWorkerState(response.body)
                    message = "Current activity • " + workerState.replace("_", " ")
                } else if (response.code != 401) {
                    errorMessage = graph.api.parseConflictMessage(response.body)
                }
            }
        }
    }

    fun startBreak(breakType: String = "REST") {
        if (!authenticated || busy || currentTask != null) {
            if (currentTask != null) errorMessage = "Finish or hand over the active order before break"
            return
        }
        busy = true
        errorMessage = null
        message = "Starting break…"
        worker.execute {
            val response = callWithRefresh { graph.api.startBreak(breakType = breakType, paid = true) }
            ui {
                busy = false
                if (response.ok) {
                    workerState = "BREAK"
                    message = "Break recorded • order dispatch blocked"
                    sendHeartbeat(forceConnectivity = "ONLINE", activityOverride = "BREAK")
                } else {
                    errorMessage = graph.api.parseConflictMessage(response.body)
                    message = "Break was not started"
                }
            }
        }
    }

    fun finishRecordedActivity() {
        if (!authenticated || busy || currentTask != null) return
        val manualStates = setOf(
            "BREAK", "TRAINING", "BIN_CHECK", "EXPIRY_AUDIT",
            "VENDOR_REMOVAL", "BOH_MOVE", "ENDING_SHIFT",
        )
        if (workerState !in manualStates) {
            errorMessage = "Finish this activity from its operational workflow so the task/session closes correctly"
            return
        }
        busy = true
        errorMessage = null
        val endingBreak = workerState == "BREAK"
        message = if (endingBreak) "Ending break…" else "Returning available…"
        worker.execute {
            val response = callWithRefresh {
                if (endingBreak) graph.api.endBreak()
                else graph.api.updateWorkerState("AVAILABLE", "ACTIVITY_COMPLETED")
            }
            ui {
                busy = false
                if (response.ok) {
                    workerState = "AVAILABLE"
                    activityReasonInput = ""
                    message = "Available • waiting for orders"
                    sendHeartbeat(forceConnectivity = "ONLINE", activityOverride = "WAITING_FOR_ORDER")
                } else {
                    errorMessage = graph.api.parseConflictMessage(response.body)
                }
            }
        }
    }

    fun recordActivity(state: String, defaultReason: String) {
        if (!authenticated || busy || currentTask != null) {
            if (currentTask != null) errorMessage = "An active order blocks other recorded tasks"
            return
        }
        val reason = activityReasonInput.trim().ifBlank { defaultReason }
        busy = true
        errorMessage = null
        message = "Recording " + state.replace("_", " ").lowercase() + "…"
        worker.execute {
            val response = callWithRefresh { graph.api.updateWorkerState(state, reason) }
            ui {
                busy = false
                if (response.ok) {
                    workerState = graph.api.parseWorkerState(response.body)
                    message = workerState.replace("_", " ") + " recorded • order dispatch blocked"
                    sendHeartbeat(forceConnectivity = "ONLINE", activityOverride = workerState)
                } else {
                    errorMessage = graph.api.parseConflictMessage(response.body)
                }
            }
        }
    }

    fun forgotPassword() {
        val identifier = usernameInput.trim()
        if (identifier.isBlank() || busy) {
            errorMessage = "Enter your username first"
            return
        }
        busy = true
        errorMessage = null
        message = "Requesting password reset…"
        worker.execute {
            val response = runCatching { graph.api.forgotPassword(identifier) }
                .getOrElse { ApiClient.Result(599, it.message.orEmpty()) }
            ui {
                busy = false
                if (response.ok) {
                    message = "Reset request sent • ask a supervisor for the temporary password"
                } else {
                    errorMessage = "Could not request password reset (" + response.code + ")"
                    message = "Password reset unavailable"
                }
            }
        }
    }

    fun login() {
        if (usernameInput.isBlank() || passwordInput.isBlank() || busy) return
        busy = true
        errorMessage = null
        message = "Signing in…"
        worker.execute {
            val result = graph.sessions.loginBlocking(usernameInput, passwordInput)
            val loggedIn = result.getOrNull()
            var task: TaskSnapshot? = null
            var loggedInWorkerState = "AVAILABLE"
            if (loggedIn != null && !loggedIn.mustChangePassword) {
                val active = graph.api.getActiveTask()
                if (active.ok) task = runCatching { graph.api.parseTaskEnvelope(active.body) }.getOrNull()
                val stateResponse = graph.api.getWorkerState()
                if (stateResponse.ok) loggedInWorkerState = graph.api.parseWorkerState(stateResponse.body)
            }
            ui {
                busy = false
                if (loggedIn == null) {
                    errorMessage = result.exceptionOrNull()?.message ?: "Login failed"
                    message = "Authentication failed"
                } else {
                    session = loggedIn
                    authenticated = true
                    workerState = loggedInWorkerState
                    passwordInput = ""
                    message = when {
                        loggedIn.mustChangePassword -> "Temporary PIN accepted • create your personal PIN"
                        task != null -> "Signed in • active order restored"
                        else -> "Signed in • waiting for orders"
                    }
                    if (task != null) installTask(task) else screen = AppScreen.HOME
                }
            }
        }
    }

    fun completeFirstLoginPin() {
        val newPin = newPinInput.trim()
        val confirm = confirmPinInput.trim()
        if (!authenticated || session?.mustChangePassword != true || busy) return
        if (newPin.length !in 6..10 || !newPin.all(Char::isDigit)) {
            errorMessage = "PIN must be 6–10 digits"
            return
        }
        if (newPin != confirm) {
            errorMessage = "PIN confirmation does not match"
            return
        }
        busy = true
        errorMessage = null
        message = "Saving your personal PIN…"
        worker.execute {
            val result = graph.sessions.completeFirstLoginBlocking(newPin)
            val updated = result.getOrNull()
            ui {
                busy = false
                if (updated == null) {
                    errorMessage = result.exceptionOrNull()?.message ?: "Could not save PIN"
                    message = "PIN change failed"
                } else {
                    session = updated
                    newPinInput = ""
                    confirmPinInput = ""
                    message = "PIN changed • waiting for orders"
                    screen = AppScreen.HOME
                }
            }
        }
    }

    fun logout() {
        graph.sessions.logout()
        session = null
        authenticated = false
        newPinInput = ""
        confirmPinInput = ""
        currentTask = null
        closedBags = emptyList()
        completionSummary = null
        screen = AppScreen.HOME
        scanPhase = PickScanPhase.BIN
        message = "Signed out"
    }

    fun goHome() {
        screen = AppScreen.HOME
        errorMessage = null
    }

    fun openInventory() {
        screen = AppScreen.INVENTORY
        errorMessage = null
        requestCameraScan("Scan a bin or item barcode")
    }

    fun openPick() {
        screen = AppScreen.PICK
        errorMessage = null
        completionSummary = null
        if (currentTask == null) claimNext()
    }

    fun claimNext() {
        pollWaitingOrders(manual = true)
    }

    private fun pollWaitingOrders(manual: Boolean = false) {
        if (!authenticated || connectivity != ConnectivityState.ONLINE) return
        if (busy && !manual) return
        if (manual) {
            busy = true
            errorMessage = null
            completionSummary = null
            message = "Checking live order queue…"
        }

        worker.execute {
            val activeResponse = callWithRefresh { graph.api.getActiveTask() }
            val activeTask = if (activeResponse.ok) {
                runCatching { graph.api.parseTaskEnvelope(activeResponse.body) }.getOrNull()
            } else null

            var offerResponse: ApiClient.Result? = null
            var offeredTask: TaskSnapshot? = null
            if (activeTask == null && activeResponse.code != 401) {
                offerResponse = callWithRefresh { graph.api.getMyOffers() }
                if (offerResponse.ok) {
                    offeredTask = runCatching { graph.api.parseFirstOffer(offerResponse.body) }.getOrNull()
                }
            }

            ui {
                if (manual) busy = false
                if (activeResponse.code == 401 || offerResponse?.code == 401) {
                    expireSession()
                    return@ui
                }

                when {
                    activeTask != null -> {
                        val changed = currentTask?.taskId != activeTask.taskId ||
                            currentTask?.serverVersion != activeTask.serverVersion
                        if (changed) installTask(activeTask) else currentTask = activeTask
                        message = when (activeTask.taskStatus) {
                            "ACCEPTED", "PICKING" -> "Active order • server synced"
                            "PICKED" -> "Pick complete • close bag"
                            else -> "Active order synced"
                        }
                    }
                    offeredTask != null -> {
                        val isNew = currentTask?.taskId != offeredTask.taskId ||
                            currentTask?.taskStatus != "OFFERED"
                        if (isNew) {
                            installTask(offeredTask)
                            message = "New order offered • Accept or Reject"
                        }
                    }
                    currentTask?.taskStatus == "OFFERED" -> {
                        currentTask = null
                        scanPhase = PickScanPhase.BIN
                        if (screen == AppScreen.PICK) screen = AppScreen.HOME
                        message = "Offer expired • waiting for orders"
                    }
                    currentTask == null -> {
                        message = "Waiting for orders • auto-check every 3 seconds"
                    }
                }
            }
        }
    }

    private fun sendHeartbeat(
        forceConnectivity: String? = null,
        activityOverride: String? = null,
    ) {
        if (!authenticated) return
        val taskId = currentTask?.taskId
        val location = lastLocationId
        val activity = activityOverride ?: currentPresenceActivity()
        val presence = forceConnectivity ?: if (appForeground) connectivity.name else "OFFLINE"
        worker.execute {
            val response = callWithRefresh {
                graph.api.heartbeat(
                    currentTaskId = taskId,
                    appVersion = BuildConfig.VERSION_NAME,
                    connectivity = presence,
                    batteryPercent = graph.batteryPercent(),
                    lastLocationId = location,
                    activity = activity,
                )
            }
            if (response.code == 401) ui { expireSession() }
        }
    }

    fun acceptOffer() {
        val task = currentTask ?: return
        if (busy) return
        busy = true
        message = "Accepting order…"
        worker.execute {
            val response = callWithRefresh { graph.api.acceptTask(task.taskId) }
            val updated = if (response.ok) runCatching { graph.api.parseTaskEnvelope(response.body) }.getOrNull() else null
            ui {
                busy = false
                if (updated != null) {
                    installTask(updated)
                    scanPhase = PickScanPhase.BIN
                    message = "Accepted • scan the bin"
                    requestCameraForCurrentContext()
                } else if (response.code == 401) {
                    expireSession()
                } else {
                    errorMessage = graph.api.parseConflictMessage(response.body)
                    message = "Offer changed"
                    refreshTask()
                }
            }
        }
    }

    fun rejectOffer() {
        val task = currentTask ?: return
        if (busy) return
        busy = true
        worker.execute {
            val response = callWithRefresh { graph.api.rejectTask(task.taskId) }
            ui {
                busy = false
                if (response.ok) {
                    currentTask = null
                    scanPhase = PickScanPhase.BIN
                    message = "Offer rejected"
                    claimNext()
                } else if (response.code == 401) {
                    expireSession()
                } else {
                    errorMessage = graph.api.parseConflictMessage(response.body)
                    refreshTask()
                }
            }
        }
    }

    fun refreshTask() {
        val id = currentTask?.taskId ?: return
        worker.execute {
            val response = callWithRefresh { graph.api.getTask(id) }
            val updated = if (response.ok) runCatching { graph.api.parseTask(response.body) }.getOrNull() else null
            ui {
                if (updated != null) {
                    installTask(updated)
                    if (updated.taskStatus != "PICKED" && !updated.recoveryRequired) {
                        scanPhase = PickScanPhase.BIN
                    }
                    message = "Server state refreshed"
                    requestCameraForCurrentContext()
                } else if (response.code == 401) {
                    expireSession()
                }
            }
        }
    }

    fun shortCurrent(reason: String = "MISSING_AT_LOCATION") {
        val task = currentTask ?: return
        val item = task.currentItem ?: return
        if (scanPhase != PickScanPhase.ITEM || busy) {
            message = "Confirm the bin before reporting a shortage"
            return
        }
        submittingItemId = item.id
        scanPhase = PickScanPhase.SYNCING
        message = "Short persisted • awaiting server ACK"
        graph.picks.createShort(
            taskId = task.taskId,
            taskItemId = item.id,
            locationId = item.locationId,
            productId = item.productId,
            qty = 1,
            reason = reason,
            onResult = ::handlePickSync,
        )
    }

    fun skipCurrent(reason: String = "DEFERRED") {
        val task = currentTask ?: return
        val item = task.currentItem ?: return
        if (scanPhase != PickScanPhase.ITEM || busy) {
            message = "Confirm the bin before skipping this item"
            return
        }
        submittingItemId = item.id
        scanPhase = PickScanPhase.SYNCING
        message = "Skip persisted • moving item to end of route"
        graph.picks.createSkip(
            taskId = task.taskId,
            taskItemId = item.id,
            locationId = item.locationId,
            productId = item.productId,
            reason = reason,
            onResult = ::handlePickSync,
        )
    }

    fun damagedCurrent(reason: String = "DAMAGED") {
        val task = currentTask ?: return
        val item = task.currentItem ?: return
        if (scanPhase != PickScanPhase.ITEM || busy) {
            message = "Confirm the bin before reporting damage"
            return
        }
        submittingItemId = item.id
        scanPhase = PickScanPhase.SYNCING
        message = "Damage persisted • awaiting server ACK"
        graph.picks.createDamaged(
            taskId = task.taskId,
            taskItemId = item.id,
            locationId = item.locationId,
            productId = item.productId,
            qty = 1,
            reason = reason,
            onResult = ::handlePickSync,
        )
    }

    fun closeBag(spooCode: String) {
        val task = currentTask ?: return
        if (task.taskStatus != "PICKED" || busy) {
            message = "Finish picking before closing bags"
            return
        }
        val code = spooCode.trim()
        if (code.length < 4) {
            errorMessage = "Invalid bag/SPOO barcode"
            return
        }
        busy = true
        errorMessage = null
        message = "Closing bag…"
        worker.execute {
            val response = callWithRefresh { graph.api.closeBag(task.taskId, code) }
            val bag = if (response.ok) runCatching { graph.api.parseClosedBag(response.body) }.getOrNull() else null
            ui {
                busy = false
                if (bag != null) {
                    if (closedBags.none { it.bagNo == bag.bagNo }) {
                        closedBags = closedBags + bag
                    }
                    scannedValue = ""
                    message = "Bag ${bag.bagNo} closed • SPOO ••••${bag.spooLast4}"
                    requestCameraScan("Scan another bag / SPOO or finish order")
                } else if (response.code == 401) {
                    expireSession()
                } else {
                    errorMessage = graph.api.parseConflictMessage(response.body)
                    message = "Bag was not closed"
                }
            }
        }
    }

    fun finishPickedOrder() {
        val task = currentTask ?: return
        if (task.taskStatus != "PICKED" || busy) return
        if (closedBags.isEmpty()) {
            errorMessage = "Scan at least one bag SPOO first"
            return
        }
        busy = true
        errorMessage = null
        message = "Finalizing order…"
        worker.execute {
            val response = callWithRefresh { graph.api.finishPicking(task.taskId) }
            val summary = if (response.ok) runCatching { graph.api.parseCompletionSummary(response.body) }.getOrNull() else null
            ui {
                busy = false
                if (summary != null) {
                    completionSummary = summary
                    currentTask = null
                    closedBags = emptyList()
                    scannedValue = ""
                    scanPhase = PickScanPhase.BIN
                    screen = AppScreen.PICK
                    workerState = "AVAILABLE"
                    message = "Order complete"
                } else if (response.code == 401) {
                    expireSession()
                } else {
                    errorMessage = graph.api.parseConflictMessage(response.body)
                    message = "Could not finalize order"
                }
            }
        }
    }

    fun retryPending() {
        val id = currentTask?.taskId ?: return
        if (connectivity != ConnectivityState.ONLINE) {
            message = "Still offline • event remains durable"
            return
        }
        scanPhase = PickScanPhase.SYNCING
        graph.picks.flush(id, ::handlePickSync)
    }

    fun lookupInventory(query: String = inventoryQuery) {
        val value = query.trim().uppercase()
        if (value.isBlank() || inventoryLoading) return
        inventoryQuery = value
        inventoryLoading = true
        errorMessage = null
        worker.execute {
            val locationLike = value.startsWith("P-") ||
                value.startsWith("TSCRET") ||
                value == "DMG" ||
                value == "SPECIAL"
            val barcodeLike = !locationLike && value.all(Char::isDigit)
            val response = callWithRefresh {
                when {
                    locationLike -> graph.api.inventoryByLocation(value)
                    barcodeLike -> graph.api.inventoryByBarcode(value)
                    else -> graph.api.inventoryByProduct(value)
                }
            }
            val parsed = if (response.ok) runCatching {
                if (locationLike) graph.api.parseInventoryLocation(response.body)
                else graph.api.parseInventoryProduct(response.body)
            }.getOrNull() else null

            ui {
                inventoryLoading = false
                if (parsed != null) {
                    inventoryResult = parsed
                    message = "Inventory loaded"
                } else if (response.code == 401) {
                    expireSession()
                } else {
                    inventoryResult = null
                    errorMessage = "Inventory lookup failed (${response.code})"
                }
            }
        }
    }

    fun openUnpack() {
        screen = AppScreen.UNPACK
        errorMessage = null
        startOrResumeUnpack(unpackTemperature)
    }

    fun startOrResumeUnpack(temperature: String = unpackTemperature) {
        if (!authenticated || busy) return
        unpackTemperature = temperature.uppercase()
        busy = true
        message = "Opening ${unpackTemperature.lowercase()} unpack…"
        worker.execute {
            var response = callWithRefresh { graph.api.getActiveUnpack(unpackTemperature) }
            var summary = if (response.ok) runCatching { graph.api.parseActiveUnpack(response.body) }.getOrNull() else null
            if (summary == null && response.code != 401) {
                response = callWithRefresh { graph.api.startUnpack(unpackTemperature) }
                if (response.ok) summary = runCatching { graph.api.parseUnpack(response.body) }.getOrNull()
            }
            ui {
                busy = false
                if (summary != null) {
                    unpackSummary = summary
                    message = when {
                        !summary.manifestLocked -> "Unpack ${summary.toteLocationId} • scan return bag / SPOO"
                        summary.completeReady -> "All ${summary.expectedUnits} units verified • ready to finish"
                        else -> "Unpack ${summary.toteLocationId} • ${summary.verifiedUnits}/${summary.expectedUnits} verified"
                    }
                    requestCameraForCurrentContext()
                } else if (response.code == 401) {
                    expireSession()
                } else {
                    errorMessage = graph.api.parseConflictMessage(response.body)
                    message = "Could not open unpack"
                }
            }
        }
    }

    fun completeCurrentUnpack() {
        val current = unpackSummary ?: return
        if (busy) return
        busy = true
        worker.execute {
            val response = callWithRefresh { graph.api.completeUnpack(current.sessionId) }
            val updated = if (response.ok) runCatching { graph.api.parseUnpack(response.body) }.getOrNull() else null
            ui {
                busy = false
                if (updated != null) {
                    unpackSummary = updated
                    message = "Unpack completed"
                } else {
                    errorMessage = graph.api.parseConflictMessage(response.body)
                }
            }
        }
    }

    fun openBoh() {
        screen = AppScreen.BOH
        resetOperationScanner()
        message = "BOH Move • scan source bin"
        requestCameraScan("Scan BOH source bin")
    }

    fun openDamage() {
        screen = AppScreen.DAMAGE
        resetOperationScanner()
        message = "Damage • scan source bin"
        requestCameraScan("Scan damage source bin")
    }

    fun openCycleCount() {
        screen = AppScreen.CYCLE_COUNT
        cycleCountSessionId = null
        cycleCountLocation = ""
        cycleCountProduct = null
        cycleCountEntries = emptyList()
        message = "Cycle Count • scan the bin to count"
        requestCameraScan("Scan bin to start cycle count")
    }

    fun startCycleCount(location: String = cycleCountLocation) {
        val loc = canonicalLocation(location)
        if (loc.isBlank() || busy) return
        busy = true
        worker.execute {
            val response = callWithRefresh { graph.api.startCycleCount(loc) }
            val root = if (response.ok) runCatching { org.json.JSONObject(response.body) }.getOrNull() else null
            ui {
                busy = false
                if (root != null) {
                    cycleCountSessionId = root.optString("session_id")
                    cycleCountLocation = root.optString("location_id", loc)
                    lastLocationId = cycleCountLocation
                    message = "Cycle Count open • scan an item barcode"
                    requestCameraScan("Scan item barcode to count")
                } else {
                    errorMessage = graph.api.parseConflictMessage(response.body)
                }
            }
        }
    }

    fun submitCycleCountLine() {
        val sessionId = cycleCountSessionId ?: return
        val product = cycleCountProduct ?: return
        val qty = cycleCountQtyInput.toIntOrNull()
        if (qty == null || qty < 0 || busy) {
            errorMessage = "Enter the physical counted quantity"
            return
        }
        busy = true
        worker.execute {
            val response = callWithRefresh { graph.api.recordCycleCount(sessionId, product.productId, qty) }
            val entry = if (response.ok) runCatching { graph.api.parseCycleCountEntry(response.body) }.getOrNull() else null
            ui {
                busy = false
                if (entry != null) {
                    cycleCountEntries = cycleCountEntries.filterNot { it.productId == entry.productId } + entry
                    cycleCountProduct = null
                    cycleCountQtyInput = "0"
                    message = "Count saved • variance ${entry.variance} • scan next item"
                    requestCameraScan("Scan next item barcode")
                } else {
                    errorMessage = graph.api.parseConflictMessage(response.body)
                }
            }
        }
    }

    fun applyCurrentCycleCount() {
        val sessionId = cycleCountSessionId ?: return
        if (busy) return
        busy = true
        worker.execute {
            val response = callWithRefresh { graph.api.applyCycleCount(sessionId) }
            ui {
                busy = false
                if (response.ok) {
                    message = "Cycle Count applied • inventory reconciled"
                    cycleCountSessionId = null
                    cycleCountProduct = null
                } else {
                    errorMessage = graph.api.parseConflictMessage(response.body)
                }
            }
        }
    }

    fun openRecovery() {
        screen = AppScreen.RECOVERY
        recoverySummary = null
        errorMessage = null
        message = "Recovery • enter or scan task ID"
        requestCameraScan("Scan recovery task ID")
    }

    fun loadRecovery(taskId: String = recoveryTaskIdInput) {
        val id = taskId.trim()
        if (id.isBlank() || busy) return
        recoveryTaskIdInput = id
        busy = true
        worker.execute {
            val response = callWithRefresh { graph.api.getRecovery(id) }
            val summary = if (response.ok) runCatching { graph.api.parseRecovery(response.body) }.getOrNull() else null
            ui {
                busy = false
                if (summary != null) {
                    recoverySummary = summary
                    message = if (summary.items.isEmpty()) "Recovery complete" else "Scan destination for ${summary.items.first().title}"
                    if (summary.items.isNotEmpty()) requestCameraScan("Scan recovery destination bin")
                } else {
                    errorMessage = graph.api.parseConflictMessage(response.body)
                }
            }
        }
    }

    fun openReceive() {
        screen = AppScreen.RECEIVE
        receiveProduct = null
        selectedStowTaskId = null
        stowDestinationInput = ""
        errorMessage = null
        loadShipments()
    }

    fun clearSelectedShipment() {
        selectedShipment = null
        receiveProduct = null
        selectedStowTaskId = null
        stowDestinationInput = ""
        message = "Choose a shipment to receive"
    }

    fun selectStowTask(taskId: String) {
        selectedStowTaskId = taskId
        stowDestinationInput = ""
        val shipment = selectedShipment
        val task = shipment?.stowTasks?.firstOrNull { it.id == taskId }
        val line = shipment?.lines?.firstOrNull { it.productId == task?.productId }
        message = if (line?.recommendedStow?.isNotEmpty() == true) {
            "Scan destination • suggested ${line.recommendedStow.take(3).joinToString()}"
        } else {
            "Scan destination bin for stow task"
        }
        requestCameraScan("Scan stow destination bin")
    }

    fun confirmSelectedStow() {
        val taskId = selectedStowTaskId ?: return
        val destination = stowDestinationInput.trim()
        if (destination.isBlank()) {
            errorMessage = "Scan or enter a destination bin"
            return
        }
        completeStowTask(taskId, destination)
    }

    fun loadShipments() {
        if (busy) return
        busy = true
        worker.execute {
            val response = callWithRefresh { graph.api.getShipments() }
            val list = if (response.ok) runCatching { graph.api.parseShipments(response.body) }.getOrNull() else null
            ui {
                busy = false
                if (list != null) {
                    shipments = list.filter { it.status != "COMPLETED" && it.status != "CANCELLED" }
                    selectedShipment = selectedShipment?.let { selected -> shipments.firstOrNull { it.id == selected.id } }
                    message = if (shipments.isEmpty()) "No active inbound shipments" else "Choose or scan a shipment"
                    if (shipments.isNotEmpty() && selectedShipment == null) requestCameraScan("Scan shipment label or ID")
                } else {
                    errorMessage = graph.api.parseConflictMessage(response.body)
                }
            }
        }
    }

    fun selectShipment(shipment: ShipmentSummary) {
        if (busy) return
        selectedShipment = shipment
        receiveProduct = null
        selectedStowTaskId = null
        stowDestinationInput = ""
        busy = true
        message = "Opening ${shipment.label}…"
        worker.execute {
            val response = callWithRefresh { graph.api.openShipment(shipment.id) }
            val updated = if (response.ok) runCatching {
                val root = org.json.JSONObject(response.body)
                graph.api.parseShipment(root.getJSONObject("shipment").toString())
            }.getOrNull() else null
            ui {
                busy = false
                if (updated != null) {
                    selectedShipment = updated
                    message = if (updated.status == "STOWING") {
                        "Stow ${updated.label} • scan destination"
                    } else {
                        "Receiving ${updated.label} • scan item barcode"
                    }
                    requestCameraForCurrentContext()
                } else {
                    errorMessage = graph.api.parseConflictMessage(response.body)
                }
            }
        }
    }

    fun submitReceiveLine() {
        val shipment = selectedShipment ?: return
        val product = receiveProduct ?: return
        val good = receiveGoodQtyInput.toIntOrNull() ?: 0
        val damaged = receiveDamagedQtyInput.toIntOrNull() ?: 0
        if (good + damaged <= 0 || busy) {
            errorMessage = "Enter received or damaged quantity"
            return
        }
        busy = true
        worker.execute {
            val response = callWithRefresh {
                graph.api.receiveShipmentLine(
                    shipmentId = shipment.id,
                    eventId = UUID.randomUUID().toString(),
                    productId = product.productId,
                    goodQty = good,
                    damagedQty = damaged,
                    lotCode = receiveLotInput.trim().ifBlank { null },
                    expiresOn = receiveExpiryInput.trim().ifBlank { null },
                )
            }
            ui {
                busy = false
                if (response.ok) {
                    receiveProduct = null
                    receiveGoodQtyInput = "1"
                    receiveDamagedQtyInput = "0"
                    message = "Receipt saved • scan next item"
                    refreshSelectedShipment()
                    requestCameraScan("Scan next received product barcode")
                } else {
                    errorMessage = graph.api.parseConflictMessage(response.body)
                }
            }
        }
    }

    fun completeSelectedReceiving() {
        val shipment = selectedShipment ?: return
        if (busy) return
        busy = true
        worker.execute {
            val response = callWithRefresh { graph.api.completeReceiving(shipment.id) }
            val updated = if (response.ok) runCatching { graph.api.parseShipment(response.body) }.getOrNull() else null
            ui {
                busy = false
                if (updated != null) {
                    selectedShipment = updated
                    message = "Receiving complete • stow tasks ready"
                    requestCameraForCurrentContext()
                } else {
                    errorMessage = graph.api.parseConflictMessage(response.body)
                }
            }
        }
    }

    fun completeStowTask(taskId: String, destination: String) {
        if (destination.isBlank() || busy) return
        busy = true
        worker.execute {
            val response = callWithRefresh {
                graph.api.completeStow(taskId, UUID.randomUUID().toString(), destination)
            }
            ui {
                busy = false
                if (response.ok) {
                    message = "Stow confirmed at ${destination.uppercase()}"
                    selectedStowTaskId = null
                    stowDestinationInput = ""
                    refreshSelectedShipment()
                    main.postDelayed({ requestCameraForCurrentContext() }, 250L)
                } else {
                    errorMessage = graph.api.parseConflictMessage(response.body)
                }
            }
        }
    }

    private fun refreshSelectedShipment() {
        val id = selectedShipment?.id ?: return
        worker.execute {
            val response = callWithRefresh { graph.api.getShipments() }
            val list = if (response.ok) runCatching { graph.api.parseShipments(response.body) }.getOrNull() else null
            ui {
                if (list != null) {
                    shipments = list.filter { it.status != "COMPLETED" && it.status != "CANCELLED" }
                    selectedShipment = list.firstOrNull { it.id == id }
                }
            }
        }
    }

    fun openReplenishment() {
        screen = AppScreen.REPLENISHMENT
        activeReplenishment = null
        loadReplenishmentQueue()
    }

    fun loadReplenishmentQueue() {
        if (busy) return
        busy = true
        worker.execute {
            val response = callWithRefresh { graph.api.getReplenishmentQueue(mine = false) }
            val list = if (response.ok) runCatching { graph.api.parseReplenishmentQueue(response.body) }.getOrNull() else null
            ui {
                busy = false
                if (list != null) {
                    replenishmentTasks = list
                    activeReplenishment = activeReplenishment?.let { active -> list.firstOrNull { it.id == active.id } ?: active }
                    message = if (list.isEmpty()) "No replenishment work" else "Select a replenishment task"
                } else {
                    errorMessage = graph.api.parseConflictMessage(response.body)
                }
            }
        }
    }

    fun claimReplenishment(task: ReplenishmentSummary) {
        if (busy) return
        busy = true
        worker.execute {
            val response = callWithRefresh { graph.api.claimReplenishment(task.id) }
            val updated = if (response.ok) runCatching { graph.api.parseReplenishmentEnvelope(response.body) }.getOrNull() else null
            ui {
                busy = false
                if (updated != null) {
                    activeReplenishment = updated
                    replenishmentQtyInput = updated.qty.toString()
                    syncReplenishmentPhase(updated)
                    message = "Replenishment claimed • scan ${updated.sourceLocationId}"
                    requestCameraForCurrentContext()
                } else {
                    errorMessage = graph.api.parseConflictMessage(response.body)
                }
            }
        }
    }

    fun completeActiveReplenishment() {
        val task = activeReplenishment ?: return
        val qty = replenishmentQtyInput.toIntOrNull() ?: 0
        if (qty <= 0 || busy) {
            errorMessage = "Enter actual moved quantity"
            return
        }
        busy = true
        worker.execute {
            val response = callWithRefresh {
                graph.api.completeReplenishment(task.id, UUID.randomUUID().toString(), qty)
            }
            val updated = if (response.ok) runCatching { graph.api.parseReplenishmentEnvelope(response.body) }.getOrNull() else null
            ui {
                busy = false
                if (updated != null) {
                    activeReplenishment = updated
                    replenishmentPhase = ReplenishmentScanPhase.COMPLETE
                    message = "Replenishment ${updated.status.lowercase()} • inventory committed"
                    loadReplenishmentQueue()
                } else {
                    errorMessage = graph.api.parseConflictMessage(response.body)
                }
            }
        }
    }

    private fun syncReplenishmentPhase(task: ReplenishmentSummary) {
        replenishmentPhase = when (task.status) {
            "CLAIMED" -> ReplenishmentScanPhase.SOURCE
            "SOURCE_CONFIRMED" -> ReplenishmentScanPhase.ITEM
            "STARTED" -> ReplenishmentScanPhase.DESTINATION
            "DESTINATION_CONFIRMED" -> ReplenishmentScanPhase.COMPLETE
            else -> ReplenishmentScanPhase.SOURCE
        }
    }

    private fun resetOperationScanner() {
        operationSourceInput = ""
        operationDestinationInput = ""
        operationProduct = null
        operationQtyInput = "1"
        operationScanPhase = OperationScanPhase.SOURCE
        operationAwaitingConfirmation = false
    }

    private fun resolveBarcode(
        barcode: String,
        onResolved: (BarcodeProduct) -> Unit,
    ) {
        worker.execute {
            val response = callWithRefresh { graph.api.inventoryByBarcode(barcode.trim()) }
            val product = if (response.ok) runCatching { graph.api.parseBarcodeProduct(response.body) }.getOrNull() else null
            ui {
                if (product != null) onResolved(product)
                else {
                    errorMessage = if (response.code == 404) "Barcode is not mapped" else graph.api.parseConflictMessage(response.body)
                    message = "Item rejected"
                }
            }
        }
    }

    private fun handleOperationSync(result: OperationSyncResult) {
        ui {
            when (result) {
                is OperationSyncResult.Acked -> {
                    message = "Operation confirmed by server"
                    when (result.kind) {
                        PendingOperationEvent.Kind.UNPACK_SCAN -> {
                            unpackSummary?.let { startOrResumeUnpack(it.temperatureClass) }
                        }
                        PendingOperationEvent.Kind.BOH_MOVE,
                        PendingOperationEvent.Kind.DAMAGE -> {
                            resetOperationScanner()
                            requestCameraForCurrentContext()
                        }
                        PendingOperationEvent.Kind.RECOVERY_STOW -> loadRecovery()
                    }
                }
                is OperationSyncResult.Queued -> message = result.reason
                is OperationSyncResult.Rejected -> {
                    errorMessage = result.message
                    message = "Operation rejected"
                }
                OperationSyncResult.AuthenticationRequired -> expireSession()
            }
        }
    }

    fun submitScanValue(value: String) {
        val normalized = value.trim()
        if (normalized.isBlank()) return
        onScan(normalized)
    }

    fun clearError() {
        errorMessage = null
    }

    private fun onScan(value: String) {
        scannedValue = value
        errorMessage = null
        when (screen) {
            AppScreen.INVENTORY -> {
                inventoryQuery = value.trim().uppercase()
                lookupInventory(inventoryQuery)
            }
            AppScreen.PICK -> handlePickScan(value)
            AppScreen.UNPACK -> handleUnpackScan(value)
            AppScreen.BOH -> handleBohScan(value)
            AppScreen.DAMAGE -> handleDamageScan(value)
            AppScreen.CYCLE_COUNT -> handleCycleCountScan(value)
            AppScreen.RECOVERY -> handleRecoveryScan(value)
            AppScreen.RECEIVE -> handleReceiveScan(value)
            AppScreen.REPLENISHMENT -> handleReplenishmentScan(value)
            AppScreen.ACTIVITY -> message = "Scan ignored • Record Task uses buttons, not barcode scans"
            AppScreen.HOME -> message = "Scan received • open a tool to use it"
        }
    }

    private fun handleUnpackScan(value: String) {
        val unpack = unpackSummary ?: run {
            startOrResumeUnpack()
            return
        }
        if (unpack.status != "OPEN") {
            message = "Start a new unpack session first"
            return
        }
        resolveBarcode(value) { product ->
            operationProduct = product
            graph.operations.enqueue(
                kind = PendingOperationEvent.Kind.UNPACK_SCAN,
                resourceId = unpack.sessionId,
                productId = product.productId,
                qty = operationQtyInput.toIntOrNull()?.coerceAtLeast(1) ?: 1,
                onResult = ::handleOperationSync,
            )
            message = "Unpack scan persisted • awaiting ACK"
        }
    }

    private fun handleBohScan(value: String) {
        when (operationScanPhase) {
            OperationScanPhase.SOURCE -> {
                operationSourceInput = canonicalLocation(value)
                lastLocationId = operationSourceInput
                operationScanPhase = OperationScanPhase.ITEM
                message = "Source ${operationSourceInput} • scan item"
                requestCameraScan("Scan item barcode")
            }
            OperationScanPhase.ITEM -> resolveBarcode(value) { product ->
                operationProduct = product
                operationScanPhase = OperationScanPhase.DESTINATION
                message = "${product.title} • scan destination bin"
                requestCameraScan("Scan destination bin")
            }
            OperationScanPhase.DESTINATION -> {
                val product = operationProduct ?: return
                operationDestinationInput = canonicalLocation(value)
                val qty = operationQtyInput.toIntOrNull()?.coerceAtLeast(1) ?: 1
                operationScanPhase = OperationScanPhase.SYNCING
                graph.operations.enqueue(
                    kind = PendingOperationEvent.Kind.BOH_MOVE,
                    productId = product.productId,
                    qty = qty,
                    sourceLocationId = operationSourceInput,
                    destinationLocationId = operationDestinationInput,
                    onResult = ::handleOperationSync,
                )
                message = "BOH move persisted • awaiting ACK"
            }
            OperationScanPhase.SYNCING -> message = "Waiting for server confirmation"
        }
    }

    private fun handleDamageScan(value: String) {
        when (operationScanPhase) {
            OperationScanPhase.SOURCE -> {
                operationSourceInput = canonicalLocation(value)
                lastLocationId = operationSourceInput
                operationScanPhase = OperationScanPhase.ITEM
                message = "Source ${operationSourceInput} • scan damaged item"
                requestCameraScan("Scan damaged item barcode")
            }
            OperationScanPhase.ITEM -> resolveBarcode(value) { product ->
                operationProduct = product
                operationScanPhase = OperationScanPhase.SYNCING
                graph.operations.enqueue(
                    kind = PendingOperationEvent.Kind.DAMAGE,
                    productId = product.productId,
                    qty = operationQtyInput.toIntOrNull()?.coerceAtLeast(1) ?: 1,
                    sourceLocationId = operationSourceInput,
                    reason = operationReasonInput.ifBlank { "DAMAGED" },
                    onResult = ::handleOperationSync,
                )
                message = "Damage move persisted • awaiting ACK"
            }
            OperationScanPhase.DESTINATION -> Unit
            OperationScanPhase.SYNCING -> message = "Waiting for server confirmation"
        }
    }

    private fun handleCycleCountScan(value: String) {
        if (cycleCountSessionId == null) {
            cycleCountLocation = canonicalLocation(value)
            startCycleCount(cycleCountLocation)
            return
        }
        resolveBarcode(value) { product ->
            cycleCountProduct = product
            cycleCountQtyInput = "0"
            message = "${product.title} • enter physical count"
        }
    }

    private fun handleRecoveryScan(value: String) {
        val summary = recoverySummary
        if (summary == null) {
            recoveryTaskIdInput = value.trim()
            loadRecovery(recoveryTaskIdInput)
            return
        }
        val item = summary.items.firstOrNull() ?: run {
            message = "Recovery is already complete"
            return
        }
        val destination = canonicalLocation(value)
        if (item.compatibleDestinations.isNotEmpty() && destination !in item.compatibleDestinations) {
            errorMessage = "Destination is not compatible for ${item.title}"
            requestCameraScan("Scan a compatible recovery destination")
            return
        }
        graph.operations.enqueue(
            kind = PendingOperationEvent.Kind.RECOVERY_STOW,
            resourceId = summary.taskId,
            productId = item.productId,
            qty = item.qty,
            sourceLocationId = item.sourceLocationId,
            destinationLocationId = destination,
            onResult = ::handleOperationSync,
        )
        message = "Recovery stow persisted • awaiting ACK"
    }

    private fun handleReceiveScan(value: String) {
        val shipment = selectedShipment
        if (shipment == null) {
            val needle = value.trim().uppercase()
            val match = shipments.firstOrNull {
                it.id.equals(needle, true) || it.label.equals(needle, true)
            }
            if (match != null) selectShipment(match)
            else {
                errorMessage = "Shipment not found"
                requestCameraScan("Scan shipment label or ID")
            }
            return
        }

        if (shipment.status == "STOWING" || selectedStowTaskId != null) {
            val pending = shipment.stowTasks.firstOrNull { it.id == selectedStowTaskId }
                ?: shipment.stowTasks.firstOrNull { it.status != "COMPLETED" }
            if (pending == null) {
                message = "All stow tasks are complete"
                return
            }
            selectedStowTaskId = pending.id
            stowDestinationInput = canonicalLocation(value)
            lastLocationId = stowDestinationInput
            message = "Destination $stowDestinationInput scanned • confirm stow"
            return
        }

        resolveBarcode(value) { product ->
            receiveProduct = product
            message = "${product.title} • confirm good/damaged quantity"
        }
    }

    private fun handleReplenishmentScan(value: String) {
        val task = activeReplenishment ?: run {
            message = "Claim a replenishment task first"
            return
        }
        if (busy) return
        busy = true
        worker.execute {
            val response = when (replenishmentPhase) {
                ReplenishmentScanPhase.SOURCE -> callWithRefresh {
                    graph.api.scanReplenishmentSource(task.id, UUID.randomUUID().toString(), value)
                }
                ReplenishmentScanPhase.ITEM -> callWithRefresh {
                    graph.api.scanReplenishmentItem(task.id, UUID.randomUUID().toString(), value)
                }
                ReplenishmentScanPhase.DESTINATION -> callWithRefresh {
                    graph.api.scanReplenishmentDestination(task.id, UUID.randomUUID().toString(), value)
                }
                ReplenishmentScanPhase.COMPLETE -> ApiClient.Result(409, "{\"detail\":\"Confirm quantity to complete\"}")
            }
            val updated = if (response.ok) runCatching {
                graph.api.parseReplenishmentEnvelope(response.body)
            }.getOrNull() else null
            ui {
                busy = false
                if (updated != null) {
                    activeReplenishment = updated
                    syncReplenishmentPhase(updated)
                    message = when (replenishmentPhase) {
                        ReplenishmentScanPhase.SOURCE -> "Scan source ${updated.sourceLocationId}"
                        ReplenishmentScanPhase.ITEM -> "Source confirmed • scan item barcode"
                        ReplenishmentScanPhase.DESTINATION -> "Item confirmed • scan ${updated.destinationLocationId}"
                        ReplenishmentScanPhase.COMPLETE -> "Destination confirmed • enter actual quantity"
                    }
                    requestCameraForCurrentContext()
                } else {
                    errorMessage = graph.api.parseConflictMessage(response.body)
                    requestCameraForCurrentContext()
                }
            }
        }
    }

    private fun handlePickScan(value: String) {
        val task = currentTask ?: run {
            message = "No active task"
            return
        }
        if (task.taskStatus == "OFFERED") {
            message = "Accept the order before scanning"
            return
        }
        if (task.recoveryRequired || task.taskStatus == "RECOVERY_REQUIRED") {
            errorMessage = "This order changed state. Recovery workflow required."
            return
        }
        if (scanPhase == PickScanPhase.SYNCING) {
            message = "Waiting for server confirmation • do not rescan"
            return
        }
        if (task.taskStatus == "PICKED") {
            closeBag(value)
            return
        }
        if (scanPhase == PickScanPhase.DONE) {
            message = "Pick already complete"
            return
        }

        val item = task.currentItem ?: run {
            scanPhase = PickScanPhase.DONE
            message = "All units confirmed"
            return
        }

        when (scanPhase) {
            PickScanPhase.BIN -> {
                val scanned = canonicalLocation(value)
                val expected = canonicalLocation(item.locationId)
                if (scanned == expected) {
                    lastLocationId = item.locationId
                    scanPhase = PickScanPhase.ITEM
                    message = "Bin confirmed • scan ${item.title}"
                    requestCameraScan("Scan " + item.title + " barcode")
                } else {
                    errorMessage = "Wrong bin: ${value.trim()} • expected ${item.locationId}"
                    message = "Bin rejected"
                    requestCameraScan("Scan bin " + item.locationId)
                }
            }
            PickScanPhase.ITEM -> {
                val code = value.trim()
                if (item.barcodes.isNotEmpty() && code !in item.barcodes) {
                    errorMessage = "Wrong item barcode • expected ${item.asin ?: item.productId}"
                    message = "Item rejected"
                    requestCameraScan("Scan " + item.title + " barcode")
                    return
                }
                submittingItemId = item.id
                scanPhase = PickScanPhase.SYNCING
                message = "Scan persisted • awaiting server ACK"
                graph.picks.createPick(
                    taskId = task.taskId,
                    taskItemId = item.id,
                    locationId = item.locationId,
                    productId = item.productId,
                    qty = 1,
                    barcode = code,
                    onResult = ::handlePickSync,
                )
            }
            PickScanPhase.SYNCING, PickScanPhase.DONE -> Unit
        }
    }

    private fun handlePickSync(result: PickSyncResult) {
        ui {
            when (result) {
                is PickSyncResult.Acked -> {
                    currentTask = result.snapshot
                    val next = result.snapshot.currentItem
                    scanPhase = when {
                        result.snapshot.taskStatus == "PICKED" || next == null -> PickScanPhase.DONE
                        next.id == submittingItemId -> PickScanPhase.ITEM
                        else -> PickScanPhase.BIN
                    }
                    scannedValue = ""
                    message = if (scanPhase == PickScanPhase.DONE) {
                        "Pick complete • server confirmed"
                    } else if (scanPhase == PickScanPhase.ITEM) {
                        "Unit confirmed • scan next unit"
                    } else {
                        "Unit confirmed • scan next bin"
                    }
                    submittingItemId = null
                    requestCameraForCurrentContext()
                }
                is PickSyncResult.Queued -> {
                    scanPhase = PickScanPhase.SYNCING
                    message = result.reason
                }
                is PickSyncResult.Conflict -> {
                    result.snapshot?.let { currentTask = it }
                    scanPhase = PickScanPhase.BIN
                    submittingItemId = null
                    errorMessage = result.message
                    message = "Reconciled to server state"
                    requestCameraForCurrentContext()
                }
                PickSyncResult.AuthenticationRequired -> expireSession()
            }
        }
    }

    private fun installTask(task: TaskSnapshot) {
        currentTask = task
        screen = AppScreen.PICK
        scanPhase = when {
            task.taskStatus == "PICKED" || task.remainingUnits <= 0 -> PickScanPhase.DONE
            task.recoveryRequired || task.taskStatus == "RECOVERY_REQUIRED" -> PickScanPhase.DONE
            else -> PickScanPhase.BIN
        }
        if (task.taskStatus != "OFFERED" && !task.recoveryRequired) {
            requestCameraForCurrentContext()
        }
    }

    private fun callWithRefresh(block: () -> ApiClient.Result): ApiClient.Result {
        var response = runCatching(block).getOrElse { return ApiClient.Result(599, it.message.orEmpty()) }
        if (response.code == 401 && graph.sessions.refreshBlocking()) {
            response = runCatching(block).getOrElse { return ApiClient.Result(599, it.message.orEmpty()) }
        }
        return response
    }

    private fun canonicalLocation(value: String): String =
        runCatching { LocationParser.parse(value).canonical }
            .getOrElse { value.trim().uppercase().replace(" ", "") }

    private fun expireSession() {
        graph.sessions.logout()
        session = null
        authenticated = false
        currentTask = null
        screen = AppScreen.HOME
        scanPhase = PickScanPhase.BIN
        errorMessage = "Session expired • sign in again"
        message = "Authentication required"
    }

    private fun ui(block: () -> Unit) {
        if (Looper.myLooper() == Looper.getMainLooper()) block() else main.post(block)
    }

    override fun onCleared() {
        main.removeCallbacks(heartbeatRunnable)
        main.removeCallbacks(offerPollRunnable)
        ScanBus.unsubscribe(scannerListener)
        worker.shutdownNow()
    }
}
