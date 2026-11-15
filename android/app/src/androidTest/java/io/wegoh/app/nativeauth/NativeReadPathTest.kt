package io.wegoh.app.nativeauth

import android.test.InstrumentationTestCase
import org.json.JSONObject

class NativeReadPathTest : InstrumentationTestCase() {
    fun testPathBoundaryMatchesServerVectors() {
        val data=JSONObject(instrumentation.context.assets.open("native_read_paths.json").bufferedReader().use {it.readText()})
        val allowed=data.getJSONArray("allowed")
        for(i in 0 until allowed.length())NativeApiClient.requireReadPath(allowed.getString(i))
        val denied=data.getJSONArray("denied")
        for(i in 0 until denied.length()) {
            try {NativeApiClient.requireReadPath(denied.getString(i));fail("Denied path was accepted")}
            catch(expected: IllegalArgumentException) {assertEquals("NATIVE_READ_PATH_NOT_ALLOWED",expected.message)}
        }
    }
}
