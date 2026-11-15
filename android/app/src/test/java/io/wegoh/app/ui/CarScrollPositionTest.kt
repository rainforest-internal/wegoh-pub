package io.wegoh.app.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class CarScrollPositionTest {
    @Test fun listThatFitsShowsNoPosition() {
        assertNull(carScrollPositionRange(0,0,1,scrollable=false))
        assertNull(carScrollPositionRange(0,null,0,scrollable=true))
    }

    @Test fun overflowingListShowsVisibleRange() {
        assertEquals(1 to 4,carScrollPositionRange(0,3,10,scrollable=true))
        assertEquals(7 to 10,carScrollPositionRange(6,12,10,scrollable=true))
        assertEquals(3 to 3,carScrollPositionRange(2,null,10,scrollable=true))
    }
}
