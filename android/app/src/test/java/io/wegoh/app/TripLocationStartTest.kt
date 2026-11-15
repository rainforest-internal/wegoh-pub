package io.wegoh.app

import org.junit.Assert.*
import org.junit.Test

class TripLocationStartTest {
    @Test fun failedInstanceIsReleasedAndAnotherAttemptCanSucceed() {
        val first=Any();val second=Any();val released=mutableListOf<Any>()
        var stored=startTripLocation(first,{throw SecurityException("denied")},{released.add(it)})
        assertNull(stored)
        assertEquals(listOf(first),released)
        stored=startTripLocation(second,{},{released.add(it)})
        assertSame(second,stored)
        assertEquals(listOf(first),released)
    }
    @Test fun releaseFailureDoesNotKeepFailedInstance() {
        assertNull(startTripLocation(Any(),{throw IllegalStateException()},{throw IllegalStateException()}))
    }
}
