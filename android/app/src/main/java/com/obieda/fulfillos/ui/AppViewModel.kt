package com.obieda.fulfillos.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import com.obieda.fulfillos.data.AppGraph
import com.obieda.fulfillos.data.ScanBus
import com.obieda.fulfillos.domain.ConnectivityState

class AppViewModel(private val graph: AppGraph) : ViewModel() {
    var connectivity by mutableStateOf(graph.connectivity.state)
        private set
    var message by mutableStateOf("Ready")
        private set
    var scannedValue by mutableStateOf("")
        private set

    private val scannerListener: (String) -> Unit = { value ->
        scannedValue = value
        message = "Scanned ${value.take(24)}"
    }

    init {
        graph.connectivity.observe { state ->
            connectivity = state
            if (state == ConnectivityState.ONLINE) graph.picks.flush { message = it }
        }
        ScanBus.subscribe(scannerListener)
    }

    fun simulateReliablePick() {
        graph.picks.createPick(
            taskId = "demo-task",
            taskItemId = "demo-item",
            locationId = "P-1-A101A110",
            productId = "demo-product",
            qty = 1,
            barcode = scannedValue.ifBlank { null },
        ) { message = it }
    }

    override fun onCleared() {
        ScanBus.unsubscribe(scannerListener)
    }
}
