package io.wegoh.app.nativeauth

import java.security.SecureRandom

/** Server route templates (FastAPI paths) the vehicle calls; reports may name only these.
 * The server skips (and counts) a report whose `METHOD template` it does not mount, so this list
 * matches the server's parameter names exactly. Functional routes mirror native_access_wire.json.
 */
internal object NativeRouteTemplates {
    private val TEMPLATES=listOf(
        "GET /v1/account",
        "PUT /v1/account",
        "GET /v1/app-release",
        "GET /v1/device/command-inbox",
        "POST /v1/device/client-reports",
        "GET /v1/device/command-receiver",
        "PUT /v1/device/command-receiver",
        "PUT /v1/device/control-support",
        "GET /v1/device/functional-permissions",
        "GET /v1/device/music-permission",
        "GET /v1/device/permissions",
        "POST /v1/device/requests/{identifier}/ack",
        "POST /v1/device/requests/{identifier}/claim",
        "GET /v1/device/vehicle-domain",
        "GET /v1/device/vehicle-profile",
        "PUT /v1/device/vehicle-profile",
        "WS /v1/events",
        "POST /v1/local/packs/{pack_id}/versions/{version}/reports",
        "POST /v1/local/visits",
        "GET /v1/native/courses/library",
        "GET /v1/native/courses/public/{pack_id}/versions/{version}",
        "POST /v1/native/courses/{pack_id}/versions/{version}/route-preview",
        "POST /v1/native/diagnostics",
        "GET /v1/native/rooms/{room}/device-reports",
        "GET /v1/native/rooms/{room}/missions",
        "POST /v1/native/rooms/{room}/missions/{mission}/progress",
        "GET /v1/native/rooms/{room}/music-permissions",
        "POST /v1/native/rooms/{room}/reports/location",
        "POST /v1/native/rooms/{room}/reports/visits",
        "GET /v1/native/rooms/{room}/voice-permissions",
        "GET /v1/native/trips/{id}",
        "PATCH /v1/native/trips/{id}",
        "POST /v1/native/trips/{id}/cars",
        "DELETE /v1/native/trips/{id}/cars/{carId}",
        "PATCH /v1/native/trips/{id}/cars/{carId}",
        "POST /v1/native/trips/{id}/cars/{carId}/courses/{packId}/complete",
        "PUT /v1/native/trips/{id}/cars/{carId}/courses/{packId}/driving-score",
        "PUT /v1/native/trips/{id}/cars/{carId}/driving-score",
        "GET /v1/native/trips/{id}/cars/{carId}/places",
        "POST /v1/native/trips/{id}/cars/{carId}/places",
        "DELETE /v1/native/trips/{id}/cars/{carId}/places/{placeId}",
        "PUT /v1/native/trips/{id}/cars/{carId}/ride",
        "POST /v1/native/trips/{id}/cars/{carId}/ride-invites",
        "DELETE /v1/native/trips/{id}/cars/{carId}/ride-invites/{inviteId}",
        "DELETE /v1/native/trips/{id}/cars/{carId}/riders/{accountId}",
        "POST /v1/native/trips/{id}/cars/{carId}/route-arrivals",
        "PUT /v1/native/trips/{id}/cars/{carId}/route-order",
        "PUT /v1/native/trips/{id}/cars/{carId}/route-progress",
        "POST /v1/native/trips/{id}/courses",
        "DELETE /v1/native/trips/{id}/courses/{packId}",
        "GET /v1/native/trips/{id}/driving-score",
        "GET /v1/native/trips/{id}/driving-versus",
        "POST /v1/native/trips/{id}/finish",
        "GET /v1/native/trips/{id}/friends",
        "DELETE /v1/native/trips/{id}/link",
        "POST /v1/native/trips/{id}/link",
        "GET /v1/native/trips/{id}/location-sharing",
        "PATCH /v1/native/trips/{id}/location-sharing",
        "POST /v1/native/trips/{id}/members",
        "DELETE /v1/native/trips/{id}/members/{accountId}",
        "DELETE /v1/native/trips/{id}/ride",
        "POST /v1/native/trips/{id}/signals/candidates",
        "POST /v1/native/trips/{id}/start",
        "GET /v1/native/trips/{id}/voice-participation",
        "PATCH /v1/native/trips/{id}/voice-participation",
        "GET /v1/native/trips/{room}/missions",
        "GET /v1/native/trips/{trip}/device-reports",
        "GET /v1/native/trips/{trip}/listen-together",
        "POST /v1/native/trips/{trip}/listen-together/end",
        "PUT /v1/native/trips/{trip}/listen-together/participation",
        "POST /v1/native/trips/{trip}/listen-together/start",
        "GET /v1/native/trips/{trip}/locations",
        "POST /v1/native/trips/{trip}/locations/me",
        "GET /v1/native/trips/{trip}/music-permissions",
        "POST /v1/native/trips/{trip}/reports/location",
        "POST /v1/native/trips/{trip}/reports/visits",
        "GET /v1/native/trips/{trip}/vehicle-domain",
        "GET /v1/native/trips/{trip}/voice-permissions",
        "GET /v1/native/voice-rooms",
        "GET /v1/packs",
        "GET /v1/packs/{pack_id}/versions/{version}",
        "GET /v1/playlists",
        "GET /v1/playlists/{playlist_id}",
        "POST /v1/recommendations/feedback",
        "POST /v1/recommendations/query",
        "GET /v1/recommendations/settings",
        "POST /v1/social/blocks",
        "DELETE /v1/social/blocks/{target}",
        "GET /v1/social/cautions",
        "GET /v1/social/cautions/{item}",
        "POST /v1/social/friends/requests",
        "POST /v1/social/friends/requests/{target}/respond",
        "DELETE /v1/social/friends/{target}",
        "GET /v1/social/history",
        "POST /v1/social/history",
        "DELETE /v1/social/history/{item}",
        "GET /v1/social/history/{item}",
        "PUT /v1/social/history/{item}",
        "POST /v1/social/history/{item}/trace-batches",
        "POST /v1/social/history/{item}/visits",
        "DELETE /v1/social/history/{item}/visits/{vid}",
        "PUT /v1/social/history/{item}/visits/{vid}",
        "GET /v1/social/history/{item}/visits/{visit}/photos/{photo}",
        "GET /v1/social/invites/{code}",
        "GET /v1/social/overview",
        "POST /v1/social/rooms",
        "POST /v1/social/rooms/join",
        "GET /v1/social/rooms/{room}",
        "PATCH /v1/social/rooms/{room}/consents",
        "GET /v1/social/rooms/{room}/device-command-access",
        "GET /v1/social/rooms/{room}/device-requests",
        "POST /v1/social/rooms/{room}/device-requests",
        "DELETE /v1/social/rooms/{room}/device-requests/{identifier}",
        "POST /v1/social/rooms/{room}/history",
        "POST /v1/social/rooms/{room}/leave",
        "DELETE /v1/social/rooms/{room}/music",
        "GET /v1/social/rooms/{room}/music",
        "PUT /v1/social/rooms/{room}/music",
        "PATCH /v1/social/rooms/{room}/role",
        "POST /v1/social/rooms/{room}/signals",
        "DELETE /v1/social/rooms/{room}/signals/{identifier}/vote",
        "POST /v1/social/rooms/{room}/signals/{identifier}/vote",
        "GET /v1/social/trips",
        "GET /v1/social/trips/{id}",
        "GET /v1/social/trips/{id}/places",
        "POST /v1/social/trips/{id}/respond",
        "GET /v1/social/trips/{id}/signals",
        "POST /v1/social/trips/{id}/signals",
        "POST /v1/social/trips/{id}/signals/{signal}/finish",
        "DELETE /v1/social/trips/{id}/signals/{signal}/vote",
        "POST /v1/social/trips/{id}/signals/{signal}/vote",
        "GET /v1/social/trips/{id}/workspace",
        "GET /v1/social/trips/{room}/voice/filters",
        "PUT /v1/social/trips/{trip}/music/now-playing",
        "GET /v1/social/trips/{trip}/music/saved-playlists",
        "POST /v1/social/trips/{trip}/music/saved-playlists",
        "PATCH /v1/social/trips/{trip}/music/saved-playlists/{item}/position",
        "GET /v1/social/trips/{trip}/voice-clips",
        "POST /v1/social/trips/{trip}/voice-clips",
        "GET /v1/social/trips/{trip}/voice-clips/{identifier}",
        // Voice sockets: team_voice.py mounts the room socket on the room router and the trip socket on the trip router.
        "WS /v1/social/rooms/{room}/voice",
        "WS /v1/social/trips/{trip}/voice",
        "GET /v1/studio/packs",
        "GET /v1/studio/packs/{pack_id}/versions/{version}",
    )
    private class Row(val method: String,val template: String,val pattern: Regex,val literals: Int)
    private val parameter=Regex("\\{[A-Za-z_]+\\}")
    private fun row(entry: String): Row {
        val (method,template)=entry.split(' ',limit=2)
        val pattern=template.split('/').joinToString("/") {if(parameter.matches(it))"[^/]+" else Regex.escape(it)}
        return Row(method,template,Regex(pattern),template.split('/').count {it.isNotEmpty() && !parameter.matches(it)})
    }
    // More literal segments first, so a fixed path never resolves to a parameter template.
    private val rows=TEMPLATES.map(::row).sortedByDescending {it.literals}
    val all: List<String> get()=TEMPLATES

    /** The template for a concrete path (query ignored), or null when the path is not one the server mounts. */
    fun match(method: String,path: String): String? {
        val route=path.substringBefore('?')
        return rows.firstOrNull {it.method==method && it.pattern.matches(route)}?.template
    }
}

internal enum class NetResult(val wire: String) {
    OK("ok"), HTTP_ERROR("http_error"), NETWORK_ERROR("network_error"), TIMEOUT("timeout"),
    CANCELLED("cancelled"), INVALID_RESPONSE("invalid_response"),
    /** Failed on the device before anything was sent (a local precondition). */
    NOT_SENT("not_sent")
}

/** One exchange's correlation ids. The same values go out as X-Request-Id and traceparent and
 * into the server's wegoh_access_v1 line, so a vehicle log line and the server record join on req_id.
 */
internal class NetExchange internal constructor(val method: String,val route: String,val reportable: Boolean,
    val requestId: String,val traceId: String,private val spanId: String,private val startedNanos: Long) {
    @Volatile var status: Int?=null
    val traceparent: String get()="00-$traceId-$spanId-00"
    fun elapsedMs(now: Long=System.nanoTime())=((now-startedNanos)/1_000_000).coerceIn(0,600_000)
    val headers: List<Pair<String,String>> get()=listOfNotNull("X-Request-Id" to requestId,"traceparent" to traceparent,
        NativeNetLog.clientVersion?.let {NativeNetLog.CLIENT_HEADER to it})
    override fun toString()="NetExchange($method $route)"
}

/** A response the app received but refused. `path` names the rejected key, never its value. */
internal class DecodeRejection(val path: String,val rule: String)

internal object NativeNetLog {
    const val CLIENT_HEADER="X-WegoH-Client"
    private val versionPattern=Regex("[0-9][0-9A-Za-z.+-]{0,31}")
    private val word=Regex("[A-Za-z][A-Za-z0-9_]{0,63}")
    private val code=Regex("[A-Z][A-Z0-9_]{1,63}")
    private val decodePath=Regex("[A-Za-z0-9_$.\\[\\]-]{1,160}")
    private val random=SecureRandom()
    /** Set once at process start by the app (this module has no app BuildConfig); unset sends no header. */
    @Volatile var clientVersion: String?=null
    /** `android/<versionName>+<versionCode>`, the form the server's X-WegoH-Client parser accepts. */
    internal fun clientValue(name: String,code: Long): String =
        "android/"+(("$name+$code").takeIf {versionPattern.matches(it)} ?: "0+$code")

    @Volatile internal var sink: (String)->Unit={android.util.Log.i("WegoH",it)}
    @Volatile internal var reports: (ClientDiagnosticEvent)->Unit={ClientDiagnostics.report(it)}
    private val lastResponse=ThreadLocal<NetExchange?>()

    private fun randomHex(bytes: Int): String {
        while(true) {
            val value=ByteArray(bytes).also {random.nextBytes(it)}.joinToString("") {"%02x".format(it.toInt() and 255)}
            if(value.any {it!='0'})return value
        }
    }

    fun start(method: String,path: String,now: Long=System.nanoTime()): NetExchange {
        val template=NativeRouteTemplates.match(method,path)
        return NetExchange(method,template ?: derived(path),template!=null,randomHex(16),randomHex(16),randomHex(8),now)
    }
    /** Path with identifier-like segments masked, for a route the template table does not list. */
    private fun derived(path: String)=NativeFunctionalDiagnostics.pathTemplate("GET",path.substringBefore('?')).substringAfter(' ')

    /** One `net:` line per exchange; failures that may not have reached the server are also reported. */
    fun finish(exchange: NetExchange,failure: Throwable?,now: Long=System.nanoTime(),remember: Boolean=true) {
        if(remember)lastResponse.set(null)
        if(failure==null) {
            write(exchange,NetResult.OK,"none",null,now)
            if(remember)lastResponse.set(exchange)
            return
        }
        val (result,reason)=classify(exchange.status,failure)
        val decode=if(result==NetResult.INVALID_RESPONSE)DecodeRejection("$",rule(failure)) else null
        write(exchange,result,reason,decode,now)
    }

    /** A decode step after the last exchange on this thread rejected its response. Only the first call
     * after an exchange counts; a precondition failure ([IllegalArgumentException]) is not a decode. */
    fun decodeFailed(failure: Throwable,now: Long=System.nanoTime()) {
        val exchange=lastResponse.get() ?: return
        lastResponse.set(null)
        if(failure is IllegalArgumentException || failure is java.io.IOException || failure is InterruptedException ||
            failure is NativeApiClient.Failure || failure is NativeSocialFailure)return
        val field=(failure as? NativeTripFieldFailure)?.field?.takeIf {decodePath.matches(it)}
        write(exchange,NetResult.INVALID_RESPONSE,reason(failure),DecodeRejection(field ?: "$",rule(failure)),now)
    }
    /** A socket that failed: a handshake answered with another status is that HTTP error, otherwise transport. */
    fun socketFailed(exchange: NetExchange,failure: Throwable,status: Int?) {
        if(status!=null)exchange.status=status
        finish(exchange,if(status!=null && status!=101)NativeApiClient.Failure(status,"WS_HANDSHAKE_REJECTED") else failure,remember=false)
    }
    /** The end of an open socket; the close code is the server's or the app's own decision, not a failure. */
    fun closed(exchange: NetExchange,code: Int,now: Long=System.nanoTime()) {
        write(exchange,NetResult.OK,"close_"+code.coerceIn(0,4999),null,now)
    }
    /** Plain HttpURLConnection calls outside [NativeApiClient]: same headers and line. [block] sets the status. */
    inline fun <T> traced(method: String,path: String,connection: java.net.HttpURLConnection,block: (NetExchange)->T): T {
        val net=start(method,path)
        net.headers.forEach {(name,value)->connection.setRequestProperty(name,value)}
        var failure: Throwable?=null
        try {return block(net)} catch(error: Throwable) {failure=error;throw error} finally {
            finish(net,failure ?: net.status?.takeIf {it !in 200..299}?.let {NativeApiClient.Failure(it,"HTTP_STATUS")},remember=false)
        }
    }
    /** Forget the previous exchange so an unrelated later failure is not attributed to it. */
    fun forget()=lastResponse.set(null)

    internal fun classify(status: Int?,failure: Throwable): Pair<NetResult,String> = when {
        failure is NativeApiClient.Failure->NetResult.HTTP_ERROR to failure.code
        failure is NativeSocialFailure && failure.httpStatus!=null->
            NetResult.HTTP_ERROR to (NativeSocialErrorCodec.safeCode(failure.serverErrorCode) ?: failure.kind.name)
        failure is java.net.SocketTimeoutException->NetResult.TIMEOUT to "SocketTimeoutException"
        // OkHttp's callTimeout ends the call with InterruptedIOException("timeout").
        failure is java.io.InterruptedIOException && failure.message=="timeout"->NetResult.TIMEOUT to "InterruptedIOException:callTimeout"
        // Thread interruption, or OkHttp's Call.cancel() / WebSocket.cancel() (IOException("Canceled")).
        failure is java.io.InterruptedIOException || failure is InterruptedException ||
            (failure is java.io.IOException && failure.message=="Canceled")->NetResult.CANCELLED to reason(failure)
        failure is java.io.IOException->NetResult.NETWORK_ERROR to reason(failure)
        status==null->NetResult.NOT_SENT to reason(failure)
        status in 100..299->NetResult.INVALID_RESPONSE to reason(failure)
        else->NetResult.HTTP_ERROR to reason(failure)
    }
    /** Class name and, only when it is a fixed uppercase code, the message. Free text is never kept. */
    private fun reason(failure: Throwable): String {
        val name=failure.javaClass.simpleName.takeIf {word.matches(it)} ?: "other"
        return failure.message?.takeIf {code.matches(it)}?.let {"$name:$it"} ?: name
    }
    /** Server decode rules: missing, type, format, range, enum, length, unknown, syntax. */
    internal fun rule(failure: Throwable): String = when {
        failure.message=="NATIVE_RESPONSE_TOO_LARGE"->"length"
        failure.message in setOf("NATIVE_JSON_RESPONSE_REQUIRED","NATIVE_SOCIAL_RESPONSE_INVALID")->"format"
        failure.message in setOf("NATIVE_JSON_RESPONSE_INVALID","NATIVE_JSON_OBJECT_REQUIRED","NATIVE_JSON_ARRAY_REQUIRED")->"type"
        failure is org.json.JSONException && failure.message?.startsWith("No value for")==true->"missing"
        failure is org.json.JSONException && failure.message?.contains("cannot be converted")==true->"type"
        failure is org.json.JSONException->"syntax"
        failure is ClassCastException->"type"
        failure is NumberFormatException || failure is java.time.format.DateTimeParseException->"format"
        else->"unknown"
    }

    internal fun line(exchange: NetExchange,result: NetResult,reason: String,decode: DecodeRejection?,now: Long): String =
        "net: req_id=${exchange.requestId} trace_id=${exchange.traceId} method=${exchange.method} route=${exchange.route} "+
            "status=${exchange.status ?: 0} dur_ms=${exchange.elapsedMs(now)} result=${result.wire} reason=$reason"+
            (decode?.let {" decode_path=${it.path} decode_rule=${it.rule}"} ?: "")

    private fun write(exchange: NetExchange,result: NetResult,reason: String,decode: DecodeRejection?,now: Long) {
        runCatching {sink(line(exchange,result,reason,decode,now))}
        if(exchange.reportable && exchange.route!=ClientDiagnostics.ROUTE && result in REPORTED)
            runCatching {reports(ClientDiagnosticEvent(result.wire,exchange.method,exchange.route,exchange.requestId,exchange.traceId,
                exchange.status,decode?.path,decode?.rule,exchange.elapsedMs(now)))}
    }
    /** The server already records every HTTP error it returned; these are the failures only the app sees. */
    private val REPORTED=setOf(NetResult.NETWORK_ERROR,NetResult.TIMEOUT,NetResult.INVALID_RESPONSE)
}
