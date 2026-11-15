package io.wegoh.app.nativeauth

import java.io.ByteArrayOutputStream
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import org.junit.Assert.*
import org.junit.Test

class NativeMutationGateTest {
    private fun pendingWrite(cancel: (NativeMutationGate,NativeMutationGate.Permit,AtomicBoolean)->Unit) {
        val gate=NativeMutationGate().also {it.setAllowed(true)}
        val current=AtomicBoolean(true)
        val attempted=AtomicInteger()
        val permit=gate.permit({current.get()},{attempted.incrementAndGet()})
        val connecting=CountDownLatch(1);val release=CountDownLatch(1)
        val body=ByteArrayOutputStream();val disconnected=AtomicInteger()
        val failed=AtomicBoolean(false)
        val worker=Thread {
            try {permit.write("body".toByteArray(),{
                connecting.countDown();check(release.await(3,TimeUnit.SECONDS));body
            },{disconnected.incrementAndGet()})} catch(_: java.io.IOException) {failed.set(true)}
        }
        worker.start()
        try {
            assertTrue(connecting.await(3,TimeUnit.SECONDS))
            cancel(gate,permit,current)
        } finally {release.countDown();worker.join(3000);permit.close()}
        assertFalse(worker.isAlive)
        assertTrue(failed.get())
        assertEquals(0,body.size())
        assertEquals(0,attempted.get())
        assertTrue(disconnected.get()>0)
    }
    @Test fun carUxLockWhileConnectingDisconnectsAndSendsNoBody()=pendingWrite {gate,_,_->gate.setAllowed(false)}
    @Test fun unlockDoesNotReviveTheOldWrite()=pendingWrite {gate,_,_->gate.setAllowed(false);gate.setAllowed(true)}
    @Test fun cancelledHttpCallCannotWriteAfterConnectionReturns()=pendingWrite {_,permit,_->permit.close()}
    @Test fun authorityIsCheckedAgainImmediatelyBeforeTheBody()=pendingWrite {_,_,current->current.set(false)}
    @Test fun allowedWriteIsSentOnce() {
        val gate=NativeMutationGate().also {it.setAllowed(true)}
        val body=ByteArrayOutputStream();var attempted=0
        gate.permit({true},{attempted++}).use {it.write(byteArrayOf(1,2,3),{body},{fail("unexpected disconnect")})}
        assertArrayEquals(byteArrayOf(1,2,3),body.toByteArray())
        assertEquals(1,attempted)
    }
}
