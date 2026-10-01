package com.obieda.fulfillos

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.animateContentSize
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
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
    OperationPage(
        "Unpack",
        "Verify the return bag against its expected manifest before it can close.",
        vm,
    ) {
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
            ElevatedCard(
                Modifier.fillMaxWidth().animateContentSize(animationSpec = tween(160)),
                shape = RoundedCornerShape(20.dp),
            ) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                        Icon(
                            if (summary.manifestLocked) Icons.Filled.FactCheck else Icons.Filled.QrCodeScanner,
                            contentDescription = null,
                            modifier = Modifier.size(30.dp),
                        )
                        Spacer(Modifier.width(10.dp))
                        Column(Modifier.weight(1f)) {
                            Text(
                                if (summary.manifestLocked) "Manifest verification" else "Identify return bag",
                                fontWeight = FontWeight.Bold,
                            )
                            Text(
                                summary.sourceRef ?: summary.toteLocationId,
                                style = MaterialTheme.typography.bodySmall,
                            )
                        }
                        AssistChip(
                            onClick = {},
                            label = { Text(summary.temperatureClass) },
                        )
                    }

                    if (summary.manifestLocked) {
                        val progress = if (summary.expectedUnits <= 0) 0f
                        else summary.verifiedUnits.toFloat() / summary.expectedUnits.toFloat()
                        LinearProgressIndicator(
                            progress = { progress.coerceIn(0f, 1f) },
                            modifier = Modifier.fillMaxWidth(),
                        )
                        Row(Modifier.fillMaxWidth()) {
                            Text(
                                "${summary.verifiedUnits}/${summary.expectedUnits} verified",
                                modifier = Modifier.weight(1f),
                                fontWeight = FontWeight.Bold,
                            )
                            Text("${summary.remainingUnits} left")
                        }

                        summary.manifest.forEach { item ->
                            Row(
                                Modifier.fillMaxWidth(),
                                verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(10.dp),
                            ) {
                                Icon(
                                    if (item.missingQty == 0) Icons.Filled.CheckCircle else Icons.Filled.HourglassBottom,
                                    contentDescription = null,
                                    modifier = Modifier.size(22.dp),
                                )
                                Column(Modifier.weight(1f)) {
                                    Text(item.title, fontWeight = FontWeight.SemiBold)
                                    item.asin?.let { Text(it, style = MaterialTheme.typography.labelSmall) }
                                }
                                Text(
                                    "${item.verifiedQty}/${item.expectedQty}",
                                    fontWeight = FontWeight.Bold,
                                )
                            }
                        }
                    } else {
                        Text(
                            "Scan the bag/SPOO first. FulfillOS must know what should be inside before item scanning starts.",
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    }
                }
            }

            if (!summary.manifestLocked) {
                ScanEntry(vm, "Scan return bag / SPOO to load expected contents.")
            } else if (!summary.completeReady) {
                ScanEntry(vm, "Scan every physical item one by one. Missing or unexpected items cannot close the bag.")
            } else {
                ElevatedCard(Modifier.fillMaxWidth(), shape = RoundedCornerShape(18.dp)) {
                    Row(
                        Modifier.fillMaxWidth().padding(16.dp),
                        verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
                    ) {
                        Icon(Icons.Filled.CheckCircle, contentDescription = null, modifier = Modifier.size(32.dp))
                        Spacer(Modifier.width(12.dp))
                        Column(Modifier.weight(1f)) {
                            Text("Bag fully verified", fontWeight = FontWeight.Bold)
                            Text("Every expected unit was scanned.", style = MaterialTheme.typography.bodySmall)
                        }
                    }
                }
            }

            Button(
                onClick = vm::completeCurrentUnpack,
                enabled = summary.status == "OPEN" && summary.completeReady && !vm.busy,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Icon(Icons.Filled.DoneAll, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text(if (summary.completeReady) "Close verified bag" else "Finish locked")
            }
        }
    }
}

@Composable
fun BohMoveScreen(vm: AppViewModel) {
    val hint = when (vm.operationScanPhase) {
        OperationScanPhase.SOURCE -> "Scan source bin"
        OperationScanPhase.ITEM -> "Scan item barcode"
        OperationScanPhase.DESTINATION -> "Scan new bin"
        OperationScanPhase.SYNCING -> "Waiting for server"
    }
    val phaseIndex = when (vm.operationScanPhase) {
        OperationScanPhase.SOURCE -> 0
        OperationScanPhase.ITEM -> 1
        OperationScanPhase.DESTINATION -> 2
        OperationScanPhase.SYNCING -> 3
    }

    OperationPage("BOH Move", "Scan → review → ✓. Nothing advances until you confirm it.", vm) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            listOf(
                Triple("Bin", Icons.Filled.Inventory2, 0),
                Triple("Item", Icons.Filled.QrCodeScanner, 1),
                Triple("New bin", Icons.Filled.MoveToInbox, 2),
            ).forEach { (label, icon, index) ->
                Surface(
                    modifier = Modifier.weight(1f),
                    shape = RoundedCornerShape(14.dp),
                    tonalElevation = if (phaseIndex == index) 4.dp else 0.dp,
                ) {
                    Column(
                        Modifier.padding(vertical = 10.dp),
                        horizontalAlignment = androidx.compose.ui.Alignment.CenterHorizontally,
                    ) {
                        Icon(
                            if (phaseIndex > index) Icons.Filled.CheckCircle else icon,
                            contentDescription = label,
                            modifier = Modifier.size(22.dp),
                        )
                        Text(label, style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Bold)
                    }
                }
            }
        }

        AnimatedContent(
            targetState = vm.operationScanPhase to vm.operationAwaitingConfirmation,
            transitionSpec = {
                (fadeIn(tween(110)) + slideInHorizontally(tween(150)) { it / 10 }) togetherWith
                    (fadeOut(tween(80)) + slideOutHorizontally(tween(110)) { -it / 12 })
            },
            label = "boh-step",
        ) { (phase, awaiting) ->
            ElevatedCard(
                Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(20.dp),
            ) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                        Icon(
                            when (phase) {
                                OperationScanPhase.SOURCE -> Icons.Filled.Inventory2
                                OperationScanPhase.ITEM -> Icons.Filled.QrCodeScanner
                                OperationScanPhase.DESTINATION -> Icons.Filled.MoveToInbox
                                OperationScanPhase.SYNCING -> Icons.Filled.Sync
                            },
                            contentDescription = null,
                            modifier = Modifier.size(30.dp),
                        )
                        Spacer(Modifier.width(10.dp))
                        Column(Modifier.weight(1f)) {
                            Text(hint, fontWeight = FontWeight.Bold)
                            Text(
                                when (phase) {
                                    OperationScanPhase.SOURCE -> vm.operationSourceInput.ifBlank { "Waiting for source bin" }
                                    OperationScanPhase.ITEM -> vm.operationProduct?.title ?: "Waiting for item"
                                    OperationScanPhase.DESTINATION -> vm.operationDestinationInput.ifBlank { "Waiting for new bin" }
                                    OperationScanPhase.SYNCING -> "Inventory move is being confirmed"
                                },
                                style = MaterialTheme.typography.bodySmall,
                            )
                        }
                    }

                    if (awaiting) {
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            OutlinedButton(
                                onClick = vm::rescanBohStep,
                                enabled = !vm.busy,
                                modifier = Modifier.weight(1f),
                            ) {
                                Icon(Icons.Filled.Refresh, contentDescription = null)
                                Spacer(Modifier.width(6.dp))
                                Text("Rescan")
                            }
                            Button(
                                onClick = vm::confirmBohStep,
                                enabled = !vm.busy,
                                modifier = Modifier.weight(1f),
                            ) {
                                Icon(Icons.Filled.Check, contentDescription = null)
                                Spacer(Modifier.width(6.dp))
                                Text("Confirm")
                            }
                        }
                    }
                }
            }
        }

        OutlinedTextField(
            value = vm.operationQtyInput,
            onValueChange = { vm.operationQtyInput = it.filter(Char::isDigit).take(5) },
            label = { Text("Move quantity") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            modifier = Modifier.fillMaxWidth(),
            leadingIcon = { Icon(Icons.Filled.Numbers, contentDescription = null) },
        )

        if (!vm.operationAwaitingConfirmation && vm.operationScanPhase != OperationScanPhase.SYNCING) {
            ScanEntry(vm, hint)
        }
        if (vm.operationScanPhase == OperationScanPhase.SYNCING) {
            LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
        }
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
private fun ReceiveExpiryField(vm: AppViewModel) {
    val context = LocalContext.current
    OutlinedTextField(
        value = vm.receiveExpiryInput,
        onValueChange = { vm.receiveExpiryInput = it.take(10) },
        label = { Text("Expiry date (optional)") },
        placeholder = { Text("YYYY-MM-DD") },
        enabled = !vm.busy,
        modifier = Modifier.fillMaxWidth(),
        trailingIcon = {
            IconButton(onClick = {
                val date = runCatching { java.time.LocalDate.parse(vm.receiveExpiryInput) }.getOrDefault(java.time.LocalDate.now())
                android.app.DatePickerDialog(context, { _, year, month, day ->
                    vm.receiveExpiryInput = java.time.LocalDate.of(year, month + 1, day).toString()
                }, date.year, date.monthValue - 1, date.dayOfMonth).show()
            }, enabled = !vm.busy) { Icon(Icons.Filled.CalendarMonth, contentDescription = "Choose expiry date") }
        },
    )
}

@Composable
private fun ShipmentIssueDialog(vm: AppViewModel) {
    AlertDialog(
        onDismissRequest = { if (!vm.busy) vm.shipmentIssueVisible = false },
        title = { Text("Shipment issue") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(vm.receiveProduct?.title ?: "Scan the affected item first for item-specific issues. Temperature and Other can describe the whole shipment.")
                listOf(listOf("DAMAGED", "EXPIRED"), listOf("WRONG_ITEM", "MISSING"), listOf("TEMPERATURE", "PACKAGING"), listOf("OTHER")).forEach { row ->
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        row.forEach { kind -> FilterChip(selected = vm.shipmentIssueType == kind,
                            onClick = { vm.shipmentIssueType = kind }, enabled = !vm.busy,
                            label = { Text(kind.lowercase().replace('_', ' ')) }) }
                    }
                }
                OutlinedTextField(value = vm.shipmentIssueQty, onValueChange = { vm.shipmentIssueQty = it.filter(Char::isDigit).take(5) },
                    label = { Text("Affected quantity") }, enabled = !vm.busy,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), modifier = Modifier.fillMaxWidth())
                ReceiveExpiryField(vm)
                OutlinedTextField(value = vm.shipmentIssueNotes, onValueChange = { vm.shipmentIssueNotes = it.take(1000) },
                    label = { Text("Describe the problem") }, enabled = !vm.busy, modifier = Modifier.fillMaxWidth())
                Text("Damaged and expired reports record rejected incoming units in DMG. Other issues record an incident without changing inventory.", style = MaterialTheme.typography.bodySmall)
                vm.errorMessage?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            }
        },
        confirmButton = { TextButton(onClick = vm::submitShipmentIssue, enabled = !vm.busy) { Text("Report issue") } },
        dismissButton = { TextButton(onClick = { vm.shipmentIssueVisible = false }, enabled = !vm.busy) { Text("Cancel") } },
    )
}

@Composable
fun ReceiveScreen(vm: AppViewModel) {
    OperationPage("Receive & Stow", "Vendor / ambient / chilled / frozen / HAZ / HRV inbound execution.", vm) {
        val selected = vm.selectedShipment
        if (vm.shipmentIssueVisible) ShipmentIssueDialog(vm)
        if (selected == null) {
            ScanEntry(vm, "Scan the barcode at the top of the shipment sheet, or enter its code.", enabled = !vm.busy)
            Text("Any signed-in employee can identify and open a shipment.", style = MaterialTheme.typography.bodySmall)
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
                    selected.supplierName?.let { Text("Supplier: $it") }
                    selected.purchaseOrderRef?.let { Text("Purchase order: $it") }
                    Text("${selected.receivingUsers.size} employees receiving · ${selected.issues.count { it.status == "OPEN" }} open issues")
                    Text("${selected.storageDomain} · ${selected.status}")
                    Text("${selected.receivedUnits}/${selected.expectedUnits} good · ${selected.damagedUnits} damaged · ${selected.missingUnits} missing")
                    if (selected.stowOverdue) Text("Stow SLA overdue", color = MaterialTheme.colorScheme.error)
                }
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = { vm.shipmentIssueVisible = true }, enabled = !vm.busy && selected.status !in listOf("COMPLETED", "CANCELLED")) {
                    Icon(Icons.Filled.ReportProblem, contentDescription = null)
                    Spacer(Modifier.width(6.dp))
                    Text("Issues")
                }
                TextButton(onClick = vm::leaveSelectedReceiving, enabled = !vm.busy) { Text("Leave shipment") }
            }
            if (selected.status == "CREATED" || selected.status == "DOCKED" || (selected.status == "RECEIVING" && !vm.receivingJoined)) {
                Text("Shipment zone: ${selected.storageDomain}. Confirm the physical receiving zone.")
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    listOf("AMBIENT", "CHILLED", "FROZEN").forEach { zone ->
                        FilterChip(selected = vm.receiveZoneInput == zone,
                            onClick = { vm.receiveZoneInput = zone }, enabled = !vm.busy, label = { Text(zone) })
                    }
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    listOf("PRODUCE", "HAZ", "HRV").forEach { zone ->
                        FilterChip(selected = vm.receiveZoneInput == zone,
                            onClick = { vm.receiveZoneInput = zone }, enabled = !vm.busy, label = { Text(zone) })
                    }
                }
                OutlinedTextField(
                    value = vm.receiveTemperatureInput,
                            enabled = !vm.busy,
                    onValueChange = { vm.receiveTemperatureInput = it.filter { c -> c.isDigit() || c == '-' || c == '.' }.take(7) },
                    label = { Text("Current temperature °C") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                    modifier = Modifier.fillMaxWidth(),
                )
                Button(onClick = vm::openSelectedShipment, enabled = !vm.busy, modifier = Modifier.fillMaxWidth()) {
                    Text(if (selected.status == "RECEIVING") "Join receiving" else "Open shipment in ${vm.receiveZoneInput}")
                }
            }
            if (selected.status == "RECEIVING" && vm.receivingJoined) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    FilterChip(selected = !vm.receiveAdhocMode,
                        onClick = { vm.chooseReceiveAdhocMode(false) }, enabled = !vm.busy,
                        label = { Text("Receive then stow") })
                    FilterChip(selected = vm.receiveAdhocMode,
                        onClick = { vm.chooseReceiveAdhocMode(true) }, enabled = !vm.busy,
                        label = { Text("Direct stow") })
                }
                vm.receiveProduct?.let { product ->
                    Text(product.title, fontWeight = FontWeight.Bold)
                    val expectedLine = selected.lines.firstOrNull { it.productId == product.productId }
                    Text(if (expectedLine == null) "Unplanned item: enter a discrepancy reason below"
                         else "Expected ${expectedLine.expectedQty} · already received ${expectedLine.receivedQty} · scan quantity and record")
                    if (vm.receiveAdhocMode) {
                        OutlinedTextField(
                            value = vm.receiveAdhocDestination,
                            enabled = !vm.busy,
                            onValueChange = { vm.receiveAdhocDestination = it.uppercase() },
                            label = { Text("Scan destination bin") },
                            modifier = Modifier.fillMaxWidth(),
                        )
                        Button(onClick = vm::checkAdhocPlacement, enabled = !vm.busy, modifier = Modifier.fillMaxWidth()) {
                            Text("Check bin zone")
                        }
                        if (vm.receivePlacementHint.isNotBlank()) Text(vm.receivePlacementHint)
                        expectedLine?.recommendedStow?.take(3)?.let { bins ->
                            if (bins.isNotEmpty()) Text("Compatible suggestions: ${bins.joinToString()}")
                        }
                    }
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(
                            value = vm.receiveGoodQtyInput,
                            enabled = !vm.busy,
                            onValueChange = { vm.receiveGoodQtyInput = it.filter(Char::isDigit).take(5) },
                            label = { Text("Quantity") },
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                            modifier = Modifier.weight(1f),
                        )

                    }
                    OutlinedTextField(
                        value = vm.receiveLotInput,
                            enabled = !vm.busy,
                        onValueChange = { vm.receiveLotInput = it },
                        label = { Text("Lot code (optional)") },
                        modifier = Modifier.fillMaxWidth(),
                    )
                    ReceiveExpiryField(vm)
                    OutlinedTextField(
                        value = vm.receiveDiscrepancyInput,
                            enabled = !vm.busy,
                        onValueChange = { vm.receiveDiscrepancyInput = it.take(240) },
                        label = { Text("Reason for unexpected / excess item") },
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedButton(onClick = { vm.shipmentIssueVisible = true }, enabled = !vm.busy, modifier = Modifier.fillMaxWidth()) {
                        Icon(Icons.Filled.ReportProblem, contentDescription = null)
                        Spacer(Modifier.width(8.dp))
                        Text("Issues · damaged / expired / wrong item")
                    }
                    Button(onClick = if (vm.receiveAdhocMode) vm::submitAdhocStow else vm::submitReceiveLine,
                        enabled = !vm.busy,
                        modifier = Modifier.fillMaxWidth()) {
                        Icon(Icons.Filled.Save, contentDescription = null)
                        Spacer(Modifier.width(8.dp))
                        Text(if (vm.receiveAdhocMode) "Confirm stow" else "Record")
                    }
                }
                ScanEntry(vm, if (vm.receiveAdhocMode && vm.receiveProduct != null) "Scan destination bin."
                              else "Scan product barcode.")
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
                            Text("${selected.lines.firstOrNull { it.productId == task.productId }?.title ?: task.productId.take(12)} · ${task.qty} units", fontWeight = FontWeight.Bold)
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
            if (selected.lines.isNotEmpty()) {
                Text("Shipment items", style = MaterialTheme.typography.titleMedium)
                selected.lines.forEach { line ->
                    Text("${line.title} · ${line.receivedQty + line.damagedQty}/${line.expectedQty} accounted · ${line.damagedQty} rejected", style = MaterialTheme.typography.bodySmall)
                }
            }
            selected.issues.take(10).forEach { issue ->
                ElevatedCard(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(12.dp)) {
                        Text("${issue.issueType} · ${issue.qty} · ${issue.status}", fontWeight = FontWeight.Bold)
                        issue.title?.let { Text(it) }
                        Text(issue.notes)
                        Text("By ${issue.reportedBy}", style = MaterialTheme.typography.bodySmall)
                    }
                }
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
