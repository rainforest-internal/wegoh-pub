package io.wegoh.app.nativeauth

import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import java.io.Closeable
import java.util.concurrent.atomic.AtomicBoolean

interface NativeVoiceSessionObserver {
    fun onState(state: NativeVoiceSession.State) {}
}

/** Explicit room/direction session. No recording until a user request receives a current floor. */
class NativeVoiceSession internal constructor(
    private val direction: VoiceDirection,
    backend: NativeVoiceAudioBackend,
    private val authority: () -> Boolean,
    private val observer: NativeVoiceSessionObserver,
    private val tripDuplex: Boolean = false,
    private val currentActor: () -> String? = { null }
): Closeable {
    internal val listener = object: NativeVoiceSocketListener {
        override fun onEvent(event: VoiceServerEvent) = serverEvent(event)
        override fun onFrame(frame: VoicePcmFrame) = serverFrame(frame)
        override fun onClosed(code: Int) { main.post { close() } }
        override fun onUnavailable() { main.post { close() } }
    }
    enum class State { JOINING, LISTENING, READY, REQUESTING, TRANSMITTING, RECEIVING, BUSY, CLOSED }
    private val guard = Any()
    private val main = Handler(Looper.getMainLooper())
    @Volatile private var state = State.JOINING
    @Volatile private var socket: NativeVoiceWire? = null
    private var adopted = false
    @Volatile private var safety = NativeVoiceAudioSafety()
    private var floor: VoiceFloor? = null
    private var audioGeneration: Long? = null
    private var receiveGeneration: Long? = null
    private val held = AtomicBoolean(false)
    @Volatile private var heldCurrent: () -> Boolean = { true }
    private var tripFloorObserved = false
    private var releasing = false
    private var releaseSent = false
    private var ownOtherFloor = false
    private val audioBackend = backend
    private val sequence = VoiceReceiveSequence()
    private val pending = ArrayDeque<VoiceServerEvent>()
    private val frames = ArrayDeque<VoicePcmFrame>()
    private val audio = NativeVoiceAudio(
        if (direction == VoiceDirection.TRANSMIT) NativeVoiceAudioDirection.TRANSMIT else NativeVoiceAudioDirection.RECEIVE,
        backend, { authority() && state != State.CLOSED && safety.permits() && (!tripDuplex || transmitHeld()) },
        send = { number, pcm -> state == State.TRANSMITTING && (!tripDuplex || transmitHeld()) && authority() && socket?.frame(number, pcm) == true },
        onStopped = { owner -> audioStopped(owner, false) },
        onExpired = { owner -> audioStopped(owner, true) }
    )
    private val receiveAudio = if (!tripDuplex) null else NativeVoiceAudio(NativeVoiceAudioDirection.RECEIVE,
        backend, { authority() && state != State.CLOSED && safety.permits() },
        onStopped = { owner -> main.post { if (receiveGeneration == owner && state == State.RECEIVING) close() } })
    private val readyTimeout = Runnable { if (state == State.JOINING) close() }
    private val requestTimeout = Runnable { if (state == State.REQUESTING) close() }
    init { main.postDelayed(readyTimeout, 10000) }
    fun status() = state
    private fun audioStopped(owner: Long, expired: Boolean) {
        main.post {
            if (audioGeneration == owner && state in setOf(State.TRANSMITTING, State.RECEIVING)) {
                if (expired && tripDuplex && state == State.TRANSMITTING) stopTransmit() else close()
            }
        }
    }
    private fun publish(value: State) {
        if (value != State.JOINING) main.removeCallbacks(readyTimeout)
        if (value != State.REQUESTING) main.removeCallbacks(requestTimeout)
        state = value
        main.post { if (state == value) observer.onState(value) }
    }
    internal fun updateSafety(value: NativeVoiceAudioSafety) {
        safety = value
        if (!value.permits()) held.set(false)
        synchronized(guard) { audio.updateSafety(value); receiveAudio?.updateSafety(value); if (!value.permits()) close() }
    }
    internal fun attach(value: NativeVoiceWire) = synchronized(guard) {
        if (state == State.CLOSED || !authority() || !safety.permits()) value.close() else socket = value
    }
    internal fun adopt(): Boolean = synchronized(guard) {
        if (state == State.CLOSED || socket == null || !authority() || !safety.permits()) { close(); return false }
        adopted = true
        while (pending.isNotEmpty() && state != State.CLOSED) handle(pending.removeFirst())
        while (frames.isNotEmpty()) { val frame = frames.removeFirst(); if (!deliver(frame)) frame.erase() }
        state != State.CLOSED
    }
    private fun serverEvent(event: VoiceServerEvent) = synchronized(guard) {
        if (state == State.CLOSED) return
        if (!authority() || !safety.permits()) { close(); return }
        if (!adopted) { if (pending.size >= 8) close() else pending.addLast(event) }
        else handle(event)
    }
    private fun begin(value: VoiceFloor, transmit: Boolean, late: Boolean = false) {
        if (floor != null || !tripDuplex && direction != (if (transmit) VoiceDirection.TRANSMIT else VoiceDirection.RECEIVE)) { close(); return }
        floor = value
        if (!transmit) sequence.begin(value.leaseId, late)
        publish(if (transmit) State.TRANSMITTING else State.RECEIVING)
        val started = (if (tripDuplex && !transmit) receiveAudio!! else audio)
            .start(SystemClock.elapsedRealtime() + NativeVoiceAudio.MAX_FLOOR_MS)
        if (tripDuplex && !transmit) receiveGeneration = started else audioGeneration = started
        if (started == null) {
            if (tripDuplex && transmit && !transmitHeld()) {
                releasing = true; releaseFloor(); if (state != State.CLOSED) publish(State.READY)
            } else close()
        }
    }
    private fun handle(event: VoiceServerEvent) {
        if (tripDuplex) { tripEvent(event); return }
        when (event) {
            is VoiceServerEvent.Ready -> {
                if (state != State.JOINING) { close(); return }
                publish(if (direction == VoiceDirection.RECEIVE) State.LISTENING else State.READY)
                if (event.floor != null) {
                    if (direction == VoiceDirection.RECEIVE) begin(event.floor, false, true) else publish(State.BUSY)
                }
            }
            is VoiceServerEvent.Granted -> {
                if (direction != VoiceDirection.TRANSMIT || state != State.REQUESTING) { close(); return }
                begin(event.floor, true)
            }
            is VoiceServerEvent.Started -> {
                // The sender can receive its own start notification after floor-granted.
                if (direction == VoiceDirection.TRANSMIT) {
                    if (state == State.TRANSMITTING) { if (floor?.leaseId != event.floor.leaseId) close() }
                    else if (state in setOf(State.READY, State.BUSY)) publish(State.BUSY)
                } else begin(event.floor, false)
            }
            is VoiceServerEvent.Ended -> {
                if (direction == VoiceDirection.TRANSMIT && state == State.BUSY) publish(State.READY)
                if (floor?.leaseId == event.leaseId) {
                    floor = null; sequence.end()
                    val ended = audioGeneration; audioGeneration = null; ended?.let { audio.stop(it) }
                    publish(if (direction == VoiceDirection.RECEIVE) State.LISTENING else State.READY)
                }
            }
            VoiceServerEvent.Busy -> if (state == State.REQUESTING) publish(State.BUSY) else close()
            VoiceServerEvent.Pong -> Unit
        }
    }
    private fun tripEvent(event: VoiceServerEvent) {
        when (event) {
            is VoiceServerEvent.Ready -> {
                if (state != State.JOINING) { close(); return }
                publish(State.LISTENING)
                event.floor?.let { receiveTripFloor(it, true) }
            }
            is VoiceServerEvent.Granted -> {
                if (currentActor()?.let { it != event.floor.speakerId } == true) { close(); return }
                if (floor != null || state !in setOf(State.REQUESTING, State.READY)) { close(); return }
                if (!transmitHeld() || releasing) {
                    floor = event.floor; releasing = true
                    releaseFloor(); if (state != State.CLOSED) publish(State.READY)
                } else begin(event.floor, true)
            }
            is VoiceServerEvent.Started -> {
                if (floor?.leaseId == event.floor.leaseId) return
                if (floor != null) { close(); return }
                receiveTripFloor(event.floor)
            }
            is VoiceServerEvent.Ended -> {
                if (floor?.leaseId == event.leaseId) {
                    floor = null; held.set(false); releasing = false; releaseSent = false; ownOtherFloor = false; sequence.end()
                    val oldTx = audioGeneration; audioGeneration = null
                    val oldRx = receiveGeneration; receiveGeneration = null
                    oldTx?.let { audio.stop(it) }; oldRx?.let { receiveAudio?.stop(it) }
                    publish(State.LISTENING)
                }
            }
            VoiceServerEvent.Busy -> {
                held.set(false)
                if (state == State.REQUESTING || state == State.READY && releasing) {
                    releasing = false; releaseSent = false; publish(State.LISTENING)
                }
                else if (state != State.RECEIVING && !(state == State.BUSY && ownOtherFloor)) close()
            }
            VoiceServerEvent.Pong -> Unit
        }
    }
    private fun receiveTripFloor(value: VoiceFloor, late: Boolean = false) {
        tripFloorObserved = true
        if (currentActor() == value.speakerId) {
            floor = value; ownOtherFloor = true; held.set(false); publish(State.BUSY)
        } else begin(value, false, late)
    }
    private fun releaseFloor() {
        if (!releaseSent) { releaseSent = true; if (socket?.control(VoiceControl.RELEASE) != true) close() }
    }
    private fun serverFrame(frame: VoicePcmFrame): Boolean = synchronized(guard) {
        if (state == State.CLOSED || !authority() || !safety.permits()) { frame.erase(); return false }
        if (!adopted) {
            if (frames.size >= 7) { frame.erase(); close(); false } else { frames.addLast(frame); true }
        } else deliver(frame)
    }
    private fun deliver(frame: VoicePcmFrame): Boolean {
        if (tripDuplex && ownOtherFloor) { frame.erase(); return true }
        if (direction == VoiceDirection.TRANSMIT && !tripDuplex || tripDuplex && state == State.TRANSMITTING) { frame.erase(); return true }
        val owner = if (tripDuplex) receiveGeneration else audioGeneration
        if (state != State.RECEIVING || owner == null || !authority()) { frame.erase(); return false }
        return try { sequence.accept(frame); (receiveAudio ?: audio).receive(owner, frame.sequence, frame.pcm) }
        catch (_: Exception) { frame.erase(); close(); false }
    }
    /** One explicit action, bounded by a server-owned 15-second lease. Never resumes automatically. */
    fun requestTransmit(): Boolean = requestTransmit({ true })
    private fun transmitHeld() = held.get() && heldCurrent()
    internal fun requestTransmit(whileHeld: () -> Boolean, initial: Boolean = false): Boolean = synchronized(guard) {
        if (tripDuplex) {
            if (state != State.LISTENING || releasing || !authority() || !safety.permits() ||
                !audioBackend.microphoneGranted() || !audioBackend.captureSupported() ||
                !whileHeld() || initial && tripFloorObserved) return false
            heldCurrent = whileHeld
            held.set(true); releaseSent = false; publish(State.REQUESTING)
            main.postDelayed(requestTimeout, 10000)
            if (socket?.control(VoiceControl.REQUEST) != true) { close(); return false }
            return true
        }
        if (direction != VoiceDirection.TRANSMIT || state !in setOf(State.READY, State.BUSY) || !authority() || !safety.permits()) return false
        publish(State.REQUESTING)
        main.postDelayed(requestTimeout, 10000)
        if (socket?.control(VoiceControl.REQUEST) != true) { close(); false } else true
    }
    /** Releases only this session; a new transmission always requires another explicit action. */
    fun stopTransmit() {
        if (tripDuplex) held.set(false)
        synchronized(guard) {
          if (tripDuplex) {
            if (state in setOf(State.REQUESTING, State.TRANSMITTING)) {
                releasing = true; audioGeneration = null; releaseFloor()
                if (state != State.CLOSED) publish(State.READY)
                audio.stop()
            }
          } else if (direction == VoiceDirection.TRANSMIT && state in setOf(State.REQUESTING, State.TRANSMITTING)) {
            // Close avoids racing a late grant from the previous floor request.
            close()
          }
        }
    }
    override fun close() {
        held.set(false); audio.close(); receiveAudio?.close()
        val old = synchronized(guard) {
            if (state == State.CLOSED) return
            publish(State.CLOSED); floor = null; sequence.end(); pending.clear()
            while (frames.isNotEmpty()) frames.removeFirst().erase()
            socket.also { socket = null }
        }
        old?.close()
    }
}
