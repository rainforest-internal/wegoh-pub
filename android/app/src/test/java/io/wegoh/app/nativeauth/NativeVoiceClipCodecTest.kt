package io.wegoh.app.nativeauth

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.util.Base64

class NativeVoiceClipCodecTest {
    private val boot = "a".repeat(32)
    private val otherBoot = "b".repeat(32)
    private val clipId = "c".repeat(32)
    private val speaker = "team-" + "d".repeat(40)
    private fun metadata(sequence: Long = 1, duration: Int = 20, id: String = clipId) = JSONObject()
        .put("id", id).put("speakerId", speaker).put("sequence", sequence).put("durationMs", duration)
    private fun feed(cursor: String, vararg items: JSONObject) = JSONObject().put("cursor", cursor).put("clips", JSONArray(items.toList()))
    private fun rejected(action: () -> Unit) {
        try { action() } catch (_: Exception) { return }
        fail("Invalid complete voice clip accepted")
    }

    @Test fun uploadContainsOneCompletePcmAndStableCallerSuppliedMessageId() {
        for (size in listOf(640, 32000, 480000)) {
            val pcm = ByteArray(size) { (it % 127).toByte() }
            val body = NativeVoiceClipCodec.upload(clipId, pcm)
            assertEquals(setOf("clientMessageId", "pcmBase64"), body.keys().asSequence().toSet())
            assertEquals(clipId, body.getString("clientMessageId"))
            assertArrayEquals(pcm, Base64.getDecoder().decode(body.getString("pcmBase64")))
            assertEquals(body.toString(), NativeVoiceClipCodec.upload(clipId, pcm).toString())
        }
        for (size in listOf(0, 639, 641, 480640)) rejected { NativeVoiceClipCodec.upload(clipId, ByteArray(size)) }
        rejected { NativeVoiceClipCodec.upload("../clip", ByteArray(640)) }
    }

    @Test fun fullClipUploadBodyKeepsBase64SlashesLiteralWithinTheBodyLimit() {
        // 0xFF bytes encode to Base64 '/' only: the worst case for "\/" escaping.
        val pcm = ByteArray(NativeVoiceClipCodec.MAX_PCM_BYTES) { 0xFF.toByte() }
        val bytes = NativeApiClient.voiceClipUploadBody(NativeVoiceClipCodec.upload(clipId, pcm), 7)
        val text = String(bytes, Charsets.UTF_8)
        assertTrue(bytes.size <= NativeApiClient.VOICE_CLIP_BODY_LIMIT)
        assertFalse(text.contains("\\/"))
        val parsed = JSONObject(text)
        assertEquals(setOf("clientMessageId", "functionalRevision", "pcmBase64"), parsed.keys().asSequence().toSet())
        assertEquals(clipId, parsed.getString("clientMessageId"))
        assertEquals(7L, parsed.getLong("functionalRevision"))
        assertArrayEquals(pcm, Base64.getDecoder().decode(parsed.getString("pcmBase64")))
        // Android's org.json writes each '/' as "\/"; that encoding of the same clip cannot be sent.
        assertTrue(text.replace("/", "\\/").toByteArray(Charsets.UTF_8).size > NativeApiClient.VOICE_CLIP_BODY_LIMIT)
    }

    @Test fun completeDownloadRequiresExpectedMetadataAndExactPcmDuration() {
        val expected = NativeVoiceClipCodec.metadata(metadata(duration = 1000))
        val pcm = ByteArray(32000) { 42 }
        val body = metadata(duration = 1000).put("pcmBase64", Base64.getEncoder().encodeToString(pcm))
        val downloaded = NativeVoiceClipCodec.clip(body, expected)
        assertEquals(expected, downloaded.metadata)
        assertArrayEquals(pcm, downloaded.pcm)
        downloaded.erase()
        assertTrue(downloaded.pcm.all { it == 0.toByte() })
        assertEquals("NativeVoiceClip(redacted)", downloaded.toString())
        assertEquals("NativeVoiceClipMetadata(redacted)", expected.toString())
        rejected { NativeVoiceClipCodec.clip(body, expected.copy(id = "e".repeat(32))) }
        rejected { NativeVoiceClipCodec.clip(metadata(duration = 1000).put("pcmBase64", Base64.getEncoder().encodeToString(ByteArray(640))), expected) }
        rejected { NativeVoiceClipCodec.clip(JSONObject(body.toString()).put("pcmBase64", "!"), expected) }
        rejected { NativeVoiceClipCodec.clip(JSONObject(body.toString()).put("pcmBase64", "a".repeat(640004)), expected) }
        rejected { NativeVoiceClipCodec.clip(JSONObject(body.toString()).put("unexpected", true), expected) }
    }

    @Test fun metadataRejectsForeignTypesFieldsAndOutOfBoundsDurations() {
        for (field in listOf("id", "speakerId", "sequence", "durationMs")) {
            rejected { NativeVoiceClipCodec.metadata(metadata().apply { remove(field) }) }
            rejected { NativeVoiceClipCodec.metadata(metadata().put(field, JSONObject.NULL)) }
        }
        for (duration in listOf(0, 19, 21, 15020)) rejected { NativeVoiceClipCodec.metadata(metadata(duration = duration)) }
        for (sequence in listOf(0L, -1L, 9007199254740992L)) rejected { NativeVoiceClipCodec.metadata(metadata(sequence = sequence)) }
        rejected { NativeVoiceClipCodec.metadata(metadata().put("sequence", 1.0)) }
        rejected { NativeVoiceClipCodec.metadata(metadata().put("durationMs", "20")) }
        rejected { NativeVoiceClipCodec.metadata(metadata().put("speakerId", "account")) }
        rejected { NativeVoiceClipCodec.metadata(metadata().put("id", "C".repeat(32))) }
        rejected { NativeVoiceClipCodec.metadata(metadata().put("unexpected", true)) }
    }

    @Test fun initialAndRestartedFeedCannotReplayPastAudio() {
        assertTrue(NativeVoiceClipCodec.feed(feed("$boot:20")).clips.isEmpty())
        assertTrue(NativeVoiceClipCodec.feed(feed("$otherBoot:20"), "$boot:10").clips.isEmpty())
        rejected { NativeVoiceClipCodec.feed(feed("$boot:20", metadata(sequence = 20))) }
        rejected { NativeVoiceClipCodec.feed(feed("$otherBoot:20", metadata(sequence = 20)), "$boot:10") }
    }

    @Test fun incrementalFeedRequiresUniqueOrderedClipsStrictlyAfterPreviousCursor() {
        val value = NativeVoiceClipCodec.feed(feed("$boot:4", metadata(sequence = 2), metadata(sequence = 4, id = "e".repeat(32))), "$boot:1")
        assertEquals(listOf(2L, 4L), value.clips.map { it.sequence })
        assertEquals("NativeVoiceClipFeed(redacted)", value.toString())
        rejected { NativeVoiceClipCodec.feed(feed("$boot:4", metadata(sequence = 1)), "$boot:1") }
        rejected { NativeVoiceClipCodec.feed(feed("$boot:4", metadata(sequence = 5)), "$boot:1") }
        rejected { NativeVoiceClipCodec.feed(feed("$boot:4", metadata(sequence = 3), metadata(sequence = 2, id = "e".repeat(32))), "$boot:1") }
        rejected { NativeVoiceClipCodec.feed(feed("$boot:4", metadata(sequence = 2), metadata(sequence = 3)), "$boot:1") }
        rejected { NativeVoiceClipCodec.feed(feed("$boot:0"), "$boot:1") }
        for (cursor in listOf("$boot:01", "$boot:-1", "$boot:9007199254740992", "../cursor"))
            rejected { NativeVoiceClipCodec.feed(feed(cursor)) }
        rejected { NativeVoiceClipCodec.feed(feed("$boot:65", *(1L..65L).map { metadata(sequence = it, id = it.toString(16).padStart(32, '0')) }.toTypedArray()), "$boot:0") }
    }

    @Test fun recorderCopiesBorrowedFramesCapsAtFifteenSecondsAndErasesBetweenRecordings() {
        val recording = NativeVoiceClipRecording()
        assertNull(recording.take())
        assertFalse(recording.append(ByteArray(639)))
        val frame = ByteArray(640) { 7 }
        repeat(750) { assertTrue(recording.append(frame)) }
        frame.fill(1)
        assertTrue(recording.isFull())
        assertFalse(recording.append(frame))
        val result = requireNotNull(recording.take())
        assertEquals(480000, result.size)
        assertTrue(result.all { it == 7.toByte() })
        assertFalse(recording.isFull())
        assertNull(recording.take())
        assertTrue(recording.append(frame))
        recording.erase()
        assertNull(recording.take())
        assertTrue(recording.append(ByteArray(640)))
        assertTrue(requireNotNull(recording.take()).all { it == 0.toByte() })
        result.fill(0)
    }

    @Test fun filterRefreshUsesOnlyUniqueSortedAccountIdentifiers() {
        val other = "team-" + "e".repeat(40)
        fun filters(vararg values: Any) = JSONObject().put("mutedSpeakerIds", JSONArray(values.toList()))
        assertEquals(setOf(speaker, other), NativeVoiceClipCodec.filters(filters(speaker, other)))
        assertTrue(NativeVoiceClipCodec.filters(filters()).isEmpty())
        rejected { NativeVoiceClipCodec.filters(filters(other, speaker)) }
        rejected { NativeVoiceClipCodec.filters(filters(speaker, speaker)) }
        rejected { NativeVoiceClipCodec.filters(filters("../account")) }
        rejected { NativeVoiceClipCodec.filters(filters(1)) }
        rejected { NativeVoiceClipCodec.filters(filters().put("unexpected", true)) }
    }

    @Test fun endedContextConflictsAlwaysClearRecordingPlaybackAndDraftAuthority() {
        for (kind in listOf(NativeSocialFailure.Kind.CONFLICT, NativeSocialFailure.Kind.AUTHORIZATION_REQUIRED,
            NativeSocialFailure.Kind.FORBIDDEN, NativeSocialFailure.Kind.CONSENT_REQUIRED,
            NativeSocialFailure.Kind.STALE, NativeSocialFailure.Kind.CLOSED)) {
            assertTrue(NativeVoiceClipFailures.contextEnded(NativeSocialFailure(kind)))
            assertFalse(NativeVoiceClipFailures.canRetryUpload(NativeSocialFailure(kind)))
        }
    }

    @Test fun onlyTransientUploadFailuresCanRetainTheSameAudioForExplicitRetry() {
        for (kind in NativeSocialFailure.Kind.entries) {
            assertEquals(kind in setOf(NativeSocialFailure.Kind.UNAVAILABLE, NativeSocialFailure.Kind.RATE_LIMITED),
                NativeVoiceClipFailures.canRetryUpload(NativeSocialFailure(kind)))
        }
        assertFalse(NativeVoiceClipFailures.canRetryUpload(IllegalStateException("invalid clip projection")))
    }
}
