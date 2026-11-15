package io.wegoh.app

import io.wegoh.app.nativeauth.WegoLog
import java.io.Closeable

internal interface VehicleControlSupportTransport: Closeable {
    fun open(onInvalidated: ()->Unit,callback: (Result<Unit>)->Unit)
    fun publish(actions: List<VehicleControlSupport>,callback: (Result<Unit>)->Unit): Closeable
}
internal class VehicleControlSupportReporter(
    private val portFactory: ()->VehicleHardwarePort,
    private val transportFactory: ()->VehicleControlSupportTransport,
    private val lane: VehicleOperationLane=AndroidVehicleOperationLane(),
    private val diagnostics: (String)->Unit={WegoLog.i("WegoClimate",it)}
): Closeable {
    private var active=false
    private var closed=false
    private var generation=0L
    private var hardware: VehicleHardwarePort?=null
    private var transport: VehicleControlSupportTransport?=null
    private var timeout: VehicleCancellation?=null
    private var heartbeat: VehicleCancellation?=null
    private var request: Closeable?=null

    fun setActive(value: Boolean)=lane.dispatch {
        if(closed || value==active)return@dispatch
        active=value;generation++;cancel()
        if(active)begin()
    }
    private fun current(token: Long)=active && !closed && generation==token
    private fun begin() {
        if(!active || closed)return
        val token=++generation
        val channel=runCatching {transportFactory()}.getOrElse {finish(token,false);return}
        transport=channel
        timeout=lane.schedule(15_000) {if(current(token))finish(token,false)}
        runCatching {channel.open({lane.dispatch {if(current(token))finish(token,false)}}) {opened->lane.dispatch {
            if(!current(token))return@dispatch
            timeout?.cancel();timeout=null
            if(opened.isFailure) {finish(token,false);return@dispatch}
            val port=runCatching {portFactory()}.getOrElse {finish(token,false);return@dispatch}
            hardware=port
            val initialized=runCatching {port.initialize()}.getOrNull()
            val remaining=TRUSTED_CLIMATE_ACTIONS.keys.toList()
            val actions=mutableListOf<VehicleControlSupport>()
            fun publish() {
                if(!current(token))return
                timeout=lane.schedule(15_000) {if(current(token))finish(token,false)}
                val handle=runCatching {channel.publish(actions.toList()) {result->lane.dispatch {
                    if(current(token))finish(token,result.isSuccess)
                }}}.getOrElse {finish(token,false);return}
                if(current(token))request=handle else handle.close()
            }
            fun next(index: Int) {
                if(!current(token))return
                if(index==remaining.size) {publish();return}
                val property=remaining[index]
                if(initialized !is VehicleReply.Value) {
                    actions+=vehicleControlSupport(property,VehicleReply.Failed(VehicleFailure.DISCONNECTED));next(index+1);return
                }
                var completed=false
                fun complete(reply: VehicleReply<ClimateCapability>) {
                    if(!current(token) || completed)return
                    completed=true;timeout?.cancel();timeout=null
                    actions+=vehicleControlSupport(property,reply);next(index+1)
                }
                timeout=lane.schedule(3_000) {complete(VehicleReply.Failed(VehicleFailure.TIMEOUT))}
                runCatching {port.climateCapability(property) {reply->lane.dispatch {complete(reply)}}}
                    .onFailure {complete(VehicleReply.Failed(VehicleFailure.UNDEFINED))}
            }
            next(0)
        }}}.onFailure {if(current(token))finish(token,false)}
    }
    private fun finish(token: Long,success: Boolean) {
        if(!current(token))return
        generation++;cancel()
        diagnostics("climate.support: ${if(success)"reported" else "failed"}")
        heartbeat=lane.schedule(30_000) {begin()}
    }
    private fun cancel() {
        heartbeat?.cancel();heartbeat=null;timeout?.cancel();timeout=null
        request?.close();request=null
        hardware?.close();hardware=null
        transport?.close();transport=null
    }
    override fun close()=lane.dispatch {
        if(closed)return@dispatch
        closed=true;active=false;generation++;cancel()
    }
}
