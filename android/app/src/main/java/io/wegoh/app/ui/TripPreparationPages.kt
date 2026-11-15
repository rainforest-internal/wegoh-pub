package io.wegoh.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import io.wegoh.app.*
import io.wegoh.app.nativeauth.*

@Composable
internal fun TripStartButton(trip: TripDetail,enabled: Boolean,actions: TripUiActions) {
    if(!trip.isOwner || trip.state!="planned")return
    val running=trip.startConflict?.activeTrips.orEmpty()
    var confirm by remember(trip.id) {mutableStateOf(false)}
    fun start(endActiveTrip: Boolean)=trip.revision?.let {
        actions.perform(TripAction.Start(it,routeContractVersion=2,endActiveTrip=endActiveTrip)) {}
    }
    CarButton("여행 시작",{if(running.isEmpty())start(false) else confirm=true},
        primary=true,enabled=enabled && tripCanStart(trip))
    if(confirm && running.isNotEmpty())TripStartConflictPopup(running,enabled && tripCanStart(trip),{confirm=false}) {
        confirm=false;start(true)
    }
}

/** One running trip per person: the owner ends the current one (finish if owned, leave otherwise) before starting.
 * 확인 버튼은 DANGER로 선언하고, 팝업 안에서는 Pleos System Popup의 진한 확인 버튼으로 그린다(carPopupButtonRole). */
/** 여행 완료 팝업과 같은 문장·문장 부호로 결과를 설명한다. 대상 여행 이름은 본문 카드가 보여 준다. */
internal fun tripStartConflictDescription(completing: Boolean,leaving: Boolean): String = when {
    completing && leaving->"완료할 여행은 모든 차의 주행을 끝내고 기록을 저장해요. 완료한 여행은 다시 시작할 수 없어요. 나갈 여행은 다른 일행이 계속해요."
    completing->"모든 차의 주행을 끝내고 기록을 저장해요. 완료한 여행은 다시 시작할 수 없어요."
    else->"다른 일행의 여행은 계속돼요."
}

@Composable
internal fun TripStartConflictPopup(running: List<TripActiveTrip>,enabled: Boolean,onDismiss: ()->Unit,onConfirm: ()->Unit) {
    val completing=running.filter {it.isOwner}
    val leaving=running.filterNot {it.isOwner}
    CarPopup("진행 중인 여행이 있어요",onDismiss,
        description=tripStartConflictDescription(completing.isNotEmpty(),leaving.isNotEmpty()),body={
        if(completing.isNotEmpty())TripPopupTargets("완료할 여행",completing.map {it.title})
        if(leaving.isNotEmpty())TripPopupTargets("나갈 여행",leaving.map {it.title})
    },actions={
        CarButton(when {leaving.isEmpty()->"완료하고 시작";completing.isEmpty()->"나가고 시작";else->"이 여행 시작"},
            onConfirm,Modifier.weight(1f),variant=CarButtonStyle.DANGER,enabled=enabled)
        CarButton("취소",onDismiss,Modifier.weight(1f))
    })
}

@Composable
internal fun TripPreparationFrame(trip: TripDetail,enabled: Boolean,selectedTab: TripPlanTab,onBack: ()->Unit,
    actions: TripUiActions,gear: TripGear?,onSelectTab: (TripPlanTab)->Unit,content: @Composable ()->Unit) {
    val narrow=LocalTripLayoutWidth.current<CarTokens.Breakpoint
    val overview=tripPlanOverview(trip)
    Column(Modifier.fillMaxSize(),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
        TripHeading(trip.title,"${tripDateLabel(trip.startDate,trip.endDate)}\n만든 사람 ${trip.members.firstOrNull {it.isOwner}?.name.orEmpty()}",onBack,badge=tripStateLabel(trip.state,trip.startDate)) {
            gear?.takeIf {it==TripGear.PARK || it==TripGear.DRIVE}?.let {CarGearBadge(it)}
            TripStartButton(trip,enabled,actions)
        }
        val busyMembers=trip.startConflict?.busyMemberIds.orEmpty().isNotEmpty()
        val preparationHint=when {
            !trip.isOwner->"여행 시작 대기"
            trip.cars.isEmpty()->"iPhone에서 차를 추가해 주세요"
            busyMembers->"다른 여행 중인 일행이 있어 시작할 수 없어요"
            trip.courses.orEmpty().isEmpty()->"저장 경로를 추가해 주세요"
            !TripRouteOrder.isComplete(trip)->"저장 경로의 장소를 확인해 주세요"
            else->null
        }
        preparationHint?.let {TripText(it,style=CarType.Label,secondary=true,maxLines=3)}
        if(trip.isOwner && trip.cars.isNotEmpty() && busyMembers)CarMetadata(tripBusyMemberNames(trip))
        if(narrow) {
            Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                overview.menu.forEach {menu->
                    CarButton(menu.tab.title,{onSelectTab(menu.tab)},Modifier.weight(1f).semantics {selected=selectedTab==menu.tab},
                        enabled=enabled,variant=if(selectedTab==menu.tab)CarButtonStyle.DARK else CarButtonStyle.OUTLINE)
                }
            }
            Box(Modifier.weight(1f)) {content()}
        } else Row(Modifier.weight(1f),horizontalArrangement=Arrangement.spacedBy(CarTokens.Frame)) {
            Column(Modifier.width(CarTokens.PreparationNavigationWidth).fillMaxHeight().verticalScroll(rememberScrollState()),
                verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                overview.menu.forEach {menu->
                    CarCard(Modifier.carTap(enabled=enabled,role=Role.Tab) {onSelectTab(menu.tab)}
                        .semantics {selected=selectedTab==menu.tab;contentDescription=menu.tab.title},
                        tone=if(selectedTab==menu.tab)CarCardTone.INK else CarCardTone.OUTLINED) {
                        TripText(menu.tab.title,style=CarType.Section,maxLines=2)
                        CarMetadata(when(menu.tab) {
                            TripPlanTab.OVERVIEW->listOf("남은 준비 ${tripPreparationChecks(trip).count {!it.done}}개")
                            TripPlanTab.GROUPS->listOf("차 ${trip.cars.size}대","빈자리 ${trip.cars.sumOf {it.seats-it.passengers.size}}석")
                            TripPlanTab.MEMBERS->listOfNotNull("준비 ${overview.ready}/${trip.members.size}명",
                                "초대 대기 ${overview.pending}명".takeIf {overview.pending>0})
                            TripPlanTab.ROUTE->listOf("저장 경로 ${trip.courses.orEmpty().size}개")
                        })
                    }
                }
            }
            TripLayoutRoot(Modifier.weight(1f).fillMaxHeight()) {content()}
        }
    }
}

@Composable
internal fun TripPreparationPanels(left: @Composable ColumnScope.()->Unit,right: @Composable ColumnScope.()->Unit) {
    if(LocalTripLayoutWidth.current<CarTokens.Breakpoint)
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {left();right()}
    else Row(Modifier.fillMaxSize(),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
        Column(Modifier.weight(1f).fillMaxHeight().verticalScroll(rememberScrollState()),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap),content=left)
        Column(Modifier.weight(1f).fillMaxHeight().verticalScroll(rememberScrollState()),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap),content=right)
    }
}

@Composable
internal fun TripGroupsPage(trip: TripDetail,enabled: Boolean,onBack: ()->Unit,actions: TripUiActions,onCreateCar: ()->Unit,
    onManageCar: ()->Unit,gear: TripGear?,onSelectTab: (TripPlanTab)->Unit) {
    val assigned=trip.cars.flatMap {listOf(it.driverId)+it.passengers.map {rider->rider.id}}.toSet()
    val waiting=trip.members.filter {it.id !in assigned}
    TripPreparationFrame(trip,enabled,TripPlanTab.GROUPS,onBack,actions,gear,onSelectTab) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
            TripText("차 ${trip.cars.size}대",style=CarType.Section,maxLines=2)
            trip.cars.forEach {car->TripPreparationGroupCard(trip,car,enabled,actions,onManageCar)}
            if(trip.cars.isEmpty())CarCard(tone=CarCardTone.DASHED) {
                TripText("차가 없어요",style=CarType.Section)
                TripText("iPhone의 여행에서 차를 추가해 주세요",secondary=true,maxLines=3)
            }
            CarCard {
                TripText("탈 차 미정 ${waiting.size}명",style=CarType.Body.copy(fontWeight=FontWeight.Bold),maxLines=2)
                if(waiting.isEmpty())TripText("모두 탈 차를 골랐어요",secondary=true,maxLines=2)
                waiting.forEach {person->PreparationPersonRow(person.name,tripWaitingCarDetail(person))}
            }
            CarPhoneHandoff("car-and-stops")
        }
    }
}

/** Accepted members still choose a car on iPhone; invited members cannot until they accept. */
internal fun tripWaitingCarDetail(person: TripMember): String=if(person.accepted)"탈 차 미정" else "초대 수락 전"

@Composable
internal fun TripPreparationGroupCard(trip: TripDetail,car: TripCar,enabled: Boolean,actions: TripUiActions,onManage: ()->Unit,showActions: Boolean=true) {
    var expanded by remember(car.id) {mutableStateOf(false)}
    val p=LocalCarPalette.current
    CarCard(tone=CarCardTone.OUTLINED) {
        Row(Modifier.fillMaxWidth().heightIn(min=CarTokens.Row),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalAlignment=Alignment.CenterVertically) {
            Box(Modifier.size(CarTokens.IconLarge).background(p.accentSoft,RoundedCornerShape(CarTokens.RadiusCard)),contentAlignment=Alignment.Center) {
                CarIcon(CarSymbol.Car,color=p.accent)
            }
            Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),verticalAlignment=Alignment.CenterVertically) {
                    TripText(car.numberedName,Modifier.weight(1f),style=CarType.Section,maxLines=3)
                    TripCarRolePill(car)
                }
                TripText("운전자 ${car.driverName}",secondary=true,maxLines=2)
                CarMetadata(listOf("탑승 ${car.passengers.size+1}/${car.seats+1}명","빈자리 ${car.seats-car.passengers.size}석"),
                    style=CarType.Label.copy(fontWeight=FontWeight.Bold))
                TripCarRoles(trip,car)
                if(car.isMine)TripText(tripRemotePolicyLabel(car.remotePolicy),style=CarType.Label,secondary=true,maxLines=3)
            }
            if(showActions)when {
                car.isMine->CarButton("관리",onManage,enabled=enabled,accessibility="${car.numberedName} 관리")
                else->CarButton(if(expanded)"접기" else "탑승자",{expanded=!expanded},enabled=enabled,accessibility="${car.numberedName} ${if(expanded)"탑승자 접기" else "탑승자 보기"}")
            }
        }
        if(expanded) {
            PreparationPersonRow(car.driverName,"운전자",driver=true)
            car.passengers.forEach {PreparationPersonRow(it.name,"동승자")}
        }
    }
}

@Composable
internal fun PreparationPersonRow(name: String,detail: String,driver: Boolean=false,actions: @Composable RowScope.()->Unit={}) {
    Row(Modifier.fillMaxWidth().heightIn(min=CarTokens.Row),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalAlignment=Alignment.CenterVertically) {
        CarAvatar(name,if(driver)CarAvatarTone.INK else CarAvatarTone.SOFT)
        Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
            TripText(name,style=CarType.Body.copy(fontWeight=FontWeight.Bold),maxLines=2)
            if(detail.isNotEmpty())CarMetadata(detail.lines())
        }
        actions()
    }
}

@Composable
internal fun TripPreparationRoutePage(trip: TripDetail,enabled: Boolean,onBack: ()->Unit,actions: TripUiActions,
    courses: AccountCourseState,onCoursesLoad: ()->Unit,gear: TripGear?,onSelectTab: (TripPlanTab)->Unit) {
    LaunchedEffect(trip.id) {if(enabled)onCoursesLoad()}
    TripPreparationFrame(trip,enabled,TripPlanTab.ROUTE,onBack,actions,gear,onSelectTab) {
        TripPreparationPanels(left={
            val mapStops=trip.courses.orEmpty().flatMap {course->course.stops.orEmpty().map {stop->
                TripRouteStop(TripRouteItem("course",stop.id,course.packId),stop.name,stop.lat,stop.lng)
            }}
            KakaoCourseMap(mapStops,Modifier.height(CarTokens.MapPreviewHeight),interactive=gear==TripGear.PARK && enabled)
            CarCard(tone=CarCardTone.OUTLINED) {
                TripText("추가한 경로 ${trip.courses.orEmpty().size}/10개",style=CarType.Section,maxLines=2)
                if(trip.courses.orEmpty().isEmpty())TripText("추가한 경로가 없어요",secondary=true,maxLines=2)
                trip.courses.orEmpty().forEachIndexed {index,course->
                    CarCard(selected=index==0,outlined=true) {
                        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),verticalAlignment=Alignment.CenterVertically) {
                            CarAvatar((index+1).toString(),CarAvatarTone.INK)
                            Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                                TripText(course.title,style=CarType.Body.copy(fontWeight=FontWeight.Bold),maxLines=3)
                                CarMetadata(listOfNotNull(course.addedByName?.let {"$it 추가"},course.stopCount?.let {"장소 ${it}곳"}))
                            }
                            if(trip.canEdit || course.canRemove==true)CarButton("빼기",{actions.perform(TripAction.RemoveCourse(course.packId)) {}},
                                enabled=enabled,accessibility="${course.title} 여행에서 빼기")
                        }
                        if(!course.stops.isNullOrEmpty())CarRouteStrip(course.stops.map {stop->
                            TripRouteStop(TripRouteItem("course",stop.id,course.packId),stop.name,stop.lat,stop.lng)
                        },TripDrivingState(),compact=true,planned=true)
                    }
                }
            }
            CarPhoneHandoff("course-save")
        },right={
            CarCard(tone=CarCardTone.OUTLINED) {
                TripText("내 경로에서 추가",style=CarType.Section,maxLines=2)
                when(courses.status) {
                    AccountCourseStatus.LOADING->TripText("경로 불러오는 중",secondary=true,maxLines=2)
                    AccountCourseStatus.CONNECTION_REQUIRED->CarPhoneHandoff("vehicle-link")
                    AccountCourseStatus.PERMISSION_REQUIRED->CarPhoneHandoff("vehicle-permission")
                    AccountCourseStatus.UNAVAILABLE->CarButton("다시 시도",onCoursesLoad,Modifier.fillMaxWidth(),enabled=enabled)
                    AccountCourseStatus.READY->if(courses.courses.isEmpty())TripText("저장한 경로가 없어요",secondary=true,maxLines=3)
                }
                courses.courses.forEachIndexed {index,course->
                    if(index>0)TripDivider()
                    Row(Modifier.fillMaxWidth().heightIn(min=CarTokens.Row),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),verticalAlignment=Alignment.CenterVertically) {
                        Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                            TripText(course.published.title,style=CarType.Body.copy(fontWeight=FontWeight.Bold),maxLines=3)
                            CarMetadata(listOfNotNull(course.published.author.takeIf {it.isNotBlank()},"장소 ${course.published.stopCount}곳"))
                        }
                        if(trip.courses.orEmpty().any {it.packId==course.published.id})CarStatusPill("추가됨",kind=CarStatusTone.NEUTRAL)
                        else if(trip.canAddCourse)CarButton("추가",{actions.perform(TripAction.AddCourse(course.published.id)) {}},
                            enabled=enabled && courses.isCurrent && courses.status==AccountCourseStatus.READY && course.available && trip.courses.orEmpty().size<10,
                            variant=CarButtonStyle.SOFT,accessibility="${course.published.title} 여행에 추가")
                    }
                }
            }
        })
    }
}
