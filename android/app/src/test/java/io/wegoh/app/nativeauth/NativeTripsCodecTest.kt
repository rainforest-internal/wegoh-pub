package io.wegoh.app.nativeauth

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class NativeTripsCodecTest {
    private val trip="a".repeat(32)
    private val car="b".repeat(32)
    private val me="team-"+"c".repeat(40)
    private val driver="team-"+"d".repeat(40)
    private fun reject(action: ()->Unit) {
        try {action();fail("Invalid trip response accepted")}
        catch(_: IllegalStateException) {}
        catch(_: IllegalArgumentException) {}
        catch(_: org.json.JSONException) {}
    }
    private fun summary()=JSONObject().put("id",trip).put("title","가을 여행").put("isOwner",true)
        .put("ownerName","사용자A").put("memberCount",2).put("carCount",1)
    private fun list()=JSONObject().put("trips",JSONArray().put(summary())).put("invitations",JSONArray())
    private fun member(id: String,name: String,isMe: Boolean)=JSONObject().put("id",id).put("name",name)
        .put("state","accepted").put("isOwner",!isMe).put("isMe",isMe).put("readiness","ready")
    private fun detail()=JSONObject().put("id",trip).put("title","가을 여행").put("description","함께 가요\n바다로")
        .put("members",JSONArray().put(member(me,"사용자A",true)).put(member(driver,"사용자D",false)))
        .put("cars",JSONArray().put(JSONObject().put("id",car).put("name","사용자D 차").put("driverId",driver)
            .put("driverName","사용자D").put("seats",3).put("isMine",false).put("iRide",true)
            .put("passengers",JSONArray().put(JSONObject().put("id",me).put("name","사용자A").put("isMe",true)))))
    @Test fun remotePolicyIsExplicitNullableAndRejectsUnknownActions() {
        val value=detail()
        val vehicle=value.getJSONArray("cars").getJSONObject(0)
        assertNull(NativeTripsCodec.detail(value,trip).cars.single().remotePolicy)
        val policy=JSONObject().put("enabled",true).put("actions",JSONArray().put("hvac.temperature")).put("deviceId","e".repeat(32))
        vehicle.put("remotePolicy",policy)
        assertEquals(TripRemotePolicy(true,setOf("hvac.temperature"),"e".repeat(32)),NativeTripsCodec.detail(value,trip).cars.single().remotePolicy)
        reject {NativeTripsCodec.detail(value.apply {policy.put("actions",JSONArray().put("vehicle.unsafe"))},trip)}
        policy.put("actions",JSONArray().put("hvac.temperature")).put("enabled","true")
        reject {NativeTripsCodec.detail(value,trip)}
        policy.put("enabled",true).put("deviceId",JSONObject.NULL)
        reject {NativeTripsCodec.detail(value,trip)}
    }
    @Test fun stableCarOrdinalAndReadOnlyMemberRolesComeFromTheServer() {
        val value=detail()
        value.getJSONArray("cars").getJSONObject(0).put("ordinal",7)
        value.getJSONArray("members").getJSONObject(0).put("role","dj")
        val result=NativeTripsCodec.detail(value,trip)
        assertEquals(7,result.cars.single().ordinal)
        assertEquals("7호차 사용자D 차",result.cars.single().numberedName)
        assertEquals("dj",result.me?.role)
        reject {NativeTripsCodec.detail(value.apply {getJSONArray("cars").getJSONObject(0).put("ordinal",0)},trip)}
        value.getJSONArray("cars").getJSONObject(0).put("ordinal",7)
        reject {NativeTripsCodec.detail(value.apply {getJSONArray("members").getJSONObject(0).put("role","driver-admin")},trip)}
    }
    @Test fun tripListRoutePreviewIsOptionalBoundedAndHasNoLocationCoordinates() {
        assertTrue(NativeTripsCodec.list(list()).trips.single().routePreview.isEmpty())
        val point=JSONObject().put("name","공유 장소").put("courseId","coast").put("ref","one")
        val value=list();value.getJSONArray("trips").getJSONObject(0).put("routePreview",JSONArray().put(point))
        assertEquals(listOf(TripRoutePreviewPlace("공유 장소","coast","one")),NativeTripsCodec.list(value).trips.single().routePreview)
        value.getJSONArray("trips").getJSONObject(0).put("routePreview",JSONArray(List(5) {point}))
        reject {NativeTripsCodec.list(value)}
    }
    @Test fun listUsesOnlyContractSummaryAndInvitations() {
        val parsed=NativeTripsCodec.list(list())
        assertEquals(2,parsed.trips.single().memberCount)
        assertEquals(1,parsed.trips.single().carCount)
        assertTrue(parsed.invitations.isEmpty())
        val value=JSONObject().put("trips",JSONArray()).put("invitations",JSONArray().put(
            JSONObject().put("tripId",trip).put("title","가을 여행").put("ownerName","사용자D")))
        assertEquals("사용자D",NativeTripsCodec.list(value).invitations.single().ownerName)
    }
    @Test fun listRejectsWrongTypesBoundsAndDuplicateTrips() {
        reject {NativeTripsCodec.list(list().put("trips",JSONArray().put(summary().put("isOwner","true"))))}
        reject {NativeTripsCodec.list(list().put("trips",JSONArray().put(summary().put("memberCount",21))))}
        reject {NativeTripsCodec.list(list().put("trips",JSONArray().put(summary().put("carCount",-1))))}
        reject {NativeTripsCodec.list(list().put("trips",JSONArray().put(summary()).put(summary())))}
        reject {NativeTripsCodec.list(list().put("trips",JSONArray().put(summary().put("title","bad\u0000title"))))}
    }
    @Test fun listRejectsMembershipAndInvitationOverlap() {
        val value=list();value.getJSONArray("invitations").put(JSONObject().put("tripId",trip).put("title","가을 여행").put("ownerName","사용자D"))
        reject {NativeTripsCodec.list(value)}
    }
    @Test fun startConflictIsOwnerOnlyStrictAndReferencesAcceptedMembers() {
        val other="e".repeat(32)
        fun owned()=detail().apply {
            getJSONArray("members").getJSONObject(0).put("isOwner",true)
            getJSONArray("members").getJSONObject(1).put("isOwner",false)
        }
        fun conflict()=JSONObject().put("activeTrips",JSONArray().put(JSONObject().put("tripId",other).put("title","지난 여행").put("isOwner",true)))
            .put("busyMemberIds",JSONArray().put(driver))
        assertNull(NativeTripsCodec.detail(owned(),trip).startConflict)
        assertNull(NativeTripsCodec.detail(owned().put("startConflict",JSONObject.NULL),trip).startConflict)
        assertEquals(TripStartConflict(listOf(TripActiveTrip(other,"지난 여행",true)),listOf(driver)),
            NativeTripsCodec.detail(owned().put("startConflict",conflict()),trip).startConflict)
        reject {NativeTripsCodec.detail(detail().put("startConflict",conflict()),trip)}
        reject {NativeTripsCodec.detail(owned().put("startConflict",conflict().put("tripName","x")),trip)}
        reject {NativeTripsCodec.detail(owned().put("startConflict",conflict().put("busyMemberIds",JSONArray().put(me))),trip)}
        reject {NativeTripsCodec.detail(owned().put("startConflict",conflict().put("busyMemberIds",JSONArray().put("team-"+"f".repeat(40)))),trip)}
        reject {NativeTripsCodec.detail(owned().put("startConflict",conflict().apply {
            getJSONArray("activeTrips").getJSONObject(0).put("tripId",trip)}),trip)}
        reject {NativeTripsCodec.detail(owned().put("startConflict",conflict().apply {
            getJSONArray("activeTrips").put(getJSONArray("activeTrips").getJSONObject(0))}),trip)}
    }
    @Test fun detailShowsPassengerDriverAndSeats() {
        val parsed=NativeTripsCodec.detail(detail(),trip)
        assertEquals("사용자D의 차 탑승",parsed.myRole)
        assertEquals(3,parsed.myCar!!.seats)
        assertEquals("사용자A",parsed.myCar!!.passengers.single().name)
        assertEquals("함께 가요\n바다로",parsed.description)
    }
    @Test fun routeSectionAcceptsAnUnsetOrderWithoutChangingMembersOrCarIdentity() {
        val base=NativeTripsCodec.detail(detail(),trip)
        val row=JSONObject().put("id",car).put("isMine",false).put("iRide",true)
            .put("places",JSONArray()).put("routeOrder",JSONObject.NULL).put("routeRevision",0)
        val patch=JSONObject().put("id",trip).put("revision",2).put("cars",JSONArray().put(row)).put("courses",JSONArray())
        val updated=NativeTripsCodec.section(base,patch,"route",1000)
        assertSame(base.members,updated.members)
        assertEquals(base.cars.single().driverId,updated.cars.single().driverId)
        assertNull(updated.cars.single().routeOrder)
        assertFalse(updated.cars.single().routeNextKnown)
        row.put("routeOrder","invalid")
        reject {NativeTripsCodec.section(base,patch,"route",1000)}
    }
    @Test fun detailShowsOwnCarAndUnassignedRole() {
        val value=detail()
        val passenger=JSONObject().put("id",driver).put("name","사용자D").put("isMe",false).put("remoteGranted",true)
        value.getJSONArray("cars").getJSONObject(0).put("driverId",me).put("driverName","사용자A").put("isMine",true)
            .put("iRide",false).put("passengers",JSONArray().put(passenger))
        val parsed=NativeTripsCodec.detail(value,trip)
        assertEquals("내 차 운전",parsed.myRole)
        assertEquals("사용자D",parsed.myCar!!.passengers.single().name)
        value.put("cars",JSONArray())
        assertEquals("탑승 차량 미정",NativeTripsCodec.detail(value,trip).myRole)
        assertNull(NativeTripsCodec.detail(value,trip).myCar)
    }
    @Test fun readinessIsRequiredKnownAndMatchesInvitationState() {
        assertEquals(listOf(TripReadiness.READY,TripReadiness.READY),NativeTripsCodec.detail(detail(),trip).members.map {it.readiness})
        val other=detail().also {it.getJSONArray("members").getJSONObject(1).put("readiness","needsPlaces")}
        assertEquals(TripReadiness.NEEDS_PLACES,NativeTripsCodec.detail(other,trip).members[1].readiness)
        reject {NativeTripsCodec.detail(detail().also {it.getJSONArray("members").getJSONObject(1).remove("readiness")},trip)}
        reject {NativeTripsCodec.detail(detail().also {it.getJSONArray("members").getJSONObject(1).put("readiness","late")},trip)}
        reject {NativeTripsCodec.detail(detail().also {it.getJSONArray("members").getJSONObject(1).put("readiness","invited")},trip)}
        val pending=detail().put("cars",JSONArray())
        pending.getJSONArray("members").getJSONObject(1).put("state","pending").put("readiness","needsCar")
        reject {NativeTripsCodec.detail(pending,trip)}
        pending.getJSONArray("members").getJSONObject(1).put("readiness","invited")
        assertEquals(TripReadiness.INVITED,NativeTripsCodec.detail(pending,trip).members[1].readiness)
    }
    @Test fun detailRejectsWrongTripAndMissingCurrentMember() {
        reject {NativeTripsCodec.detail(detail(),"0".repeat(32))}
        val value=detail();value.getJSONArray("members").getJSONObject(0).put("isMe",false)
        reject {NativeTripsCodec.detail(value,trip)}
        value.getJSONArray("members").getJSONObject(0).put("isMe",true).put("state","pending")
        reject {NativeTripsCodec.detail(value,trip)}
    }
    @Test fun detailRejectsInvalidSeatsAndContradictoryRole() {
        for(seats in listOf(0,9)) {
            val value=detail();value.getJSONArray("cars").getJSONObject(0).put("seats",seats)
            reject {NativeTripsCodec.detail(value,trip)}
        }
        val value=detail();value.getJSONArray("cars").getJSONObject(0).put("isMine",true)
        reject {NativeTripsCodec.detail(value,trip)}
        value.getJSONArray("cars").getJSONObject(0).put("isMine",false).put("iRide",false)
        reject {NativeTripsCodec.detail(value,trip)}
    }
    @Test fun detailRejectsDuplicateMembersAndCars() {
        val value=detail();value.getJSONArray("members").put(member(me,"사용자A",true))
        reject {NativeTripsCodec.detail(value,trip)}
        val duplicate=detail();duplicate.getJSONArray("cars").put(duplicate.getJSONArray("cars").getJSONObject(0))
        reject {NativeTripsCodec.detail(duplicate,trip)}
    }
    @Test fun tripPathsAreFixedAndRejectPathInjection() {
        assertEquals("/v1/social/trips",NativeApiClient.tripPath(null))
        assertEquals("/v1/social/trips/$trip",NativeApiClient.tripPath(trip))
        assertEquals("/v1/native/trips/$trip",NativeApiClient.nativeTripPath(trip))
        assertEquals("/v1/native/trips/$trip/cars/$car",NativeApiClient.nativeTripPath(trip,car))
        for(id in listOf("",trip.uppercase(),"../trips",trip+"/respond",trip+"?x=1",trip+"#part",trip+"%2f"))
            reject {NativeApiClient.tripPath(id)}
        reject {NativeApiClient.nativeTripPath(trip,"../cars")}
    }
    @Test fun responseRequiresExpectedStatusAndExactKeys() {
        NativeTripsCodec.response(JSONObject().put("status","accepted"),true)
        NativeTripsCodec.response(JSONObject().put("status","declined"),false)
        reject {NativeTripsCodec.response(JSONObject().put("status","accepted"),false)}
        reject {NativeTripsCodec.response(JSONObject().put("status","accepted").put("extra",true),true)}
    }
}
