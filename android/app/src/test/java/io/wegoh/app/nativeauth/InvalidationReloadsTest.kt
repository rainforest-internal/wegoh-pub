package io.wegoh.app.nativeauth

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class InvalidationReloadsTest {
    @Test fun reloadsAreCappedUntilASuccessfulRead() {
        val reloads=InvalidationReloads()
        assertEquals(listOf(1,2,3),List(3) {reloads.take()})
        assertNull(reloads.take())
        reloads.reset()
        assertEquals(1,reloads.take())
    }
}
