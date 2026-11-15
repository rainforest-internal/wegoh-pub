package io.wegoh.app.nativeauth

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class NativeTripMusicCodecTest {
    private val trip="a".repeat(32)
    private val me="team-"+"b".repeat(40)
    private val peer="team-"+"c".repeat(40)
    private val source=TripSavedPlaylistSource("d".repeat(32),7,"e".repeat(32))

    private fun item(id: String="1".repeat(32),owner: String=me,state: String="approved")=JSONObject()
        .put("id",id).put("title","바다 가는 길")
        .put("url","https://www.melon.com/mymusic/playlist/mymusicplaylistview_inform.htm?plylstSeq=1234")
        .put("addedBy",JSONObject().put("id",owner).put("name","일행"))
        .put("reviewState",state)
    private fun page(vararg items: JSONObject)=JSONObject().put("tripId",trip).put("items",JSONArray(items.toList()))
        .put("limit",200).put("canAdd",true).put("canReorder",false).put("nowPlaying",JSONArray())
    private fun playback(item: String="1".repeat(32),by: String=peer)=JSONObject().put("itemId",item)
        .put("startedBy",JSONObject().put("id",by).put("name","운전자")).put("startedAt","2026-11-14T03:00:00+00:00")
    private fun decode(value: JSONObject)=NativeTripMusicCodec.collection(value,trip,me)
    private fun rejected(action: ()->Unit) {
        try {action()} catch(_: Exception) {return}
        fail("Invalid trip music collection accepted")
    }

    @Test fun collectionReadsBothEmptyAndPopulatedCanonicalSnapshots() {
        val empty=decode(page())
        assertEquals(trip,empty.tripId);assertTrue(empty.items.isEmpty());assertTrue(empty.canAdd);assertEquals(200,empty.limit)
        val full=decode(page(item(owner=peer)))
        assertEquals("바다 가는 길",full.items.single().title)
        assertEquals(peer,full.items.single().addedById)
        assertEquals("일행",full.items.single().addedByName)
        assertEquals("approved",full.items.single().reviewState)
        assertEquals("TripMusicCollection(redacted)",full.toString())
        assertEquals("TripSavedPlaylist(redacted)",full.items.single().toString())
    }

    @Test fun savedAndTypedLinksStayInTheServerOrder() {
        val typed=item(id="2".repeat(32),owner=peer).put("title","Zoo").put("url","https://youtu.be/jNQXAC9IVRw")
        val value=decode(page(typed,item()))
        assertEquals(listOf("2".repeat(32),"1".repeat(32)),value.items.map {it.id})
        assertEquals("https://youtu.be/jNQXAC9IVRw",value.items.first().url)
    }

    @Test fun pendingPrivateAndRejectedMetadataIsAcceptedOnlyForTheCurrentAccount() {
        for(state in listOf("private","quarantined","rejected","approved")) {
            assertEquals(state,decode(page(item(state=state))).items.single().reviewState)
            if(state!="approved")rejected {decode(page(item(owner=peer,state=state)))}
        }
    }

    @Test fun theTripAndCurrentAccountMustBeValidAndMatchTheRequestedTrip() {
        rejected {decode(page().put("tripId","f".repeat(32)))}
        rejected {NativeTripMusicCodec.collection(page(),"A".repeat(32),me)}
        rejected {NativeTripMusicCodec.collection(page(),trip,"../account")}
        for(raw in listOf("A".repeat(32),"a".repeat(31),"../trip",1,JSONObject.NULL))
            rejected {decode(page().put("tripId",raw))}
    }

    @Test fun responseObjectsRejectMissingAndUnexpectedFields() {
        for(key in listOf("tripId","items","limit","canAdd","canReorder","nowPlaying"))rejected {decode(page().apply {remove(key)})}
        rejected {decode(page().put("functionalRevision",7))}
        for(key in listOf("id","title","url","addedBy","reviewState"))
            rejected {decode(page(item().apply {remove(key)}))}
        rejected {decode(page(item().put("playlistId",source.playlistId)))}
        rejected {decode(page(item().apply {getJSONObject("addedBy").put("email","private@example.invalid")}))}
        rejected {decode(page(item().apply {getJSONObject("addedBy").remove("name")}))}
    }

    @Test fun collectionLimitIsAnExactBoundedIntegerAndCapabilityIsABoolean() {
        for(raw in listOf(199,201,200.0,"200",true,JSONObject.NULL))rejected {decode(page().put("limit",raw))}
        for(raw in listOf(0,1,"true",JSONObject.NULL))rejected {decode(page().put("canAdd",raw))}
        val filtered=decode(page(item()).put("canAdd",false))
        assertFalse("The canonical cap may include rows hidden from this viewer",filtered.canAdd)
    }

    @Test fun collectionRejectsDuplicateRowsAndRowsBeyondTheServerCap() {
        rejected {decode(page(item(),item()))}
        val twoHundred=(1..200).map {item(it.toString(16).padStart(32,'0'))}
        assertEquals(200,decode(page(*twoHundred.toTypedArray())).items.size)
        rejected {decode(page(*(twoHundred+item("f".repeat(32))).toTypedArray()))}
        rejected {decode(page().put("items",JSONArray().put("not a playlist")))}
    }

    @Test fun unsafeMusicUrlsNeverReachAnExternalLinkAction() {
        for(raw in listOf("http://www.melon.com/list","//www.melon.com/list","https://user:secret@www.melon.com/list",
            "https://www.melon.com:444/list","https:///missing-host","https://www.melon.com/a b",
            "https://www.melon.com/\n","https://www.melon.com/\u0085","https://www.melon.com\\@evil.invalid/list",
            "javascript:alert(1)","https://[broken/list","https://www.melon.com/"+"x".repeat(2048)))
            rejected {decode(page(item().put("url",raw)))}
        for(raw in listOf("https://open.spotify.com/playlist/example","https://music.youtube.com/playlist?list=example",
            "https://www.melon.com:443/list"))assertEquals(raw,decode(page(item().put("url",raw))).items.single().url)
    }

    @Test fun metadataRequiresKnownReviewStatesIdsAndBoundedReadableText() {
        for(raw in listOf("pending","APPROVED",true,JSONObject.NULL))rejected {decode(page(item().put("reviewState",raw)))}
        for(raw in listOf(""," ","line\nbreak","x".repeat(121),1,JSONObject.NULL))rejected {decode(page(item().put("title",raw)))}
        rejected {decode(page(item().put("id","A".repeat(32))))}
        rejected {decode(page(item(owner="b".repeat(40))))}
        rejected {decode(page(item().apply {getJSONObject("addedBy").put("name","x".repeat(81))}))}
    }

    @Test fun rawResponseRejectsDuplicateKeysAndTrailingOrNonObjectJson() {
        val good=page(item()).toString()
        assertEquals(1,NativeTripMusicCodec.collection(good.toByteArray(),trip,me).items.size)
        rejected {NativeTripMusicCodec.collection(good.replace("\"limit\":200","\"limit\":200,\"limit\":200").toByteArray(),trip,me)}
        for(raw in listOf("[]","null",good+"{}"))rejected {NativeTripMusicCodec.collection(raw.toByteArray(),trip,me)}
    }

    @Test fun nowPlayingMustReferenceAVisibleItemAndOneEntryPerMember() {
        val value=decode(page(item(),item("2".repeat(32),peer)).put("canReorder",true)
            .put("nowPlaying",JSONArray().put(playback("2".repeat(32),me)).put(playback())))
        assertTrue(value.canReorder)
        assertEquals(listOf(me,peer),value.nowPlaying.map {it.startedById})
        assertEquals("2".repeat(32),value.mine?.itemId)
        assertEquals("2".repeat(32),value.playing?.second?.id)
        assertEquals("TripMusicPlayback(redacted)",value.nowPlaying.first().toString())
        val others=decode(page(item()).put("nowPlaying",JSONArray().put(playback())))
        assertNull(others.mine);assertEquals(peer,others.playing?.first?.startedById)
        rejected {decode(page(item()).put("nowPlaying",JSONArray().put(playback("f".repeat(32)))))}
        rejected {decode(page(item()).put("nowPlaying",JSONArray().put(playback()).put(playback())))}
        rejected {decode(page(item()).put("nowPlaying",JSONArray().put(playback().put("deviceId","d".repeat(32)))))}
        rejected {decode(page(item()).put("nowPlaying",JSONArray().put(playback().apply {getJSONObject("startedBy").put("id","x")})))}
        for(raw in listOf(0,"false",JSONObject.NULL))rejected {decode(page().put("canReorder",raw))}
    }

    @Test fun playAndMoveBodiesCarryOnlyCheckedIdentifiers() {
        assertEquals(setOf("itemId"),NativeTripMusicCodec.playBody("1".repeat(32)).keys().asSequence().toSet())
        val top=NativeTripMusicCodec.moveBody("1".repeat(32),null)
        assertTrue(top.isNull("afterId") && top.has("afterId"))
        assertEquals("2".repeat(32),NativeTripMusicCodec.moveBody("1".repeat(32),"2".repeat(32)).getString("afterId"))
        for(bad in listOf("","A".repeat(32),"../x"))rejected {NativeTripMusicCodec.playBody(bad)}
        rejected {NativeTripMusicCodec.moveBody("1".repeat(32),"1".repeat(32))}
        rejected {NativeTripMusicCodec.moveBody("1".repeat(32),"bad")}
    }

    @Test fun addUsesOnlyObservedSourceReferencesAndExplicitConsents() {
        val body=NativeTripMusicCodec.addBody(source,true,true)
        assertEquals(setOf("playlistId","playlistRevision","trackId","rightsConfirmed","reviewConsent"),body.keys().asSequence().toSet())
        assertEquals(source.playlistId,body.getString("playlistId"));assertEquals(7L,body.getLong("playlistRevision"))
        assertEquals(source.trackId,body.getString("trackId"));assertEquals(true,body.get("rightsConfirmed"));assertEquals(true,body.get("reviewConsent"))
        for(consents in listOf(false to true,true to false,false to false))
            rejected {NativeTripMusicCodec.addBody(source,consents.first,consents.second)}
    }

    @Test fun addRejectsMalformedOrStaleSourceIdentityBeforeARequestCanBeCreated() {
        for(invalid in listOf(source.copy(playlistId="../playlists"),source.copy(trackId="E".repeat(32)),
            source.copy(playlistRevision=0),source.copy(playlistRevision=2147483648L)))
            rejected {NativeTripMusicCodec.addBody(invalid,true,true)}
        assertEquals(2147483647L,NativeTripMusicCodec.addBody(source.copy(playlistRevision=2147483647L),true,true).getLong("playlistRevision"))
    }

}
