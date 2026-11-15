package io.wegoh.app

import org.junit.Assert.*
import org.junit.Test
import java.io.Closeable

class VehicleControlSupportTest {
    private val front=VehicleSeat.ROW_1_RIGHT
    private fun support(property: ClimateProperty,cap: ClimateCapability)=vehicleControlSupport(property,VehicleReply.Value(cap))
    @Test fun observedTemperatureNeverInventsRearSeatsOrIncrement() {
        val cap=ClimateCapability(VehicleAccess.READ_WRITE,setOf(front),mapOf(front to ClimateBounds(15.0,30.0)))
        val result=support(ClimateProperty.TARGET_CELSIUS,cap)
        assertEquals(listOf("ROW_1_RIGHT"),result.areas.map {it.id})
        assertNull(result.areas.single().step)
        assertEquals(0.5,support(ClimateProperty.TARGET_CELSIUS,cap.copy(celsiusStep=CelsiusStep(15.0,30.0,0.5))).areas.single().step)
        assertEquals(setOf("id","revision","status","available","areas","zones"),result.json().keys().asSequence().toSet())
        assertEquals(0,result.json().getJSONArray("zones").length())
    }
    @Test fun seatsSharingOneSdkAreaAreReportedAsOneZoneInSeatOrder() {
        val rear=ClimateSeatArea(setOf(VehicleSeat.ROW_2_RIGHT,VehicleSeat.ROW_2_LEFT))
        val front=listOf(VehicleSeat.ROW_1_RIGHT,VehicleSeat.ROW_1_CENTER).map {ClimateSeatArea(setOf(it))}
        val seats=rear.seats+front.flatMap {it.seats}
        val fan=support(ClimateProperty.FAN_LEVEL,ClimateCapability(VehicleAccess.READ_WRITE,seats,
            seats.associateWith {ClimateBounds(1.0,8.0)},seatAreas=listOf(rear)+front))
        assertEquals(listOf("ROW_1_CENTER","ROW_1_RIGHT","ROW_2_LEFT","ROW_2_RIGHT"),fan.areas.map {it.id})
        assertEquals(listOf(listOf("ROW_2_LEFT","ROW_2_RIGHT")),fan.zones)
        val zones=fan.json().getJSONArray("zones")
        assertEquals(listOf("ROW_2_LEFT","ROW_2_RIGHT"),(0 until zones.getJSONArray(0).length()).map {zones.getJSONArray(0).getString(it)})
        val heat=support(ClimateProperty.SEAT_HEAT,ClimateCapability(VehicleAccess.READ_WRITE,setOf(VehicleSeat.ROW_1_RIGHT),
            mapOf(VehicleSeat.ROW_1_RIGHT to ClimateBounds(0.0,3.0))))
        assertTrue(heat.zones.isEmpty())
        val window=support(ClimateProperty.WINDOW_POSITION,ClimateCapability(VehicleAccess.READ_WRITE,windows=setOf(VehicleWindow.ROW_1_RIGHT),
            windowBounds=mapOf(VehicleWindow.ROW_1_RIGHT to ClimateBounds(0.0,10.0))))
        assertTrue(window.zones.isEmpty())
    }
    @Test fun driverSeatIsNeverReportedAndSeatZonesWithTheDriverAreOmitted() {
        val driver=VehicleSeat.ROW_1_LEFT
        val cabin=ClimateSeatArea(setOf(VehicleSeat.ROW_2_RIGHT,driver,VehicleSeat.ROW_2_CENTER,VehicleSeat.ROW_1_RIGHT))
        val power=support(ClimateProperty.GLOBAL_POWER,ClimateCapability(VehicleAccess.READ_WRITE,cabin.seats,seatAreas=listOf(cabin)))
        assertTrue(power.available)
        assertEquals(listOf("ROW_1_RIGHT","ROW_2_CENTER","ROW_2_RIGHT"),power.areas.map {it.id})
        assertEquals(listOf(listOf("ROW_1_RIGHT","ROW_2_CENTER","ROW_2_RIGHT")),power.zones)
        val shared=ClimateSeatArea(setOf(driver,VehicleSeat.ROW_2_LEFT))
        val seats=shared.seats+VehicleSeat.ROW_1_RIGHT
        val bounds=seats.associateWith {ClimateBounds(15.0,30.0)}
        val temperature=support(ClimateProperty.TARGET_CELSIUS,ClimateCapability(VehicleAccess.READ_WRITE,seats,bounds,
            seatAreas=listOf(shared,ClimateSeatArea(setOf(VehicleSeat.ROW_1_RIGHT)))))
        assertEquals(listOf("ROW_1_RIGHT"),temperature.areas.map {it.id})
        assertTrue(temperature.zones.isEmpty())
        // Fan, AC and air cleaner write the whole SDK area, so a front zone with the driver is never offered.
        val front=ClimateSeatArea(setOf(driver,VehicleSeat.ROW_1_RIGHT))
        val rear=ClimateSeatArea(setOf(VehicleSeat.ROW_2_LEFT,VehicleSeat.ROW_2_RIGHT))
        val zoned=front.seats+rear.seats
        for(property in listOf(ClimateProperty.FAN_LEVEL,ClimateProperty.AC,ClimateProperty.AIR_CLEANER)) {
            val result=support(property,ClimateCapability(VehicleAccess.READ_WRITE,zoned,
                zoned.associateWith {ClimateBounds(1.0,8.0)},seatAreas=listOf(front,rear)))
            assertEquals(property.name,listOf("ROW_2_LEFT","ROW_2_RIGHT"),result.areas.map {it.id})
            assertEquals(property.name,listOf(listOf("ROW_2_LEFT","ROW_2_RIGHT")),result.zones)
        }
        val driverOnly=support(ClimateProperty.SEAT_HEAT,ClimateCapability(VehicleAccess.READ_WRITE,setOf(driver),
            mapOf(driver to ClimateBounds(0.0,3.0))))
        assertEquals("known",driverOnly.status);assertFalse(driverOnly.available)
        val lights=support(ClimateProperty.READING_LIGHT,ClimateCapability(VehicleAccess.READ_WRITE,setOf(driver,VehicleSeat.ROW_1_RIGHT),
            seatLightSwitches=setOf(driver,VehicleSeat.ROW_1_RIGHT).associateWith {setOf(VehicleLightSwitch.OFF,VehicleLightSwitch.ON)}))
        assertEquals(listOf("ROW_1_RIGHT"),lights.areas.map {it.id})
        val window=support(ClimateProperty.WINDOW_POSITION,ClimateCapability(VehicleAccess.READ_WRITE,
            windows=setOf(VehicleWindow.ROW_1_LEFT,VehicleWindow.ROW_2_LEFT),
            windowBounds=mapOf(VehicleWindow.ROW_1_LEFT to ClimateBounds(0.0,10.0),VehicleWindow.ROW_2_LEFT to ClimateBounds(0.0,10.0))))
        assertEquals(listOf("ROW_2_LEFT"),window.areas.map {it.id})
        val driverWindow=support(ClimateProperty.WINDOW_POSITION,ClimateCapability(VehicleAccess.READ_WRITE,
            windows=setOf(VehicleWindow.ROW_1_LEFT),windowBounds=mapOf(VehicleWindow.ROW_1_LEFT to ClimateBounds(0.0,10.0))))
        assertEquals("known",driverWindow.status);assertFalse(driverWindow.available)
    }
    @Test fun anOverlappingSdkAreaCannotBecomeASingleSeatOrASmallerZone() {
        val left=VehicleSeat.ROW_2_LEFT
        val right=VehicleSeat.ROW_2_RIGHT
        for(seats in listOf(setOf(left,right),setOf(left,VehicleSeat.ROW_2_CENTER,right))) {
            val front=ClimateSeatArea(seats)
            val capability=ClimateCapability(VehicleAccess.READ_WRITE,seats,
                seatAreas=listOf(front,ClimateSeatArea(setOf(left))))
            // The SDK still uses the whole front area for the unambiguous right seat.
            assertNull(capability.area(left))
            assertSame(front,capability.area(right))
            val result=support(ClimateProperty.GLOBAL_POWER,capability)
            assertFalse(result.available)
            assertTrue(result.areas.isEmpty())
            assertTrue(result.zones.isEmpty())
        }
    }
    @Test fun incompleteGroupsAreOmittedWhileIndependentAndCompleteGroupsStayAvailable() {
        val left=VehicleSeat.ROW_1_CENTER
        val right=VehicleSeat.ROW_1_RIGHT
        val rearLeft=VehicleSeat.ROW_2_LEFT
        val rearRight=VehicleSeat.ROW_2_RIGHT
        val standalone=VehicleSeat.ROW_3_LEFT
        val seats=setOf(left,right,rearLeft,rearRight,standalone)
        val capability=ClimateCapability(VehicleAccess.READ_WRITE,seats,
            bounds=(seats-left).associateWith {ClimateBounds(1.0,8.0)},
            seatAreas=listOf(ClimateSeatArea(setOf(left,right)),ClimateSeatArea(setOf(rearLeft,rearRight)),
                ClimateSeatArea(setOf(standalone))))
        val result=support(ClimateProperty.FAN_LEVEL,capability)
        assertTrue(result.available)
        assertEquals(listOf(rearLeft.name,rearRight.name,standalone.name),result.areas.map {it.id})
        assertEquals(listOf(listOf(rearLeft.name,rearRight.name)),result.zones)
    }
    @Test fun unsupportedAndUnobservedAreDifferent() {
        val unknown=vehicleControlSupport(ClimateProperty.FAN_LEVEL,VehicleReply.Failed(VehicleFailure.TIMEOUT))
        val unsupported=vehicleControlSupport(ClimateProperty.FAN_LEVEL,VehicleReply.Failed(VehicleFailure.UNSUPPORTED_PROPERTY))
        assertEquals("unknown",unknown.status);assertFalse(unknown.available);assertTrue(unknown.areas.isEmpty())
        assertEquals("known",unsupported.status);assertFalse(unsupported.available)
        assertEquals("unknown",support(ClimateProperty.FAN_LEVEL,ClimateCapability(VehicleAccess.READ_WRITE,setOf(front))).status)
    }
    @Test fun numericBoundsRespectActualSupportAndCommandDomain() {
        val cap=ClimateCapability(VehicleAccess.READ_WRITE,setOf(front),mapOf(front to ClimateBounds(-3.0,3.0)))
        val area=support(ClimateProperty.SEAT_HEAT,cap).areas.single()
        assertEquals(VehicleControlArea("ROW_1_RIGHT",0.0,3.0,1.0),area)
        val readOnly=support(ClimateProperty.SEAT_HEAT,cap.copy(access=VehicleAccess.READ))
        assertFalse(readOnly.available)
    }
    @Test fun windowMetadataUsesExistingNormalizedPercentContract() {
        val cap=ClimateCapability(VehicleAccess.READ_WRITE,windows=setOf(VehicleWindow.ROW_2_RIGHT),
            windowBounds=mapOf(VehicleWindow.ROW_2_RIGHT to ClimateBounds(0.0,10.0)))
        assertEquals(VehicleControlArea("ROW_2_RIGHT",0.0,100.0,1.0),support(ClimateProperty.WINDOW_POSITION,cap).areas.single())
    }
    @Test fun cabinLightCanBeSupportedWithoutAreasAndSeatedLightsNeedBothSwitches() {
        val cap=ClimateCapability(VehicleAccess.READ_WRITE,lightSwitches=setOf(VehicleLightSwitch.ON,VehicleLightSwitch.OFF))
        val cabin=support(ClimateProperty.CABIN_LIGHT,cap)
        assertEquals("known",cabin.status);assertTrue(cabin.available);assertTrue(cabin.areas.isEmpty())
        val reading=support(ClimateProperty.READING_LIGHT,cap.copy(areas=setOf(front),seatLightSwitches=mapOf(front to setOf(VehicleLightSwitch.ON))))
        assertFalse(reading.available)
    }
    @Test fun reportsReadOnlyCapabilitiesAndHeartbeatWithoutBlockingCommandExecution() {
        val lane=Lane();val ports=mutableListOf<Port>();val channels=mutableListOf<Transport>()
        val reporter=VehicleControlSupportReporter({Port().also {ports+=it}},{Transport().also {channels+=it}},lane,{})
        reporter.setActive(true)
        assertEquals(11,channels.single().reports.single().size)
        assertTrue(ports.single().closed);assertTrue(channels.single().closed)
        lane.advance(29_999);assertEquals(1,channels.size)
        lane.advance(1);assertEquals(2,channels.size)
        reporter.setActive(false);lane.advance(60_000);assertEquals(2,channels.size)
        reporter.close()
    }
    @Test fun pauseAndRevocationCancelDelayedCallbacksAndNeverPublishStaleMetadata() {
        val lane=Lane();val port=Port(deferred=true);val channel=Transport()
        val reporter=VehicleControlSupportReporter({port},{channel},lane,{})
        reporter.setActive(true);assertNotNull(port.callback)
        reporter.setActive(false);assertTrue(port.closed);assertTrue(channel.closed)
        port.callback!!(VehicleReply.Value(ClimateCapability(VehicleAccess.READ_WRITE)))
        lane.advance(60_000);assertTrue(channel.reports.isEmpty())
    }
    @Test fun timeoutRemainsUnknownAndFailedPublicationRetriesOnNextHeartbeat() {
        val lane=Lane();val channels=mutableListOf<Transport>()
        val reporter=VehicleControlSupportReporter({Port(deferred=true)},{Transport(success=false).also {channels+=it}},lane,{})
        reporter.setActive(true);lane.advance(33_000)
        assertTrue(channels.single().reports.single().all {it.status=="unknown" && !it.available})
        lane.advance(30_000);assertEquals(2,channels.size)
        reporter.close()
    }
    @Test fun authorizationInvalidationImmediatelyClosesCapabilitySessionAndIgnoresLateReply() {
        val lane=Lane();val port=Port(deferred=true);val channel=Transport()
        val reporter=VehicleControlSupportReporter({port},{channel},lane,{})
        reporter.setActive(true)
        channel.invalidate!!()
        assertTrue(port.closed);assertTrue(channel.closed)
        port.callback!!(VehicleReply.Failed(VehicleFailure.UNSUPPORTED_PROPERTY))
        assertTrue(channel.reports.isEmpty())
        reporter.setActive(false);lane.advance(60_000);assertTrue(channel.reports.isEmpty())
    }
    @Test fun transportExceptionDoesNotEscapeTheReporterOrAffectOtherWorkers() {
        val lane=Lane();val channel=Transport(throwOnPublish=true)
        val reporter=VehicleControlSupportReporter({Port()},{channel},lane,{})
        reporter.setActive(true)
        assertTrue(channel.closed)
        var commandWorkerRan=false;lane.dispatch {commandWorkerRan=true}
        assertTrue(commandWorkerRan)
        reporter.close()
    }
    private class Port(private val deferred: Boolean=false): VehicleHardwarePort {
        var closed=false;var callback: ((VehicleReply<ClimateCapability>)->Unit)?=null
        override fun initialize()=VehicleReply.Value(Unit)
        override fun climateCapability(property: ClimateProperty,callback: (VehicleReply<ClimateCapability>)->Unit) {
            this.callback=callback
            if(!deferred)callback(VehicleReply.Failed(VehicleFailure.UNSUPPORTED_PROPERTY))
        }
        override fun readClimate(target: ClimateTarget,capability: ClimateCapability,callback: (VehicleReply<ClimateReading>)->Unit)=error("Support reporter must not read current vehicle values")
        override fun setClimate(target: ClimateTarget,capability: ClimateCapability,callback: (VehicleReply<Unit>)->Unit)=error("Support reporter must not write vehicle values")
        override fun telemetryCapability(signal: VehicleTelemetrySignal,callback: (VehicleReply<VehicleAccess>)->Unit)=error("Unrelated vehicle signal")
        override fun readTelemetry(signal: VehicleTelemetrySignal,callback: (VehicleReply<VehicleTelemetryValue?>)->Unit)=error("Unrelated vehicle signal")
        override fun close() {closed=true}
    }
    private class Transport(val success: Boolean=true,val throwOnPublish: Boolean=false): VehicleControlSupportTransport {
        var invalidate: (()->Unit)?=null
        val reports=mutableListOf<List<VehicleControlSupport>>();var closed=false
        override fun open(onInvalidated: ()->Unit,callback: (Result<Unit>)->Unit) {invalidate=onInvalidated;callback(Result.success(Unit))}
        override fun publish(actions: List<VehicleControlSupport>,callback: (Result<Unit>)->Unit): Closeable {
            if(throwOnPublish)throw IllegalStateException("transport unavailable")
            reports+=actions;callback(if(success)Result.success(Unit) else Result.failure(IllegalStateException("offline")))
            return Closeable {}
        }
        override fun close() {closed=true}
    }
    private class Lane: VehicleOperationLane {
        var now=0L
        private data class Task(val at: Long,val action: ()->Unit,var cancelled: Boolean=false)
        private val tasks=mutableListOf<Task>()
        override fun dispatch(block: ()->Unit)=block()
        override fun nowElapsedMillis()=now
        override fun schedule(delayMillis: Long,block: ()->Unit): VehicleCancellation {
            val task=Task(now+delayMillis,block);tasks+=task
            return VehicleCancellation {task.cancelled=true}
        }
        fun advance(millis: Long) {
            val until=now+millis
            while(true) {
                val next=tasks.filter {!it.cancelled && it.at<=until}.minByOrNull {it.at} ?: break
                tasks.remove(next);now=next.at;next.action()
            }
            now=until
        }
    }
}
