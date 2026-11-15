package io.wegoh.app.nativeauth

import org.junit.Assert.*
import org.junit.Test

class NativeTripsWireCodecTest {
    private val trip="a".repeat(32)
    private val invitedTrip="b".repeat(32)
    private val car="c".repeat(32)
    private val place="d".repeat(32)
    private val me="team-"+"e".repeat(40)
    private fun wire(json: String)=StrictNativeJson.parseBusiness(json.toByteArray(Charsets.UTF_8))
    private fun list(memberCount: String="6",carCount: String="3",invitedMembers: String="2",invitedCars: String="1")=wire("""
        {"trips":[{"id":"$trip","title":"강릉 바다 여행","ownerName":"사용자A","isOwner":true,
          "memberCount":$memberCount,"carCount":$carCount,"state":"active","startDate":null,"endDate":"2026-11-15"}],
         "invitations":[{"tripId":"$invitedTrip","title":"주문진 여행","ownerName":"사용자E",
          "memberCount":$invitedMembers,"carCount":$invitedCars,"startDate":"2026-11-16","endDate":null}]}
    """)
    private fun detail(seats: String="4",revision: String="3",version: String="1",stopCount: String="2",
        lat: String="37",lng: String="128")=wire("""
        {"id":"$trip","title":"강릉 바다 여행","description":"함께 가요","state":"active","revision":$revision,
         "members":[{"id":"$me","name":"사용자A","state":"accepted","isOwner":true,"isMe":true,"readiness":"ready"}],
         "cars":[{"id":"$car","name":"사용자A 차","driverId":"$me","driverName":"사용자A","seats":$seats,
          "isMine":true,"iRide":false,"passengers":[],"places":[{"id":"$place","name":"합정역","kind":"pickup",
          "lat":$lat,"lng":$lng,"selectedBy":["$me"]}]}],
         "courses":[{"packId":"gangneung","title":"강릉 바다 한 바퀴","version":$version,"stopCount":$stopCount,
          "stops":[{"id":"beach","name":"경포해변","lat":$lat,"lng":$lng},
           {"id":"coffee","name":"안목 커피거리","lat":37.773,"lng":128.949}]}]}
    """)
    private fun places(selected: String="2",lat: String="37",lng: String="128")=wire("""
        {"places":[{"id":"$place","name":"합정역","kind":"pickup","lat":$lat,"lng":$lng,"selectedBy":["$me"]},
         {"name":"강릉역","selectedBy":$selected}]}
    """).getJSONArray("places")
    private fun reject(label: String,action: ()->Unit) {
        try {action();fail("Invalid trip response accepted: $label")}
        catch(_: IllegalStateException) {}
        catch(_: IllegalArgumentException) {}
        catch(_: org.json.JSONException) {}
    }

    @Test fun activeDetailIgnoresAdditionalSignalsAndPlacesFields() {
        val value=detail().put("state","active").put("signals",org.json.JSONArray()).put("places",org.json.JSONArray())
        value.getJSONArray("cars").getJSONObject(0).put("signals",org.json.JSONArray()).put("driverVehicleReady",true)
        val parsed=NativeTripsCodec.detail(value,trip)
        assertEquals("active",parsed.state)
        assertEquals(1,parsed.cars.size)
        assertEquals("합정역",parsed.cars.single().places!!.single().name)
    }
    @Test fun invalidDetailFieldIsIdentifiedWithoutLoggingItsValue() {
        val value=detail(seats="\"private-value\"")
        val failure=runCatching {NativeTripsCodec.detail(value,trip)}.exceptionOrNull()!!
        val message=TripLoadDiagnostics.message("trip.detail",failure,trip)
        assertTrue(message.contains("field=seats"))
        assertFalse(message.contains("private-value"))
        assertEquals(NativeSocialFailure.Kind.INVALID_RESPONSE,socialRequestFailure(failure,false).kind)
        assertEquals(NativeSocialFailure.Kind.UNAVAILABLE,socialRequestFailure(java.io.IOException("private-url"),false).kind)
    }
    @Test fun listReadsLongCountsFromTheNativeTransportParser() {
        val response=list()
        val summary=response.getJSONArray("trips").getJSONObject(0)
        assertTrue(summary.get("memberCount") is Long);assertTrue(summary.get("carCount") is Long)
        assertTrue(response.getJSONArray("invitations").getJSONObject(0).get("memberCount") is Long)
        val result=NativeTripsCodec.list(response)
        assertEquals(6,result.trips.single().memberCount);assertEquals(3,result.trips.single().carCount)
        assertEquals(2,result.invitations.single().memberCount);assertEquals(1,result.invitations.single().carCount)
        assertNull(result.trips.single().startDate);assertNull(result.invitations.single().endDate)
    }

    @Test fun acceptingAnInvitationSendsTheSelectedLocationChoiceAndDecliningOmitsIt() {
        for(choice in listOf(false,true)) {
            val body=NativeTripsCodec.invitationResponseBody(true,choice)
            assertEquals(true,body.get("accept"))
            assertEquals(choice,body.get("locationConsent"))
        }
        assertFalse(NativeTripsCodec.invitationResponseBody(false,null).has("locationConsent"))
        reject("missing choice") {NativeTripsCodec.invitationResponseBody(true,null)}
        reject("choice on decline") {NativeTripsCodec.invitationResponseBody(false,true)}
    }
    @Test fun changingLocationSharingOnlyUpdatesTheCurrentTripConsent() {
        for(choice in listOf(true,false)) {
            val action=TripAction.SetLocationSharing(choice)
            val request=TripActionCodec.request(action)
            assertEquals("PATCH",request.method)
            assertEquals("/location-sharing",request.suffix)
            assertEquals(setOf("locationConsent"),request.body.keys().asSequence().toSet())
            assertEquals(choice,request.body.get("locationConsent"))
            val snapshot=wire("""{"locationConsent":$choice,"revision":2,"locationShareId":null}""")
            assertEquals(2L,TripActionCodec.response(action,snapshot).revision)
            assertEquals(choice,NativeTripsCodec.detail(detail().put("locationConsent",choice),trip).locationSharing)
            reject("mismatched saved choice") {TripActionCodec.response(TripAction.SetLocationSharing(!choice),snapshot)}
        }
        assertFalse(NativeTripsCodec.detail(detail(),trip).locationSharing)
    }

    @Test fun detailReadsLongSeatsRevisionCourseCountsAndCoordinates() {
        val response=detail()
        assertTrue(response.get("revision") is Long)
        assertTrue(response.getJSONArray("cars").getJSONObject(0).get("seats") is Long)
        val course=response.getJSONArray("courses").getJSONObject(0)
        assertTrue(course.get("version") is Long);assertTrue(course.get("stopCount") is Long)
        assertTrue(course.getJSONArray("stops").getJSONObject(0).get("lat") is Long)
        assertTrue(course.getJSONArray("stops").getJSONObject(1).get("lat") is Double)
        val result=NativeTripsCodec.detail(response,trip)
        val parsedCourse=result.courses!!.single()
        assertEquals(3L,result.revision);assertEquals(4,result.cars.single().seats)
        assertEquals(1,parsedCourse.version);assertEquals(2,parsedCourse.stopCount)
        assertEquals(37.0,result.cars.single().places!!.single().lat!!,0.0)
        assertEquals(128.0,parsedCourse.stops!![0].lng!!,0.0)
        assertEquals(37.773,parsedCourse.stops!![1].lat!!,0.0)
    }

    @Test fun placesReadLongSelectedCountsAndWholeOrFractionalCoordinates() {
        val response=places(lng="128.949")
        assertTrue(response.getJSONObject(0).get("lat") is Long)
        assertTrue(response.getJSONObject(1).get("selectedBy") is Long)
        val result=NativeTripsCodec.places(response)
        assertEquals(listOf(me),result[0].selectedBy);assertEquals(1,result[0].selectedCount)
        assertEquals(37.0,result[0].lat!!,0.0);assertEquals(128.949,result[0].lng!!,0.0)
        assertEquals(2,result[1].selectedCount);assertNull(result[1].selectedBy);assertNull(result[1].lat)
    }

    @Test fun friendsReadTheNativeTransportProjectionWithoutNumericCoercion() {
        val response=wire("""{"friends":[
            {"id":"$me","name":"사용자E","hasVehicle":true,"tripState":"none"},
            {"id":"team-${"f".repeat(40)}","name":"사용자E","hasVehicle":false,"tripState":"pending"},
            {"id":"team-${"a".repeat(40)}","name":"사용자C","hasVehicle":null,"tripState":"accepted"}]}""")
        val friends=NativeTripsCodec.friends(response)
        assertEquals(listOf("none","pending","accepted"),friends.map {it.state})
        assertEquals(listOf(true,false,null),friends.map {it.hasVehicle})
        for(value in listOf("0","1","\"true\""))reject("friend hasVehicle=$value") {
            NativeTripsCodec.friends(wire("""{"friends":[{"id":"$me","name":"사용자E","hasVehicle":$value,"tripState":"pending"}]}"""))
        }
    }

    @Test fun integerBoundsAreCheckedBeforeNarrowingLongs() {
        val minimum=NativeTripsCodec.list(list("1","0","1","0"))
        assertEquals(1,minimum.trips.single().memberCount);assertEquals(0,minimum.invitations.single().carCount)
        val maximum=NativeTripsCodec.list(list("20","20","20","20"))
        assertEquals(20,maximum.trips.single().memberCount);assertEquals(20,maximum.invitations.single().carCount)
        val minDetail=NativeTripsCodec.detail(detail("1","1","1","0"),trip)
        assertEquals(1,minDetail.cars.single().seats);assertEquals(0,minDetail.courses!!.single().stopCount)
        val maxDetail=NativeTripsCodec.detail(detail("8","2147483647","2147483647","100"),trip)
        assertEquals(8,maxDetail.cars.single().seats);assertEquals(2147483647L,maxDetail.revision)
        val course=maxDetail.courses!!.single()
        assertEquals(Int.MAX_VALUE,course.version);assertEquals(100,course.stopCount)
        for(count in listOf(0,20))assertEquals(count,NativeTripsCodec.places(places(count.toString()))[1].selectedCount)
    }

    @Test fun listRejectsOutOfRangeAndNonIntegerCountsFromJson() {
        val wrong=listOf("-1","21","4294967302","9223372036854775807","1.5","1.0","1e0","\"6\"","true")
        for(value in wrong) {
            reject("memberCount=$value") {NativeTripsCodec.list(list(memberCount=value))}
            reject("carCount=$value") {NativeTripsCodec.list(list(carCount=value))}
            reject("invited memberCount=$value") {NativeTripsCodec.list(list(invitedMembers=value))}
            reject("invited carCount=$value") {NativeTripsCodec.list(list(invitedCars=value))}
        }
        for(value in listOf("0","null"))reject("required memberCount=$value") {NativeTripsCodec.list(list(memberCount=value))}
        reject("required carCount=null") {NativeTripsCodec.list(list(carCount="null"))}
        reject("invited memberCount=0") {NativeTripsCodec.list(list(invitedMembers="0"))}
    }

    @Test fun detailRejectsOutOfRangeAndNonIntegerNumbersFromJson() {
        for(value in listOf("0","9","4294967300","9223372036854775807","4.5","4.0","4e0","\"4\"","true","null"))
            reject("seats=$value") {NativeTripsCodec.detail(detail(seats=value),trip)}
        for(value in listOf("0","-1","2147483648","4294967297","9223372036854775807","1.5","1.0","1e0","\"1\"","true")) {
            reject("revision=$value") {NativeTripsCodec.detail(detail(revision=value),trip)}
            reject("version=$value") {NativeTripsCodec.detail(detail(version=value),trip)}
        }
        for(value in listOf("-1","101","4294967298","9223372036854775807","2.5","2.0","2e0","\"2\"","false"))
            reject("stopCount=$value") {NativeTripsCodec.detail(detail(stopCount=value),trip)}
    }

    @Test fun placesRejectOutOfRangeAndNonIntegerSelectedCountsFromJson() {
        for(value in listOf("-1","21","4294967298","9223372036854775807","2.5","2.0","2e0","\"2\"","true"))
            reject("selectedBy=$value") {NativeTripsCodec.places(places(selected=value))}
    }

    @Test fun coordinatesRetainTheirBoundsForIntegerAndDecimalJsonNumbers() {
        for((lat,lng) in listOf("-90" to "-180","90" to "180","37.773" to "128.949")) {
            val result=NativeTripsCodec.places(places(lat=lat,lng=lng)).first()
            assertEquals(lat.toDouble(),result.lat!!,0.0);assertEquals(lng.toDouble(),result.lng!!,0.0)
            val stop=NativeTripsCodec.detail(detail(lat=lat,lng=lng),trip).courses!!.single().stops!!.first()
            assertEquals(lat.toDouble(),stop.lat!!,0.0);assertEquals(lng.toDouble(),stop.lng!!,0.0)
        }
        for(value in listOf("-91","91","90.0001","9223372036854775807","1e999","\"37\"","true")) {
            reject("place lat=$value") {NativeTripsCodec.places(places(lat=value))}
            reject("stop lat=$value") {NativeTripsCodec.detail(detail(lat=value).apply {
                getJSONArray("cars").getJSONObject(0).remove("places")
            },trip)}
        }
        for(value in listOf("-181","181","180.0001","9223372036854775807","1e999","\"128\"","false")) {
            reject("place lng=$value") {NativeTripsCodec.places(places(lng=value))}
            reject("stop lng=$value") {NativeTripsCodec.detail(detail(lng=value).apply {
                getJSONArray("cars").getJSONObject(0).remove("places")
            },trip)}
        }
    }

    @Test fun nullableNumbersRemainNullAfterTheNativeTransportParser() {
        val invitation=NativeTripsCodec.list(list(invitedMembers="null",invitedCars="null")).invitations.single()
        assertNull(invitation.memberCount);assertNull(invitation.carCount)
        val result=NativeTripsCodec.detail(detail(revision="null",version="null",stopCount="null",lat="null",lng="null"),trip)
        val course=result.courses!!.single()
        assertNull(result.revision);assertNull(course.version);assertNull(course.stopCount)
        assertNull(course.stops!!.first().lat);assertNull(result.cars.single().places!!.single().lng)
        assertNull(NativeTripsCodec.places(places(selected="null"))[1].selectedCount)
    }

    @Test fun currentLocationShareMustBelongToTheRequestedTrip() {
        val value=wire("""{"tripId":"$trip","serverNow":"2026-11-11T01:00:00Z","shareId":"${"f".repeat(32)}","locations":[],"cars":[]}""")
        assertEquals("f".repeat(32),NativeTripsCodec.locationShare(value,trip).shareId)
        reject("another trip") {NativeTripsCodec.locationShare(value,invitedTrip)}
        reject("invalid sharing segment") {NativeTripsCodec.locationShare(value.put("shareId","previous"),trip)}
        value.put("shareId",org.json.JSONObject.NULL)
        assertNull(NativeTripsCodec.locationShare(value,trip).shareId)
    }

    @Test fun carLocationsCarryOnlyStrictCurrentPositionsAndTheirAge() {
        val car="b".repeat(32)
        fun page(row: String)=wire("""{"tripId":"$trip","serverNow":"2026-11-11T01:00:40Z","shareId":null,"locations":[],"cars":[$row]}""")
        val row="""{"carId":"$car","source":"vehicle","latitude":37.5,"longitude":127.25,"accuracyMeters":null,"capturedAt":"2026-11-11T01:00:00Z"}"""
        val position=NativeTripsCodec.locationShare(page(row),trip).cars.single()
        assertEquals(car,position.carId);assertEquals("vehicle",position.source)
        assertEquals(37.5,position.latitude,0.0);assertEquals(127.25,position.longitude,0.0)
        assertEquals(40_000L,position.ageMillis)
        reject("missing cars") {NativeTripsCodec.locationShare(wire("""{"tripId":"$trip","serverNow":"2026-11-11T01:00:00Z","shareId":null,"locations":[]}"""),trip)}
        reject("duplicate car") {NativeTripsCodec.locationShare(page("$row,$row"),trip)}
        reject("route leak") {NativeTripsCodec.locationShare(page(row.replace("}",",\"routeOrder\":[]}")),trip)}
        reject("out of range") {NativeTripsCodec.locationShare(page(row.replace("37.5","97.5")),trip)}
        reject("unknown source") {NativeTripsCodec.locationShare(page(row.replace("vehicle","watch")),trip)}
    }

    @Test fun currentLocationPreservesTheSdkCaptureTimeAndNeverInventsAccuracy() {
        val captured=java.time.Instant.parse("2026-11-11T01:00:00Z").toEpochMilli()
        val fix=TripLocationFix(37.5,127.0,captured)
        val body=NativeTripsCodec.locationBody("f".repeat(32),fix)
        assertEquals("2026-11-11T01:00:00Z",body.getString("capturedAt"))
        assertTrue(body.isNull("accuracyMeters"))
        reject("nonfinite location") {NativeTripsCodec.locationBody("f".repeat(32),fix.copy(latitude=Double.NaN))}
        reject("negative accuracy") {NativeTripsCodec.locationBody("f".repeat(32),fix.copy(accuracyMeters=-1.0))}
    }
}
