package io.wegoh.app

import org.junit.Assert.*
import org.junit.Test

class VehicleHardwareSessionTest {
    @Test fun healthySessionInitializesOnceAndClosesAtShutdown() {
        val port=Hardware();val session=VehicleHardwareSession(port)
        repeat(5) { assertTrue(session.start() is VehicleReply.Value);session.failed(null) }
        session.failed(VehicleFailure.INVALID_VALUE)
        assertEquals(1,port.initializes)
        assertEquals(0,port.closes)
        session.close();session.close()
        assertEquals(1,port.closes)
        assertEquals(VehicleReply.Failed(VehicleFailure.DISCONNECTED),session.start())
        assertEquals(1,port.initializes)
    }

    @Test fun connectionFailuresInvalidateTheSessionUntilTheNextPoll() {
        for(reason in listOf(VehicleFailure.DISCONNECTED,VehicleFailure.TIMEOUT,VehicleFailure.UNDEFINED)) {
            val port=Hardware();val session=VehicleHardwareSession(port)
            session.start();session.failed(reason);session.failed(reason)
            assertEquals(1,port.initializes)
            assertEquals(1,port.closes)
            session.start();session.start()
            assertEquals(2,port.initializes)
            assertEquals(1,port.closes)
            session.close()
        }
    }

    @Test fun initializationFailureDoesNotMarkTheSessionReady() {
        val port=Hardware();val session=VehicleHardwareSession(port)
        port.result=VehicleReply.Failed(VehicleFailure.DISCONNECTED)
        assertEquals(port.result,session.start())
        port.result=VehicleReply.Value(Unit)
        assertTrue(session.start() is VehicleReply.Value)
        session.start()
        assertEquals(2,port.initializes)
        session.close()
    }

    private class Hardware: VehicleHardwarePort {
        var initializes=0
        var closes=0
        var result: VehicleReply<Unit> = VehicleReply.Value(Unit)
        override fun initialize(): VehicleReply<Unit> { initializes++;return result }
        override fun close() { closes++ }
        override fun climateCapability(property: ClimateProperty,callback: (VehicleReply<ClimateCapability>)->Unit)=error("unexpected capability call")
        override fun readClimate(target: ClimateTarget,capability: ClimateCapability,callback: (VehicleReply<ClimateReading>)->Unit)=error("unexpected getter")
        override fun setClimate(target: ClimateTarget,capability: ClimateCapability,callback: (VehicleReply<Unit>)->Unit)=error("unexpected setter")
        override fun telemetryCapability(signal: VehicleTelemetrySignal,callback: (VehicleReply<VehicleAccess>)->Unit)=error("unexpected telemetry capability")
        override fun readTelemetry(signal: VehicleTelemetrySignal,callback: (VehicleReply<VehicleTelemetryValue?>)->Unit)=error("unexpected telemetry getter")
    }
}
