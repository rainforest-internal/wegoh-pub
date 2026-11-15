package io.wegoh.app.nativeauth

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
import org.json.JSONObject
import java.io.Closeable
import java.net.URI
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import javax.net.ssl.SSLSocketFactory
import javax.net.ssl.X509TrustManager

/** Read-only event feed. No token, CSR, certificate or raw exception is exposed. */
interface VehicleEventsListener {
    fun onOpen() {}
    fun onEvent(event: VehicleEvent)
    fun onClosed() {}
    fun onClosed(code: Int) {onClosed()}
    fun onUnavailable() {}
}
class VehicleEvent internal constructor(val type: String, val resources: List<String>, val versions: Map<String,String?>?=null) {
    override fun toString() = "VehicleEvent($type)"
}
/** Exact native resource projection, matching server/native_access_policy.py. */
internal class NativeEventParser(scopes: Set<String>,private val fine: Boolean=false) {
    private val allowed=mapOf("devices" to "device:self:manage","courses" to "courses:read","playlists" to "playlists:read")
        .filterValues {it in scopes}.keys.sorted()
    private var streamEpoch: String?=null
    private var sequence=-1L
    init {check(scopes.containsAll(setOf("account:read","device:self:manage")) &&
        setOf("account:read","account:write","device:self:manage","courses:read","playlists:read").containsAll(scopes))}
    fun decode(text: String): VehicleEvent {
        check(text.toByteArray(Charsets.UTF_8).size<=65536)
        val value=if(fine)StrictNativeJson.parseBusiness(text.toByteArray(Charsets.UTF_8),65536) else StrictNativeJson.parse(text.toByteArray(Charsets.UTF_8),65536)
        val type=value.get("type") as? String ?: error("NATIVE_EVENTS_UNAVAILABLE")
        check(type in setOf("snapshot","invalidate","heartbeat"))
        val fields=if(type=="heartbeat")setOf("type","epoch","seq") else setOf("type","epoch","seq",if(fine)"versions" else "resources")
        check(value.keys().asSequence().toSet()==fields)
        val epoch=value.get("epoch") as? String ?: error("NATIVE_EVENTS_UNAVAILABLE")
        check(Regex("[a-f0-9]{16}").matches(epoch))
        val raw=value.get("seq");check(raw is Int || raw is Long);val seq=(raw as Number).toLong();check(seq in 0..9007199254740991L)
        if(streamEpoch==null)check(type=="snapshot" && seq==0L)
        else check(type!="snapshot" && epoch==streamEpoch && (if(type=="invalidate")seq==sequence+1 else seq==sequence))
        var versions: Map<String,String?>?=null
        val resources=if(type=="heartbeat")emptyList() else if(fine) {
            val entries=value.getJSONObject("versions")
            check(entries.length()<=620)
            val keys=entries.keys().asSequence().toList().sorted()
            check(keys.all {key -> key in setOf("devices","friends","rooms","history","vehicle","recommendations","cautions","commands","profile","music","voice") ||
                key in allowed || Regex("trip\\.[a-f0-9]{32}\\.(detail|route|signals|music|location|voice)").matches(key)})
            versions=keys.associateWith {key ->
                if(entries.isNull(key)){check(type=="invalidate");null}
                else (entries.get(key) as? String ?: error("NATIVE_EVENTS_UNAVAILABLE")).also {check(Regex("[a-f0-9]{32}").matches(it))}
            }
            keys
        } else value.getJSONArray("resources").let {array ->
            check(array.length()<=3)
            (0 until array.length()).map {array.get(it) as? String ?: error("NATIVE_EVENTS_UNAVAILABLE")}
                .also {check(it==it.distinct().sorted() && allowed.containsAll(it))}
        }
        if(type=="snapshot")check(if(fine)resources.containsAll(allowed) else resources==allowed)
        if(type=="invalidate")check(resources.isNotEmpty())
        streamEpoch=epoch;sequence=seq
        return VehicleEvent(type,resources,versions)
    }
}
internal class NativeEventsFailure(val kind: Kind): IllegalStateException("NATIVE_EVENTS_UNAVAILABLE") {
    enum class Kind { TRANSPORT, AUTHORITY, INVALID_RESPONSE }
    companion object {
        fun from(error: Throwable): NativeEventsFailure = when {
            error is NativeEventsFailure->error
            error is NativeApiClient.Failure && (error.status in setOf(401,403) || error.code in setOf("CONSENT_REVOKED","GRANT_EXPIRED","INSTALLATION_REVOKED"))->NativeEventsFailure(Kind.AUTHORITY)
            error is NativeApiClient.Failure && (error.status in setOf(408,429) || error.status in 500..599)->NativeEventsFailure(Kind.TRANSPORT)
            error is java.io.IOException && error !is javax.net.ssl.SSLException && error !is java.net.ProtocolException->NativeEventsFailure(Kind.TRANSPORT)
            else->NativeEventsFailure(Kind.INVALID_RESPONSE)
        }
        fun http(status: Int)=NativeEventsFailure(when(status) {
            401,403->Kind.AUTHORITY
            408,429,in 500..599->Kind.TRANSPORT
            else->Kind.INVALID_RESPONSE
        })
    }
}
internal object NativeEvents {
    private const val SUBPROTOCOL = "wegoh.events.v1"

    fun connector(listener: VehicleEventsListener,scopes: Set<String>,quiet: Boolean=false): NativeApiClient.EventsConnector = NativeApiClient.EventsConnector {endpoint,factory,trust,authorization ->
        open(endpoint,factory,trust,authorization,listener,scopes,quiet)
    }
    private fun open(endpoint: URI, factory: SSLSocketFactory, trust: X509TrustManager,
        authorization: String, listener: VehicleEventsListener,scopes: Set<String>,quiet: Boolean): Closeable {
        check(endpoint.scheme=="wss" && endpoint.userInfo==null && endpoint.query==null && endpoint.fragment==null && endpoint.path=="/v1/events")
        val finished=AtomicBoolean(false);val connected=AtomicBoolean(false)
        val opened=CountDownLatch(1);val failure=AtomicReference<NativeEventsFailure?>()
        val pool=ConnectionPool(0,1,TimeUnit.SECONDS)
        val client=OkHttpClient.Builder().sslSocketFactory(factory,trust)
            .connectionSpecs(listOf(ConnectionSpec.Builder(ConnectionSpec.MODERN_TLS).tlsVersions(TlsVersion.TLS_1_3).build()))
            .followRedirects(false).followSslRedirects(false).retryOnConnectionFailure(false)
            .authenticator(Authenticator.NONE).proxyAuthenticator(Authenticator.NONE).cookieJar(CookieJar.NO_COOKIES)
            .connectionPool(pool).connectTimeout(10,TimeUnit.SECONDS).readTimeout(30,TimeUnit.SECONDS)
            .callTimeout(10,TimeUnit.SECONDS).build()
        val cleaned=AtomicBoolean(false)
        fun cleanup() {
            if(cleaned.compareAndSet(false,true))client.dispatcher.executorService.execute {
                try {pool.evictAll()} finally {client.dispatcher.executorService.shutdown()}
            }
        }
        val parser=NativeEventParser(scopes,fine=true)
        val net=NativeNetLog.start("WS",endpoint.path)
        val request=Request.Builder().url(endpoint.toString()).header("Authorization",authorization).header("Sec-WebSocket-Protocol",SUBPROTOCOL)
        net.headers.forEach {(name,value)->request.header(name,value)}
        val socket=client.newWebSocket(request.build(),object: WebSocketListener() {
            override fun onOpen(webSocket: WebSocket,response: Response) {
                net.status=response.code
                if(response.header("Sec-WebSocket-Protocol")!=SUBPROTOCOL || response.code!=101 || response.handshake?.tlsVersion!=TlsVersion.TLS_1_3 || finished.get()) {
                    // Claim the end before cancel(), so the onFailure that cancel() triggers neither logs again nor races this line.
                    if(finished.compareAndSet(false,true))NativeNetLog.finish(net,IllegalStateException("NATIVE_EVENTS_HANDSHAKE_INVALID"),remember=false)
                    failure.compareAndSet(null,NativeEventsFailure(NativeEventsFailure.Kind.INVALID_RESPONSE));webSocket.cancel();opened.countDown();return
                }
                NativeNetLog.finish(net,null,remember=false)
                connected.set(true)
                opened.countDown()
                listener.onOpen()
            }
            override fun onMessage(webSocket: WebSocket,text: String) {
                if(finished.get())return
                try {
                    listener.onEvent(parser.decode(text))
                } catch(error: Throwable) {if(finished.compareAndSet(false,true)){
                    if(!quiet)WegoLog.w("WegoH","native.events: parse failed reason=${error.javaClass.simpleName} kind=invalid_response")
                    NativeNetLog.finish(net,error,remember=false)
                    webSocket.cancel();listener.onUnavailable()
                }}
            }
            override fun onMessage(webSocket: WebSocket,bytes: ByteString) {
                if(finished.compareAndSet(false,true)){
                    if(!quiet)WegoLog.w("WegoH","native.events: parse failed reason=binary_frame kind=invalid_response")
                    NativeNetLog.finish(net,IllegalStateException("NATIVE_EVENTS_BINARY_FRAME"),remember=false)
                    webSocket.cancel();listener.onUnavailable()
                }
            }
            override fun onClosing(webSocket: WebSocket,code: Int,reason: String) {webSocket.close(code,null)}
            override fun onClosed(webSocket: WebSocket,code: Int,reason: String) {
                if(finished.compareAndSet(false,true)) {
                    if(!quiet && code!=1008)WegoLog.w("WegoH","native.events: connection closed code=$code")
                    NativeNetLog.closed(net,code)
                    listener.onClosed(code)
                }
                cleanup()
            }
            override fun onFailure(webSocket: WebSocket,error: Throwable,response: Response?) {
                if(!quiet && !finished.get())WegoLog.w("WegoH","native.events: connection failed reason=${error.javaClass.simpleName} kind=${NativeEventsFailure.from(error).kind.name.lowercase()} status=${response?.code ?: 0}")
                if(!finished.get())NativeNetLog.socketFailed(net,error,response?.code)
                failure.compareAndSet(null,response?.let {NativeEventsFailure.http(it.code)} ?: NativeEventsFailure.from(error));opened.countDown()
                if(finished.compareAndSet(false,true) && connected.get())listener.onUnavailable()
                cleanup()
            }
        })
        if(!opened.await(11,TimeUnit.SECONDS) || failure.get()!=null || finished.get()) {
            finished.set(true);socket.cancel();cleanup()
            throw failure.get() ?: NativeEventsFailure(NativeEventsFailure.Kind.TRANSPORT)
        }
        return Closeable {if(finished.compareAndSet(false,true))socket.cancel();cleanup()}
    }
}
