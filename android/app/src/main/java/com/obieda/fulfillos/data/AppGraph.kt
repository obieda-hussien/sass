package com.obieda.fulfillos.data

import android.content.Context
import android.provider.Settings
import com.obieda.fulfillos.BuildConfig

class AppGraph(context: Context) {
    val events = PendingEventStore(context)
    val secureSession = SecureSessionStore(context)
    val api = ApiClient()
    val connectivity = ConnectivityMonitor(context)

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
}
