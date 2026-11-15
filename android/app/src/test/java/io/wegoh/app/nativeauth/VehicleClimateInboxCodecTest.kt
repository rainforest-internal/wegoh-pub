package io.wegoh.app.nativeauth

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class VehicleClimateInboxCodecTest {
    @Test fun routeDiagnosticsIdentifyTheVerifiedPrincipalWithoutLoggingRawIdentifiers() {
        val permissions=FunctionalPermissions("private-device","private-grant",7,Long.MAX_VALUE,
            setOf(FunctionalPurpose.DEVICE_COMMANDS_RECEIVE),1,"disclosure")
        val log=vehicleClimateInboxRoute("api.example.test","private-owner",permissions)
        assertTrue(log.contains("host=api.example.test"))
        assertTrue(log.contains("functional_revision=7 token_source=connection_credentials"))
        assertFalse(log.contains("private-"))
        for(field in listOf("account_ref","device_ref","grant_ref"))assertTrue(Regex("$field=[a-f0-9]{12}( |$)").containsMatchIn(log))
        assertEquals(log,vehicleClimateInboxRoute("api.example.test","private-owner",permissions))
        assertNotEquals(log,vehicleClimateInboxRoute("api.example.test","another-owner",permissions))
    }

    private fun row(number: Int)=JSONObject().put("id",number.toString(16).padStart(32,'0'))
        .put("capabilityId","hvac.fan").put("capabilityRevision",1).put("roomId",JSONObject.NULL)
        .put("stage","queued").put("createdAt","2026-11-06T06:10:12.123456Z")
    private fun body(vararg rows: JSONObject)=JSONObject().put("requests",JSONArray(rows.toList()))
        .put("supportedControlActions",JSONArray().put(JSONObject().put("id","hvac.fan").put("revision",1)))

    @Test fun displayMetadataIsOptionalAndInvalidLabelsAreNeverPublished() {
        val requester="team-"+"a".repeat(40)
        val value=body(row(1).put("requesterId",requester).put("expiresAt","1970-01-01T00:00:05Z"))
            .put("serverNow","1970-01-01T00:00:01Z")
        value.getJSONArray("supportedControlActions").getJSONObject(0).put("label","풍량")
        val inbox=decodeVehicleClimateInbox(value)
        assertEquals(requester,inbox.requests.single().requesterId)
        assertEquals(5000L,inbox.requests.single().expiresAtMillis)
        assertEquals(1000L,inbox.serverNowMillis);assertEquals("풍량",inbox.labels["hvac.fan"])
        value.getJSONArray("requests").getJSONObject(0).put("requesterId","invalid-private").put("expiresAt","invalid-private")
        value.getJSONArray("supportedControlActions").getJSONObject(0).put("label","invalid\nprivate")
        val fallback=decodeVehicleClimateInbox(value)
        assertNull(fallback.requests.single().requesterId);assertNull(fallback.requests.single().expiresAtMillis)
        assertTrue(fallback.labels.isEmpty())
    }

    @Test fun emptyServerResponseIsLoggedBeforeHostFiltering() {
        val logs=mutableListOf<String>()
        val inbox=decodeVehicleClimateInbox(body()) {logs+=it}
        assertTrue(inbox.requests.isEmpty())
        assertTrue(logs.first().contains("received_rows=0"))
        assertTrue(logs.last().contains("decoded_rows=0 discarded_rows=0"))
    }

    @Test fun serverTimestampIsLoggedWithoutChangingOptionalMetadataValidation() {
        val logs=mutableListOf<String>()
        decodeVehicleClimateInbox(body().put("serverNow","1970-01-01T00:00:01Z")) {logs+=it}
        assertTrue(logs.first().contains("server_time_ms=1000"))
        logs.clear()
        decodeVehicleClimateInbox(body().put("serverNow","private-invalid-time")) {logs+=it}
        assertTrue(logs.first().contains("server_time_ms=-1"))
        assertFalse(logs.joinToString().contains("private-invalid-time"))
    }

    @Test fun nullMissingAndNonNullRoomFieldsAreDistinguishedWithoutDroppingRows() {
        val logs=mutableListOf<String>()
        val missing=row(2).apply {remove("roomId")}
        val room=row(3).put("roomId","private-room")
        val nullText=row(4).put("roomId","null")
        val inbox=decodeVehicleClimateInbox(body(row(1),missing,room,nullText)) {logs+=it}
        assertEquals(4,inbox.requests.size)
        assertEquals(listOf(true,false,false,false),inbox.requests.map {it.friendRemote})
        assertEquals(1,inbox.queuedFriendRequests().size)
        assertTrue(logs.last().contains("received_rows=4 decoded_rows=4 discarded_rows=0"))
        assertTrue(logs.last().contains("room_null=1 room_missing=1 room_other=2"))
        assertFalse(logs.joinToString().contains("private-room"))
    }

    @Test fun stagesArePreservedAndMicrosecondTimestampsAcceptUtcOffsets() {
        val first=row(1)
        val equivalent=row(2).put("stage","delivered").put("createdAt","2026-11-06T15:10:12.123456+09:00")
        val logs=mutableListOf<String>()
        val inbox=decodeVehicleClimateInbox(body(first,equivalent)) {logs+=it}
        assertEquals(inbox.requests.first().createdAtMillis,inbox.requests.last().createdAtMillis)
        assertEquals(listOf("queued","delivered"),inbox.requests.map {it.stage})
        assertTrue(logs.last().contains("queued_rows=1 other_stage_rows=1"))
    }

    @Test fun malformedRowsRejectTheResponseAndLogTheFieldInsteadOfReturningAnEmptyInbox() {
        val changes=listOf(
            "invalid_created_at" to {value: JSONObject->value.put("createdAt","private-invalid-date")},
            "invalid_stage" to {value: JSONObject->value.apply {remove("stage")}},
            "invalid_request_id" to {value: JSONObject->value.put("id","private-invalid-id")},
            "invalid_capability_revision" to {value: JSONObject->value.put("capabilityRevision","private-invalid-revision")}
        )
        for((reason,change)in changes) {
            val logs=mutableListOf<String>()
            assertTrue(runCatching {decodeVehicleClimateInbox(body(row(1),change(row(2)))) {logs+=it}}.isFailure)
            assertTrue(logs.last().contains("received_rows=2 decoded_rows=1 discarded_rows=2 row_index=1 reason=$reason"))
            assertFalse(logs.joinToString().contains("private-invalid"))
            assertFalse(logs.any {it.contains("inbox parsed")})
        }
    }

    @Test fun duplicateRequestsAndInvalidDescriptorsRemainResponseFailures() {
        val logs=mutableListOf<String>()
        assertTrue(runCatching {decodeVehicleClimateInbox(body(row(1),row(1))) {logs+=it}}.isFailure)
        assertTrue(logs.last().contains("reason=duplicate_request_id"))
        logs.clear()
        val invalid=body(row(1)).put("supportedControlActions",JSONArray().put(JSONObject().put("id","hvac.fan").put("revision",0)))
        assertTrue(runCatching {decodeVehicleClimateInbox(invalid) {logs+=it}}.isFailure)
        assertTrue(logs.last().contains("discarded_rows=1"))
        assertTrue(logs.last().contains("reason=invalid_descriptor"))
    }
}
