package io.wegoh.app.ui

import org.junit.Assert.*
import org.junit.Test

class CarErrorReportStateTest {
    @Test fun reportToggleStartsOffAndSendsOnlyAfterTurnedOn() {
        val initial=CarErrorReportState()
        assertFalse(initial.enabled)
        assertFalse(initial.canSend)
        assertSame(initial,initial.sending())
        val on=initial.toggled(true)
        assertTrue(on.canSend)
        val sending=on.sending()
        assertEquals(CarErrorReportStatus.SENDING,sending.status)
        assertFalse(sending.canSend)
        assertSame(sending,sending.toggled(false))
        val sent=sending.finished(Result.success("0123456789abcdef"))
        assertEquals("보냈어요 · 보고 번호 01234567",sent.message)
        assertFalse(sent.canSend)
        assertEquals(CarErrorReportState(),sent.toggled(false))
        val failed=sending.finished(Result.failure(IllegalStateException("NATIVE_DATA_UNAVAILABLE")))
        assertEquals(CarErrorReportStatus.FAILED,failed.status)
        assertTrue(failed.canSend)
        assertSame(on,on.finished(Result.success("x")))
    }
}
