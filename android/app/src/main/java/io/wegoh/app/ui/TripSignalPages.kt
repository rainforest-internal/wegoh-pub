@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package io.wegoh.app.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.*
import androidx.activity.compose.BackHandler
import androidx.compose.ui.zIndex
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.graphics.vector.PathParser
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import io.wegoh.app.*
import io.wegoh.app.nativeauth.*
import androidx.compose.runtime.saveable.rememberSaveable
import kotlinx.coroutines.delay
import java.util.Locale

@Composable
internal fun SignalIcon(kind: TripSignalKind?,modifier: Modifier=Modifier,color: Color=LocalCarPalette.current.text) {
    val data=when(kind) {
        TripSignalKind.RESTROOM->"M7 4.5a1.5 1.5 0 1 0 0 .01M17 4.5a1.5 1.5 0 1 0 0 .01M5 8h4l1 7H8v6M7 15v6M15 8h4l1 7h-6zM16 15v6M18 15v6M12 3v18"
        TripSignalKind.CAFE->"M4 8h12v8a4 4 0 0 1-4 4H8a4 4 0 0 1-4-4zM16 9h2a3 3 0 0 1 0 6h-2M7 3v2M11 3v2"
        TripSignalKind.FUEL->"M5 21V4h9v17M5 10h9M14 6h3l3 4v8a2 2 0 0 1-4 0v-3h-2M3 21h13"
        TripSignalKind.EV_CHARGE->"M7 3h10v18H7zM13 6l-3 6h4l-3 6"
        TripSignalKind.REST->"M4 18h16M6 18v-6a6 6 0 0 1 12 0v6M12 6V3"
        TripSignalKind.DROWSY->"M4 5h6l-6 6h6M13 11h5l-5 5h5M3 19c2.5-1.5 5.5-1.5 9 0s6.5 1.5 9 0"
        TripSignalKind.HUNGRY->"M7 3v8M5 3v5a2 2 0 0 0 4 0V3M7 11v10M16 3c-2 2-2 6 0 8v10"
        TripSignalKind.SMOKING->"M3 16h13v3H3zM19 16v3M19 7c0 2 2 2 2 4M16 8c0 2 2 2 2 4"
        TripSignalKind.NURSING->"M9 3h6M10 3v3a4 4 0 0 0-2 3.5V20a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V9.5A4 4 0 0 0 14 6V3"
        null->"M8 13V5.5a1.5 1.5 0 0 1 3 0V12M11 11.5v-2a1.5 1.5 0 0 1 3 0V12M14 10.5a1.5 1.5 0 0 1 3 0V12M17 11.5a1.5 1.5 0 0 1 3 0V16a6 6 0 0 1-6 6h-2a6 6 0 0 1-5-2.7L4.5 15a1.5 1.5 0 0 1 2.5-1.7L8 15"
    }
    val path=remember(data) {PathParser().parsePathString(data).toPath()}
    Canvas(modifier) {scale(size.width/24f,size.height/24f,pivot=androidx.compose.ui.geometry.Offset.Zero) {
        drawPath(path,color,style=Stroke(1.8f,cap=StrokeCap.Round,join=StrokeJoin.Round))
    }}
}

@Composable
internal fun TripHandRaiseButton(onClick: ()->Unit,modifier: Modifier=Modifier.fillMaxWidth()) =
    TripJourneyBarButton("손들기",onClick,modifier) {SignalIcon(null,Modifier.size(CarTokens.Icon))}

@Composable
private fun TripJourneyBarButton(label: String,onClick: ()->Unit,modifier: Modifier,icon: @Composable ()->Unit) {
    Row(modifier.height(CarTokens.ButtonDrivingCompact).clip(RoundedCornerShape(CarTokens.ButtonRadius)).background(LocalCarPalette.current.background)
        .tripBorder(CarTokens.SelectedBorderWidth,LocalCarPalette.current.divider,CarTokens.ButtonRadius).carTap(onClick=onClick).semantics {contentDescription=label},
        horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap,Alignment.CenterHorizontally),verticalAlignment=Alignment.CenterVertically) {
        icon()
        TripText(label,style=CarType.Title)
    }
}

@Composable
internal fun TripSignalRequestPage(trip: TripDetail,state: TripSignalState,next: TripRouteStop?,actions: TripUiActions,
    driving: Boolean=false,gear: TripGear=if(driving)TripGear.DRIVE else TripGear.PARK,onBack: ()->Unit) = TripSurface {
    var showLatest by remember(trip.id) {mutableStateOf(false)}
    if(showLatest && state.latestGroupSignal!=null) {
        TripGroupSignalStatusPage(trip,state.latestGroupSignal,state,actions) {showLatest=false}
        return@TripSurface
    }
    LaunchedEffect(trip.id) {actions.refreshSignals()}
    LaunchedEffect(trip.id,state.checked,state.hasActiveSignal,next?.key,next?.lat,next?.lng) {
        if(state.checked && !state.hasActiveSignal && state.result==null)actions.loadSignalCandidates(state.kind)
    }
    if(state.hasActiveSignal && state.ongoing!=null) {
        TripDrivingSignalPage(trip,state.ongoing,state,actions,onBack)
        return@TripSurface
    }
    if(!state.checked || state.hasActiveSignal) {
        Column(Modifier.fillMaxSize().padding(CarTokens.Frame),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
            TripHeading("손들기",onBack=onBack)
            TripText(if(state.hasActiveSignal)"손들기 진행 중" else state.hint ?: "손들기 확인 중",maxLines=3)
            CarButton("다시 불러오기",actions.refreshSignals)
        }
        return@TripSurface
    }
    val narrow=LocalTripLayoutWidth.current<CarTokens.Breakpoint
    val palette=LocalCarPalette.current
    val candidates=state.candidates.filter {it.verdict=="ahead"}.let {if(driving)it.take(DRIVING_SIGNAL_CANDIDATES) else it}
    var selection by remember(state.kind,candidates) {mutableStateOf(candidates.firstOrNull())}
    val locked=state.sending || state.sentId!=null
    Column(Modifier.fillMaxSize().padding(CarTokens.Frame),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
        TripHeading("손들기",trip.title,onBack) {CarGearBadge(gear)}
        TripAdaptiveRow(Modifier.weight(1f).then(if(narrow)Modifier.verticalScroll(rememberScrollState()) else Modifier),narrow=narrow,gap=CarTokens.Gap) {
            Column(Modifier.weight(1f).then(if(narrow)Modifier else Modifier.fillMaxHeight().verticalScroll(rememberScrollState())),
                verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                TripText("무엇이 필요하세요?",style=CarType.Section)
                TripSignalKind.entries.chunked(3).forEach {row->
                    Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                        row.forEach {kind->
                            val checked=kind==state.kind
                            CarChoiceTile(kind.label,checked,CarSymbol.Pin,Modifier.weight(1f),enabled=!locked,
                                iconContent={SignalIcon(kind,Modifier.size(CarTokens.Icon),if(checked)palette.onInk else palette.text)}) {
                                actions.loadSignalCandidates(kind)
                            }
                        }
                    }
                }
                if(driving)TripText("주행 중에는 추천 ${DRIVING_SIGNAL_CANDIDATES}곳만 보여요",secondary=true,maxLines=2)
                else if(state.latestGroupSignal!=null)CarButton("최근 손들기 결과",{showLatest=true},Modifier.fillMaxWidth())
            }
            Column(Modifier.weight(1f).then(if(narrow)Modifier else Modifier.fillMaxHeight()),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                TripText("들를 곳",style=CarType.Section)
                if(!driving)TripSignalFacility.entries.chunked(3).forEach {row->
                    Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                        row.forEach {facility->
                            val selected=facility in state.requiredFacilities
                            CarFilterChip(facility.label,selected,{
                                actions.filterSignalFacilities(if(selected)state.requiredFacilities-facility else state.requiredFacilities+facility)
                            },Modifier.weight(1f),enabled=!locked)
                        }
                    }
                }
                TripText(when {
                    state.loading->"가까운 곳 찾는 중"
                    state.hint!=null->state.hint
                    candidates.firstOrNull()?.basis=="heading"->"내 차 앞에서 찾은 곳"
                    candidates.firstOrNull()?.leaderCarId!=null->"${trip.cars.firstOrNull {it.id==candidates.first().leaderCarId}?.name ?: "맨 앞 차"} 앞에서 찾은 곳"
                    next!=null->"${next.name}까지 가는 길"
                    else->"현재 위치에서 찾은 곳"
                },secondary=true,maxLines=2)
                if(state.hint!=null && !state.loading)CarButton("다시 찾기",{actions.loadSignalCandidates(state.kind)},enabled=!locked)
                val places: @Composable ()->Unit={
                    candidates.forEach {candidate->
                        SignalPlaceRow(candidate.name,signalCandidateMeta(candidate),selection==candidate,!locked) {selection=candidate}
                    }
                    SignalPlaceRow("장소는 운전자가 선택",emptyList(),selection==null,!locked,dashed=true) {selection=null}
                }
                Column(Modifier.fillMaxWidth().then(if(narrow)Modifier else Modifier.weight(1f).verticalScroll(rememberScrollState())),
                    verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {places()}
                state.result?.let {TripText(it,color=palette.accent,maxLines=CarMessageLines)}
                CarButton(when {
                    state.sentId!=null->"보냈어요"
                    state.sending->"보내는 중"
                    else->"${state.kind.label} 요청 보내기"
                },{actions.sendSignal(selection?.destination)},Modifier.fillMaxWidth(),primary=true,enabled=!locked && !state.loading)
            }
        }
    }
}

internal fun signalCandidateMeta(candidate: SignalCandidate): List<String> = buildList {
    val distance=if(candidate.basis=="heading")candidate.fromRequesterMeters else candidate.fromLeadMeters ?: candidate.fromRequesterMeters
    add(String.format(Locale.KOREAN,"%.1f km 앞",distance/1000))
    candidate.detourSeconds?.takeIf {it>=0}?.let {add("예상 "+(if(it>=60)"${kotlin.math.ceil(it/60).toInt()}분" else "${it.toInt()}초")+" 추가")}
    addAll(listOfNotNull(candidate.routeName,candidate.direction))
    addAll(TripSignalFacility.entries.filter {it.wire in candidate.facilities}.map {it.label})
}

@Composable
private fun SignalPlaceRow(name: String,meta: List<String>,on: Boolean,enabled: Boolean,dashed: Boolean=false,onClick: ()->Unit) {
    CarCard(Modifier.carTap(enabled=enabled,onClick=onClick).semantics {contentDescription=name;selected=on},
        selected=on,outlined=!on && !dashed,dashed=dashed) {
        TripText(name,style=CarType.Body.copy(fontWeight=FontWeight.Bold),maxLines=2)
        CarMetadata(meta)
    }
}

@Composable
internal fun TripDrivingSignalPage(trip: TripDetail,signal: TripSignal,state: TripSignalState,actions: TripUiActions,onBack: (()->Unit)?=null) {
    if(signal.isGroupDecision) {
        TripGroupSignalStatusPage(trip,signal,state,actions,onBack ?: actions.dismissSignal)
        return
    }
    val p=LocalCarPalette.current
    val driver=trip.signalCar(signal)
    val requester=trip.members.firstOrNull {it.id==signal.accountId}?.name ?: "일행"
    val total=signal.driverTotal ?: trip.cars.size
    val majority=signal.destination!=null && signal.hasMajority(total,trip.me?.id)
    val vote=state.voted ?: signal.myVote
    val done=state.result ?: vote?.let {if(it=="pass")"‘다음에’를 선택했어요" else "동의했어요"}
    // 수신 오버레이(onBack 없음)만 자동으로 닫힌다. 남은 초는 그룹 손들기와 같은 카운트다운으로 보인다.
    val remaining=if(onBack==null)rememberTripSignalCountdown(signal.id,running=true,onTimeout=actions.dismissSignal) else null
    TripSurface {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(CarTokens.Frame),
            verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
            TripHeading("손들기",remaining?.let(::tripSignalCloseLabel) ?: "진행 중인 요청",onBack)
            CarCard(tone=CarCardTone.INK,radius=CarTokens.RadiusHero) {
                Row(horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalAlignment=Alignment.CenterVertically) {
                    Box(Modifier.size(CarTokens.ButtonDrivingCompact).background(p.accent,RoundedCornerShape(CarTokens.RadiusCard)),contentAlignment=Alignment.Center) {
                        SignalIcon(signal.kind,Modifier.size(CarTokens.Touch),p.onInk)
                    }
                    Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                        CarMetadata(listOf(driver?.numberedName ?: "일행의 차",requester),style=CarType.Body)
                        TripText(signal.kind.headline,style=CarType.DrivingHero,maxLines=3)
                    }
                }
            }
            CarCard(tone=CarCardTone.SOFT) {
                if(signal.destination!=null)TripText("들를 곳",style=CarType.Label,secondary=true)
                TripText(signal.destination?.name ?: "가까운 안전한 곳에 세워 주세요",style=CarType.SignalPlace,maxLines=3)
                TripText(if(signal.destination==null)"세울 곳은 운전자가 정해요" else "과반 동의 시 모든 차 경로에 추가해요",maxLines=3)
                if(signal.destination!=null) {
                    TripText(if(signal.resolution==null)"동의 ${signal.agreeCount(trip.me?.id)}/$total" else "동의 ${signal.agreeCount(trip.me?.id)}명",style=CarType.Title)
                    TripText(if(majority)"과반 동의" else if(signal.resolution!=null)"운전자 답변을 기다려요" else "${total/2+1}명 동의 시 추가",secondary=true,maxLines=2)
                }
            }
            if(done!=null)CarInfoHint(done)
            if(signal.inProgress && signal.destination==null && signal.accountId==trip.me?.id)Row(horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                SignalVoteButton("취소",false,!state.ending,Modifier.weight(1f)) {actions.finishSignal("cancelled")}
                SignalVoteButton("완료",true,!state.ending,Modifier.weight(1f)) {actions.finishSignal("completed")}
            }
            else if(signal.destination==null)SignalVoteButton("확인",true,true,Modifier.fillMaxWidth(),onBack ?: actions.dismissSignal)
            else if(vote==null && !majority && !trip.signalFromMyCar(signal) && trip.myCar?.isMine==true && (done==null || done=="답을 보내지 못했어요. 다시 눌러 주세요"))Row(horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                SignalVoteButton("다음에",false,!state.voting,Modifier.weight(1f)) {
                    io.wegoh.app.nativeauth.WegoLog.i("WegoH","trip.signals: vote tapped choice=pass");if(onBack==null)actions.voteSignal("pass") else actions.voteOngoingSignal("pass")
                }
                SignalVoteButton("동의",true,!state.voting,Modifier.weight(1f)) {
                    io.wegoh.app.nativeauth.WegoLog.i("WegoH","trip.signals: vote tapped choice=agree");if(onBack==null)actions.voteSignal("agree") else actions.voteOngoingSignal("agree")
                }
            }
        }
    }
}

@Composable
private fun SignalVoteButton(label: String,primary: Boolean,enabled: Boolean,modifier: Modifier,onClick: ()->Unit) {
    CarButton(label,onClick,modifier.heightIn(min=CarTokens.ButtonDriving),primary=primary,enabled=enabled,textStyle=CarType.SignalAction)
}

@Composable
internal fun TripSignalDialog(onDismiss: ()->Unit,content: @Composable ()->Unit) {
    Dialog(onDismissRequest=onDismiss,properties=DialogProperties(usePlatformDefaultWidth=false)) {ObserveOwnedCarWindow();content()}
}

@Composable
internal fun TripSignalOverlay(trip: TripDetail,signal: TripSignal,state: TripSignalState,actions: TripUiActions,gear: TripGear=TripGear.UNKNOWN) {
    BackHandler(onBack=actions.dismissSignal)
    Box(Modifier.fillMaxSize().zIndex(Float.MAX_VALUE)) {
        Box(Modifier.matchParentSize().pointerInput(Unit) {
            awaitPointerEventScope {while(true)awaitPointerEvent().changes.forEach {it.consume()}}
        })
        if(signal.isGroupDecision)TripGroupSignalResponsePage(trip,signal,state,actions,gear)
        else TripDrivingSignalPage(trip,signal,state,actions)
    }
}

/** 받은 손들기 화면이 스스로 닫히기까지의 시간. 개인·그룹 손들기가 같은 값을 쓴다. */
internal const val TRIP_SIGNAL_AUTO_CLOSE_SECONDS=15

internal fun tripSignalCloseLabel(remaining: Int)="${remaining}초 뒤 닫혀요"

/** 받은 손들기 화면의 남은 초. [running]이 false면 멈추고, 0이 되면 [onTimeout]을 한 번 부른다. */
@Composable
internal fun rememberTripSignalCountdown(signalId: String,running: Boolean,onTimeout: ()->Unit): Int {
    var remaining by rememberSaveable(signalId) {mutableIntStateOf(TRIP_SIGNAL_AUTO_CLOSE_SECONDS)}
    val currentTimeout by rememberUpdatedState(onTimeout)
    LaunchedEffect(signalId,running) {
        if(!running)return@LaunchedEffect
        while(remaining>0) {delay(1000);remaining--}
        currentTimeout()
    }
    return remaining
}

/** 멀티 윈도우에서 내비에 포커스가 있어도 보이는 WegoH 창에는 손들기를 띄운다. 응답 터치가 포커스를 가져온다. */
internal fun showsTripSignalOverlay(window: CarWindowState?)=window==null || window.visible

@Composable
internal fun TripSignalsHost(state: TripsPageState,actions: TripUiActions,setupAllowed: Boolean) {
    val currentActions by rememberUpdatedState(actions)
    val context=LocalContext.current
    LaunchedEffect(state.selectedId,state.list?.trips?.map {it.id to it.state},state.eventDriven) {
        if(state.detail?.state=="active" || state.list?.trips?.any {it.state=="active"}==true)
            while(true) {currentActions.refreshSignals();delay(if(state.eventDriven)30000L else 3000L)}
    }
    val signal=state.signals.overlay
    val signalControls=state.canUseSignalResponses(setupAllowed)
    LaunchedEffect(state.signals.result,signalControls) {
        if(signalControls && state.signals.result!=null && signal==null) {
            android.widget.Toast.makeText(context,state.signals.result,android.widget.Toast.LENGTH_SHORT).show()
            delay(5000);currentActions.dismissSignal()
        }
    }
    val trip=state.signals.overlayTrip ?: state.detail
    val window=LocalCarWindowVisibility.current?.state
    if(signalControls && signal!=null && trip!=null && showsTripSignalOverlay(window))key(signal.id) {
        TripSignalOverlay(trip,signal,state.signals,actions,state.gear)
    }
}
