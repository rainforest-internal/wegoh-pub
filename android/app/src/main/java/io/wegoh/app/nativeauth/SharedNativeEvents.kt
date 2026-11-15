package io.wegoh.app.nativeauth

import java.io.Closeable
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong

internal class SharedNativeEvents(
    private val post: (()->Unit)->Unit,
    private val connect: (VehicleEventsListener,(Result<Closeable>)->Unit)->Unit
) {
    private class Subscriber(val listener: VehicleEventsListener,val completed: (Result<Closeable>)->Unit) {
        val active=AtomicBoolean(true)
        var opened=false
        lateinit var lease: Closeable
    }
    private val generation=AtomicLong(0)
    private var owner=-1L
    private var stream=0L
    private val subscribers=linkedSetOf<Subscriber>()
    private var opening=false
    private var socket: Closeable?=null
    private var snapshot: VehicleEvent?=null

    fun subscribe(listener: VehicleEventsListener,completed: (Result<Closeable>)->Unit) {
        val expected=generation.get()
        post {
            if(expected!=generation.get())return@post
            if(owner!=expected) {stop();owner=expected}
            val subscriber=Subscriber(listener,completed)
            subscriber.lease=Closeable {
                subscriber.active.set(false)
                post {
                    subscribers.remove(subscriber)
                    if(subscribers.isEmpty() && owner==expected)stop()
                }
            }
            subscribers.add(subscriber)
            if(socket!=null && snapshot!=null)ready() else if(!opening)open(expected)
        }
    }
    private fun open(expected: Long) {
        opening=true
        val token=++stream
        val listener=object: VehicleEventsListener {
            override fun onEvent(event: VehicleEvent) {
                if(expected!=generation.get() || token!=stream)return
                if(event.type=="snapshot")snapshot=event
                else event.versions?.let {updates->snapshot?.let {previous->
                    val versions=previous.versions.orEmpty().toMutableMap().apply {
                        updates.forEach {(key,value)->if(value==null)remove(key) else put(key,value)}
                    }
                    snapshot=VehicleEvent("snapshot",versions.keys.sorted(),versions)
                }}
                val opened=subscribers.filter {it.opened}
                ready()
                if(event.type!="snapshot")opened.forEach {if(it.active.get() && expected==generation.get() && token==stream)it.listener.onEvent(event)}
            }
            override fun onClosed(code: Int)=failed(expected,token,NativeEventsFailure(NativeEventsFailure.Kind.TRANSPORT))
            override fun onClosed()=onClosed(1000)
            override fun onUnavailable()=failed(expected,token,NativeEventsFailure(NativeEventsFailure.Kind.TRANSPORT))
        }
        connect(listener) {result->
            if(expected!=generation.get() || token!=stream) {result.getOrNull()?.close();return@connect}
            result.fold(onSuccess={socket=it;ready()},onFailure={failed(expected,token,it)})
        }
    }
    private fun ready() {
        val baseline=snapshot ?: return
        if(socket==null)return
        val expected=generation.get()
        val token=stream
        subscribers.toList().forEach {subscriber->
            if(expected==generation.get() && token==stream && subscriber.active.get() && !subscriber.opened) {
                subscriber.opened=true;subscriber.completed(Result.success(subscriber.lease))
                if(subscriber.active.get() && expected==generation.get() && token==stream) {
                    subscriber.listener.onOpen()
                    if(subscriber.active.get() && expected==generation.get() && token==stream)subscriber.listener.onEvent(baseline)
                }
            }
        }
    }
    private fun failed(expected: Long,token: Long,error: Throwable) {
        if(expected!=generation.get() || token!=stream)return
        val waiting=subscribers.toList();stop()
        waiting.forEach {if(it.active.getAndSet(false)) {
            if(it.opened)it.listener.onUnavailable() else it.completed(Result.failure(error))
        }}
    }
    private fun stop() {
        stream++;socket?.close();socket=null;snapshot=null;opening=false;subscribers.clear();owner=-1
    }
    fun reset() {
        val next=generation.incrementAndGet()
        post {
            if(owner<next) {
                val waiting=subscribers.toList();stop()
                waiting.forEach {if(it.active.getAndSet(false)) {
                    if(it.opened)it.listener.onUnavailable()
                    else it.completed(Result.failure(NativeEventsFailure(NativeEventsFailure.Kind.AUTHORITY)))
                }}
            }
        }
    }
}
