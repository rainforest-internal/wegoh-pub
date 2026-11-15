package io.wegoh.app.nativeauth

import org.junit.Assert.assertEquals
import org.junit.Test

class VoiceDraftLifetimeTest {
    @Test fun recordedClipExpiresWhenItCanNoLongerBeSent() {
        assertEquals(VOICE_DRAFT_LIFETIME_MS,voiceDraftRemainingMs(1_000,1_000))
        assertEquals(45_000L,voiceDraftRemainingMs(1_000,16_000))
        assertEquals(0L,voiceDraftRemainingMs(1_000,61_000))
        assertEquals(0L,voiceDraftRemainingMs(1_000,500_000))
    }
}
