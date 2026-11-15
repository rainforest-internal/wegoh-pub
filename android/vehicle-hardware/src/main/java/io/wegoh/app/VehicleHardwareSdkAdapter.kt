package io.wegoh.app

import android.content.Context
import android.content.pm.PackageManager
import android.os.DeadObjectException
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import ai.pleos.playground.vehicle.Vehicle
import ai.pleos.playground.vehicle.api.model.area.SeatArea
import ai.pleos.playground.vehicle.api.model.area.WindowArea
import ai.pleos.playground.vehicle.api.model.capability.AccessType
import ai.pleos.playground.vehicle.constant.area.WindowValue
import ai.pleos.playground.vehicle.constant.control.LightSwitch
import ai.pleos.playground.vehicle.constant.unit.TemperatureUnit

/**
 * The provided 2.3.2 AAR does not expose the documented VehicleException class name.
 * No reflection, obfuscated implementation class or message parsing is used here.
 * Normal Java SecurityException is distinguishable; other unmatched errors remain UNDEFINED.
 * A failure before the setter blocks execution; a failure after it leaves the outcome unknown.
 */
fun interface VehicleSdkFailureDecoder {
    fun decode(error: Exception): VehicleFailure
}
class AndroidVehicleOperationLane: VehicleOperationLane {
    private val handler=Handler(Looper.getMainLooper())
    override fun dispatch(block: ()->Unit) {
        if (Looper.myLooper()==handler.looper) block() else handler.post(block)
    }
    override fun nowElapsedMillis()=SystemClock.elapsedRealtime()
    override fun schedule(delayMillis: Long,block: ()->Unit): VehicleCancellation {
        val task=Runnable(block)
        handler.postDelayed(task,delayMillis)
        return VehicleCancellation { handler.removeCallbacks(task) }
    }
}

/** Host app only: never package OEM dependencies or permissions in the reusable Native AAR. */
class VehicleHardwareSdkAdapter(
    context: Context,
    private val failureDecoder: VehicleSdkFailureDecoder = VehicleSdkFailureDecoder {
        when(it) {
            is SecurityException -> VehicleFailure.PERMISSION
            is DeadObjectException -> VehicleFailure.DISCONNECTED
            else -> VehicleFailure.UNDEFINED
        }
    }
): VehicleHardwarePort {
    private val context=context.applicationContext
    private var vehicle: Vehicle?=null
    private val callbacks=VehicleCallbackOwner(AndroidVehicleOperationLane())

    override fun initialize(): VehicleReply<Unit> {
        checkMain()
        if(vehicle!=null)return VehicleReply.Value(Unit)
        val started=SystemClock.elapsedRealtime()
        Log.i("WegoClimate","climate.receiver: session initializing")
        var candidate: Vehicle?=null
        return try {
            candidate=Vehicle(context)
            candidate.initialize()
            vehicle=candidate
            Log.i("WegoClimate","climate.receiver: session initialized elapsed_ms=${SystemClock.elapsedRealtime()-started} readiness=awaiting_capability")
            VehicleReply.Value(Unit)
        } catch (error: Exception) {
            runCatching { candidate?.release() }
            val reason=decode(error)
            Log.i("WegoClimate","climate.receiver: failed phase=session reason=${reason.name.lowercase()} elapsed_ms=${SystemClock.elapsedRealtime()-started}")
            VehicleReply.Failed(reason)
        }
    }

    override fun climateCapability(property: ClimateProperty,callback: (VehicleReply<ClimateCapability>)->Unit) =
        use(observe("capability",property,callback)) { sdk,reply ->
            val failed: (Exception)->Unit={ reply(VehicleReply.Failed(decode(it))) }
            when(property) {
                ClimateProperty.TARGET_CELSIUS -> sdk.getHVAC().checkHvacTemperatureCapabilities(
                    { config,areas,step ->
                        val capability=seatCapability(config.accessType,areas.keys.toList())
                        val bounds=areas.entries.flatMap { (area,range) -> seats(area).map {
                            it to ClimateBounds(range.minValue.toDouble(),range.maxValue.toDouble())
                        }}.toMap()
                        reply(VehicleReply.Value(capability.copy(bounds=bounds,
                            celsiusStep=step?.let { CelsiusStep(it.minCelsius.toDouble(),it.maxCelsius.toDouble(),it.incrementCelsius.toDouble()) })))
                    },failed)
                ClimateProperty.FAN_LEVEL -> sdk.getHVAC().checkHvacFanSpeedCapabilities(
                    { config,areas -> reply(VehicleReply.Value(seatBounds(config.accessType,areas))) },failed)
                ClimateProperty.GLOBAL_POWER -> sdk.getHVAC().checkHvacPowerCapabilities(
                    { config,areas -> reply(VehicleReply.Value(seatCapability(config.accessType,areas))) },failed)
                ClimateProperty.AC -> sdk.getHVAC().checkHvacAcCapabilities(
                    { config,areas -> reply(VehicleReply.Value(seatCapability(config.accessType,areas))) },failed)
                ClimateProperty.AIR_CLEANER -> sdk.getHVAC().checkHvacAirCleanerCapabilities(
                    { config,areas -> reply(VehicleReply.Value(seatCapability(config.accessType,areas))) },failed)
                ClimateProperty.SEAT_HEAT -> sdk.getSeat().checkSeatTemperatureCapabilities(
                    { config,areas -> reply(VehicleReply.Value(seatBounds(config.accessType,areas))) },failed)
                ClimateProperty.SEAT_VENTILATION -> sdk.getSeat().checkSeatVentilationCapabilities(
                    { config,areas -> reply(VehicleReply.Value(seatBounds(config.accessType,areas))) },failed)
                ClimateProperty.WINDOW_POSITION -> sdk.getWindow().checkWindowPositionCapabilities(
                    { config,areas ->
                        val bounds=areas.entries.mapNotNull { (area,range) -> window(area)?.let {
                            it to ClimateBounds(range.minValue.toDouble(),range.maxValue.toDouble())
                        }}.toMap()
                        reply(VehicleReply.Value(ClimateCapability(access(config.accessType),windows=bounds.keys,windowBounds=bounds)))
                    },failed)
                ClimateProperty.CABIN_LIGHT -> sdk.getLight().checkCabinLightSwitchCapabilities(
                    { config,values -> reply(VehicleReply.Value(ClimateCapability(access(config.accessType),
                        lightSwitches=values.map(::lightSwitch).toSet()))) },failed)
                ClimateProperty.READING_LIGHT -> sdk.getLight().checkReadingLightSwitchCapabilities(
                    { config,areas -> reply(VehicleReply.Value(seatLights(config.accessType,areas))) },failed)
                ClimateProperty.AMBIENT_LIGHT -> sdk.getLight().checkAmbientLightSwitchCapabilities(
                    { config,areas -> reply(VehicleReply.Value(seatLights(config.accessType,areas))) },failed)
            }
        }

    override fun readClimate(target: ClimateTarget,capability: ClimateCapability,callback: (VehicleReply<ClimateReading>)->Unit) =
        use(observe("getter",target.property,callback)) { sdk,reply ->
            val failed: (Exception)->Unit={ reply(VehicleReply.Failed(decode(it))) }
            val seatArea=(target as? ClimateTarget.Seated)?.let { area(it.seat,capability) }
            if(target is ClimateTarget.Seated && seatArea==null) {
                reply(VehicleReply.Failed(VehicleFailure.UNSUPPORTED_AREA));return@use
            }
            when(target) {
                is ClimateTarget.Celsius -> sdk.getHVAC().getHvacTemperature(requireNotNull(seatArea),TemperatureUnit.CELSIUS,
                    { reply(VehicleReply.Value(ClimateReading.Celsius(it))) },failed)
                is ClimateTarget.Fan -> sdk.getHVAC().getHvacFanSpeed(requireNotNull(seatArea),
                    { reply(VehicleReply.Value(ClimateReading.Fan(it))) },failed)
                is ClimateTarget.GlobalPower -> sdk.getHVAC().getHvacPowerState(requireNotNull(seatArea),
                    { reply(VehicleReply.Value(ClimateReading.GlobalPower(it))) },failed)
                is ClimateTarget.Ac -> sdk.getHVAC().getHvacAcState(requireNotNull(seatArea),
                    { reply(VehicleReply.Value(ClimateReading.Ac(it))) },failed)
                is ClimateTarget.AirCleaner -> sdk.getHVAC().getHvacAirCleanerState(requireNotNull(seatArea),
                    { reply(VehicleReply.Value(ClimateReading.AirCleaner(it))) },failed)
                is ClimateTarget.SeatHeat -> sdk.getSeat().getHvacSeatTemperature(requireNotNull(seatArea),
                    { reply(VehicleReply.Value(ClimateReading.SeatHeat(it))) },failed)
                is ClimateTarget.SeatVentilation -> sdk.getSeat().getHvacSeatVentilationState(requireNotNull(seatArea),
                    { reply(VehicleReply.Value(ClimateReading.SeatVentilation(it))) },failed)
                is ClimateTarget.WindowPosition -> {
                    val bounds=capability.windowBounds[target.window]
                    if(target.window !in capability.windows || bounds==null)
                        reply(VehicleReply.Failed(VehicleFailure.UNSUPPORTED_AREA))
                    else sdk.getWindow().getCurrentWindowPosition(area(target.window),
                        { reply(VehicleReply.Value(ClimateReading.WindowPosition(it?.let(bounds::windowPercent)))) },failed)
                }
                is ClimateTarget.CabinLight -> sdk.getLight().getCabinLightSwitch(
                    { reply(VehicleReply.Value(ClimateReading.CabinLight(it?.let(::lightSwitch)))) },failed)
                is ClimateTarget.ReadingLight -> sdk.getLight().getReadingLightSwitch(requireNotNull(seatArea),
                    { reply(VehicleReply.Value(ClimateReading.ReadingLight(it?.let(::lightSwitch)))) },failed)
                is ClimateTarget.AmbientLight -> sdk.getLight().getAmbientLightSwitch(requireNotNull(seatArea),
                    { reply(VehicleReply.Value(ClimateReading.AmbientLight(it?.let(::lightSwitch)))) },failed)
            }
        }

    override fun setClimate(target: ClimateTarget,capability: ClimateCapability,callback: (VehicleReply<Unit>)->Unit) =
        use(observe("setter",target.property,callback)) { sdk,reply ->
            val failed: (Exception)->Unit={ reply(VehicleReply.Failed(decode(it))) }
            val seatArea=(target as? ClimateTarget.Seated)?.let { area(it.seat,capability) }
            if(target is ClimateTarget.Seated && seatArea==null) {
                reply(VehicleReply.Failed(VehicleFailure.UNSUPPORTED_AREA));return@use
            }
            // Deliberately discard callback area/value: they may echo requested arguments.
            when(target) {
                is ClimateTarget.Celsius -> sdk.getHVAC().setHvacTemperature(requireNotNull(seatArea),target.value,TemperatureUnit.CELSIUS,
                    { _,_ -> reply(VehicleReply.Value(Unit)) },failed)
                is ClimateTarget.Fan -> sdk.getHVAC().setHvacFanSpeed(requireNotNull(seatArea),target.value,
                    { _,_ -> reply(VehicleReply.Value(Unit)) },failed)
                is ClimateTarget.GlobalPower -> sdk.getHVAC().setHvacPower(requireNotNull(seatArea),target.enabled,
                    { _,_ -> reply(VehicleReply.Value(Unit)) },failed)
                is ClimateTarget.Ac -> sdk.getHVAC().setHvacAc(requireNotNull(seatArea),target.value,
                    { _,_ -> reply(VehicleReply.Value(Unit)) },failed)
                is ClimateTarget.AirCleaner -> sdk.getHVAC().setHvacAirCleaner(requireNotNull(seatArea),target.value,
                    { _,_ -> reply(VehicleReply.Value(Unit)) },failed)
                is ClimateTarget.SeatHeat -> sdk.getSeat().setHvacSeatTemperature(requireNotNull(seatArea),target.value,
                    { _,_ -> reply(VehicleReply.Value(Unit)) },failed)
                is ClimateTarget.SeatVentilation -> sdk.getSeat().setHvacSeatVentilation(requireNotNull(seatArea),target.value,
                    { _,_ -> reply(VehicleReply.Value(Unit)) },failed)
                is ClimateTarget.WindowPosition -> {
                    val bounds=capability.windowBounds[target.window]
                    val position=bounds?.windowPosition(target.value)
                    if(target.window !in capability.windows || bounds==null)
                        reply(VehicleReply.Failed(VehicleFailure.UNSUPPORTED_AREA))
                    else if(position==null)reply(VehicleReply.Failed(VehicleFailure.INVALID_VALUE))
                    else sdk.getWindow().setWindowPosition(area(target.window),position,
                        { _,_ -> reply(VehicleReply.Value(Unit)) },failed)
                }
                is ClimateTarget.CabinLight -> sdk.getLight().setCabinLightSwitch(lightSwitch(target.value),
                    { _ -> reply(VehicleReply.Value(Unit)) },failed)
                is ClimateTarget.ReadingLight -> sdk.getLight().setReadingLightSwitch(requireNotNull(seatArea),lightSwitch(target.value),
                    { _ -> reply(VehicleReply.Value(Unit)) },failed)
                is ClimateTarget.AmbientLight -> sdk.getLight().setAmbientLightSwitch(requireNotNull(seatArea),lightSwitch(target.value),
                    { _,_ -> reply(VehicleReply.Value(Unit)) },failed)
            }
        }

    // These optional sensor permissions are deliberately not requested by this app.
    // Each SDK branch below first returns PERMISSION unless its literal permission is granted.
    @android.annotation.SuppressLint("MissingPermission")
    override fun telemetryCapability(signal: VehicleTelemetrySignal,callback: (VehicleReply<VehicleAccess>)->Unit) =
        use(callback) { sdk,reply ->
            val done: (ai.pleos.playground.vehicle.api.model.capability.CapabilityConfig)->Unit =
                { reply(VehicleReply.Value(access(it.accessType))) }
            val failed: (Exception)->Unit={ reply(VehicleReply.Failed(decode(it))) }
            when(signal) {
                VehicleTelemetrySignal.BRAKE_PRESSED -> {
                    if(context.checkSelfPermission("pleos.car.permission.CAR_DRIVE")!=PackageManager.PERMISSION_GRANTED)
                        reply(VehicleReply.Failed(VehicleFailure.PERMISSION))
                    else sdk.getBrake().checkBrakePedalStatusCapabilities(done,failed)
                }
                VehicleTelemetrySignal.FUEL_PERCENT -> {
                    if(context.checkSelfPermission("pleos.car.permission.CAR_ENERGY")!=PackageManager.PERMISSION_GRANTED)
                        reply(VehicleReply.Failed(VehicleFailure.PERMISSION))
                    else sdk.getFuel().checkFuelPercentCapabilities(done,failed)
                }
                VehicleTelemetrySignal.ODOMETER_KM -> {
                    if(context.checkSelfPermission("pleos.car.permission.CAR_DRIVE")!=PackageManager.PERMISSION_GRANTED)
                        reply(VehicleReply.Failed(VehicleFailure.PERMISSION))
                    else sdk.getOdometer().checkCurrentDistanceDrivenCapabilities(done,failed)
                }
            }
        }

    // These optional sensor permissions are deliberately not requested by this app.
    // Each SDK branch below first returns PERMISSION unless its literal permission is granted.
    @android.annotation.SuppressLint("MissingPermission")
    override fun readTelemetry(signal: VehicleTelemetrySignal,callback: (VehicleReply<VehicleTelemetryValue?>)->Unit) =
        use(callback) { sdk,reply ->
            val failed: (Exception)->Unit={ reply(VehicleReply.Failed(decode(it))) }
            when(signal) {
                VehicleTelemetrySignal.BRAKE_PRESSED -> {
                    if(context.checkSelfPermission("pleos.car.permission.CAR_DRIVE")!=PackageManager.PERMISSION_GRANTED)
                        reply(VehicleReply.Failed(VehicleFailure.PERMISSION))
                    else sdk.getBrake().getCurrentBrakePedalStatus(
                        { value -> reply(VehicleReply.Value(value?.let { VehicleTelemetryValue.Brake(it) })) },failed)
                }
                VehicleTelemetrySignal.FUEL_PERCENT -> {
                    if(context.checkSelfPermission("pleos.car.permission.CAR_ENERGY")!=PackageManager.PERMISSION_GRANTED)
                        reply(VehicleReply.Failed(VehicleFailure.PERMISSION))
                    else sdk.getFuel().getFuelPercent(
                        { value -> reply(VehicleReply.Value(value?.let { VehicleTelemetryValue.Fuel(it) })) },failed)
                }
                VehicleTelemetrySignal.ODOMETER_KM -> {
                    if(context.checkSelfPermission("pleos.car.permission.CAR_DRIVE")!=PackageManager.PERMISSION_GRANTED)
                        reply(VehicleReply.Failed(VehicleFailure.PERMISSION))
                    else sdk.getOdometer().getCurrentDistanceDriven(
                        { value -> reply(VehicleReply.Value(value?.let { VehicleTelemetryValue.Odometer(it) })) },failed)
                }
            }
        }

    override fun close() {
        checkMain()
        val old=vehicle
        vehicle=null
        callbacks.close()
        runCatching { old?.release() }
        if(old!=null)Log.i("WegoClimate","climate.receiver: session closed")
    }
    private fun <T> observe(operation: String,property: ClimateProperty,callback: (VehicleReply<T>)->Unit): (VehicleReply<T>)->Unit {
        val started=SystemClock.elapsedRealtime()
        Log.i("WegoClimate","climate.receiver: sdk started phase=$operation property=${property.name.lowercase()}")
        return { reply->
            val reason=(reply as? VehicleReply.Failed)?.reason
            val result=if(reason==null)"sdk completed" else "failed"
            Log.i("WegoClimate","climate.receiver: $result phase=$operation property=${property.name.lowercase()} reason=${reason?.name?.lowercase() ?: "none"} elapsed_ms=${SystemClock.elapsedRealtime()-started}")
            callback(reply)
        }
    }
    private fun <T> use(callback: (VehicleReply<T>)->Unit,block: (Vehicle,(VehicleReply<T>)->Unit)->Unit) {
        checkMain()
        val sdk=vehicle
        if (sdk==null) { callback(VehicleReply.Failed(VehicleFailure.DISCONNECTED)); return }
        val reply=callbacks.register(callback)
        try { block(sdk,reply) } catch(error: Exception) { reply(VehicleReply.Failed(decode(error))) }
    }
    private fun decode(error: Exception): VehicleFailure {
        val reason=try {failureDecoder.decode(error)} catch(_: Exception) {VehicleFailure.UNDEFINED}
        Log.i("WegoClimate","climate.receiver: sdk failed reason=${reason.name.lowercase()} sdk_error_code=${failureCode(error)}")
        return reason
    }
    private fun checkMain()=check(Looper.myLooper()==Looper.getMainLooper())
    private class SdkSeatArea(val sdkArea: SeatArea): ClimateSeatArea(seats(sdkArea))
    private fun area(window: VehicleWindow)=WindowArea(WindowValue.valueOf(window.name))
    private fun window(area: WindowArea)=area.values.singleOrNull()?.let {
        VehicleWindow.entries.firstOrNull { window -> window.name==it.name }
    }
    private fun lightSwitch(value: Boolean)=if(value)LightSwitch.ON else LightSwitch.OFF
    internal companion object {
        internal fun failureCode(error: Exception): String {
            val message=runCatching {error.message}.getOrNull()
            return message?.takeIf {Regex("-?[0-9]{1,10}").matches(it)}?.toIntOrNull()?.toString() ?: "unavailable"
        }
        fun area(seat: VehicleSeat,capability: ClimateCapability)=
            (capability.area(seat) as? SdkSeatArea)?.sdkArea
        private fun lightSwitch(value: LightSwitch)=VehicleLightSwitch.valueOf(value.name)
        internal fun seatCapability(accessType: AccessType,areas: List<SeatArea>): ClimateCapability {
            val groups=areas.map(::SdkSeatArea)
            return ClimateCapability(access(accessType),groups.flatMap { it.seats }.toSet(),seatAreas=groups)
        }
        internal fun seatBounds(accessType: AccessType,areas: Map<SeatArea,ai.pleos.playground.vehicle.api.model.capability.AreaBounds<Int>>): ClimateCapability {
            val bounds=areas.entries.flatMap { (area,range) -> seats(area).map {
                it to ClimateBounds(range.minValue.toDouble(),range.maxValue.toDouble())
            }}.toMap()
            return seatCapability(accessType,areas.keys.toList()).copy(bounds=bounds)
        }
        internal fun seatLights(accessType: AccessType,areas: Map<SeatArea,List<LightSwitch>>): ClimateCapability {
            val switches=areas.entries.flatMap { (area,values) -> seats(area).map {
                it to values.map(::lightSwitch).toSet()
            }}.toMap()
            return seatCapability(accessType,areas.keys.toList()).copy(seatLightSwitches=switches)
        }
        private fun seats(area: SeatArea)=area.values.mapNotNull { value ->
            VehicleSeat.entries.firstOrNull { it.name==value.name }
        }.toSet()
        private fun access(value: AccessType)=when(value) {
            AccessType.NONE -> VehicleAccess.NONE
            AccessType.READ -> VehicleAccess.READ
            AccessType.WRITE -> VehicleAccess.WRITE
            AccessType.READ_WRITE -> VehicleAccess.READ_WRITE
        }
    }
}
