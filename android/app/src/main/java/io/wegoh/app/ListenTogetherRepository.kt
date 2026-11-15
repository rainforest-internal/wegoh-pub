package io.wegoh.app

import io.wegoh.app.nativeauth.*
import java.io.Closeable
import kotlin.math.abs
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow

/** Maps the server clock onto this device's monotonic clock from the fastest recent round trip. */
internal class ListenTogetherClock {
    private data class Sample(val roundTripMs: Long,val offsetMs: Long)
    private val samples=ArrayDeque<Sample>()
    fun sample(serverTimeMs: Long,sentElapsedMs: Long,receivedElapsedMs: Long) {
        val roundTrip=receivedElapsedMs-sentElapsedMs
        if(roundTrip<0 || roundTrip>MAX_ROUND_TRIP_MS)return
        samples.addLast(Sample(roundTrip,serverTimeMs-(sentElapsedMs+roundTrip/2)))
        while(samples.size>SAMPLES)samples.removeFirst()
    }
    val roundTripMs get()=samples.minByOrNull {it.roundTripMs}?.roundTripMs
    fun elapsedAt(serverTimeMs: Long): Long?=samples.minByOrNull {it.roundTripMs}?.let {serverTimeMs-it.offsetMs}
    fun reset()=samples.clear()
    companion object {
        const val SAMPLES=8
        const val MAX_ROUND_TRIP_MS=3000L
    }
}

/** Local audio output for the bundled track. Every call happens on the main thread. */
internal interface ListenTogetherPlayer: Closeable {
    interface Listener {
        fun onPlaying(playing: Boolean)
        fun onEnded()
        fun onError()
        /** Permanent audio focus loss or output change; the user has to choose to listen again. */
        fun onStoppedBySystem()
    }
    var listener: Listener?
    val positionMs: Long
    /** True while playback is suppressed by a transient focus loss and will resume by itself. */
    val suspended: Boolean
    fun prepare()
    fun playFrom(positionMs: Long)
    fun seekTo(positionMs: Long)
    fun stop()
}

internal interface ListenTogetherGateway: Closeable {
    val current: Boolean
    fun open(observer: NativeSocialObserver,callback: (Result<Unit>)->Unit)
    fun read(callback: (Result<ListenTogetherSnapshot>)->Unit): Closeable
    fun participate(sessionId: String?,trackSha256: String,joined: Boolean,callback: (Result<ListenTogetherSnapshot>)->Unit): Closeable
    fun start(sessionId: String,revision: Long,callback: (Result<ListenTogetherSnapshot>)->Unit): Closeable
    fun end(sessionId: String,callback: (Result<ListenTogetherSnapshot>)->Unit): Closeable
}

internal interface ListenTogetherTimer {
    val elapsedMs: Long
    fun post(delayMs: Long,action: ()->Unit): Closeable
}

internal enum class ListenTogetherAudio { IDLE, READY, COUNTDOWN, PLAYING, SUSPENDED, FINISHED }

internal data class ListenTogetherUiState(val offered: Boolean=false,val loading: Boolean=false,val host: Boolean=false,
    val session: ListenTogetherSession?=null,val minimumDevices: Int=2,val joined: Boolean=false,
    val audio: ListenTogetherAudio=ListenTogetherAudio.IDLE,val countdownSeconds: Int?=null,
    val blocked: String?=null,val notice: String?=null,val busy: Boolean=false) {
    val active get()=session?.takeIf {it.phase!=ListenTogetherPhase.ENDED}
    val canStart get()=host && joined && active?.phase==ListenTogetherPhase.PREPARING && active!!.deviceCount>=minimumDevices
}

/**
 * Vehicle side of the demo listen-together session. The server holds the canonical control state;
 * this class only plays the bundled file after an explicit tap, on a parked vehicle, while the screen
 * is in the foreground. Anything it can no longer verify stops local audio and requires a new tap.
 */
internal class ListenTogetherRepository(private val gateway: ()->ListenTogetherGateway,private val player: ()->ListenTogetherPlayer,
    private val timer: ListenTogetherTimer,private val log: (String)->Unit={}): Closeable {
    private val mutable=MutableStateFlow(ListenTogetherUiState())
    val states=mutable.asStateFlow()
    val state get()=states.value
    private val clock=ListenTogetherClock()
    private var client: ListenTogetherGateway?=null
    private var audio: ListenTogetherPlayer?=null
    private var trackSha256: String?=null
    private var trackDurationMs=0L
    private var visible=false
    private var focused=false
    private var parked: Boolean?=null
    private var uxAllowed: Boolean?=null
    private var closed=false
    private var generation=0L
    private var reading: Closeable?=null
    private var readSerial=0L
    private var readIssuedMs=0L
    private var rereadPending=false
    private var writeSerial=0L
    /** Writes in flight, oldest first. They are never cancelled by a later write; see [send]. */
    private val sending=mutableListOf<Closeable>()
    private var poll: Closeable?=null
    private var watchdog: Closeable?=null
    private var retry: Closeable?=null
    /** 재생 타이머(시작 예약·카운트다운·드리프트)의 세대. 연결 세대와 따로 두어 일시 재연결이 재생을 끊지 않게 한다. */
    private var playback=0L
    private var scheduled: Closeable?=null
    private var drift: Closeable?=null
    private var ticking: Closeable?=null
    private var joinedSession: String?=null
    private var lastConfirmedMs=0L
    private var appliedRevision=0L

    private val safe get()=parked==true && uxAllowed==true
    private fun interactive()=!closed && visible && focused && safe && client?.current==true

    /** Bundled track hash; null when this build carries no demo track, which hides the feature. */
    fun setTrack(sha256: String?) {
        if(closed || trackSha256==sha256)return
        trackSha256=sha256
        if(sha256==null){leaveLocally(null);disconnect();mutable.value=ListenTogetherUiState()} else if(visible)connect()
    }

    fun setEnvironment(visible: Boolean,focused: Boolean,parked: Boolean?,uxAllowed: Boolean?) {
        if(closed)return
        val wasVisible=this.visible
        this.visible=visible;this.focused=focused;this.parked=parked;this.uxAllowed=uxAllowed
        if(!visible) {
            if(wasVisible) {leave(null);disconnect();mutable.value=ListenTogetherUiState()}
            return
        }
        if(!safe && joinedSession!=null)leave(NOTICE_RESTRICTED)
        publishBlocked()
        if(!wasVisible || client==null)connect()
    }

    private fun publishBlocked() {
        mutable.value=state.copy(blocked=when {
            parked==null || uxAllowed==null->"차량 상태를 확인하고 있어요"
            !safe->"정차(P단)하고 주행 제한이 없을 때만 들을 수 있어요"
            trackSha256==null->"시연 음원을 확인하고 있어요"
            else->null
        })
    }

    private fun connect() {
        if(closed || !visible || trackSha256==null)return
        // 참여 중이면 같은 세션을 이어 확인하므로 시계 표본과 리비전을 남긴다.
        disconnect(keepTimeline=joinedSession!=null)
        val token=++generation
        val own=gateway();client=own
        mutable.value=state.copy(loading=true)
        own.open(object: NativeSocialObserver {
            override fun onInvalidated() {
                if(token!=generation || client!==own)return
                // 함께 듣는 중의 무효화(연결 일시 unavailable·권한 스냅샷 교체)는 화면 이탈이 아니라 확인 지연이다.
                // 재생과 참여는 그대로 두고 다시 연결하며, 멈춤은 확인 감시(CONFIRMATION_TIMEOUT_MS)만 판정한다.
                if(joinedSession!=null && visible && !closed) {reconnectLater();return}
                leaveLocally(NOTICE_CONNECTION);disconnect()
                mutable.value=state.copy(loading=false,offered=false,session=null,joined=false)
                // 권한 교체만으로 끊긴 경우 화면이 보이는 동안 다시 연결한다(재생 참여는 다시 하지 않는다).
                if(visible && !closed)invalidationReloads.take()?.let {connect()}
            }
            override fun onConnectionLost()=onInvalidated()
            override fun onResourcesChanged(resources: Set<String>) {
                if(token==generation && resources.any {it in setOf("rooms","music") || it.endsWith(".music")})refresh()
            }
        }) {result->
            if(token!=generation || client!==own || closed)return@open
            if(result.isSuccess && own.current)refresh() else {
                // 열었는데 현재가 아니면(계정·연결 경계 변경) 확인할 수 없는 재생을 바로 멈춘다.
                if(result.isSuccess)leaveLocally(NOTICE_CONNECTION)
                mutable.value=state.copy(loading=false,offered=false);disconnect()
            }
        }
    }

    /** 연결만 닫는다. 참여 중 재생과 확인 감시는 [leaveLocally]가 끝낸다. [keepTimeline]이면 같은 세션을 이어 확인하도록
     * 서버 시계 표본과 적용한 리비전을 남긴다. */
    private fun disconnect(keepTimeline: Boolean=false) {
        generation++
        reading?.close();sending.forEach {it.close()};poll?.close();retry?.close()
        reading=null;sending.clear();poll=null;retry=null;rereadPending=false
        client?.close();client=null
        if(!keepTimeline){clock.reset();appliedRevision=0L}
    }

    /** 참여 중 연결이 끊기면 하트비트 간격으로 다시 연다. 연결이 돌아오지 않으면 확인 감시가 멈춘다. */
    private fun reconnectLater() {
        log("reconnect joined=true")
        disconnect(keepTimeline=true)
        val token=generation
        retry=timer.post(HEARTBEAT_MS) {
            retry=null
            if(token==generation && visible && !closed)connect()
        }
    }

    fun refresh() {
        val own=client ?: return
        if(closed || !own.current)return
        // An in-flight read is never cancelled: its answer is the next confirmation. Reads run in order on the
        // connection's realtime lane, so cancelling one to send another only delays the confirmation further.
        if(reading!=null){rereadPending=true;return}
        poll?.close();poll=null
        val token=generation;val serial=++readSerial;val writes=writeSerial
        var done=false
        readIssuedMs=timer.elapsedMs
        val handle=own.read {result->
            if(token!=generation || serial!=readSerial)return@read
            done=true;reading=null
            // A write sent meanwhile carries a newer state; this read only keeps the poll going and,
            // since every read refreshes server presence, still confirms the participation it reports.
            if(writes==writeSerial)result.fold(onSuccess={apply(it)},onFailure={readFailed(it)})
            else result.getOrNull()?.session?.let {if(it.id==joinedSession && it.joined && it.phase!=ListenTogetherPhase.ENDED)lastConfirmedMs=timer.elapsedMs}
            if(token!=generation)return@read
            if(rereadPending){rereadPending=false;refresh()} else schedulePoll()
        }
        if(!done)reading=handle
    }

    /** Fixed cadence from the previous send, so time spent waiting on the realtime lane is not added on top. */
    private fun schedulePoll() {
        poll?.close();poll=null
        if(closed || client==null || reading!=null)return
        val token=generation
        val interval=if(joinedSession!=null)HEARTBEAT_MS else IDLE_POLL_MS
        poll=timer.post(readIssuedMs+interval-timer.elapsedMs) {if(token==generation)refresh()}
    }

    private fun readFailed(error: Throwable) {
        val kind=(error as? NativeSocialFailure)?.kind
        if(kind in setOf(NativeSocialFailure.Kind.FORBIDDEN,NativeSocialFailure.Kind.NOT_FOUND,NativeSocialFailure.Kind.AUTHORIZATION_REQUIRED,NativeSocialFailure.Kind.CLOSED)) {
            leaveLocally(NOTICE_CONNECTION)
            mutable.value=state.copy(loading=false,offered=false,session=null,joined=false)
        } else mutable.value=state.copy(loading=false)
    }

    private val invalidationReloads=InvalidationReloads()

    private fun apply(snapshot: ListenTogetherSnapshot) {
        invalidationReloads.reset()
        clock.sample(snapshot.serverTimeMs,snapshot.sentElapsedMs,snapshot.receivedElapsedMs)
        if(joinedSession!=null)log("sample rtt=${snapshot.receivedElapsedMs-snapshot.sentElapsedMs} best_rtt=${clock.roundTripMs}")
        trackDurationMs=snapshot.track.durationMs
        if(!snapshot.available || snapshot.track.sha256!=trackSha256) {
            leaveLocally(null)
            mutable.value=ListenTogetherUiState(blocked=state.blocked)
            return
        }
        val session=snapshot.session
        // A response that predates one already shown for the same session never rolls the screen back.
        if(session!=null && session.id==state.session?.id && session.revision<appliedRevision)return
        appliedRevision=session?.revision ?: 0L
        mutable.value=state.copy(offered=true,loading=false,host=snapshot.host,session=session,minimumDevices=snapshot.minimumDevices)
        val mine=joinedSession
        if(mine!=null) {
            when {
                session==null || session.id!=mine->leaveLocally(NOTICE_SESSION_GONE)
                session.phase==ListenTogetherPhase.ENDED->leaveLocally(endNotice(session.endedReason))
                !session.joined->leaveLocally(NOTICE_DROPPED)
                else->{lastConfirmedMs=timer.elapsedMs;follow(session)}
            }
        } else if(session!=null && session.joined && session.phase!=ListenTogetherPhase.ENDED && sending.isEmpty()) {
            // Every read refreshes server presence, so a participation this vehicle already stopped would otherwise
            // stay counted as ready (for example after a local timeout whose leave request was lost).
            release(session.id)
        }
        mutable.value=state.copy(joined=joinedSession!=null)
    }

    /** Explicit consent for this session: get ready, or join a session already playing at its current position. */
    fun join() {
        val own=client ?: return
        val sha=trackSha256 ?: return
        if(!interactive() || state.busy || joinedSession!=null || !state.offered)return
        val target=state.active
        if(target!=null && target.phase==ListenTogetherPhase.PLAYING && remainingMs(target)<=MIN_LATE_JOIN_MS)return
        write(own,{own.participate(target?.id,sha,true,it)}) {snapshot->
            val session=snapshot.session
            if(session!=null && session.joined && session.phase!=ListenTogetherPhase.ENDED) {
                joinedSession=session.id;lastConfirmedMs=timer.elapsedMs
                ensurePlayer().prepare()
                startWatchdog()
            }
            apply(snapshot)
            // A poll armed while idle could fire after the confirmation timeout; switch to the heartbeat now.
            schedulePoll()
        }
    }

    /** This vehicle only: stop now, then tell the server. */
    fun leave()=leave(null)

    private fun leave(notice: String?) {
        val mine=joinedSession ?: return
        leaveLocally(notice)
        release(mine)
    }

    /** Tells the server this vehicle is out, so its reads no longer keep a participation it does not play. */
    private fun release(sessionId: String) {
        val own=client ?: return
        val sha=trackSha256 ?: return
        if(!own.current)return
        val serial=++writeSerial
        mutable.value=state.copy(busy=false)
        send({own.participate(sessionId,sha,false,it)}) {result->
            if(serial==writeSerial)result.onSuccess {apply(it)}
        }
    }

    /**
     * Sends a write and lets it finish even when another write follows: a cancelled join or start would leave
     * the server and this vehicle disagreeing. The connection's listen lane is serial, so writes reach the
     * server in the order they were made; only the newest write's answer is applied to the screen.
     */
    private fun send(call: ((Result<ListenTogetherSnapshot>)->Unit)->Closeable,done: (Result<ListenTogetherSnapshot>)->Unit) {
        val token=generation
        var handle: Closeable?=null
        var finished=false
        val sent=call {result->
            finished=true;handle?.let {sending.remove(it)}
            if(token==generation)done(result)
        }
        if(!finished){handle=sent;sending+=sent}
    }

    fun start() {
        val own=client ?: return
        val session=state.active ?: return
        if(!interactive() || state.busy || !state.canStart)return
        write(own,{own.start(session.id,session.revision,it)}) {apply(it)}
    }

    fun endForEveryone() {
        val own=client ?: return
        val session=state.active ?: return
        if(!interactive() || state.busy || !state.host)return
        write(own,{own.end(session.id,it)}) {apply(it)}
    }

    private fun write(own: ListenTogetherGateway,call: ((Result<ListenTogetherSnapshot>)->Unit)->Closeable,success: (ListenTogetherSnapshot)->Unit) {
        val serial=++writeSerial
        mutable.value=state.copy(busy=true,notice=null)
        send(call) {result->
            if(serial!=writeSerial)return@send
            mutable.value=state.copy(busy=false)
            result.fold(onSuccess=success,onFailure={error->
                val kind=(error as? NativeSocialFailure)?.kind
                mutable.value=state.copy(notice=when(kind) {
                    NativeSocialFailure.Kind.CONFLICT->"함께 듣기 상태가 바뀌었어요. 확인하고 다시 눌러 주세요"
                    NativeSocialFailure.Kind.FORBIDDEN->"이 여행에서는 함께 듣기를 쓸 수 없어요"
                    else->"요청을 보내지 못했어요. 다시 시도해 주세요"
                })
                refresh()
            })
        }
    }

    private fun ensurePlayer(): ListenTogetherPlayer = audio ?: player().also {created->
        audio=created
        created.listener=object: ListenTogetherPlayer.Listener {
            override fun onPlaying(playing: Boolean) {
                if(audio!==created || joinedSession==null)return
                mutable.value=state.copy(audio=when {
                    playing->ListenTogetherAudio.PLAYING
                    created.suspended->ListenTogetherAudio.SUSPENDED
                    else->state.audio
                },countdownSeconds=if(playing)null else state.countdownSeconds)
            }
            override fun onEnded() {
                if(audio!==created || joinedSession==null)return
                cancelPlayback();mutable.value=state.copy(audio=ListenTogetherAudio.FINISHED)
            }
            override fun onError() {if(audio===created)leave(NOTICE_PLAYER_ERROR)}
            override fun onStoppedBySystem() {if(audio===created)leave(NOTICE_FOCUS)}
        }
    }

    private fun remainingMs(session: ListenTogetherSession): Long {
        val start=session.startAtMs?.let(clock::elapsedAt) ?: return Long.MAX_VALUE
        return start+trackDurationMs-timer.elapsedMs
    }

    private fun expectedPositionMs(session: ListenTogetherSession): Long? =
        session.startAtMs?.let(clock::elapsedAt)?.let {timer.elapsedMs-it}

    /** Plays at the shared start time, or from the elapsed position when this vehicle is late. */
    private fun follow(session: ListenTogetherSession) {
        val output=audio ?: return
        if(session.phase!=ListenTogetherPhase.PLAYING) {
            if(state.audio==ListenTogetherAudio.IDLE)mutable.value=state.copy(audio=ListenTogetherAudio.READY)
            return
        }
        if(state.audio==ListenTogetherAudio.FINISHED)return
        val position=expectedPositionMs(session) ?: return
        if(position>=trackDurationMs)return
        if(position<0) {
            if(scheduled==null) {
                val token=playback
                log("scheduled delay=${-position} best_rtt=${clock.roundTripMs}")
                scheduled=timer.post(-position) {
                    scheduled=null
                    if(token==playback && joinedSession==session.id)expectedPositionMs(session)?.let {
                        log("play position=${it.coerceAtLeast(0)}");output.playFrom(it.coerceAtLeast(0));startDrift(session)
                    }
                }
            }
            if(ticking==null)countdown(session)
        } else if(state.audio in setOf(ListenTogetherAudio.IDLE,ListenTogetherAudio.READY,ListenTogetherAudio.COUNTDOWN) && scheduled==null && drift==null) {
            log("late position=$position");output.playFrom(position);startDrift(session)
        }
    }

    private fun countdown(session: ListenTogetherSession) {
        val start=session.startAtMs?.let(clock::elapsedAt) ?: return
        val left=start-timer.elapsedMs
        if(left<=0 || joinedSession!=session.id)return
        mutable.value=state.copy(audio=ListenTogetherAudio.COUNTDOWN,countdownSeconds=((left+999)/1000).toInt())
        val token=playback
        ticking?.close()
        ticking=timer.post(minOf(left,COUNTDOWN_TICK_MS)) {ticking=null;if(token==playback && state.audio==ListenTogetherAudio.COUNTDOWN)countdown(session)}
    }

    /** Re-aligns to the shared timeline when the local position wanders, including after a transient focus pause. */
    private fun startDrift(session: ListenTogetherSession) {
        drift?.close()
        val token=playback
        drift=timer.post(DRIFT_CHECK_MS) {
            drift=null
            val output=audio
            if(token!=playback || joinedSession!=session.id || output==null || state.audio==ListenTogetherAudio.FINISHED)return@post
            val expected=expectedPositionMs(session)
            if(expected!=null && !output.suspended && expected<trackDurationMs) {
                val difference=output.positionMs-expected
                log("drift difference=$difference")
                if(abs(difference)>DRIFT_TOLERANCE_MS)output.seekTo(expected)
            }
            startDrift(session)
        }
    }

    /** 연결이 바뀌어도 이어진다. 참여를 끝내는 [leaveLocally]만 닫는다. */
    private fun startWatchdog() {
        watchdog?.close()
        watchdog=timer.post(WATCHDOG_TICK_MS) {
            watchdog=null
            if(joinedSession==null)return@post
            if(timer.elapsedMs-lastConfirmedMs>CONFIRMATION_TIMEOUT_MS)leave(NOTICE_CONNECTION) else startWatchdog()
        }
    }

    private fun cancelPlayback() {playback++;scheduled?.close();scheduled=null;drift?.close();drift=null;ticking?.close();ticking=null}

    /**
     * Silences this vehicle immediately; the session itself is left to the server. [notice] explains why this vehicle
     * stopped, so it is shown only when this vehicle was participating (ready or playing); otherwise nothing stopped.
     */
    private fun leaveLocally(notice: String?) {
        val wasJoined=joinedSession!=null
        joinedSession=null
        cancelPlayback();watchdog?.close();watchdog=null
        audio?.let {it.listener=null;it.stop();it.close()};audio=null
        if(wasJoined)mutable.value=state.copy(joined=false,audio=ListenTogetherAudio.IDLE,countdownSeconds=null,
            notice=notice ?: state.notice)
    }

    override fun close() {
        if(closed)return
        leave(null);closed=true;visible=false
        disconnect();mutable.value=ListenTogetherUiState()
    }

    companion object {
        const val HEARTBEAT_MS=1500L
        const val IDLE_POLL_MS=5000L
        const val WATCHDOG_TICK_MS=250L
        /**
         * Local stop bound when confirmation stops. Reads run on the realtime lane, but a lane call may still wait for
         * account verification on the shared worker; the demo vehicles measured waits of up to 3.4 s on that worker,
         * so confirmations can land about 5 s apart while healthy.
         * Kept below the server's 8 s presence timeout so this vehicle stops before the server drops it.
         */
        const val CONFIRMATION_TIMEOUT_MS=6000L
        const val DRIFT_CHECK_MS=1000L
        const val DRIFT_TOLERANCE_MS=120L
        const val COUNTDOWN_TICK_MS=250L
        const val MIN_LATE_JOIN_MS=3000L
        const val NOTICE_RESTRICTED="주행 제한으로 이 차의 재생을 멈췄어요. 정차(P단) 후 다시 참여해 주세요"
        const val NOTICE_CONNECTION="연결이 끊겨 이 차의 재생을 멈췄어요. 다시 들으려면 참여를 눌러 주세요"
        const val NOTICE_DROPPED="참여가 끝났어요. 다시 들으려면 참여를 눌러 주세요"
        const val NOTICE_SESSION_GONE="함께 듣기가 끝났어요"
        const val NOTICE_PLAYER_ERROR="재생 오류로 이 차의 재생을 멈췄어요"
        const val NOTICE_FOCUS="다른 오디오가 재생돼 이 차의 재생을 멈췄어요"
        fun endNotice(reason: ListenTogetherEndReason?)=when(reason) {
            ListenTogetherEndReason.HOST_ENDED->"방장이 모두 종료했어요"
            ListenTogetherEndReason.TRACK_FINISHED->"곡이 끝났어요"
            ListenTogetherEndReason.EVERYONE_LEFT->"모두 나가서 함께 듣기가 끝났어요"
            ListenTogetherEndReason.TRIP_CLOSED->"여행이 끝나 함께 듣기를 멈췄어요"
            null->NOTICE_SESSION_GONE
        }
    }
}
