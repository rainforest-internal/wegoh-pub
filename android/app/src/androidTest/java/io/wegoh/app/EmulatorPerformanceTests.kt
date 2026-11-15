package io.wegoh.app

import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.test.InstrumentationTestCase
import android.view.FrameMetrics
import android.view.Window
import androidx.activity.compose.setContent
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import io.wegoh.app.ui.*
import java.io.File
import java.util.concurrent.ConcurrentLinkedQueue
import org.json.JSONObject

/** Local emulator UI replay only; not a vehicle performance/certification benchmark. */
@Suppress("DEPRECATION")
class EmulatorPerformanceTests: InstrumentationTestCase() {
    fun testFrameReplay() {
        val activity=instrumentation.startActivitySync(Intent(instrumentation.targetContext,MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
        val parkedDeadline=android.os.SystemClock.elapsedRealtime()+12000
        while(!activity.controller.state.setupAllowed && android.os.SystemClock.elapsedRealtime()<parkedDeadline)Thread.sleep(100)
        assertTrue("Resource window requires actual parked CarUx state",activity.controller.state.setupAllowed)
        instrumentation.waitForIdleSync();Thread.sleep(1000)
        val parkedCpu=android.os.Process.getElapsedCpuTime();val parkedAt=android.os.SystemClock.elapsedRealtime()
        val pss=mutableListOf<Int>()
        repeat(5){Thread.sleep(2000);val info=android.os.Debug.MemoryInfo();android.os.Debug.getMemoryInfo(info);pss.add(info.totalPss)}
        val parkedWall=android.os.SystemClock.elapsedRealtime()-parkedAt
        val parkedCpuMs=android.os.Process.getElapsedCpuTime()-parkedCpu
        val cores=Runtime.getRuntime().availableProcessors()
        val base=PackCodec.decode(activity.assets.open("packs/01-city-story.json").use{PackCodec.read(it)})
        val state=WegoState(packs=listOf(base),selectedKey=base.key,setupAllowed=true,storageReady=true,locationConsented=true)
        val route=mutableStateOf("discover")
        val frames=ConcurrentLinkedQueue<Long>()
        val listener=Window.OnFrameMetricsAvailableListener {_,metrics,_->
            if(metrics.getMetric(FrameMetrics.FIRST_DRAW_FRAME)==0L)frames.add(metrics.getMetric(FrameMetrics.TOTAL_DURATION))
        }
        instrumentation.runOnMainSync {
            activity.window.addOnFrameMetricsAvailableListener(listener,Handler(Looper.getMainLooper()))
            activity.setContent {WegoCarTheme {key(route.value){PlatformScreen(state,route.value){exit->
                WegoVehicleScreen(state,{},{},{},{},{},{},{},{},{},onRootBack=exit,onPlatform=exit)
            }}}}
        }
        instrumentation.waitForIdleSync();Thread.sleep(500);frames.clear()
        val replayCpu=android.os.Process.getElapsedCpuTime();val replayAt=android.os.SystemClock.elapsedRealtime()
        try {
            repeat(5){for(next in listOf("rooms","friends","pack","challenge","results","discover")) {
                instrumentation.runOnMainSync {route.value=next}
                instrumentation.waitForIdleSync();Thread.sleep(100)
            }}
            val samples=frames.toList().sorted();assertTrue("Insufficient displayed frames",samples.size>=20)
            fun percentile(value: Double)=samples[((samples.size-1)*value).toInt()]/1_000_000.0
            val replayWall=android.os.SystemClock.elapsedRealtime()-replayAt
            val replayCpuMs=android.os.Process.getElapsedCpuTime()-replayCpu
            val result=JSONObject().put("scope","emulator-actual-parked-idle-and-synthetic-ui-replay").put("frames",samples.size)
                .put("cpuDenominator","process CPU ms / wall ms; one logical core is 100%; total-capacity value divided by available cores")
                .put("availableCores",cores).put("parkedIdleWallMs",parkedWall).put("parkedIdleCpuMs",parkedCpuMs)
                .put("parkedIdleCpuOneCorePercent",100.0*parkedCpuMs/parkedWall)
                .put("parkedIdleCpuCapacityPercent",100.0*parkedCpuMs/parkedWall/cores)
                .put("replayWallMs",replayWall).put("replayCpuMs",replayCpuMs)
                .put("replayCpuOneCorePercent",100.0*replayCpuMs/replayWall)
                .put("replayCpuCapacityPercent",100.0*replayCpuMs/replayWall/cores)
                .put("idlePssKiB",org.json.JSONArray(pss)).put("idlePeakPssMiB",pss.max()/1024.0)
                .put("limitation","Debug emulator and instrumentation workload, not market/vehicle certification; driving CPU measured separately")
                .put("medianMs",percentile(.5)).put("p90Ms",percentile(.9)).put("p95Ms",percentile(.95))
                .put("over16_7Ms",samples.count{it>16_700_000L}).put("screenChanges",30)
            File(activity.cacheDir,"emulator-performance.json").writeText(result.toString(2))
        } finally {instrumentation.runOnMainSync {activity.window.removeOnFrameMetricsAvailableListener(listener);activity.finish()}}
    }
}
