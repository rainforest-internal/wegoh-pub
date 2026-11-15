package io.wegoh.app.nativeauth

import android.os.Handler
import android.os.Looper
import java.io.Closeable
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong

interface NativeSocialObserver {
    fun onState(state: NativeSocialClient.State) {}
    fun onResourcesChanged(resources: Set<String>) {}
    fun onConnectionLost() {onInvalidated()}
    /** Clear host-owned private UI/cache. Previously copied host memory cannot be recalled. */
    fun onInvalidated() {}
}
internal class NativeSocialRequest<T>(val all: Set<FunctionalPurpose>,val any: Set<FunctionalPurpose> = emptySet(),
    val mutation: Boolean=false,val fetch: (NativeApiClient,String,FunctionalPermissions,String)->T,
    val expires: (T)->Long? = {null}, val discard: (T)->Unit = {},val climateAcknowledgement: Boolean=false,
    val setupRequired: Boolean=false,val diagnosticScope: String?=null,
    /** Time-bound call (listen-together presence and control) served on its own lane; see [NativeCallLanes]. */
    val realtime: Boolean=false)

internal fun socialRequestFailure(error: Throwable,mayHaveExecuted: Boolean): NativeSocialFailure {
    if(error is NativeSocialFailure)return error
    val status=(error as? NativeApiClient.Failure)?.status
    val kind=when {
        error is NativeApiClient.Failure && error.code in setOf("CONSENT_REVOKED","GRANT_EXPIRED","INSTALLATION_REVOKED")->NativeSocialFailure.Kind.AUTHORIZATION_REQUIRED
        status==401->NativeSocialFailure.Kind.AUTHORIZATION_REQUIRED
        status==403->NativeSocialFailure.Kind.FORBIDDEN
        status==404->NativeSocialFailure.Kind.NOT_FOUND
        status==409->NativeSocialFailure.Kind.CONFLICT
        status==413->NativeSocialFailure.Kind.TOO_LARGE
        status==429->NativeSocialFailure.Kind.RATE_LIMITED
        status==408 || status!=null && status in 500..599 || error is java.io.IOException->NativeSocialFailure.Kind.UNAVAILABLE
        else->NativeSocialFailure.Kind.INVALID_RESPONSE
    }
    return NativeSocialFailure(kind,httpStatus=status,mayHaveExecuted=mayHaveExecuted,
        retryAfterSeconds=(error as? NativeApiClient.Failure)?.retryAfterSeconds,
        serverErrorCode=NativeSocialErrorCodec.safeCode((error as? NativeApiClient.Failure)?.code))
}

/** Typed business calls own a subscription to the connection manager's event feed. */
class NativeSocialClient internal constructor(private val connection: VehicleConnection,internal val climateReceiver: Boolean=false,
    private val refreshOnDataChange: Boolean=false): Closeable {
    enum class State { UNOPENED, OPENING, READY, UNAVAILABLE, CLOSED }
    private val main=Handler(Looper.getMainLooper())
    private val guard=Any()
    private val generation=AtomicLong(0)
    @Volatile private var state=State.UNOPENED
    @Volatile private var baseEpoch=-1L
    private var socket: Closeable?=null
    private var snapshot=false
    private var observer: NativeSocialObserver?=null
    private var opening: ((Result<Unit>)->Unit)?=null
    @Volatile private var expiry: Runnable?=null
    private var expiresAt=Long.MAX_VALUE
    private var acknowledgementsOnly=false
    /** Seconds the current expiry timer was armed for; reported when that timer ends this client. */
    @Volatile private var armedExpirySeconds=0L
    private val watched=java.util.concurrent.ConcurrentHashMap.newKeySet<String>()

    fun status(): State = state
    /** Explicit open/reopen. READY requires both adoption and a verified first devices snapshot. */
    fun open(observer: NativeSocialObserver,callback: (Result<Unit>)->Unit) {
        check(!acknowledgementsOnly)
        val token=synchronized(guard) {
            if(state in setOf(State.CLOSED,State.OPENING,State.READY)) {
                main.post {callback(Result.failure(NativeSocialFailure(if(state==State.CLOSED)NativeSocialFailure.Kind.CLOSED else NativeSocialFailure.Kind.UNAVAILABLE)))}
                return
            }
            generation.incrementAndGet().also {state=State.OPENING;this.observer=observer;opening=callback;snapshot=false;baseEpoch=connection.dataEpoch()}
        }
        main.post {if(generation.get()==token && state==State.OPENING)observer.onState(State.OPENING)}
        val listener=object: VehicleEventsListener {
            override fun onEvent(event: VehicleEvent) {
                if(generation.get()!=token)return
                if(event.type=="snapshot" && "devices" in event.resources) {synchronized(guard){snapshot=true};finishOpen(token)}
                else if(event.type=="invalidate" && ("devices" in event.resources || (refreshOnDataChange && event.resources.isNotEmpty() || event.resources.any {it in watched}))) {
                    observer.onResourcesChanged(event.resources.toSet())
                    if(!refreshOnDataChange)end(false,why=NativeFunctionalDiagnostics.End.LOCAL,cause="event_devices")
                }
            }
            override fun onClosed() {if(generation.get()==token)end(false,transport=true,why=NativeFunctionalDiagnostics.End.TRANSPORT,cause="closed")}
            override fun onUnavailable() {if(generation.get()==token)end(false,transport=true,why=NativeFunctionalDiagnostics.End.TRANSPORT,cause="unavailable")}
        }
        val completed: (Result<Closeable>)->Unit = {result ->
            result.fold(onSuccess={handle->
                val adopted=synchronized(guard) {if(generation.get()!=token || state!=State.OPENING)false else {socket=handle;true}}
                if(!adopted)handle.close() else finishOpen(token)
            },onFailure={if(generation.get()==token) {
                if((it as? NativeEventsFailure)?.kind==NativeEventsFailure.Kind.TRANSPORT)end(false,transport=true,why=NativeFunctionalDiagnostics.End.TRANSPORT,cause="open_failed")
                else end(false,why=NativeFunctionalDiagnostics.End.LOCAL,cause="open_failed")
            }})
        }
        try {if(climateReceiver)connection.connectClimateEvents(listener,completed) else connection.connectEvents(listener,completed)}
        catch(_: java.util.concurrent.RejectedExecutionException) {end(false,why=NativeFunctionalDiagnostics.End.LOCAL,cause="rejected")}
    }
    private fun finishOpen(token: Long) {
        val notify=synchronized(guard) {
            if(generation.get()!=token || state!=State.OPENING || socket==null || !snapshot)return
            if(!baseCurrent()) {end(false,why=NativeFunctionalDiagnostics.End.LOCAL,cause="base_changed");return}
            state=State.READY;val callback=opening;opening=null;observer to callback
        }
        limitLifetime(token,connection.socialBaseExpiry())
        notify.first?.onState(State.READY);notify.second?.invoke(Result.success(Unit))
    }
    private fun baseCurrent()=if(climateReceiver)connection.climateBaseCurrent(baseEpoch) else connection.socialBaseCurrent(baseEpoch)
    internal fun adoptClimateAcknowledgements(expectedEpoch: Long,expiresAtMillis: Long,observer: NativeSocialObserver) {
        val token=synchronized(guard) {
            check(climateReceiver && state==State.UNOPENED)
            baseEpoch=expectedEpoch;check(baseCurrent())
            acknowledgementsOnly=true;this.observer=observer;state=State.READY
            generation.incrementAndGet()
        }
        limitLifetime(token,expiresAtMillis)
    }
    internal fun current(token: Long): Boolean = token==generation.get() && state==State.READY && baseCurrent()
    internal fun limitLifetime(token: Long,until: Long) {
        main.post {
            if(!current(token))return@post
            expiresAt=minOf(expiresAt,until);expiry?.let {main.removeCallbacks(it)}
            val task=Runnable {if(current(token))end(false,why=NativeFunctionalDiagnostics.End.EXPIRED)};expiry=task
            val remaining=expiresAt-connection.socialNow()
            armedExpirySeconds=remaining.coerceAtLeast(0)/1000
            if(remaining<=0)end(false,why=NativeFunctionalDiagnostics.End.EXPIRED) else {main.postDelayed(task,remaining);if(!current(token))main.removeCallbacks(task)}
        }
    }
    /** Ends this client for [cause]: a connection-wide invalidation reason, or a local one when [connectionWide] is false. */
    internal fun authorityInvalidated(cause: String,connectionWide: Boolean=true)=
        end(false,why=if(connectionWide)NativeFunctionalDiagnostics.End.INVALIDATED else NativeFunctionalDiagnostics.End.LOCAL,cause=cause)
    internal val diagnosticKind get()=if(climateReceiver)"climate" else if(refreshOnDataChange)"trip" else "social"
    private fun end(closed: Boolean,transport: Boolean=false,why: NativeFunctionalDiagnostics.End,cause: String?=null) {
        var endedAt=0L
        var oldExpiry: Runnable?=null
        val old=synchronized(guard) {
            if(state==State.CLOSED || (!closed && state in setOf(State.UNOPENED,State.UNAVAILABLE)))return
            val active=state in setOf(State.OPENING,State.READY);endedAt=generation.incrementAndGet();state=if(closed)State.CLOSED else State.UNAVAILABLE
            oldExpiry=expiry;expiry=null
            val handle=socket;socket=null;snapshot=false;expiresAt=Long.MAX_VALUE
            val callback=opening;opening=null
            Triple(handle,callback,if(active)observer else null)
        }
        connection.socialEnded(this,why,cause,if(why==NativeFunctionalDiagnostics.End.EXPIRED)armedExpirySeconds else null)
        old.first?.let {runCatching {it.close()}}
        oldExpiry?.let {main.removeCallbacks(it)}
        main.post {
            // Already-occurred termination must settle its captured observer/open callback.
            // A newer generation suppresses old state/data, not mandatory private-cache clearing.
            if(transport)old.third?.onConnectionLost() else old.third?.onInvalidated()
            if(generation.get()==endedAt)old.third?.onState(if(closed)State.CLOSED else State.UNAVAILABLE)
            old.second?.invoke(Result.failure(NativeSocialFailure(if(closed)NativeSocialFailure.Kind.CLOSED else NativeSocialFailure.Kind.UNAVAILABLE)))}
        if(closed)connection.socialClosed(this)
    }
    internal fun <T> call(request: NativeSocialRequest<T>,callback: (Result<T>)->Unit): Closeable {
        require(!climateReceiver || request.all==setOf(FunctionalPurpose.DEVICE_COMMANDS_RECEIVE) && request.any.isEmpty())
        require(!acknowledgementsOnly || request.climateAcknowledgement && request.mutation)
        watched.addAll((request.all+request.any).mapNotNull {purpose -> when(purpose.wire.substringBefore(':')) {
            "friends"->"friends";"rooms"->"rooms";"history"->"history";"cautions"->"cautions";"recommendations"->"recommendations"
            "vehicle-reports"->"vehicle";"device-commands"->"commands";"room-music"->"music";"room-voice"->"voice";else->null
        }})
        val token=generation.get()
        if(!current(token)) {
            WegoLog.w("WegoH","native.social: call skipped reason=client_not_ready")
            val cancelled=AtomicBoolean(false)
            main.post {if(!cancelled.get())callback(Result.failure(NativeSocialFailure(if(state==State.CLOSED)NativeSocialFailure.Kind.CLOSED else NativeSocialFailure.Kind.UNAVAILABLE)))}
            return Closeable {cancelled.set(true)}
        }
        return connection.socialCall(this,token,request,callback)
    }
    /** Internal Voice projections reuse the same atomic authority/callback boundary. */
    internal fun <T> executeVoiceRequest(request: NativeSocialRequest<T>, callback: (Result<T>)->Unit): Closeable = call(request,callback)
    val deviceCommandsApi: DeviceCommandsApi=NativeDeviceCommandsApi(this)
    val missionsApi: MissionsApi=NativeMissionsApi(this)
    val recommendationsApi: RecommendationsApi=NativeRecommendationsApi(this)
    val cautionsApi: CautionsApi=NativeCautionsApi(this)
    val friendsApi: FriendsApi=NativeFriendsApi(this)
    val overviewApi: SocialOverviewApi=NativeSocialOverviewApi(this)
    val roomsApi: RoomsApi=NativeRoomsApi(this)
    val tripsApi: TripsApi=NativeTripsApi(this)
    val historyApi: HistoryApi=NativeHistoryApi(this)
    fun readOverview(callback: (Result<SocialOverview>)->Unit)=overviewApi.readOverview(callback)
    fun readRoom(roomId: String,callback: (Result<SocialRoom>)->Unit)=roomsApi.readRoom(roomId,callback)
    fun readHistoryPage(cursor: SocialHistoryCursor?=null,callback: (Result<SocialHistoryPage>)->Unit)=historyApi.readHistoryPage(cursor,callback)
    fun sendStatusSignal(roomId: String,kind: SocialSignalKind,callback: (Result<SocialSignalReceipt>)->Unit)=roomsApi.sendStatusSignal(roomId,kind,callback)
    override fun close()=end(true,why=NativeFunctionalDiagnostics.End.CLOSE)
}
