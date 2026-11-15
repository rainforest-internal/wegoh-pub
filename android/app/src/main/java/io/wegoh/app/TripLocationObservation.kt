package io.wegoh.app

import android.content.Context
import android.os.Handler
import android.os.Looper
import io.wegoh.app.nativeauth.TripLocationFix
import java.io.Closeable

internal class TripLocationObservation(
    context: Context,private val canLocate: ()->Boolean,private val update: (TripLocationFix)->Unit,
    private val unavailable: (LocationUnavailableReason)->Unit,
): Closeable {
    private val main=Handler(Looper.getMainLooper())
    private var closed=false
    private var client: LocationClient?=null

    init {
        if(canLocate()) {
            val candidate=LocationClient(context,{data->main.post {
                if(!closed) {
                    if(canLocate())update(TripLocationFix(data.latitude,data.longitude,data.timestampMillis))
                    else {close();unavailable(LocationUnavailableReason.ERROR)}
                }
            }},report={reason->main.post {if(!closed) {
                if(reason==LocationUnavailableReason.ERROR)close()
                unavailable(reason)
            }}})
            client=startTripLocation(candidate,{it.start()},{it.release()})
            if(client==null)unavailable(LocationUnavailableReason.ERROR)
        } else unavailable(LocationUnavailableReason.ERROR)
    }

    override fun close() {closed=true;client?.release();client=null}
}
