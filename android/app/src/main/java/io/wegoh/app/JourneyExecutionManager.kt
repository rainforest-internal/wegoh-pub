package io.wegoh.app

import android.content.Context
import android.os.Handler
import android.os.Looper
import io.wegoh.app.nativeauth.VehicleConnection

internal data class JourneyStartPlan(val pack: DrivePack,val owner: CourseOwner,
    val progress: ProgressStore,val visits: VisitedPlaces,val connection: VehicleConnection?,val published: PublishedPack?)

internal class JourneyExecutionManager(private val context: Context,private val platformContext: Context,
    private val read: ()->WegoState,private val update: (WegoState)->Unit,
    private val prepare: (String)->JourneyStartPlan,private val isForeground: ()->Boolean,private val isVisible: ()->Boolean,
    private val hasPermissions: ()->Boolean,private val reportFailure: (String)->Unit,private val note: (String)->Unit,
    private val log: (String)->Unit,private val onStop: ()->Unit,private val navigate: ()->Unit) {
    private val main=Handler(Looper.getMainLooper())
    private val cue=ArrivalCue(platformContext)
    private var engine: PackEngine?=null
    private var generation=0
    private var locationClient: LocationClient?=null
    private val scores=vehicleCourseScores(context)
    private var scoreKey: String?=null
    fun score(owner: CourseOwner,pack: DrivePack)=scores.read(localCourseScoreKey(owner,pack))?.takeIf {it.completed}
    fun resetScore(owner: CourseOwner,pack: DrivePack)=scores.reset(localCourseScoreKey(owner,pack))
    fun forgetScores() {scores.forget();state=state.copy(courseResult=null)}
    var execution: AccountCourseRun?=null;private set
    val completed get()=engine?.completed?.toSet().orEmpty()
    val isActive get()=state.active
    private var state: WegoState
        get()=read()
        set(value)=update(value)
    fun begin(key: String,onCompleted: ()->Unit={},onReady: ()->Unit={}) {
        val plan=prepare(key)
        val pack=plan.pack;val owned=plan.owner
        val namespace=(owned as? CourseOwner.Account)?.storageKey
        val connection=plan.connection
        val sessionProgress=plan.progress;val sessionVisits=plan.visits
        engine = PackEngine(pack,sessionProgress.read(pack))
        // A finished route has nothing left to observe; the visit record must be reset before another run.
        if(engine?.next==null) {engine=null;error("모든 장소를 방문했어요. 경로 기록을 초기화해 주세요")}
        scores.pause()
        scoreKey=localCourseScoreKey(owned,pack)
        val sessionGeneration = ++generation
        state = state.copy(active = true, selectedKey = key, completed = engine!!.completed.toSet(),
            error = null, location = "위치 연결 중", message = "위치 연결 중",courseResult=null)
        log("SESSION_START")
        val run=if(namespace!=null)AccountCourseRun(checkNotNull(connection),pack,
            checkNotNull(plan.published),
            checkNotNull(connection?.accountDataBoundary())) {
                if(state.active && generation==sessionGeneration)interrupt("계정 경로를 닫았습니다")
            } else null
        execution=run
        fun currentRun()=owned is CourseOwner.Local || execution===run && run?.isCurrent()==true &&
            (owned as CourseOwner.Account).epoch==connection?.dataEpoch()
        fun startLocation() {
            if(!state.active || generation!=sessionGeneration || !currentRun())return
            scoreKey?.let(scores::start)
        try {
            locationClient = LocationClient(platformContext, { data -> main.post {
                if (!state.active || generation != sessionGeneration) return@post
                if(!currentRun()) {interrupt("계정 경로를 닫았습니다");return@post}
                if(!context.getSystemService(android.os.PowerManager::class.java).isInteractive) {
                    interrupt("화면이 꺼져 경로를 중단했어요");return@post
                }
                if(!hasPermissions()) {interrupt("위치 권한이 해제됐어요");fail("위치 권한이 해제됐어요");return@post}
                if(isForeground())state = state.copy(location = "위치 수신")
                val activeEngine = engine ?: return@post
                val stop = activeEngine.candidate(data.latitude, data.longitude, data.timestampMillis, System.currentTimeMillis())
                if (stop != null) {
                    val nextIds = activeEngine.completed + stop.id
                    if (!sessionProgress.save(pack, nextIds)) {
                        interrupt("기록 보관이 중단되었습니다");state=state.copy(storageReady=false)
                        fail("저장 공간을 확인해 주세요");return@post
                    }
                    if (!sessionVisits.record(pack,stop)) {
                        if(isForeground())state=state.copy(completed=nextIds)
                        interrupt("방문 보관이 중단되었습니다");state=state.copy(storageReady=false)
                        fail("저장 공간을 확인해 주세요");return@post
                    }
                    if(!currentRun()) {interrupt("계정 경로를 닫았습니다");return@post}
                    activeEngine.mark(stop.id)
                    if(isForeground() && (namespace==null || state.selectedKey==pack.key)) {
                        state = state.copy(completed = nextIds, message = stop.message, visitedCount=sessionVisits.list().length())
                        log("EVENT_EXECUTED source=FusedLocation")
                        if(isVisible())cue.play { result -> main.post { log(result) } } else log("AUDIO_SKIPPED_BACKGROUND")
                        if (activeEngine.next == null) note("모든 장소 방문 완료")
                    }
                    if(activeEngine.next==null) {
                        // Finish the score before the service ends the session and clears scoreKey.
                        val result=scoreKey?.let(scores::finish)
                        if(state.selectedKey==pack.key)state=state.copy(courseResult=result)
                        onCompleted()
                        complete()
                    }
                }
            } }, { reason -> main.post { if (state.active && generation == sessionGeneration) {
                when(reason) {
                    LocationUnavailableReason.ERROR -> {interrupt("위치 연결이 중단되었습니다");fail("위치 연결을 확인해 주세요")}
                    LocationUnavailableReason.NO_DATA -> state=state.copy(location="위치 정보 없음",message="차량 위치를 기다리고 있어요")
                }
            } } })
            locationClient!!.start()
            onReady()
        } catch (e: Exception) {
            stop()
            throw e
        }
        }
        if(run==null)startLocation() else run.start {ready ->
            if(state.active && generation==sessionGeneration) {
                if(ready)runCatching {startLocation()}.onFailure {interrupt("위치 연결이 중단되었습니다")}
                else interrupt("계정 경로를 닫았습니다")
            }
        }
    }
    fun fail(message: String)=reportFailure(message)
    fun silence()=cue.stop()
    fun requestNavigation()=navigate()
    fun interrupt(message: String) {
        stop();context.stopService(android.content.Intent(context,SessionService::class.java));note(message)
    }
    /** The final foreground chime owns its own completion/focus cleanup after location tracking ends. */
    private fun complete() {
        releaseSession()
        context.stopService(android.content.Intent(context,SessionService::class.java))
        state=state.copy(location="위치 확인 완료")
        note("모든 장소 방문 완료")
    }
    fun stop() {releaseSession();cue.stop()}
    private fun releaseSession() {
        scores.pause();scoreKey=null
        execution?.close();execution=null;generation++
        state=state.copy(active=false)
        locationClient?.release();locationClient=null;engine=null
        onStop()
        log("SESSION_STOP 내비의 기존 길 안내는 유지됩니다")
    }
}
