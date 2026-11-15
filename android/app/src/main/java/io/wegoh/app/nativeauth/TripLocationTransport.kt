package io.wegoh.app.nativeauth

import java.io.Closeable

data class TripLocationFix(val latitude: Double,val longitude: Double,val capturedAtMillis: Long,val accuracyMeters: Double?=null)
/** 다른 차의 현재 위치. 서버가 공유 동의·차단·60초 최신성을 통과한 탑승자 위치로 만든다. */
data class TripCarPosition(val carId: String,val latitude: Double,val longitude: Double,val source: String,val ageMillis: Long)
data class TripLocationShare(val tripId: String,val shareId: String?,val cars: List<TripCarPosition> = emptyList())

interface TripLocationTransport {
    fun readLocationShare(id: String,callback: (Result<TripLocationShare>)->Unit): Closeable {
        callback(Result.failure(IllegalStateException("Location sharing unavailable")))
        return Closeable {}
    }
    /** 다른 차 위치 지도용 읽기. 공유 상태 확인(readLocationShare)과 같은 응답을 쓰지만 진단과 주기가 다르다. */
    fun readCarLocations(id: String,callback: (Result<TripLocationShare>)->Unit): Closeable {
        callback(Result.failure(IllegalStateException("Car locations unavailable")))
        return Closeable {}
    }
    fun reportLocation(id: String,shareId: String,fix: TripLocationFix,callback: (Result<Unit>)->Unit): Closeable {
        callback(Result.failure(IllegalStateException("Location sharing unavailable")))
        return Closeable {}
    }
}
