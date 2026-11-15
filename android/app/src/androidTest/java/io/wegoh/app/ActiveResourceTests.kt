package io.wegoh.app

import android.content.Intent
import android.os.Bundle
import android.os.SystemClock
import android.test.InstrumentationTestCase
import androidx.activity.compose.setContent
import io.wegoh.app.ui.*
import java.io.File
import java.util.concurrent.atomic.AtomicInteger
import org.json.JSONArray
import org.json.JSONObject

/** Confirmed emulator only; real SDK callbacks/CarUx, isolated records, no route request. */
@Suppress("DEPRECATION")
class ActiveResourceTests: InstrumentationTestCase() {
    private fun signal(value: String)=instrumentation.sendStatus(0,Bundle().apply{putString("stream","\n$value\n")})
    private fun await(label: String,predicate: ()->Boolean) {
        val end=SystemClock.elapsedRealtime()+20000
        while(SystemClock.elapsedRealtime()<end){var ok=false;instrumentation.runOnMainSync {ok=predicate()};if(ok)return;Thread.sleep(100)}
        fail(label)
    }
    fun testActiveJourneyParkAndDriveResources() {
        assertEquals("Emulator only","1",Runtime.getRuntime().exec(arrayOf("getprop","ro.kernel.qemu")).inputStream.bufferedReader().use{it.readText().trim()})
        val base=instrumentation.targetContext
        val activity=instrumentation.startActivitySync(Intent(base,MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
        val id="active-resources-"+java.util.UUID.randomUUID();val dir=File(base.cacheDir,id).apply{mkdirs()}
        val isolated=object: android.content.ContextWrapper(base) {
            override fun getApplicationContext(): android.content.Context=this
            override fun getFilesDir()=File(dir,"files").apply{mkdirs()}
            override fun getNoBackupFilesDir()=File(dir,"no-backup").apply{mkdirs()}
            override fun getSharedPreferences(name: String,mode: Int)=base.getSharedPreferences("$id-$name",mode)
            override fun deleteSharedPreferences(name: String)=base.deleteSharedPreferences("$id-$name")
        }
        fun originals(): String {val progress=ProgressStore(base)
            return PackRepository(base).list().sortedBy{it.key}.joinToString {it.key+progress.read(it).sorted().toString()}+VisitedPlaces(base).list().toString()}
        val before=originals();lateinit var controller: WegoController
        val fresh=AtomicInteger();var observer: LocationClient?=null
        instrumentation.runOnMainSync {controller=WegoController(isolated,base.applicationContext);controller.setVisible(true)}
        try {
            await("Real parked CarUx") {controller.state.setupAllowed && controller.state.storageReady}
            instrumentation.runOnMainSync {
                assertTrue(controller.consentLocation());controller.select("city-story@1");controller.reset();controller.begin("city-story@1")
                observer=LocationClient(base,{data->if(System.currentTimeMillis()-data.timestampMillis in 0..15000)fresh.incrementAndGet()},{})
                observer!!.start()
                activity.setContent {WegoCarTheme {WegoVehicleScreen(controller.state,{},{},{},{},{},{},{},{},{})}}
            }
            await("Real fresh Fused callbacks") {controller.state.active && fresh.get()>=2 && controller.state.location=="위치 수신"}
            instrumentation.waitForIdleSync();Thread.sleep(1000)
            fun sample(label: String,parked: Boolean): JSONObject {
                val count=fresh.get();val cpu=android.os.Process.getElapsedCpuTime();val wall=SystemClock.elapsedRealtime();val pss=mutableListOf<Int>()
                repeat(5) {
                    Thread.sleep(2000)
                    instrumentation.runOnMainSync {assertTrue(controller.state.active);assertEquals(parked,controller.state.setupAllowed);assertNull(controller.state.error)}
                    val info=android.os.Debug.MemoryInfo();android.os.Debug.getMemoryInfo(info);pss.add(info.totalPss)
                }
                val duration=SystemClock.elapsedRealtime()-wall;val consumed=android.os.Process.getElapsedCpuTime()-cpu
                val percentage=100.0*consumed/duration;val bytes=pss.max().toLong()*1024
                val received=fresh.get()-count
                val result=JSONObject().put("state",label).put("activeJourney",true).put("actualCarUxAllowed",parked)
                    .put("wallMs",duration).put("processCpuMs",consumed).put("cpuOneCorePercent",percentage)
                    .put("pssKiB",JSONArray(pss)).put("peakPssBytes",bytes).put("freshSdkCallbacks",received)
                    .put("cpuWithinGuide",if(parked)percentage<=25.0 else percentage<5.0).put("ramWithinGuide",bytes<=400000000)
                assertTrue("Fresh SDK callbacks must continue in $label",received>=3)
                return result
            }
            val parked=sample("Park",true)
            signal("UX_READY_PARKED");await("Real driving CarUx") {!controller.state.setupAllowed}
            val driving=sample("Drive",false)
            signal("UX_READY_RESTRICTED");await("Original Park recovery") {controller.state.setupAllowed}
            val result=JSONObject().put("virtualGps",true).put("virtualCarUx",true).put("recordedAtMillis",System.currentTimeMillis())
                .put("cpuDenominator","process CPU ms / wall ms; one logical core is 100%; no core-count division")
                .put("memoryLimitBytes",400000000).put("windows",JSONArray().put(parked).put(driving))
                .put("scope","debug emulator actual active Fused journey, representative steady cruise; no navigation request or audio arrival")
                .put("observerOverhead","one extra real Fused subscriber plus instrumentation is included in app-process CPU/PSS; conservative upper observation, not vehicle certification")
            File(base.cacheDir,"active-resource.json").writeText(result.toString(2))
            assertTrue("Park active CPU exceeds25%",parked.getBoolean("cpuWithinGuide"))
            assertTrue("Drive non-navigation active CPU must be below5%",driving.getBoolean("cpuWithinGuide"))
            assertTrue("RAM exceeds400 decimal MB",parked.getBoolean("ramWithinGuide") && driving.getBoolean("ramWithinGuide"))
        } finally {
            instrumentation.runOnMainSync {observer?.release();controller.close();activity.finish()}
            assertEquals("Resource test must preserve user records",before,originals())
        }
    }
}
