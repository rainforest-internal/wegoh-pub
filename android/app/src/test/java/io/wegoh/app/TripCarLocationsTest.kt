package io.wegoh.app

import io.wegoh.app.nativeauth.TripCarPosition
import io.wegoh.app.nativeauth.TripLocationShare
import io.wegoh.app.nativeauth.TripLocationTransport
import org.junit.Assert.*
import org.junit.Test
import java.io.Closeable

class TripCarLocationsTest {
    private class Transport: TripLocationTransport {
        val reads=ArrayDeque<Pair<String,(Result<TripLocationShare>)->Unit>>()
        var closedReads=0
        override fun readCarLocations(id: String,callback: (Result<TripLocationShare>)->Unit): Closeable {
            reads.add(id to callback);return Closeable {closedReads++}
        }
    }
    private class Timer {
        val pending=ArrayDeque<Pair<Long,()->Unit>>()
        var cancelled=0
        fun schedule(delay: Long,action: ()->Unit): Closeable {val entry=delay to action;pending.add(entry);return Closeable {if(pending.remove(entry))cancelled++}}
        fun fire()=pending.removeFirst().second()
    }
    private val car=TripCarPosition("c".repeat(32),37.5,127.0,"vehicle",1_000)

    @Test fun pollsEveryIntervalAndClearsPositionsWhenAReadFails() {
        val transport=Transport();val timer=Timer();val published=mutableListOf<List<TripCarPosition>>()
        val watcher=TripCarLocations({published+=it},timer::schedule)
        watcher.update("trip",transport)
        transport.reads.removeFirst().second(Result.success(TripLocationShare("trip",null,listOf(car))))
        assertEquals(listOf(listOf(car)),published)
        assertEquals(TRIP_CAR_LOCATION_INTERVAL_MILLIS,timer.pending.single().first)
        timer.fire()
        transport.reads.removeFirst().second(Result.failure(java.io.IOException()))
        assertEquals(emptyList<TripCarPosition>(),published.last())
        timer.fire()
        transport.reads.removeFirst().second(Result.success(TripLocationShare("other",null,listOf(car))))
        assertEquals(emptyList<TripCarPosition>(),published.last())
        assertEquals(1,timer.pending.size)
    }

    @Test fun closingOrSwitchingTripsStopsReadsAndIgnoresLateReplies() {
        val transport=Transport();val timer=Timer();val published=mutableListOf<List<TripCarPosition>>()
        val watcher=TripCarLocations({published+=it},timer::schedule)
        watcher.update("trip",transport)
        val late=transport.reads.removeFirst().second
        watcher.update("trip",transport)
        assertTrue(transport.reads.isEmpty())
        watcher.update("next",transport)
        assertEquals(1,transport.closedReads)
        late(Result.success(TripLocationShare("trip",null,listOf(car))))
        assertEquals(listOf(emptyList<TripCarPosition>()),published)
        transport.reads.removeFirst().second(Result.success(TripLocationShare("next",null,listOf(car))))
        watcher.close()
        assertEquals(1,timer.cancelled)
        assertEquals(emptyList<TripCarPosition>(),published.last())
        assertTrue(timer.pending.isEmpty())
        watcher.update(null,null)
        assertTrue(transport.reads.isEmpty())
    }
}
