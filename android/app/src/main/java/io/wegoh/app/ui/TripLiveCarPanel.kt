@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package io.wegoh.app.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.Dp
import io.wegoh.app.TripsPageState
import io.wegoh.app.nativeauth.*

internal class TripVoicePresentation {
    var ui by mutableStateOf<TripInlineVoiceUi?>(null)
    val receiving get()=ui?.let {it.permitted && it.participating && it.phase==TripInlineVoicePhase.HEARING}==true
}

internal val LocalTripVoicePresentation=staticCompositionLocalOf<TripVoicePresentation?> {null}

@Composable
internal fun TripLiveCarPanel(trip: TripDetail,state: TripsPageState,enabled: Boolean,onScoreRefresh: ()->Unit,
    onMusic: (() ->Unit)?,onSignal: (() ->Unit)?,voice: (@Composable (Modifier)->Unit)?,modifier: Modifier=Modifier) {
    val presentation=remember(trip.id) {TripVoicePresentation()}
    val display=currentTripDisplay(trip)
    CompositionLocalProvider(LocalTripVoicePresentation provides presentation) {
        Column(modifier,verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
            Column(Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()),
                verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                trip.myCar?.let {TripLiveOwnCar(trip,it,currentTripRemotePolicy(state))}
                if(presentation.receiving)TripVoiceReceivingCard(presentation.ui,parked=true)
                else {
                    trip.cars.filter {it.id!=trip.myCar?.id}.forEach {car->
                        CarCard(tone=CarCardTone.OUTLINED,padding=PaddingValues(CarTokens.SpaceMedium)) {
                            Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),verticalAlignment=Alignment.CenterVertically) {
                                CarAvatar(car.ordinal?.let {"${it}호"} ?: car.driverName,CarAvatarTone.INK)
                                Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                                    TripText(car.numberedName,style=CarType.Label,maxLines=2)
                                    CarMetadata(listOfNotNull("${car.driverName} 운전",car.passengers.takeIf {it.isNotEmpty()}?.let {"동승 ${it.size}명"},
                                        companionLabel(display,car.id) ?: car.routeStatus?.let {tripSegmentPhaseLabel(it.phase)}),style=CarType.Caption)
                                }
                            }
                        }
                    }
                    TripLiveScoreSummary(trip,state,enabled,onScoreRefresh)
                    val musicBar=LocalTripMusicBar.current
                    if(musicBar!=null)musicBar(trip,onMusic?.takeIf {enabled},Modifier.fillMaxWidth())
                    else if(onMusic!=null)CarCard(tone=CarCardTone.OUTLINED,padding=PaddingValues(CarTokens.SpaceSmall)) {
                        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),verticalAlignment=Alignment.CenterVertically) {
                            CarIcon(CarSymbol.Music,color=LocalCarPalette.current.accent)
                            Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                                TripText("여행 음악",style=CarType.Label)
                                val music=display?.music
                                CarMetadata(listOfNotNull(music?.djName?.let {"DJ $it"},music?.name,music?.trackCount?.let {"링크 ${it}개"})
                                    .ifEmpty {listOf("음악 링크")},style=CarType.Caption)
                            }
                            CarIconAction("여행 음악",CarSymbol.Next,onMusic,enabled)
                        }
                    }
                }
            }
            TripLiveActionBar(onSignal,voice)
        }
    }
}

@Composable
private fun TripLiveOwnCar(trip: TripDetail,car: TripCar,policy: TripRemotePolicy?) {
    CarCard(padding=PaddingValues(CarTokens.SpaceMedium)) {
        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),verticalAlignment=Alignment.CenterVertically) {
            CarIcon(CarSymbol.Car,color=LocalCarPalette.current.accent)
            Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                TripText(if(car.isMine)"내 차" else "타고 있는 차",style=CarType.Caption,color=LocalCarPalette.current.accent)
                TripText(car.numberedName,style=CarType.Section,maxLines=2)
            }
        }
        val people=listOf(Triple(car.driverId,car.driverName,"운전"))+car.passengers.map {Triple(it.id,it.name,"동승")}
        FlowRow(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),
            verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),maxItemsInEachRow=3) {
            people.forEach {(id,name,kind)->
                Row(Modifier.weight(1f).widthIn(min=CarTokens.RouteSegmentMinWidth),
                    horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall),verticalAlignment=Alignment.CenterVertically) {
                    CarAvatar(name,if(id==car.driverId)CarAvatarTone.INK else CarAvatarTone.SOFT)
                    Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                        CarMetadata(listOfNotNull(name,"나".takeIf {id==trip.me?.id}),secondary=false)
                        CarMetadata(listOfNotNull(kind,tripRoleLabel(trip.members.firstOrNull {it.id==id}?.role)),style=CarType.Caption)
                    }
                }
            }
        }
        TripDivider()
        Column(verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
            CarMetadata(listOfNotNull("동승자 리모컨","iPhone에서 변경".takeIf {car.isMine}),style=CarType.Caption,secondary=false)
            TripText(tripRemotePolicyLabel(policy),style=CarType.Caption,secondary=true,maxLines=3)
        }
    }
}

@Composable
private fun TripLiveScoreSummary(trip: TripDetail,state: TripsPageState,enabled: Boolean,onRefresh: ()->Unit) {
    val rows=tripLiveScoreRows(trip,state)
    CarCard(tone=CarCardTone.OUTLINED,padding=PaddingValues(CarTokens.SpaceMedium)) {
        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall),verticalAlignment=Alignment.CenterVertically) {
            TripText("안전운전 점수",Modifier.weight(1f),style=CarType.Label)
            TripText("여행 전체",style=CarType.Caption,secondary=true)
            CarIconAction("점수 새로고침",CarSymbol.Refresh,onRefresh,enabled && !state.drivingVersusLoading)
        }
        Column(verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
        rows.forEach {row->
            Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),verticalAlignment=Alignment.CenterVertically) {
                Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                    CarMetadata(listOfNotNull(row.name,"내 차".takeIf {row.own}),secondary=false)
                    if(row.score==null)TripText(row.status,style=CarType.Caption,secondary=true,maxLines=3)
                }
                TripText(row.score?.let {"${it}점"} ?: "—",style=CarType.Section,color=LocalCarPalette.current.accent)
            }
        }
        }
        if(rows.isEmpty())TripText("함께 가는 차가 없어요",style=CarType.Caption,secondary=true,maxLines=2)
        state.drivingVersusNotice?.let {TripText(it,style=CarType.Caption,secondary=true,maxLines=CarMessageLines)}
    }
}

@Composable
internal fun TripVoiceReceivingCard(ui: TripInlineVoiceUi?,parked: Boolean,modifier: Modifier=Modifier) {
    CarCard(modifier,tone=CarCardTone.INK,radius=CarTokens.RadiusCard) {
        Box(if(parked)Modifier else Modifier.fillMaxSize(),contentAlignment=Alignment.Center) {
        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalAlignment=Alignment.CenterVertically) {
            CarIcon(CarSymbol.Microphone,color=LocalCarPalette.current.routeOnInk)
            Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                TripText("워키토키 듣는 중",style=CarType.Section,maxLines=2)
                ui?.notice?.let {TripText(it,style=CarType.Label,secondary=true,maxLines=3)}
            }
        }
        }
    }
}

@Composable
internal fun TripLiveActionBar(onSignal: (() ->Unit)?,voice: (@Composable (Modifier)->Unit)?) {
    Row(Modifier.fillMaxWidth().height(CarTokens.ButtonDrivingCompact),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
        Box(Modifier.weight(1f).fillMaxHeight()) {
            if(onSignal!=null)TripHandRaiseButton(onSignal,Modifier.fillMaxSize())
            else CarButton("손들기",{},Modifier.fillMaxSize(),enabled=false,variant=CarButtonStyle.SOFT)
        }
        if(voice!=null)voice(Modifier.weight(1f).fillMaxHeight())
        else CarButton("워키토키",{},Modifier.weight(1f).fillMaxHeight(),primary=true,enabled=false,icon=CarSymbol.Microphone)
    }
}

@Composable
internal fun TripSharedRouteCard(trip: TripDetail,state: TripsPageState,course: TripCourse?,stops: List<io.wegoh.app.TripRouteStop>,
    next: io.wegoh.app.TripRouteStop?,enabled: Boolean,actions: io.wegoh.app.TripUiActions,reserve: Dp,onFullRoute: ()->Unit) {
    val car=trip.myCar
    val route=stops.filter {it.item.courseId==course?.packId || it.item.type=="signal"}
    CarCard(tone=CarCardTone.INK,radius=CarTokens.RadiusHero,padding=PaddingValues(CarTokens.Frame)) {
        // 주요 동작은 지도 위에 두어 높이가 모자라도 잘리지 않게 한다(Pleos 즉시성). 지도가 남은 높이에 맞춰 줄어든다.
        TripFixedRouteColumn(reserve,top={
            Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),verticalAlignment=Alignment.CenterVertically) {
                TripText(course?.let {"공유 경로 ${trip.courses.orEmpty().indexOf(it)+1}"} ?: "우리 차 경로",
                    Modifier.weight(1f),style=CarType.Label,maxLines=2)
                CarButton("전체 경로",onFullRoute,variant=CarButtonStyle.INK_OUTLINE,enabled=enabled)
            }
            TripText("다음 장소",style=CarType.Label,secondary=true)
            TripText(next?.name ?: "경로 완료",style=CarType.Hero,maxLines=2)
            CarMetadata(listOfNotNull(course?.title)+tripNextRemainingLabels(state.driving,next))
            if(car?.isMine==true) {
                if(car.routePlan?.awaitingJoinCourseCompletion==true) {
                    TripText("공유 경로 진행 중",secondary=true,maxLines=2)
                    TripCompleteCourseButton(trip,enabled && state.gear==io.wegoh.app.TripGear.PARK,state.busy,actions.completeCourse)
                } else Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                    next?.let {stop->CarButton("길 안내",{actions.navigate(stop)},Modifier.weight(1.6f),
                        variant=CarButtonStyle.ON_INK,enabled=enabled && stop.canNavigate,icon=CarSymbol.Navigate,
                        accessibility="${stop.name} 길 안내")}
                    CarButton("도착했어요",actions.arrive,Modifier.weight(1f),variant=CarButtonStyle.INK_OUTLINE,
                        enabled=enabled && state.gear==io.wegoh.app.TripGear.PARK && car.routePlan?.next!=null && car.routePlan.phase=="shared")
                }
                if(car.routePlan?.next!=null)tripArrivalGearHint(state.gear)?.let {TripText(it,secondary=true,maxLines=3)}
            }
        },map={
            KakaoCourseMap(route,Modifier.height(CarTokens.MapPreviewHeight),interactive=enabled && state.gear==io.wegoh.app.TripGear.PARK,
                vehicle=state.driving.position,focus=next,others=courseMapOtherCars(trip,state.otherCars))
        },strip={
            CarRouteStrip(route,state.driving,onInk=true,compact=true,companions=tripCompanionMarkers(trip,route))
        },extra={TripCompanionProgress(trip,currentTripDisplay(trip))})
    }
}
