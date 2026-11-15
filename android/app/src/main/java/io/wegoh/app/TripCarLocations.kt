package io.wegoh.app

import io.wegoh.app.nativeauth.TripCarPosition
import io.wegoh.app.nativeauth.TripLocationTransport
import java.io.Closeable

/**
 * 진행 중 여행 화면이 열려 있는 동안 /locations를 주기적으로 읽어 다른 차 위치를 알린다.
 * 내 위치 공유 여부와 관계없이 읽으며, 읽기에 실패하면 오래된 위치를 남기지 않도록 비운다.
 */
internal class TripCarLocations(
    private val publish: (List<TripCarPosition>)->Unit,
    private val schedule: (Long,()->Unit)->Closeable,
    private val intervalMillis: Long = TRIP_CAR_LOCATION_INTERVAL_MILLIS,
): Closeable {
    private var tripId: String?=null
    private var transport: TripLocationTransport?=null
    private var generation=0L
    private var reading: Closeable?=null
    private var waiting: Closeable?=null

    fun update(id: String?,api: TripLocationTransport?) {
        if(id==tripId && api===transport)return
        close()
        tripId=id;transport=api
        if(id!=null && api!=null)read(generation,id,api)
    }

    private fun read(token: Long,id: String,api: TripLocationTransport) {
        val request=api.readCarLocations(id) {result->
            if(token!=generation)return@readCarLocations
            reading=null
            publish(result.getOrNull()?.takeIf {it.tripId==id}?.cars.orEmpty())
            waiting=schedule(intervalMillis) {if(token==generation){waiting=null;read(token,id,api)}}
        }
        if(token!=generation)request.close() else if(waiting==null)reading=request
    }

    override fun close() {
        generation++
        reading?.close();reading=null
        waiting?.close();waiting=null
        if(tripId!=null)publish(emptyList())
        tripId=null;transport=null
    }
}

/** 차량 앱은 위치를 10초마다 보내므로 같은 주기로 읽는다. 읽기 한도(분당 60회) 안에 들어간다. */
internal const val TRIP_CAR_LOCATION_INTERVAL_MILLIS=10_000L
