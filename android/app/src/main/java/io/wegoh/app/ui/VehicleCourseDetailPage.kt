@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package io.wegoh.app.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import io.wegoh.app.*
import io.wegoh.app.nativeauth.TripRouteItem

@Composable
internal fun VehicleCourseDetailPage(state: WegoState,clock: Long,onBack: ()->Unit,onNavigate: ()->Unit,
    onJourney: ()->Unit,onReset: ()->Unit,onError: ()->Unit,onPlace: (Int)->Unit,onAdd: ((PublishedPack)->Unit)?=null) = TripSurface {
    val pack=state.selected
    val narrow=LocalTripLayoutWidth.current<CarTokens.Breakpoint
    val published=pack?.let {selected->
        state.accountCourses.courses.firstOrNull {it.available && it.published.key==selected.key}
            ?.published?.takeIf {state.accountCourses.status==AccountCourseStatus.READY && state.accountCourses.isCurrent}
            ?: state.accountDiscovery.packs.firstOrNull {it.key==selected.key}
                ?.takeIf {state.accountDiscovery.status==AccountReadStatus.READY && state.accountDiscovery.isCurrent}
    }
    val metadata=if(state.accountDiscovery.status==AccountReadStatus.READY && state.accountDiscovery.isCurrent)
        state.accountDiscovery.library?.let {library->
            (library.public+library.saved+library.news.map {it.course}).firstOrNull {it.published.key==pack?.key}
        } else null
    val ownTags=if(state.accountCourses.status==AccountCourseStatus.READY && state.accountCourses.isCurrent)
        state.accountCourses.courses.firstOrNull {it.available && it.published.key==pack?.key}?.tags.orEmpty() else emptyList()
    val tags=metadata?.tags?.ifEmpty {ownTags} ?: ownTags
    val ready=pack!=null && state.accountCourses.downloading==null &&
        (pack.source!=CoursesRepository.SOURCE || state.accountCourses.isCurrent)
    Column(Modifier.fillMaxSize().padding(CarTokens.SpaceMedium),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
        TripHeading("경로",onBack=onBack)
        if(pack==null)CarEmptyState("경로를 골라주세요",Modifier.weight(1f),symbol=CarSymbol.Route)
        else TripAdaptiveRow(Modifier.weight(1f).then(if(narrow)Modifier.verticalScroll(rememberScrollState()) else Modifier),
            narrow=narrow,gap=CarTokens.Gap) {
            Column(Modifier.weight(1f).then(if(narrow)Modifier else Modifier.fillMaxHeight().verticalScroll(rememberScrollState())),
                verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                CarCard(tone=CarCardTone.INK,radius=CarTokens.RadiusHero) {
                    if(tags.isNotEmpty())FlowRow(horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall),
                        verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                        tags.distinctBy(::vehicleCourseTagKey).forEach {tag->
                            CarStatusPill("#${tag.trim().removePrefix("#")}",kind=CarStatusTone.ACTIVE)
                        }
                    }
                    TripText(pack.title,style=CarType.Hero,maxLines=2)
                    CarMetadata(listOfNotNull("${pack.stops.size}곳",pack.author,metadata?.let {"별표 ${it.starCount}"}),style=CarType.Label)
                    if(metadata?.starred==true)CarStatusPill("저장됨",kind=CarStatusTone.ON_INK)
                    val stops=pack.stops.map {TripRouteStop(TripRouteItem("course",it.id,pack.id),it.name,it.latitude,it.longitude)}
                    // 순서와 이름은 오른쪽 '들를 곳' 목록이 주므로 지도는 피드와 같은 번호 표식만 쓴다.
                    CourseRoadMap(published,Modifier.height(CarTokens.MapPreviewHeight),fallback=stops,interactive=state.setupAllowed,numbersOnly=true)
                    if(state.setupAllowed && pack.description.isNotBlank())TripText(pack.description,style=CarType.Label,secondary=true,maxLines=3)
                    state.courseResult?.let {result->
                        TripDivider()
                        TripText("경로 안전운전 결과",style=CarType.Label,color=LocalCarPalette.current.routeOnInk,maxLines=2)
                        TripText(result.score?.let {"${it}점"} ?: "측정 불가",style=CarType.Hero)
                        if(result.score!=null)CarMetadata(listOf("급가속 ${result.accelerations}회","급감속 ${result.brakings}회"),style=CarType.Label)
                        if(result.interrupted)TripText("일부 구간만 측정했어요",style=CarType.Label,secondary=true,maxLines=2)
                    }
                }
                if(!state.active && state.completed.isNotEmpty())CarButton("경로 기록 초기화",onReset,Modifier.fillMaxWidth(),icon=CarSymbol.Refresh)
                CarPhoneHandoff("course-edit")
            }
            Column(Modifier.weight(1f).then(if(narrow)Modifier else Modifier.fillMaxHeight().verticalScroll(rememberScrollState())),
                verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically) {
                    TripText("들를 곳",Modifier.weight(1f),style=CarType.Section)
                    CarStatusPill("방문 ${state.completed.size}/${pack.stops.size}")
                }
                val overview=state.navigationOverview?.takeIf {it.packKey==pack.key}
                if(overview==null)TripText("시간과 교통은 길 안내를 시작하면 보여요",style=CarType.Label,secondary=true,maxLines=2)
                pack.stops.forEachIndexed {index,stop->
                    CarCard(Modifier.carTap(enabled=!state.active){onPlace(index)},tone=CarCardTone.OUTLINED) {
                        Row(horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalAlignment=Alignment.CenterVertically) {
                            CarAvatar("${index+1}",if(stop.id in state.completed)CarAvatarTone.INK else CarAvatarTone.SOFT)
                            Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                                TripText(stop.name,style=CarType.Section,maxLines=2)
                                CarMetadata(overview.stopEstimates(stop.id,clock),style=CarType.Label)
                            }
                            if(stop.id in state.completed)CarStatusPill("방문")
                        }
                    }
                }
                if(state.navigationPhase!=NavigationPhase.IDLE)TripText(courseNavigationStatus(state.navigationPhase),style=CarType.Label,secondary=true,maxLines=2)
                if(state.error!=null)CarButton("문제 확인",onError,Modifier.fillMaxWidth(),icon=CarSymbol.Alert)
                Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                    if(published!=null && onAdd!=null)CarButton("여행에 추가",{onAdd(published)},Modifier.weight(1f),
                        enabled=state.setupAllowed && ready,variant=CarButtonStyle.SOFT)
                    CarButton("길 안내",onNavigate,Modifier.weight(1f),primary=true,enabled=ready && !state.navigationBusy,icon=CarSymbol.Navigate,
                        accessibility="${pack.stops.firstOrNull()?.name ?: "목적지"}까지 길 안내")
                }
                CarButton(if(state.active)"종료" else "도착 알림",onJourney,Modifier.fillMaxWidth(),
                    enabled=state.accountCourses.downloading==null && (state.active || ready && !state.allVisited),
                    icon=if(state.active)CarSymbol.Stop else CarSymbol.Pin)
            }
        }
    }
}

internal fun courseNavigationStatus(phase: NavigationPhase): String=when(phase) {
    NavigationPhase.CONNECTING->"내비 연결 중"
    NavigationPhase.SENT->"길 안내 요청 중"
    NavigationPhase.SEARCHING->"경로 탐색 중"
    NavigationPhase.CALCULATED->"경로 탐색 완료"
    NavigationPhase.OEM_GUIDANCE_REPORTED->"길 안내 상태 확인 필요"
    NavigationPhase.ACTIVE->"길 안내 중"
    else->"길 안내 상태를 확인하지 못했어요"
}
