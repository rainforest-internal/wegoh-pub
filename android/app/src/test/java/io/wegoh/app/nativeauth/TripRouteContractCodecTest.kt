package io.wegoh.app.nativeauth

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class TripRouteContractCodecTest {
    private val car="a".repeat(32)
    private val pickup=TripRouteItem("pickup","b".repeat(32))
    private val join=TripRouteItem("course","join","coast")
    private val next=TripRouteItem("course","beach","coast")
    private fun plan()=JSONObject().put("contractVersion",2).put("phase","waiting")
        .put("segments",JSONArray().put(JSONObject().put("segment","pickup").put("items",NativeTripsCodec.routeBody(listOf(pickup)).getJSONArray("items")))
            .put(JSONObject().put("segment","shared").put("items",NativeTripsCodec.routeBody(listOf(join,next)).getJSONArray("items")))
            .put(JSONObject().put("segment","drop").put("items",JSONArray())))
        .put("joinPoint",JSONObject().put("courseId","coast").put("ref","join").put("name","간월암").put("lat",36.6).put("lng",126.4))
        .put("joinEtaSeconds",JSONObject.NULL).put("progressRevision",2)
        .put("next",NativeTripsCodec.routeBody(listOf(next)).getJSONArray("items").getJSONObject(0))
        .put("joinBarrier",JSONObject().put("arrivedCarIds",JSONArray().put(car)).put("totalCarCount",2).put("released",false))
        .put("progress",JSONObject.NULL)
    private fun status(phase: String,progress: Any=JSONObject.NULL)=JSONObject().put("phase",phase).put("joinEtaSeconds",JSONObject.NULL).put("progress",progress)
    private fun publicProgress(fraction: Any=0.4)=JSONObject().put("target",NativeTripsCodec.routeBody(listOf(next)).getJSONArray("items").getJSONObject(0))
        .put("remainingMeters",1200).put("legFraction",fraction)
    @Test fun liveProgressIsParsedStrictlyForOwnPlanAndPublicStatus() {
        val own=TripRouteContractCodec.plan(plan().put("progress",JSONObject().put("remainingMeters",830).put("legFraction",0.25)))
        assertEquals(TripPlanProgress(830,0.25),own.progress)
        assertEquals(TripPlanProgress(830,null),TripRouteContractCodec.plan(plan().put("progress",
            JSONObject().put("remainingMeters",830).put("legFraction",JSONObject.NULL))).progress)
        assertNull(TripRouteContractCodec.plan(plan()).progress)
        assertEquals(TripStatusProgress(next,1200,0.4),TripRouteContractCodec.status(status("shared",publicProgress())).progress)
        assertEquals(TripStatusProgress(next,1200,null),TripRouteContractCodec.status(status("pickup",publicProgress(JSONObject.NULL))).progress)
        assertNull(TripRouteContractCodec.status(status("drop")).progress)
        for(value in listOf(plan().put("progress",JSONObject().put("remainingMeters",-1).put("legFraction",0.2)),
            plan().put("progress",JSONObject().put("remainingMeters",10).put("legFraction",1.5)),
            plan().put("progress",JSONObject().put("remainingMeters",10).put("legFraction",true)),
            plan().put("progress",JSONObject().put("remainingMeters",10)),
            plan().put("progress",JSONObject().put("remainingMeters",10).put("legFraction",0.1).put("lat",36.6)),
            plan().apply {remove("progress")}))assertTrue(runCatching {TripRouteContractCodec.plan(value)}.isFailure)
        for(value in listOf(status("drop",publicProgress()),status("shared",publicProgress().put("target",
            NativeTripsCodec.routeBody(listOf(pickup)).getJSONArray("items").getJSONObject(0))),
            status("shared",publicProgress().put("remainingMeters",1.5)),JSONObject().put("phase","shared").put("joinEtaSeconds",JSONObject.NULL)))
            assertTrue(runCatching {TripRouteContractCodec.status(value)}.isFailure)
    }
    @Test fun displayRefreshMovesOnlyMatchingLiveProgress() {
        val parsed=TripRouteContractCodec.plan(plan())
        val own=TripCar(car,"사용자A의 차","team-"+"c".repeat(40),"사용자A",4,true,false,emptyList(),
            routePlan=parsed,routeStatus=TripRouteStatus("waiting"))
        val moved=TripPlanProgress(500,0.5)
        val fresh=own.copy(routePlan=parsed.copy(progress=moved),routeStatus=TripRouteStatus("waiting",progress=TripStatusProgress(join,600,null)))
        val merged=withLiveProgress(listOf(own),listOf(fresh)).single()
        assertEquals(moved,merged.routePlan?.progress);assertEquals(600,merged.routeStatus?.progress?.remainingMeters)
        val advanced=fresh.copy(routePlan=parsed.copy(progressRevision=3,progress=moved),routeStatus=TripRouteStatus("shared",progress=TripStatusProgress(join,600,null)))
        assertEquals(own,withLiveProgress(listOf(own),listOf(advanced)).single())
    }
    @Test fun waitingKeepsTheServerNextWithoutInventingReleaseOrEta() {
        val parsed=TripRouteContractCodec.plan(plan())
        assertEquals("waiting",parsed.phase);assertEquals(next,parsed.next)
        assertEquals(2L,parsed.progressRevision);assertFalse(parsed.joinBarrier.released);assertNull(parsed.joinEtaSeconds)
        assertEquals(listOf("pickup","shared","drop"),parsed.segments.map {it.segment})
        for(status in listOf("updated","unchanged"))
            assertEquals(parsed,TripRouteContractCodec.arrival(JSONObject().put("status",status).put("routePlan",plan())))
    }
    @Test fun arrivalBodyKeepsTwoIndependentRevisionsAndExactItem() {
        val body=TripRouteContractCodec.arrivalBody(7,2,join)
        assertEquals(setOf("routeRevision","progressRevision","item"),body.keys().asSequence().toSet())
        assertEquals(7L,body.getLong("routeRevision"));assertEquals(2L,body.getLong("progressRevision"))
        assertEquals(join,NativeTripsCodec.routeItem(body.getJSONObject("item")))
        assertFalse(body.has("singleJoinCompletion"))
        assertEquals("explicit-v1",TripRouteContractCodec.arrivalBody(7,2,join,true).getString("singleJoinCompletion"))
        assertTrue(runCatching {TripRouteContractCodec.arrivalBody(-1,2,join)}.isFailure)
        assertTrue(runCatching {TripRouteContractCodec.arrivalBody(1,2,join.copy(courseId=null))}.isFailure)
    }
    @Test fun singleJoinCompletionPreservesRevisionBoundsAndRejectsDetourOrWaiting() {
        val body=TripRouteContractCodec.completionBody(7,2)
        assertEquals(setOf("routeRevision","progressRevision"),body.keys().asSequence().toSet())
        assertEquals(7L,body.getLong("routeRevision"));assertEquals(2L,body.getLong("progressRevision"))
        for(invalid in listOf(-1L,Int.MAX_VALUE.toLong()+1)) {
            assertTrue(runCatching {TripRouteContractCodec.completionBody(invalid,2)}.isFailure)
            assertTrue(runCatching {TripRouteContractCodec.completionBody(7,invalid)}.isFailure)
        }
        val held=TripRouteContractCodec.plan(plan()).let {it.copy(phase="shared",next=join,
            joinBarrier=it.joinBarrier.copy(released=true),segments=it.segments.map {segment->
                if(segment.segment=="shared")segment.copy(items=listOf(join)) else segment
            })}
        assertTrue(held.awaitingJoinCourseCompletion)
        assertFalse(held.copy(phase="waiting").awaitingJoinCourseCompletion)
        assertFalse(held.copy(next=TripRouteItem("signal","d".repeat(32))).awaitingJoinCourseCompletion)
        assertFalse(TripRouteContractCodec.plan(plan()).copy(phase="shared",next=join).awaitingJoinCourseCompletion)
    }
    @Test fun unknownFieldsAndMalformedProgressDoNotBecomeUsablePlans() {
        for(value in listOf(plan().put("phase","guessed"),plan().put("progressRevision",true),plan().put("progressRevision",1.5),
            plan().put("joinEtaSeconds",60),plan().put("extra",true),plan().apply {
                getJSONArray("segments").getJSONObject(0).put("segment","shared")
            },plan().apply {getJSONObject("next").put("ref","outside")},plan().apply {
                getJSONArray("segments").getJSONObject(1).getJSONArray("items").getJSONObject(0).put("rawLocation",JSONArray())
            }))assertTrue(runCatching {TripRouteContractCodec.plan(value)}.isFailure)
    }
    @Test fun legacyStartOmitsVersionAndNewStartSelectsV2Explicitly() {
        assertFalse(TripActionCodec.request(TripAction.Start(3)).body.has("routeContractVersion"))
        assertEquals(2,TripActionCodec.request(TripAction.Start(3,2)).body.getInt("routeContractVersion"))
        assertTrue(runCatching {TripActionCodec.request(TripAction.Start(3,3))}.isFailure)
        assertFalse(TripActionCodec.request(TripAction.Start(3,2)).body.has("endActiveTrip"))
        assertTrue(TripActionCodec.request(TripAction.Start(3,2,endActiveTrip=true)).body.getBoolean("endActiveTrip"))
    }
    @Test fun modernRoutePatchesPreserveProgressWithoutReconstructingOtherCarPlans() {
        val own=TripCar(car,"사용자A의 차","team-"+"c".repeat(40),"사용자A",4,true,false,emptyList())
        val other=own.copy(id="d".repeat(32),isMine=false)
        val base=TripDetail("e".repeat(32),"여행","",emptyList(),listOf(own,other),revision=3,routeContractVersion=2)
        fun carUpdate(id: String,mine: Boolean)=JSONObject().put("id",id).put("isMine",mine).put("iRide",false)
            .put("places",JSONArray()).put("routeOrder",JSONObject.NULL).put("routePlan",if(mine)plan() else JSONObject.NULL)
            .put("routeStatus",status("waiting"))
        val update=JSONObject().put("id",base.id).put("revision",3).put("routeContractVersion",2).put("courses",JSONArray())
            .put("cars",JSONArray().put(carUpdate(own.id,true).put("routeRevision",1)).put(carUpdate(other.id,false)))
        val parsed=NativeTripsCodec.section(base,update,"route",1000)
        assertEquals(3L,parsed.revision);assertEquals(1L,parsed.myCar?.routeRevision)
        assertEquals(2L,parsed.myCar?.routePlan?.progressRevision)
        assertNull(parsed.cars[1].routePlan);assertEquals("waiting",parsed.cars[1].routeStatus?.phase)
        assertTrue(parsed.cars[1].places.orEmpty().isEmpty())
        update.getJSONArray("cars").getJSONObject(1).put("routePlan",plan())
        assertTrue(runCatching {NativeTripsCodec.section(base,update,"route",1000)}.isFailure)
    }
}
