package io.wegoh.app.nativeauth

import android.os.SystemClock
import okhttp3.Authenticator
import okhttp3.ConnectionPool
import okhttp3.ConnectionSpec
import okhttp3.CookieJar
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.TlsVersion
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import java.io.Closeable
import java.net.URI
import java.util.ArrayDeque
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import javax.net.ssl.SSLSocketFactory
import javax.net.ssl.X509TrustManager

/** Internal worker callbacks. The client must check its current authority before adopting data. */
internal interface NativeVoiceSocketListener {
    fun onEvent(event: VoiceServerEvent)
    /** True transfers this mutable PCM buffer; the receiver must erase it after use. */
    fun onFrame(frame: VoicePcmFrame): Boolean
    fun onClosed(code: Int)
    fun onUnavailable()
}

internal interface NativeVoiceWire: Closeable {
    fun control(control: VoiceControl): Boolean
    fun frame(sequence: Long, pcm: ByteArray): Boolean
}

/** SDK-owned fixed Voice WS only; no public URL, token, TLS policy or raw socket escape. */
internal class NativeVoiceSocket private constructor(): NativeVoiceWire {
    private val finished = AtomicBoolean(false)
    private val ready = AtomicBoolean(false)
    private val sending = Any()
    private val controls = ArrayDeque<Long>()
    private var frameTokens = 6.0
    private var frameAt = SystemClock.elapsedRealtimeNanos()
    private lateinit var socket: WebSocket
    private lateinit var client: OkHttpClient
    private lateinit var pool: ConnectionPool
    private lateinit var listener: NativeVoiceSocketListener

    private fun release() { pool.evictAll(); client.dispatcher.executorService.shutdown() }
    private fun unavailable(code: Int = 1008) {
        if (!finished.compareAndSet(false, true)) return
        ready.set(false); socket.close(code, null); socket.cancel(); release()
        listener.onUnavailable()
    }
    override fun control(control: VoiceControl): Boolean {
        var failed: Int? = null
        val sent = synchronized(sending) {
            if (finished.get() || !ready.get()) return@synchronized false
            val now = SystemClock.elapsedRealtimeNanos()
            while (controls.isNotEmpty() && now - controls.first >= 1_000_000_000L) controls.removeFirst()
            if (controls.size >= 10) { failed = 1008; return@synchronized false }
            val body = NativeVoiceCodec.control(control)
            if (socket.queueSize() + body.toByteArray().size > NativeVoiceCodec.FRAME_BYTES * 8L) {
                failed = 1013; return@synchronized false
            }
            controls.addLast(now)
            socket.send(body).also { if (!it) failed = 1013 }
        }
        failed?.let { unavailable(it) }
        return sent
    }
    override fun frame(sequence: Long, pcm: ByteArray): Boolean {
        var failed: Int? = null
        val sent = synchronized(sending) {
            if (finished.get() || !ready.get()) return@synchronized false
            val bytes = NativeVoiceCodec.frame(sequence, pcm)
            try {
                val now = SystemClock.elapsedRealtimeNanos()
                frameTokens = minOf(6.0, frameTokens + (now - frameAt).coerceAtLeast(0) / 1_000_000_000.0 * 55.0)
                frameAt = now
                if (frameTokens < 1.0 || socket.queueSize() + bytes.size > NativeVoiceCodec.FRAME_BYTES * 8L) {
                    failed = 1013; return@synchronized false
                }
                frameTokens -= 1.0
                socket.send(ByteString.of(*bytes)).also { if (!it) failed = 1013 }
            } finally { bytes.fill(0) }
        }
        failed?.let { unavailable(it) }
        return sent
    }
    override fun close() {
        if (finished.compareAndSet(false, true)) { ready.set(false); socket.cancel(); release() }
    }
    companion object {
        fun open(endpoint: URI, factory: SSLSocketFactory, trust: X509TrustManager, authorization: String,
            functionalRevision: Long, roomRevision: Long, listener: NativeVoiceSocketListener): NativeVoiceSocket {
            check(endpoint.scheme == "wss" && endpoint.userInfo == null && endpoint.query == null && endpoint.fragment == null)
            val trip = Regex("/v1/social/trips/[a-f0-9]{32}/voice").matches(endpoint.path)
            check(trip || Regex("/v1/social/rooms/[a-f0-9]{32}/voice").matches(endpoint.path))
            check(endpoint.host == "api-wegoh.devforest.io" && endpoint.port == -1 ||
                NativeBuildType.DEBUG && endpoint.host == "127.0.0.1" && endpoint.port in 1024..65535)
            check(functionalRevision in 1..Int.MAX_VALUE.toLong() && roomRevision in (if (trip) 0 else 1)..Int.MAX_VALUE.toLong())
            val result = NativeVoiceSocket(); result.listener = listener
            val opened = CountDownLatch(1); val failure = AtomicBoolean(false)
            result.pool = ConnectionPool(0, 1, TimeUnit.SECONDS)
            result.client = OkHttpClient.Builder().sslSocketFactory(factory, trust)
                .connectionSpecs(listOf(ConnectionSpec.Builder(ConnectionSpec.MODERN_TLS).tlsVersions(TlsVersion.TLS_1_3).build()))
                .followRedirects(false).followSslRedirects(false).retryOnConnectionFailure(false)
                .authenticator(Authenticator.NONE).proxyAuthenticator(Authenticator.NONE).cookieJar(CookieJar.NO_COOKIES)
                .connectionPool(result.pool).connectTimeout(10, TimeUnit.SECONDS).readTimeout(30, TimeUnit.SECONDS)
                .callTimeout(10, TimeUnit.SECONDS).build()
            // WebSocket callbacks may arrive before newWebSocket returns. Install the handle
            // from each callback before any cleanup; only internal callers see this object.
            val live = AtomicReference<WebSocket?>()
            fun handle(socket: WebSocket) { live.compareAndSet(null, socket); result.socket = live.get()!! }
            val net = NativeNetLog.start("WS", endpoint.path)
            val request = Request.Builder().url(endpoint.toString())
                .header("Authorization", authorization)
                .header("X-WegoH-Functional-Revision", functionalRevision.toString())
                .header("X-WegoH-Room-Voice-Revision", roomRevision.toString())
            net.headers.forEach { (name, value) -> request.header(name, value) }
            result.socket = result.client.newWebSocket(request.build(), object: WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    handle(webSocket); net.status = response.code
                    if (response.code != 101 || response.handshake?.tlsVersion != TlsVersion.TLS_1_3 || result.finished.get()) {
                        if (!result.finished.get()) NativeNetLog.finish(net, IllegalStateException("NATIVE_VOICE_HANDSHAKE_INVALID"), remember = false)
                        failure.set(true); result.unavailable(); opened.countDown(); return
                    }
                    NativeNetLog.finish(net, null, remember = false)
                    opened.countDown()
                }
                override fun onMessage(webSocket: WebSocket, text: String) {
                    handle(webSocket); if (result.finished.get()) return
                    try {
                        val event = NativeVoiceCodec.event(text.toByteArray(Charsets.UTF_8))
                        if (event is VoiceServerEvent.Ready) check(result.ready.compareAndSet(false, true))
                        else check(result.ready.get())
                        listener.onEvent(event)
                    } catch (_: Exception) { result.unavailable() }
                }
                override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                    handle(webSocket); if (result.finished.get()) return
                    var frame: VoicePcmFrame? = null
                    try {
                        check(result.ready.get()); frame = NativeVoiceCodec.frame(bytes.toByteArray())
                        if (!listener.onFrame(frame)) { frame.erase(); result.unavailable(1013) }
                    } catch (_: Exception) { frame?.erase(); result.unavailable() }
                }
                override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                    handle(webSocket); webSocket.close(code, null)
                }
                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                    handle(webSocket); opened.countDown()
                    if (result.finished.compareAndSet(false, true)) {
                        NativeNetLog.closed(net, code)
                        result.ready.set(false); result.release(); listener.onClosed(code)
                    }
                }
                override fun onFailure(webSocket: WebSocket, error: Throwable, response: Response?) {
                    if (!result.finished.get()) NativeNetLog.socketFailed(net, error, response?.code)
                    handle(webSocket); failure.set(true); opened.countDown(); result.unavailable()
                }
            })
            live.compareAndSet(null, result.socket)
            if (!opened.await(11, TimeUnit.SECONDS) || failure.get() || result.finished.get()) {
                result.close(); error("NATIVE_VOICE_UNAVAILABLE")
            }
            return result
        }
    }
}
