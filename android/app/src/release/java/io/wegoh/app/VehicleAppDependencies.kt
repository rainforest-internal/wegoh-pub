package io.wegoh.app

import android.content.Context
import android.content.Intent
import io.wegoh.app.nativeauth.VehicleConnection

internal object VehicleAppDependencies {
    fun configure(context: Context, intent: Intent) = Unit
    fun controller(app: WegoApplication) = WegoController(app)
    fun connection(context: Context) = VehicleConnection(context)
    fun privateStoreAlias(context: Context) = "wegoh.private.v1"
    fun checkForUpdates()=true
    fun preferenceName(name: String) = name
}
