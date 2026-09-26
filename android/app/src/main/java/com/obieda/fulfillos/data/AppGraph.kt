package com.obieda.fulfillos.data

import android.content.Context

class AppGraph(context: Context) {
    val events = PendingEventStore(context)
    val session = SecureSessionStore(context)
    val api = ApiClient()
    val connectivity = ConnectivityMonitor(context)
    val picks = PickRepository(events, api, connectivity)
}
