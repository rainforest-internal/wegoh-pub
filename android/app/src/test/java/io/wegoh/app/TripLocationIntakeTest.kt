package io.wegoh.app

import org.junit.Assert.*
import org.junit.Test

class TripLocationIntakeTest {
    private val point=TripPosition(37.554,126.9699)

    @Test fun mapAndShareUseOneLocationPolicy() {
        assertNull(tripLocationBlock(foreground=true,consented=true,permitted=true))
        assertEquals("background",tripLocationBlock(foreground=false,consented=true,permitted=true))
        assertEquals("no_consent",tripLocationBlock(foreground=true,consented=false,permitted=true))
        assertEquals("no_permission",tripLocationBlock(foreground=true,consented=true,permitted=false))
    }
    @Test fun consentIsAskedOnceWhenTheOwnActiveTripScreenOpens() {
        fun needed(screen: String?="t",selected: String?="t",declined: Set<String> = emptySet(),setup: Boolean=true,
            storage: Boolean=true,course: Boolean=false,consented: Boolean=false)=
            tripLocationPromptNeeded(screen,selected,declined,setup,storage,course,consented)
        assertTrue(needed())
        assertFalse(needed(consented=true))
        assertFalse(needed(screen=null))
        assertFalse(needed(selected="other"))
        assertFalse(needed(declined=setOf("t")))
        assertTrue(needed(screen="u",selected="u",declined=setOf("t")))
        assertFalse(needed(setup=false))
        assertFalse(needed(storage=false))
        assertFalse(needed(course=true))
    }
    @Test fun freshNewerFixWithoutRecentNaviIsAccepted() {
        assertNull(tripFusedLocationDrop(100_000,95_000,0,0,point))
        assertNull(tripFusedLocationDrop(100_000,85_000,80_000,90_000,point))
    }
    @Test fun eachDropBranchHasItsReason() {
        assertEquals("invalid",tripFusedLocationDrop(100_000,95_000,0,0,TripPosition(Double.NaN,126.0)))
        assertEquals("not_newer",tripFusedLocationDrop(100_000,95_000,95_000,0,point))
        assertEquals("future",tripFusedLocationDrop(100_000,100_001,0,0,point))
        assertEquals("stale",tripFusedLocationDrop(100_000,84_999,0,0,point))
        assertEquals("navi_recent",tripFusedLocationDrop(100_000,99_000,0,95_000,point))
    }
    @Test fun diagnosticsRoundCoordinatesAndLimitEachKind() {
        var now=0L;val lines=mutableListOf<String>()
        val diagnostics=TripLocationDiagnostics({now},write=lines::add)
        diagnostics.accepted("fused",TripPosition(37.55449,126.96991))
        now=1_000;diagnostics.accepted("fused",point)
        diagnostics.dropped("stale",point,"source=fused age_ms=20000")
        now=9_999;diagnostics.dropped("stale",point)
        now=11_000;diagnostics.dropped("stale")
        diagnostics.dropped("blocked_no_consent")
        assertEquals(listOf(
            "trip.vehicle.location: accepted source=fused lat=37.554 lng=126.970",
            "trip.vehicle.location: dropped reason=stale source=fused age_ms=20000 lat=37.554 lng=126.970",
            "trip.vehicle.location: dropped reason=stale",
            "trip.vehicle.location: dropped reason=blocked_no_consent"),lines)
    }
}
