package io.wegoh.app.nativeauth

import org.json.JSONObject
import java.security.MessageDigest

internal data class CourseRoadCoordinate(val latitude: Double,val longitude: Double)

internal class CourseRoadMapsApi(private val reads: AuthorizedAccountReads) {
    fun <T> pack(id: String,version: Int,checksum: String,decode: (ByteArray)->T,callback: (Result<T>)->Unit)=
        reads.read(VehicleConnection.Scope.COURSES,callback) {client,credentials->
            val bytes=client.readPackVersion(id,version,credentials.getString("accessToken")).bytes()
            check(MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") {"%02x".format(it.toInt() and 255)}==checksum)
            decode(bytes)
        }
    fun route(id: String,version: Int,checksum: String,points: List<CourseRoadCoordinate>,callback: (Result<List<CourseRoadCoordinate>>)->Unit)=
        reads.read(VehicleConnection.Scope.COURSES,callback) {client,credentials->
            decodeCourseRoad(client.courseRoadPreview(id,version,checksum,points,credentials.getString("accessToken")))
        }
}

internal fun decodeCourseRoad(value: JSONObject): List<CourseRoadCoordinate> {
    require(value.keys().asSequence().toSet()==setOf("distanceMeters","durationSeconds","path"))
    listOf("distanceMeters","durationSeconds").forEach {key->
        require(value.get(key) is Number && value.getDouble(key).let {it.isFinite() && it>=0})
    }
    val path=value.getJSONArray("path")
    require(path.length() in 2..2000)
    return (0 until path.length()).map {index->
        val point=path.getJSONArray(index);require(point.length()==2)
        require(point.get(0) is Number && point.get(1) is Number)
        val lat=point.getDouble(0);val lng=point.getDouble(1)
        require(lat.isFinite() && lng.isFinite() && lat in 32.0..39.0 && lng in 124.0..132.0)
        CourseRoadCoordinate(lat,lng)
    }
}
