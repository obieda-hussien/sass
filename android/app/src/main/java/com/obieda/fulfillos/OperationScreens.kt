package com.obieda.fulfillos

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.obieda.fulfillos.domain.OperationScanPhase
import com.obieda.fulfillos.domain.ReplenishmentScanPhase
import com.obieda.fulfillos.ui.AppViewModel

@Composable
private fun OperationPage(
    title: String,
    subtitle: String,
    vm: AppViewModel,
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
            IconButton(onClick = vm::goHome) {
                Icon(Icons.Filled.Home, contentDescription = "Home")
            }
            Column(Modifier.weight(1f)) {
                Text(title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                Text(subtitle, style = MaterialTheme.typography.bodySmall)
            }
        }
        content()
        Spacer(Modifier.height(30.dp))
    }
}

@Composable
private fun ScanEntry(vm: AppViewModel, hint: String, enabled: Boolean = true) {
    var manual by remember { mutableStateOf("") }
    ElevatedCard(Modifier.fillMaxWidth(), shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(Modifier.fillMaxWidth(), verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                Icon(Icons.Filled.QrCodeScanner, contentDescription = null, modifier = Modifier.size(28.dp))
                Spacer(Modifier.width(10.dp))
                Text(hint, modifier = Modifier.weight(1f), fontWeight = FontWeight.SemiBold)
                IconButton(
                    onClick = { vm.requestCameraScan(hint) },
                    enabled = enabled,
                ) {
                    Icon(Icons.Filled.CameraAlt, contentDescription = "Open camera scanner")
                }
            }
            OutlinedTextField(
                value = manual,
                onValueChange = { manual = it },
                enabled = enabled,
                label = { Text("Barcode / location") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
                leadingIcon = { Icon(Icons.Filled.QrCodeScanner, contentDescription = null) },
                trailingIcon = {
                    IconButton(
                        onClick = { vm.submitScanValue(manual); manual = "" },
                        enabled = enabled && manual.isNotBlank(),
                    ) {
                        Icon(Icons.Filled.ArrowForward, contentDescription = "Submit scan")
                    }
                },
            )
        }
    }
}

@Composable
fun UnpackScreen(vm: AppViewModel) {
    OperationPage("Unpack", "Temperature-safe temporary tote → normal stow.", vm) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf("AMBIENT", "CHILLED", "FROZEN").forEach { temp ->
                FilterChip(
                    selected = vm.unpackTemperature == temp,
                    onClick = { vm.startOrResumeUnpack(temp) },
                    label = { Text(temp) },
                )
            }
        }
        vm.unpackSummary?.let { summary ->
            ElevatedCard(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text("Session ${summary.sessionId.take(8)}", fontWeight = FontWeight.Bold)
                    Text("Temporary tote: ${summary.toteLocationId}")
                    Text("Status: ${summary.status} · ${summary.temperatureClass}")
                    summary.items.forEach {
                        Text("${it.productId.take(10)} · ${it.qty} units · ${it.compatibleDestinations.size} stow options")
                    }
                }
            }
        }
        OutlinedTextField(
            value = vm.operationQtyInput,
            onValueChange = { vm.operationQtyInput = it.filter(Char::isDigit).take(5) },
            label = { Text("Quantity per scan") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            modifier = Modifier.fillMaxWidth(),
        )
        ScanEntry(vm, "Scan each item barcode. The event is durable before network transmission.")
        Button(
            onClick = vm::completeCurrentUnpack,
            enabled = vm.unpackSummary?.status == "OPEN" && !vm.busy,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Icon(Icons.Filled.Done, contentDescription = null)
            Spacer(Modifier.width(8.dp))
            Text("Finish")
        }
    }
}

@Composable
fun BohMoveScreen(vm: AppViewModel) {
    val hint = when (vm.operationScanPhase) {
        OperationScanPhase.SOURCE -> "Scan source bin"
        OperationScanPhase.ITEM -> "Scan item barcode"
        OperationScanPhase.DESTINATION -> "Scan destination bin"
        OperationScanPhase.SYNCING -> "Waiting for server ACK"
    }
    OperationPage("BOH Move", "Source → item → compatible destination.", vm) {
        ElevatedCard(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                Text(hint, fontWeight = FontWeight.Bold)
                Text("Source: ${vm.operationSourceInput.ifBlank { "—" }}")
                Text("Item: ${vm.operationProduct?.title ?: "—"}")
                Text("Destination: ${vm.operationDestinationInput.ifBlank { "—" }}")
            }
        }
        OutlinedTextField(
            value = vm.operationQtyInput,
            onValueChange = { vm.operationQtyInput = it.filter(Char::isDigit).take(5) },
            label = { Text("Move quantity") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            modifier = Modifier.fillMaxWidth(),
        )
        ScanEntry(vm, hint, enabled = vm.operationScanPhase != OperationScanPhase.SYNCING)
    }
}

@Composable
fun DamageScreen(vm: AppViewModel) {
    val hint = when (vm.operationScanPhase) {
        OperationScanPhase.SOURCE -> "Scan source bin"
        OperationScanPhase.ITEM -> "Scan damaged item barcode"
        OperationScanPhase.DESTINATION -> "Damage moves automatically to DMG"
        OperationScanPhase.SYNCING -> "Waiting for server ACK"
    }
    OperationPage("Damage", "Move damaged stock to DMG with evidence.", vm) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(
                value = vm.operationQtyInput,
                onValueChange = { vm.operationQtyInput = it.filter(Char::isDigit).take(5) },
                label = { Text("Quantity") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.weight(1f),
            )
            OutlinedTextField(
                value = vm.operationReasonInput,
                onValueChange = { vm.operationReasonInput = it.take(64) },
                label = { Text("Reason") },
                modifier = Modifier.weight(2f),
            )
        }
        ElevatedCard(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                Text(hint, fontWeight = FontWeight.Bold)
                Text("Source: ${vm.operationSourceInput.ifBlank { "—" }}")
                Text("Item: ${vm.operationProduct?.title ?: "—"}")
                Text("Destination: DMG")
            }
        }
        ScanEntry(vm, hint, enabled = vm.operationScanPhase != OperationScanPhase.SYNCING)
    }
}

@Composable
fun CycleCountScreen(vm: AppViewModel) {
    OperationPage("Cycle Count", "Count physical stock, review variance, then apply explicitly.", vm) {
        if (vm.cycleCountSessionId == null) {
            OutlinedTextField(
                value = vm.cycleCountLocation,
                onValueChange = { vm.cycleCountLocation = it.uppercase() },
                label = { Text("Bin/location") },
                modifier = Modifier.fillMaxWidth(),
            )
            Button(
                onClick = { vm.startCycleCount() },
                enabled = vm.cycleCountLocation.isNotBlank() && !vm.busy,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Icon(Icons.Filled.PlayArrow, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text("Start")
            }
            ScanEntry(vm, "Or scan the bin to start.")
        } else {
            Text("Counting ${vm.cycleCountLocation}", fontWeight = FontWeight.Bold)
            vm.cycleCountProduct?.let { product ->
                ElevatedCard(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(14.dp)) {
                        Text(product.title, fontWeight = FontWeight.Bold)
                        Text(product.asin)
                    }
                }
                OutlinedTextField(
                    value = vm.cycleCountQtyInput,
                    onValueChange = { vm.cycleCountQtyInput = it.filter(Char::isDigit).take(6) },
                    label = { Text("Physical quantity") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    modifier = Modifier.fillMaxWidth(),
                )
                Button(onClick = vm::submitCycleCountLine, modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.Filled.Save, contentDescription = null)
                    Spacer(Modifier.width(8.dp))
                    Text("Save")
                }
            }
            ScanEntry(vm, "Scan item barcode, enter the physical quantity, then save it.")
            if (vm.cycleCountEntries.isNotEmpty()) {
                ElevatedCard(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text("Counted items", fontWeight = FontWeight.Bold)
                        vm.cycleCountEntries.forEach {
                            Text("${it.productId.take(10)} · system ${it.systemQty} · counted ${it.countedQty} · variance ${it.variance}")
                        }
                    }
                }
                Button(onClick = vm::applyCurrentCycleCount, enabled = !vm.busy, modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.Filled.DoneAll, contentDescription = null)
                    Spacer(Modifier.width(8.dp))
                    Text("Apply")
                }
            }
        }
    }
}

@Composable
fun RecoveryScreen(vm: AppViewModel) {
    OperationPage("Recovery", "Return committed stock explicitly after cancellation/exception.", vm) {
        OutlinedTextField(
            value = vm.recoveryTaskIdInput,
            onValueChange = { vm.recoveryTaskIdInput = it },
            label = { Text("Recovery task ID") },
            modifier = Modifier.fillMaxWidth(),
        )
        Button(
            onClick = { vm.loadRecovery() },
            enabled = vm.recoveryTaskIdInput.isNotBlank() && !vm.busy,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Icon(Icons.Filled.Search, contentDescription = null)
            Spacer(Modifier.width(8.dp))
            Text("Load")
        }
        vm.recoverySummary?.let { recovery ->
            ElevatedCard(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(7.dp)) {
                    Text("${recovery.recoveryType} · order ${recovery.orderId.take(8)}", fontWeight = FontWeight.Bold)
                    recovery.items.forEach { item ->
                        Text("${item.title} · ${item.qty} units")
                        if (item.compatibleDestinations.isNotEmpty()) {
                            Text("Suggested: ${item.compatibleDestinations.take(3).joinToString()}", style = MaterialTheme.typography.bodySmall)
                        }
                    }
                }
            }
            ScanEntry(vm, "Scan a compatible destination for the first recovery item.")
        }
    }
}

@Composable
fun ReceiveScreen(vm: AppViewModel) {
    OperationPage("Receive & Stow", "Vendor / ambient / chilled / frozen / HAZ / HRV inbound execution.", vm) {
        val selected = vm.selectedShipment
        if (selected == null) {
            Button(onClick = vm::loadShipments, enabled = !vm.busy, modifier = Modifier.fillMaxWidth()) {
                Icon(Icons.Filled.Refresh, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text("Refresh")
            }
            vm.shipments.forEach { shipment ->
                ElevatedCard(onClick = { vm.selectShipment(shipment) }, modifier = Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text(shipment.label, fontWeight = FontWeight.Bold)
                        Text("${shipment.shipmentType} · ${shipment.storageDomain} · ${shipment.status}")
                        Text("${shipment.receivedUnits}/${shipment.expectedUnits} received · ${shipment.damagedUnits} damaged")
                    }
                }
            }
        } else {
            ElevatedCard(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                    Text(selected.label, fontWeight = FontWeight.Bold)
                    Text("${selected.storageDomain} · ${selected.status}")
                    Text("${selected.receivedUnits}/${selected.expectedUnits} good · ${selected.damagedUnits} damaged · ${selected.missingUnits} missing")
                    if (selected.stowOverdue) Text("Stow SLA overdue", color = MaterialTheme.colorScheme.error)
                }
            }
            if (selected.status == "RECEIVING") {
                vm.receiveProduct?.let { product ->
                    Text(product.title, fontWeight = FontWeight.Bold)
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(
                            value = vm.receiveGoodQtyInput,
                            onValueChange = { vm.receiveGoodQtyInput = it.filter(Char::isDigit).take(5) },
                            label = { Text("Good") },
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                            modifier = Modifier.weight(1f),
                        )
                        OutlinedTextField(
                            value = vm.receiveDamagedQtyInput,
                            onValueChange = { vm.receiveDamagedQtyInput = it.filter(Char::isDigit).take(5) },
                            label = { Text("Damaged") },
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                            modifier = Modifier.weight(1f),
                        )
                    }
                    OutlinedTextField(
                        value = vm.receiveLotInput,
                        onValueChange = { vm.receiveLotInput = it },
                        label = { Text("Lot code (optional)") },
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = vm.receiveExpiryInput,
                        onValueChange = { vm.receiveExpiryInput = it },
                        label = { Text("Expiry YYYY-MM-DD (optional)") },
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Button(onClick = vm::submitReceiveLine, modifier = Modifier.fillMaxWidth()) {
                        Icon(Icons.Filled.Save, contentDescription = null)
                        Spacer(Modifier.width(8.dp))
                        Text("Record")
                    }
                }
                ScanEntry(vm, "Scan product barcode.")
                Button(onClick = vm::completeSelectedReceiving, enabled = !vm.busy, modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.Filled.DoneAll, contentDescription = null)
                    Spacer(Modifier.width(8.dp))
                    Text("Finish receive")
                }
            }
            if (selected.status == "STOWING" || selected.stowTasks.isNotEmpty()) {
                Text("Stow tasks", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                selected.stowTasks.filter { it.status != "COMPLETED" }.forEach { task ->
                    val selectedTask = vm.selectedStowTaskId == task.id
                    ElevatedCard(
                        onClick = { vm.selectStowTask(task.id) },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text("${task.productId.take(12)} · ${task.qty} units", fontWeight = FontWeight.Bold)
                            val line = selected.lines.firstOrNull { it.productId == task.productId }
                            if (line?.recommendedStow?.isNotEmpty() == true) {
                                Text("Recommended: ${line.recommendedStow.take(3).joinToString()}", style = MaterialTheme.typography.bodySmall)
                            }
                            Text(
                                if (selectedTask) "Selected • scan destination below" else "Tap to select this stow task",
                                style = MaterialTheme.typography.bodySmall,
                            )
                        }
                    }
                }

                vm.selectedStowTaskId?.let {
                    OutlinedTextField(
                        value = vm.stowDestinationInput,
                        onValueChange = { vm.stowDestinationInput = it.uppercase() },
                        label = { Text("Destination bin") },
                        modifier = Modifier.fillMaxWidth(),
                    )
                    ScanEntry(vm, "Scan the destination bin for the selected stow task.")
                    Button(
                        onClick = vm::confirmSelectedStow,
                        enabled = vm.stowDestinationInput.isNotBlank() && !vm.busy,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Icon(Icons.Filled.CheckCircle, contentDescription = null)
                        Spacer(Modifier.width(8.dp))
                        Text("Confirm")
                    }
                }
            }
            OutlinedButton(onClick = vm::clearSelectedShipment, modifier = Modifier.fillMaxWidth()) {
                Icon(Icons.Filled.ArrowBack, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text("Shipments")
            }
        }
    }
}

@Composable
fun ReplenishmentScreen(vm: AppViewModel) {
    OperationPage("Replenishment", "Move reserve stock into pick faces with scan validation.", vm) {
        val active = vm.activeReplenishment
        if (active == null) {
            Button(onClick = vm::loadReplenishmentQueue, enabled = !vm.busy, modifier = Modifier.fillMaxWidth()) {
                Icon(Icons.Filled.Refresh, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text("Refresh")
            }
            vm.replenishmentTasks.forEach { task ->
                ElevatedCard(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(7.dp)) {
                        Text(task.title, fontWeight = FontWeight.Bold)
                        Text("${task.qty} units · priority ${task.priority}")
                        Text("${task.sourceLocationId} → ${task.destinationLocationId}")
                        Text("${task.status} · source available ${task.sourceAvailableQty}")
                        Button(
                            onClick = { vm.claimReplenishment(task) },
                            enabled = task.status in setOf("READY", "ASSIGNED") && !vm.busy,
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Icon(Icons.Filled.PlayArrow, contentDescription = null)
                            Spacer(Modifier.width(8.dp))
                            Text("Claim")
                        }
                    }
                }
            }
        } else {
            val hint = when (vm.replenishmentPhase) {
                ReplenishmentScanPhase.SOURCE -> "Scan source ${active.sourceLocationId}"
                ReplenishmentScanPhase.ITEM -> "Scan ${active.title} barcode"
                ReplenishmentScanPhase.DESTINATION -> "Scan destination ${active.destinationLocationId}"
                ReplenishmentScanPhase.COMPLETE -> "Confirm actual moved quantity"
            }
            ElevatedCard(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                    Text(active.title, fontWeight = FontWeight.Bold)
                    Text("${active.sourceLocationId} → ${active.destinationLocationId}")
                    Text("Planned ${active.qty} · status ${active.status}")
                    Text(hint, fontWeight = FontWeight.SemiBold)
                }
            }
            if (vm.replenishmentPhase != ReplenishmentScanPhase.COMPLETE) {
                ScanEntry(vm, hint, enabled = !vm.busy)
            } else {
                OutlinedTextField(
                    value = vm.replenishmentQtyInput,
                    onValueChange = { vm.replenishmentQtyInput = it.filter(Char::isDigit).take(6) },
                    label = { Text("Actual moved quantity") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    modifier = Modifier.fillMaxWidth(),
                )
                Button(onClick = vm::completeActiveReplenishment, enabled = !vm.busy, modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.Filled.DoneAll, contentDescription = null)
                    Spacer(Modifier.width(8.dp))
                    Text("Commit")
                }
            }
        }
    }
}
