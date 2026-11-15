package io.wegoh.app

import android.content.Context
import android.content.Intent
import android.os.SystemClock
import android.test.InstrumentationTestCase
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong

/** Actual emulator SDK delivery; host supplies staged synthetic GPS, never SDK callbacks. */
@Suppress("DEPRECATION")
class NavigationWaypointsTests: InstrumentationTestCase() {
    private fun await(label: String,seconds: Int=25,predicate: ()->Boolean) {
        val until=SystemClock.elapsedRealtime()+seconds*1000
        while(SystemClock.elapsedRealtime()<until) {
            var ok=false;instrumentation.runOnMainSync {ok=predicate()}
            if(ok)return
            Thread.sleep(100)
        }
        fail("Timed out: $label")
    }
    fun testRealTwoWaypointsThenCompletedStopExclusion() {
        assertEquals("Emulator only","1",Runtime.getRuntime().exec(arrayOf("getprop","ro.kernel.qemu")).inputStream.bufferedReader().use {it.readText().trim()})
        val base=instrumentation.targetContext
        val activity=instrumentation.startActivitySync(Intent(base,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        val namespace="waypoint-sdk-"+java.util.UUID.randomUUID()
        val dir=File(base.cacheDir,namespace).apply {mkdirs()}
        val isolated=object: android.content.ContextWrapper(base) {
            override fun getApplicationContext(): Context=this
            override fun getFilesDir()=File(dir,"files").apply {mkdirs()}
            override fun getNoBackupFilesDir()=File(dir,"no-backup").apply {mkdirs()}
            override fun getSharedPreferences(name: String,mode: Int)=base.getSharedPreferences("$namespace-$name",mode)
            override fun deleteSharedPreferences(name: String)=base.deleteSharedPreferences("$namespace-$name")
        }
        fun originals(): String {val progress=ProgressStore(base)
            return PackRepository(base).list().sortedBy {it.key}.joinToString {it.key+progress.read(it).sorted().toString()}+VisitedPlaces(base).list().toString()}
        val before=originals();val results=JSONArray();val freshOutside=AtomicInteger();val lastTimestamp=AtomicLong()
        lateinit var controller: WegoController
        var probe: LocationClient?=null
        var succeeded=false
        fun stage(value: String) {File(base.cacheDir,"sdk-waypoints-stage.json").writeText(JSONObject()
            .put("stage",value).put("recordedAtMillis",System.currentTimeMillis()).toString())}
        stage("OUTSIDE")
        instrumentation.runOnMainSync {controller=WegoController(isolated,base.applicationContext);controller.setVisible(true)}
        try {
            await("actual parked CarUx and protected records") {controller.state.setupAllowed && controller.state.storageReady}
            val json=JSONObject(base.assets.open("packs/02-weekend.json").use {PackCodec.read(it)}).put("id","sdk-three-stop-waypoints")
            val pack=controller.repository.importPack(json.toString().byteInputStream())
            assertEquals(3,pack.stops.size)
            instrumentation.runOnMainSync {
                assertTrue(controller.consentLocation());controller.select(pack.key);controller.reset();controller.begin(pack.key)
                // Additional test-only actual subscription checks the geographic/freshness
                // precondition. Raw coordinates/timestamps never enter evidence or logs.
                probe=LocationClient(base,{data->
                    val fresh=System.currentTimeMillis()-data.timestampMillis in 0..15000
                    val outside=pack.stops.all {PackEngine.distance(data.latitude,data.longitude,it.latitude,it.longitude)>it.radiusMeters}
                    if(fresh && outside && lastTimestamp.getAndSet(data.timestampMillis)!=data.timestampMillis)freshOutside.incrementAndGet()
                },{})
                probe!!.start()
            }
            await("two distinct fresh actual Fused positions outside every stop",35) {
                freshOutside.get()>=2 && controller.state.location=="위치 수신"
            }
            assertTrue(controller.state.active);assertNull(controller.state.error)
            assertTrue("Initial fresh outside input must not execute a stop",controller.state.completed.isEmpty())
            results.put(JSONObject().put("stage","outside").put("freshDistinctOutsideCallbacks",freshOutside.get())
                .put("outsideAllThreeRegions",true).put("productLocationReceived",true).put("completedCount",0))
            fun readback(label: String,expectedStops: Int) {
                instrumentation.runOnMainSync {controller.requestNavigation()}
                await("$label current destination and ordered waypoints") {
                    controller.state.navigationPhase in setOf(NavigationPhase.ACTIVE,NavigationPhase.OEM_GUIDANCE_REPORTED) &&
                        controller.state.navigationObservation?.oemGuidanceReported==true
                }
                val observed=controller.state.navigationObservation!!
                assertTrue(observed.requestCurrent && observed.targetMatches && observed.orderMatches)
                assertNotNull(observed.isRouting)
                val phase=if(observed.isRouting==true)NavigationPhase.ACTIVE else NavigationPhase.OEM_GUIDANCE_REPORTED
                assertEquals(phase,controller.state.navigationPhase)
                assertEquals(observed.isRouting==false,observed.activeFlagConflict)
                assertFalse(controller.state.navigationBusy);assertNull(controller.state.error)
                if(observed.isRouting==false)assertNull(controller.state.navigationOverview)
                results.put(JSONObject().put("stage",label).put("requestedStops",expectedStops).put("expectedWaypoints",expectedStops-1)
                    .put("targetMatches",observed.targetMatches).put("orderMatches",observed.orderMatches)
                    .put("status",observed.status!!.name).put("mode",observed.mode!!.name).put("isRouting",observed.isRouting)
                    .put("activeFlagConflict",observed.activeFlagConflict).put("phase",phase.name)
                    .put("verifiedOverviewPublished",controller.state.navigationOverview!=null))
            }
            readback("two-waypoints",3)
            assertTrue("All three stops must still be pending",controller.state.completed.isEmpty())
            stage("ENTER_FIRST")
            await("first actual Fused arrival event",35) {controller.state.completed==setOf(pack.stops.first().id)}
            Thread.sleep(3000);instrumentation.waitForIdleSync()
            assertEquals(setOf(pack.stops.first().id),controller.state.completed)
            assertEquals(1,controller.state.history.takeWhile {it!="SESSION_START"}.count {it.startsWith("EVENT_EXECUTED ")})
            val remaining=remainingNavigationPack(pack,controller.state.completed)!!
            assertEquals(pack.stops.drop(1).map {it.id},remaining.stops.map {it.id})
            results.put(JSONObject().put("stage","first-arrival").put("completedCount",1).put("executionCount",1).put("duplicateExecuted",false))
            readback("completed-stop-excluded",2)
            assertEquals(setOf(pack.stops.first().id),controller.state.completed)
            succeeded=true
        } finally {
            stage("DONE")
            instrumentation.runOnMainSync {probe?.release();controller.close();activity.finish()}
            val cleared=controller.state.navigationObservation==null && controller.state.navigationPhase==NavigationPhase.IDLE
            val preserved=before==originals()
            File(base.cacheDir,"sdk-waypoints-result.json").writeText(JSONObject().put("recordedAtMillis",System.currentTimeMillis())
                .put("emulatorOnly",true).put("virtualGps",true).put("succeeded",succeeded).put("observations",results)
                .put("closeClearedObservation",cleared).put("originalRecordsPreserved",preserved).toString(2))
            assertTrue("Close must clear current provider state",cleared)
            assertTrue("Real SDK test must preserve original user records",preserved)
        }
    }
}
