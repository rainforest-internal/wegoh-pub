package io.wegoh.app

import android.Manifest
import android.app.Application
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.media.MediaPlayer
import android.os.Handler
import android.os.Looper
import io.wegoh.app.nativeauth.NativeNetLog
import android.util.Log
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue

data class WegoState(
    val accountCourses: AccountCourseState = AccountCourseState(),
    val accountPlaylists: AccountPlaylistState = AccountPlaylistState(),
    val accountProfile: AccountProfileState = AccountProfileState(),
    val accountDiscovery: AccountDiscoveryState = AccountDiscoveryState(),
    val packs: List<DrivePack> = emptyList(), val selectedKey: String? = null,
    val active: Boolean = false, val setupAllowed: Boolean = false, val carUxKnown: Boolean = false,
    val policy: String = "차량 연결 대기", val location: String = "아직 위치를 받지 않았어요",
    val navigation: String = "안내 시작 전", val completed: Set<String> = emptySet(),
    val message: String = "경로를 선택해 주세요",
    val error: String? = null, val history: List<String> = emptyList(),
    val published: List<PublishedPack> = emptyList(), val catalogueBusy: Boolean = false,
    val downloading: String? = null,
    val reportOrigin: VerifiedPackOrigin? = null,val reportBusy: Boolean=false,val reportOutcome: CourseReportOutcome?=null,
    val navigationBusy: Boolean = false,val navigationPhase: NavigationPhase=NavigationPhase.IDLE,
    val navigationObservation: NavigationObservation?=null,
    val navigationOverview: NavigationOverview? = null,
    val visitedCount: Int = 0, val sharingVisits: Boolean = false,val visitSharingAllowed: Boolean=true,
    val storageReady: Boolean = false, val locationConsented: Boolean = false,
    val courseResult: CourseDrivingResult?=null,
) {
    val selected get() = packs.find { it.key == selectedKey }
    /** Arrival alerts end with the last stop; a fully visited route needs a record reset before another run. */
    val allVisited get() = selected?.stops?.let { stops -> stops.isNotEmpty() && stops.all { it.id in completed } } == true
}

class WegoApplication : Application() {
    internal val receiverSettings by lazy {VehicleReceiverSettings.forVehicle(this)}
    internal val journeyExecution get()=controller.journeys
    val controller by lazy { VehicleAppDependencies.controller(this).also {it.connectAccount(vehicleConnection)} }
    val vehicleConnection by lazy { VehicleAppDependencies.connection(this) }
    override fun onCreate() {
        super.onCreate()
        NativeNetLog.clientVersion=NativeNetLog.clientValue(BuildConfig.VERSION_NAME,BuildConfig.VERSION_CODE.toLong())
        val handler=Handler(Looper.getMainLooper())
        var started=0
        val background=Runnable {if(started==0)controller.setAppForeground(false)}
        registerActivityLifecycleCallbacks(object: ActivityLifecycleCallbacks {
            override fun onActivityStarted(activity: android.app.Activity) {
                if(BuildConfig.DEBUG && activity.javaClass.name=="io.wegoh.app.TripScreensPreviewActivity")return
                started++;handler.removeCallbacks(background);if(started==1)controller.setAppForeground(true)
            }
            override fun onActivityStopped(activity: android.app.Activity) {
                if(BuildConfig.DEBUG && activity.javaClass.name=="io.wegoh.app.TripScreensPreviewActivity")return
                started--;if(started==0)handler.post(background)
            }
            override fun onActivityCreated(activity: android.app.Activity,state: android.os.Bundle?) {}
            override fun onActivityResumed(activity: android.app.Activity) {}
            override fun onActivityPaused(activity: android.app.Activity) {}
            override fun onActivitySaveInstanceState(activity: android.app.Activity,state: android.os.Bundle) {}
            override fun onActivityDestroyed(activity: android.app.Activity) {}
        })
    }
}

class WegoController(private val context: Context,private val platformContext: Context=context.applicationContext): AutoCloseable {
    internal val firstRunGuide=FirstRunGuide(context)
    val repository = PackRepository(context)
    private val progress = ProgressStore(context)
    private val visits = VisitedPlaces(context)
    private val settings = PrivateSettings(context)
    private val main = Handler(Looper.getMainLooper())
    private var journeyState by mutableStateOf(WegoState(),androidx.compose.runtime.referentialEqualityPolicy())
    var state: WegoState
        get()=journeyState.copy(accountCourses=account?.state ?: AccountCourseState(),
            accountPlaylists=playlists?.state ?: AccountPlaylistState(),accountProfile=profile?.state?.toUiState() ?: AccountProfileState(),
            accountDiscovery=discovery?.state ?: AccountDiscoveryState())
        private set(value) {journeyState=value.copy(accountCourses=AccountCourseState(),accountPlaylists=AccountPlaylistState(),
            accountProfile=AccountProfileState(),accountDiscovery=AccountDiscoveryState())}
    private var repositorySnapshot: List<DrivePack> = emptyList()
    private var selection: CourseSelection? = null
    private var preferLocalSelection=false
    private var sessionOwner: CourseOwner?=null
    private var navigationOwner: CourseOwner?=null
    private var historyOwner: CourseOwner?=null
    internal val localEntryState get()=localCourseEntryState(state,repositorySnapshot,selection,sessionOwner,navigationOwner,historyOwner)
    @Volatile private var privacyEpoch = 0
    private var visible = false
    private var foreground = false
    private var visibilityOwner: Any?=null
    private var account: CoursesRepository?=null
    private var accountEvents: AccountEvents?=null
    private var playlists: PlaylistsRepository?=null
    private var profile: ProfileRepository?=null
    private var discovery: DiscoveryRepository?=null
    private var social: SocialRepository?=null
    private var trips: TripsRepository?=null
    private var tripGear: TripGearObserver?=null
    private val tripNavigation=TripNavigationSession(platformContext,
        {foreground && state.setupAllowed && state.storageReady && !state.active},
        ::tripLocationBlock,
        {trips?.navigationUpdate(it)},{trips?.navigationFailed()})
    private val tripSignalNavigation=TripSignalNavigation(platformContext) {foreground && settings.consented() && hasPermissions()}
    internal val tripsRepository get()=checkNotNull(trips)
    internal val socialRepository get()=checkNotNull(social)
    @Volatile private var accountConnection: io.wegoh.app.nativeauth.VehicleConnection?=null
    internal val vehicleAccountConnection get()=accountConnection
    private lateinit var remoteHistory: VehicleRemoteHistory
    private var remoteHistoryObservation: java.io.Closeable?=null
    internal fun remoteHistoryFor(connection: io.wegoh.app.nativeauth.VehicleConnection): VehicleRemoteHistory {
        check(connection===accountConnection)
        return remoteHistory
    }
    internal val profileRepository get()=checkNotNull(profile)
    internal val coursesRepository get()=checkNotNull(account)
    internal val playlistsRepository get()=checkNotNull(playlists)
    internal val discoveryRepository get()=checkNotNull(discovery)
    private var previousAccountSelection: DrivePack?=null
    private val execution get()=journeys.execution
    internal val navigationCoordinator=NavigationCoordinator(platformContext,{state},{state=it},{foreground},::fail,::log)
    internal val journeys=JourneyExecutionManager(context,platformContext,{state},{state=it},::prepareJourney,
        {foreground},{visible},::hasPermissions,::fail,::note,::log,
        {sessionOwner=null;navigationOwner=null;navigationCoordinator.cancel()},{requestNavigation()})
    private val localPublishing=LocalPublishingCoordinator(repository,visits,{state},{state=it},{privacyEpoch},::personal,
        {refresh(it)},::note,::fail,::log)
    private val policy = DrivingPolicy(platformContext) { allowed, known, status ->
        main.post {
            state = state.copy(setupAllowed = allowed, carUxKnown = known, policy = status)
            account?.setSetupAllowed(allowed);playlists?.setSetupAllowed(allowed);profile?.setSetupAllowed(allowed);discovery?.setSetupAllowed(allowed);social?.setSetupAllowed(allowed)
            trips?.setCarUxKnown(known);trips?.setSetupAllowed(allowed)
            accountConnection?.setSetupAllowed(allowed)
        }
    }
    init { refresh() }
    internal fun connectAccount(connection: io.wegoh.app.nativeauth.VehicleConnection) {
        check(account==null)
        accountConnection=connection
        val history=VehicleRemoteHistory(android.os.SystemClock::elapsedRealtime) {
            connection.currentDataBoundary().takeIf {connection===accountConnection}
        }
        remoteHistory=history
        remoteHistoryObservation=connection.observeDataBoundary {history.refreshBoundary()}
        val events=AccountEvents(connection);accountEvents=events
        trips=TripsRepository(connection,events,tripNavigation::start,tripNavigation::close,tripSignalNavigation::locate,
            scores=vehicleCourseScores(context,changed={key,result->trips?.scoreChanged(key,result)}),
            canShareLocation={settings.consented() && hasPermissions()},canScore={!state.active && hasCoursePermissions()},observeRoute=tripNavigation::monitor,observeLocation={update,unavailable->
                TripLocationObservation(platformContext,{tripLocationBlock()==null},update,unavailable)
            }).also {it.setCarUxKnown(state.carUxKnown);it.setSetupAllowed(state.setupAllowed);it.setForeground(appForeground)}
        tripGear=TripGearObserver(platformContext) {trips?.setGear(it)}
        social=SocialRepository(connection).also {it.setSetupAllowed(state.setupAllowed);it.setForeground(appForeground)}
        playlists=PlaylistsRepository(connection,events).also {it.setSetupAllowed(state.setupAllowed);it.setForeground(appForeground)}
        profile=ProfileRepository(connection,events).also {it.setSetupAllowed(state.setupAllowed);it.setForeground(appForeground)}
        discovery=DiscoveryRepository(connection,events,repository).also {it.setSetupAllowed(state.setupAllowed);it.setForeground(appForeground)}
        account=CoursesRepository(connection,repository,feed=events,changed=changed@ { next ->
            if(state.active && execution!=null && next.status in setOf(AccountCourseStatus.PERMISSION_REQUIRED,AccountCourseStatus.UNAVAILABLE))
                interrupt("계정 경로를 닫았습니다")
            val running=execution?.takeIf {state.active && it.isCurrent()}
            if(next.status==AccountCourseStatus.READY && next.selected==null && running!=null &&
                account?.restoreExecution(running.pack,running.published.checksum)==true)return@changed
            val old=previousAccountSelection
            val selectedAccount=state.selected?.source==CoursesRepository.SOURCE
            if(selectedAccount && old!=next.selected) {
                if(running==null)interrupt("계정 경로를 닫았습니다")
                state=state.copy(selectedKey=null,completed=emptySet(),history=emptyList(),message="경로를 선택해 주세요",
                    location="아직 위치를 받지 않았어요",navigation="안내 시작 전")
            }
            previousAccountSelection=next.selected
            val selectCurrent=next.selected!=null && (next.selected!==old || running?.pack===next.selected)
            if(selectCurrent)preferLocalSelection=false
            refresh(if(selectCurrent)checkNotNull(next.selected).key else state.selectedKey)
        }).also {it.setSetupAllowed(state.setupAllowed);it.setForeground(appForeground)}
        connection.setSetupAllowed(state.setupAllowed);connection.setForeground(appForeground)
    }
    fun downloadAccountPublic(pack: PublishedPack) {
        val epoch=privacyEpoch
        discovery?.download(pack,canStore={epoch==privacyEpoch && foreground && state.setupAllowed && state.storageReady && !state.active}) {saved ->
            refresh(saved.key)
            note("경로를 저장했어요")
        }
    }
    fun playlistLink(id: String,revision: Long,track: String): String? =
        if(visible && foreground && state.setupAllowed)playlists?.link(id,revision,track) else null
    fun selectAccountCourse(course: AccountCourse) {
        if(state.active || !state.storageReady || !state.setupAllowed || state.downloading!=null || !course.available || course !in state.accountCourses.courses || account?.canUse()!=true)return
        preferLocalSelection=false
        if(state.accountCourses.selected?.key==course.published.key)select(course.published.key)
        else account?.select(course)
    }
    private fun personal(pack: DrivePack)=state.accountCourses.selected===pack ||
        selection.let {it is CourseSelection.Account && it.pack===pack}
    private fun owner(pack: DrivePack): CourseOwner? {
        if(personal(pack)) {
            if(account?.canUse()!=true)return null
            val boundary=accountConnection?.accountDataBoundary() ?: return null
            val key=account?.storageKey() ?: return null
            return CourseOwner.Account(key,boundary.revision)
        }
        return repositorySnapshot.firstOrNull {it===pack}?.let {CourseOwner.Local(it.key)}
    }
    fun refreshLocal(key: String) {preferLocalSelection=true;refresh(key)}
    fun selectLocal(key: String) {
        if(state.active || !state.setupAllowed || !state.storageReady || repositorySnapshot.none {it.key==key})return
        preferLocalSelection=true;invalidateNavigation();refresh(key)
        if(state.storageReady)state=state.copy(error=null)
    }
    private fun accountKey()=checkNotNull(account?.storageKey()) {"계정 연결을 확인하세요"}
    private fun courseProgress(pack: DrivePack)=if(personal(pack))ProgressStore(context,accountKey()) else progress
    private fun courseVisits(pack: DrivePack?)=if(pack?.let(::personal)==true)VisitedPlaces(context,accountKey()) else visits

    fun refresh(select: String? = state.selectedKey) {
        runCatching {
            repositorySnapshot=repository.list()
            val running=execution?.takeIf {state.active && it.isCurrent()}
            val accountSelection=listOfNotNull(state.accountCourses.selected.takeIf {account?.canDisplaySelection()==true})
            val packs=(if(preferLocalSelection)repositorySnapshot+accountSelection else accountSelection+repositorySnapshot).distinctBy {it.key}
            val hidden=running!=null && accountSelection.isEmpty()
            val key = if(hidden)null else (select ?: settings.selected())?.takeIf { k -> packs.any { it.key == k } } ?: packs.firstOrNull()?.key
            val selected = packs.find { it.key == key }
            selection=courseSelection(selected,repositorySnapshot,state.accountCourses.selected)
            if(key!=state.selectedKey && running==null)invalidateNavigation()
            state = state.copy(packs = packs, selectedKey = key,storageReady=true,locationConsented=settings.consented(),
                courseResult=if(hidden)null else selected?.let {pack->owner(pack)?.let {journeys.score(it,pack)}},
                visitedCount = if(hidden)0 else courseVisits(selected).list().length(),visitSharingAllowed=!hidden && selected?.let(::personal)!=true,reportOrigin=if(BuildConfig.DEBUG)selected?.takeUnless(::personal)?.let {repository.verifiedOrigin(it)} else null,
                completed = if(hidden)emptySet() else if(running?.pack?.key==key)journeys.completed else if (state.active) state.completed else selected?.let { courseProgress(it).read(it) }.orEmpty())
            if(!hidden && selected?.let(::personal)!=true)settings.select(key)
        }.onFailure { state=state.copy(storageReady=false);fail("저장된 기록을 읽지 못했어요") }
        trips?.refreshLocationPermissions()
    }
    private fun invalidateNavigation() {
        navigationOwner=null;navigationCoordinator.cancel(resetLabel=true)
    }
    fun select(key: String) {
        if (!state.setupAllowed || !state.storageReady || state.active || state.reportBusy || state.accountCourses.downloading!=null) return
        if(state.packs.find {it.key==key}?.let(::owner)==null)return
        invalidateNavigation()
        refresh(key)
        if(!state.storageReady)return
        state = state.copy(error = null, navigation = "안내 시작 전", navigationOverview=null,message = "경로 선택 완료")
    }
    fun loadPublished()=localPublishing.loadPublished()
    fun downloadPublished(pack: PublishedPack)=localPublishing.downloadPublished(pack)
    fun shareVisitedPlaces()=localPublishing.shareVisitedPlaces()
    fun reportSelectedCourse(reason: CourseReportReason)=localPublishing.reportSelectedCourse(reason)
    fun fail(message: String) { state = state.copy(error = message); log("ERROR") }
    fun note(message: String) {
        state = state.copy(message = message, error = null)
        log("NOTICE")
    }
    fun refreshTripLocation() {trips?.refreshLocationPermissions()}
    private fun tripLocationBlock()=tripLocationBlock(appForeground,settings.consented(),hasPermissions())
    fun hasPermissions() = PERMISSIONS.all { context.checkSelfPermission(it) == PackageManager.PERMISSION_GRANTED }
    fun hasCoursePermissions() = COURSE_PERMISSIONS.all {context.checkSelfPermission(it)==PackageManager.PERMISSION_GRANTED}
    private fun prepareJourney(key: String): JourneyStartPlan {
        check(context.getSystemService(android.os.PowerManager::class.java).isInteractive) {"화면이 켜진 상태에서 시작하세요"}
        check(state.storageReady && settings.consented()) {"위치 사용 동의와 기록 확인이 필요합니다"}
        check(state.setupAllowed) { "차량 제한 상태에서는 새 경로를 시작할 수 없습니다" }
        check(hasPermissions()) { "위치 사용 권한이 필요합니다" }
        check(!state.active) { "이미 실행 중인 경로가 있습니다" }
        check(state.accountCourses.downloading==null) {"경로를 불러오는 중입니다"}
        val pack = state.packs.firstOrNull { it.key == key } ?: error("경로를 찾을 수 없습니다")
        val owned=owner(pack) ?: error("계정 연결을 확인하세요")
        val namespace=(owned as? CourseOwner.Account)?.storageKey
        selection=courseSelection(pack,repositorySnapshot,state.accountCourses.selected)
        sessionOwner=owned
        val sessionProgress=if(namespace!=null)ProgressStore(context,namespace) else progress
        val sessionVisits=if(namespace!=null)VisitedPlaces(context,namespace) else visits
        return JourneyStartPlan(pack,owned,sessionProgress,sessionVisits,accountConnection,
            if(namespace!=null)state.accountCourses.courses.first {it.published.key==pack.key}.published else null)
    }
    fun begin(key: String,onReady: ()->Unit = {}) {trips?.pauseScoring();journeys.begin(key,onReady=onReady)}
    fun requestNavigation() = requestNavigation(wholeCourse=false)
    fun requestNavigation(wholeCourse: Boolean) {
        if(!state.storageReady)return
        if (!state.setupAllowed) { fail("정차 후 경로를 변경해 주세요"); return }
        if (state.navigationBusy) return
        val selected = state.selected ?: return
        val owned=owner(selected) ?: run {fail("차량 연결을 확인해 주세요");return}
        val namespace=(owned as? CourseOwner.Account)?.storageKey
        navigationOwner=owned
        val pack = if(wholeCourse)selected else remainingNavigationPack(selected,state.completed) ?: return
        val activeRun=execution?.takeIf {it.pack.key==selected.key && it.isCurrent()}
        navigationCoordinator.request(pack,ownerCurrent={owned is CourseOwner.Local ||
            (owned as CourseOwner.Account).epoch==accountConnection?.dataEpoch() &&
                (activeRun?.isCurrent()==true || namespace==account?.storageKey())},running={activeRun?.isCurrent()==true})
    }

    fun reset() {
        if (state.active || !state.setupAllowed || !state.storageReady) return
        state.selected?.let {
            if(owner(it)==null)return
            if (courseProgress(it).reset(it)) {
                runCatching {journeys.resetScore(checkNotNull(owner(it)),it)}.onSuccess {
                    state = state.copy(completed = emptySet(),courseResult=null); note("경로 기록을 초기화했어요")
                }.onFailure {state=state.copy(storageReady=false);fail("점수 기록을 초기화하지 못했어요")}
            }
            else fail("방문 기록을 초기화하지 못했어요")
        }
    }
    fun consentLocation(): Boolean = runCatching {
        check(state.setupAllowed && state.storageReady && !state.active)
        settings.consent();state=state.copy(locationConsented=true);trips?.refreshLocationPermissions();true
    }.getOrElse {fail("동의를 저장하지 못했어요");false}
    private var appForeground=false
    private val climateWindows=mutableSetOf<Any>()
    private val climateForegroundObservers=mutableSetOf<(Boolean)->Unit>()
    private var climateForeground=false
    internal fun observeClimateForeground(observer: (Boolean)->Unit): java.io.Closeable {
        climateForegroundObservers.add(observer);observer(climateForeground)
        return java.io.Closeable {climateForegroundObservers.remove(observer)}
    }
    private fun updateClimateForeground() {
        val value=appForeground && climateWindows.isNotEmpty()
        if(climateForeground==value)return
        climateForeground=value
        climateForegroundObservers.toList().forEach {it(value)}
    }
    fun setAppForeground(value: Boolean) {
        appForeground=value
        tripNavigation.setForeground(value)
        if(!value)tripSignalNavigation.close()
        if(!value)climateWindows.clear()
        updateClimateForeground()
        account?.setForeground(value);playlists?.setForeground(value)
        profile?.setForeground(value);discovery?.setForeground(value);social?.setForeground(value);trips?.setForeground(value)
        accountConnection?.setForeground(value)
    }
    fun setVisible(value: Boolean,owner: Any=context,focused: Boolean=value) {
        if(value && focused)climateWindows.add(owner) else climateWindows.remove(owner)
        updateClimateForeground()
        if(!value && visibilityOwner!==owner)return
        visibilityOwner=if(value)owner else null
        foreground=value;visible=value && focused;if(!visible)journeys.silence()

    }
    fun suspendLocationConsent() {
        if(!state.setupAllowed || !state.storageReady)return
        runCatching {settings.revoke();tripNavigation.close();trips?.pauseScoring();interrupt("위치 사용을 중지했어요");state=state.copy(locationConsented=false);trips?.refreshLocationPermissions()}
            .onFailure {fail("변경을 저장하지 못했어요")}
    }
    fun withdrawLocationAndDeleteRecords() {
        if(!state.setupAllowed || !state.storageReady)return
        privacyEpoch++;localPublishing.cancelPendingRequests()
        tripNavigation.close()
        interrupt("위치 사용을 중지했어요")
        state=state.copy(locationConsented=false,sharingVisits=false,downloading=null,reportBusy=false,reportOutcome=null)
        runCatching {
            journeys.forgetScores();trips?.forgetScores()
            LocalPrivacy.withdrawAndDelete(context)
            state=state.copy(selectedKey=null,completed=emptySet(),visitedCount=0,history=emptyList(),location="위치 사용 중지됨")
            refresh()
        }.onFailure {state=state.copy(storageReady=false);fail("기록 삭제를 완료하지 못했어요")}
    }
    fun interrupt(message: String)=journeys.interrupt(message)
    fun stop()=journeys.stop()
    override fun close() {
        accountConnection=null
        remoteHistoryObservation?.close()
        if(::remoteHistory.isInitialized)remoteHistory.refreshBoundary()
        climateWindows.clear();updateClimateForeground();climateForegroundObservers.clear()
        stop();account?.close();account=null;playlists?.close();playlists=null;profile?.close();profile=null;discovery?.close();discovery=null
        tripSignalNavigation.close();trips?.close();trips=null;tripGear?.close();tripGear=null;tripNavigation.close();social?.close();social=null;accountEvents?.close();accountEvents=null;policy.close();localPublishing.close()
    }
    private fun log(message: String) {
        if(BuildConfig.DEBUG) {
            Log.i("WegoH", message)
            val currentOwner=state.selected?.let(::owner)
            val previous=state.history.takeIf {historyOwner==currentOwner}.orEmpty()
            historyOwner=currentOwner
            state = state.copy(history = (listOf(message) + previous).take(12))
        }
    }
    companion object {
        val PERMISSIONS = arrayOf(Manifest.permission.ACCESS_COARSE_LOCATION, Manifest.permission.ACCESS_FINE_LOCATION,
            "pleos.car.permission.FUSED_LOCATION")
        val COURSE_PERMISSIONS = PERMISSIONS+"android.car.permission.CAR_SPEED"
    }
}

internal class ArrivalCue(context: Context) {
    private val context = context.applicationContext
    private val audio = context.getSystemService(AudioManager::class.java)
    private var player: MediaPlayer? = null
    private var focus: AudioFocusRequest? = null
    private var epoch=0
    internal val active get()=player?.isPlaying==true
    internal val ownsFocus get()=focus!=null
    fun play(report: (String) -> Unit) {
        stop()
        val token=++epoch
        // A non-verbal place notification, never a second navigation/TBT stream.
        val attributes = AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_NOTIFICATION)
            .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build()
        val request = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)
            .setAudioAttributes(attributes).setOnAudioFocusChangeListener({ change ->
                if(token==epoch)when(change) {
                    AudioManager.AUDIOFOCUS_LOSS,AudioManager.AUDIOFOCUS_LOSS_TRANSIENT->{stop();report("AUDIO_FOCUS_RELEASED")}
                    AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK->{player?.setVolume(.2f,.2f);report("AUDIO_DUCKED")}
                    AudioManager.AUDIOFOCUS_GAIN->{player?.setVolume(1f,1f);report("AUDIO_UNDUCKED")}
                }
            },Handler(Looper.getMainLooper())).build()
        focus = request
        if (audio.requestAudioFocus(request) != AudioManager.AUDIOFOCUS_REQUEST_GRANTED) {
            stop(); report("AUDIO_SKIPPED 다른 오디오가 우선입니다"); return
        }
        runCatching {
            player = MediaPlayer().apply {
                setAudioAttributes(attributes)
                context.resources.openRawResourceFd(R.raw.arrival).use { fd ->
                    setDataSource(fd.fileDescriptor, fd.startOffset, fd.length)
                }
                setOnCompletionListener { if(token==epoch){this@ArrivalCue.stop();report("AUDIO_COMPLETED")} }
                setOnErrorListener { _, what, extra -> if(token==epoch){this@ArrivalCue.stop();report("AUDIO_ERROR $what/$extra")};true }
                prepare(); start()
            }
            report("AUDIO_STARTED")
        }.onFailure { stop(); report("AUDIO_ERROR") }
    }
    fun stop() {
        epoch++
        player?.release(); player = null
        focus?.let { audio.abandonAudioFocusRequest(it) }; focus = null
    }
}
