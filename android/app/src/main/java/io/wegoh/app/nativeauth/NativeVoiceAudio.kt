package io.wegoh.app.nativeauth

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.AudioRecordingConfiguration
import android.media.AudioTrack
import android.media.MediaRecorder
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import java.io.Closeable
import java.util.ArrayDeque
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

/** Internal platform component, not an authority to join a room or acquire a floor. */
internal enum class NativeVoiceAudioDirection { TRANSMIT, RECEIVE }
internal data class NativeVoiceAudioSafety(val foreground: Boolean = false, val carUxAllowed: Boolean? = null) {
    fun permits() = foreground && carUxAllowed == true
}
internal interface NativeVoiceCapture: Closeable {
    fun start()
    fun read(bytes: ByteArray, offset: Int, count: Int): Int
}
internal interface NativeVoicePlayback: Closeable {
    fun start()
    fun write(bytes: ByteArray, offset: Int, count: Int): Int
    fun playedFrames(): Long? = null
}
internal interface NativeVoiceAudioBackend {
    fun captureSupported(): Boolean
    fun microphoneGranted(): Boolean
    fun focus(lost: () -> Unit): Closeable?
    fun capture(invalidated: () -> Unit): NativeVoiceCapture
    fun playback(): NativeVoicePlayback
}

/** Positive initial client configuration is required before the first microphone frame. */
internal data class NativeVoiceInputConfiguration(val silenced: Boolean, val sampleRate: Int,
    val channels: Int, val encoding: Int, val deviceId: Int, val source: Int)
internal object NativeVoiceCaptureContract {
    fun supportsPlatform(api: Int) = api >= 29
    fun permits(value: NativeVoiceInputConfiguration?) = value != null && !value.silenced &&
        value.sampleRate == NativeVoiceAudio.SAMPLE_RATE && value.channels == 1 &&
        value.encoding == AudioFormat.ENCODING_PCM_16BIT && value.deviceId >= 0 &&
        value.source == MediaRecorder.AudioSource.VOICE_COMMUNICATION
    fun invalidates(value: NativeVoiceInputConfiguration?, baseline: Int) =
        (baseline >= 0 || value != null) && (!permits(value) || baseline >= 0 && value!!.deviceId != baseline)
    fun awaitInitial(current: () -> Boolean, read: () -> NativeVoiceInputConfiguration?): NativeVoiceInputConfiguration? {
        val deadline = SystemClock.elapsedRealtime() + 250
        while (current()) {
            val value = read()
            if (value != null) return value.takeIf { permits(it) && current() && SystemClock.elapsedRealtime() <= deadline }
            val remaining = deadline - SystemClock.elapsedRealtime()
            if (remaining <= 0) return null
            Thread.sleep(minOf(10L, remaining))
        }
        return null
    }
}

/** One explicit, direction-specific floor, at most 15 seconds. No auto-start or resume.
 * The future session owner supplies current authority and invalidates it before stopping.
 * A sink consumes a borrowed buffer synchronously; it must never retain it. No public raw PCM API.
 * OEM Suspend notification is not provided by this component or inferred from SCREEN_OFF.
 */
internal class NativeVoiceAudio(
    private val direction: NativeVoiceAudioDirection,
    private val backend: NativeVoiceAudioBackend,
    private val authorityCurrent: () -> Boolean,
    private val onStopped: (Long) -> Unit = {},
    private val onExpired: ((Long) -> Unit)? = null,
    private val send: (Long, ByteArray) -> Boolean = { _, _ -> false }
): Closeable {
    private val guard = Object()
    private val timer = Handler(Looper.getMainLooper())
    private var safety = NativeVoiceAudioSafety()
    private var closed = false
    private var closingBusy = false
    private var serial = 0L
    private var active: Run? = null
    private inner class Run(val generation: Long, val deadline: Long) {
        var focus: Closeable? = null
        var capture: NativeVoiceCapture? = null
        var playback: NativeVoicePlayback? = null
        val queue = ArrayDeque<ByteArray>()
        var receiveSequence: Long? = null
        var deadlineReached = false
        val expiry = Runnable { stop(this, expired=true) }
    }
    private fun current(run: Run): Boolean {
        if (active !== run || closed || !safety.permits() || !authorityCurrent() ||
            direction == NativeVoiceAudioDirection.TRANSMIT && !backend.microphoneGranted()) return false
        if (SystemClock.elapsedRealtime() >= run.deadline) { run.deadlineReached = true; return false }
        return true
    }

    fun updateSafety(value: NativeVoiceAudioSafety) {
        val ended = synchronized(guard) { safety = value; if (!value.permits()) active else null }
        ended?.let { stop(it) }
    }
    fun isRunning() = synchronized(guard) { active?.let { current(it) } == true }

    /** Caller has already obtained the current direction-specific server floor.
     * Deadline uses elapsedRealtime, never wall time. An excessive lease fails closed.
     */
    fun start(deadlineElapsedMs: Long): Long? {
        val run = synchronized(guard) {
            val remaining = deadlineElapsedMs - SystemClock.elapsedRealtime()
            if (closed || closingBusy || active != null || remaining !in 1..MAX_FLOOR_MS || !safety.permits() ||
                !authorityCurrent() || direction == NativeVoiceAudioDirection.TRANSMIT &&
                (!backend.captureSupported() || !backend.microphoneGranted())) return null
            Run(++serial, deadlineElapsedMs).also { active = it }
        }
        try {
            val focus = backend.focus { stop(run) }
            if (focus == null) { stop(run); return null }
            if (!adopt(run) { run.focus = focus }) { focus.close(); return null }
            if (direction == NativeVoiceAudioDirection.TRANSMIT) {
                val capture = backend.capture { stop(run) }
                if (!adopt(run) { run.capture = capture }) { capture.close(); return null }
            } else {
                val playback = backend.playback()
                if (!adopt(run) { run.playback = playback }) { playback.close(); return null }
            }
            run.capture?.start(); run.playback?.start()
            val started = synchronized(guard) {
                if (!current(run)) false else {
                    timer.postDelayed(run.expiry, (run.deadline - SystemClock.elapsedRealtime()).coerceAtLeast(0))
                    Thread({ if (direction == NativeVoiceAudioDirection.TRANSMIT) capture(run) else playback(run) },
                        "WegoH-voice-audio").start()
                    true
                }
            }
            if (!started) stop(run)
            return if (started) run.generation else null
        } catch (_: Exception) { stop(run); return null }
    }
    private fun adopt(run: Run, assign: () -> Unit): Boolean {
        val adopted = synchronized(guard) { if (!current(run)) false else { assign(); true } }
        if (!adopted) stop(run)
        return adopted
    }
    private fun capture(run: Run) {
        val bytes = ByteArray(PCM_BYTES)
        try {
            var offset = 0
            var sequence = 0L
            while (synchronized(guard) { current(run) }) {
                val count = run.capture!!.read(bytes, offset, bytes.size - offset)
                if (count <= 0 || count > bytes.size - offset || count % 2 != 0) break
                offset += count
                if (offset != bytes.size) continue
                val sent = synchronized(guard) { current(run) && sequence <= 0xffff_ffffL && send(sequence, bytes) }
                bytes.fill(0); offset = 0
                if (!sent) break
                sequence++
            }
        } catch (_: Exception) { /* Fail closed without logging audio or platform error text. */ }
        finally { bytes.fill(0); stop(run) }
    }
    /** Always takes ownership, including rejection. Queue plus in-flight frame is bounded. */
    fun receive(ownerGeneration: Long, sequence: Long, pcm: ByteArray): Boolean {
        var rejectedOwner: Run? = null
        val accepted = synchronized(guard) {
            val run = active
            if (run == null || run.generation != ownerGeneration) false
            else if (direction != NativeVoiceAudioDirection.RECEIVE || !current(run) ||
                pcm.size != PCM_BYTES || run.receiveSequence != null && sequence != run.receiveSequence || sequence !in 0..0xffff_ffffL ||
                run.queue.size >= MAX_QUEUED_FRAMES) { rejectedOwner = run; false }
            else { run.receiveSequence = sequence + 1; run.queue.addLast(pcm); guard.notifyAll(); true }
        }
        if (!accepted) { pcm.fill(0); rejectedOwner?.let { stop(it) } }
        return accepted
    }
    private fun playback(run: Run) {
        var bytes: ByteArray? = null
        try {
            while (true) {
                bytes = synchronized(guard) {
                    while (current(run) && run.queue.isEmpty()) guard.wait((run.deadline - SystemClock.elapsedRealtime()).coerceAtLeast(1))
                    if (!current(run)) null else run.queue.removeFirst()
                } ?: break
                var offset = 0
                var stalledUntil: Long? = null
                while (offset < bytes!!.size) {
                    val count = synchronized(guard) {
                        if (!current(run)) -1 else run.playback!!.write(bytes!!, offset, bytes!!.size - offset)
                    }
                    if (count < 0 || count > bytes!!.size - offset || count % 2 != 0) return
                    if (count == 0) {
                        val now = SystemClock.elapsedRealtime()
                        val deadline = stalledUntil ?: (now + 250).also { stalledUntil = it }
                        if (now >= deadline) return
                        Thread.sleep(5)
                        continue
                    }
                    stalledUntil = null
                    offset += count
                }
                bytes!!.fill(0); bytes = null
            }
        } catch (_: Exception) { /* No PCM or platform error text is exposed. */ }
        finally { bytes?.fill(0); stop(run) }
    }
    /** Room/floor callbacks must carry their original owner, never stop the current replacement. */
    fun stop(ownerGeneration: Long) {
        val run = synchronized(guard) { active?.takeIf { it.generation == ownerGeneration } }
        run?.let { stop(it) }
    }
    fun stop() { val run = synchronized(guard) { active }; run?.let { stop(it) } }
    private fun stop(run: Run, expired: Boolean = false) {
        val ended = synchronized(guard) {
            if (active !== run) false else {
                // Invalidate dispatch before stopping platform resources. Late owners cannot stop a replacement.
                active = null; serial++; closingBusy = true
                timer.removeCallbacks(run.expiry)
                while (run.queue.isNotEmpty()) run.queue.removeFirst().fill(0)
                guard.notifyAll(); true
            }
        }
        if (!ended) return
        var cleanupFailed = false
        try {
            if (runCatching { run.capture?.close() }.isFailure) cleanupFailed = true
            if (runCatching { run.playback?.close() }.isFailure) cleanupFailed = true
            if (runCatching { run.focus?.close() }.isFailure) cleanupFailed = true
        } finally {
            synchronized(guard) { if (cleanupFailed) closed = true; closingBusy = false }
        }
        if (!cleanupFailed && (expired || run.deadlineReached) && onExpired != null) onExpired.invoke(run.generation)
        else onStopped(run.generation)
        // A blocking read is unblocked by close; its single owned frame is erased in the worker finally.
    }
    override fun close() { val run = synchronized(guard) { closed = true; active }; run?.let { stop(it) } }
    companion object {
        const val SAMPLE_RATE = 16000
        const val PCM_BYTES = 640
        const val MAX_FLOOR_MS = 15000L
        const val MAX_QUEUED_FRAMES = 7 // Plus at most one worker-owned playback frame.
    }
}

/** Ordinary Android APIs only. Runtime permission UI belongs to a future explicit host action. */
internal class NativeVoiceAndroidAudio(context: Context): NativeVoiceAudioBackend {
    private val context = context.applicationContext
    private val audio = requireNotNull(context.getSystemService(AudioManager::class.java))
    private val main = Handler(Looper.getMainLooper())
    private val attributes = AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build()
    override fun captureSupported() = NativeVoiceCaptureContract.supportsPlatform(Build.VERSION.SDK_INT)
    override fun microphoneGranted() = context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
    override fun focus(lost: () -> Unit): Closeable? {
        val finished = AtomicBoolean(false)
        val request = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT).setAudioAttributes(attributes)
            .setAcceptsDelayedFocusGain(false).setWillPauseWhenDucked(true)
            .setOnAudioFocusChangeListener({ change ->
                if (change != AudioManager.AUDIOFOCUS_GAIN && !finished.get()) lost()
            }, main).build()
        val result = audio.requestAudioFocus(request)
        if (result != AudioManager.AUDIOFOCUS_REQUEST_GRANTED) {
            finished.set(true); audio.abandonAudioFocusRequest(request); return null
        }
        return Closeable { if (finished.compareAndSet(false, true)) audio.abandonAudioFocusRequest(request) }
    }
    private fun format(mask: Int) = AudioFormat.Builder().setSampleRate(NativeVoiceAudio.SAMPLE_RATE)
        .setChannelMask(mask).setEncoding(AudioFormat.ENCODING_PCM_16BIT).build()
    private fun bufferSize(minimum: Int): Int {
        check(minimum > 0 && minimum <= NativeVoiceAudio.PCM_BYTES * 8)
        return maxOf(minimum, NativeVoiceAudio.PCM_BYTES * 2)
    }
    @android.annotation.TargetApi(29)
    override fun capture(invalidated: () -> Unit): NativeVoiceCapture {
        check(captureSupported())
        if (context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED)
            throw SecurityException("NATIVE_VOICE_MICROPHONE_REQUIRED")
        val minimum = AudioRecord.getMinBufferSize(NativeVoiceAudio.SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val record = AudioRecord.Builder().setAudioSource(MediaRecorder.AudioSource.VOICE_COMMUNICATION)
            .setAudioFormat(format(AudioFormat.CHANNEL_IN_MONO)).setBufferSizeInBytes(bufferSize(minimum)).build()
        val closed = AtomicBoolean(false)
        val invalid = AtomicBoolean(false)
        val lifecycle = Any()
        val initialDevice = AtomicInteger(-1)
        fun configuration(): NativeVoiceInputConfiguration? = record.activeRecordingConfiguration?.let {
            NativeVoiceInputConfiguration(it.isClientSilenced, it.clientFormat.sampleRate, it.clientFormat.channelCount,
                it.clientFormat.encoding, it.audioDevice?.id ?: -1, it.clientAudioSource)
        }
        val callback = object: AudioManager.AudioRecordingCallback() {
            override fun onRecordingConfigChanged(configs: MutableList<AudioRecordingConfiguration>) {
                if (closed.get()) return
                val current = runCatching { configuration() }.getOrNull()
                val baseline = initialDevice.get()
                if (NativeVoiceCaptureContract.invalidates(current, baseline)) { invalid.set(true); invalidated() }
            }
        }
        try {
            check(record.state == AudioRecord.STATE_INITIALIZED && record.sampleRate == NativeVoiceAudio.SAMPLE_RATE &&
                record.channelCount == 1 && record.audioFormat == AudioFormat.ENCODING_PCM_16BIT)
            record.registerAudioRecordingCallback(context.mainExecutor, callback)
        } catch (error: Exception) { record.release(); throw error }
        return object: NativeVoiceCapture {
            override fun start() = synchronized(lifecycle) {
                check(!closed.get() && microphoneGranted())
                record.startRecording()
                check(record.recordingState == AudioRecord.RECORDSTATE_RECORDING)
                val initial = NativeVoiceCaptureContract.awaitInitial(
                    { !closed.get() && !invalid.get() && microphoneGranted() && record.recordingState == AudioRecord.RECORDSTATE_RECORDING },
                    ::configuration)
                checkNotNull(initial)
                initialDevice.set(initial.deviceId)
            }
            override fun read(bytes: ByteArray, offset: Int, count: Int): Int {
                check(!closed.get() && !invalid.get() && microphoneGranted())
                return record.read(bytes, offset, count, AudioRecord.READ_BLOCKING)
            }
            override fun close() {
                if (!closed.compareAndSet(false, true)) return
                synchronized(lifecycle) {
                    runCatching { record.unregisterAudioRecordingCallback(callback) }
                    try { record.stop() } finally { record.release() }
                }
            }
        }
    }
    override fun playback(): NativeVoicePlayback {
        val minimum = AudioTrack.getMinBufferSize(NativeVoiceAudio.SAMPLE_RATE, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val track = AudioTrack.Builder().setAudioAttributes(attributes).setAudioFormat(format(AudioFormat.CHANNEL_OUT_MONO))
            .setTransferMode(AudioTrack.MODE_STREAM).setBufferSizeInBytes(bufferSize(minimum)).build()
        val closed = AtomicBoolean(false)
        if (track.state != AudioTrack.STATE_INITIALIZED) { track.release(); error("NATIVE_VOICE_AUDIO_UNAVAILABLE") }
        return object: NativeVoicePlayback {
            override fun start() { check(!closed.get()); track.play() }
            override fun playedFrames() = track.playbackHeadPosition.toLong() and 0xffff_ffffL
            override fun write(bytes: ByteArray, offset: Int, count: Int): Int {
                check(!closed.get())
                return track.write(bytes, offset, count, AudioTrack.WRITE_NON_BLOCKING)
            }
            override fun close() {
                if (!closed.compareAndSet(false, true)) return
                try { track.pause(); track.flush(); track.stop() } finally { track.release() }
            }
        }
    }
}
