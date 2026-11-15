package io.wegoh.app

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import io.wegoh.app.nativeauth.NativeNetLog

data class PublishedPack(val id: String, val version: Int, val title: String, val author: String,
    val description: String, val stopCount: Int, val checksum: String) {
    val key get() = "$id@$version"
}

interface LocalPublishingApi {
    fun list(): List<PublishedPack>
    fun download(pack: PublishedPack): ByteArray
    fun shareVisits(visits: org.json.JSONArray,canSend: ()->Boolean={true}): Int
    fun report(origin: VerifiedPackOrigin,reason: CourseReportReason,canSend: ()->Boolean={true})
    fun cancelPendingRequests()
}

/** Only public, published content. No author credentials or vehicle location are transmitted. */
class PublishedPacks(baseUrl: String = BuildConfig.PACK_API_BASE_URL): LocalPublishingApi {
    private val baseUrl=baseUrl.takeIf {it.isNotBlank()}?.let{DistributionPolicy.endpoint(it)}.orEmpty()
    private val connections=java.util.concurrent.ConcurrentHashMap.newKeySet<HttpURLConnection>()
    override fun cancelPendingRequests() {connections.toList().forEach {runCatching {it.disconnect()}}}
    override fun shareVisits(visits: org.json.JSONArray,canSend: ()->Boolean): Int {
        require(visits.length()<=1000)
        return (0 until visits.length() step 100).sumOf { start ->
            val batch=org.json.JSONArray()
            for(index in start until minOf(start+100,visits.length()))batch.put(visits.getJSONObject(index))
            check(canSend());shareBatch(batch,canSend)
        }
    }
    private fun shareBatch(visits: org.json.JSONArray,canSend: ()->Boolean): Int {
        check(BuildConfig.DEBUG && java.net.URI(baseUrl).host=="127.0.0.1") {"방문 공유는 로컬 시험 모드에서만 지원합니다"}
        check(baseUrl.isNotBlank()) { "로컬 창작 공간이 설정되지 않은 빌드입니다" }
        val bytes=JSONObject().put("consent",true).put("visits",visits).toString().toByteArray(Charsets.UTF_8)
        check(bytes.size<=262144) { "공유할 기록이 너무 큽니다" }
        val connection=URL(baseUrl+"/v1/local/visits").openConnection() as HttpURLConnection
        connection.requestMethod="POST"; connection.doOutput=true
        connection.connectTimeout=5000; connection.readTimeout=10000; connection.instanceFollowRedirects=false
        connection.setRequestProperty("Content-Type","application/json")
        connection.setRequestProperty("Origin",baseUrl)
        connection.setRequestProperty("X-WegoH-Local-Visit","1")
        connection.setFixedLengthStreamingMode(bytes.size)
        connections.add(connection)
        try {NativeNetLog.traced("POST","/v1/local/visits",connection) {net->
            check(canSend())
            connection.outputStream.use {check(canSend());it.write(bytes)}
            net.status=connection.responseCode
            check(connection.responseCode==200) { "방문 기록 공유 실패 (${connection.responseCode})" }
            return JSONObject(PackCodec.read(connection.inputStream)).getInt("accepted")
        }} finally { connections.remove(connection);connection.disconnect() }
    }
    override fun report(origin: VerifiedPackOrigin,reason: CourseReportReason,canSend: ()->Boolean) {
        check(BuildConfig.DEBUG && java.net.URI(baseUrl).host=="127.0.0.1")
        require(origin.id.matches(Regex("[a-z0-9][a-z0-9_-]{0,79}")) && origin.version>0 && origin.checksum.matches(Regex("[0-9a-f]{64}")))
        val bytes=JSONObject().put("reason",reason.wire).put("checksum",origin.checksum).toString().toByteArray(Charsets.UTF_8)
        val connection=URL(baseUrl+"/v1/local/packs/${origin.id}/versions/${origin.version}/reports").openConnection() as HttpURLConnection
        connection.requestMethod="POST";connection.doOutput=true;connection.instanceFollowRedirects=false
        connection.connectTimeout=5000;connection.readTimeout=10000
        connection.setRequestProperty("Content-Type","application/json");connection.setRequestProperty("Origin",baseUrl)
        connection.setRequestProperty("X-WegoH-Local-Report","1");connection.setFixedLengthStreamingMode(bytes.size)
        connections.add(connection)
        try {NativeNetLog.traced("POST","/v1/local/packs/${origin.id}/versions/${origin.version}/reports",connection) {net->
            check(canSend());connection.outputStream.use {check(canSend());it.write(bytes)}
            net.status=connection.responseCode
            check(connection.responseCode==202)
            val result=JSONObject(PackCodec.read(connection.inputStream))
            check(result.getString("state")=="quarantined" && result.getString("reportId").isNotBlank())
        }} finally {connections.remove(connection);connection.disconnect()}
    }
    private fun get(path: String, limit: Int): ByteArray {
        check(baseUrl.isNotBlank()) { "이 빌드의 코스 배포 서버가 아직 설정되지 않았습니다" }
        val connection = URL(baseUrl + path).openConnection() as HttpURLConnection
        connection.connectTimeout = 5000
        connection.readTimeout = 10000
        connection.instanceFollowRedirects = false
        connection.setRequestProperty("Accept", "application/json")
        connections.add(connection)
        try {NativeNetLog.traced("GET",path,connection) {net->
            net.status = connection.responseCode
            check(connection.responseCode == 200) { "코스 서버 응답 오류 (${connection.responseCode})" }
            return connection.inputStream.use { input ->
                val output = java.io.ByteArrayOutputStream()
                val chunk = ByteArray(8192)
                while (true) {
                    val count = input.read(chunk)
                    if (count < 0) break
                    check(output.size() + count <= limit) { "응답 크기가 너무 큽니다" }
                    output.write(chunk, 0, count)
                }
                output.toByteArray()
            }
        }} finally { connections.remove(connection);connection.disconnect() }
    }
    override fun list(): List<PublishedPack> {
        val array = JSONObject(get("/v1/packs", 1048576).toString(Charsets.UTF_8)).getJSONArray("packs")
        check(array.length() <= 100) { "코스 목록이 너무 큽니다" }
        return (0 until array.length()).map { index ->
            val item = array.getJSONObject(index)
            PublishedPack(item.getString("id"), item.getInt("version"), item.getString("title"),
                item.getString("author"), item.getString("description"), item.getInt("stopCount"), item.getString("checksum")).also {
                check(it.id.matches(Regex("[a-z0-9][a-z0-9_-]{0,79}")) && it.version > 0 && it.stopCount in 1..3 &&
                    it.checksum.matches(Regex("[0-9a-f]{64}")) && it.title.length <= 100 && it.description.length <= 500 && it.author.length <= 80) {
                    "잘못된 게시 코스 목록입니다"
                }
            }
        }
    }
    override fun download(pack: PublishedPack): ByteArray {
        val bytes = get("/v1/packs/${pack.id}/versions/${pack.version}", PackCodec.MAX_BYTES)
        val hash = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it.toInt() and 255) }
        check(hash == pack.checksum) { "다운로드한 코스의 무결성을 확인할 수 없습니다" }
        val decoded = PackCodec.decode(bytes.toString(Charsets.UTF_8))
        check(decoded.key == pack.key) { "요청한 코스 버전과 다릅니다" }
        return bytes
    }
}
