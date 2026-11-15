package io.wegoh.app

import android.content.Intent
import android.test.InstrumentationTestCase
import ai.pleos.playground.location.fused.FusedLocation
import ai.pleos.playground.location.fused.listener.FusedLocationListener
import ai.pleos.playground.location.fused.model.LocationData

/** Actual SDK observations in the confirmed emulator; never coordinates or fake callbacks. */
@Suppress("DEPRECATION")
class FusedTransportDiagnosticsTests: InstrumentationTestCase() {
    fun testActualTimestampClockDomainsAndContext() {
        val base=instrumentation.targetContext
        val activity=instrumentation.startActivitySync(Intent(base,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        val rows=org.json.JSONArray()
        try {
            for(wrapped in listOf(false,true)) {
                val context=if(wrapped)object: android.content.ContextWrapper(base) {override fun getApplicationContext(): android.content.Context=this} else base.applicationContext
                val samples=java.util.concurrent.CopyOnWriteArrayList<org.json.JSONObject>()
                val nulls=java.util.concurrent.atomic.AtomicInteger();val errors=java.util.concurrent.atomic.AtomicInteger();var initialized=false
                lateinit var fused: FusedLocation
                val listener=object: FusedLocationListener {
                    override fun onChanged(location: LocationData?) {
                        if(location==null){nulls.incrementAndGet();return}
                        samples.add(org.json.JSONObject().put("wallAgeMs",System.currentTimeMillis()-location.timestampMillis)
                            .put("elapsedAgeMs",android.os.SystemClock.elapsedRealtime()-location.timestampMillis)
                            .put("withinSyntheticStop",PackEngine.distance(location.latitude,location.longitude,37.4979,127.0276)<=100))
                    }
                    override fun onError(exception: Exception) {errors.incrementAndGet()}
                }
                try {
                    instrumentation.runOnMainSync {fused=FusedLocation(context);assertTrue(fused.isSupported());initialized=true;fused.initialize();fused.registerFusedLocationCallback(listener);fused.getLastKnownLocation(listener)}
                    Thread.sleep(15000)
                } finally {if(initialized)instrumentation.runOnMainSync {runCatching {fused.unregisterFusedLocationCallback(listener)};fused.release()}}
                rows.put(org.json.JSONObject().put("wrappedApplicationContext",wrapped).put("samples",org.json.JSONArray(samples)).put("nulls",nulls.get()).put("errors",errors.get()))
            }
        } finally {
            java.io.File(base.cacheDir,"fused-transport-diagnostics.json").writeText(org.json.JSONObject().put("virtualGps",true).put("observations",rows).toString(2))
            instrumentation.runOnMainSync {activity.finish()}
        }
        assertEquals(2,rows.length())
        assertTrue("Actual platform ApplicationContext delivered no non-null location; see private masked clock-domain diagnostic",rows.getJSONObject(0).getJSONArray("samples").length()>0)
    }
}
