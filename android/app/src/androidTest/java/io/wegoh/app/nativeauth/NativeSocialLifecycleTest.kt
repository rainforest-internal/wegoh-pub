package io.wegoh.app.nativeauth

import android.content.Context
import android.content.ContextWrapper
import android.test.InstrumentationTestCase
import java.io.File
import java.util.concurrent.atomic.AtomicInteger
import org.json.JSONObject

/** Actual main Handler/API ordering with injected feed termination; not a connected TLS session. */
@Suppress("DEPRECATION")
class NativeSocialLifecycleTest: InstrumentationTestCase() {
    fun testClosedOwnedFeedDropsQueuedEffectsAndKeepsActiveHostFeed() {
        val main=android.os.Handler(android.os.Looper.getMainLooper())
        val invalidations=AtomicInteger(0);val oldCalls=AtomicInteger(0)
        val hostCalls=AtomicInteger(0);val overflowCalls=AtomicInteger(0)
        val old=OwnedVehicleEvents(main,{true},{true},{true},{overflowCalls.incrementAndGet()},
            {invalidations.incrementAndGet()},object: VehicleEventsListener {
                override fun onOpen(){oldCalls.incrementAndGet()}
                override fun onEvent(event: VehicleEvent){oldCalls.incrementAndGet()}
                override fun onClosed(){oldCalls.incrementAndGet()}
                override fun onUnavailable(){oldCalls.incrementAndGet()}
            })
        val host=OwnedVehicleEvents(main,{true},{true},{true},{overflowCalls.incrementAndGet()},
            {invalidations.incrementAndGet()},object: VehicleEventsListener {
                override fun onEvent(event: VehicleEvent){hostCalls.incrementAndGet()}
            })
        val invalidate=VehicleEvent("invalidate",listOf("devices"))
        instrumentation.runOnMainSync {
            // Real default dispatcher queues these effects behind this main operation.
            old.onOpen();old.onEvent(invalidate);old.onClosed();old.onUnavailable()
            old.close()
            // Calls received after close must not even fill/overflow the queue.
            repeat(12){old.onEvent(invalidate)}
            // Closing one owned feed must not suppress the still-active host feed.
            host.onEvent(invalidate)
            assertEquals(0,invalidations.get())
        }
        instrumentation.waitForIdleSync()
        assertEquals(0,oldCalls.get());assertEquals(0,overflowCalls.get())
        assertEquals(1,invalidations.get());assertEquals(1,hostCalls.get())
        host.close()
        val terminal=AtomicInteger(0);val globalVersion=AtomicInteger(0)
        val autoCloses=AtomicInteger(0)
        lateinit var overflowing: OwnedVehicleEvents
        overflowing=OwnedVehicleEvents(main,{globalVersion.get()==0},{globalVersion.get()==0},{true},
            {autoCloses.incrementAndGet();globalVersion.incrementAndGet();overflowing.close()},
            {invalidations.incrementAndGet()},object: VehicleEventsListener {
                override fun onUnavailable(){terminal.incrementAndGet()}
                override fun onEvent(event: VehicleEvent){oldCalls.incrementAndGet()}
            })
        instrumentation.runOnMainSync {
            repeat(9){overflowing.onEvent(invalidate)}
            assertEquals(1,autoCloses.get());assertEquals(1,globalVersion.get())
            assertEquals(0,terminal.get())
        }
        instrumentation.waitForIdleSync()
        assertEquals(1,terminal.get());assertEquals(1,invalidations.get())
        assertEquals(0,oldCalls.get())
    }

    fun testQueuedMandatoryEndSurvivesImmediateReopenOrClose() {
        val target=instrumentation.targetContext
        val root=File(target.cacheDir,"c2-handler-"+java.util.UUID.randomUUID()).apply {check(mkdir())}
        val isolated=object: ContextWrapper(target) {
            override fun getApplicationContext(): Context = this
            override fun getNoBackupFilesDir()=File(root,"no-backup").apply {mkdirs()}
            override fun getFilesDir()=File(root,"files").apply {mkdirs()}
            override fun getCacheDir()=File(root,"cache").apply {mkdirs()}
        }
        // Product canonical assets belong to instrumentation.targetContext.assets.
        // Owned test fixture/certificate/vector assets belong to instrumentation.context.assets.
        val vector=JSONObject(instrumentation.context.assets.open("native_access_certificate_vectors.json").bufferedReader().use {it.readText()})
        val pem=vector.getJSONArray("rows").getJSONObject(0).getJSONObject("response").getJSONObject("certificateReceipt").getString("certificatePem")
        val certificate=NativeDeviceIdentity.parseCertificates(pem).single()
        val connection=VehicleConnection.synthetic(isolated,"handler_"+java.util.UUID.randomUUID().toString().replace("-",""),1025,certificate)
        try {
            // Foreground remains false: no TCP, account/approval or default profile is opened.
            for(reopen in listOf(true,false)) {
                val client=connection.social();val cleared=AtomicInteger(0);val completed=AtomicInteger(0);val data=AtomicInteger(0)
                instrumentation.runOnMainSync {
                    client.open(object: NativeSocialObserver {override fun onInvalidated(){cleared.incrementAndGet()}}) {
                        check(it.isFailure);completed.incrementAndGet()
                    }
                    check(client.status()==NativeSocialClient.State.OPENING)
                    client.authorityInvalidated("test") // The same real end(false) path as own-feed termination.
                    if(reopen)client.open(object: NativeSocialObserver {}) {} else client.close()
                    client.readOverview {if(it.isSuccess)data.incrementAndGet()}
                    // Mandatory old notifications are queued behind this main-thread operation.
                    check(cleared.get()==0 && completed.get()==0)
                }
                instrumentation.waitForIdleSync()
                assertEquals(1,cleared.get());assertEquals(1,completed.get());assertEquals(0,data.get())
                client.close();instrumentation.waitForIdleSync()
            }
        } finally {connection.close();instrumentation.waitForIdleSync()}
        // This intentionally does not claim READY, adopted/snapshot/host feed, or late authenticated data.
        // Those remain the product-PG/TLS/AAR lifecycle gate in the accepted plan.
    }
}
