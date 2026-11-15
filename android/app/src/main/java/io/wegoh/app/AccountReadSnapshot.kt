package io.wegoh.app

import android.os.Handler
import android.os.Looper
import io.wegoh.app.nativeauth.VehicleConnection

internal class AccountReadSnapshot(private val connection: VehicleConnection,private val scope: VehicleConnection.Scope?=null,
    private val expired: ()->Unit) {
    private val main=Handler(Looper.getMainLooper())
    private var value: VehicleConnection.DataBoundary?=null
    private var expiry: Runnable?=null
    fun remember(boundary: VehicleConnection.DataBoundary) {
        forget();value=boundary
        expiry=Runnable {forget();expired()}.also {main.postDelayed(it,(boundary.expiresAtMillis-System.currentTimeMillis()).coerceAtLeast(1))}
    }
    fun invalidated()=value!=null && !canRetain()
    fun storageKey()=value?.takeIf {canRetain()}?.storageKey
    fun canRetain(): Boolean {
        val saved=value ?: return false
        val progress=connection.readDisplayAuthority()
        return saved.revision==connection.dataEpoch() && System.currentTimeMillis()<saved.expiresAtMillis &&
            !progress.canRegisterAgain && progress.stage in setOf(VehicleConnection.Stage.CONNECTED,VehicleConnection.Stage.CHECKING,
                VehicleConnection.Stage.UNAVAILABLE,VehicleConnection.Stage.RECOVERY_REQUIRED) &&
            (scope==null || scope in saved.scopes && scope !in progress.deniedOptionalScopes &&
                (progress.stage!=VehicleConnection.Stage.CONNECTED || scope in progress.approvedOptionalScopes)) &&
            connection.verifiedDataBoundary()?.let {it.storageKey==saved.storageKey}!=false
    }
    fun forget() {expiry?.let {main.removeCallbacks(it)};expiry=null;value=null}
}
