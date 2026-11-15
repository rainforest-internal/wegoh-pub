package io.wegoh.app

import ai.pleos.playground.navi.helper.NaviHelper
import ai.pleos.playground.navi.helper.listener.NaviHelperEventListener
import ai.pleos.playground.navi.data.*
import android.content.Context
import android.os.Handler
import android.os.Looper
import io.wegoh.app.nativeauth.*
import java.io.Closeable

internal class TripSignalNavigation(private val context: Context,private val canUse: ()->Boolean): Closeable {
    private val main=Handler(Looper.getMainLooper())
    private val sessions=mutableSetOf<Closeable>()
    fun locate(callback: (SignalLocation?)->Unit): Closeable {
        if(!canUse()){callback(null);return Closeable {}}
        val helper=NaviHelper(context.applicationContext)
        var point: SignalPoint?=null
        var destination: SignalPoint?=null
        var fallback: LocationClient?=null
        var done=false
        lateinit var session: Closeable
        lateinit var listener: NaviHelperEventListener
        fun finish() {
            if(done)return
            val result=if(canUse())point?.let {SignalLocation(it,destination)} else null
            session.close();callback(result)
        }
        val timeout=Runnable {finish()}
        listener=object: NaviHelperEventListener {
            override fun onCurrentLocationInfo(currentLocationInfo: CurrentLocationInfo) {main.post {
                if(!done)point=SignalPoint(currentLocationInfo.latitude,currentLocationInfo.longitude,currentLocationInfo.heading)
            }}
            override fun onDestinationInfo(destinationInfo: DestinationInfo) {main.post {
                if(!done && destinationInfo.latitude!=0.0 && destinationInfo.longitude!=0.0)
                    destination=SignalPoint(destinationInfo.latitude,destinationInfo.longitude)
            }}
        }
        session=Closeable {
            done=true;main.removeCallbacks(timeout);fallback?.release()
            runCatching {helper.removeListener(listener);helper.release()};sessions.remove(session)
        }
        sessions.add(session)
        main.postDelayed(timeout,3500)
        runCatching {helper.initialize(onConnected={main.post {
            if(!done)runCatching {helper.addListener(listener);helper.getCurrentLocationInfo();helper.getDestinationInfo()}
        }},onFailed={})}
        main.postDelayed({
            if(!done && point==null && canUse())runCatching {
                fallback=LocationClient(context,{data->main.post {
                    if(!done && point==null && System.currentTimeMillis()-data.timestampMillis in 0..15000)
                        point=SignalPoint(data.latitude,data.longitude,data.heading.toDouble())
                }},{})
                fallback?.start()
            }
        },1500)
        return session
    }
    override fun close() {sessions.toList().forEach {it.close()}}
}
