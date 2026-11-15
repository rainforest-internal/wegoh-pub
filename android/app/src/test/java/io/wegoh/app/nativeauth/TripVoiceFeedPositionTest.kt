package io.wegoh.app.nativeauth

import org.junit.Assert.*
import org.junit.Test

/** 연결 교체·일시 무효화 뒤에도 같은 계정 경계 안이면 음성 조회 위치를 이어 받는다. */
class TripVoiceFeedPositionTest {
    private fun clip(n: Int)=NativeVoiceClipMetadata("%032x".format(n),"team-"+"a".repeat(40),n.toLong(),1000)
    private val cursor="b".repeat(32)+":7"

    @Test fun reconnectWithinSameEpochKeepsCursorAndPendingClips() {
        val position=TripVoiceFeedPosition()
        position.advanced(cursor,epoch=3,now=10_000)
        position.inbox.addLast(clip(1))
        // 기능 권한 무효화 뒤 다시 연결: 1초 폴링이 끊긴 몇 초 뒤.
        assertTrue(position.resumeOrClear(epoch=3,now=14_000))
        assertEquals(cursor,position.cursor)
        assertEquals(listOf(clip(1)),position.inbox.toList())
    }

    @Test fun interruptedPlaybackIsRequeuedFirstWithoutDuplicates() {
        val position=TripVoiceFeedPosition()
        position.inbox.addLast(clip(2))
        position.requeue(clip(1))
        position.requeue(clip(1))
        assertEquals(listOf(clip(1),clip(2)),position.inbox.toList())
        repeat(4) {position.requeue(clip(10+it))}
        assertEquals(TripVoiceFeedPosition.INBOX_LIMIT,position.inbox.size)
        assertEquals(clip(13),position.inbox.first())
    }

    @Test fun accountBoundaryChangeStartsFromCurrentPosition() {
        val position=TripVoiceFeedPosition()
        position.advanced(cursor,epoch=3,now=10_000)
        position.inbox.addLast(clip(1))
        // 계정 변경·잠금·연결 해제는 VehicleConnection epoch를 올린다.
        assertFalse(position.resumeOrClear(epoch=4,now=11_000))
        assertNull(position.cursor)
        assertTrue(position.inbox.isEmpty())
    }

    @Test fun neverResumesBeyondServerRetention() {
        val position=TripVoiceFeedPosition()
        position.advanced(cursor,epoch=3,now=10_000)
        assertTrue(position.resumable(epoch=3,now=10_000+VOICE_CLIP_RETENTION_MS))
        assertFalse(position.resumeOrClear(epoch=3,now=10_001+VOICE_CLIP_RETENTION_MS))
        assertNull(position.cursor)
        assertEquals(90_000L,VOICE_CLIP_RETENTION_MS)
    }

    @Test fun clockGoingBackwardsOrNoCursorIsNotResumable() {
        val position=TripVoiceFeedPosition()
        assertFalse(position.resumable(epoch=0,now=0))
        position.advanced(cursor,epoch=3,now=10_000)
        assertFalse(position.resumable(epoch=3,now=9_999))
    }

    @Test fun participationBoundaryClearsEverything() {
        val position=TripVoiceFeedPosition()
        position.advanced(cursor,epoch=3,now=10_000)
        position.inbox.addLast(clip(1))
        // 참여 해제·재가입(revision·가입 시각 변경)은 호출부가 clear한다.
        position.clear()
        assertNull(position.cursor)
        assertTrue(position.inbox.isEmpty())
        assertFalse(position.resumable(epoch=3,now=10_000))
    }
}
