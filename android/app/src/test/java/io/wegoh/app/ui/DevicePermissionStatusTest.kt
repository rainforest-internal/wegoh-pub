package io.wegoh.app.ui

import org.junit.Assert.assertEquals
import org.junit.Test

class DevicePermissionStatusTest {
    @Test fun grantedIsQuietAndMissingOrPartialIsEmphasized() {
        assertEquals("허용됨" to CarStatusTone.NEUTRAL,devicePermissionStatus(true,null))
        assertEquals("허용 안 됨" to CarStatusTone.SOFT,devicePermissionStatus(false,null))
        assertEquals("부분 허용" to CarStatusTone.SOFT,devicePermissionStatus(true,"부분 허용"))
    }
}
