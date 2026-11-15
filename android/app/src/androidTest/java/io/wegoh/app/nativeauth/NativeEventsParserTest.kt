package io.wegoh.app.nativeauth

import android.test.InstrumentationTestCase

class NativeEventsParserTest: InstrumentationTestCase() {
    fun testVersionedFramesKeepExactFieldsSequenceAndOpaqueVersions() {
        val key="trip."+"a".repeat(32)+".location"
        val parser=NativeEventParser(setOf("account:read","device:self:manage"),fine=true)
        val first="""{"type":"snapshot","epoch":"0123456789abcdef","seq":0,"versions":{"devices":"${"1".repeat(32)}","$key":"${"2".repeat(32)}"}}"""
        assertEquals(listOf("devices",key),parser.decode(first).resources)
        for(bad in listOf(
            """{"type":"invalidate","epoch":"0123456789abcdef","seq":2,"versions":{"$key":null}}""",
            """{"type":"invalidate","epoch":"0123456789abcdef","seq":1,"versions":{"private-name":"${"1".repeat(32)}"}}""",
            """{"type":"invalidate","epoch":"0123456789abcdef","seq":1,"versions":{"$key":"coordinates"}}""")) {
            try {parser.decode(bad);fail("Invalid version frame accepted")}catch(expected: IllegalStateException){}
        }
        assertEquals(mapOf(key to null),parser.decode("""{"type":"invalidate","epoch":"0123456789abcdef","seq":1,"versions":{"$key":null}}""").versions)
    }
    fun testEventOpenFailuresSeparateTransportAndAuthorityWithoutLeakingCause() {
        val input=listOf(
            java.net.SocketTimeoutException("private fixture detail") to NativeEventsFailure.Kind.TRANSPORT,
            java.net.ConnectException("private fixture detail") to NativeEventsFailure.Kind.TRANSPORT,
            NativeApiClient.Failure(503,"UNAVAILABLE") to NativeEventsFailure.Kind.TRANSPORT,
            NativeApiClient.Failure(401,"AUTHENTICATION_REQUIRED") to NativeEventsFailure.Kind.AUTHORITY,
            NativeApiClient.Failure(403,"FORBIDDEN") to NativeEventsFailure.Kind.AUTHORITY,
            NativeApiClient.Failure(503,"GRANT_EXPIRED") to NativeEventsFailure.Kind.AUTHORITY,
            javax.net.ssl.SSLHandshakeException("private fixture detail") to NativeEventsFailure.Kind.INVALID_RESPONSE,
            java.net.ProtocolException("private fixture detail") to NativeEventsFailure.Kind.INVALID_RESPONSE,
            IllegalStateException("private fixture detail") to NativeEventsFailure.Kind.INVALID_RESPONSE
        )
        for((error,expected) in input) {
            val failure=NativeEventsFailure.from(error)
            assertEquals(expected,failure.kind)
            assertEquals("NATIVE_EVENTS_UNAVAILABLE",failure.message)
            assertNull(failure.cause)
        }
        assertEquals(NativeEventsFailure.Kind.AUTHORITY,NativeEventsFailure.http(401).kind)
        assertEquals(NativeEventsFailure.Kind.AUTHORITY,NativeEventsFailure.http(403).kind)
        assertEquals(NativeEventsFailure.Kind.TRANSPORT,NativeEventsFailure.http(503).kind)
        assertEquals(NativeEventsFailure.Kind.INVALID_RESPONSE,NativeEventsFailure.http(302).kind)
    }
    fun testScopeClosedResourcesAndContiguousSequence() {
        val minimal=setOf("account:read","device:self:manage")
        fun snapshot(resources: String)="""{"type":"snapshot","epoch":"0123456789abcdef","seq":0,"resources":$resources}"""
        val minimalParser=NativeEventParser(minimal)
        assertEquals(listOf("devices"),minimalParser.decode(snapshot("[\"devices\"]")).resources)
        for(bad in listOf("[\"courses\",\"devices\"]","[\"devices\",\"friends\"]","[\"devices\",\"rooms\"]")) {
            try {NativeEventParser(minimal).decode(snapshot(bad));fail("Unapproved resource accepted")}catch(expected: IllegalStateException){}
        }
        val parser=NativeEventParser(minimal+"courses:read")
        parser.decode(snapshot("[\"courses\",\"devices\"]"))
        for(seq in listOf(0,2)) {
            try {parser.decode("""{"type":"invalidate","epoch":"0123456789abcdef","seq":$seq,"resources":["courses"]}""");fail("Gap/repeat accepted")}catch(expected: IllegalStateException){}
        }
        assertEquals(listOf("courses"),parser.decode("""{"type":"invalidate","epoch":"0123456789abcdef","seq":1,"resources":["courses"]}""").resources)
        try {parser.decode("""{"type":"invalidate","epoch":"fedcba9876543210","seq":2,"resources":["courses"]}""");fail("Epoch change accepted")}catch(expected: IllegalStateException){}
    }
}
