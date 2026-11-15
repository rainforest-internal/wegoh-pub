@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package io.wegoh.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import io.wegoh.app.*
import io.wegoh.app.nativeauth.*

@Composable
internal fun TripActivePage(trip: TripDetail,state: TripsPageState,enabled: Boolean,actions: TripUiActions,onBack: ()->Unit,
    onDeparture: ()->Unit,onHistory: ()->Unit,onSignal: (() ->Unit)? = {},voice: (@Composable (Modifier)->Unit)?=null,
    roomTabs: @Composable ()->Unit = {},onMusic: (() ->Unit)?=null,onEdit: (() ->Unit)?=null) {
    val mine=trip.myCar?.isMine==true
    DisposableEffect(trip.id,mine,actions) {
        actions.locationScreen(trip.id.takeIf {mine})
        onDispose {actions.locationScreen(null)}
    }
    if(trip.routeContractVersion==2 && trip.myCar?.routePlan?.phase!="shared") {
        TripSegmentActivePage(trip,state,enabled,actions,onBack,onHistory,voice,roomTabs,onMusic,onSignal,onEdit)
        return
    }
    var finish by rememberSaveable(trip.id) {mutableStateOf(false)}
    val car=trip.myCar
    val courses=trip.courses.orEmpty()
    val stops=car?.let {TripRouteOrder.resolve(TripRouteOrder.initial(trip,it),trip,it)}.orEmpty()
    val next=if(trip.routeContractVersion==2)stops.firstOrNull {it.key==car?.routePlan?.next?.key}
        else tripNextStop(stops,state.driving)
    var pickedKey by remember(next?.key) {mutableStateOf<String?>(null)}
    val target=stops.firstOrNull {it.key==pickedKey && it.key !in state.driving.arrived} ?: next
    val current=courses.firstOrNull {car!=null && car.id !in it.completedCarIds.orEmpty()} ?: courses.firstOrNull()
    var expanded by remember(trip.id,current?.packId) {mutableStateOf(current?.packId)}
    var fullRoute by rememberSaveable(trip.id) {mutableStateOf(false)}
    val narrow=LocalTripLayoutWidth.current<CarTokens.Breakpoint
    val palette=LocalCarPalette.current
    Column(Modifier.fillMaxSize(),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
        TripHeading(trip.title,tripDateLabel(trip.startDate,trip.endDate),onBack,
            badge="진행 중",activeBadge=true) {
            CarGearBadge(if(state.gear==TripGear.PARK)TripGear.PARK else TripGear.UNKNOWN)
            if(trip.isOwner)CarButton("여행 완료",{finish=true},enabled=enabled && trip.revision!=null)
        }
        CarMetadata(listOf("차 ${trip.cars.size}대","일행 ${trip.members.count {it.accepted}}명"))
        roomTabs()
        // 공유 경로 카드는 화면 스크롤과 무관하게 고정한다. 전체 경로는 경로 목록이라 함께 스크롤한다.
        val shared=trip.routeContractVersion==2 && !fullRoute
        TripRouteBody(narrow,fixed=shared,Modifier.weight(1f),panel={modifier->
            TripLiveCarPanel(trip,state,enabled,actions.refreshDrivingVersus,onMusic,onSignal,voice,modifier)}) {reserve->
                if(shared) {
                    TripSharedRouteCard(trip,state,current,stops,next,enabled,actions,reserve) {fullRoute=true}
                } else Column(verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                if(trip.routeContractVersion==2)CarButton("현재 구간",{fullRoute=false},icon=CarSymbol.Back)
                else if(car?.isMine==true)CarButton("경로 순서",onDeparture,enabled=enabled && state.gear==TripGear.PARK)
                TripHeading("경로 ${courses.size}개",badge="${courses.count {car!=null && car.id in it.completedCarIds.orEmpty()}}개 완료")
                KakaoCourseMap(stops,Modifier.height(CarTokens.MapPreviewHeight),interactive=state.gear==TripGear.PARK && enabled)
                if(courses.isEmpty())CarRouteStrip(stops,state.driving)
                courses.forEachIndexed {index,course->
                    val completed=car!=null && car.id in course.completedCarIds.orEmpty()
                    val isCurrent=course==current && !completed
                    val rows=if(course==current)stops.filter {
                        (trip.routeContractVersion!=2 || it.item.type in setOf("course","signal")) &&
                            (tripStopCourse(it,stops)==course.packId || it.item.type=="signal")}
                        else course.stops.orEmpty().map {TripRouteStop(TripRouteItem("course",it.id,course.packId),it.name,it.lat,it.lng)}
                    val result=if(isCurrent && state.liveCourseId==course.packId && state.isCurrent)state.liveCourseScore else state.courseResults[course.packId]
                    CarCard(tone=if(isCurrent)CarCardTone.INK else CarCardTone.OUTLINED) {
                        Row(Modifier.fillMaxWidth().heightIn(min=CarTokens.Touch).carTap {expanded=if(expanded==course.packId)null else course.packId}
                            .semantics {contentDescription="${index+1}. ${course.title}";stateDescription=if(expanded==course.packId)"펼쳐짐" else "접힘"},
                            horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalAlignment=Alignment.CenterVertically) {
                            Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                                TripText("${index+1}. ${course.title}",style=CarType.Section,maxLines=2)
                                CarMetadata(courseMeta(course,trip.cars.size))
                            }
                            CarStatusPill(if(trip.routeContractVersion==2 && completed)"경로 완료" else if(completed)result?.score?.let {"최종 ${it}점"} ?: "측정 불가" else if(isCurrent)"주행 중" else "다음 경로",
                                kind=if(isCurrent)CarStatusTone.ON_INK else if(completed)CarStatusTone.INK else CarStatusTone.NEUTRAL)
                            CarIcon(if(expanded==course.packId)CarSymbol.Up else CarSymbol.Down,
                                Modifier.size(CarTokens.ButtonIcon),if(isCurrent)palette.onInk else palette.secondary)
                        }
                        if(expanded==course.packId) {
                            if(isCurrent) {
                                Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalAlignment=Alignment.CenterVertically) {
                                    TripText("현재 경로",Modifier.weight(1f),style=CarType.Label,secondary=true)
                                    if(trip.routeContractVersion!=2) {
                                        TripText(result?.score?.let {"${it}점"} ?: "측정 불가",style=CarType.Title)
                                        TripText("안전운전 점수",style=CarType.Label,secondary=true)
                                    }
                                }
                                CarRouteStrip(rows,state.driving,onInk=true)
                                if(car?.isMine==true) {
                                    if(car.routePlan?.awaitingJoinCourseCompletion==true) {
                                        TripText("합류 완료",secondary=true)
                                        TripCompleteCourseButton(trip,enabled && state.gear==TripGear.PARK,state.busy,actions.completeCourse)
                                    } else {
                                        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                                            target?.let {stop->CarButton("길 안내",{actions.navigate(stop)},Modifier.weight(1f),
                                                variant=CarButtonStyle.ON_INK,enabled=enabled && stop.canNavigate,icon=CarSymbol.Navigate,
                                                accessibility="${stop.name} 길 안내")}
                                            if(trip.routeContractVersion==2 && car.routePlan?.next!=null || state.driving.phase==TripDrivingPhase.NEAR)CarButton("도착했어요",actions.arrive,Modifier.weight(1f),
                                                variant=CarButtonStyle.INK_OUTLINE,enabled=enabled && (trip.routeContractVersion!=2 ||
                                                    state.gear==TripGear.PARK && car.routePlan?.phase=="shared"))
                                            if(trip.routeContractVersion!=2 && state.driving.phase==TripDrivingPhase.ROUTE_END)CarButton("경로 완료",actions.completeCourse,Modifier.weight(1f),
                                                variant=CarButtonStyle.INK_OUTLINE,enabled=enabled)
                                        }
                                    }
                                    if(state.driving.phase==TripDrivingPhase.ARRIVED)CarButton("나중에",actions.later,
                                        variant=CarButtonStyle.INK_OUTLINE,enabled=enabled)
                                }
                                if(target!=null && target!=next)TripText(if(trip.routeContractVersion==2)"도착은 경로 순서대로 확인해요" else "앞선 장소는 들르지 않음으로 남아요",
                                    secondary=true,maxLines=2)
                                if(state.driving.phase==TripDrivingPhase.NEAR)TripText("${next?.name.orEmpty()}에 도착했나요?",maxLines=2)
                            } else if(completed && trip.routeContractVersion!=2)CourseDrivingResultCard(result)
                            rows.forEach {stop->
                                val routeStop=stops.firstOrNull {it.key==stop.key}
                                val pickable=car?.isMine==true && enabled && routeStop!=null && routeStop.canNavigate && stop.key !in state.driving.arrived
                                val chosen=routeStop!=null && routeStop==target
                                Row(Modifier.fillMaxWidth().heightIn(min=CarTokens.Touch)
                                    .then(if(pickable)Modifier.carTap {pickedKey=if(routeStop==next)null else routeStop!!.key} else Modifier)
                                    .padding(vertical=CarTokens.SpaceMedium),verticalAlignment=Alignment.CenterVertically,
                                    horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                                    TripText(when {stop.key in state.driving.arrived->"도착";chosen && stop!=next->"선택";stop==next->"다음";stop.key in state.driving.skipped->"들르지 않음";else->"예정"},
                                        Modifier.width(CarTokens.Header),style=CarType.Label,maxLines=2)
                                    Column(Modifier.weight(1f)) {
                                        TripText(stop.name,style=CarType.Body.copy(fontWeight=if(chosen)FontWeight.Bold else FontWeight.Normal),maxLines=2)
                                        CarMetadata(stopPeople(stop))
                                    }
                                }
                            }
                        }
                    }
                }
                }
        }
    }
    if(finish && trip.isOwner) {
        val incomplete=courses.mapNotNull {course->
            val cars=trip.cars.filter {it.id !in course.completedCarIds.orEmpty()}
            if(cars.isEmpty())null else "${courses.indexOf(course)+1}. ${course.title}\n${if(cars.size==trip.cars.size)"모든 차" else cars.joinToString(", ") {it.name}}"
        }
        TripFinishDialog(incomplete,enabled && trip.revision!=null,busy=state.busy,onDismiss={finish=false}) {
            trip.revision?.let {actions.perform(TripAction.Finish(it)) {finish=false}}
        }
    }
}

private fun courseMeta(course: TripCourse,cars: Int): List<String> = listOfNotNull(course.addedByName?.let {"$it 추가"},
    course.stopCount?.let {"장소 ${it}곳"},course.completedCarIds?.let {"완료 ${it.size}/${cars}대"})
private fun stopPeople(stop: TripRouteStop): List<String> = listOfNotNull(
    stop.people.takeIf {it.isNotEmpty()}?.joinToString(", ")?.let {"$it ${if(stop.item.type=="pickup")"탑승" else "하차"}"},
    stop.dropPeople.takeIf {it.isNotEmpty()}?.joinToString(", ")?.let {"$it 하차"})
private fun tripDistance(meters: Double): String = if(meters<1000)"${meters.toInt()}m 남음" else "${"%.1f".format(java.util.Locale.KOREAN,meters/1000)}km 남음"

/** 내비가 안내 중인 장소가 화면의 다음 장소일 때만 남은 거리·시간을 그 장소에 붙인다. */
internal fun tripNextRemainingLabels(drive: TripDrivingState,next: TripRouteStop?): List<String> =
    if(next!=null && drive.targetKey==next.key)tripRemainingLabels(drive) else emptyList()

internal fun tripRemainingLabels(drive: TripDrivingState): List<String> {
    val distance=drive.distanceMeters?.let(::tripDistance) ?: return emptyList()
    val time=drive.remainingSeconds?.let {seconds->
        if(seconds>=3600) {
            val minutes=(seconds+59)/60
            "${minutes/60}시간"+(if(minutes%60==0)"" else " ${minutes%60}분")
        } else if(seconds>=60)"${(seconds+59)/60}분" else "${seconds}초"
    }
    return listOfNotNull(distance,time?.let {"$it 남음"})
}

@Composable
private fun TripCompanions(trip: TripDetail,drive: TripDrivingState,display: TripDisplay?,scores: Map<String,Int>) {
    val palette=LocalCarPalette.current
    CarCard {
        TripText("함께 가는 차",style=CarType.Section)
        trip.cars.forEach {car->Column(Modifier.fillMaxWidth(),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
            Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),verticalAlignment=Alignment.CenterVertically) {
                TripText(car.numberedName,Modifier.weight(1f),maxLines=2,color=if(car.isMine)palette.accent else palette.text,
                    style=CarType.Body.copy(fontWeight=FontWeight.Bold))
                TripCarRolePill(car)
            }
            CarMetadata(if(car.isMine)when(drive.phase) {
                TripDrivingPhase.ARRIVED,TripDrivingPhase.ROUTE_END->listOf("도착")
                else->tripRemainingLabels(drive)
            } else listOfNotNull(companionLabel(display,car.id) ?: "상태 확인 중",scores[car.id]?.let {"${it}점"}))
        }}
    }
}

@Composable
internal fun TripDeparturePage(trip: TripDetail,state: TripsPageState,enabled: Boolean,actions: TripUiActions,onBack: ()->Unit,onSaved: ()->Unit) {
    val palette=LocalCarPalette.current
    if(trip.state=="planned" || trip.routeContractVersion==2) {
        TripSegmentPreparationPage(trip,state,enabled,actions,onBack,onSaved)
        return
    }
    val car=trip.myCar?.takeIf {it.isMine}
    if(car==null){CarEmptyState("등록된 차가 없어요",action={CarButton("뒤로",onBack)});return}
    var order by rememberSaveable(trip.id,car.id,stateSaver=TripRouteOrderSaver) {mutableStateOf(TripRouteOrder.initial(trip,car))}
    var draftRevision by rememberSaveable(trip.id,car.id) {mutableStateOf(car.routeRevision)}
    val changed=draftRevision!=car.routeRevision
    val canEdit=enabled && !changed
    val stops=TripRouteOrder.resolve(order,trip,car)
    val outside=TripRouteOrder.outside(order,car.places.orEmpty())
    Box(Modifier.fillMaxSize()) {
    val narrow=LocalTripLayoutWidth.current<CarTokens.Breakpoint
    Column(Modifier.fillMaxSize(),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
        TripHeading("경로 순서",onBack=onBack,gear=TripGear.PARK)
        if(changed)CarCard {
            TripText("경로가 바뀌었어요. 새 경로를 불러와 주세요",maxLines=3)
            CarButton("새 경로 불러오기",{order=TripRouteOrder.initial(trip,car);draftRevision=car.routeRevision},enabled=enabled)
        }
        TripAdaptiveRow(Modifier.weight(1f).then(if(narrow)Modifier.verticalScroll(rememberScrollState()) else Modifier),narrow=narrow,gap=CarTokens.Frame) {
            Column(Modifier.weight(1.6f),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                TripText("내 차 경로",style=CarType.Section)
                Column(Modifier.then(if(narrow)Modifier else Modifier.weight(1f).verticalScroll(rememberScrollState())),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                    stops.forEach {stop->
                        val index=stops.indexOf(stop)
                        CarCard(outlined=true,padding=PaddingValues(horizontal=CarTokens.SpaceComfortable,vertical=CarTokens.SpaceCompact),radius=CarTokens.DepartureRowRadius) {
                            Box {
                            val stacked=if(narrow)true else (LocalTripLayoutWidth.current-CarTokens.Frame)*1.6f/2.6f-CarTokens.SpaceComfortable*2<CarTokens.DepartureControlsBreakpoint
                            val controls: @Composable RowScope.()->Unit={
                                if(stop.item.type!="course" || stop.item.dropRef!=null)CarButton(if(stop.item.dropRef!=null)"하차 빼기" else "빼기",
                                    {order=TripRouteOrder.remove(order,index)},Modifier.width(CarTokens.DepartureRemoveWidth),enabled=canEdit,textStyle=CarType.DepartureRemove)
                                CarButton("위로",{order=TripRouteOrder.move(order,index,-1)},enabled=canEdit && index>0,variant=CarButtonStyle.SOFT,
                                    icon=CarSymbol.Up,accessibility="${stop.name} 순서 위로")
                                CarButton("아래로",{order=TripRouteOrder.move(order,index,1)},enabled=canEdit && index<stops.lastIndex,variant=CarButtonStyle.SOFT,
                                    icon=CarSymbol.Down,accessibility="${stop.name} 순서 아래로")
                            }
                            Column(verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                            Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceComfortable),verticalAlignment=Alignment.CenterVertically) {
                                TripText("${index+1}",Modifier.width(CarTokens.DepartureIndexWidth),style=CarType.Body.copy(fontWeight=FontWeight.Bold),color=palette.secondary)
                                Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                                    TripText(stop.name,style=CarType.DepartureTitle,maxLines=2)
                                    CarMetadata(stopPeople(stop))
                                }
                                CarStatusPill(stop.kind)
                                if(!stacked)controls()
                            }
                            if(stacked)Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium,Alignment.End),content=controls)
                            }
                            }
                        }
                    }
                }
            }
            Column(Modifier.weight(1f).then(if(narrow)Modifier else Modifier.verticalScroll(rememberScrollState())),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceComfortable)) {
                TripHeading("추가할 장소")
                outside.forEach {place->CarCard(padding=PaddingValues(CarTokens.Gap)) {
                    val who=place.selectedBy.orEmpty().mapNotNull {id->trip.members.firstOrNull {it.id==id}?.name}.joinToString(", ")
                    Row(horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),verticalAlignment=Alignment.CenterVertically) {
                    Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceXSmall)) {
                        CarMetadata(listOf(who,when(place.kind){"pickup"->"타는 곳";"signal"->"손들기";else->"내리는 곳"}),secondary=false)
                        TripText(place.name,secondary=true,maxLines=2)
                    }
                    CarButton("추가",{order=TripRouteOrder.add(order,place,trip)},primary=true,enabled=canEdit,accessibility="${place.name} 경로에 추가")
                    }
                }}
                if(outside.isEmpty())TripText("모든 장소가 경로에 있어요",secondary=true,maxLines=2)
            }
        }
        CarButton("저장",{actions.saveOrder(order,draftRevision,onSaved)},Modifier.fillMaxWidth(),primary=true,
            enabled=canEdit && TripRouteOrder.preservesCourses(order,trip))
        if(!TripRouteOrder.isComplete(trip))TripText("경로의 장소 정보를 확인해 주세요",secondary=true,maxLines=2)
    }
    }
}

@Composable
internal fun TripDrivingPage(trip: TripDetail,state: TripsPageState,enabled: Boolean,actions: TripUiActions) {
    val display=currentTripDisplay(trip)
    val car=trip.myCar
    val stops=car?.let {TripRouteOrder.resolve(TripRouteOrder.initial(trip,it),trip,it)}.orEmpty()
    val drive=state.driving
    val target=stops.firstOrNull {it.key==drive.targetKey}
    val next=tripNextStop(stops,drive)
    val newSignal=next?.takeIf {it.item.type=="signal" && it.key!=drive.targetKey}
    val currentCourse=target?.let {tripStopCourse(it,stops)}?.let {id->trip.courses.orEmpty().firstOrNull {it.packId==id}}
    val courseStops=stops.filter {it.item.type=="course" && it.item.courseId==currentCourse?.packId}
    val position=courseStops.indexOfFirst {it.key==target?.key}.takeIf {it>=0}?.plus(1)
    val hero=if(newSignal!=null || drive.phase in setOf(TripDrivingPhase.LATER,TripDrivingPhase.SKIPPED,TripDrivingPhase.ROUTE_COMPLETE))next else target ?: next
    val heroLabel=if(newSignal!=null)"새 경유지" else when(drive.phase) {
        TripDrivingPhase.ARRIVED->"안내 끝"
        TripDrivingPhase.ROUTE_END->"마지막 장소"
        TripDrivingPhase.ROUTE_COMPLETE->"경로 완료"
        else->"다음 장소"
    }
    val canAct=enabled && car?.isMine==true
    Box(Modifier.fillMaxSize()) {
    val narrow=LocalTripLayoutWidth.current<CarTokens.Breakpoint
    Column(Modifier.fillMaxSize(),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
    Column(Modifier.weight(1f).verticalScroll(rememberScrollState()),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
        TripHeading(trip.title,screenTitle=true,gear=TripGear.DRIVE)
        val p=LocalCarPalette.current
        val finished=drive.phase in setOf(TripDrivingPhase.ARRIVED,TripDrivingPhase.ROUTE_END,TripDrivingPhase.ROUTE_COMPLETE)
        CompositionLocalProvider(LocalCarPalette provides p.copy(text=p.onInk,secondary=p.onInkSecondary)) {
            Row(Modifier.fillMaxWidth().background(if(finished)p.inkDivider else p.ink,
                androidx.compose.foundation.shape.RoundedCornerShape(CarTokens.DrivingHeroRadius)).padding(horizontal=if(narrow)CarTokens.Frame else CarTokens.DrivingHeroPaddingHorizontal,vertical=if(narrow)CarTokens.Frame else CarTokens.Space3XLarge),
                horizontalArrangement=Arrangement.spacedBy(if(narrow)CarTokens.Gap else CarTokens.Space3XLarge),verticalAlignment=Alignment.CenterVertically) {
                Box(Modifier.size(if(narrow)CarTokens.DrivingHeroIconCompact else CarTokens.DrivingHeroIcon).background(p.onInk,androidx.compose.foundation.shape.CircleShape),contentAlignment=Alignment.Center) {
                    CarIcon(CarSymbol.Navigate,Modifier.size(if(narrow)CarTokens.DrivingHeroSymbolCompact else CarTokens.DrivingHeroSymbol),p.ink)
                }
                Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.DrivingHeroTextGap)) {
                CarMetadata(listOfNotNull(heroLabel,position?.let {"장소 $it/${courseStops.size}"}),style=CarType.DrivingHeroLabel)
                TripText(if(drive.phase==TripDrivingPhase.ROUTE_COMPLETE)currentCourse?.title ?: "경로 완료" else hero?.name ?: "경로 끝",style=if(narrow)CarType.DrivingHeroCompact else CarType.DrivingHero,maxLines=2)
                CarMetadata(if(newSignal!=null)listOf("안내 전") else when(drive.phase) {
                    TripDrivingPhase.FAR,TripDrivingPhase.NEAR->tripRemainingLabels(drive).ifEmpty {listOf("안내 중")}
                    TripDrivingPhase.ARRIVED->listOf("도착")
                    TripDrivingPhase.ROUTE_END->listOf("도착")+target?.let(::stopPeople).orEmpty()
                    TripDrivingPhase.ROUTE_COMPLETE->emptyList()
                    TripDrivingPhase.SKIPPED->listOf("들르지 않음")
                    TripDrivingPhase.LATER->listOf("안내 전")
                },style=CarType.Title.copy(fontWeight=FontWeight.Normal))
                }
            }
        }
        if(car?.isMine==true && newSignal!=null)TripDrivingPrompt("새 경유지가 추가됐어요",newSignal.name,highlight=true) {
            CarButton("길 안내",{actions.navigate(newSignal)},primary=true,enabled=canAct && newSignal.canNavigate,icon=CarSymbol.Navigate,accessibility="${newSignal.name} 길 안내")
        }
        else if(car?.isMine==true)when(drive.phase) {
            TripDrivingPhase.NEAR->TripDrivingPrompt("${target?.name.orEmpty()}에 도착했나요?",highlight=true,marker=true) {
                CarButton("도착했어요",actions.arrive,primary=true,enabled=canAct,large=true,textStyle=CarType.ArrivalAction)
            }
            TripDrivingPhase.ARRIVED->TripDrivingPrompt("${target?.name.orEmpty()}에 도착했어요",next?.let {"다음 장소는 ${it.name}"}) {
                CarButton("나중에",actions.later,enabled=canAct,large=true)
                next?.let {CarButton("길 안내",{actions.navigate(it)},primary=true,enabled=canAct && it.canNavigate,large=true,icon=CarSymbol.Navigate,accessibility="${it.name} 길 안내")}
            }
            TripDrivingPhase.ROUTE_END->TripDrivingPrompt(currentCourse?.title?.takeIf {it.isNotBlank()} ?: "경로 완료",
                "완료 상태가 일행에게 보여요",highlight=true) {
                CarButton("경로 완료",actions.completeCourse,primary=true,enabled=canAct,large=true)
            }
            TripDrivingPhase.ROUTE_COMPLETE->TripDrivingPrompt("경로 완료",next?.let {"다음 장소: ${it.name}"}) {
                next?.let {CarButton("길 안내",{actions.navigate(it)},primary=true,enabled=canAct && it.canNavigate,large=true,icon=CarSymbol.Navigate,accessibility="${it.name} 길 안내")}
            }
            TripDrivingPhase.LATER,TripDrivingPhase.SKIPPED->TripDrivingPrompt(
                if(drive.phase==TripDrivingPhase.SKIPPED)"들르지 않음" else "안내 전",next?.let {"다음 장소: ${it.name}"}) {
                next?.let {CarButton("길 안내",{actions.navigate(it)},primary=true,enabled=canAct && it.canNavigate,large=true,icon=CarSymbol.Navigate,accessibility="${it.name} 길 안내")}
            }
            TripDrivingPhase.FAR->Unit
        }
        if(car?.isMine==true && !canAct && drive.phase!=TripDrivingPhase.FAR)TripText("정차하면 누를 수 있어요",secondary=true)
        if(car?.isMine==true && drive.phase==TripDrivingPhase.ROUTE_COMPLETE) {
            val result=state.courseResults[drive.completedCourse]
            CarMetadata(listOf("경로 안전운전 점수",result?.score?.let {"${it}점"} ?: "측정 불가"),secondary=false)
        }
        TripCompanions(trip,state.driving,display,tripCompanionScores(trip,state))
        LocalTripMusicBar.current?.invoke(trip,null,Modifier.fillMaxWidth())
    }
    }
    }
}

@Composable
private fun TripDrivingPrompt(title: String,subtitle: String?=null,highlight: Boolean=false,marker: Boolean=false,
    actions: @Composable RowScope.()->Unit) {
    val palette=LocalCarPalette.current
    CarCard(selected=highlight,background=if(highlight)palette.background else palette.low,borderWidth=CarTokens.DrivingPromptBorder,
        padding=PaddingValues(start=CarTokens.Space3XLarge,end=CarTokens.Frame,top=CarTokens.Frame,bottom=CarTokens.Frame),radius=CarTokens.DrivingPromptRadius) {
        Box {
        val narrow=LocalTripLayoutWidth.current<CarTokens.Breakpoint
        val actionWidth=(LocalTripLayoutWidth.current-CarTokens.DrivingPromptActionReservedWidth).coerceAtLeast(0.dp)*0.55f
        val message: @Composable (Modifier)->Unit={modifier->
            Row(modifier,horizontalArrangement=Arrangement.spacedBy(CarTokens.CardPadding),verticalAlignment=Alignment.CenterVertically) {
                if(marker)Box(Modifier.size(CarTokens.DrivingPromptMarker).background(palette.accent,androidx.compose.foundation.shape.CircleShape))
                Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                TripText(title,style=CarType.Title,maxLines=2)
                subtitle?.let {TripText(it,style=CarType.DrivingPromptCaption,secondary=true,maxLines=3)}
                }
            }
        }
        if(narrow)Column(verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
            message(Modifier.fillMaxWidth())
            Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap,Alignment.End),content=actions)
        } else Row(horizontalArrangement=Arrangement.spacedBy(CarTokens.CardPadding),verticalAlignment=Alignment.CenterVertically) {
            message(Modifier.weight(1f))
            Row(Modifier.widthIn(max=actionWidth),horizontalArrangement=Arrangement.spacedBy(CarTokens.CardPadding,Alignment.End),content=actions)
        }
        }
    }
}
