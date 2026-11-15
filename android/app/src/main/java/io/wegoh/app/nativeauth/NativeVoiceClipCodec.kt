package io.wegoh.app.nativeauth

import org.json.JSONObject
import java.util.Base64

internal data class NativeVoiceClipMetadata(val id: String, val speakerId: String, val sequence: Long, val durationMs: Int) {
    override fun toString() = "NativeVoiceClipMetadata(redacted)"
}
internal data class NativeVoiceClipFeed(val cursor: String, val clips: List<NativeVoiceClipMetadata>) {
    override fun toString() = "NativeVoiceClipFeed(redacted)"
}
internal class NativeVoiceClip(val metadata: NativeVoiceClipMetadata, val pcm: ByteArray) {
    fun erase() = pcm.fill(0)
    override fun toString() = "NativeVoiceClip(redacted)"
}

internal object NativeVoiceClipFailures {
    fun contextEnded(error: Throwable) = (error as? NativeSocialFailure)?.kind in setOf(
        NativeSocialFailure.Kind.AUTHORIZATION_REQUIRED, NativeSocialFailure.Kind.FORBIDDEN, NativeSocialFailure.Kind.CONSENT_REQUIRED,
        NativeSocialFailure.Kind.STALE, NativeSocialFailure.Kind.CLOSED, NativeSocialFailure.Kind.CONFLICT)
    fun canRetryUpload(error: Throwable) = (error as? NativeSocialFailure)?.kind in setOf(
        NativeSocialFailure.Kind.UNAVAILABLE, NativeSocialFailure.Kind.RATE_LIMITED)
}

internal object NativeVoiceClipCodec {
    const val MAX_PCM_BYTES = 480000
    private val id = Regex("[a-f0-9]{32}")
    private val account = Regex("team-[a-f0-9]{40}")
    val cursorPattern = Regex("[a-f0-9]{32}:(0|[1-9][0-9]{0,15})")
    private fun fields(value: JSONObject, vararg names: String) = check(value.keys().asSequence().toSet() == names.toSet())
    private fun number(value: JSONObject, name: String, min: Long, max: Long): Long {
        val raw = value.get(name)
        check(raw is Int || raw is Long)
        return (raw as Number).toLong().also { check(it in min..max) }
    }
    private fun text(value: JSONObject, name: String, pattern: Regex) =
        (value.get(name) as? String).also { check(it != null && pattern.matches(it)) }!!
    private fun read(value: JSONObject) = NativeVoiceClipMetadata(text(value, "id", id), text(value, "speakerId", account),
        number(value, "sequence", 1, 9007199254740991), number(value, "durationMs", 20, 15000).toInt().also { check(it % 20 == 0) })
    fun metadata(value: JSONObject): NativeVoiceClipMetadata {
        fields(value, "id", "speakerId", "sequence", "durationMs")
        return read(value)
    }
    fun feed(value: JSONObject, previous: String? = null): NativeVoiceClipFeed {
        fields(value, "cursor", "clips")
        val cursor = text(value, "cursor", cursorPattern)
        val end = cursor.substringAfter(':').toLong()
        check(end <= 9007199254740991)
        val list = value.getJSONArray("clips").also { check(it.length() <= 64) }
        val clips = (0 until list.length()).map { metadata(list.getJSONObject(it)) }
        check(clips.map { it.id }.toSet().size == clips.size)
        check(clips.zipWithNext().all { (a, b) -> a.sequence < b.sequence } && clips.all { it.sequence <= end })
        if (previous == null || previous.substringBefore(':') != cursor.substringBefore(':')) check(clips.isEmpty())
        else {
            check(cursorPattern.matches(previous))
            val start = previous.substringAfter(':').toLong()
            check(end >= start && clips.all { it.sequence > start })
        }
        return NativeVoiceClipFeed(cursor, clips)
    }
    fun clip(value: JSONObject, expected: NativeVoiceClipMetadata): NativeVoiceClip {
        fields(value, "id", "speakerId", "sequence", "durationMs", "pcmBase64")
        val metadata = read(value)
        check(metadata == expected)
        val encoded = value.get("pcmBase64") as? String ?: error("NATIVE_VOICE_CLIP_INVALID")
        check(encoded.length <= 640000)
        val pcm = Base64.getDecoder().decode(encoded)
        if (pcm.size != metadata.durationMs * 32 || pcm.size !in 640..MAX_PCM_BYTES || pcm.size % 640 != 0) {
            pcm.fill(0); error("NATIVE_VOICE_CLIP_INVALID")
        }
        return NativeVoiceClip(metadata, pcm)
    }
    fun filters(value: JSONObject): Set<String> {
        fields(value, "mutedSpeakerIds")
        val items = value.getJSONArray("mutedSpeakerIds").also { check(it.length() <= 1024) }
        val speakers = (0 until items.length()).map { index ->
            (items.get(index) as? String).also { check(it != null && account.matches(it)) }!!
        }
        check(speakers.distinct().size == speakers.size && speakers.sorted() == speakers)
        return speakers.toSet()
    }
    fun upload(messageId: String, pcm: ByteArray): JSONObject {
        check(id.matches(messageId) && pcm.size in 640..MAX_PCM_BYTES && pcm.size % 640 == 0)
        return JSONObject().put("clientMessageId", messageId).put("pcmBase64", Base64.getEncoder().encodeToString(pcm))
    }
}

internal class NativeVoiceClipRecording {
    private val bytes = ByteArray(NativeVoiceClipCodec.MAX_PCM_BYTES)
    private var size = 0
    @Synchronized fun isFull() = size == bytes.size
    @Synchronized fun append(frame: ByteArray): Boolean {
        if (frame.size != 640 || size + frame.size > bytes.size) return false
        frame.copyInto(bytes, size); size += frame.size
        return true
    }
    @Synchronized fun take(): ByteArray? = (if (size >= 640) bytes.copyOf(size) else null).also { erase() }
    @Synchronized fun erase() { bytes.fill(0); size = 0 }
}
