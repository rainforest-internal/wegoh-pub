package io.wegoh.app

import org.junit.Assert.*
import org.junit.Test

class VehicleReceiverLifetimeTest {
    @Test fun revocationOrExpiryEndsReceptionOnceAndCannotReactivateOldOwner() {
        var revision: Long?=7L
        var stops=0
        val lifetime=VehicleReceiverLifetime({revision},{stops++})
        assertTrue(lifetime.check())
        // currentDataBoundary becomes null on either revocation or boundary expiration.
        revision=null
        assertFalse(lifetime.check())
        assertFalse(lifetime.check())
        revision=7L
        assertFalse(lifetime.check())
        assertEquals(1,stops)
    }

    @Test fun backgroundAndTemporaryTransportLossRetainTheValidAccountBoundary() {
        var stops=0
        val lifetime=VehicleReceiverLifetime({7L},{stops++})
        // Transport availability and window visibility do not replace verified authority.
        repeat(3) {assertTrue(lifetime.check())}
        assertEquals(0,stops)
    }

    @Test fun accountReplacementRequiresANewReceiverOwner() {
        var revision: Long?=7L
        var stops=0
        val old=VehicleReceiverLifetime({revision},{stops++})
        revision=8L
        assertFalse(old.check())
        val refreshed=VehicleReceiverLifetime({revision},{stops++})
        assertTrue(refreshed.check())
        assertFalse(old.check())
        assertEquals(1,stops)
    }

    @Test fun unverifiedStartupCannotKeepAForegroundReceiver() {
        var stops=0
        val lifetime=VehicleReceiverLifetime({null},{stops++})
        assertFalse(lifetime.check())
        assertEquals(1,stops)
    }
}
