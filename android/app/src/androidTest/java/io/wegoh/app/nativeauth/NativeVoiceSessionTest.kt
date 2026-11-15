package io.wegoh.app.nativeauth

import android.os.SystemClock
import android.test.InstrumentationTestCase
import java.io.Closeable
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

/** Synthetic socket/backend; no account, physical microphone, vehicle input or production state. */
@Suppress("DEPRECATION")
class NativeVoiceSessionTest: InstrumentationTestCase() {
    private class Wire: NativeVoiceWire {
        var closed = false
        var requests = 0
        var releases = 0
        override fun control(control: VoiceControl): Boolean {
            if (control == VoiceControl.REQUEST) requests++
            if (control == VoiceControl.RELEASE) releases++
            return !closed
        }
        override fun frame(sequence: Long, pcm: ByteArray) = !closed
        override fun close() { closed=true }
    }
    private class Backend: NativeVoiceAudioBackend {
        var granted = true
        var loss: (() -> Unit)? = null
        val captures = AtomicInteger()
        val playbacks = AtomicInteger()
        val writes = AtomicInteger()
        val released = AtomicInteger()
        val abandoned = AtomicInteger()
        val reads = AtomicInteger()
        var holdStart = false
        var readWaitMillis = 2000L
        val starting = CountDownLatch(1)
        val continueStart = CountDownLatch(1)
        val stop = CountDownLatch(1)
        override fun captureSupported() = true
        override fun microphoneGranted() = granted
        override fun focus(lost: () -> Unit): Closeable { loss=lost; return Closeable { abandoned.incrementAndGet() } }
        override fun capture(invalidated: () -> Unit): NativeVoiceCapture {
            captures.incrementAndGet()
            return object: NativeVoiceCapture {
                override fun start() { starting.countDown(); if (holdStart) check(continueStart.await(3, TimeUnit.SECONDS)) }
                override fun read(bytes: ByteArray, offset: Int, count: Int): Int { reads.incrementAndGet(); stop.await(readWaitMillis, TimeUnit.MILLISECONDS); return -1 }
                override fun close() { released.incrementAndGet(); stop.countDown() }
            }
        }
        override fun playback(): NativeVoicePlayback {
            playbacks.incrementAndGet()
            return object: NativeVoicePlayback {
                override fun start() {}
                override fun write(bytes: ByteArray, offset: Int, count: Int): Int { writes.incrementAndGet(); return count }
                override fun close() { released.incrementAndGet() }
            }
        }
    }
    private val a = VoiceFloor("a".repeat(32), "team-"+"1".repeat(40))
    private val b = VoiceFloor("b".repeat(32), "team-"+"2".repeat(40))
    private fun session(direction: VoiceDirection, backend: Backend, authority: () -> Boolean = { true }, trip: Boolean = false,
        actor: String? = null): Pair<NativeVoiceSession, Wire> {
        val own = NativeVoiceSession(direction, backend, authority, object: NativeVoiceSessionObserver {}, trip, { actor })
        own.updateSafety(NativeVoiceAudioSafety(true, true))
        val wire = Wire(); own.attach(wire); assertTrue(own.adopt())
        return own to wire
    }
    private fun eventually(predicate: () -> Boolean) {
        val end=SystemClock.elapsedRealtime()+2000
        while (!predicate() && SystemClock.elapsedRealtime()<end) Thread.sleep(5)
        assertTrue(predicate())
    }
    fun testExplicitDirectionAndServerGrantBeforeCapture() {
        val backend=Backend(); val (own,wire)=session(VoiceDirection.TRANSMIT,backend)
        try {
            own.listener.onEvent(VoiceServerEvent.Ready(null))
            assertEquals(NativeVoiceSession.State.READY,own.status()); assertEquals(0,backend.captures.get())
            assertTrue(own.requestTransmit()); assertEquals(1,wire.requests); assertEquals(0,backend.captures.get())
            own.listener.onEvent(VoiceServerEvent.Granted(a))
            assertEquals(NativeVoiceSession.State.TRANSMITTING,own.status()); assertEquals(1,backend.captures.get())
            own.updateSafety(NativeVoiceAudioSafety(true,null))
            assertEquals(NativeVoiceSession.State.CLOSED,own.status()); assertTrue(wire.closed); assertEquals(1,backend.abandoned.get())
            own.updateSafety(NativeVoiceAudioSafety(true,true)); assertFalse(own.requestTransmit()); assertEquals(1,backend.captures.get())
        } finally { own.close() }
    }
    fun testInitialHoldDoesNotWaitOutFloorHiddenByPreAdoptionEvents() {
        val backend=Backend()
        val own=NativeVoiceSession(VoiceDirection.RECEIVE,backend,{true},object: NativeVoiceSessionObserver {},true,{a.speakerId})
        val wire=Wire()
        try {
            own.updateSafety(NativeVoiceAudioSafety(true,true));own.attach(wire)
            own.listener.onEvent(VoiceServerEvent.Ready(b))
            own.listener.onEvent(VoiceServerEvent.Ended(b.leaseId))
            assertTrue(own.adopt())
            assertEquals(NativeVoiceSession.State.LISTENING,own.status())
            assertFalse("An initial hold must not wait for an occupied floor to end",own.requestTransmit({true},initial=true))
            assertEquals(0,wire.requests)
            assertTrue("A fresh explicit press may request the now free floor",own.requestTransmit({true}))
            assertEquals(1,wire.requests)
        } finally {own.close()}
    }
    fun testExternalHeldAtomicStopsLateGrantBeforeCapture() {
        val backend=Backend();val (own,wire)=session(VoiceDirection.RECEIVE,backend,trip=true,actor=a.speakerId)
        val pressed=AtomicBoolean(true)
        try {
            own.listener.onEvent(VoiceServerEvent.Ready(null))
            assertTrue(own.requestTransmit(pressed::get,initial=true))
            assertEquals(1,wire.requests)
            pressed.set(false)
            own.listener.onEvent(VoiceServerEvent.Granted(a))
            assertEquals(0,backend.captures.get())
            assertEquals(1,wire.releases)
            own.listener.onEvent(VoiceServerEvent.Ended(a.leaseId))
            assertEquals(NativeVoiceSession.State.LISTENING,own.status())
            assertEquals(1,wire.requests)
        } finally {own.close()}
    }
    fun testRevokedAuthorityAndDeniedMicrophoneNeverCapture() {
        val allowed=AtomicBoolean(true); val backend=Backend()
        val (own,wire)=session(VoiceDirection.TRANSMIT,backend,{allowed.get()})
        try {
            own.listener.onEvent(VoiceServerEvent.Ready(null)); assertTrue(own.requestTransmit())
            allowed.set(false); own.listener.onEvent(VoiceServerEvent.Granted(a))
            assertEquals(NativeVoiceSession.State.CLOSED,own.status()); assertEquals(0,backend.captures.get()); assertTrue(wire.closed)
        } finally { own.close() }
        val denied=Backend().also {it.granted=false}; val (next,_)=session(VoiceDirection.TRANSMIT,denied)
        try {
            next.listener.onEvent(VoiceServerEvent.Ready(null)); assertTrue(next.requestTransmit())
            next.listener.onEvent(VoiceServerEvent.Granted(a)); assertEquals(0,denied.captures.get())
            assertEquals(NativeVoiceSession.State.CLOSED,next.status())
        } finally {next.close()}
    }
    fun testSafetyLossAndCloseDuringPlatformStartNeverReadPcm() {
        for (safetyLoss in listOf(true,false)) {
            val backend = Backend().also { it.holdStart = true }
            val (own,wire) = session(VoiceDirection.TRANSMIT,backend)
            try {
                own.listener.onEvent(VoiceServerEvent.Ready(null)); assertTrue(own.requestTransmit())
                val starter = Thread { own.listener.onEvent(VoiceServerEvent.Granted(a)) }.also { it.start() }
                assertTrue(backend.starting.await(2,TimeUnit.SECONDS))
                val stopper = Thread {
                    if (safetyLoss) own.updateSafety(NativeVoiceAudioSafety(false,true)) else own.close()
                }.also { it.start() }
                eventually { if (safetyLoss) stopper.state == Thread.State.BLOCKED else backend.released.get() == 1 }
                backend.continueStart.countDown(); starter.join(2000); stopper.join(2000)
                assertFalse(starter.isAlive); assertFalse(stopper.isAlive)
                assertEquals(0,backend.reads.get()); assertEquals(1,backend.released.get())
                assertEquals(NativeVoiceSession.State.CLOSED,own.status()); assertTrue(wire.closed)
            } finally { backend.continueStart.countDown(); own.close() }
        }
    }
    fun testReceiveLateJoinSequenceAndNoMicrophone() {
        val backend=Backend(); val (own,_)=session(VoiceDirection.RECEIVE,backend)
        try {
            own.listener.onEvent(VoiceServerEvent.Ready(a))
            val frame=VoicePcmFrame(57,ByteArray(640){3})
            assertTrue(own.listener.onFrame(frame))
            eventually {backend.writes.get()==1 && frame.pcm.all {it==0.toByte()}}
            assertEquals(0,backend.captures.get())
            val gap=VoicePcmFrame(59,ByteArray(640){4})
            assertFalse(own.listener.onFrame(gap)); assertTrue(gap.pcm.all {it==0.toByte()})
            assertEquals(NativeVoiceSession.State.CLOSED,own.status())
        } finally {own.close()}
    }
    fun testEndedFloorCannotCloseReplacementAndCurrentFocusLossCloses() {
        val backend=Backend(); val (own,wire)=session(VoiceDirection.RECEIVE,backend)
        try {
            instrumentation.runOnMainSync {
                own.listener.onEvent(VoiceServerEvent.Ready(null))
                own.listener.onEvent(VoiceServerEvent.Started(a))
                own.listener.onEvent(VoiceServerEvent.Ended(a.leaseId))
                own.listener.onEvent(VoiceServerEvent.Started(b))
                own.listener.onEvent(VoiceServerEvent.Ended(a.leaseId))
            }
            instrumentation.waitForIdleSync()
            assertEquals(NativeVoiceSession.State.RECEIVING,own.status()); assertEquals(2,backend.playbacks.get())
            backend.loss!!(); eventually {own.status()==NativeVoiceSession.State.CLOSED}
            assertTrue(wire.closed); assertEquals(2,backend.abandoned.get())
        } finally {own.close()}
    }
    fun testTransmitDirectionDiscardsUnrequestedReceiveAndBusyReturnsReady() {
        val backend=Backend(); val (own,_)=session(VoiceDirection.TRANSMIT,backend)
        try {
            own.listener.onEvent(VoiceServerEvent.Ready(a)); assertEquals(NativeVoiceSession.State.BUSY,own.status())
            val frame=VoicePcmFrame(19,ByteArray(640){8}); assertTrue(own.listener.onFrame(frame))
            assertTrue(frame.pcm.all {it==0.toByte()}); assertEquals(0,backend.playbacks.get()); assertEquals(0,backend.captures.get())
            own.listener.onEvent(VoiceServerEvent.Ended(a.leaseId)); assertEquals(NativeVoiceSession.State.READY,own.status())
        } finally {own.close()}
    }
    fun testUnknownSafetyAndBoundedPreAdoptionFramesFailClosed() {
        val backend=Backend(); val own=NativeVoiceSession(VoiceDirection.RECEIVE,backend,{true},object:NativeVoiceSessionObserver{})
        val wire=Wire(); own.attach(wire); assertTrue(wire.closed); assertFalse(own.adopt())
        assertEquals(0,backend.playbacks.get()); own.close()
        val next=NativeVoiceSession(VoiceDirection.RECEIVE,backend,{true},object:NativeVoiceSessionObserver{})
        try {
            next.updateSafety(NativeVoiceAudioSafety(true,true))
            repeat(7) {assertTrue(next.listener.onFrame(VoicePcmFrame(it.toLong(),ByteArray(640))))}
            val overflow=VoicePcmFrame(7,ByteArray(640){9}); assertFalse(next.listener.onFrame(overflow))
            assertTrue(overflow.pcm.all {it==0.toByte()}); assertEquals(NativeVoiceSession.State.CLOSED,next.status())
        } finally {next.close()}
    }
    fun testTripReleasedPendingGrantNeverCapturesAndNeedsAnotherPress() {
        val backend = Backend(); val (own, wire) = session(VoiceDirection.TRANSMIT, backend, trip=true)
        try {
            own.listener.onEvent(VoiceServerEvent.Ready(null))
            assertEquals(NativeVoiceSession.State.LISTENING, own.status())
            assertTrue(own.requestTransmit()); own.stopTransmit()
            assertFalse(own.requestTransmit())
            own.listener.onEvent(VoiceServerEvent.Granted(a))
            own.listener.onEvent(VoiceServerEvent.Started(a))
            assertEquals(0, backend.captures.get()); assertEquals(0, backend.reads.get())
            assertEquals(1, wire.releases); assertFalse(wire.closed)
            own.listener.onEvent(VoiceServerEvent.Ended(a.leaseId))
            assertEquals(NativeVoiceSession.State.LISTENING, own.status())
            assertTrue(own.requestTransmit())
            own.listener.onEvent(VoiceServerEvent.Granted(b))
            assertEquals(1, backend.captures.get())
            own.stopTransmit(); own.listener.onEvent(VoiceServerEvent.Ended(b.leaseId))
            assertEquals(NativeVoiceSession.State.LISTENING, own.status()); assertFalse(wire.closed)
        } finally { own.close() }
    }
    fun testTripMicrophonePermissionGrantDoesNotArmTransmission() {
        val backend = Backend().also { it.granted=false }
        val (own, wire) = session(VoiceDirection.TRANSMIT, backend, trip=true)
        try {
            own.listener.onEvent(VoiceServerEvent.Ready(null)); assertFalse(own.requestTransmit())
            backend.granted=true
            assertEquals(0, backend.captures.get()); assertEquals(0, wire.requests)
            assertEquals(NativeVoiceSession.State.LISTENING, own.status())
            assertTrue(own.requestTransmit()); own.listener.onEvent(VoiceServerEvent.Granted(a))
            assertEquals(1, backend.captures.get())
        } finally { own.close() }
    }
    fun testTripReleasedRequestCanReceiveLateBusyWithoutClosingOrRearming() {
        val backend = Backend(); val (own, wire) = session(VoiceDirection.TRANSMIT, backend, trip=true)
        try {
            own.listener.onEvent(VoiceServerEvent.Ready(null)); assertTrue(own.requestTransmit())
            own.stopTransmit(); own.listener.onEvent(VoiceServerEvent.Busy)
            assertFalse(wire.closed); assertEquals(0, backend.captures.get())
            assertEquals(NativeVoiceSession.State.LISTENING, own.status())
            assertEquals(1, wire.requests); assertTrue(own.requestTransmit())
            assertEquals(2, wire.requests); assertEquals(0, backend.captures.get())
        } finally { own.close() }
    }
    fun testTripOneSocketReceivesThenTransmitsOnlyWhileHeld() {
        val backend = Backend(); val (own, wire) = session(VoiceDirection.TRANSMIT, backend, trip=true)
        try {
            own.listener.onEvent(VoiceServerEvent.Ready(a))
            assertEquals(NativeVoiceSession.State.RECEIVING, own.status())
            val frame = VoicePcmFrame(2, ByteArray(640) { 3 })
            assertTrue(own.listener.onFrame(frame))
            eventually { backend.writes.get()==1 && frame.pcm.all { it==0.toByte() } }
            assertFalse(own.requestTransmit()); assertEquals(0, backend.captures.get())
            own.listener.onEvent(VoiceServerEvent.Ended(a.leaseId))
            assertTrue(own.requestTransmit()); own.listener.onEvent(VoiceServerEvent.Granted(b))
            assertEquals(1, backend.captures.get()); assertEquals(1, backend.playbacks.get())
            own.stopTransmit(); own.listener.onEvent(VoiceServerEvent.Ended(b.leaseId))
            assertFalse(wire.closed); assertEquals(NativeVoiceSession.State.LISTENING, own.status())
        } finally { own.close() }
    }
    fun testTripReleaseDuringPlatformStartCannotReadOrCloseListeningSocket() {
        val backend = Backend().also { it.holdStart=true }
        val (own, wire) = session(VoiceDirection.TRANSMIT, backend, trip=true)
        try {
            own.listener.onEvent(VoiceServerEvent.Ready(null)); assertTrue(own.requestTransmit())
            val starter = Thread { own.listener.onEvent(VoiceServerEvent.Granted(a)) }.also { it.start() }
            assertTrue(backend.starting.await(2, TimeUnit.SECONDS))
            val releaser = Thread { own.stopTransmit() }.also { it.start() }
            eventually { releaser.state==Thread.State.BLOCKED }
            backend.continueStart.countDown(); starter.join(2000); releaser.join(2000)
            assertFalse(starter.isAlive); assertFalse(releaser.isAlive)
            assertEquals(0, backend.reads.get()); assertFalse(wire.closed)
            own.listener.onEvent(VoiceServerEvent.Ended(a.leaseId))
            assertEquals(NativeVoiceSession.State.LISTENING, own.status())
        } finally { backend.continueStart.countDown(); own.close() }
    }
    fun testTripSameAccountOtherDeviceFloorNeverOpensPlayback() {
        for (ready in listOf(true, false)) {
            val backend = Backend(); val (own, wire) = session(VoiceDirection.TRANSMIT, backend, trip=true, actor=a.speakerId)
            try {
                own.listener.onEvent(VoiceServerEvent.Ready(if (ready) a else null))
                if (!ready) {
                    assertTrue(own.requestTransmit())
                    own.listener.onEvent(VoiceServerEvent.Started(a))
                    own.listener.onEvent(VoiceServerEvent.Busy)
                }
                assertEquals(NativeVoiceSession.State.BUSY, own.status())
                val frame = VoicePcmFrame(0, ByteArray(640) { 5 })
                assertTrue(own.listener.onFrame(frame)); assertTrue(frame.pcm.all { it==0.toByte() })
                assertEquals(0, backend.playbacks.get()); assertEquals(0, backend.captures.get())
                assertFalse(own.requestTransmit()); assertFalse(wire.closed)
                own.listener.onEvent(VoiceServerEvent.Ended(a.leaseId))
                assertEquals(NativeVoiceSession.State.LISTENING, own.status())
            } finally { own.close() }
        }
    }
    fun testTripNormalFifteenSecondLimitReleasesFloorWithoutRearmingOrClosing() {
        val backend = Backend().also { it.readWaitMillis=20000 }
        val (own, wire) = session(VoiceDirection.TRANSMIT, backend, trip=true)
        try {
            own.listener.onEvent(VoiceServerEvent.Ready(null)); assertTrue(own.requestTransmit())
            val began = SystemClock.elapsedRealtime()
            own.listener.onEvent(VoiceServerEvent.Granted(a))
            val until = began+17000
            while (own.status()==NativeVoiceSession.State.TRANSMITTING && SystemClock.elapsedRealtime()<until) Thread.sleep(10)
            assertTrue(SystemClock.elapsedRealtime()-began >= 14900)
            assertEquals(NativeVoiceSession.State.READY, own.status())
            assertFalse(wire.closed); assertEquals(1, wire.releases); assertEquals(1, backend.captures.get())
            assertFalse(own.requestTransmit())
            own.listener.onEvent(VoiceServerEvent.Ended(a.leaseId))
            assertEquals(NativeVoiceSession.State.LISTENING, own.status())
            Thread.sleep(30); assertEquals(1, wire.requests); assertEquals(1, backend.captures.get())
        } finally { own.close() }
    }
}
