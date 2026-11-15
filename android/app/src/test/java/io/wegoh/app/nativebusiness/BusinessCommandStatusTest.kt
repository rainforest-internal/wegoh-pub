package io.wegoh.app.nativebusiness

import io.wegoh.app.nativeauth.BusinessCommand.Stage
import io.wegoh.app.ui.CarStatusTone
import org.junit.Assert.*
import org.junit.Test

class BusinessCommandStatusTest {
    @Test fun outcomeGroupsUseDistinctTones() {
        val pending=listOf(Stage.QUEUED,Stage.DELIVERED,Stage.RECEIVED,Stage.SDK_ACCEPTED).map {businessCommandStatus(it).second}.toSet()
        val failed=listOf(Stage.REJECTED,Stage.CANCELLED,Stage.EXPIRED).map {businessCommandStatus(it).second}.toSet()
        val success=businessCommandStatus(Stage.STATE_CONFIRMED).second
        val unknown=businessCommandStatus(Stage.UNKNOWN).second
        assertEquals(1,pending.size);assertEquals(1,failed.size)
        assertEquals(4,setOf(pending.single(),failed.single(),success,unknown).size)
    }

    @Test fun outcomeNamesShareOneAxis() {
        assertEquals("동작 확인됨",businessCommandStatus(Stage.STATE_CONFIRMED).first)
        assertEquals("동작 미확인",businessCommandStatus(Stage.UNKNOWN).first)
    }

    @Test fun unknownRowDoesNotRepeatItsChipButFinishedFailuresStillWarn() {
        assertFalse(businessCommandUncertain(Stage.UNKNOWN,true))
        assertFalse(businessCommandUncertain(Stage.STATE_CONFIRMED,true))
        assertFalse(businessCommandUncertain(Stage.QUEUED,true))
        assertTrue(businessCommandUncertain(Stage.EXPIRED,true))
        assertTrue(businessCommandUncertain(Stage.REJECTED,true))
        assertFalse(businessCommandUncertain(Stage.EXPIRED,false))
    }

    @Test fun everyStageHasAChip() {
        Stage.entries.forEach {assertTrue(businessCommandStatus(it).first.isNotBlank())}
        assertNotEquals(CarStatusTone.ACTIVE,businessCommandStatus(Stage.STATE_CONFIRMED).second)
    }
}
