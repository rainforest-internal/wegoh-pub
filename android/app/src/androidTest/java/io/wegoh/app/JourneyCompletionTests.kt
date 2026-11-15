package io.wegoh.app

import ai.pleos.playground.location.fused.listener.FusedLocationListener
import ai.pleos.playground.location.fused.model.LocationData
import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.test.InstrumentationTestCase
import java.io.File

/** Isolated records; the second case requires the Pleos location SDK but uses synthetic fixes. */
@Suppress("DEPRECATION")
class JourneyCompletionTests: InstrumentationTestCase() {
    private class Fixture(base: Context) {
        val id="journey-completion-${java.util.UUID.randomUUID()}"
        val directory=File(base.cacheDir,id).apply {mkdirs()}
        var stopped=0
        val context=object: ContextWrapper(base) {
            override fun getApplicationContext(): Context=this
            override fun getFilesDir()=File(directory,"files").apply {mkdirs()}
            override fun getNoBackupFilesDir()=File(directory,"no-backup").apply {mkdirs()}
            override fun getSharedPreferences(name: String,mode: Int)=base.getSharedPreferences("$id-$name",mode)
            override fun stopService(service: Intent): Boolean {stopped++;return true}
        }
        val pack=DrivePack("completion-test",1,"완료 검증","","",listOf(
            Stop("first","첫 장소",80.0,-150.0,25f,"도착"),
            Stop("last","마지막 장소",80.1,-150.1,25f,"도착")))
        val progress=ProgressStore(context)
        val visits=VisitedPlaces(context)
        var state=WegoState(packs=listOf(pack),selectedKey=pack.key)
        val manager=JourneyExecutionManager(context,base,{state},{state=it},
            {JourneyStartPlan(pack,CourseOwner.Local(pack.key),progress,visits,null,null)},
            {true},{false},{true},{state=state.copy(error=it)},{state=state.copy(message=it)},{},{},{})
    }

    fun testAlreadyCompletedCourseNeverStartsLocationAndStopsItsService() {
        instrumentation.runOnMainSync {
            val f=Fixture(instrumentation.targetContext)
            assertTrue(f.progress.save(f.pack,f.pack.stops.map {it.id}.toSet()))
            try {
                var ready=false
                f.manager.begin(f.pack.key) {ready=true}
                assertFalse(f.manager.isActive)
                assertFalse("There is no remaining destination to navigate",ready)
                assertEquals(1,f.stopped)
                assertEquals(f.pack.stops.map {it.id}.toSet(),f.progress.read(f.pack))
                val client=JourneyExecutionManager::class.java.getDeclaredField("locationClient").apply {isAccessible=true}.get(f.manager)
                assertNull("Completed courses must not initialize a location subscription",client)
            } finally {f.manager.stop()}
        }
    }

    fun testFinalFixReleasesLocationAfterDurableCompletionAndEmptyFixCanRecover() {
        lateinit var f: Fixture
        lateinit var listener: FusedLocationListener
        instrumentation.runOnMainSync {
            f=Fixture(instrumentation.targetContext)
            f.manager.begin(f.pack.key)
            val client=JourneyExecutionManager::class.java.getDeclaredField("locationClient").apply {isAccessible=true}.get(f.manager) as LocationClient
            listener=LocationClient::class.java.getDeclaredField("listener").apply {isAccessible=true}.get(client) as FusedLocationListener
        }
        fun emit(stop: Stop) {
            instrumentation.runOnMainSync {listener.onChanged(LocationData(stop.latitude,stop.longitude,0.0,0f,1f,System.currentTimeMillis()))}
            instrumentation.waitForIdleSync()
        }
        try {
            emit(f.pack.stops.first())
            instrumentation.runOnMainSync {assertTrue(f.manager.isActive);listener.onChanged(null)}
            instrumentation.waitForIdleSync()
            instrumentation.runOnMainSync {
                assertTrue("An empty cached fix must not terminate an ongoing course",f.manager.isActive)
                assertEquals("위치 정보 없음",f.state.location)
                assertEquals(0,f.stopped)
            }
            emit(f.pack.stops.last())
            instrumentation.runOnMainSync {
                assertFalse(f.manager.isActive)
                assertEquals(1,f.stopped)
                assertEquals(f.pack.stops.map {it.id}.toSet(),f.progress.read(f.pack))
                assertEquals(2,f.visits.list().length())
                assertTrue(f.state.courseResult?.completed==true)
            }
            emit(f.pack.stops.last())
            instrumentation.runOnMainSync {assertEquals(2,f.visits.list().length());assertEquals(1,f.stopped)}
        } finally {instrumentation.runOnMainSync {f.manager.stop()}}
    }
}
