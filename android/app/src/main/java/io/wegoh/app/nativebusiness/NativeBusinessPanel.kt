@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package io.wegoh.app.nativebusiness

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import io.wegoh.app.nativeauth.*
import io.wegoh.app.AccountReadSnapshot
import io.wegoh.app.DRIVING_RESTRICTED_REASON
import io.wegoh.app.VehicleRemoteResult
import io.wegoh.app.ui.*
import java.io.Closeable
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

internal enum class BusinessSection(val title: String,val phoneView: String) {
    MENU("내 차","vehicle"), COMMANDS("차량 요청","vehicle"), MISSIONS("함께 미션","together"),
    RECOMMENDATIONS("내 취향 추천","recommendations"), CAUTIONS("주의 기록","cautions")
}
internal class BusinessLine(val title: String,val detail: String,val status: String?=null,
    val tone: CarStatusTone=CarStatusTone.OUTLINE)
private val pendingCommandStages=setOf(BusinessCommand.Stage.QUEUED,BusinessCommand.Stage.DELIVERED,
    BusinessCommand.Stage.RECEIVED,BusinessCommand.Stage.SDK_ACCEPTED)

/** Remote request stage → chip. Waiting keeps the outline, success is soft accent, failure is a muted fill and
 *  unknown is dashed, so the four outcomes differ at a glance. Outcome names share one axis: '동작 확인됨' / '동작 미확인'. */
internal fun businessCommandStatus(stage: BusinessCommand.Stage,reason: String?=null): Pair<String,CarStatusTone> = when(stage) {
    BusinessCommand.Stage.QUEUED->"대기 중" to CarStatusTone.OUTLINE
    BusinessCommand.Stage.DELIVERED->"요청 전달됨" to CarStatusTone.OUTLINE
    BusinessCommand.Stage.RECEIVED->"차량에서 받음" to CarStatusTone.OUTLINE
    BusinessCommand.Stage.SDK_ACCEPTED->"차량 확인 중" to CarStatusTone.OUTLINE
    BusinessCommand.Stage.STATE_CONFIRMED->"동작 확인됨" to CarStatusTone.SOFT
    BusinessCommand.Stage.REJECTED->(if(reason==DRIVING_RESTRICTED_REASON)VehicleRemoteResult.DRIVING_BLOCKED.label else "거절됨") to
        CarStatusTone.PAST
    BusinessCommand.Stage.CANCELLED->"취소됨" to CarStatusTone.PAST
    BusinessCommand.Stage.EXPIRED->"시간 만료" to CarStatusTone.PAST
    BusinessCommand.Stage.UNKNOWN->"동작 미확인" to CarStatusTone.PENDING
}

/** A finished request that may still have run says so, except UNKNOWN whose chip already says it. */
internal fun businessCommandUncertain(stage: BusinessCommand.Stage,mayHaveExecuted: Boolean): Boolean =
    mayHaveExecuted && stage !in pendingCommandStages && stage!=BusinessCommand.Stage.STATE_CONFIRMED &&
        stage!=BusinessCommand.Stage.UNKNOWN
/** Read-only first-four UI; phone performs existing explicit consent/settings and unsupported actions. */
@Composable
fun NativeBusinessPanel(connection: VehicleConnection,allowed: Boolean,onBack: ()->Unit,onHistory: ()->Unit,initialSection: String="MENU",embedded: Boolean=false,tripId: String?=null,
    drivingVersus: TripDrivingVersus?=null,drivingVersusLoading: Boolean=false,
    drivingVersusNotice: String?=null,onDrivingVersusRefresh: (() ->Unit)?=null,inlineCommands: Boolean=false) {
    val active=allowed && LocalCarWindowVisibility.current?.state?.focused==true
    val initial=BusinessSection.entries.firstOrNull {it.name==initialSection && it!=BusinessSection.MISSIONS} ?: BusinessSection.MENU
    var section by rememberSaveable(initial) {mutableStateOf(initial)}
    var roomId by remember(tripId) {mutableStateOf<String?>(null)}
    var rooms by remember {mutableStateOf<List<SocialRoomSummary>>(emptyList())}
    var lines by remember {mutableStateOf<List<BusinessLine>>(emptyList())}
    var phone by remember {mutableStateOf(false)}
    var message by remember {mutableStateOf("")}
    var retry by remember {mutableIntStateOf(0)}
    val invalidationReloads=remember(connection) {InvalidationReloads()}
    var contentKey by remember(connection) {mutableStateOf<Pair<BusinessSection,String?>?>(null)}
    val scope=rememberCoroutineScope()
    fun clear() {rooms=emptyList();lines=emptyList();phone=false;message="연결과 이용 권한을 확인해 주세요"}
    val snapshot=remember(connection) {AccountReadSnapshot(connection) {clear()}}
    DisposableEffect(connection) {
        val observer=connection.observe {if(snapshot.invalidated()){snapshot.forget();clear()}}
        onDispose {observer.close();snapshot.forget()}
    }
    fun back() {when {phone->phone=false;roomId!=null->roomId=null;section!=initial->section=initial;else->onBack()}}
    CarChildBackHandler(enabled=!embedded || phone || roomId!=null || section!=initial) {back()}
    val headerRefresh=LocalCarRemoteRefresh.current
    DisposableEffect(connection,active,section,roomId,tripId,retry,if(inlineCommands)headerRefresh else 0) {
        var current=true
        var request: Closeable?=null
        var social: NativeSocialClient?=null
        var scheduled: Job?=null
        var readingCommands=false
        var refreshQueued=false
        val key=section to (tripId ?: roomId)
        if(contentKey!=key || snapshot.invalidated()) {snapshot.forget();clear();message="";contentKey=key}
        fun accept(): Boolean {
            val boundary=connection.verifiedDataBoundary()
            if(boundary==null){snapshot.forget();clear();return false}
            snapshot.remember(boundary);invalidationReloads.reset();return true
        }
        fun failed(error: Throwable) {
            io.wegoh.app.nativeauth.WegoLog.w("WegoH","business.panel: load failed section=${section.name} reason=${error.javaClass.simpleName} kind=${(error as? NativeSocialFailure)?.kind?.name?.lowercase() ?: "other"}")
            if(current)when((error as? NativeSocialFailure)?.kind) {
                NativeSocialFailure.Kind.CONSENT_REQUIRED,NativeSocialFailure.Kind.FORBIDDEN->{
                    snapshot.forget();clear()
                    message=if(section==BusinessSection.COMMANDS)"리모컨 수신 설정을 확인해 주세요"
                        else "이 계정에서는 볼 수 없어요"
                }
                NativeSocialFailure.Kind.NOT_FOUND->{snapshot.forget();clear();message="더 이상 볼 수 없는 항목이에요"}
                else->message=if(snapshot.canRetain())"저장된 내용이에요. 새로고침해 주세요" else "연결을 확인하고 다시 시도해 주세요"
            }
        }
        fun scheduleCommands(action: ()->Unit) {
            scheduled?.cancel()
            scheduled=scope.launch {delay(4_000);if(current)action()}
        }
        fun loadCommands(client: NativeSocialClient) {
            if(readingCommands) {refreshQueued=true;return}
            if(client.status()!=NativeSocialClient.State.READY)return
            scheduled?.cancel();readingCommands=true
            request=client.readCommandStatuses {result->
                if(!current)return@readCommandStatuses
                readingCommands=false
                var pending=false
                result.onSuccess {value->
                    if(!accept())return@readCommandStatuses
                    val date=DateTimeFormatter.ofPattern("HH:mm:ss",Locale.KOREAN).withZone(ZoneId.systemDefault())
                    lines=value.commands.map {item->
                        val (status,tone)=businessCommandStatus(item.stage,item.reason)
                        val uncertain=businessCommandUncertain(item.stage,item.mayHaveExecuted)
                        BusinessLine(item.label,date.format(item.createdAt)+(if(uncertain)"\n실제 동작 미확인" else ""),status,tone)
                    }
                    pending=value.commands.any {it.stage in pendingCommandStages}
                    message=if(lines.isEmpty())"받은 차량 요청이 없어요" else "요청 상태"
                }.onFailure {error->
                    failed(error)
                    pending=(error as? NativeSocialFailure)?.kind in setOf(NativeSocialFailure.Kind.UNAVAILABLE,NativeSocialFailure.Kind.STALE)
                }
                if(refreshQueued) {refreshQueued=false;loadCommands(client)}
                else if(pending)scheduleCommands {loadCommands(client)}
            }
        }
        if(active && section!=BusinessSection.MENU) {
            message=if(rooms.isEmpty() && lines.isEmpty())"불러오는 중" else "새로고침 중"
            val client=if(section==BusinessSection.COMMANDS)connection.tripSocial() else connection.social()
            social=client
            client.open(object: NativeSocialObserver {
                override fun onResourcesChanged(resources: Set<String>) {
                    if(!current || section!=BusinessSection.COMMANDS)return
                    if("devices" in resources) {
                        current=false;request?.close();snapshot.forget();clear();retry++
                    } else if("commands" in resources)loadCommands(client)
                }
                override fun onInvalidated() {
                    if(!current)return
                    snapshot.forget();clear()
                    // 권한 교체만으로 끊긴 경우 다시 연다(성공 전 반복은 3회까지).
                    invalidationReloads.take()?.let {retry++}
                }
                override fun onConnectionLost() {
                    if(current) {
                        if(snapshot.canRetain())message="저장된 내용이에요. 새로고침해 주세요"
                        else clear()
                        if(section==BusinessSection.COMMANDS)scheduleCommands {retry++}
                    }
                }
            }) {opened->
                if(current)opened.onSuccess {
                    when(section) {
                        BusinessSection.COMMANDS->loadCommands(client)
                        BusinessSection.MISSIONS->{
                            val room=tripId ?: roomId
                            if(room==null)request=client.overviewApi.readOverview {result->
                                if(current)result.onSuccess {value->
                                    if(!accept())return@readOverview
                                    rooms=value.rooms
                                    message=if(!value.roomsAvailable)"이 계정의 여행을 볼 수 없어요"
                                        else if(rooms.isEmpty())"참여 중인 여행이 없어요" else "여행을 선택해 주세요"
                                }.onFailure(::failed)
                            } else {
                                val completed: (Result<BusinessMissionList>)->Unit = {result->
                                    if(current)result.onSuccess {value->
                                        if(accept()) {
                                            lines=value.missions.map {item->BusinessLine(item.title,when(item.state) {
                                                BusinessMission.State.ENROLLING->"참여 확인 중"
                                                BusinessMission.State.ACTIVE->"진행 중"
                                                BusinessMission.State.COMPLETED->"완료"
                                                BusinessMission.State.CANCELLED->"취소됨"
                                                BusinessMission.State.INTERRUPTED->"중단됨"
                                                BusinessMission.State.RESULT_WITHDRAWN->"공유 중단됨"
                                                BusinessMission.State.COURSE_UNAVAILABLE->"경로를 확인해 주세요"
                                            }+(item.nextPlaceName?.let {"\n다음 $it"} ?: ""))}
                                            message=if(lines.isEmpty())"참여한 미션이 없어요" else "직접 확인한 기록"
                                        }
                                    }.onFailure(::failed)
                                }
                                request=if(tripId!=null)client.missionsApi.readTripMissions(room,completed) else client.missionsApi.readMissions(room,completed)
                            }
                        }
                        BusinessSection.RECOMMENDATIONS->request=client.recommendationsApi.readSettings {result->
                            if(current)result.onSuccess {value->
                                if(!accept())return@readSettings
                                message=if(value.configured)"추천 설정" else "추천 설정을 확인해 주세요"
                                lines=listOf(BusinessLine("추천 기준",when(value.priority) {
                                    BusinessRecommendationSettings.Priority.NEARBY->"가까운 경로"
                                    BusinessRecommendationSettings.Priority.FEW_STOPS->"장소가 적은 경로"
                                    BusinessRecommendationSettings.Priority.MANY_STOPS->"장소가 많은 경로"
                                }),BusinessLine("방문 기록 활용",if(value.usesHistory)"허용" else "허용 안 함"),
                                    BusinessLine("평가 활용",if(value.usesFeedback)"허용" else "허용 안 함"),
                                    BusinessLine("취향 학습",if(value.learningEnabled)"허용" else "허용 안 함"))
                            }.onFailure(::failed)
                        }
                        BusinessSection.CAUTIONS->request=client.cautionsApi.readCautions {result->
                            if(current)result.onSuccess {value->
                                if(!accept())return@readCautions
                                val date=DateTimeFormatter.ofPattern("yyyy.MM.dd (E)",Locale.KOREAN).withZone(ZoneId.systemDefault())
                                lines=value.items.map {item->BusinessLine(item.placeName,when(item.kind) {
                                    BusinessCaution.Kind.ROAD_SURFACE->"노면"
                                    BusinessCaution.Kind.CONSTRUCTION->"공사"
                                    BusinessCaution.Kind.VISIBILITY->"시야"
                                    BusinessCaution.Kind.HARSH_BRAKING->"급제동"
                                    BusinessCaution.Kind.OTHER->"기타"
                                }+"\n"+date.format(item.observedAt)+(if(item.own)"\n내 기록" else "\n공유 기록"))}
                                message=if(lines.isEmpty())"주의 기록이 없어요" else ""
                            }.onFailure(::failed)
                        }
                        else->Unit
                    }
                }.onFailure(::failed)
            }
        }
        onDispose {current=false;scheduled?.cancel();request?.close();social?.close()}
    }
    if(inlineCommands && section==BusinessSection.COMMANDS) {
        Column(Modifier.fillMaxWidth(),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
            Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically,
                horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                TripText("차량 요청",Modifier.weight(1f),style=CarType.Section)
                TripText("${lines.size}건",style=CarType.Label,secondary=true)
            }
            CarCard(tone=CarCardTone.OUTLINED,padding=PaddingValues()) {
                if(!active || lines.isEmpty())Box(Modifier.padding(CarTokens.Frame)) {
                    TripText(if(!active)"정차 후 이용해 주세요" else message,secondary=true,maxLines=CarMessageLines)
                } else {
                    if(message.isNotEmpty() && message!="요청 상태")Box(Modifier.padding(CarTokens.Frame)) {
                        TripText(message,secondary=true,maxLines=CarMessageLines)
                    }
                    lines.forEachIndexed {index,line->
                        if(index>0)TripDivider()
                        Column(Modifier.fillMaxWidth().padding(CarTokens.Frame),
                            verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                            Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically,
                                horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                                TripText(line.title,Modifier.weight(1f),style=CarType.Body,maxLines=3)
                                line.status?.let {CarStatusPill(it,kind=line.tone)}
                            }
                            TripText(line.detail,
                                style=CarType.Label,secondary=true,maxLines=3)
                        }
                    }
                }
            }
        }
        return
    }
    if(section==BusinessSection.CAUTIONS || (section==BusinessSection.MISSIONS && tripId!=null)) {
        BusinessActivityDetail(section,lines,message,active,embedded,{back()},{if(active){retry++;onDrivingVersusRefresh?.invoke()}},
            drivingVersus,drivingVersusLoading,drivingVersusNotice)
        return
    }
    TripSurface {
        val narrow=LocalTripLayoutWidth.current<CarTokens.Breakpoint
        Column(Modifier.fillMaxSize()
            .then(if(embedded)Modifier.padding(horizontal=CarTokens.SpaceMedium,vertical=CarTokens.SpaceSmall) else Modifier.systemBarsPadding().padding(horizontal=CarTokens.Frame,vertical=CarTokens.Gap)),
            verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
            if(!embedded) {
                TripHeading(section.title,onBack={back()})
                TripDivider()
            }
            TripAdaptiveRow(Modifier.weight(1f)
                .then(if(narrow)Modifier.verticalScroll(rememberScrollState()) else Modifier),narrow=narrow,gap=CarTokens.Space2XLarge) {
                Column(Modifier.weight(600f).then(if(narrow)Modifier else Modifier.verticalScroll(rememberScrollState())),
                    verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                    CarCard(padding=PaddingValues(CarTokens.BusinessCardPadding)) {
                        TripText(section.title,style=CarType.Title,maxLines=3)
                        if(!active)TripText("정차 후 이용해 주세요",secondary=true,maxLines=3)
                        else if(!phone && (rooms.isNotEmpty() || lines.isNotEmpty()) && message.isNotEmpty())
                            TripText(message,secondary=true,maxLines=CarMessageLines)
                    }
                    if(active && phone)CarButton("취소",{phone=false},Modifier.fillMaxWidth(),icon=CarSymbol.Close)
                    else if(active && section!=BusinessSection.MENU) {
                        if(rooms.isNotEmpty() || lines.isNotEmpty())CarButton("새로고침",{if(active)retry++},Modifier.fillMaxWidth(),icon=CarSymbol.Refresh)
                        if(tripId==null)CarPhoneHandoff("vehicle")
                    }
                }
                if(active)Column(Modifier.weight(968f).then(if(narrow)Modifier else Modifier.verticalScroll(rememberScrollState())),
                    verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                    if(phone)CarCard(outlined=true,padding=PaddingValues(CarTokens.Space2XLarge)) {
                        Column(Modifier.fillMaxWidth(),horizontalAlignment=Alignment.CenterHorizontally,verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                            CarPhoneHandoff("vehicle")
                        }
                    } else if(section==BusinessSection.MENU)CarCard(outlined=true,padding=PaddingValues(CarTokens.Frame)) {
                        for(item in BusinessSection.entries.filter {it !in setOf(BusinessSection.MENU,BusinessSection.MISSIONS,BusinessSection.CAUTIONS)})
                            CarButton(item.title,{if(active)section=item},Modifier.fillMaxWidth(),icon=CarSymbol.File)
                    } else {
                        if(rooms.isEmpty() && lines.isEmpty())CarCard(outlined=true,padding=PaddingValues(CarTokens.BusinessCardPadding)) {
                            if(message.isNotEmpty())TripText(message,style=CarType.Section,maxLines=CarMessageLines)
                            CarButton("새로고침",{if(active)retry++},Modifier.fillMaxWidth(),icon=CarSymbol.Refresh)
                        }
                        if(rooms.isNotEmpty())CarCard(outlined=true,padding=PaddingValues()) {
                            Column {
                                rooms.forEachIndexed {index,room->
                                    if(index>0)TripDivider()
                                    Column(Modifier.fillMaxWidth().padding(CarTokens.Frame),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                                        TripText(room.name,style=CarType.Section,maxLines=3)
                                        TripText("일행 ${room.memberCount}명",secondary=true,maxLines=3)
                                        CarButton("여행 선택",{if(active)roomId=room.id},Modifier.fillMaxWidth(),accessibility=room.name)
                                    }
                                }
                            }
                        }
                        if(lines.isNotEmpty())CarCard(outlined=true,padding=PaddingValues()) {
                            Column {
                                lines.forEachIndexed {index,line->
                                    if(index>0)TripDivider()
                                    val parts=line.detail.lines()
                                    val status=line.status ?: if(section in setOf(BusinessSection.MISSIONS,BusinessSection.CAUTIONS))parts.firstOrNull() else null
                                    val detail=if(line.status!=null || status==null)line.detail else parts.drop(1).joinToString("\n")
                                    Column(Modifier.fillMaxWidth().padding(CarTokens.Frame),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceCompact)) {
                                        if(narrow) {
                                            TripText(line.title,style=CarType.Section,maxLines=3)
                                            status?.let {CarStatusPill(it)}
                                        } else Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalAlignment=Alignment.CenterVertically) {
                                            TripText(line.title,Modifier.weight(1f),style=CarType.Section,maxLines=3)
                                            status?.let {CarStatusPill(it)}
                                        }
                                        if(detail.isNotEmpty())TripText(detail,secondary=true,maxLines=3)
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
internal fun BusinessActivityDetail(section: BusinessSection,lines: List<BusinessLine>,message: String,active: Boolean,
    embedded: Boolean,onBack: ()->Unit,onRefresh: ()->Unit,
    drivingVersus: TripDrivingVersus?=null,drivingVersusLoading: Boolean=false,drivingVersusNotice: String?=null) = TripSurface {
    val narrow=LocalTripLayoutWidth.current<CarTokens.Breakpoint
    val missions=section==BusinessSection.MISSIONS
    Column(Modifier.fillMaxSize().padding(if(embedded)CarTokens.SpaceMedium else CarTokens.Frame),
        verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
        TripHeading(section.title,if(missions)null else "현재 도로 상태는 다를 수 있어요",onBack=onBack)
        if(!missions) {
            CautionActivityList(lines,message,active,Modifier.weight(1f),onRefresh)
            return@Column
        }
        val summary: @Composable (Modifier)->Unit = {modifier->
            Column(modifier.then(if(narrow)Modifier else Modifier.verticalScroll(rememberScrollState())),
                verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                if(active)TripDrivingVersusSummary(drivingVersus,drivingVersusLoading,drivingVersusNotice,onRefresh)
                else CarCard(tone=CarCardTone.INK,radius=CarTokens.RadiusHero) {
                    TripText("함께 미션",style=CarType.Label,secondary=true)
                    TripText("정차 후 이용해 주세요",style=CarType.Hero,maxLines=3)
                }
                if(active && drivingVersus!=null) {
                    TripText("출발한 차는 자동 참가해요",secondary=true,maxLines=3)
                    TripText("여행 전체 점수만 참가한 차끼리 공유해요",secondary=true,maxLines=3)
                }
            }
        }
        val records: @Composable (Modifier)->Unit = {modifier->
            Column(modifier.then(if(narrow)Modifier else Modifier.verticalScroll(rememberScrollState())),
                verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                if(!active)CarEmptyState("정차 후 이용해 주세요",symbol=CarSymbol.Shield)
                else {
                    if(lines.isNotEmpty())TripText("함께한 기록",style=CarType.Section)
                    if(message.isNotEmpty())TripText(message,secondary=true,maxLines=CarMessageLines)
                    lines.forEach {line->
                        val parts=line.detail.lines()
                        CarCard(tone=CarCardTone.OUTLINED) {
                            Row(horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalAlignment=Alignment.CenterVertically) {
                                CarIcon(CarSymbol.Check)
                                TripText(line.title,Modifier.weight(1f),style=CarType.Section,maxLines=3)
                            }
                            parts.firstOrNull()?.let {CarStatusPill(it)}
                            parts.drop(1).filter {it.isNotEmpty()}.forEach {TripText(it,secondary=true,maxLines=3)}
                        }
                    }
                }
            }
        }
        if(narrow)Column(Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()),
            verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
            summary(Modifier.fillMaxWidth());records(Modifier.fillMaxWidth())
        } else Row(Modifier.weight(1f).fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
            summary(Modifier.weight(1f).fillMaxHeight());records(Modifier.weight(1f).fillMaxHeight())
        }
    }
}

@Composable
internal fun CautionActivityList(lines: List<BusinessLine>,message: String,active: Boolean,modifier: Modifier,onRefresh: ()->Unit) {
    androidx.compose.foundation.lazy.LazyColumn(modifier.fillMaxWidth(),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
        if(active)item {
            Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.End) {
                CarIconAction("주의 기록 새로고침",CarSymbol.Refresh,onRefresh)
            }
        }
        if(!active)item {CarEmptyState("정차 후 이용해 주세요",symbol=CarSymbol.Shield)}
        else {
            if(message.isNotEmpty())item {TripText(message,secondary=true,maxLines=CarMessageLines)}
            items(lines.size) {index->
                val line=lines[index]
                val parts=line.detail.lines()
                CarCard(tone=CarCardTone.OUTLINED) {
                    Row(Modifier.heightIn(min=CarTokens.Row),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalAlignment=Alignment.CenterVertically) {
                        CarIcon(CarSymbol.Pin,color=LocalCarPalette.current.accent)
                        Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                            TripText(line.title,style=CarType.Section,maxLines=3)
                            parts.getOrNull(1)?.let {TripText(it,secondary=true,maxLines=2)}
                        }
                        Column(verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                            parts.firstOrNull()?.let {CarStatusPill(it)}
                            parts.getOrNull(2)?.let {CarStatusPill(it)}
                        }
                    }
                }
            }
        }
        item {CarPhoneHandoff("caution")}
    }
}
