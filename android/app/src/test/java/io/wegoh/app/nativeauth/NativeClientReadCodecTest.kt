package io.wegoh.app.nativeauth

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.util.Base64

class NativeClientReadCodecTest {
    private val id="a".repeat(32)
    private val room="b".repeat(32)
    private val trackId="c".repeat(32)
    private val owner="team-"+"d".repeat(40)
    private val time="2026-11-01T00:00:00Z"
    private fun reject(action: ()->Unit) {
        try {action();fail("invalid projection must fail")} catch(_: IllegalStateException) {}
        catch(_: IllegalArgumentException) {}
        catch(_: org.json.JSONException) {}
        catch(_: java.time.format.DateTimeParseException) {}
    }
    private fun permission(vararg purposes: FunctionalPurpose)=FunctionalPermissions(id,room,1,Long.MAX_VALUE,
        purposes.toSet(),1,"0".repeat(64))
    private fun review(kind: String,key: String)=JSONObject().put("kind",kind).put("key",key).put("state","private")
        .put("checksum",JSONObject.NULL).put("requested",false)
    private fun track()=JSONObject().put("id",trackId).put("title","함께 듣는 곡").put("url","https://www.melon.com/song/detail.htm?songId=10000001")
    private fun music()=JSONObject().put("revision",1).put("canEdit",false).put("nativeReadOnly",true)
        .put("selection",JSONObject().put("id",id).put("ownerId",owner).put("playlistId",room).put("playlistRevision",2)
            .put("currentTrackId",trackId).put("name","여행 음악").put("tracks",JSONArray().put(track()))
            .put("review",review("room-music","$room:$id")))
    @Test fun roomMusicReadsMetadataAndEmptySelectionWithoutPlaybackAuthority() {
        val selection=NativeSocialCodec.roomMusic(music(),room).selection!!
        assertEquals("여행 음악",selection.name);assertEquals(trackId,selection.currentTrackId)
        assertEquals("함께 듣는 곡",selection.tracks.single().title)
        assertTrue(selection.tracks.single().url.startsWith("https://"))
        assertNull(NativeSocialCodec.roomMusic(music().put("selection",JSONObject.NULL),room).selection)
        val editable=music().put("canEdit",true).put("nativeReadOnly",false)
        assertEquals(selection.id,NativeSocialCodec.roomMusic(editable,room).selection!!.id)
    }
    @Test fun roomMusicRejectsUnsafeLinksDuplicatesWrongReviewAndUnboundedMetadata() {
        for(url in listOf("http://example.com/song","https://user:secret@example.com/song","https://example.com:444/song",
            "file:///song","https://example.com/a b","https:///song")) {
            val value=music();value.getJSONObject("selection").getJSONArray("tracks").getJSONObject(0).put("url",url)
            reject {NativeSocialCodec.roomMusic(value,room)}
        }
        val duplicate=music();duplicate.getJSONObject("selection").getJSONArray("tracks").put(track())
        reject {NativeSocialCodec.roomMusic(duplicate,room)}
        reject {NativeSocialCodec.roomMusic(music(),"0".repeat(32))}
        val unknown=music();unknown.getJSONObject("selection").put("currentTrackId","0".repeat(32))
        reject {NativeSocialCodec.roomMusic(unknown,room)}
        val longTitle=music();longTitle.getJSONObject("selection").getJSONArray("tracks").getJSONObject(0).put("title","x".repeat(121))
        reject {NativeSocialCodec.roomMusic(longTitle,room)}
        val tooMany=music();tooMany.getJSONObject("selection").put("tracks",JSONArray().apply {repeat(101){put(track())}})
        reject {NativeSocialCodec.roomMusic(tooMany,room)}
        reject {NativeSocialCodec.roomMusic(music().put("playbackUrl","https://example.com/audio"),room)}
    }
    private fun capabilities()=JSONObject().put("history",true).put("historyRemix",false).put("historyTraceIngest",false)
        .put("historyPhotos",false).put("historyPhotoUpload",false).put("historyReplay",true).put("historyExport",false).put("cautions",false)
    private fun summary()=JSONObject().put("id",id).put("title","여행 기록").put("ownerId",owner).put("ownerName","나").put("own",true)
        .put("createdAt",time).put("updatedAt",time).put("startedAt",time).put("endedAt",JSONObject.NULL)
        .put("courseId",JSONObject.NULL).put("courseVersion",JSONObject.NULL).put("revision",1).put("permissionRevision",JSONObject.NULL)
        .put("review",review("history",id)).put("visitCount",0).put("tracePointCount",0).put("sharedWith",JSONArray())
    private fun source()=JSONObject().put("kind","device-reported").put("actorId",owner).put("receivedAt",time)
    private fun detail()=summary().put("permissions",JSONObject.NULL).put("grants",JSONArray()).put("source",source())
        .put("course",JSONObject.NULL).put("capabilities",capabilities()).put("nativeReadOnly",true)
        .put("access",JSONObject().put("visits",true).put("trace",true).put("photos",true)).put("visits",JSONArray()).put("traceBatches",JSONArray())
    private fun visit()=JSONObject().put("id",trackId).put("place",JSONObject().put("name","첫 장소").put("latitude",37.5).put("longitude",127.0))
        .put("visitedAt",time).put("review","직접 남긴 기록\n두 번째 줄").put("rating",4).put("source",source()).put("photos",JSONArray())
    private fun point()=JSONObject().put("latitude",37.5).put("longitude",127.0).put("capturedAt",time).put("accuracyMeters",JSONObject.NULL)
    private fun populated()=detail().put("visitCount",1).put("tracePointCount",1).put("visits",JSONArray().put(visit()))
        .put("traceBatches",JSONArray().put(JSONObject().put("id",room).put("streamId",trackId).put("label","보고한 경로")
            .put("source",source()).put("points",JSONArray().put(point()))))
    @Test fun historyDetailReadsExactOwnedOrSharedProjectionAndPreservesUnverifiedSource() {
        val parsed=NativeSocialCodec.historyDetail(populated(),id,permission(FunctionalPurpose.HISTORY_READ),owner)
        assertEquals("첫 장소",parsed.visits.single().place.name)
        assertEquals("device-reported",parsed.source.kind);assertNull(parsed.traces.single().points.single().accuracyMeters)
        assertEquals(1,parsed.summary.tracePointCount)
        val shared=detail().put("own",false)
        assertFalse(NativeSocialCodec.historyDetail(shared,id,permission(FunctionalPurpose.HISTORY_READ),"team-"+"e".repeat(40)).summary.own)
        assertTrue(NativeSocialCodec.historyDetail(detail(),id,permission(FunctionalPurpose.HISTORY_READ),owner).visits.isEmpty())
    }
    @Test fun historyDetailRejectsCrossRecordPrivateFieldsInvalidCoordinatesAndAclMismatch() {
        val permission=permission(FunctionalPurpose.HISTORY_READ)
        reject {NativeSocialCodec.historyDetail(detail(),room,permission,owner)}
        reject {NativeSocialCodec.historyDetail(detail().put("own",false),id,permission,owner)}
        reject {NativeSocialCodec.historyDetail(detail().put("permissions",JSONObject().put("collectTrace",true)),id,permission,owner)}
        reject {NativeSocialCodec.historyDetail(detail().put("grants",JSONArray().put(JSONObject())),id,permission,owner)}
        val photos=populated();photos.getJSONArray("visits").getJSONObject(0).getJSONArray("photos").put(JSONObject())
        reject {NativeSocialCodec.historyDetail(photos,id,permission,owner)}
        val invalid=populated();invalid.getJSONArray("visits").getJSONObject(0).getJSONObject("place").put("latitude",91)
        reject {NativeSocialCodec.historyDetail(invalid,id,permission,owner)}
        val denied=populated();denied.getJSONObject("access").put("visits",false)
        reject {NativeSocialCodec.historyDetail(denied,id,permission,owner)}
        val duplicate=populated();duplicate.getJSONArray("visits").put(visit());duplicate.put("visitCount",2)
        reject {NativeSocialCodec.historyDetail(duplicate,id,permission,owner)}
        val reversed=populated();reversed.getJSONArray("traceBatches").getJSONObject(0).getJSONArray("points").put(point())
        reversed.put("tracePointCount",2)
        reject {NativeSocialCodec.historyDetail(reversed,id,permission,owner)}
        reject {NativeSocialCodec.historyDetail(populated().put("tracePointCount",2),id,permission,owner)}
    }
    private fun cursor(raw: String)=Base64.getUrlEncoder().withoutPadding().encodeToString(raw.toByteArray(Charsets.UTF_8))
    private fun page(items: JSONArray,next: String?)=JSONObject().put("history",items).put("friends",JSONArray())
        .put("nextCursor",next ?: JSONObject.NULL).put("nativeReadOnly",true).put("capabilities",capabilities())
    @Test fun historyPagesConsumeOnlyTheDeclaredServerCursor() {
        val encodedCursor=cursor("""{"updatedAt":"2026-11-01T00:00:00+00:00","id":"$id"}""")
        val permission=permission(FunctionalPurpose.HISTORY_READ)
        val first=NativeSocialCodec.historyPage(page(JSONArray().put(summary()),encodedCursor),permission,owner)
        assertEquals("/v1/social/history?cursor=$encodedCursor",NativeApiClient.socialHistoryPath(first.nextCursor!!.encoded))
        val last=NativeSocialCodec.historyPage(page(JSONArray(),null),permission,owner)
        assertNull(last.nextCursor);assertTrue(last.history.isEmpty())
        for(bad in listOf("", "A", "x".repeat(257), "$encodedCursor&limit=1", "$encodedCursor=", cursor("""{"updatedAt":"2026-11-01","id":"$id"}"""),
            cursor("""{"updatedAt":"$time","id":"$id","id":"$room"}"""),cursor("""{"updatedAt":"$time","id":"$id","limit":1}"""))) {
            reject {NativeApiClient.socialHistoryPath(bad)}
        }
        reject {NativeSocialCodec.historyPage(page(JSONArray().apply {repeat(51){put(summary())}},null),permission,owner)}
    }
    @Test fun businessPathsCannotWidenIntoWritesQueriesAbsoluteUrlsOrSiblingResources() {
        for(path in listOf("/v1/native/rooms/$room/missions","/v1/native/trips/$room/missions","/v1/social/rooms/$room/music","/v1/social/history/$id",
            "/v1/device/command-inbox?view=status"))
            NativeApiClient.requireBusinessReadPath(path)
        assertEquals("/v1/native/rooms/$room/missions/$id/progress",NativeApiClient.missionProgressPath(room,id))
        for(path in listOf("/v1/social/rooms/$room/music?cursor=a","/v1/social/rooms/$room/music/reports",
            "/v1/social/history/$id/visits","/v1/social/history?cursor=a","/v1/social/history/$id#fragment",
            "/v1/social/history/${id.uppercase()}","https://api-wegoh.devforest.io/v1/social/history/$id",
            "/v1/native/rooms/$room/missions/$id/progress","/v1/social/rooms/../music",
            "/v1/native/trips/$room/missions/$id/progress","/v1/native/trips/$room/missions?room=other",
            "/v1/native/trips/../missions","/v1/device/command-inbox?view=status&deviceId=$id"))reject {NativeApiClient.requireBusinessReadPath(path)}
        reject {NativeApiClient.missionProgressPath("../rooms",id)}
        reject {NativeApiClient.missionProgressPath(room,"$id?token=a")}
    }
    @Test fun commandStatusKeepsTripAndRoomRowsBoundToCurrentReceiver() {
        fun row(commandId: String,roomId: Any,stage: String)=JSONObject().put("id",commandId).put("roomId",roomId)
            .put("targetDeviceId",id).put("ownerId",owner).put("requesterId",owner).put("capabilityId","hvac.temperature")
            .put("capabilityRevision",1).put("stage",stage).put("createdAt",time).put("expiresAt",time)
            .put("mayHaveExecuted",true).put("physicalExecutionVerified",false)
        fun snapshot(vararg rows: JSONObject)=JSONObject().put("serverNow",time).put("supportedControlActions",JSONArray())
            .put("requests",JSONArray(rows.toList()))
        val confirmed=row(trackId,JSONObject.NULL,"state-confirmed")
        val queued=row(room,room,"queued")
        assertEquals(listOf(trackId,room),NativeBusinessCodec.commands(snapshot(confirmed,queued),id,owner).commands.map {it.id})
        assertEquals(BusinessCommand.Stage.STATE_CONFIRMED,NativeBusinessCodec.commands(snapshot(confirmed),id,owner).commands.single().stage)
        reject {NativeBusinessCodec.commands(snapshot(confirmed,confirmed),id,owner)}
        reject {NativeBusinessCodec.commands(snapshot(confirmed),room,owner)}
        reject {NativeBusinessCodec.commands(snapshot(confirmed),id,"team-"+"e".repeat(40))}
        confirmed.remove("roomId")
        reject {NativeBusinessCodec.commands(snapshot(confirmed),id,owner)}
    }
    @Test fun musicRequiresBothPurposesAndProgressRequiresSeparateWriteConsent() {
        val gate=FunctionalPermissionGate()
        val music=setOf(FunctionalPurpose.ROOMS_READ,FunctionalPurpose.ROOM_MUSIC_READ)
        val progress=setOf(FunctionalPurpose.ROOMS_READ,FunctionalPurpose.MISSIONS_READ,FunctionalPurpose.MISSIONS_PROGRESS)
        for(approved in listOf(emptySet(),setOf(FunctionalPurpose.ROOMS_READ),setOf(FunctionalPurpose.ROOM_MUSIC_READ))) {
            gate.clear();gate.replace(permission(*approved.toTypedArray()))
            reject {gate.stamp(music,emptySet(),1)}
        }
        gate.clear();gate.replace(permission(*music.toTypedArray()));val stamp=gate.stamp(music,emptySet(),1)
        assertTrue(gate.current(stamp,2));gate.clear();assertFalse(gate.current(stamp,2))
        gate.replace(permission(FunctionalPurpose.ROOMS_READ,FunctionalPurpose.MISSIONS_READ))
        reject {gate.stamp(progress,emptySet(),1)}
        gate.clear();gate.replace(permission(*progress.toTypedArray()));assertNotNull(gate.stamp(progress,emptySet(),1))
    }
    @Test fun strictTransportStillRejectsDuplicatesAndOversizedResponses() {
        reject {StrictNativeJson.parseBusiness("""{"revision":1,"revision":2}""".toByteArray())}
        reject {StrictNativeJson.parseBusiness(ByteArray(1048577){32})}
        reject {StrictNativeJson.parseBusiness("""{"latitude":1e999}""".toByteArray())}
    }
    @Test fun serverDenialsAndFailuresNeverBecomeSuccessfulReads() {
        for((status,kind) in listOf(403 to NativeSocialFailure.Kind.FORBIDDEN,404 to NativeSocialFailure.Kind.NOT_FOUND,
            503 to NativeSocialFailure.Kind.UNAVAILABLE)) {
            val error=socialRequestFailure(NativeApiClient.Failure(status,"NATIVE_REQUEST_REJECTED"),false)
            assertEquals(kind,error.kind);assertEquals(status,error.httpStatus);assertFalse(error.mayHaveExecuted)
        }
    }
}
