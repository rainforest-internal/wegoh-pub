package io.wegoh.app.nativeauth

import android.os.SystemClock
import java.io.Closeable

internal class NativeVoiceClipAudio(private val backend: NativeVoiceAudioBackend,
    private val authority: () -> Boolean): Closeable {
    private val guard = Any()
    private var safety = NativeVoiceAudioSafety()
    private var closed = false
    private class Recording(val bytes: NativeVoiceClipRecording, val complete: (ByteArray) -> Unit, val interrupted: () -> Unit,
        val full: () -> Unit) {
        var audio: NativeVoiceAudio? = null
        var released = false
        var captureFinished = false
    }
    private class Playing(val bytes: ByteArray, val complete: (Boolean) -> Unit) {
        var output: NativeVoicePlayback? = null
        var focus: Closeable? = null
    }
    private var recording: Recording? = null
    private var playing: Playing? = null
    private fun allowed() = !closed && safety.permits() && authority()

    fun updateSafety(value: NativeVoiceAudioSafety) {
        val input = synchronized(guard) { safety = value; recording?.audio }
        if (!value.permits()) cancel() else input?.updateSafety(value)
    }
    fun record(complete: (ByteArray) -> Unit, interrupted: () -> Unit, full: () -> Unit): Boolean {
        val run = synchronized(guard) {
            if (!allowed() || recording != null || playing != null) return false
            Recording(NativeVoiceClipRecording(), complete, interrupted, full).also { recording = it }
        }
        val audio = NativeVoiceAudio(NativeVoiceAudioDirection.TRANSMIT, backend,
            { synchronized(guard) { recording === run && allowed() } },
            send={ _, frame -> synchronized(guard) { recording === run && allowed() && (run.bytes.isFull() || run.bytes.append(frame)) } },
            onStopped={ finishRecording(run, false) }, onExpired={ finishRecording(run, true) })
        val configured = synchronized(guard) { run.audio = audio; safety }
        audio.updateSafety(configured)
        val started = audio.start(SystemClock.elapsedRealtime() + NativeVoiceAudio.MAX_FLOOR_MS) != null
        if (!started) finishRecording(run, false)
        return started
    }
    fun release() {
        val run = synchronized(guard) { recording?.also { it.released = true } } ?: return
        if (run.captureFinished) finishRecording(run, false) else run.audio?.stop()
    }
    private fun finishRecording(run: Recording, expired: Boolean) {
        val retained = synchronized(guard) {
            if (recording !== run) return
            (expired && !run.released && allowed()).also { if (it) run.captureFinished = true }
        }
        if (retained) { run.full(); return }
        val result = synchronized(guard) {
            if (recording !== run) return
            recording = null
            if (allowed() && run.released) run.bytes.take() else { run.bytes.erase(); null }
        }
        run.audio?.close()
        if (result != null) run.complete(result) else run.interrupted()
    }
    fun play(bytes: ByteArray, complete: (Boolean) -> Unit): Boolean {
        val run = synchronized(guard) {
            if (!allowed() || recording != null || playing != null || bytes.size !in 640..NativeVoiceClipCodec.MAX_PCM_BYTES || bytes.size % 640 != 0) {
                bytes.fill(0); return false
            }
            Playing(bytes, complete).also { playing = it }
        }
        Thread({ playback(run) }, "WegoH-voice-clip").start()
        return true
    }
    private fun current(run: Playing) = synchronized(guard) { playing === run && allowed() }
    private fun playback(run: Playing) {
        var completed = false
        try {
            val focus = backend.focus { finishPlayback(run, false) } ?: return
            synchronized(guard) { if (!current(run)) { focus.close(); return }; run.focus = focus }
            val output = backend.playback()
            synchronized(guard) { if (!current(run)) { output.close(); return }; run.output = output }
            output.start()
            val deadline = SystemClock.elapsedRealtime() + run.bytes.size / 32 + 2000
            var offset = 0
            var stalledUntil: Long? = null
            while (current(run) && SystemClock.elapsedRealtime() < deadline && offset < run.bytes.size) {
                val count = synchronized(guard) {
                    if (!current(run)) -1 else output.write(run.bytes, offset, minOf(640, run.bytes.size - offset))
                }
                if (count < 0 || count > minOf(640, run.bytes.size - offset) || count % 2 != 0) return
                if (count == 0) {
                    val now = SystemClock.elapsedRealtime()
                    val stalled = stalledUntil ?: (now + 250).also { stalledUntil = it }
                    if (now >= stalled) return
                    Thread.sleep(5)
                } else { offset += count; stalledUntil = null }
            }
            if (offset != run.bytes.size) return
            val expected = run.bytes.size / 2
            while (current(run) && SystemClock.elapsedRealtime() < deadline) {
                val played = output.playedFrames() ?: return
                if (played >= expected) { completed = true; return }
                Thread.sleep(5)
            }
        } catch (_: Exception) {
        } finally { finishPlayback(run, completed) }
    }
    private fun finishPlayback(run: Playing, completed: Boolean) {
        synchronized(guard) { if (playing !== run) return; playing = null }
        runCatching { run.output?.close() }; runCatching { run.focus?.close() }
        run.bytes.fill(0)
        run.complete(completed)
    }
    fun cancel() {
        val own = synchronized(guard) { recording.also { recording = null } }
        own?.bytes?.erase(); own?.audio?.close()
        val output = synchronized(guard) { playing }
        output?.let { finishPlayback(it, false) }
    }
    override fun close() { synchronized(guard) { closed = true }; cancel() }
}
