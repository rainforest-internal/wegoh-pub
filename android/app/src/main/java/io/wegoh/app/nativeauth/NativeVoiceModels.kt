package io.wegoh.app.nativeauth

import java.time.Instant
import java.util.Collections

/** A direction is never implied by the opposite direction or by room membership. */
enum class VoiceDirection(internal val wire: String, internal val purpose: FunctionalPurpose) {
    RECEIVE("receive", FunctionalPurpose.ROOM_VOICE_RECEIVE),
    TRANSMIT("transmit", FunctionalPurpose.ROOM_VOICE_TRANSMIT)
}

class VoiceTripParticipation internal constructor(
    val tripId: String, val participating: Boolean, val memberJoinedAt: Instant, val revision: Long,
    internal val memberJoinedAtWire: String = memberJoinedAt.toString()
) {
    override fun toString() = "VoiceTripParticipation(redacted)"
}

/** A short-lived, owner-projected selection reference, not room or microphone authority. */
class VoiceRoomReference internal constructor(
    val roomId: String, val name: String, directions: Set<VoiceDirection>,
    val revision: Long, val memberJoinedAt: Instant, val expiresAt: Instant,
    internal val deviceId: String, internal val grantId: String, internal val functionalRevision: Long,
    internal val trip: Boolean = false
) {
    val availableDirections: Set<VoiceDirection> = Collections.unmodifiableSet(directions.toSet())
    override fun toString() = "VoiceRoomReference(redacted)"
}
class VoiceRoomCursor internal constructor(internal val encoded: String) {
    override fun toString() = "VoiceRoomCursor(redacted)"
}
class VoiceRoomPage internal constructor(items: List<VoiceRoomReference>, val nextCursor: VoiceRoomCursor?) {
    val items: List<VoiceRoomReference> = Collections.unmodifiableList(items.toList())
    override fun toString() = "VoiceRoomPage(redacted)"
}

internal class VoiceRoomPermission(
    val roomId: String, val revision: Long, val functionalRevision: Long,
    val memberJoinedAt: Instant, val expiresAt: Instant, directions: Set<VoiceDirection>
) {
    val directions: Set<VoiceDirection> = Collections.unmodifiableSet(directions.toSet())
    override fun toString() = "VoiceRoomPermission(redacted)"
}
internal class VoiceFloor(val leaseId: String, val speakerId: String) {
    override fun toString() = "VoiceFloor(redacted)"
}
internal sealed class VoiceServerEvent {
    class Ready(val floor: VoiceFloor?): VoiceServerEvent()
    class Granted(val floor: VoiceFloor): VoiceServerEvent()
    class Started(val floor: VoiceFloor): VoiceServerEvent()
    class Ended(val leaseId: String): VoiceServerEvent()
    object Busy: VoiceServerEvent()
    object Pong: VoiceServerEvent()
    override fun toString() = "VoiceServerEvent(redacted)"
}
internal enum class VoiceControl(val wire: String) {
    REQUEST("floor-request"), RELEASE("floor-release"), STOP("stop"), PING("ping")
}
internal class VoicePcmFrame(val sequence: Long, val pcm: ByteArray) {
    fun erase() { pcm.fill(0) }
    override fun toString() = "VoicePcmFrame(redacted)"
}
