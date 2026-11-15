package io.wegoh.app.nativeauth

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class TripPlanCodecTest {
    private val trip="a".repeat(32)
    private val car="b".repeat(32)
    private val place="c".repeat(32)
    private val me="team-"+"d".repeat(40)
    private fun detail()=JSONObject().put("id",trip).put("title","강릉 바다 여행").put("description","")
        .put("members",JSONArray().put(JSONObject().put("id",me).put("name","사용자A").put("state","accepted").put("isOwner",true).put("isMe",true).put("readiness","ready")))
        .put("cars",JSONArray().put(JSONObject().put("id",car).put("name","사용자A 차").put("driverId",me).put("driverName","사용자A")
            .put("seats",4).put("isMine",true).put("iRide",false).put("passengers",JSONArray())))
    private fun reject(action: ()->Unit) {
        try {action();fail("Invalid response accepted")}
        catch(_: IllegalArgumentException) {}
        catch(_: IllegalStateException) {}
        catch(_: org.json.JSONException) {}
    }
    @Test fun legacyAndNullFieldsStayNull() {
        val old=NativeTripsCodec.detail(detail(),trip)
        assertNull(old.state);assertNull(old.revision);assertNull(old.courses);assertNull(old.cars.single().places)
        assertFalse(old.cars.single().routeNextKnown);assertNull(old.cars.single().routeNext);assertEquals(0L,old.cars.single().routeRevision)
        val dates=NativeTripsCodec.detail(detail().put("startDate",JSONObject.NULL).put("endDate","2026-11-15"),trip)
        assertNull(dates.startDate);assertEquals("2026-11-15",dates.endDate)
    }
    @Test fun fullAndRedactedPlacesHaveDistinctShapes() {
        val values=JSONArray().put(JSONObject().put("id",place).put("kind","pickup").put("name","합정역 2번 출구")
            .put("lat",37.5).put("lng",127.0).put("selectedBy",JSONArray().put(me)))
            .put(JSONObject().put("name","강릉역").put("selectedBy",2))
        val parsed=NativeTripsCodec.places(values)
        assertEquals(listOf(me),parsed[0].selectedBy);assertEquals(1,parsed[0].selectedCount)
        assertEquals(2,parsed[1].selectedCount);assertNull(parsed[1].selectedBy)
        assertNull(parsed[1].id);assertNull(parsed[1].lat);assertNull(parsed[1].kind)
    }
    @Test fun optionalCoordinatesAndCountsRejectWrongTypes() {
        reject {NativeTripsCodec.places(JSONArray().put(JSONObject().put("name","강릉역").put("lat","37.0")))}
        reject {NativeTripsCodec.places(JSONArray().put(JSONObject().put("name","강릉역").put("selectedBy",true)))}
        reject {NativeTripsCodec.places(JSONArray().put(JSONObject().put("name","강릉역").put("lat",91)))}
        reject {NativeTripsCodec.detail(detail().put("revision","1"),trip)}
    }
    @Test fun courseStopsAreReadFromFakeNativeDetail() {
        val payload=detail().put("state","active").put("revision",3).put("courses",JSONArray().put(JSONObject()
            .put("packId","gangneung").put("title","강릉 바다 한 바퀴").put("completedCarIds",JSONArray().put(car))
            .put("stops",JSONArray().put(JSONObject().put("id","beach").put("name","경포해변").put("lat",37.7).put("lng",128.9)))))
        val parsed=NativeTripsCodec.detail(payload,trip)
        assertEquals("active",parsed.state);assertEquals(3L,parsed.revision)
        assertEquals("beach",parsed.courses?.single()?.stops?.single()?.id)
        assertEquals(listOf(car),parsed.courses?.single()?.completedCarIds)
    }
    @Test fun routeWireUsesStopRefAndPackIdAndDoesNotInventRevision() {
        val items=listOf(TripRouteItem("pickup",place),TripRouteItem("course","beach","gangneung","e".repeat(32)))
        val body=NativeTripsCodec.routeBody(items)
        assertEquals(setOf("items"),body.keys().asSequence().toSet())
        assertEquals(items,NativeTripsCodec.routeItems(body.getJSONArray("items")))
        assertEquals("beach",body.getJSONArray("items").getJSONObject(1).getString("ref"))
        reject {NativeTripsCodec.routeBody(listOf(TripRouteItem("pickup","../places")))}
        reject {NativeTripsCodec.routeBody(items+items.first())}
        reject {NativeTripsCodec.routeBody(listOf(TripRouteItem("course","beach","gangneung",place),TripRouteItem("drop",place)))}
    }
    @Test fun agreedSignalPlacesAndRouteRefsPreserveTheirSeparateNamespace() {
        val value=JSONObject().put("id",place).put("kind","signal").put("name","가".repeat(80)).put("lat",37.5).put("lng",127.0)
        val parsed=NativeTripsCodec.places(JSONArray().put(value)).single()
        assertEquals("signal",parsed.kind);assertEquals(80,parsed.name.length)
        val items=listOf(TripRouteItem("pickup",place),TripRouteItem("signal",place))
        assertEquals(items,NativeTripsCodec.routeItems(NativeTripsCodec.routeBody(items).getJSONArray("items")))
        reject {NativeTripsCodec.routeBody(items+items.last())}
        reject {NativeTripsCodec.routeBody(listOf(TripRouteItem("signal","../signals")))}
        reject {NativeTripsCodec.routeBody(listOf(TripRouteItem("signal",place,"gangneung")))}
        reject {NativeTripsCodec.routeBody(listOf(TripRouteItem("signal",place,dropRef=car)))}
        reject {NativeTripsCodec.places(JSONArray().put(value.put("name","가".repeat(81))))}
        reject {NativeTripsCodec.places(JSONArray().put(value.put("kind","pickup").put("name","가".repeat(41))))}
        reject {TripActionCodec.request(TripAction.AddPlace(car,"signal","직접 만든 장소",37.5,127.0))}
    }
    @Test fun routeProgressDistinguishesUnreportedNextFromAnExplicitEndAndRejectsInvalidVersions() {
        val payload=detail()
        val vehicle=payload.getJSONArray("cars").getJSONObject(0)
        vehicle.put("routeNext",JSONObject().put("type","signal").put("ref",place)).put("routeRevision",3)
        val next=NativeTripsCodec.detail(payload,trip).cars.single()
        assertTrue(next.routeNextKnown);assertEquals(TripRouteItem("signal",place),next.routeNext);assertEquals(3L,next.routeRevision)
        vehicle.put("routeNext",JSONObject.NULL)
        val ended=NativeTripsCodec.detail(payload,trip).cars.single()
        assertTrue(ended.routeNextKnown);assertNull(ended.routeNext)
        for(invalid in listOf(-1,3.5,"3",JSONObject.NULL)) {
            vehicle.put("routeRevision",invalid)
            reject {NativeTripsCodec.detail(payload,trip)}
        }
        vehicle.put("routeRevision",0).put("routeNext",JSONObject().put("type","signal").put("ref",place).put("courseId","gangneung"))
        reject {NativeTripsCodec.detail(payload,trip)}
    }
    @Test fun invitationFriendsUseDedicatedTripStateProjection() {
        val friends=NativeTripsCodec.friends(JSONObject().put("friends",JSONArray().put(JSONObject()
            .put("id",me).put("name","사용자E").put("hasVehicle",false).put("tripState","pending"))))
        assertEquals("pending",friends.single().state)
        assertFalse(checkNotNull(friends.single().hasVehicle))
    }
    @Test fun actionsUseExactNativeSuffixesAndLifecycleRevision() {
        val finish=TripActionCodec.request(TripAction.Finish(4))
        assertEquals("POST",finish.method);assertEquals("/finish",finish.suffix)
        assertEquals(setOf("revision"),finish.body.keys().asSequence().toSet())
        assertEquals(4L,finish.body.getLong("revision"))
        val add=TripActionCodec.request(TripAction.AddPlace(car,"pickup","합정역",37.5,127.0))
        assertEquals("/cars/$car/places",add.suffix)
        assertEquals(setOf("kind","name","lat","lng"),add.body.keys().asSequence().toSet())
        assertEquals(setOf(201),add.success)
        assertEquals("DELETE",TripActionCodec.request(TripAction.RemoveRider(car,me)).method)
        reject {TripActionCodec.request(TripAction.Finish(0))}
        reject {TripActionCodec.request(TripAction.EditIntro(" ",""))}
        reject {TripActionCodec.request(TripAction.CreateCar("사용자A 차",9))}
    }
    @Test fun dateOnlyPatchPreservesIndependentNullsAndValidatesInterval() {
        val dates=TripActionCodec.request(TripAction.EditDates(null,"2026-11-15"))
        assertEquals("PATCH",dates.method)
        assertEquals(setOf("startDate","endDate"),dates.body.keys().asSequence().toSet())
        assertTrue(dates.body.isNull("startDate"))
        reject {TripActionCodec.request(TripAction.EditDates("2026-11-16","2026-11-15"))}
        reject {TripActionCodec.request(TripAction.EditDates("2026-11-01","2026-12-02"))}
    }
}
