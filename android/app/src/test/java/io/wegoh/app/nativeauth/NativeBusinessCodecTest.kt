package io.wegoh.app.nativeauth

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class NativeBusinessCodecTest {
    private val id="a".repeat(32)
    private val room="b".repeat(32)
    private val owner="team-"+"c".repeat(40)
    private val device="d".repeat(32)
    private val time="2026-11-01T00:00:00Z"
    private fun reject(action: ()->Unit) {
        try {action();fail("invalid or unauthorized projection must fail")} catch(_: IllegalStateException) {}
        catch(_: IllegalArgumentException) {}
        catch(_: org.json.JSONException) {}
        catch(_: NoSuchElementException) {}
    }
    private fun command()=JSONObject().put("id",id).put("roomId",room).put("ownerId",owner)
        .put("targetDeviceId",device).put("requesterId","team-"+"e".repeat(40))
        .put("capabilityId","fixture.no-effect").put("capabilityRevision",1).put("stage","queued")
        .put("mayHaveExecuted",false).put("physicalExecutionVerified",false).put("createdAt",time).put("expiresAt",time)
    private fun inbox(item: JSONObject?=null)=JSONObject().put("serverNow",time)
        .put("supportedControlActions",org.json.JSONArray()).put("requests",org.json.JSONArray().apply {if(item!=null)put(item)})
    @Test fun emptyInboxNeverInventsCapabilitiesOrExecution() {
        val value=NativeBusinessCodec.commands(inbox(),device,owner)
        assertTrue(value.commands.isEmpty());assertEquals(0,value.supportedActionCount)
    }
    @Test fun inboxAcceptsServerActionsThatTakeArguments() {
        val actions=org.json.JSONArray()
        listOf("empty-object","hvac-celsius","hvac-fan","seat-switch","seat-level","window-position","switch").forEachIndexed {index,kind->
            actions.put(JSONObject().put("id","action.$index").put("revision",1).put("label","조작 $index").put("argumentKind",kind))
        }
        assertEquals(7,NativeBusinessCodec.commands(inbox().put("supportedControlActions",actions),device,owner).supportedActionCount)
        val unknown=org.json.JSONArray().put(JSONObject().put("id","action.x").put("revision",1).put("label","조작").put("argumentKind","free-text"))
        reject {NativeBusinessCodec.commands(inbox().put("supportedControlActions",unknown),device,owner)}
    }
    @Test fun commandMustBelongToCurrentOwnerAndDevice() {
        reject {NativeBusinessCodec.commands(inbox(command().put("ownerId","team-"+"f".repeat(40))),device,owner)}
        reject {NativeBusinessCodec.commands(inbox(command().put("targetDeviceId","0".repeat(32))),device,owner)}
    }
    @Test fun commandUnknownStatePhysicalClaimAndDuplicateAreRejected() {
        reject {NativeBusinessCodec.commands(inbox(command().put("stage","success")),device,owner)}
        reject {NativeBusinessCodec.commands(inbox(command().put("physicalExecutionVerified",true)),device,owner)}
        val value=inbox(command());value.getJSONArray("requests").put(command())
        reject {NativeBusinessCodec.commands(value,device,owner)}
        assertEquals(BusinessCommand.Stage.QUEUED,NativeBusinessCodec.commands(inbox(command()),device,owner).commands.single().stage)
    }
    @Test fun commandKeepsTheServerRejectionReason() {
        val rejected=command().put("stage","rejected").put("reason","driving-restricted")
        val value=NativeBusinessCodec.commands(inbox(rejected),device,owner).commands.single()
        assertEquals(BusinessCommand.Stage.REJECTED,value.stage)
        assertEquals("driving-restricted",value.reason)
        assertNull(NativeBusinessCodec.commands(inbox(command().put("reason",org.json.JSONObject.NULL)),device,owner).commands.single().reason)
        reject {NativeBusinessCodec.commands(inbox(command().put("reason","x".repeat(41))),device,owner)}
        reject {NativeBusinessCodec.commands(inbox(command().put("reason",1)),device,owner)}
    }
    private fun mission()=JSONObject().put("id",id).put("roomId",room).put("ownerId",owner).put("revision",1)
        .put("title","함께 코스 완료하기").put("state","active").put("physicalArrivalVerified",false)
        .put("confirmationSource","user-confirmed").put("nativeReportingPurpose","mission-progress").put("expiresAt",time)
        .put("checkpoints",org.json.JSONArray().put(JSONObject().put("ordinal",1).put("label","첫 장소")))
        .put("participation",JSONObject().put("consent",true).put("revision",1).put("nextCheckpoint",1))
    private fun missions(item: JSONObject)=JSONObject().put("serverNow",time).put("missions",org.json.JSONArray().put(item))
    @Test fun missionRequiresExactRoomAndExplicitParticipation() {
        assertEquals(1,NativeBusinessCodec.missions(missions(mission()),room).missions.single().nextCheckpoint)
        val parsed=NativeBusinessCodec.missions(missions(mission()),room).missions.single()
        assertEquals("첫 장소",parsed.nextPlaceName)
        assertEquals(listOf("첫 장소"),parsed.checkpointLabels)
        reject {NativeBusinessCodec.missions(missions(mission()),"0".repeat(32))}
        val noConsent=mission();noConsent.getJSONObject("participation").put("consent",false)
        reject {NativeBusinessCodec.missions(missions(noConsent),room)}
        reject {NativeBusinessCodec.missions(missions(mission().put("physicalArrivalVerified",true)),room)}
    }
    @Test fun tripMissionsAreBoundToTripAndHaveNoInventedRoomOrExpiry() {
        val item=mission().apply {
            remove("roomId");remove("expiresAt");put("tripId",room);put("contractVersion",1)
        }
        val parsed=NativeBusinessCodec.tripMissions(missions(item),room).missions.single()
        assertEquals("첫 장소",parsed.nextPlaceName)
        assertNull(parsed.expiresAt)
        reject {NativeBusinessCodec.tripMissions(missions(item),"0".repeat(32))}
        reject {NativeBusinessCodec.missions(missions(item),room)}
        reject {NativeBusinessCodec.tripMissions(missions(mission()),room)}
        reject {NativeBusinessCodec.tripMissions(missions(JSONObject(item.toString()).put("roomId",room)),room)}
        reject {NativeBusinessCodec.tripMissions(missions(JSONObject(item.toString()).put("expiresAt",time)),room)}
        reject {NativeBusinessCodec.tripMissions(missions(JSONObject(item.toString()).put("contractVersion",2)),room)}
        val noConsent=JSONObject(item.toString());noConsent.getJSONObject("participation").put("consent",false)
        reject {NativeBusinessCodec.tripMissions(missions(noConsent),room)}
    }
    @Test fun missionProgressUsesExactCasAndIdempotencyFieldsAndParsesSnapshot() {
        val body=NativeBusinessCodec.missionProgressRequest(id,1,7,9)
        assertEquals(setOf("eventId","checkpoint","participationRevision","functionalRevision"),body.keys().asSequence().toSet())
        assertEquals(id,body.getString("eventId"));assertEquals(7,body.getInt("participationRevision"));assertEquals(9L,body.getLong("functionalRevision"))
        assertEquals(1,body.getInt("checkpoint"))
        val response=mission();response.getJSONObject("participation").put("revision",8).put("nextCheckpoint",JSONObject.NULL)
        val result=NativeBusinessCodec.mission(response,room)
        assertEquals(id,result.id);assertEquals(8,result.participationRevision);assertNull(result.nextCheckpoint)
        reject {NativeBusinessCodec.mission(response,"0".repeat(32))}
        reject {NativeBusinessCodec.mission(response.put("confirmationSource","gps-verified"),room)}
        for(checkpoint in listOf(0,4))reject {NativeBusinessCodec.missionProgressRequest(id,checkpoint,7,9)}
        reject {NativeBusinessCodec.missionProgressRequest("../progress",1,7,9)}
        reject {NativeBusinessCodec.missionProgressRequest(id,1,0,9)}
        reject {NativeBusinessCodec.missionProgressRequest(id,1,7,0)}
        reject {NativeBusinessCodec.missionProgressRequest(id,1,7,Int.MAX_VALUE.toLong()+1)}
    }
    private fun settings()=JSONObject().put("revision",2).put("configured",true).put("algorithm","explicit-rules-v1").put("aiUsed",false)
        .put("preferences",JSONObject().put("coursePriority","nearby").put("hideVisited",false).put("maxDistanceKm",50)
            .put("facilities",org.json.JSONArray()))
        .put("permissions",JSONObject().put("useHistory",false).put("useFeedback",false))
        .put("learning",JSONObject().put("settingsRevision",2).put("learningRevision",0).put("enabled",false)
            .put("eligibleSamples",0).put("modelVersion","personal-logistic-v1").put("status","disabled"))
    @Test fun savedRecommendationsPreserveOffConsentAndRejectStaleSettings() {
        val value=NativeBusinessCodec.recommendations(settings())
        assertFalse(value.usesHistory);assertFalse(value.usesFeedback);assertFalse(value.learningEnabled)
        val stale=settings();stale.getJSONObject("learning").put("settingsRevision",1)
        reject {NativeBusinessCodec.recommendations(stale)}
        reject {NativeBusinessCodec.recommendations(settings().put("aiUsed",true))}
    }
    private fun caution()=JSONObject().put("id",id).put("own",true).put("ownerId",owner).put("ownerName","나")
        .put("revision",1).put("kind","road-surface").put("observedAt",time).put("shareExpiresAt",JSONObject.NULL)
        .put("currentRoadConditionVerified",false).put("place",JSONObject().put("name","선택한 공공 장소"))
    private fun cautions(item: JSONObject)=JSONObject().put("serverNow",time).put("items",org.json.JSONArray().put(item)).put("nextCursor",JSONObject.NULL)
    @Test fun cautionMustKeepCurrentOwnerMeaningAndUnverifiedRoadCondition() {
        val value=NativeBusinessCodec.cautions(cautions(caution()),owner).items.single()
        assertTrue(value.own);assertEquals("선택한 공공 장소",value.placeName)
        reject {NativeBusinessCodec.cautions(cautions(caution().put("own",false)),owner)}
        reject {NativeBusinessCodec.cautions(cautions(caution().put("currentRoadConditionVerified",true)),owner)}
        reject {NativeBusinessCodec.cautions(cautions(caution().put("kind","live-hazard")),owner)}
    }
    @Test fun manuallyReportedHarshBrakingHasNoVerifiedRoadOrSensorClaim() {
        val manual=caution().put("kind","harsh-braking")
        val value=NativeBusinessCodec.cautions(cautions(manual),owner).items.single()
        assertEquals(BusinessCaution.Kind.HARSH_BRAKING,value.kind)
        assertEquals(java.time.Instant.parse(time),value.observedAt)
        reject {NativeBusinessCodec.cautions(cautions(caution().put("kind","sdk-hard-braking")),owner)}
        reject {NativeBusinessCodec.cautions(cautions(caution().put("kind","harsh-braking").put("currentRoadConditionVerified",true)),owner)}
    }
    @Test fun functionalPurposeOffExpiryAndRevisionChangeCannotAuthorizeRead() {
        val gate=FunctionalPermissionGate()
        fun permission(revision: Long,purposes: Set<FunctionalPurpose>)=
            FunctionalPermissions(device,id,revision,1000,purposes,1,"0".repeat(64))
        gate.replace(permission(1,emptySet()))
        try {gate.stamp(setOf(FunctionalPurpose.CAUTIONS_READ),emptySet(),1);fail("off purpose")}
        catch(error: NativeSocialFailure) {assertEquals(NativeSocialFailure.Kind.CONSENT_REQUIRED,error.kind)}
        gate.replace(permission(2,setOf(FunctionalPurpose.CAUTIONS_READ)))
        val stamp=gate.stamp(setOf(FunctionalPurpose.CAUTIONS_READ),emptySet(),1)
        assertTrue(gate.current(stamp,999));assertFalse(gate.current(stamp,1000))
        gate.replace(permission(3,emptySet()))
        assertFalse(gate.current(stamp,1))
    }

}
