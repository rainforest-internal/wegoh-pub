package io.wegoh.app.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import io.wegoh.app.*
import io.wegoh.app.nativeauth.TripDetail

@Composable
internal fun TripDrivingHost(state: TripsPageState,actions: TripUiActions,onRootBack: ()->Unit,setupAllowed: Boolean=false,
    voice: (@Composable (TripDetail,Boolean,Modifier)->Unit)?=null) = TripSurface {
    BackHandler(onBack=onRootBack)
    var signal by remember(state.selectedId) {mutableStateOf(false)}
    var signalBlocked by remember(state.selectedId) {mutableStateOf<String?>(null)}
    LaunchedEffect(state.signals.overlay?.id) {if(state.signals.overlay?.isGroupDecision==true)signal=false}
    val trip=state.detail?.takeIf {it.state=="active"}
    val signalControls=state.canUseSignalControls(setupAllowed)
    LaunchedEffect(signalControls) {if(!signalControls)signal=false}
    val openSignal: ()->Unit={
        if(signalControls && state.isCurrent)signal=true
        else signalBlocked=when {
            state.gear!=TripGear.DRIVE->"P단에서 보낼 수 있어요"
            !state.carUxKnown->"주행 제한 확인 중"
            !state.isCurrent->"여행 확인 중"
            else->"지금은 보낼 수 없어요"
        }
    }
    Box(Modifier.fillMaxSize().padding(CarTokens.Frame)) {
        Box(Modifier.fillMaxSize().then(if(state.signals.overlay?.isGroupDecision==true)Modifier.clearAndSetSemantics {} else Modifier)) {
        if(trip!=null) {
            // The reduced composer replaces the dashboard in place: no full-screen popup while driving.
            if(signal && signalControls)TripSignalRequestPage(trip,state.signals,trip.signalRouteStop(state.driving),actions,
                driving=state.usesDrivingSignalComposer(),gear=state.gear) {signal=false}
            // 워키토키는 D단에서만 연다. N·R·미확인 기어는 대시보드만 같고 조작을 넓히지 않는다(비활성 버튼).
            else TripDrivingDashboard(trip,state,openSignal,voice=if(voice==null || state.gear!=TripGear.DRIVE)null else {modifier->
                voice(trip,(setupAllowed || state.carUxKnown) && state.isCurrent && state.signals.overlay==null,modifier)
            })
            signalBlocked?.let {reason->CarPopup("손들기",{signalBlocked=null},body={CarText(reason,maxLines=2)},
                actions={CarButton("닫기",{signalBlocked=null})})}
        } else CarEmptyState(when {state.busy->"여행 확인 중";state.list==null->"여행을 확인할 수 없어요";else->"진행 중인 여행이 없어요"},
            Modifier.fillMaxSize(),detail="P단에서 확인할 수 있어요",symbol=CarSymbol.Route)
        }
        TripSignalsHost(state,actions,setupAllowed)
    }
}

@Composable
internal fun TripDrivingDashboard(trip: TripDetail,state: TripsPageState,onSignal: ()->Unit,
    voice: (@Composable (Modifier)->Unit)?=null) {
    if(trip.routeContractVersion==2 && trip.myCar?.routePlan?.phase!="shared") {
        TripSegmentDrivingDashboard(trip,state,voice,onSignal)
        return
    }
    val car=trip.myCar
    val drive=state.driving
    val stops=car?.let {TripRouteOrder.resolve(TripRouteOrder.initial(trip,it),trip,it)}.orEmpty()
    val target=stops.firstOrNull {it.key==drive.targetKey}
    val next=tripNextStop(stops,drive)
    val total=state.liveCourseId=="trip-total-v1"
    val courseId=state.liveCourseId?.takeUnless {total} ?: target?.let {tripStopCourse(it,stops)} ?: next?.let {tripStopCourse(it,stops)}
    val course=trip.courses.orEmpty().firstOrNull {it.packId==courseId}
    val route=if(course==null)stops else stops.filter {tripStopCourse(it,stops)==course.packId || it.item.type=="signal"}
    val result=(if(!total && drive.phase==TripDrivingPhase.ROUTE_COMPLETE)state.courseResults[drive.completedCourse] else state.liveCourseScore).takeIf {state.isCurrent}
    val presentation=remember(trip.id) {TripVoicePresentation()}
    CompositionLocalProvider(LocalTripVoicePresentation provides presentation) {
    BoxWithConstraints(Modifier.fillMaxSize().semantics {contentDescription="주행 전용 화면"}) {
        val short=maxHeight<CarTokens.DrivingShortBreakpoint
        val narrow=maxWidth<CarTokens.Breakpoint
        val controls=if(short)CarTokens.ButtonDrivingCompact else CarTokens.ButtonDriving
        val gap=if(short)CarTokens.SpaceMedium else CarTokens.Gap
        Column(Modifier.fillMaxSize(),verticalArrangement=Arrangement.spacedBy(gap)) {
            Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                    TripText(trip.title,style=if(narrow)CarType.Section else CarType.Title,maxLines=1)
                    TripText(course?.let {"지금 ${trip.courses.orEmpty().indexOf(it)+1}. ${it.title}"} ?: "내 차 경로",style=CarType.Caption,maxLines=1,secondary=true)
                }
                CarGearBadge(state.gear)
            }
            CarCard(padding=PaddingValues(if(short)CarTokens.SpaceMedium else CarTokens.Gap)) {
                if(!presentation.receiving)KakaoCourseMap(route,Modifier.height(CarTokens.MapDrivingHeight),numbersOnly=true,vehicle=drive.position,focus=next,follow=true,
                    others=courseMapOtherCars(trip,state.otherCars))
                if(!short || presentation.receiving)CarRouteStrip(route,drive,compact=true,showPosition=true,companions=tripCompanionMarkers(trip,route))
                TripText(next?.let {"다음 ${it.name}"} ?: "경로 완료",style=if(short)CarType.Section else CarType.Hero,maxLines=2)
                CarMetadata(tripNextRemainingLabels(drive,next),style=if(short)CarType.Caption else CarType.Label)
                if(!short || presentation.receiving)TripCompanionProgress(trip,currentTripDisplay(trip),tripCompanionScores(trip,state))
            }
            if(presentation.receiving)TripVoiceReceivingCard(presentation.ui,parked=false,modifier=Modifier.weight(1f))
            else CarCard(Modifier.weight(1f),tone=CarCardTone.INK,padding=PaddingValues(if(short)CarTokens.SpaceMedium else CarTokens.Frame),radius=CarTokens.RadiusHero) {
                Row(Modifier.fillMaxSize(),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalAlignment=Alignment.CenterVertically) {
                    Column(Modifier.weight(2f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                        TripText(when {total->"여행 안전운전 점수";result?.completed==true->"경로 안전운전 결과";else->"안전운전 점수"},style=if(short)CarType.Label else CarType.Section,maxLines=2)
                        if(result?.score!=null)CarMetadata(listOf("급가속 ${result.accelerations}회","급감속 ${result.brakings}회"),
                            style=if(short)CarType.Caption else CarType.Label)
                    }
                    BoxWithConstraints(Modifier.weight(1f).fillMaxHeight(),contentAlignment=Alignment.Center) {
                        val density=androidx.compose.ui.platform.LocalDensity.current
                        val large=with(density) {maxWidth>=CarType.DrivingScore.fontSize.toDp()*2 && maxHeight>=CarType.DrivingScore.lineHeight.toDp()}
                        if(result?.score!=null)Row(Modifier.semantics(mergeDescendants=true) {contentDescription="${result.score}점"},
                            horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall),verticalAlignment=Alignment.Bottom) {
                            TripText(result.score.toString(),style=if(large)CarType.DrivingScore else CarType.DrivingHero)
                            TripText("점",style=CarType.Label)
                        } else TripText("측정 대기",style=CarType.Title,maxLines=2)
                    }
                }
            }
            Row(Modifier.fillMaxWidth().height(controls),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                CarButton("손들기",onSignal,Modifier.weight(1f).fillMaxHeight(),variant=CarButtonStyle.SOFT,textStyle=CarType.Title)
                if(voice!=null)voice(Modifier.weight(1f).fillMaxHeight())
                else CarButton("워키토키",{},Modifier.weight(1f).fillMaxHeight(),primary=true,enabled=false,textStyle=CarType.Title)
            }
        }
    }
}
}
