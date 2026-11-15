package io.wegoh.app.nativeauth

import io.wegoh.app.canRespondToSignal
import io.wegoh.app.signalFromMyCar
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class TripSignalsCodecTest {
    @Test fun devWireAcceptsOneTwoAndThreeSignalsWithSpaceOrIsoTimestamp() {
        for(count in 1..3)for(separator in listOf(" ","T")) {
            val signals=TripSignalsDevFixture.signals(count,"2026-11-09${separator}13:13:15.323474+09:00")
            assertEquals(count,signals.size)
            assertEquals(count,signals.map {it.id}.distinct().size)
            assertTrue(signals.all {java.time.Instant.parse(it.createdAt)==java.time.Instant.parse("2026-11-09T04:13:15.323474Z")})
            assertEquals(count,TripSignalsCodec.newSignals(emptySet(),signals,"me").size)
        }
    }
    @Test fun candidatesExposeOnlyAheadPlacesWithFacilitiesAndNullableDetours() {
        val value=JSONObject("""{"candidates":[
            {"name":"국도 식당","lat":37.1,"lng":128.1,"verdict":"off_route","label":"경로 벗어남","fromRequesterMeters":11000,"detourSeconds":null,"facilities":null},
            {"name":"휴게소","lat":37.2,"lng":128.2,"verdict":"ahead","label":"들르면 +3분","fromRequesterMeters":6000,"detourSeconds":180,"facilities":{"toilet":true,"nursing":false}},
            {"name":"앞쪽 쉼터","lat":37.3,"lng":128.3,"verdict":"heading","label":"앞쪽 · 9km","fromRequesterMeters":9000,"detourSeconds":20,"facilities":null}]}""")
        val parsed=TripSignalsCodec.candidates(value)
        assertEquals(listOf("ahead"),parsed.map {it.verdict})
        assertEquals(setOf("toilet"),parsed.first().facilities)
        assertEquals(180.0,parsed.first().detourSeconds!!,0.0)
    }
    @Test fun candidateContextUsesTheLeadingCarAndExactFacilityKeys() {
        val value=JSONObject("""{"basis":"route","cars":[{"carId":"rear","state":"same_road","alongMeters":0},{"carId":"lead","state":"same_road","alongMeters":500}],"candidates":[{"name":"서산휴게소","lat":36.7,"lng":126.5,"verdict":"ahead","label":"모든 차 앞쪽","fromRequesterMeters":1500,"fromLeadMeters":1000,"detourSeconds":null,"facilities":{"toilet":true,"gasStation":true}}]}""")
        val candidate=TripSignalsCodec.candidates(value).single()
        assertEquals("lead",candidate.leaderCarId)
        assertEquals(1000.0,candidate.fromLeadMeters!!,0.0)
        assertEquals("route",candidate.basis)
        val selected=setOf(TripSignalFacility.TOILET,TripSignalFacility.GAS_STATION)
        val body=TripSignalsCodec.candidateBody(TripSignalKind.FUEL,SignalLocation(SignalPoint(36.5,126.5,180.0)),selected)
        assertEquals(setOf("toilet","gasStation"),(0 until body.getJSONArray("requiredFacilities").length()).map {body.getJSONArray("requiredFacilities").getString(it)}.toSet())
        assertEquals(9,TripSignalKind.entries.size)
        assertEquals(setOf(TripSignalFacility.EV_CHARGER),TripSignalKind.EV_CHARGE.defaultFacilities)
    }
    @Test fun repeatedGroupVoteKeepsTheFirstChoiceAndResponder() {
        val reply=TripSignalsCodec.voteResult(JSONObject("""{"status":"saved","already":true,"choice":"pass","responderAccountId":"first"}"""),"agree")
        assertEquals("pass",reply.choice);assertTrue(reply.already);assertEquals("first",reply.responderAccountId)
    }
    private fun list()=TripSignalsCodec.signals(JSONObject("""{"signals":[
        {"id":"new","accountId":"other","kind":"hungry","destination":{"name":"휴게소","latitude":37.2,"longitude":128.2},"createdAt":"2026-11-09T10:00:00Z","contextState":"valid","votes":{"agree":1,"pass":0},"myVote":null,"agreed":false},
        {"id":"old","accountId":"other","kind":"rest","destination":null,"createdAt":"2026-11-09T09:00:00Z","contextState":"valid","votes":{"agree":0,"pass":0},"myVote":"pass","agreed":false},
        {"id":"mine","accountId":"me","kind":"nursing","destination":null,"createdAt":"2026-11-09T08:00:00Z","contextState":"valid","votes":{"agree":1,"pass":0},"myVote":"agree","agreed":false},
        {"id":"changed","accountId":"other","kind":"drowsy","destination":null,"createdAt":"2026-11-09T07:00:00Z","contextState":"reconfirm","votes":{"agree":0,"pass":0},"myVote":null,"agreed":false}]}"""))
    @Test fun parsesTripSignalsAndDetectsNewUnvotedSignalsFromOtherCars() {
        val parsed=list()
        assertEquals(TripSignalKind.HUNGRY,parsed.first().kind)
        assertEquals("휴게소",parsed.first().destination!!.name)
        assertEquals(listOf("new"),TripSignalsCodec.newSignals(emptySet(),parsed,"me").map {it.id})
        assertTrue(TripSignalsCodec.newSignals(setOf("new"),parsed,"me").isEmpty())
    }
    @Test fun majorityUsesCarsAndDoesNotDoubleCountRequestersOwnVote() {
        assertTrue(list().first().hasMajority(3,"me"))
        assertFalse(list().first().hasMajority(4,"me"))
        assertEquals(1,list()[2].agreeCount("me"))
        assertFalse(list()[2].hasMajority(3,"me"))
    }
    @Test fun activeSummaryAndServerDriverVotesSurviveHiddenOrHistoricalSignals() {
        val hidden=TripSignalsCodec.page(JSONObject("""{"signals":[],"hasActiveSignal":true}"""))
        assertTrue(hidden.hasActiveSignal);assertTrue(hidden.signals.isEmpty())
        assertFalse(TripSignalsCodec.page(JSONObject(TripSignalsDevFixture.response(1))).hasActiveSignal)
        val value=JSONObject(TripSignalsDevFixture.response(1)).apply {
            put("hasActiveSignal",false)
            getJSONArray("signals").getJSONObject(0).put("inProgress",false).put("resolution","agreed")
                .put("driverVotes",JSONObject("""{"agree":2,"pass":0,"total":3}"""))
        }
        val page=TripSignalsCodec.page(value)
        assertFalse(page.hasActiveSignal)
        val signal=page.signals.single()
        assertFalse(signal.inProgress)
        assertEquals("agreed",signal.resolution)
        assertEquals(2,signal.agreeCount("passenger"))
        assertTrue(signal.hasMajority(20,"passenger"))
        assertFalse(signal.copy(resolution="pending",driverAgrees=2,driverTotal=2).hasMajority(3,"passenger"))
        assertTrue(signal.copy(resolution="passed",driverPasses=0,driverTotal=1).hasPassed(3))
        assertTrue(TripSignalsCodec.newSignals(emptySet(),page.signals,"passenger").isEmpty())
    }
    private val requestingCar="a".repeat(32)
    private val respondingCar="b".repeat(32)
    private fun groupPage()=JSONObject(TripSignalsDevFixture.response(1)).apply {
        put("hasActiveSignal",true)
        getJSONArray("signals").getJSONObject(0).apply {
            put("decisionRule","other-car-groups-v1")
            put("requesterCarId",requestingCar)
            put("requiredCarIds",org.json.JSONArray().put(respondingCar))
            put("canRespond",true)
            put("myGroupChoice",JSONObject.NULL)
            put("inProgress",true)
            put("resolution","pending")
            put("groupVotes",JSONObject("""{"agree":0,"pass":0,"total":1}"""))
            put("groupResponses",org.json.JSONArray().put(JSONObject().put("carId",respondingCar)
                .put("carName","함께 가는 차").put("choice",JSONObject.NULL)))
        }
    }
    @Test fun candidateReceiptIsPassedAsAnOpaqueTopLevelValueWithoutClientMetrics() {
        val destination=SignalDestination("휴게소",37.5,127.1,"abc_123-XYZ")
        val body=TripSignalsCodec.sendBody(TripSignalKind.REST,destination)
        assertEquals("abc_123-XYZ",body.getString("candidateReceipt"))
        assertEquals(setOf("kind","destination","candidateReceipt"),body.keys().asSequence().toSet())
        assertEquals(setOf("name","latitude","longitude"),body.getJSONObject("destination").keys().asSequence().toSet())
        assertFalse(TripSignalsCodec.sendBody(TripSignalKind.REST,destination.copy(candidateReceipt=null)).has("candidateReceipt"))
        for(invalid in listOf("has.dot","a".repeat(2049),"")) {
            assertTrue(runCatching {TripSignalsCodec.sendBody(TripSignalKind.REST,destination.copy(candidateReceipt=invalid))}.isFailure)
        }
    }
    @Test fun signalResponseSourceAndVerifiedCandidateContextAreExplicitAndBounded() {
        val value=groupPage();val signal=value.getJSONArray("signals").getJSONObject(0)
        signal.getJSONArray("groupResponses").getJSONObject(0).put("responseSource","iphone")
        signal.put("candidateDetails",JSONObject().put("routeName","서해안고속도로").put("direction","목포 방향")
            .put("fromLeadMeters",12500).put("detourSeconds",240))
        val parsed=TripSignalsCodec.page(value).signals.single()
        assertEquals("iphone",parsed.groupResponses.single().responseSource)
        assertEquals(TripSignalCandidateDetails("서해안고속도로","목포 방향",12500,240),parsed.candidateDetails)
        signal.getJSONObject("candidateDetails").put("fromLeadMeters",-1)
        assertTrue(runCatching {TripSignalsCodec.page(value)}.isFailure)
        signal.put("candidateDetails",JSONObject.NULL)
        signal.getJSONArray("groupResponses").getJSONObject(0).put("responseSource",42)
        assertTrue(runCatching {TripSignalsCodec.page(value)}.isFailure)
    }
    private fun passengerTrip(): TripDetail {
        val me=TripMember("passenger","동승자",true,false,true,carId=respondingCar)
        val car=TripCar(respondingCar,"함께 가는 차","driver","운전자",4,false,true,
            listOf(TripPassenger(me.id,me.name,true)))
        return TripDetail("trip","여행","",listOf(me),listOf(car),state="active")
    }
    @Test fun groupDecisionReadsOtherCarsOnlyAndLetsTheirPassengerRespond() {
        val signal=TripSignalsCodec.page(groupPage()).signals.single()
        assertTrue(signal.isGroupDecision)
        assertEquals(requestingCar,signal.requesterCarId)
        assertEquals(listOf(respondingCar),signal.requiredCarIds)
        assertEquals(TripGroupVotes(0,0,1),signal.groupVotes)
        assertEquals(listOf(TripGroupResponse(respondingCar,"함께 가는 차",null)),signal.groupResponses)
        assertNull(signal.responseChoice)
        val trip=passengerTrip()
        assertFalse(checkNotNull(trip.myCar).isMine)
        assertTrue(trip.canRespondToSignal(signal))
        assertFalse(trip.signalFromMyCar(signal))
        assertFalse(trip.canRespondToSignal(signal.copy(requesterCarId=respondingCar)))
        assertTrue(trip.canRespondToSignal(signal.copy(requiredCarIds=emptyList(),requesterCarId=null)))
        assertFalse(trip.canRespondToSignal(signal.copy(canRespond=false)))
    }
    @Test fun firstReplyFromTheCarBlocksOtherMembersAndFreshPopup() {
        val value=groupPage()
        value.getJSONArray("signals").getJSONObject(0).apply {
            put("canRespond",false)
            put("myGroupChoice","agree")
            getJSONObject("groupVotes").put("agree",1)
            getJSONArray("groupResponses").getJSONObject(0).put("choice","agree")
        }
        val signal=TripSignalsCodec.page(value).signals.single()
        assertNull(signal.myVote)
        assertEquals("agree",signal.responseChoice)
        assertEquals(1,signal.agreeCount("passenger"))
        assertFalse(passengerTrip().canRespondToSignal(signal))
        assertTrue(TripSignalsCodec.newSignals(emptySet(),listOf(signal),"passenger").isEmpty())
    }
    @Test fun groupResolutionWaitsForTheServerEvenWhenVisibleRepliesLookDecided() {
        val signal=TripSignalsCodec.page(groupPage()).signals.single().copy(groupVotes=TripGroupVotes(1,0,1))
        assertFalse(signal.hasMajority(1,"passenger"))
        assertFalse(signal.copy(groupVotes=TripGroupVotes(0,1,1)).hasPassed(1))
        assertTrue(signal.copy(resolution="agreed",groupVotes=TripGroupVotes(0,0,1)).hasMajority(10,"passenger"))
        assertTrue(signal.copy(resolution="passed",groupVotes=TripGroupVotes(0,0,1)).hasPassed(10))
        assertFalse(passengerTrip().canRespondToSignal(signal.copy(resolution="agreed",inProgress=false)))
        assertFalse(passengerTrip().canRespondToSignal(signal.copy(decisionRule="future-group-rule")))
        assertFalse(signal.copy(decisionRule="future-group-rule",resolution=null).hasMajority(1,"passenger"))
        assertTrue(TripSignalsCodec.newSignals(emptySet(),listOf(signal.copy(canRespond=false)),"passenger").isEmpty())
    }
    @Test fun groupMetadataRejectsInvalidPermissionChoiceAndCounts() {
        for(change in listOf<(JSONObject)->Unit>(
            {it.put("canRespond","true")},
            {it.put("myGroupChoice","later")},
            {it.getJSONObject("groupVotes").put("agree",2)}
        )) {
            val value=groupPage()
            change(value.getJSONArray("signals").getJSONObject(0))
            assertTrue(runCatching {TripSignalsCodec.page(value)}.isFailure)
        }
    }
    @Test fun legacySignalStillUsesTheDriverAndPersonalVote() {
        val signal=list().first()
        val trip=passengerTrip()
        assertFalse(signal.isGroupDecision)
        assertNull(signal.canRespond)
        assertFalse(trip.canRespondToSignal(signal))
        val driver=checkNotNull(trip.myCar).copy(isMine=true,iRide=false)
        assertTrue(trip.copy(cars=listOf(driver)).canRespondToSignal(signal))
        assertFalse(trip.copy(cars=listOf(driver)).canRespondToSignal(signal.copy(myVote="agree")))
    }
    @Test fun voteRequestContainsOnlyChoice() {
        assertEquals("""{"choice":"agree"}""",TripSignalsCodec.voteBody("agree").toString())
        assertEquals("""{"choice":"pass"}""",TripSignalsCodec.voteBody("pass").toString())
    }
    @Test fun noPlaceSendOmitsDestinationAndCandidateRequestUsesNaviCoordinates() {
        val body=TripSignalsCodec.sendBody(TripSignalKind.RESTROOM,null)
        assertEquals("restroom",body.getString("kind"));assertFalse(body.has("destination"))
        val candidate=TripSignalsCodec.candidateBody(TripSignalKind.REST,SignalLocation(SignalPoint(37.0,128.0,90.0)))
        assertTrue(candidate.isNull("destination"))
        assertEquals(90.0,candidate.getJSONObject("location").getDouble("heading"),0.0)
        val destination=TripSignalsCodec.sendBody(TripSignalKind.HUNGRY,SignalDestination("휴게소",37.2,128.2)).getJSONObject("destination")
        assertEquals(setOf("name","latitude","longitude"),destination.keys().asSequence().toSet())
    }
}
