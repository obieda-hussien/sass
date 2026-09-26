package com.obieda.fulfillos

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.obieda.fulfillos.domain.ConnectivityState
import com.obieda.fulfillos.ui.AppViewModel

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val graph = (application as FulfillApplication).graph
        setContent {
            val vm: AppViewModel = viewModel { AppViewModel(graph) }
            MaterialTheme { FulfillHome(vm) }
        }
    }
}

@Composable
private fun FulfillHome(vm: AppViewModel) {
    Scaffold(
        topBar = {
            Surface(tonalElevation = 3.dp) {
                Row(
                    Modifier.fillMaxWidth().padding(18.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column {
                        Text("FulfillOS", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                        Text("PDA reliability client", style = MaterialTheme.typography.labelMedium)
                    }
                    AssistChip(onClick = {}, label = { Text(vm.connectivity.name) })
                }
            }
        }
    ) { padding ->
        Column(
            Modifier.padding(padding).padding(18.dp).fillMaxSize(),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            ReliabilityBanner(vm.connectivity, vm.message)
            Text("Waiting for Orders", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
            Text("The active task is server-owned. Pending scans survive app or device restarts and are replayed idempotently.")

            ElevatedCard(Modifier.fillMaxWidth(), shape = RoundedCornerShape(18.dp)) {
                Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Scanner input", fontWeight = FontWeight.SemiBold)
                    Text(vm.scannedValue.ifBlank { "No scan received yet" })
                    LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
                }
            }

            Button(onClick = vm::simulateReliablePick, modifier = Modifier.fillMaxWidth()) {
                Text("Create durable pick event (demo)")
            }

            HorizontalDivider()
            Text("Planned modules", fontWeight = FontWeight.Bold)
            Text("Inventory Viewer • Receive • Unpack • BOH Move • Pick • Stage • Cycle Count • DMG • Metrics")
        }
    }
}

@Composable
private fun ReliabilityBanner(connectivity: ConnectivityState, message: String) {
    val title = when (connectivity) {
        ConnectivityState.ONLINE -> "Online • server confirmation enabled"
        ConnectivityState.OFFLINE -> "Offline • scans will queue safely"
        ConnectivityState.RECONNECTING -> "Reconnecting • preserving task state"
    }
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(title, fontWeight = FontWeight.Bold)
            Text(message, style = MaterialTheme.typography.bodySmall)
        }
    }
}
