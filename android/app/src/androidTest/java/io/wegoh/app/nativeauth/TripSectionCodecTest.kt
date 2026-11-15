package io.wegoh.app.nativeauth

import android.test.InstrumentationTestCase
import org.json.JSONArray
import org.json.JSONObject

class TripSectionCodecTest: InstrumentationTestCase() {
    fun testLocationUpdatesDoNotExtendOtherPrivateDisplayData() {
        val id="a".repeat(32)
        val before=TripDisplay(emptyList(),null,null,TripMusic("Private playlist",null,1,null),emptyList(),1500)
        val trip=TripDetail(id,"Trip","",emptyList(),emptyList(),revision=1,display=before)
        val display=JSONObject().put("serverNow","2026-11-11T00:00:00Z").put("validUntil","2026-11-11T00:00:15Z")
            .put("endedAt",JSONObject.NULL).put("timeline",JSONArray()).put("visitCount",JSONObject.NULL)
            .put("metrics",JSONObject.NULL).put("music",JSONObject.NULL).put("companions",JSONArray())
        val patch=JSONObject().put("id",id).put("revision",2).put("locationConsent",true).put("display",display)
        val updated=NativeTripsCodec.section(trip,patch,"location",1000)
        assertSame(trip.members,updated.members);assertSame(trip.cars,updated.cars)
        assertTrue(updated.locationSharing)
        assertEquals(1500L,updated.display?.expiresAtElapsedMillis)
        assertEquals(16000L,updated.display?.companionsExpiresAtElapsedMillis)
        assertEquals(before.music,updated.display?.music)
        patch.put("id","b".repeat(32))
        try {NativeTripsCodec.section(trip,patch,"location",1000);fail("Cross trip patch accepted")}catch(expected: IllegalStateException){}
    }

    fun testRoutePatchKeepsMembershipAndRejectsAChangedCarRoster() {
        val id="a".repeat(32);val carId="b".repeat(32);val person="team-"+"c".repeat(40)
        val car=TripCar(carId,"Car",person,"Driver",4,true,false,emptyList())
        val trip=TripDetail(id,"Trip","",listOf(TripMember(person,"Driver",true,true,true)),listOf(car),revision=1)
        val route=JSONObject().put("id",carId).put("isMine",true).put("iRide",false)
            .put("places",JSONArray()).put("routeOrder",JSONArray()).put("routeRevision",3).put("routeNext",JSONObject.NULL)
        val patch=JSONObject().put("id",id).put("revision",2).put("cars",JSONArray().put(route)).put("courses",JSONArray())
        val updated=NativeTripsCodec.section(trip,patch,"route",1000)
        assertSame(trip.members,updated.members);assertEquals(trip.title,updated.title)
        assertEquals(3L,updated.cars.single().routeRevision)
        assertTrue(updated.cars.single().routeNextKnown)
        route.put("routeOrder",JSONObject.NULL);route.remove("routeNext")
        val unset=NativeTripsCodec.section(trip,patch,"route",1000)
        assertNull(unset.cars.single().routeOrder)
        assertFalse(unset.cars.single().routeNextKnown)
        route.put("id","d".repeat(32))
        try {NativeTripsCodec.section(trip,patch,"route",1000);fail("Changed roster accepted")}catch(expected: IllegalStateException){}
    }
}
