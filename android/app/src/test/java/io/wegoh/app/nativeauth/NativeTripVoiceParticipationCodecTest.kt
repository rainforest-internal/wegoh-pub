package io.wegoh.app.nativeauth

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.time.Instant

class NativeTripVoiceParticipationCodecTest {
    private val trip = "a".repeat(32)
    private val device = "d".repeat(32)
    private val grant = "c".repeat(32)
    private val joined = "2026-11-11T03:14:15.123000+00:00"
    private val hash = "e".repeat(64)
    private val now = 1900000000000L
    private val voice = NativeVoiceCodec(2, hash)
    private fun wire(enabled: String = "true", revision: String = "7") =
        """{"tripId":"$trip","participating":$enabled,"memberJoinedAt":"$joined","revision":$revision}"""
    private fun snapshot(value: JSONObject) = NativeTripVoiceParticipationCodec.snapshot(value.toString().toByteArray(), trip)
    private fun rejected(action: () -> Unit) {
        try { action() } catch (_: Exception) { return }
        fail("Invalid trip voice projection accepted")
    }
    private fun permissions(vararg purposes: FunctionalPurpose) = FunctionalPermissions(device, grant, 3,
        now + 120000, purposes.toSet(), 1, "f".repeat(64))
    private fun tripPermission() = JSONObject().put("authorizationVersion", 1).put("contractVersion", 1)
        .put("deviceId", device).put("grantId", grant).put("tripId", trip).put("revision", 7)
        .put("functionalRevision", 3).put("memberJoinedAt", joined).put("expiresAt", now / 1000 + 60)
        .put("permissions", JSONObject().put("receiveVoice", true).put("transmitVoice", true))
        .put("roomVoiceDisclosureVersion", 2).put("roomVoiceDisclosureSha256", hash)

    @Test fun snapshotReadsBothParticipationStatesWithoutExposingItsIdentityInText() {
        for (enabled in listOf(true, false)) {
            val value = NativeTripVoiceParticipationCodec.snapshot(wire(enabled.toString()).toByteArray(), trip)
            assertEquals(trip, value.tripId); assertEquals(enabled, value.participating)
            assertEquals(Instant.parse("2026-11-11T03:14:15.123Z"), value.memberJoinedAt)
            assertEquals(7L, value.revision)
            assertEquals("VoiceTripParticipation(redacted)", value.toString())
        }
    }
    @Test fun patchUsesTheExactObservedJoinTextAndRevisionForTheCompareAndSwap() {
        for (raw in listOf(joined, "2026-11-11T12:14:15.123000+09:00", "2026-11-11T03:14:15.123Z")) {
            val current = snapshot(JSONObject(wire()).put("memberJoinedAt", raw))
            val body = NativeTripVoiceParticipationCodec.patchBody(current, false)
            assertEquals(setOf("participating", "memberJoinedAt", "revision"), body.keys().asSequence().toSet())
            assertEquals(false, body.get("participating")); assertEquals(raw, body.getString("memberJoinedAt"))
            assertEquals(7L, body.getLong("revision")); assertTrue(current.participating)
        }
    }
    @Test fun snapshotRejectsWrongTripAndMalformedTripIdentifiers() {
        rejected { NativeTripVoiceParticipationCodec.snapshot(wire().toByteArray(), "b".repeat(32)) }
        for (id in listOf("A".repeat(32), "a".repeat(31), "../trips", "")) {
            rejected { snapshot(JSONObject(wire()).put("tripId", id)) }
            rejected { NativeTripVoiceParticipationCodec.snapshot(wire().toByteArray(), id) }
        }
        rejected { snapshot(JSONObject(wire()).put("tripId", 1)) }
    }
    @Test fun participationRequiresABooleanAndRevisionRequiresAnExactBoundedInteger() {
        for (raw in listOf("0", "1", "\"true\"", "null", "[]"))
            rejected { NativeTripVoiceParticipationCodec.snapshot(wire(enabled = raw).toByteArray(), trip) }
        for (raw in listOf("0", "-1", "2147483648", "7.0", "7e0", "\"7\"", "true", "null"))
            rejected { NativeTripVoiceParticipationCodec.snapshot(wire(revision = raw).toByteArray(), trip) }
        assertEquals(1L, NativeTripVoiceParticipationCodec.snapshot(wire(revision = "1").toByteArray(), trip).revision)
        assertEquals(Int.MAX_VALUE.toLong(), NativeTripVoiceParticipationCodec.snapshot(
            wire(revision = Int.MAX_VALUE.toString()).toByteArray(), trip).revision)
    }
    @Test fun joinStampRequiresAnOffsetDateTimeWithAValidCalendarDate() {
        for (raw in listOf("2026-11-11", "2026-11-11T03:14:15", "2026-02-30T03:14:15Z", "later", "", "x".repeat(65)))
            rejected { snapshot(JSONObject(wire()).put("memberJoinedAt", raw)) }
        for (raw in listOf(1, true, JSONObject.NULL))
            rejected { snapshot(JSONObject(wire()).put("memberJoinedAt", raw)) }
    }
    @Test fun snapshotRejectsMissingExpandedDuplicateAndNonObjectJson() {
        val original = JSONObject(wire())
        for (field in original.keys().asSequence().toList()) {
            val missing = JSONObject(wire()).apply { remove(field) }
            rejected { snapshot(missing) }
        }
        rejected { snapshot(JSONObject(wire()).put("functionalRevision", 3)) }
        rejected { NativeTripVoiceParticipationCodec.snapshot(wire().replace("\"revision\":7", "\"revision\":7,\"revision\":7").toByteArray(), trip) }
        for (raw in listOf("[]", "null", wire() + "{}"))
            rejected { NativeTripVoiceParticipationCodec.snapshot(raw.toByteArray(), trip) }
    }
    @Test fun patchRejectsAnInvalidInternallyConstructedSnapshot() {
        val instant = Instant.parse("2026-11-11T03:14:15.123Z")
        for (revision in listOf(0L, Int.MAX_VALUE.toLong() + 1))
            rejected { NativeTripVoiceParticipationCodec.patchBody(VoiceTripParticipation(trip, true, instant, revision), false) }
        rejected { NativeTripVoiceParticipationCodec.patchBody(VoiceTripParticipation("../trips", true, instant, 1), false) }
        rejected { NativeTripVoiceParticipationCodec.patchBody(VoiceTripParticipation(trip, true, instant, 1, "2026-11-11T03:14:16Z"), false) }
    }
    @Test fun tripDirectionsUseOnlyTheBaseRoomsGateAndKeepDirectionalFlagsExplicit() {
        val base = permissions(FunctionalPurpose.ROOMS_READ)
        val enabled = voice.tripPermission(tripPermission().toString().toByteArray(), base, trip, now)
        assertEquals(setOf(VoiceDirection.RECEIVE, VoiceDirection.TRANSMIT), enabled.directions)
        val disabled = tripPermission().apply { getJSONObject("permissions").put("receiveVoice", false).put("transmitVoice", false) }
        assertTrue(voice.tripPermission(disabled.toString().toByteArray(), base, trip, now).directions.isEmpty())
        val receive = tripPermission().apply { getJSONObject("permissions").put("transmitVoice", false) }
        assertEquals(setOf(VoiceDirection.RECEIVE), voice.tripPermission(receive.toString().toByteArray(), base, trip, now).directions)
        rejected { voice.tripPermission(tripPermission().toString().toByteArray(), permissions(FunctionalPurpose.ROOM_VOICE_RECEIVE, FunctionalPurpose.ROOM_VOICE_TRANSMIT), trip, now) }
    }
    @Test fun tripPermissionStillRejectsStaleForeignExpandedAndInvalidAuthority() {
        val base = permissions(FunctionalPurpose.ROOMS_READ)
        val mutations: List<(JSONObject) -> Unit> = listOf(
            { it.put("deviceId", "b".repeat(32)); Unit }, { it.put("grantId", "b".repeat(32)); Unit },
            { it.put("functionalRevision", 2); Unit }, { it.put("roomVoiceDisclosureVersion", 1); Unit },
            { it.put("roomVoiceDisclosureSha256", "0".repeat(64)); Unit }, { it.put("memberJoinedAt", "2026-11-11"); Unit },
            { it.put("expiresAt", now / 1000); Unit }, { it.put("expiresAt", now / 1000 + 121); Unit },
            { it.put("contractVersion", 2); Unit }, { it.put("unexpected", true); Unit },
            { it.getJSONObject("permissions").put("receiveVoice", "true"); Unit })
        for (mutate in mutations) {
            val value = tripPermission(); mutate(value)
            rejected { voice.tripPermission(value.toString().toByteArray(), base, trip, now) }
        }
        rejected { voice.tripPermission(tripPermission().toString().toByteArray(), base, "b".repeat(32), now) }
        rejected { voice.tripPermission(tripPermission().toString().toByteArray(), base, trip, now + 120000) }
    }
    @Test fun legacyRoomPermissionsAndRoomListingStillRequireTheirOriginalPurposes() {
        val legacy = tripPermission().apply { remove("tripId"); remove("contractVersion"); put("roomId", trip) }
        val both = permissions(FunctionalPurpose.ROOM_VOICE_RECEIVE, FunctionalPurpose.ROOM_VOICE_TRANSMIT)
        assertEquals(setOf(VoiceDirection.RECEIVE, VoiceDirection.TRANSMIT), voice.roomPermission(legacy.toString().toByteArray(), both, trip, now).directions)
        rejected { voice.roomPermission(legacy.toString().toByteArray(), permissions(FunctionalPurpose.ROOMS_READ), trip, now) }
        rejected { voice.roomPermission(legacy.toString().toByteArray(), permissions(FunctionalPurpose.ROOM_VOICE_RECEIVE), trip, now) }
        val listing = JSONObject().put("authorizationVersion", 1).put("deviceId", device).put("grantId", grant)
            .put("functionalRevision", 3).put("items", org.json.JSONArray()).put("nextCursor", JSONObject.NULL)
        rejected { voice.rooms(listing.toString().toByteArray(), permissions(FunctionalPurpose.ROOMS_READ), null, now) }
        assertTrue(voice.rooms(listing.toString().toByteArray(), both, null, now).items.isEmpty())
    }
}
