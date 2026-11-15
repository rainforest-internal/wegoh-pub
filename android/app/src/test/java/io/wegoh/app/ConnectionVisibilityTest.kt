package io.wegoh.app

import io.wegoh.app.nativeauth.VehicleConnection.Stage
import org.junit.Assert.assertEquals
import org.junit.Test

class ConnectionVisibilityTest {
    @Test fun drivingRestrictionWinsOverEveryStage() {
        for(stage in Stage.entries)for(focused in listOf(true,false))
            assertEquals(ConnectionVisibility.RESTRICTED,connectionVisibility(allowed=false,focused=focused,stage=stage))
    }

    @Test fun focusLossHidesOnlyTheApprovalCode() {
        assertEquals(ConnectionVisibility.CODE_HIDDEN,connectionVisibility(allowed=true,focused=false,stage=Stage.APPROVAL_REQUIRED))
        for(stage in Stage.entries-Stage.APPROVAL_REQUIRED)
            assertEquals("$stage",ConnectionVisibility.SHOWN,connectionVisibility(allowed=true,focused=false,stage=stage))
    }

    @Test fun focusedWindowShowsActualState() {
        for(stage in Stage.entries)
            assertEquals(ConnectionVisibility.SHOWN,connectionVisibility(allowed=true,focused=true,stage=stage))
    }
}
