package io.wegoh.app.nativeauth

import java.io.Closeable
import org.junit.Assert.*
import org.junit.Test

class NativeEventRotationTest {
    @Test fun unchangedVersionsAfterRotationEmitNoBusinessInvalidationAndMissedChangesAreRecovered() {
        val f=Fixture();f.rotation.start()
        val key="trip."+"a".repeat(32)+".location"
        fun ready(index: Int,versions: Map<String,String?>) {
            f.attempts[index].listener.onEvent(VehicleEvent("snapshot",versions.keys.sorted(),versions))
            f.attempts[index].handle()
        }
        val baseline=mapOf("devices" to "1".repeat(32),key to "2".repeat(32))
        ready(0,baseline);f.events.clear()
        f.attempts[0].listener.onClosed(1008);ready(1,baseline)
        assertTrue(f.events.isEmpty())
        f.attempts[1].listener.onEvent(VehicleEvent("invalidate",listOf(key),mapOf(key to "3".repeat(32))))
        f.events.clear()
        f.attempts[1].listener.onClosed(1008);ready(2,baseline+mapOf(key to "3".repeat(32)))
        assertTrue(f.events.isEmpty())
        f.attempts[2].listener.onClosed(1008);ready(3,baseline)
        assertEquals(listOf(key),f.events.single().resources)
        f.events.clear()
        f.attempts[3].listener.onClosed(1008);ready(4,mapOf("devices" to "1".repeat(32)))
        assertEquals(mapOf(key to null),f.events.single().versions)
        f.rotation.close()
    }
    private class Attempt(val quiet: Boolean,val listener: VehicleEventsListener,val complete: (Result<Closeable>)->Unit) {
        var released=false
        fun handle()=complete(Result.success(Closeable {released=true}))
        fun snapshot()=listener.onEvent(VehicleEvent("snapshot",listOf("devices")))
        fun ready() {snapshot();handle()}
        fun fail()=complete(Result.failure(NativeEventsFailure(NativeEventsFailure.Kind.TRANSPORT)))
    }
    private class Fixture {
        var current=true
        var available=false
        var completed=0
        var unavailable=0
        var ended=0
        val attempts=mutableListOf<Attempt>()
        val logs=mutableListOf<String>()
        val events=mutableListOf<VehicleEvent>()
        val timeouts=mutableListOf<()->Unit>()
        val rotation=NativeEventRotation({current},{quiet,listener,reply->attempts.add(Attempt(quiet,listener,reply))},
            {task->timeouts.add(task);Closeable {}},object: VehicleEventsListener {
                override fun onEvent(event: VehicleEvent) {events.add(event)}
                override fun onUnavailable() {unavailable++;available=false}
                override fun onClosed() {ended++;available=false}
            },{completed++;available=it.isSuccess},logs::add)
        fun start() {rotation.start();attempts.single().ready()}
    }
    @Test fun initialConnectionRequiresHandleAndSnapshot() {
        val f=Fixture();f.rotation.start();f.attempts[0].handle()
        assertEquals(0,f.completed)
        f.attempts[0].snapshot()
        assertEquals(1,f.completed);assertTrue(f.available)
        assertEquals("snapshot",f.events.single().type)
        f.rotation.close()
    }
    @Test fun serverRotationPreservesAvailabilityUntilFreshSnapshotAndLogsOnlyReconnect() {
        val f=Fixture();f.start()
        f.attempts[0].listener.onClosed(1008)
        assertEquals(2,f.attempts.size);assertTrue(f.attempts[1].quiet)
        assertTrue(f.available);assertEquals(0,f.unavailable);assertEquals(0,f.ended);assertTrue(f.logs.isEmpty())
        f.attempts[1].handle()
        assertTrue(f.logs.isEmpty())
        f.attempts[1].snapshot()
        assertEquals(listOf("native.events: reconnected reason=server_rotation"),f.logs)
        assertEquals(1,f.completed);assertTrue(f.available)
        f.rotation.close()
    }
    @Test fun onlyTwoConsecutiveReconnectFailuresReportUnavailable() {
        val f=Fixture();f.start();f.attempts[0].listener.onClosed(1008)
        f.attempts[1].fail()
        assertEquals(3,f.attempts.size);assertTrue(f.available);assertEquals(0,f.unavailable);assertTrue(f.logs.isEmpty())
        f.attempts[2].fail()
        assertEquals(1,f.unavailable);assertFalse(f.available);assertEquals(3,f.attempts.size)
        assertTrue(f.logs.single().startsWith("native.events: reconnect failed"))
    }
    @Test fun successfulReconnectResetsFailureBudgetForNextRotation() {
        val f=Fixture();f.start();f.attempts[0].listener.onClosed(1008)
        f.attempts[1].fail();f.attempts[2].ready()
        f.attempts[2].listener.onClosed(1008)
        f.attempts[3].fail();assertEquals(0,f.unavailable)
        f.attempts[4].ready()
        assertEquals(2,f.logs.size);assertTrue(f.available)
        f.rotation.close()
    }
    @Test fun missingReconnectSnapshotsTimeOutTwiceThenFail() {
        val f=Fixture();f.start();f.attempts[0].listener.onClosed(1008)
        f.attempts[1].handle();f.timeouts[1]()
        assertEquals(0,f.unavailable)
        f.attempts[2].handle();f.timeouts[2]()
        assertEquals(1,f.unavailable)
    }
    @Test fun closingWhileReconnectingDisposesLateSocketWithoutPublishingIt() {
        val f=Fixture();f.start();f.attempts[0].listener.onClosed(1008)
        f.rotation.close();f.attempts[1].ready()
        assertTrue(f.attempts[1].released);assertEquals(1,f.completed);assertTrue(f.logs.isEmpty())
    }
    @Test fun revokedBoundaryDoesNotReconnectOrRetainAvailability() {
        val f=Fixture();f.start();f.current=false;f.attempts[0].listener.onClosed(1008)
        assertEquals(1,f.attempts.size);assertFalse(f.available);assertEquals(1,f.unavailable)
    }
    @Test fun otherCloseCodesKeepExistingCloseBehavior() {
        val f=Fixture();f.start();f.attempts[0].listener.onClosed(1000)
        assertEquals(1,f.ended);assertEquals(1,f.attempts.size);assertFalse(f.available)
    }
    @Test fun authorityClosureDoesNotEnterTheRotationRetryWindow() {
        val f=Fixture();f.start();f.attempts[0].listener.onClosed(4003)
        assertEquals(1,f.ended);assertEquals(1,f.attempts.size);assertFalse(f.available)
        assertTrue(f.logs.isEmpty())
    }
}
