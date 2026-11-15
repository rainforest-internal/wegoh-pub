package io.wegoh.app.nativeauth

import android.test.InstrumentationTestCase
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject

@Suppress("DEPRECATION")
class NativeSocialCodecTest: InstrumentationTestCase() {
    fun testFunctionalHttpFailuresRetainAuthorityMeaningAndRedactDetails() {
        val forbidden=socialRequestFailure(NativeApiClient.Failure(403,"private fixture detail"),false)
        assertEquals(NativeSocialFailure.Kind.FORBIDDEN,forbidden.kind)
        assertEquals(403,forbidden.httpStatus)
        assertEquals("NATIVE_SOCIAL_FORBIDDEN",forbidden.message)
        assertNull(forbidden.cause)
        assertFalse(forbidden.mayHaveExecuted)
        assertEquals(NativeSocialFailure.Kind.AUTHORIZATION_REQUIRED,socialRequestFailure(NativeApiClient.Failure(401,"UNAUTHORIZED"),false).kind)
        assertEquals(NativeSocialFailure.Kind.AUTHORIZATION_REQUIRED,socialRequestFailure(NativeApiClient.Failure(503,"GRANT_EXPIRED"),false).kind)
        val unavailable=socialRequestFailure(NativeApiClient.Failure(503,"UNAVAILABLE",5),true)
        assertEquals(NativeSocialFailure.Kind.UNAVAILABLE,unavailable.kind)
        assertTrue(unavailable.mayHaveExecuted)
        assertEquals(5,unavailable.retryAfterSeconds)
        assertEquals(NativeSocialFailure.Kind.UNAVAILABLE,socialRequestFailure(java.net.SocketTimeoutException("private fixture detail"),false).kind)
        val stale=NativeSocialFailure(NativeSocialFailure.Kind.STALE)
        assertSame(stale,socialRequestFailure(stale,false))
    }
    private val account="team-"+"a".repeat(40)
    private val room="b".repeat(32)
    private val moment="2026-10-31T01:02:03.123456+00:00"
    private fun permissions(purposes: Set<FunctionalPurpose>,revision: Long=1)=FunctionalPermissions("c".repeat(32),"d".repeat(32),revision,
        System.currentTimeMillis()+60000,purposes,1,"e".repeat(64))
    private fun transport(value: JSONObject)=StrictNativeJson.parseBusiness(value.toString().toByteArray())
    private fun rejected(action: ()->Unit) {var rejected=false;try {action()}catch(_: Exception){rejected=true};assertTrue(rejected)}
    private fun review(kind: String,key: String)=JSONObject().put("kind",kind).put("key",key).put("state","private").put("checksum",JSONObject.NULL).put("requested",false)
    fun testOverviewKeepsUnapprovedSeparateFromEmptyAndRejectsForeignFields() {
        val permission=permissions(setOf(FunctionalPurpose.FRIENDS_READ,FunctionalPurpose.ROOMS_READ))
        val body=JSONObject().put("people",JSONArray()).put("friends",JSONArray().put(JSONObject().put("id",account).put("name","Synthetic").put("hasVehicle",false)))
            .put("requests",JSONArray()).put("blocks",JSONArray()).put("rooms",JSONArray()).put("history",JSONArray())
            .put("capabilities",JSONObject().put("friends",true).put("rooms",true).put("history",false).put("nativeReadOnly",true))
        val value=NativeSocialCodec.overview(transport(body),permission);assertEquals(1,value.friends.size);assertTrue(value.roomsAvailable);assertFalse(value.historyAvailable)
        val numeric=StrictNativeJson.parseBusiness("{\"nullable\":null,\"duration\":2.5e-1}".toByteArray())
        assertTrue(numeric.isNull("nullable"));assertEquals(0.25,numeric.getDouble("duration"),0.0)
        rejected {StrictNativeJson.parse("{\"nullable\":null}".toByteArray())}
        rejected {StrictNativeJson.parse("{\"duration\":0.25}".toByteArray())}
        for(raw in listOf("{\"a\":null,\"a\":1}","{\"a\":1e999}","{\"a\":NaN}","{\"a\":Infinity}","{\"a\":01}","{\"a\":1.}"))
            rejected {StrictNativeJson.parseBusiness(raw.toByteArray())}
        assertFalse(value.toString().contains("Synthetic"));assertFalse(value.friends[0].toString().contains(account))
        rejected {NativeSocialCodec.overview(JSONObject(body.toString()).put("extra",true),permission)}
        rejected {NativeSocialCodec.overview(JSONObject(body.toString()).put("people",JSONArray().put(JSONObject().put("id",account).put("name","Synthetic"))),permission)}
        rejected {NativeSocialCodec.overview(JSONObject(body.toString()).apply {getJSONObject("capabilities").put("friends",false)},permission)}
    }
    fun testRoomAcceptsFloatingDurationAndSelectedPlaceButRejectsAuthorityFallback() {
        val permission=permissions(setOf(FunctionalPurpose.ROOMS_READ))
        val signal="f".repeat(32)
        val body=JSONObject().put("name","Synthetic room").put("review",review("room",room)).put("courseId",JSONObject.NULL).put("courseVersion",JSONObject.NULL)
            .put("preference","balanced").put("id",room).put("ownerId",account).put("expiresAt",moment).put("serverNow",moment).put("expiresInSeconds",0.25)
            .put("course",JSONObject.NULL).put("role","member").put("nativeReadOnly",true)
            .put("members",JSONArray().put(JSONObject().put("id",account).put("name","Synthetic").put("role","member")))
            .put("signals",JSONArray().put(JSONObject().put("kind","rest").put("destination",JSONObject().put("name","Selected fixture place").put("latitude",37.0).put("longitude",127.0))
                .put("review",review("room-place",room+":"+signal)).put("id",signal).put("accountId",account).put("createdAt",moment)
                .put("votes",JSONObject().put("agree",0).put("pass",1)).put("myVote",JSONObject.NULL)))
        val value=NativeSocialCodec.room(transport(body),room,permission);assertEquals(0.25,value.expiresInSeconds,0.0);assertEquals(37.0,value.signals[0].destination!!.latitude,0.0)
        rejected {NativeSocialCodec.room(JSONObject(body.toString()).put("expiresInSeconds",true),room,permission)}
        rejected {NativeSocialCodec.room(JSONObject(body.toString()).put("inviteUri","https://example.invalid"),room,permission)}
        rejected {NativeSocialCodec.room(JSONObject(body.toString()).put("id","a".repeat(32)),room,permission)}
    }
    fun testHistoryPaginationPreservesNullsAndClosesCursor() {
        val permission=permissions(setOf(FunctionalPurpose.HISTORY_READ));val id="1".repeat(32)
        val summary=JSONObject().put("id",id).put("title","Synthetic record").put("ownerId",account).put("ownerName",JSONObject.NULL).put("own",true)
            .put("createdAt",moment).put("updatedAt",moment).put("startedAt",moment).put("endedAt",JSONObject.NULL)
            .put("courseId",JSONObject.NULL).put("courseVersion",JSONObject.NULL).put("revision",1).put("permissionRevision",JSONObject.NULL)
            .put("review",review("history",id)).put("visitCount",0).put("tracePointCount",0).put("sharedWith",JSONArray())
        val cursor=Base64.encodeToString(JSONObject().put("updatedAt",moment).put("id",id).toString().toByteArray(),Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)
        val cap=JSONObject().put("history",true).put("historyRemix",false).put("historyTraceIngest",false).put("historyPhotos",false)
            .put("historyPhotoUpload",false).put("historyReplay",true).put("historyExport",false).put("cautions",false)
        val body=JSONObject().put("history",JSONArray().put(summary)).put("friends",JSONArray()).put("nextCursor",cursor).put("nativeReadOnly",true).put("capabilities",cap)
        val value=NativeSocialCodec.historyPage(transport(body),permission,account);assertNull(value.history[0].ownerName);assertNull(value.history[0].endedAt);assertNotNull(value.nextCursor)
        rejected {NativeSocialCodec.cursor(cursor+"&access_token=synthetic")}
        val duplicate="{\"updatedAt\":\"$moment\",\"updatedAt\":\"$moment\",\"id\":\"$id\"}"
        rejected {NativeSocialCodec.cursor(Base64.encodeToString(duplicate.toByteArray(),Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING))}
        rejected {NativeSocialCodec.historyPage(JSONObject(body.toString()).apply {getJSONArray("history").getJSONObject(0).put("permissionRevision",1)},permission,account)}
    }
    fun testEqualPermissionProjectionKeepsStampButChangedAuthorityInvalidates() {
        val gate=FunctionalPermissionGate();val purposes=setOf(FunctionalPurpose.ROOMS_READ,FunctionalPurpose.ROOMS_INTERACT)
        val first=permissions(purposes);gate.replace(first);val stamp=gate.stamp(purposes,emptySet(),System.currentTimeMillis())
        val equal=FunctionalPermissions(first.deviceId,first.grantId,first.revision,first.expiresAtMillis,purposes,first.disclosureVersion,first.disclosureSha256)
        assertFalse(gate.replace(equal));assertTrue(gate.current(stamp,System.currentTimeMillis()))
        assertTrue(gate.replace(permissions(setOf(FunctionalPurpose.ROOMS_READ),2)));assertFalse(gate.current(stamp,System.currentTimeMillis()))
        rejected {gate.stamp(purposes,emptySet(),System.currentTimeMillis())}
    }
}
