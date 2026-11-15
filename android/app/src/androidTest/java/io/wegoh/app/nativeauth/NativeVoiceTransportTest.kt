package io.wegoh.app.nativeauth

import android.content.Context
import android.content.ContextWrapper
import android.test.InstrumentationTestCase
import android.test.InstrumentationTestRunner
import android.util.Base64
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference

/** Private fixed transport probe; not a public Voice client, microphone or onboarding proof. */
@Suppress("DEPRECATION")
class NativeVoiceTransportTest: InstrumentationTestCase() {
    private fun waitFor(label: String, predicate: () -> Boolean) {
        val until = android.os.SystemClock.elapsedRealtime() + 25000
        while (android.os.SystemClock.elapsedRealtime() < until) { if (predicate()) return; Thread.sleep(20) }
        fail("Owned voice transport timeout: $label")
    }
    private class Receiver: NativeVoiceSocketListener {
        val ready = CountDownLatch(1)
        val granted = CountDownLatch(1)
        val frame = CountDownLatch(1)
        val ended = CountDownLatch(1)
        val received = AtomicInteger(0)
        val unavailable = AtomicInteger(0)
        val sequence = VoiceReceiveSequence()
        override fun onEvent(event: VoiceServerEvent) {
            when (event) {
                is VoiceServerEvent.Ready -> { event.floor?.let { sequence.begin(it.leaseId, true) }; ready.countDown() }
                is VoiceServerEvent.Granted -> granted.countDown()
                is VoiceServerEvent.Started -> sequence.begin(event.floor.leaseId, false)
                is VoiceServerEvent.Ended -> { sequence.end(); ended.countDown() }
                else -> Unit
            }
        }
        override fun onFrame(frame: VoicePcmFrame): Boolean {
            try {
                sequence.accept(frame)
                check(frame.pcm.size == 640 && frame.pcm.indices.all { frame.pcm[it] == if (it % 2 == 0) 1.toByte() else 0.toByte() })
                received.incrementAndGet(); this.frame.countDown(); return true
            } finally { frame.erase() }
        }
        override fun onClosed(code: Int) { unavailable.incrementAndGet() }
        override fun onUnavailable() { unavailable.incrementAndGet() }
    }
    fun testPrivateFixedTlsDirectionsAndFrame() {
        val args = (instrumentation as InstrumentationTestRunner).arguments
        val target = instrumentation.targetContext
        val nonce = args.getString("voiceNonce")!!.also { check(Regex("[a-f0-9]{24}").matches(it)) }
        val root = File(target.cacheDir, "voice-transport-" + java.util.UUID.randomUUID()).apply { check(mkdir()) }
        val context = object: ContextWrapper(target) {
            override fun getApplicationContext(): Context = this
            override fun getNoBackupFilesDir() = File(root, "no-backup").apply { mkdirs() }
            override fun getFilesDir() = File(root, "files").apply { mkdirs() }
            override fun getCacheDir() = File(root, "cache").apply { mkdirs() }
        }
        val profile = "voice_" + nonce
        fun file(stage: String) = File(target.cacheDir, "voice_" + nonce + "_" + stage)
        fun mark(stage: String) { file(stage).writeText("1") }
        fun marked(stage: String) = file(stage).let { it.isFile && it.readText() == "1" }
        val ca = NativeDeviceIdentity.parseCertificates(String(Base64.decode(args.getString("ca"), Base64.DEFAULT), Charsets.US_ASCII)).single()
        val connection = VehicleConnection.synthetic(context, profile, args.getString("port")!!.toInt(), ca, args.getString("eventsPort")!!.toInt())
        val store = NativeConnectionState(context, profile)
        val codec = NativeVoiceCodec(args.getString("noticeVersion")!!.toInt(), args.getString("noticeSha256")!!)
        var socket: NativeVoiceSocket? = null
        fun permission(): FunctionalPermissions {
            val result = AtomicReference<Result<FunctionalPermissions>?>(null)
            connection.readFunctionalPermissions { result.set(it) }
            waitFor("current functional GET") { result.get() != null }
            return result.get()!!.getOrThrow()
        }
        try {
            connection.setSetupAllowed(true); connection.setForeground(true)
            waitFor("isolated ready") { connection.status().stage == VehicleConnection.Stage.READY }
            connection.start("Synthetic Voice transport")
            waitFor("synthetic current grant") { connection.status().stage == VehicleConnection.Stage.CONNECTED }
            val saved = store.read()
            val identity = NativeDeviceIdentity(context, saved.getString("installationId"))
            // Test-only access to this disposable profile. No SDK credential getter or token arguments.
            val token = saved.getJSONObject("access").getJSONObject("credentials").getString("accessToken")
            val api = NativeApiClient.syntheticLoopback(args.getString("port")!!.toInt(), ca, identity, eventsPort=args.getString("eventsPort")!!.toInt())
            assertTrue(permission().approvedPurposes.isEmpty())
            mark("tx-request"); waitFor("explicit owner TX room consent") { marked("tx-done") }
            val tx = permission(); assertEquals(setOf(FunctionalPurpose.ROOM_VOICE_TRANSMIT), tx.approvedPurposes)
            val page = codec.rooms(api.voiceRooms(null, token).toString().toByteArray(), tx, null, System.currentTimeMillis())
            val ref = page.items.single(); assertEquals(setOf(VoiceDirection.TRANSMIT), ref.availableDirections)
            val room = codec.roomPermission(api.voiceRoomPermission(ref.roomId, token).toString().toByteArray(), tx, ref.roomId, System.currentTimeMillis())
            assertEquals(setOf(VoiceDirection.TRANSMIT), room.directions)
            val receiver = Receiver()
            socket = api.connectVoice(ref.roomId, tx.revision, room.revision, token, receiver)
            assertTrue(receiver.ready.await(8, TimeUnit.SECONDS)); assertTrue(socket.control(VoiceControl.REQUEST))
            assertTrue(receiver.granted.await(8, TimeUnit.SECONDS))
            val pcm = ByteArray(640) { if (it % 2 == 0) 1 else 0 }
            try { assertTrue(socket.frame(0, pcm)) } finally { pcm.fill(0) }
            mark("tx-sent"); waitFor("actual peer PCM readback") { marked("tx-received") }
            assertEquals(0, receiver.received.get())
            assertTrue(socket.control(VoiceControl.RELEASE)); assertTrue(receiver.ended.await(8, TimeUnit.SECONDS))
            socket.close(); socket = null
            mark("rx-request"); waitFor("explicit owner RX room consent") { marked("rx-done") }
            val rx = permission(); assertEquals(setOf(FunctionalPurpose.ROOM_VOICE_RECEIVE), rx.approvedPurposes)
            val rxPage = codec.rooms(api.voiceRooms(null, token).toString().toByteArray(), rx, null, System.currentTimeMillis())
            val rxRef = rxPage.items.single(); assertEquals(setOf(VoiceDirection.RECEIVE), rxRef.availableDirections)
            val rxRoom = codec.roomPermission(api.voiceRoomPermission(rxRef.roomId, token).toString().toByteArray(), rx, rxRef.roomId, System.currentTimeMillis())
            val listener = Receiver()
            socket = api.connectVoice(rxRef.roomId, rx.revision, rxRoom.revision, token, listener)
            assertTrue(listener.ready.await(8, TimeUnit.SECONDS)); mark("rx-ready")
            assertTrue(listener.frame.await(8, TimeUnit.SECONDS)); assertEquals(1, listener.received.get())
            // Wrong-direction control is rejected by the current server; no implicit TX approval.
            assertTrue(socket.control(VoiceControl.REQUEST))
            waitFor("RX-only transmit rejection") { listener.unavailable.get() == 1 }
            mark("complete")
        } finally { socket?.close(); connection.close() }
    }
}
