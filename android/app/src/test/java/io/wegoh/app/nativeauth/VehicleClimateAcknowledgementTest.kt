package io.wegoh.app.nativeauth

import java.io.Closeable
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class VehicleClimateAcknowledgementTest {
    @Test fun socketRotationPreservesPendingAndRemainingAcknowledgements() {
        val h=Harness();val claim=h.claim()
        val completed=mutableListOf<Result<Unit>>()
        h.transport.ack(claim,"sdk-accepted",JSONObject()) {completed+=it}
        h.events.lost()
        assertEquals(0,h.invalidations)
        assertFalse(h.transport.current())
        assertTrue(h.transport.current(claim))
        h.replies.complete(Unit)
        h.transport.ack(claim,"state-confirmed",JSONObject()) {completed+=it}
        h.replies.complete(Unit)
        assertEquals(2,completed.size)
        assertTrue(completed.all {it.isSuccess})
        assertTrue(h.replies.requests.all {it.climateAcknowledgement && it.mutation})
        assertFalse(h.events.requests.any {it.climateAcknowledgement})
    }

    @Test fun devicesInvalidationStillClosesClaimAcknowledgements() {
        val h=Harness();val claim=h.claim()
        h.transport.ack(claim,"sdk-accepted",JSONObject()) {}
        h.events.observer.onResourcesChanged(setOf("devices"))
        assertEquals(1,h.invalidations)
        assertTrue(h.replies.closed)
        assertFalse(h.transport.current(claim))
        val calls=h.replies.requests.size
        h.transport.ack(claim,"state-confirmed",JSONObject()) {assertTrue(it.isFailure)}
        assertEquals(calls,h.replies.requests.size)
        assertFalse(h.events.ready())
        h.transport.open({h.invalidations++}) {assertTrue(it.isSuccess)}
        assertTrue(h.transport.current())
    }

    @Test fun acknowledgementAuthorityLossStopsTheClaimEvenWithoutAnEventSocket() {
        val h=Harness();val claim=h.claim();h.events.lost()
        h.replies.invalidate()
        assertEquals(1,h.invalidations)
        assertFalse(h.transport.current(claim))
    }

    @Test fun expiredLeaseAndChangedAccountBoundaryCannotSendAnotherAck() {
        for(expired in listOf(true,false)) {
            val h=Harness();val claim=h.claim();h.events.lost()
            if(expired)h.now=claim.deadlineElapsedMillis else h.base=false
            h.transport.ack(claim,"state-confirmed",JSONObject()) {assertTrue(it.isFailure)}
            assertTrue(h.replies.requests.isEmpty())
        }
    }

    @Test fun releasingAClaimClosesOnlyItsRestChannel() {
        val h=Harness();val claim=h.claim();h.transport.release(claim)
        assertTrue(h.replies.closed)
        assertFalse(h.events.closed)
        assertTrue(h.transport.current())
        assertFalse(h.transport.current(claim))
    }

    @Test fun socketLossBeforeClaimAdoptionDoesNotRetainAuthority() {
        val h=Harness();var result: Result<VehicleClimateNativeTransport.Claim>?=null
        h.transport.claim("a".repeat(32)) {result=it}
        h.events.lost();h.events.complete(h.value)
        assertEquals(1,h.invalidations)
        assertTrue(checkNotNull(result).isFailure)
        assertFalse(h.replies.ready())
    }

    private class Harness {
        val events=Client();val replies=Client()
        var now=100L;var base=true;var invalidations=0
        val transport=VehicleClimateNativeTransport(events,{replies},{1L},{base},{now},{})
        val value=VehicleClimateNativeTransport.Claim("a".repeat(32),"owner","device","grant","hvac.ac",1,"lease",JSONObject(),10_000,1)
        init {transport.open({invalidations++}) {assertTrue(it.isSuccess)}}
        fun claim(): VehicleClimateNativeTransport.Claim {
            var claimed: VehicleClimateNativeTransport.Claim?=null
            transport.claim(value.id) {claimed=it.getOrThrow()};events.complete(value)
            return checkNotNull(claimed)
        }
    }
    private class Client: VehicleClimateClient {
        lateinit var observer: NativeSocialObserver
        var closed=false
        private var active=false
        private var completion: ((Any)->Unit)?=null
        val requests=mutableListOf<NativeSocialRequest<*>>()
        override fun ready()=active && !closed
        override fun open(observer: NativeSocialObserver,callback: (Result<Unit>)->Unit) {
            this.observer=observer;active=true;callback(Result.success(Unit))
        }
        override fun adopt(epoch: Long,remainingMillis: Long,observer: NativeSocialObserver) {this.observer=observer;active=true}
        override fun <T> call(request: NativeSocialRequest<T>,callback: (Result<T>)->Unit): Closeable {
            check(ready());requests+=request
            @Suppress("UNCHECKED_CAST")
            val reply: (Any)->Unit={callback(Result.success(it as T))}
            completion=reply;return Closeable {completion=null}
        }
        fun complete(value: Any) {val callback=completion;completion=null;checkNotNull(callback).invoke(value)}
        fun lost() {active=false;observer.onConnectionLost()}
        override fun invalidate() {active=false;observer.onInvalidated()}
        override fun close() {closed=true;active=false;completion=null}
    }
}
