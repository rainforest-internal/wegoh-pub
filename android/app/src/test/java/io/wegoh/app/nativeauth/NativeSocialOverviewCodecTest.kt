package io.wegoh.app.nativeauth

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class NativeSocialOverviewCodecTest {
    private val account="team-"+"a".repeat(40)
    private fun permissions(friends: Boolean)=FunctionalPermissions("b".repeat(32),"c".repeat(32),1,Long.MAX_VALUE,
        if(friends)setOf(FunctionalPurpose.FRIENDS_READ) else setOf(FunctionalPurpose.ROOMS_READ),2,"d".repeat(64))
    private fun overview(friends: Boolean)=JSONObject("""{"people":[],"friends":[],"requests":[],"blocks":[],"rooms":[],"history":[],
        "capabilities":{"friends":$friends,"rooms":${!friends},"history":false,"nativeReadOnly":true}}""")
    @Test fun readsCurrentServerFriendWithVehicleClassification() {
        val response=overview(true)
        response.getJSONArray("friends").put(JSONObject().put("id",account).put("name","실제 친구").put("hasVehicle",false))
        val result=NativeSocialCodec.overview(response,permissions(true))
        assertTrue(result.friendsAvailable)
        assertEquals("실제 친구",result.friends.single().name)
        assertEquals(account,result.friends.single().id)
    }
    @Test fun roomsConsentDoesNotImplyFriendConsent() {
        val result=NativeSocialCodec.overview(overview(false),permissions(false))
        assertFalse(result.friendsAvailable)
        assertTrue(result.roomsAvailable)
        assertTrue(result.friends.isEmpty())
    }
    @Test fun approvedEmptyFriendsAreAvailable() {
        val result=NativeSocialCodec.overview(overview(true),permissions(true))
        assertTrue(result.friendsAvailable)
        assertTrue(result.friends.isEmpty())
    }
    @Test fun rejectsFriendFieldsAndCapabilitiesOutsideTheCurrentContract() {
        val response=overview(true)
        response.getJSONArray("friends").put(JSONObject().put("id",account).put("name","실제 친구").put("hasVehicle","false"))
        assertThrows(Exception::class.java) {NativeSocialCodec.overview(response,permissions(true))}
        assertThrows(Exception::class.java) {NativeSocialCodec.overview(overview(true),permissions(false))}
    }
}
