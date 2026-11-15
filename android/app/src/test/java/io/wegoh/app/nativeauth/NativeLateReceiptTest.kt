package io.wegoh.app.nativeauth

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class NativeLateReceiptTest {
    private val receipt=JSONObject().put("grantId","a".repeat(32)).put("revokeCapability","b".repeat(43))
        .put("installationKeyId","c".repeat(64)).put("certificateSha256","d".repeat(64))
    private fun outbox()=JSONArray().put(JSONObject().put("request",JSONObject()
        .put("grantId",receipt.getString("grantId")).put("revokeCapability",receipt.getString("revokeCapability"))))
    private fun validate(value: JSONObject,pending: JSONArray)=VehicleConnection.validateLateReceipt(value,pending,
        receipt.getString("installationKeyId"),receipt.getString("certificateSha256"))

    @Test fun lateCredentialLeavesExactRevokePendingUntilServerAcknowledges() {
        val pending=outbox();val before=pending.toString()
        validate(receipt,pending)
        assertEquals(before,pending.toString())
        for(field in listOf("grantId","revokeCapability","installationKeyId","certificateSha256")) {
            assertTrue(runCatching {validate(JSONObject(receipt.toString()).put(field,"unrelated"),pending)}.isFailure)
            assertEquals(before,pending.toString())
        }
    }

    @Test fun lateCredentialCannotRecreateAcknowledgedOutbox() {
        val pending=JSONArray()
        assertTrue(runCatching {validate(receipt,pending)}.isFailure)
        assertEquals(0,pending.length())
    }
}
