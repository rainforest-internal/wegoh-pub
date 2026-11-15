package io.wegoh.app.ui

import io.wegoh.app.nativeauth.TripRoutePreviewPlace
import org.junit.Assert.*
import org.junit.Test

class TripRoutePreviewDestinationTest {
    private fun place(name: String)=TripRoutePreviewPlace(name,"course",name)

    @Test fun singleStopIsShownAsDestinationText() {
        assertEquals("목적지 서울역",tripRoutePreviewDestination(listOf(place("서울역"))))
    }
    @Test fun emptyOrMultipleStopsKeepTheRouteStrip() {
        assertNull(tripRoutePreviewDestination(emptyList()))
        assertNull(tripRoutePreviewDestination(listOf(place("경포해변"),place("안목 커피거리"))))
    }
}
