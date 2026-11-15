package io.wegoh.app.nativeauth

import java.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import java.time.OffsetDateTime

/** Exact first-four server projections, independent of UI and private credentials. */
internal object NativeSocialCodec {
    private val idPattern=Regex("[a-f0-9]{32}")
    private val accountPattern=Regex("team-[a-f0-9]{40}")
    fun roomId(value: String): String = value.also {check(idPattern.matches(it))}
    private fun fields(value: JSONObject,vararg names: String) {check(value.keys().asSequence().toSet()==names.toSet())}
    private fun text(value: JSONObject,key: String,max: Int): String = (value.get(key) as? String).also {
        check(it!=null && it.isNotBlank() && it.codePointCount(0,it.length)<=max && it.none {c->c.code<32})
    }!!
    private fun id(value: JSONObject,key: String)=text(value,key,32).also {check(idPattern.matches(it))}
    private fun account(value: JSONObject,key: String)=text(value,key,45).also {check(accountPattern.matches(it))}
    private fun bool(value: JSONObject,key: String)=value.get(key).also {check(it is Boolean)} as Boolean
    private fun integer(value: JSONObject,key: String,min: Int=0): Int {
        val raw=value.get(key);check(raw is Int || raw is Long)
        return (raw as Number).toLong().also {check(it in min.toLong()..Int.MAX_VALUE.toLong())}.toInt()
    }
    private fun number(value: JSONObject,key: String,min: Double,max: Double=Double.MAX_VALUE): Double {
        val raw=value.get(key);check(raw is Number && raw !is Boolean)
        return (raw as Number).toDouble().also {check(it.isFinite() && it in min..max)}
    }
    private fun instant(value: JSONObject,key: String): Instant = OffsetDateTime.parse(text(value,key,40)).toInstant()
    private fun nullableText(value: JSONObject,key: String,max: Int)=if(value.isNull(key))null else text(value,key,max)
    private fun array(value: JSONObject,key: String,max: Int): JSONArray = value.getJSONArray(key).also {check(it.length()<=max)}
    private fun <T> objects(value: JSONObject,key: String,max: Int,decode: (JSONObject)->T): List<T> = array(value,key,max).let {a ->
        (0 until a.length()).map {check(a.get(it) is JSONObject);decode(a.getJSONObject(it))}
    }
    private fun coursePair(value: JSONObject): Pair<String?,Int?> {
        check(value.isNull("courseId")==value.isNull("courseVersion"))
        if(value.isNull("courseId"))return null to null
        return text(value,"courseId",80).also {check(Regex("[a-z0-9][a-z0-9_-]{0,79}").matches(it))} to integer(value,"courseVersion",1)
    }
    private fun review(value: JSONObject,kind: String,key: String): SocialReview {
        fields(value,"kind","key","state","checksum","requested")
        check(value.get("kind")==kind && value.get("key")==key)
        val state=when(value.get("state")) {
            "private"->SocialReview.State.PRIVATE;"quarantined"->SocialReview.State.QUARANTINED
            "approved"->SocialReview.State.APPROVED;"rejected"->SocialReview.State.REJECTED
            else->error("NATIVE_SOCIAL_RESPONSE_INVALID")
        }
        val requested=bool(value,"requested")
        if(value.isNull("checksum"))check(state==SocialReview.State.PRIVATE && !requested)
        else check(Regex("[a-f0-9]{64}").matches(text(value,"checksum",64)))
        return SocialReview(kind,state,requested)
    }
    private fun person(value: JSONObject,nullableName: Boolean=false): SocialPerson = SocialPerson(account(value,"id"),
        if(nullableName && value.isNull("name"))null else text(value,"name",64))
    private fun roomSummary(value: JSONObject): SocialRoomSummary {
        fields(value,"id","name","courseId","courseVersion","expiresAt","review","ownerId","active","memberCount")
        check(bool(value,"active"));val id=id(value,"id");val pair=coursePair(value)
        return SocialRoomSummary(id,text(value,"name",80),account(value,"ownerId"),pair.first,pair.second,
            instant(value,"expiresAt"),integer(value,"memberCount",1),review(value.getJSONObject("review"),"room",id))
    }
    fun overview(value: JSONObject,permission: FunctionalPermissions): SocialOverview {
        fields(value,"people","friends","requests","blocks","rooms","history","capabilities")
        val capabilities=value.getJSONObject("capabilities");fields(capabilities,"friends","rooms","history","nativeReadOnly")
        val friends=permission.allows(FunctionalPurpose.FRIENDS_READ);val rooms=permission.allows(FunctionalPurpose.ROOMS_READ)
        val history=permission.allows(FunctionalPurpose.HISTORY_READ);val manage=friends && permission.allows(FunctionalPurpose.FRIENDS_MANAGE)
        check(bool(capabilities,"friends")==friends && bool(capabilities,"rooms")==rooms && bool(capabilities,"history")==history && bool(capabilities,"nativeReadOnly")==!manage)
        val people=objects(value,"people",10000) {fields(it,"id","name");person(it)}
        val linked=objects(value,"friends",10000) {fields(it,"id","name","hasVehicle");bool(it,"hasVehicle");person(it)}
        val requests=objects(value,"requests",10000) {
            fields(it,"id","name","direction");SocialFriendRequest(person(it),when(it.get("direction")) {
                "incoming"->SocialFriendRequest.Direction.INCOMING;"outgoing"->SocialFriendRequest.Direction.OUTGOING
                else->error("NATIVE_SOCIAL_RESPONSE_INVALID")})
        }
        val blocks=objects(value,"blocks",10000) {fields(it,"id","name","available");val available=bool(it,"available")
            SocialBlock(person(it,!available),available).also {b->check(available==(b.person.name!=null))}}
        val groups=objects(value,"rooms",100,::roomSummary)
        check(array(value,"history",0).length()==0)
        if(!friends)check(linked.isEmpty())
        if(!manage)check(people.isEmpty() && requests.isEmpty() && blocks.isEmpty())
        if(!rooms)check(groups.isEmpty())
        check(linked.map {it.id}.distinct().size==linked.size && groups.map {it.id}.distinct().size==groups.size)
        return SocialOverview(people,linked,requests,blocks,groups,friends,rooms,history,!manage)
    }
    private fun role(value: String)=when(value) {
        "member"->SocialRole.MEMBER;"dj"->SocialRole.DJ;"rest"->SocialRole.REST;"food"->SocialRole.FOOD
        else->error("NATIVE_SOCIAL_RESPONSE_INVALID")
    }
    private fun preference(value: String)=when(value) {
        "balanced"->SocialPreference.BALANCED;"country-roads"->SocialPreference.COUNTRY_ROADS
        "short-distance"->SocialPreference.SHORT_DISTANCE;"short-time"->SocialPreference.SHORT_TIME
        else->error("NATIVE_SOCIAL_RESPONSE_INVALID")
    }
    private fun signalKind(value: String)=SocialSignalKind.entries.singleOrNull {it.wire==value} ?: error("NATIVE_SOCIAL_RESPONSE_INVALID")
    private fun signal(value: JSONObject,room: String): SocialSignal {
        fields(value,"kind","destination","review","id","accountId","createdAt","votes","myVote")
        val id=id(value,"id");val place=if(value.isNull("destination"))null else value.getJSONObject("destination").let {
            fields(it,"name","latitude","longitude");SocialSelectedPlace(text(it,"name",80),number(it,"latitude",-90.0,90.0),number(it,"longitude",-180.0,180.0))}
        val review=if(value.isNull("review"))null else review(value.getJSONObject("review"),"room-place",room+":"+id)
        check((place==null)==(review==null))
        val votes=value.getJSONObject("votes");fields(votes,"agree","pass")
        val mine=if(value.isNull("myVote"))null else when(value.get("myVote")) {
            "agree"->SocialSignal.Vote.AGREE;"pass"->SocialSignal.Vote.PASS;else->error("NATIVE_SOCIAL_RESPONSE_INVALID")}
        return SocialSignal(id,signalKind(text(value,"kind",20)),account(value,"accountId"),instant(value,"createdAt"),
            place,review,integer(votes,"agree"),integer(votes,"pass"),mine)
    }
    fun room(value: JSONObject,expectedId: String,permission: FunctionalPermissions): SocialRoom {
        fields(value,"name","review","courseId","courseVersion","preference","id","ownerId","expiresAt","serverNow",
            "expiresInSeconds","course","role","nativeReadOnly","members","signals")
        check(id(value,"id")==roomId(expectedId));val pair=coursePair(value)
        val course=if(value.isNull("course"))null else value.getJSONObject("course").let {
            fields(it,"id","version","title");check(it.get("id")==pair.first && integer(it,"version",1)==pair.second)
            SocialCourse(text(it,"id",80),integer(it,"version",1),text(it,"title",100))}
        val members=objects(value,"members",10000) {fields(it,"id","name","role");SocialMember(person(it),role(text(it,"role",16)))}
        val signals=objects(value,"signals",100) {signal(it,expectedId)}
        check(members.map {it.person.id}.distinct().size==members.size && signals.map {it.id}.distinct().size==signals.size)
        val readOnly=bool(value,"nativeReadOnly");check(readOnly==!permission.allows(FunctionalPurpose.ROOMS_INTERACT))
        return SocialRoom(expectedId,text(value,"name",80),account(value,"ownerId"),pair.first,pair.second,
            preference(text(value,"preference",20)),role(text(value,"role",16)),instant(value,"expiresAt"),instant(value,"serverNow"),
            number(value,"expiresInSeconds",0.0),course,review(value.getJSONObject("review"),"room",expectedId),readOnly,members,signals)
    }
    private fun historySummary(value: JSONObject,accountId: String,detail: Boolean=false): SocialHistorySummary {
        val names=listOf("id","title","ownerId","ownerName","own","createdAt","updatedAt","startedAt","endedAt",
            "courseId","courseVersion","revision","permissionRevision","review","visitCount","tracePointCount","sharedWith")
        fields(value,*(names+if(detail)listOf("permissions","access","visits","traceBatches","grants","source","course","capabilities","nativeReadOnly") else emptyList()).toTypedArray())
        check(value.isNull("permissionRevision") && array(value,"sharedWith",0).length()==0)
        val id=id(value,"id");val owner=account(value,"ownerId");val own=bool(value,"own");check(own==(owner==accountId));val pair=coursePair(value)
        return SocialHistorySummary(id,text(value,"title",100),owner,nullableText(value,"ownerName",64),own,
            instant(value,"createdAt"),instant(value,"updatedAt"),instant(value,"startedAt"),if(value.isNull("endedAt"))null else instant(value,"endedAt"),
            pair.first,pair.second,integer(value,"revision",1),review(value.getJSONObject("review"),"history",id),integer(value,"visitCount"),integer(value,"tracePointCount"))
    }
    fun cursor(value: String): String {
        check(value.length in 1..256 && Regex("[A-Za-z0-9_-]+").matches(value))
        val bytes=Base64.getUrlDecoder().decode(value)
        check(Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)==value)
        val objectValue=StrictNativeJson.parse(bytes,256);fields(objectValue,"updatedAt","id");instant(objectValue,"updatedAt");id(objectValue,"id")
        return value
    }
    fun historyPage(value: JSONObject,permission: FunctionalPermissions,accountId: String): SocialHistoryPage {
        fields(value,"history","friends","nextCursor","nativeReadOnly","capabilities");check(array(value,"friends",0).length()==0)
        historyCapabilities(value,permission)
        val write=permission.allows(FunctionalPurpose.HISTORY_WRITE)
        val history=objects(value,"history",50) {historySummary(it,accountId)};check(history.map {it.id}.distinct().size==history.size)
        val next=if(value.isNull("nextCursor"))null else SocialHistoryCursor(cursor(text(value,"nextCursor",256)))
        return SocialHistoryPage(history,next,!write,write)
    }
    private fun historyCapabilities(value: JSONObject,permission: FunctionalPermissions) {
        val capabilities=value.getJSONObject("capabilities");fields(capabilities,"history","historyRemix","historyTraceIngest","historyPhotos","historyPhotoUpload","historyReplay","historyExport","cautions")
        check(bool(capabilities,"history") && bool(capabilities,"historyReplay"))
        for(key in listOf("historyRemix","historyPhotos","historyPhotoUpload","historyExport","cautions"))check(!bool(capabilities,key))
        val write=permission.allows(FunctionalPurpose.HISTORY_WRITE)
        check(bool(capabilities,"historyTraceIngest")==write && bool(value,"nativeReadOnly")==!write)
    }
    private fun historySource(value: JSONObject): SocialHistorySource {
        fields(value,"kind","actorId","receivedAt")
        val kind=text(value,"kind",40);check(kind in setOf("web-confirmed","room-confirmed","browser-reported","device-reported"))
        return SocialHistorySource(kind,account(value,"actorId"),instant(value,"receivedAt"))
    }
    fun historyDetail(value: JSONObject,itemId: String,permission: FunctionalPermissions,accountId: String): SocialHistoryDetail {
        val summary=historySummary(value,accountId,true);check(summary.id==roomId(itemId))
        historyCapabilities(value,permission)
        check(value.isNull("permissions") && array(value,"grants",0).length()==0)
        val access=value.getJSONObject("access");fields(access,"visits","trace","photos")
        val allowVisits=bool(access,"visits");val allowTrace=bool(access,"trace");bool(access,"photos")
        val visits=objects(value,"visits",500) {visit->
            fields(visit,"id","place","visitedAt","review","rating","source","photos")
            check(array(visit,"photos",0).length()==0)
            val place=visit.getJSONObject("place");fields(place,"name","latitude","longitude")
            val review=visit.get("review") as? String ?: error("NATIVE_SOCIAL_RESPONSE_INVALID")
            check(review.codePointCount(0,review.length)<=1000 && review.none {it.code<32 && it !in "\n\r\t"})
            val rating=if(visit.isNull("rating"))null else integer(visit,"rating",1).also {check(it<=5)}
            SocialHistoryVisit(id(visit,"id"),SocialSelectedPlace(text(place,"name",80),number(place,"latitude",-90.0,90.0),
                number(place,"longitude",-180.0,180.0)),instant(visit,"visitedAt"),review,rating,historySource(visit.getJSONObject("source")))
        }
        var pointCount=0
        val traces=objects(value,"traceBatches",100000) {batch->
            fields(batch,"id","streamId","label","points","source")
            val points=objects(batch,"points",200) {point->
                fields(point,"latitude","longitude","capturedAt","accuracyMeters")
                SocialHistoryPoint(number(point,"latitude",-90.0,90.0),number(point,"longitude",-180.0,180.0),instant(point,"capturedAt"),
                    if(point.isNull("accuracyMeters"))null else number(point,"accuracyMeters",0.0,10000.0))
            }
            check(points.isNotEmpty() && points.zipWithNext().all {it.first.capturedAt<it.second.capturedAt})
            pointCount+=points.size;check(pointCount<=100000)
            SocialHistoryTrace(id(batch,"id"),id(batch,"streamId"),text(batch,"label",64),points,historySource(batch.getJSONObject("source")))
        }
        check((allowVisits || visits.isEmpty()) && (allowTrace || traces.isEmpty()))
        check(visits.size==summary.visitCount && pointCount==summary.tracePointCount)
        check(visits.map {it.id}.distinct().size==visits.size && traces.map {it.id}.distinct().size==traces.size)
        val course=if(value.isNull("course"))null else value.getJSONObject("course").let {
            fields(it,"id","version","title");check(it.get("id")==summary.courseId && integer(it,"version",1)==summary.courseVersion)
            SocialCourse(text(it,"id",80),integer(it,"version",1),text(it,"title",100))}
        return SocialHistoryDetail(summary,visits,traces,historySource(value.getJSONObject("source")),course)
    }
    fun roomMusic(value: JSONObject,roomId: String): SocialRoomMusic {
        NativeSocialCodec.roomId(roomId);fields(value,"revision","canEdit","selection","nativeReadOnly")
        check(bool(value,"nativeReadOnly")==!bool(value,"canEdit"))
        val selection=if(value.isNull("selection"))null else value.getJSONObject("selection").let {item->
            fields(item,"id","ownerId","playlistId","playlistRevision","currentTrackId","name","tracks","review")
            val selectionId=id(item,"id");account(item,"ownerId");id(item,"playlistId");integer(item,"playlistRevision",1)
            val current=id(item,"currentTrackId")
            val tracks=objects(item,"tracks",100) {track->
                fields(track,"id","title","url")
                val url=text(track,"url",2048);val uri=java.net.URI.create(url)
                check(uri.scheme=="https" && !uri.host.isNullOrBlank() && uri.rawUserInfo==null && uri.port in setOf(-1,443) && url.none {it.isWhitespace()})
                SocialMusicTrack(id(track,"id"),text(track,"title",120),url)
            }
            check(tracks.map {it.id}.distinct().size==tracks.size && tracks.any {it.id==current})
            SocialMusicSelection(selectionId,text(item,"name",80),current,tracks,review(item.getJSONObject("review"),"room-music","$roomId:$selectionId"))
        }
        return SocialRoomMusic(integer(value,"revision"),selection)
    }
    fun signalReceipt(value: JSONObject): SocialSignalReceipt {
        fields(value,"id","status");check(value.get("status")=="sent");return SocialSignalReceipt(id(value,"id"))
    }
}
