package io.wegoh.app.nativeauth

import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File

class NativeNetLogTest {
    private val lines=ArrayList<String>()
    private val events=ArrayList<ClientDiagnosticEvent>()
    private lateinit var sink: (String)->Unit
    private lateinit var reports: (ClientDiagnosticEvent)->Unit
    private val trip="0123456789abcdef0123456789abcdef"
    private val car="fedcba9876543210fedcba9876543210"

    @Before fun capture() {
        sink=NativeNetLog.sink;reports=NativeNetLog.reports
        NativeNetLog.clientVersion=NativeNetLog.clientValue("0.4.0",4)
        NativeNetLog.sink={lines.add(it)};NativeNetLog.reports={events.add(it)}
        NativeNetLog.forget()
    }
    @After fun restore() {NativeNetLog.sink=sink;NativeNetLog.reports=reports;NativeNetLog.clientVersion=null;NativeNetLog.forget()}

    @Test fun headersCarryOnlyRandomCorrelationAndTheAppVersion() {
        val net=NativeNetLog.start("GET","/v1/native/trips/$trip?section=route")
        val headers=net.headers.toMap()
        assertEquals(setOf("X-Request-Id","traceparent","X-WegoH-Client"),headers.keys)
        // Server: REQUEST_ID [A-Za-z0-9][A-Za-z0-9._-]{7,63}, traceparent 00-<32 hex>-<16 hex>-<2 hex>.
        assertTrue(Regex("[A-Za-z0-9][A-Za-z0-9._-]{7,63}").matches(headers.getValue("X-Request-Id")))
        val parent=Regex("00-([0-9a-f]{32})-([0-9a-f]{16})-00").matchEntire(headers.getValue("traceparent"))!!
        assertEquals(net.traceId,parent.groupValues[1])
        assertTrue(parent.groupValues[1].any {it!='0'} && parent.groupValues[2].any {it!='0'})
        assertTrue(Regex("android/[0-9][0-9A-Za-z.+-]{0,31}").matches(headers.getValue("X-WegoH-Client")))
        headers.values.forEach {assertFalse(it.contains(trip))}
        val other=NativeNetLog.start("GET","/v1/social/overview")
        assertFalse(other.requestId==net.requestId || other.traceId==net.traceId)
    }

    @Test fun clientVersionUsesTheServerHeaderForm() {
        assertEquals("android/0.4.0+4",NativeNetLog.clientValue("0.4.0",4))
        assertEquals("android/0+4",NativeNetLog.clientValue("dev build",4))
    }

    @Test fun routesResolveToServerTemplatesWithoutIdentifiers() {
        fun route(method: String,path: String)=NativeRouteTemplates.match(method,path)
        assertEquals("/v1/native/trips/{id}",route("GET","/v1/native/trips/$trip?section=route"))
        assertEquals("/v1/native/trips/{id}/cars/{carId}/route-order",route("PUT","/v1/native/trips/$trip/cars/$car/route-order"))
        assertEquals("/v1/native/trips/{trip}/locations/me",route("POST","/v1/native/trips/$trip/locations/me"))
        assertEquals("/v1/social/rooms/join",route("POST","/v1/social/rooms/join"))
        assertEquals("/v1/social/history",route("GET","/v1/social/history?cursor=abc"))
        assertEquals("/v1/native/diagnostics",route("POST","/v1/native/diagnostics"))
        assertEquals("/v1/events",route("WS","/v1/events"))
        assertNull(route("GET","/v1/native/trips/$trip/unknown"))
        assertNull(route("DELETE","/v1/social/overview"))
        assertEquals("/v1/social/trips/{trip}/voice",route("WS","/v1/social/trips/$trip/voice"))
        assertEquals("/v1/social/rooms/{room}/voice",route("WS","/v1/social/rooms/$trip/voice"))
        assertEquals("/v1/device/client-reports",route("POST","/v1/device/client-reports"))
    }

    @Test fun everyFunctionalWireRouteIsListed() {
        val wire=JSONObject(File("src/main/assets/native_access_wire.json").readText())
        val functional=wire.getJSONObject("functional")
        val routes=functional.getJSONArray("nativeRoutes")
        val expected=(0 until routes.length()).map {routes.getJSONObject(it).let {r->r.getString("method")+" "+r.getString("path")}}+
            listOf(functional.getJSONObject("apis").getJSONObject("nativeGet"),wire.getJSONObject("courseOriginalRead"),wire.getJSONObject("courseRoutePreview"))
                .map {it.getString("method")+" "+it.getString("path")}
        val missing=expected.toSet()-NativeRouteTemplates.all.toSet()
        assertTrue("$missing",missing.isEmpty())
    }

    @Test fun oneLinePerExchangeWithoutIdentifiersOrValues() {
        val net=NativeNetLog.start("GET","/v1/native/trips/$trip")
        net.status=200
        NativeNetLog.finish(net,null)
        val line=lines.single()
        assertTrue(line,Regex("net: req_id=[0-9a-f]{32} trace_id=[0-9a-f]{32} method=GET route=/v1/native/trips/\\{id\\} "+
            "status=200 dur_ms=[0-9]+ result=ok reason=none").matches(line))
        assertFalse(line.contains(trip))
        assertTrue(events.isEmpty())
    }

    @Test fun unlistedPathsAreMasked() {
        val net=NativeNetLog.start("GET","/v1/social/rooms/$trip/unlisted?cursor=$car")
        NativeNetLog.finish(net,java.net.ConnectException("connect to 10.0.0.1 failed"))
        val line=lines.single()
        assertTrue(line,line.contains("route=/v1/social/rooms/{id}/unlisted ") && line.contains("result=network_error reason=ConnectException"))
        listOf(trip,car,"10.0.0.1").forEach {assertFalse(line.contains(it))}
        assertTrue("an unmounted route cannot be reported",events.isEmpty())
    }

    @Test fun transportFailuresAreClassifiedAndReported() {
        val timeout=NativeNetLog.start("GET","/v1/social/overview")
        NativeNetLog.finish(timeout,java.net.SocketTimeoutException("Read timed out"))
        val offline=NativeNetLog.start("POST","/v1/native/trips/$trip/locations/me")
        NativeNetLog.finish(offline,java.net.UnknownHostException("api-wegoh.devforest.io"))
        assertTrue(lines[0].contains("result=timeout reason=SocketTimeoutException"))
        assertTrue(lines[1].contains("result=network_error reason=UnknownHostException"))
        assertFalse(lines[1].contains("devforest"))
        assertEquals(listOf("timeout","network_error"),events.map {it.kind})
        assertEquals("/v1/native/trips/{trip}/locations/me",events[1].route)
        assertEquals(offline.requestId,events[1].requestId)
        assertNull(events[1].status)
    }

    @Test fun callTimeoutIsATimeoutAndOnlyARealCancelIsCancelled() {
        // OkHttp callTimeout: InterruptedIOException("timeout"); Call.cancel(): IOException("Canceled").
        assertEquals(NetResult.TIMEOUT,NativeNetLog.classify(null,java.io.InterruptedIOException("timeout")).first)
        assertEquals(NetResult.CANCELLED,NativeNetLog.classify(null,java.io.IOException("Canceled")).first)
        assertEquals(NetResult.CANCELLED,NativeNetLog.classify(null,java.io.InterruptedIOException()).first)
        assertEquals(NetResult.CANCELLED,NativeNetLog.classify(null,InterruptedException()).first)
        assertEquals(NetResult.NETWORK_ERROR,NativeNetLog.classify(null,java.io.IOException("unexpected end of stream")).first)
        val events=NativeNetLog.start("WS","/v1/events")
        NativeNetLog.finish(events,java.io.InterruptedIOException("timeout"))
        assertTrue(lines.single().contains("result=timeout reason=InterruptedIOException:callTimeout"))
        assertEquals(listOf("timeout"),this.events.map {it.kind})
    }

    @Test fun serverAnswersAreNotReportedAgain() {
        val net=NativeNetLog.start("GET","/v1/social/overview").also {it.status=503}
        NativeNetLog.finish(net,NativeApiClient.Failure(503,"NATIVE_REGISTRATION_UNAVAILABLE"))
        val social=NativeNetLog.start("GET","/v1/social/trips").also {it.status=409}
        NativeNetLog.finish(social,NativeSocialFailure(NativeSocialFailure.Kind.CONFLICT,409,serverErrorCode="TRIP_STATE_CONFLICT"))
        assertTrue(lines[0].contains("status=503") && lines[0].contains("result=http_error reason=NATIVE_REGISTRATION_UNAVAILABLE"))
        assertTrue(lines[1].contains("result=http_error reason=TRIP_STATE_CONFLICT"))
        assertTrue(events.isEmpty())
    }

    @Test fun aRejectedResponseNamesTheKeyAndRuleButNotTheValue() {
        val net=NativeNetLog.start("GET","/v1/native/trips/$trip?section=route").also {it.status=200}
        NativeNetLog.finish(net,null)
        NativeNetLog.decodeFailed(NativeTripFieldFailure("routePlan"))
        NativeNetLog.decodeFailed(NativeTripFieldFailure("routePlan"))
        assertEquals(2,lines.size)
        assertTrue(lines[1],lines[1].contains(" status=200 ") && lines[1].startsWith("net: req_id=${net.requestId} ") && lines[1].endsWith(
            "result=invalid_response reason=NativeTripFieldFailure:NATIVE_TRIP_FIELD_INVALID decode_path=routePlan decode_rule=unknown"))
        val event=events.single()
        assertEquals("invalid_response",event.kind)
        assertEquals(net.requestId,event.requestId)
        assertEquals(net.traceId,event.traceId)
        assertEquals(200,event.status)
        assertEquals("routePlan",event.decodePath)

        val parsed=NativeNetLog.start("GET","/v1/social/overview").also {it.status=200}
        NativeNetLog.finish(parsed,null)
        NativeNetLog.decodeFailed(org.json.JSONException("Value secret-title at title of type java.lang.String cannot be converted to int"))
        assertTrue(lines[3].contains("decode_path=$ decode_rule=type"))
        assertFalse(lines[3].contains("secret-title"))
        assertFalse(events[1].json().toString().contains("secret-title"))
    }

    @Test fun preconditionsAndStaleExchangesAreNotDecodeFailures() {
        NativeNetLog.decodeFailed(IllegalStateException("no exchange"))
        val net=NativeNetLog.start("GET","/v1/social/overview").also {it.status=200}
        NativeNetLog.finish(net,null)
        NativeNetLog.decodeFailed(IllegalArgumentException("bad input"))
        NativeNetLog.decodeFailed(IllegalStateException("later"))
        NativeNetLog.finish(NativeNetLog.start("GET","/v1/social/overview").also {it.status=200},null)
        NativeNetLog.forget()
        NativeNetLog.decodeFailed(IllegalStateException("unrelated"))
        assertEquals(2,lines.size)
        assertTrue(events.isEmpty())
    }

    @Test fun decodeRulesFollowTheServerVocabulary() {
        assertEquals("missing",NativeNetLog.rule(org.json.JSONException("No value for routePlan")))
        assertEquals("length",NativeNetLog.rule(IllegalStateException("NATIVE_RESPONSE_TOO_LARGE")))
        assertEquals("format",NativeNetLog.rule(IllegalStateException("NATIVE_JSON_RESPONSE_REQUIRED")))
        assertEquals("format",NativeNetLog.rule(java.time.format.DateTimeParseException("bad","x",0)))
        assertEquals("syntax",NativeNetLog.rule(org.json.JSONException("Unterminated object at 12")))
        assertEquals("unknown",NativeNetLog.rule(IllegalStateException("Check failed.")))
    }

    @Test fun socketsLogHandshakeRejectionAsHttpAndCloseAsOk() {
        val rejected=NativeNetLog.start("WS","/v1/events")
        NativeNetLog.socketFailed(rejected,java.net.ProtocolException("Expected HTTP 101 response but was '401 Unauthorized'"),401)
        val dropped=NativeNetLog.start("WS","/v1/events")
        dropped.status=101
        NativeNetLog.closed(dropped,1000)
        assertTrue(lines[0].contains("method=WS route=/v1/events status=401") && lines[0].contains("result=http_error reason=WS_HANDSHAKE_REJECTED"))
        assertTrue(lines[1].contains("status=101") && lines[1].contains("result=ok reason=close_1000"))
        assertTrue(events.isEmpty())
    }

    @Test fun reportsAboutReportsAreNeverQueued() {
        NativeNetLog.finish(NativeNetLog.start("POST",ClientDiagnostics.ROUTE),java.net.SocketTimeoutException())
        assertEquals(1,lines.size)
        assertTrue(events.isEmpty())
    }
}
