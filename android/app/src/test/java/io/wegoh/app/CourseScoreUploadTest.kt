package io.wegoh.app

import io.wegoh.app.nativeauth.DrivingScoreReport
import org.junit.Assert.*
import org.junit.Test
import java.io.Closeable

class CourseScoreUploadTest {
    private fun report(accelerations: Int=0,brakings: Int=0)=CourseDrivingResult(accelerations,brakings,measuredMillis=1000).report()
    @Test fun unchangedSpeedSamplesAndCountChangesAtZeroDoNotUploadAgain() {
        val upload=CourseScoreUploads();val sent=mutableListOf<DrivingScoreReport>()
        val send: (DrivingScoreReport,(Result<Unit>)->Unit)->Closeable={value,reply->sent+=value;reply(Result.success(Unit));Closeable {}}
        repeat(100) {upload.update("a",report(),send)}
        assertEquals(1,sent.size)
        upload.update("a",report(20),send)
        upload.update("a",report(21),send)
        assertEquals(listOf(100,0),sent.map {it.score})
        assertEquals(20,sent.last().accelerations)
        assertEquals(21,report(21).accelerations)
    }
    @Test fun changedScoresCoalesceWhileARequestIsInFlightAndFailuresWaitForTheNextChange() {
        val upload=CourseScoreUploads();val sent=mutableListOf<DrivingScoreReport>();val replies=ArrayDeque<(Result<Unit>)->Unit>()
        val send: (DrivingScoreReport,(Result<Unit>)->Unit)->Closeable={value,reply->sent+=value;replies+=reply;Closeable {}}
        upload.update("a",report(),send)
        upload.update("a",report(1),send)
        upload.update("a",report(2),send)
        assertEquals(listOf(100),sent.map {it.score})
        replies.removeFirst()(Result.failure(IllegalStateException()))
        assertEquals(listOf(100,90),sent.map {it.score})
        replies.removeFirst()(Result.failure(IllegalStateException()))
        upload.update("a",report(2),send)
        assertEquals(2,sent.size)
        upload.update("a",report(3),send)
        assertEquals(listOf(100,90,85),sent.map {it.score})
    }
    @Test fun ChangingAccountOrCourseCancelsTheOldRequestAndIgnoresItsCallback() {
        val upload=CourseScoreUploads();val sent=mutableListOf<Int?>();val replies=ArrayDeque<(Result<Unit>)->Unit>();var closed=0
        val send: (DrivingScoreReport,(Result<Unit>)->Unit)->Closeable={value,reply->sent+=value.score;replies+=reply;Closeable {closed++}}
        upload.update("account-a:course-a",report(),send)
        upload.update("account-a:course-a",report(1),send)
        upload.update("account-b:course-a",report(),send)
        replies.removeFirst()(Result.success(Unit))
        assertEquals(listOf(100,100),sent)
        assertEquals(1,closed)
        upload.clear()
        replies.removeFirst()(Result.success(Unit))
        assertEquals(2,sent.size)
        assertEquals(2,closed)
    }
    @Test fun wireBodyHasOnlyScoreCountsAndFlagsWithoutRawSpeedOrTimeSamples() {
        val raw=CourseDrivingResult(1,1,measuredMillis=12345,interrupted=true).report(final=true).body()
        assertEquals(setOf("drivingScore"),raw.keys().asSequence().toSet())
        val value=raw.getJSONObject("drivingScore")
        assertEquals(setOf("score","accelerations","brakings","measurable","final"),value.keys().asSequence().toSet())
        assertEquals(90,value.getInt("score"));assertTrue(value.getBoolean("measurable"));assertTrue(value.getBoolean("final"))
        val unavailable=CourseDrivingResult().report().body().getJSONObject("drivingScore")
        assertTrue(unavailable.isNull("score"));assertFalse(unavailable.getBoolean("measurable"))
        assertTrue(runCatching {DrivingScoreReport(100,1,0,true,false)}.isFailure)
    }
}
