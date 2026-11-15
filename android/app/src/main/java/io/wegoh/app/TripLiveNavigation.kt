package io.wegoh.app

import kotlin.math.*

data class TripPosition(val latitude: Double,val longitude: Double,val heading: Double?=null) {
    val valid get()=latitude.isFinite() && longitude.isFinite() && latitude in -90.0..90.0 && longitude in -180.0..180.0
}
data class TripNavigationTarget(val latitude: Double,val longitude: Double,val meters: Double?,val seconds: Int?)
data class TripNavigationUpdate(val position: TripPosition?=null,val targets: List<TripNavigationTarget>?=null,
    val arrived: Boolean=false,val receivedAtMillis: Long=System.currentTimeMillis(),val positionUnavailable: Boolean=false)

/** Independent provider observations expire; an empty provider must not erase the other's fresh fix. */
internal class TripPositionSources {
    private var navi: Pair<TripPosition,Long>?=null
    private var fused: Pair<TripPosition,Long>?=null
    fun navi(point: TripPosition?,at: Long) {navi=point?.takeIf {it.valid}?.let {it to at}}
    fun fused(point: TripPosition?,at: Long) {fused=point?.takeIf {it.valid}?.let {it to at}}
    fun current(now: Long): TripPosition? = navi?.takeIf {now-it.second in 0L..5000L}?.first
        ?: fused?.takeIf {now-it.second in 0L..15000L}?.first
    fun clear() {navi=null;fused=null}
}

internal fun tripMeters(a: TripPosition,b: TripPosition): Double {
    val latitude=Math.toRadians(b.latitude-a.latitude)
    val longitude=Math.toRadians(b.longitude-a.longitude)
    val h=sin(latitude/2).pow(2)+cos(Math.toRadians(a.latitude))*cos(Math.toRadians(b.latitude))*sin(longitude/2).pow(2)
    return 6371000.0*2*atan2(sqrt(h.coerceIn(0.0,1.0)),sqrt((1-h).coerceIn(0.0,1.0)))
}
internal fun TripRouteStop.position(): TripPosition? = if(lat!=null && lng!=null)TripPosition(lat,lng).takeIf {it.valid} else null
internal fun applyTripNavigation(stops: List<TripRouteStop>,drive: TripDrivingState,update: TripNavigationUpdate,localProgress: Boolean=true): TripDrivingState {
    if(update.positionUnavailable)return drive.copy(position=null,positionUnavailable=true,distanceMeters=null,
        remainingSeconds=null,legStartMeters=null,naviAtMillis=0)
    val position=update.position?.takeIf {it.valid} ?: drive.position
    fun withPosition(value: TripDrivingState)=value.copy(position=position,
        positionUnavailable=if(update.position?.valid==true)false else value.positionUnavailable)
    val next=tripNextStop(stops,drive)
    val active=stops.firstOrNull {it.key==drive.targetKey && it.key !in drive.arrived && it.key !in drive.skipped}
    fun meters(candidate: TripNavigationTarget,stop: TripRouteStop): Double? {
        val point=TripPosition(candidate.latitude,candidate.longitude)
        return if(point.valid)stop.position()?.let {tripMeters(point,it)}?.takeIf {it<=100.0} else null
    }
    // OEM 내비 목적지는 좌표로만 온다. 100m 안에 남은 장소가 여럿이면(예: 서울역과 서울역점 카페 손들기 장소)
    // 경로 순서상 앞의 장소가 아니라 그 좌표에 가장 가까운 남은 장소 하나만 그 안내의 대상으로 본다.
    // 이미 도착·건너뛴 장소는 후보가 아니다(순환 코스의 출발지와 도착지처럼 좌표가 겹쳐도 남은 장소가 대상이 된다).
    fun owner(candidate: TripNavigationTarget): TripRouteStop? =
        stops.filter {it.key !in drive.arrived && it.key !in drive.skipped}.mapNotNull {stop->meters(candidate,stop)?.let {stop to it}}
            .minWithOrNull(compareBy<Pair<TripRouteStop,Double>> {it.second}.thenBy {if(it.first.key==drive.targetKey)0 else 1})?.first
    fun matches(candidate: TripNavigationTarget,stop: TripRouteStop)=owner(candidate)?.key==stop.key
    val observed=if(drive.naviAtMillis==0L && !update.arrived && drive.phase !in
        setOf(TripDrivingPhase.ARRIVED,TripDrivingPhase.ROUTE_END,TripDrivingPhase.ROUTE_COMPLETE))stops.firstOrNull {stop->
        stop.key !in drive.arrived && stop.key !in drive.skipped && update.targets.orEmpty().any {matches(it,stop)}
    } else null
    val target=observed ?: active ?: next ?: return withPosition(drive)
    val targetPosition=target.position() ?: return withPosition(drive)
    val matching=update.targets.orEmpty().firstOrNull {matches(it,target)}
    val reading=matching?.takeIf {it.meters?.let {meters->meters.isFinite() && meters>=0}==true}
    if(reading==null && update.position?.takeIf {it.valid}==null && !(update.arrived && matching!=null))return withPosition(drive)
    val completed=drive.phase in setOf(TripDrivingPhase.ARRIVED,TripDrivingPhase.ROUTE_END,TripDrivingPhase.ROUTE_COMPLETE)
    if(completed && reading==null)return withPosition(drive)
    if(completed && update.targets?.firstOrNull()?.let {candidate->
        stops.firstOrNull {it.key==drive.targetKey}?.let {meters(candidate,it)!=null}
    }==true)return withPosition(drive)
    // 내비 좌표 100m 안의 앞선 장소(예: 목적지 옆에 새로 들어온 손들기 장소)는 지나쳤는지 좌표로 알 수 없으므로 건너뛰지 않는다.
    val observedTarget=observed?.let {stop->update.targets.orEmpty().firstOrNull {matches(it,stop)}}
    val initial=if(observed!=null && localProgress)drive.copy(skipped=drive.skipped+
        stops.takeWhile {it.key!=observed.key}.filter {it.key !in drive.arrived && observedTarget?.let {target->meters(target,it)}==null}.map {it.key}) else drive
    var state=if(observed!=null || initial.targetKey!=target.key || initial.phase==TripDrivingPhase.LATER)initial.navigate(target) else initial
    state=withPosition(state)
    val naviFresh=state.naviAtMillis>0 && update.receivedAtMillis-state.naviAtMillis in 0..5000
    val meters=reading?.meters ?: if(!naviFresh)position?.let {tripMeters(it,targetPosition)} else null
    if(meters!=null) {
        state=state.distance(meters,localProgress).copy(legStartMeters=maxOf(state.legStartMeters ?: meters,meters),
            remainingSeconds=reading?.seconds?.takeIf {it>=0},
            naviAtMillis=if(reading!=null)update.receivedAtMillis else state.naviAtMillis)
        if(localProgress && meters<=50.0 && (meters>0 || position?.let {tripMeters(it,targetPosition)<=50.0}==true))
            state=tripArriveAtStop(stops,state)
    }
    if(localProgress && update.arrived && active!=null && matching!=null)state=tripArriveAtStop(stops,state.distance(0.0))
    return state
}
internal fun tripLiveMarker(stops: List<TripRouteStop>,drive: TripDrivingState): Float? {
    val target=if(drive.phase in setOf(TripDrivingPhase.ARRIVED,TripDrivingPhase.ROUTE_END,TripDrivingPhase.ROUTE_COMPLETE))
        tripNextStop(stops,drive)?.let {stop->stops.indexOfFirst {it.key==stop.key}} ?: stops.lastIndex
        else tripMarkerTarget(stops,drive)
    if(target !in stops.indices)return null
    val position=drive.position
    if(position==null && drive.phase in setOf(TripDrivingPhase.ARRIVED,TripDrivingPhase.ROUTE_END,TripDrivingPhase.ROUTE_COMPLETE))
        return stops.indexOfFirst {it.key==drive.targetKey}.takeIf {it>=0}?.toFloat()
    if(target>0 && position!=null && stops[target-1].key in drive.arrived) {
        val start=stops[target-1].position();val end=stops[target].position()
        if(start!=null && end!=null) {
            val scale=cos(Math.toRadians(start.latitude))
            val dx=(end.longitude-start.longitude)*scale;val dy=end.latitude-start.latitude
            val length=dx*dx+dy*dy
            if(length>0) {
                val fraction=(((position.longitude-start.longitude)*scale*dx+(position.latitude-start.latitude)*dy)/length).coerceIn(0.0,1.0)
                return target-1+fraction.toFloat()
            }
        }
    }
    // 남은 거리는 내비 안내 대상까지의 값이므로 표식이 그 장소를 향할 때만 쓴다.
    if(stops[target].key==drive.targetKey && drive.distanceMeters!=null && drive.legStartMeters?.let {it>0}==true)
        return (target-1+(1-drive.distanceMeters/drive.legStartMeters).toFloat()).coerceIn(target-1f,target.toFloat())
    return null
}
