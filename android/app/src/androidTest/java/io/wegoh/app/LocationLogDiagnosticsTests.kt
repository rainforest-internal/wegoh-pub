package io.wegoh.app

import android.content.pm.PackageManager
import android.os.SystemClock
import android.test.InstrumentationTestCase
import android.test.InstrumentationTestRunner
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest

@Suppress("DEPRECATION")
class LocationLogDiagnosticsTests: InstrumentationTestCase() {
    fun testExplicitLocationLogWithoutJourney() {
        val args=(instrumentation as InstrumentationTestRunner).arguments
        assertEquals("location-log-only",args.getString("diagnosticConsent"))
        assertTrue(BuildConfig.DEBUG)
        val context=instrumentation.targetContext
        assertEquals("1",Runtime.getRuntime().exec(arrayOf("getprop","ro.kernel.qemu")).inputStream.bufferedReader().use {it.readText().trim()})
        assertEquals(10,android.os.Process.myUid()/100000)
        assertTrue(WegoController.PERMISSIONS.all {context.checkSelfPermission(it)==PackageManager.PERMISSION_GRANTED})
        fun sessionRunning()=context.getSystemService(android.app.ActivityManager::class.java).getRunningServices(100)
            .any {it.service.className==SessionService::class.java.name}
        assertFalse("Use a diagnostic subscription without a running journey",sessionRunning())
        fun records()=context.noBackupFilesDir.walkTopDown().filter {it.isFile}.associate {
            it.relativeTo(context.noBackupFilesDir).path to MessageDigest.getInstance("SHA-256").digest(it.readBytes()).toList()
        }
        val before=records()
        val result=JSONObject().put("startedAtMillis",System.currentTimeMillis()).put("diagnosticConsent","explicit test invocation")
            .put("userId",android.os.Process.myUid()/100000).put("sessionServicePresentBefore",false)
        val log=LocationSampleLog()
        val lock=Any()
        var callbacks=0;var coordinateChanges=0;var timestampChanges=0
        var nullReports=0;var errorReports=0
        var latitude: Double?=null;var longitude: Double?=null;var timestamp: Long?=null
        val client=LocationClient(context,{data->
            val wall=System.currentTimeMillis();val elapsed=SystemClock.elapsedRealtime()
            synchronized(lock) {
                callbacks++
                if(latitude!=null && (latitude!=data.latitude || longitude!=data.longitude))coordinateChanges++
                if(timestamp!=null && timestamp!=data.timestampMillis)timestampChanges++
                latitude=data.latitude;longitude=data.longitude;timestamp=data.timestampMillis
                log.received(data,wall,elapsed)
            }
        },{message->synchronized(lock) {
            if(message==LocationUnavailableReason.NO_DATA)nullReports++
            if(message==LocationUnavailableReason.ERROR)errorReports++
        }})
        try {
            client.start()
            Thread.sleep(60000)
        } finally {
            client.release()
            val stoppedCount=synchronized(lock) {callbacks}
            Thread.sleep(1500)
            synchronized(lock) {
                result.put("nonNullLocationCallbacks",callbacks).put("coordinateChanges",coordinateChanges)
                    .put("sdkTimestampChanges",timestampChanges).put("callbacksAfterRelease",callbacks-stoppedCount)
                    .put("nullLocationReports",nullReports).put("locationErrorReports",errorReports)
            }
            result.put("finishedAtMillis",System.currentTimeMillis()).put("protectedRecordsUnchanged",before==records())
                .put("sessionServicePresentAfter",sessionRunning()).put("testPath","LocationClient subscription only; no Controller.begin or service start")
            File(context.cacheDir,"location-log-diagnostic.json").writeText(result.toString(2))
            assertEquals("A released diagnostic subscription must stop",stoppedCount,callbacks)
            assertEquals("The diagnostic must not write protected user records",before,records())
            assertFalse("The diagnostic must not start a journey service",sessionRunning())
        }
        assertTrue("No non-null FusedLocation sample received",callbacks>0)
    }
}
