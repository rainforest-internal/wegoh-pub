package io.wegoh.app.nativeauth

import org.junit.Assert.*
import org.junit.Test

class NativeConnectionDiagnosticsTest {
    private val secret="private-token https://private.invalid/path?code=private-code account-private"
    private fun failure(error: Throwable)=NativeConnectionDiagnostics.message(NativeConnectionDiagnostics.Event.FAILED,
        NativeConnectionDiagnostics.Operation.START,VehicleConnection.Stage.RECOVERY_REQUIRED,error)

    @Test fun transportReasonsNeverIncludeExceptionMessages() {
        val cases=listOf(java.net.UnknownHostException(secret) to "dns",
            javax.net.ssl.SSLHandshakeException(secret) to "tls",
            java.net.SocketTimeoutException(secret) to "timeout",
            java.util.concurrent.TimeoutException(secret) to "timeout")
        for((error,reason) in cases) {
            val output=failure(IllegalStateException(secret,error))
            assertEquals("native.connection: failed operation=start stage=RECOVERY_REQUIRED reason=$reason",output)
            assertFalse(output.contains(secret));assertFalse(output.contains("private"))
        }
    }

    @Test fun nativeRejectionsExposeOnlyTypedHttpStatus() {
        val output=failure(NativeApiClient.Failure(403,secret))
        assertEquals("native.connection: failed operation=start stage=RECOVERY_REQUIRED reason=native_rejected status=403",output)
        assertFalse(output.contains(secret));assertFalse(output.contains("private"))
        assertFalse(failure(NativeApiClient.Failure(-1,secret)).contains("status="))
    }

    @Test fun contentTypeAndStateClassificationRequireExactKnownMessages() {
        for((message,reason) in listOf("NATIVE_JSON_RESPONSE_REQUIRED" to "invalid_content_type",
            "NATIVE_STATE_INVALID" to "state_unavailable","NATIVE_PRIVATE_KEY_MISSING" to "state_unavailable")) {
            assertTrue(failure(IllegalStateException(message)).endsWith("reason=$reason"))
            val output=failure(IllegalStateException("$message $secret"))
            assertTrue(output.endsWith("reason=unexpected"));assertFalse(output.contains(secret))
        }
        assertTrue(failure(javax.crypto.AEADBadTagException(secret)).endsWith("reason=state_unavailable"))
    }

    @Test fun startedAndFinishedContainOnlyFixedOperationAndStage() {
        for(operation in NativeConnectionDiagnostics.Operation.entries) {
            for(event in listOf(NativeConnectionDiagnostics.Event.STARTED,NativeConnectionDiagnostics.Event.FINISHED)) {
                val output=NativeConnectionDiagnostics.message(event,operation,VehicleConnection.Stage.CONNECTING,NativeApiClient.Failure(503,secret))
                assertEquals("native.connection: ${event.wire} operation=${operation.wire} stage=CONNECTING",output)
            }
        }
    }

    @Test fun unknownAndCyclicCausesDoNotExposeNamesOrUnboundedMessages() {
        val first=IllegalArgumentException(secret);val second=RuntimeException(secret)
        first.initCause(second);second.initCause(first)
        assertEquals("native.connection: failed operation=start stage=RECOVERY_REQUIRED reason=unexpected",failure(first))
    }
}
