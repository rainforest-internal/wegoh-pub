package io.wegoh.app

import android.content.Intent
import android.test.InstrumentationTestCase

/** Real SCREEN_OFF/WAKE receiver and SDK lifecycle; isolated records, not OEM Suspend. */
@Suppress("DEPRECATION")
class PowerPolicyTests: InstrumentationTestCase() {
    private fun shell(command: String): String = instrumentation.uiAutomation.executeShellCommand(command).use {
        android.os.ParcelFileDescriptor.AutoCloseInputStream(it).bufferedReader().use{reader->reader.readText()}
    }
    private fun waitFor(label: String, predicate: ()->Boolean) {
        val deadline=System.currentTimeMillis()+15000
        while(System.currentTimeMillis()<deadline) {
            var ready=false;instrumentation.runOnMainSync {ready=predicate()}
            if(ready)return
            Thread.sleep(200)
        }
        fail(label)
    }
    fun testScreenOffStopsSessionAndWakeDoesNotRestart() {
        assertEquals("1",shell("getprop ro.kernel.qemu").trim())
        shell("input keyevent KEYCODE_WAKEUP")
        val activity=instrumentation.startActivitySync(Intent(instrumentation.targetContext,MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        val base=instrumentation.targetContext
        val id="power-runtime-"+java.util.UUID.randomUUID()
        val dir=java.io.File(base.cacheDir,id).apply{mkdirs()}
        val isolated=object: android.content.ContextWrapper(base) {
            override fun getApplicationContext(): android.content.Context=this
            override fun getFilesDir()=java.io.File(dir,"files").apply{mkdirs()}
            override fun getNoBackupFilesDir()=java.io.File(dir,"no-backup").apply{mkdirs()}
            override fun getSharedPreferences(name: String,mode: Int)=base.getSharedPreferences("$id-$name",mode)
            override fun deleteSharedPreferences(name: String)=base.deleteSharedPreferences("$id-$name")
        }
        fun originals(): String {
            val progress=ProgressStore(base)
            return PackRepository(base).list().sortedBy{it.key}.joinToString{it.key+progress.read(it).sorted().toString()}+VisitedPlaces(base).list().toString()
        }
        val original=originals()
        lateinit var controller: WegoController
        var monitor: SessionPowerMonitor?=null
        instrumentation.runOnMainSync {controller=WegoController(isolated,base.applicationContext)}
        try {
            waitFor("Connected and decrypted") {controller.state.setupAllowed && controller.state.storageReady}
            instrumentation.runOnMainSync {
                assertTrue(controller.consentLocation())
                controller.begin("city-story@1")
                monitor=SessionPowerMonitor(isolated) {controller.stop()}
            }
            waitFor("Session started") {controller.state.active}
            shell("input keyevent KEYCODE_SLEEP")
            waitFor("Screen off must stop monitoring") {!controller.state.active}
            val before=controller.state.completed
            shell("input keyevent KEYCODE_WAKEUP")
            Thread.sleep(1000)
            assertFalse(controller.state.active)
            assertEquals(before,controller.state.completed)
        } finally {
            shell("input keyevent KEYCODE_WAKEUP")
            instrumentation.runOnMainSync {monitor?.close();controller.close();activity.finish()}
            assertEquals("Power test must preserve user pack progress and visit records",original,originals())
        }
    }
}
