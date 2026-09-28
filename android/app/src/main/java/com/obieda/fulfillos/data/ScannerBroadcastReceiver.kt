package com.obieda.fulfillos.data

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter

/**
 * Foreground-only adapter for common industrial PDA scanner services.
 *
 * FulfillOS deliberately does not bind the workflow to one vendor. Site/device
 * profiles can emit the FulfillOS custom action, while known vendor actions and
 * payload keys are normalized into the same ScanBus.
 */
class ScannerBroadcastReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context?, intent: Intent?) {
        val value = ScannerIntentAdapter.extract(intent) ?: return
        ScanBus.publish(value)
    }
}

object ScannerIntentAdapter {
    const val FULFILLOS_ACTION = "com.obieda.fulfillos.SCAN"

    private val actions = listOf(
        FULFILLOS_ACTION,
        "com.symbol.datawedge.api.RESULT_ACTION",
        "com.honeywell.decode.intent.action.EDIT_DATA",
        "com.datalogic.decodewedge.decode_action",
    )

    private val stringKeys = listOf(
        "scan_data",
        "barcode",
        "data",
        "com.symbol.datawedge.data_string",
        "com.honeywell.decode.intent.extra.DATA",
        "com.datalogic.decode.intentwedge.barcode_string",
    )

    private val byteKeys = listOf(
        "decode_data",
        "com.honeywell.decode.intent.extra.DATA",
    )

    fun filter(): IntentFilter = IntentFilter().apply {
        actions.forEach(::addAction)
    }

    fun extract(intent: Intent?): String? {
        if (intent == null) return null
        for (key in stringKeys) {
            val value = intent.getStringExtra(key)?.trim()
            if (!value.isNullOrBlank()) return value
        }
        for (key in byteKeys) {
            val bytes = intent.getByteArrayExtra(key) ?: continue
            val value = bytes.toString(Charsets.UTF_8).trim().trimEnd('\u0000')
            if (value.isNotBlank()) return value
        }
        return null
    }
}

object ScanBus {
    private val listeners = mutableSetOf<(String) -> Unit>()

    @Synchronized
    fun subscribe(listener: (String) -> Unit) {
        listeners += listener
    }

    @Synchronized
    fun unsubscribe(listener: (String) -> Unit) {
        listeners -= listener
    }

    @Synchronized
    fun publish(value: String) {
        val normalized = value.trim()
        if (normalized.isBlank()) return
        listeners.toList().forEach { it(normalized) }
    }
}
