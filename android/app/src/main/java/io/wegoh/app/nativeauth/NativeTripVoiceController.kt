package io.wegoh.app.nativeauth

import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import java.io.Closeable
import java.util.ArrayDeque
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong

class NativeTripVoiceController internal constructor(
    private val host: TripVoiceHost,
    private val tripId: String,
    private val title: String,
    private val observer: (State) -> Unit
): Closeable {
    constructor(connection: VehicleConnection, tripId: String, title: String, observer: (State) -> Unit):
        this(VehicleTripVoiceHost(connection), tripId, title, observer)
    enum class Phase { LOADING, LISTENING, HEARING, REQUESTING, TRANSMITTING, RECORDED, SENDING, OFF, UNAVAILABLE }
    data class State(val phase: Phase = Phase.LOADING, val participating: Boolean = false, val notice: String? = null)
    private class Outgoing(val id: String, val pcm: ByteArray, val recordedAt: Long) {
        fun erase() = pcm.fill(0)
    }
    private val generation = AtomicLong()
    private val held = AtomicBoolean(false)
    private val closing = AtomicBoolean(false)
    @Volatile private var closed = false
    @Volatile private var started = false
    @Volatile private var safety = NativeVoiceAudioSafety()
    @Volatile private var participation: VoiceTripParticipation? = null
    @Volatile private var permission: VoiceRoomPermission? = null
    private var client: TripVoiceClient? = null
    private var reservation: Closeable? = null
    private var call: Closeable? = null
    private var pollCall: Closeable? = null
    private var audio: NativeVoiceClipAudio? = null
    private var changingParticipation = false
    private val position = TripVoiceFeedPosition()
    private val inbox = position.inbox
    /** 같은 계정 경계 안의 연결 교체 중. 상태·조회 위치는 남기고 새 클라이언트의 첫 조회까지 재생·녹음만 미룬다. */
    private var reconnecting = false
    /**
     * 지금 클라이언트로 참여(revision·가입 시각)를 확인했는지. 무효화가 모든 소셜 클라이언트를 끝내 여행 다시 읽기와 겹치면
     * 준비 전 새 클라이언트로 조회해 client_not_ready로 '음성을 받지 못했어요'가 깜빡이므로, 확인 전에는 조회하지 않는다.
     */
    private var clientConfirmed = false
    /** 여행 화면이 현재 여행을 확인한 상태인지. 다시 읽는 동안은 조회·재생·녹음만 멈추고 연결·조회 위치는 남긴다. */
    private var tripReady = true
    private var incoming: NativeVoiceClipMetadata? = null
    private var retryingClipId: String? = null
    private var outgoing: Outgoing? = null
    private var recordStartedAt = 0L
    private var state = State()
    private val poll = Runnable { readFeed(generation.get()) }

    init { require(Regex("[a-f0-9]{32}").matches(tripId)) }
    private fun onMain(action: () -> Unit) {
        if (host.onMainThread()) action() else host.post(action)
    }
    private fun current(token: Long) = !closed && !closing.get() && started && token == generation.get() && safety.permits()
    private fun audioCurrent(): Boolean {
        val own = permission
        return current(generation.get()) && participation?.participating == true && own != null &&
            host.socialNow() < own.expiresAt.toEpochMilli() && VoiceDirection.entries.all { it in own.directions }
    }
    private fun publish(phase: Phase, notice: String? = null) {
        state = State(phase, participation?.participating == true, notice)
        val value = state
        onMain { if (!closed && !closing.get() && state === value) observer(value) }
    }
    fun start() = onMain {
        if (!closed && !closing.get()) { started = true; if (safety.permits() && client == null) connect() }
    }
    fun retry() = onMain {
        if (!current(generation.get())) return@onMain
        if (outgoing != null && client?.status() == NativeSocialClient.State.READY) sendOutgoing(generation.get())
        else { reset(); connect() }
    }
    fun updateSafety(foreground: Boolean, carUxAllowed: Boolean?) = onMain {
        safety = NativeVoiceAudioSafety(foreground, carUxAllowed)
        if (!safety.permits()) {
            reset(); publish(Phase.OFF, when(carUxAllowed) {
                false -> "정차 후 이용해 주세요"
                null -> "주행 제한 확인 중"
                true -> "여행 화면에서 다시 연결해요"
            })
        } else if (started && !closed && client == null) connect()
        else audio?.updateSafety(safety)
    }
    fun press(): Boolean {
        if (!host.onMainThread() || !current(generation.get()) || !tripReady || changingParticipation || held.get()) return false
        if (reconnecting) {
            // 연결 교체 중의 누름은 새 클라이언트의 첫 조회가 끝날 때까지 남아 있어야 녹음으로 이어진다(손을 떼면 취소).
            if (state.phase != Phase.LISTENING || outgoing != null || participation?.participating != true) return false
            held.set(true); publish(Phase.REQUESTING)
            return true
        }
        if (state.phase == Phase.OFF && participation?.participating == false && client != null) {
            held.set(true)
            if (!changeParticipation(true)) { held.set(false); return false }
            return true
        }
        if (state.phase != Phase.LISTENING || outgoing != null) return false
        held.set(true); prepareRecording(generation.get())
        return true
    }
    fun release() = onMain {
        if (!held.getAndSet(false)) return@onMain
        if (state.phase in setOf(Phase.TRANSMITTING, Phase.RECORDED)) audio?.release()
        else if (state.phase == Phase.REQUESTING) { call?.close(); call = null; publish(Phase.LISTENING); playNext() }
    }
    fun cancel() = onMain {
        held.set(false)
        if (state.phase in setOf(Phase.REQUESTING, Phase.TRANSMITTING, Phase.RECORDED)) {
            call?.close(); call = null; audio?.cancel(); publish(Phase.LISTENING); playNext()
        }
    }
    fun setParticipation(value: Boolean) = onMain { cancel(); changeParticipation(value) }
    /** 여행 다시 읽기·손들기 결정 화면 동안은 녹음과 재생을 멈추고 조회를 미룬다. 참여 상태와 조회 위치는 그대로 둔다. */
    fun setTripReady(value: Boolean) = onMain {
        if (closed || closing.get() || tripReady == value) return@onMain
        tripReady = value
        if (!value) {
            held.set(false); host.removeCallbacks(poll)
            if (state.phase in setOf(Phase.REQUESTING, Phase.TRANSMITTING, Phase.RECORDED)) {
                call?.close(); call = null; audio?.cancel(); publish(Phase.LISTENING)
            } else if (state.phase == Phase.HEARING) {
                call?.close(); call = null; incoming?.let(position::requeue); incoming = null; retryingClipId = null
                audio?.cancel(); publish(Phase.LISTENING)
            }
        } else if (current(generation.get())) {
            // 다시 읽는 동안 조회를 멈췄으므로 연결 교체와 같은 90초 이어 받기 규칙을 적용한다.
            position.resumeOrClear(host.dataEpoch(), host.elapsedRealtime())
            readFeed(generation.get()); playNext()
        }
    }
    private fun changeParticipation(value: Boolean): Boolean {
        if (!current(generation.get()) || changingParticipation || reconnecting) return false
        val known = participation ?: return false
        val own = client ?: return false
        outgoing?.erase(); outgoing = null; inbox.clear(); incoming = null; retryingClipId = null; audio?.cancel()
        changingParticipation = true; publish(Phase.LOADING)
        val token = generation.get()
        call?.close()
        call = own.executeVoiceRequest(NativeSocialRequest(
            setOf(FunctionalPurpose.ROOMS_READ, FunctionalPurpose.ROOMS_INTERACT), mutation=true,
            fetch={ api, bearer, functional, _ -> NativeTripVoiceParticipationCodec.snapshot(
                api.setVoiceTripParticipation(tripId, NativeTripVoiceParticipationCodec.patchBody(known, value),
                    functional.revision, bearer).toString().toByteArray(), tripId).also {
                        check(it.participating == value && it.memberJoinedAt == known.memberJoinedAt)
                    } })) { result ->
            if (!current(token) || client !== own) return@executeVoiceRequest
            changingParticipation = false
            result.fold(onSuccess={ updated ->
                participation = updated
                if (value) readFeed(token) else { held.set(false); permission = null; host.removeCallbacks(poll); publish(Phase.OFF) }
            }, onFailure={ failed("participation.write", it); held.set(false); unavailable("워키토키 설정을 바꾸지 못했어요") })
        }
        return true
    }
    private fun reset() {
        generation.incrementAndGet(); held.set(false); changingParticipation = false
        host.removeCallbacks(poll); call?.close(); call = null; pollCall?.close(); pollCall = null
        audio?.close(); audio = null; client?.close(); client = null; reservation?.close(); reservation = null
        permission = null; participation = null; position.clear(); incoming = null; retryingClipId = null
        outgoing?.erase(); outgoing = null; reconnecting = false
    }
    /**
     * 기능 권한 무효화·연결 끊김. 클라이언트만 닫고 참여 상태·조회 위치·받을 음성 목록·마이크 예약은 남긴다.
     * 진행 중 녹음·보낼 음성은 지금처럼 버리고(새 누름 필요), 재생 중이던 음성은 목록 앞에 다시 넣는다.
     * 새 클라이언트는 참여(revision·가입 시각)와 권한을 다시 확인한 뒤에만 남긴 위치로 조회한다.
     */
    private fun suspendForReconnect() {
        generation.incrementAndGet(); held.set(false); changingParticipation = false
        host.removeCallbacks(poll); call?.close(); call = null; pollCall?.close(); pollCall = null
        incoming?.let(position::requeue); incoming = null; retryingClipId = null
        audio?.cancel(); client?.close(); client = null
        permission = null; outgoing?.erase(); outgoing = null; reconnecting = true
    }
    private fun connect() {
        if (!current(generation.get()) || client != null) return
        if (reservation == null) reservation = host.reserveVoice()
        if (reservation == null) { publish(Phase.UNAVAILABLE, "다른 화면에서 워키토키 사용 중"); return }
        if (reconnecting) position.resumeOrClear(host.dataEpoch(), host.elapsedRealtime())
        val token = generation.incrementAndGet()
        val own = host.tripSocial(); client = own; clientConfirmed = false
        if (audio == null) audio = NativeVoiceClipAudio(host.voiceAudioBackend(), ::audioCurrent).also { it.updateSafety(safety) }
        if (!reconnecting) publish(Phase.LOADING)
        own.open(object: NativeSocialObserver {
            override fun onResourcesChanged(resources: Set<String>) {
                if (resources.any { it in setOf("devices", "voice", "rooms", "trip.$tripId.voice", "trip.$tripId.detail") } && current(token) && client === own && !changingParticipation)
                    readParticipation(token)
            }
            override fun onInvalidated() {
                if (!current(token) || client !== own) return
                // 권한 교체·연결 끊김으로 끝난 경우 운전자가 누르지 않아도 다시 연결한다(녹음은 시작하지 않는다).
                // 같은 계정 경계면 참여·조회 위치를 남겨 '준비 중'으로 돌아가지 않고, 그 사이 음성도 이어 받는다.
                if (!started || closed || !safety.permits() || invalidationReloads.take() == null) {
                    unavailable("워키토키를 다시 연결해 주세요"); return
                }
                val previous = state
                val interrupted = outgoing != null || previous.phase in setOf(Phase.REQUESTING, Phase.TRANSMITTING, Phase.RECORDED, Phase.SENDING)
                suspendForReconnect()
                // 참여를 아직 확인하지 못한 상태('준비 중'·연결 오류)는 그대로 두고, 새 클라이언트의 첫 조회가 바꾼다.
                if (previous.phase in setOf(Phase.LOADING, Phase.UNAVAILABLE)) publish(previous.phase, previous.notice)
                else publish(if (participation?.participating == false) Phase.OFF else Phase.LISTENING,
                    if (interrupted) "음성 연결이 바뀌었어요. 다시 녹음해 주세요" else null)
                connect()
            }
        }) { result ->
            if (!current(token) || client !== own) return@open
            if (result.isSuccess) readParticipation(token) else { failed("open", result.exceptionOrNull()); unavailable("워키토키를 연결하지 못했어요") }
        }
    }
    private val invalidationReloads = InvalidationReloads()
    private fun readParticipation(token: Long) {
        val own = client ?: return
        if (changingParticipation) return
        own.executeVoiceRequest(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ),
            fetch={ api, bearer, _, _ -> NativeTripVoiceParticipationCodec.snapshot(
                api.voiceTripParticipation(tripId, bearer).toString().toByteArray(), tripId) })) { result ->
            if (!current(token) || client !== own) return@executeVoiceRequest
            result.fold(onSuccess={ updated ->
                val previous = participation
                if (previous != null && (previous.revision != updated.revision || previous.memberJoinedAt != updated.memberJoinedAt)) {
                    call?.close(); call = null; pollCall?.close(); pollCall = null; host.removeCallbacks(poll)
                    held.set(false); audio?.cancel(); incoming = null; retryingClipId = null; outgoing?.erase(); outgoing = null; position.clear()
                    publish(Phase.LOADING)
                }
                participation = updated; clientConfirmed = true
                invalidationReloads.reset()
                if (!updated.participating) { host.removeCallbacks(poll); permission = null; audio?.cancel(); incoming = null; position.clear(); reconnecting = false; publish(Phase.OFF) }
                else if (pollCall == null) readFeed(token)
            }, onFailure={ failed("participation.read", it); unavailable("워키토키 설정을 불러오지 못했어요") })
        }
    }
    private fun checkedPermission(api: NativeApiClient, bearer: String, functional: FunctionalPermissions): VoiceRoomPermission {
        val result = host.tripPermission(api.voiceTripPermission(tripId, bearer).toString().toByteArray(), functional, tripId)
        val known = participation ?: error("NATIVE_VOICE_PARTICIPATION_REQUIRED")
        check(result.revision == known.revision && result.memberJoinedAt == known.memberJoinedAt &&
            VoiceDirection.entries.all { it in result.directions })
        return result
    }
    private fun readFeed(token: Long) {
        val own = client ?: return
        if (!current(token) || !clientConfirmed || !tripReady || changingParticipation || participation?.participating != true || pollCall != null) return
        host.removeCallbacks(poll)
        val after = position.cursor
        val refreshFilters = incoming != null
        pollCall = own.executeVoiceRequest(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ),
            fetch={ api, bearer, functional, _ -> Triple(checkedPermission(api, bearer, functional),
                NativeVoiceClipCodec.feed(api.voiceClips(tripId, after, bearer), after),
                if (refreshFilters) NativeVoiceClipCodec.filters(api.voiceClipFilters(tripId, bearer)) else emptySet()) },
            expires={ it.first.expiresAt.toEpochMilli() })) { result ->
            if (!current(token) || client !== own) return@executeVoiceRequest
            pollCall = null
            result.fold(onSuccess={ (checked, feed, muted) ->
                permission = checked
                inbox.removeAll { it.speakerId in muted }
                if (incoming?.speakerId in muted) {
                    call?.close(); call = null; incoming = null; retryingClipId = null; audio?.cancel(); publish(Phase.LISTENING)
                }
                val resumePress = reconnecting && held.get() && state.phase == Phase.REQUESTING
                if (after != null && after.substringBefore(':') != feed.cursor.substringBefore(':')) {
                    held.set(false); call?.close(); call = null; audio?.cancel(); incoming = null; retryingClipId = null; inbox.clear()
                    outgoing?.erase(); outgoing = null; publish(Phase.LISTENING, "음성 연결이 바뀌었어요. 다시 녹음해 주세요")
                }
                reconnecting = false
                position.advanced(feed.cursor, host.dataEpoch(), host.elapsedRealtime())
                for (clip in feed.clips) if (clip.speakerId !in muted && clip.id != incoming?.id && inbox.none { it.id == clip.id }) {
                    while (inbox.size >= 4) inbox.removeFirst()
                    inbox.addLast(clip)
                }
                if (held.get() && (state.phase == Phase.LOADING || resumePress)) prepareRecording(token)
                else if (state.phase in setOf(Phase.LOADING, Phase.UNAVAILABLE) && outgoing == null) publish(Phase.LISTENING)
                playNext()
            }, onFailure={ error ->
                if (state.phase != Phase.UNAVAILABLE) failed("feed", error)
                if (authorityFailure(error) || (error as? NativeSocialFailure)?.kind == NativeSocialFailure.Kind.NOT_FOUND)
                    unavailable("워키토키를 다시 연결해 주세요")
                else if (state.phase !in setOf(Phase.TRANSMITTING, Phase.RECORDED, Phase.SENDING, Phase.HEARING)) {
                    // 녹음 준비 중(연결 교체 중의 누름 포함)이던 누름도 끝낸다. 남기면 회복 뒤 재생과 새 누름이 막힌다.
                    if (state.phase == Phase.REQUESTING) { held.set(false); call?.close(); call = null }
                    publish(Phase.UNAVAILABLE, "음성을 받지 못했어요. 다시 연결해 주세요")
                }
            })
            if (current(token) && client === own) host.postDelayed(poll, 1000)
        }
    }
    private fun prepareRecording(token: Long) {
        val own = client ?: return
        if (!held.get() || !current(token)) return
        publish(Phase.REQUESTING)
        call?.close()
        call = own.executeVoiceRequest(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ, FunctionalPurpose.ROOMS_INTERACT),
            fetch={ api, bearer, functional, _ -> checkedPermission(api, bearer, functional) }, expires={ it.expiresAt.toEpochMilli() })) { result ->
            if (!current(token) || client !== own || !held.get() || state.phase != Phase.REQUESTING) return@executeVoiceRequest
            call = null
            result.fold(onSuccess={ checked ->
                permission = checked; recordStartedAt = host.elapsedRealtime(); publish(Phase.TRANSMITTING)
                if (audio?.record(complete={ pcm -> onMain {
                    if (!current(token) || state.phase !in setOf(Phase.TRANSMITTING, Phase.RECORDED)) { pcm.fill(0); return@onMain }
                    held.set(false)
                    outgoing = Outgoing(UUID.randomUUID().toString().replace("-", ""), pcm, recordStartedAt)
                    sendOutgoing(token)
                } }, interrupted={ onMain {
                    if (current(token) && state.phase == Phase.TRANSMITTING) { held.set(false); publish(Phase.LISTENING, "녹음이 중단됐어요. 다시 눌러 주세요"); playNext() }
                } }, full={ onMain {
                    if (current(token) && state.phase == Phase.TRANSMITTING) { publish(Phase.RECORDED); expireRecorded(token, recordStartedAt) }
                } }) != true) { held.set(false); publish(Phase.LISTENING, "마이크를 준비하지 못했어요") }
            }, onFailure={ failed("permission", it); held.set(false); unavailable("워키토키 이용 권한을 확인하지 못했어요") })
        }
    }
    private fun sendOutgoing(token: Long) {
        val own = client ?: return
        val draft = outgoing ?: return
        if (!current(token) || state.phase == Phase.SENDING) return
        if (voiceDraftRemainingMs(draft.recordedAt, host.elapsedRealtime()) == 0L) {
            draft.erase(); outgoing = null; publish(Phase.LISTENING, VOICE_DRAFT_EXPIRED); return
        }
        publish(Phase.SENDING)
        call?.close()
        call = own.executeVoiceRequest(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ, FunctionalPurpose.ROOMS_INTERACT), mutation=true,
            fetch={ api, bearer, functional, account ->
                checkedPermission(api, bearer, functional)
                NativeVoiceClipCodec.metadata(api.uploadVoiceClip(tripId, NativeVoiceClipCodec.upload(draft.id, draft.pcm), functional.revision, bearer)).also {
                    check(it.durationMs == draft.pcm.size / 32 && it.speakerId == account)
                }
            })) { result ->
            if (!current(token) || client !== own || outgoing !== draft) return@executeVoiceRequest
            call = null
            result.fold(onSuccess={ _ ->
                draft.erase(); outgoing = null; publish(Phase.LISTENING, "음성을 보냈어요"); playNext()
            }, onFailure={ error ->
                failed("upload", error)
                if (authorityFailure(error)) unavailable("워키토키를 다시 연결해 주세요")
                else if (NativeVoiceClipFailures.canRetryUpload(error)) publish(Phase.UNAVAILABLE, "보내지 못했어요. 다시 시도해 주세요")
                else { draft.erase(); outgoing = null; publish(Phase.LISTENING, "음성을 보내지 못했어요. 다시 녹음해 주세요"); playNext() }
            })
        }
    }
    /** A finished recording waits for 보내기/취소 only until it could still be sent; then the floor is returned to playback. */
    private fun expireRecorded(token: Long, startedAt: Long) {
        host.postDelayed({
            if (current(token) && state.phase == Phase.RECORDED && recordStartedAt == startedAt) {
                held.set(false); audio?.cancel(); publish(Phase.LISTENING, VOICE_DRAFT_EXPIRED); playNext()
            }
        }, voiceDraftRemainingMs(startedAt, host.elapsedRealtime()))
    }
    private fun playNext() {
        if (!current(generation.get()) || !tripReady || reconnecting || state.phase != Phase.LISTENING || outgoing != null || incoming != null || held.get()) return
        val metadata = inbox.pollFirst() ?: return
        val own = client ?: return
        val token = generation.get()
        incoming = metadata; publish(Phase.HEARING)
        call = own.executeVoiceRequest(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ),
            fetch={ api, bearer, _, _ -> NativeVoiceClipCodec.clip(api.voiceClip(tripId, metadata.id, bearer), metadata) }, discard={ it.erase() })) { result ->
            if (!current(token) || client !== own || incoming !== metadata) { result.getOrNull()?.erase(); return@executeVoiceRequest }
            call = null
            result.fold(onSuccess={ clip ->
                retryingClipId = null
                if (audio?.play(clip.pcm) { completed -> onMain {
                    if (current(token) && incoming === metadata) { incoming = null; publish(Phase.LISTENING, if (completed) null else "음성 재생이 중단됐어요"); playNext() }
                } } != true) { clip.erase(); incoming = null; publish(Phase.LISTENING); playNext() }
            }, onFailure={ error ->
                incoming = null
                if (authorityFailure(error)) unavailable("워키토키를 다시 연결해 주세요")
                else if ((error as? NativeSocialFailure)?.kind in setOf(NativeSocialFailure.Kind.UNAVAILABLE, NativeSocialFailure.Kind.RATE_LIMITED) &&
                    retryingClipId != metadata.id) {
                    retryingClipId = metadata.id
                    while (inbox.size >= 4) inbox.removeLast()
                    inbox.addFirst(metadata); publish(Phase.LISTENING, "받은 음성 다시 불러오는 중")
                }
                else { retryingClipId = null; publish(Phase.LISTENING, "받은 음성을 재생하지 못했어요"); playNext() }
            })
        }
    }
    /** Step and mapped kind/status/server code only; no token, trip id or audio. */
    private fun failed(step: String, error: Throwable?) {
        host.warn("native.voice.trip: $step failed " + (error?.let(NativeSocialErrorCodec::fields) ?: "kind=none"))
    }
    private fun authorityFailure(error: Throwable) = NativeVoiceClipFailures.contextEnded(error)
    private fun unavailable(notice: String) { reset(); publish(Phase.UNAVAILABLE, notice) }
    override fun close() {
        if (!closing.compareAndSet(false, true)) return
        held.set(false)
        onMain { if (!closed) { closed = true; started = false; reset() } }
    }
}

internal const val VOICE_DRAFT_LIFETIME_MS = 60_000L
/** 서버가 원음을 RAM에 두는 최대 시간. 이보다 오래 조회하지 못한 위치로는 이어 받지 않는다. */
internal const val VOICE_CLIP_RETENTION_MS = 90_000L

/**
 * 연결 교체 뒤 이어 받을 음성 조회 위치와 아직 재생하지 않은 음성 목록. 같은 계정·연결 경계(epoch)이고 마지막 조회가
 * 서버 보관 한도 안일 때만 이어 받는다. 그 밖(계정 변경·잠금·오래 끊김)은 처음 조회처럼 현재 위치부터 받는다.
 * 참여 해제·재가입(revision·가입 시각 변경)과 여행 변경은 호출부가 [clear]하거나 새 controller를 만든다.
 */
internal class TripVoiceFeedPosition(private val retentionMs: Long = VOICE_CLIP_RETENTION_MS) {
    var cursor: String? = null
        private set
    val inbox = ArrayDeque<NativeVoiceClipMetadata>()
    private var epoch = -1L
    private var readAt = 0L
    fun advanced(cursor: String, epoch: Long, now: Long) { this.cursor = cursor; this.epoch = epoch; readAt = now }
    fun resumable(epoch: Long, now: Long) = cursor != null && epoch == this.epoch && now - readAt in 0..retentionMs
    /** 다시 연결할 때 이어 받을 수 있으면 그대로 두고 true, 아니면 위치와 목록을 비운다. */
    fun resumeOrClear(epoch: Long, now: Long): Boolean = resumable(epoch, now).also { if (!it) clear() }
    /** 끊겨서 다 듣지 못한 음성은 목록 앞에 다시 둔다. 목록은 최대 [INBOX_LIMIT]개다. */
    fun requeue(clip: NativeVoiceClipMetadata) {
        if (inbox.any { it.id == clip.id }) return
        while (inbox.size >= INBOX_LIMIT) inbox.removeLast()
        inbox.addFirst(clip)
    }
    fun clear() { cursor = null; epoch = -1L; readAt = 0L; inbox.clear() }
    companion object { const val INBOX_LIMIT = 4 }
}
private const val VOICE_DRAFT_EXPIRED = "전송 시간이 지났어요. 다시 녹음해 주세요"

/** Remaining time before a recorded clip is too old to send. */
internal fun voiceDraftRemainingMs(recordedAt: Long, now: Long): Long =
    (recordedAt + VOICE_DRAFT_LIFETIME_MS - now).coerceAtLeast(0L)

/** controller가 쓰는 차량 연결·메인 스레드·시계 경계. 운영은 [VehicleTripVoiceHost]이고 단위 시험만 가짜로 바꾼다. */
internal interface TripVoiceHost {
    fun onMainThread(): Boolean
    fun post(action: Runnable)
    fun postDelayed(action: Runnable, delayMs: Long)
    fun removeCallbacks(action: Runnable)
    fun elapsedRealtime(): Long
    fun socialNow(): Long
    fun dataEpoch(): Long
    fun reserveVoice(): Closeable?
    fun tripSocial(): TripVoiceClient
    fun voiceAudioBackend(): NativeVoiceAudioBackend
    fun tripPermission(bytes: ByteArray, functional: FunctionalPermissions, tripId: String): VoiceRoomPermission
    fun warn(message: String)
}
/** controller가 쓰는 [NativeSocialClient]의 부분. */
internal interface TripVoiceClient: Closeable {
    fun status(): NativeSocialClient.State
    fun open(observer: NativeSocialObserver, callback: (Result<Unit>) -> Unit)
    fun <T> executeVoiceRequest(request: NativeSocialRequest<T>, callback: (Result<T>) -> Unit): Closeable
}
private class VehicleTripVoiceHost(private val connection: VehicleConnection): TripVoiceHost {
    private val main = Handler(Looper.getMainLooper())
    override fun onMainThread() = Looper.myLooper() == Looper.getMainLooper()
    override fun post(action: Runnable) { main.post(action) }
    override fun postDelayed(action: Runnable, delayMs: Long) { main.postDelayed(action, delayMs) }
    override fun removeCallbacks(action: Runnable) = main.removeCallbacks(action)
    override fun elapsedRealtime() = SystemClock.elapsedRealtime()
    override fun socialNow() = connection.socialNow()
    override fun dataEpoch() = connection.dataEpoch()
    override fun reserveVoice() = connection.reserveVoice()
    override fun tripSocial(): TripVoiceClient {
        val social = connection.tripSocial()
        return object: TripVoiceClient {
            override fun status() = social.status()
            override fun open(observer: NativeSocialObserver, callback: (Result<Unit>) -> Unit) = social.open(observer, callback)
            override fun <T> executeVoiceRequest(request: NativeSocialRequest<T>, callback: (Result<T>) -> Unit) =
                social.executeVoiceRequest(request, callback)
            override fun close() = social.close()
        }
    }
    override fun voiceAudioBackend() = connection.voiceAudioBackend()
    override fun tripPermission(bytes: ByteArray, functional: FunctionalPermissions, tripId: String) =
        connection.loadVoiceCodec().tripPermission(bytes, functional, tripId, connection.socialNow())
    override fun warn(message: String) { WegoLog.w("WegoH", message) }
}
