package com.obieda.fulfillos.data

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/**
 * Placeholder adapter for scanner-service broadcasts from industrial PDAs.
 * Configure the actual action/extras per device model through site policy rather than hard-coding a vendor.
 */
class ScannerBroadcastReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context?, intent: Intent?) {
        val payload = intent?.getStringExtra("scan_data") ?: return
        ScanBus.publish(payload)
    }
}

object ScanBus {
    private val listeners = mutableSetOf<(String) -> Unit>()
    @Synchronized fun subscribe(listener: (String) -> Unit) { listeners += listener }
    @Synchronized fun unsubscribe(listener: (String) -> Unit) { listeners -= listener }
    @Synchronized fun publish(value: String) { listeners.toList().forEach { it(value) } }
}
