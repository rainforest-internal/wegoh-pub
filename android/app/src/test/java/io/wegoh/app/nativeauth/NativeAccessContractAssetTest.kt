package io.wegoh.app.nativeauth

import java.io.ByteArrayInputStream
import java.io.File
import org.junit.Assert.*
import org.junit.Test

class NativeAccessContractAssetTest {
    @Test fun bundledContractLoadsThroughStartupReader() {
        val wire=File("src/main/assets/native_access_wire.json").inputStream().use {readBundledNativeAccessWire(it)}
        assertEquals(1,wire.getInt("schemaVersion"))
        assertTrue(wire.getJSONArray("operations").length()>0)
        assertTrue(wire.has("functional"))
    }

    @Test fun bundledContractLoadsForVoice() {
        val bytes=File("src/main/assets/native_access_wire.json").readBytes()
        assertTrue("Voice must read the same grown asset as startup",bytes.size>131072)
        NativeVoiceContract.decode(bytes)
    }

    @Test fun oversizedContractRemainsRejected() {
        try {
            readBundledNativeAccessWire(ByteArrayInputStream(ByteArray(NATIVE_WIRE_MAX_BYTES+1)))
            fail("Oversized bundled contract must be rejected")
        } catch(error: IllegalStateException) {
            assertEquals("NATIVE_RESPONSE_TOO_LARGE",error.message)
        }
    }

    @Test fun bundledVoiceContractLoadsThroughTheSharedBoundedReader() {
        val bytes=File("src/main/assets/native_access_wire.json").readBytes()
        assertNotNull(NativeVoiceContract.decode(bytes))
    }

    @Test fun voiceContractKeepsSizeAndExactSchemaValidation() {
        try {
            NativeVoiceContract.decode(ByteArray(NATIVE_WIRE_MAX_BYTES+1))
            fail("Oversized voice contract must be rejected by the bundle reader")
        } catch(error: IllegalStateException) {
            assertEquals("NATIVE_RESPONSE_TOO_LARGE",error.message)
        }
        val raw=File("src/main/assets/native_access_wire.json").readText()
        val invalid=Regex("\"schemaVersion\"\\s*:\\s*1").replaceFirst(raw,"\"schemaVersion\":\"1\"")
        assertNotEquals(raw,invalid)
        assertTrue(runCatching {NativeVoiceContract.decode(invalid.toByteArray(Charsets.UTF_8))}.isFailure)
    }
}
