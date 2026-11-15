package io.wegoh.app.nativeauth

import org.junit.Assert.*
import org.junit.Test

class ClientDiagnosticsTest {
    @Test fun masksIdentifiersTokensPlacesAndTitles() {
        val line="climate.receiver: inbox requested account_ref=0123456789ab deviceId=${"d".repeat(32)} "+
            "at 37.56651,127.12345 title=\"Jeju trip\" 제주 여행 https://example.test/x?q=1 "+
            "Bearer abc.def eyJhbGciOiJIUzI1NiJ9abc1234567 a@b.co 0f8fad5b-d9cb-469f-a165-70867728950e"
        val masked=ClientDiagnostics.mask(line)
        for(secret in listOf("0123456789ab","d".repeat(32),"37.56651","127.12345","Jeju","제주","example.test",
            "abc.def","eyJhbGci","a@b.co","0f8fad5b"))assertFalse(secret,masked.contains(secret))
        val kept="trip.detail: load failed reason=invalid_field trip=1a2b3c4d status=0 field=routePlan"
        assertEquals(kept,ClientDiagnostics.mask(kept))
        assertEquals(masked,ClientDiagnostics.mask(masked))
        assertEquals(ClientDiagnostics.MAX_LINE_CHARS,ClientDiagnostics.mask("x".repeat(500)).length)
    }

    @Test fun ringKeepsNewestLinesWithinLineAndByteLimits() {
        val ring=DiagnosticRing(maxLines=3,maxBytes=1000)
        (1..5).forEach {ring.add("line $it")}
        assertEquals(listOf("line 3","line 4","line 5"),ring.snapshot())
        val bytes=DiagnosticRing(maxLines=60,maxBytes=500)
        repeat(10) {bytes.add("x ".repeat(100)+it)}
        assertEquals(2,bytes.snapshot().size)
        assertTrue(bytes.snapshot().last().endsWith("9"))
        val masked=DiagnosticRing()
        masked.add("token=secret-value")
        assertEquals(listOf("token={masked}"),masked.snapshot())
    }

    @Test fun bodyIsBoundedAndCarriesOnlyFixedForms() {
        val lines=List(60) {"\"\\".repeat(100)}
        val body=ClientDiagnostics.body("trip.detail",ClientFailure("invalid_field","GET /v1/native/trips/{id}"),"0.4.0",4,lines)
        assertTrue(body.toString().toByteArray(Charsets.UTF_8).size<=ClientDiagnostics.MAX_BODY_BYTES)
        assertTrue(body.getJSONArray("lines").length()<60)
        assertEquals(setOf("reportVersion","screen","reason","requestTemplate","appVersion","appBuild","lines"),body.keys().asSequence().toSet())
        assertEquals("GET /v1/native/trips/{id}",body.getString("requestTemplate"))
        val unknown=ClientDiagnostics.body("trip.list",ClientFailure("not a word","GET https://x"),"0.4.0",4,listOf("lat=37.123456"))
        assertEquals("unknown",unknown.getString("reason"))
        assertTrue(unknown.isNull("requestTemplate"))
        assertEquals("lat={masked}",unknown.getJSONArray("lines").getString(0))
        assertTrue(ClientDiagnostics.body("account.profile",null,"0.4.0",4,emptyList()).isNull("requestTemplate"))
        assertThrows(IllegalArgumentException::class.java) {ClientDiagnostics.body("Bad Screen",null,"0.4.0",4,emptyList())}
    }

    @Test fun tripFailuresKeepDecodeFieldAndRecordHttpTemplates() {
        val written=mutableListOf<String>()
        WegoLog.logcat={_,_,message->written+=message}
        val trip="a".repeat(32)
        assertThrows(NativeTripFieldFailure::class.java) {
            TripLoadDiagnostics.decode("trip.report.test",trip,"GET /v1/native/trips/{id}") {throw NativeTripFieldFailure("routePlan")}
        }
        assertEquals(ClientFailure("invalid_field","GET /v1/native/trips/{id}"),ClientDiagnostics.failure("trip.report.test"))
        assertEquals(listOf("trip.report.test: load failed reason=invalid_field trip=aaaaaaaa field=routePlan"),written)
        // The same failure arrives at the repository as a local INVALID_RESPONSE without a template.
        TripLoadDiagnostics.recordFailure("trip.report.test",NativeSocialFailure(NativeSocialFailure.Kind.INVALID_RESPONSE))
        assertEquals("invalid_field",ClientDiagnostics.failure("trip.report.test")?.reason)
        TripLoadDiagnostics.recordFailure("trip.report.test",NativeSocialFailure(NativeSocialFailure.Kind.UNAVAILABLE,503,
            requestTemplate="GET /v1/native/trips/{id}"))
        assertEquals(ClientFailure("unavailable","GET /v1/native/trips/{id}"),ClientDiagnostics.failure("trip.report.test"))
    }
}
