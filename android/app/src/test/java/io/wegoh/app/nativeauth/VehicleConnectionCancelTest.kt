package io.wegoh.app.nativeauth

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** 차량 "취소" ends its own pending code on the server, not only on screen. */
class VehicleConnectionCancelTest {
    private val operation="a".repeat(32)
    private val verifier="V".repeat(43)
    private fun auth(action: String,response: JSONObject?=null)=JSONObject().put("action",action)
        .put("request",JSONObject().put("operationId",operation)).put("verifier",verifier)
        .apply {response?.let {put("response",it)}}

    @Test fun cancelTargetsTheOriginalOperationWithItsVerifier() {
        for(action in listOf("CONNECTION_BEGIN","ACCOUNT_AUTHORIZE","CONNECTION_REAUTHORIZE","CONNECTION_RESTART")) {
            for(response in listOf(null,JSONObject().put("state","PENDING"),JSONObject().put("state","APPROVED"))) {
                val request=VehicleConnection.cancelRequest(auth(action,response))!!
                assertEquals(setOf("authorizationVersion","operationId","codeVerifier","proofNonce"),request.keySet())
                assertEquals(operation,request.getString("operationId"))
                assertEquals(verifier,request.getString("codeVerifier"))
                assertEquals("connection-cancel",request.getString("proofNonce"))
            }
        }
    }

    @Test fun codeWithGrantOrPastIssuanceIsNotCancelled() {
        assertNull(VehicleConnection.cancelRequest(auth("ACCOUNT_AUTHORIZE",JSONObject().put("state","APPROVED").put("grantId","c".repeat(32)))))
        assertNull(VehicleConnection.cancelRequest(auth("CONNECTION_BEGIN",JSONObject().put("state","ISSUING"))))
        assertNull(VehicleConnection.cancelRequest(auth("CONNECTION_BEGIN").put("expired",true)))
        assertNull(VehicleConnection.cancelRequest(auth("CERTIFICATE_RENEW_BEGIN")))
    }

    @Test fun cancelCallsTheServerApi() {
        val calls=mutableListOf<Pair<String,JSONObject>>()
        val request=VehicleConnection.cancelRequest(auth("CONNECTION_BEGIN"))!!
        assertTrue(VehicleConnection.sendCancel(request) {action,body -> calls+=action to body;JSONObject()})
        assertEquals(listOf("CONNECTION_CANCEL" to request),calls)
    }

    @Test fun networkFailureKeepsTheCancelForRetry() {
        assertFalse(VehicleConnection.sendCancel(JSONObject()) {_,_ -> throw java.net.SocketTimeoutException()})
        for(status in listOf(408,429,503))
            assertFalse(VehicleConnection.sendCancel(JSONObject()) {_,_ -> throw NativeApiClient.Failure(status,"SERVICE_UNAVAILABLE")})
    }

    @Test fun serverTerminalAnswerSettlesTheCancel() {
        for((status,code) in listOf(403 to "INVALID_PROOF",404 to "OPERATION_NOT_FOUND",409 to "OPERATION_CONFLICT",410 to "AUTHORIZATION_EXPIRED"))
            assertTrue(VehicleConnection.sendCancel(JSONObject()) {_,_ -> throw NativeApiClient.Failure(status,code)})
    }

    private val now=1_000_000L
    private fun locked(auth: JSONObject,epoch: Long=7,sign: (JSONObject)->JSONObject={it.put("proof","signed")})=
        JSONObject().put("epoch",epoch-1).also {VehicleConnection.storeCancelOnLock(it,auth,epoch,now,sign)}

    @Test fun lockStoresTheSignedCancelWithItsEpochAndDeadline() {
        val pending=locked(auth("CONNECTION_BEGIN",JSONObject().put("state","PENDING"))).getJSONObject("pendingCancel")
        assertEquals(setOf("request","epoch","deadline"),pending.keySet())
        val request=pending.getJSONObject("request")
        assertEquals(operation,request.getString("operationId"))
        assertEquals("signed",request.getString("proof"))
        assertEquals(7L,pending.getLong("epoch"))
        assertEquals(now+VehicleConnection.CANCEL_RETRY_WINDOW_MS,pending.getLong("deadline"))
    }

    @Test fun lockStoresNothingForAGrantOrAFailedSignature() {
        assertFalse(locked(auth("ACCOUNT_AUTHORIZE",JSONObject().put("state","APPROVED").put("grantId","c".repeat(32)))).has("pendingCancel"))
        assertFalse(locked(auth("CONNECTION_BEGIN")) {throw IllegalStateException("keystore")}.has("pendingCancel"))
    }

    @Test fun drainSendsTheStoredRequestThenClearsIt() {
        val saved=locked(auth("CONNECTION_BEGIN"));val pending=saved.getJSONObject("pendingCancel")
        val calls=mutableListOf<Pair<String,JSONObject>>()
        assertTrue(VehicleConnection.cancelSettled(pending,now+1) {action,body -> calls+=action to body;JSONObject()})
        assertEquals(listOf("CONNECTION_CANCEL" to pending.getJSONObject("request")),calls)
        VehicleConnection.clearCancel(saved,pending)
        assertFalse(saved.has("pendingCancel"))
    }

    @Test fun drainLeavesALaterLocksCancelInPlace() {
        val sent=locked(auth("CONNECTION_BEGIN")).getJSONObject("pendingCancel")
        val laterEpoch=locked(auth("CONNECTION_BEGIN"),epoch=8)
        VehicleConnection.clearCancel(laterEpoch,sent)
        assertTrue(laterEpoch.has("pendingCancel"))
        val other=JSONObject(auth("CONNECTION_BEGIN").toString());other.getJSONObject("request").put("operationId","b".repeat(32))
        val laterOperation=locked(other)
        VehicleConnection.clearCancel(laterOperation,sent)
        assertTrue(laterOperation.has("pendingCancel"))
    }

    @Test fun retryStopsAtTheCodesOwnLifetime() {
        val pending=locked(auth("CONNECTION_BEGIN")).getJSONObject("pendingCancel")
        val down: (String,JSONObject)->JSONObject={_,_ -> throw java.net.SocketTimeoutException()}
        assertFalse(VehicleConnection.cancelSettled(pending,now+VehicleConnection.CANCEL_RETRY_WINDOW_MS-1,down))
        var sent=false
        assertTrue(VehicleConnection.cancelSettled(pending,now+VehicleConnection.CANCEL_RETRY_WINDOW_MS) {_,_ -> sent=true;JSONObject()})
        assertFalse(sent)
    }
}
