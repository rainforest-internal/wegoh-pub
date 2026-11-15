package io.wegoh.app.nativeauth

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class TripDisplayCodecTest {
    private fun value()=JSONObject("""{"serverNow":"2026-11-09T00:00:00Z","validUntil":"2026-11-09T00:00:10Z",
        "endedAt":"2026-11-09T00:00:00Z","timeline":[{"id":"course:test","name":"완료한 코스","kind":"코스 완료","at":"2026-11-09T00:00:00Z"}],
        "visitCount":null,"metrics":null,"music":{"name":"같이 듣는 곡","currentTitle":"선택한 곡","trackCount":2,"djName":"친구"},
        "companions":[{"carId":"11111111111111111111111111111111","distanceMeters":3000,"direction":"ahead"}]}""")
    @Test fun readsRealMetadataWithoutInventingMetrics() {
        val display=NativeTripDisplayCodec.read(value(),1000)
        assertEquals(11000L,display.expiresAtElapsedMillis)
        assertNull(display.visitCount);assertNull(display.metrics)
        assertEquals("완료한 코스",display.timeline.single().name)
        assertEquals("선택한 곡",display.music?.currentTitle)
        assertEquals("ahead",display.companions.single().direction)
    }
    @Test fun rejectsInvalidDirectionAndNonFiniteDistance() {
        val reply=value();reply.getJSONArray("companions").getJSONObject(0).put("direction","unknown")
        assertThrows(IllegalStateException::class.java) {NativeTripDisplayCodec.read(reply,0)}
        val negative=value();negative.getJSONArray("companions").getJSONObject(0).put("distanceMeters",-1)
        assertThrows(IllegalStateException::class.java) {NativeTripDisplayCodec.read(negative,0)}
    }
    @Test fun rejectsUnboundedLiveDataLifetime() {
        val reply=value().put("validUntil","2026-11-10T00:00:00Z")
        assertThrows(IllegalStateException::class.java) {NativeTripDisplayCodec.read(reply,0)}
    }
}
