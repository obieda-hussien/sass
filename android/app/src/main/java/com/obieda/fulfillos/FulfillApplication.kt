package com.obieda.fulfillos

import android.app.Application
import com.obieda.fulfillos.data.AppGraph

class FulfillApplication : Application() {
    lateinit var graph: AppGraph
        private set

    override fun onCreate() {
        super.onCreate()
        graph = AppGraph(this)
    }
}
