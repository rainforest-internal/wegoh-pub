package io.wegoh.app.nativeauth

import org.json.JSONArray
import org.json.JSONObject

internal class NativeTripFieldFailure(val field: String): IllegalStateException("NATIVE_TRIP_FIELD_INVALID")

internal object NativeTripsCodec {
    fun locationShare(value: JSONObject,requestedId: String): TripLocationShare {
        check(value.keys().asSequence().toSet()==setOf("tripId","serverNow","shareId","locations","cars"))
        check(value.getString("tripId")==requestedId)
        val now=java.time.Instant.parse(value.getString("serverNow"))
        check(value.getJSONArray("locations").length()<=100)
        val shareId=if(value.isNull("shareId"))null else value.getString("shareId").also {
            check(Regex("[a-f0-9]{32}").matches(it))
        }
        val cars=unique(rows(array(value,"cars").also {check(it.length()<=20)}) {row->
            check(row.keys().asSequence().toSet()==setOf("carId","source","latitude","longitude","accuracyMeters","capturedAt"))
            val latitude=checkNotNull(coordinate(row,"latitude",90.0));val longitude=checkNotNull(coordinate(row,"longitude",180.0))
            val source=text(row,"source",8).also {check(it in setOf("phone","vehicle"))}
            val captured=field("capturedAt") {java.time.Instant.parse(text(row,"capturedAt",40))}
            TripCarPosition(id(row,"carId"),latitude,longitude,source,maxOf(0L,java.time.Duration.between(captured,now).toMillis()))
        }) {it.carId}
        return TripLocationShare(requestedId,shareId,cars)
    }
    fun locationBody(shareId: String,fix: TripLocationFix): JSONObject {
        require(Regex("[a-f0-9]{32}").matches(shareId))
        require(fix.latitude.isFinite() && fix.latitude in -90.0..90.0 &&
            fix.longitude.isFinite() && fix.longitude in -180.0..180.0 &&
            (fix.accuracyMeters==null || fix.accuracyMeters.isFinite() && fix.accuracyMeters in 0.0..10000.0))
        return JSONObject().put("shareId",shareId).put("latitude",fix.latitude).put("longitude",fix.longitude)
            .put("capturedAt",java.time.Instant.ofEpochMilli(fix.capturedAtMillis).toString())
            .put("accuracyMeters",fix.accuracyMeters ?: JSONObject.NULL)
    }
    private fun <T> field(name: String,read: ()->T): T = try {read()} catch(error: NativeTripFieldFailure) {
        throw error
    } catch(_: Exception) {throw NativeTripFieldFailure(name)}
    private fun array(value: JSONObject,key: String)=field(key) {value.getJSONArray(key)}
    fun friends(value: JSONObject): List<TripInviteFriend> = unique(rows(array(value,"friends")) {
        val state=text(it,"tripState",8).also {state->check(state in setOf("none","pending","accepted"))}
        TripInviteFriend(id(it,"id",true),text(it,"name",80),optionalFlag(it,"hasVehicle"),state)
    }) {it.id}
    private fun text(value: JSONObject,key: String,max: Int,empty: Boolean=false): String = field(key) {
        val raw=value.get(key);check(raw is String && raw.codePointCount(0,raw.length) in (if(empty)0 else 1)..max &&
            raw.none {it.isISOControl() && !(empty && it=='\n')})
        raw
    }
    private fun flag(value: JSONObject,key: String): Boolean = field(key) {val raw=value.get(key);check(raw is Boolean);raw}
    private fun count(value: JSONObject,key: String,min: Int,max: Int): Int = field(key) {
        val raw=value.get(key);check(raw is Int || raw is Long)
        (raw as Number).toLong().also {check(it in min.toLong()..max.toLong())}.toInt()
    }
    private fun id(value: JSONObject,key: String,account: Boolean=false): String = field(key) {text(value,key,64).also {
        check(Regex(if(account)"team-[a-f0-9]{40}" else "[a-f0-9]{32}").matches(it))
    }}
    private fun <T> rows(value: JSONArray,parse: (JSONObject)->T): List<T> = (0 until value.length()).map {parse(value.getJSONObject(it))}
    private fun <T> unique(rows: List<T>,key: (T)->String): List<T> = rows.also {check(it.map(key).distinct().size==it.size)}
    private fun optionalText(value: JSONObject,key: String,max: Int=80): String? =
        if(value.isNull(key))null else text(value,key,max)
    private fun optionalFlag(value: JSONObject,key: String): Boolean? = if(value.isNull(key))null else flag(value,key)
    private fun optionalCount(value: JSONObject,key: String,min: Int,max: Int): Int? =
        if(value.isNull(key))null else count(value,key,min,max)
    private fun date(value: JSONObject,key: String): String? = field(key) {optionalText(value,key,10)?.also {
        check(Regex("[0-9]{4}-[0-9]{2}-[0-9]{2}").matches(it));java.time.LocalDate.parse(it)
    }}
    private fun state(value: JSONObject): String? = field("state") {optionalText(value,"state",16)?.also {
        check(it in setOf("planned","active","completed","cancelled"))
    }}
    private fun permissions(value: JSONObject?): TripPermissions? = value?.let {TripPermissions(flag(it,"invite"),flag(it,"edit"))}
    private fun coordinate(value: JSONObject,key: String,max: Double): Double? = field(key) {
        if(value.isNull(key))null else {
            val raw=value.get(key);check(raw is Number)
            raw.toDouble().also {check(it.isFinite() && it in -max..max)}
        }
    }
    private fun strings(value: JSONArray,account: Boolean=false): List<String> = (0 until value.length()).map {
        val raw=value.get(it);check(raw is String && Regex(if(account)"team-[a-f0-9]{40}" else "[a-f0-9]{32}").matches(raw));raw
    }.also {check(it.distinct().size==it.size)}
    fun places(value: JSONArray): List<TripPlace> = rows(value) {place->
        val selected=place.opt("selectedBy")
        val people=if(selected is JSONArray)strings(selected,true) else null
        val count=if(selected is JSONArray)people?.size else optionalCount(place,"selectedBy",0,20)
        val identifier=if(place.isNull("id"))null else id(place,"id")
        val kind=optionalText(place,"kind",6)?.also {check(it in setOf("pickup","drop","signal"))}
        TripPlace(text(place,"name",if(kind=="signal")80 else 40),identifier,kind,coordinate(place,"lat",90.0),coordinate(place,"lng",180.0),
            if(place.isNull("addedBy"))null else id(place,"addedBy",true),optionalText(place,"createdAt",40),people,count)
    }
    fun routeItem(value: JSONObject): TripRouteItem =
        TripRouteItem(text(value,"type",6),text(value,"ref",80),optionalText(value,"courseId",80),optionalText(value,"dropRef",32))
            .also(::validateRouteItem)
    fun routeItems(value: JSONArray): List<TripRouteItem> = unique(rows(value,::routeItem)) {it.key}
    private fun validateRouteItem(item: TripRouteItem) {
        require(item.type in setOf("course","pickup","drop","signal"))
        if(item.type=="course") {
            require(Regex("[a-z0-9][a-z0-9_-]{0,79}").matches(item.ref))
            require(item.courseId==null || Regex("[a-z0-9][a-z0-9_-]{0,79}").matches(item.courseId))
            require(item.dropRef==null || Regex("[a-f0-9]{32}").matches(item.dropRef))
        } else require(Regex("[a-f0-9]{32}").matches(item.ref) && item.courseId==null && item.dropRef==null)
    }
    fun routeBody(items: List<TripRouteItem>): JSONObject {
        require(items.map {it.key}.distinct().size==items.size)
        val places=items.flatMap {listOfNotNull(it.ref.takeIf {_ ->it.type in setOf("pickup","drop")},it.dropRef)}
        require(places.distinct().size==places.size)
        return JSONObject().put("items",JSONArray().apply {items.forEach {item->
            validateRouteItem(item)
            put(JSONObject().put("type",item.type).put("ref",item.ref).apply {
                item.courseId?.let {put("courseId",it)};item.dropRef?.let {put("dropRef",it)}
            })
        }})
    }
    private fun courses(value: JSONArray): List<TripCourse> = unique(rows(value) {course->
        val pack=text(course,"packId",80).also {check(Regex("[a-z0-9][a-z0-9_-]{0,79}").matches(it))}
        val stops=if(course.isNull("stops"))null else unique(rows(array(course,"stops")) {
            TripCourseStop(text(it,"id",80),text(it,"name",80),coordinate(it,"lat",90.0),coordinate(it,"lng",180.0))
        }) {it.id}
        TripCourse(pack,text(course,"title",100),optionalCount(course,"version",1,Int.MAX_VALUE),
            optionalCount(course,"stopCount",0,100),optionalText(course,"addedByName"),optionalFlag(course,"reviewed"),
            optionalFlag(course,"canRemove"),if(course.isNull("completedCarIds"))null else strings(array(course,"completedCarIds")),stops)
    }) {it.packId}
    fun list(value: JSONObject): TripList {
        val trips=unique(rows(array(value,"trips")) {
            TripSummary(id(it,"id"),text(it,"title",40),flag(it,"isOwner"),text(it,"ownerName",80),
                count(it,"memberCount",1,20),count(it,"carCount",0,20),date(it,"startDate"),date(it,"endDate"),state(it),optionalText(it,"myRole"),
                if(it.isNull("routePreview"))emptyList() else rows(array(it,"routePreview")) {place->
                    TripRoutePreviewPlace(text(place,"name",80),text(place,"courseId",80).also {pack->
                        check(Regex("[a-z0-9][a-z0-9_-]{0,79}").matches(pack))},text(place,"ref",80))
                }.also {preview->check(preview.size<=4)})
        }) {it.id}
        val invitations=unique(rows(array(value,"invitations")) {
            TripInvitation(id(it,"tripId"),text(it,"title",40),text(it,"ownerName",80),date(it,"startDate"),date(it,"endDate"),
                optionalCount(it,"memberCount",1,20),optionalCount(it,"carCount",0,20))
        }) {it.tripId}
        check(trips.none {trip->invitations.any {it.tripId==trip.id}})
        return TripList(trips,invitations)
    }
    private fun remotePolicy(car: JSONObject): TripRemotePolicy? = field("remotePolicy") {
        val policy=car.optJSONObject("remotePolicy")
        if(car.isNull("remotePolicy"))return@field null
        check(policy!=null && policy.keys().asSequence().toSet()==setOf("enabled","actions","deviceId"))
        val enabled=flag(policy,"enabled")
        val raw=array(policy,"actions")
        check(raw.length()<=TripRemotePolicy.supportedActions.size)
        val actions=(0 until raw.length()).map {raw.get(it).also {value->check(value is String && value in TripRemotePolicy.supportedActions)} as String}
        check(actions.distinct().size==actions.size && (!enabled || actions.isNotEmpty()))
        val device=if(policy.isNull("deviceId"))null else id(policy,"deviceId")
        check(!enabled || device!=null)
        TripRemotePolicy(enabled,actions.toSet(),device,optionalCount(car,"remotePolicyRevision",0,Int.MAX_VALUE)?.toLong())
    }
    fun detail(value: JSONObject,expected: String,requestedAtElapsedMillis: Long?=null): TripDetail {
        check(id(value,"id")==expected)
        val contractVersion=field("routeContractVersion") {TripRouteContractCodec.version(value)}
        val members=unique(rows(array(value,"members")) {
            val state=text(it,"state",8);check(state in setOf("pending","accepted"))
            TripMember(id(it,"id",true),text(it,"name",80),state=="accepted",flag(it,"isOwner"),flag(it,"isMe"),
                if(it.isNull("carId"))null else id(it,"carId"),optionalFlag(it,"hasVehicle"),permissions(it.optJSONObject("permissions")),
                optionalText(it,"role",20)?.also {role->check(role in setOf("member","dj","food","rest"))},
                field("readiness") {text(it,"readiness",16).let {raw->TripReadiness.values().first {r->r.wire==raw}}
                    .also {r->check((state=="pending")==(r==TripReadiness.INVITED))}})
        }) {it.id}
        check(members.size in 1..20 && members.count {it.isMe}==1 && members.first {it.isMe}.accepted)
        val cars=unique(rows(array(value,"cars")) {car->
            val passengers=unique(rows(array(car,"passengers")) {
                TripPassenger(id(it,"id",true),text(it,"name",80),flag(it,"isMe"))
            }) {it.id}
            val seats=count(car,"seats",1,8);check(passengers.size<=seats)
            TripCar(id(car,"id"),text(car,"name",20),id(car,"driverId",true),text(car,"driverName",80),seats,
                flag(car,"isMine"),flag(car,"iRide"),passengers,if(car.isNull("places"))null else places(array(car,"places")),
                if(car.isNull("routeOrder"))null else routeItems(array(car,"routeOrder")),
                if(car.isNull("routeNext"))null else field("routeNext") {routeItem(car.getJSONObject("routeNext"))},
                car.has("routeNext"),if(car.has("routeRevision"))count(car,"routeRevision",0,Int.MAX_VALUE).toLong() else 0,remotePolicy(car),
                if(car.isNull("routePlan"))null else field("routePlan") {TripRouteContractCodec.plan(car.getJSONObject("routePlan"))},
                if(car.isNull("routeStatus"))null else field("routeStatus") {TripRouteContractCodec.status(car.getJSONObject("routeStatus"))},
                optionalCount(car,"ordinal",1,Int.MAX_VALUE))
        }) {it.id}
        check(cars.size<=20 && cars.count {it.isMine || it.iRide}<=1)
        check(cars.mapNotNull {it.ordinal}.let {it.distinct().size==it.size})
        for(car in cars) {
            check(!(car.isMine && car.iRide))
            check(car.passengers.none {it.id==car.driverId})
            check(car.iRide==car.passengers.any {it.isMe})
            check(car.isMine==(car.driverId==members.first {it.isMe}.id))
            checkRoutePrivacy(car,contractVersion)
        }
        val revision=field("revision") {if(value.isNull("revision"))null else value.get("revision").let {
            check(it is Int || it is Long);(it as Number).toLong().also {n->check(n in 1..Int.MAX_VALUE.toLong())}
        }}
        val invites=if(value.isNull("rideInvites"))null else unique(rows(array(value,"rideInvites")) {
            TripRideInvite(id(it,"id"),id(it,"carId"),id(it,"accountId",true),optionalText(it,"createdAt",40))
        }) {it.id}
        val startConflict=if(value.isNull("startConflict"))null else field("startConflict") {startConflict(value.getJSONObject("startConflict"),expected,members)}
        return TripDetail(expected,text(value,"title",40),text(value,"description",300,true),members,cars,
            date(value,"startDate"),date(value,"endDate"),state(value),revision,permissions(value.optJSONObject("myPermissions")),
            if(value.isNull("courses"))null else courses(array(value,"courses")),invites,
            value.optJSONObject("link")?.let {TripLink(flag(it,"active"),optionalText(it,"expiresAt",40))},
            value.optJSONObject("display")?.let {NativeTripDisplayCodec.read(it,requestedAtElapsedMillis ?: android.os.SystemClock.elapsedRealtime())},
            if(value.has("locationConsent"))flag(value,"locationConsent") else false,contractVersion,startConflict)
    }
    private fun startConflict(value: JSONObject,expected: String,members: List<TripMember>): TripStartConflict {
        check(value.keys().asSequence().toSet()==setOf("activeTrips","busyMemberIds") && members.first {it.isMe}.isOwner)
        val active=unique(rows(array(value,"activeTrips")) {
            check(it.keys().asSequence().toSet()==setOf("tripId","title","isOwner"))
            TripActiveTrip(id(it,"tripId"),text(it,"title",40),flag(it,"isOwner"))
        }) {it.id}
        val raw=array(value,"busyMemberIds")
        val busy=(0 until raw.length()).map {index->raw.get(index).also {check(it is String)} as String}
        check(active.none {it.id==expected} && busy.distinct().size==busy.size &&
            busy.all {id->members.any {it.id==id && it.accepted && !it.isMe}})
        return TripStartConflict(active,busy)
    }
    fun section(base: TripDetail,value: JSONObject,section: String,requestedAtElapsedMillis: Long): TripDetail {
        check(id(value,"id")==base.id)
        val revision=count(value,"revision",1,Int.MAX_VALUE).toLong()
        if(section=="location") {
            check(value.keys().asSequence().toSet()==setOf("id","revision","locationConsent","display"))
            val display=NativeTripDisplayCodec.read(value.getJSONObject("display"),requestedAtElapsedMillis)
            return base.copy(revision=revision,locationSharing=flag(value,"locationConsent"),display=base.display?.copy(
                companions=display.companions,companionsExpiresAtElapsedMillis=display.expiresAtElapsedMillis) ?: display)
        }
        val modern=value.has("routeContractVersion")
        check(section=="route" && value.keys().asSequence().toSet()==
            setOf("id","revision","cars","courses")+(if(modern)setOf("routeContractVersion") else emptySet()))
        val contractVersion=field("routeContractVersion") {TripRouteContractCodec.version(value)}
        check(modern || base.routeContractVersion==1)
        val updates=unique(rows(array(value,"cars")) {it}) {id(it,"id")}.associateBy {id(it,"id")}
        check(updates.keys==base.cars.map {it.id}.toSet())
        val cars=base.cars.map {car ->
            val update=updates.getValue(car.id)
            check(update.keys().asSequence().toSet().all {it in setOf("id","isMine","iRide","places","routeOrder","routeRevision","routeNext")+
                (if(modern)setOf("routePlan","routeStatus","ordinal") else emptySet())})
            if(modern)check(update.has("routePlan") && update.has("routeStatus"))
            check(flag(update,"isMine")==car.isMine && flag(update,"iRide")==car.iRide)
            car.copy(places=places(array(update,"places")),
                routeOrder=if(update.isNull("routeOrder"))null else routeItems(array(update,"routeOrder")),
                routeNext=if(update.isNull("routeNext"))null else routeItem(update.getJSONObject("routeNext")),
                routeNextKnown=update.has("routeNext"),routeRevision=if(update.has("routeRevision"))count(update,"routeRevision",0,Int.MAX_VALUE).toLong() else 0,
                routePlan=if(update.isNull("routePlan"))null else field("routePlan") {TripRouteContractCodec.plan(update.getJSONObject("routePlan"))},
                routeStatus=if(update.isNull("routeStatus"))null else field("routeStatus") {TripRouteContractCodec.status(update.getJSONObject("routeStatus"))},
                ordinal=if(update.has("ordinal"))count(update,"ordinal",1,Int.MAX_VALUE).also {check(car.ordinal==null || it==car.ordinal)} else car.ordinal)
                .also {checkRoutePrivacy(it,contractVersion)}
        }
        return base.copy(revision=revision,cars=cars,courses=courses(array(value,"courses")),routeContractVersion=contractVersion)
    }
    private fun checkRoutePrivacy(car: TripCar,contractVersion: Int) {
        check(contractVersion==2 || car.routePlan==null && car.routeStatus==null)
        check(car.routePlan==null || car.isMine || car.iRide)
        if(contractVersion==2 && !car.isMine && !car.iRide)
            check(car.places.orEmpty().isEmpty() && car.routeOrder==null && !car.routeNextKnown && car.routeRevision==0L)
    }
    fun invitationResponseBody(accept: Boolean, locationConsent: Boolean?): JSONObject {
        require(accept == (locationConsent != null))
        return JSONObject().put("accept",accept).apply {
            if(locationConsent != null)put("locationConsent",locationConsent)
        }
    }
    fun response(value: JSONObject,accept: Boolean) {
        check(value.keys().asSequence().toSet()==setOf("status") && value.get("status")==if(accept)"accepted" else "declined")
    }
}
