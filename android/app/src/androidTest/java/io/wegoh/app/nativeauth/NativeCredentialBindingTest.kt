package io.wegoh.app.nativeauth

import android.test.InstrumentationTestCase
import org.json.JSONObject
import org.json.JSONArray

class NativeCredentialBindingTest: InstrumentationTestCase() {
    fun testReplacementAndLateReceiptCannotChangeKnownAuthority() {
        val value=JSONObject().put("accountId","team-"+"a".repeat(40)).put("grantId","b".repeat(32)).put("deviceId","c".repeat(32))
            .put("installationKeyId","d".repeat(64)).put("certificateSha256","e".repeat(64)).put("recoveryCapability","f".repeat(43)).put("revokeCapability","g".repeat(43))
            .put("slotRevision",1L).put("grantExpiresAt",1900000000L).put("credentialEpoch",1L).put("consentVersion",1L)
            .put("scopes",JSONArray(listOf("account:read","device:self:manage")))
        VehicleConnection.validateReplacement(JSONObject(value.toString()),value)
        for(field in listOf("accountId","grantId","deviceId","installationKeyId","recoveryCapability","revokeCapability","slotRevision")) {
            val bad=JSONObject(value.toString()).put(field,if(field=="slotRevision")2L else "changed")
            try {VehicleConnection.validateReplacement(bad,value);fail("Changed authority accepted: $field")}catch(expected: IllegalStateException){}
        }
        for(scope in listOf("courses:read","playlists:read")) {
            val wider=JSONObject(value.toString()).put("scopes",JSONArray(listOf("account:read","device:self:manage",scope)))
            try {VehicleConnection.validateReplacement(wider,value);fail("Old credential expanded scope")}catch(expected: IllegalStateException){}
        }
        val outbox=JSONArray().put(JSONObject().put("request",JSONObject().put("grantId",value.getString("grantId")).put("revokeCapability",value.getString("revokeCapability"))))
        VehicleConnection.validateLateReceipt(value,outbox,value.getString("installationKeyId"),value.getString("certificateSha256"))
        for(field in listOf("grantId","revokeCapability","installationKeyId","certificateSha256")) {
            val bad=JSONObject(value.toString()).put(field,"changed")
            try {VehicleConnection.validateLateReceipt(bad,outbox,value.getString("installationKeyId"),value.getString("certificateSha256"));fail("Unrelated late receipt accepted")}catch(expected: IllegalStateException){}
        }
        assertEquals(1,outbox.length());assertEquals(value.getString("grantId"),outbox.getJSONObject(0).getJSONObject("request").getString("grantId"))
    }
}
