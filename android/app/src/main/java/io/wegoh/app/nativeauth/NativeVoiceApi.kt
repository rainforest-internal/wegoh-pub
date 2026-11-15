package io.wegoh.app.nativeauth

import android.content.Context
import android.os.Handler
import android.os.Looper
import org.json.JSONObject
import java.io.Closeable
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference

interface NativeVoiceObserver {
    fun onState(state: NativeVoiceClient.State) {}
    /** Clear host-owned room data. Already copied host memory cannot be recalled. */
    fun onInvalidated() {}
}
class NativeVoiceFailure internal constructor(val kind: Kind, val httpStatus: Int? = null):
    IllegalStateException("NATIVE_VOICE_" + kind.name) {
    enum class Kind { CLOSED, UNAVAILABLE, ALREADY_OPEN, CONSENT_REQUIRED, FORBIDDEN, NOT_FOUND, STALE, INVALID_RESPONSE }
    override fun toString() = "NativeVoiceFailure(" + kind.name + ")"
}

/** Canonical packaged contract only. Absence is unavailable; there is no old-hash fallback. */
internal object NativeVoiceContract {
    fun load(context: Context): NativeVoiceCodec {
        return decodeWire(context.assets.open("native_access_wire.json").use { readBundledNativeAccessWire(it) })
    }
    /** Uses the startup contract's limit. A separate smaller Voice limit rejected the grown asset before any request. */
    internal fun decode(bytes: ByteArray): NativeVoiceCodec = bytes.inputStream().use { decodeWire(readBundledNativeAccessWire(it)) }
    private fun decodeWire(wire: JSONObject): NativeVoiceCodec {
        exactInteger(wire.get("schemaVersion"), 1L)
        val contract = wire.getJSONObject("functional").getJSONObject("roomVoice")
        exactInteger(contract.get("authorizationVersion"), 1L)
        check(contract.get("nativePath") == "/v1/native/rooms/{room}/voice-permissions")
        val list = contract.getJSONObject("roomList")
        check(list.get("method") == "GET" && list.get("path") == "/v1/native/voice-rooms")
        exactInteger(list.get("pageSize"), 20L)
        check(list.get("requiresCurrentRoomVoiceNotice") == true && list.get("cursorPattern") == "^[a-f0-9]{32}$")
        fun fields(key: String, vararg names: String) {
            val a = list.getJSONArray(key); val values = (0 until a.length()).map { a.get(it).also { v -> check(v is String) } as String }
            check(values.size == names.size && values.toSet() == names.toSet())
        }
        fields("responseFields", "authorizationVersion", "deviceId", "grantId", "functionalRevision", "items", "nextCursor")
        fields("itemFields", "roomId", "name", "availableDirections", "revision", "memberJoinedAt", "expiresAt")
        val version = contract.get("disclosureVersion"); check(version is Int || version is Long)
        val number = (version as Number).toLong(); check(number in 1..Int.MAX_VALUE.toLong())
        return NativeVoiceCodec(number.toInt(), contract.get("disclosureSha256") as String)
    }
    private fun exactInteger(raw: Any, expected: Long) {
        check(raw is Int || raw is Long)
        check((raw as Number).toLong() == expected)
    }
}

/** First public Voice stage: one owned base feed and an authorized room catalogue.
 * SELECTING means only that this channel is current; it never means audio or Voice101.
 * No room roster permission, opposite direction or consent is implied by opening it.
 */
class NativeVoiceClient internal constructor(private val connection: VehicleConnection): Closeable {
    enum class State { UNOPENED, OPENING, SELECTING, UNAVAILABLE, CLOSED }
    private val main = Handler(Looper.getMainLooper())
    private val guard = Any()
    private val generation = AtomicLong(0)
    @Volatile private var state = State.UNOPENED
    private var session: NativeSocialClient? = null
    private var reservation: Closeable? = null
    private var baseEpoch = -1L
    private var codec: NativeVoiceCodec? = null
    private var observer: NativeVoiceObserver? = null
    private var opening: ((Result<Unit>) -> Unit)? = null
    private var page: PageCall? = null
    private var joined: NativeVoiceSession? = null
    private var joining: Closeable? = null
    private var safety = NativeVoiceAudioSafety()
    fun status(): State = state

    fun open(observer: NativeVoiceObserver, callback: (Result<Unit>) -> Unit) {
        val token = synchronized(guard) {
            if (state in setOf(State.CLOSED, State.OPENING, State.SELECTING)) {
                val failure = NativeVoiceFailure(if (state == State.CLOSED) NativeVoiceFailure.Kind.CLOSED else NativeVoiceFailure.Kind.ALREADY_OPEN)
                main.post { callback(Result.failure(failure)) }; return
            }
            val expectedBase = connection.dataEpoch()
            if (!connection.socialBaseCurrent(expectedBase)) {
                main.post { callback(Result.failure(NativeVoiceFailure(NativeVoiceFailure.Kind.UNAVAILABLE))) }; return
            }
            generation.incrementAndGet().also {
                state = State.OPENING; this.observer = observer; opening = callback; codec = null; baseEpoch = expectedBase
            }
        }
        main.post { if (generation.get() == token && state == State.OPENING) observer.onState(State.OPENING) }
        val slot = connection.reserveVoice()
        if (slot == null) { end(false, NativeVoiceFailure.Kind.UNAVAILABLE, token); return }
        var own: NativeSocialClient? = null
        try {
            val channel = connection.social(); own = channel
            val adopted = synchronized(guard) {
                if (generation.get() != token || state != State.OPENING) false
                else { session = channel; reservation = slot; true }
            }
            if (!adopted) { channel.close(); slot.close(); return }
            channel.open(object: NativeSocialObserver {
                override fun onInvalidated() { end(false, NativeVoiceFailure.Kind.UNAVAILABLE, token) }
            }) channelReady@{ opened ->
                if (opened.isFailure) { end(false, NativeVoiceFailure.Kind.UNAVAILABLE, token); return@channelReady }
                // Reuse C2's atomic current-permission check/adopt on its worker. No token leaves the SDK.
                channel.executeVoiceRequest(NativeSocialRequest(emptySet(), fetch={ _, _, _, _ -> connection.loadVoiceCodec() })) { result ->
                    result.fold(onSuccess={ value ->
                        val notify = synchronized(guard) {
                            if (!openingCurrent(token, channel)) null
                            else { codec = value; state = State.SELECTING; val cb = opening; opening = null; this.observer to cb }
                        }
                        if (notify == null) end(false, NativeVoiceFailure.Kind.STALE, token)
                        else { notify.first?.onState(State.SELECTING); notify.second?.invoke(Result.success(Unit)) }
                    }, onFailure={ end(false, NativeVoiceFailure.Kind.UNAVAILABLE, token) })
                }
            }
            // Catch invalidation that happened before the child entered OPENING and
            // therefore could not terminate that child via the manager registry.
            if (!connection.socialBaseCurrent(baseEpoch)) end(false, NativeVoiceFailure.Kind.UNAVAILABLE, token)
        } catch (_: Exception) {
            if (own == null) slot.close()
            end(false, NativeVoiceFailure.Kind.UNAVAILABLE, token)
        }
    }
    private fun openingCurrent(token: Long, own: NativeSocialClient) = generation.get() == token && state == State.OPENING &&
        session === own && own.status() == NativeSocialClient.State.READY && connection.socialBaseCurrent(baseEpoch)
    private fun current(token: Long, own: NativeSocialClient) = generation.get() == token && state == State.SELECTING &&
        session === own && own.status() == NativeSocialClient.State.READY && connection.socialBaseCurrent(baseEpoch)

    private inner class PageCall: Closeable {
        val cancelled = AtomicBoolean(false)
        var handle: Closeable? = null
        override fun close() {
            if (!cancelled.compareAndSet(false, true)) return
            val old = synchronized(guard) { val old = handle; handle = null; if (page === this) page = null; old }
            old?.close()
        }
    }
    /** Names are current owner projections, not a roster, authority or permission to join. */
    fun listRooms(cursor: VoiceRoomCursor? = null, callback: (Result<VoiceRoomPage>) -> Unit): Closeable {
        val token = generation.get(); val call = PageCall()
        val selected = synchronized(guard) {
            val own = session; val decoder = codec
            if (own == null || decoder == null || !current(token, own) || page != null) null
            else { page = call; own to decoder }
        }
        if (selected == null) {
            main.post { if (!call.cancelled.get()) callback(Result.failure(NativeVoiceFailure(if (state == State.CLOSED) NativeVoiceFailure.Kind.CLOSED else NativeVoiceFailure.Kind.UNAVAILABLE))) }
            return call
        }
        val own = selected.first
        try {
            val handle = own.executeVoiceRequest(NativeSocialRequest(emptySet(),
                VoiceDirection.entries.map { it.purpose }.toSet(), fetch={ api, tokenValue, permission, _ ->
                    selected.second.rooms(api.voiceRooms(cursor?.encoded, tokenValue).toString().toByteArray(Charsets.UTF_8),
                        permission, cursor, connection.socialNow())
                }, expires={ it.items.minOfOrNull { item -> item.expiresAt.toEpochMilli() } })) { result ->
                val deliver = synchronized(guard) {
                    if (page !== call || call.cancelled.get() || !current(token, own)) false
                    else { page = null; call.handle = null; true }
                }
                if (deliver) callback(result.fold(onSuccess={ Result.success(it) }, onFailure={ Result.failure(failure(it)) }))
            }
            val close = synchronized(guard) {
                if (page !== call || call.cancelled.get() || !current(token, own)) true else { call.handle = handle; false }
            }
            if (close) handle.close()
        } catch (_: Exception) { call.close(); main.post { if (current(token, own)) callback(Result.failure(NativeVoiceFailure(NativeVoiceFailure.Kind.UNAVAILABLE))) } }
        return call
    }

    /** One trip's current answer for this car. Empty directions mean a setting is off; this never turns anything on. */
    fun tripRoom(trip: String, name: String, callback: (Result<VoiceRoomReference>) -> Unit): Closeable {
        val token = generation.get(); val call = PageCall()
        val selected = synchronized(guard) {
            val own = session; val decoder = codec
            if (own == null || decoder == null || !current(token, own) || page != null) null
            else { page = call; own to decoder }
        }
        if (selected == null) {
            main.post { if (!call.cancelled.get()) callback(Result.failure(NativeVoiceFailure(if (state == State.CLOSED) NativeVoiceFailure.Kind.CLOSED else NativeVoiceFailure.Kind.UNAVAILABLE))) }
            return call
        }
        val own = selected.first
        try {
            val handle = own.executeVoiceRequest(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ),
                fetch={ api, tokenValue, permission, _ ->
                    val value = selected.second.tripPermission(api.voiceTripPermission(trip, tokenValue).toString().toByteArray(Charsets.UTF_8),
                        permission, trip, connection.socialNow())
                    VoiceRoomReference(trip, name, value.directions, value.revision, value.memberJoinedAt, value.expiresAt,
                        permission.deviceId, permission.grantId, permission.revision, true)
                }, expires={ it.expiresAt.toEpochMilli() })) { result ->
                val deliver = synchronized(guard) {
                    if (page !== call || call.cancelled.get() || !current(token, own)) false
                    else { page = null; call.handle = null; true }
                }
                if (deliver) callback(result.fold(onSuccess={ Result.success(it) }, onFailure={ Result.failure(failure(it)) }))
            }
            val close = synchronized(guard) {
                if (page !== call || call.cancelled.get() || !current(token, own)) true else { call.handle = handle; false }
            }
            if (close) handle.close()
        } catch (_: Exception) { call.close(); main.post { if (current(token, own)) callback(Result.failure(NativeVoiceFailure(NativeVoiceFailure.Kind.UNAVAILABLE))) } }
        return call
    }

    /** Host must supply current foreground and actual CarUx observation. Unknown fails closed. */
    fun updateSafety(foreground: Boolean, carUxAllowed: Boolean?) {
        val value = NativeVoiceAudioSafety(foreground, carUxAllowed)
        val audio = synchronized(guard) { safety = value; joined }
        audio?.updateSafety(value)
    }
    /** Selection references cannot confer consent or survive a changed membership/revision. */
    fun join(room: VoiceRoomReference, direction: VoiceDirection, observer: NativeVoiceSessionObserver,
        callback: (Result<NativeVoiceSession>) -> Unit) = join(room, direction, observer, false, callback)
    fun joinTrip(room: VoiceRoomReference, observer: NativeVoiceSessionObserver,
        callback: (Result<NativeVoiceSession>) -> Unit) {
        require(room.trip)
        join(room, VoiceDirection.TRANSMIT, observer, true, callback)
    }
    private fun join(room: VoiceRoomReference, direction: VoiceDirection, observer: NativeVoiceSessionObserver,
        duplex: Boolean, callback: (Result<NativeVoiceSession>) -> Unit) {
        val token = generation.get()
        val selected = synchronized(guard) {
            val own = session; val decoder = codec
            if (own == null || decoder == null || !current(token, own) || !safety.permits() ||
                joined?.status()?.let { it != NativeVoiceSession.State.CLOSED } == true || joining != null) null
            else own to decoder
        }
        if (selected == null) { main.post { callback(Result.failure(NativeVoiceFailure(NativeVoiceFailure.Kind.UNAVAILABLE))) }; return }
        val own = selected.first
        val validUntil = AtomicLong(room.expiresAt.toEpochMilli())
        val actor = AtomicReference<String?>(null)
        val audio = NativeVoiceSession(direction, connection.voiceAudioBackend(),
            { current(token, own) && connection.socialNow() < validUntil.get() }, observer, duplex, { actor.get() })
        synchronized(guard) { joined = audio; audio.updateSafety(safety) }
        val purposes = if (room.trip) setOf(FunctionalPurpose.ROOMS_READ, FunctionalPurpose.ROOMS_INTERACT) else setOf(direction.purpose)
        val call = own.executeVoiceRequest(NativeSocialRequest(purposes, fetch={ api, bearer, permissions, account ->
            check(room.deviceId == permissions.deviceId && room.grantId == permissions.grantId &&
                room.functionalRevision == permissions.revision && direction in room.availableDirections &&
                (!duplex || VoiceDirection.entries.all { it in room.availableDirections }) &&
                connection.socialNow() < room.expiresAt.toEpochMilli())
            val permission = if (room.trip) selected.second.tripPermission(api.voiceTripPermission(room.roomId, bearer).toString().toByteArray(Charsets.UTF_8),
                permissions, room.roomId, connection.socialNow())
            else selected.second.roomPermission(api.voiceRoomPermission(room.roomId, bearer).toString().toByteArray(Charsets.UTF_8),
                permissions, room.roomId, connection.socialNow())
            check(direction in permission.directions && permission.revision == room.revision &&
                (!duplex || VoiceDirection.entries.all { it in permission.directions }) &&
                permission.memberJoinedAt == room.memberJoinedAt)
            validUntil.set(minOf(validUntil.get(), permission.expiresAt.toEpochMilli()))
            actor.set(account)
            val socket = api.connectVoice(room.roomId, permissions.revision, permission.revision, bearer, audio.listener, room.trip)
            audio.attach(socket)
            audio
        }, expires={ validUntil.get() }, discard={ it.close() })) { result ->
            synchronized(guard) { joining = null }
            result.fold(onSuccess={
                if (current(token, own) && it.adopt()) callback(Result.success(it))
                else { it.close(); callback(Result.failure(NativeVoiceFailure(NativeVoiceFailure.Kind.STALE))) }
            }, onFailure={ audio.close(); callback(Result.failure(failure(it))) })
        }
        synchronized(guard) { if (current(token, own)) joining = call else { call.close(); audio.close() } }
    }

    private fun failure(error: Throwable): NativeVoiceFailure {
        val social = error as? NativeSocialFailure ?: return NativeVoiceFailure(NativeVoiceFailure.Kind.UNAVAILABLE)
        val kind = when (social.kind) {
            NativeSocialFailure.Kind.CONSENT_REQUIRED -> NativeVoiceFailure.Kind.CONSENT_REQUIRED
            NativeSocialFailure.Kind.FORBIDDEN -> NativeVoiceFailure.Kind.FORBIDDEN
            NativeSocialFailure.Kind.NOT_FOUND -> NativeVoiceFailure.Kind.NOT_FOUND
            NativeSocialFailure.Kind.STALE, NativeSocialFailure.Kind.CONFLICT -> NativeVoiceFailure.Kind.STALE
            NativeSocialFailure.Kind.INVALID_RESPONSE -> NativeVoiceFailure.Kind.INVALID_RESPONSE
            NativeSocialFailure.Kind.CLOSED -> NativeVoiceFailure.Kind.CLOSED
            else -> NativeVoiceFailure.Kind.UNAVAILABLE
        }
        return NativeVoiceFailure(kind, social.httpStatus)
    }
    private fun end(closed: Boolean, kind: NativeVoiceFailure.Kind, expected: Long? = null) {
        var endedAt = 0L
        val old = synchronized(guard) {
            if (expected != null && generation.get() != expected || state == State.CLOSED ||
                !closed && state in setOf(State.UNOPENED, State.UNAVAILABLE)) return
            val active = state in setOf(State.OPENING, State.SELECTING)
            endedAt = generation.incrementAndGet(); state = if (closed) State.CLOSED else State.UNAVAILABLE
            val values = Triple(session, reservation, page); session = null; reservation = null; page = null; codec = null
            val completion = opening; opening = null
            Triple(values, completion, if (active) observer else null)
        }
        synchronized(guard) { joining?.close(); joining = null; joined?.close(); joined = null }
        old.first.third?.close(); old.first.first?.close(); old.first.second?.close()
        main.post {
            old.third?.onInvalidated()
            if (generation.get() == endedAt) old.third?.onState(if (closed) State.CLOSED else State.UNAVAILABLE)
            // Captured opening completion must survive a later explicit reopen or close.
            old.second?.invoke(Result.failure(NativeVoiceFailure(kind)))
        }
    }
    override fun close() = end(true, NativeVoiceFailure.Kind.CLOSED)
}
