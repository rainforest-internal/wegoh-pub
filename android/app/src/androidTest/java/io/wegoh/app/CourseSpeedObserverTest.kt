package io.wegoh.app

import android.test.InstrumentationTestCase
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

@Suppress("DEPRECATION")
class CourseSpeedObserverTest: InstrumentationTestCase() {
    private val received=CountDownLatch(2)
    private var observer: CourseSpeedObserver?=null
    @Volatile private var speed: Double?=null
    private fun open() {observer=CourseSpeedObserver(instrumentation.targetContext) {_,value->
        if(value!=null) {speed=value;received.countDown()}
    }}
    private fun close() {observer?.close()}
    fun testVehicleSpeedCallbacksArriveThroughTheProductionObserver() {
        instrumentation.runOnMainSync(::open)
        try {
            assertTrue("No two valid speed callbacks from VHAL",received.await(8,TimeUnit.SECONDS))
            assertTrue(checkNotNull(speed).isFinite())
            assertTrue(checkNotNull(speed)>=0)
        } finally {instrumentation.runOnMainSync(::close)}
    }
}
