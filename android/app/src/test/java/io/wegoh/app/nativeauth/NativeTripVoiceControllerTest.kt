package io.wegoh.app.nativeauth

import io.wegoh.app.nativeauth.NativeTripVoiceController.Phase
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.Closeable
import java.time.Instant

/**
 * 기능 권한 무효화(모든 소셜 클라이언트 종료)와 여행 다시 읽기가 같은 순간 겹칠 때의 controller 흐름.
 * 가짜 클라이언트는 실제 [NativeSocialClient]처럼 READY 전 요청을 UNAVAILABLE(client_not_ready)로 실패시킨다.
 */
class NativeTripVoiceControllerTest {
    private val trip="c".repeat(32)
    private val speaker="team-"+"a".repeat(40)
    private fun cursor(n: Int)="d".repeat(32)+":$n"
    private fun clip(n: Int)=NativeVoiceClipMetadata("%032x".format(n),speaker,n.toLong(),1000)
    private fun participation(on: Boolean=true)=VoiceTripParticipation(trip,on,Instant.parse("2026-11-15T00:00:00Z"),1)
    private val permission=VoiceRoomPermission(trip,1,1,Instant.parse("2026-11-15T00:00:00Z"),Instant.parse("2100-01-01T00:00:00Z"),
        VoiceDirection.entries.toSet())

    private class Pending(val callback: (Result<Any?>)->Unit) { var closed=false }
    private inner class FakeClient: TripVoiceClient {
        var status=NativeSocialClient.State.UNOPENED
        lateinit var observer: NativeSocialObserver
        private var opened: ((Result<Unit>)->Unit)?=null
        val requests=mutableListOf<Pending>()
        val live get()=requests.filter {!it.closed}
        override fun status()=status
        override fun open(observer: NativeSocialObserver,callback: (Result<Unit>)->Unit) {
            this.observer=observer;opened=callback;status=NativeSocialClient.State.OPENING
        }
        fun ready() {status=NativeSocialClient.State.READY;opened!!(Result.success(Unit));opened=null}
        @Suppress("UNCHECKED_CAST")
        override fun <T> executeVoiceRequest(request: NativeSocialRequest<T>,callback: (Result<T>)->Unit): Closeable {
            val pending=Pending(callback as (Result<Any?>)->Unit)
            if(status!=NativeSocialClient.State.READY) {
                // NativeSocialClient.call: "call skipped reason=client_not_ready" 뒤 UNAVAILABLE을 비동기로 돌려준다.
                host.post {if(!pending.closed)callback(Result.failure(NativeSocialFailure(NativeSocialFailure.Kind.UNAVAILABLE)))}
                return Closeable {pending.closed=true}
            }
            requests+=pending
            return Closeable {pending.closed=true}
        }
        fun succeed(value: Any?) {val next=live.first();next.closed=true;next.callback(Result.success(value))}
        fun fail(kind: NativeSocialFailure.Kind) {val next=live.first();next.closed=true;next.callback(Result.failure(NativeSocialFailure(kind)))}
        fun feed(cursor: String,vararg clips: NativeVoiceClipMetadata)=succeed(Triple(permission,NativeVoiceClipFeed(cursor,clips.toList()),emptySet<String>()))
        override fun close() {status=NativeSocialClient.State.CLOSED}
    }
    private inner class FakeHost: TripVoiceHost {
        var now=1_000_000L
        val clients=mutableListOf<FakeClient>()
        private val queue=mutableListOf<Pair<Long,Runnable>>()
        override fun onMainThread()=true
        override fun post(action: Runnable) {queue+=now to action}
        override fun postDelayed(action: Runnable,delayMs: Long) {queue+=(now+delayMs) to action}
        override fun removeCallbacks(action: Runnable) {queue.removeAll {it.second===action}}
        /** 시계를 [ms]만큼 옮기며 그때까지 예약된 작업을 순서대로 돌린다. */
        fun advance(ms: Long=0) {
            val until=now+ms
            while(true) {
                val next=queue.filter {it.first<=until}.minByOrNull {it.first} ?: break
                queue.remove(next);now=maxOf(now,next.first);next.second.run()
            }
            now=until
        }
        override fun elapsedRealtime()=now
        override fun socialNow()=Instant.parse("2026-11-15T01:00:00Z").toEpochMilli()
        override fun dataEpoch()=7L
        override fun reserveVoice()=Closeable {}
        override fun tripSocial()=FakeClient().also {clients+=it}
        override fun voiceAudioBackend()=object: NativeVoiceAudioBackend {
            override fun captureSupported()=false
            override fun microphoneGranted()=false
            override fun focus(lost: ()->Unit): Closeable?=null
            override fun capture(invalidated: ()->Unit): NativeVoiceCapture=error("unused")
            override fun playback(): NativeVoicePlayback=error("unused")
        }
        override fun tripPermission(bytes: ByteArray,functional: FunctionalPermissions,tripId: String)=permission
        override fun warn(message: String) {}
    }
    private val host=FakeHost()
    private val phases=mutableListOf<Phase>()
    private val voice=NativeTripVoiceController(host,trip,"Synthetic trip") {phases+=it.phase}
    private val client get()=host.clients.last()

    /** 연결 → 참여 확인 → 첫 조회까지 끝낸 '녹음 가능' 상태. */
    private fun listening(vararg clips: NativeVoiceClipMetadata) {
        voice.updateSafety(true,true);voice.start()
        client.ready();client.succeed(participation());client.feed(cursor(1),*clips)
        host.advance()
        assertEquals(if(clips.isEmpty())Phase.LISTENING else Phase.HEARING,phases.last())
    }
    /** invalidateFunctionalPermissions: 모든 소셜 클라이언트가 함께 끝나고 TripsRepository가 다시 읽기를 시작한다. */
    private fun invalidateWithTripReload() {
        client.close();client.observer.onInvalidated()
        voice.setTripReady(false)
    }

    @Test fun tripReloadFinishingBeforeNewClientIsReadyDoesNotQueryOrFlashUnavailable() {
        listening()
        invalidateWithTripReload()
        assertEquals(2,host.clients.size)
        val before=phases.size
        voice.setTripReady(true)
        host.advance(3_000)
        assertFalse("준비 전 새 클라이언트로 조회해 깜빡임: ${phases.drop(before)}",Phase.UNAVAILABLE in phases.drop(before))
        assertTrue(client.requests.isEmpty())
        // 새 클라이언트가 참여를 확인한 뒤에만 남긴 위치로 조회한다.
        client.ready()
        assertEquals(1,client.live.size)
        client.succeed(participation())
        assertEquals(1,client.live.size)
        client.feed(cursor(2))
        host.advance()
        assertEquals(Phase.LISTENING,phases.last())
        assertFalse(Phase.UNAVAILABLE in phases.drop(before))
    }

    @Test fun invalidationBeforeParticipationIsKnownKeepsLoading() {
        voice.updateSafety(true,true);voice.start()
        client.ready()
        assertEquals(Phase.LOADING,phases.last())
        client.close();client.observer.onInvalidated()
        assertEquals("참여 확인 전 무효화가 '녹음 가능'을 보여 줌: $phases",listOf(Phase.LOADING),phases.distinct())
        assertFalse(voice.press())
        client.ready();client.succeed(participation());client.feed(cursor(1))
        assertEquals(Phase.LISTENING,phases.last())
    }

    @Test fun failedFirstFeedAfterReconnectClearsHeldPress() {
        listening()
        client.close();client.observer.onInvalidated()
        assertTrue(voice.press())
        assertEquals(Phase.REQUESTING,phases.last())
        client.ready();client.succeed(participation())
        client.fail(NativeSocialFailure.Kind.UNAVAILABLE)
        assertEquals(Phase.UNAVAILABLE,phases.last())
        // 1초 뒤 다시 조회해 회복하면 손을 뗀 적이 없어도 새로 누르고 받을 음성을 재생할 수 있어야 한다.
        host.advance(1_000)
        client.feed(cursor(2),clip(1))
        assertEquals(Phase.HEARING,phases.last())
        client.fail(NativeSocialFailure.Kind.INVALID_RESPONSE)
        assertEquals(Phase.LISTENING,phases.last())
        assertTrue("실패 뒤 held가 남아 새 누름이 막힘",voice.press())
        assertEquals(Phase.REQUESTING,phases.last())
    }

    @Test fun tripReadyAfterRetentionWindowDropsStalePosition() {
        listening(clip(1))
        assertEquals(Phase.HEARING,phases.last())
        voice.setTripReady(false)
        assertEquals(Phase.LISTENING,phases.last())
        host.advance(VOICE_CLIP_RETENTION_MS+1_000)
        val before=client.requests.size
        voice.setTripReady(true)
        // 90초가 지난 위치·받을 목록은 버리고 처음 조회처럼 현재 위치부터 받는다: 조회만 하고 지난 음성은 재생하지 않는다.
        assertEquals("오래된 목록의 음성을 재생하려 함",1,client.requests.size-before)
        assertEquals(Phase.LISTENING,phases.last())
    }

    @Test fun tripReadyWithinRetentionWindowResumesPendingClip() {
        listening(clip(1))
        voice.setTripReady(false)
        host.advance(10_000)
        val before=client.requests.size
        voice.setTripReady(true)
        assertEquals(2,client.requests.size-before)
        assertEquals(Phase.HEARING,phases.last())
    }
}
