package io.wegoh.app

import android.content.pm.PackageManager
import android.test.InstrumentationTestCase
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference
import io.wegoh.app.nativeauth.TripLocationFix

class TripLocationObservationTest: InstrumentationTestCase() {
    fun testForegroundVirtualGpsStopsAfterClose() {
        val context=instrumentation.targetContext
        assertTrue(WegoController.PERMISSIONS.all {context.checkSelfPermission(it)==PackageManager.PERMISSION_GRANTED})
        val first=CountDownLatch(1)
        val received=AtomicReference<TripLocationFix>()
        val calls=AtomicInteger()
        val unavailable=AtomicInteger()
        lateinit var observation: TripLocationObservation
        instrumentation.runOnMainSync {
            observation=TripLocationObservation(context,{true},{fix->
                calls.incrementAndGet()
                if(kotlin.math.abs(fix.latitude-37.5)<0.001 && kotlin.math.abs(fix.longitude-127.0)<0.001) {
                    received.set(fix);first.countDown()
                }
            },{unavailable.incrementAndGet()})
        }
        try {
            assertTrue("No current fix from the emulator's virtual GPS",first.await(35,TimeUnit.SECONDS))
            assertEquals(0,unavailable.get())
            val fix=received.get()
            assertNotNull(fix)
            assertTrue(System.currentTimeMillis()-fix.capturedAtMillis in 0L..15000L)
            instrumentation.runOnMainSync {observation.close()}
            val stopped=calls.get()
            Thread.sleep(2500)
            instrumentation.waitForIdleSync()
            assertEquals("A closed trip must not receive further GPS callbacks",stopped,calls.get())
        } finally {instrumentation.runOnMainSync {observation.close()}}
    }
}
