package com.obieda.fulfillos

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                PdaHome()
            }
        }
    }
}

private val Background = Color(0xFF090B12)
private val Panel = Color(0xFF171C29)
private val Accent = Color(0xFF8E8DE5)
private val Muted = Color(0xFF929CAF)

@Composable
fun PdaHome() {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Background)
            .padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = "FULFILLOS PDA",
                    color = Accent,
                    fontSize = 11.sp,
                    fontWeight = FontWeight.Bold,
                )
                Text(
                    text = "Waiting for orders",
                    color = Color.White,
                    fontSize = 28.sp,
                    fontWeight = FontWeight.Bold,
                )
            }
            Box(
                modifier = Modifier
                    .background(Color(0x223FD89B), RoundedCornerShape(999.dp))
                    .padding(horizontal = 10.dp, vertical = 6.dp),
            ) {
                Text("ONLINE", color = Color(0xFF78DFB0), fontSize = 11.sp)
            }
        }

        Text(
            "Final progress is server-confirmed. Pending scans remain durable through app and PDA restarts.",
            color = Muted,
            lineHeight = 21.sp,
        )

        Spacer(Modifier.height(6.dp))

        PdaAction("Pick", "Order offer · bin scan · item scan · recovery")
        PdaAction("Inventory Viewer", "Scan a location or barcode")
        PdaAction("Unpack", "Ambient · chilled · frozen temporary totes")
        PdaAction("BOH Move", "Transactional source → destination move")
        PdaAction("Damage", "Move opened/broken/spoiled units to DMG")
        PdaAction("Cycle Count", "Count and reconcile with an audit movement")
    }
}

@Composable
private fun PdaAction(title: String, subtitle: String) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = Panel),
        shape = RoundedCornerShape(16.dp),
    ) {
        Row(
            modifier = Modifier.padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(title, color = Color.White, fontWeight = FontWeight.SemiBold)
                Text(subtitle, color = Muted, fontSize = 12.sp)
            }
            Button(onClick = {}) {
                Text("Open")
            }
        }
    }
}
