package io.wegoh.app

import io.wegoh.app.nativeauth.VehicleConnection
import io.wegoh.app.nativeauth.VehicleEvent
import io.wegoh.app.nativeauth.VehicleEventsListener
import java.io.Closeable
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import io.wegoh.app.nativeauth.ProfileApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

enum class AccountReadStatus { CONNECTION_REQUIRED, PERMISSION_REQUIRED, LOADING, READY, UNAVAILABLE }
internal enum class ProfileNotice { SAVED, VEHICLE_SAVED, CONFIRM_REQUIRED }
internal data class ProfileDataState(val status: AccountReadStatus=AccountReadStatus.CONNECTION_REQUIRED,val name: String?=null,
    val canEdit: Boolean=false,val saving: Boolean=false,val notice: ProfileNotice?=null,val needsReload: Boolean=false,val isCurrent: Boolean=true,
    val vehicle: io.wegoh.app.nativeauth.VehicleProfile?=null,val vehicleUnavailable: Boolean=false,val vehicleLoading: Boolean=false)

internal class ProfileRepository(private val connection: VehicleConnection,private val events: AccountEvents,
    private val api: ProfileApi=connection.profileApi): Closeable {
    private val scope=CoroutineScope(SupervisorJob()+Dispatchers.Main.immediate)
    private var foreground=false
    private var setupAllowed=false
    private var activated=false
    private var deferredProfileRefresh=false
    private var attempted=false
    private var closed=false
    private var generation=0L
    private var boundary: VehicleConnection.DataBoundary?=null
    private var revision=-1L
    private var subscription: Closeable?=null
    private val mutableState=MutableStateFlow(ProfileDataState())
    val states: StateFlow<ProfileDataState> = mutableState.asStateFlow()
    val state get()=states.value
    private val snapshot=AccountReadSnapshot(connection,null) {clear(AccountReadStatus.CONNECTION_REQUIRED)}
    private val observer=connection.observe {progress ->
        if(!closed && foreground && activated) {
            if(snapshot.invalidated()) {
                val authority=connection.readDisplayAuthority()
                attempted=false
                clear(AccountReadStatus.CONNECTION_REQUIRED)
                if(authority.stage!=VehicleConnection.Stage.CONNECTED)return@observe
            }
            if(boundary?.revision?.let {it!=connection.dataEpoch()}==true) {attempted=false;clear(AccountReadStatus.CONNECTION_REQUIRED)}
            if(boundary!=null && (revision!=connection.dataStreamRevision() ||
                progress.stage==VehicleConnection.Stage.CONNECTED && boundary!=connection.verifiedDataBoundary())) {
                attempted=true;clear(AccountReadStatus.UNAVAILABLE);return@observe
            }
            when(progress.stage) {
                VehicleConnection.Stage.CONNECTED -> if(setupAllowed && !attempted)refresh()
                VehicleConnection.Stage.CHECKING -> Unit
                VehicleConnection.Stage.UNAVAILABLE,VehicleConnection.Stage.RECOVERY_REQUIRED -> clear(AccountReadStatus.UNAVAILABLE)
                else -> {attempted=false;clear(AccountReadStatus.CONNECTION_REQUIRED)}
            }
        }
    }
    private fun publish(value: ProfileDataState) {mutableState.value=value}
    private fun clear(status: AccountReadStatus) {
        deferredProfileRefresh=false
        val retain=!closed && state.status==AccountReadStatus.READY && snapshot.canRetain() &&
            status in setOf(AccountReadStatus.LOADING,AccountReadStatus.UNAVAILABLE)
        generation++;boundary=null;revision=-1;subscription?.close();subscription=null
        if(retain)publish(state.copy(canEdit=false,saving=false,needsReload=true,isCurrent=false)) else {snapshot.forget();publish(ProfileDataState(status))}
    }
    fun setForeground(value: Boolean) {
        if(closed || foreground==value)return
        foreground=value
        if(!value) {attempted=false;clear(AccountReadStatus.UNAVAILABLE)}
    }
    fun setSetupAllowed(value: Boolean) {setupAllowed=value}
    fun request(force: Boolean=false) {
        if(closed || !foreground || !setupAllowed)return
        if(!force && (state.status==AccountReadStatus.LOADING || state.status==AccountReadStatus.READY && state.isCurrent && !state.needsReload &&
            snapshot.canRetain() && boundary==connection.verifiedDataBoundary() && revision==connection.dataStreamRevision()))return
        activated=true;attempted=false
        if(connection.status().stage==VehicleConnection.Stage.CONNECTED)refresh() else if(force)connection.ensureConnected()
    }
    fun saveName(name: String) {
        if(closed || !foreground || !setupAllowed || !state.isCurrent || state.saving || state.needsReload || !state.canEdit || state.status!=AccountReadStatus.READY || !VehicleConnection.validAccountName(name))return
        val old=state.name ?: return
        if(name==old)return
        val expected=generation
        publish(state.copy(saving=true,notice=null))
        scope.launch {
            val result=apiResult {api.saveDisplayName(name,old)}
            if(!current(expected))return@launch
            if(!setupAllowed) {publish(state.copy(saving=false,needsReload=true,notice=ProfileNotice.CONFIRM_REQUIRED));return@launch}
            result.fold(onSuccess={
                val refreshNeeded=deferredProfileRefresh;deferredProfileRefresh=false
                publish(state.copy(name=it,saving=false,notice=ProfileNotice.SAVED))
                if(refreshNeeded)refresh()
            },
                onFailure={publish(state.copy(saving=false,needsReload=true,notice=ProfileNotice.CONFIRM_REQUIRED))})
        }
    }
    fun saveVehicle(plate: String) {
        val vehicle=state.vehicle ?: return
        if(closed || !foreground || !setupAllowed || !state.isCurrent || state.saving || state.needsReload || !state.canEdit ||
            state.status!=AccountReadStatus.READY || state.vehicleLoading || state.vehicleUnavailable || !io.wegoh.app.nativeauth.VehicleProfile.validPlate(plate) || plate==vehicle.plateNumber)return
        val expected=generation
        publish(state.copy(saving=true,notice=null))
        scope.launch {
            val result=apiResult {api.saveVehicleProfile(plate,vehicle.name,vehicle.revision)}
            if(!current(expected))return@launch
            if(!setupAllowed) {publish(state.copy(saving=false,needsReload=true,notice=ProfileNotice.CONFIRM_REQUIRED));return@launch}
            result.fold(onSuccess={
                val refreshNeeded=deferredProfileRefresh;deferredProfileRefresh=false
                publish(state.copy(vehicle=it,saving=false,notice=ProfileNotice.VEHICLE_SAVED))
                if(refreshNeeded)refresh()
            },onFailure={publish(state.copy(saving=false,needsReload=true,notice=ProfileNotice.CONFIRM_REQUIRED))})
        }
    }
    private fun current(expected: Long): Boolean {
        if(closed || !foreground || expected!=generation)return false
        if(boundary==null || boundary!=connection.verifiedDataBoundary() || revision!=connection.dataStreamRevision()) {
            attempted=true;clear(AccountReadStatus.UNAVAILABLE);return false
        }
        return true
    }
    private fun refresh() {
        if(closed || !foreground || !setupAllowed || connection.status().stage!=VehicleConnection.Stage.CONNECTED)return
        val verified=connection.verifiedDataBoundary() ?: return
        attempted=true;clear(AccountReadStatus.LOADING);boundary=verified;revision=connection.dataStreamRevision();val expected=generation
        val opened=events.subscribe(object: VehicleEventsListener {
            override fun onOpen() {
                if(!current(expected))return
                scope.launch {
            val result=apiResult {api.displayName()}
                    if(current(expected)) {
                        if(!setupAllowed) {attempted=false;clear(AccountReadStatus.UNAVAILABLE);return@launch}
                        result.fold(onSuccess={value ->snapshot.remember(checkNotNull(boundary));publish(ProfileDataState(AccountReadStatus.READY,value,connection.verifiedDataBoundary()!=null,notice=state.notice.takeIf {state.name==value},vehicle=state.vehicle,vehicleLoading=true))},onFailure={clear(AccountReadStatus.UNAVAILABLE)})
                        if(current(expected) && state.status==AccountReadStatus.READY) {
                            val vehicle=apiResult {api.vehicleProfile()}
                            if(current(expected))vehicle.fold(onSuccess={publish(state.copy(vehicle=it,vehicleUnavailable=false,vehicleLoading=false))},
                                onFailure={publish(state.copy(vehicleUnavailable=true,vehicleLoading=false))})
                        }
                    }
                }
            }
            override fun onEvent(event: VehicleEvent) {
                if(current(expected) && event.type=="invalidate" && event.resources.any {it in setOf("devices","profile")}) {
                    if(state.saving)deferredProfileRefresh=true
                    else {attempted=false;clear(AccountReadStatus.UNAVAILABLE);refresh()}
                }
            }
            override fun onUnavailable() {if(!closed && foreground && expected==generation)clear(AccountReadStatus.UNAVAILABLE)}
            override fun onClosed()=onUnavailable()
        })
        if(expected==generation)subscription=opened else opened.close()
    }
    override fun close() {if(!closed){closed=true;scope.cancel();clear(AccountReadStatus.CONNECTION_REQUIRED);observer.close()}}
}
