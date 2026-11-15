package io.wegoh.app.nativeauth

import org.json.JSONObject
import java.time.Instant
import java.time.OffsetDateTime

internal object NativeTripVoiceParticipationCodec {
    private val ID = Regex("[a-f0-9]{32}")
    private fun revision(value: Any): Long {
        check(value is Int || value is Long)
        return (value as Number).toLong().also { check(it in 1..Int.MAX_VALUE.toLong()) }
    }
    private fun joined(value: String): Instant {
        check(value.length in 1..64)
        return OffsetDateTime.parse(value).toInstant()
    }
    fun snapshot(bytes: ByteArray, trip: String): VoiceTripParticipation {
        check(ID.matches(trip))
        val value = StrictNativeJson.parseBusiness(bytes, 4096)
        check(value.keys().asSequence().toSet() == setOf("tripId", "participating", "memberJoinedAt", "revision"))
        val id = value.get("tripId"); check(id is String && ID.matches(id) && id == trip)
        val participating = value.get("participating"); check(participating is Boolean)
        val memberJoinedAt = value.get("memberJoinedAt"); check(memberJoinedAt is String)
        return VoiceTripParticipation(id, participating, joined(memberJoinedAt), revision(value.get("revision")), memberJoinedAt)
    }
    fun patchBody(current: VoiceTripParticipation, participating: Boolean): JSONObject {
        check(ID.matches(current.tripId))
        revision(current.revision)
        check(joined(current.memberJoinedAtWire) == current.memberJoinedAt)
        return JSONObject().put("participating", participating).put("memberJoinedAt", current.memberJoinedAtWire)
            .put("revision", current.revision)
    }
}

/** Closed business projections only. Does not change canonical/authentication JSON parsing. */
internal class NativeVoiceCodec(private val noticeVersion: Int, private val noticeSha256: String) {
    init { check(noticeVersion > 0 && Regex("[a-f0-9]{64}").matches(noticeSha256)) }

    fun rooms(bytes: ByteArray, permission: FunctionalPermissions, after: VoiceRoomCursor?, now: Long): VoiceRoomPage {
        val value = StrictNativeJson.parseBusiness(bytes, 32768)
        fields(value, "authorizationVersion", "deviceId", "grantId", "functionalRevision", "items", "nextCursor")
        authority(value, permission, now)
        val array = value.getJSONArray("items"); check(array.length() <= 20)
        var previous = after?.encoded
        val items = (0 until array.length()).map { index ->
            val item = array.getJSONObject(index)
            fields(item, "roomId", "name", "availableDirections", "revision", "memberJoinedAt", "expiresAt")
            val room = id(item, "roomId"); check(previous == null || room > previous!!); previous = room
            val directions = directions(item.getJSONArray("availableDirections"), permission)
            check(directions.isNotEmpty())
            VoiceRoomReference(room, text(item, "name", 80), directions, integer(item, "revision", 1),
                joined(item), expiry(item, permission, now), permission.deviceId, permission.grantId, permission.revision)
        }
        val next = if (value.isNull("nextCursor")) null else VoiceRoomCursor(id(value, "nextCursor")).also {
            check(items.size == 20 && it.encoded == items.last().roomId)
        }
        return VoiceRoomPage(items, next)
    }

    fun roomPermission(bytes: ByteArray, permission: FunctionalPermissions, room: String, now: Long) =
        snapshot(bytes, permission, room, now, false)
    /** A trip room may be on at revision 0: the member's own trip voice setting, decided by the server. */
    fun tripPermission(bytes: ByteArray, permission: FunctionalPermissions, trip: String, now: Long) =
        snapshot(bytes, permission, trip, now, true)
    private fun snapshot(bytes: ByteArray, permission: FunctionalPermissions, room: String, now: Long, trip: Boolean): VoiceRoomPermission {
        check(ID.matches(room))
        val value = StrictNativeJson.parseBusiness(bytes, 8192)
        val common = arrayOf("authorizationVersion", "deviceId", "grantId", "revision", "functionalRevision",
            "memberJoinedAt", "expiresAt", "permissions", "roomVoiceDisclosureVersion", "roomVoiceDisclosureSha256")
        if (trip) { fields(value, *common, "tripId", "contractVersion"); check(integer(value, "contractVersion", 1, 1) == 1L) }
        else fields(value, *common, "roomId")
        authority(value, permission, now, trip); check(id(value, if (trip) "tripId" else "roomId") == room)
        check(integer(value, "roomVoiceDisclosureVersion", 1) == noticeVersion.toLong())
        check(value.get("roomVoiceDisclosureSha256") == noticeSha256)
        val flags = value.getJSONObject("permissions"); fields(flags, "receiveVoice", "transmitVoice")
        val directions = linkedSetOf<VoiceDirection>()
        if (boolean(flags, "receiveVoice")) directions.add(VoiceDirection.RECEIVE)
        if (boolean(flags, "transmitVoice")) directions.add(VoiceDirection.TRANSMIT)
        check(trip || directions.all { permission.allows(it.purpose) })
        val revision = integer(value, "revision", 0); if (revision == 0L && !trip) check(directions.isEmpty())
        return VoiceRoomPermission(room, revision, permission.revision, joined(value), expiry(value, permission, now), directions)
    }

    private fun authority(value: JSONObject, permission: FunctionalPermissions, now: Long, trip: Boolean = false) {
        check(integer(value, "authorizationVersion", 1) == 1L)
        check(id(value, "deviceId") == permission.deviceId && id(value, "grantId") == permission.grantId)
        check(integer(value, "functionalRevision", 1) == permission.revision)
        check(now < permission.expiresAtMillis && if (trip) permission.allows(FunctionalPurpose.ROOMS_READ)
            else VoiceDirection.entries.any { permission.allows(it.purpose) })
    }
    private fun expiry(value: JSONObject, permission: FunctionalPermissions, now: Long): Instant {
        val seconds = integer(value, "expiresAt", 0, 253402300799L)
        check(seconds > now / 1000 && seconds <= permission.expiresAtMillis / 1000)
        return Instant.ofEpochSecond(seconds)
    }
    private fun joined(value: JSONObject): Instant {
        val parsed = OffsetDateTime.parse(text(value, "memberJoinedAt", 40))
        return parsed.toInstant()
    }
    private fun directions(array: org.json.JSONArray, permission: FunctionalPermissions): Set<VoiceDirection> {
        check(array.length() in 1..2)
        val result = (0 until array.length()).map { index ->
            val raw = array.get(index); check(raw is String)
            VoiceDirection.entries.singleOrNull { it.wire == raw } ?: invalid()
        }
        check(result.distinct().size == result.size && result.all { permission.allows(it.purpose) })
        check(result == VoiceDirection.entries.filter { it in result }); return result.toSet()
    }
    companion object {
        const val PCM_BYTES = 640
        const val FRAME_BYTES = 644
        private val ID = Regex("[a-f0-9]{32}")
        private fun invalid(): Nothing = error("NATIVE_VOICE_RESPONSE_INVALID")
        private fun fields(value: JSONObject, vararg keys: String) { check(value.keys().asSequence().toSet() == keys.toSet()) }
        private fun text(value: JSONObject, key: String, max: Int): String = (value.get(key) as? String ?: invalid()).also {
            check(it.isNotBlank() && it.codePointCount(0, it.length) <= max)
            check(it.codePoints().toArray().none { c -> c < 32 || c in 127..159 || c in 0xd800..0xdfff })
        }
        private fun id(value: JSONObject, key: String) = text(value, key, 32).also { check(ID.matches(it)) }
        private fun integer(value: JSONObject, key: String, min: Long, max: Long = Int.MAX_VALUE.toLong()): Long {
            val raw = value.get(key); check(raw is Int || raw is Long)
            return (raw as Number).toLong().also { check(it in min..max) }
        }
        private fun boolean(value: JSONObject, key: String) = value.get(key).also { check(it is Boolean) } as Boolean
        private fun floor(value: JSONObject): VoiceFloor {
            fields(value, "leaseId", "speakerId")
            val speaker = text(value, "speakerId", 45); check(Regex("team-[a-f0-9]{40}").matches(speaker))
            return VoiceFloor(id(value, "leaseId"), speaker)
        }
        fun event(bytes: ByteArray): VoiceServerEvent {
            val value = StrictNativeJson.parseBusiness(bytes, 4096)
            return when (value.get("type")) {
                "ready" -> {
                    fields(value, "type", "format", "leaseSeconds", "automaticTransmit", "floor")
                    val format = value.getJSONObject("format")
                    fields(format, "encoding", "sampleRate", "channels", "samplesPerFrame", "frameBytes", "sequence")
                    check(format.get("encoding") == "pcm_s16le" && format.get("sequence") == "uint32-le-first0")
                    for ((key, expected) in listOf("sampleRate" to 16000L, "channels" to 1L, "samplesPerFrame" to 320L, "frameBytes" to 644L))
                        check(integer(format, key, expected, expected) == expected)
                    check(integer(value, "leaseSeconds", 15, 15) == 15L && !boolean(value, "automaticTransmit"))
                    VoiceServerEvent.Ready(if (value.isNull("floor")) null else floor(value.getJSONObject("floor")))
                }
                "floor-granted", "floor-started" -> {
                    fields(value, "type", "leaseId", "speakerId", "leaseSeconds")
                    check(integer(value, "leaseSeconds", 15, 15) == 15L)
                    val f = floor(JSONObject().put("leaseId", value.get("leaseId")).put("speakerId", value.get("speakerId")))
                    if (value.get("type") == "floor-granted") VoiceServerEvent.Granted(f) else VoiceServerEvent.Started(f)
                }
                "floor-ended" -> { fields(value, "type", "leaseId"); VoiceServerEvent.Ended(id(value, "leaseId")) }
                "floor-busy" -> { fields(value, "type"); VoiceServerEvent.Busy }
                "pong" -> { fields(value, "type"); VoiceServerEvent.Pong }
                else -> invalid()
            }
        }
        fun control(value: VoiceControl): String = JSONObject().put("type", value.wire).toString()
        fun frame(sequence: Long, pcm: ByteArray): ByteArray {
            check(sequence in 0..0xffffffffL && pcm.size == PCM_BYTES)
            return ByteArray(FRAME_BYTES).also { output ->
                repeat(4) { output[it] = (sequence ushr (8 * it)).toByte() }
                pcm.copyInto(output, 4)
            }
        }
        fun frame(bytes: ByteArray): VoicePcmFrame {
            check(bytes.size == FRAME_BYTES)
            var sequence = 0L; repeat(4) { sequence = sequence or ((bytes[it].toLong() and 255L) shl (8 * it)) }
            return VoicePcmFrame(sequence, bytes.copyOfRange(4, FRAME_BYTES))
        }
    }
}

/** A late join may begin mid-floor. A newly announced floor begins at zero; neither may skip or wrap. */
internal class VoiceReceiveSequence {
    private var floor: String? = null
    private var next: Long? = null
    fun begin(leaseId: String, lateJoin: Boolean) {
        check(Regex("[a-f0-9]{32}").matches(leaseId)); floor = leaseId; next = if (lateJoin) null else 0
    }
    fun accept(frame: VoicePcmFrame) {
        check(floor != null && frame.sequence in 0..0xffffffffL)
        val expected = next; check(expected == null || frame.sequence == expected)
        next = frame.sequence + 1
    }
    fun end() { floor = null; next = null }
}
