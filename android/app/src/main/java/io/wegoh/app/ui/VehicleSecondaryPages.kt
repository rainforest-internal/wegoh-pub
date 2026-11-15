@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package io.wegoh.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.listSaver
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.wegoh.app.*
import io.wegoh.app.nativeauth.*

@Composable
internal fun VehicleCoursesPage(state: WegoState,onLoad: ()->Unit,onDiscover: ()->Unit,
    onSelect: (String)->Unit,onAccountSelect: (AccountCourse)->Unit,onDownload: (PublishedPack)->Unit,
    onConnection: ()->Unit,onAdd: (PublishedPack)->Unit,onRefresh: ()->Unit={onLoad();onDiscover()}) = TripSurface {
    var tab by rememberSaveable {mutableStateOf(VehicleCourseFeedTab.RECOMMENDED)}
    var tags by rememberSaveable(stateSaver=listSaver<Set<String>,String>(save={it.toList()},restore={it.toSet()})) {
        mutableStateOf(emptySet<String>())
    }
    var opening by remember {mutableStateOf<String?>(null)}
    val feed=vehicleCourseLibraryState(state,tab,tags)
    val library=state.accountDiscovery.library
    val published=library?.readablePacks.orEmpty().associateBy {it.key}
    LaunchedEffect(Unit) {onLoad();onDiscover()}
    LaunchedEffect(opening,library,state.packs,state.accountDiscovery.verifiedSelection,state.accountDiscovery.isCurrent,state.accountDiscovery.status) {
        val key=opening ?: return@LaunchedEffect
        if(!state.accountDiscovery.isCurrent || state.accountDiscovery.status!=AccountReadStatus.READY) {opening=null;return@LaunchedEffect}
        val expected=published[key]
        if(expected==null) {opening=null;return@LaunchedEffect}
        if(state.accountDiscovery.verifiedSelection==expected) {
            val local=state.packs.firstOrNull {it.key==key}
            io.wegoh.app.nativeauth.WegoLog.i("WegoH","course.open: verified local=${local!=null}")
            local?.let {onSelect(it.key);opening=null}
        }
    }
    VehicleCourseFeed(feed,onTab={next->
        tab=next;tags=emptySet();opening=null
        if(next==VehicleCourseFeedTab.MINE)onLoad() else onDiscover()
    },onTag={tag->
        tags=if(tag==null)emptySet() else if(tags.any {vehicleCourseTagKey(it)==vehicleCourseTagKey(tag)})
            tags.filterNot {vehicleCourseTagKey(it)==vehicleCourseTagKey(tag)}.toSet() else tags+tag
    },onRetry=onRefresh,onConnection=onConnection,onOpen=open@{key->
        if(!feed.isCurrent || feed.status!=AccountReadStatus.READY || feed.courses.none {it.key==key && it.canOpen})return@open
        if(tab==VehicleCourseFeedTab.MINE)state.accountCourses.courses.firstOrNull {it.published.key==key}?.let(onAccountSelect)
        else published[key]?.let {pack->
            opening=key;onDownload(pack)
        }
    },onAdd=add@{key->
        if(!feed.isCurrent || feed.status!=AccountReadStatus.READY || feed.courses.none {it.key==key && it.canAdd})return@add
        val pack=if(tab==VehicleCourseFeedTab.MINE)state.accountCourses.courses.firstOrNull {it.published.key==key}?.published else published[key]
        pack?.let(onAdd)
    },openingKey=opening)
}

@Composable
internal fun TripResultPage(trip: TripDetail,onBack: ()->Unit,
    tripScore: CourseDrivingResult?=null,drivingVersus: TripDrivingVersus?=null,
    drivingVersusLoading: Boolean=false,drivingVersusNotice: String?=null,refreshDrivingVersus: (() ->Unit)?=null,
    history: @Composable ()->Unit) = TripSurface {
    val narrow=LocalTripLayoutWidth.current<CarTokens.Breakpoint
    val display=currentTripDisplay(trip)
    val palette=LocalCarPalette.current
    Column(Modifier.fillMaxSize(),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
        TripHeading(trip.title,onBack=onBack,badge="여행 끝"+display?.endedAt?.let {
            " "+java.time.Instant.parse(it).atZone(java.time.ZoneId.systemDefault()).format(java.time.format.DateTimeFormatter.ofPattern("MM/dd HH:mm"))}.orEmpty())
        TripResultColumns(Modifier.weight(1f),narrow) {columnModifier->
            Column(columnModifier.then(if(narrow)Modifier else Modifier.verticalScroll(rememberScrollState())),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                CarCard(tone=CarCardTone.INK,radius=CarTokens.RadiusHero,padding=PaddingValues(CarTokens.Frame)) {
                    CarStatusPill("여행 끝",kind=CarStatusTone.ON_INK)
                    TripText(trip.title,style=CarType.Hero,maxLines=3)
                    val stops=trip.myCar?.let {TripRouteOrder.resolve(TripRouteOrder.initial(trip,it),trip,it)}.orEmpty()
                    TripText("계획한 경로",style=CarType.Section)
                    if(stops.size<=3)CarRouteStrip(stops,TripDrivingState(),
                        onInk=true,compact=true,showPosition=false,planned=true)
                    else CompositionLocalProvider(LocalCarPalette provides palette) {
                        stops.forEachIndexed {index,stop->
                            CarListRow("${index+1}. ${stop.name}",subtitle=listOf(when(stop.item.type) {
                                "pickup"->"타는 곳";"drop"->"내리는 곳";else->"공유 경로"
                            }))
                        }
                    }
                    TripText("주행 기록",style=CarType.Section)
                    val statistics=buildList {
                        display?.metrics?.let {metrics->
                            add("달린 거리" to String.format(java.util.Locale.KOREAN,if(metrics.distanceKm>=10)"%.0f km" else "%.1f km",metrics.distanceKm))
                            val seconds=metrics.drivingSeconds.toLong()
                            add("운전 시간" to when {seconds>=3600->"${seconds/3600}시간 ${seconds%3600/60}분";seconds>=60->"${seconds/60}분";else->"${seconds}초"})
                        }
                        display?.visitCount?.let {add("들른 곳" to "${it}곳")}
                    }
                    if(statistics.isEmpty())TripText("주행 기록을 확인할 수 없어요",secondary=true,maxLines=2)
                    else Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                        statistics.forEach {(label,value)->Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                            TripText(label,secondary=true,maxLines=2)
                            TripText(value,style=CarType.Title,maxLines=3)
                        }}
                    }
                }
                TripText("경로와 들른 곳은 일행에게만 공개돼요",secondary=true,style=CarType.Label,maxLines=2)
            }
            Column(columnModifier.then(if(narrow)Modifier else Modifier.verticalScroll(rememberScrollState())),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                if(trip.routeContractVersion==2)TripDrivingVersusSummary(drivingVersus,drivingVersusLoading,drivingVersusNotice,refreshDrivingVersus,compact=true)
                TripScoreResult(trip,tripScore,drivingVersus)
                if(display?.timeline?.isNotEmpty()==true)CarCard(tone=CarCardTone.OUTLINED) {
                    display.timeline.forEach {entry->
                        Row(Modifier.fillMaxWidth().heightIn(min=CarTokens.Touch),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalAlignment=Alignment.CenterVertically) {
                            val time=java.time.Instant.parse(entry.at).atZone(java.time.ZoneId.systemDefault()).format(java.time.format.DateTimeFormatter.ofPattern("HH:mm"))
                            TripText(time,style=CarType.Label,secondary=true)
                            Column(Modifier.weight(1f)) {TripText(entry.name,maxLines=2);TripText(entry.kind,secondary=true,maxLines=2)}
                        }
                    }
                }
                Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                    CarButton("여행 홈으로",onBack,Modifier.weight(1f))
                }
            }
        }
    }
}

/** 여행이 끝난 뒤 우리 차의 여행 전체 안전운전 결과. 이 기기의 측정값이 우선이고, 없으면 서버가 공개한 같은 차 점수를 쓴다. */
@Composable
private fun TripScoreResult(trip: TripDetail,local: CourseDrivingResult?,versus: TripDrivingVersus?) {
    val shared=versus?.takeIf {it.scope=="trip"}?.cars?.firstOrNull {it.carId==trip.myCar?.id}?.takeIf {it.state in setOf("pending","ready")}
    val score=local?.score ?: shared?.totalScore
    val final=if(local?.score!=null)local.completed else shared?.final==true
    TripHeading("여행 안전운전 결과",trip.myCar?.name ?: "내 차 기준")
    CarCard(tone=CarCardTone.OUTLINED) {
        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalAlignment=Alignment.CenterVertically) {
            TripText("여행 전체",Modifier.weight(1f),style=CarType.Section,maxLines=3)
            CarStatusPill(score?.let {if(final)"최종 ${it}점" else "집계 중 ${it}점"} ?: "측정 결과 없음",
                kind=if(score!=null)CarStatusTone.INK else CarStatusTone.NEUTRAL)
        }
        when {
            local?.score!=null-> {
                CarMetadata(listOf("급가속 ${local.accelerations}회","급감속 ${local.brakings}회"),style=CarType.Body,secondary=false)
                if(local.interrupted)TripText("일부 구간만 측정했어요",secondary=true,maxLines=2)
            }
            score!=null->Unit
            else->TripText("측정 결과를 확인할 수 없어요",secondary=true,maxLines=2)
        }
    }
    CarInfoHint("점수는 일행에게만 공개돼요. 속도와 위치 원본은 보내지 않아요.")
}

@Composable
private fun TripResultColumns(modifier: Modifier,narrow: Boolean,content: @Composable (Modifier)->Unit) {
    if(narrow)Column(modifier.fillMaxWidth().verticalScroll(rememberScrollState()),
        verticalArrangement=Arrangement.spacedBy(CarTokens.Frame)) {content(Modifier.fillMaxWidth())}
    else Row(modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.Frame)) {
        content(Modifier.weight(1f).fillMaxHeight())
    }
}
