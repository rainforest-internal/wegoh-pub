package io.wegoh.app

import io.wegoh.app.nativeauth.WegoLog
import android.content.Intent
import android.os.Bundle
import androidx.activity.viewModels
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import io.wegoh.app.ui.WegoCarTheme
import io.wegoh.app.ui.WegoVehicleScreen
import io.wegoh.app.ui.PlatformScreen
import io.wegoh.app.ui.AppUpdatePrompt
import io.wegoh.app.ui.AppUpdateMarketError
import io.wegoh.app.ui.CarWindowVisibility
import io.wegoh.app.ui.ProvideCarWindowVisibility
import io.wegoh.app.ui.ProvideCourseRoadMaps
import io.wegoh.app.ui.ProvideCarErrorReports

class MainActivity : ComponentActivity() {
    val controller get() = (application as WegoApplication).controller
    private val profileModel: ProfileViewModel by viewModels {ProfileViewModel.Factory(controller.profileRepository)}
    private val coursesModel: CoursesViewModel by viewModels {FeatureViewModelFactory(CoursesViewModel::class.java) {CoursesViewModel(controller.coursesRepository,controller::selectAccountCourse)}}
    private val playlistsModel: PlaylistsViewModel by viewModels {FeatureViewModelFactory(PlaylistsViewModel::class.java) {PlaylistsViewModel(controller.playlistsRepository,controller::playlistLink)}}
    private val discoveryModel: DiscoveryViewModel by viewModels {FeatureViewModelFactory(DiscoveryViewModel::class.java) {DiscoveryViewModel(controller.discoveryRepository,controller::downloadAccountPublic)}}
    private val tripsModel: TripsViewModel by viewModels {FeatureViewModelFactory(TripsViewModel::class.java) {TripsViewModel(controller.tripsRepository)}}
    private val socialModel: SocialViewModel by viewModels {FeatureViewModelFactory(SocialViewModel::class.java) {SocialViewModel(controller.socialRepository)}}
    private val connection get()=controller.vehicleAccountConnection ?: (application as WegoApplication).vehicleConnection
    private var updateResult by mutableStateOf<AppUpdateResult>(AppUpdateResult.Unknown)
    private var receiverObserver: java.io.Closeable?=null
    private var updateResumed by mutableStateOf(false)
    private var updateDismissed by mutableStateOf(false)
    private var marketError by mutableStateOf(false)
    private lateinit var windows: CarWindowVisibility
    private val updateWorker=java.util.concurrent.Executors.newSingleThreadExecutor()
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        VehicleAppDependencies.configure(this, intent)
        windows=CarWindowVisibility(this) {controller.setVisible(it.visible,this,it.focused)}
        if(VehicleAppDependencies.checkForUpdates())updateWorker.execute {
            val result=runCatching {AppUpdate().check(BuildConfig.VERSION_CODE.toLong(),AppUpdate.installedCertificates(this))}
                .getOrDefault(AppUpdateResult.Unknown)
            runOnUiThread {if(!isDestroyed)updateResult=result}
        }
        receiverObserver=connection.observe {if(updateResumed)(application as WegoApplication).receiverSettings.connectionChanged()}
        setContent {
            val tripsState by tripsModel.uiState.collectAsStateWithLifecycle()
            val socialState by socialModel.uiState.collectAsStateWithLifecycle()
            val profileState by profileModel.uiState.collectAsStateWithLifecycle()
            val coursesState by coursesModel.uiState.collectAsStateWithLifecycle()
            val playlistsState by playlistsModel.uiState.collectAsStateWithLifecycle()
            val discoveryState by discoveryModel.uiState.collectAsStateWithLifecycle()
            val screenState=controller.state.copy(accountProfile=profileState,accountCourses=coursesState,
                accountPlaylists=playlistsState,accountDiscovery=discoveryState)
            val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
                if (controller.hasPermissions()) startSession()
                else controller.fail("위치 권한이 필요해요")
            }
            var localCourses by rememberSaveable {mutableStateOf(false)}
            val tripMusicSessions=rememberTripMusicSessions(connection)
            val tripMusicBar=remember(tripMusicSessions) {
                @Composable {trip: io.wegoh.app.nativeauth.TripDetail,onOpen: (()->Unit)?,modifier: androidx.compose.ui.Modifier->
                    TripMusicBarHost(tripMusicSessions,trip,onOpen,modifier)}
            }
            ProvideCarWindowVisibility(windows) {ProvideCourseRoadMaps(connection) {ProvideCarErrorReports(connection) {WegoCarTheme {
            CompositionLocalProvider(io.wegoh.app.ui.LocalTripMusicBar provides tripMusicBar) {
                if(localCourses) {
                    LocalCourseScreen(controller.localEntryState,
                        onSelect=controller::selectLocal,onImport={},
                        onStart={if(controller.consentLocation()) {
                            if(controller.hasCoursePermissions())startSession() else permission.launch(WegoController.COURSE_PERMISSIONS)
                        }},onStop={stopService(Intent(this,SessionService::class.java))},
                        onNavigate={controller.requestNavigation(wholeCourse=true)},onReset=controller::reset,
                        onBack={localCourses=false},onSuspendConsent=controller::suspendLocationConsent,
                        onWithdrawAndDelete=controller::withdrawLocationAndDeleteRecords,
                        onSystemSettings=::openSystemSettings,onLegalDocument=::openLegalDocument)
                } else {

                VehicleConnectionPanel(connection,controller.state.setupAllowed,manageForeground=false,onboarding=true,
                    canRequestPermissions={controller.state.setupAllowed},
                    walkthroughSeen=controller.firstRunGuide.completed,onWalkthroughComplete=controller.firstRunGuide::complete,
                    onLocalCourses={if(controller.state.setupAllowed && !controller.state.active)localCourses=true},connectedContent={
                PlatformScreen(screenState,initialRoute=intent.getStringExtra("screen") ?: "trips",
                    onRootBack={moveTaskToBack(true)},onVehicleConnection={openVehicleConnection()},
                    vehicleConnection={VehicleConnectionPanel(connection,controller.state.setupAllowed,manageForeground=false)},onProfileLoad=profileModel::load,onProfileRefresh=profileModel::refresh) { exit ->
                WegoVehicleScreen(screenState, onSelect = controller::select,
                    onFriendManage=socialModel::manageFriend,
                    tripsState=tripsState,onTripsLoad=tripsModel::load,onTripsRefresh=tripsModel::refresh,
                    onTripSelect=tripsModel::select,onTripClose=tripsModel::closeDetail,onTripRespond=tripsModel::respond,
                    tripActions=io.wegoh.app.ui.rememberTripNavigationActions(controller,tripsState,tripsModel.actions),
                    socialState=socialState,onSocialLoad=socialModel::load,onSocialRefresh=socialModel::refresh,
                    onRoomSelect=socialModel::selectRoom,onRoomClose=socialModel::closeRoom,onSocialSignal=socialModel::signal,onFriendRespond=socialModel::respond,
                    onClimate={if(controller.state.setupAllowed)startActivity(Intent(this,VehicleClimateActivity::class.java))},
                    tripVoice={trip,allowed,modifier->TripInlineVoiceHost(connection,trip,allowed,modifier)},
                    tripMusic={trip,allowed,back->TripMusicHost(tripMusicSessions,connection,trip,allowed,back,::openVehicleConnection) {url->
                        openTripMusicLink(controller.state.setupAllowed,{WegoLog.w("WegoH",it)}) {
                            startActivity(Intent(Intent.ACTION_VIEW,android.net.Uri.parse(url)))
                        }
                    }},
                    tripExtras={section->when(section) {
                        io.wegoh.app.ui.TripSection.VOICE->io.wegoh.app.ui.CarEmptyState("워키토키",detail="여행 화면에서 마이크를 눌러 주세요",symbol=io.wegoh.app.ui.CarSymbol.Microphone)
                        else->Unit
                    }},
                    carExtras={_,back->io.wegoh.app.nativebusiness.NativeBusinessPanel(connection,controller.state.setupAllowed,back,{},
                        initialSection="COMMANDS",embedded=true,inlineCommands=true)},
                    onImport = {},
                    onStart = { if(controller.consentLocation()) {
                        if (controller.hasCoursePermissions()) startSession()
                        else permission.launch(WegoController.COURSE_PERMISSIONS)
                    } },
                    onStop = { stopService(Intent(this, SessionService::class.java)) },
                    onNavigate = {controller.requestNavigation(wholeCourse=true)}, onReset = controller::reset,
                    onBrowse = controller::loadPublished, onDownload = controller::downloadPublished,
                    onAccountCourses=coursesModel::load,onAccountRefresh={page ->when {page=="profile"->profileModel.refresh();page=="account"->coursesModel.refresh();page.startsWith("music")->playlistsModel.refresh();page=="discover"->discoveryModel.refresh();page in setOf("home","courses")-> {coursesModel.refresh();discoveryModel.refresh();controller.refresh()};page=="privacy"->controller.refresh()}},onAccountSelect=coursesModel::select,
                    onAccountProfile=profileModel::load,
                    onAccountDiscovery=discoveryModel::load,onPublicDownload=discoveryModel::download,
                    onAccountPlaylists=playlistsModel::load,onPlaylistSelect=playlistsModel::select,
                    onPlaylistLink={id,revision,track ->
                        val url=if(window.decorView.hasWindowFocus())playlistsModel.link(id,revision,track) else null
                        url!=null && runCatching {startActivity(Intent(Intent.ACTION_VIEW,android.net.Uri.parse(url)).addCategory(Intent.CATEGORY_BROWSABLE));true}.getOrDefault(false)
                    },
                    onShareVisits = controller::shareVisitedPlaces,
                    onRootBack = exit,onSuspendConsent=controller::suspendLocationConsent,onWithdrawAndDelete=controller::withdrawLocationAndDeleteRecords,onReport=controller::reportSelectedCourse,onPlatform=exit,
                    onVehicleConnection={openVehicleConnection()},
                    onSystemSettings=::openSystemSettings,onLegalDocument=::openLegalDocument)
                }
                })
                }
                if(controller.state.setupAllowed && updateResumed) {
                    if(updateResult is AppUpdateResult.Available && !updateDismissed)AppUpdatePrompt(
                        onNo={updateDismissed=true},onYes={
                            if(controller.state.setupAllowed && updateResumed) {
                                updateDismissed=true
                                runCatching {startActivity(AppUpdate.marketIntent())}.onFailure {marketError=true}
                            }
                        })
                    if(marketError)AppUpdateMarketError {marketError=false}
                }
            }
            }}}}
        }
    }
    private fun openSystemSettings() {
        if(controller.state.setupAllowed)runCatching {startActivity(Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
            android.net.Uri.parse("package:$packageName")))}.onFailure {controller.fail("기기 설정을 열지 못했어요")}
    }
    private fun openLegalDocument(url: String) {
        if(controller.state.setupAllowed)runCatching {
            startActivity(Intent(Intent.ACTION_VIEW,android.net.Uri.parse(DistributionPolicy.endpoint(url,false))))
        }.onFailure {controller.fail("문서를 열지 못했어요")}
    }
    private fun openVehicleConnection() {
        if(controller.state.setupAllowed) startActivity(Intent(this,VehicleConnectionActivity::class.java))
    }
    private fun startSession(navigate: Boolean=false) {
        if (!controller.state.setupAllowed) { controller.fail("정차 후 시작해 주세요"); return }
        runCatching {
            startForegroundService(Intent(this, SessionService::class.java).putExtra("pack", controller.state.selectedKey).putExtra("navigate",navigate))
        }.onFailure { controller.fail("경로를 시작하지 못했어요") }
    }
    override fun onResume() {super.onResume();updateResumed=true;controller.refresh();(application as WegoApplication).receiverSettings.refresh()}
    override fun onPause() {updateResumed=false;super.onPause()}
    override fun onDestroy() {receiverObserver?.close();windows.close();updateWorker.shutdownNow();super.onDestroy()}
}
