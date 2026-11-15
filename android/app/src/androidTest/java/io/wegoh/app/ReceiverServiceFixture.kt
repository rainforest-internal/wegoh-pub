package io.wegoh.app

import android.content.Context
import android.content.ComponentName
import android.content.Intent
import android.content.ServiceConnection
import android.os.IBinder
import android.os.Looper
import io.wegoh.app.nativeauth.CommandReceiver
import java.io.Closeable
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

internal class ApprovedReceiverFixture(val service: VehicleClimateService,
    val revision: AtomicReference<Long?>,private val cleanup: ()->Unit): Closeable {
    override fun close()=cleanup()
}

internal fun WegoApplication.simulateApprovedReceiver(): ApprovedReceiverFixture {
    check(Looper.myLooper()!=Looper.getMainLooper()) {"Service fixture waits on the instrumentation thread"}
    val preferenceName = "climate_service_test_" + UUID.randomUUID()
    val car = CommandReceiver("a".repeat(32), "b".repeat(32), 1, true)
    val settings = VehicleReceiverSettings(getSharedPreferences(preferenceName, Context.MODE_PRIVATE),
        { 1L }, { it(Result.success(car)) }, { _, _, _ -> error("Unexpected change to reception") }, {})
    settings.refresh()
    val field = javaClass.getDeclaredField("receiverSettings\$delegate").apply { isAccessible = true }
    val original = field.get(this)
    field.set(this, lazyOf(settings))
    // These existing tests isolate window/CarUx behavior, not account authentication.
    // Supply that explicit authority fixture to the bound service without weakening
    // the production connection boundary or writing synthetic credentials.
    val ready=CountDownLatch(1)
    val revision=AtomicReference<Long?>(1L)
    var receiver: VehicleClimateService?=null
    val binding=object: ServiceConnection {
        override fun onServiceConnected(name: ComponentName,binder: IBinder) {
            val service=(binder as VehicleClimateService.ReceiverBinder).service
            receiver=service
            val authority=service.javaClass.getDeclaredField("currentReceiverRevision").apply {isAccessible=true}
            authority.set(service,{revision.get()})
            ready.countDown()
        }
        override fun onServiceDisconnected(name: ComponentName) {}
    }
    val bound=bindService(Intent(this,VehicleClimateService::class.java),binding,Context.BIND_AUTO_CREATE)
    if(!bound || !ready.await(10,TimeUnit.SECONDS)) {
        if(bound)unbindService(binding)
        field.set(this,original)
        deleteSharedPreferences(preferenceName)
        error("Receiver fixture did not bind")
    }
    return ApprovedReceiverFixture(checkNotNull(receiver),revision) {
        unbindService(binding)
        field.set(this, original)
        deleteSharedPreferences(preferenceName)
    }
}
