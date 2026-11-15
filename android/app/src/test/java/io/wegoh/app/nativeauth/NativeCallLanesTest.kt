package io.wegoh.app.nativeauth

import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import org.junit.After
import org.junit.Assert.*
import org.junit.Test

class NativeCallLanesTest {
    private val lanes=NativeCallLanes(Executors.newSingleThreadExecutor(),Executors.newSingleThreadExecutor())
    private val release=CountDownLatch(1)

    @After fun tearDown() {release.countDown();lanes.shutdown()}

    /** The demo vehicles queued listen reads 1.6 to 5.3 s behind location, versus, music and route reads. */
    @Test fun realtimeCallIsServedWhileTheSharedWorkerIsBusy() {
        val started=CountDownLatch(1)
        lanes.execute(false) {started.countDown();release.await()}
        repeat(6) {lanes.execute(false) {release.await()}}
        assertTrue(started.await(1,TimeUnit.SECONDS))
        val served=CountDownLatch(1)
        lanes.execute(true) {served.countDown()}
        assertTrue(served.await(1,TimeUnit.SECONDS))
    }

    @Test fun realtimeCallsRunInTheOrderTheyWereMade() {
        val order=java.util.Collections.synchronizedList(mutableListOf<Int>())
        val done=CountDownLatch(5)
        repeat(5) {i->lanes.execute(true) {Thread.sleep(5);order+=i;done.countDown()}}
        assertTrue(done.await(1,TimeUnit.SECONDS))
        assertEquals(listOf(0,1,2,3,4),order)
    }

    /** Account state work requested from the realtime lane still waits for what the worker already holds. */
    @Test fun sharedWorkRunsAfterQueuedWorkAndReturnsItsResult() {
        val order=java.util.Collections.synchronizedList(mutableListOf<String>())
        val result=AtomicReference<Result<String>>()
        val done=CountDownLatch(1)
        lanes.execute(false) {release.await();order+="queued"}
        lanes.execute(true) {result.set(runCatching {lanes.onShared {order+="verify";"ok"}});done.countDown()}
        assertFalse(done.await(200,TimeUnit.MILLISECONDS))
        release.countDown()
        assertTrue(done.await(1,TimeUnit.SECONDS))
        assertEquals(listOf("queued","verify"),order)
        assertEquals("ok",result.get().getOrThrow())
    }

    @Test fun sharedWorkFailureReachesTheCaller() {
        val failure=runCatching {lanes.onShared<Unit> {throw IllegalStateException("NATIVE_ACCOUNT_CHECK")}}.exceptionOrNull()
        assertEquals("NATIVE_ACCOUNT_CHECK",(failure as IllegalStateException).message)
    }
}
