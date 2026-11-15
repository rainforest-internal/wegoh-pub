package io.wegoh.app.ui

import org.junit.Assert.assertEquals
import org.junit.Test

class TripSignalCountdownTest {
    @Test fun personalAndGroupSignalsShareTheSameCountdownCopy() {
        assertEquals(15,TRIP_SIGNAL_AUTO_CLOSE_SECONDS)
        assertEquals("15초 뒤 닫혀요",tripSignalCloseLabel(TRIP_SIGNAL_AUTO_CLOSE_SECONDS))
        assertEquals("3초 뒤 닫혀요",tripSignalCloseLabel(3))
    }
}
