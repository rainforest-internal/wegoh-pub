package io.wegoh.app

import io.wegoh.app.nativeauth.VehicleConnection
import org.junit.Assert.*
import org.junit.Test

class VehicleRemoteHistoryTest {
    @Test fun pendingRequestAdvancesToOneCompletedRowAndStalePollCannotResurrectIt() {
        val history=newHistory {1000L}
        val token=history.captureToken()
        val queued=VehicleRemoteEntry("사용자F","공조",VehicleRemoteResult.QUEUED,900,false,"request-1",5000)
        history.pending(token,listOf(queued))
        assertEquals("대기 중",history.entries.single().resultLabel)
        history.advance(token,"request-1","사용자F","공조 켜기",VehicleRemoteResult.PROCESSING,4000)
        assertEquals(1,history.entries.size);assertEquals("처리 중",history.entries.single().resultLabel)
        history.record(token,"사용자F","공조 켜기",VehicleRemoteResult.APPLIED,requestId="request-1")
        assertEquals(1,history.entries.size);assertFalse(history.entries.single().pending)
        history.pending(token,listOf(queued))
        assertEquals(1,history.entries.size);assertEquals("적용됨",history.entries.single().resultLabel)
    }
    @Test fun pendingRowsDoNotDisplaceTheFiveCompletedResultsAndExpireLocally() {
        var now=1000L
        val history=newHistory {now}
        repeat(7) {history.recordCurrent("친구","완료 $it",VehicleRemoteResult.APPLIED)}
        val token=history.captureToken()
        history.pending(token,listOf(VehicleRemoteEntry("친구","새 요청",VehicleRemoteResult.QUEUED,1000,false,"pending",2000)))
        assertEquals(6,history.entries.size);assertTrue(history.entries.first().pending)
        now=2000
        assertEquals(5,history.entries.size)
        history.clearPending(token);assertEquals(5,history.entries.size)
    }
    @Test fun pendingCallbacksFromOldAccountCannotWriteIntoTheNewAccount() {
        var boundary=boundaryA
        val history=VehicleRemoteHistory({0L}) {boundary}
        val old=history.captureToken()
        boundary=boundaryB
        val current=history.captureToken()
        val pending=VehicleRemoteEntry("친구","새 요청",VehicleRemoteResult.QUEUED,0,false,"id",5000)
        history.pending(current,listOf(pending));history.clearPending(old)
        history.pending(old,emptyList());history.advance(old,"old","이전 친구","조작",VehicleRemoteResult.PROCESSING,5000)
        assertEquals(listOf("id"),history.entriesFor(boundaryB).map {it.requestId})
    }
    @Test fun inboxPresentationUsesOnlySupportedFriendRowsAndServerLifetime() {
        val epoch=1_700_000_000_000L
        fun row(id: String,stage: String,friend: Boolean=true,action: String="hvac.fan",revision: Long=1)=
            io.wegoh.app.nativeauth.VehicleClimateNativeTransport.Request(id,action,revision,friend,stage,epoch-1000,"sender",epoch+2000)
        val inbox=io.wegoh.app.nativeauth.VehicleClimateNativeTransport.Inbox(listOf(
            row("pending","queued"),row("running","sdk-accepted"),row("completed","state-confirmed"),
            row("room","queued",false),row("unknown","queued",action="unknown"),row("revision","queued",revision=2)),
            mapOf("hvac.fan" to 1),mapOf("hvac.fan" to "풍량"),epoch)
        val entries=vehiclePendingEntries(inbox,5000,{"친구 이름"})
        assertEquals(listOf("pending","running"),entries.map {it.requestId})
        assertEquals(listOf(VehicleRemoteResult.QUEUED,VehicleRemoteResult.PROCESSING),entries.map {it.result})
        assertEquals("친구 이름",entries.first().sender);assertEquals("풍량",entries.first().action)
        assertEquals(4000L,entries.first().completedAtElapsedMillis)
        assertTrue(entries.first().visibleAt(6999));assertFalse(entries.first().visibleAt(7000))
        assertTrue(vehiclePendingEntries(inbox,5000,{null},emptyMap()).isEmpty())
    }

    private val boundaryA=VehicleConnection.DataBoundary(1,"account-a-device-a",emptySet(),1_000_000L)
    private val boundaryB=VehicleConnection.DataBoundary(2,"account-b-device-b",emptySet(),1_000_000L)
    private fun newHistory(nowElapsedMillis: ()->Long)=VehicleRemoteHistory(nowElapsedMillis) {boundaryA}
    private val VehicleRemoteHistory.entries get()=entriesFor(boundaryA)
    private fun VehicleRemoteHistory.recordCurrent(sender: String?,action: String,result: VehicleRemoteResult,mayHaveExecuted: Boolean=false) {
        record(captureToken(),sender,action,result,mayHaveExecuted)
    }

    @Test fun claimFromAnotherRevisionCannotCaptureCurrentBoundaryToken() {
        val history=newHistory {0L}
        assertNull(history.captureToken(boundaryB.revision))
        assertNotNull(history.captureToken(boundaryA.revision))
        history.record(null,"이전 친구","공조 켜기",VehicleRemoteResult.APPLIED)
        assertTrue(history.entries.isEmpty())
    }

    @Test fun expirationHidesHistoryAndRejectsLateCompletion() {
        var wallTime=0L
        val history=VehicleRemoteHistory({0L}) {boundaryA.takeIf {wallTime<it.expiresAtMillis}}
        val token=history.captureToken()
        history.record(token,"친구","공조 켜기",VehicleRemoteResult.APPLIED)
        wallTime=boundaryA.expiresAtMillis
        assertTrue(history.entriesFor(boundaryA).isEmpty())
        history.refreshBoundary()
        assertNull(history.captureToken())
        history.record(token,"친구","공조 끄기",VehicleRemoteResult.APPLIED)
        assertTrue(history.entriesFor(boundaryA).isEmpty())
    }

    @Test fun disconnectAndAccountSwitchClearPreviousAccountCommands() {
        var boundary: VehicleConnection.DataBoundary?=boundaryA
        val history=VehicleRemoteHistory({0L}) {boundary}
        val tokenA=history.captureToken()
        history.record(tokenA,"A의 친구","공조 켜기",VehicleRemoteResult.APPLIED)
        assertEquals("A의 친구",history.entriesFor(boundaryA).single().sender)

        boundary=null
        history.refreshBoundary()
        assertTrue(history.entriesFor(null).isEmpty())
        assertTrue(history.entriesFor(boundaryA).isEmpty())

        boundary=boundaryB
        history.refreshBoundary()
        assertTrue(history.entriesFor(boundaryB).isEmpty())
        assertTrue(history.entriesFor(boundaryA).isEmpty())
        history.record(history.captureToken(),"B의 친구","공조 끄기",VehicleRemoteResult.APPLIED)
        assertEquals("B의 친구",history.entriesFor(boundaryB).single().sender)
        assertTrue(history.entriesFor(boundaryA).isEmpty())
    }

    @Test fun lateCompletionFromAccountAIsIgnoredAfterSwitchingToAccountB() {
        var boundary: VehicleConnection.DataBoundary?=boundaryA
        val history=VehicleRemoteHistory({0L}) {boundary}
        val tokenA=history.captureToken()
        boundary=null
        history.refreshBoundary()
        history.record(tokenA,"A의 친구","공조 켜기",VehicleRemoteResult.APPLIED)
        assertTrue(history.entriesFor(null).isEmpty())

        boundary=boundaryB
        val tokenB=history.captureToken()
        history.record(tokenB,"B의 친구","공조 끄기",VehicleRemoteResult.APPLIED)
        history.record(tokenA,"A의 친구","공조 켜기",VehicleRemoteResult.APPLIED)
        assertEquals(listOf("B의 친구"),history.entriesFor(boundaryB).map {it.sender})
    }

    @Test fun boundaryChangesAreCheckedBeforeRecordingEvenWithoutNotification() {
        var boundary: VehicleConnection.DataBoundary?=boundaryA
        val history=VehicleRemoteHistory({0L}) {boundary}
        val tokenA=history.captureToken()
        history.record(tokenA,"A의 친구","공조 켜기",VehicleRemoteResult.APPLIED)
        boundary=boundaryB
        assertTrue(history.entriesFor(boundaryA).isEmpty())
        assertTrue(history.entriesFor(boundaryB).isEmpty())
        history.record(tokenA,"A의 친구","공조 켜기",VehicleRemoteResult.APPLIED)
        assertTrue(history.entriesFor(boundaryB).isEmpty())
    }

    @Test fun invalidatingAndReverifyingSameBoundaryDoesNotAcceptOldCallbacks() {
        var boundary: VehicleConnection.DataBoundary?=boundaryA
        val history=VehicleRemoteHistory({0L}) {boundary}
        val oldToken=history.captureToken()
        history.record(oldToken,"이전 친구","공조 켜기",VehicleRemoteResult.APPLIED)
        boundary=null
        history.refreshBoundary()
        boundary=boundaryA
        val newToken=history.captureToken()
        assertNotSame(oldToken,newToken)
        history.record(oldToken,"이전 친구","공조 켜기",VehicleRemoteResult.APPLIED)
        assertTrue(history.entriesFor(boundaryA).isEmpty())
        history.record(newToken,"현재 친구","공조 끄기",VehicleRemoteResult.APPLIED)
        assertEquals("현재 친구",history.entriesFor(boundaryA).single().sender)
    }

    @Test fun deviceAndRevisionChangesInvalidateHistoryWithinSameAccount() {
        var boundary: VehicleConnection.DataBoundary?=boundaryA
        val history=VehicleRemoteHistory({0L}) {boundary}
        val token=history.captureToken()
        history.record(token,"친구","공조 켜기",VehicleRemoteResult.APPLIED)
        boundary=boundaryA.copy(revision=3)
        history.refreshBoundary()
        assertTrue(history.entriesFor(boundary).isEmpty())
        history.record(token,"친구","공조 켜기",VehicleRemoteResult.APPLIED)
        assertTrue(history.entriesFor(boundary).isEmpty())
        val nextToken=history.captureToken()
        history.record(nextToken,"친구","공조 끄기",VehicleRemoteResult.APPLIED)
        boundary=boundaryA.copy(storageKey="account-a-device-new")
        history.refreshBoundary()
        assertTrue(history.entriesFor(boundary).isEmpty())
    }

    @Test fun keepsOnlyFiveMostRecentCompletedCommands() {
        var now=0L
        val history=newHistory {now}
        repeat(7) {index->
            now=index*1_000L
            history.recordCurrent("친구 $index","조작 $index",VehicleRemoteResult.APPLIED)
        }
        assertEquals(listOf("조작 6","조작 5","조작 4","조작 3","조작 2"),history.entries.map {it.action})
        assertEquals(listOf(6000L,5000L,4000L,3000L,2000L),history.entries.map {it.completedAtElapsedMillis})
        assertEquals("친구 6",history.entries.first().sender)
    }

    @Test fun emptyHistoryStartsFreshAndPublishedSnapshotsStayUnchanged() {
        val history=newHistory {123L}
        assertTrue(history.entries.isEmpty())
        history.recordCurrent(" 사용자C ","공조 켜기",VehicleRemoteResult.APPLIED)
        val first=history.entries
        history.recordCurrent(null,"공조 끄기",VehicleRemoteResult.REJECTED)
        assertEquals(1,first.size)
        assertEquals("사용자C",first.single().sender)
        assertTrue(newHistory {123L}.entries.isEmpty())
    }

    @Test fun missingAndBlankNamesUseFriend() {
        val history=newHistory {0L}
        listOf(null,"","  ").forEach {history.recordCurrent(it,"실내등 켜기",VehicleRemoteResult.APPLIED)}
        assertEquals(listOf("친구","친구","친구"),history.entries.map {it.sender})
    }

    @Test fun mapsExecutionOutcomesWithoutClaimingUnconfirmedApplication() {
        val cases=listOf(
            VehicleCommandOutcome(VehicleCommandState.TARGET_CONFIRMED,mayHaveExecuted=true) to VehicleRemoteResult.APPLIED,
            VehicleCommandOutcome(VehicleCommandState.BLOCKED,VehicleFailure.DRIVING_RESTRICTED) to VehicleRemoteResult.DRIVING_BLOCKED,
            VehicleCommandOutcome(VehicleCommandState.BLOCKED,VehicleFailure.PERMISSION) to VehicleRemoteResult.REJECTED,
            VehicleCommandOutcome(VehicleCommandState.UNSUPPORTED,VehicleFailure.UNSUPPORTED_AREA) to VehicleRemoteResult.REJECTED,
            VehicleCommandOutcome(VehicleCommandState.FAILED,VehicleFailure.INVALID_VALUE) to VehicleRemoteResult.REJECTED,
            VehicleCommandOutcome(VehicleCommandState.FAILED,VehicleFailure.TIMEOUT) to VehicleRemoteResult.TIMED_OUT,
            VehicleCommandOutcome(VehicleCommandState.UNKNOWN,VehicleFailure.TIMEOUT,true) to VehicleRemoteResult.TIMED_OUT,
            VehicleCommandOutcome(VehicleCommandState.UNKNOWN,VehicleFailure.MISMATCH,true) to VehicleRemoteResult.UNKNOWN,
            VehicleCommandOutcome(VehicleCommandState.UNKNOWN,VehicleFailure.EXPIRED_AUTHORITY,true) to VehicleRemoteResult.UNKNOWN,
            VehicleCommandOutcome(VehicleCommandState.BLOCKED,VehicleFailure.DISCONNECTED) to VehicleRemoteResult.UNAVAILABLE
        )
        cases.forEach {(outcome,expected)->assertEquals(outcome.toString(),expected,vehicleRemoteResult(outcome))}
        assertEquals(VehicleRemoteResult.DRIVING_BLOCKED,vehicleRemoteResult(
            VehicleCommandOutcome(VehicleCommandState.BLOCKED,VehicleFailure.EXPIRED_AUTHORITY),drivingBlocked=true))
        assertEquals(VehicleRemoteResult.UNKNOWN,vehicleRemoteResult(
            VehicleCommandOutcome(VehicleCommandState.UNKNOWN,VehicleFailure.DRIVING_RESTRICTED,true),drivingBlocked=true))
    }

    @Test fun keepsResultAndUncertaintyWithEachEntry() {
        val history=newHistory {0L}
        history.recordCurrent(null,"공조 켜기",VehicleRemoteResult.APPLIED,true)
        history.recordCurrent(null,"공조 끄기",VehicleRemoteResult.TIMED_OUT,true)
        history.recordCurrent(null,"공조 끄기",VehicleRemoteResult.TIMED_OUT)
        assertEquals(listOf("시간 초과","시간 초과\n적용 여부 미확인","적용됨"),history.entries.map {it.resultLabel})
        assertEquals(listOf(VehicleRemoteResult.TIMED_OUT,VehicleRemoteResult.TIMED_OUT,VehicleRemoteResult.APPLIED),
            history.entries.map {it.result})
    }

    @Test fun showsElapsedMinutesAtBoundaries() {
        val history=newHistory {10_000L}
        history.recordCurrent(null,"공조 켜기",VehicleRemoteResult.APPLIED)
        val entry=history.entries.single()
        assertEquals("방금",entry.relativeTime(9_000L))
        assertEquals("방금",entry.relativeTime(69_999L))
        assertEquals("1분 전",entry.relativeTime(70_000L))
        assertEquals("12분 전",entry.relativeTime(730_000L))
    }

    @Test fun formatsEverySupportedActionInKorean() {
        val seat=VehicleSeat.ROW_1_RIGHT
        val cases=listOf(
            ClimateTarget.Celsius(seat,22f) to "조수석 설정 온도 22°C",
            ClimateTarget.Celsius(seat,22.5f) to "조수석 설정 온도 22.5°C",
            ClimateTarget.Fan(seat,2) to "조수석 바람 세기 2단계",
            ClimateTarget.GlobalPower(seat,true) to "공조 켜기",
            ClimateTarget.Ac(seat,false) to "조수석 에어컨 끄기",
            ClimateTarget.AirCleaner(seat,true) to "조수석 공기 청정 켜기",
            ClimateTarget.SeatHeat(seat,1) to "조수석 시트 열선 1단계",
            ClimateTarget.SeatVentilation(seat,0) to "조수석 시트 통풍 끄기",
            ClimateTarget.WindowPosition(VehicleWindow.ROW_1_RIGHT,30) to "조수석 창문 30%",
            ClimateTarget.CabinLight(true) to "실내등 켜기",
            ClimateTarget.ReadingLight(seat,false) to "조수석 독서등 끄기",
            ClimateTarget.AmbientLight(seat,true) to "조수석 무드등 켜기"
        )
        cases.forEach {(target,expected)->assertEquals(expected,vehicleRemoteAction(target))}
        assertEquals(TRUSTED_CLIMATE_ACTIONS.keys,cases.map {it.first.property}.toSet())
    }
}
