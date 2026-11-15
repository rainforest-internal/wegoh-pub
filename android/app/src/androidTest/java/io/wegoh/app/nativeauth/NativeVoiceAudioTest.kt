package io.wegoh.app.nativeauth

import android.os.SystemClock
import android.test.AndroidTestCase
import java.io.Closeable
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

/** Synthetic component tests only. No AudioRecord, host microphone, public join or OEM event. */
class NativeVoiceAudioTest: AndroidTestCase() {
    private class Backend: NativeVoiceAudioBackend {
        var platformSupported = true
        var permission = true
        var focusGranted = true
        var loseDuringFocus = false
        var loss: (() -> Unit)? = null
        var oldLoss: (() -> Unit)? = null
        val focusRequests = AtomicInteger()
        val abandoned = AtomicInteger()
        val captures = AtomicInteger()
        val released = AtomicInteger()
        val writes = AtomicInteger()
        var played: ByteArray? = null
        var holdClose = false
        var holdStart = false
        var zeroWritesForever = false
        val writeResults = ArrayDeque<Int>()
        var failClose = false
        val starting = CountDownLatch(1)
        val continueStart = CountDownLatch(1)
        val closing = CountDownLatch(1)
        val continueClose = CountDownLatch(1)
        val reading = CountDownLatch(1)
        val resume = CountDownLatch(1)
        val done = CountDownLatch(1)
        var borrowed: ByteArray? = null
        var hold = true
        override fun captureSupported() = platformSupported
        override fun microphoneGranted() = permission
        private fun releaseDevice() {
            released.incrementAndGet(); closing.countDown()
            try { if (holdClose) check(continueClose.await(3, TimeUnit.SECONDS)) }
            finally { resume.countDown() }
            check(!failClose)
        }
        override fun focus(lost: () -> Unit): Closeable? {
            focusRequests.incrementAndGet(); oldLoss = loss; loss = lost
            if (loseDuringFocus) lost()
            return if (focusGranted) Closeable { abandoned.incrementAndGet() } else null
        }
        override fun capture(invalidated: () -> Unit): NativeVoiceCapture {
            captures.incrementAndGet()
            return object: NativeVoiceCapture {
                private val closed = AtomicBoolean()
                override fun start() { starting.countDown(); if (holdStart) check(continueStart.await(3, TimeUnit.SECONDS)) }
                override fun read(bytes: ByteArray, offset: Int, count: Int): Int {
                    borrowed = bytes; reading.countDown()
                    if (hold) check(resume.await(3, TimeUnit.SECONDS))
                    // Deliberately return late data after close to test generation, not the fake's correctness.
                    bytes.fill(7, offset, offset + minOf(count, 320))
                    done.countDown()
                    return minOf(count, 320)
                }
                override fun close() { if (closed.compareAndSet(false, true)) { releaseDevice() } }
            }
        }
        override fun playback(): NativeVoicePlayback = object: NativeVoicePlayback {
            override fun start() {}
            override fun write(bytes: ByteArray, offset: Int, count: Int): Int {
                played = bytes; writes.incrementAndGet()
                if (writeResults.isNotEmpty()) return writeResults.removeFirst()
                if (zeroWritesForever) return 0
                return minOf(count, 320)
            }
            override fun close() { releaseDevice() }
        }
    }
    private fun expiry(ms: Long = 2000) = SystemClock.elapsedRealtime() + ms
    private fun safe(audio: NativeVoiceAudio) = audio.updateSafety(NativeVoiceAudioSafety(true, true))
    private fun eventually(check: () -> Boolean) {
        val end = SystemClock.elapsedRealtime() + 2000
        while (!check() && SystemClock.elapsedRealtime() < end) Thread.sleep(5)
        assertTrue(check())
    }
    fun testUnknownPermissionAndFocusDenialsDoNotCapture() {
        val backend = Backend()
        val audio = NativeVoiceAudio(NativeVoiceAudioDirection.TRANSMIT, backend, { true })
        try {
            assertNull(audio.start(expiry())); assertEquals(0, backend.focusRequests.get())
            safe(audio); backend.platformSupported = false
            assertNull(audio.start(expiry())); assertEquals(0, backend.focusRequests.get()); assertEquals(0, backend.captures.get())
            backend.platformSupported = true; backend.permission = false
            assertNull(audio.start(expiry())); assertEquals(0, backend.focusRequests.get())
            backend.permission = true; backend.focusGranted = false
            assertNull(audio.start(expiry())); assertEquals(0, backend.captures.get())
            assertNull(audio.start(expiry(16000))); assertEquals(1, backend.focusRequests.get())
        } finally { audio.close() }
    }
    fun testUnknownInitialConfigurationAndOldPlatformFailClosed() {
        assertFalse(NativeVoiceCaptureContract.supportsPlatform(28)); assertTrue(NativeVoiceCaptureContract.supportsPlatform(29))
        val valid = NativeVoiceInputConfiguration(false, 16000, 1, 2, 4, 7)
        assertTrue(NativeVoiceCaptureContract.permits(valid)); assertFalse(NativeVoiceCaptureContract.permits(null))
        assertFalse(NativeVoiceCaptureContract.permits(valid.copy(deviceId = -1)))
        assertFalse(NativeVoiceCaptureContract.permits(valid.copy(silenced = true)))
        assertFalse(NativeVoiceCaptureContract.permits(valid.copy(sampleRate = 48000)))
        assertFalse(NativeVoiceCaptureContract.permits(valid.copy(channels = 2)))
        assertFalse(NativeVoiceCaptureContract.permits(valid.copy(encoding = 4)))
        assertFalse(NativeVoiceCaptureContract.permits(valid.copy(source = 1)))
    }
    fun testInitialConfigurationCanArriveAfterRecordingStarts() {
        val valid = NativeVoiceInputConfiguration(false, 16000, 1, 2, 4, 7)
        var reads = 0
        assertEquals(valid, NativeVoiceCaptureContract.awaitInitial({ true }) { if (++reads < 3) null else valid })
        assertEquals(3, reads)
        assertFalse(NativeVoiceCaptureContract.invalidates(null, -1))
        assertTrue(NativeVoiceCaptureContract.invalidates(null, valid.deviceId))
        assertTrue(NativeVoiceCaptureContract.invalidates(valid.copy(silenced = true), -1))
        assertTrue(NativeVoiceCaptureContract.invalidates(valid.copy(deviceId = 5), valid.deviceId))
    }
    fun testInitialConfigurationNeverWaitsPastExplicitFailureOrCancellation() {
        val valid = NativeVoiceInputConfiguration(false, 16000, 1, 2, 4, 7)
        var reads = 0
        assertNull(NativeVoiceCaptureContract.awaitInitial({ true }) { reads++; valid.copy(silenced = true) })
        assertEquals(1, reads)
        var current = true
        reads = 0
        assertNull(NativeVoiceCaptureContract.awaitInitial({ current }) { reads++; current = false; null })
        assertEquals(1, reads)
        assertNull(NativeVoiceCaptureContract.awaitInitial({ false }) { fail("Read after cancellation"); valid })
        val began = SystemClock.elapsedRealtime()
        assertNull(NativeVoiceCaptureContract.awaitInitial({ true }) { null })
        assertTrue(SystemClock.elapsedRealtime() - began in 200..1000)
    }
    fun testSafetyLossDuringPlatformStartCancelsBeforeAnyPcmRead() {
        val backend = Backend().also { it.holdStart = true }
        val audio = NativeVoiceAudio(NativeVoiceAudioDirection.TRANSMIT, backend, { true })
        var owner: Long? = -1L
        try {
            safe(audio)
            val starter = Thread { owner = audio.start(expiry()) }.also { it.start() }
            assertTrue(backend.starting.await(2, TimeUnit.SECONDS))
            audio.updateSafety(NativeVoiceAudioSafety(false, true))
            assertEquals(1, backend.released.get())
            backend.continueStart.countDown(); starter.join(2000)
            assertFalse(starter.isAlive); assertNull(owner)
            assertEquals(1L, backend.reading.count)
            assertFalse(audio.isRunning())
        } finally { backend.continueStart.countDown(); audio.close() }
    }
    fun testDeviceCleanupMustCompleteBeforeReplacementAndFailureBlocksRestart() {
        val backend = Backend().also { it.holdClose = true }
        val audio = NativeVoiceAudio(NativeVoiceAudioDirection.RECEIVE, backend, { true })
        try {
            safe(audio); assertNotNull(audio.start(expiry()))
            val closer = Thread { audio.stop() }.also { it.start() }
            assertTrue(backend.closing.await(2, TimeUnit.SECONDS))
            assertNull(audio.start(expiry())); assertEquals(1, backend.focusRequests.get())
            backend.continueClose.countDown(); closer.join(2000); assertFalse(closer.isAlive)
            backend.holdClose = false; assertNotNull(audio.start(expiry()))
            backend.failClose = true; audio.stop()
            assertNull(audio.start(expiry())); assertEquals(2, backend.abandoned.get())
        } finally { backend.continueClose.countDown(); audio.close() }
    }
    fun testFocusLossDuringAcquireDisposesLateOwner() {
        val backend = Backend().also { it.loseDuringFocus = true }
        val audio = NativeVoiceAudio(NativeVoiceAudioDirection.TRANSMIT, backend, { true })
        try {
            safe(audio); assertNull(audio.start(expiry()))
            assertEquals(0, backend.captures.get()); assertEquals(1, backend.abandoned.get())
        } finally { audio.close() }
    }
    fun testHeldPartialReadAfterStopCannotSendAndIsErased() {
        val backend = Backend(); val sent = AtomicInteger()
        val audio = NativeVoiceAudio(NativeVoiceAudioDirection.TRANSMIT, backend, { true }) { _, _ -> sent.incrementAndGet(); true }
        try {
            safe(audio); assertNotNull(audio.start(expiry())); assertTrue(backend.reading.await(2, TimeUnit.SECONDS))
            audio.updateSafety(NativeVoiceAudioSafety(false, true))
            assertTrue(backend.done.await(2, TimeUnit.SECONDS))
            eventually { backend.borrowed?.all { it == 0.toByte() } == true }
            assertFalse(audio.isRunning()); assertEquals(0, sent.get()); assertEquals(1, backend.released.get()); assertEquals(1, backend.abandoned.get())
            safe(audio); assertFalse(audio.isRunning()); assertEquals(1, backend.focusRequests.get())
        } finally { audio.close() }
    }
    fun testPartialReadsAssembleOneFrameAndEraseBorrowedBytes() {
        val backend = Backend().also { it.hold = false }
        val sent = CountDownLatch(1); val count = AtomicInteger(); var correct = false
        val audio = NativeVoiceAudio(NativeVoiceAudioDirection.TRANSMIT, backend, { true }) { sequence, bytes ->
            correct = sequence == 0L && bytes.size == 640 && bytes.all { it == 7.toByte() }
            count.incrementAndGet(); sent.countDown(); false
        }
        try {
            safe(audio); assertNotNull(audio.start(expiry())); assertTrue(sent.await(2, TimeUnit.SECONDS))
            eventually { backend.abandoned.get() == 1 && backend.borrowed?.all { it == 0.toByte() } == true }
            assertTrue(correct); assertEquals(1, count.get()); assertFalse(audio.isRunning())
        } finally { audio.close() }
    }
    fun testOldLossCannotStopExplicitReplacementAndUnknownUxStops() {
        val backend = Backend()
        val audio = NativeVoiceAudio(NativeVoiceAudioDirection.RECEIVE, backend, { true })
        try {
            safe(audio); val oldGeneration = audio.start(expiry())!!; val oldLoss = backend.loss!!
            audio.stop(); assertNotNull(audio.start(expiry()))
            oldLoss(); audio.stop(oldGeneration); assertTrue(audio.isRunning())
            val late = ByteArray(640) { 4 }
            assertFalse(audio.receive(oldGeneration, 0, late)); assertTrue(late.all { it == 0.toByte() }); assertTrue(audio.isRunning())
            audio.updateSafety(NativeVoiceAudioSafety(true, null)); assertFalse(audio.isRunning())
            safe(audio); assertFalse(audio.isRunning()); assertEquals(2, backend.focusRequests.get())
        } finally { audio.close() }
    }
    fun testCurrentFocusLossReleasesAndGainCannotAutoStart() {
        val backend = Backend()
        val audio = NativeVoiceAudio(NativeVoiceAudioDirection.TRANSMIT, backend, { true })
        try {
            safe(audio); assertNotNull(audio.start(expiry())); assertTrue(backend.reading.await(2, TimeUnit.SECONDS))
            backend.loss!!(); assertFalse(audio.isRunning())
            assertEquals(1, backend.abandoned.get()); assertEquals(1, backend.released.get())
            safe(audio); assertFalse(audio.isRunning()); assertEquals(1, backend.focusRequests.get())
        } finally { audio.close() }
    }
    fun testReceivePartialPlaybackErasesAndWrongSequenceEndsOnlyItsOwner() {
        val backend = Backend().also { it.writeResults.addAll(listOf(0,0,0,320,0,320)) }
        val audio = NativeVoiceAudio(NativeVoiceAudioDirection.RECEIVE, backend, { true })
        try {
            safe(audio); val owner = audio.start(expiry())!!
            val frame = ByteArray(640) { 5 }; assertTrue(audio.receive(owner, 0, frame))
            eventually { backend.writes.get() == 6 && frame.all { it == 0.toByte() } }
            assertTrue(audio.isRunning())
            val gap = ByteArray(640) { 9 }; assertFalse(audio.receive(owner, 2, gap))
            assertTrue(gap.all { it == 0.toByte() }); assertFalse(audio.isRunning())
            assertEquals(0, backend.captures.get()); assertEquals(1, backend.abandoned.get())
        } finally { audio.close() }
    }
    fun testPlaybackBackpressureTimesOutAndSafetyLossCancelsItsRetry() {
        for (end in listOf("timeout", "safety", "authority", "close")) {
            val backend = Backend().also { it.zeroWritesForever = true }
            val authority = AtomicBoolean(true)
            val audio = NativeVoiceAudio(NativeVoiceAudioDirection.RECEIVE, backend, { authority.get() })
            try {
                safe(audio); val owner = audio.start(expiry())!!
                val frame = ByteArray(640) { 8 }; assertTrue(audio.receive(owner, 0, frame))
                eventually { backend.writes.get() > 0 }
                when (end) {
                    "safety" -> audio.updateSafety(NativeVoiceAudioSafety(false, true))
                    "authority" -> authority.set(false)
                    "close" -> audio.close()
                }
                eventually { !audio.isRunning() && backend.released.get() == 1 && frame.all { it == 0.toByte() } }
                val writes = backend.writes.get()
                Thread.sleep(20); assertEquals(writes, backend.writes.get())
                assertEquals(1, backend.abandoned.get())
            } finally { audio.close() }
        }
    }
    fun testPlaybackErrorsAndMalformedWriteCountsDoNotRetry() {
        for (count in listOf(-1, 1, 642)) {
            val backend = Backend().also { it.writeResults.add(count) }
            val audio = NativeVoiceAudio(NativeVoiceAudioDirection.RECEIVE, backend, { true })
            try {
                safe(audio); val owner = audio.start(expiry())!!
                val frame = ByteArray(640) { 9 }; assertTrue(audio.receive(owner, 0, frame))
                eventually { !audio.isRunning() && backend.released.get() == 1 && frame.all { it == 0.toByte() } }
                assertEquals(1, backend.writes.get())
            } finally { audio.close() }
        }
    }
    fun testAuthorityRevocationAndDeadlineRejectReceiveAndErase() {
        val backend = Backend(); val authority = AtomicBoolean(true)
        val audio = NativeVoiceAudio(NativeVoiceAudioDirection.RECEIVE, backend, { authority.get() })
        try {
            safe(audio); val first = audio.start(expiry())!!
            authority.set(false); val rejected = ByteArray(640) { 9 }
            assertFalse(audio.receive(first, 0, rejected)); assertTrue(rejected.all { it == 0.toByte() }); assertFalse(audio.isRunning())
            authority.set(true); assertNotNull(audio.start(expiry(40))); eventually { backend.abandoned.get() == 2 }
            assertFalse(audio.isRunning()); assertEquals(0, backend.captures.get())
            val late = ByteArray(640) { 3 }; assertFalse(audio.receive(first, 0, late)); assertTrue(late.all { it == 0.toByte() })
        } finally { audio.close() }
    }
    fun testExpiryCallbackIsOwnedAndExplicitStopKeepsItsOriginalReason() {
        for (timeout in listOf(true, false)) {
            val backend = Backend(); val ended = CountDownLatch(1)
            val stopped = AtomicInteger(); val expired = AtomicInteger()
            val audio = NativeVoiceAudio(NativeVoiceAudioDirection.TRANSMIT, backend, { true },
                onStopped={ stopped.incrementAndGet(); ended.countDown() },
                onExpired={ expired.incrementAndGet(); ended.countDown() })
            try {
                safe(audio); assertNotNull(audio.start(expiry(if (timeout) 40 else 2000)))
                if (!timeout) audio.stop()
                assertTrue(ended.await(2, TimeUnit.SECONDS))
                assertEquals(if (timeout) 1 else 0, expired.get())
                assertEquals(if (timeout) 0 else 1, stopped.get())
                assertFalse(audio.isRunning()); assertEquals(1, backend.released.get())
            } finally { audio.close() }
        }
    }
}
