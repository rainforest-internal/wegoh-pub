package io.wegoh.app

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class CourseLibraryCodecTest {
    private val creator="team-"+"a".repeat(40)
    private val follow="11111111-1111-4111-8111-111111111111"
    private fun course(id: String="coast",version: Int=1,starred: Boolean=false)=JSONObject()
        .put("id",id).put("version",version).put("title","바다 코스").put("author","사용자F").put("description","간월암\n대천")
        .put("stopCount",2).put("stopNames",JSONArray(listOf("간월암","대천"))).put("checksum","b".repeat(64)).put("tags",JSONArray(listOf("바다","호수")))
        .put("starred",starred).put("starCount",2).put("canFollow",true).put("followId",follow)
        .put("creatorRank",JSONObject.NULL).put("creatorId",creator).put("hasCover",false)
    private fun payload()=JSONObject().put("public",JSONArray().put(course()))
        .put("saved",JSONArray().put(course("older",2,true)))
        .put("news",JSONArray().put(course().put("eventId","12").put("approvedAt","2026-11-13T00:00:00Z").put("read",false)))
        .put("following",JSONArray().put(JSONObject().put("id",follow).put("name","사용자F").put("creatorId",creator)))
        .put("popularTags",JSONArray(listOf("바다","호수"))).put("followedTags",JSONArray(listOf("호수"))).put("unreadCount",1)
    private fun rejected(value: JSONObject) {assertTrue(runCatching {CourseLibraryCodec.library(value)}.isFailure)}
    @Test fun catalogueKeepsActualSavedVersionsNewsAndServerRecommendationOrder() {
        val value=payload().put("public",JSONArray().put(course("second")).put(course("first")))
        val library=CourseLibraryCodec.library(value)
        assertEquals(listOf("second","first"),library.public.map {it.published.id})
        assertEquals("older@2",library.saved.single().published.key)
        assertEquals(1,library.unreadCount);assertFalse(library.news.single().read)
        assertEquals(listOf("호수"),library.followedTags)
        assertEquals("b".repeat(64),library.saved.single().published.checksum)
        assertEquals("간월암\n대천",library.public.first().published.description)
        assertEquals(listOf("간월암","대천"),library.public.first().stopNames)
        assertEquals(listOf("간월암","대천"),library.news.single().course.stopNames)
    }
    @Test fun nullableIdentityAndEmptyCollectionsRemainUnavailableFacts() {
        val value=payload().put("public",JSONArray().put(course().put("creatorId",JSONObject.NULL).put("followId",JSONObject.NULL)))
            .put("following",JSONArray().put(JSONObject().put("id",follow).put("name",JSONObject.NULL).put("creatorId",JSONObject.NULL)))
            .put("news",JSONArray()).put("unreadCount",0)
        val library=CourseLibraryCodec.library(value)
        assertNull(library.public.single().creatorId);assertNull(library.following.single().name)
        assertTrue(library.news.isEmpty());assertEquals(0,library.unreadCount)
    }
    @Test fun invalidOrConflictingPrivateCatalogueRowsAreRejected() {
        rejected(payload().put("unreadCount",true))
        rejected(payload().put("public",JSONArray().put(course().put("checksum","invalid"))))
        rejected(payload().put("saved",JSONArray().put(course(starred=false))))
        rejected(payload().put("news",JSONArray().put(course().put("eventId","12").put("approvedAt","bad").put("read",false))))
        rejected(payload().put("public",JSONArray().put(course()).put(course())))
        rejected(payload().put("saved",JSONArray().put(course(starred=true).put("checksum","c".repeat(64)))))
        rejected(payload().put("public",JSONArray().put(course().put("creatorId","not-an-account"))))
        rejected(payload().put("following",JSONArray().put(JSONObject().put("id","not-a-follow").put("name","사용자F").put("creatorId",creator))))
        rejected(payload().put("public",JSONArray().put(course().put("stopNames",JSONArray(listOf("간월암"))))))
        rejected(payload().put("public",JSONArray().put(course().put("stopNames",JSONArray(listOf("간월암"," "))))))
        rejected(payload().put("public",JSONArray().put(course().put("stopNames",JSONArray(listOf("간월암","가".repeat(81)))))))
        rejected(payload().put("public",JSONArray().put(course().put("stopNames",JSONArray(listOf("간월암",2))))))
        rejected(payload().put("public",JSONArray().put(course().apply {remove("stopNames")})))
    }
    @Test fun publicDetailMustMatchTheSelectedImmutableVersionAndChecksum() {
        val pack=CourseLibraryCodec.library(payload()).public.single().published
        val detail=JSONObject().put("pack",JSONObject().put("id",pack.id).put("version",pack.version))
            .put("checksum",pack.checksum).put("tags",JSONArray()).put("hasCover",false)
            .put("creatorId",creator).put("starred",false).put("starCount",0).put("canFollow",true).put("followId",JSONObject.NULL)
        CourseLibraryCodec.verifyPublicDetail(detail,pack)
        assertTrue(runCatching {CourseLibraryCodec.verifyPublicDetail(JSONObject(detail.toString()).put("checksum","c".repeat(64)),pack)}.isFailure)
        detail.getJSONObject("pack").put("version",2)
        assertTrue(runCatching {CourseLibraryCodec.verifyPublicDetail(detail,pack)}.isFailure)
    }
    @Test fun catalogueTagListsAcceptTheServerLimitWithoutChangingPerCourseTagLimit() {
        val tags=(1..1000).map {"태그$it"}
        val value=payload().put("popularTags",JSONArray(tags)).put("followedTags",JSONArray(tags))
        val library=CourseLibraryCodec.library(value)
        assertEquals(1000,library.popularTags.size);assertEquals(1000,library.followedTags.size)
        rejected(payload().put("followedTags",JSONArray(tags+"초과")))
        rejected(payload().put("public",JSONArray().put(course().put("tags",JSONArray(tags.take(9))))))
    }
}
