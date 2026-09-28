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
import com.obieda.fulfillos.data.ScanBus
import com.obieda.fulfillos.domain.AppScreen
import com.obieda.fulfillos.domain.ConnectivityState
import com.obieda.fulfillos.domain.ClosedBagSummary
import com.obieda.fulfillos.domain.OrderCompletionSummary
import com.obieda.fulfillos.domain.InventoryLookup
import com.obieda.fulfillos.domain.LocationParser
import com.obieda.fulfillos.domain.PickScanPhase
import com.obieda.fulfillos.domain.SessionInfo
import com.obieda.fulfillos.domain.TaskSnapshot
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

    var screen by mutableStateOf(AppScreen.HOME)
        private set
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

    private var submittingItemId: String? = null
    private var lastLocationId: String? = null
    private val heartbeatIntervalMs = 5_000L
    private val offerPollIntervalMs = 3_000L

    private val heartbeatRunnable = object : Runnable {
        override fun run() {
            if (authenticated && session?.mustChangePassword != true) sendHeartbeat()
            main.postDelayed(this, heartbeatIntervalMs)
        }
    }

    private val offerPollRunnable = object : Runnable {
        override fun run() {
            if (authenticated && session?.mustChangePassword != true && connectivity == ConnectivityState.ONLINE && !busy) {
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
            if (recovered != null && !recovered.mustChangePassword) {
                val response = callWithRefresh { graph.api.getActiveTask() }
                if (response.ok) task = runCatching { graph.api.parseTaskEnvelope(response.body) }.getOrNull()
            }
            ui {
                session = recovered
                authenticated = recovered != null
                booting = false
                busy = false
                if (recovered == null) {
                    message = "Sign in to this trusted PDA"
                } else {
                    message = if (task != null) "Active order restored" else "Online • waiting for orders"
                    if (task != null) installTask(task)
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
            if (loggedIn != null && !loggedIn.mustChangePassword) {
                val active = graph.api.getActiveTask()
                if (active.ok) task = runCatching { graph.api.parseTaskEnvelope(active.body) }.getOrNull()
            }
            ui {
                busy = false
                if (loggedIn == null) {
                    errorMessage = result.exceptionOrNull()?.message ?: "Login failed"
                    message = "Authentication failed"
                } else {
                    session = loggedIn
                    authenticated = true
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

    private fun sendHeartbeat() {
        if (!authenticated) return
        val taskId = currentTask?.taskId
        val location = lastLocationId
        val activity = when {
            currentTask != null -> "ORDER_${currentTask?.taskStatus ?: "ACTIVE"}"
            screen == AppScreen.INVENTORY -> "INVENTORY_VIEW"
            screen == AppScreen.UNPACK -> "UNPACK"
            screen == AppScreen.BOH -> "BOH_MOVE"
            screen == AppScreen.DAMAGE -> "DAMAGE"
            screen == AppScreen.CYCLE_COUNT -> "CYCLE_COUNT"
            screen == AppScreen.RECOVERY -> "RECOVERY"
            screen == AppScreen.RECEIVE -> "RECEIVE"
            screen == AppScreen.REPLENISHMENT -> "REPLENISHMENT"
            else -> "WAITING_FOR_ORDER"
        }
        worker.execute {
            val response = callWithRefresh {
                graph.api.heartbeat(
                    currentTaskId = taskId,
                    appVersion = BuildConfig.VERSION_NAME,
                    connectivity = connectivity.name,
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
            AppScreen.HOME -> message = "Scan received • open a tool to use it"
            AppScreen.UNPACK,
            AppScreen.BOH,
            AppScreen.DAMAGE,
            AppScreen.CYCLE_COUNT,
            AppScreen.RECOVERY,
            AppScreen.RECEIVE,
            AppScreen.REPLENISHMENT -> message = "Scan received • operation screen is not active yet"
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
                } else {
                    errorMessage = "Wrong bin: ${value.trim()} • expected ${item.locationId}"
                    message = "Bin rejected"
                }
            }
            PickScanPhase.ITEM -> {
                val code = value.trim()
                if (item.barcodes.isNotEmpty() && code !in item.barcodes) {
                    errorMessage = "Wrong item barcode • expected ${item.asin ?: item.productId}"
                    message = "Item rejected"
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
