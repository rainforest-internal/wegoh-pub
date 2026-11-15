package io.wegoh.app.nativeauth

import android.content.Context
import android.content.ContextWrapper
import android.test.InstrumentationTestCase
import android.test.InstrumentationTestRunner
import android.util.Base64
import java.io.Closeable
import java.io.File
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference

/** Real public selector methods/owned event lifetime; no Voice audio, Main or default profile. */
@Suppress("DEPRECATION")
class NativeVoiceSelectorTest: InstrumentationTestCase() {
    fun testPackagedVoiceContractLoadsFromApplicationAssets() {
        assertNotNull(NativeVoiceContract.load(instrumentation.targetContext))
    }

    private fun waitFor(label: String, test: () -> Boolean) {
        val until = android.os.SystemClock.elapsedRealtime() + 30000
        while (android.os.SystemClock.elapsedRealtime() < until) { if (test()) return; Thread.sleep(20) }
        fail("Owned Voice selector timeout: $label")
    }
    private fun <T> receive(start: ((Result<T>) -> Unit) -> Unit): Result<T> {
        val result = AtomicReference<Result<T>?>(null); start { result.set(it) }
        waitFor("public callback") { result.get() != null }; return result.get()!!
    }
    fun testPublicSelectorOwnedFeedAndHeldCloseReopen() {
        val args = (instrumentation as InstrumentationTestRunner).arguments
        val target = instrumentation.targetContext
        // Keep original JSON number spellings: JSONObject serialization can erase .0.
        val canonical = target.assets.open("native_access_wire.json").use { it.readBytes() }
        NativeVoiceContract.decode(canonical)
        val raw = canonical.toString(Charsets.UTF_8)
        val voiceStart = raw.indexOf("\"roomVoice\": {").also { check(it > 0) }
        for ((field, expected) in listOf("schemaVersion" to 1, "authorizationVersion" to 1, "pageSize" to 20)) {
            val start = if (field == "schemaVersion") 0 else voiceStart
            val match = Regex("\"" + field + "\"\\s*:\\s*" + expected).find(raw, start)!!
            for (bad in listOf("\"$expected\"", "true", "false", "$expected.0", "${expected}e0", "null", "0", "-1", "2147483648")) {
                val changed = raw.replaceRange(match.range, "\"$field\":$bad")
                assertTrue("Reject canonical field $field as $bad", runCatching { NativeVoiceContract.decode(changed.toByteArray(Charsets.UTF_8)) }.isFailure)
            }
        }
        val nonce = args.getString("voiceNonce")!!.also { check(Regex("[a-f0-9]{24}").matches(it)) }
        val root = File(target.cacheDir, "voice-selector-" + java.util.UUID.randomUUID()).apply { check(mkdir()) }
        val context = object: ContextWrapper(target) {
            override fun getApplicationContext(): Context = this
            override fun getNoBackupFilesDir() = File(root, "no-backup").apply { mkdirs() }
            override fun getFilesDir() = File(root, "files").apply { mkdirs() }
            override fun getCacheDir() = File(root, "cache").apply { mkdirs() }
        }
        fun file(stage: String) = File(target.cacheDir, "voice_" + nonce + "_" + stage)
        fun mark(stage: String) { file(stage).writeText("1") }
        fun marked(stage: String) = file(stage).let { it.isFile && it.readText() == "1" }
        val ca = NativeDeviceIdentity.parseCertificates(String(Base64.decode(args.getString("ca"), Base64.DEFAULT), Charsets.US_ASCII)).single()
        val connection = VehicleConnection.synthetic(context, "voice_selector_" + nonce, args.getString("port")!!.toInt(), ca,
            args.getString("eventsPort")!!.toInt())
        val hostSnapshots = AtomicInteger(0); val hostInvalidations = AtomicInteger(0); val hostClosed = AtomicInteger(0)
        val firstCleared = AtomicInteger(0); val nextCleared = AtomicInteger(0)
        val oldData = AtomicInteger(0)
        var host: Closeable? = null
        var voice: NativeVoiceClient? = null
        var replacement: NativeVoiceClient? = null
        val observer = object: NativeVoiceObserver { override fun onInvalidated() { firstCleared.incrementAndGet() } }
        fun watermark(): Pair<Int, Int> {
            instrumentation.waitForIdleSync(); var value = 0 to 0
            instrumentation.runOnMainSync { value = hostInvalidations.get() to firstCleared.get() }; return value
        }
        try {
            connection.setSetupAllowed(true); connection.setForeground(true)
            waitFor("own isolated profile") { connection.status().stage == VehicleConnection.Stage.READY }
            connection.start("Synthetic Voice selector")
            waitFor("current base2 grant") { connection.status().stage == VehicleConnection.Stage.CONNECTED }
            assertTrue(connection.status().approvedOptionalScopes.isEmpty())
            connection.connectEvents(object: VehicleEventsListener {
                override fun onEvent(event: VehicleEvent) {
                    if (event.type == "snapshot") hostSnapshots.incrementAndGet()
                    if (event.type == "invalidate" && "devices" in event.resources) hostInvalidations.incrementAndGet()
                }
                override fun onClosed() { hostClosed.incrementAndGet() }
                override fun onUnavailable() { hostClosed.incrementAndGet() }
            }) { host = it.getOrThrow() }
            waitFor("host baseline snapshot") { host != null && hostSnapshots.get() == 1 }
            val current = connection.voice(); voice = current
            receive<Unit> { current.open(observer, it) }.getOrThrow()
            assertEquals(NativeVoiceClient.State.SELECTING, current.status())
            assertEquals(NativeVoiceFailure.Kind.CONSENT_REQUIRED,
                (receive<VoiceRoomPage> { current.listRooms(callback=it) }.exceptionOrNull() as NativeVoiceFailure).kind)
            assertTrue(receive<Unit> { current.open(observer, it) }.isFailure)
            val other = connection.voice(); replacement = other
            assertTrue(receive<Unit> { other.open(object: NativeVoiceObserver {}, it) }.isFailure)
            assertEquals(NativeVoiceClient.State.SELECTING, current.status()); assertEquals(0, hostClosed.get())
            val before = watermark(); mark("selector-purpose-request")
            waitFor("explicit TX room choice") { marked("selector-purpose-done") }
            waitFor("exact new authority observed") { hostInvalidations.get() > before.first && firstCleared.get() > before.second }
            waitFor("old selecting channel unavailable") { current.status() == NativeVoiceClient.State.UNAVAILABLE }
            instrumentation.waitForIdleSync()
            receive<Unit> { current.open(observer, it) }.getOrThrow()
            val page = receive<VoiceRoomPage> { current.listRooms(callback=it) }.getOrThrow()
            assertEquals(1, page.items.size); assertEquals(setOf(VoiceDirection.TRANSMIT), page.items.single().availableDirections)
            assertNull(page.nextCursor); assertEquals(0, hostClosed.get()); mark("selector-positive")
            mark("selector-hold-request"); waitFor("held list armed") { marked("selector-hold-armed") }
            current.listRooms { oldData.incrementAndGet() }
            waitFor("real list response held") { marked("selector-hold-entered") }
            val clearedBeforeClose = firstCleared.get()
            val nextOpened = AtomicReference<Result<Unit>?>(null)
            instrumentation.runOnMainSync {
                current.close()
                other.open(object: NativeVoiceObserver { override fun onInvalidated() { nextCleared.incrementAndGet() } }) { nextOpened.set(it) }
            }
            mark("selector-replacement-queued")
            waitFor("old return and replacement open") { nextOpened.get() != null }; nextOpened.get()!!.getOrThrow()
            waitFor("mandatory old cache clear") { firstCleared.get() == clearedBeforeClose + 1 }
            val fresh = receive<VoiceRoomPage> { other.listRooms(callback=it) }.getOrThrow()
            assertEquals(page.items.single().roomId, fresh.items.single().roomId)
            assertEquals(0, oldData.get()); assertEquals(0, hostClosed.get())
            assertEquals(NativeVoiceClient.State.SELECTING, other.status())
            assertEquals(NativeVoiceFailure.Kind.CLOSED,
                (receive<Unit> { current.open(observer, it) }.exceptionOrNull() as NativeVoiceFailure).kind)
            connection.setForeground(false)
            waitFor("foreground loss clears own data") { other.status() == NativeVoiceClient.State.UNAVAILABLE && nextCleared.get() == 1 }
            assertTrue(receive<VoiceRoomPage> { other.listRooms(callback=it) }.isFailure)
            assertTrue(receive<Unit> { other.open(object: NativeVoiceObserver {}, it) }.isFailure)
            assertEquals(NativeVoiceClient.State.UNAVAILABLE, other.status())
            assertEquals(1, nextCleared.get())
            mark("selector-complete")
        } finally { voice?.close(); replacement?.close(); host?.close(); connection.close() }
    }
}
