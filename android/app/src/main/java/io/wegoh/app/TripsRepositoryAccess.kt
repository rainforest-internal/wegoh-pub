package io.wegoh.app

import android.os.Handler
import android.os.Looper
import io.wegoh.app.nativeauth.*
import java.io.Closeable

internal interface TripsRepositoryClient: Closeable {
    val tripsApi: TripsApi
    val ready: Boolean
    fun open(observer: NativeSocialObserver,callback: (Result<Unit>)->Unit)
}

internal interface TripsRepositoryAccess {
    val scoreNamespace: String? get()=null
    val scoreReportAuthority: ScoreReportAuthority? get()=null
    val connected: Boolean
    var onExpired: ()->Unit
    fun observe(changed: ()->Unit): Closeable
    fun client(): TripsRepositoryClient
    fun subscribe(listener: VehicleEventsListener): Closeable
    fun remember(): Boolean
    fun canRetain(): Boolean
    fun invalidated(): Boolean
    fun forget()
    fun post(action: ()->Unit)
    /** 주기 작업용 지연 실행. 기본은 예약하지 않아 단위 시험에서 반복 읽기를 만들지 않는다. */
    fun schedule(delayMillis: Long,action: ()->Unit): Closeable = Closeable {}
}

internal class NativeTripsRepositoryAccess(private val connection: VehicleConnection,private val events: AccountEvents): TripsRepositoryAccess {
    override val scoreNamespace get()=connection.verifiedDataBoundary()?.storageKey
    override val scoreReportAuthority get()=connection.verifiedScoreReportAuthority()
    override var onExpired: ()->Unit = {}
    private val snapshot=AccountReadSnapshot(connection,null) {onExpired()}
    override val connected get()=connection.status().stage==VehicleConnection.Stage.CONNECTED
    override fun observe(changed: ()->Unit)=connection.observe {changed()}
    override fun client(): TripsRepositoryClient {
        val client=connection.tripSocial()
        return object: TripsRepositoryClient {
            override val tripsApi get()=client.tripsApi
            override val ready get()=client.status()==NativeSocialClient.State.READY
            override fun open(observer: NativeSocialObserver,callback: (Result<Unit>)->Unit)=client.open(observer,callback)
            override fun close()=client.close()
        }
    }
    override fun subscribe(listener: VehicleEventsListener)=events.subscribe(listener)
    override fun remember(): Boolean {
        val boundary=connection.verifiedDataBoundary() ?: return false
        snapshot.remember(boundary);return true
    }
    override fun canRetain()=snapshot.canRetain()
    override fun invalidated()=snapshot.invalidated()
    override fun forget()=snapshot.forget()
    override fun post(action: ()->Unit) {Handler(Looper.getMainLooper()).post(action)}
    override fun schedule(delayMillis: Long,action: ()->Unit): Closeable {
        val main=Handler(Looper.getMainLooper());val task=Runnable(action)
        main.postDelayed(task,delayMillis)
        return Closeable {main.removeCallbacks(task)}
    }
}
