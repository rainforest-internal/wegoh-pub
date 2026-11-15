package io.wegoh.app

import ai.pleos.playground.navi.helper.NaviHelper
import ai.pleos.playground.navi.helper.listener.NaviHelperEventListener
import ai.pleos.playground.navi.constants.NavigationStatus
import ai.pleos.playground.navi.constants.NaviMode
import ai.pleos.playground.navi.constants.NaviErrorCode
import ai.pleos.playground.navi.constants.WaypointIndex
import ai.pleos.playground.navi.data.*
import ai.pleos.playground.location.fused.FusedLocation
import ai.pleos.playground.location.fused.listener.FusedLocationListener
import ai.pleos.playground.location.fused.model.*
import android.car.Car
import android.car.drivingstate.CarUxRestrictionsManager
import android.content.Context
import android.os.Handler
import android.os.Looper

enum class NavigationPhase { IDLE, CONNECTING, SENT, SEARCHING, CALCULATED, OEM_GUIDANCE_REPORTED, ACTIVE, FAILED }

/** Provider observations remain distinct from verified ACTIVE and never own navigation. */
data class NavigationObservation(val status: NavigationStatus?=null,val mode: NaviMode?=null,
    val isRouting: Boolean?=null,val targetMatches: Boolean=false,val orderMatches: Boolean=false,
    val requestCurrent: Boolean=false) {
    val oemGuidanceReported get()=requestCurrent && targetMatches && orderMatches &&
        status==NavigationStatus.ROUTE_DRIVE && mode==NaviMode.ROUTE_GUIDING
    val activeFlagConflict get()=oemGuidanceReported && isRouting==false
}

/** Authoring coordinates are canonical. Stored vendor metadata is not a verified POI identity. */
internal fun coordinateRouteInfo(stop: Stop)=RouteInfo(latitude=stop.latitude,longitude=stop.longitude,
    displayLatitude=stop.latitude,displayLongitude=stop.longitude,poiName=stop.name,
    poiId="",address=stop.address,poiSubId="0")
internal fun coordinateWaypointInfo(stop: Stop,index: Int): RequestWaypointInfo {
    require(index in 0..1) {"경유지는 최대 2개입니다"}
    return RequestWaypointInfo(latitude=stop.latitude,
    longitude=stop.longitude,poiName=stop.name,poiId="",address=stop.address,poiSubId="0",
    waypointIndex=if(index==0)WaypointIndex.FIRST else WaypointIndex.SECOND)
}

/** Completed places are never requested again; selected course identity is retained. */
internal fun remainingNavigationPack(pack: DrivePack,completed: Set<String>): DrivePack? =
    pack.stops.filter {it.id !in completed}.takeIf {it.isNotEmpty()}?.let {pack.copy(stops=it)}

/** Current active OEM response only; no estimates or late-request fallback. */
internal fun verifiedNavigationReadback(pack: DrivePack,isRouting: Boolean,isCurrent: Boolean,
    target: DestinationInfo?,via: List<WaypointInfo>?,destinationAt: Long,waypointsAt: Long,
    traffic: TrafficStatus?=null,trafficAt: Long?=null): NavigationOverview? {
    if(!isCurrent || !isRouting || target==null || via==null)return null
    fun same(stop: Stop,latitude: Double,longitude: Double)=
        kotlin.math.abs(stop.latitude-latitude)<0.00001 && kotlin.math.abs(stop.longitude-longitude)<0.00001
    if(!same(pack.stops.last(),target.latitude,target.longitude) || via.size!=pack.stops.size-1 ||
        via.withIndex().any{!same(pack.stops[it.index],it.value.latitude,it.value.longitude)})return null
    val legs=via.mapIndexed {i,item->NavigationLeg(pack.stops[i].id,item.remainTime,item.remainDistance)}+
        NavigationLeg(pack.stops.last().id,target.remainTime,target.remainDistance)
    if(legs.any{it.cumulativeSeconds<0 || it.cumulativeMeters<0} || legs.zipWithNext().any{it.first.cumulativeSeconds>it.second.cumulativeSeconds || it.first.cumulativeMeters>it.second.cumulativeMeters})return null
    val sections=traffic?.congestionItemList.orEmpty().filter{it.offset.isFinite() && it.distance.isFinite() && it.offset>=0 && it.distance>0}
        .map{NavigationTraffic(it.offset,it.offset+it.distance,it.trafficCongestionType.name)}
    return NavigationOverview(pack.key,legs,minOf(destinationAt,waypointsAt),sections,trafficAt)
}

private enum class ReadbackTrigger { SEARCH, CALCULATED, ROUTE_STATUS, DRIVING, TBT }

class NavigationClient(context: Context, private val report: (String) -> Unit,
    private val overview: (NavigationOverview?)->Unit = {},
    private val canRequest: ()->Boolean = {true},
    private val onPhase: (NavigationPhase)->Unit = {},
    private val onObservation: (NavigationObservation?)->Unit = {}) {
    private val helper = NaviHelper(context.applicationContext)
    private val main = Handler(Looper.getMainLooper())
    private var initialized = false
    private var connected = false
    @Volatile private var closed = false
    @Volatile private var requested: DrivePack? = null
    @Volatile private var diagnosticEpoch=0L
    private val diagnosticSequence=java.util.concurrent.atomic.AtomicInteger()
    companion object {private val diagnosticEpochs=java.util.concurrent.atomic.AtomicLong()}
    private fun trace(event: String,details: String="") {
        if(BuildConfig.DEBUG)android.util.Log.d("WegoH-NaviTrace","epoch=$diagnosticEpoch seq=${diagnosticSequence.incrementAndGet()} elapsedMs=${android.os.SystemClock.elapsedRealtime()} event=$event closed=$closed $details")
    }
    private fun destinationMatches(value: DestinationInfo): Boolean = requested?.stops?.lastOrNull()?.let {kotlin.math.abs(it.latitude-value.latitude)<0.00001 && kotlin.math.abs(it.longitude-value.longitude)<0.00001} ?: false
    private fun waypointsMatch(values: List<WaypointInfo>): Boolean {
        val expected=requested?.stops?.dropLast(1) ?: return false
        return values.size==expected.size && values.indices.all {kotlin.math.abs(expected[it].latitude-values[it].latitude)<0.00001 && kotlin.math.abs(expected[it].longitude-values[it].longitude)<0.00001}
    }
    private var destination: DestinationInfo? = null
    private var waypoints: List<WaypointInfo>? = null
    private var traffic: TrafficStatus? = null
    private var trafficAt: Long? = null
    private var destinationAt = 0L
    private var waypointsAt = 0L
    private var queried = false
    private var routeActive=false
    private var routeStateReceived=false
    private var routeMode: NaviMode?=null
    private var navigationStatus: NavigationStatus?=null
    private var guidanceReported=false
    private var confirmed=false
    private var currentPhase=NavigationPhase.IDLE
    private val readbacks=mutableSetOf<ReadbackTrigger>()
    private fun phase(value: NavigationPhase) {
        if(closed)return
        if(currentPhase in setOf(NavigationPhase.ACTIVE,NavigationPhase.OEM_GUIDANCE_REPORTED) && value in setOf(NavigationPhase.SENT,NavigationPhase.SEARCHING,NavigationPhase.CALCULATED))return
        trace("PHASE","value=$value");currentPhase=value;onPhase(value)
    }
    private fun receive(event: String,details: String="",action: ()->Unit) {
        trace(event,details)
        if(Looper.myLooper()==Looper.getMainLooper()){if(!closed)action()}
        else main.post {if(!closed)action()}
    }
    private fun publishOverview() {
        if(closed)return
        val pack=requested ?: return
        val data=verifiedNavigationReadback(pack,routeActive,canRequest(),destination,waypoints,destinationAt,waypointsAt,traffic,trafficAt)
        val observed=NavigationObservation(navigationStatus,routeMode,if(routeStateReceived)routeActive else null,
            destination?.let {destinationMatches(it)} ?: false,waypoints?.let {waypointsMatch(it)} ?: false,canRequest())
        onObservation(observed)
        if(BuildConfig.DEBUG)android.util.Log.d("WegoH-Navi","READBACK active=$routeActive current=${canRequest()} destination=${destination!=null} waypoints=${waypoints?.size ?: -1} match=${data!=null}")
        overview(data)
        if(data==null && confirmed){confirmed=false;phase(NavigationPhase.IDLE)}
        if(data!=null && !confirmed) {
            confirmed=true;phase(NavigationPhase.ACTIVE);report("안내 시작 확인")
        } else if(data==null && observed.oemGuidanceReported && !guidanceReported) {
            guidanceReported=true;phase(NavigationPhase.OEM_GUIDANCE_REPORTED);report("내비 응답 수신")
        } else if(guidanceReported && !observed.oemGuidanceReported) {
            guidanceReported=false;if(!confirmed)phase(NavigationPhase.IDLE)
        }
    }
    private fun requestReadback(trigger: ReadbackTrigger) {
        // One batch per actual route/guidance event kind, never timer polling/re-entry.
        if(closed || confirmed || guidanceReported || requested==null || !canRequest() || !readbacks.add(trigger))return
        trace("GETTERS_BEGIN","trigger=$trigger")
        queried=true;routeActive=false;routeStateReceived=false;routeMode=null;destination=null
        waypoints=null // Even a zero-waypoint request requires the provider's explicit empty list.
        destinationAt=0;waypointsAt=0;traffic=null;trafficAt=null;overview(null)
        runCatching {helper.getDestinationInfo();helper.getWaypointInfo();helper.getRouteStateInfo()}
            .onFailure {overview(null);phase(NavigationPhase.FAILED);report("내비 오류")}
    }
    private val listener = object : NaviHelperEventListener {
        override fun onRouteStarted(routeStartInfo: RouteStartInfo) = receive("onRouteStarted") {
            if(closed)return@receive
            if(!confirmed && !guidanceReported){phase(NavigationPhase.SEARCHING);report("경로 탐색 시작")};requestReadback(ReadbackTrigger.SEARCH)
        }
        override fun onRoutingCompleted() = receive("onRoutingCompleted") {
            if(closed)return@receive
            phase(NavigationPhase.CALCULATED)
            if(!confirmed && !guidanceReported)report("경로 탐색 완료")
            requestReadback(ReadbackTrigger.CALCULATED)
        }
        override fun onDestinationInfo(destinationInfo: DestinationInfo) = receive("onDestinationInfo","expected=${requested!=null} destinationMatch=${destinationMatches(destinationInfo)}") {if(!closed && queried && canRequest()){destination=destinationInfo;destinationAt=android.os.SystemClock.elapsedRealtime();publishOverview()}}
        override fun onWayPointInfo(waypointInfoList: List<WaypointInfo>) = receive("onWayPointInfo","expected=${requested!=null} count=${waypointInfoList.size} orderMatch=${waypointsMatch(waypointInfoList)}") {if(!closed && queried && canRequest()){waypoints=waypointInfoList;waypointsAt=android.os.SystemClock.elapsedRealtime();publishOverview()}}
        override fun onRouteStateInfo(routeStateInfo: RouteStateInfo) = receive("onRouteStateInfo","mode=${routeStateInfo.naviMode.name} active=${routeStateInfo.isRouting}") {
            if(closed || !queried || !canRequest())return@receive
            routeActive=routeStateInfo.isRouting
            routeStateReceived=true
            routeMode=routeStateInfo.naviMode
            traffic=if(routeStateInfo.isRouting)routeStateInfo.trafficStatus else null
            trafficAt=if(traffic!=null)android.os.SystemClock.elapsedRealtime() else null
            if(!routeStateInfo.isRouting && confirmed){confirmed=false;phase(NavigationPhase.IDLE)}
            publishOverview()
        }
        override fun onNavigationStatus(status: NavigationStatus) = receive("onNavigationStatus","status=${status.name}") {
            if(closed)return@receive
            navigationStatus=status
            if(status==NavigationStatus.ROUTE_DRIVE){requestReadback(ReadbackTrigger.ROUTE_STATUS);publishOverview()}
            else {routeActive=false;routeMode=null;guidanceReported=false;confirmed=false;phase(NavigationPhase.IDLE);overview(null);publishOverview()}
        }
        override fun onDrivingInfo(drivingInfo: DrivingInfo)=receive("onDrivingInfo","positive=${drivingInfo.destination.duration>0 && drivingInfo.destination.distance>0}") {
            if(drivingInfo.destination.duration>0 && drivingInfo.destination.distance>0 && currentPhase in setOf(NavigationPhase.SEARCHING,NavigationPhase.CALCULATED))
                requestReadback(ReadbackTrigger.DRIVING)
        }
        override fun onTBTInfo(tbtInfoList: List<TBTInfo>)=receive("onTBTInfo","nonempty=${tbtInfoList.isNotEmpty()}") {
            if(tbtInfoList.isNotEmpty() && currentPhase in setOf(NavigationPhase.SEARCHING,NavigationPhase.CALCULATED))requestReadback(ReadbackTrigger.TBT)
        }
        override fun onDestinationChanged()=receive("onDestinationChanged") {if(!closed){routeActive=false;routeMode=null;navigationStatus=null;guidanceReported=false;phase(NavigationPhase.IDLE);confirmed=false;destination=null;waypoints=null;traffic=null;trafficAt=null;overview(null);onObservation(null)}}
        override fun onRouteCancelled()=receive("onRouteCancelled") {if(!closed){queried=false;routeActive=false;routeMode=null;navigationStatus=null;guidanceReported=false;confirmed=false;destination=null;waypoints=null;overview(null);onObservation(null);phase(NavigationPhase.IDLE)}}
        override fun onError(errorCode: NaviErrorCode) = receive("onError","code=${errorCode.name}") {if(!closed){requested=null;queried=false;guidanceReported=false;confirmed=false;onObservation(null);overview(null);phase(NavigationPhase.FAILED);report("내비 오류")}}
        override fun onDestinationArrived(destinationArrivedInfo: DestinationArrivedInfo) = receive("onDestinationArrived") {if(!closed)report("목적지 도착 확인")}
    }
    fun request(pack: DrivePack) {
        check(!closed) {"Create a new NavigationClient after release"}
        require(pack.stops.size in 1..3) {"방문 지점은 1~3개입니다"}
        diagnosticEpoch=diagnosticEpochs.incrementAndGet();trace("REQUEST","stopCount=${pack.stops.size}")
        requested=pack;queried=false;routeActive=false;routeStateReceived=false;routeMode=null;navigationStatus=null;guidanceReported=false;confirmed=false;readbacks.clear();phase(NavigationPhase.CONNECTING);destination=null;waypoints=null;traffic=null;trafficAt=null;overview(null);onObservation(null)
        if (!initialized) {
            initialized = true
            trace("INITIALIZE")
            helper.initialize(onConnected={main.post {
                trace("CONNECTED")
                if(closed)return@post
                runCatching {
                    helper.addListener(listener)
                    trace("LISTENER_REGISTERED")
                    connected=true
                    requested?.let {sendRoute(it)}
                }.onFailure {overview(null);phase(NavigationPhase.FAILED);report("내비 오류")}
            }},onFailed={main.post {
                trace("CONNECT_FAILED")
                if(!closed){overview(null);phase(NavigationPhase.FAILED);report("내비 오류")}
            }})
        } else if(connected)sendRoute(pack)
    }
    private fun sendRoute(pack: DrivePack) {
        if(closed || !canRequest()) {
            overview(null);phase(NavigationPhase.FAILED);report("내비 오류");return
        }
        trace("SEND_BEGIN")
        val last = pack.stops.last()
        val destination = coordinateRouteInfo(last)
        if (pack.stops.size == 1) helper.requestRoute(destination)
        else helper.requestRouteWithWaypoints(RouteWithWaypointsRequest(destination,
            pack.stops.dropLast(1).mapIndexed { index, stop ->
                coordinateWaypointInfo(stop,index)
            }))
        trace("SEND_RETURN")
        phase(NavigationPhase.SENT);report("경로 요청 전송 내비에서 안내를 시작하세요")
    }
    fun release() {
        trace("RELEASE")
        closed=true;connected=false
        requested=null;queried=false;routeActive=false;routeStateReceived=false;routeMode=null;navigationStatus=null;guidanceReported=false;confirmed=false;readbacks.clear();destination=null;waypoints=null;traffic=null;trafficAt=null;overview(null);onObservation(null)
        if (!initialized) return
        runCatching { helper.removeListener(listener) }
        runCatching { helper.release() }
        initialized = false
    }
}

class LocationClient(
    context: Context, private val update: (LocationData) -> Unit,
    private val report: (LocationUnavailableReason) -> Unit,
) {
    private val fused = FusedLocation(context.applicationContext)
    @Volatile private var initialized = false
    @Volatile private var closed=false
    private val listener = object : FusedLocationListener {
        override fun onChanged(location: LocationData?) {
            if(closed || !initialized)return
            if (location == null) report(LocationUnavailableReason.NO_DATA) else update(location)
        }
        override fun onError(exception: Exception) {if(!closed && initialized)report(LocationUnavailableReason.ERROR)}
    }
    fun start() {
        check(!closed){"Create a new LocationClient after release"}
        check(fused.isSupported()) {"이 환경은 Pleos 위치 서비스를 지원하지 않습니다"}
        initialized=true
        fused.initialize()
        fused.registerFusedLocationCallback(listener)
        fused.getLastKnownLocation(listener)
        // The ordered event engine uses these timestamped updates. No redundant proximity
        // registration is made: its asynchronous ID has no pending-cancellation API.
    }
    fun release() {
        closed=true
        if (!initialized) return
        initialized=false
        runCatching {fused.unregisterFusedLocationCallback(listener)}
        runCatching {fused.release()}
    }
}

/** Fail closed until the platform explicitly supplies a usable UX state.
 * `allowed` is the unrestricted (setup) state; `known` only says CarUx was actually read for this DO activity. */
class DrivingPolicy(context: Context, private val changed: (allowed: Boolean, known: Boolean, status: String) -> Unit): AutoCloseable {
    private var manager: CarUxRestrictionsManager? = null
    private var epoch=0
    private var closed=false
    private val car = Car.createCar(context.applicationContext, Handler(Looper.getMainLooper()),
        Car.CAR_WAIT_TIMEOUT_DO_NOT_WAIT) { vehicle, ready ->
        val token=++epoch
        if (!ready || closed) {
            runCatching {manager?.unregisterListener()}
            manager = null
            changed(false, false, "차량 연결 대기 설정 잠금")
        } else runCatching {
            val ux = vehicle.getCarManager(Car.CAR_UX_RESTRICTION_SERVICE) as CarUxRestrictionsManager
            manager = ux
            ux.registerListener { restriction ->
                if(!closed && token==epoch && manager===ux)
                    changed(!restriction.isRequiresDistractionOptimization, true, "주행 제한 상태 반영")
            }
            changed(!ux.currentCarUxRestrictions.isRequiresDistractionOptimization, true, "차량 상태 확인")
        }.onFailure {epoch++;runCatching {manager?.unregisterListener()};manager=null;changed(false, false, "차량 상태 확인 실패 설정 잠금") }
    }
    override fun close() {
        closed=true;epoch++
        runCatching {manager?.unregisterListener()};manager=null
        car.disconnect();changed(false,false,"차량 연결 종료")
    }
}
