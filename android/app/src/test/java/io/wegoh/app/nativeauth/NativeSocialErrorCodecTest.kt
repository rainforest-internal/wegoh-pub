package io.wegoh.app.nativeauth

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class NativeSocialErrorCodecTest {
    @Test fun signalPostBodiesUseTheSameCurrentRevisionEnvelopeAsOtherNativeWrites() {
        val bodies=listOf(TripSignalsCodec.voteBody("agree"),TripSignalsCodec.sendBody(TripSignalKind.REST,null),
            TripSignalsCodec.candidateBody(TripSignalKind.REST,SignalLocation(SignalPoint(37.0,128.0,90.0))))
        bodies.forEach {body->
            val wire=NativeApiClient.functionalBody(body,27)
            assertEquals(27L,wire.getLong("functionalRevision"))
            assertFalse(body.has("functionalRevision"))
            assertEquals(body.keys().asSequence().toSet()+"functionalRevision",wire.keys().asSequence().toSet())
        }
        assertEquals("agree",NativeApiClient.functionalBody(bodies.first(),27).getString("choice"))
        assertTrue(runCatching {NativeApiClient.functionalBody(bodies.first(),0)}.isFailure)
    }
    @Test fun missingRevisionFailureKeepsHttpStatusKindAndServerCode() {
        val failure=NativeSocialErrorCodec.failure(400,JSONObject("""{"error":"INVALID_FUNCTIONAL_REQUEST","message":"private payload"}"""),true,null)
        assertEquals(400,failure.httpStatus)
        assertEquals(NativeSocialFailure.Kind.INVALID_RESPONSE,failure.kind)
        assertEquals("INVALID_FUNCTIONAL_REQUEST",failure.serverErrorCode)
        assertSame(failure,socialRequestFailure(failure,true))
        assertEquals("status=400 kind=invalid_response error_code=INVALID_FUNCTIONAL_REQUEST",NativeSocialErrorCodec.fields(failure))
        val log=TripLoadDiagnostics.message("trip.signals.vote",failure,"a".repeat(32))
        assertTrue(log.contains("status=400"));assertTrue(log.contains("kind=invalid_response"))
        assertTrue(log.contains("error_code=INVALID_FUNCTIONAL_REQUEST"));assertFalse(log.contains("private payload"))
    }
    @Test fun codeFieldIsReadButMessagesDetailAndUnsafeValuesAreNotLogged() {
        assertEquals("PURPOSE_DENIED",NativeSocialErrorCodec.code(JSONObject("""{"code":"PURPOSE_DENIED","detail":"private detail"}""")))
        for(value in listOf("private name","private\nmessage","a".repeat(43),"x".repeat(100),"37.689,128.755"))
            assertNull(NativeSocialErrorCodec.code(JSONObject().put("error",value).put("message","never read")))
        assertNull(NativeSocialErrorCodec.code(JSONObject().put("error",JSONObject().put("message","private"))))
        assertNull(NativeSocialErrorCodec.code(JSONObject().put("detail","INVALID_FUNCTIONAL_REQUEST")))
    }
    @Test fun legacyRevisionConflictStillInvalidatesWithoutLoggingDetail() {
        val failure=NativeSocialErrorCodec.failure(409,JSONObject().put("detail","FUNCTIONAL_REVISION_CHANGED"),true,12)
        assertEquals(NativeSocialFailure.Reason.REVISION_CHANGED,failure.reason)
        assertEquals(12,failure.retryAfterSeconds)
        assertNull(failure.serverErrorCode)
    }
    @Test fun activeTripConflictsDecodeTheActualFastApiEnvelopeWithoutInvalidatingAuthority() {
        for(code in listOf("TRIP_ALREADY_ACTIVE","TRIP_MEMBER_ALREADY_ACTIVE")) {
            val body=StrictNativeJson.parseBusiness("""{"detail":"$code"}""".toByteArray())
            val failure=NativeSocialErrorCodec.failure(409,body,true,7)
            assertEquals(NativeSocialFailure.Kind.CONFLICT,failure.kind)
            assertEquals(409,failure.httpStatus)
            assertEquals(code,failure.serverErrorCode)
            assertNull(failure.reason)
            assertEquals(7,failure.retryAfterSeconds)
            assertTrue(failure.mayHaveExecuted)
            assertFalse(NativeSocialErrorCodec.invalidatesAuthority(failure))
            assertSame(failure,socialRequestFailure(failure,true))
            assertEquals("status=409 kind=conflict error_code=$code",NativeSocialErrorCodec.fields(failure))
            // The generic code reader still never accepts arbitrary detail fields.
            assertNull(NativeSocialErrorCodec.code(body))
        }
    }
    @Test fun activeTripDetailsRequireConflictStatusAndAnExactSingleFieldEnvelope() {
        for(code in listOf("TRIP_ALREADY_ACTIVE","TRIP_MEMBER_ALREADY_ACTIVE")) {
            val body=JSONObject().put("detail",code)
            for(status in listOf(400,401,403,404,422,429,500,503)) {
                val failure=NativeSocialErrorCodec.failure(status,body,true,null)
                assertNull("$status $code",failure.serverErrorCode)
            }
            val withExtra=JSONObject().put("detail",code).put("message","private detail")
            assertNull(NativeSocialErrorCodec.failure(409,withExtra,true,null).serverErrorCode)
        }
        for(detail in listOf("OTHER_CONFLICT","private detail","TRIP_ALREADY_ACTIVE\n",
            "trip_already_active",7,JSONObject.NULL,JSONObject().put("code","TRIP_ALREADY_ACTIVE"),
            org.json.JSONArray().put("TRIP_ALREADY_ACTIVE"))) {
            val failure=NativeSocialErrorCodec.failure(409,JSONObject().put("detail",detail),true,null)
            assertEquals(NativeSocialFailure.Kind.CONFLICT,failure.kind)
            assertNull(failure.serverErrorCode)
            assertEquals("status=409 kind=conflict error_code=none",NativeSocialErrorCodec.fields(failure))
        }
        val machine=NativeSocialErrorCodec.failure(409,JSONObject().put("error","FUNCTIONAL_REVISION_CHANGED")
            .put("detail","TRIP_ALREADY_ACTIVE"),true,null)
        assertEquals("FUNCTIONAL_REVISION_CHANGED",machine.serverErrorCode)
        assertEquals(NativeSocialFailure.Reason.REVISION_CHANGED,machine.reason)
        assertTrue(NativeSocialErrorCodec.invalidatesAuthority(machine))
    }
    @Test fun jsonBusinessErrorWithNullFieldsKeepsMachineError() {
        val parsed=StrictNativeJson.parseBusiness("""{"authorizationVersion":1,"error":"PURPOSE_DENIED","message":null}""".toByteArray())
        val failure=NativeSocialErrorCodec.failure(403,parsed,true,null)
        assertEquals(NativeSocialFailure.Kind.FORBIDDEN,failure.kind)
        assertEquals("PURPOSE_DENIED",failure.serverErrorCode)
    }
    @Test fun disabledVoiceIsFeatureLocalOnlyForTheExactParticipationRead() {
        val disabled=StrictNativeJson.parseBusiness("""{"detail":"TRIP_VOICE_UNAVAILABLE"}""".toByteArray())
        val local=NativeSocialErrorCodec.failure(403,disabled,false,null,tripVoiceParticipationRead=true)
        assertEquals(NativeSocialFailure.Kind.UNAVAILABLE,local.kind)
        assertEquals(403,local.httpStatus)
        assertEquals("TRIP_VOICE_UNAVAILABLE",local.serverErrorCode)
        assertFalse(local.mayHaveExecuted)
        assertSame(local,socialRequestFailure(local,false))

        val otherRead=NativeSocialErrorCodec.failure(403,disabled,false,null)
        assertEquals(NativeSocialFailure.Kind.FORBIDDEN,otherRead.kind)
        assertNull(otherRead.serverErrorCode)
        val write=NativeSocialErrorCodec.failure(403,disabled,true,null,tripVoiceParticipationRead=true)
        assertEquals(NativeSocialFailure.Kind.FORBIDDEN,write.kind)
        assertTrue(write.mayHaveExecuted)
    }
    @Test fun voiceParticipationDoesNotHideAuthorityFailures() {
        val expired=JSONObject().put("detail","TRIP_VOICE_UNAVAILABLE")
        assertEquals(NativeSocialFailure.Kind.AUTHORIZATION_REQUIRED,
            NativeSocialErrorCodec.failure(401,expired,false,null,tripVoiceParticipationRead=true).kind)
        val ordinary=JSONObject().put("detail","PURPOSE_DENIED")
        assertEquals(NativeSocialFailure.Kind.FORBIDDEN,
            NativeSocialErrorCodec.failure(403,ordinary,false,null,tripVoiceParticipationRead=true).kind)
        val revoked=JSONObject().put("detail","TRIP_VOICE_UNAVAILABLE").put("error","CONSENT_REVOKED")
        val failure=NativeSocialErrorCodec.failure(403,revoked,false,null,tripVoiceParticipationRead=true)
        assertEquals(NativeSocialFailure.Kind.FORBIDDEN,failure.kind)
        assertEquals("CONSENT_REVOKED",failure.serverErrorCode)
    }
    @Test fun vehicleOwnerRejectionStaysFeatureLocalWithoutInvalidatingFunctionalAuthority() {
        val owner=NativeSocialErrorCodec.failure(403,StrictNativeJson.parseBusiness(
            """{"authorizationVersion":1,"error":"VEHICLE_OWNER_REQUIRED"}""".toByteArray()),true,null)
        assertEquals(NativeSocialFailure.Kind.FORBIDDEN,owner.kind)
        assertEquals("VEHICLE_OWNER_REQUIRED",owner.serverErrorCode)
        assertFalse(NativeSocialErrorCodec.invalidatesAuthority(owner))
        assertFalse(NativeSocialErrorCodec.invalidatesAuthority(socialRequestFailure(owner,true)))
        assertEquals("status=403 kind=forbidden error_code=VEHICLE_OWNER_REQUIRED",NativeSocialErrorCodec.fields(owner))
    }
    @Test fun functionalAuthorityFailuresStillInvalidate() {
        for(code in listOf("FUNCTIONAL_PURPOSE_REQUIRED","FUNCTIONAL_CONSENT_INACTIVE","PURPOSE_DENIED","CONSENT_REVOKED"))
            assertTrue(code,NativeSocialErrorCodec.invalidatesAuthority(
                NativeSocialErrorCodec.failure(403,JSONObject().put("error",code),true,null)))
        assertTrue(NativeSocialErrorCodec.invalidatesAuthority(NativeSocialErrorCodec.failure(403,null,false,null)))
        // Only the machine error field may mark a 403 feature-local; detail text cannot.
        assertTrue(NativeSocialErrorCodec.invalidatesAuthority(
            NativeSocialErrorCodec.failure(403,JSONObject().put("detail","VEHICLE_OWNER_REQUIRED"),false,null)))
        assertTrue(NativeSocialErrorCodec.invalidatesAuthority(
            NativeSocialErrorCodec.failure(401,JSONObject().put("error","VEHICLE_OWNER_REQUIRED"),false,null)))
        assertTrue(NativeSocialErrorCodec.invalidatesAuthority(NativeSocialFailure(NativeSocialFailure.Kind.STALE)))
        assertTrue(NativeSocialErrorCodec.invalidatesAuthority(
            NativeSocialErrorCodec.failure(409,JSONObject().put("error","FUNCTIONAL_REVISION_CHANGED"),true,null)))
        assertFalse(NativeSocialErrorCodec.invalidatesAuthority(
            NativeSocialErrorCodec.failure(409,JSONObject().put("error","RECEIVER_CHANGED"),true,null)))
        assertFalse(NativeSocialErrorCodec.invalidatesAuthority(NativeSocialErrorCodec.failure(503,null,false,null)))
        assertFalse(NativeSocialErrorCodec.invalidatesAuthority(IllegalStateException("x")))
        assertFalse(NativeSocialErrorCodec.invalidatesAuthority(null))
    }
}
