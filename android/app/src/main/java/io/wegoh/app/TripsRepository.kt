package io.wegoh.app

import io.wegoh.app.nativeauth.*
import java.io.Closeable
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow

private const val TRIP_LOCATION_SYNC_FAILURE="위치 공유를 시작하지 못했어요. 다시 불러와 주세요"
private val TRIP_INVALIDATION_RESOURCES=setOf("devices","rooms","vehicle","friends","history")

data class TripRemotePolicySnapshot(val status: AccountReadStatus=AccountReadStatus.CONNECTION_REQUIRED,
    val tripId: String?=null,val tripTitle: String?=null,val policy: TripRemotePolicy?=null)

data class TripsPageState(val status: AccountReadStatus=AccountReadStatus.CONNECTION_REQUIRED,
    val list: TripList?=null,val selectedId: String?=null,val detail: TripDetail?=null,
    val isCurrent: Boolean=false,val busy: Boolean=false,val notice: String?=null,
    val gear: TripGear=TripGear.UNKNOWN,val driving: TripDrivingState=TripDrivingState(),
    val inviteFriends: List<TripInviteFriend>?=null,val inviteLink: TripInviteLink?=null,val signals: TripSignalState=TripSignalState(),
    val locationNotice: String?=null,val eventDriven: Boolean=false,
    val courseResults: Map<String,CourseDrivingResult> = emptyMap(),
    val liveCourseId: String?=null,val liveCourseScore: CourseDrivingResult?=null,
    val drivingVersus: TripDrivingVersus?=null,val drivingVersusLoading: Boolean=false,val drivingVersusNotice: String?=null,
    val remotePolicySnapshot: TripRemotePolicySnapshot=TripRemotePolicySnapshot(),val otherCars: List<TripCarPosition> = emptyList(),val carUxKnown: Boolean=false) {
    val canRespond get()=isCurrent && !busy && list!=null
    fun suspended(retain: Boolean)=if(retain)copy(isCurrent=false,busy=false,inviteLink=null,signals=TripSignalState(),
        remotePolicySnapshot=TripRemotePolicySnapshot(),otherCars=emptyList()) else TripsPageState(gear=gear,carUxKnown=carUxKnown)
}

/** `clear()` 진입 경로. 실기 로그에서 어느 경로가 화면을 비웠는지 구분한다. */
private enum class TripClearReason(val wire: String) {
    /** 연결 관찰 콜백이 같은 콜백 안에서 이어서 다시 읽는다. */
    ACCESS_INVALIDATED("access_invalidated"),
    /** 데이터 경계 만료는 연결 재확인이 다음 상태를 알린다. */
    EXPIRED("expired"),
    /** 현재 소셜 클라이언트의 기능 권한이 끝났다. 연결 단계는 그대로일 수 있다.
     * 같은 계정·연결 경계(canRetain)가 남아 있으면 비우지 않고 [TripsRepository.suspendForReload]로 다시 읽는다. */
    SOCIAL_INVALIDATED("social_invalidated"),
    /** 읽기 성공 뒤 데이터 경계를 기억하지 못했다. 이전 경계가 남아 있으면 새 응답만 버리고 다시 읽는다. */
    UNREMEMBERED("unremembered"),
    /** 손들기 읽기가 권한 없음으로 끝났다. */
    SIGNALS_DENIED("signals_denied"),
}

internal class TripsRepository(private val access: TripsRepositoryAccess,
    private val navigateTo: (TripRouteStop)->Boolean = {false},private val stopNavigation: ()->Unit = {},
    private val locateSignal: ((SignalLocation?)->Unit)->Closeable = {callback->callback(null);Closeable {}},
    private val log: (String)->Unit = {},private val observeRoute: (List<TripRouteStop>)->Unit = {},
    observeLocation: ((TripLocationFix)->Unit, (LocationUnavailableReason)->Unit)->Closeable = {_,_->Closeable {}},
    private val scores: CourseScores?=null,private val canScore: ()->Boolean = {true},private val canShareLocation: (()->Boolean)?=null): Closeable {
    constructor(connection: VehicleConnection,events: AccountEvents,navigateTo: (TripRouteStop)->Boolean = {false},
        stopNavigation: ()->Unit = {},locateSignal: ((SignalLocation?)->Unit)->Closeable = {callback->callback(null);Closeable {}},
        observeRoute: (List<TripRouteStop>)->Unit = {},
        observeLocation: ((TripLocationFix)->Unit, (LocationUnavailableReason)->Unit)->Closeable = {_,_->Closeable {}},scores: CourseScores?=null,canScore: ()->Boolean = {true},canShareLocation: (()->Boolean)?=null):
        this(NativeTripsRepositoryAccess(connection,events),navigateTo,stopNavigation,locateSignal,TripLoadDiagnostics::write,observeRoute,observeLocation,scores,canScore,canShareLocation)
    private val mutable=MutableStateFlow(TripsPageState())
    val states=mutable.asStateFlow()
    private val state get()=states.value
    private var client: TripsRepositoryClient?=null
    private var pending: Closeable?=null
    private var remotePolicyRead: Closeable?=null
    private var remotePolicySerial=0L
    private var remotePolicyWanted=false
    private var remotePolicyReading=false
    private var remotePolicyAgain=false
    private var signalRead: Closeable?=null
    private var responseRead: Closeable?=null
    private var responseReading=false
    private var responseGeneration=0L
    private val dismissedResponses=mutableSetOf<String>()
    private val acknowledgedResponses=mutableSetOf<String>()
    private var routeProgressWrite: Closeable?=null
    private var routeProgressWriting=false
    private var publishedRouteProgress: List<Any?>?=null
    private val scoreUploads=CourseScoreUploads()
    private val finalUploads=CourseFinalUploads()
    private var versusRead: Closeable?=null
    private var versusGeneration=0L
    private var versusAgain=false
    private var arrivalWrite: Closeable?=null
    private var arrivalSerial=0L
    private var suppressScoreReports=false
    private val drivingByTrip=mutableMapOf<String,TripDrivingState>()
    private var preferredDrivingTripId: String?=null
    private val routeRevisionsByTrip=mutableMapOf<String,Long>()
    private val routeNeedsNavigation=mutableSetOf<String>()
    private val locationDiagnostics=TripLocationDiagnostics(write=log)
    private val sectionQueue=linkedSetOf<String>()
    private var sectionRead: Closeable?=null
    private var sectionReading=false
    private var sectionGeneration=0L
    private fun refreshSection(section: String) {sectionQueue.add(section);drainSections()}
    private fun drainSections() {
        val detail=state.detail ?: return
        val api=client?.tripsApi ?: return
        if(closed || !foreground || !state.isCurrent || !access.canRetain() || state.busy || sectionReading || sectionQueue.isEmpty())return
        val section=sectionQueue.first();sectionQueue.remove(section);sectionReading=true
        val token=generation;val serial=++sectionGeneration
        sectionRead=api.readSection(detail,section) {reply->
            if(token!=generation || serial!=sectionGeneration || state.selectedId!=detail.id)return@readSection
            sectionReading=false
            reply.fold(onSuccess={updated->
                if(!access.remember()){suspendForReload(TripClearReason.UNREMEMBERED);return@readSection}
                val current=state.detail ?: return@readSection
                val staleRoute=section=="route" && (updated.routeContractVersion<current.routeContractVersion ||
                    updated.cars.any {route->current.cars.firstOrNull {it.id==route.id}?.let {before->
                        route.routeRevision<before.routeRevision || route.routePlan?.let {plan->before.routePlan?.let {previous->
                            plan.progressRevision<previous.progressRevision || previous.joinBarrier.released && !plan.joinBarrier.released
                        }}==true
                    }==true})
                if(state.busy || staleRoute || (updated.revision ?: 0)<(current.revision ?: 0)) {sectionQueue.add(section);drainSections();return@readSection}
                val merged=if(section=="location")current.copy(revision=updated.revision,locationSharing=updated.locationSharing,
                    display=current.display?.copy(companions=updated.display?.companions.orEmpty(),
                        companionsExpiresAtElapsedMillis=updated.display?.companionsExpiresAtElapsedMillis ?: 0) ?: updated.display)
                    else current.copy(revision=updated.revision,cars=current.cars.map {car->
                        updated.cars.firstOrNull {it.id==car.id}?.let {route->car.copy(places=route.places,
                            routeOrder=route.routeOrder,routeNext=route.routeNext,routeNextKnown=route.routeNextKnown,
                            routeRevision=route.routeRevision,routePlan=route.routePlan,routeStatus=route.routeStatus)} ?: car
                    },courses=updated.courses,routeContractVersion=updated.routeContractVersion)
                mutable.value=state.copy(detail=merged,driving=if(section=="route")restoreRouteProgress(merged,reconcileTripDriving(merged,state.driving)) else state.driving)
                if(section=="route")merged.myCar?.let {observeRoute(TripRouteOrder.resolve(TripRouteOrder.initial(merged,it),merged,it))}
                if(section=="route") {rememberDriving();clearCandidatesWhenUnavailable();readDrivingVersus()}
                syncLocation();drainSections()
            },onFailure={failed(it,"trip.$section.read")})
        }
    }
    private var displayRead: Closeable?=null
    private var displayReading=false
    private var signalWrite: Closeable?=null
    private var candidateRead: Closeable?=null
    private var signalLocation: Closeable?=null
    private var candidateGeneration=0L
    private var signalReading=false
    private var signalsAgain=false
    private val arrivals=mutableMapOf<String,MutableList<TripTimelineEntry>>()
    private val seenSignals=mutableSetOf<String>()
    private val resolvedSignals=mutableSetOf<String>()
    private var signalsInitialized=false
    private val locationPublisher=TripLocationPublisher(observeLocation,status={notice->mutable.value=state.copy(locationNotice=notice)})
    private val carLocations=TripCarLocations({cars->if(state.otherCars!=cars)mutable.value=state.copy(otherCars=cars)},access::schedule)
    private var locationPreferenceWrite: Closeable?=null
    private var locationPreferenceGeneration=0L
    private var locationPreferenceBusy=false
    private var locationPreferenceAttempted: String?=null
    private var locationPermissionAllowed: Boolean?=null
    private fun resetLocationPreference() {
        locationPreferenceGeneration++;locationPreferenceWrite?.close();locationPreferenceWrite=null
        locationPreferenceBusy=false;locationPreferenceAttempted=null
    }
    fun refreshLocationPermissions()=syncLocation()
    private fun syncLocation() {
        val permission=canShareLocation?.invoke()==true
        if(permission!=locationPermissionAllowed) {
            locationPublisher.close();locationPermissionAllowed=permission
            if(!permission)resetLocationPreference()
        }
        val trip=state.detail?.takeIf { !closed && foreground && state.isCurrent && access.canRetain() &&
            it.id==state.selectedId && it.state in setOf("planned","active") && it.me?.accepted==true }
        carLocations.update(trip?.takeIf {it.state=="active"}?.id,client?.tripsApi.takeIf {trip?.state=="active"})
        if(trip!=null && permission && !trip.locationSharing) {
            locationPublisher.close();enableLocationSharing(trip)
            return
        }
        if(trip?.locationSharing==true && !locationPreferenceBusy) {
            locationPreferenceAttempted=null
            if(state.notice==TRIP_LOCATION_SYNC_FAILURE)mutable.value=state.copy(notice=null,locationNotice=null)
        }
        val publishing=trip?.takeIf {permission && it.state=="active" && it.locationSharing}
        locationPublisher.update(publishing?.id,client?.tripsApi.takeIf {publishing!=null})
    }
    private fun enableLocationSharing(trip: TripDetail) {
        val api=client?.tripsApi ?: return
        if(locationPreferenceBusy || locationPreferenceAttempted==trip.id)return
        locationPreferenceBusy=true;locationPreferenceAttempted=trip.id
        val token=generation;val serial=++locationPreferenceGeneration
        val request=api.enableAutomaticLocationSharing(trip.id) {reply->
            if(token!=generation || serial!=locationPreferenceGeneration || state.selectedId!=trip.id ||
                !foreground || !state.isCurrent || !access.canRetain())return@enableAutomaticLocationSharing
            if(canShareLocation?.invoke()!=true) {
                resetLocationPreference();locationPublisher.close()
                return@enableAutomaticLocationSharing
            }
            locationPreferenceBusy=false;locationPreferenceWrite=null
            reply.fold(onSuccess={result->
                val current=state.detail ?: return@fold
                val revision=result.revision
                if(revision!=null && (current.revision==null || revision>=current.revision)) {
                    mutable.value=state.copy(detail=current.copy(locationSharing=true,revision=revision),locationNotice=null)
                    syncLocation()
                } else refreshSection("location")
            },onFailure={
                mutable.value=state.copy(locationNotice=TRIP_LOCATION_SYNC_FAILURE,notice=TRIP_LOCATION_SYNC_FAILURE)
            })
        }
        if(token==generation && serial==locationPreferenceGeneration && locationPreferenceBusy)locationPreferenceWrite=request else request.close()
    }
    private fun resetSignals(clearHistory: Boolean=true) {
        resetLocationPreference()
        versusGeneration++;versusRead?.close();versusRead=null;versusAgain=false
        if(state.drivingVersusLoading)mutable.value=state.copy(drivingVersusLoading=false)
        arrivalSerial++;arrivalWrite?.close();arrivalWrite=null
        finalUploads.cancel()
        sectionGeneration++;sectionRead?.close();sectionRead=null;sectionReading=false;sectionQueue.clear()
        responseGeneration++;responseRead?.close();responseRead=null;responseReading=false
        displayRead?.close();displayRead=null;displayReading=false
        signalRead?.close();signalRead=null;signalWrite?.close();signalWrite=null
        candidateRead?.close();candidateRead=null;signalLocation?.close();signalLocation=null
        candidateGeneration++;signalReading=false;signalsAgain=false
        if(clearHistory){seenSignals.clear();resolvedSignals.clear();signalsInitialized=false}
    }
    private var subscription: Closeable?=null
    private var generation=0L
    private var foreground=false
    private var allowed=false
    private var activated=false
    private var closed=false
    private var dirty=true
    private var detailRetried=false
    private var recovery: Closeable?=null
    private var recoveryAttempts=0
    private var invalidationReloads=0
    private var fineEvents=false
    private val observer=access.observe {
        if(access.invalidated())clear(TripClearReason.ACCESS_INVALIDATED)
        if(activated && foreground && (allowed || state.gear==TripGear.DRIVE) && access.connected && dirty && !state.busy)request()
    }
    init {access.onExpired={clear(TripClearReason.EXPIRED)}}
    private fun cancel() {withoutScoreReports {scores?.pause()};locationPublisher.close();carLocations.close();resetSignals(false);routeProgressWrite?.close();routeProgressWrite=null;routeProgressWriting=false;publishedRouteProgress=null;generation++;pending?.close();pending=null;remotePolicySerial++;remotePolicyRead?.close();remotePolicyRead=null;remotePolicyReading=false;remotePolicyAgain=false;if(state.remotePolicySnapshot.status==AccountReadStatus.LOADING)mutable.value=state.copy(remotePolicySnapshot=TripRemotePolicySnapshot());subscription?.close();subscription=null;client?.close();client=null}
    private fun stopRecovery() {recovery?.close();recovery=null;recoveryAttempts=0}
    /** 일시 장애(네트워크·5xx) 뒤 운전자가 누르지 않아도 다시 읽는다. 지수 백오프, 최대 횟수 뒤에는 "다시 불러오기"에 맡긴다. */
    private fun scheduleRecovery() {
        if(closed || !foreground || recovery!=null || recoveryAttempts>=TRANSIENT_RECOVERY_ATTEMPTS)return
        val delay=(TRANSIENT_RECOVERY_BASE_MILLIS shl recoveryAttempts).coerceAtMost(TRANSIENT_RECOVERY_MAX_MILLIS)
        recoveryAttempts++
        log("trip.recovery: retry scheduled attempt=$recoveryAttempts delayMs=$delay")
        recovery=access.schedule(delay) {
            recovery=null
            if(!closed && foreground && !state.isCurrent && !state.busy)request()
        }
    }
    /** 권한 스냅샷 교체(기능 권한 갱신·리모컨 받기 저장 등)로 클라이언트만 무효화되거나, 읽은 뒤 데이터 경계를 기억하지
     * 못하거나, 손들기 권한이 없어 비우면 연결 상태 알림이 오지 않아 다시 읽을 계기가 없다. 연결이 그대로면 바로 다시 읽고,
     * 성공 전 반복은 이 경로들이 함께 쓰는 횟수로 막는다. */
    private fun reloadAfterInvalidation() {
        if(closed || !activated)return
        if(invalidationReloads>=INVALIDATION_RELOAD_LIMIT) {
            log("trip.reload: skipped reason=limit")
            // 남겨 둔 화면은 운전자가 다시 불러올 수 있게 알린다.
            if(state.list!=null && !state.isCurrent && !state.busy)mutable.value=state.copy(notice="다시 불러와 주세요")
            return
        }
        invalidationReloads++
        log("trip.reload: after invalidation attempt=$invalidationReloads")
        access.post {if(!closed && foreground && (allowed || state.gear==TripGear.DRIVE) && access.connected && dirty && !state.busy)request()}
    }
    /** 클라이언트만 무효화됐을 때의 처리. 연결이 잠깐 unavailable이 되거나 권한 스냅샷이 교체되면 같은 계정·같은 기기라도
     * 소셜 클라이언트가 무효화된다. 이때 열린 여행·하위 화면까지 비우면 화면이 목록으로 튕기고 함께 듣기도 멈춘다.
     * 계정·연결 경계가 그대로면(canRetain) 백그라운드 전환과 같은 보존 규칙(suspended)으로 선택한 여행과 상세를 두고
     * 조작만 막은 채 그 자리에서 다시 읽는다. 계정 변경·연결 해제·만료는 canRetain이 거짓이 되어 지금처럼 비우고,
     * 기능 권한 철회는 다시 읽기가 CONSENT_REQUIRED·FORBIDDEN으로 끝나 [failed]가 비운다. */
    private fun suspendForReload(reason: TripClearReason) {
        if(!access.canRetain()) {clear(reason);reloadAfterInvalidation();return}
        log("trip.retain: reason=${reason.wire} connected=${access.connected} foreground=$foreground busy=${state.busy}")
        rememberDriving();cancel();dirty=true
        mutable.value=state.suspended(true)
        reloadAfterInvalidation()
    }
    /** 비운 경로를 진단 로그로 남긴다. 값·식별자는 기록하지 않는다. */
    private fun clear(reason: TripClearReason) {
        log("trip.clear: reason=${reason.wire} connected=${access.connected} foreground=$foreground busy=${state.busy}")
        clear()
    }
    private fun clear() {stopRecovery();cancel();resetSignals();finalUploads.clear();arrivals.clear();drivingByTrip.clear();preferredDrivingTripId=null;routeRevisionsByTrip.clear();routeNeedsNavigation.clear();dismissedResponses.clear();acknowledgedResponses.clear();access.forget();stopNavigation();dirty=true;mutable.value=TripsPageState(gear=state.gear,carUxKnown=state.carUxKnown)}
    fun setForeground(value: Boolean) {
        if(closed || foreground==value)return
        foreground=value
        if(!value) {stopRecovery();rememberDriving();cancel();dirty=true;mutable.value=state.suspended(access.canRetain())}
        else access.post {
            if(!closed && activated && foreground && (allowed || state.gear==TripGear.DRIVE))request()
        }
    }
    fun setSetupAllowed(value: Boolean) {
        if(closed || allowed==value)return
        allowed=value
        if(!state.canUseSignalControls(allowed))clearSignalCandidates()
        if(activated && foreground)request()
    }
    /** CarUx was actually read for this DO activity. Driving hand-raise and replies need it; unknown fails closed. */
    fun setCarUxKnown(value: Boolean) {
        if(closed || state.carUxKnown==value)return
        mutable.value=state.copy(carUxKnown=value)
        if(!state.canUseSignalControls(allowed))clearSignalCandidates()
    }
    fun request(force: Boolean=false) {
        if(closed || !foreground)return
        activated=true
        if(force){resetLocationPreference();locationPublisher.close();carLocations.close();finalUploads.retryFailures();dirty=true}
        if(!access.connected || state.busy)return
        if(state.isCurrent && !dirty)return
        if(client?.ready==true && access.canRetain()) {refreshData();return}
        cancel();val token=generation
        mutable.value=state.copy(status=if(state.list==null)AccountReadStatus.LOADING else AccountReadStatus.READY,
            busy=true,isCurrent=false,notice=null)
        val social=access.client();client=social
        social.open(object: NativeSocialObserver {
            override fun onInvalidated() {if(token==generation)suspendForReload(TripClearReason.SOCIAL_INVALIDATED)}
            override fun onConnectionLost() {if(token==generation)failed(NativeSocialFailure(NativeSocialFailure.Kind.UNAVAILABLE),"trip.events")}
        }) {result->
            if(token!=generation || closed)return@open
            result.fold(onSuccess={
                val opened=access.subscribe(object: VehicleEventsListener {
                    override fun onOpen() {
                        if(token!=generation)return
                        readList()
                    }
                    override fun onEvent(event: VehicleEvent) {
                        if(token!=generation)return
                        if(event.versions!=null){fineEvents=true;mutable.value=state.copy(eventDriven=true)}
                        if(event.type!="invalidate")return
                        val id=state.selectedId
                        val relevant=event.resources.toSet()
                        if(remotePolicyWanted && relevant.any {it in TRIP_INVALIDATION_RESOURCES || Regex("trip\\.[a-f0-9]{32}\\.(detail|route)").matches(it)})
                            refreshRemotePolicy()
                        if(event.versions!=null) {
                            if(relevant.any {it in setOf("devices","rooms","friends") || it=="trip.$id.detail"}) {
                                dirty=true;if(!state.busy)request()
                            } else {
                                if("trip.$id.route" in relevant || "courses" in relevant)refreshSection("route")
                                if("trip.$id.location" in relevant)refreshSection("location")
                                // v2 경로의 차별 실시간 진행(routePlan·routeStatus.progress)은 위치 공유 좌표로 계산되므로 위치가 바뀌면 경로 영역도 다시 읽는다.
                                if("trip.$id.location" in relevant && state.detail?.let {it.routeContractVersion==2 && it.state=="active"}==true)refreshSection("route")
                            }
                            val signals=relevant.mapNotNull {Regex("trip\\.([a-f0-9]{32})\\.signals").matchEntire(it)?.groupValues?.get(1)}.toSet()
                            if(signals.isNotEmpty())refreshSignals(signals)
                        } else if(relevant.any {it in TRIP_INVALIDATION_RESOURCES}) {
                            dirty=true;if(!state.busy)request();refreshSignals()
                        }
                    }
                    override fun onUnavailable() {if(token==generation)failed(NativeSocialFailure(NativeSocialFailure.Kind.UNAVAILABLE),"trip.events")}
                    override fun onClosed()=onUnavailable()
                })
                if(token==generation)subscription=opened else opened.close()
            },onFailure=::failed)
        }
    }
    private fun refreshData() {
        val selected=state.selectedId
        if(selected!=null)readDetail(selected) else readList()
    }
    private fun refreshIfDirty() {if(dirty && !state.busy)request() else drainSections()}
    private fun readList() {
        val social=client ?: return
        val token=generation;dirty=false;mutable.value=state.copy(busy=true)
        pending=social.tripsApi.readList {reply->
            if(token!=generation || closed)return@readList
            reply.fold(onSuccess={list->
                if(!access.remember()){suspendForReload(TripClearReason.UNREMEMBERED);return@readList}
                val selected=state.selectedId?.takeIf {id->list.trips.any {it.id==id}}
                recoveryAttempts=0;invalidationReloads=0
                mutable.value=state.copy(status=AccountReadStatus.READY,list=list,selectedId=selected,
                    detail=state.detail.takeIf {selected!=null},isCurrent=true,busy=false,notice=null,
                    driving=if(selected!=null)state.driving else TripDrivingState())
                if(remotePolicyWanted)readRemotePolicy()
                if(selected!=null)readDetail(selected) else {locationPublisher.close();carLocations.close();ensureDrivingTrip();refreshIfDirty()}
            },onFailure=::failed)
        }
    }
    private fun failed(error: Throwable)=failed(error,if(state.selectedId==null)"trip.list" else "trip.detail")
    private fun failed(error: Throwable,scope: String) {
        locationPublisher.close();carLocations.close()
        log(TripLoadDiagnostics.message(scope,error,state.selectedId))
        TripLoadDiagnostics.recordFailure(scope,error)
        if(client?.ready!=true)mutable.value=state.copy(signals=state.signals.copy(
            ending=false,sending=false,hint=if(state.signals.sending)"보내지 못했어요. 다시 눌러 주세요" else state.signals.hint,
            voting=false,result=if(state.signals.voting)"답을 보내지 못했어요. 다시 눌러 주세요" else state.signals.result))
        val failure=error as? NativeSocialFailure
        val id=state.selectedId
        if(!closed && foreground && id!=null && failure?.kind==NativeSocialFailure.Kind.UNAVAILABLE && (failure.httpStatus ?: 0)==0) {
            if(!detailRetried) {
                detailRetried=true
                log("trip.detail: retry started reason=unavailable attempt=1")
                mutable.value=state.copy(isCurrent=false,busy=false)
                if(client?.ready==true)readDetail(id)
                else {cancel();dirty=true;request(true)}
                return
            }
            if(client?.ready==true && state.detail!=null && access.canRetain()) {
                dirty=false
                mutable.value=state.copy(isCurrent=false,busy=false,notice="다시 불러와 주세요")
                scheduleRecovery()
                return
            }
        }
        cancel();dirty=true
        val prepare=(error as? NativeSocialFailure)?.kind in setOf(NativeSocialFailure.Kind.CONSENT_REQUIRED,
            NativeSocialFailure.Kind.NOT_FOUND,NativeSocialFailure.Kind.FORBIDDEN,NativeSocialFailure.Kind.AUTHORIZATION_REQUIRED)
        mutable.value=if(!prepare && access.canRetain())state.copy(isCurrent=false,busy=false,notice="다시 불러와 주세요")
            else TripsPageState(if(prepare)AccountReadStatus.PERMISSION_REQUIRED else AccountReadStatus.UNAVAILABLE,gear=state.gear,carUxKnown=state.carUxKnown).also {
                stopNavigation();access.forget()
            }
        if(transientTripFailure(error))scheduleRecovery()
    }
    fun select(id: String) {
        if(!foreground || !allowed || !state.isCurrent || state.busy || state.list?.trips?.none {it.id==id}!=false)return
        rememberDriving();scores?.pause();locationPublisher.close();carLocations.close()
        stopNavigation();resetSignals();detailRetried=false
        mutable.value=state.copy(signals=retainedResponse(),selectedId=id,detail=null,notice=null,driving=drivingByTrip[id] ?: TripDrivingState(),inviteFriends=null,inviteLink=null,courseResults=emptyMap(),liveCourseId=null,liveCourseScore=null,drivingVersus=null,drivingVersusLoading=false,drivingVersusNotice=null)
        readDetail(id)
    }
    private fun readDetail(id: String) {
        val social=client ?: return
        val token=generation;dirty=false;mutable.value=state.copy(busy=true)
        pending=social.tripsApi.readDetail(id) {reply->
            if(token!=generation || state.selectedId!=id)return@readDetail
            reply.fold(onSuccess={received->
                val detail=withArrivals(received)
                if(!access.remember()){suspendForReload(TripClearReason.UNREMEMBERED);return@readDetail}
                if(detail.state=="active")preferredDrivingTripId=detail.id
                detailRetried=false;recoveryAttempts=0;invalidationReloads=0
                mutable.value=state.copy(detail=detail,busy=false,isCurrent=true,notice=null,driving=restoreRouteProgress(detail,reconcileTripDriving(detail,state.driving)),
                    inviteFriends=state.inviteFriends.takeIf {detail.canInvite},inviteLink=state.inviteLink.takeIf {detail.canInvite},
                    list=state.list?.let {list->list.copy(trips=list.trips.map {
                    if(it.id==id)it.copy(title=detail.title,state=detail.state,startDate=detail.startDate,endDate=detail.endDate,
                        ownerName=detail.members.firstOrNull {member->member.isOwner}?.name ?: it.ownerName,
                        myRole=detail.myRole,carCount=detail.cars.size,memberCount=detail.members.count {member->member.accepted}) else it
                })})
                if(remotePolicyWanted)readRemotePolicy()
                if(detail.state!="active" || detail.myCar?.isMine!=true)stopNavigation()
                else detail.myCar?.let {observeRoute(TripRouteOrder.resolve(TripRouteOrder.initial(detail,it),detail,it))}
                syncLocation()
                rememberDriving();publishRouteProgress();clearCandidatesWhenUnavailable()
                if(detail.routeContractVersion==2)readDrivingVersus()
                refreshIfDirty()
                ensureDrivingTrip()
            },onFailure={error->
                if((error as? NativeSocialFailure)?.kind==NativeSocialFailure.Kind.NOT_FOUND) {
                    log(TripLoadDiagnostics.message("trip.detail",error,id))
                    stopNavigation()
                    mutable.value=state.copy(selectedId=null,detail=null,busy=false,driving=TripDrivingState(),inviteFriends=null,inviteLink=null);request(true)
                } else failed(error)
            })
        }
    }
    fun closeDetail() {
        if(state.selectedId==null)return
        rememberDriving();scores?.pause();val response=retainedResponse();locationPublisher.close();carLocations.close()
        pending?.close();pending=null
        resetSignals();stopNavigation()
        mutable.value=state.copy(selectedId=null,detail=null,busy=false,notice=null,signals=response,driving=TripDrivingState(),inviteFriends=null,inviteLink=null,courseResults=emptyMap(),liveCourseId=null,liveCourseScore=null,drivingVersus=null,drivingVersusLoading=false,drivingVersusNotice=null)
    }
    fun refreshRemotePolicy() {
        if(closed || !foreground)return
        remotePolicyWanted=true
        if(client?.ready==true && state.isCurrent && access.canRetain())readRemotePolicy() else request()
    }
    private fun readRemotePolicy() {
        val api=client?.tripsApi ?: return
        if(closed || !foreground || client?.ready!=true || !state.isCurrent || !access.canRetain())return
        if(remotePolicyReading){remotePolicyAgain=true;return}
        val token=generation;val serial=++remotePolicySerial
        remotePolicyReading=true;remotePolicyAgain=false
        mutable.value=state.copy(remotePolicySnapshot=TripRemotePolicySnapshot(AccountReadStatus.LOADING))
        fun owned()=token==generation && serial==remotePolicySerial
        fun current()=owned() && !closed && foreground && state.isCurrent && client?.ready==true && access.canRetain()
        fun finish(snapshot: TripRemotePolicySnapshot) {
            remotePolicyReading=false
            mutable.value=state.copy(remotePolicySnapshot=snapshot)
            if(remotePolicyAgain)readRemotePolicy()
        }
        // 세대가 바뀐 읽기는 cancel()이 이미 정리했다. 세대는 같은데 현재성·연결·보존 조건만 잃은 읽기는 여기서 버리고
        // 읽는 중 표시를 풀어야 다음 읽기가 막히지 않는다. 결과를 보일 수 없으니 확인 중이 아닌 기본 상태로 돌린다.
        fun dropped(): Boolean {
            if(current())return false
            if(owned())finish(TripRemotePolicySnapshot())
            return true
        }
        remotePolicyRead=api.readList {reply->
            if(dropped())return@readList
            val list=reply.getOrNull()
            if(list==null) {finish(TripRemotePolicySnapshot(AccountReadStatus.UNAVAILABLE));return@readList}
            val active=list.trips.filter {it.state=="active"}.map {it.id}
            fun inspect(index: Int) {
                if(dropped())return
                if(index==active.size){finish(TripRemotePolicySnapshot(AccountReadStatus.READY));return}
                remotePolicyRead=api.readDetail(active[index]) {detailReply->
                    if(dropped())return@readDetail
                    val detail=detailReply.getOrNull()
                    if(detail==null){finish(TripRemotePolicySnapshot(AccountReadStatus.UNAVAILABLE));return@readDetail}
                    val car=detail.myCar?.takeIf {it.isMine}
                    if(detail.state=="active" && car!=null)
                        finish(TripRemotePolicySnapshot(AccountReadStatus.READY,detail.id,detail.title,car.remotePolicy))
                    else inspect(index+1)
                }
            }
            inspect(0)
        }
    }
    fun respond(id: String,accept: Boolean,@Suppress("UNUSED_PARAMETER") locationConsent: Boolean?) {
        if(!foreground || !allowed || !state.canRespond || state.list?.invitations?.none {it.tripId==id}!=false)return
        val social=client ?: return
        val token=generation;mutable.value=state.copy(busy=true,notice=null)
        pending=social.tripsApi.respond(id,accept,if(accept)true else null) {reply->
            if(token!=generation)return@respond
            reply.fold(onSuccess={mutable.value=state.copy(busy=false);request(true)},onFailure=::failed)
        }
    }
    fun setGear(gear: TripGear) {
        if(state.gear==gear)return
        mutable.value=state.copy(gear=gear)
        if(!state.canUseSignalControls(allowed))clearSignalCandidates()
        if(gear==TripGear.DRIVE && foreground && !state.isCurrent && !state.busy)request()
        ensureDrivingTrip();syncScores()
    }
    private fun ensureDrivingTrip() {
        if(closed || !foreground || state.gear!=TripGear.DRIVE || !state.isCurrent || state.busy)return
        if(state.detail?.state=="active")return
        val active=state.list?.trips.orEmpty().filter {it.state=="active"}
        val id=(active.firstOrNull {it.id==preferredDrivingTripId} ?: active.firstOrNull())?.id ?: return
        if(state.selectedId==id && state.detail!=null)return
        rememberDriving();scores?.pause();stopNavigation();resetSignals()
        mutable.value=state.copy(selectedId=id,detail=null,driving=drivingByTrip[id] ?: TripDrivingState(),courseResults=emptyMap(),liveCourseId=null,liveCourseScore=null,drivingVersus=null,drivingVersusLoading=false,drivingVersusNotice=null)
        readDetail(id)
    }
    fun clearLink() {mutable.value=state.copy(inviteLink=null)}
    fun readInviteFriends() {
        val trip=state.detail ?: return
        if(!canMutate() || !trip.canInvite)return
        val api=client?.tripsApi ?: return
        val token=generation;mutable.value=state.copy(busy=true,notice=null)
        pending=api.readInviteFriends(trip.id) {reply->
            if(token!=generation || state.selectedId!=trip.id)return@readInviteFriends
            reply.fold(onSuccess={mutable.value=state.copy(inviteFriends=it,busy=false);refreshIfDirty()},onFailure=::mutationFailed)
        }
    }
    private fun canMutate()=!closed && foreground && allowed && state.isCurrent && !state.busy && state.detail!=null
    private fun mutationFailed(error: Throwable) {
        val failure=error as? NativeSocialFailure
        val kind=failure?.kind
        if(kind in setOf(NativeSocialFailure.Kind.AUTHORIZATION_REQUIRED,NativeSocialFailure.Kind.FORBIDDEN)) {failed(error);return}
        dirty=true
        mutable.value=state.copy(busy=false,isCurrent=false,notice=if(kind==NativeSocialFailure.Kind.CONFLICT)when(failure?.serverErrorCode) {
            "TRIP_ALREADY_ACTIVE"->"다른 여행에 참여 중이에요. 다시 불러와 주세요"
            "TRIP_MEMBER_ALREADY_ACTIVE"->"일행이 다른 여행에 참여 중이에요. 다시 불러와 주세요"
            else->"내용이 바뀌었어요. 다시 불러와 주세요"
        } else "저장 결과를 확인하지 못했어요. 다시 불러와 주세요")
    }
    fun perform(action: TripAction,onSuccess: ()->Unit) {
        val trip=state.detail ?: return
        if(!canMutate() || !canPerformTripAction(trip,action))return
        if(runCatching {TripActionCodec.request(action)}.isFailure) {
            mutable.value=state.copy(notice="입력한 내용을 확인해 주세요");return
        }
        val api=client?.tripsApi ?: return
        if(action is TripAction.SetLocationSharing || action is TripAction.Finish){locationPublisher.close();carLocations.close()}
        val token=generation;mutable.value=state.copy(busy=true,notice=null)
        pending=api.perform(trip.id,action) {reply->
            if(token!=generation || state.selectedId!=trip.id)return@perform
            reply.fold(onSuccess={result->
                mutable.value=state.copy(busy=false,inviteLink=when(action) {
                    TripAction.CreateLink->result.link;TripAction.RevokeLink->null;else->state.inviteLink
                },inviteFriends=state.inviteFriends?.map {friend->when {
                    action is TripAction.Invite && friend.id==action.accountId->friend.copy(state="pending")
                    action is TripAction.RemoveMember && friend.id==action.accountId->friend.copy(state="none")
                    else->friend
                }})
                if(action is TripAction.SetLocationSharing && result.revision!=null) {
                    mutable.value=state.copy(detail=state.detail?.copy(locationSharing=action.enabled,revision=result.revision))
                    syncLocation();refreshIfDirty()
                } else readDetail(trip.id)
                onSuccess()
            },onFailure=::mutationFailed)
        }
    }
    fun saveOrder(items: List<TripRouteItem>,expectedRouteRevision: Long,onSuccess: ()->Unit) {
        val trip=state.detail ?: return
        val car=trip.myCar?.takeIf {it.isMine} ?: return
        val segmented=trip.state=="planned" || trip.routeContractVersion==2
        if(!canMutate() || state.gear!=TripGear.PARK || trip.routeContractVersion==2 && trip.state!="planned" ||
            !(if(segmented)TripRouteOrder.preservesSegments(items,trip) else TripRouteOrder.preservesCourses(items,trip)))return
        if(expectedRouteRevision!=car.routeRevision) {
            mutable.value=state.copy(notice="경로가 바뀌었어요. 다시 불러와 저장해 주세요");return
        }
        if(runCatching {NativeTripsCodec.routeBody(items)}.isFailure) {
            mutable.value=state.copy(notice="경로를 확인해 주세요");return
        }
        val api=client?.tripsApi ?: return
        val token=generation;mutable.value=state.copy(busy=true,notice=null)
        pending=api.saveRouteOrder(trip.id,car.id,expectedRouteRevision,items,if(segmented)2 else 1) {reply->
            if(token!=generation || state.selectedId!=trip.id)return@saveRouteOrder
            reply.fold(onSuccess={mutable.value=state.copy(busy=false);readDetail(trip.id);onSuccess()},onFailure=::mutationFailed)
        }
    }
    fun navigate(stop: TripRouteStop) {
        val trip=state.detail ?: return
        val car=trip.myCar?.takeIf {it.isMine} ?: return
        val stops=TripRouteOrder.resolve(TripRouteOrder.initial(trip,car),trip,car)
        if(!canMutate() || trip.state!="active" || !stop.canNavigate || state.driving.phase==TripDrivingPhase.ROUTE_END ||
            stops.none {it.key==stop.key} || stop.key in state.driving.arrived)return
        val passed=if(trip.routeContractVersion==2)emptyList() else stops.takeWhile {it.key!=stop.key}.map {it.key}.filter {it !in state.driving.arrived}
        if(navigateTo(stop)) {
            routeNeedsNavigation.remove(trip.id)
            mutable.value=state.copy(driving=state.driving.copy(skipped=state.driving.skipped+passed-stop.key).navigate(stop),notice=null)
            rememberDriving();publishRouteProgress()
        }
        else mutable.value=state.copy(notice="길 안내를 시작할 수 없어요. 위치 권한과 동의를 확인해 주세요")
    }
    fun distance(meters: Double) {
        if(!closed && foreground && state.detail?.state=="active" && access.canRetain())
            mutable.value=state.copy(driving=state.driving.distance(meters))
        rememberDriving();publishRouteProgress()
    }
    fun navigationUpdate(update: TripNavigationUpdate) {
        fun drop(reason: String) {update.position?.let {locationDiagnostics.dropped(reason,it,"stage=trip")}}
        val trip=state.detail ?: return drop("no_trip")
        val car=trip.myCar?.takeIf {it.isMine} ?: return drop("not_my_car")
        if(closed || !foreground || trip.state!="active" || !access.canRetain())return drop(when {
            closed->"closed";!foreground->"background";trip.state!="active"->"trip_${trip.state}";else->"not_retained"})
        if(trip.id in routeNeedsNavigation)return drop("route_needs_navigation")
        val stops=TripRouteOrder.resolve(TripRouteOrder.initial(trip,car),trip,car)
        mutable.value=state.copy(driving=applyTripNavigation(stops,state.driving,update,localProgress=trip.routeContractVersion!=2))
        rememberDriving();publishRouteProgress()
    }
    fun navigationFailed() {scores?.pause();mutable.value=state.copy(notice="길 안내를 시작할 수 없어요",driving=state.driving.copy(phase=TripDrivingPhase.LATER,targetKey=null))}
    private fun withArrivals(detail: TripDetail): TripDetail {
        val confirmed=arrivals[detail.id].orEmpty()
        if(confirmed.isEmpty())return detail
        val server=detail.display
        val display=server ?: TripDisplay(emptyList(),null,null,null,emptyList())
        return detail.copy(display=display.copy(
            timeline=(display.timeline+confirmed).distinctBy {it.id}.sortedBy {it.at},
            visitCount=if(display.timeline.any {it.kind=="방문 기록" && !it.id.startsWith("local:")})null else confirmed.size))
    }
    fun arrive() {
        val trip=state.detail ?: return
        val car=trip.myCar?.takeIf {it.isMine} ?: return
        if(!canMutate() || trip.state!="active" || !access.canRetain())return
        if(trip.routeContractVersion==2) {arriveAtSegment(trip,car);return}
        val stops=TripRouteOrder.resolve(TripRouteOrder.initial(trip,car),trip,car)
        val next=tripArriveAtStop(stops,state.driving)
        val confirmed=next.arrived-state.driving.arrived
        stops.filter {it.key in confirmed}.forEach {stop->
            val rows=arrivals.getOrPut(trip.id) {mutableListOf()}
            if(rows.none {it.id=="local:${stop.key}"})rows.add(TripTimelineEntry("local:${stop.key}",stop.name,
                when(stop.item.type){"pickup"->"타는 곳 도착";"drop"->"내리는 곳 도착";else->"도착 확인"},java.time.Instant.now().toString()))
        }
        mutable.value=state.copy(driving=next,detail=withArrivals(trip))
        rememberDriving();publishRouteProgress()
    }
    private fun arriveAtSegment(trip: TripDetail,car: TripCar) {
        val plan=car.routePlan ?: return
        val item=plan.next ?: return
        if(state.gear!=TripGear.PARK || plan.phase !in setOf("pickup","shared","drop") && !(plan.phase=="waiting" && item.type=="signal"))return
        val api=client?.tripsApi ?: return
        val singleJoin=plan.singleJoinCourseItem==item
        val token=generation;val operation=++arrivalSerial
        mutable.value=state.copy(busy=true,notice=null)
        arrivalWrite=api.routeArrival(trip.id,car.id,car.routeRevision,plan.progressRevision,item,singleJoin) {reply->
            if(token!=generation || operation!=arrivalSerial || state.selectedId!=trip.id)return@routeArrival
            arrivalWrite=null
            reply.fold(onSuccess={updated->
                val current=state.detail ?: return@fold
                val merged=current.copy(cars=current.cars.map {if(it.id==car.id)it.copy(routePlan=updated,
                    routeStatus=TripRouteStatus(updated.phase,updated.joinEtaSeconds)) else it})
                mutable.value=state.copy(busy=false,detail=merged,driving=restoreRouteProgress(merged,state.driving))
                clearCandidatesWhenUnavailable();rememberDriving();publishRouteProgress()
                readDetail(trip.id)
            },onFailure={error->
                val conflict=(error as? NativeSocialFailure)?.kind==NativeSocialFailure.Kind.CONFLICT
                mutable.value=state.copy(busy=false,notice=tripArrivalFailureNotice(error))
                if(conflict)readDetail(trip.id)
            })
        }
    }
    fun refreshDrivingVersus() {
        finalUploads.retryFailures()
        state.detail?.let(::syncFinalScores)
        readDrivingVersus()
    }
    private fun readDrivingVersus() {
        val trip=state.detail ?: return
        val api=client?.tripsApi ?: return
        if(closed || !foreground || !state.isCurrent || !access.canRetain())return
        if(state.drivingVersusLoading) {versusAgain=true;return}
        versusAgain=false
        val token=generation;val operation=++versusGeneration
        mutable.value=state.copy(drivingVersusLoading=true,drivingVersusNotice=null)
        versusRead=api.readDrivingVersus(trip.id) {reply->
            if(token!=generation || operation!=versusGeneration || state.selectedId!=trip.id)return@readDrivingVersus
            versusRead=null
            mutable.value=state.copy(drivingVersusLoading=false,drivingVersus=reply.getOrNull(),
                drivingVersusNotice=if(reply.isFailure)"대결 결과를 불러오지 못했어요. 다시 확인해 주세요" else null)
            if(versusAgain)readDrivingVersus()
        }
    }
    private fun syncFinalScores(trip: TripDetail) {
        val car=trip.myCar?.takeIf {it.isMine} ?: return
        val authority=access.scoreReportAuthority ?: return
        val api=client?.tripsApi?.takeIf {client?.ready==true} ?: return
        if(trip.routeContractVersion!=2 || suppressScoreReports || closed || !foreground || !state.isCurrent || !access.canRetain())return
        syncTotalFinalScore(trip,car,authority,api)
    }
    private fun clearCandidatesWhenUnavailable() {
        if(state.detail?.let {it.state!="active" || it.myCar?.routePlan?.phase=="done"}==true)
            clearSignalCandidates()
    }
    fun later() {if(canMutate()){mutable.value=state.copy(driving=state.driving.later());rememberDriving();publishRouteProgress()}}
    private fun scoreKey(trip: TripDetail,course: String): String? {
        val namespace=access.scoreNamespace ?: return null
        val car=trip.myCar?.takeIf {it.isMine} ?: return null
        if(course=="trip-total-v1")return courseScoreKey("trip-total-v1",namespace,trip.id,car.id)
        val version= trip.courses.orEmpty().firstOrNull {it.packId==course}?.version?.toString().orEmpty()
        return courseScoreKey(namespace,trip.id,car.id,course,version)
    }
    private fun syncScores() {
        val trip=state.detail
        val car=trip?.myCar?.takeIf {it.isMine}
        if(trip==null || car==null || !foreground || !access.canRetain()) {scores?.pause();return}
        syncFinalScores(trip)
        if(trip.routeContractVersion==2) {syncTotalScore(trip,car);return}
        val results=trip.courses.orEmpty().mapNotNull {course->
            val key=scoreKey(trip,course.packId) ?: return@mapNotNull null
            val result=scores?.read(key) ?: return@mapNotNull null
            if(car.id in course.completedCarIds.orEmpty())course.packId to
                (if(result.completed)result else scores?.finish(key) ?: result) else null
        }.toMap()
        if(results!=state.courseResults)mutable.value=state.copy(courseResults=results)
        val stops=TripRouteOrder.resolve(TripRouteOrder.initial(trip,car),trip,car)
        val target=stops.firstOrNull {it.key==state.driving.targetKey} ?: if(state.gear==TripGear.DRIVE)tripNextStop(stops,state.driving) else null
        val course=if(trip.routeContractVersion==2)car.routePlan?.takeIf {it.phase=="shared"}?.next?.courseId
            else target?.let {tripStopCourse(it,stops)}
        if(trip.state=="active" && state.isCurrent && canScore() && course!=null &&
            (state.driving.phase in setOf(TripDrivingPhase.FAR,TripDrivingPhase.NEAR,TripDrivingPhase.ARRIVED,TripDrivingPhase.ROUTE_END) ||
                state.gear==TripGear.DRIVE && state.driving.phase==TripDrivingPhase.LATER) &&
            trip.courses.orEmpty().none {it.packId==course && car.id in it.completedCarIds.orEmpty()})
            scoreKey(trip,course)?.let {
                if(state.liveCourseId!=course)mutable.value=state.copy(liveCourseId=course,liveCourseScore=null)
                scores?.start(it)
                val result=scores?.read(it)
                if(result!=state.liveCourseScore)mutable.value=state.copy(liveCourseScore=result)
                publishScore(trip,course,it,result ?: CourseDrivingResult())
            }
        else if(trip.routeContractVersion==2 && car.routePlan?.phase!="shared" || !canScore() || !state.isCurrent || trip.state!="active" || target?.item?.type!="signal")scores?.pause()
    }
    private fun syncTotalScore(trip: TripDetail,car: TripCar) {
        val key=scoreKey(trip,"trip-total-v1") ?: return
        if(trip.state=="active" && car.routePlan?.phase!="done" && state.isCurrent && canScore()) {
            if(state.liveCourseId!="trip-total-v1")mutable.value=state.copy(liveCourseId="trip-total-v1",liveCourseScore=null,courseResults=emptyMap())
            scores?.start(key)
            val result=scores?.read(key) ?: CourseDrivingResult()
            mutable.value=state.copy(liveCourseScore=result)
            publishScore(trip,"trip-total-v1",key,result)
        } else {
            scores?.pause()
            // 측정을 멈춘 뒤에도 이 기기의 여행 점수(완료 시 최종값)를 결과 화면에 보여 준다.
            val result=scores?.read(key)
            if(state.liveCourseId!="trip-total-v1" || state.liveCourseScore!=result)
                mutable.value=state.copy(liveCourseId="trip-total-v1",liveCourseScore=result,courseResults=emptyMap())
        }
    }
    private fun syncTotalFinalScore(trip: TripDetail,car: TripCar,authority: ScoreReportAuthority,api: TripsApi) {
        if(trip.state!="completed" && car.routePlan?.phase!="done")return
        val key=scoreKey(trip,"trip-total-v1") ?: return
        val result=withoutTotalScoreReports {scores?.finish(key)} ?: return
        val report=result.report(final=true)
        finalUploads.submit(key,authority,report,send={callback->
            if(access.scoreReportAuthority!=authority) {
                callback(Result.failure(IllegalStateException("SCORE_AUTHORITY_CHANGED")));Closeable {}
            } else api.reportTripDrivingScore(trip.id,car.id,report) {reply->
                callback(if(access.scoreReportAuthority==authority)reply else Result.failure(IllegalStateException("SCORE_AUTHORITY_CHANGED")))
            }
        },onSuccess={if(state.selectedId==trip.id)readDrivingVersus()})
    }
    private fun <T> withoutTotalScoreReports(action: ()->T): T {
        val previous=suppressScoreReports;suppressScoreReports=true
        return try {action()} finally {suppressScoreReports=previous}
    }
    fun pauseScoring() {scores?.pause()}
    fun scoreChanged(key: String,result: CourseDrivingResult) {
        val trip=state.detail ?: return
        val course=state.liveCourseId ?: return
        if(!closed && foreground && state.isCurrent && access.canRetain() && scoreKey(trip,course)==key) {
            mutable.value=state.copy(liveCourseScore=result)
            publishScore(trip,course,key,result)
        }
    }
    private inline fun withoutScoreReports(action: ()->Unit) {
        val previous=suppressScoreReports;suppressScoreReports=true
        try {action()} finally {suppressScoreReports=previous;scoreUploads.clear()}
    }
    private fun publishScore(trip: TripDetail,course: String,key: String,result: CourseDrivingResult) {
        val car=trip.myCar?.takeIf {it.isMine} ?: return
        val api=client?.tripsApi?.takeIf {client?.ready==true} ?: return
        if(suppressScoreReports || closed || !foreground || !state.isCurrent || !access.canRetain() || !canScore() || trip.state!="active" || result.completed)return
        if(course=="trip-total-v1") {
            if(access.scoreReportAuthority==null)return
            scoreUploads.update(key,result.report()) {report,reply->api.reportTripDrivingScore(trip.id,car.id,report,reply)}
            return
        }
        scoreUploads.update(key,result.report()) {report,reply->api.reportDrivingScore(trip.id,car.id,course,report,reply)}
    }
    fun forgetScores() {
        withoutScoreReports {scores?.forget()}
        mutable.value=state.copy(courseResults=emptyMap(),liveCourseId=null,liveCourseScore=null)
    }
    private fun rememberDriving() {state.selectedId?.let {drivingByTrip[it]=state.driving};syncScores()}
    private fun restoreRouteProgress(trip: TripDetail,drive: TripDrivingState): TripDrivingState {
        val car=trip.myCar ?: return drive
        if(trip.routeContractVersion==2) {
            val plan=car.routePlan ?: return TripDrivingState(position=drive.position)
            val stops=TripRouteOrder.resolve(TripRouteOrder.initial(trip,car),trip,car)
            val prefix=if(plan.next==null)stops else stops.takeWhile {it.key!=plan.next.key}
            val arrived=prefix.map {it.key}.toSet()
            val target=drive.targetKey?.takeIf {key->stops.any {it.key==key} && key !in arrived}
            return drive.copy(arrived=arrived,skipped=emptySet(),targetKey=target,
                phase=if(target==null)TripDrivingPhase.LATER else drive.phase,
                completedCourse=null,distanceMeters=drive.distanceMeters.takeIf {target!=null},
                enteredNear=target!=null && drive.enteredNear,remainingSeconds=drive.remainingSeconds.takeIf {target!=null})
        }
        val previous=routeRevisionsByTrip.put(trip.id,car.routeRevision)
        if(!car.routeNextKnown || previous==car.routeRevision && trip.id in drivingByTrip)return drive
        val stops=TripRouteOrder.resolve(TripRouteOrder.initial(trip,car),trip,car)
        val next=car.routeNext?.let {item->stops.firstOrNull {it.item.key==item.key}}
        if(next?.item?.type!="signal")routeNeedsNavigation.remove(trip.id)
        val prefix=if(next==null)stops else stops.takeWhile {it.key!=next.key}
        var restored=drive.copy(skipped=drive.skipped+prefix.map {it.key}-listOfNotNull(next?.key).toSet())
        if(next?.item?.type=="signal" && drive.targetKey!=next.key) {
            routeNeedsNavigation.add(trip.id)
            restored=restored.copy(phase=TripDrivingPhase.LATER,targetKey=null,distanceMeters=null,enteredNear=false,remainingSeconds=null,legStartMeters=null,naviAtMillis=0)
        }
        return restored
    }
    private fun publishRouteProgress() {
        val trip=state.detail ?: return
        val car=trip.myCar?.takeIf {it.isMine} ?: return
        if(closed || !foreground || !state.isCurrent || trip.state!="active" || client?.ready!=true || routeProgressWriting)return
        val stops=TripRouteOrder.resolve(TripRouteOrder.initial(trip,car),trip,car)
        // The place the car is being guided to; without active guidance, the next stop still ahead.
        val next=(stops.firstOrNull {it.key==state.driving.targetKey && it.key !in state.driving.arrived}
            ?: tripNextStop(stops,state.driving))?.item
        val stamp=listOf(trip.id,car.id,car.routeRevision,next?.key)
        if(stamp==publishedRouteProgress)return
        val token=generation;routeProgressWriting=true
        routeProgressWrite=client?.tripsApi?.routeProgress(trip.id,car.id,car.routeRevision,next) {reply->
            if(token!=generation)return@routeProgress
            routeProgressWriting=false
            if(reply.isSuccess){publishedRouteProgress=stamp;publishRouteProgress()}
            else if((reply.exceptionOrNull() as? NativeSocialFailure)?.kind==NativeSocialFailure.Kind.CONFLICT && state.selectedId==trip.id && !state.busy)readDetail(trip.id)
        }
    }
    private fun retainedResponse(): TripSignalState {
        val signals=state.signals
        val overlay=signals.overlay?.takeIf {it.isGroupDecision} ?: return TripSignalState()
        return TripSignalState(overlay=overlay,overlayTrip=signals.overlayTrip ?: state.detail,voted=signals.voted,result=signals.result)
    }
    fun completeCourse() {
        val trip=state.detail ?: return
        val car=trip.myCar?.takeIf {it.isMine} ?: return
        if(trip.routeContractVersion==2) {
            val plan=car.routePlan ?: return
            if(!canMutate() || trip.state!="active" || state.gear!=TripGear.PARK || !plan.awaitingJoinCourseCompletion)return
            val api=client?.tripsApi ?: return
            val course=plan.joinPoint.courseId
            val snapshot=scoreKey(trip,course)?.let {scores?.read(it)} ?: CourseDrivingResult()
            val token=generation;mutable.value=state.copy(busy=true,notice=null)
            pending=api.completeJoinedCourse(trip.id,car.id,course,car.routeRevision,plan.progressRevision,snapshot.report(final=true)) {reply->
                if(token!=generation || state.selectedId!=trip.id)return@completeJoinedCourse
                reply.fold(onSuccess={
                    val result=scoreKey(trip,course)?.let {scores?.finish(it)}
                    mutable.value=state.copy(busy=false,courseResults=if(result!=null)state.courseResults+(course to result) else state.courseResults)
                    readDetail(trip.id)
                },onFailure=::mutationFailed)
            }
            return
        }
        if(!canMutate() || trip.state!="active" || state.driving.phase!=TripDrivingPhase.ROUTE_END)return
        val stops=TripRouteOrder.resolve(TripRouteOrder.initial(trip,car),trip,car)
        val target=stops.firstOrNull {it.key==state.driving.targetKey} ?: return
        val course=tripStopCourse(target,stops) ?: return
        val api=client?.tripsApi ?: return
        withoutScoreReports {scores?.pause()}
        val snapshot=scoreKey(trip,course)?.let {scores?.read(it)} ?: CourseDrivingResult()
        val token=generation;mutable.value=state.copy(busy=true,notice=null)
        pending=api.completeCourse(trip.id,car.id,course,snapshot.report(final=true)) {reply->
            if(token!=generation || state.selectedId!=trip.id)return@completeCourse
            reply.fold(onSuccess={
                val result=scoreKey(trip,course)?.let {scores?.finish(it)}
                mutable.value=state.copy(busy=false,driving=state.driving.complete(course),
                    courseResults=if(result!=null)state.courseResults+(course to result) else state.courseResults)
                readDetail(trip.id)
            },onFailure=::mutationFailed)
        }
    }
    private fun signalPhaseNotice(error: Throwable?): String? = when((error as? NativeSocialFailure)?.serverErrorCode) {
        "TRIP_SIGNAL_JOIN_PENDING"->"모든 차가 합류한 뒤 손들기를 보낼 수 있어요"
        "TRIP_SIGNAL_SHARED_FINISHED","TRIP_SIGNAL_ROUTE_FINISHED"->"우리 차 경로가 끝나 손들기를 보낼 수 없어요"
        else->null
    }
    private fun canReadSignals()=!closed && foreground && state.detail?.state=="active" && client?.ready==true
    private fun canSignal()=canReadSignals() && state.isCurrent && state.canUseSignalControls(allowed)
    private fun clearSignalCandidates() {
        candidateGeneration++
        signalLocation?.close();signalLocation=null
        candidateRead?.close();candidateRead=null
        mutable.value=state.copy(signals=state.signals.copy(loading=false,candidates=emptyList(),hint=null))
    }
    fun setSignalFacilities(required: Set<TripSignalFacility>)=loadSignalCandidates(state.signals.kind,required)
    fun loadSignalCandidates(kind: TripSignalKind)=loadSignalCandidates(kind,
        if(kind==state.signals.kind)state.signals.requiredFacilities else kind.defaultFacilities)
    private fun loadSignalCandidates(kind: TripSignalKind,requiredFacilities: Set<TripSignalFacility>) {
        val trip=state.detail ?: return
        if(!canSignal() || state.signals.hasActiveSignal || !state.signals.checked || state.signals.sending || state.signals.sentId!=null)return
        candidateRead?.close();signalLocation?.close()
        val candidateToken=++candidateGeneration
        mutable.value=state.copy(signals=state.signals.copy(kind=kind,requiredFacilities=requiredFacilities.toSet(),candidates=emptyList(),loading=true,sentId=null,sentWithoutDestination=false,hint=null,result=null))
        signalLocation=locateSignal {location->
            if(candidateToken!=candidateGeneration || state.selectedId!=trip.id)return@locateSignal
            if(location==null) {
                mutable.value=state.copy(signals=state.signals.copy(loading=false,hint="위치를 확인하지 못했어요. 장소 없이 보낼 수 있어요"))
                return@locateSignal
            }
            val next=state.detail?.signalRouteStop(state.driving)
            val destination=next?.let {SignalPoint(checkNotNull(it.lat),checkNotNull(it.lng))} ?: location.destination
            val point=location.location
            val heading=point.heading?.takeIf {it in 0.0..360.0}
            if(destination==null && heading==null) {
                mutable.value=state.copy(signals=state.signals.copy(loading=false,hint="진행 방향을 확인할 수 없어요. 장소 없이 보낼 수 있어요"))
                return@locateSignal
            }
            candidateRead=client?.tripsApi?.signalCandidates(trip.id,kind,SignalLocation(point.copy(heading=heading),destination),requiredFacilities) {reply->
                if(candidateToken!=candidateGeneration || state.selectedId!=trip.id)return@signalCandidates
                mutable.value=state.copy(signals=state.signals.copy(loading=false,candidates=reply.getOrDefault(emptyList()).filter {it.verdict=="ahead"},
                    hint=signalPhaseNotice(reply.exceptionOrNull()) ?: if(reply.isFailure)"가까운 곳을 찾지 못했어요. 장소 없이 보낼 수 있어요" else if(reply.getOrThrow().isEmpty())"가까운 장소가 없어요. 장소 없이 보낼 수 있어요" else null))
            }
        }
    }
    fun sendTripSignal(destination: SignalDestination?) {
        val trip=state.detail ?: return
        if(!canSignal() || state.signals.sending || state.signals.sentId!=null || state.signals.hasActiveSignal)return
        if(!state.signals.checked) {refreshSignals();return}
        val token=generation
        log("trip.signals: send started")
        mutable.value=state.copy(signals=state.signals.copy(sending=true,hint=null))
        signalWrite=client?.tripsApi?.sendSignal(trip.id,state.signals.kind,destination) {reply->
            if(token!=generation || state.selectedId!=trip.id)return@sendSignal
            mutable.value=state.copy(signals=state.signals.copy(sending=false,sentId=reply.getOrNull(),sentWithoutDestination=destination==null,
                hint=signalPhaseNotice(reply.exceptionOrNull()) ?: if((reply.exceptionOrNull() as? NativeSocialFailure)?.serverErrorCode=="TRIP_SIGNAL_CANDIDATE_CHANGED")
                    "장소 정보가 바뀌었어요. 다시 찾아 주세요" else if((reply.exceptionOrNull() as? NativeSocialFailure)?.serverErrorCode=="TRIP_SIGNAL_IN_PROGRESS")
                    "손들기가 진행 중이에요" else if((reply.exceptionOrNull() as? NativeSocialFailure)?.serverErrorCode=="TRIP_SIGNAL_CAR_REQUIRED")
                    "탈 차를 먼저 정해 주세요" else if((reply.exceptionOrNull() as? NativeSocialFailure)?.serverErrorCode=="TRIP_SIGNAL_GROUP_UNREACHABLE")
                    "응답할 수 없는 차가 있어요. 참여 상태를 확인해 주세요" else if(reply.isFailure)"보내지 못했어요. 다시 눌러 주세요" else null))
            if((reply.exceptionOrNull() as? NativeSocialFailure)?.serverErrorCode=="TRIP_SIGNAL_CANDIDATE_CHANGED")
                mutable.value=state.copy(signals=state.signals.copy(candidates=emptyList()))
            refreshSignals()
        }
    }
    fun refreshSignals()=refreshSignals(null)
    private fun refreshSignals(ids: Set<String>?) {
        if(ids==null || state.selectedId in ids)refreshSelectedSignals()
        refreshOtherSignals(ids)
    }
    private fun refreshOtherSignals(only: Set<String>?=null) {
        val api=client?.tripsApi ?: return
        if(closed || !foreground || client?.ready!=true || !access.canRetain() || responseReading || state.signals.voting)return
        val ownTrip=state.detail?.takeIf {it.state=="active"}?.id
        val ids=state.list?.trips.orEmpty().filter {it.state=="active" && it.id!=ownTrip && (only==null || it.id in only)}.map {it.id}
            .sortedBy {if(it==state.signals.overlayTrip?.id)0 else 1}
        if(state.signals.overlayTrip?.id!=null && state.signals.overlayTrip?.id!=ownTrip && state.signals.overlayTrip?.id !in ids)
            mutable.value=state.copy(signals=state.signals.copy(overlay=null,overlayTrip=null,voted=null,voting=false,result=null))
        if(ids.isEmpty())return
        val mine=++responseGeneration;val token=generation;responseReading=true
        fun current()=mine==responseGeneration && token==generation && !closed && foreground
        fun scan(index: Int) {
            if(!current())return
            if(index>=ids.size){responseReading=false;return}
            val id=ids[index]
            responseRead=api.readSignals(id) {reply->
                if(!current())return@readSignals
                val signals=reply.getOrNull()?.signals
                if(signals==null){scan(index+1);return@readSignals}
                val before=state.signals.overlay
                val ownsOverlay=state.signals.overlayTrip?.id==id
                val candidate=signals.firstOrNull {it.isGroupDecision && it.inProgress && it.contextState=="valid" &&
                    it.canRespond==true && it.myGroupChoice==null && it.id !in dismissedResponses}
                if(ownsOverlay && candidate?.id!=before?.id)
                    mutable.value=state.copy(signals=state.signals.copy(overlay=null,overlayTrip=null,voted=null,voting=false,result=null))
                if(candidate==null || state.signals.overlay!=null && !ownsOverlay){scan(index+1);return@readSignals}
                val cached=state.signals.overlayTrip?.takeIf {it.id==id}
                if(cached!=null) {
                    mutable.value=state.copy(signals=state.signals.copy(overlay=candidate,overlayTrip=cached))
                    responseReading=false
                } else responseRead=api.readDetail(id) {detailReply->
                    if(!current())return@readDetail
                    val detail=detailReply.getOrNull()
                    if(detail!=null && detail.canRespondToSignal(candidate)) {
                        mutable.value=state.copy(signals=state.signals.copy(overlay=candidate,overlayTrip=detail,voted=null,result=null))
                        responseReading=false
                    } else scan(index+1)
                }
            }
        }
        scan(0)
    }
    private fun refreshSelectedSignals() {
        val trip=state.detail ?: return
        if(closed || !foreground || (!allowed && trip.state!="active") || client?.ready!=true || !access.canRetain())return
        val token=generation
        if(!fineEvents && trip.display!=null && trip.display.expiresAtElapsedMillis!=Long.MAX_VALUE && trip.display.expiresAtElapsedMillis-android.os.SystemClock.elapsedRealtime()<=5000 && !displayReading && !state.busy) {
            displayReading=true
            displayRead=client?.tripsApi?.readDetail(trip.id) {reply->
                if(token==generation && state.selectedId==trip.id) {
                    displayReading=false
                    val current=state.detail
                    if(current!=null)mutable.value=state.copy(detail=withArrivals(current.copy(display=reply.getOrNull()?.display,
                        cars=reply.getOrNull()?.let {fresh->withLiveProgress(current.cars,fresh.cars)} ?: current.cars)))
                }
            }
        }
        if(!canReadSignals())return
        if(signalReading){signalsAgain=true;return}
        signalReading=true;signalsAgain=false
        signalRead=client?.tripsApi?.readSignals(trip.id) {reply->
            if(token!=generation || state.selectedId!=trip.id)return@readSignals
            signalReading=false
            reply.onFailure {error->
                log(TripLoadDiagnostics.message("trip.signals",error,trip.id))
                if((error as? NativeSocialFailure)?.kind in setOf(NativeSocialFailure.Kind.AUTHORIZATION_REQUIRED,NativeSocialFailure.Kind.FORBIDDEN)) {
                    // 연결이 이어서 기능 권한을 무효화해도 이 클라이언트는 이미 닫혀 그 알림을 받지 못한다. 업무 규칙 거절은 다시 읽어도 같다.
                    clear(TripClearReason.SIGNALS_DENIED)
                    if(NativeSocialErrorCodec.invalidatesAuthority(error))reloadAfterInvalidation()
                }
                else if(state.signals.result!="답을 보내지 못했어요. 다시 눌러 주세요")
                    mutable.value=state.copy(signals=state.signals.copy(checked=false,overlay=null,voted=null,voting=false,result=null,
                        hint="손들기를 확인하지 못했어요. 다시 불러와 주세요"))
            }.onSuccess {page->
                val signals=page.signals
                val me=trip.me?.id
                val cars=trip.cars.size
                val current=state.signals.overlay.takeIf {state.signals.overlayTrip?.id in setOf(null,trip.id)}
                val fresh=TripSignalsCodec.newSignals(seenSignals,signals,me).filter {signal->
                    trip.announcesSignal(signal) && (signalsInitialized || runCatching {java.time.Instant.now().epochSecond-java.time.Instant.parse(signal.createdAt).epochSecond in 0..15}.getOrDefault(false))
                }
                if(!signalsInitialized) {
                    resolvedSignals.addAll(signals.filter {signal->
                        val recent=runCatching {java.time.Instant.now().epochSecond-java.time.Instant.parse(signal.createdAt).epochSecond in 0..15}.getOrDefault(false)
                        !recent && (signal.hasMajority(cars,me) || signal.hasPassed(cars) || signal.resolution in setOf("completed","cancelled","reconfirm"))
                    }.map {it.id})
                    signalsInitialized=true
                }
                seenSignals.addAll(signals.map {it.id})
                val updated=current?.let {old->signals.firstOrNull {it.id==old.id && (!it.isGroupDecision || trip.canRespondToSignal(it))}}
                val incoming=signals.firstOrNull {it.isGroupDecision && trip.canRespondToSignal(it) && it.id !in dismissedResponses}
                    ?: fresh.firstOrNull {it.id !in resolvedSignals}
                val otherOverlay=state.signals.overlay.takeIf {state.signals.overlayTrip?.id!=null && state.signals.overlayTrip?.id!=trip.id}
                mutable.value=state.copy(signals=state.signals.copy(checked=true,hasActiveSignal=page.hasActiveSignal,ongoing=signals.firstOrNull {page.hasActiveSignal && it.inProgress},
                    latestGroupSignal=signals.firstOrNull {it.isGroupDecision},
                    candidates=if(page.hasActiveSignal)emptyList() else state.signals.candidates,loading=if(page.hasActiveSignal)false else state.signals.loading,
                    overlay=otherOverlay ?: updated ?: incoming,overlayTrip=if(otherOverlay!=null)state.signals.overlayTrip else if(updated!=null || incoming!=null)trip else null,
                    voting=if(current?.isGroupDecision==true && updated==null)false else state.signals.voting,
                    voted=if(updated==null && incoming!=null)null else state.signals.voted,
                    result=if(updated==null && incoming!=null)null else if(current!=null && updated==null)"손들기가 끝났어요" else state.signals.result))
                for(signal in signals) {
                    if(signal.id in resolvedSignals)continue
                    if(signal.isGroupDecision) {
                        if(signal.inProgress)continue
                        resolvedSignals.add(signal.id)
                        mutable.value=state.copy(signals=state.signals.copy(result=when(signal.resolution) {
                            "agreed"->"모든 차가 동의해 여행 경로에 추가했어요";"passed"->"거절한 차가 있어 경로에 추가하지 않았어요";else->"손들기가 끝났어요"}))
                        if(signal.resolution=="agreed" && !state.busy){if(fineEvents)refreshSection("route") else readDetail(trip.id)}
                        continue
                    }
                    if(signal.contextState!="valid" || signal.hasPassed(cars) || signal.resolution in setOf("completed","cancelled")) {
                        resolvedSignals.add(signal.id)
                        if(signal.accountId==me || state.signals.overlay?.id==signal.id)
                            mutable.value=state.copy(signals=state.signals.copy(result=when(signal.resolution) {
                                "completed"->"손들기를 완료했어요";"cancelled"->"손들기를 취소했어요";else->"손들기가 끝났어요"}))
                    } else if(signal.destination!=null && signal.hasMajority(cars,me)) {
                        resolvedSignals.add(signal.id)
                        mutable.value=state.copy(signals=state.signals.copy(overlay=signal,result="과반이 동의했어요"))
                    }
                }
                val sent=state.signals.sentId
                if(sent!=null && signals.none {it.id==sent && it.inProgress})
                    mutable.value=state.copy(signals=state.signals.copy(sentId=null,result=state.signals.result ?: "손들기가 끝났어요"))
            }
            if(signalsAgain && token==generation)refreshSelectedSignals()
        }
    }
    private fun skipVote(reason: String) {
        log("trip.signals: vote skipped reason=$reason")
        if(reason=="client_not_ready" && state.signals.overlay!=null)
            mutable.value=state.copy(signals=state.signals.copy(voting=false,result="답을 보내지 못했어요. 다시 눌러 주세요"))
    }
    fun voteTripSignal(choice: String)=voteTripSignal(choice,state.signals.overlay)
    fun voteOngoingTripSignal(choice: String)=voteTripSignal(choice,state.signals.ongoing)
    private fun voteTripSignal(choice: String,selected: TripSignal?) {
        if(closed || !foreground)return skipVote("closed")
        if(!state.canUseSignalResponses(allowed))return skipVote("driving_restrictions")
        if(choice!="agree" && choice!="pass")return skipVote("invalid_choice")
        val trip=state.signals.overlayTrip?.takeIf {selected?.id==state.signals.overlay?.id} ?: state.detail ?: return skipVote("detail_missing")
        if(trip.state!="active")return skipVote("trip_not_active")
        val signal=selected ?: return skipVote("signal_missing")
        if(signal.destination==null)return skipVote("destination_missing")
        val social=client?.takeIf {it.ready} ?: return skipVote("client_not_ready")
        if(state.signals.voting)return skipVote("voting")
        if(signal.isGroupDecision && !trip.canRespondToSignal(signal))return skipVote("group_cannot_respond")
        if(signal.isGroupDecision && signal.id in acknowledgedResponses)return skipVote("already_voted")
        if(!signal.isGroupDecision && state.signals.voted!=null)return skipVote("already_voted")
        if(!signal.isGroupDecision && trip.myCar?.isMine!=true)return skipVote("not_driver")
        if(trip.signalFromMyCar(signal))return skipVote("requester_car")
        val token=generation
        log("trip.signals: vote started choice=$choice")
        mutable.value=state.copy(signals=state.signals.copy(voting=true,result=null))
        signalWrite=social.tripsApi.voteSignalResult(trip.id,signal.id,choice) {reply->
            if(token!=generation || state.signals.overlay?.id!=signal.id && state.signals.ongoing?.id!=signal.id)return@voteSignalResult
            if(signal.isGroupDecision && reply.isSuccess) {
                dismissedResponses.add(signal.id)
                acknowledgedResponses.add(signal.id)
                mutable.value=state.copy(signals=state.signals.copy(voting=false,voted=null,overlay=null,overlayTrip=null,
                    result=if(reply.getOrThrow().already)"우리 차에서 이미 응답했어요" else null))
                refreshSignals();return@voteSignalResult
            }
            mutable.value=state.copy(signals=state.signals.copy(voting=false,voted=choice.takeIf {reply.isSuccess},
                result=if(reply.isFailure)"답을 보내지 못했어요. 다시 눌러 주세요" else null))
            if(reply.isSuccess || signal.isGroupDecision)refreshSignals()
        }
    }
    fun finishTripSignal(result: String) {
        val trip=state.detail ?: return
        val signal=state.signals.ongoing ?: return
        if(!canSignal() || signal.accountId!=trip.me?.id || signal.destination!=null && !(signal.isGroupDecision && result=="cancelled") || state.signals.ending || result !in setOf("completed","cancelled"))return
        val token=generation
        mutable.value=state.copy(signals=state.signals.copy(ending=true,result=null))
        signalWrite=client?.tripsApi?.finishSignal(trip.id,signal.id,result) {reply->
            if(token!=generation || state.selectedId!=trip.id)return@finishSignal
            mutable.value=state.copy(signals=state.signals.copy(ending=false,
                result=if(reply.isFailure)"끝내지 못했어요. 다시 눌러 주세요" else if(result=="completed")"손들기를 완료했어요" else "손들기를 취소했어요"))
            refreshSignals()
        }
    }
    fun dismissTripSignal() {
        state.signals.overlay?.takeIf {it.isGroupDecision}?.let {dismissedResponses.add(it.id)}
        mutable.value=state.copy(signals=state.signals.copy(overlay=null,overlayTrip=null,voted=null,result=null,voting=false))
    }
    override fun close() {closed=true;stopRecovery();cancel();stopNavigation();observer.close();access.forget();mutable.value=TripsPageState()}
}

/** Tells the driver why an arrival confirmation was not saved so the next step is clear. */
internal fun tripArrivalFailureNotice(error: Throwable?): String {
    val failure=error as? NativeSocialFailure
    return when {
        failure?.serverErrorCode=="TRIP_STATE_CONFLICT"->"진행 중인 여행만 도착을 저장할 수 있어요"
        failure?.serverErrorCode=="TRIP_ROUTE_COURSE_UNAVAILABLE"->"경로를 볼 수 없어요. 여행 만든 사람에게 확인해 주세요"
        failure?.kind==NativeSocialFailure.Kind.CONFLICT->"경로가 바뀌었어요. 다음 장소를 확인하고 다시 눌러 주세요"
        failure?.kind==NativeSocialFailure.Kind.FORBIDDEN->"이 차의 운전자만 도착을 확인할 수 있어요"
        failure?.kind in setOf(NativeSocialFailure.Kind.AUTHORIZATION_REQUIRED,NativeSocialFailure.Kind.CONSENT_REQUIRED)->
            "도착을 저장하려면 연결 권한을 확인해 주세요"
        else->"도착을 저장하지 못했어요. 정차 후 다시 눌러 주세요"
    }
}

internal const val TRANSIENT_RECOVERY_BASE_MILLIS=2_000L
internal const val TRANSIENT_RECOVERY_MAX_MILLIS=60_000L
internal const val TRANSIENT_RECOVERY_ATTEMPTS=8

/** 네트워크 끊김·5xx·이벤트 스트림 중단만 자동 재시도한다. 401/403 등 인증·권한 실패는 기존 처리(권한 필요 화면)를 따른다. */
internal fun transientTripFailure(error: Throwable): Boolean = when(error) {
    is java.io.IOException->true
    is NativeSocialFailure->error.kind==NativeSocialFailure.Kind.UNAVAILABLE
    else->false
}
