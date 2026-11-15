package io.wegoh.app

enum class VehicleSampleQuality { AVAILABLE, UNSUPPORTED, DENIED, UNAVAILABLE, STALE }
data class VehicleTelemetrySample(
    val signal: VehicleTelemetrySignal, val value: VehicleTelemetryValue?,
    val quality: VehicleSampleQuality, val receivedAtElapsedMillis: Long,
    val failure: VehicleFailure? = null,
    /** SDK getter callbacks do not provide a capture timestamp; never substitute receipt time. */
    val capturedAtMillis: Long? = null,
    val source: String = "pleos-vehicle-getter"
) {
    fun at(nowElapsedMillis: Long,maximumAgeMillis: Long): VehicleTelemetrySample {
        if (quality != VehicleSampleQuality.AVAILABLE) return this
        return if (maximumAgeMillis < 0 || nowElapsedMillis < receivedAtElapsedMillis ||
            nowElapsedMillis-receivedAtElapsedMillis > maximumAgeMillis)
            copy(value=null,quality=VehicleSampleQuality.STALE) else this
    }
}
data class VehicleTelemetrySnapshot(val samples: Map<VehicleTelemetrySignal,VehicleTelemetrySample>) {
    /** No measured speed, acceleration, collection consent or validated formula is supplied here. */
    val safetyScore: Double? get() = null
    val safetyStatus: String get() = "unavailable"
    fun at(nowElapsedMillis: Long,maximumAgeMillis: Long)=VehicleTelemetrySnapshot(
        samples.mapValues { (_,sample) -> sample.at(nowElapsedMillis,maximumAgeMillis) })
}
data class VehicleTelemetryReadScope(
    val ownerId: String, val deviceId: String, val purposeId: String,
    val authorizationEpoch: Long, val expiresAtElapsedMillis: Long
) {
    fun validAt(now: Long)=ownerId.isNotBlank() && deviceId.isNotBlank() && purposeId.isNotBlank() &&
        authorizationEpoch >= 0 && now >= 0 && now < expiresAtElapsedMillis
}
data class VehicleTelemetryReadAuthority(
    val scope: VehicleTelemetryReadScope?, val foreground: Boolean, val suspended: Boolean
)

/** One-shot local observations only; contains no upload, background collector or sensor inference. */
class VehicleTelemetryReader(
    private val port: VehicleHardwarePort, private val lane: VehicleOperationLane,
    private val authority: ()->VehicleTelemetryReadAuthority, private val timeoutMillis: Long=5_000
): AutoCloseable {
    private enum class Phase { CAPABILITY, READING, DONE }
    private class Pending(
        val scope: VehicleTelemetryReadScope, val callback: (VehicleTelemetrySnapshot)->Unit
    ) {
        val phases=VehicleTelemetrySignal.entries.associateWith { Phase.CAPABILITY }.toMutableMap()
        val samples=mutableMapOf<VehicleTelemetrySignal,VehicleTelemetrySample>()
        var timeout: VehicleCancellation?=null
        var deadline: Long=0
    }
    private var pending: Pending?=null
    private var closed=false
    fun read(scope: VehicleTelemetryReadScope,callback: (VehicleTelemetrySnapshot)->Unit)=lane.dispatch {
        if (closed || pending!=null || timeoutMillis<=0 || !permitted(scope)) {
            callback(unavailable(if(closed) VehicleFailure.DISCONNECTED else if(pending!=null) VehicleFailure.BUSY else VehicleFailure.EXPIRED_AUTHORITY))
            return@dispatch
        }
        val item=Pending(scope,callback)
        pending=item
        item.deadline=lane.nowElapsedMillis()+minOf(timeoutMillis,scope.expiresAtElapsedMillis-lane.nowElapsedMillis())
        item.timeout=lane.schedule(minOf(timeoutMillis,scope.expiresAtElapsedMillis-lane.nowElapsedMillis()).coerceAtLeast(1)) {
            lane.dispatch {
                if (pending===item) {
                    if (!permitted(scope)) invalidate(item,VehicleFailure.EXPIRED_AUTHORITY)
                    else {
                        VehicleTelemetrySignal.entries.filter { it !in item.samples }.forEach {
                            receive(item,it,null,VehicleFailure.TIMEOUT)
                        }
                    }
                }
            }
        }
        VehicleTelemetrySignal.entries.forEach { signal ->
            if (pending!==item) return@forEach
            invoke(item,signal) {
                port.telemetryCapability(signal) { result -> lane.dispatch {
                    if (!current(item,signal,Phase.CAPABILITY)) return@dispatch
                    if (!permitted(scope)) { invalidate(item,VehicleFailure.EXPIRED_AUTHORITY); return@dispatch }
                    when(result) {
                        is VehicleReply.Failed -> receive(item,signal,null,result.reason)
                        is VehicleReply.Value -> {
                            if (result.value !in setOf(VehicleAccess.READ,VehicleAccess.READ_WRITE))
                                receive(item,signal,null,VehicleFailure.UNSUPPORTED_PROPERTY)
                            else {
                                item.phases[signal]=Phase.READING
                                invoke(item,signal) { port.readTelemetry(signal) { observation -> lane.dispatch {
                                    if (!current(item,signal,Phase.READING)) return@dispatch
                                    if (!permitted(scope)) { invalidate(item,VehicleFailure.EXPIRED_AUTHORITY); return@dispatch }
                                    when(observation) {
                                        is VehicleReply.Failed -> receive(item,signal,null,observation.reason)
                                        is VehicleReply.Value -> {
                                            val value=observation.value
                                            receive(item,signal,value,if(valid(signal,value))null else
                                                if(value==null)VehicleFailure.EMPTY_RESULT else VehicleFailure.INVALID_VALUE)
                                        }
                                    }
                                } } }
                            }
                        }
                    }
                } }
            }
        }
    }
    fun authorityChanged()=lane.dispatch {
        pending?.let { if(!permitted(it.scope))invalidate(it,VehicleFailure.EXPIRED_AUTHORITY) }
    }
    override fun close()=lane.dispatch {
        closed=true
        pending?.let { invalidate(it,VehicleFailure.CANCELLED) }
    }
    private fun permitted(scope: VehicleTelemetryReadScope)=try {
        val current=authority()
        current.scope==scope && current.foreground && !current.suspended && scope.validAt(lane.nowElapsedMillis())
    } catch(_: Exception) { false }
    private fun current(item: Pending,signal: VehicleTelemetrySignal,phase: Phase): Boolean {
        if (closed || pending!==item || item.phases[signal]!=phase) return false
        if (lane.nowElapsedMillis() >= item.deadline) {
            if (!permitted(item.scope)) invalidate(item,VehicleFailure.EXPIRED_AUTHORITY)
            else VehicleTelemetrySignal.entries.filter { it !in item.samples }.forEach {
                receive(item,it,null,VehicleFailure.TIMEOUT)
            }
            return false
        }
        return true
    }
    private fun invoke(item: Pending,signal: VehicleTelemetrySignal,block: ()->Unit) {
        try { block() } catch(_: SecurityException) { receive(item,signal,null,VehicleFailure.PERMISSION) }
        catch(_: Exception) { receive(item,signal,null,VehicleFailure.INTERNAL) }
    }
    private fun valid(signal: VehicleTelemetrySignal,value: VehicleTelemetryValue?)=when(signal) {
        VehicleTelemetrySignal.BRAKE_PRESSED -> value is VehicleTelemetryValue.Brake
        VehicleTelemetrySignal.FUEL_PERCENT -> value is VehicleTelemetryValue.Fuel && value.percent in 0..100
        VehicleTelemetrySignal.ODOMETER_KM -> value is VehicleTelemetryValue.Odometer &&
            value.kilometers.isFinite() && value.kilometers>=0
    }
    private fun receive(item: Pending,signal: VehicleTelemetrySignal,value: VehicleTelemetryValue?,failure: VehicleFailure?) {
        if (pending!==item || item.phases[signal]==Phase.DONE) return
        item.phases[signal]=Phase.DONE
        item.samples[signal]=sample(signal,if(failure==null)value else null,failure)
        if (item.samples.size==VehicleTelemetrySignal.entries.size) {
            item.timeout?.cancel()
            pending=null
            item.callback(VehicleTelemetrySnapshot(item.samples.toMap()))
        }
    }
    private fun invalidate(item: Pending,reason: VehicleFailure) {
        if (pending!==item)return
        item.timeout?.cancel()
        pending=null
        item.callback(unavailable(reason))
    }
    private fun unavailable(reason: VehicleFailure)=VehicleTelemetrySnapshot(
        VehicleTelemetrySignal.entries.associateWith { sample(it,null,reason) })
    private fun sample(signal: VehicleTelemetrySignal,value: VehicleTelemetryValue?,failure: VehicleFailure?)=
        VehicleTelemetrySample(signal,value,when(failure) {
            null -> VehicleSampleQuality.AVAILABLE
            VehicleFailure.PERMISSION,VehicleFailure.EXPIRED_AUTHORITY,VehicleFailure.DRIVING_RESTRICTED -> VehicleSampleQuality.DENIED
            VehicleFailure.UNSUPPORTED_PROPERTY,VehicleFailure.UNSUPPORTED_AREA -> VehicleSampleQuality.UNSUPPORTED
            else -> VehicleSampleQuality.UNAVAILABLE
        },lane.nowElapsedMillis(),failure)
}
