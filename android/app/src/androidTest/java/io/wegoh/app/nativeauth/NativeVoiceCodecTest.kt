package io.wegoh.app.nativeauth

import android.test.InstrumentationTestCase
import org.json.JSONObject

@Suppress("DEPRECATION")
class NativeVoiceCodecTest: InstrumentationTestCase() {
    private val device = "d".repeat(32)
    private val grant = "c".repeat(32)
    private val room = "a".repeat(32)
    private val speaker = "team-" + "b".repeat(40)
    private val hash = "c2f43974b09137e0a63fd32621c89b49a288704dee494743cf876b47a3d166a7"
    private val now = 1900000000000L
    private val codec = NativeVoiceCodec(2, hash)
    private fun permission(vararg directions: VoiceDirection) = FunctionalPermissions(device, grant, 3,
        now + 120000, directions.map { it.purpose }.toSet(), 1, "e".repeat(64))
    private fun rejected(action: () -> Unit) {
        var failed = false; try { action() } catch (_: Exception) { failed = true }; assertTrue(failed)
    }
    private fun page() = """{"authorizationVersion":1,"deviceId":"$device","grantId":"$grant","functionalRevision":3,
        "items":[{"roomId":"$room","name":"Synthetic room","availableDirections":["transmit"],"revision":7,
        "memberJoinedAt":"2030-01-01T00:00:00+00:00","expiresAt":1900000060}],"nextCursor":null}"""
    private fun snapshot() = """{"authorizationVersion":1,"deviceId":"$device","grantId":"$grant","roomId":"$room",
        "revision":7,"functionalRevision":3,"memberJoinedAt":"2030-01-01T00:00:00+00:00","expiresAt":1900000060,
        "permissions":{"receiveVoice":false,"transmitVoice":true},"roomVoiceDisclosureVersion":2,
        "roomVoiceDisclosureSha256":"$hash"}"""

    fun testRawRoomProjectionIsDirectionSpecificAndClosed() {
        val permission = permission(VoiceDirection.TRANSMIT)
        val value = codec.rooms(page().toByteArray(), permission, null, now)
        assertEquals(setOf(VoiceDirection.TRANSMIT), value.items.single().availableDirections)
        assertNull(value.nextCursor)
        val offset = page().replace("2030-01-01T00:00:00+00:00", "2030-01-01T09:00:00+09:00")
        val zulu = page().replace("2030-01-01T00:00:00+00:00", "2030-01-01T00:00:00Z")
        assertEquals(value.items.single().memberJoinedAt, codec.rooms(offset.toByteArray(), permission, null, now).items.single().memberJoinedAt)
        assertEquals(value.items.single().memberJoinedAt, codec.rooms(zulu.toByteArray(), permission, null, now).items.single().memberJoinedAt)
        rejected { codec.rooms(page().replace("2030-01-01T00:00:00+00:00", "2030-01-01T00:00:00").toByteArray(), permission, null, now) }
        assertFalse(value.toString().contains(room)); assertFalse(value.items.single().toString().contains("Synthetic"))
        rejected { (value.items as MutableList<VoiceRoomReference>).clear() }
        rejected { (value.items[0].availableDirections as MutableSet<VoiceDirection>).clear() }
        rejected { codec.rooms(page().replace("\"functionalRevision\":3", "\"functionalRevision\":3.0").toByteArray(), permission, null, now) }
        rejected { codec.rooms(page().replace("\"authorizationVersion\":1", "\"authorizationVersion\":1,\"authorizationVersion\":1").toByteArray(), permission, null, now) }
        rejected { codec.rooms(page().replace("\"transmit\"", "\"receive\"").toByteArray(), permission, null, now) }
        rejected { codec.rooms(page().replace("\"transmit\"", "\"transmit\",\"transmit\"").toByteArray(), permission, null, now) }
        rejected { codec.rooms(page().replace("1900000060", "1900000121").toByteArray(), permission, null, now) }
        rejected { codec.rooms(page().toByteArray(), permission, VoiceRoomCursor(room), now) }
        rejected { codec.rooms(JSONObject(page()).put("nextCursor", room).toString().toByteArray(), permission, null, now) }
        rejected { codec.rooms(JSONObject(page()).put("deviceId", "f".repeat(32)).toString().toByteArray(), permission, null, now) }
        rejected { codec.rooms(JSONObject(page()).put("roomsRead", true).toString().toByteArray(), permission, null, now) }
    }

    fun testRoomConsentNeverInfersOppositePurposeOrOldNotice() {
        val permission = permission(VoiceDirection.TRANSMIT)
        val value = codec.roomPermission(snapshot().toByteArray(), permission, room, now)
        assertEquals(setOf(VoiceDirection.TRANSMIT), value.directions); assertEquals(7L, value.revision)
        val denied = JSONObject(snapshot()).put("revision", 0).apply { getJSONObject("permissions").put("transmitVoice", false) }
        assertTrue(codec.roomPermission(denied.toString().toByteArray(), permission, room, now).directions.isEmpty())
        rejected { codec.roomPermission(snapshot().replace("\"receiveVoice\":false", "\"receiveVoice\":true").toByteArray(), permission, room, now) }
        rejected { codec.roomPermission(JSONObject(snapshot()).put("revision", 0).toString().toByteArray(), permission, room, now) }
        rejected { codec.roomPermission(JSONObject(snapshot()).put("roomVoiceDisclosureVersion", 1).toString().toByteArray(), permission, room, now) }
        rejected { codec.roomPermission(JSONObject(snapshot()).put("functionalRevision", 2).toString().toByteArray(), permission, room, now) }
        rejected { codec.roomPermission(snapshot().toByteArray(), permission, "b".repeat(32), now) }
        rejected { codec.roomPermission(snapshot().toByteArray(), permission, room, now + 120000) }
    }

    fun testTripAnswerMayStartOnAtRevisionZeroButNeverAsARoomAnswer() {
        val permission = FunctionalPermissions(device, grant, 3, now + 120000,
            setOf(FunctionalPurpose.ROOMS_READ), 1, "e".repeat(64))
        val trip = JSONObject(snapshot()).put("revision", 0).put("tripId", room).put("contractVersion", 1).apply { remove("roomId") }
        val value = codec.tripPermission(trip.toString().toByteArray(), permission, room, now)
        assertEquals(setOf(VoiceDirection.TRANSMIT), value.directions); assertEquals(0L, value.revision)
        rejected { codec.roomPermission(trip.toString().toByteArray(), permission, room, now) }
        rejected { codec.tripPermission(snapshot().toByteArray(), permission, room, now) }
        rejected { codec.tripPermission(JSONObject(trip.toString()).put("contractVersion", 2).toString().toByteArray(), permission, room, now) }
        rejected { codec.tripPermission(trip.toString().toByteArray(), permission, "b".repeat(32), now) }
        assertEquals(setOf(VoiceDirection.RECEIVE, VoiceDirection.TRANSMIT), codec.tripPermission(
            trip.toString().replace("\"receiveVoice\":false", "\"receiveVoice\":true").toByteArray(), permission, room, now).directions)
        rejected { codec.tripPermission(trip.toString().toByteArray(), this.permission(VoiceDirection.TRANSMIT), room, now) }
    }

    fun testRawReadyAndControlsRejectProtocolExpansion() {
        val ready = """{"type":"ready","format":{"encoding":"pcm_s16le","sampleRate":16000,"channels":1,
            "samplesPerFrame":320,"frameBytes":644,"sequence":"uint32-le-first0"},"leaseSeconds":15,
            "automaticTransmit":false,"floor":{"leaseId":"$room","speakerId":"$speaker"}}"""
        val value = NativeVoiceCodec.event(ready.toByteArray()) as VoiceServerEvent.Ready
        assertEquals(speaker, value.floor!!.speakerId)
        assertNull((NativeVoiceCodec.event(JSONObject(ready).put("floor", JSONObject.NULL).toString().toByteArray()) as VoiceServerEvent.Ready).floor)
        for (raw in listOf(ready.replace("16000", "16000.0"), ready.replace("false", "true"), ready.replace("644", "640"),
            ready.replace("\"leaseSeconds\":15", "\"leaseSeconds\":15,\"leaseSeconds\":15"), ready.replace(speaker, "f".repeat(32))))
            rejected { NativeVoiceCodec.event(raw.toByteArray()) }
        for (kind in listOf("floor-granted", "floor-started")) {
            val event = """{"type":"$kind","leaseId":"$room","speakerId":"$speaker","leaseSeconds":15}"""
            assertNotNull(NativeVoiceCodec.event(event.toByteArray()))
            rejected { NativeVoiceCodec.event(JSONObject(event).put("token", "synthetic-not-authority").toString().toByteArray()) }
        }
        assertTrue(NativeVoiceCodec.event("""{"type":"floor-busy"}""".toByteArray()) === VoiceServerEvent.Busy)
        assertTrue(NativeVoiceCodec.event("""{"type":"pong"}""".toByteArray()) === VoiceServerEvent.Pong)
        assertEquals(room, (NativeVoiceCodec.event("""{"type":"floor-ended","leaseId":"$room"}""".toByteArray()) as VoiceServerEvent.Ended).leaseId)
        rejected { NativeVoiceCodec.event("""{"type":"pong","floor":null}""".toByteArray()) }
        for (control in VoiceControl.entries) {
            val body = StrictNativeJson.parseBusiness(NativeVoiceCodec.control(control).toByteArray())
            assertEquals(setOf("type"), body.keys().asSequence().toSet()); assertEquals(control.wire, body.get("type"))
        }
    }

    fun testFrameOwnershipAndLateJoinSequenceRejectSkipsAndWrap() {
        val pcm = ByteArray(640) { (it % 127).toByte() }
        val encoded = NativeVoiceCodec.frame(0x01020304L, pcm)
        assertEquals(644, encoded.size); assertEquals(4.toByte(), encoded[0]); assertEquals(1.toByte(), encoded[3])
        val decoded = NativeVoiceCodec.frame(encoded); assertEquals(0x01020304L, decoded.sequence)
        encoded.fill(0); assertTrue(pcm.contentEquals(decoded.pcm)); decoded.erase(); assertTrue(decoded.pcm.all { it == 0.toByte() })
        assertTrue(pcm.any { it != 0.toByte() })
        rejected { NativeVoiceCodec.frame(ByteArray(640)) }; rejected { NativeVoiceCodec.frame(-1, pcm) }
        rejected { NativeVoiceCodec.frame(0x100000000L, pcm) }; rejected { NativeVoiceCodec.frame(0, ByteArray(639)) }
        val sequence = VoiceReceiveSequence()
        val zero = NativeVoiceCodec.frame(NativeVoiceCodec.frame(0, pcm))
        val seven = NativeVoiceCodec.frame(NativeVoiceCodec.frame(7, pcm))
        rejected { sequence.accept(zero) }
        sequence.begin(room, false); rejected { sequence.accept(seven) }; sequence.accept(zero)
        rejected { sequence.accept(zero) }; sequence.end()
        sequence.begin(room, true); sequence.accept(seven)
        sequence.accept(NativeVoiceCodec.frame(NativeVoiceCodec.frame(8, pcm)))
        rejected { sequence.accept(NativeVoiceCodec.frame(NativeVoiceCodec.frame(10, pcm))) }
        sequence.begin(room, true); sequence.accept(NativeVoiceCodec.frame(NativeVoiceCodec.frame(0xffffffffL, pcm)))
        rejected { sequence.accept(zero) }
        sequence.end(); rejected { sequence.accept(seven) }
        pcm.fill(0); zero.erase(); seven.erase()
    }
}
