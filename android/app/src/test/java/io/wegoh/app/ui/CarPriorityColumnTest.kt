package io.wegoh.app.ui

import org.junit.Assert.assertEquals
import org.junit.Test

class CarPriorityColumnTest {
    @Test fun optionalRowsAreKeptOnlyWhileTheyFitCompletely() {
        // title 100 + map 220 with a 16 gap leaves room for one 60 strip within 420, not the 80 companion row too.
        assertEquals(1,carPriorityOptionalCount(listOf(100,220),listOf(60,80),gap=16,maxHeight=420))
        assertEquals(2,carPriorityOptionalCount(listOf(100,220),listOf(60,80),gap=16,maxHeight=508))
        assertEquals(0,carPriorityOptionalCount(listOf(100,220),listOf(60,80),gap=16,maxHeight=395))
    }

    @Test fun aLaterRowNeverReplacesAnEarlierOneThatDidNotFit() {
        assertEquals(0,carPriorityOptionalCount(listOf(100),listOf(500,10),gap=16,maxHeight=300))
    }

    @Test fun unboundedHeightKeepsEverything() {
        assertEquals(2,carPriorityOptionalCount(listOf(100),listOf(500,10),gap=16,maxHeight=Int.MAX_VALUE))
        assertEquals(1,carPriorityOptionalCount(emptyList(),listOf(40),gap=16,maxHeight=40))
    }
}
