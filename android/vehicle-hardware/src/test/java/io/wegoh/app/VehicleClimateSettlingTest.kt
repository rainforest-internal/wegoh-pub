package io.wegoh.app

import org.junit.Assert.*
import org.junit.Test

class VehicleClimateSettlingTest {
    @Test fun delayedAirCleanerStateConfirmsWithoutRepeatingSetter() {
        val h=Harness()
        h.port.reading={ ClimateReading.AirCleaner(h.lane.now>=2_500) }
        h.start()
        h.lane.advance(3_000)
        assertEquals(VehicleCommandState.TARGET_CONFIRMED,h.results.single().state)
        assertEquals(1,h.port.setters)
        assertTrue(h.port.reads>5)
    }

    @Test fun permanentMismatchStopsWithoutRepeatingSetterOrInventingSuccess() {
        val h=Harness();h.start();h.lane.advance(5_000)
        assertEquals(VehicleFailure.MISMATCH,h.results.single().reason)
        assertEquals(VehicleCommandState.UNKNOWN,h.results.single().state)
        assertTrue(h.results.single().mayHaveExecuted)
        assertEquals(1,h.port.setters)
        assertTrue(h.port.reads in 2..17)
        assertTrue(h.lane.jobs.all { it.cancelled })
    }

    @Test fun shortLeaseIsNeverExtendedBySettling() {
        val h=Harness(expires=600)
        h.port.reading={ ClimateReading.AirCleaner(h.lane.now>=750) }
        h.start();h.lane.advance(3_000)
        assertEquals(VehicleFailure.TIMEOUT,h.results.single().reason)
        assertEquals(1,h.port.setters)
        assertEquals(3,h.port.reads)
    }

    @Test fun authorityWithdrawalStopsScheduledReads() {
        val h=Harness();h.start()
        h.authority=h.authority.copy(currentLease=null)
        h.executor.authorityChanged();h.lane.advance(5_000)
        assertEquals(VehicleFailure.EXPIRED_AUTHORITY,h.results.single().reason)
        assertEquals(1,h.port.reads)
        assertEquals(1,h.port.setters)
    }

    @Test fun scheduledReadAlsoRechecksAuthorityWithoutAnExplicitNotification() {
        val h=Harness();h.start()
        h.authority=h.authority.copy(currentLease=null)
        h.lane.advance(250)
        assertEquals(VehicleFailure.EXPIRED_AUTHORITY,h.results.single().reason)
        assertEquals(1,h.port.reads)
    }

    @Test fun duplicateOrLateGetterCannotSpawnReadsOrConfirmAnOldAttempt() {
        val h=Harness()
        val replies=mutableListOf<(VehicleReply<ClimateReading>)->Unit>()
        h.port.onRead={ replies+=it }
        h.start()
        val first=replies.single()
        repeat(2) { first(VehicleReply.Value(ClimateReading.AirCleaner(false))) }
        h.lane.advance(250)
        assertEquals(2,h.port.reads)
        first(VehicleReply.Value(ClimateReading.AirCleaner(true)))
        assertTrue(h.results.isEmpty())
        replies.last()(VehicleReply.Value(ClimateReading.AirCleaner(true)))
        h.lane.advance(5_000)
        assertEquals(VehicleCommandState.TARGET_CONFIRMED,h.results.single().state)
        assertEquals(2,h.port.reads)
        assertEquals(1,h.port.setters)
    }

    @Test fun closingCancelsQueuedReads() {
        val h=Harness();h.start();h.executor.close();h.lane.advance(5_000)
        assertEquals(VehicleFailure.CANCELLED,h.results.single().reason)
        assertEquals(1,h.port.reads)
        assertTrue(h.lane.jobs.all { it.cancelled })
    }

    @Test fun getterFailureIsNotRetriedAsACommand() {
        val h=Harness();h.port.onRead={ it(VehicleReply.Failed(VehicleFailure.PERMISSION)) }
        h.start();h.lane.advance(5_000)
        assertEquals(VehicleFailure.PERMISSION,h.results.single().reason)
        assertEquals(1,h.port.reads)
        assertEquals(1,h.port.setters)
    }

    @Test fun immediateMatchingGetterDoesNotWaitForTheSettlingWindow() {
        val h=Harness();h.port.reading={ ClimateReading.AirCleaner(true) };h.start()
        assertEquals(VehicleCommandState.TARGET_CONFIRMED,h.results.single().state)
        assertEquals(0L,h.results.single().readbackReceivedAtElapsedMillis)
        assertEquals(1,h.port.reads)
        assertTrue(h.lane.jobs.all { it.cancelled })
    }

    private class Lane: VehicleOperationLane {
        data class Job(val at: Long,val run: ()->Unit,var cancelled: Boolean=false)
        var now=0L
        val jobs=mutableListOf<Job>()
        override fun dispatch(block: ()->Unit)=block()
        override fun nowElapsedMillis()=now
        override fun schedule(delayMillis: Long,block: ()->Unit): VehicleCancellation {
            val job=Job(now+delayMillis,block);jobs+=job
            return VehicleCancellation { job.cancelled=true }
        }
        fun advance(delta: Long) {
            val until=now+delta
            while(true) {
                val next=jobs.filter { !it.cancelled && it.at<=until }.minByOrNull { it.at } ?: break
                now=next.at;next.cancelled=true;next.run()
            }
            now=until
        }
    }
    private class Port: VehicleHardwarePort {
        var setters=0;var reads=0
        var reading: ()->ClimateReading={ ClimateReading.AirCleaner(false) }
        var onRead: (((VehicleReply<ClimateReading>)->Unit)->Unit)?=null
        override fun initialize()=VehicleReply.Value(Unit)
        override fun close() {}
        override fun climateCapability(property: ClimateProperty,callback: (VehicleReply<ClimateCapability>)->Unit) {
            callback(VehicleReply.Value(ClimateCapability(VehicleAccess.READ_WRITE,setOf(VehicleSeat.ROW_1_RIGHT))))
        }
        override fun setClimate(target: ClimateTarget,capability: ClimateCapability,callback: (VehicleReply<Unit>)->Unit) {
            setters++;callback(VehicleReply.Value(Unit))
        }
        override fun readClimate(target: ClimateTarget,capability: ClimateCapability,callback: (VehicleReply<ClimateReading>)->Unit) {
            reads++;onRead?.invoke(callback) ?: callback(VehicleReply.Value(reading()))
        }
        override fun telemetryCapability(signal: VehicleTelemetrySignal,callback: (VehicleReply<VehicleAccess>)->Unit)=error("unused")
        override fun readTelemetry(signal: VehicleTelemetrySignal,callback: (VehicleReply<VehicleTelemetryValue?>)->Unit)=error("unused")
    }
    private class Harness(val expires: Long=10_000) {
        val lane=Lane();val port=Port()
        val lease=VehicleCommandLease("request","owner","device","grant","purpose","lease","hvac.air_cleaner","1",1,expires)
        var authority=VehicleCommandAuthority(lease,true,true,true,true,false)
        val results=mutableListOf<VehicleCommandOutcome>()
        val executor=VehicleClimateCommandExecutor(port,lane,{authority},mapOf(ClimateProperty.AIR_CLEANER to TrustedClimateAction("hvac.air_cleaner","1")))
        fun start()=executor.execute(lease,ClimateTarget.AirCleaner(VehicleSeat.ROW_1_RIGHT,true),callback={results+=it})
    }
}
