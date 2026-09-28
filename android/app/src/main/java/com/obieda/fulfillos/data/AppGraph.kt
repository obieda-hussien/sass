package com.obieda.fulfillos.data

import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.provider.Settings
import com.obieda.fulfillos.BuildConfig

class AppGraph(context: Context) {
    private val appContext = context.applicationContext
    val events = PendingEventStore(appContext)
    val operationEvents = PendingOperationStore(appContext)
    val secureSession = SecureSessionStore(appContext)
    val api = ApiClient()
    val connectivity = ConnectivityMonitor(appContext)

    val deviceId: String = run {
        val androidId = Settings.Secure.getString(context.contentResolver, Settings.Secure.ANDROID_ID)
            .orEmpty()
            .uppercase()
        "PDA-${androidId.takeLast(12).ifBlank { "UNKNOWN" }}"
    }

    val sessions = SessionManager(
        api = api,
        secureStore = secureSession,
        deviceId = deviceId,
        appVersion = BuildConfig.VERSION_NAME,
    )

    val picks = PickRepository(events, api, connectivity, sessions)
    val operations = OperationsRepository(operationEvents, api, connectivity, sessions)

    fun batteryPercent(): Int? {
        val intent = appContext.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED)) ?: return null
        val level = intent.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
        val scale = intent.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
        if (level < 0 || scale <= 0) return null
        return ((level * 100f) / scale).toInt().coerceIn(0, 100)
    }
}
