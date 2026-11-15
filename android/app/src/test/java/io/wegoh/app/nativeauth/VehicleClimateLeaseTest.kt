package io.wegoh.app.nativeauth

import org.junit.Assert.*
import org.junit.Test

class VehicleClimateLeaseTest {
    @Test fun workerQueueAndPermissionPreflightDoNotConsumeTheNewClaimLease() {
        val queuedAt=1_000L
        val postStarted=queuedAt+7_000
        val deadline=vehicleClimateLeaseDeadline(postStarted,100_000,110_000,200_000)
        assertEquals(18_000L,deadline)
        val deliveredAt=postStarted+1_000+900
        assertEquals(8_100L,deadline-deliveredAt)
    }

    @Test fun networkAndPostPermissionTimeStillConsumeTheLease() {
        val deadline=vehicleClimateLeaseDeadline(5_000,100_000,110_000,200_000)
        assertEquals(15_000L,deadline)
        assertTrue(15_001L>=deadline)
    }

    @Test fun slowNetworkLeavesTimeForAllAcknowledgementsWithinThirtySeconds() {
        val postStarted=5_000L
        val deadline=vehicleClimateLeaseDeadline(postStarted,100_000,130_000,200_000)
        assertEquals(35_000L,deadline)
        val afterClaimAndReceived=postStarted+4_953+1_979
        assertTrue(deadline-afterClaimAndReceived>20_000)
    }

    @Test fun permissionExpiryAndServerRemainingTimeStillBoundTheLease() {
        assertEquals(7_000L,vehicleClimateLeaseDeadline(5_000,100_000,110_000,102_000))
        assertEquals(5_001L,vehicleClimateLeaseDeadline(5_000,100_000,100_001,200_000))
        for(expiry in listOf(99_999L,100_000L,130_001L))
            assertTrue(runCatching {vehicleClimateLeaseDeadline(5_000,100_000,expiry,200_000)}.isFailure)
    }
}
