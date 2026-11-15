package io.wegoh.app.nativeauth

import org.junit.Assert.*
import org.junit.Test

class FunctionalScoreAuthorityTest {
    private val purposes=setOf(FunctionalPurpose.ROOMS_READ,FunctionalPurpose.ROOMS_INTERACT,FunctionalPurpose.DRIVING_SCORE_REPORT)
    private fun snapshot(revision: Long,approved: Int?,allowed: Set<FunctionalPurpose> = purposes)=FunctionalPermissions(
        "a".repeat(32),"b".repeat(32),revision,1000,allowed,4,"c".repeat(64),approvedDisclosureVersion=approved)
    @Test fun scoreAuthorityRetainsDeviceBindingAcrossConsentChanges() {
        val gate=FunctionalPermissionGate()
        gate.replace(snapshot(3,3))
        val before=gate.stamp(FunctionalPurpose.DRIVING_SCORE_REPORT,10)
        val prior=checkNotNull(gate.scoreReportAuthority(10))
        assertEquals("a".repeat(32),prior.deviceId)
        assertTrue(runCatching {gate.replace(snapshot(3,4))}.isFailure)
        gate.replace(snapshot(4,4))
        val current=checkNotNull(gate.scoreReportAuthority(10))
        assertEquals(prior,current)
        assertFalse(gate.current(before,10));assertNull(gate.scoreReportAuthority(1000))
        gate.replace(snapshot(5,4,purposes-FunctionalPurpose.DRIVING_SCORE_REPORT))
        assertEquals(prior,gate.scoreReportAuthority(10))
        gate.replace(snapshot(6,4,purposes-FunctionalPurpose.ROOMS_INTERACT))
        assertNull(gate.scoreReportAuthority(10))
        gate.clear();assertNull(gate.scoreReportAuthority(10))
    }
    @Test fun unknownLegacyApprovalDoesNotBlockCurrentDeviceScoreAuthority() {
        val legacy=snapshot(1,null)
        assertNotNull(legacy.scoreReportAuthority())
        assertFalse(FunctionalPurpose.DRIVING_SCORE_REPORT in FunctionalPurpose.accountPurposes)
    }
}
