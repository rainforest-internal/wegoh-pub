package io.wegoh.app

import android.content.Context
import org.json.JSONObject
import java.io.InputStream
import java.io.ByteArrayOutputStream
import kotlin.math.*

data class Stop(
    val id: String, val name: String, val latitude: Double, val longitude: Double,
    val radiusMeters: Float, val message: String, val poiId: String? = null,
    val address: String = "",
    val placeId: String? = null, val placeProvider: String? = null,
    val originalPlaceName: String? = null,
)

data class DrivePack(
    val id: String, val version: Int, val title: String, val author: String,
    val description: String, val stops: List<Stop>, val source: String = "저장된 경로",
) {
    val key get() = "$id@$version"
}

object PackCodec {
    const val MAX_BYTES = 262144
    private fun fields(json: JSONObject, allowed: Set<String>) {require(json.keys().asSequence().all {it in allowed}) {"지원하지 않는 필드"}}
    private fun integer(json: JSONObject, name: String): Int {
        val value=json.get(name)
        require((value is Int || value is Long) && (value as Number).toLong() in 1..Int.MAX_VALUE.toLong()) {"잘못된 정수"}
        return (value as Number).toInt()
    }
    private fun optionalText(json: JSONObject,name: String,max: Int): String {
        if(!json.has(name))return ""
        val value=json.get(name);require(value is String && value.length<=max) {"잘못된 문자열"};return value
    }
    private fun text(json: JSONObject, name: String, max: Int = 200): String {
        val value = json.get(name)
        require(value is String && value.isNotBlank() && value.length <= max) { "$name: 비어 있거나 너무 긴 문자열" }
        return value
    }
    fun read(input: InputStream): String = input.use {
        val output = ByteArrayOutputStream()
        val buffer = ByteArray(8192)
        while (true) {
            val count = it.read(buffer)
            if (count < 0) break
            require(output.size() + count <= MAX_BYTES) { "코스는 256 KiB 이하여야 합니다" }
            output.write(buffer, 0, count)
        }
        output.toByteArray().toString(Charsets.UTF_8)
    }
    fun decode(raw: String, source: String = "저장된 경로"): DrivePack {
        require(raw.toByteArray().size <= MAX_BYTES) { "코스 크기 초과" }
        val obj = JSONObject(raw)
        fields(obj,setOf("schemaVersion","id","version","title","author","description","stops"))
        require(integer(obj,"schemaVersion") == 1) { "지원하지 않는 코스 형식" }
        val id = text(obj, "id", 80)
        require(id.matches(Regex("[a-z0-9][a-z0-9_-]*"))) { "잘못된 코스 ID" }
        val version = integer(obj,"version")
        require(version > 0) { "버전은 양수여야 합니다" }
        val list = obj.getJSONArray("stops")
        require(list.length() in 1..3) { "방문 지점은 1~3개입니다" }
        val stops = (0 until list.length()).map { i ->
            val s = list.getJSONObject(i)
            fields(s,setOf("id","name","latitude","longitude","radiusMeters","action","poiId","address","place"))
            val stopId = text(s, "id", 80)
            require(stopId.matches(Regex("[a-z0-9][a-z0-9_-]*"))) { "잘못된 지점 ID" }
            for(name in listOf("latitude","longitude","radiusMeters"))require(s.get(name) is Number) {"잘못된 수치"}
            val lat = s.getDouble("latitude")
            val lon = s.getDouble("longitude")
            val radius = s.getDouble("radiusMeters")
            require(lat.isFinite() && lat in -90.0..90.0 && lon.isFinite() && lon in -180.0..180.0) { "잘못된 좌표" }
            require(radius.isFinite() && radius in 25.0..500.0) { "반경은 25~500m입니다" }
            val action = s.getJSONObject("action")
            require(action.length()==2);fields(action,setOf("type","message"))
            require(text(action, "type") == "chime") { "지원하지 않는 액션" }
            val place = if (s.has("place")) s.getJSONObject("place") else null
            place?.let {fields(it,setOf("id","provider","name","address"));require(it.length()==4);optionalText(it,"address",200)}
            Stop(stopId, text(s, "name", 80), lat, lon, radius.toFloat(),
                text(action, "message", 240), optionalText(s,"poiId",100).takeIf { it.isNotBlank() }, optionalText(s,"address",200),
                place?.let { text(it,"id",240) }, place?.let { text(it,"provider",40) }, place?.let { text(it,"name",80) })
        }
        require(stops.map { it.id }.distinct().size == stops.size) { "지점 ID 중복" }
        return DrivePack(id, version, text(obj, "title", 100), text(obj, "author", 80),
            text(obj, "description", 500), stops, source)
    }
}

class PackRepository(private val context: Context) {
    private val directory = context.filesDir.resolve("packs").apply { mkdirs() }
    private val store=PrivateStore(context)
    private fun copyLegacy() {
        directory.listFiles().orEmpty().filter {it.extension=="json"}.forEach { file ->
            val raw=PackCodec.read(file.inputStream());val pack=PackCodec.decode(raw)
            val name="pack-${pack.id}-${pack.version}"
            if(!store.exists(name))store.write(name,raw)
            check(PackCodec.decode(store.read(name)!!).copy(source="")==pack.copy(source=""))
            check(file.delete()) {"이전 코스 정리 실패"}
        }
    }
    fun list(): List<DrivePack> = buildList {
        copyLegacy()
        context.assets.list("packs").orEmpty().filter { it.endsWith(".json") }.sorted().forEach {
            add(PackCodec.decode(PackCodec.read(context.assets.open("packs/$it")), "기본 경로"))
        }
        store.names().filter {it.startsWith("pack-")}.sorted().forEach {
            val pack=PackCodec.decode(store.read(it)!!,"가져온 경로")
            add(if(verifiedOrigin(pack)!=null)pack.copy(source="공개 경로") else pack)
        }
    }.distinctBy { it.key }
    internal fun verifyPublished(published: PublishedPack,bytes: ByteArray,source: String="공개 경로"): DrivePack {
        require(bytes.size<=PackCodec.MAX_BYTES)
        val hash=java.security.MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") {"%02x".format(it.toInt() and 255)}
        check(hash==published.checksum)
        val pack=PackCodec.decode(bytes.toString(Charsets.UTF_8),source)
        check(pack.key==published.key && pack.stops.size==published.stopCount)
        return pack
    }
    internal fun accountCourse(published: PublishedPack,bytes: ByteArray)=verifyPublished(published,bytes,CoursesRepository.SOURCE)
    fun importPublished(published: PublishedPack,bytes: ByteArray): DrivePack {
        val raw=bytes.toString(Charsets.UTF_8)
        val decoded=verifyPublished(published,bytes)
        val hash=java.security.MessageDigest.getInstance("SHA-256").digest(bytes).joinToString(""){"%02x".format(it.toInt() and 255)}
        val imported=importPack(java.io.ByteArrayInputStream(bytes))
        // Bind provenance to the exact verified download, including when an equivalent
        // manually imported JSON had different whitespace. Semantic content cannot change.
        store.write("pack-${decoded.id}-${decoded.version}",raw)
        store.write("origin-${decoded.id}-${decoded.version}",JSONObject().put("id",decoded.id)
            .put("version",decoded.version).put("checksum",hash).toString())
        return imported
    }
    fun verifiedOrigin(pack: DrivePack): VerifiedPackOrigin? {
        return runCatching {
            val raw=store.read("pack-${pack.id}-${pack.version}") ?: return null
            val metadata=store.read("origin-${pack.id}-${pack.version}")?.let(::JSONObject) ?: return null
            val origin=VerifiedPackOrigin(metadata.getString("id"),metadata.getInt("version"),metadata.getString("checksum"))
            val hash=java.security.MessageDigest.getInstance("SHA-256").digest(raw.toByteArray(Charsets.UTF_8))
                .joinToString(""){"%02x".format(it.toInt() and 255)}
            check(origin.key==pack.key && origin.checksum==hash && PackCodec.decode(raw).copy(source="")==pack.copy(source=""))
            origin
        }.getOrNull()
    }
    fun importPack(input: InputStream): DrivePack {
        val raw = PackCodec.read(input)
        val pack = PackCodec.decode(raw, "가져온 경로")
        val existing = list().find { it.key == pack.key }
        require(existing == null || existing.copy(source = pack.source) == pack) { "같은 ID 및 버전이 이미 있습니다. 버전을 올려주세요" }
        if (existing != null) return existing
        check(store.names().count{it.startsWith("pack-")}<100) {"저장할 수 있는 코스 수를 초과했습니다"}
        store.write("pack-${pack.id}-${pack.version}",raw)
        return pack
    }
}

/** Ordered, one-time events. A receipt must be durably saved before an action runs. */
class PackEngine(val pack: DrivePack, completed: Set<String> = emptySet()) {
    val completed = completed.toMutableSet()
    val next: Stop? get() = pack.stops.firstOrNull { it.id !in completed }
    fun candidate(latitude: Double, longitude: Double, timestamp: Long, now: Long): Stop? {
        if (!latitude.isFinite() || !longitude.isFinite() || latitude !in -90.0..90.0 || longitude !in -180.0..180.0) return null
        if (timestamp <= 0 || now - timestamp > 15000 || timestamp - now > 5000) return null
        return next?.takeIf { distance(latitude, longitude, it.latitude, it.longitude) <= it.radiusMeters }
    }
    fun mark(id: String) { require(next?.id == id); completed.add(id) }
    companion object {
        fun distance(a: Double, b: Double, c: Double, d: Double): Double {
            val p = Math.toRadians(c - a); val q = Math.toRadians(d - b)
            val v = sin(p / 2).pow(2) + cos(Math.toRadians(a)) * cos(Math.toRadians(c)) * sin(q / 2).pow(2)
            return 6371000 * 2 * asin(sqrt(v.coerceIn(0.0, 1.0)))
        }
    }
}

class ProgressStore(context: Context,private val namespace: String?=null) {
    init {require(namespace==null || namespace.matches(Regex("[a-f0-9]{64}")))}
    private val record=namespace?.let {"account-$it-progress"} ?: "progress"
    private val context=context.applicationContext
    private val store=PrivateStore(context)
    private val prefs get() = context.getSharedPreferences("pack_progress", Context.MODE_PRIVATE)
    private fun data(): JSONObject {
        if(namespace!=null)return JSONObject(store.read(record) ?: "{}")
        if(!store.exists("progress") && prefs.all.isNotEmpty()) {
            val next=JSONObject();prefs.all.forEach {(key,value) -> next.put(key,org.json.JSONArray((value as Set<*>).toList()))}
            store.write("progress",next.toString())
        }
        val result=JSONObject(store.read("progress") ?: "{}")
        if(prefs.all.isNotEmpty()) {
            val previous=JSONObject();prefs.all.forEach {(key,value)->previous.put(key,org.json.JSONArray((value as Set<*>).toList()))}
            LegacyArchive.preserve(store,"progress",previous.toString())
            check(context.deleteSharedPreferences("pack_progress")) {"이전 진행 정리 실패"}
        }
        return result
    }
    fun read(pack: DrivePack): Set<String> {
        val ids=data().optJSONArray(pack.key) ?: return emptySet()
        return (0 until ids.length()).map {ids.getString(it)}.toSet()
    }
    fun save(pack: DrivePack, ids: Set<String>): Boolean = runCatching {
        val next=data();next.put(pack.key,org.json.JSONArray(ids.toList()));store.write(record,next.toString());true
    }.getOrDefault(false)
    fun reset(pack: DrivePack): Boolean = runCatching {
        val next=data();next.remove(pack.key);store.write(record,next.toString());true
    }.getOrDefault(false)
}
