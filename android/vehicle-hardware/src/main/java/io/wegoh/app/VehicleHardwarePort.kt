package io.wegoh.app

/** Host-only typed boundary. No capability, SDK callback or normal permission grants user consent. */
enum class VehicleSeat {
    ROW_1_LEFT, ROW_1_CENTER, ROW_1_RIGHT,
    ROW_2_LEFT, ROW_2_CENTER, ROW_2_RIGHT,
    ROW_3_LEFT, ROW_3_CENTER, ROW_3_RIGHT
}
enum class VehicleAccess { NONE, READ, WRITE, READ_WRITE }
enum class VehicleFailure {
    PERMISSION, UNSUPPORTED_PROPERTY, UNSUPPORTED_AREA, INVALID_VALUE_TYPE,
    DRIVING_RESTRICTED, DISCONNECTED, EMPTY_RESULT, INTERNAL, UNDEFINED,
    INVALID_VALUE, EXPIRED_AUTHORITY, CANCELLED, BUSY, TIMEOUT, MISMATCH, DRIVER_SEAT_RESTRICTED
}
sealed interface VehicleReply<out T> {
    data class Value<T>(val value: T): VehicleReply<T>
    data class Failed(val reason: VehicleFailure): VehicleReply<Nothing>
}
enum class VehicleWindow {
    ROW_1_LEFT, ROW_1_RIGHT, ROW_2_LEFT, ROW_2_RIGHT
}
enum class VehicleLightSwitch { OFF, ON, DAYTIME_RUNNING, AUTOMATIC }
enum class ClimateProperty {
    TARGET_CELSIUS, FAN_LEVEL, GLOBAL_POWER, AC, AIR_CLEANER, SEAT_HEAT, SEAT_VENTILATION,
    WINDOW_POSITION, CABIN_LIGHT, READING_LIGHT, AMBIENT_LIGHT
}
sealed class ClimateTarget(val property: ClimateProperty) {
    abstract val value: Any
    sealed class Seated(val seat: VehicleSeat, property: ClimateProperty): ClimateTarget(property)
    sealed class Windowed(val window: VehicleWindow, property: ClimateProperty): ClimateTarget(property)
    class Celsius(seat: VehicleSeat, override val value: Float): Seated(seat, ClimateProperty.TARGET_CELSIUS)
    class Fan(seat: VehicleSeat, override val value: Int): Seated(seat, ClimateProperty.FAN_LEVEL)
    /** This is global HVAC power, even when the OEM API requires an area argument. */
    class GlobalPower(seat: VehicleSeat, val enabled: Boolean): Seated(seat, ClimateProperty.GLOBAL_POWER) {
        override val value: Boolean get()=enabled
    }
    class Ac(seat: VehicleSeat, override val value: Boolean): Seated(seat, ClimateProperty.AC)
    class AirCleaner(seat: VehicleSeat, override val value: Boolean): Seated(seat, ClimateProperty.AIR_CLEANER)
    class SeatHeat(seat: VehicleSeat, override val value: Int): Seated(seat, ClimateProperty.SEAT_HEAT)
    class SeatVentilation(seat: VehicleSeat, override val value: Int): Seated(seat, ClimateProperty.SEAT_VENTILATION)
    class WindowPosition(window: VehicleWindow, override val value: Int): Windowed(window, ClimateProperty.WINDOW_POSITION)
    class CabinLight(override val value: Boolean): ClimateTarget(ClimateProperty.CABIN_LIGHT)
    class ReadingLight(seat: VehicleSeat, override val value: Boolean): Seated(seat, ClimateProperty.READING_LIGHT)
    class AmbientLight(seat: VehicleSeat, override val value: Boolean): Seated(seat, ClimateProperty.AMBIENT_LIGHT)

    fun arguments(): Map<String,Any> = when(this) {
        is Seated -> mapOf("seat" to seat.name, "value" to value)
        is Windowed -> mapOf("window" to window.name, "value" to value)
        else -> mapOf("value" to value)
    }
}
/**
 * Pleos Vehicle SDK 2.3.2 (CarInfo: VIN/CRN only, SeatValue: row/side only) exposes no driver-side
 * or driver-seat API, so the left-hand-drive driver position is fixed here.
 */
val DRIVER_SEAT = VehicleSeat.ROW_1_LEFT
val DRIVER_WINDOW = VehicleWindow.ROW_1_LEFT
/**
 * Only setHvacPower is documented as the "global power state"; its area argument does not scope it.
 * Fan speed (per-area AreaBounds), AC ("for the designated areaId") and air cleaner take the seat area
 * they change, so they are seat-zone actions like temperature.
 */
val CAR_WIDE_CLIMATE_PROPERTIES = setOf(ClimateProperty.GLOBAL_POWER)
/**
 * Remote control never targets the driver seat. Seat-zone actions are also refused when the SDK area
 * that would be written includes the driver seat (one zone changes every seat in it).
 */
fun ClimateTarget.touchesDriverSeat(capability: ClimateCapability?): Boolean = when(this) {
    is ClimateTarget.Windowed -> window == DRIVER_WINDOW
    is ClimateTarget.Seated -> seat == DRIVER_SEAT || (property !in CAR_WIDE_CLIMATE_PROPERTIES &&
        capability?.area(seat)?.seats?.contains(DRIVER_SEAT) == true)
    else -> false
}
data class ClimateBounds(val minimum: Double, val maximum: Double) {
    fun valid()=minimum.isFinite() && maximum.isFinite() && minimum <= maximum
    private fun windowRangeValid()=valid() && minimum < maximum &&
        minimum >= Int.MIN_VALUE && maximum <= Int.MAX_VALUE &&
        minimum == kotlin.math.floor(minimum) && maximum == kotlin.math.floor(maximum)
    fun windowPosition(percent: Int): Int? = if(!windowRangeValid() || percent !in 0..100) null
        else kotlin.math.floor(minimum+(maximum-minimum)*percent/100.0+0.5).toInt()
    fun windowPercent(position: Int): Int? = if(!windowRangeValid() || position.toDouble() !in minimum..maximum) null
        else kotlin.math.floor((position.toDouble()-minimum)*100.0/(maximum-minimum)+0.5).toInt()
}
data class CelsiusStep(val minimum: Double, val maximum: Double, val increment: Double)
open class ClimateSeatArea(val seats: Set<VehicleSeat>)
data class ClimateCapability(
    val access: VehicleAccess,
    val areas: Set<VehicleSeat> = emptySet(),
    val bounds: Map<VehicleSeat, ClimateBounds> = emptyMap(),
    val celsiusStep: CelsiusStep? = null,
    val windows: Set<VehicleWindow> = emptySet(),
    val windowBounds: Map<VehicleWindow, ClimateBounds> = emptyMap(),
    val lightSwitches: Set<VehicleLightSwitch> = emptySet(),
    val seatLightSwitches: Map<VehicleSeat, Set<VehicleLightSwitch>> = emptyMap(),
    val seatAreas: List<ClimateSeatArea> = areas.map { ClimateSeatArea(setOf(it)) }
) {
    fun area(seat: VehicleSeat): ClimateSeatArea? =
        seatAreas.singleOrNull { seat in it.seats && seat in areas }
}
sealed interface ClimateReading {
    data class Celsius(val value: Float?): ClimateReading
    data class Fan(val value: Int?): ClimateReading
    data class GlobalPower(val enabled: Boolean?): ClimateReading
    data class Ac(val value: Boolean?): ClimateReading
    data class AirCleaner(val value: Boolean?): ClimateReading
    data class SeatHeat(val value: Int?): ClimateReading
    data class SeatVentilation(val value: Int?): ClimateReading
    data class WindowPosition(val value: Int?): ClimateReading
    data class CabinLight(val value: VehicleLightSwitch?): ClimateReading
    data class ReadingLight(val value: VehicleLightSwitch?): ClimateReading
    data class AmbientLight(val value: VehicleLightSwitch?): ClimateReading
}
fun decodeClimateTarget(property: ClimateProperty,args: Map<String,Any?>): ClimateTarget?=runCatching {
    val areaKey=when(property) {
        ClimateProperty.WINDOW_POSITION -> "window"
        ClimateProperty.CABIN_LIGHT -> null
        else -> "seat"
    }
    check(args.keys == if(areaKey==null)setOf("value") else setOf(areaKey,"value"))
    fun seat()=VehicleSeat.valueOf(args.getValue("seat") as String)
    fun window()=VehicleWindow.valueOf(args.getValue("window") as String)
    fun level(range: IntRange)=(args.getValue("value") as Int).also { check(it in range) }
    fun switch()=args.getValue("value") as Boolean
    when(property) {
        ClimateProperty.TARGET_CELSIUS -> {
            val value=args.getValue("value") as Number
            check(value.toDouble().isFinite() && value.toDouble() in 0.0..50.0)
            ClimateTarget.Celsius(seat(),value.toFloat())
        }
        ClimateProperty.FAN_LEVEL -> ClimateTarget.Fan(seat(),level(0..100))
        ClimateProperty.GLOBAL_POWER -> ClimateTarget.GlobalPower(seat(),switch())
        ClimateProperty.AC -> ClimateTarget.Ac(seat(),switch())
        ClimateProperty.AIR_CLEANER -> ClimateTarget.AirCleaner(seat(),switch())
        ClimateProperty.SEAT_HEAT -> ClimateTarget.SeatHeat(seat(),level(0..10))
        ClimateProperty.SEAT_VENTILATION -> ClimateTarget.SeatVentilation(seat(),level(0..10))
        ClimateProperty.WINDOW_POSITION -> ClimateTarget.WindowPosition(window(),level(0..100))
        ClimateProperty.CABIN_LIGHT -> ClimateTarget.CabinLight(switch())
        ClimateProperty.READING_LIGHT -> ClimateTarget.ReadingLight(seat(),switch())
        ClimateProperty.AMBIENT_LIGHT -> ClimateTarget.AmbientLight(seat(),switch())
    }
}.getOrNull()
/** initialize() returning means called only; actual support/read replies are separate observations. */
interface VehicleHardwarePort: AutoCloseable {
    fun initialize(): VehicleReply<Unit>
    fun climateCapability(property: ClimateProperty, callback: (VehicleReply<ClimateCapability>)->Unit)
    fun readClimate(target: ClimateTarget, capability: ClimateCapability, callback: (VehicleReply<ClimateReading>)->Unit)
    /** onComplete may echo the request; a caller must issue a separate read before confirming. */
    fun setClimate(target: ClimateTarget, capability: ClimateCapability, callback: (VehicleReply<Unit>)->Unit)
    fun telemetryCapability(signal: VehicleTelemetrySignal, callback: (VehicleReply<VehicleAccess>)->Unit)
    fun readTelemetry(signal: VehicleTelemetrySignal, callback: (VehicleReply<VehicleTelemetryValue?>)->Unit)
}
class VehicleHardwareSession(private val port: VehicleHardwarePort): AutoCloseable {
    private var initialized=false
    private var closed=false
    fun start(): VehicleReply<Unit> {
        if(closed)return VehicleReply.Failed(VehicleFailure.DISCONNECTED)
        if(initialized)return VehicleReply.Value(Unit)
        return port.initialize().also { initialized=it is VehicleReply.Value }
    }
    fun failed(reason: VehicleFailure?) {
        if(initialized && reason in setOf(VehicleFailure.DISCONNECTED,VehicleFailure.TIMEOUT,VehicleFailure.UNDEFINED)) {
            initialized=false
            port.close()
        }
    }
    override fun close() {
        if(closed)return
        closed=true
        initialized=false
        port.close()
    }
}
enum class VehicleTelemetrySignal { BRAKE_PRESSED, FUEL_PERCENT, ODOMETER_KM }
sealed interface VehicleTelemetryValue {
    data class Brake(val pressed: Boolean): VehicleTelemetryValue
    data class Fuel(val percent: Int): VehicleTelemetryValue
    data class Odometer(val kilometers: Float): VehicleTelemetryValue
}
fun interface VehicleCancellation { fun cancel() }
/** All state access and callbacks must be serialized through this owner lane. */
interface VehicleOperationLane {
    fun dispatch(block: ()->Unit)
    fun nowElapsedMillis(): Long
    fun schedule(delayMillis: Long, block: ()->Unit): VehicleCancellation
}

/**
 * Adapter-owned callback lifetime. Register/close on the owner lane; provider callbacks may arrive
 * on any thread. Closing settles every request once and old replies cannot cross reconnect.
 */
class VehicleCallbackOwner(private val lane: VehicleOperationLane) {
    private val pending=mutableMapOf<Any,()->Unit>()
    fun <T> register(callback: (VehicleReply<T>)->Unit): (VehicleReply<T>)->Unit {
        val token=Any()
        pending[token]={ callback(VehicleReply.Failed(VehicleFailure.DISCONNECTED)) }
        return { reply -> lane.dispatch {
            if (pending.remove(token)!=null) callback(reply)
        } }
    }
    fun close() {
        val callbacks=pending.values.toList()
        pending.clear()
        callbacks.forEach { it() }
    }
}

/** This is the current trusted command claim, not data accepted from a QR or capability JSON. */
data class VehicleCommandLease(
    val commandId: String, val ownerId: String, val deviceId: String,
    val grantId: String, val purposeId: String, val leaseId: String,
    val actionId: String, val actionRevision: String, val authorizationEpoch: Long,
    val expiresAtElapsedMillis: Long
) {
    fun wellFormed() = listOf(commandId,ownerId,deviceId,grantId,purposeId,leaseId,actionId,actionRevision)
        .all { it.isNotBlank() } && authorizationEpoch >= 0 && expiresAtElapsedMillis >= 0
}
data class VehicleCommandAuthority(
    val currentLease: VehicleCommandLease?,
    val foreground: Boolean, val parked: Boolean,
    val carUxKnown: Boolean, val setupAllowed: Boolean, val suspended: Boolean,
    val climateReceiverActive: Boolean = false
) {
    fun permits(expected: VehicleCommandLease, now: Long) =
        expected.wellFormed() && currentLease == expected && now >= 0 &&
        now < expected.expiresAtElapsedMillis && carUxKnown && !suspended &&
        ((foreground && parked && setupAllowed) || (climateReceiverActive &&
            (DRIVING_RECEIVER_CLIMATE_ACTIONS.values.any { it.matches(expected) } ||
                (parked && PARKED_RECEIVER_CLIMATE_ACTIONS.values.any { it.matches(expected) }))))
}
data class TrustedClimateAction(val id: String, val revision: String) {
    fun matches(lease: VehicleCommandLease) = id == lease.actionId && revision == lease.actionRevision
}
val DRIVING_RECEIVER_CLIMATE_ACTIONS: Map<ClimateProperty,TrustedClimateAction> = mapOf(
    ClimateProperty.TARGET_CELSIUS to TrustedClimateAction("hvac.temperature","1"),
    ClimateProperty.FAN_LEVEL to TrustedClimateAction("hvac.fan","1"),
    ClimateProperty.GLOBAL_POWER to TrustedClimateAction("hvac.power","1"),
    ClimateProperty.AC to TrustedClimateAction("hvac.ac","1"),
    ClimateProperty.AIR_CLEANER to TrustedClimateAction("hvac.air_cleaner","1"),
    ClimateProperty.WINDOW_POSITION to TrustedClimateAction("window.position","1"),
    ClimateProperty.READING_LIGHT to TrustedClimateAction("light.reading","1"),
    ClimateProperty.AMBIENT_LIGHT to TrustedClimateAction("light.ambient","1")
)
/** The receiver runs these only while parked, without needing the screen (cabin light lights the whole cabin). */
val PARKED_RECEIVER_CLIMATE_ACTIONS: Map<ClimateProperty,TrustedClimateAction> = mapOf(
    ClimateProperty.CABIN_LIGHT to TrustedClimateAction("light.cabin","1")
)
/** Seat heat/ventilation stay behind the foreground UX_RESTRICTIONS_NO_SETUP check. */
val TRUSTED_CLIMATE_ACTIONS: Map<ClimateProperty,TrustedClimateAction> = DRIVING_RECEIVER_CLIMATE_ACTIONS +
    PARKED_RECEIVER_CLIMATE_ACTIONS + mapOf(
    ClimateProperty.SEAT_HEAT to TrustedClimateAction("seat.heat","1"),
    ClimateProperty.SEAT_VENTILATION to TrustedClimateAction("seat.ventilation","1")
)
enum class VehicleCommandStage { CHECKING_SUPPORT, SETTER_READY, SDK_ACCEPTED, READBACK_REQUESTED }
enum class VehicleCommandState { BLOCKED, UNSUPPORTED, FAILED, UNKNOWN, TARGET_CONFIRMED }
data class VehicleCommandOutcome(
    val state: VehicleCommandState, val reason: VehicleFailure? = null,
    val mayHaveExecuted: Boolean = false, val readbackReceivedAtElapsedMillis: Long? = null,
    val readbackAttempts: Int = 0, val readbackWaitMillis: Long? = null
)

/**
 * Single-flight, one setter attempt, bounded independent readback. No setter retry, inverse setter, persistence,
 * network ACK or production registry registration. Default descriptor map is empty (disabled).
 * The host must re-evaluate the current authenticated owner/device/grant/claim/purpose/lease and
 * local receiver/foreground/Park/CarUx at authority(), and invalidate on every relevant withdrawal.
 */
class VehicleClimateCommandExecutor(
    private val port: VehicleHardwarePort,
    private val lane: VehicleOperationLane,
    private val authority: ()->VehicleCommandAuthority,
    trustedActions: Map<ClimateProperty,TrustedClimateAction> = emptyMap(),
    private val timeoutMillis: Long = 8_000
): AutoCloseable {
    private val trustedActions = trustedActions.toMap()
    private enum class Phase { CAPABILITY, SETTING, READING, DONE }
    private companion object {
        const val READBACK_WINDOW_MILLIS = 4_000L
        const val READBACK_RETRY_MILLIS = 250L
    }
    private class Pending(
        val lease: VehicleCommandLease, val target: ClimateTarget,
        val onStage: (VehicleCommandStage)->Unit, val callback: (VehicleCommandOutcome)->Unit
    ) {
        var phase = Phase.CAPABILITY
        var attempted = false
        var timeout: VehicleCancellation? = null
        var readRequestedAt: Long? = null
        var readDeadline = 0L
        var readGeneration = 0
        var readRetry: VehicleCancellation? = null
        var deadline: Long = 0
    }
    private var pending: Pending? = null
    private var closed = false
    private val seenCommands = mutableSetOf<String>()

    fun execute(
        lease: VehicleCommandLease, target: ClimateTarget,
        onStage: (VehicleCommandStage)->Unit = {}, callback: (VehicleCommandOutcome)->Unit
    ) = lane.dispatch {
        if (closed || pending != null || lease.commandId in seenCommands) {
            callback(VehicleCommandOutcome(VehicleCommandState.BLOCKED,
                if (closed) VehicleFailure.DISCONNECTED else VehicleFailure.BUSY))
            return@dispatch
        }
        val descriptor = trustedActions[target.property]
        if (descriptor == null || descriptor.id != lease.actionId || descriptor.revision != lease.actionRevision ||
            !permitted(lease) || timeoutMillis <= 0) {
            callback(VehicleCommandOutcome(VehicleCommandState.BLOCKED, VehicleFailure.EXPIRED_AUTHORITY))
            return@dispatch
        }
        val item = Pending(lease,target,onStage,callback)
        pending = item
        seenCommands.add(lease.commandId)
        val untilExpiry = lease.expiresAtElapsedMillis - lane.nowElapsedMillis()
        item.deadline = lane.nowElapsedMillis() + minOf(timeoutMillis,untilExpiry)
        item.timeout = lane.schedule(minOf(timeoutMillis,untilExpiry).coerceAtLeast(1)) {
            lane.dispatch { if (pending === item) finish(item, VehicleFailure.TIMEOUT) }
        }
        item.onStage(VehicleCommandStage.CHECKING_SUPPORT)
        if (!current(item,Phase.CAPABILITY)) return@dispatch
        invoke(item) {
            port.climateCapability(target.property) { reply -> lane.dispatch {
                if (!current(item,Phase.CAPABILITY)) return@dispatch
                when(reply) {
                    is VehicleReply.Failed -> finish(item,reply.reason)
                    is VehicleReply.Value -> {
                        val problem = validate(target,reply.value)
                        if (problem != null) { finish(item,problem); return@dispatch }
                        if (!permitted(lease)) { finish(item,VehicleFailure.EXPIRED_AUTHORITY); return@dispatch }
                        // Move phase before calling external SDK: duplicate/reentrant capability cannot set twice.
                        item.phase = Phase.SETTING
                        item.onStage(VehicleCommandStage.SETTER_READY)
                        // A stage consumer may revoke synchronously; do not dispatch after that revocation.
                        if (!current(item,Phase.SETTING)) return@dispatch
                        if (!permitted(lease)) { finish(item,VehicleFailure.EXPIRED_AUTHORITY); return@dispatch }
                        item.attempted = true
                        invoke(item) { port.setClimate(target,reply.value) { setter -> lane.dispatch {
                            if (!current(item,Phase.SETTING)) return@dispatch
                            when(setter) {
                                is VehicleReply.Failed -> finish(item,setter.reason)
                                is VehicleReply.Value -> {
                                    item.onStage(VehicleCommandStage.SDK_ACCEPTED)
                                    if (!current(item,Phase.SETTING)) return@dispatch
                                    if (!permitted(lease)) { finish(item,VehicleFailure.EXPIRED_AUTHORITY); return@dispatch }
                                    item.phase = Phase.READING
                                    item.readRequestedAt = lane.nowElapsedMillis()
                                    item.readDeadline = minOf(item.deadline,lane.nowElapsedMillis()+READBACK_WINDOW_MILLIS)
                                    item.onStage(VehicleCommandStage.READBACK_REQUESTED)
                                    if (!current(item,Phase.READING)) return@dispatch
                                    if (!permitted(lease)) { finish(item,VehicleFailure.EXPIRED_AUTHORITY); return@dispatch }
                                    fun readBack() {
                                    val generation=++item.readGeneration
                                    var replied=false
                                    invoke(item) { port.readClimate(target,reply.value) { readback -> lane.dispatch {
                                        if (!current(item,Phase.READING) || generation!=item.readGeneration || replied) return@dispatch
                                        replied=true
                                        if (!permitted(lease)) { finish(item,VehicleFailure.EXPIRED_AUTHORITY); return@dispatch }
                                        when(readback) {
                                            is VehicleReply.Failed -> finish(item,readback.reason)
                                            is VehicleReply.Value -> {
                                                val now = lane.nowElapsedMillis()
                                                if (now >= (item.readRequestedAt ?: Long.MAX_VALUE) && matches(target,readback.value))
                                                    complete(item,VehicleCommandOutcome(
                                                        VehicleCommandState.TARGET_CONFIRMED,
                                                        mayHaveExecuted=true,readbackReceivedAtElapsedMillis=now))
                                                else if (now < item.readDeadline)
                                                    item.readRetry=lane.schedule(minOf(READBACK_RETRY_MILLIS,item.readDeadline-now)) { lane.dispatch {
                                                        if (current(item,Phase.READING)) {
                                                            if (permitted(lease)) readBack()
                                                            else finish(item,VehicleFailure.EXPIRED_AUTHORITY)
                                                        }
                                                    } }
                                                else finish(item,VehicleFailure.MISMATCH)
                                            }
                                        }
                                    } } }
                                    }
                                    readBack()
                                }
                            }
                        } } }
                    }
                }
            } }
        }
    }
    /** Host calls on revoke/account/device switch/foreground or CarUx loss, including before expiry. */
    fun authorityChanged() = lane.dispatch {
        pending?.let { if (!permitted(it.lease)) finish(it,VehicleFailure.EXPIRED_AUTHORITY) }
    }
    override fun close() = lane.dispatch {
        closed = true
        pending?.let { finish(it,VehicleFailure.CANCELLED) }
    }
    private fun permitted(lease: VehicleCommandLease) = try {
        authority().permits(lease,lane.nowElapsedMillis())
    } catch (_: Exception) { false }
    private fun current(item: Pending,phase: Phase): Boolean {
        if (pending !== item || item.phase != phase || closed) return false
        // A busy main queue may deliver a provider reply before its delayed timer runnable.
        if (lane.nowElapsedMillis() >= item.deadline) {
            finish(item,VehicleFailure.TIMEOUT)
            return false
        }
        return true
    }
    private fun invoke(item: Pending,block: ()->Unit) {
        try { block() } catch (_: SecurityException) { finish(item,VehicleFailure.PERMISSION) }
        catch (_: Exception) { finish(item,VehicleFailure.INTERNAL) }
    }
    private fun finish(item: Pending,reason: VehicleFailure) {
        val state = when {
            item.attempted -> VehicleCommandState.UNKNOWN
            reason in setOf(VehicleFailure.UNSUPPORTED_PROPERTY,VehicleFailure.UNSUPPORTED_AREA) -> VehicleCommandState.UNSUPPORTED
            reason in setOf(VehicleFailure.EXPIRED_AUTHORITY,VehicleFailure.CANCELLED,VehicleFailure.PERMISSION,
                VehicleFailure.DRIVING_RESTRICTED,VehicleFailure.DRIVER_SEAT_RESTRICTED) -> VehicleCommandState.BLOCKED
            else -> VehicleCommandState.FAILED
        }
        complete(item,VehicleCommandOutcome(state,reason,item.attempted))
    }
    private fun complete(item: Pending,outcome: VehicleCommandOutcome) {
        if (pending !== item || item.phase == Phase.DONE) return
        item.phase=Phase.DONE
        item.timeout?.cancel()
        item.readRetry?.cancel()
        pending=null
        item.callback(outcome.copy(readbackAttempts=item.readGeneration,
            readbackWaitMillis=item.readRequestedAt?.let { (lane.nowElapsedMillis()-it).coerceAtLeast(0) }))
    }
    private fun validate(target: ClimateTarget,capability: ClimateCapability): VehicleFailure? {
        if (capability.access != VehicleAccess.READ_WRITE) return VehicleFailure.UNSUPPORTED_PROPERTY
        if (target.touchesDriverSeat(capability)) return VehicleFailure.DRIVER_SEAT_RESTRICTED
        if (target is ClimateTarget.Seated && capability.area(target.seat)==null) return VehicleFailure.UNSUPPORTED_AREA
        if (target is ClimateTarget.Windowed && target.window !in capability.windows) return VehicleFailure.UNSUPPORTED_AREA
        if (target is ClimateTarget.WindowPosition) {
            val bounds=capability.windowBounds[target.window] ?: return VehicleFailure.UNSUPPORTED_AREA
            return if(bounds.windowPosition(target.value)==null)VehicleFailure.INVALID_VALUE else null
        }
        val switches=when(target) {
            is ClimateTarget.CabinLight -> capability.lightSwitches
            is ClimateTarget.ReadingLight -> capability.seatLightSwitches[target.seat] ?: emptySet()
            is ClimateTarget.AmbientLight -> capability.seatLightSwitches[target.seat] ?: emptySet()
            else -> null
        }
        if (switches!=null) return if(lightSwitch(target.value as Boolean) in switches)null else VehicleFailure.INVALID_VALUE
        if (target.value is Boolean) return null
        val bounds=when(target) {
            is ClimateTarget.Seated -> capability.bounds[target.seat]
            else -> null
        } ?: return VehicleFailure.UNSUPPORTED_AREA
        if (!bounds.valid()) return VehicleFailure.INVALID_VALUE
        val value=(target.value as Number).toDouble()
        if (!value.isFinite() || value < bounds.minimum || value > bounds.maximum) return VehicleFailure.INVALID_VALUE
        if (target is ClimateTarget.SeatHeat || target is ClimateTarget.SeatVentilation)
            if(value !in 0.0..10.0)return VehicleFailure.INVALID_VALUE
        if (target is ClimateTarget.Celsius) capability.celsiusStep?.let { step ->
            if (!step.minimum.isFinite() || !step.maximum.isFinite() || !step.increment.isFinite() ||
                step.minimum > step.maximum || step.increment <= 0 || value < step.minimum || value > step.maximum)
                return VehicleFailure.INVALID_VALUE
            val count=(value-step.minimum)/step.increment
            if (!count.isFinite() || kotlin.math.abs(count-kotlin.math.round(count)) > .001)
                return VehicleFailure.INVALID_VALUE
        }
        return null
    }
    private fun lightSwitch(value: Boolean)=if(value)VehicleLightSwitch.ON else VehicleLightSwitch.OFF
    private fun matches(target: ClimateTarget,value: ClimateReading) = when(target) {
        is ClimateTarget.Celsius -> value is ClimateReading.Celsius && value.value?.isFinite()==true &&
            kotlin.math.abs(value.value-target.value) < .001f
        is ClimateTarget.Fan -> value is ClimateReading.Fan && value.value == target.value
        is ClimateTarget.GlobalPower -> value is ClimateReading.GlobalPower && value.enabled == target.enabled
        is ClimateTarget.Ac -> value is ClimateReading.Ac && value.value == target.value
        is ClimateTarget.AirCleaner -> value is ClimateReading.AirCleaner && value.value == target.value
        is ClimateTarget.SeatHeat -> value is ClimateReading.SeatHeat && value.value == target.value
        is ClimateTarget.SeatVentilation -> value is ClimateReading.SeatVentilation && value.value == target.value
        is ClimateTarget.WindowPosition -> value is ClimateReading.WindowPosition && value.value == target.value
        is ClimateTarget.CabinLight -> value is ClimateReading.CabinLight && value.value == lightSwitch(target.value)
        is ClimateTarget.ReadingLight -> value is ClimateReading.ReadingLight && value.value == lightSwitch(target.value)
        is ClimateTarget.AmbientLight -> value is ClimateReading.AmbientLight && value.value == lightSwitch(target.value)
    }
}
