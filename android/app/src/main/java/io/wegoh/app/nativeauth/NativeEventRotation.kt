package io.wegoh.app.nativeauth

import java.io.Closeable

internal class NativeEventRotation(
    private val current: ()->Boolean,
    private val connect: (Boolean,VehicleEventsListener,(Result<Closeable>)->Unit)->Unit,
    private val schedule: (()->Unit)->Closeable,
    private val listener: VehicleEventsListener,
    private val completed: (Result<Closeable>)->Unit,
    private val log: (String)->Unit
): Closeable {
    private var generation=0L
    private var closed=false
    private var initialized=false
    private var rotating=false
    private var waiting=false
    private var failures=0
    private var socket: Closeable?=null
    private var timeout: Closeable?=null
    private var snapshot: VehicleEvent?=null
    private val changed=mutableSetOf<String>()
    private var versions: Map<String,String?>?=null
    private val pendingVersions=mutableMapOf<String,String?>()

    fun start()=open()
    private fun open() {
        if(closed)return
        if(!current()){finishFailure(NativeEventsFailure(NativeEventsFailure.Kind.AUTHORITY));return}
        val token=++generation
        waiting=true;snapshot=null;changed.clear();pendingVersions.clear()
        timeout=schedule {if(token==generation && waiting)attemptFailed(token,NativeEventsFailure(NativeEventsFailure.Kind.TRANSPORT))}
        val events=object: VehicleEventsListener {
            override fun onEvent(event: VehicleEvent) {
                if(token!=generation || closed)return
                if(waiting) {
                    if(event.type=="snapshot") {snapshot=event;ready(token)}
                    else if(event.type=="invalidate"){changed.addAll(event.resources);event.versions?.let {pendingVersions.putAll(it)}}
                } else {
                    event.versions?.let {updates->versions=versions.orEmpty().toMutableMap().apply {updates.forEach {(key,value)->if(value==null)remove(key) else put(key,value)}}}
                    listener.onEvent(event)
                }
            }
            override fun onClosed(code: Int) {
                if(token!=generation || closed)return
                if(code==1008 && initialized && !waiting) {
                    rotating=true;failures=0
                    socket?.close();socket=null
                    open()
                } else if(waiting)attemptFailed(token,NativeEventsFailure(NativeEventsFailure.Kind.TRANSPORT))
                else finishClosed(code)
            }
            override fun onClosed()=onClosed(1000)
            override fun onUnavailable() {
                if(token!=generation || closed)return
                if(waiting)attemptFailed(token,NativeEventsFailure(NativeEventsFailure.Kind.TRANSPORT))
                else finishFailure(NativeEventsFailure(NativeEventsFailure.Kind.TRANSPORT))
            }
        }
        try {connect(rotating,events) {reply->
            if(token!=generation || closed) {reply.getOrNull()?.close();return@connect}
            reply.fold(onSuccess={socket=it;ready(token)},onFailure={attemptFailed(token,it)})
        }} catch(error: Exception) {attemptFailed(token,error)}
    }
    private fun ready(token: Long) {
        val first=snapshot ?: return
        if(token!=generation || closed || !waiting || socket==null)return
        if(!current()){finishFailure(NativeEventsFailure(NativeEventsFailure.Kind.AUTHORITY));return}
        timeout?.close();timeout=null;waiting=false
        val rotation=rotating
        rotating=false;failures=0
        if(!initialized) {initialized=true;completed(Result.success(this));if(closed)return;listener.onOpen()}
        if(rotation)log("native.events: reconnected reason=server_rotation")
        val previous=versions
        if(first.versions!=null) {
            val latest=first.versions.toMutableMap().apply {pendingVersions.forEach {(key,value)->if(value==null)remove(key) else put(key,value)}}
            if(rotation && previous!=null) {
                val delta=(latest.keys+previous.keys).filter {latest[it]!=previous[it]}.sorted()
                if(delta.isNotEmpty())listener.onEvent(VehicleEvent("invalidate",delta,delta.associateWith {latest[it]}))
            } else {
                listener.onEvent(first)
                if(changed.isNotEmpty())listener.onEvent(VehicleEvent("invalidate",changed.toList().sorted(),pendingVersions.toMap()))
            }
            versions=latest
        } else {
            listener.onEvent(first)
            if(changed.isNotEmpty())listener.onEvent(VehicleEvent("invalidate",changed.toList().sorted()))
        }
        changed.clear()
    }
    private fun attemptFailed(token: Long,error: Throwable) {
        if(token!=generation || closed)return
        generation++;timeout?.close();timeout=null;socket?.close();socket=null
        if(rotating && current() && ++failures<2)open() else finishFailure(error)
    }
    private fun finishFailure(error: Throwable) {
        val notify=initialized
        close()
        if(notify) {
            if(rotating)log("native.events: reconnect failed reason=${NativeEventsFailure.from(error).kind.name.lowercase()}")
            listener.onUnavailable()
        }
        else completed(Result.failure(error))
    }
    private fun finishClosed(code: Int) {close();listener.onClosed(code)}
    override fun close() {
        if(closed)return
        closed=true;generation++;timeout?.close();timeout=null;socket?.close();socket=null;changed.clear()
    }
}
