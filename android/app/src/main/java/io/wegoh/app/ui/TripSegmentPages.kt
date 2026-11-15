@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package io.wegoh.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.saveable.listSaver
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.Layout
import androidx.compose.ui.layout.Placeable
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.unit.constrainHeight
import androidx.compose.ui.unit.constrainWidth
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import io.wegoh.app.*
import io.wegoh.app.nativeauth.*

/** Why the parked-only arrival confirmation is unavailable right now, or null when it can be pressed. */
internal fun tripArrivalGearHint(gear: TripGear): String? = when(gear) {
    TripGear.PARK->null
    TripGear.UNKNOWN->"기어 확인 중이에요. 도착 확인은 P단에서 해 주세요"
    else->"P단에서 도착을 확인해 주세요"
}

internal fun tripSegmentPhaseLabel(phase: String): String = when(phase) {
    "pickup"->"타는 곳으로 이동 중";"waiting"->"합류 대기";"shared"->"경로 주행 중";"drop"->"내리는 곳으로 이동 중";"done"->"주행 완료";else->"상태 확인 중"
}

@Composable
internal fun TripSegmentBand(trip: TripDetail,phase: String?) {
    val p=LocalCarPalette.current
    val stops=tripMyStops(trip)
    val stages=buildList {
        add(Triple("pickup","타는 곳",stops.label("pickup")))
        trip.courses.orEmpty().forEachIndexed {index,course->add(Triple("shared","경로 ${index+1}",course.title))}
        add(Triple("drop","내리는 곳",stops.label("drop")))
    }
    FlowRow(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall),
        verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
        stages.forEach {(kind,title,detail)->
            val current=kind==phase || kind=="pickup" && phase=="waiting"
            val shared=kind=="shared"
            val fill=when {current->p.accent;shared->p.ink;else->p.background}
            val text=when {current->p.selectionMark;shared->p.onInk;else->p.text}
            val edge=if(shared || current)Modifier else Modifier.tripBorder(CarTokens.BorderWidth,p.personalRouteBorder,CarTokens.RadiusCard,true)
            Column(Modifier.weight(1f).widthIn(min=CarTokens.RouteSegmentMinWidth).heightIn(min=CarTokens.ButtonLarge)
                .clip(RoundedCornerShape(CarTokens.RadiusCard)).background(fill).then(edge).padding(CarTokens.Gap)
                .semantics(mergeDescendants=true) {},
                verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                TripText(title,style=CarType.Section,color=text,maxLines=2)
                TripText(detail,style=CarType.Caption,color=text,maxLines=2)
            }
        }
    }
}

@Composable
internal fun TripSegmentActivePage(trip: TripDetail,state: TripsPageState,enabled: Boolean,actions: TripUiActions,
    onBack: ()->Unit,onHistory: ()->Unit,voice: (@Composable (Modifier)->Unit)?,roomTabs: @Composable ()->Unit,
    onMusic: (() ->Unit)?,onSignal: (() ->Unit)?=null,onEdit: (() ->Unit)?=null) {
    val plan=trip.myCar?.routePlan
    var finish by rememberSaveable(trip.id) {mutableStateOf(false)}
    Column(Modifier.fillMaxSize(),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
        TripHeading(trip.title,plan?.let {tripSegmentPhaseLabel(it.phase)},onBack) {
            if(state.gear==TripGear.PARK)CarGearBadge(TripGear.PARK)
            if(trip.isOwner)CarButton("여행 완료",{finish=true},enabled=enabled && trip.revision!=null)
        }
        roomTabs()
        if(plan==null) {
            CarEmptyState("우리 차 경로를 확인할 수 없어요",Modifier.weight(1f),symbol=CarSymbol.Route)
            TripSegmentVoiceBar(voice)
        } else {
            val car=checkNotNull(trip.myCar)
            val narrow=LocalTripLayoutWidth.current<CarTokens.Breakpoint
            val all=TripRouteOrder.resolve(plan.segments.flatMap {it.items},trip,car)
            val next=all.firstOrNull {it.item.key==plan.next?.key}
            var fullRoute by rememberSaveable(trip.id) {mutableStateOf(false)}
            val route=if(fullRoute)all else tripPrivateRouteStops(all,plan)
            val dropStops: (@Composable ColumnScope.()->Unit)?=if(plan.phase in setOf("drop","done")) {{TripDropStops(plan,route,next)}} else null
            // 우리 차 경로 카드는 화면 스크롤과 무관하게 고정하고, 내리는 곳 목록과 패널만 스크롤한다.
            TripRouteBody(narrow,fixed=true,Modifier.weight(1f),panel={modifier->
                TripLiveCarPanel(trip,state,enabled,actions.refreshDrivingVersus,onMusic,onSignal,voice,modifier)},
                rest=dropStops) {reserve->
                TripPrivateRouteCard(trip,state,plan,route,next,enabled,actions,fullRoute,{fullRoute=!fullRoute},reserve)
            }
        }
    }
    if(finish && trip.isOwner)TripFinishDialog(emptyList(),enabled && trip.revision!=null,state.busy,{finish=false}) {
        trip.revision?.let {actions.perform(TripAction.Finish(it)) {finish=false}}
    }
}

/** 우리 차 구간의 지도·경로 줄에 보일 장소. 손들기로 들어온 장소는 어느 구간에 있어도 함께 보여 준다. */
internal fun tripPrivateRouteStops(all: List<TripRouteStop>,plan: TripRoutePlan): List<TripRouteStop> {
    val drop=plan.phase in setOf("drop","done")
    val items=plan.segments.first {it.segment==if(drop)"drop" else "pickup"}.items
    val join=TripRouteItem("course",plan.joinPoint.ref,plan.joinPoint.courseId)
    return all.filter {it.item in items || it.item.type=="signal" || !drop && it.item.key==join.key}
}

/** 우리 차 경로 카드에서 다음 장소 이름 위에 붙는 종류. 손들기 장소를 합류 지점으로 부르지 않는다. */
internal fun tripPrivateNextLabel(next: TripRouteItem): String = when(next.type) {
    "pickup"->"다음 타는 곳";"drop"->"다음 내리는 곳";"signal"->"손들기 장소";else->"합류 지점"
}

internal fun tripPrivateArrivalLabel(next: TripRouteItem,lastPrivate: TripRouteItem?): String = when {
    next.type=="pickup"->"탔어요"
    next.type=="drop" && lastPrivate?.key==next.key->"우리 차 주행 완료"
    next.type=="drop"->"내렸어요"
    next.type=="signal"->"도착했어요"
    else->"합류 지점 도착"
}

@Composable
private fun TripPrivateRouteCard(trip: TripDetail,state: TripsPageState,plan: TripRoutePlan,route: List<TripRouteStop>,
    next: TripRouteStop?,enabled: Boolean,actions: TripUiActions,fullRoute: Boolean,onFullRoute: ()->Unit,reserve: Dp) {
    val drop=plan.phase in setOf("drop","done")
    val waiting=plan.phase=="waiting"
    val car=checkNotNull(trip.myCar)
    val privateItems=plan.segments.first {it.segment==if(drop)"drop" else "pickup"}.items
    val canConfirm=state.gear==TripGear.PARK && (plan.phase in setOf("pickup","drop") || plan.phase=="waiting" && plan.next?.type=="signal")
    CarCard(tone=CarCardTone.INK,radius=CarTokens.RadiusHero,padding=PaddingValues(CarTokens.Frame)) {
        // 주요 동작은 지도 위에 두어 높이가 모자라도 잘리지 않게 한다. 지도가 남은 높이에 맞춰 줄어든다.
        TripFixedRouteColumn(reserve,top={
        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalAlignment=Alignment.CenterVertically) {
            TripText(if(waiting)"합류 대기" else if(drop)"내리는 곳" else "타는 곳",
                Modifier.weight(1f),style=CarType.Section,maxLines=2)
            CarButton(if(fullRoute)"현재 구간" else "전체 경로",onFullRoute,variant=CarButtonStyle.INK_OUTLINE,enabled=enabled)
        }
        when {
            waiting->{
                TripText(plan.joinPoint.name,style=CarType.Hero,maxLines=2)
                TripText("도착 ${plan.joinBarrier.arrivedCarIds.size}/${plan.joinBarrier.totalCarCount}대",secondary=true)
            }
            plan.phase=="done"->{
                TripText("우리 차 주행 완료",style=CarType.Hero,maxLines=2)
                TripText("다른 차의 주행이 끝나면 여행이 완료돼요",secondary=true,maxLines=3)
            }
            next!=null->{
                TripText(tripPrivateNextLabel(next.item),style=CarType.Label,secondary=true)
                TripText(next.name,style=CarType.Hero,maxLines=2)
                tripPrivatePeople(next)?.let {TripText(it,style=CarType.Label,maxLines=3)}
                if(state.driving.targetKey==next.key)CarMetadata(tripRemainingLabels(state.driving))
            }
            else->TripText("다음 경로 확인 중",style=CarType.Section,maxLines=2)
        }
        if(car.isMine && next!=null && plan.phase!="done") {
            Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                CarButton("길 안내",{actions.navigate(next)},Modifier.weight(1.6f),
                    variant=CarButtonStyle.ON_INK,enabled=enabled && next.canNavigate,icon=CarSymbol.Navigate,
                    accessibility="${next.name} 길 안내")
                if(!waiting)CarButton(tripPrivateArrivalLabel(next.item,privateItems.lastOrNull()),actions.arrive,Modifier.weight(1f),variant=CarButtonStyle.INK_OUTLINE,enabled=enabled && canConfirm)
            }
            if(!waiting)tripArrivalGearHint(state.gear)?.let {TripText(it,secondary=true,maxLines=3)}
        }
        },map={
            KakaoCourseMap(route,Modifier.height(CarTokens.MapPreviewHeight),interactive=state.gear==TripGear.PARK && enabled,
                vehicle=state.driving.position.takeIf {plan.phase!="done"},focus=next,others=courseMapOtherCars(trip,state.otherCars))
        },strip={
            CarRouteStrip(route,state.driving,onInk=true,compact=true,showPosition=plan.phase!="done")
        },extra={if(plan.phase!="done")TripCompanionProgress(trip,currentTripDisplay(trip))})
    }
}

/** 내리는 구간의 장소 목록. 고정 경로 카드 아래 스크롤 영역에 둔다. */
@Composable
private fun TripDropStops(plan: TripRoutePlan,route: List<TripRouteStop>,next: TripRouteStop?) {
    CarCard(tone=CarCardTone.INK,radius=CarTokens.RadiusHero,padding=PaddingValues(CarTokens.Frame)) {
        route.forEachIndexed {index,stop->
            Row(Modifier.fillMaxWidth().padding(vertical=CarTokens.SpaceMedium),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                TripText("${index+1}",style=CarType.Section)
                Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                    TripText(stop.name,style=CarType.Section,maxLines=2)
                    tripPrivatePeople(stop)?.let {TripText(it,secondary=true,maxLines=3)}
                }
                if(stop.key==next?.key)CarStatusPill("다음",kind=CarStatusTone.ON_INK)
            }
        }
        if(plan.phase!="done")TripText("모든 차가 하차를 마치면 여행이 완료돼요",secondary=true,maxLines=3)
    }
}

private fun tripPrivatePeople(stop: TripRouteStop): String? = stop.people.takeIf {it.isNotEmpty()}?.joinToString(", ")
    ?.let {it+if(stop.item.type=="pickup")" 탑승" else " 하차"}

@Composable
internal fun TripSegmentVoiceBar(voice: (@Composable (Modifier)->Unit)?) {
    // 높이가 정해지지 않은 자리라 내용 높이로 고정한다. 워키토키 주 버튼이 그 높이를 채운다.
    if(voice!=null)voice(Modifier.fillMaxWidth().height(IntrinsicSize.Min).heightIn(min=CarTokens.ButtonLarge))
    else CarButton("워키토키",{},Modifier.fillMaxWidth(),primary=true,enabled=false,icon=CarSymbol.Microphone)
}

@Composable
internal fun TripSegmentDrivingDashboard(trip: TripDetail,state: TripsPageState,voice: (@Composable (Modifier)->Unit)?,onSignal: ()->Unit={}) {
    val plan=trip.myCar?.routePlan
    val car=trip.myCar
    val stops=if(plan!=null && car!=null)TripRouteOrder.resolve(plan.segments.flatMap {it.items},trip,car) else emptyList()
    val next=stops.firstOrNull {it.key==plan?.next?.key}
    val presentation=remember(trip.id) {TripVoicePresentation()}
    CompositionLocalProvider(LocalTripVoicePresentation provides presentation) {
    BoxWithConstraints(Modifier.fillMaxSize().semantics {contentDescription="주행 전용 화면"}) {
        val short=maxHeight<CarTokens.DrivingShortBreakpoint
        val controls=if(short)CarTokens.ButtonDrivingCompact else CarTokens.ButtonDriving
        Column(Modifier.fillMaxSize(),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
            Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalAlignment=Alignment.CenterVertically) {
                TripText(plan?.let {tripSegmentPhaseLabel(it.phase)} ?: "우리 차 경로 확인 중",Modifier.weight(1f),style=CarType.Section,maxLines=2)
                CarGearBadge(state.gear)
            }
            // 히어로 카드가 남은 높이를 먼저 받고, 점수 카드는 내용 높이만 쓴다. 도착 확인은 이 화면에 없으므로
            // P단 도착 안내도 두지 않는다(정차 화면에서만 보인다).
            val mapStops=plan?.let {tripPrivateRouteStops(stops,it)}.orEmpty()
            CarCard(Modifier.weight(1f),tone=CarCardTone.SOFT,padding=PaddingValues(if(short)CarTokens.SpaceMedium else CarTokens.Frame),radius=CarTokens.RadiusHero) {
                CarPriorityColumn(Modifier.fillMaxWidth(),spacing=CarTokens.SpaceMedium,required={
                    TripText(when {plan==null->"우리 차 경로를 확인할 수 없어요";plan.phase=="waiting"->plan.joinPoint.name;plan.phase=="done"->"우리 차 주행 완료";else->next?.name ?: "다음 경로 확인 중"},
                        style=if(short)CarType.Section else CarType.DrivingHero,maxLines=2)
                    if(next!=null && state.driving.targetKey==next.key)CarMetadata(tripRemainingLabels(state.driving),secondary=false)
                    if(plan!=null && !presentation.receiving)KakaoCourseMap(mapStops,Modifier.height(CarTokens.MapDrivingHeight),numbersOnly=true,vehicle=state.driving.position.takeIf {plan.phase!="done"},
                        focus=next,follow=true,others=courseMapOtherCars(trip,state.otherCars))
                }) {
                    // 남은 높이에 다 들어갈 때만 순서대로 둔다. 잘린 채 보이는 줄을 남기지 않는다.
                    if(plan!=null && (!short || presentation.receiving)) {
                        CarRouteStrip(mapStops,state.driving,compact=true,showPosition=plan.phase!="done")
                        if(plan.phase!="done")TripCompanionProgress(trip,currentTripDisplay(trip),tripCompanionScores(trip,state))
                    }
                }
            }
            if(presentation.receiving)TripVoiceReceivingCard(presentation.ui,parked=false,modifier=Modifier.weight(1f))
            else CarCard(tone=CarCardTone.INK,padding=PaddingValues(CarTokens.Frame)) {
                TripText("여행 안전운전 점수",style=CarType.Section,maxLines=2)
                val result=state.liveCourseScore.takeIf {state.isCurrent && state.liveCourseId=="trip-total-v1"}
                TripText(result?.score?.let {"${it}점"} ?: "측정 대기",style=CarType.DrivingHero,maxLines=2)
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

@Composable
internal fun TripSegmentPreparationPage(trip: TripDetail,state: TripsPageState,enabled: Boolean,actions: TripUiActions,onBack: ()->Unit,onSaved: ()->Unit) {
    val car=trip.myCar?.takeIf {it.isMine}
    if(car==null) {CarEmptyState("등록된 차가 없어요",action={CarButton("뒤로",onBack)});return}
    fun initial(): List<TripRouteItem> {
        val saved=TripRouteOrder.initial(trip,car)
        return saved.filter {it.type=="pickup"}+TripRouteOrder.courseItems(trip)+
            (saved.filter {it.type=="drop"}+saved.mapNotNull {it.dropRef?.let {ref->TripRouteItem("drop",ref)}}).distinctBy {it.key}
    }
    var order by rememberSaveable(trip.id,car.id,stateSaver=TripRouteOrderSaver) {mutableStateOf(initial())}
    var revision by rememberSaveable(trip.id,car.id) {mutableStateOf(car.routeRevision)}
    val changed=revision!=car.routeRevision
    val editable=enabled && state.gear==TripGear.PARK && trip.state=="planned" && !changed
    val narrow=LocalTripLayoutWidth.current<CarTokens.Breakpoint
    val stops=TripRouteOrder.resolve(order,trip,car)
    Column(Modifier.fillMaxSize(),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
        TripHeading("출발 준비",car.numberedName,onBack) {CarGearBadge(TripGear.PARK)}
        val route: @Composable (Modifier)->Unit={modifier->
            Column(modifier,verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                TripPrivateOrderColumn("타는 곳","pickup",stops,Modifier,editable) {item,delta->order=tripMovePrivateItem(order,item,delta)}
                trip.courses.orEmpty().firstOrNull()?.stops?.firstOrNull()?.let {join->
                    TripText("합류 지점",style=CarType.Label,secondary=true)
                    TripText(join.name,style=CarType.Section,maxLines=2)
                }
                TripText("함께 가는 경로",style=CarType.Section)
                if(trip.courses.orEmpty().isEmpty())CarCard(tone=CarCardTone.DASHED) {
                    TripText("경로가 없어요",style=CarType.Section)
                }
                trip.courses.orEmpty().forEachIndexed {index,course->CarCard(tone=CarCardTone.INK) {
                    Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalAlignment=Alignment.CenterVertically) {
                        TripText("${index+1}. ${course.title}",Modifier.weight(1f),style=CarType.Section,maxLines=2)
                        CarIcon(CarSymbol.Lock,color=LocalCarPalette.current.onInkSecondary)
                    }
                    course.stops.orEmpty().forEach {stop->TripText(stop.name,style=CarType.Label,secondary=true,maxLines=2)}
                }}
                TripPrivateOrderColumn("내리는 곳","drop",stops,Modifier,editable) {item,delta->order=tripMovePrivateItem(order,item,delta)}
                car.passengers.filter {person->car.places.orEmpty().none {it.kind=="drop" && person.id in it.selectedBy.orEmpty()}}.forEach {person->
                    CarInfoHint("${person.name}님의 내리는 곳이 정해지지 않았어요")
                }
            }
        }
        val mapAndSave: @Composable (Modifier)->Unit={modifier->
            Column(modifier,verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                KakaoCourseMap(stops,Modifier.height(CarTokens.MapPreviewHeight),interactive=enabled && state.gear==TripGear.PARK)
                if(changed)CarInfoHint("경로가 바뀌었어요. 새 경로를 불러와 주세요")
                Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                    CarButton(if(changed)"새 경로 불러오기" else "되돌리기",{order=initial();revision=car.routeRevision},Modifier.weight(1f),enabled=enabled)
                    CarButton("저장",{actions.saveOrder(order,revision,onSaved)},Modifier.weight(1f),primary=true,
                        enabled=editable && TripRouteOrder.preservesCourses(order,trip))
                }
                CarPhoneHandoff("trip-route")
            }
        }
        if(narrow)Column(Modifier.weight(1f).verticalScroll(rememberScrollState()),verticalArrangement=Arrangement.spacedBy(CarTokens.Frame)) {
            route(Modifier.fillMaxWidth());mapAndSave(Modifier.fillMaxWidth())
        } else Row(Modifier.weight(1f),horizontalArrangement=Arrangement.spacedBy(CarTokens.Frame)) {
            route(Modifier.weight(1f).fillMaxHeight().verticalScroll(rememberScrollState()))
            mapAndSave(Modifier.weight(1f).fillMaxHeight().verticalScroll(rememberScrollState()))
        }
    }
}

/** Preserve every item field so restoring a draft does not silently change route identity. */
internal val TripRouteOrderSaver = listSaver<List<TripRouteItem>,Any?>(
    save={items->items.flatMap {listOf(it.type,it.ref,it.courseId,it.dropRef)}},
    restore={fields->fields.chunked(4).map {TripRouteItem(it[0] as String,it[1] as String,it[2] as String?,it[3] as String?)}}
)

private fun tripMovePrivateItem(order: List<TripRouteItem>,item: TripRouteItem,delta: Int): List<TripRouteItem> {
    val own=order.filter {it.type==item.type}
    val index=own.indexOfFirst {it.key==item.key}
    val moved=TripRouteOrder.move(own,index,delta)
    var position=0
    return order.map {if(it.type==item.type)moved[position++] else it}
}

@Composable
private fun TripPrivateOrderColumn(title: String,kind: String,stops: List<TripRouteStop>,modifier: Modifier,enabled: Boolean,
    onMove: (TripRouteItem,Int)->Unit) {
    val rows=stops.filter {it.item.type==kind}
    Column(modifier,verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
        TripText(title,style=CarType.Section)
        CarCard(tone=CarCardTone.DASHED) {
            if(rows.isEmpty())TripText(if(kind=="pickup")"타는 곳이 없어요" else "내리는 곳이 없어요",secondary=true,maxLines=2)
            rows.forEachIndexed {index,stop->
                Column(Modifier.fillMaxWidth(),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                    TripText("${index+1}. ${stop.name}",style=CarType.Section,maxLines=2)
                    tripPrivatePeople(stop)?.let {TripText(it,secondary=true,maxLines=3)}
                    Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                        CarButton("위로",{onMove(stop.item,-1)},Modifier.weight(1f),enabled=enabled && index>0,icon=CarSymbol.Up,accessibility="${stop.name} 순서 위로")
                        CarButton("아래로",{onMove(stop.item,1)},Modifier.weight(1f),enabled=enabled && index<rows.lastIndex,icon=CarSymbol.Down,accessibility="${stop.name} 순서 아래로")
                    }
                }
            }
        }
        if(rows.isEmpty())CarPhoneHandoff(if(kind=="pickup")"pickup" else "drop")
    }
}

/** [optional] 앞에서부터 [required]와 함께 [maxHeight] 안에 다 들어가는 항목 수. 하나라도 넘치면 그 뒤는 세지 않는다. */
internal fun carPriorityOptionalCount(required: List<Int>,optional: List<Int>,gap: Int,maxHeight: Int): Int {
    var count=required.size
    var used=required.sum()+gap*(count-1).coerceAtLeast(0)
    optional.forEachIndexed {index,height->
        val next=used+(if(count==0)0 else gap)+height
        if(next>maxHeight)return index
        used=next;count++
    }
    return optional.size
}

/**
 * 높이가 정해진 주행 카드 안에서 [required]를 먼저 두고, [optional]의 각 항목은 순서대로 남은 높이에 다 들어갈 때만 둔다.
 * 앞 항목이 들어가지 않으면 뒤 항목도 두지 않아 우선순위를 지킨다. 측정만 하고 놓지 않은 항목은 그려지지 않는다.
 */
@Composable
internal fun CarPriorityColumn(modifier: Modifier=Modifier,spacing: Dp,required: @Composable ()->Unit,optional: @Composable ()->Unit) {
    Layout(contents=listOf(required,optional),modifier=modifier) {(must,extra),constraints->
        val gap=spacing.roundToPx()
        val child=Constraints(maxWidth=constraints.maxWidth)
        val first=must.map {it.measure(child)}
        val rest=extra.map {it.measure(child)}
        val placed=first+rest.take(carPriorityOptionalCount(first.map {it.height},rest.map {it.height},gap,constraints.maxHeight))
        val used=placed.sumOf {it.height}+gap*(placed.size-1).coerceAtLeast(0)
        val width=if(constraints.hasBoundedWidth)constraints.maxWidth else placed.maxOfOrNull {it.width} ?: 0
        layout(constraints.constrainWidth(width),constraints.constrainHeight(used)) {
            var y=0
            placed.forEach {it.placeRelative(0,y);y+=it.height+gap}
        }
    }
}

/** 고정 경로 카드에서 지도가 받을 높이(0이면 두지 않음)와 진행 바·함께 가는 차 줄을 둘지. */
internal data class TripFixedRouteFit(val mapHeight: Int,val strip: Boolean,val extra: Boolean)

/**
 * 고정 경로 카드의 높이 우선순위. [top](다음 장소·길 안내·도착 버튼)은 항상 두고, 다음으로 진행 바([strip])를
 * 다 들어갈 때만 둔다. 남은 높이가 모자라면 함께 가는 차 줄([extra])을 먼저 빼고, 지도를 [mapMax]에서 [mapMin]까지 줄이며,
 * 그래도 모자라면 지도를 뺀다. 잘린 채 보이는 줄은 남기지 않는다.
 */
internal fun tripFixedRouteFit(maxHeight: Int,top: Int,strip: Int,extra: Int,gap: Int,mapMin: Int,mapMax: Int): TripFixedRouteFit {
    if(maxHeight==Constraints.Infinity)return TripFixedRouteFit(mapMax,strip>0,extra>0)
    val showStrip=strip>0 && top+gap+strip<=maxHeight
    val room=maxHeight-top-(if(showStrip)gap+strip else 0)-gap
    if(extra>0 && room-gap-extra>=mapMax)return TripFixedRouteFit(mapMax,showStrip,true)
    val map=minOf(mapMax,room)
    return TripFixedRouteFit(if(map>=mapMin)map else 0,showStrip,false)
}

/**
 * 고정 경로 카드의 내용. [top](다음 장소와 주요 동작), [map], [strip](진행 바), [extra]를 차례로 쌓되,
 * 받은 높이에서 [reserve]를 뺀 높이 안에 [tripFixedRouteFit] 우선순위로 맞춘다. 지도는 정한 높이로만 잰다.
 */
@Composable
internal fun TripFixedRouteColumn(reserve: Dp,top: @Composable ()->Unit,map: @Composable ()->Unit,strip: @Composable ()->Unit,extra: @Composable ()->Unit) {
    Layout(contents=listOf(top,map,strip,extra),modifier=Modifier.fillMaxWidth()) {(heads,maps,strips,extras),constraints->
        val gap=CarTokens.SpaceMedium.roundToPx()
        val child=Constraints(maxWidth=constraints.maxWidth)
        fun stack(items: List<Placeable>)=items.sumOf {it.height}+gap*(items.size-1).coerceAtLeast(0)
        val head=heads.map {it.measure(child)}
        val bar=strips.map {it.measure(child)}
        val more=extras.map {it.measure(child)}
        val available=if(constraints.hasBoundedHeight)(constraints.maxHeight-reserve.roundToPx()).coerceAtLeast(0) else Constraints.Infinity
        val fit=tripFixedRouteFit(available,stack(head),stack(bar),stack(more),gap,CarTokens.MapDrivingHeight.roundToPx(),CarTokens.MapPreviewHeight.roundToPx())
        val shown=if(fit.mapHeight>0)maps.map {it.measure(Constraints.fixed(constraints.maxWidth,fit.mapHeight))} else emptyList()
        val placed=head+shown+(if(fit.strip)bar else emptyList())+(if(fit.extra)more else emptyList())
        layout(constraints.maxWidth,constraints.constrainHeight(stack(placed))) {
            var y=0
            placed.forEach {it.placeRelative(0,y);y+=it.height+gap}
        }
    }
}

/**
 * 여행 진행 본문(경로 열 + 실시간 패널). [fixed]이면 경로 카드([route])를 화면 스크롤과 무관하게 고정하고
 * 나머지([rest]와 좁은 화면의 [panel])만 스크롤한다. 카드에는 아래 스크롤 영역이 한 줄은 보이도록 남길 높이를 넘긴다.
 * 넓은 화면은 [TripAdaptiveRow] 비율을 그대로 쓴다. 패널은 워키토키 연결을, 카드는 지도를 들고 있어
 * 배치가 바뀌어도 다시 만들지 않는다.
 */
@Composable
internal fun TripRouteBody(narrow: Boolean,fixed: Boolean,modifier: Modifier,panel: @Composable (Modifier)->Unit,
    rest: (@Composable ColumnScope.()->Unit)?=null,route: @Composable (reserve: Dp)->Unit) {
    val latestPanel=rememberUpdatedState(panel)
    val latestRoute=rememberUpdatedState(route)
    val livePanel=remember {movableContentOf {m: Modifier->latestPanel.value(m)}}
    val routeCard=remember {movableContentOf {reserve: Dp->latestRoute.value(reserve)}}
    if(narrow && fixed)Column(modifier,verticalArrangement=Arrangement.spacedBy(CarTokens.Frame)) {
        routeCard(CarTokens.Frame+CarTokens.ButtonDrivingCompact)
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()),verticalArrangement=Arrangement.spacedBy(CarTokens.Frame)) {
            rest?.invoke(this)
            livePanel(Modifier.height(CarTokens.DrivingShortBreakpoint))
        }
    } else TripAdaptiveRow(modifier.then(if(narrow)Modifier.verticalScroll(rememberScrollState()) else Modifier),narrow=narrow,gap=CarTokens.Frame) {
        Column(Modifier.weight(1.25f).then(when {narrow->Modifier;fixed->Modifier.fillMaxHeight();else->Modifier.verticalScroll(rememberScrollState())}),
            verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
            routeCard(if(fixed && rest!=null)CarTokens.Gap+CarTokens.ButtonDrivingCompact else 0.dp)
            if(rest!=null) {
                if(fixed)Column(Modifier.weight(1f).verticalScroll(rememberScrollState()),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap),content=rest)
                else rest()
            }
        }
        livePanel(Modifier.weight(1f).then(if(narrow)Modifier.height(CarTokens.DrivingShortBreakpoint) else Modifier.fillMaxHeight()))
    }
}
