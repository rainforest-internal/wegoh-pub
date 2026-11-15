package io.wegoh.app.nativeauth

import org.json.JSONObject

enum class TripSignalKind(val wire: String,val label: String,val headline: String) {
    RESTROOM("restroom","화장실","화장실 가고 싶어요"),
    CAFE("cafe","카페","카페에 들르고 싶어요"),
    HUNGRY("hungry","배고파요","배고파요"),
    REST("rest","쉬어 가요","잠깐 쉬어 가요"),
    DROWSY("drowsy","졸려요","졸려요. 운전 교대해요"),
    FUEL("fuel","주유","주유가 필요해요"),
    EV_CHARGE("ev_charge","전기차 충전","전기차 충전이 필요해요"),
    NURSING("nursing","수유","수유가 필요해요"),
    SMOKING("smoking","흡연","담배 피우고 싶어요");

    val defaultFacilities: Set<TripSignalFacility> get()=when(this) {
        RESTROOM->setOf(TripSignalFacility.TOILET)
        NURSING->setOf(TripSignalFacility.NURSING)
        EV_CHARGE->setOf(TripSignalFacility.EV_CHARGER)
        FUEL->setOf(TripSignalFacility.GAS_STATION)
        REST->setOf(TripSignalFacility.REST_SPACE)
        else->emptySet()
    }
}
enum class TripSignalFacility(val wire: String,val label: String) {
    TOILET("toilet","화장실"),NURSING("nursing","수유실"),EV_CHARGER("evCharger","전기차 충전"),
    GAS_STATION("gasStation","주유소"),LPG("lpg","LPG"),REST_SPACE("restSpace","쉼터")
}
data class SignalPoint(val lat: Double,val lng: Double,val heading: Double?=null)
data class SignalLocation(val location: SignalPoint,val destination: SignalPoint?=null)
data class SignalDestination(val name: String,val latitude: Double,val longitude: Double,val candidateReceipt: String?=null)
data class SignalCandidate(val name: String,val lat: Double,val lng: Double,val verdict: String,val label: String,
    val fromRequesterMeters: Double,val detourSeconds: Double?,val facilities: Set<String> = emptySet(),
    val fromLeadMeters: Double?=null,val basis: String="route",val leaderCarId: String?=null,
    val routeName: String?=null,val direction: String?=null,val candidateReceipt: String?=null) {
    val destination get()=SignalDestination(name,lat,lng,candidateReceipt)
}
data class TripSignalCandidateDetails(val routeName: String?,val direction: String?,val fromLeadMeters: Int?,val detourSeconds: Int?)
data class TripGroupVotes(val agree: Int,val pass: Int,val total: Int) {
    init {require(total in 0..20 && agree in 0..total && pass in 0..total-agree)}
}
data class TripGroupResponse(val carId: String,val carName: String,val choice: String?,
    val responderAccountId: String?=null,val responderName: String?=null,val responseSource: String?=null)
data class TripSignalVoteResult(val choice: String,val already: Boolean=false,val responderAccountId: String?=null)
data class TripSignal(val id: String,val accountId: String,val kind: TripSignalKind,val destination: SignalDestination?,
    val createdAt: String,val contextState: String,val agrees: Int,val passes: Int,val myVote: String?,val inProgress: Boolean=contextState=="valid",
    val resolution: String?=null,val driverAgrees: Int?=null,val driverPasses: Int?=null,val driverTotal: Int?=null,
    val decisionRule: String?=null,val requesterCarId: String?=null,val requiredCarIds: List<String> = emptyList(),
    val canRespond: Boolean?=null,val myGroupChoice: String?=null,val groupVotes: TripGroupVotes?=null,
    val groupResponses: List<TripGroupResponse> = emptyList(),val candidateDetails: TripSignalCandidateDetails?=null) {
    val isGroupDecision get()=decisionRule=="other-car-groups-v1"
    val responseChoice get()=if(isGroupDecision)myGroupChoice else myVote
    fun agreeCount(myAccountId: String?)=if(isGroupDecision)groupVotes?.agree ?: 0
        else driverAgrees ?: (1+agrees-if(accountId==myAccountId && myVote=="agree")1 else 0)
    fun hasMajority(cars: Int,myAccountId: String?)=if(resolution!=null)resolution=="agreed"
        else if(decisionRule!=null)false
        else (driverTotal ?: cars)>0 && agreeCount(myAccountId)>(driverTotal ?: cars)/2
    fun hasPassed(cars: Int)=if(resolution!=null)resolution=="passed"
        else if(decisionRule!=null)false else (driverPasses ?: passes)>(driverTotal ?: cars)/2
}
data class TripSignalPage(val signals: List<TripSignal>,val hasActiveSignal: Boolean=signals.any {it.inProgress})
object TripSignalsCodec {
    private fun optionalText(value: JSONObject,key: String,max: Int): String? {
        if(value.isNull(key))return null
        val raw=value.get(key)
        check(raw is String && raw.codePointCount(0,raw.length) in 1..max && raw.none {it.isISOControl()})
        return raw
    }
    private fun candidateReceipt(value: JSONObject): String?=optionalText(value,"candidateReceipt",2048)?.also {
        check(Regex("[A-Za-z0-9_-]+").matches(it))
    }
    private fun candidateDetails(value: JSONObject): TripSignalCandidateDetails? {
        if(value.isNull("candidateDetails"))return null
        val details=value.getJSONObject("candidateDetails")
        check(details.keys().asSequence().toSet()==setOf("routeName","direction","fromLeadMeters","detourSeconds"))
        fun integer(key: String,min: Int): Int? {
            if(details.isNull(key))return null
            val raw=details.get(key);check(raw is Int || raw is Long)
            return (raw as Number).toLong().also {check(it in min.toLong()..Int.MAX_VALUE.toLong())}.toInt()
        }
        return TripSignalCandidateDetails(optionalText(details,"routeName",100),optionalText(details,"direction",80),
            integer("fromLeadMeters",0),integer("detourSeconds",-Int.MAX_VALUE))
    }
    fun candidates(value: JSONObject): List<SignalCandidate> {
        val list=value.getJSONArray("candidates")
        val cars=value.optJSONArray("cars")
        val leader=(0 until (cars?.length() ?: 0)).map {cars!!.getJSONObject(it)}
            .filter {it.optString("state")=="same_road" && !it.isNull("alongMeters")}
            .maxByOrNull {it.getDouble("alongMeters")}?.optString("carId")
        return (0 until list.length()).map {index->val item=list.getJSONObject(index)
            val facilities=item.optJSONObject("facilities")
            SignalCandidate(item.getString("name"),item.getDouble("lat"),item.getDouble("lng"),item.getString("verdict"),
                item.getString("label"),item.getDouble("fromRequesterMeters"),
                if(item.isNull("detourSeconds"))null else item.getDouble("detourSeconds"),
                facilities?.keys()?.asSequence()?.filter {facilities.optBoolean(it)}?.toSet().orEmpty(),
                if(item.isNull("fromLeadMeters"))null else item.getDouble("fromLeadMeters"),value.optString("basis","route"),leader,
                optionalText(item,"routeName",100),optionalText(item,"direction",80),candidateReceipt(item))
        }.filter {it.verdict=="ahead"}
    }
    fun signals(value: JSONObject): List<TripSignal> {
        val list=value.getJSONArray("signals")
        return (0 until list.length()).mapNotNull {index->val item=list.getJSONObject(index)
            val kind=TripSignalKind.entries.firstOrNull {it.wire==item.getString("kind")} ?: return@mapNotNull null
            val destination=item.optJSONObject("destination")?.let {SignalDestination(it.getString("name"),it.getDouble("latitude"),it.getDouble("longitude"))}
            val votes=item.getJSONObject("votes")
            val drivers=item.optJSONObject("driverVotes")
            val group=item.optJSONObject("groupVotes")
            val required=item.optJSONArray("requiredCarIds")
            val responses=item.optJSONArray("groupResponses")
            TripSignal(item.getString("id"),item.getString("accountId"),kind,destination,java.time.OffsetDateTime.parse(item.getString("createdAt").replace(' ','T')).toInstant().toString(),
                item.getString("contextState"),votes.getInt("agree"),votes.getInt("pass"),item.opt("myVote") as? String,
                if(item.has("inProgress"))item.getBoolean("inProgress") else item.getString("contextState")=="valid",
                if(item.has("resolution"))item.getString("resolution") else null,drivers?.getInt("agree"),drivers?.getInt("pass"),drivers?.getInt("total"),
                item.opt("decisionRule") as? String,item.opt("requesterCarId") as? String,
                if(required==null)emptyList() else (0 until required.length()).map {required.getString(it)},
                if(item.has("canRespond"))item.get("canRespond").let {check(it is Boolean);it} else null,
                choice(item,"myGroupChoice"),group?.let {TripGroupVotes(it.getInt("agree"),it.getInt("pass"),it.getInt("total"))},
                if(responses==null)emptyList() else (0 until responses.length()).map {index->
                    val response=responses.getJSONObject(index)
                    TripGroupResponse(response.getString("carId"),response.getString("carName"),choice(response,"choice"),
                        response.opt("responderAccountId") as? String,response.opt("responderName") as? String,
                        optionalText(response,"responseSource",6)?.also {check(it in setOf("native","iphone","web"))})
                },candidateDetails(item))
        }
    }
    private fun choice(value: JSONObject,key: String): String? {
        if(value.isNull(key))return null
        val choice=value.get(key)
        check(choice is String && choice in setOf("agree","pass"))
        return choice
    }
    fun page(value: JSONObject): TripSignalPage {
        val signals=signals(value)
        return TripSignalPage(signals,if(value.has("hasActiveSignal"))value.getBoolean("hasActiveSignal") else false)
    }
    fun newSignals(previous: Set<String>,signals: List<TripSignal>,me: String?)=
        signals.filter {it.id !in previous && it.accountId!=me && it.responseChoice==null && it.contextState=="valid" && it.inProgress &&
            (it.decisionRule==null || it.isGroupDecision && it.canRespond==true)}
    fun candidateBody(kind: TripSignalKind,location: SignalLocation,requiredFacilities: Set<TripSignalFacility> = emptySet()): JSONObject = JSONObject().put("kind",kind.wire)
        .put("location",point(location.location).apply {location.location.heading?.let {put("heading",it)}})
        .put("destination",location.destination?.let(::point) ?: JSONObject.NULL)
        .put("requiredFacilities",org.json.JSONArray(requiredFacilities.sortedBy {it.wire}.map {it.wire}))
    private fun point(value: SignalPoint)=JSONObject().put("lat",value.lat).put("lng",value.lng)
    fun sendBody(kind: TripSignalKind,destination: SignalDestination?)=JSONObject().put("kind",kind.wire).apply {
        destination?.let {put("destination",JSONObject().put("name",it.name).put("latitude",it.latitude).put("longitude",it.longitude))}
        destination?.candidateReceipt?.let {receipt->
            require(receipt.length in 1..2048 && Regex("[A-Za-z0-9_-]+").matches(receipt))
            put("candidateReceipt",receipt)
        }
    }
    fun voteResult(value: JSONObject,requestedChoice: String): TripSignalVoteResult {
        val selected=choice(value,"choice") ?: requestedChoice
        check(value.optString("status")=="saved")
        return TripSignalVoteResult(selected,value.optBoolean("already",false),value.opt("responderAccountId") as? String)
    }
    fun voteBody(choice: String): JSONObject {require(choice in setOf("agree","pass"));return JSONObject().put("choice",choice)}
}
