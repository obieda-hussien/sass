package com.obieda.fulfillos.data

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import com.obieda.fulfillos.domain.ConnectivityState
import java.util.concurrent.CopyOnWriteArrayList

class ConnectivityMonitor(context: Context) {
    private val cm = context.getSystemService(ConnectivityManager::class.java)
    private val listeners = CopyOnWriteArrayList<(ConnectivityState) -> Unit>()
    @Volatile var state: ConnectivityState = ConnectivityState.OFFLINE
        private set

    init {
        cm.registerDefaultNetworkCallback(object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) = update(ConnectivityState.RECONNECTING)
            override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) {
                val internet = caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
                update(if (internet) ConnectivityState.ONLINE else ConnectivityState.RECONNECTING)
            }
            override fun onLost(network: Network) = update(ConnectivityState.OFFLINE)
        })
    }

    fun observe(listener: (ConnectivityState) -> Unit) {
        listeners += listener
        listener(state)
    }

    private fun update(newState: ConnectivityState) {
        if (newState == state) return
        state = newState
        listeners.forEach { it(newState) }
    }
}
