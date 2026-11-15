package io.wegoh.app.nativeauth

import android.os.Build
import android.os.Looper
import java.security.KeyStore
import java.io.Closeable
import javax.net.ssl.X509TrustManager
import java.security.cert.X509Certificate
import javax.net.ssl.TrustManagerFactory
import android.util.Base64
import org.json.JSONObject
import java.net.InetAddress
import java.net.Socket
import java.net.URI
import java.security.MessageDigest
import java.security.SecureRandom
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLSocket
import javax.net.ssl.SSLSocketFactory

/** Native API and registration transport; deliberately independent of browser cookies.
 * Call on a worker thread. Returned deviceCode/verifier/tokens are secrets: callers
 * must encrypt stored state with Keystore/AES-GCM, never log it or put it in a URL.
 */
class NativeApiClient private constructor(private val origin: URI,
    private val identity: NativeDeviceIdentity?, private val enrollment: Boolean,
    private val fixtureCa: X509Certificate? = null, private val fixtureEventsPort: Int? = null) {
    private var mutationPermit: NativeMutationGate.Permit?=null
    internal fun <T> withMutationPermit(permit: NativeMutationGate.Permit,action: ()->T): T {
        check(mutationPermit==null)
        mutationPermit=permit
        return try {action()} finally {mutationPermit=null}
    }
    init {
        require(origin.scheme == "https" && origin.userInfo == null && origin.query == null &&
            origin.fragment == null && origin.path.isNullOrEmpty())
        if (fixtureCa != null) check(NativeBuildType.DEBUG && origin.host == "127.0.0.1" && origin.port > 0)
        else require(origin.port == -1 && origin.host == if (enrollment)
            "enroll-wegoh.devforest.io" else "api-wegoh.devforest.io")
    }
    class Failure(val status: Int, val code: String, val retryAfterSeconds: Int? = null) :
        Exception(code)
    class Pkce private constructor(val verifier: String, val challenge: String) {
        override fun toString() = "Pkce(redacted)"
        companion object {
            fun generate(): Pkce {
                val bytes = ByteArray(32).also { SecureRandom().nextBytes(it) }
                val verifier = encode(bytes)
                return Pkce(verifier, encode(MessageDigest.getInstance("SHA-256")
                    .digest(verifier.toByteArray(Charsets.US_ASCII))))
            }
            internal fun restore(verifier: String): Pkce {
                require(Regex("[A-Za-z0-9._~-]{43,128}").matches(verifier))
                return Pkce(verifier, encode(MessageDigest.getInstance("SHA-256")
                    .digest(verifier.toByteArray(Charsets.US_ASCII))))
            }
            private fun encode(bytes: ByteArray) = Base64.encodeToString(bytes,
                Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP)
        }
    }

    internal fun vehicleProfile(token: String): JSONObject=request("GET","/v1/device/vehicle-profile",bearer=token)
    internal fun updateVehicleProfile(plate: String,name: String,revision: Int,token: String): JSONObject=
        request("PUT","/v1/device/vehicle-profile",JSONObject().put("plateNumber",plate).put("name",name).put("expectedRevision",revision),token)

    internal fun commandReceiver(token: String): JSONObject {
        check(!enrollment)
        return request("GET", "/v1/device/command-receiver", bearer=token)
    }

    internal fun setCommandReceiver(previous: CommandReceiver, enabled: Boolean, token: String): JSONObject {
        check(!enrollment)
        val body = JSONObject().put("grantId", previous.grantId).put("revision", previous.revision).put("enabled", enabled)
        return request("PUT", "/v1/device/command-receiver", body, token)
    }

    internal fun updateAccountName(name: String,expected: String,accessToken: String): JSONObject =
        request("PUT","/v1/account",JSONObject().put("displayName",name).put("expectedDisplayName",expected),accessToken)

    fun account(accessToken: String): JSONObject {
        check(!enrollment)
        return request("GET", "/v1/account", bearer = accessToken).also {
            check(Regex("[a-f0-9]{32}").matches(it.getString("deviceId"))) { "NATIVE_ACCOUNT_RESPONSE_INVALID" }
        }
    }
    class Document internal constructor(private val value: Any) {
        fun asObject(): JSONObject = value as? JSONObject ?: error("NATIVE_JSON_OBJECT_REQUIRED")
        fun asArray(): org.json.JSONArray = value as? org.json.JSONArray ?: error("NATIVE_JSON_ARRAY_REQUIRED")
        override fun toString() = "NativeApiClient.Document(redacted)"
    }
    internal fun functionalPermissions(accessToken: String,contract: NativeFunctionalCodec): JSONObject {
        check(!enrollment)
        return exchange("GET","/v1/device/functional-permissions",bearer=accessToken,functionalPresentation=contract) as? JSONObject
            ?: error("NATIVE_JSON_OBJECT_REQUIRED")
    }
    internal fun friendChange(target: String,action: String,accept: Boolean?,revision: Long,token: String): JSONObject {
        require(Regex("team-[a-f0-9]{40}").matches(target))
        val body=JSONObject().put("functionalRevision",revision)
        val path=when(action) {
            "respond"->{require(accept!=null);body.put("accept",accept);"/v1/social/friends/requests/$target/respond"}
            "remove"->"/v1/social/friends/$target"
            "block"->{body.put("targetId",target);"/v1/social/blocks"}
            else->error("NATIVE_FRIEND_ACTION_INVALID")
        }
        return exchange(if(action=="remove")"DELETE" else "POST",path,body,bearer=token,social=true) as JSONObject
    }
    internal fun socialOverview(token: String): JSONObject = exchange("GET","/v1/social/overview",bearer=token,social=true) as JSONObject
    internal fun tripSignals(id: String,token: String): JSONObject =
        exchange("GET",tripPath(id)+"/signals",bearer=token,social=true) as JSONObject
    internal fun tripSignalCandidates(id: String,body: JSONObject,revision: Long,token: String): JSONObject =
        nativeTripWrite("POST",nativeTripPath(id)+"/signals/candidates",body,revision,token)
    internal fun tripSignalSend(id: String,body: JSONObject,revision: Long,token: String): JSONObject =
        nativeTripWrite("POST",tripPath(id)+"/signals",body,revision,token,setOf(200,201))
    internal fun tripSignalFinish(id: String,signal: String,body: JSONObject,revision: Long,token: String): JSONObject {
        require(Regex("[a-f0-9]{32}").matches(signal))
        return nativeTripWrite("POST",tripPath(id)+"/signals/$signal/finish",body,revision,token)
    }
    internal fun tripSignalVote(id: String,signal: String,body: JSONObject,revision: Long,token: String): JSONObject {
        require(Regex("[a-f0-9]{32}").matches(signal))
        return nativeTripWrite("POST",tripPath(id)+"/signals/$signal/vote",body,revision,token)
    }
    internal fun tripSavedPlaylists(id: String,token: String): JSONObject =
        exchange("GET",tripPath(id)+"/music/saved-playlists",bearer=token,social=true) as JSONObject
    internal fun addTripSavedPlaylist(id: String,body: JSONObject,revision: Long,token: String): JSONObject =
        nativeTripWrite("POST",tripPath(id)+"/music/saved-playlists",body,revision,token)
    internal fun listenTogether(id: String,token: String): JSONObject =
        exchange("GET",nativeTripPath(id)+"/listen-together",bearer=token,social=true) as JSONObject
    internal fun listenTogetherWrite(id: String,suffix: String,body: JSONObject,revision: Long,token: String): JSONObject {
        require(suffix in setOf("/participation","/start","/end"))
        return nativeTripWrite(if(suffix=="/participation")"PUT" else "POST",nativeTripPath(id)+"/listen-together"+suffix,body,revision,token)
    }
    internal fun tripMusicNowPlaying(id: String,body: JSONObject,revision: Long,token: String): JSONObject =
        nativeTripWrite("PUT",tripPath(id)+"/music/now-playing",body,revision,token)
    internal fun tripSavedPlaylistPosition(id: String,item: String,body: JSONObject,revision: Long,token: String): JSONObject {
        require(Regex("[a-f0-9]{32}").matches(item))
        return nativeTripWrite("PATCH",tripPath(id)+"/music/saved-playlists/$item/position",body,revision,token)
    }
    internal fun tripsRead(id: String?,token: String): JSONObject =
        exchange("GET",tripPath(id),bearer=token,social=true) as JSONObject
    internal fun nativeTripRead(id: String,token: String): JSONObject =
        exchange("GET",nativeTripPath(id),bearer=token,social=true) as JSONObject
    internal fun nativeTripSection(id: String,section: String,token: String): JSONObject {
        require(section in setOf("route","location"))
        return exchange("GET",nativeTripPath(id)+"?section="+section,bearer=token,social=true,tripRouteContract=section=="route") as JSONObject
    }
    internal fun tripLocationShare(id: String,token: String): JSONObject =
        exchange("GET",nativeTripPath(id)+"/locations",bearer=token,social=true) as JSONObject
    internal fun tripLocationReport(id: String,body: JSONObject,revision: Long,token: String): JSONObject =
        nativeTripWrite("POST",nativeTripPath(id)+"/locations/me",body,revision,token)
    internal fun nativeTripPlaces(id: String,carId: String,token: String): JSONObject =
        exchange("GET",nativeTripPath(id,carId)+"/places",bearer=token,social=true) as JSONObject
    internal fun nativeTripFriends(id: String,token: String): JSONObject =
        exchange("GET",nativeTripPath(id)+"/friends",bearer=token,social=true) as JSONObject
    internal fun nativeTripRouteOrder(id: String,carId: String,body: JSONObject,revision: Long,token: String): JSONObject =
        nativeTripWrite("PUT",nativeTripPath(id,carId)+"/route-order",body,revision,token)
    internal fun nativeTripRouteProgress(id: String,carId: String,body: JSONObject,revision: Long,token: String): JSONObject =
        nativeTripWrite("PUT",nativeTripPath(id,carId)+"/route-progress",body,revision,token)
    internal fun nativeTripRouteArrival(id: String,carId: String,body: JSONObject,revision: Long,token: String): JSONObject =
        nativeTripWrite("POST",nativeTripPath(id,carId)+"/route-arrivals",body,revision,token)
    internal fun nativeTripDrivingVersus(id: String,token: String): JSONObject =
        exchange("GET",nativeTripPath(id)+"/driving-score",bearer=token,social=true) as JSONObject
    internal fun nativeTripCourseComplete(id: String,carId: String,packId: String,revision: Long,token: String): JSONObject {
        require(Regex("[a-z0-9][a-z0-9_-]{0,79}").matches(packId))
        return nativeTripWrite("POST",nativeTripPath(id,carId)+"/courses/$packId/complete",JSONObject(),revision,token)
    }
    internal fun nativeTripCourseComplete(id: String,carId: String,packId: String,body: JSONObject,revision: Long,token: String): JSONObject {
        require(Regex("[a-z0-9][a-z0-9_-]{0,79}").matches(packId))
        return nativeTripWrite("POST",nativeTripPath(id,carId)+"/courses/$packId/complete",body,revision,token)
    }
    internal fun nativeTripTotalScore(id: String,carId: String,body: JSONObject,revision: Long,token: String): JSONObject =
        nativeTripWrite("PUT",nativeTripPath(id,carId)+"/driving-score",body,revision,token)
    internal fun nativeTripDrivingScore(id: String,carId: String,packId: String,body: JSONObject,revision: Long,token: String): JSONObject {
        require(Regex("[a-z0-9][a-z0-9_-]{0,79}").matches(packId))
        return nativeTripWrite("PUT",nativeTripPath(id,carId)+"/courses/$packId/driving-score",body,revision,token)
    }
    internal fun nativeTripAction(id: String,action: TripActionRequest,revision: Long,token: String): JSONObject =
        nativeTripWrite(action.method,nativeTripPath(id)+action.suffix,action.body,revision,token,action.success)
    private fun nativeTripWrite(method: String,path: String,body: JSONObject,revision: Long,token: String,success: Set<Int> = setOf(200)): JSONObject {
        val payload=functionalBody(body,revision)
        require(payload.toString().toByteArray(Charsets.UTF_8).size<=4096)
        return exchange(method,path,payload,bearer=token,social=true,socialSuccessStatuses=success) as JSONObject
    }
    internal fun tripRespond(id: String,accept: Boolean,locationConsent: Boolean?,revision: Long,token: String): JSONObject {
        require(revision in 1..Int.MAX_VALUE.toLong())
        val body=NativeTripsCodec.invitationResponseBody(accept,locationConsent).put("functionalRevision",revision)
        return exchange("POST",tripPath(id)+"/respond",body,bearer=token,social=true) as JSONObject
    }
    internal fun socialRoom(room: String,token: String): JSONObject =
        exchange("GET","/v1/social/rooms/"+NativeSocialCodec.roomId(room),bearer=token,social=true) as JSONObject
    internal fun socialHistory(cursor: String?,token: String): JSONObject =
        exchange("GET",socialHistoryPath(cursor),bearer=token,social=true) as JSONObject
    internal fun socialSignal(room: String,kind: SocialSignalKind,revision: Long,token: String): JSONObject {
        require(revision in 1..Int.MAX_VALUE.toLong())
        return exchange("POST","/v1/social/rooms/"+NativeSocialCodec.roomId(room)+"/signals",
            JSONObject().put("kind",kind.wire).put("functionalRevision",revision),bearer=token,social=true,socialSuccessStatus=201) as JSONObject
    }
    /** Voice-only projections use the same private strict business transport, never a caller URL. */
    internal fun voiceRooms(cursor: String?, token: String): JSONObject {
        check(!enrollment && identity != null)
        require(cursor == null || Regex("[a-f0-9]{32}").matches(cursor))
        return exchange("GET", "/v1/native/voice-rooms" + (cursor?.let { "?cursor=$it" } ?: ""),
            bearer=token, social=true) as JSONObject
    }
    internal fun voiceRoomPermission(room: String, token: String): JSONObject {
        check(!enrollment && identity != null)
        require(Regex("[a-f0-9]{32}").matches(room))
        return exchange("GET", "/v1/native/rooms/$room/voice-permissions", bearer=token, social=true) as JSONObject
    }
    internal fun voiceTripPermission(trip: String, token: String): JSONObject {
        check(!enrollment && identity != null)
        return exchange("GET", nativeTripPath(trip) + "/voice-permissions", bearer=token, social=true) as JSONObject
    }
    internal fun voiceTripParticipation(trip: String, token: String): JSONObject {
        check(!enrollment && identity != null)
        return exchange("GET", nativeTripPath(trip) + "/voice-participation", bearer=token, social=true,
            tripVoiceParticipationRead=true) as JSONObject
    }
    internal fun setVoiceTripParticipation(trip: String, body: JSONObject, revision: Long, token: String): JSONObject {
        check(!enrollment && identity != null)
        return exchange("PATCH", nativeTripPath(trip) + "/voice-participation", functionalBody(body, revision),
            bearer=token, social=true) as JSONObject
    }
    internal fun voiceClips(trip: String, cursor: String?, token: String): JSONObject {
        check(!enrollment && identity != null)
        require(cursor == null || NativeVoiceClipCodec.cursorPattern.matches(cursor))
        return exchange("GET", tripPath(trip) + "/voice-clips" + (cursor?.let { "?cursor=$it" } ?: ""),
            bearer=token, social=true) as JSONObject
    }
    internal fun uploadVoiceClip(trip: String, body: JSONObject, revision: Long, token: String): JSONObject {
        check(!enrollment && identity != null)
        return exchange("POST", tripPath(trip) + "/voice-clips", encodedBody=voiceClipUploadBody(body, revision),
            bearer=token, social=true, socialSuccessStatuses=setOf(200,201), requestBodyLimit=VOICE_CLIP_BODY_LIMIT) as JSONObject
    }
    internal fun voiceClip(trip: String, clip: String, token: String): JSONObject {
        check(!enrollment && identity != null)
        require(Regex("[a-f0-9]{32}").matches(clip))
        return exchange("GET", tripPath(trip) + "/voice-clips/" + clip, bearer=token, social=true) as JSONObject
    }
    internal fun voiceClipFilters(trip: String, token: String): JSONObject {
        check(!enrollment && identity != null)
        return exchange("GET", tripPath(trip) + "/voice/filters", bearer=token, social=true) as JSONObject
    }
    internal fun connectVoice(room: String, functionalRevision: Long, roomRevision: Long, token: String,
        listener: NativeVoiceSocketListener, trip: Boolean = false): NativeVoiceSocket {
        require(Regex("[a-f0-9]{32}").matches(room))
        require(functionalRevision in 1..Int.MAX_VALUE.toLong() && roomRevision in (if (trip) 0 else 1)..Int.MAX_VALUE.toLong())
        // Reuse the existing TLS1.3/mTLS/default-trust credential seam unchanged. Its
        // endpoint is SDK-owned; replace only its fixed path inside this internal callback.
        return connectEvents(token, EventsConnector { endpoint, factory, trust, authorization ->
            val fixed = URI("wss", null, endpoint.host, endpoint.port, (if (trip) tripPath(room) else "/v1/social/rooms/$room") + "/voice", null, null)
            NativeVoiceSocket.open(fixed, factory, trust, authorization, functionalRevision, roomRevision, listener)
        }) as NativeVoiceSocket
    }
    /** Background failure reports only; see [ClientDiagnostics]. */
    internal fun clientDiagnostics(body: ByteArray, token: String) {
        check(!enrollment && identity != null)
        exchange("POST", ClientDiagnostics.ROUTE, encodedBody=body, bearer=token, requestBodyLimit=ClientDiagnosticsQueue.MAX_BYTES)
    }
    fun readDocument(path: String, accessToken: String): Document {
        check(!enrollment); requireReadPath(path)
        return Document(exchange("GET", path, bearer = accessToken))
    }
    class PackVersion internal constructor(val id: String,val version: Int,bytes: ByteArray) {
        private val encoded=bytes.copyOf()
        fun bytes(): ByteArray = encoded.copyOf()
        override fun toString() = "NativeApiClient.PackVersion(redacted)"
    }
    fun readPackVersion(id: String,version: Int,accessToken: String): PackVersion = readPack(id,version,accessToken,false)
    internal fun courseRoadPreview(id: String,version: Int,checksum: String,points: List<CourseRoadCoordinate>,token: String): JSONObject {
        packVersionPath(id,version,false)
        require(Regex("[a-f0-9]{64}").matches(checksum) && points.size in 2..3)
        val coordinates=org.json.JSONArray()
        points.forEach {point->
            require(point.latitude.isFinite() && point.longitude.isFinite() && point.latitude in 32.0..39.0 && point.longitude in 124.0..132.0)
            coordinates.put(JSONObject().put("lat",point.latitude).put("lng",point.longitude))
        }
        return request("POST","/v1/native/courses/$id/versions/$version/route-preview",
            JSONObject().put("checksum",checksum).put("points",coordinates),token)
    }
    fun readOriginalPackVersion(id: String,version: Int,accessToken: String): PackVersion = readPack(id,version,accessToken,true)
    private fun readPack(id: String,version: Int,accessToken: String,original: Boolean): PackVersion {
        check(!enrollment)
        val path=packVersionPath(id,version,original)
        val bytes=exchange("GET",path,bearer=accessToken,packFile=true) as ByteArray
        val body=JSONObject(String(bytes,Charsets.UTF_8))
        check(body.get("id") is String && body.getString("id")==id && body.get("version") is Int && body.getInt("version")==version)
        return PackVersion(id,version,bytes)
    }
    private fun request(method: String, path: String, body: JSONObject? = null,
        bearer: String? = null): JSONObject = exchange(method, path, body, bearer) as? JSONObject
        ?: error("NATIVE_JSON_OBJECT_REQUIRED")

    internal fun access(action: String, body: JSONObject, codec: NativeAccessCodec,
        connectionId: String? = null, deviceId: String? = null, installationKeyId: String, stagedCertificate: JSONObject? = null): JSONObject {
        check(codec.origin(action) == origin || (fixtureCa != null && NativeBuildType.DEBUG))
        codec.request(action, body)
        check(stagedCertificate==null || (!enrollment && action in setOf("CREDENTIAL_REBIND","GRANT_REVOKE","SESSION_EXCHANGE") && identity!=null))
        return exchange("POST", codec.path(action,connectionId,deviceId), body,
            accessAction=action,accessCodec=codec,accessKeyId=installationKeyId,stagedCertificate=stagedCertificate) as JSONObject
    }

    /** Opt-in error report; returns the server's random report id. */
    internal fun clientReport(body: JSONObject,token: String): String {
        check(!enrollment)
        val response=request("POST","/v1/device/client-reports",body,bearer=token)
        check(response.keys().asSequence().toSet()==setOf("status","reportId") && response.getString("status")=="accepted")
        return response.getString("reportId").also {require(Regex("[a-f0-9]{16}").matches(it))}
    }
    internal fun controlSupport(body: JSONObject,token: String): JSONObject {
        check(!enrollment)
        return exchange("PUT","/v1/device/control-support",body,bearer=token,social=true) as JSONObject
    }
    internal fun deviceCommandHost(): String = origin.host
    internal fun deviceCommandExchange(method: String, path: String, body: JSONObject?, token: String): JSONObject {
        check(!enrollment)
        require((method == "GET" && path == "/v1/device/command-inbox" && body == null) ||
            (method == "POST" && Regex("/v1/device/requests/[a-f0-9]{32}/(claim|ack)").matches(path) && body != null))
        return exchange(method, path, body, bearer = token, social = true) as JSONObject
    }
    internal fun businessRead(path: String, token: String): JSONObject {
        check(!enrollment)
        requireBusinessReadPath(path)
        return exchange("GET", path, bearer = token, social = true) as JSONObject
    }
    internal fun missionProgress(path: String,body: JSONObject,token: String): JSONObject {
        check(!enrollment)
        require(Regex("/v1/native/rooms/[a-f0-9]{32}/missions/[a-f0-9]{32}/progress").matches(path))
        return exchange("POST",path,body,bearer=token,social=true) as JSONObject
    }

    private fun exchange(method: String, path: String, body: JSONObject? = null,
        bearer: String? = null, accessAction: String? = null, accessCodec: NativeAccessCodec? = null, accessKeyId: String? = null, stagedCertificate: JSONObject? = null, packFile: Boolean = false, social: Boolean = false, socialSuccessStatus: Int = 200,
        socialSuccessStatuses: Set<Int> = setOf(socialSuccessStatus), tripVoiceParticipationRead: Boolean = false,functionalPresentation: NativeFunctionalCodec? = null,
        tripRouteContract: Boolean=false, requestBodyLimit: Int = 16384, encodedBody: ByteArray? = null): Any {
        check(Build.VERSION.SDK_INT >= 29) { "NATIVE_TLS13_UNSUPPORTED" }
        check(Looper.myLooper() != Looper.getMainLooper()) { "NATIVE_WORKER_THREAD_REQUIRED" }
        // No shared browser/HTTP cookie state may enter this transport. Android has
        // no public Authenticator.getDefault API; embedding apps must not install
        // a process-global password authenticator for this dedicated transport.
        check(java.net.CookieHandler.getDefault() == null) {
            "NATIVE_AMBIENT_HTTP_CREDENTIALS_UNSUPPORTED"
        }
        val fixtureTrust = fixtureCa?.let { ca ->
            check(NativeBuildType.DEBUG && origin.host == "127.0.0.1")
            val keys = KeyStore.getInstance(KeyStore.getDefaultType()).apply {
                load(null); setCertificateEntry("synthetic-loopback-ca", ca)
            }
            TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm()).apply {
                init(keys)
            }.trustManagers
        }
        val ssl = SSLContext.getInstance("TLSv1.3").apply {
            init(identity?.let { arrayOf(if(stagedCertificate!=null) it.stagedKeyManager(stagedCertificate.getString("certificatePem"),stagedCertificate.getString("certificateSha256")) else it.keyManager()) }, fixtureTrust, SecureRandom())
        }
        NativeNetLog.forget()
        val net = NativeNetLog.start(method, path)
        val connection = origin.resolve(path).toURL().openConnection() as HttpsURLConnection
        var failure: Throwable? = null
        try {
            connection.sslSocketFactory = Tls13SocketFactory(ssl.socketFactory)
            // HttpsURLConnection's platform hostname verifier is deliberately unchanged.
            connection.instanceFollowRedirects = false
            connection.useCaches = false
            connection.connectTimeout = 10000
            connection.readTimeout = 10000
            connection.requestMethod = method
            connection.setRequestProperty("Accept", "application/json")
            // Correlation only: ids are random per request and carry no account, device or token.
            net.headers.forEach { (name, value) -> connection.setRequestProperty(name, value) }
            functionalPresentation?.let {
                check(method=="GET" && path=="/v1/device/functional-permissions")
                connection.setRequestProperty("X-WegoH-Functional-Presentation",it.disclosureVersion.toString())
            }
            if(tripRouteContract) {
                check(method=="GET" && Regex("/v1/native/trips/[a-f0-9]{32}\\?section=route").matches(path))
                connection.setRequestProperty("X-WegoH-Trip-Route-Contract","2")
            }
            if (bearer != null) {
                require(bearer.length in 1..4096 && bearer.none { it == '\r' || it == '\n' })
                connection.setRequestProperty("Authorization", "Bearer $bearer")
            }
            check(encodedBody == null || body == null && accessAction == null)
            if (body != null || encodedBody != null) {
                val bytes = encodedBody ?: if(accessAction!=null) NativeAccessCodec.canonical(body!!) else body!!.toString().toByteArray(Charsets.UTF_8)
                require(bytes.size <= requestBodyLimit)
                connection.setRequestProperty("Content-Type", "application/json")
                connection.doOutput = true
                connection.setFixedLengthStreamingMode(bytes.size)
                val permit=mutationPermit
                if(permit!=null)permit.write(bytes,{connection.outputStream},{connection.disconnect()})
                else connection.outputStream.use { it.write(bytes) }
            }
            val status = connection.responseCode
            net.status = status
            if(social) {
                val mutation=method!="GET"
                if(status !in socialSuccessStatuses) {
                    val error=if(connection.contentType?.substringBefore(';')?.trim()=="application/json")
                        runCatching {connection.errorStream?.use {StrictNativeJson.parseBusiness(boundedBytes(it,4096),4096)}}.getOrNull() else null
                    throw NativeSocialErrorCodec.failure(status,error,mutation,
                        connection.getHeaderField("Retry-After")?.toIntOrNull()?.coerceIn(1,86400),tripVoiceParticipationRead,
                        NativeFunctionalDiagnostics.pathTemplate(method,path))
                }
                check(connection.contentType?.substringBefore(';')?.trim()=="application/json") {"NATIVE_SOCIAL_RESPONSE_INVALID"}
                return connection.inputStream.use {StrictNativeJson.parseBusiness(boundedBytes(it,1048576),1048576)}
            }
            if(accessAction != null) {
                check(connection.contentType?.substringBefore(';')?.trim() == "application/json") { "NATIVE_JSON_RESPONSE_REQUIRED" }
                val input=if(status in 200..299) connection.inputStream else connection.errorStream
                val value=input?.use { StrictNativeJson.parse(boundedBytes(it,12288)) }
                    ?: error("NATIVE_PROTOCOL_RESPONSE_INVALID")
                if(status !in 200..299) throw accessCodec!!.error(status,value)
                return accessCodec!!.response(accessAction,status,value,body!!.getString("operationId"),accessKeyId!!)
            }
            if (status !in 200..299) {
                val retry = connection.getHeaderField("Retry-After")?.toIntOrNull()?.coerceIn(5, 86400)
                // App-data errors expose only the declared scope code.
                if (!enrollment && status == 403 && connection.contentType?.substringBefore(';')?.trim() == "application/json") {
                    val code = runCatching { connection.errorStream?.use {
                        JSONObject(String(boundedBytes(it, 4096), Charsets.UTF_8)).optString("detail")
                    } }.getOrNull()
                    if (code == "SCOPE_DENIED") throw Failure(status, code, retry)
                }
                throw Failure(status, when (status) {
                    401 -> "NATIVE_AUTHORIZATION_REQUIRED"
                    403 -> "NATIVE_CERTIFICATE_OR_ACCESS_DENIED"
                    429 -> "NATIVE_RETRY_LATER"
                    503 -> "NATIVE_REGISTRATION_UNAVAILABLE"
                    else -> "NATIVE_REQUEST_REJECTED"
                }, retry)
            }
            check(connection.contentType?.substringBefore(';')?.trim() == "application/json") {
                "NATIVE_JSON_RESPONSE_REQUIRED"
            }
            val limit=when {
                packFile || path.startsWith("/v1/packs/") -> 262144
                path=="/v1/playlists" -> 33554432
                path.startsWith("/v1/playlists/") -> 524288
                path=="/v1/studio/packs" -> 8388608
                path=="/v1/native/courses/library" -> 16777216
                path.startsWith("/v1/native/courses/public/") -> 524288
                path.startsWith("/v1/native/courses/") && path.endsWith("/route-preview") -> 262144
                path=="/v1/packs" -> 1048576
                else -> 65536
            }
            val bytes = connection.inputStream.use { boundedBytes(it, limit) }
            if(path.startsWith("/v1/native/courses/") && path.endsWith("/route-preview"))return StrictNativeJson.parseBusiness(bytes,262144)
            if(path=="/v1/device/functional-permissions")return StrictNativeJson.parseFunctional(bytes,65536)
            if(path=="/v1/device/command-receiver" || method=="PUT" && path=="/v1/account")return StrictNativeJson.parse(bytes,65536)
            val parser = org.json.JSONTokener(String(bytes, Charsets.UTF_8))
            val value = parser.nextValue()
            check((value is JSONObject || value is org.json.JSONArray) && parser.nextClean() == '\u0000') {
                "NATIVE_JSON_RESPONSE_INVALID"
            }
            return if(packFile)bytes else value
        } catch (error: Throwable) {
            failure = error; throw error
        } finally { connection.disconnect(); NativeNetLog.finish(net, failure) }
    }

    /** Trusted app networking layer only. Credentials must not be logged, retained in UI,
     * redirected or forwarded. Returning this handle means an attempt, not a successful101.
     * Keep the connector library's hostname verification and disable ambient auth/cookies/retries.
     */
    fun interface EventsConnector {
        fun connect(endpoint: URI, tlsSocketFactory: SSLSocketFactory,
            serverTrustManager: X509TrustManager, authorizationHeader: String): Closeable
    }

    internal fun connectEvents(accessToken: String, connector: EventsConnector): Closeable {
        check(!enrollment && identity != null)
        check(Build.VERSION.SDK_INT >= 29) { "NATIVE_TLS13_UNSUPPORTED" }
        check(Looper.myLooper() != Looper.getMainLooper()) { "NATIVE_WORKER_THREAD_REQUIRED" }
        check(java.net.CookieHandler.getDefault() == null) { "NATIVE_AMBIENT_HTTP_CREDENTIALS_UNSUPPORTED" }
        require(Regex("[A-Za-z0-9_-]{43}").matches(accessToken))
        val anchors = fixtureCa?.let { ca ->
            check(NativeBuildType.DEBUG && origin.host == "127.0.0.1")
            KeyStore.getInstance(KeyStore.getDefaultType()).apply {
                load(null); setCertificateEntry("synthetic-loopback-ca", ca)
            }
        }
        // Explicit platform default manager is also required by OkHttp's public TLS API.
        // A fixture CA is permitted only by the existing debug loopback constructor.
        val manager = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm()).apply {
            init(anchors)
        }.trustManagers.filterIsInstance<X509TrustManager>().single()
        val ssl = SSLContext.getInstance("TLSv1.3").apply {
            init(arrayOf(identity.keyManager()), arrayOf(manager), SecureRandom())
        }
        return connector.connect(if(fixtureCa!=null) URI("wss://127.0.0.1:${fixtureEventsPort ?: origin.port}/v1/events") else URI("wss://api-wegoh.devforest.io/v1/events"),
            Tls13SocketFactory(ssl.socketFactory), manager, "Bearer $accessToken")
    }

    companion object {
        internal fun functionalBody(body: JSONObject,revision: Long): JSONObject {
            require(revision in 1..Int.MAX_VALUE.toLong())
            return JSONObject(body.toString()).put("functionalRevision",revision)
        }
        /** Same limit as the server's voice clip body. A 15 s clip is 640000 Base64 characters. */
        internal const val VOICE_CLIP_BODY_LIMIT = 700000
        /** Android's org.json writes every Base64 '/' as "\/", which pushes a 15 s clip past
         * VOICE_CLIP_BODY_LIMIT. Canonical JSON keeps '/' literal, so a full clip always fits. */
        internal fun voiceClipUploadBody(body: JSONObject,revision: Long): ByteArray =
            NativeAccessCodec.canonical(functionalBody(body,revision))
        internal fun nativeTripPath(id: String,carId: String?=null): String {
            require(Regex("[a-f0-9]{32}").matches(id))
            require(carId==null || Regex("[a-f0-9]{32}").matches(carId))
            return "/v1/native/trips/$id"+(carId?.let {"/cars/$it"} ?: "")
        }
        internal fun tripPath(id: String?): String {
            require(id==null || Regex("[a-f0-9]{32}").matches(id))
            return "/v1/social/trips"+(id?.let {"/$it"} ?: "")
        }
        internal fun missionProgressPath(room: String,mission: String): String {
            require(Regex("[a-f0-9]{32}").matches(room) && Regex("[a-f0-9]{32}").matches(mission))
            return "/v1/native/rooms/$room/missions/$mission/progress"
        }
        internal fun socialHistoryPath(cursor: String?): String = "/v1/social/history"+
            (cursor?.let {"?cursor="+NativeSocialCodec.cursor(it)} ?: "")
        internal fun requireBusinessReadPath(path: String) {
            require(path in setOf("/v1/device/command-inbox", "/v1/device/command-inbox?view=status", "/v1/recommendations/settings", "/v1/social/cautions") ||
                Regex("/v1/native/rooms/[a-f0-9]{32}/missions").matches(path) ||
                Regex("/v1/native/trips/[a-f0-9]{32}/missions").matches(path) ||
                Regex("/v1/social/rooms/[a-f0-9]{32}/music").matches(path) ||
                Regex("/v1/social/history/[a-f0-9]{32}").matches(path))
        }
        /** Read-only native resources; no credential-bearing absolute URL/query or
         * pairing/token endpoints can be routed through this app-data boundary. */
        internal fun packVersionPath(id: String,version: Int,original: Boolean=false): String =
            (if(original)"/v1/studio/packs/$id/versions/$version" else "/v1/packs/$id/versions/$version").also {requireReadPath(it)}
        internal fun publicCoursePath(id: String,version: Int): String =
            "/v1/native/courses/public/$id/versions/$version".also {requireReadPath(it)}
        internal fun requireReadPath(path: String) {
            val pack=Regex("/v1/(?:studio/)?packs/[a-z0-9][a-z0-9_-]{0,79}/versions/([1-9][0-9]{0,9})").matchEntire(path)
            val course=Regex("/v1/native/courses/public/[a-z0-9][a-z0-9_-]{0,79}/versions/([1-9][0-9]{0,9})").matchEntire(path)
            require(path in setOf("/v1/account","/v1/packs","/v1/studio/packs","/v1/playlists","/v1/device/permissions","/v1/native/courses/library") ||
                Regex("/v1/playlists/[a-f0-9]{32}").matches(path) ||
                course!=null && course.groupValues[1].toLong()<=Int.MAX_VALUE.toLong() ||
                pack!=null && pack.groupValues[1].toLong()<=Int.MAX_VALUE.toLong()) {"NATIVE_READ_PATH_NOT_ALLOWED"}
        }
        /** Deployment origin is fixed; user input cannot redirect credential-bearing calls. */
        internal fun native(identity: NativeDeviceIdentity) = NativeApiClient(
            URI("https://api-wegoh.devforest.io"), identity, false)
        /** Registration sends no client certificate or personal Bearer to the bootstrap host. */
        internal fun enrollment() = NativeApiClient(URI("https://enroll-wegoh.devforest.io"), null, true)
        /** Instrumentation only: release rejects this path; no arbitrary host/trust-all. */
        internal fun syntheticLoopback(port: Int, ca: X509Certificate,
            identity: NativeDeviceIdentity?, enrollment: Boolean = false, eventsPort: Int? = null): NativeApiClient {
            check(NativeBuildType.DEBUG)
            require(port in 1024..65535 && (eventsPort==null || eventsPort in 1024..65535))
            return NativeApiClient(URI("https://127.0.0.1:$port"), identity, enrollment, ca, eventsPort)
        }
    }
}

internal class Tls13SocketFactory(private val delegate: SSLSocketFactory) : SSLSocketFactory() {
    private fun restrict(socket: Socket): Socket = (socket as SSLSocket).apply {
        check(supportedProtocols.contains("TLSv1.3")) { "NATIVE_TLS13_UNSUPPORTED" }
        enabledProtocols = arrayOf("TLSv1.3")
    }
    override fun getDefaultCipherSuites() = delegate.defaultCipherSuites
    override fun getSupportedCipherSuites() = delegate.supportedCipherSuites
    override fun createSocket(): Socket = restrict(delegate.createSocket())
    override fun createSocket(socket: Socket?, host: String?, port: Int, autoClose: Boolean): Socket =
        restrict(delegate.createSocket(socket, host, port, autoClose))
    override fun createSocket(host: String?, port: Int): Socket = restrict(delegate.createSocket(host, port))
    override fun createSocket(host: String?, port: Int, local: InetAddress?, localPort: Int): Socket =
        restrict(delegate.createSocket(host, port, local, localPort))
    override fun createSocket(host: InetAddress?, port: Int): Socket = restrict(delegate.createSocket(host, port))
    override fun createSocket(host: InetAddress?, port: Int, local: InetAddress?, localPort: Int): Socket =
        restrict(delegate.createSocket(host, port, local, localPort))
}
