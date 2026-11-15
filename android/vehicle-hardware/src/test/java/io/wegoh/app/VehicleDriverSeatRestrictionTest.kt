package io.wegoh.app

import org.junit.Assert.*
import org.junit.Test

class VehicleDriverSeatRestrictionTest {
    private val left=VehicleSeat.ROW_1_LEFT
    private val right=VehicleSeat.ROW_1_RIGHT
    private val rear=VehicleSeat.ROW_2_LEFT

    @Test fun driverSeatAndDriverWindowAreRefusedForEverySeatedAction() {
        val alone=capability(setOf(left,right,rear))
        for(target in listOf(
            ClimateTarget.Celsius(left,22f),ClimateTarget.Fan(left,3),ClimateTarget.GlobalPower(left,true),
            ClimateTarget.Ac(left,true),ClimateTarget.AirCleaner(left,true),ClimateTarget.SeatHeat(left,2),
            ClimateTarget.SeatVentilation(left,2),ClimateTarget.ReadingLight(left,true),ClimateTarget.AmbientLight(left,true))) {
            val result=run(target,alone,parked=true)
            assertEquals(target.property.name,VehicleFailure.DRIVER_SEAT_RESTRICTED,result.outcome.reason)
            assertEquals(VehicleCommandState.BLOCKED,result.outcome.state)
            assertEquals(0,result.port.writes)
        }
        val window=run(ClimateTarget.WindowPosition(VehicleWindow.ROW_1_LEFT,30),windows(),parked=true)
        assertEquals(VehicleFailure.DRIVER_SEAT_RESTRICTED,window.outcome.reason)
        assertEquals(0,window.port.writes)
    }

    @Test fun seatZoneActionsAreRefusedWhenTheSdkAreaAlsoChangesTheDriverSeat() {
        val shared=capability(setOf(left,right,rear),ClimateSeatArea(setOf(left,rear)),ClimateSeatArea(setOf(right)))
        for(target in listOf(ClimateTarget.Celsius(rear,22f),ClimateTarget.Fan(rear,3),ClimateTarget.Ac(rear,true),
            ClimateTarget.AirCleaner(rear,true),ClimateTarget.SeatHeat(rear,2),
            ClimateTarget.ReadingLight(rear,true),ClimateTarget.AmbientLight(rear,true))) {
            val result=run(target,shared,parked=true)
            assertEquals(target.property.name,VehicleFailure.DRIVER_SEAT_RESTRICTED,result.outcome.reason)
            assertEquals(0,result.port.writes)
        }
        assertEquals(VehicleCommandState.TARGET_CONFIRMED,run(ClimateTarget.Celsius(right,22f),shared,parked=true).outcome.state)
    }

    @Test fun onlyGlobalPowerStaysAvailableFromAPassengerSeatInACabinArea() {
        val cabin=capability(setOf(left,right,rear),ClimateSeatArea(setOf(left,right,rear)))
        assertEquals(VehicleCommandState.TARGET_CONFIRMED,run(ClimateTarget.GlobalPower(right,true),cabin,parked=false).outcome.state)
        for(target in listOf(ClimateTarget.Fan(right,3),ClimateTarget.Ac(right,true),ClimateTarget.AirCleaner(rear,true))) {
            val result=run(target,cabin,parked=false)
            assertEquals(target.property.name,VehicleFailure.DRIVER_SEAT_RESTRICTED,result.outcome.reason)
            assertEquals(0,result.port.writes)
        }
        val split=capability(setOf(left,right,rear),ClimateSeatArea(setOf(left)),ClimateSeatArea(setOf(right)),ClimateSeatArea(setOf(rear)))
        for(target in listOf(ClimateTarget.Fan(right,3),ClimateTarget.Ac(right,true),ClimateTarget.AirCleaner(rear,true)))
            assertEquals(target.property.name,VehicleCommandState.TARGET_CONFIRMED,run(target,split,parked=false).outcome.state)
    }

    @Test fun cabinLightRunsOnlyWhileParkedButPassengerWindowStillRunsWhileDriving() {
        val lights=ClimateCapability(VehicleAccess.READ_WRITE,lightSwitches=setOf(VehicleLightSwitch.OFF,VehicleLightSwitch.ON))
        val driving=run(ClimateTarget.CabinLight(true),lights,parked=false)
        assertEquals(VehicleCommandState.BLOCKED,driving.outcome.state)
        assertEquals(VehicleFailure.EXPIRED_AUTHORITY,driving.outcome.reason)
        assertEquals(0,driving.port.writes)
        assertNull(DRIVING_RECEIVER_CLIMATE_ACTIONS[ClimateProperty.CABIN_LIGHT])
        assertEquals(VehicleCommandState.TARGET_CONFIRMED,run(ClimateTarget.CabinLight(true),lights,parked=true).outcome.state)
        assertEquals(VehicleCommandState.TARGET_CONFIRMED,
            run(ClimateTarget.WindowPosition(VehicleWindow.ROW_1_RIGHT,30),windows(),parked=false).outcome.state)
    }

    @Test fun parkedReceiverRunsCabinLightWithoutTheRemoteScreenButNotSeatSetup() {
        val lights=ClimateCapability(VehicleAccess.READ_WRITE,lightSwitches=setOf(VehicleLightSwitch.OFF,VehicleLightSwitch.ON))
        val background=run(ClimateTarget.CabinLight(true),lights,parked=true,foreground=false)
        assertEquals(VehicleCommandState.TARGET_CONFIRMED,background.outcome.state)
        assertEquals(1,background.port.writes)
        val driving=run(ClimateTarget.CabinLight(true),lights,parked=false,foreground=false)
        assertEquals(VehicleFailure.EXPIRED_AUTHORITY,driving.outcome.reason)
        assertEquals(0,driving.port.writes)
        val receiverOff=run(ClimateTarget.CabinLight(true),lights,parked=true,foreground=false,receiverActive=false)
        assertEquals(VehicleFailure.EXPIRED_AUTHORITY,receiverOff.outcome.reason)
        val heat=run(ClimateTarget.SeatHeat(right,2),capability(setOf(left,right,rear)),parked=true,foreground=false)
        assertEquals(VehicleFailure.EXPIRED_AUTHORITY,heat.outcome.reason)
        assertEquals(0,heat.port.writes)
    }

    private fun capability(seats: Set<VehicleSeat>,vararg areas: ClimateSeatArea)=ClimateCapability(VehicleAccess.READ_WRITE,seats,
        seats.associateWith {ClimateBounds(0.0,30.0)},seatLightSwitches=seats.associateWith {setOf(VehicleLightSwitch.OFF,VehicleLightSwitch.ON)},
        seatAreas=if(areas.isEmpty())seats.map {ClimateSeatArea(setOf(it))} else areas.toList())
    private fun windows()=ClimateCapability(VehicleAccess.READ_WRITE,windows=setOf(VehicleWindow.ROW_1_LEFT,VehicleWindow.ROW_1_RIGHT),
        windowBounds=mapOf(VehicleWindow.ROW_1_LEFT to ClimateBounds(0.0,100.0),VehicleWindow.ROW_1_RIGHT to ClimateBounds(0.0,100.0)))

    private class Result(val outcome: VehicleCommandOutcome,val port: Port)
    private fun run(target: ClimateTarget,capability: ClimateCapability,parked: Boolean,
                    foreground: Boolean=parked,receiverActive: Boolean=true): Result {
        val action=checkNotNull(TRUSTED_CLIMATE_ACTIONS[target.property])
        val lease=VehicleCommandLease("command","owner","device","grant","purpose","lease",action.id,action.revision,1,10_000)
        val port=Port(capability)
        var outcome: VehicleCommandOutcome?=null
        VehicleClimateCommandExecutor(port,Lane,{
            VehicleCommandAuthority(lease,foreground=foreground,parked=parked,carUxKnown=true,setupAllowed=parked,
                suspended=false,climateReceiverActive=receiverActive)
        },TRUSTED_CLIMATE_ACTIONS).execute(lease,target) {outcome=it}
        return Result(checkNotNull(outcome),port)
    }
    private object Lane: VehicleOperationLane {
        override fun dispatch(block: ()->Unit)=block()
        override fun nowElapsedMillis()=100L
        override fun schedule(delayMillis: Long,block: ()->Unit)=VehicleCancellation {}
    }
    private class Port(val capability: ClimateCapability): VehicleHardwarePort {
        var writes=0
        private var last: ClimateTarget?=null
        override fun initialize(): VehicleReply<Unit> =VehicleReply.Value(Unit)
        override fun close() {}
        override fun climateCapability(property: ClimateProperty,callback: (VehicleReply<ClimateCapability>)->Unit)=
            callback(VehicleReply.Value(capability))
        override fun setClimate(target: ClimateTarget,capability: ClimateCapability,callback: (VehicleReply<Unit>)->Unit) {
            writes++;last=target;callback(VehicleReply.Value(Unit))
        }
        override fun readClimate(target: ClimateTarget,capability: ClimateCapability,callback: (VehicleReply<ClimateReading>)->Unit) {
            val value=checkNotNull(last).value
            callback(VehicleReply.Value(when(target) {
                is ClimateTarget.Celsius -> ClimateReading.Celsius(value as Float)
                is ClimateTarget.Fan -> ClimateReading.Fan(value as Int)
                is ClimateTarget.GlobalPower -> ClimateReading.GlobalPower(value as Boolean)
                is ClimateTarget.Ac -> ClimateReading.Ac(value as Boolean)
                is ClimateTarget.AirCleaner -> ClimateReading.AirCleaner(value as Boolean)
                is ClimateTarget.SeatHeat -> ClimateReading.SeatHeat(value as Int)
                is ClimateTarget.SeatVentilation -> ClimateReading.SeatVentilation(value as Int)
                is ClimateTarget.WindowPosition -> ClimateReading.WindowPosition(value as Int)
                is ClimateTarget.CabinLight -> ClimateReading.CabinLight(if(value as Boolean)VehicleLightSwitch.ON else VehicleLightSwitch.OFF)
                is ClimateTarget.ReadingLight -> ClimateReading.ReadingLight(if(value as Boolean)VehicleLightSwitch.ON else VehicleLightSwitch.OFF)
                is ClimateTarget.AmbientLight -> ClimateReading.AmbientLight(if(value as Boolean)VehicleLightSwitch.ON else VehicleLightSwitch.OFF)
            }))
        }
        override fun telemetryCapability(signal: VehicleTelemetrySignal,callback: (VehicleReply<VehicleAccess>)->Unit)=error("unexpected")
        override fun readTelemetry(signal: VehicleTelemetrySignal,callback: (VehicleReply<VehicleTelemetryValue?>)->Unit)=error("unexpected")
    }
}
