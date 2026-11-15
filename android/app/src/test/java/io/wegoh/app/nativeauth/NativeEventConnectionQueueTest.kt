package io.wegoh.app.nativeauth

import java.io.Closeable
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import org.junit.Assert.*
import org.junit.Test

class NativeEventConnectionQueueTest {
    @Test fun blockedSocketHandshakeDoesNotBlockHttpOwnerAndAdoptsOnOwner() {
        val owner=Executors.newSingleThreadExecutor {Thread(it,"http-owner")}
        val network=Executors.newSingleThreadExecutor {Thread(it,"event-network")}
        val started=CountDownLatch(1);val release=CountDownLatch(1);val adopted=CountDownLatch(1)
        val preparation=AtomicReference<String>();val completion=AtomicReference<String>()
        try {
            openNativeEventConnection(owner,network,prepare={
                preparation.set(Thread.currentThread().name)
                val connect: ()->Closeable={started.countDown();check(release.await(3,TimeUnit.SECONDS));Closeable {}}
                connect
            },complete={assertTrue(it.isSuccess);completion.set(Thread.currentThread().name);adopted.countDown()})
            assertTrue(started.await(2,TimeUnit.SECONDS))
            val post=CountDownLatch(1)
            owner.execute {post.countDown()}
            assertTrue("HTTP owner must run before socket handshake finishes",post.await(1,TimeUnit.SECONDS))
            release.countDown()
            assertTrue(adopted.await(2,TimeUnit.SECONDS))
            assertEquals("http-owner",preparation.get())
            assertEquals("http-owner",completion.get())
        } finally {release.countDown();owner.shutdownNow();network.shutdownNow()}
    }
    @Test fun failedAuthorizationNeverOpensSocket() {
        val connected=AtomicBoolean(false)
        var failure: Throwable?=null
        val immediate=java.util.concurrent.Executor {it.run()}
        val network=java.util.concurrent.Executor {connected.set(true);it.run()}
        openNativeEventConnection(immediate,network,prepare={throw IllegalStateException("not authorized")},
            complete={failure=it.exceptionOrNull()})
        assertFalse(connected.get());assertTrue(failure is IllegalStateException)
    }
    @Test fun rejectedNetworkQueueCompletesWithFailure() {
        var failed=false
        val immediate=java.util.concurrent.Executor {it.run()}
        val rejected=java.util.concurrent.Executor {throw java.util.concurrent.RejectedExecutionException()}
        openNativeEventConnection(immediate,rejected,prepare={{Closeable {}}},complete={failed=it.isFailure})
        assertTrue(failed)
    }
    @Test fun ownerShutdownDuringConnectClosesUnadoptedSocket() {
        val calls=java.util.concurrent.atomic.AtomicInteger()
        val closed=AtomicBoolean(false)
        val owner=java.util.concurrent.Executor {if(calls.incrementAndGet()==1)it.run() else throw java.util.concurrent.RejectedExecutionException()}
        val immediate=java.util.concurrent.Executor {it.run()}
        openNativeEventConnection(owner,immediate,prepare={{Closeable {closed.set(true)}}},complete={fail("Closed owner must not receive callbacks")})
        assertTrue(closed.get())
    }
}
