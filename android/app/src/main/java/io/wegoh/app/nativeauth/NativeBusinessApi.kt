package io.wegoh.app.nativeauth

import org.json.JSONObject
import java.io.Closeable
import java.time.Instant

/** Read-only projections: delivery, user reports and saved preferences never prove physical action. */
class BusinessCommand internal constructor(val id: String,val label: String,val stage: Stage,
    val mayHaveExecuted: Boolean,val expiresAt: Instant,val createdAt: Instant,val reason: String?=null) {
    enum class Stage { QUEUED, DELIVERED, RECEIVED, SDK_ACCEPTED, STATE_CONFIRMED, REJECTED, UNKNOWN, CANCELLED, EXPIRED }
    override fun toString()="BusinessCommand(redacted)"
}
class BusinessCommandInbox internal constructor(commands: List<BusinessCommand>,val supportedActionCount: Int) {
    val commands=immutableSocialList(commands)
    override fun toString()="BusinessCommandInbox(redacted)"
}
class BusinessMission internal constructor(val id: String,val title: String,val state: State,
    val checkpointCount: Int,val nextCheckpoint: Int?,val expiresAt: Instant?,checkpointLabels: List<String> = emptyList(),
    val participationRevision: Int=0) {
    val checkpointLabels=immutableSocialList(checkpointLabels)
    val nextPlaceName: String? get()=nextCheckpoint?.let {checkpointLabels.getOrNull(it-1)}
    enum class State { ENROLLING, ACTIVE, COMPLETED, CANCELLED, INTERRUPTED, RESULT_WITHDRAWN, COURSE_UNAVAILABLE }
    override fun toString()="BusinessMission(redacted)"
}
class BusinessMissionList internal constructor(missions: List<BusinessMission>) {
    val missions=immutableSocialList(missions)
    override fun toString()="BusinessMissionList(redacted)"
}
class BusinessRecommendationSettings internal constructor(val configured: Boolean,val priority: Priority,
    val hideVisited: Boolean,val maxDistanceKm: Double,val usesHistory: Boolean,val usesFeedback: Boolean,
    val learningEnabled: Boolean) {
    enum class Priority { NEARBY, FEW_STOPS, MANY_STOPS }
    override fun toString()="BusinessRecommendationSettings(redacted)"
}
class BusinessCaution internal constructor(val id: String,val kind: Kind,val placeName: String,
    val observedAt: Instant,val own: Boolean,val ownerName: String?,val shareExpiresAt: Instant?) {
    enum class Kind { ROAD_SURFACE, CONSTRUCTION, VISIBILITY, HARSH_BRAKING, OTHER }
    override fun toString()="BusinessCaution(redacted)"
}
class BusinessCautionPage internal constructor(items: List<BusinessCaution>,val hasMore: Boolean) {
    val items=immutableSocialList(items)
    override fun toString()="BusinessCautionPage(redacted)"
}

fun NativeSocialClient.readBusinessCommandInbox(callback: (Result<BusinessCommandInbox>)->Unit): Closeable=deviceCommandsApi.readCommandInbox(callback)
fun NativeSocialClient.readBusinessMissions(roomId: String,callback: (Result<BusinessMissionList>)->Unit): Closeable=missionsApi.readMissions(roomId,callback)
fun NativeSocialClient.readBusinessRecommendationSettings(callback: (Result<BusinessRecommendationSettings>)->Unit): Closeable=recommendationsApi.readSettings(callback)
fun NativeSocialClient.readBusinessCautions(callback: (Result<BusinessCautionPage>)->Unit): Closeable=cautionsApi.readCautions(callback)

internal object NativeBusinessCodec {
    private fun text(value: JSONObject,key: String,max: Int)= (value.get(key) as? String).also {
        check(it!=null && it.isNotBlank() && it.codePointCount(0,it.length)<=max && it.none {c->c.code<32})
    }!!
    private fun id(value: JSONObject,key: String)=text(value,key,32).also {check(Regex("[a-f0-9]{32}").matches(it))}
    private fun bool(value: JSONObject,key: String)=value.get(key).also {check(it is Boolean)} as Boolean
    private fun integer(value: JSONObject,key: String,min: Int=0,max: Int=Int.MAX_VALUE): Int {
        val raw=value.get(key);check(raw is Int || raw is Long)
        return (raw as Number).toLong().also {check(it in min.toLong()..max.toLong())}.toInt()
    }
    private fun instant(value: JSONObject,key: String)=Instant.parse(text(value,key,40))
    private fun optionalInstant(value: JSONObject,key: String)=if(value.isNull(key))null else instant(value,key)
    private fun objects(value: JSONObject,key: String,max: Int): List<JSONObject> {
        val array=value.getJSONArray(key);check(array.length()<=max)
        return (0 until array.length()).map {array.getJSONObject(it)}
    }
    private fun account(value: JSONObject,key: String)=text(value,key,45).also {check(Regex("team-[a-f0-9]{40}").matches(it))}
    private inline fun <reified T: Enum<T>> wire(value: JSONObject,key: String): T =
        enumValues<T>().single {it.name.lowercase().replace('_','-')==text(value,key,40)}
    private val COMMAND_ARGUMENT_KINDS=setOf("empty-object","hvac-celsius","hvac-fan","seat-switch","seat-level","window-position","switch")
    fun commands(value: JSONObject,deviceId: String,accountId: String): BusinessCommandInbox {
        instant(value,"serverNow")
        val actions=objects(value,"supportedControlActions",100).associate {item->
            val key=text(item,"id",128) to integer(item,"revision",1)
            check(text(item,"argumentKind",40) in COMMAND_ARGUMENT_KINDS)
            key to text(item,"label",80)
        }
        val items=objects(value,"requests",100).map {item->
            check(id(item,"targetDeviceId")==deviceId && account(item,"ownerId")==accountId)
            account(item,"requesterId");check(item.has("roomId"));if(!item.isNull("roomId"))id(item,"roomId")
            check(!bool(item,"physicalExecutionVerified"))
            val capability=text(item,"capabilityId",128) to integer(item,"capabilityRevision",1)
            BusinessCommand(id(item,"id"),actions[capability] ?: "차량 요청",wire(item,"stage"),
                bool(item,"mayHaveExecuted"),instant(item,"expiresAt"),instant(item,"createdAt"),
                if(item.isNull("reason"))null else text(item,"reason",40))
        };check(items.map {it.id}.distinct().size==items.size)
        return BusinessCommandInbox(items,actions.size)
    }
    fun missions(value: JSONObject,roomId: String): BusinessMissionList {
        instant(value,"serverNow")
        val items=objects(value,"missions",50).map {mission(it,roomId)}
        check(items.map {it.id}.distinct().size==items.size)
        return BusinessMissionList(items)
    }
    fun tripMissions(value: JSONObject,tripId: String): BusinessMissionList {
        instant(value,"serverNow")
        val items=objects(value,"missions",50).map {mission(it,tripId,tripContext=true)}
        check(items.map {it.id}.distinct().size==items.size)
        return BusinessMissionList(items)
    }
    fun missionProgressRequest(eventId: String,checkpoint: Int,participationRevision: Int,functionalRevision: Long): JSONObject {
        require(Regex("[a-f0-9]{32}").matches(eventId) && checkpoint in 1..3 && participationRevision>=1 &&
            functionalRevision in 1..Int.MAX_VALUE.toLong())
        return JSONObject().put("eventId",eventId).put("checkpoint",checkpoint)
            .put("participationRevision",participationRevision).put("functionalRevision",functionalRevision)
    }
    fun mission(item: JSONObject,roomId: String,tripContext: Boolean=false): BusinessMission {
            if(tripContext)check(id(item,"tripId")==roomId && integer(item,"contractVersion",1,1)==1 && !item.has("roomId") && !item.has("expiresAt"))
            else check(id(item,"roomId")==roomId)
            check(!bool(item,"physicalArrivalVerified"))
            check(text(item,"confirmationSource",40)=="user-confirmed")
            check(text(item,"nativeReportingPurpose",40)=="mission-progress")
            account(item,"ownerId");integer(item,"revision",1)
            val checkpoints=objects(item,"checkpoints",3);check(checkpoints.isNotEmpty())
            val labels=checkpoints.mapIndexed {i,point->check(integer(point,"ordinal",1)==i+1);text(point,"label",100)}
            val participation=item.getJSONObject("participation");check(bool(participation,"consent"))
            val participationRevision=integer(participation,"revision",1)
            val next=if(participation.isNull("nextCheckpoint"))null else integer(participation,"nextCheckpoint",1,checkpoints.size)
            return BusinessMission(id(item,"id"),text(item,"title",100),wire(item,"state"),checkpoints.size,next,
                if(tripContext)null else instant(item,"expiresAt"),labels,participationRevision)
    }
    fun recommendations(value: JSONObject): BusinessRecommendationSettings {
        val revision=integer(value,"revision");check(text(value,"algorithm",40)=="explicit-rules-v1" && !bool(value,"aiUsed"))
        val preferences=value.getJSONObject("preferences");val permissions=value.getJSONObject("permissions")
        val priority=when(text(preferences,"coursePriority",40)) {
            "nearby"->BusinessRecommendationSettings.Priority.NEARBY
            "fewStops"->BusinessRecommendationSettings.Priority.FEW_STOPS
            "manyStops"->BusinessRecommendationSettings.Priority.MANY_STOPS
            else->error("INVALID_RECOMMENDATION_PRIORITY")
        }
        val facilities=preferences.getJSONArray("facilities");check(facilities.length()<=5)
        val allowed=setOf("toilet","nursing","evCharger","gasStation","lpg")
        val selected=(0 until facilities.length()).map {facilities.getString(it)}
        check(selected.distinct().size==selected.size && allowed.containsAll(selected))
        val raw=preferences.get("maxDistanceKm");check(raw is Number)
        val distance=(raw as Number).toDouble();check(distance.isFinite() && distance in 1.0..150.0)
        val learning=value.getJSONObject("learning");check(integer(learning,"settingsRevision")==revision)
        bool(learning,"enabled");integer(learning,"learningRevision");integer(learning,"eligibleSamples")
        text(learning,"modelVersion",80);text(learning,"status",40)
        return BusinessRecommendationSettings(bool(value,"configured"),priority,bool(preferences,"hideVisited"),distance,
            bool(permissions,"useHistory"),bool(permissions,"useFeedback"),bool(learning,"enabled"))
    }
    fun cautions(value: JSONObject,accountId: String): BusinessCautionPage {
        instant(value,"serverNow")
        val items=objects(value,"items",50).map {item->
            val own=bool(item,"own");check(own==(account(item,"ownerId")==accountId))
            check(!bool(item,"currentRoadConditionVerified"));integer(item,"revision",1)
            val place=item.getJSONObject("place");val name=text(place,"name",80)
            val ownerName=if(item.isNull("ownerName"))null else text(item,"ownerName",64)
            BusinessCaution(id(item,"id"),wire(item,"kind"),name,instant(item,"observedAt"),own,ownerName,optionalInstant(item,"shareExpiresAt"))
        };check(items.map {it.id}.distinct().size==items.size)
        val hasMore=!value.isNull("nextCursor")
        if(hasMore)NativeSocialCodec.cursor(text(value,"nextCursor",256))
        return BusinessCautionPage(items,hasMore)
    }
}
