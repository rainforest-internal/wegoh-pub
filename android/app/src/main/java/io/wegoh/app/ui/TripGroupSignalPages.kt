@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package io.wegoh.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import kotlinx.coroutines.delay
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.wegoh.app.*
import io.wegoh.app.nativeauth.*

internal fun tripResponseSourceLabel(response: TripGroupResponse): String? = when(response.responseSource) {
    "iphone"->"iPhone 응답"
    "native"->"차량 응답"
    else->null
}

internal fun tripResponseSummary(response: TripGroupResponse): String = when(response.choice) {
    "agree"->if(response.responderName==null)"${response.carName}에서 동의했어요" else "${response.carName}의 ${response.responderName}님이 동의했어요"
    "pass"->if(response.responderName==null)"${response.carName}에서 ‘다음에’를 선택했어요" else "${response.carName}의 ${response.responderName}님이 ‘다음에’를 선택했어요"
    else->"${response.carName}의 답을 기다려요"
}

internal fun tripSignalCandidateContext(signal: TripSignal): List<String> {
    val details=signal.candidateDetails ?: return emptyList()
    return listOfNotNull(details.fromLeadMeters?.let {String.format(java.util.Locale.KOREAN,"맨 앞 차에서 %.1f km",it/1000.0)},
        details.detourSeconds?.takeIf {it>=0}?.let {"예상 ${kotlin.math.ceil(it/60.0).toInt()}분 추가"})
}

@Composable
internal fun TripGroupSignalResponsePage(trip: TripDetail,signal: TripSignal,state: TripSignalState,actions: TripUiActions,gear: TripGear=TripGear.UNKNOWN) {
    val p=LocalCarPalette.current
    // A submitted response must finish, and a failure must stay available for retry.
    val remaining=rememberTripSignalCountdown(signal.id,running=!state.voting && state.result==null,onTimeout=actions.dismissSignal)
    val requester=trip.members.firstOrNull {it.id==signal.accountId}
    val car=trip.cars.firstOrNull {it.id==signal.requesterCarId}
    val stops=trip.myCar?.let {TripRouteOrder.resolve(TripRouteOrder.initial(trip,it),trip,it)}.orEmpty()
    TripLayoutRoot {
        Column(Modifier.fillMaxSize().background(p.background).padding(CarTokens.Frame),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
            Column(Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalAlignment=Alignment.CenterVertically) {
                    CarAvatar(requester?.name ?: car?.driverName ?: "일행")
                    Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                        TripText(signal.kind.headline,style=CarType.Title,maxLines=2)
                        TripText("${requester?.name ?: car?.driverName ?: "일행"}님의 요청",style=CarType.Section,maxLines=2)
                        TripText(car?.numberedName ?: "다른 차",style=CarType.Label,secondary=true,maxLines=2)
                    }
                    Column(horizontalAlignment=Alignment.End,verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                        if(gear==TripGear.PARK || gear==TripGear.DRIVE)CarGearBadge(gear)
                        if(!state.voting && state.result==null)TripText(tripSignalCloseLabel(remaining),style=CarType.Label,secondary=true)
                    }
                }
                CarCard(tone=CarCardTone.SOFT) {
                    TripText("들를 곳",style=CarType.Label,secondary=true)
                    TripText(signal.destination?.name.orEmpty(),style=CarType.SignalPlace,maxLines=3)
                    FlowRow(horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),
                        verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                        CarMetadata(tripSignalCandidateContext(signal))
                        signal.candidateDetails?.let {details->
                            CarMetadata(listOfNotNull(details.routeName,details.direction))
                        }
                    }
                    signal.destination?.let {destination->
                        val proposed=TripRouteStop(TripRouteItem("signal",signal.id),destination.name,destination.latitude,destination.longitude)
                        val next=stops.firstOrNull {it.item==trip.myCar?.routeNext} ?: tripNextStop(stops,TripDrivingState())
                        val at=stops.indexOfFirst {it.key==next?.key}.takeIf {it>=0} ?: stops.size
                        val preview=stops.toMutableList().apply {add(at,proposed)}
                        SignalRoutePreview(preview,planned=true)
                    }
                    TripText("전원 동의 시 다음 목적지 앞에 추가해요",style=CarType.Label,maxLines=2)
                    FlowRow(horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),
                        verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                        signal.groupVotes?.let {TripText("동의 ${it.agree}/${it.total}",style=CarType.Label)}
                        if(trip.canRespondToSignal(signal))
                            CarStatusPill("내 차 응답 대기",kind=CarStatusTone.SOFT)
                    }
                }
                state.result?.let {TripText(it,maxLines=CarMessageLines)}
                if(state.voting)TripText("답을 보내고 있어요",maxLines=2)
            }
            Row(Modifier.fillMaxWidth().height(CarTokens.ButtonDriving),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                CarButton("다음에",{actions.voteSignal("pass")},Modifier.weight(1f).fillMaxHeight(),
                    enabled=trip.canRespondToSignal(signal),textStyle=CarType.SignalAction,busy=state.voting)
                CarButton("동의",{actions.voteSignal("agree")},Modifier.weight(1f).fillMaxHeight(),primary=true,
                    enabled=trip.canRespondToSignal(signal),textStyle=CarType.SignalAction,busy=state.voting)
            }
            TripText("차마다 먼저 선택한 답을 보내요",style=CarType.Label,secondary=true,maxLines=2)
        }
    }
}

@Composable
private fun SignalRoutePreview(stops: List<TripRouteStop>,planned: Boolean=false) {
    val palette=LocalCarPalette.current
    CompositionLocalProvider(LocalCarPalette provides if(planned)palette.copy(divider=palette.accent) else palette) {
    if(stops.size>3)Box(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState())) {
        Box(Modifier.width(CarTokens.RouteCell*stops.size)) {
            CarRouteStrip(stops,TripDrivingState(),compact=true,showPosition=false,planned=planned)
        }
    } else CarRouteStrip(stops,TripDrivingState(),compact=true,showPosition=false,planned=planned)
    }
}

@Composable
private fun SignalStatusColumns(modifier: Modifier,narrow: Boolean,content: @Composable (Modifier)->Unit) {
    if(narrow)Column(modifier.fillMaxWidth().verticalScroll(rememberScrollState()),
        verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {content(Modifier.fillMaxWidth())}
    else Row(modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
        content(Modifier.weight(1f).fillMaxHeight())
    }
}

@Composable
internal fun TripGroupSignalStatusPage(trip: TripDetail,signal: TripSignal,state: TripSignalState,actions: TripUiActions,onBack: ()->Unit) = TripSurface {
    val narrow=LocalTripLayoutWidth.current<CarTokens.Breakpoint
    val requester=trip.members.firstOrNull {it.id==signal.accountId}
    val requesterCar=trip.cars.firstOrNull {it.id==signal.requesterCarId}
    val stops=trip.myCar?.let {TripRouteOrder.resolve(TripRouteOrder.initial(trip,it),trip,it)}.orEmpty()
    val status=when(signal.resolution) {
        "agreed"->"여행 경로에 추가했어요"
        "passed"->"동의하지 않은 차가 있어 경로에 추가하지 않았어요"
        "cancelled"->"손들기를 취소했어요"
        "reconfirm"->"여행 구성이 바뀌어 손들기가 끝났어요"
        else->"일행의 답을 기다려요"
    }
    Column(Modifier.fillMaxSize().padding(CarTokens.Frame),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
        TripHeading("손들기 결과",trip.title,onBack=onBack)
        SignalStatusColumns(Modifier.weight(1f),narrow) {columnModifier->
            Column(columnModifier.then(if(narrow)Modifier else Modifier.verticalScroll(rememberScrollState())),
                verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                CarCard(tone=CarCardTone.SOFT,radius=CarTokens.RadiusHero) {
                    Row(horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalAlignment=Alignment.CenterVertically) {
                        CarAvatar(requester?.name ?: requesterCar?.driverName ?: "일행",CarAvatarTone.INK)
                        Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                            TripText("${requester?.name ?: "일행"}님의 요청",style=CarType.Section,maxLines=2)
                            TripText(signal.kind.headline,style=CarType.Label,secondary=true,maxLines=2)
                            requesterCar?.name?.let {TripText(it,style=CarType.Label,secondary=true,maxLines=2)}
                        }
                    }
                    TripText("들를 곳",style=CarType.Label,color=LocalCarPalette.current.accent)
                    TripText(signal.destination?.name ?: signal.kind.headline,style=CarType.Hero,maxLines=3)
                    CarMetadata(tripSignalCandidateContext(signal))
                    if(stops.isNotEmpty())SignalRoutePreview(stops,planned=true)
                    CarCard {TripText(status,style=CarType.Section,maxLines=CarMessageLines)}
                }
                if(signal.inProgress && signal.accountId==trip.me?.id)
                    CarButton("손들기 취소",{actions.finishSignal("cancelled")},Modifier.fillMaxWidth(),busy=state.ending)
            }
            Column(columnModifier.then(if(narrow)Modifier else Modifier.verticalScroll(rememberScrollState())),
                verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                TripText("차량별 응답",style=CarType.Section)
                signal.groupVotes?.let {votes->
                    CarMetadata(listOf("동의 ${votes.agree}대","다음에 ${votes.pass}대","전체 ${votes.total}대"))
                }
                signal.groupResponses.forEach {response->
                    CarCard(Modifier.semantics(mergeDescendants=true) {
                        contentDescription=listOfNotNull(tripResponseSummary(response),tripResponseSourceLabel(response)).joinToString(". ")
                    },tone=CarCardTone.OUTLINED) {
                        Row(horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalAlignment=Alignment.CenterVertically) {
                            CarAvatar(response.responderName ?: response.carName)
                            Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                                TripText(response.carName,style=CarType.Section,maxLines=2)
                                response.responderName?.let {TripText("${it}님이 답했어요",secondary=true,maxLines=2)}
                                tripResponseSourceLabel(response)?.let {TripText(it,style=CarType.Label,secondary=true,maxLines=2)}
                            }
                            CarStatusPill(when(response.choice) {"agree"->"동의";"pass"->"다음에";else->"응답 대기"})
                        }
                    }
                }
                state.result?.let {TripText(it,color=LocalCarPalette.current.accent,maxLines=CarMessageLines)}
                if(trip.canRespondToSignal(signal))Row(horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                    CarButton("다음에",{actions.voteOngoingSignal("pass")},Modifier.weight(1f),busy=state.voting)
                    CarButton("동의",{actions.voteOngoingSignal("agree")},Modifier.weight(1f),primary=true,busy=state.voting)
                }
                CarButton("여행 상세로",onBack,Modifier.fillMaxWidth(),primary=true)
            }
        }
    }
}
