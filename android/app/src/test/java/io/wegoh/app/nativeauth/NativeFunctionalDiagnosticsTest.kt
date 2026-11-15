package io.wegoh.app.nativeauth

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

/** invalidation lines must name the cause without identifiers, tokens or server text. */
class NativeFunctionalDiagnosticsTest {
    private val trip="0123456789abcdef0123456789abcdef"
    private val signal="fedcba9876543210fedcba9876543210"

    @Test fun pathTemplateMasksIdentifiersAndQueryValues() {
        assertEquals("POST /v1/native/trips/{id}/signals/{id}/vote",
            NativeFunctionalDiagnostics.pathTemplate("POST","/v1/native/trips/$trip/signals/$signal/vote"))
        assertEquals("GET /v1/native/trips/{id}?section={v}",
            NativeFunctionalDiagnostics.pathTemplate("GET","/v1/native/trips/$trip?section=route"))
        assertEquals("GET /v1/social/history?cursor={v}",
            NativeFunctionalDiagnostics.pathTemplate("GET","/v1/social/history?cursor=private-cursor-123"))
        // A word-shaped hex id and a slug with digits are masked too.
        assertEquals("GET /v1/social/rooms/{id}/music",
            NativeFunctionalDiagnostics.pathTemplate("GET","/v1/social/rooms/deadbeefcafebabe/music"))
        assertEquals("GET /v1/native/courses/public/{id}/versions/{id}",
            NativeFunctionalDiagnostics.pathTemplate("GET","/v1/native/courses/public/seoul2/versions/3"))
        assertEquals("POST /v1/device/control-support",NativeFunctionalDiagnostics.pathTemplate("POST","/v1/device/control-support"))
    }

    @Test fun unscopedForbiddenNamesTemplateStatusAndCodeOnly() {
        val body=JSONObject().put("detail","TRIP_LOCATION_SHARING_OFF private-account@example.invalid")
        val failure=NativeSocialErrorCodec.failure(403,body,true,null,
            requestTemplate=NativeFunctionalDiagnostics.pathTemplate("POST","/v1/native/trips/$trip/location"))
        val scope=NativeFunctionalDiagnostics.scope(null,failure,"request")
        val line=NativeFunctionalDiagnostics.invalidated(NativeFunctionalDiagnostics.socialReason(failure),scope,failure,true,3)
        assertEquals("native.functional: invalidated reason=social_forbidden scope=POST /v1/native/trips/{id}/location "+
            "status=403 code=none gate=cleared clients=3",line)
        assertFalse(line.contains(trip));assertFalse(line.contains("private"));assertFalse(line.contains("SHARING_OFF"))
    }

    @Test fun declaredScopeWinsAndMachineCodeIsKept() {
        val failure=NativeSocialErrorCodec.failure(403,JSONObject().put("error","FUNCTIONAL_PURPOSE_REQUIRED"),false,null,
            requestTemplate="GET /v1/native/trips/{id}/signals")
        val line=NativeFunctionalDiagnostics.invalidated(NativeFunctionalDiagnostics.socialReason(failure),
            NativeFunctionalDiagnostics.scope("trip.signals.read",failure,"request"),failure,true,1)
        assertEquals("native.functional: invalidated reason=social_forbidden scope=trip.signals.read status=403 "+
            "code=FUNCTIONAL_PURPOSE_REQUIRED gate=cleared clients=1",line)
    }

    @Test fun reasonsAreDistinguished() {
        val revision=NativeSocialErrorCodec.failure(409,JSONObject().put("detail","FUNCTIONAL_REVISION_CHANGED"),true,null)
        assertEquals("social_revision_changed",NativeFunctionalDiagnostics.socialReason(revision))
        assertEquals("social_authorization_required",NativeFunctionalDiagnostics.socialReason(NativeSocialErrorCodec.failure(401,null,false,null)))
        assertEquals("social_stale",NativeFunctionalDiagnostics.socialReason(NativeSocialFailure(NativeSocialFailure.Kind.STALE)))
        // A failure before the business request names the phase it reached.
        assertEquals("phase=permissions",NativeFunctionalDiagnostics.scope(null,NativeSocialFailure(NativeSocialFailure.Kind.STALE),"permissions"))
        assertEquals("native.functional: invalidated reason=stamp_changed scope=verify_account status=0 code=none gate=kept clients=2",
            NativeFunctionalDiagnostics.invalidated("stamp_changed","verify_account",null,false,2))
        assertEquals("native.functional: invalidated reason=sockets_background scope=none status=0 code=none gate=cleared clients=0",
            NativeFunctionalDiagnostics.invalidated("sockets_background",null,null,true,0))
    }

    @Test fun unexpectedFreeTextNeverReachesTheLine() {
        val line=NativeFunctionalDiagnostics.invalidated("Bearer private-token","https://private.invalid/x?code=1",null,true,0)
        assertEquals("native.functional: invalidated reason=other scope=other status=0 code=none gate=cleared clients=0",line)
    }

    @Test fun endingsSeparateExpiryInvalidationTransportAndClose() {
        assertEquals("native.social: ended client=trip reason=expired expiry_in_s=13",
            NativeFunctionalDiagnostics.ended("trip",NativeFunctionalDiagnostics.End.EXPIRED,null,13,0))
        assertEquals("native.social: ended client=climate reason=invalidated cause=social_forbidden suppressed=2",
            NativeFunctionalDiagnostics.ended("climate",NativeFunctionalDiagnostics.End.INVALIDATED,"social_forbidden",null,2))
        assertEquals("native.social: ended client=social reason=transport cause=closed",
            NativeFunctionalDiagnostics.ended("social",NativeFunctionalDiagnostics.End.TRANSPORT,"closed",null,0))
        assertEquals("native.social: ended client=trip reason=close",
            NativeFunctionalDiagnostics.ended("trip",NativeFunctionalDiagnostics.End.CLOSE,null,null,0))
        assertEquals("native.social: ended client=trip reason=expired expiry_in_s=0",
            NativeFunctionalDiagnostics.ended("trip",NativeFunctionalDiagnostics.End.EXPIRED,null,-5,0))
    }

    @Test fun rateLimitAdmitsOncePerKeyPerIntervalAndReportsSkips() {
        var now=0L
        val limit=DiagnosticRateLimit({now},10_000)
        assertEquals(0,limit.admit("trip invalidated social_forbidden"))
        assertNull(limit.admit("trip invalidated social_forbidden"))
        assertEquals(0,limit.admit("climate invalidated social_forbidden"))
        now=9_999;assertNull(limit.admit("trip invalidated social_forbidden"))
        // A 13 s loop is never hidden: each cycle is past the interval.
        now=13_000;assertEquals(2,limit.admit("trip invalidated social_forbidden"))
        now=26_000;assertEquals(0,limit.admit("trip invalidated social_forbidden"))
    }
}
