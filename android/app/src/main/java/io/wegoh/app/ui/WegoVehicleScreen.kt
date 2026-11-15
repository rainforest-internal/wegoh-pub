package io.wegoh.app.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.semantics.toggleableState
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.onClick
import androidx.compose.ui.semantics.disabled
import androidx.compose.ui.semantics.text
import androidx.compose.ui.state.ToggleableState
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.unit.dp
import io.wegoh.app.*
import io.wegoh.app.nativeauth.TripDetail
import kotlinx.coroutines.launch
import kotlinx.coroutines.delay

/** 제한 화면의 경로 진행(다음 장소, 방문 수). 실행 중이 아닌 선택 경로(내장 예시 포함)는 보이지 않는다. */
internal fun restrictedPackProgress(state: WegoState): Pair<String,String>? = state.selected?.takeIf {state.active}?.let {pack->
    (pack.stops.firstOrNull {it.id !in state.completed}?.name ?: "도착") to "${state.completed.size} / ${pack.stops.size}"
}

/** App-window UI only. Driving view, status bar and GNB belong to Pleos. */
@Composable
fun WegoVehicleScreen(
    state: WegoState, onSelect: (String) -> Unit, onImport: () -> Unit,
    onStart: () -> Unit, onStop: () -> Unit, onNavigate: () -> Unit, onReset: () -> Unit,
    onBrowse: () -> Unit, onDownload: (PublishedPack) -> Unit, onShareVisits: () -> Unit,
    onAccountCourses: () -> Unit = {},
    onAccountRefresh: (String)->Unit = {},
    onAccountSelect: (AccountCourse) -> Unit = {},
    onRootBack: () -> Unit = {},
    onSuspendConsent: () -> Unit = {},
    onWithdrawAndDelete: () -> Unit = {},
    onReport: (CourseReportReason) -> Unit = {},
    onSystemSettings: () -> Unit = {},
    onVehicleConnection: (() -> Unit)? = null,
    onLegalDocument: (String) -> Unit = {},
    onPlatform: (() -> Unit)? = null,
    onAccountPlaylists: () -> Unit = {},
    onPlaylistSelect: (PlaylistSummary) -> Unit = {},
    onPlaylistLink: (String,Long,String) -> Boolean = {_,_,_->false},
    onAccountProfile: (() -> Unit)? = null,
    onAccountDiscovery: (() -> Unit)? = null,
    onPublicDownload: (PublishedPack) -> Unit = {},
    accountFeatures: Boolean = true,
    tripsState: TripsPageState = TripsPageState(),
    onTripsLoad: ()->Unit = {},onTripsRefresh: ()->Unit = {},onTripSelect: (String)->Unit = {},
    onTripClose: ()->Unit = {},onTripRespond: (String,Boolean,Boolean?)->Unit = {_,_,_->},
    tripActions: io.wegoh.app.TripUiActions = io.wegoh.app.TripUiActions(),
    socialState: SocialPageState = SocialPageState(),
    onSocialLoad: ()->Unit = {},onSocialRefresh: ()->Unit = {},onRoomSelect: (String)->Unit = {},onRoomClose: ()->Unit = {},
    onSocialSignal: (io.wegoh.app.nativeauth.SocialSignalKind)->Unit = {},onFriendRespond: (String,Boolean)->Unit = {_,_->},
    onFriendManage: (String,Boolean)->Unit = {_,_->},
    onClimate: ()->Unit = {},
    tripVoice: (@Composable (TripDetail,Boolean,Modifier)->Unit)?=null,
    tripMusic: (@Composable (TripDetail,Boolean,()->Unit)->Unit)?=null,
    remoteReceiving: Boolean?=io.wegoh.app.VehicleClimateService.receiving,
    remoteMessage: String=io.wegoh.app.VehicleClimateService.message,
    remoteHistory: (@Composable ()->Unit)?=null,
    tripExtras: @Composable (TripSection)->Unit = {CarEmptyState("준비 중입니다")},
    carExtras: @Composable (CarSection,()->Unit)->Unit = {section,back->
        Column {TripHeading(section.title,onBack=back);CarEmptyState("준비 중입니다")}
    },
) {
    var addCourse by remember {mutableStateOf<PublishedPack?>(null)}
    var courseTrip by remember {mutableStateOf<String?>(null)}
    val landing=LocalVehicleLandingPage.current
    val navigator=rememberSaveable(saver=AppNavigator.Saver) {AppNavigator(if(!accountFeatures)AppDestination.HOME else AppDestination.fromId(landing) ?: AppDestination.TRIPS)}
    val page=navigator.current.id
    var popup by remember { mutableStateOf<String?>(null) }
    var permissionRefresh by remember {mutableIntStateOf(0)}
    var remoteRefresh by remember {mutableIntStateOf(0)}
    var profileSelection by rememberSaveable {mutableStateOf<String?>(null)}
    var detail by rememberSaveable { mutableStateOf(false) }
    var playlistDetails by rememberSaveable {mutableStateOf(false)}
    var musicTripRequest by rememberSaveable {mutableStateOf<String?>(null)}
    var playlistOpening by remember {mutableStateOf<String?>(null)}
    var reportReason by remember {mutableStateOf<CourseReportReason?>(null)}
    var reportSubmitted by remember {mutableStateOf(false)}
    var friendRequest by remember {mutableStateOf<io.wegoh.app.nativeauth.SocialFriendRequest?>(null)}
    val dismissedRequests=remember {mutableSetOf<String>()}
    LaunchedEffect(accountFeatures) {if(accountFeatures)onTripsLoad()}
    LaunchedEffect(accountFeatures,page,tripsState.selectedId) {
        if(accountFeatures && page=="trips" && tripsState.selectedId==null)onTripsRefresh()
    }
    LaunchedEffect(accountFeatures,page) {
        if(accountFeatures && page=="car")tripActions.refreshRemotePolicy()
    }
    LaunchedEffect(tripsState.signals.overlay?.id) {
        if(tripsState.signals.overlay?.isGroupDecision==true) {popup=null;friendRequest=null;addCourse=null;courseTrip=null}
    }
    LaunchedEffect(socialState.overview,state.setupAllowed) {
        val incoming=socialState.overview?.requests.orEmpty().filter {it.direction==io.wegoh.app.nativeauth.SocialFriendRequest.Direction.INCOMING}
        dismissedRequests.retainAll(incoming.map {it.person.id}.toSet())
        if(!state.setupAllowed || socialState.overview==null ||
            friendRequest?.let {current->incoming.none {it.person.id==current.person.id}}==true)friendRequest=null
        if(state.setupAllowed && socialState.isCurrent && socialState.overview?.friendsReadOnly==false && popup==null)
            friendRequest=incoming.firstOrNull {it.person.id !in dismissedRequests}
    }
    val courseList=rememberLazyListState()
    val accountList=rememberLazyListState()
    val scope=rememberCoroutineScope()
    var overviewClock by remember {mutableLongStateOf(android.os.SystemClock.elapsedRealtime())}
    LaunchedEffect(state.navigationOverview) {
        while(state.navigationOverview!=null){overviewClock=android.os.SystemClock.elapsedRealtime();delay(1000)}
    }
    val platformNavigation=LocalCarPageNavigation.current
    val childBack=remember(page) {CarChildBackState()}
    val back: ()->Unit={when {
        addCourse!=null->{addCourse=null;courseTrip=null;onTripClose()}
        popup!=null->{popup=null;reportSubmitted=false}
        childBack.action!=null->childBack.action?.invoke()
        page=="profile" && profileSelection!=null->profileSelection=null
        page in setOf("rooms","music") && navigator.canGoBack->navigator.back()
        detail->detail=false
        page=="music-picker"->{playlistOpening=null;navigator.replace(AppDestination.MUSIC)}
        page=="privacy"->navigator.replace(AppDestination.PROFILE)
        page=="account"->navigator.replace(AppDestination.HOME)
        else->onRootBack()
    }}
    BackHandler {back()}
    LaunchedEffect(page) {if(page!="music-picker")playlistOpening=null}
    LaunchedEffect(state.setupAllowed,tripsState.gear) {
        if(!state.setupAllowed || tripsState.gear==TripGear.DRIVE) {
            popup=null;reportSubmitted=false;playlistOpening=null;addCourse=null;courseTrip=null;friendRequest=null
        }
    }
    LaunchedEffect(state.reportBusy,state.reportOutcome,reportSubmitted) {
        if(state.setupAllowed && popup=="report" && reportSubmitted && !state.reportBusy && state.reportOutcome!=null) {
            reportSubmitted=false;popup=if(state.reportOutcome==CourseReportOutcome.ACCEPTED)"report-accepted" else "report-failed"
        }
    }
    LaunchedEffect(state.accountCourses.selected) {
        if(page=="account" && state.accountCourses.selected!=null) {navigator.replace(AppDestination.HOME);detail=true}
    }
    LaunchedEffect(state.accountCourses.status) {
        if(state.accountCourses.status!=AccountCourseStatus.READY) {popup=null;detail=false}
    }
    LaunchedEffect(page) {
        if(page in setOf("profile","rooms"))onSocialLoad()
        if(page=="profile") {onAccountProfile?.invoke();onAccountCourses();onTripsLoad()}
        if(page=="music")onAccountPlaylists()
    }
    LaunchedEffect(landing) {
        if(landing=="music-picker")onAccountPlaylists()
        if(landing=="profile")onAccountProfile?.invoke()
        if(landing=="discover")onAccountDiscovery?.invoke()
    }
    LaunchedEffect(state.accountPlaylists.selected,state.accountPlaylists.opening,playlistOpening,page) {
        if(page.startsWith("music") && playlistOpening!=null && state.accountPlaylists.selected?.summary?.id==playlistOpening && state.accountPlaylists.opening==null) {navigator.replace(AppDestination.MUSIC);playlistDetails=true;playlistOpening=null}
    }
    LaunchedEffect(state.accountPlaylists.status) {if(state.accountPlaylists.status!=AccountPlaylistStatus.READY)playlistOpening=null}
    val p=LocalCarPalette.current
    val currentTitle=when(page){"trips"->"여행";"home","courses"->"경로";"account"->"내 경로";"privacy"->"권한 관리";"music"->"음악";"music-picker"->"음악 고르기";"discover"->"공개 경로";"profile"->"프로필";"rooms"->"여행방";"car"->"리모컨";else->"경로"}
    val activeRoot=when(page){"music","music-picker"->"music";"account","home","courses","discover"->"courses";"rooms"->"trips";"privacy"->"profile";else->page}
    val menuItems=if(accountFeatures)PlatformRoutes.primary.map {target->
        CarPageItem(PlatformRoutes.titles.getValue(target),PlatformRoutes.symbol(target),target==activeRoot) {
            musicTripRequest=null;playlistDetails=false
            navigator.root(AppDestination.require(if(target=="courses")"home" else target));detail=false
            if(target!="car" && !(activeRoot=="car" && target=="trips"))onTripClose()
            when(target){"profile"->onAccountProfile?.invoke();"discover"->onAccountDiscovery?.invoke();"rooms"->onSocialLoad()}
        }
    } else listOf(CarPageItem("경로",CarSymbol.Route,page=="home"){navigator.replace(AppDestination.HOME);detail=false},
        CarPageItem("권한 관리",CarSymbol.Lock,page=="privacy"){navigator.replace(AppDestination.PRIVACY);detail=false})
    val refreshPage: ()->Unit={when(page) {
        "trips"->onTripsRefresh()
        "rooms"->onSocialRefresh()
        "car"->{tripActions.refreshRemotePolicy();remoteRefresh++}
        "profile"->{onAccountRefresh(page);onSocialRefresh()}
        "privacy"->permissionRefresh++
        else->onAccountRefresh(page)
    }}
    val refreshEnabled=state.setupAllowed && state.storageReady && when {
        page=="account"->!state.active && state.accountCourses.downloading==null && state.accountCourses.status!=AccountCourseStatus.LOADING
        page.startsWith("music")->state.accountPlaylists.status!=AccountPlaylistStatus.LOADING
        page=="profile"->state.accountProfile.status!=AccountReadStatus.LOADING && !socialState.busy
        page=="discover"->state.accountDiscovery.status!=AccountReadStatus.LOADING && state.accountDiscovery.downloading==null
        page=="trips"->!tripsState.busy
        page=="rooms"->!socialState.busy
        page=="car"->tripsState.remotePolicySnapshot.status!=AccountReadStatus.LOADING
        else->!state.active
    }
    if(accountFeatures && tripsState.showsDrivingDashboard(state.setupAllowed)) {
        TripDrivingHost(tripsState,tripActions,onRootBack=onRootBack,setupAllowed=state.setupAllowed,voice=tripVoice)
        return
    }
    Box(Modifier.fillMaxSize()) {
    CompositionLocalProvider(LocalCarChildBackState provides childBack,LocalCarRemoteRefresh provides remoteRefresh) {
    Box(Modifier.fillMaxSize().then(if(tripsState.signals.overlay?.isGroupDecision==true)Modifier.clearAndSetSemantics {} else Modifier)) {
    CarScreenScaffold(currentTitle,back,{if(page=="trips")onTripClose();navigator.root(if(accountFeatures)AppDestination.DISCOVER else AppDestination.HOME);detail=false;onAccountDiscovery?.invoke()},
            menuItems,showHeader=state.setupAllowed,menuEnabled=state.setupAllowed&&state.storageReady,
            primaryTabs=accountFeatures,receiving=remoteReceiving.takeUnless {page=="car"},onRefresh=refreshPage,refreshEnabled=refreshEnabled,suffix={
                if(accountFeatures && state.setupAllowed && state.storageReady)CarIconAction("새로고침",CarSymbol.Refresh,refreshPage,refreshEnabled)
        }) {
        if(accountFeatures && state.setupAllowed && page !in setOf("trips","profile","privacy") && !(page in setOf("home","courses") && detail) &&
            (childBack.action!=null || profileSelection!=null && page=="profile" || detail || page in setOf("rooms","privacy","account","music-picker")))
            CarContentBack(currentTitle,back)
        BoxWithConstraints(Modifier.weight(1f).fillMaxWidth()) {
            val wide=maxWidth>=CarTokens.LegacyCourseBreakpoint
            when {
                state.setupAllowed && !state.storageReady -> Column(Modifier.fillMaxSize(),verticalArrangement=Arrangement.Center,horizontalAlignment=Alignment.CenterHorizontally) {
                    CarIcon(CarSymbol.Lock,Modifier.size(CarTokens.IconLarge))
                    CarText("저장한 기록을 열 수 없어요",style=CarType.Section)
                    CarText("기존 기록은 보존됩니다",secondary=true)
                    Spacer(Modifier.height(CarTokens.SpaceLarge))
                    CarAction("기기 설정",CarSymbol.Settings,onSystemSettings)
                }
                page=="trips" && tripsState.detail?.state=="active" && tripsState.gear==io.wegoh.app.TripGear.DRIVE ->
                    VehicleTripDetailPage(tripsState,onTripClose,onTripsRefresh,tripActions,state.setupAllowed,
                        state.accountCourses,onAccountCourses,{navigator.root(AppDestination.CAR)},tripVoice,tripMusic) {tripExtras(TripSection.HISTORY)}
                !state.setupAllowed -> CarRestrictedState(when {
                    state.policy.contains("대기") || state.policy.contains("실패") -> "차량 연결 확인"
                    state.active -> "경로 진행 중"
                    else -> CAR_PARK_REQUIRED
                },Modifier.fillMaxSize(),detail=restrictedPackProgress(state)?.first,
                    progress=restrictedPackProgress(state)?.second,
                    onStop=onStop.takeIf {state.active})
                page=="trips" -> if(tripsState.selectedId!=null)VehicleTripDetailPage(tripsState,onTripClose,onTripsRefresh,
                    tripActions,state.setupAllowed,state.accountCourses,onAccountCourses,{navigator.root(AppDestination.CAR)},tripVoice,tripMusic,
                        openMusicOnEntry=musicTripRequest!=null && musicTripRequest==tripsState.selectedId,onMusicEntryHandled={musicTripRequest=null}) {tripExtras(TripSection.HISTORY)}
                    else VehicleTripListPage(tripsState,onTripsRefresh,{musicTripRequest=null;onTripSelect(it)},onTripRespond,{popup="phone-trip-new"},
                        {onVehicleConnection?.invoke()})
                accountFeatures && page in setOf("home","courses") && !detail -> VehicleCoursesPage(state,onAccountCourses,
                    {onAccountDiscovery?.invoke()},{onSelect(it);detail=true},{course->
                        navigator.replace(AppDestination.ACCOUNT);onAccountSelect(course)
                        if(state.accountCourses.selected?.key==course.published.key) {navigator.replace(AppDestination.HOME);detail=true}
                    },onPublicDownload,
                    {onVehicleConnection?.invoke()},{addCourse=it;courseTrip=null;onTripsLoad()},
                    onRefresh={onAccountRefresh("courses")})
                page=="rooms" -> VehicleTripsPage(socialState,onSocialLoad,onSocialRefresh,onRoomSelect,onRoomClose,onSocialSignal,{popup="phone-together"},tripExtras)
                page=="car" -> VehicleCarPage(remoteReceiving==true,remoteMessage,onClimate,
                    {onVehicleConnection?.invoke()},carExtras,remoteHistory,remotePolicy=currentTripRemotePolicy(tripsState),
                    remoteSnapshot=tripsState.remotePolicySnapshot.takeIf {tripsState.isCurrent})
                page=="profile" -> VehicleProfilesPage(state.accountProfile,socialState,profileSelection,{profileSelection=it},onFriendManage,
                    {onVehicleConnection?.invoke()}, {onAccountRefresh("profile")}, {navigator.replace(AppDestination.PRIVACY)},
                    courseCount=state.accountCourses.courses.map {it.published.id}.distinct().size.takeIf {state.accountCourses.status==AccountCourseStatus.READY && state.accountCourses.isCurrent},
                    tripCount=tripsState.list?.takeIf {tripsState.isCurrent}?.trips?.size,onBack=back)
                page=="discover" -> AccountDiscoveryScreen(state.accountDiscovery,state.packs.map {it.key}.toSet(),onPublicDownload,
                    onConnection=onVehicleConnection,
                    canDownload=!state.active && state.downloading==null && state.accountCourses.downloading==null)
                page.startsWith("music") -> {
                    val trip=tripsState.list?.takeIf {tripsState.isCurrent}?.trips?.firstOrNull {it.state=="active"}
                    AccountMusicScreen(state.accountPlaylists,page=="music-picker",
                        onPick={playlistDetails=false},onSelect={playlistOpening=it.id;onPlaylistSelect(it)},onConnection={onVehicleConnection?.invoke()},
                        onLink={id,version,track->if(!onPlaylistLink(id,version,track))popup="music-link-unavailable"},
                        currentTripTitle=trip?.title,
                        currentTripMusic=tripsState.detail?.takeIf {it.id==trip?.id && tripsState.isCurrent}?.let {currentTripDisplay(it)}?.music,
                        onTripMusic=trip?.let {current->{musicTripRequest=current.id;onTripSelect(current.id);navigator.root(AppDestination.TRIPS)}},showDetails=playlistDetails)
                }
                page=="privacy" -> VehiclePrivacyPage(state.locationConsented,onSuspendConsent,
                    onWithdraw={popup="withdraw"},onSettings=onSystemSettings,onDisclosure={popup="privacy-info"},
                    onPrivacyPolicy=if(!BuildConfig.DEBUG && BuildConfig.PRIVACY_URL.isNotBlank())({onLegalDocument(BuildConfig.PRIVACY_URL)}) else null,
                    onLocationTerms=if(!BuildConfig.DEBUG && BuildConfig.LOCATION_TERMS_URL.isNotBlank())({onLegalDocument(BuildConfig.LOCATION_TERMS_URL)}) else null,
                    onBack=back,permissionRefresh=permissionRefresh)
                page=="account" -> Column(Modifier.fillMaxSize(),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                    CarText("내 경로",style=CarType.Hero)
                    if(state.accountCourses.courses.isNotEmpty())Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically) {
                        val label=when(state.accountCourses.status) {
                            AccountCourseStatus.CONNECTION_REQUIRED -> "차량을 연결해 주세요"
                            AccountCourseStatus.PERMISSION_REQUIRED -> "이 차에서 경로를 볼 권한이 없어요"
                            AccountCourseStatus.LOADING -> "경로를 불러오는 중"
                            AccountCourseStatus.UNAVAILABLE -> "경로를 불러오지 못했어요"
                            AccountCourseStatus.READY -> "${state.accountCourses.courses.size}개"
                        }
                        CarText(label,Modifier.weight(1f),secondary=true)
                        CarScrollPosition(accountList,state.accountCourses.courses.size,"내 경로 목록")
                    }
                    if(state.accountCourses.courses.isEmpty()) {
                        when(state.accountCourses.status) {
                            AccountCourseStatus.LOADING->CarLoadingState("경로를 불러오는 중",Modifier.weight(1f))
                            AccountCourseStatus.READY->CarEmptyState("저장한 경로가 없어요",Modifier.weight(1f),
                                action={CarPhoneHandoff("course-save")})
                            AccountCourseStatus.CONNECTION_REQUIRED->CarConnectionState("차량을 연결해 주세요",Modifier.weight(1f),onConnect={onVehicleConnection?.invoke()})
                            AccountCourseStatus.PERMISSION_REQUIRED->CarConnectionState("이 차에서 경로를 볼 권한이 없어요",Modifier.weight(1f),
                                onConnect={onVehicleConnection?.invoke()})
                            AccountCourseStatus.UNAVAILABLE->CarFailureState("경로를 불러오지 못했어요",Modifier.weight(1f),reportScreen="account.courses",onRetry={onAccountRefresh("account")})
                        }
                    } else LazyColumn(Modifier.weight(1f).fillMaxWidth(),state=accountList,verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                    items(state.accountCourses.courses,key={it.published.key}) { course ->
                        val pack=course.published
                        val versionLabel=if(state.accountCourses.courses.count {it.published.id==pack.id}>1)"버전 ${pack.version}" else null
                        CarListRow(pack.title,listOfNotNull(pack.author,versionLabel,"${pack.stopCount}곳")+
                            if(course.available)emptyList() else listOf("열 수 없는 경로"),CarSymbol.Route,trailing={
                            CarAction("선택",CarSymbol.Check,{onAccountSelect(course);if(state.accountCourses.selected?.key==pack.key){navigator.replace(AppDestination.HOME);detail=true}},
                                enabled=state.accountCourses.isCurrent && course.available && !state.active && state.accountCourses.downloading==null,
                                busy=state.accountCourses.downloading==pack.key,accessibility=listOfNotNull(pack.title,versionLabel,"선택").joinToString(" "))
                        })
                    }
                    }

                }
                else -> if(accountFeatures && detail)VehicleCourseDetailPage(state,overviewClock,back,onNavigate,
                    if(state.active)onStop else { {if(state.locationConsented)onStart() else popup="consent"} },
                    {popup="reset"},{popup="error"},{popup="stop:$it"},{addCourse=it;courseTrip=null;onTripsLoad()})
                else Row(Modifier.fillMaxSize(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceXLarge)) {
                    if(wide || !detail) Column(Modifier.weight(1f).fillMaxHeight(),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                        Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically) {
                            CarText("경로 목록",Modifier.weight(1f),style=CarType.Section)
                            CarScrollPosition(courseList,state.packs.size,"경로 목록")
                        }
                        LazyColumn(Modifier.weight(1f).fillMaxWidth(),state=courseList,verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                        items(state.packs,key={it.key}) { pack ->
                            CarListRow(pack.title,listOf(pack.source,pack.author,"v${pack.version}","${pack.stops.size}곳"),CarSymbol.Route,
                                selected=pack.key==state.selectedKey,enabled=!state.active&&!state.reportBusy,
                                onClick={onSelect(pack.key);if(!wide)detail=true})
                        }
                        if(state.packs.isEmpty())item {CarText("경로를 추가하세요",secondary=true)}
                        }

                    }
                    if(wide || detail) Column(Modifier.weight(1.1f).fillMaxHeight(),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceLarge)) {
                        val pack=state.selected
                        Column(Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceLarge)) {
                            if(pack!=null) {
                                CarText(pack.title,style=CarType.Section,maxLines=2)
                                if(state.completed.size==pack.stops.size)CourseDrivingResultCard(state.courseResult)
                                Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically) {
                                    CarText("경로 전체",secondary=true)
                                    Spacer(Modifier.weight(1f))
                                    CarText("방문 ${state.completed.size} / ${pack.stops.size}",style=CarType.Label,secondary=true)
                                    if(!state.active&&state.completed.isNotEmpty())CarIconAction("경로 기록 초기화",CarSymbol.Refresh,{popup="reset"})
                                }
                                CarText(pack.stops.firstOrNull()?.name ?: "도착",style=CarType.Hero,maxLines=2)
                                pack.stops.forEachIndexed { index,stop ->
                                    Row(Modifier.fillMaxWidth().heightIn(min=CarTokens.Touch).carTap(enabled=!state.active){popup="stop:$index"},
                                        verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceLarge)) {
                                        Box(Modifier.size(CarTokens.CourseStopBadgeSize).clip(RoundedCornerShape(CarTokens.CourseStopBadgeRadius)).background(p.low),contentAlignment=Alignment.Center) {
                                            if(stop.id in state.completed)CarIcon(CarSymbol.Check,color=p.success) else CarText("${index+1}",style=CarType.Label)
                                        }
                                        Column(Modifier.weight(1f)) {
                                            CarText(stop.name,maxLines=2)
                                            val estimate=state.navigationOverview?.takeIf {it.packKey==pack.key}
                                            CarMetadata(estimate.stopEstimates(stop.id,overviewClock),style=CarType.Caption)
                                        }
                                    }
                                }
                            }
                        }
                        if(state.navigationPhase!=NavigationPhase.IDLE)CarText(courseNavigationStatus(state.navigationPhase),
                            style=CarType.Label,secondary=true,maxLines=2)
                        if(state.error!=null) CarAction("문제 확인",CarSymbol.Alert,{popup="error"},Modifier.fillMaxWidth())
                        CarActionGroup {
                            CarAction("출발",CarSymbol.Navigate,onNavigate,primary=true,
                                enabled=pack!=null && state.accountCourses.downloading==null && (pack.source!=CoursesRepository.SOURCE || state.accountCourses.isCurrent),busy=state.navigationBusy)
                            CarAction(if(state.active)"종료" else "도착 알림",if(state.active)CarSymbol.Stop else CarSymbol.Pin,
                                if(state.active)onStop else { {if(state.locationConsented)onStart() else popup="consent"} },enabled=pack!=null && state.accountCourses.downloading==null && (state.active || !state.allVisited && (pack.source!=CoursesRepository.SOURCE || state.accountCourses.isCurrent)))
                        }
                    }
                }
            }
        }
    }
    }
    }
    addCourse?.takeIf {state.setupAllowed}?.let {course->
        CarPopup("여행에 추가",{addCourse=null;courseTrip=null},body={
            val target=tripsState.detail?.takeIf {it.id==courseTrip}
            TripText(course.title,style=CarType.Section,maxLines=2)
            if(courseTrip==null) {
                val available=tripsState.list?.trips.orEmpty().filter {it.state !in setOf("completed","cancelled")}
                if(tripsState.busy)TripText("여행을 불러오는 중")
                else if(!tripsState.isCurrent) {
                    TripText(tripsState.notice ?: "여행을 불러오지 못했어요",maxLines=3)
                    CarButton("다시 불러오기",onTripsRefresh,Modifier.fillMaxWidth())
                } else if(available.isEmpty())TripText("추가할 여행을 휴대전화에서 먼저 만들어주세요",maxLines=2)
                available.forEach {trip->
                    CarButton(trip.title,{courseTrip=trip.id;onTripSelect(trip.id)},Modifier.fillMaxWidth(),
                        enabled=tripsState.isCurrent && !tripsState.busy)
                }
                if(tripsState.list?.trips.isNullOrEmpty())TripText(carPhoneHint("trip-new"),maxLines=2)
            } else if(target==null) {
                if(tripsState.busy)TripText("여행을 불러오는 중")
                else {
                    TripText(tripsState.notice ?: "여행을 불러오지 못했어요",maxLines=3)
                    CarButton("다시 불러오기",{
                        if(tripsState.selectedId==courseTrip)onTripsRefresh()
                        else {courseTrip=null;onTripClose();onTripsRefresh()}
                    },Modifier.fillMaxWidth())
                }
            }
            else {
                TripText(target.title,style=CarType.Body,maxLines=2)
                tripsState.notice?.let {TripText(it,maxLines=3)}
                if(!tripsState.isCurrent && !tripsState.busy)CarButton("다시 불러오기",onTripsRefresh,Modifier.fillMaxWidth())
                CarAction("여행에 추가",CarSymbol.Plus,{tripActions.perform(io.wegoh.app.nativeauth.TripAction.AddCourse(course.id)) {
                    addCourse=null;courseTrip=null;navigator.root(AppDestination.TRIPS)
                }},Modifier.fillMaxWidth(),primary=true,busy=tripsState.busy,enabled=target.canAddCourse && tripsState.isCurrent && !tripsState.busy &&
                    target.courses.orEmpty().size<10 && target.courses.orEmpty().none {it.packId==course.id})
            }
        },actions={CarButton("취소",{addCourse=null;courseTrip=null;onTripClose()})})
    }
    if(friendRequest!=null && state.setupAllowed && socialState.overview!=null) {
        val request=friendRequest!!
        val dismiss={dismissedRequests.add(request.person.id);friendRequest=null;Unit}
        CarPopup("친구 요청",dismiss,body={
            CarText(request.person.name ?: "친구",maxLines=3)
            if(socialState.busy)CarText("처리 중",secondary=true,maxLines=2)
            else if(!socialState.isCurrent) {
                CarText(socialState.notice ?: "처리 결과를 확인하지 못했어요",secondary=true,maxLines=3)
                CarButton("다시 불러오기",onSocialRefresh,Modifier.fillMaxWidth())
            }
        },actions={
            val canRespond=socialState.isCurrent && !socialState.busy && socialState.overview.friendsReadOnly==false
            CarButton("수락",{onFriendRespond(request.person.id,true)},Modifier.weight(1f),primary=true,enabled=canRespond)
            CarButton("거절",{onFriendRespond(request.person.id,false)},Modifier.weight(1f),enabled=canRespond)
        })
    }
    if(popup!=null && state.setupAllowed) {
        val close={popup=null;reportSubmitted=false}
        when(val current=popup) {
            "menu" -> CarPopup("더보기",close,body={
                if(accountFeatures)CarAction("내 경로",CarSymbol.Person,{close();navigator.replace(AppDestination.ACCOUNT);if(state.accountCourses.status!=AccountCourseStatus.READY)onAccountCourses()},Modifier.fillMaxWidth(),enabled=!state.active)
                if(accountFeatures)CarAction("내 음악",CarSymbol.Music,{close();navigator.replace(AppDestination.MUSIC);if(state.accountPlaylists.status!=AccountPlaylistStatus.READY)onAccountPlaylists()},Modifier.fillMaxWidth())
                onAccountProfile?.let {CarAction("프로필",CarSymbol.Person,{close();navigator.replace(AppDestination.PROFILE);it()},Modifier.fillMaxWidth())}
                CarAction("휴대전화에서 계속",CarSymbol.Link,{popup="phone-create"},Modifier.fillMaxWidth())
                if(BuildConfig.DEBUG && accountFeatures)CarAction("방문 기록",CarSymbol.Share,{popup="share"},Modifier.fillMaxWidth(),enabled=state.visitedCount>0&&!state.sharingVisits&&state.visitSharingAllowed)
                if(state.reportOrigin!=null)CarAction("경로 신고",CarSymbol.Alert,{reportReason=null;reportSubmitted=false;popup="report"},Modifier.fillMaxWidth(),enabled=!state.reportBusy)
                CarAction("자세히",CarSymbol.Info,{popup="about"},Modifier.fillMaxWidth())
                CarAction("권한 관리",CarSymbol.Lock,{close();navigator.replace(AppDestination.PRIVACY)},Modifier.fillMaxWidth())
                if(BuildConfig.DEBUG)CarAction("진단",CarSymbol.Info,{popup="diagnostics"},Modifier.fillMaxWidth())
            },actions={CarAction("닫기",CarSymbol.Close,close,Modifier.weight(1f))})
            "phone-create" -> CarPopup("경로 만들기",close,body={CarPhoneHandoff("create")},actions={CarAction("닫기",CarSymbol.Close,close,Modifier.weight(1f))})
            "phone-trip-new" -> CarPopup("새 여행 만들기",close,body={CarPhoneHandoff("trip-new")},actions={CarAction("닫기",CarSymbol.Close,close,Modifier.weight(1f))})
            "phone-together" -> CarPopup("함께 가기",close,body={CarPhoneHandoff("together")},actions={CarAction("닫기",CarSymbol.Close,close,Modifier.weight(1f))})
            "music-link-unavailable" -> CarPopup("음악 링크를 열지 못했어요",close,body={},actions={CarAction("확인",CarSymbol.Check,close,Modifier.weight(1f),primary=true)})
            "report" -> CarPopup("경로 신고",close,body={
                CourseReportReason.values().forEach {reason ->CarChoice(reason.label,reportReason==reason,CarSymbol.Alert,enabled=!state.reportBusy){reportReason=reason}}
            },actions={
                CarAction("신고",CarSymbol.Alert,{reportSubmitted=true;onReport(reportReason!!)},Modifier.weight(1f),primary=true,enabled=reportReason!=null&&!state.reportBusy,busy=state.reportBusy)
                CarAction("취소",CarSymbol.Close,close,Modifier.weight(1f),enabled=!state.reportBusy)
            })
            "report-accepted","report-failed" -> CarPopup(if(current=="report-accepted")"신고를 접수했어요" else "신고를 보내지 못했어요",close,
                body={},actions={CarAction("확인",CarSymbol.Check,close,Modifier.weight(1f),primary=true)})
            "consent" -> CarPopup("위치 사용",close,body={
                PrivacyDisclosure()
            },actions={
                CarAction("동의",CarSymbol.Play,{close();onStart()},Modifier.weight(1f),primary=true,accessibility="동의하고 시작")
                CarAction("취소",CarSymbol.Close,close,Modifier.weight(1f))
            })
            "privacy-info" -> CarPopup("이 기기의 위치 정보",close,body={
                Column(Modifier.heightIn(max=CarTokens.LegacyPopupContentMaxHeight).verticalScroll(rememberScrollState()),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                    PrivacyDisclosure()
                    CarText("사용 일시중지는 기록을 보존합니다",style=CarType.Label,maxLines=2)
                    CarText("동의 철회 시 이 기기의 기록을 삭제합니다",style=CarType.Label,maxLines=2)
                }
            },actions={CarAction("닫기",CarSymbol.Close,close,Modifier.weight(1f))})
            "withdraw" -> CarPopup("동의 철회 및 기록 삭제",close,body={
                CarText("위치 사용을 중지하고 이 기기의 기록을 삭제합니다",style=CarType.Label,maxLines=2)
                CarMetadata(listOf("방문 기록","진행 상태","불러온 경로"))
                CarText("삭제한 기록은 되돌릴 수 없습니다",style=CarType.Label,maxLines=2)
            },actions={
                CarButton("철회 및 삭제",{close();onWithdrawAndDelete()},Modifier.weight(1f),variant=CarButtonStyle.DANGER)
                CarButton("취소",close,Modifier.weight(1f))
            })
            "reset" -> CarPopup("경로 기록을 초기화할까요?",close,description="완료한 장소와 안전운전 점수가 초기화돼요.",actions={
                CarAction("초기화",CarSymbol.Refresh,{onReset();close()},Modifier.weight(1f),primary=true)
                CarAction("취소",CarSymbol.Close,close,Modifier.weight(1f))
            })
            "share" -> CarPopup("방문 ${state.visitedCount}곳 공유",close,body={
                CarText("개발용 창작 공간으로 보냅니다",maxLines=2)
                CarMetadata(listOf("장소","주소","경로 위치","방문 시각"))
                CarText("실시간 위치와 이동 경로는 제외",style=CarType.Label,secondary=true,maxLines=2)
            },actions={
                CarAction("공유",CarSymbol.Share,{close();onShareVisits()},Modifier.weight(1f),primary=true)
                CarAction("취소",CarSymbol.Close,close,Modifier.weight(1f))
            })
            "about" -> CarPopup(state.selected?.title ?: "WegoH",close,body={
                CarText(state.selected?.description.orEmpty(),maxLines=3)
                CarText(state.selected?.author.orEmpty(),style=CarType.Label,secondary=true)
            },actions={CarAction("닫기",CarSymbol.Close,close,Modifier.weight(1f))})
            "error" -> CarPopup("문제 확인",close,body={CarErrorNotice(state.error.orEmpty())},actions={CarAction("닫기",CarSymbol.Close,close,Modifier.weight(1f))})
            "diagnostics" -> if(BuildConfig.DEBUG)CarPopup("진단",close,body={
                Column(Modifier.heightIn(max=CarTokens.LegacyPopupContentMaxHeight).verticalScroll(rememberScrollState())) {
                    listOf(state.policy,state.location,state.navigation,state.message).plus(state.history.take(4)).forEach {CarText(it,style=CarType.Caption,maxLines=3)}
                }
            },actions={CarAction("닫기",CarSymbol.Close,close,Modifier.weight(1f))})
            else -> if(current?.startsWith("stop:")==true) {
                val stop=state.selected?.stops?.getOrNull(current.substringAfter(':').toInt())
                CarPopup(stop?.name.orEmpty(),close,body={CarText(stop?.message.orEmpty(),maxLines=3)},actions={CarAction("닫기",CarSymbol.Close,close,Modifier.weight(1f))})
            }
        }
    }
    TripSignalsHost(tripsState,tripActions,state.setupAllowed)
    }
}

/** Mandatory four-part notice is local app behavior; public legal URLs remain a release gate. */
@Composable private fun PrivacyDisclosure() {
    CarText("항목: 위치, 방문 장소와 시각, 진행 상태",style=CarType.Label,maxLines=2)
    CarText("목적: 장소 도착 확인과 여정 이어가기",style=CarType.Label,maxLines=2)
    CarText("보유: 동의 철회와 기록 삭제 전까지",style=CarType.Label,maxLines=2)
    CarText("거부할 수 있으며 위치 기반 실행은 제한됩니다",style=CarType.Label,maxLines=2)
    CarText("실행 중 다른 앱에서도 위치를 사용합니다",style=CarType.Label,maxLines=2)
    CarText("방문 기록은 기기에 암호화하며 공유 전에는 전송하지 않습니다",style=CarType.Label,maxLines=2)
    CarText("진행 중인 여행에서는 지도에 내 차 위치를 보여 주고, 위치 공유가 켜진 여행의 일행에게 이 차의 위치를 보내요.",style=CarType.Label,maxLines=Int.MAX_VALUE)
    CarText("여행에 참가하면 여행 전체 안전운전 점수만 같은 여행의 일행에게 보여요. 원시 속도·위치·표본은 보내지 않아요.",style=CarType.Label,maxLines=Int.MAX_VALUE)
}
