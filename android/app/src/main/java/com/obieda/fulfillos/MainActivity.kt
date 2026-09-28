package com.obieda.fulfillos

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.core.content.ContextCompat
import com.obieda.fulfillos.data.ScannerBroadcastReceiver
import com.obieda.fulfillos.data.ScannerIntentAdapter
import com.obieda.fulfillos.domain.AppScreen
import com.obieda.fulfillos.domain.ConnectivityState
import com.obieda.fulfillos.domain.LocationParser
import com.obieda.fulfillos.domain.PickScanPhase
import com.obieda.fulfillos.domain.TaskItem
import com.obieda.fulfillos.domain.TaskSnapshot
import com.obieda.fulfillos.ui.AppViewModel
import kotlinx.coroutines.delay
import java.time.Duration
import java.time.Instant

class MainActivity : ComponentActivity() {
    private val scannerReceiver = ScannerBroadcastReceiver()
    private var scannerReceiverRegistered = false

    override fun onStart() {
        super.onStart()
        if (!scannerReceiverRegistered) {
            ContextCompat.registerReceiver(
                this,
                scannerReceiver,
                ScannerIntentAdapter.filter(),
                ContextCompat.RECEIVER_EXPORTED,
            )
            scannerReceiverRegistered = true
        }
    }

    override fun onStop() {
        if (scannerReceiverRegistered) {
            runCatching { unregisterReceiver(scannerReceiver) }
            scannerReceiverRegistered = false
        }
        super.onStop()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val graph = (application as FulfillApplication).graph
        setContent {
            val vm: AppViewModel = viewModel { AppViewModel(graph) }
            MaterialTheme {
                FulfillApp(vm)
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun FulfillApp(vm: AppViewModel) {
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner, vm) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_RESUME -> vm.onAppForegrounded()
                Lifecycle.Event.ON_PAUSE -> vm.onAppBackgrounded()
                else -> Unit
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        if (lifecycleOwner.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) {
            vm.onAppForegrounded()
        }
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
            vm.onAppBackgrounded()
        }
    }
    if (vm.booting) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
                CircularProgressIndicator()
                Text("Recovering PDA session…")
            }
        }
        return
    }

    if (!vm.authenticated) {
        LoginScreen(vm)
        return
    }

    if (vm.session?.mustChangePassword == true) {
        ForcePersonalPinScreen(vm)
        return
    }

    var cameraOpen by remember { mutableStateOf(false) }

    LaunchedEffect(vm.cameraRequestId) {
        if (vm.cameraRequestId > 0 && vm.appForeground) {
            cameraOpen = true
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text("FulfillOS", fontWeight = FontWeight.Bold)
                        Text(vm.session?.username.orEmpty(), style = MaterialTheme.typography.labelSmall)
                    }
                },
                actions = {
                    AssistChip(onClick = {}, label = { Text(vm.connectivity.name) })
                    IconButton(onClick = { vm.requestCameraScan("Manual camera scan") }) {
                        Icon(Icons.Filled.CameraAlt, contentDescription = "Open camera scanner")
                    }
                    IconButton(onClick = vm::logout) {
                        Icon(Icons.Filled.Logout, contentDescription = "Sign out")
                    }
                },
            )
        },
    ) { padding ->
        Column(
            Modifier
                .padding(padding)
                .fillMaxSize()
        ) {
            ConnectionBanner(vm.connectivity, vm.message, vm.errorMessage, vm::clearError)
            when (vm.screen) {
                AppScreen.HOME -> HomeScreen(vm)
                AppScreen.ACTIVITY -> ActivityRecorderScreen(vm)
                AppScreen.PICK -> PickScreen(vm)
                AppScreen.INVENTORY -> InventoryScreen(vm)
                AppScreen.UNPACK -> UnpackScreen(vm)
                AppScreen.BOH -> BohMoveScreen(vm)
                AppScreen.DAMAGE -> DamageScreen(vm)
                AppScreen.CYCLE_COUNT -> CycleCountScreen(vm)
                AppScreen.RECOVERY -> RecoveryScreen(vm)
                AppScreen.RECEIVE -> ReceiveScreen(vm)
                AppScreen.REPLENISHMENT -> ReplenishmentScreen(vm)
            }
        }
    }

    if (cameraOpen) {
        CameraScannerOverlay(
            prompt = vm.cameraRequestHint,
            onScan = { value ->
                vm.submitScanValue(value)
                cameraOpen = false
            },
            onDismiss = { cameraOpen = false },
        )
    }
}

@Composable
private fun ForcePersonalPinScreen(vm: AppViewModel) {
    Box(Modifier.fillMaxSize().padding(24.dp), contentAlignment = Alignment.Center) {
        ElevatedCard(Modifier.fillMaxWidth(), shape = RoundedCornerShape(24.dp)) {
            Column(
                Modifier.padding(22.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                Text("Create your personal PIN", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
                Text(
                    "This is your first sign-in with a temporary PIN. Choose a private 6–10 digit PIN you can remember. Warehouse tools stay locked until this is complete.",
                    style = MaterialTheme.typography.bodyMedium,
                )
                OutlinedTextField(
                    value = vm.newPinInput,
                    onValueChange = { value -> vm.newPinInput = value.filter(Char::isDigit).take(10) },
                    label = { Text("New PIN") },
                    singleLine = true,
                    visualTransformation = PasswordVisualTransformation(),
                    modifier = Modifier.fillMaxWidth(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword, imeAction = ImeAction.Next),
                )
                OutlinedTextField(
                    value = vm.confirmPinInput,
                    onValueChange = { value -> vm.confirmPinInput = value.filter(Char::isDigit).take(10) },
                    label = { Text("Confirm PIN") },
                    singleLine = true,
                    visualTransformation = PasswordVisualTransformation(),
                    modifier = Modifier.fillMaxWidth(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword, imeAction = ImeAction.Done),
                )
                Text("6–10 digits only. Do not share it with coworkers.", style = MaterialTheme.typography.bodySmall)
                vm.errorMessage?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                Button(
                    onClick = vm::completeFirstLoginPin,
                    enabled = !vm.busy &&
                        vm.newPinInput.length in 6..10 &&
                        vm.confirmPinInput.length in 6..10,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    if (vm.busy) CircularProgressIndicator(Modifier.height(20.dp)) else Text("Save PIN & continue")
                }
                TextButton(onClick = vm::logout, modifier = Modifier.align(Alignment.End)) {
                    Text("Sign out")
                }
            }
        }
    }
}


@Composable
private fun LoginScreen(vm: AppViewModel) {
    Box(Modifier.fillMaxSize().padding(24.dp), contentAlignment = Alignment.Center) {
        ElevatedCard(Modifier.fillMaxWidth(), shape = RoundedCornerShape(24.dp)) {
            Column(
                Modifier.padding(22.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                Text("FulfillOS", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
                Text("Trusted PDA sign-in", style = MaterialTheme.typography.titleMedium)
                Text(
                    "The active task belongs to the server. Re-authentication restores the same task instead of starting over.",
                    style = MaterialTheme.typography.bodySmall,
                )
                OutlinedTextField(
                    value = vm.usernameInput,
                    onValueChange = { vm.usernameInput = it },
                    label = { Text("Username") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next),
                )
                OutlinedTextField(
                    value = vm.passwordInput,
                    onValueChange = { value -> vm.passwordInput = value.filter(Char::isDigit).take(10) },
                    label = { Text("6–10 digit PIN") },
                    singleLine = true,
                    visualTransformation = PasswordVisualTransformation(),
                    modifier = Modifier.fillMaxWidth(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword, imeAction = ImeAction.Done),
                )
                TextButton(
                    onClick = vm::forgotPassword,
                    enabled = !vm.busy && vm.usernameInput.isNotBlank(),
                    modifier = Modifier.align(Alignment.End),
                ) {
                    Text("Forgot password?")
                }
                vm.errorMessage?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                Button(
                    onClick = vm::login,
                    enabled = !vm.busy && vm.usernameInput.isNotBlank() && vm.passwordInput.length in 6..10,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    if (vm.busy) CircularProgressIndicator(Modifier.height(20.dp)) else Text("Sign in")
                }
            }
        }
    }
}

@Composable
private fun ConnectionBanner(
    connectivity: ConnectivityState,
    message: String,
    error: String?,
    clearError: () -> Unit,
) {
    val title = when (connectivity) {
        ConnectivityState.ONLINE -> "Online • server ACK required"
        ConnectivityState.OFFLINE -> "Offline • durable queue active"
        ConnectivityState.RECONNECTING -> "Reconnecting • task state preserved"
    }
    Surface(tonalElevation = 1.dp) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 18.dp, vertical = 10.dp)) {
            Text(title, fontWeight = FontWeight.SemiBold)
            Text(message, style = MaterialTheme.typography.bodySmall)
            if (error != null) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(error, color = MaterialTheme.colorScheme.error, modifier = Modifier.weight(1f), style = MaterialTheme.typography.bodySmall)
                    TextButton(onClick = clearError) { Text("Dismiss") }
                }
            }
        }
    }
}

@Composable
private fun HomeScreen(vm: AppViewModel) {
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Operations", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                Text(
                    if (vm.workerState == "AVAILABLE") "Ready • live every 3s"
                    else vm.workerState.replace("_", " "),
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            AssistChip(onClick = vm::openActivityRecorder, label = { Text(vm.workerState.replace("_", " ")) })
        }

        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            OperationModule(
                name = "Task",
                subtitle = "Break / activity",
                icon = Icons.Filled.Assignment,
                onClick = vm::openActivityRecorder,
                modifier = Modifier.weight(1f),
            )
            OperationModule(
                name = if (vm.currentTask == null) "Pick" else "Order",
                subtitle = if (vm.currentTask == null) "Waiting" else "Resume",
                icon = Icons.Filled.ShoppingCart,
                onClick = vm::openPick,
                modifier = Modifier.weight(1f),
            )
            OperationModule(
                name = "Stock",
                subtitle = "Search / scan",
                icon = Icons.Filled.Inventory2,
                onClick = vm::openInventory,
                modifier = Modifier.weight(1f),
            )
        }

        Text("Warehouse", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            OperationModule("Receive", "Inbound", Icons.Filled.LocalShipping, vm::openReceive, Modifier.weight(1f))
            OperationModule("Unpack", "Returns", Icons.Filled.Inventory, vm::openUnpack, Modifier.weight(1f))
            OperationModule("BOH", "Move", Icons.Filled.SwapHoriz, vm::openBoh, Modifier.weight(1f))
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            OperationModule("Damage", "DMG", Icons.Filled.Delete, vm::openDamage, Modifier.weight(1f))
            OperationModule("Count", "Cycle", Icons.Filled.FactCheck, vm::openCycleCount, Modifier.weight(1f))
            OperationModule("Replenish", "Restock", Icons.Filled.PlaylistAddCheck, vm::openReplenishment, Modifier.weight(1f))
        }
        OperationModule(
            "Recovery",
            "Exceptions / cancelled stock",
            Icons.Filled.Warning,
            vm::openRecovery,
            Modifier.fillMaxWidth(),
        )
    }
}

@Composable
private fun OperationModule(
    name: String,
    subtitle: String,
    icon: ImageVector,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    ElevatedCard(onClick = onClick, modifier = modifier.heightIn(min = 104.dp)) {
        Column(
            Modifier.fillMaxWidth().padding(horizontal = 10.dp, vertical = 14.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Icon(icon, contentDescription = name, modifier = Modifier.size(30.dp))
            Text(name, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleSmall)
            Text(subtitle, style = MaterialTheme.typography.labelSmall)
        }
    }
}

@Composable
private fun IconTaskButton(
    label: String,
    icon: ImageVector,
    onClick: () -> Unit,
    enabled: Boolean,
    modifier: Modifier = Modifier,
) {
    FilledTonalButton(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier.heightIn(min = 58.dp),
        contentPadding = PaddingValues(horizontal = 10.dp, vertical = 8.dp),
    ) {
        Icon(icon, contentDescription = label)
        Spacer(Modifier.width(6.dp))
        Text(label)
    }
}


@Composable
private fun ActivityRecorderScreen(vm: AppViewModel) {
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = vm::goHome) {
                Icon(Icons.Filled.Home, contentDescription = "Home")
            }
            Text("Record task", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
            Spacer(Modifier.weight(1f))
            IconButton(onClick = vm::refreshWorkerState, enabled = !vm.busy) {
                Icon(Icons.Filled.Refresh, contentDescription = "Refresh worker state")
            }
        }

        ElevatedCard(Modifier.fillMaxWidth(), shape = RoundedCornerShape(18.dp)) {
            Row(
                Modifier.fillMaxWidth().padding(16.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Icon(
                    if (vm.workerState == "AVAILABLE") Icons.Filled.CheckCircle else Icons.Filled.Assignment,
                    contentDescription = null,
                    modifier = Modifier.size(34.dp),
                )
                Column(Modifier.weight(1f)) {
                    Text("Current", style = MaterialTheme.typography.labelMedium)
                    Text(vm.workerState.replace("_", " "), style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                }
                if (vm.workerState != "AVAILABLE") {
                    val manualFinishStates = setOf(
                        "BREAK", "TRAINING", "BIN_CHECK", "EXPIRY_AUDIT",
                        "VENDOR_REMOVAL", "BOH_MOVE", "ENDING_SHIFT",
                    )
                    IconButton(
                        onClick = vm::finishRecordedActivity,
                        enabled = !vm.busy && vm.currentTask == null && vm.workerState in manualFinishStates,
                    ) {
                        Icon(Icons.Filled.Done, contentDescription = "Finish current task and become available")
                    }
                }
            }
        }

        if (vm.currentTask != null) {
            ElevatedCard(onClick = vm::openPick, modifier = Modifier.fillMaxWidth()) {
                Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Filled.ShoppingCart, contentDescription = null, modifier = Modifier.size(30.dp))
                    Spacer(Modifier.width(12.dp))
                    Column(Modifier.weight(1f)) {
                        Text("Active order", fontWeight = FontWeight.Bold)
                        Text("Other tasks are locked", style = MaterialTheme.typography.bodySmall)
                    }
                    Icon(Icons.Filled.PlayArrow, contentDescription = "Return to order")
                }
            }
        } else {
            OutlinedTextField(
                value = vm.activityReasonInput,
                onValueChange = { vm.activityReasonInput = it.take(120) },
                label = { Text("Note (optional)") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )

            Text("Break", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                IconTaskButton("Break", Icons.Filled.Pause, { vm.startBreak("REST") }, !vm.busy && vm.workerState == "AVAILABLE", Modifier.weight(1f))
                IconTaskButton("Meal", Icons.Filled.Restaurant, { vm.startBreak("MEAL") }, !vm.busy && vm.workerState == "AVAILABLE", Modifier.weight(1f))
            }

            Text("Other work", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                IconTaskButton("Training", Icons.Filled.School, { vm.recordActivity("TRAINING", "TRAINING") }, !vm.busy && vm.workerState == "AVAILABLE", Modifier.weight(1f))
                IconTaskButton("Bin", Icons.Filled.Inventory2, { vm.recordActivity("BIN_CHECK", "BIN_CHECK") }, !vm.busy && vm.workerState == "AVAILABLE", Modifier.weight(1f))
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                IconTaskButton("Expiry", Icons.Filled.FactCheck, { vm.recordActivity("EXPIRY_AUDIT", "EXPIRY_AUDIT") }, !vm.busy && vm.workerState == "AVAILABLE", Modifier.weight(1f))
                IconTaskButton("Vendor", Icons.Filled.LocalShipping, { vm.recordActivity("VENDOR_REMOVAL", "VENDOR_REMOVAL") }, !vm.busy && vm.workerState == "AVAILABLE", Modifier.weight(1f))
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                IconTaskButton("BOH", Icons.Filled.SwapHoriz, { vm.recordActivity("BOH_MOVE", "MANUAL_BOH_TASK") }, !vm.busy && vm.workerState == "AVAILABLE", Modifier.weight(1f))
                IconTaskButton("End shift", Icons.Filled.Logout, { vm.recordActivity("ENDING_SHIFT", "ENDING_SHIFT") }, !vm.busy && vm.workerState == "AVAILABLE", Modifier.weight(1f))
            }

            if (vm.workerState == "AVAILABLE") {
                Text("Workflows", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    OperationModule("Receive", "Inbound", Icons.Filled.LocalShipping, vm::openReceive, Modifier.weight(1f))
                    OperationModule("Unpack", "Returns", Icons.Filled.Inventory, vm::openUnpack, Modifier.weight(1f))
                    OperationModule("Count", "Cycle", Icons.Filled.FactCheck, vm::openCycleCount, Modifier.weight(1f))
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    OperationModule("Replenish", "Restock", Icons.Filled.PlaylistAddCheck, vm::openReplenishment, Modifier.weight(1f))
                    OperationModule("BOH", "Move", Icons.Filled.SwapHoriz, vm::openBoh, Modifier.weight(1f))
                    Spacer(Modifier.weight(1f))
                }
            }
        }
    }
}


@Composable
private fun PickScreen(vm: AppViewModel) {
    val task = vm.currentTask
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = vm::goHome) {
                Icon(Icons.Filled.Home, contentDescription = "Home")
            }
            Spacer(Modifier.weight(1f))
            IconButton(onClick = vm::refreshTask, enabled = task != null) {
                Icon(Icons.Filled.Refresh, contentDescription = "Refresh order")
            }
        }

        if (task == null) {
            val summary = vm.completionSummary
            if (summary != null) {
                ElevatedCard(Modifier.fillMaxWidth(), shape = RoundedCornerShape(22.dp)) {
                    Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        Text("ORDER COMPLETE", style = MaterialTheme.typography.labelLarge)
                        Text(
                            summary.externalRef ?: summary.orderId.take(12),
                            style = MaterialTheme.typography.headlineSmall,
                            fontWeight = FontWeight.Bold,
                        )
                        Text("${summary.pickedUnits} picked • ${summary.shortedUnits} short • ${summary.bagCount} bag(s)")
                        summary.items.forEach { item ->
                            Row(Modifier.fillMaxWidth()) {
                                Text(item.title, modifier = Modifier.weight(1f))
                                Text(
                                    "${item.pickedQty}/${item.requestedQty}" +
                                        if (item.shortedQty > 0) " • short ${item.shortedQty}" else "",
                                    fontWeight = FontWeight.SemiBold,
                                )
                            }
                        }
                        HorizontalDivider()
                        Text("Bags / SPOO", fontWeight = FontWeight.Bold)
                        summary.bags.forEach { bag ->
                            Text("Bag ${bag.bagNo} • ••••${bag.spooLast4}")
                        }
                        Button(onClick = vm::goHome, modifier = Modifier.fillMaxWidth()) {
                            Icon(Icons.Filled.Done, contentDescription = null)
                            Spacer(Modifier.width(8.dp))
                            Text("Done")
                        }
                    }
                }
            } else {
                Text("Waiting for Orders", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
                Text("No task is owned by this picker right now.")
                Button(onClick = vm::claimNext, enabled = !vm.busy, modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.Filled.Refresh, contentDescription = null)
                    Spacer(Modifier.width(8.dp))
                    Text("Check")
                }
            }
            return@Column
        }

        if (task.taskStatus == "OFFERED") {
            OfferPanel(task, vm)
            return@Column
        }

        if (task.recoveryRequired || task.taskStatus == "RECOVERY_REQUIRED") {
            ElevatedCard(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Recovery required", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                    Text("The order changed after physical inventory moved. Do not continue picking. A recovery/stow workflow must reconcile the tote.")
                    Text("Order ${task.orderId.take(12)}… • v${task.serverVersion}")
                    Button(onClick = vm::refreshTask, modifier = Modifier.fillMaxWidth()) {
                        Icon(Icons.Filled.Refresh, contentDescription = null)
                        Spacer(Modifier.width(8.dp))
                        Text("Refresh")
                    }
                }
            }
            return@Column
        }

        ActivePickPanel(task, vm)
    }
}

@Composable
private fun OfferPanel(task: TaskSnapshot, vm: AppViewModel) {
    ElevatedCard(Modifier.fillMaxWidth(), shape = RoundedCornerShape(22.dp)) {
        Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("NEW ORDER", style = MaterialTheme.typography.labelLarge)
            Text("${task.expectedUnits} units", style = MaterialTheme.typography.displaySmall, fontWeight = FontWeight.Bold)
            val lines = task.items.count { it.plannedQty > 0 }
            Text("$lines item lines • Order ${task.orderId.take(10)}…")
            OfferCountdown(task.offerExpiresAt)
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedButton(onClick = vm::rejectOffer, enabled = !vm.busy, modifier = Modifier.weight(1f)) {
                    Icon(Icons.Filled.Close, contentDescription = null)
                    Spacer(Modifier.width(6.dp))
                    Text("Reject")
                }
                Button(onClick = vm::acceptOffer, enabled = !vm.busy, modifier = Modifier.weight(1f)) {
                    Icon(Icons.Filled.CheckCircle, contentDescription = null)
                    Spacer(Modifier.width(6.dp))
                    Text("Accept")
                }
            }
        }
    }
}

@Composable
private fun OfferCountdown(expiresAt: String?) {
    var remaining by remember(expiresAt) { mutableIntStateOf(secondsRemaining(expiresAt)) }
    LaunchedEffect(expiresAt) {
        while (remaining > 0) {
            delay(1_000)
            remaining = secondsRemaining(expiresAt)
        }
    }
    LinearProgressIndicator(
        progress = { (remaining.coerceIn(0, 30) / 30f) },
        modifier = Modifier.fillMaxWidth(),
    )
    Text("Offer expires in ${remaining}s", fontWeight = FontWeight.SemiBold)
}

private fun secondsRemaining(expiresAt: String?): Int {
    if (expiresAt == null) return 30
    return runCatching {
        Duration.between(Instant.now(), Instant.parse(expiresAt)).seconds.coerceAtLeast(0).coerceAtMost(30).toInt()
    }.getOrDefault(30)
}

@Composable
private fun ActivePickPanel(task: TaskSnapshot, vm: AppViewModel) {
    val item = task.currentItem
    val progress = if (task.expectedUnits <= 0) 0f else task.processedUnits.toFloat() / task.expectedUnits.toFloat()

    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text("Order ${task.orderId.take(10)}…", style = MaterialTheme.typography.labelLarge)
            Text("${task.processedUnits}/${task.expectedUnits} processed", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
            if (task.shortedUnits > 0) {
                Text("Picked ${task.pickedUnits} • Short ${task.shortedUnits}", style = MaterialTheme.typography.bodySmall)
            }
        }
        Text("v${task.serverVersion}", style = MaterialTheme.typography.labelMedium)
    }
    LinearProgressIndicator(progress = { progress.coerceIn(0f, 1f) }, modifier = Modifier.fillMaxWidth())

    if (task.taskStatus == "PICKED" || item == null || vm.scanPhase == PickScanPhase.DONE) {
        ElevatedCard(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("Pick complete", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                Text("Scan every bag SPOO now. One order may close on one or more bags.")
                if (vm.closedBags.isEmpty()) {
                    Text("No bags closed yet • scan the first bag barcode", fontWeight = FontWeight.SemiBold)
                } else {
                    vm.closedBags.forEach { bag ->
                        Text("Bag ${bag.bagNo} • SPOO ••••${bag.spooLast4}")
                    }
                    Text("Scan another SPOO for another bag, or finish the order.")
                }
                if (vm.busy) LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
                Button(
                    onClick = vm::finishPickedOrder,
                    enabled = vm.closedBags.isNotEmpty() && !vm.busy,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Icon(Icons.Filled.Done, contentDescription = null)
                    Spacer(Modifier.width(8.dp))
                    Text("Finish")
                }
            }
        }
        return
    }

    LocationCard(item)

    ElevatedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(item.title, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Text(item.asin ?: item.productId, style = MaterialTheme.typography.bodySmall)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                item.temperatureClass?.let { AssistChip(onClick = {}, label = { Text(it) }) }
                item.handlingClass?.takeIf { it != "STANDARD" }?.let { AssistChip(onClick = {}, label = { Text(it) }) }
            }
            Text("Remaining ${item.remainingQty} / ${item.plannedQty}", fontWeight = FontWeight.SemiBold)
            HorizontalDivider()
            val prompt = when (vm.scanPhase) {
                PickScanPhase.BIN -> "SCAN BIN BARCODE"
                PickScanPhase.ITEM -> "SCAN ITEM BARCODE"
                PickScanPhase.SYNCING -> "WAITING FOR SERVER ACK"
                PickScanPhase.DONE -> "COMPLETE"
            }
            Text(prompt, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Black)
            if (vm.scanPhase == PickScanPhase.ITEM) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { vm.skipCurrent() }, modifier = Modifier.weight(1f), contentPadding = PaddingValues(8.dp)) {
                        Icon(Icons.Filled.PlayArrow, contentDescription = "Skip")
                    }
                    OutlinedButton(onClick = { vm.shortCurrent() }, modifier = Modifier.weight(1f), contentPadding = PaddingValues(8.dp)) {
                        Icon(Icons.Filled.Close, contentDescription = "Short")
                    }
                    OutlinedButton(onClick = { vm.damagedCurrent() }, modifier = Modifier.weight(1f), contentPadding = PaddingValues(8.dp)) {
                        Icon(Icons.Filled.Delete, contentDescription = "Damaged")
                    }
                }
            }
            if (vm.scannedValue.isNotBlank()) {
                Text("Last scan: ${vm.scannedValue}", style = MaterialTheme.typography.bodySmall)
            }
            if (vm.scanPhase == PickScanPhase.SYNCING) {
                LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
                OutlinedButton(onClick = vm::retryPending, modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.Filled.Refresh, contentDescription = null)
                    Spacer(Modifier.width(8.dp))
                    Text("Retry")
                }
            }
        }
    }
}

@Composable
private fun LocationCard(item: TaskItem) {
    val parsed = runCatching { LocationParser.parse(item.locationId) }.getOrNull()
    ElevatedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("LOCATION", style = MaterialTheme.typography.labelLarge)
            if (parsed == null || parsed.logical) {
                Text(item.locationId, style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
            } else {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    LocationSegment("Floor", "P-${parsed.floor}", Modifier.weight(1f))
                    LocationSegment("Aisle", "${parsed.fixture ?: parsed.classification}${parsed.aisle}", Modifier.weight(1f))
                    val level = parsed.level.orEmpty()
                    LocationSegment(
                        "Bin",
                        "$level${parsed.slot}",
                        Modifier.weight(1f),
                        levelColor(level),
                    )
                }
            }
            Text(item.locationId, style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
private fun LocationSegment(label: String, value: String, modifier: Modifier = Modifier, color: Color? = null) {
    val background = color ?: MaterialTheme.colorScheme.surfaceVariant
    val foreground = if (color == Color(0xFFFFD54F)) Color(0xFF201A00) else MaterialTheme.colorScheme.onSurface
    Column(
        modifier.background(background, RoundedCornerShape(14.dp)).padding(12.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(label, style = MaterialTheme.typography.labelSmall, color = foreground)
        Text(value, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Black, color = foreground)
    }
}

private fun levelColor(level: String): Color? = when (level.uppercase()) {
    "A" -> Color(0xFF2E7D32)
    "B" -> Color(0xFF1565C0)
    "C" -> Color(0xFFFFD54F)
    else -> null
}

@Composable
private fun InventoryScreen(vm: AppViewModel) {
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = vm::goHome) {
                Icon(Icons.Filled.Home, contentDescription = "Home")
            }
            Text("Inventory", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        }
        Text("Scan a bin or item barcode, or enter an ASIN. Product → locations and location → products are both supported.")
        OutlinedTextField(
            value = vm.inventoryQuery,
            onValueChange = { vm.inventoryQuery = it },
            label = { Text("Location / ASIN") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
        )
        Button(
            onClick = { vm.lookupInventory() },
            enabled = !vm.inventoryLoading && vm.inventoryQuery.isNotBlank(),
            modifier = Modifier.fillMaxWidth(),
        ) {
            if (vm.inventoryLoading) {
                CircularProgressIndicator(Modifier.size(20.dp))
            } else {
                Icon(Icons.Filled.Search, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text("Search")
            }
        }

        vm.inventoryResult?.let { result ->
            ElevatedCard(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(result.heading, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                    Text(result.subheading)
                    result.total?.let { Text("Total on hand: $it", fontWeight = FontWeight.SemiBold) }
                }
            }
            result.rows.forEach { row ->
                Card(Modifier.fillMaxWidth()) {
                    Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(row.primary, fontWeight = FontWeight.SemiBold)
                            Text(row.secondary, style = MaterialTheme.typography.bodySmall)
                        }
                        Text(row.quantity.toString(), style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                    }
                }
            }
        }
    }
}
