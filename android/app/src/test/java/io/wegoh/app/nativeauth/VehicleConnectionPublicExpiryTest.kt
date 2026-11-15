package io.wegoh.app.nativeauth

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Test

class VehicleConnectionPublicExpiryTest {
    private val now=1_800_000_000_000L

    @Test fun codeDeadlineFollowsServerRelativeLifetime() {
        val public=JSONObject().put("userCode","ABCD2345").put("expiresAt",2_300L)
            .put("serverTime",2_000L).put("receivedAtMillis",now)
        assertEquals(now+300_000,VehicleConnection.publicExpiry(public))
    }

    @Test fun receiptWithoutServerTimeUsesAbsoluteExpiry() {
        assertEquals(5_000_000L,VehicleConnection.publicExpiry(JSONObject().put("expiresAt",5_000L)))
    }
}
