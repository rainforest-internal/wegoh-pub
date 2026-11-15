package io.wegoh.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import io.wegoh.app.*
import io.wegoh.app.nativeauth.*

@Composable
internal fun VehicleTripListPage(state: TripsPageState,onRefresh: ()->Unit,onSelect: (String)->Unit,
    onRespond: (String,Boolean,Boolean?)->Unit,onNew: ()->Unit,onConnection: ()->Unit) = TripSurface {
    val list=state.list
    if(list==null) {
        if(state.status==AccountReadStatus.LOADING)CarLoadingState("여행 불러오는 중",Modifier.fillMaxSize())
        else TripStatePanel(CarSymbol.Group,when(state.status) {
            AccountReadStatus.CONNECTION_REQUIRED->"차량 연결이 필요해요"
            AccountReadStatus.PERMISSION_REQUIRED->"여행 접근 권한이 필요해요"
            else->"여행을 불러오지 못했어요"
        },when(state.status) {
            AccountReadStatus.CONNECTION_REQUIRED->"iPhone에서 차량을 연결해 주세요"
            AccountReadStatus.PERMISSION_REQUIRED->"연결 관리에서 계정을 확인해 주세요"
            else->null
        }) {
            CarButton("다시 불러오기",onRefresh,Modifier.fillMaxWidth(),primary=true,icon=CarSymbol.Refresh,enabled=!state.busy)
            CarButton("연결 관리",onConnection,Modifier.fillMaxWidth(),icon=CarSymbol.Link)
            if(state.status!=AccountReadStatus.CONNECTION_REQUIRED)CarErrorReport("trip.list")
        }
        return@TripSurface
    }
    val ordered=list.trips.sortedBy {when(it.state){"active"->0;"completed","cancelled"->2;else->1}}
    val narrow=LocalTripLayoutWidth.current<CarTokens.Breakpoint
    if(narrow)LazyColumn(Modifier.fillMaxSize(),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
        item {CarMetadata(listOf("내 여행",list.trips.size.toString()),style=CarType.Title,secondary=false)}
        if(ordered.isEmpty())item {TripText("참여 중인 여행이 없어요",secondary=true)}
        items(ordered,key={it.id}) {trip->TripHomeCard(trip,state.isCurrent && !state.busy) {onSelect(trip.id)}}
        state.notice?.let {notice->item {TripText(notice,maxLines=CarMessageLines)}}
        item {CarMetadata(listOf("받은 초대",list.invitations.size.toString()),style=CarType.Title,secondary=false)}
        if(list.invitations.isEmpty())item {TripText("받은 초대가 없어요",secondary=true)}
        items(list.invitations,key={"invite:${it.tripId}"}) {TripInvitationCard(it,state.canRespond,onRespond)}
        item {CarPhoneHandoff("trip-new")}
    } else Row(Modifier.fillMaxSize(),horizontalArrangement=Arrangement.spacedBy(CarTokens.Frame)) {
        LazyColumn(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
            item {Row(horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),verticalAlignment=Alignment.CenterVertically) {
                TripText("내 여행",style=CarType.Title);TripText(list.trips.size.toString(),secondary=true)
            }}
            if(ordered.isEmpty())item {TripText("참여 중인 여행이 없어요",secondary=true)}
            items(ordered,key={it.id}) {trip->TripHomeCard(trip,state.isCurrent && !state.busy) {onSelect(trip.id)}}
            state.notice?.let {notice->item {TripText(notice,maxLines=CarMessageLines)}}
        }
        LazyColumn(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
            item {Row(horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),verticalAlignment=Alignment.CenterVertically) {
                TripText("받은 초대",style=CarType.Title);TripText(list.invitations.size.toString(),secondary=true)
            }}
            if(list.invitations.isEmpty())item {TripText("받은 초대가 없어요",secondary=true)}
            items(list.invitations,key={"invite:${it.tripId}"}) {TripInvitationCard(it,state.canRespond,onRespond)}
            item {CarPhoneHandoff("trip-new")}
        }
    }
}

@Composable
private fun TripInvitationCard(invite: TripInvitation,canRespond: Boolean,onRespond: (String,Boolean,Boolean?)->Unit) {
    CarCard(tone=CarCardTone.SOFT) {
        TripText(invite.title,style=CarType.Section,maxLines=2)
        CarMetadata(listOf("${invite.ownerName}님의 초대",tripDateLabel(invite.startDate,invite.endDate)))
        if(invite.carCount!=null && invite.memberCount!=null)
            CarMetadata(listOf("차 ${invite.carCount}대","일행 ${invite.memberCount}명"))
        Row(horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
            CarButton("거절",{onRespond(invite.tripId,false,null)},Modifier.weight(1f),enabled=canRespond)
            CarButton("참여",{onRespond(invite.tripId,true,true)},Modifier.weight(1f),primary=true,enabled=canRespond)
        }
    }
}


/** 경로 미리보기 장소가 하나뿐이면 선 없는 표식 하나로는 뜻이 전해지지 않아 목적지 이름을 글로 보여 준다. */
internal fun tripRoutePreviewDestination(preview: List<TripRoutePreviewPlace>): String? =
    preview.singleOrNull()?.let {"목적지 ${it.name}"}

@Composable
private fun TripHomeCard(trip: TripSummary,enabled: Boolean,onSelect: ()->Unit) {
    val active=trip.state=="active"
    CarCard(tone=if(active)CarCardTone.INK else CarCardTone.OUTLINED) {
        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),verticalAlignment=Alignment.CenterVertically) {
            CarStatusPill(tripStateLabel(trip.state,trip.startDate),
                kind=if(active)CarStatusTone.ON_INK else CarStatusTone.NEUTRAL)
            if(active)Spacer(Modifier.weight(1f))
        }
        TripText(trip.title,style=CarType.Title,maxLines=2)
        CarMetadata(listOfNotNull(tripDateLabel(trip.startDate,trip.endDate),"만든 사람 ${trip.ownerName}","차 ${trip.carCount}대","일행 ${trip.memberCount}명",trip.myRole))
        val destination=tripRoutePreviewDestination(trip.routePreview)
        if(active && destination!=null)TripText(destination,maxLines=2)
        else if(active && trip.routePreview.isNotEmpty())CarRouteStrip(trip.routePreview.map {
            TripRouteStop(TripRouteItem("course",it.ref,it.courseId),it.name,null,null)
        },TripDrivingState(),compact=true,planned=true,showPosition=false,onInk=true)
        CarButton("여행 열기",onSelect,Modifier.fillMaxWidth(),enabled=enabled,
            variant=if(active)CarButtonStyle.ON_INK else CarButtonStyle.OUTLINE,accessibility="${trip.title} 여행 열기")
    }
}

internal enum class TripScreen { PLAN, GROUPS, MEMBERS, ROUTE, ROOM, EDIT, CAR_CREATE, CAR_MANAGE, CAR_SETTINGS, ACTIVE, DEPARTURE, DRIVING, HISTORY, MUSIC, MISSIONS }

@Composable
internal fun VehicleTripDetailPage(state: TripsPageState,onBack: ()->Unit,onRefresh: ()->Unit,
    actions: TripUiActions,setupAllowed: Boolean,courses: AccountCourseState,onCoursesLoad: ()->Unit,onRemote: ()->Unit,
    voice: (@Composable (TripDetail,Boolean,Modifier)->Unit)?=null,
    music: (@Composable (TripDetail,Boolean,()->Unit)->Unit)?=null,
    openMusicOnEntry: Boolean=false,onMusicEntryHandled: ()->Unit={},
    history: @Composable ()->Unit) = TripSurface {
    val trip=state.detail
    if(trip==null) {
        CarChildBackHandler(enabled=true,onBack=onBack)
        if(state.busy)CarLoadingState("여행 불러오는 중",Modifier.fillMaxSize())
        else CarEmptyState("여행을 불러오지 못했어요",Modifier.fillMaxSize(),action={CarActionGroup {
            CarButton("다시 불러오기",onRefresh,Modifier.fillMaxWidth(),primary=true,icon=CarSymbol.Refresh)
            CarButton("여행 목록",onBack,Modifier.fillMaxWidth(),icon=CarSymbol.Back)
        };CarErrorReport("trip.detail")})
        return@TripSurface
    }
    var signalRequest by remember(trip.id) {mutableStateOf(false)}
    val signalControls=state.canUseSignalControls(setupAllowed)
    LaunchedEffect(signalControls,state.signals.overlay?.id) {
        if(!signalControls || state.signals.overlay?.isGroupDecision==true)signalRequest=false
    }
    val openSignal: (() ->Unit)? = if(signalControls && state.isCurrent) {
        {signalRequest=true}
    } else null
    if(signalRequest && signalControls)TripSignalDialog({signalRequest=false}) {
        TripSignalRequestPage(trip,state.signals,trip.signalRouteStop(state.driving),actions,
            driving=state.usesDrivingSignalComposer(),gear=state.gear) {signalRequest=false}
    }
    val root=when(trip.state){"active"->TripScreen.ACTIVE;"completed","cancelled"->TripScreen.HISTORY;else->TripScreen.PLAN}
    val roomAllowed=setupAllowed && state.gear==TripGear.PARK && root!=TripScreen.HISTORY
    var screen by rememberSaveable(trip.id) {mutableStateOf(root)}
    var musicReturn by rememberSaveable(trip.id) {mutableStateOf(root)}
    LaunchedEffect(trip.id,openMusicOnEntry,roomAllowed) {
        if(openMusicOnEntry && roomAllowed) {musicReturn=root;screen=TripScreen.MUSIC;onMusicEntryHandled()}
    }
    var departureReturn by rememberSaveable(trip.id) {mutableStateOf(TripScreen.ACTIVE)}
    var previousGear by rememberSaveable(trip.id) {mutableStateOf(state.gear)}
    var previousTripState by rememberSaveable(trip.id) {mutableStateOf(trip.state)}
    val currentActions by rememberUpdatedState(actions)
    DisposableEffect(trip.id) {onDispose {currentActions.clearLink()}}
    LaunchedEffect(trip.state) {
        if(previousTripState!=trip.state) {
            screen=root
            previousTripState=trip.state
        }
    }
    val preparationScreen=screen in setOf(TripScreen.GROUPS,TripScreen.MEMBERS,TripScreen.ROUTE,TripScreen.CAR_CREATE,TripScreen.CAR_MANAGE,TripScreen.CAR_SETTINGS)
    val roomScreen=preparationScreen || screen==TripScreen.MUSIC
    val page=when {
        trip.state=="active" && state.gear==TripGear.DRIVE->TripScreen.DRIVING
        screen in setOf(TripScreen.ROOM,TripScreen.MISSIONS,TripScreen.EDIT) || screen==TripScreen.HISTORY && root!=TripScreen.HISTORY->root
        roomScreen && !roomAllowed->root
        else->screen
    }
    LaunchedEffect(roomAllowed,root) {
        if(!roomAllowed && roomScreen)screen=page
    }
    LaunchedEffect(trip.canEdit,trip.canInvite,trip.myCar?.isMine,trip.me?.hasVehicle) {
        if(screen in setOf(TripScreen.CAR_MANAGE,TripScreen.CAR_SETTINGS,TripScreen.DEPARTURE) && trip.myCar?.isMine!=true ||
            screen==TripScreen.CAR_CREATE && (trip.me?.hasVehicle!=true || trip.myCar?.isMine==true))screen=root
    }
    LaunchedEffect(state.gear,trip.state) {
        if(state.gear!=TripGear.PARK && screen==TripScreen.DEPARTURE)screen=departureReturn
        if(trip.state=="active") {
            if(state.gear==TripGear.DRIVE)screen=TripScreen.DRIVING
            else if(state.gear==TripGear.PARK && previousGear!=TripGear.PARK)screen=TripScreen.ACTIVE
        }
        previousGear=state.gear
    }
    val childBack=remember(trip.id) {CarChildBackState()}
    val navigateBack: ()->Unit={
        val nested=childBack.action
        when {
            nested!=null->nested()
            page==root || page==TripScreen.DRIVING->onBack()
            else->screen=when(page) {
                TripScreen.MUSIC->musicReturn
                TripScreen.DEPARTURE->departureReturn
                TripScreen.CAR_SETTINGS->TripScreen.CAR_MANAGE
                else->root
            }
        }
    }
    CarChildBackHandler(enabled=true,onBack=navigateBack)
    val editable=setupAllowed && state.isCurrent && !state.busy
    val depart: ()->Unit = {if(state.gear==TripGear.PARK && editable){departureReturn=screen;screen=TripScreen.DEPARTURE}}
    val selectPreparation: (TripPlanTab)->Unit={tab->
        if(roomAllowed && editable)screen=when(tab) {
            TripPlanTab.OVERVIEW->root
            TripPlanTab.GROUPS->TripScreen.GROUPS
            TripPlanTab.MEMBERS->TripScreen.MEMBERS
            TripPlanTab.ROUTE->TripScreen.ROUTE
        }
    }
    val createCar: ()->Unit={if(roomAllowed && editable && trip.me?.hasVehicle==true && trip.myCar?.isMine!=true)screen=TripScreen.CAR_CREATE}
    val manageCar: ()->Unit={if(roomAllowed && editable && trip.myCar?.isMine==true)screen=TripScreen.CAR_MANAGE}
    val openMusic: (() ->Unit)?=music?.let {{if(roomAllowed && editable){musicReturn=page;screen=TripScreen.MUSIC}}}
    CompositionLocalProvider(LocalCarChildBackState provides childBack) {
    Column(Modifier.fillMaxSize(),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
        if(state.notice!=null)Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
            TripText(state.notice,Modifier.weight(1f),maxLines=CarMessageLines)
            CarButton("다시 불러오기",onRefresh,enabled=!state.busy && setupAllowed)
        }
        Box(Modifier.weight(1f)) {
            when(page) {
                TripScreen.ROOM,TripScreen.MISSIONS,TripScreen.EDIT->Unit
                TripScreen.PLAN->TripPlanPage(trip,editable && roomAllowed,navigateBack,actions,null,{selectPreparation(TripPlanTab.MEMBERS)},
                    createCar,manageCar,courses,onCoursesLoad,gear=state.gear,onPickupOrder=depart.takeIf {state.gear==TripGear.PARK},
                    onGroups={selectPreparation(TripPlanTab.GROUPS)},onMembers={selectPreparation(TripPlanTab.MEMBERS)},onRoute={selectPreparation(TripPlanTab.ROUTE)})
                TripScreen.GROUPS->TripGroupsPage(trip,editable && roomAllowed,navigateBack,actions,createCar,manageCar,state.gear,selectPreparation)
                TripScreen.MEMBERS->TripInvitePage(trip,state,editable && roomAllowed,actions,navigateBack,state.gear,selectPreparation)
                TripScreen.ROUTE->TripPreparationRoutePage(trip,editable && roomAllowed,navigateBack,actions,courses,onCoursesLoad,state.gear,selectPreparation)
                TripScreen.CAR_CREATE->TripCarCreatePage(trip,null,editable && state.gear==TripGear.PARK,actions,navigateBack,state.gear)
                TripScreen.CAR_SETTINGS->TripCarCreatePage(trip,trip.myCar,editable && state.gear==TripGear.PARK,actions,navigateBack,state.gear)
                TripScreen.CAR_MANAGE->TripCarManagePage(trip,editable,actions,navigateBack,{screen=TripScreen.CAR_SETTINGS},depart,
                    state.gear==TripGear.PARK,state.gear,onRemote)
                TripScreen.ACTIVE->TripActivePage(trip,state,editable,actions,navigateBack,depart,{},openSignal,
                    voice=if(voice==null)null else {modifier->voice(trip,setupAllowed && state.isCurrent && state.signals.overlay==null,modifier)},
                    onMusic=openMusic)
                // 여행 다시 읽기(isCurrent=false) 중에도 화면은 그대로다. 음악·함께 듣기는 자기 연결로 따로 확인하므로
                // 이를 화면 이탈로 넘기면 함께 듣기가 멈춘다.
                TripScreen.MUSIC->music?.invoke(trip,roomAllowed,navigateBack)
                TripScreen.DEPARTURE->TripDeparturePage(trip,state,editable && state.gear==TripGear.PARK,actions,navigateBack,
                    {screen=if(trip.state=="active")TripScreen.ACTIVE else departureReturn})
                TripScreen.DRIVING->TripDrivingPage(trip,state,editable,actions)
                TripScreen.HISTORY->TripResultPage(trip,navigateBack,
                    tripScore=state.liveCourseScore.takeIf {state.isCurrent && state.liveCourseId=="trip-total-v1"},
                    drivingVersus=state.drivingVersus,drivingVersusLoading=state.drivingVersusLoading,
                    drivingVersusNotice=state.drivingVersusNotice,refreshDrivingVersus=actions.refreshDrivingVersus,history={})
            }
        }
    }
    }
}

@Composable
internal fun TripStatePanel(symbol: CarSymbol,title: String,detail: String?,actions: @Composable ColumnScope.()->Unit) {
    CarEmptyState(title,Modifier.fillMaxSize(),detail,symbol) {
        Column(Modifier.fillMaxWidth(),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap),content=actions)
    }
}
