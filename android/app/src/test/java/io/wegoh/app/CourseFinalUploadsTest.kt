package io.wegoh.app

import io.wegoh.app.nativeauth.DrivingScoreReport
import io.wegoh.app.nativeauth.ScoreReportAuthority
import java.io.Closeable
import org.junit.Assert.*
import org.junit.Test

class CourseFinalUploadsTest {
    private val legacy=ScoreReportAuthority("device","grant")
    private val current=legacy.copy()
    private val report=DrivingScoreReport(90,1,1,true,true)
    @Test fun sameDeviceDoesNotResendButAChangedGrantOrDeviceDoes() {
        val uploads=CourseFinalUploads();val calls=mutableListOf<DrivingScoreReport>()
        fun submit(authority: ScoreReportAuthority,key: String="trip/car/course/v1")=uploads.submit(key,authority,report,
            send={reply->calls+=report;reply(Result.success(Unit));Closeable {}},onSuccess={})
        submit(legacy);submit(legacy)
        assertEquals(1,calls.size)
        submit(current);submit(current)
        assertEquals(listOf(report),calls)
        submit(current.copy(deviceId="other-device"));submit(current.copy(grantId="other-grant"))
        submit(current,"another-trip/car/course/v1");submit(current,"trip/another-car/course/v1")
        assertEquals(5,calls.size)
    }
    @Test fun aCancelledAuthorityCannotAcknowledgeTheNewFinalDelivery() {
        val uploads=CourseFinalUploads();val replies=mutableListOf<(Result<Unit>)->Unit>();var acknowledged=0
        fun submit(authority: ScoreReportAuthority)=uploads.submit("key",authority,report,
            send={reply->replies+=reply;Closeable {}},onSuccess={acknowledged++})
        submit(legacy);uploads.cancel();submit(current)
        replies[0](Result.success(Unit));assertEquals(0,acknowledged)
        replies[1](Result.success(Unit));assertEquals(1,acknowledged)
        submit(current);assertEquals(2,replies.size)
    }
    @Test fun failedFinalWaitsForExplicitRetryAndKeepsTheSamePayload() {
        val uploads=CourseFinalUploads();val replies=mutableListOf<(Result<Unit>)->Unit>();var calls=0
        fun submit()=uploads.submit("key",current,report,
            send={reply->calls++;replies+=reply;Closeable {}},onSuccess={})
        submit();replies.single()(Result.failure(java.io.IOException()))
        repeat(4) {submit()};assertEquals(1,calls)
        uploads.retryFailures();submit();assertEquals(2,calls)
        replies.last()(Result.success(Unit));uploads.retryFailures();submit();assertEquals(2,calls)
    }
    @Test fun queuedFinalsAreSerializedAndAcknowledgedWithoutRepeatingSuccessfulPosts() {
        val uploads=CourseFinalUploads();val replies=mutableListOf<(Result<Unit>)->Unit>();var completed=0
        fun submit(key: String)=uploads.submit(key,current,report,
            {reply->replies+=reply;Closeable {}},{completed++})
        submit("first");submit("second");assertEquals(1,replies.size)
        replies[0](Result.success(Unit));assertEquals(2,replies.size)
        replies[1](Result.success(Unit));assertEquals(2,completed)
        submit("first");submit("second");assertEquals(2,replies.size)
    }
}
