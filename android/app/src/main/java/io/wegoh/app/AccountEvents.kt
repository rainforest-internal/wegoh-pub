package io.wegoh.app

import io.wegoh.app.nativeauth.WegoLog
import android.os.Looper
import android.os.Handler
import io.wegoh.app.nativeauth.VehicleConnection
import io.wegoh.app.nativeauth.VehicleEvent
import io.wegoh.app.nativeauth.VehicleEventsListener
import java.io.Closeable

internal class AccountEvents(private val connection: VehicleConnection): Closeable {
    private class Subscriber(val listener: VehicleEventsListener) {var opened=false}
    private val subscribers=linkedSetOf<Subscriber>()
    private val handler=Handler(Looper.getMainLooper())
    private var expiry: Runnable?=null
    private var socket: Closeable?=null
    private var generation=0L
    private var connecting=false
    private var closed=false
    private var epoch=-1L
    private var revision=-1L
    private var versions: Map<String,String?>?=null
    private val observer=connection.observe {
        if(subscribers.isNotEmpty() && (epoch!=connection.dataEpoch() || revision!=connection.dataStreamRevision()))fail("boundary_changed")
    }
    private fun main()=check(Looper.myLooper()==Looper.getMainLooper())
    fun subscribe(listener: VehicleEventsListener): Closeable {
        main();check(!closed)
        if(subscribers.isNotEmpty() && (epoch!=connection.dataEpoch() || revision!=connection.dataStreamRevision()))fail("boundary_changed")
        val subscriber=Subscriber(listener);subscribers.add(subscriber)
        if(socket==null && !connecting)open() else if(socket!=null)ready()
        return Closeable {
            main();subscribers.remove(subscriber)
            if(subscribers.isEmpty())reset()
        }
    }
    private fun reset() {generation++;connecting=false;expiry?.let {handler.removeCallbacks(it)};expiry=null;socket?.close();socket=null;epoch=-1;revision=-1;versions=null}
    private fun fail(reason: String) {
        main();val waiting=subscribers.toList();subscribers.clear();reset()
        if(waiting.isNotEmpty())WegoLog.w("WegoH","account.events: stream stopped reason=$reason")
        waiting.forEach {it.listener.onUnavailable()}
    }
    private fun ready() {subscribers.toList().forEach {if(it in subscribers && !it.opened){it.opened=true;it.listener.onOpen();versions?.let {current->it.listener.onEvent(VehicleEvent("snapshot",current.keys.sorted(),current))}}}}
    private fun open() {
        connecting=true;epoch=connection.dataEpoch();revision=connection.dataStreamRevision();val expected=++generation
        fun current()=!closed && expected==generation && subscribers.isNotEmpty()
        connection.connectEvents(object: VehicleEventsListener {
            override fun onEvent(event: VehicleEvent) {
                if(current())event.versions?.let {updates->
                    versions=(if(event.type=="snapshot")emptyMap() else versions.orEmpty()).toMutableMap().apply {
                        updates.forEach {(key,value)->if(value==null)remove(key) else put(key,value)}
                    }
                }
                if(current())subscribers.toList().forEach {if(it in subscribers)it.listener.onEvent(event)}
            }
            override fun onClosed() {if(current())fail("stream_closed")}
            override fun onUnavailable() {if(current())fail("stream_unavailable")}
        }) {result ->
            if(!current()) {result.getOrNull()?.close();return@connectEvents}
            connecting=false
            result.fold(onSuccess={
                val verified=connection.verifiedDataBoundary()
                if(epoch==connection.dataEpoch() && revision==connection.dataStreamRevision() && verified!=null) {
                    socket=it
                    expiry=Runnable {if(current())fail("expired")}.also {timer ->handler.postDelayed(timer,(verified.expiresAtMillis-System.currentTimeMillis()).coerceAtLeast(1))}
                    ready()
                } else {it.close();fail("boundary_changed")}
            },onFailure={fail("open_failed")})
        }
    }
    override fun close() {main();if(!closed){closed=true;observer.close();fail("closed")}}
}
