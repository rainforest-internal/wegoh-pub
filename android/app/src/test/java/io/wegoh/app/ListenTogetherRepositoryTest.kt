package io.wegoh.app

import io.wegoh.app.nativeauth.*
import java.io.Closeable
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class ListenTogetherRepositoryTest {
    private val trip="a".repeat(32)
    private val sha="0".repeat(64)
    private val sessionId="c".repeat(32)
    private val track=ListenTogetherTrack("wegoh-demo-01",1,sha,48000)

    private class Pending<T>(private val callback: (Result<T>)->Unit): Closeable {
        var cancelled=false
            private set
        override fun close(){cancelled=true}
        fun success(value: T)=callback(Result.success(value))
        fun failure(error: Throwable)=callback(Result.failure(error))
    }
    private data class Participation(val sessionId: String?,val sha: String,val joined: Boolean,val response: Pending<ListenTogetherSnapshot>)
    private class FakeGateway: ListenTogetherGateway {
        var ready=false
        var closed=false
        override val current get()=ready && !closed
        lateinit var observer: NativeSocialObserver
        private lateinit var opening: (Result<Unit>)->Unit
        val reads=mutableListOf<Pending<ListenTogetherSnapshot>>()
        val participations=mutableListOf<Participation>()
        val starts=mutableListOf<Pair<Long,Pending<ListenTogetherSnapshot>>>()
        val ends=mutableListOf<Pending<ListenTogetherSnapshot>>()
        override fun open(observer: NativeSocialObserver,callback: (Result<Unit>)->Unit){this.observer=observer;opening=callback}
        fun opened(){ready=true;opening(Result.success(Unit))}
        override fun read(callback: (Result<ListenTogetherSnapshot>)->Unit): Closeable = Pending(callback).also {reads+=it}
        override fun participate(sessionId: String?,trackSha256: String,joined: Boolean,callback: (Result<ListenTogetherSnapshot>)->Unit): Closeable =
            Pending(callback).also {participations+=Participation(sessionId,trackSha256,joined,it)}
        override fun start(sessionId: String,revision: Long,callback: (Result<ListenTogetherSnapshot>)->Unit): Closeable =
            Pending(callback).also {starts+=revision to it}
        override fun end(sessionId: String,callback: (Result<ListenTogetherSnapshot>)->Unit): Closeable = Pending(callback).also {ends+=it}
        override fun close(){closed=true}
    }
    private class FakePlayer: ListenTogetherPlayer {
        override var listener: ListenTogetherPlayer.Listener?=null
        override var positionMs=0L
        override var suspended=false
        var prepared=false
        var closed=false
        val plays=mutableListOf<Long>()
        val seeks=mutableListOf<Long>()
        var playing=false
        override fun prepare(){prepared=true}
        override fun playFrom(positionMs: Long){plays+=positionMs;this.positionMs=positionMs;playing=true;listener?.onPlaying(true)}
        override fun seekTo(positionMs: Long){seeks+=positionMs;this.positionMs=positionMs}
        override fun stop(){playing=false}
        override fun close(){closed=true;playing=false}
    }
    private class FakeTimer: ListenTogetherTimer {
        private data class Task(val at: Long,val action: ()->Unit,var cancelled: Boolean=false)
        private val tasks=mutableListOf<Task>()
        override var elapsedMs=100_000L
        override fun post(delayMs: Long,action: ()->Unit): Closeable {
            val task=Task(elapsedMs+delayMs.coerceAtLeast(0),action);tasks+=task
            return Closeable {task.cancelled=true}
        }
        fun advance(ms: Long) {
            val until=elapsedMs+ms
            while(true) {
                val next=tasks.filter {!it.cancelled && it.at<=until}.minByOrNull {it.at} ?: break
                tasks.remove(next);elapsedMs=next.at;next.action()
            }
            elapsedMs=until
        }
    }
    private inner class Fixture {
        val timer=FakeTimer()
        val gateways=mutableListOf<FakeGateway>()
        val players=mutableListOf<FakePlayer>()
        val repository=ListenTogetherRepository({FakeGateway().also {gateways+=it}},{FakePlayer().also {players+=it}},timer)
        val gateway get()=gateways.last()
        val player get()=players.last()
        /** Server clock equals local elapsed + 1_000_000 with a 40 ms round trip. */
        fun snapshot(session: ListenTogetherSession?,host: Boolean=false,available: Boolean=true,trackSha: String=sha)=
            ListenTogetherSnapshot(trip,available,timer.elapsedMs+1_000_000-20,host,2,track.copy(sha256=trackSha),session,
                timer.elapsedMs-40,timer.elapsedMs)
        fun open(session: ListenTogetherSession?=null,host: Boolean=false) {
            repository.setTrack(sha)
            repository.setEnvironment(true,true,true,true)
            gateway.opened();gateway.reads.last().success(snapshot(session,host))
        }
        /** Advances time while the server answers every heartbeat with the same session. */
        fun confirmed(ms: Long,session: ListenTogetherSession) {
            var left=ms
            while(left>0) {
                val step=minOf(left,100L);timer.advance(step);left-=step
                val pending=gateway.reads.size
                if(pending>answered){answered=pending;gateway.reads.last().success(snapshot(session))}
            }
        }
        var answered=1
        fun join(session: ListenTogetherSession) {
            repository.join()
            gateway.participations.last().response.success(snapshot(session))
        }
    }
    private fun session(phase: ListenTogetherPhase=ListenTogetherPhase.PREPARING,revision: Long=1,count: Int=1,joined: Boolean=true,
        startAt: Long?=null,reason: ListenTogetherEndReason?=null,id: String=sessionId)=
        ListenTogetherSession(id,revision,phase,count,joined,startAt,reason)

    @Test fun clockUsesFastestRoundTripMidpoint() {
        val clock=ListenTogetherClock()
        clock.sample(serverTimeMs=10_500,sentElapsedMs=0,receivedElapsedMs=400)
        clock.sample(serverTimeMs=11_050,sentElapsedMs=1000,receivedElapsedMs=1100)
        assertEquals(100L,clock.roundTripMs)
        assertEquals(1000L,clock.elapsedAt(11_000))
        clock.sample(serverTimeMs=1,sentElapsedMs=5000,receivedElapsedMs=4000)
        assertEquals(100L,clock.roundTripMs)
    }

    @Test fun invalidationWhileVisibleReconnectsAndStopsAtTheLimit() {
        val f=Fixture()
        f.open()
        f.gateway.observer.onInvalidated()
        assertEquals(2,f.gateways.size)
        f.gateway.opened();f.gateway.reads.last().success(f.snapshot(null))
        assertTrue(f.repository.state.offered)
        repeat(INVALIDATION_RELOAD_LIMIT+2) {f.gateway.observer.onInvalidated()}
        assertEquals(2+INVALIDATION_RELOAD_LIMIT,f.gateways.size)
    }

    @Test fun joiningRequiresParkedForegroundAndBundledTrack() {
        val f=Fixture()
        f.repository.setEnvironment(true,true,true,true)
        assertTrue(f.gateways.isEmpty())
        f.repository.setTrack(sha)
        f.gateway.opened();f.gateway.reads.last().success(f.snapshot(null))
        assertTrue(f.repository.state.offered)
        f.repository.setEnvironment(true,true,false,true)
        assertNotNull(f.repository.state.blocked)
        f.repository.join()
        assertTrue(f.gateway.participations.isEmpty())
        f.repository.setEnvironment(true,false,true,true)
        f.repository.join()
        assertTrue(f.gateway.participations.isEmpty())
        f.repository.setEnvironment(true,true,true,true)
        f.repository.join()
        assertEquals(listOf(Participation(null,sha,true,f.gateway.participations.single().response)),f.gateway.participations)
        f.repository.close()
    }

    @Test fun unavailableTripOrDifferentTrackIsNotOffered() {
        val f=Fixture()
        f.repository.setTrack(sha);f.repository.setEnvironment(true,true,true,true);f.gateway.opened()
        f.gateway.reads.last().success(f.snapshot(null,available=false))
        assertFalse(f.repository.state.offered)
        f.repository.refresh();f.gateway.reads.last().success(f.snapshot(null,trackSha="1".repeat(64)))
        assertFalse(f.repository.state.offered)
        f.repository.setTrack(null)
        assertFalse(f.repository.state.offered)
        assertTrue(f.gateway.closed)
    }

    @Test fun readyVehicleStartsAtSharedServerTimeAndCountsDown() {
        val f=Fixture()
        f.open()
        f.join(session())
        assertTrue(f.repository.state.joined)
        assertTrue(f.player.prepared)
        assertEquals(ListenTogetherAudio.READY,f.repository.state.audio)
        val startAt=f.timer.elapsedMs+1_000_000+4000
        f.repository.refresh();f.gateway.reads.last().success(f.snapshot(session(ListenTogetherPhase.PLAYING,3,2,startAt=startAt)))
        assertEquals(ListenTogetherAudio.COUNTDOWN,f.repository.state.audio)
        assertEquals(4,f.repository.state.countdownSeconds)
        assertTrue(f.player.plays.isEmpty())
        val playing=session(ListenTogetherPhase.PLAYING,3,2,startAt=startAt)
        f.answered=f.gateway.reads.size
        f.confirmed(3900,playing)
        assertTrue(f.player.plays.isEmpty())
        f.confirmed(100,playing)
        assertEquals(listOf(0L),f.player.plays)
        assertEquals(ListenTogetherAudio.PLAYING,f.repository.state.audio)
        f.repository.close()
    }

    @Test fun lateJoinStartsFromElapsedPositionAndDriftIsCorrected() {
        val f=Fixture()
        val startAt=f.timer.elapsedMs+1_000_000-7000
        f.open(session(ListenTogetherPhase.PLAYING,4,2,joined=false,startAt=startAt))
        assertFalse(f.repository.state.joined)
        f.join(session(ListenTogetherPhase.PLAYING,5,3,startAt=startAt))
        assertEquals(listOf(7000L),f.player.plays)
        f.player.positionMs=7500
        f.timer.advance(1000)
        assertEquals(listOf(8000L),f.player.seeks)
        // A transient focus pause resumes by itself; position is not forced while suspended.
        f.player.suspended=true;f.player.positionMs=0
        f.gateway.reads.lastOrNull()?.success(f.snapshot(session(ListenTogetherPhase.PLAYING,5,3,startAt=startAt)))
        f.timer.advance(1000)
        assertEquals(1,f.player.seeks.size)
        f.repository.close()
    }

    @Test fun hostStartsOnlyWithTwoReadyVehiclesIncludingItself() {
        val f=Fixture()
        f.open(session(count=1,joined=false),host=true)
        assertFalse(f.repository.state.canStart)
        f.repository.join()
        f.gateway.participations.last().response.success(f.snapshot(session(revision=2,count=2),host=true))
        assertTrue(f.repository.state.canStart)
        f.repository.start()
        f.repository.start()
        assertEquals(listOf(2L),f.gateway.starts.map {it.first})
        f.gateway.starts.last().second.failure(NativeSocialFailure(NativeSocialFailure.Kind.CONFLICT))
        assertEquals("함께 듣기 상태가 바뀌었어요. 확인하고 다시 눌러 주세요",f.repository.state.notice)
        f.repository.close()
    }

    @Test fun guestCannotStartOrEnd() {
        val f=Fixture()
        f.open(session(count=2,joined=false))
        f.join(session(revision=2,count=3))
        f.repository.start();f.repository.endForEveryone()
        assertTrue(f.gateway.starts.isEmpty() && f.gateway.ends.isEmpty())
        f.repository.close()
    }

    @Test fun hostEndAndTrackFinishStopEveryVehicleWithDistinctNotices() {
        val f=Fixture()
        val startAt=f.timer.elapsedMs+1_000_000-1000
        f.open(session(ListenTogetherPhase.PLAYING,4,2,joined=false,startAt=startAt))
        f.join(session(ListenTogetherPhase.PLAYING,5,3,startAt=startAt))
        val player=f.player
        f.gateway.observer.onResourcesChanged(setOf("music"))
        f.gateway.reads.last().success(f.snapshot(session(ListenTogetherPhase.ENDED,6,0,joined=false,startAt=startAt,reason=ListenTogetherEndReason.HOST_ENDED)))
        assertTrue(player.closed)
        assertFalse(f.repository.state.joined)
        assertEquals("방장이 모두 종료했어요",f.repository.state.notice)
        assertNotEquals(ListenTogetherRepository.endNotice(ListenTogetherEndReason.TRACK_FINISHED),f.repository.state.notice)
        f.repository.close()
    }

    @Test fun droppedParticipationIsNotRestoredByReconnecting() {
        val f=Fixture()
        f.open()
        f.join(session())
        f.repository.refresh();f.gateway.reads.last().success(f.snapshot(session(revision=3,count=1,joined=false)))
        assertFalse(f.repository.state.joined)
        assertEquals(ListenTogetherRepository.NOTICE_DROPPED,f.repository.state.notice)
        assertTrue(f.player.closed)
        f.repository.refresh();f.gateway.reads.last().success(f.snapshot(session(revision=3,count=1,joined=true)))
        assertFalse(f.repository.state.joined)
        f.repository.close()
    }

    @Test fun lostConfirmationStopsLocalAudioWithinBound() {
        val f=Fixture()
        val startAt=f.timer.elapsedMs+1_000_000-1000
        f.open(session(ListenTogetherPhase.PLAYING,4,2,joined=false,startAt=startAt))
        f.join(session(ListenTogetherPhase.PLAYING,5,3,startAt=startAt))
        f.timer.advance(ListenTogetherRepository.CONFIRMATION_TIMEOUT_MS)
        assertTrue(f.repository.state.joined)
        f.timer.advance(ListenTogetherRepository.WATCHDOG_TICK_MS)
        assertFalse(f.repository.state.joined)
        assertEquals(ListenTogetherRepository.NOTICE_CONNECTION,f.repository.state.notice)
        assertTrue(f.player.closed)
        // The server is told as well, so this vehicle's later reads do not keep it counted as ready.
        assertEquals(Participation(sessionId,sha,false,f.gateway.participations.last().response),f.gateway.participations.last())
        f.repository.close()
    }

    @Test fun joiningSwitchesToHeartbeatEvenWithAnIdlePollArmed() {
        val f=Fixture()
        f.open()
        f.timer.advance(1000)
        f.join(session())
        val reads=f.gateway.reads.size
        f.timer.advance(ListenTogetherRepository.HEARTBEAT_MS)
        assertEquals(reads+1,f.gateway.reads.size)
        f.answered=reads
        f.confirmed(20_000,session())
        assertTrue(f.repository.state.joined)
        f.repository.close()
    }

    @Test fun refreshDuringReadKeepsTheReadInFlightAndReadsAgainAfter() {
        val f=Fixture()
        f.open();f.join(session())
        f.timer.advance(ListenTogetherRepository.HEARTBEAT_MS)
        val inFlight=f.gateway.reads.last()
        val reads=f.gateway.reads.size
        f.gateway.observer.onResourcesChanged(setOf("trip.$trip.music"))
        f.gateway.observer.onResourcesChanged(setOf("music"))
        assertFalse(inFlight.cancelled)
        assertEquals(reads,f.gateway.reads.size)
        inFlight.success(f.snapshot(session(revision=2,count=2)))
        assertEquals(2,f.repository.state.session!!.deviceCount)
        assertEquals(reads+1,f.gateway.reads.size)
        f.repository.close()
    }

    @Test fun slowSharedWorkerDoesNotDropAReadyVehicle() {
        val f=Fixture()
        f.open();f.join(session())
        // Measured on the demo vehicles: up to 3.4 s queued behind other native calls plus a 0.7 s round trip.
        repeat(8) {
            val issued=f.gateway.reads.size
            f.timer.advance(ListenTogetherRepository.HEARTBEAT_MS)
            assertEquals(issued+1,f.gateway.reads.size)
            f.timer.advance(4100-ListenTogetherRepository.HEARTBEAT_MS)
            f.gateway.reads.last().success(f.snapshot(session()))
            assertTrue(f.repository.state.joined)
        }
        assertTrue(f.gateway.participations.all {it.joined})
        f.repository.close()
    }

    @Test fun participationThisVehicleNoLongerPlaysIsReleased() {
        val f=Fixture()
        f.open(session(count=2,joined=true))
        assertFalse(f.repository.state.joined)
        assertEquals(Participation(sessionId,sha,false,f.gateway.participations.single().response),f.gateway.participations.single())
        f.repository.refresh();f.gateway.reads.last().success(f.snapshot(session(count=2,joined=true)))
        assertEquals(1,f.gateway.participations.size)
        f.repository.close()
    }

    @Test fun connectionLossWhileJoinedKeepsPlayingAndReconnects() {
        // 연결 일시 무효화는 화면 이탈이 아니다. 재생을 유지하고 다시 연결해 같은 세션을 이어 확인한다.
        val f=Fixture()
        val startAt=f.timer.elapsedMs+1_000_000-1000
        f.open(session(ListenTogetherPhase.PLAYING,4,2,joined=false,startAt=startAt))
        val playing=session(ListenTogetherPhase.PLAYING,5,3,startAt=startAt)
        f.join(playing)
        assertEquals(listOf(1000L),f.player.plays)
        f.gateway.observer.onConnectionLost()
        assertTrue(f.repository.state.joined)
        assertTrue(f.player.playing)
        assertFalse(f.player.closed)
        assertEquals(1,f.gateways.size)
        f.timer.advance(ListenTogetherRepository.HEARTBEAT_MS)
        assertEquals(2,f.gateways.size)
        f.gateway.opened();f.gateway.reads.last().success(f.snapshot(playing))
        f.answered=f.gateway.reads.size
        f.confirmed(10_000,playing)
        assertTrue(f.repository.state.joined)
        assertEquals(1,f.players.size)
        assertEquals(listOf(1000L),f.player.plays)
        assertTrue(f.gateway.participations.isEmpty())
        f.repository.close()
    }

    @Test fun connectionThatStaysLostStopsAtTheConfirmationBound() {
        val f=Fixture()
        f.open();f.join(session())
        f.gateway.observer.onInvalidated()
        f.timer.advance(ListenTogetherRepository.HEARTBEAT_MS)
        // 다시 연 연결도 곧바로 끊긴다.
        f.gateway.observer.onConnectionLost()
        assertTrue(f.repository.state.joined)
        f.timer.advance(ListenTogetherRepository.CONFIRMATION_TIMEOUT_MS)
        assertFalse(f.repository.state.joined)
        assertEquals(ListenTogetherRepository.NOTICE_CONNECTION,f.repository.state.notice)
        assertTrue(f.player.closed)
        f.repository.close()
    }

    @Test fun reconnectingToADifferentBoundaryStopsAtOnce() {
        val f=Fixture()
        f.open();f.join(session())
        f.gateway.observer.onInvalidated()
        f.timer.advance(ListenTogetherRepository.HEARTBEAT_MS)
        f.gateway.closed=true;f.gateway.opened()
        assertFalse(f.repository.state.joined)
        assertEquals(ListenTogetherRepository.NOTICE_CONNECTION,f.repository.state.notice)
        assertTrue(f.player.closed)
        f.repository.close()
    }

    @Test fun connectionLossBeforeJoiningShowsNoStopNotice() {
        // 참여하지 않은 차는 멈춘 재생이 없으므로 "재생을 멈췄어요" 안내를 띄우지 않는다.
        val f=Fixture()
        f.open(session(count=1,joined=false))
        f.gateway.observer.onInvalidated()
        assertNull(f.repository.state.notice)
        f.gateway.opened();f.gateway.reads.last().success(f.snapshot(session(count=1,joined=false)))
        f.gateway.observer.onConnectionLost()
        assertNull(f.repository.state.notice)
        // 다시 연 연결이 다른 경계에 있거나 읽기가 권한 오류로 끝나도 마찬가지다.
        f.gateway.closed=true;f.gateway.opened()
        assertNull(f.repository.state.notice)
        f.repository.setEnvironment(true,true,true,true)
        f.gateway.opened();f.gateway.reads.last().failure(NativeSocialFailure(NativeSocialFailure.Kind.FORBIDDEN))
        assertFalse(f.repository.state.offered)
        assertNull(f.repository.state.notice)
        assertFalse(f.repository.state.joined)
        assertTrue(f.players.isEmpty())
        f.repository.close()
    }

    @Test fun invalidationAfterLeavingDoesNotReportAStop() {
        val f=Fixture()
        f.open();f.join(session())
        f.repository.leave()
        f.gateway.participations.last().response.success(f.snapshot(session(revision=2,joined=false)))
        f.gateway.observer.onInvalidated()
        assertNull(f.repository.state.notice)
        f.repository.close()
    }

    @Test fun drivingRestrictionOrLeavingScreenStopsAndLeaves() {
        val f=Fixture()
        f.open();f.join(session())
        f.repository.setEnvironment(true,true,true,false)
        assertFalse(f.repository.state.joined)
        assertEquals(ListenTogetherRepository.NOTICE_RESTRICTED,f.repository.state.notice)
        assertFalse(f.gateway.participations.last().joined)
        f.repository.setEnvironment(true,true,true,true)
        f.join(session(revision=4))
        f.repository.setEnvironment(false,false,true,true)
        assertFalse(f.gateway.participations.last().joined)
        assertTrue(f.gateway.closed)
        assertFalse(f.repository.state.offered)
        f.repository.close()
    }

    @Test fun permanentFocusLossOrErrorLeavesThisVehicleOnly() {
        val f=Fixture()
        f.open();f.join(session())
        f.player.listener!!.onStoppedBySystem()
        assertFalse(f.repository.state.joined)
        assertEquals(ListenTogetherRepository.NOTICE_FOCUS,f.repository.state.notice)
        assertEquals(Participation(sessionId,sha,false,f.gateway.participations.last().response),f.gateway.participations.last())
        assertTrue(f.gateway.ends.isEmpty())
        f.repository.close()
    }

    @Test fun staleRevisionNeverRollsBackScreen() {
        val f=Fixture()
        f.open(session(revision=5,count=3,joined=false))
        f.repository.refresh();f.gateway.reads.last().success(f.snapshot(session(revision=4,count=1,joined=false)))
        assertEquals(3,f.repository.state.session!!.deviceCount)
        f.repository.close()
    }

    @Test fun startIsNotCancelledByALaterLeave() {
        val f=Fixture()
        f.open(session(count=1,joined=false),host=true)
        f.repository.join()
        f.gateway.participations.last().response.success(f.snapshot(session(revision=2,count=2),host=true))
        f.repository.start()
        val start=f.gateway.starts.single().second
        f.repository.leave()
        assertFalse(start.cancelled)
        assertFalse(f.gateway.participations.last().joined)
        // Both writes go out in order; only the newer one's answer reaches the screen.
        start.success(f.snapshot(session(ListenTogetherPhase.PLAYING,3,2,startAt=f.timer.elapsedMs+1_000_000+3000),host=true))
        f.gateway.participations.last().response.success(f.snapshot(session(ListenTogetherPhase.PLAYING,4,1,joined=false,
            startAt=f.timer.elapsedMs+1_000_000+3000),host=true))
        assertFalse(f.repository.state.joined)
        assertFalse(f.repository.state.busy)
        assertEquals(4L,f.repository.state.session!!.revision)
        f.repository.close()
    }

    @Test fun readAnsweredDuringAWriteStillConfirmsPresence() {
        val f=Fixture()
        f.open(session(count=1,joined=false),host=true)
        f.repository.join()
        f.gateway.participations.last().response.success(f.snapshot(session(revision=2,count=2),host=true))
        f.timer.advance(ListenTogetherRepository.HEARTBEAT_MS)
        val inFlight=f.gateway.reads.last()
        f.repository.start()
        val start=f.gateway.starts.single().second
        f.timer.advance(ListenTogetherRepository.CONFIRMATION_TIMEOUT_MS-ListenTogetherRepository.HEARTBEAT_MS-500)
        inFlight.success(f.snapshot(session(revision=2,count=2),host=true))
        f.timer.advance(1000)
        assertTrue(f.repository.state.joined)
        assertFalse(start.cancelled)
        f.repository.close()
    }

    @Test fun codecIsStrict() {
        val ok=JSONObject("""{"tripId":"$trip","available":true,"serverTimeMs":5,"host":false,"minimumDevices":2,
            "track":{"id":"wegoh-demo-01","version":1,"sha256":"$sha","durationMs":48000},
            "session":{"id":"$sessionId","revision":2,"state":"playing","deviceCount":2,"joined":true,"startAtMs":9,"endedReason":null}}""")
        val parsed=NativeListenTogetherCodec.snapshot(ok,trip)
        assertEquals(ListenTogetherPhase.PLAYING,parsed.session!!.phase)
        assertEquals(9L,parsed.session!!.startAtMs)
        for(broken in listOf(JSONObject(ok.toString()).put("extra",1),JSONObject(ok.toString()).put("tripId","b".repeat(32)),
            JSONObject(ok.toString()).also {it.getJSONObject("session").put("startAtMs",JSONObject.NULL)},
            JSONObject(ok.toString()).put("available",false),
            JSONObject(ok.toString()).also {it.getJSONObject("track").put("id","other")}))
            assertTrue(runCatching {NativeListenTogetherCodec.snapshot(broken,trip)}.isFailure)
        val body=NativeListenTogetherCodec.participationBody(null,sha,true)
        assertEquals(setOf("sessionId","trackSha256","joined"),body.keySet())
        assertTrue(body.isNull("sessionId") && body.getString("trackSha256")==sha && body.getBoolean("joined"))
        assertTrue(runCatching {NativeListenTogetherCodec.startBody(sessionId,0)}.isFailure)
    }
}
