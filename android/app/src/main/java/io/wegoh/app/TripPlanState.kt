package io.wegoh.app

import io.wegoh.app.nativeauth.*
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.time.temporal.ChronoUnit
import java.util.Locale

enum class TripPlanTab(val title: String) { OVERVIEW("준비"), GROUPS("차"), MEMBERS("일행"), ROUTE("경로") }
data class TripPlanMenu(val tab: TripPlanTab,val count: String,val subtitle: String)
data class TripTodo(val text: String,val action: String,val tab: TripPlanTab)
data class TripPlanOverview(val menu: List<TripPlanMenu>,val todos: List<TripTodo>,val accepted: Int,val pending: Int,val unassigned: Int,val ready: Int)

/**
 * 여행 준비 체크리스트 한 줄. [notApplicable]이면 이 여행에서는 할 일이 없어 '해당 없음'으로 보이고 완료로 센다.
 * 체크리스트는 내 준비 안내이고 시작 조건은 [tripCanStart]가 정한다. 둘이 같이 보는 조건은 [tripRouteReady] 하나다.
 */
data class TripPreparationCheck(val label: String,val done: Boolean,val notApplicable: Boolean=false)

/**
 * 내가 타고 내릴 곳. 운전자는 직접 고르지 않으므로 [driving]이고 차에 정해진 타는 곳·내리는 곳을 그대로 보여 준다.
 * 동승자는 자기가 고른 곳만 센다. 준비 체크리스트와 이동 경로 칩이 같은 판정과 문구를 쓴다.
 */
data class TripMyStops(val driving: Boolean,val pickup: List<TripPlace>,val drop: List<TripPlace>) {
    val chosen get()=driving || pickup.isNotEmpty() && drop.isNotEmpty()
    fun label(kind: String): String {
        val places=if(kind=="pickup")pickup else drop
        return when {
            places.isEmpty()->if(driving)"해당 없음" else "미정"
            places.size==1->places.single().name
            else->"${places.first().name} 외 ${places.size-1}곳"
        }
    }
}

fun tripMyStops(trip: TripDetail): TripMyStops {
    val car=trip.myCar
    val driving=car?.isMine==true
    val me=trip.me
    val places=car?.places.orEmpty().filter {driving || me?.id in it.selectedBy.orEmpty()}
    return TripMyStops(driving,places.filter {it.kind=="pickup"},places.filter {it.kind=="drop"})
}

/** 혼자 하는 여행은 기다릴 일행이 없어 '일행 준비'가 해당 없음이다. */
fun tripTravelsAlone(trip: TripDetail)=trip.members.size<=1

fun tripRouteReady(trip: TripDetail)=trip.courses.orEmpty().isNotEmpty() && TripRouteOrder.isComplete(trip)

fun tripPreparationChecks(trip: TripDetail): List<TripPreparationCheck> {
    val alone=tripTravelsAlone(trip)
    val stops=tripMyStops(trip)
    return listOf(
        TripPreparationCheck("일행 준비",alone || trip.members.all {it.readiness==TripReadiness.READY},notApplicable=alone),
        TripPreparationCheck("탈 차 고르기",trip.myCar!=null),
        TripPreparationCheck("타고 내릴 곳 정하기",trip.myCar!=null && stops.chosen,notApplicable=stops.driving),
        TripPreparationCheck("경로 준비",tripRouteReady(trip)))
}

/** 일행 준비·타고 내릴 곳은 안내만 하고 시작을 막지 않는다. 시작은 만든 사람·차·완성된 경로·다른 여행 중인 일행만 본다. */
fun tripCanStart(trip: TripDetail)=trip.isOwner && trip.state=="planned" && trip.revision!=null &&
    trip.cars.isNotEmpty() && tripRouteReady(trip) &&
    trip.startConflict?.busyMemberIds.isNullOrEmpty()

/** Names of accepted members who are still in another running trip, so the owner knows whom to ask. */
fun tripBusyMemberNames(trip: TripDetail)=trip.startConflict?.busyMemberIds.orEmpty()
    .mapNotNull {id->trip.members.firstOrNull {it.id==id}?.name}

fun tripPlanOverview(trip: TripDetail): TripPlanOverview {
    val accepted=trip.members.filter {it.accepted}
    val pending=trip.members.size-accepted.size
    val assigned=trip.cars.flatMap {listOf(it.driverId)+it.passengers.map {rider->rider.id}}.toSet()
    val unassigned=accepted.count {it.carId==null && it.id !in assigned}
    val freeSeats=trip.cars.sumOf {it.seats-it.passengers.size}
    val courses=trip.courses.orEmpty()
    val todos=buildList {
        if(accepted.size<=1)add(TripTodo("일행을 초대해 주세요","초대하기",TripPlanTab.MEMBERS))
        if(trip.cars.isEmpty())add(TripTodo("탈 차를 추가해 주세요","차 추가",TripPlanTab.GROUPS))
        if(courses.isEmpty())add(TripTodo("경로를 추가해 주세요","경로 추가",TripPlanTab.ROUTE))
    }
    val memberSub=listOfNotNull("초대 대기 ${pending}명".takeIf {pending>0},"차 미정 ${unassigned}명".takeIf {unassigned>0})
        .joinToString("\n").ifEmpty {if(accepted.size>1)"탈 차 선택 완료" else "나만 참여"}
    return TripPlanOverview(listOf(
        TripPlanMenu(TripPlanTab.OVERVIEW,if(todos.isEmpty())"" else "${todos.size}",if(todos.isEmpty())"할 일 없음" else "할 일 ${todos.size}"),
        TripPlanMenu(TripPlanTab.GROUPS,"${trip.cars.size}",if(trip.cars.isEmpty())"없음" else "빈자리 ${freeSeats}석"),
        TripPlanMenu(TripPlanTab.MEMBERS,"${accepted.size}",memberSub),
        TripPlanMenu(TripPlanTab.ROUTE,"${courses.size}",if(courses.isEmpty())"없음" else "")),todos,accepted.size,pending,unassigned,
        trip.members.count {it.readiness==TripReadiness.READY})
}

fun tripDateLabel(start: String?,end: String?): String {
    val format=DateTimeFormatter.ofPattern("M/d(E)",Locale.KOREAN)
    val first=start?.let {runCatching {LocalDate.parse(it)}.getOrNull()}
    val last=end?.let {runCatching {LocalDate.parse(it)}.getOrNull()}
    return when {
        first!=null && last!=null && first!=last->"${first.format(format)}~${last.format(format)}"
        first!=null->first.format(format)
        last!=null->"${last.format(format)}까지"
        else->"날짜 미정"
    }
}
/**
 * 여행 상태 이름. 목록 카드와 상세 머리 배지가 같이 쓰고, 계획 중인 여행은 iPhone과 같은 '준비 중'으로 부른다.
 * 시작일이 오늘이거나 앞으로면 남은 날만 덧붙인다.
 */
fun tripStateLabel(state: String?,start: String?,today: LocalDate=LocalDate.now()): String {
    if(state=="active")return "진행 중"
    if(state in setOf("completed","cancelled"))return "지난 여행"
    val days=start?.let {runCatching {ChronoUnit.DAYS.between(today,LocalDate.parse(it))}.getOrNull()}
    return when {days==null || days<0->"준비 중";days==0L->"준비 중 · 오늘";else->"준비 중 · ${days}일 후"}
}

data class TripRouteStop(val item: TripRouteItem,val name: String,val lat: Double?,val lng: Double?,val people: List<String> = emptyList(),
    val dropPeople: List<String> = emptyList()) {
    val key get()=item.key
    val kind get()=when(item.type){"pickup"->"타는 곳";"drop"->"내리는 곳";"signal"->"손들기";else->if(item.dropRef!=null)"경로 (내리는 곳)" else "경로"}
    val canNavigate get()=lat!=null && lng!=null
}

object TripRouteOrder {
    fun courseItems(trip: TripDetail): List<TripRouteItem> = trip.courses.orEmpty().flatMap {course->
        course.stops.orEmpty().map {TripRouteItem("course",it.id,course.packId)}
    }
    fun isComplete(trip: TripDetail): Boolean = trip.courses!=null && trip.courses.all {course->
        course.stops!=null && course.stops.isNotEmpty() && (course.stopCount==null || course.stops.size==course.stopCount)
    }
    fun initial(trip: TripDetail,car: TripCar): List<TripRouteItem> {
        if(trip.routeContractVersion==2)return car.routePlan?.segments.orEmpty().flatMap {it.items}
        car.routeOrder?.let {saved->return saved.map {item->
            if(item.type=="course" && item.courseId==null)item.copy(courseId=trip.courses.orEmpty()
                .singleOrNull {course->course.stops.orEmpty().any {it.id==item.ref}}?.packId) else item
        }}
        var result=courseItems(trip)
        car.places.orEmpty().filter {it.kind=="pickup"}.forEach {result=add(result,it,trip)}
        car.places.orEmpty().filter {it.kind=="drop"}.forEach {result=add(result,it,trip)}
        return result
    }
    fun move(items: List<TripRouteItem>,index: Int,delta: Int): List<TripRouteItem> {
        val target=index+delta
        if(index !in items.indices || target !in items.indices || delta !in listOf(-1,1))return items
        return items.toMutableList().apply {val previous=this[index];this[index]=this[target];this[target]=previous}
    }
    fun remove(items: List<TripRouteItem>,index: Int): List<TripRouteItem> {
        val item=items.getOrNull(index) ?: return items
        return when {item.type!="course"->items.filterIndexed {i,_->i!=index}
            item.dropRef!=null->items.mapIndexed {i,row->if(i==index)row.copy(dropRef=null) else row}
            else->items}
    }
    fun outside(items: List<TripRouteItem>,places: List<TripPlace>): List<TripPlace> {
        val used=items.flatMap {item->listOfNotNull(item.ref.takeIf {item.type!="course"}?.let {"${item.type}:$it"},
            item.dropRef?.let {"drop:$it"})}.toSet()
        return places.filter {it.id!=null && "${it.kind}:${it.id}" !in used && it.kind in setOf("pickup","drop","signal")}
    }
    fun add(items: List<TripRouteItem>,place: TripPlace,trip: TripDetail): List<TripRouteItem> {
        val id=place.id ?: return items
        if(place !in outside(items,listOf(place)))return items
        val host=if(place.kind=="drop")items.indexOfFirst {item->item.type=="course" && item.dropRef==null &&
            trip.courses.orEmpty().firstOrNull {it.packId==item.courseId}?.stops?.any {
                it.id==item.ref && it.lat!=null && it.lng!=null && it.lat==place.lat && it.lng==place.lng
            }==true} else -1
        if(host>=0)return items.mapIndexed {index,item->if(index==host)item.copy(dropRef=id) else item}
        val added=TripRouteItem(place.kind ?: return items,id)
        val index=if(place.kind=="pickup")items.indexOfFirst {it.type=="course"}.takeIf {it>=0} ?: items.size else items.size
        return items.toMutableList().apply {add(index,added)}
    }
    fun resolve(items: List<TripRouteItem>,trip: TripDetail,car: TripCar): List<TripRouteStop> = items.map {item->
        fun place(ref: String?,kind: String)=car.places.orEmpty().firstOrNull {
            it.id==ref && (it.kind==kind || it.kind==null && kind in setOf("pickup","drop"))}
        val stop=trip.courses.orEmpty().firstOrNull {it.packId==item.courseId}?.stops?.firstOrNull {it.id==item.ref}
        fun people(ref: String?,kind: String)=place(ref,kind)?.selectedBy.orEmpty().mapNotNull {id->
            trip.members.firstOrNull {it.id==id}?.name}
        val selected=place(item.ref,item.type)
        if(item.type=="course")TripRouteStop(item,stop?.name ?: "장소 정보 없음",stop?.lat,stop?.lng,dropPeople=people(item.dropRef,"drop"))
        else TripRouteStop(item,selected?.name ?: "위치 정보 없음",selected?.lat,selected?.lng,
            if(item.type=="signal")emptyList() else people(item.ref,item.type))
    }
    fun preservesSegments(items: List<TripRouteItem>,trip: TripDetail): Boolean {
        if(!isComplete(trip) || items.filter {it.type=="course"}!=courseItems(trip))return false
        if(items.any {it.dropRef!=null || it.type !in setOf("pickup","course","drop")})return false
        val ranks=items.map {when(it.type){"pickup"->0;"course"->1;else->2}}
        return ranks.zipWithNext().all {(first,second)->first<=second}
    }
    fun preservesCourses(items: List<TripRouteItem>,trip: TripDetail): Boolean = isComplete(trip) &&
        items.filter {it.type=="course"}.map {it.key}.sorted()==courseItems(trip).map {it.key}.sorted()
}

enum class TripGear { UNKNOWN, PARK, DRIVE, OTHER }
enum class TripDrivingPhase { FAR, NEAR, ARRIVED, ROUTE_END, ROUTE_COMPLETE, LATER, SKIPPED }
data class TripDrivingState(val phase: TripDrivingPhase=TripDrivingPhase.LATER,val targetKey: String?=null,
    val distanceMeters: Double?=null,val enteredNear: Boolean=false,val arrived: Set<String> = emptySet(),
    val skipped: Set<String> = emptySet(),val completedCourse: String?=null,
    val remainingSeconds: Int?=null,val position: TripPosition?=null,val legStartMeters: Double?=null,val naviAtMillis: Long=0,
    val positionUnavailable: Boolean=false) {
    fun navigate(stop: TripRouteStop)=copy(phase=TripDrivingPhase.FAR,targetKey=stop.key,distanceMeters=null,enteredNear=false,completedCourse=null,remainingSeconds=null,legStartMeters=null,naviAtMillis=0)
    fun distance(meters: Double,localProgress: Boolean=true): TripDrivingState {
        if(!meters.isFinite() || meters<0 || targetKey==null || phase !in setOf(TripDrivingPhase.FAR,TripDrivingPhase.NEAR))return this
        val near=enteredNear || meters<=300.0
        return when {near && meters>1000.0 && !localProgress->copy(phase=TripDrivingPhase.FAR,distanceMeters=meters,enteredNear=false)
            near && meters>1000.0->copy(phase=TripDrivingPhase.SKIPPED,distanceMeters=meters,enteredNear=true,skipped=skipped+targetKey)
            else->copy(phase=if(meters<=300.0)TripDrivingPhase.NEAR else if(near)TripDrivingPhase.NEAR else TripDrivingPhase.FAR,
                distanceMeters=meters,enteredNear=near)}
    }
    fun arrive(lastInCourse: Boolean): TripDrivingState = if(phase!=TripDrivingPhase.NEAR || targetKey==null)this else
        copy(phase=if(lastInCourse)TripDrivingPhase.ROUTE_END else TripDrivingPhase.ARRIVED,arrived=arrived+targetKey)
    fun later()=if(phase==TripDrivingPhase.ARRIVED)copy(phase=TripDrivingPhase.LATER) else this
    fun complete(packId: String)=copy(phase=TripDrivingPhase.ROUTE_COMPLETE,completedCourse=packId)
}

fun tripNextStop(stops: List<TripRouteStop>,drive: TripDrivingState): TripRouteStop? =
    stops.firstOrNull {it.key !in drive.arrived && it.key !in drive.skipped}
fun tripRouteMarker(stops: List<TripRouteStop>,drive: TripDrivingState): Float? {
    if(drive.positionUnavailable)return null
    tripLiveMarker(stops,drive)?.let {return it}
    val target=tripMarkerTarget(stops,drive)
    if(target>=0)return if(drive.phase in setOf(TripDrivingPhase.FAR,TripDrivingPhase.NEAR) || stops[target].key!=drive.targetKey)
        target-0.5f else target.toFloat()
    return stops.indexOfLast {it.key in drive.arrived || it.key in drive.skipped}.takeIf {it>=0}?.toFloat()
}
/**
 * 진행 띠의 현재 위치 표식이 향하는 장소의 순번. 표식은 "다음 남은 장소 앞"을 뜻하므로, 내비 안내 대상이
 * 다음 남은 장소보다 뒤에 있으면(예: 서울역 안내 중 그 앞에 들어온 손들기 장소) 다음 남은 장소를 향한다.
 */
internal fun tripMarkerTarget(stops: List<TripRouteStop>,drive: TripDrivingState): Int {
    val aimed=stops.indexOfFirst {it.key==drive.targetKey}
    val pending=tripNextStop(stops,drive)?.let {stop->stops.indexOfFirst {it.key==stop.key}} ?: return aimed
    return if(aimed>pending)pending else aimed
}
data class TripRouteStripProgress(val showStart: Boolean,val marker: Float?)
fun tripRouteStripProgress(stops: List<TripRouteStop>,drive: TripDrivingState,planned: Boolean): TripRouteStripProgress {
    if(planned)return TripRouteStripProgress(false,null)
    val marker=tripRouteMarker(stops,drive)
    val showStart=stops.none {it.key in drive.arrived || it.key in drive.skipped} || marker!=null && marker<0f
    return TripRouteStripProgress(showStart,(marker ?: if(showStart && !drive.positionUnavailable)-1f else null)?.let {it+if(showStart)1 else 0})
}
fun tripArriveAtStop(stops: List<TripRouteStop>,drive: TripDrivingState): TripDrivingState {
    val target=stops.firstOrNull {it.key==drive.targetKey} ?: return drive
    val course=tripStopCourse(target,stops)
    val remaining=stops.dropWhile {it.key!=target.key}.drop(1).any {
        tripStopCourse(it,stops)==course && it.key !in drive.skipped && it.key !in drive.arrived
    }
    return drive.arrive(course!=null && !remaining)
}
fun tripStopCourse(stop: TripRouteStop,items: List<TripRouteStop>): String? {
    if(stop.item.type=="signal")return null
    return stop.item.courseId ?: items.dropWhile {it.key!=stop.key}.firstNotNullOfOrNull {it.item.courseId} ?:
        items.asReversed().firstNotNullOfOrNull {it.item.courseId}
}

fun reconcileTripDriving(trip: TripDetail,drive: TripDrivingState): TripDrivingState {
    val car=trip.myCar ?: return TripDrivingState()
    val stops=TripRouteOrder.resolve(TripRouteOrder.initial(trip,car),trip,car)
    val keys=stops.map {it.key}.toSet()
    val completed=trip.courses.orEmpty().filter {car.id in it.completedCarIds.orEmpty()}.map {it.packId}.toSet()
    val completedStops=stops.filter {tripStopCourse(it,stops) in completed}.map {it.key}.toSet()
    val target=stops.firstOrNull {it.key==drive.targetKey}
    val updated=drive.copy(arrived=drive.arrived.intersect(keys)+completedStops,skipped=drive.skipped.intersect(keys))
    return when {
        target==null->updated.copy(targetKey=null,phase=TripDrivingPhase.LATER,distanceMeters=null,enteredNear=false,remainingSeconds=null,legStartMeters=null,naviAtMillis=0)
        target.key in completedStops->updated.copy(phase=TripDrivingPhase.ROUTE_COMPLETE,completedCourse=tripStopCourse(target,stops))
        else->updated
    }
}

fun canPerformTripAction(trip: TripDetail,action: TripAction): Boolean {
    if(trip.state !in setOf("planned","active"))return false
    fun driving(id: String)=trip.cars.any {it.id==id && it.isMine}
    return when(action) {
        is TripAction.SetLocationSharing->trip.me?.accepted==true
        is TripAction.Start->trip.isOwner && trip.state=="planned" && trip.revision==action.revision
        is TripAction.Finish->trip.isOwner && trip.state=="active" && trip.revision==action.revision
        is TripAction.EditIntro,is TripAction.EditDates->trip.canEdit
        is TripAction.AddCourse->trip.canAddCourse
        is TripAction.RemoveCourse->trip.canEdit || trip.courses.orEmpty().any {it.packId==action.packId && it.canRemove==true}
        is TripAction.Invite,TripAction.CreateLink,TripAction.RevokeLink->trip.canInvite
        is TripAction.RemoveMember->trip.isOwner && action.accountId!=trip.me?.id
        is TripAction.CreateCar->trip.me?.hasVehicle==true && trip.cars.none {it.isMine}
        is TripAction.EditCar->driving(action.carId) && action.seats>=trip.cars.first {it.id==action.carId}.passengers.size
        is TripAction.DeleteCar->driving(action.carId) || trip.isOwner
        is TripAction.Ride->trip.cars.none {it.isMine} && trip.cars.any {it.id==action.carId && it.passengers.size<it.seats}
        TripAction.LeaveCar->trip.myCar?.iRide==true
        is TripAction.AddPlace->driving(action.carId)
        is TripAction.DeletePlace->driving(action.carId)
        is TripAction.InviteRider->driving(action.carId) && trip.cars.first {it.id==action.carId}.let {it.passengers.size<it.seats} &&
            trip.members.any {it.id==action.accountId && it.accepted} && trip.cars.none {it.driverId==action.accountId}
        is TripAction.CancelRideInvite->driving(action.carId)
        is TripAction.RemoveRider->driving(action.carId)
    }
}
