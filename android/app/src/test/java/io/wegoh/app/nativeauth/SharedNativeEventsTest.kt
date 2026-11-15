package io.wegoh.app.nativeauth

import java.io.Closeable
import org.junit.Assert.*
import org.junit.Test

class SharedNativeEventsTest {
    private class Attempt(val listener: VehicleEventsListener,val complete: (Result<Closeable>)->Unit) {
        var closed=false
        fun ready(versions: Map<String,String?> = mapOf("devices" to "a".repeat(32))) {
            complete(Result.success(Closeable {closed=true}))
            listener.onEvent(VehicleEvent("snapshot",versions.keys.sorted(),versions))
        }
    }
    private class Subscriber: VehicleEventsListener {
        val events=mutableListOf<VehicleEvent>()
        var lease: Closeable?=null
        var failures=0
        var unavailable=0
        override fun onEvent(event: VehicleEvent) {events.add(event)}
        override fun onUnavailable() {unavailable++}
        fun complete(result: Result<Closeable>) {result.fold(onSuccess={lease=it},onFailure={failures++})}
    }
    private class Fixture {
        val attempts=mutableListOf<Attempt>()
        val posted=ArrayDeque<()->Unit>()
        val shared=SharedNativeEvents({posted.add(it)},{listener,callback->attempts.add(Attempt(listener,callback))})
        fun flush() {while(posted.isNotEmpty())posted.removeFirst()()}
        fun subscribe(subscriber: Subscriber)=shared.subscribe(subscriber,subscriber::complete).also {flush()}
    }
    @Test fun screenReentrySharesOneFeedAndReplaysTheLatestVersions() {
        val f=Fixture();val host=Subscriber();val first=Subscriber()
        f.subscribe(host);f.subscribe(first);assertEquals(1,f.attempts.size)
        assertNull(first.lease);f.attempts[0].ready()
        assertNotNull(first.lease);first.lease!!.close();f.flush()
        assertFalse(f.attempts[0].closed)
        f.attempts[0].listener.onEvent(VehicleEvent("invalidate",listOf("music"),mapOf("music" to "b".repeat(32))))
        f.attempts[0].listener.onEvent(VehicleEvent("invalidate",listOf("music"),mapOf("music" to null)))
        val next=Subscriber();f.subscribe(next)
        assertEquals(1,f.attempts.size);assertNotNull(next.lease)
        assertEquals(mapOf("devices" to "a".repeat(32)),next.events.single().versions)
        assertEquals(1,first.events.size)
        host.lease!!.close();next.lease!!.close();f.flush();assertTrue(f.attempts[0].closed)
    }
    @Test fun resetDropsOldSnapshotLateAdoptionAndQueuedSubscribers() {
        val f=Fixture();val old=Subscriber();f.subscribe(old)
        f.shared.reset();f.flush();assertEquals(1,old.failures)
        val fresh=Subscriber();f.subscribe(fresh)
        f.attempts[0].ready();assertTrue(f.attempts[0].closed);assertNull(fresh.lease)
        f.attempts[1].ready();assertNotNull(fresh.lease);assertEquals(1,fresh.events.size)
        f.shared.reset()
        f.attempts[1].listener.onEvent(VehicleEvent("invalidate",listOf("devices")))
        assertEquals(1,fresh.events.size)
        f.flush();assertEquals(1,fresh.unavailable);assertTrue(f.attempts[1].closed)
    }
    @Test fun failedSharedTransportNotifiesEveryOwnerOnceAndAllowsExplicitReopen() {
        val f=Fixture();val a=Subscriber();val b=Subscriber()
        f.subscribe(a);f.subscribe(b);f.attempts[0].ready()
        f.attempts[0].listener.onUnavailable();f.attempts[0].listener.onClosed()
        assertEquals(1,a.unavailable);assertEquals(1,b.unavailable)
        val next=Subscriber();f.subscribe(next);f.attempts[1].ready()
        a.lease!!.close();f.flush();assertFalse(f.attempts[1].closed);assertNotNull(next.lease)
    }
    @Test fun closingTheLastScreenAndImmediatelyOpeningAnotherDoesNotLoseTheNewSubscriber() {
        val f=Fixture();val old=Subscriber();f.subscribe(old);f.attempts[0].ready()
        old.lease!!.close()
        val next=Subscriber();f.shared.subscribe(next,next::complete);f.flush()
        assertEquals(2,f.attempts.size);f.attempts[0].listener.onUnavailable()
        f.attempts[1].ready();assertNotNull(next.lease);assertEquals(0,next.unavailable)
    }
    @Test fun authorityResetInsideOpenCannotDeliverTheOldPrivateSnapshot() {
        val f=Fixture();var snapshots=0
        f.shared.subscribe(object: VehicleEventsListener {
            override fun onOpen() {f.shared.reset()}
            override fun onEvent(event: VehicleEvent) {snapshots++}
        }) {assertTrue(it.isSuccess)}
        f.flush();f.attempts[0].ready();f.flush();assertEquals(0,snapshots)
    }
}
