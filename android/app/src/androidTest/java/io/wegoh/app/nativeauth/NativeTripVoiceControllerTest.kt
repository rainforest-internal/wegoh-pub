package io.wegoh.app.nativeauth

import android.Manifest
import android.content.Context
import android.content.ContextWrapper
import android.content.pm.PackageManager
import android.test.InstrumentationTestCase
import android.test.InstrumentationTestRunner
import android.util.Base64
import java.io.File
import java.util.concurrent.atomic.AtomicReference

@Suppress("DEPRECATION")
class NativeTripVoiceControllerTest: InstrumentationTestCase() {
    private fun await(label: String, condition: ()->Boolean) {
        val deadline=android.os.SystemClock.elapsedRealtime()+25000
        while(android.os.SystemClock.elapsedRealtime()<deadline) {if(condition())return;Thread.sleep(20)}
        fail("Trip voice controller fixture timeout: $label")
    }

    fun testOffHoldActivationAndCancellationThroughActualTlsSession() {
        val args=(instrumentation as InstrumentationTestRunner).arguments
        val target=instrumentation.targetContext
        assertEquals("Only the disposable QA test app may have microphone permission",PackageManager.PERMISSION_GRANTED,
            target.checkSelfPermission(Manifest.permission.RECORD_AUDIO))
        val nonce=args.getString("voiceNonce")!!.also {check(Regex("[a-f0-9]{24}").matches(it))}
        val trip=args.getString("tripId")!!.also {check(Regex("[a-f0-9]{32}").matches(it))}
        val root=File(target.cacheDir,"trip-voice-controller-"+java.util.UUID.randomUUID()).apply {check(mkdir())}
        val context=object: ContextWrapper(target) {
            override fun getApplicationContext(): Context=this
            override fun getNoBackupFilesDir()=File(root,"no-backup").apply {mkdirs()}
            override fun getFilesDir()=File(root,"files").apply {mkdirs()}
            override fun getCacheDir()=File(root,"cache").apply {mkdirs()}
        }
        fun file(stage: String)=File(target.cacheDir,"tripvoice_"+nonce+"_"+stage)
        fun mark(stage: String) {file(stage).writeText("1")}
        fun marked(stage: String)=file(stage).let {it.isFile && it.readText()=="1"}
        fun main(action: ()->Unit)=instrumentation.runOnMainSync(action)
        val ca=NativeDeviceIdentity.parseCertificates(String(Base64.decode(args.getString("ca"),Base64.DEFAULT),Charsets.US_ASCII)).single()
        val connection=VehicleConnection.synthetic(context,"tripvoice_"+nonce,args.getString("port")!!.toInt(),ca)
        var controller: NativeTripVoiceController?=null
        val latest=AtomicReference<NativeTripVoiceController.State>()
        fun start(name: String): NativeTripVoiceController {
            mark(name+"-ready");await(name+" armed") {marked(name+"-go")}
            latest.set(null)
            val own=NativeTripVoiceController(connection,trip,"Synthetic held controller") {latest.set(it)}
            controller=own
            main {own.updateSafety(true,true);own.start()}
            await(name+" starts OFF") {latest.get()?.let {it.phase==NativeTripVoiceController.Phase.OFF && !it.participating}==true}
            return own
        }
        fun press(own: NativeTripVoiceController) {
            var accepted=false
            main {accepted=own.press()}
            assertTrue("The current OFF hold must be accepted",accepted)
        }
        fun finish(name: String, own: NativeTripVoiceController) {
            main {own.release();own.close()};controller=null
            instrumentation.waitForIdleSync()
            mark(name+"-closed")
        }
        try {
            connection.setSetupAllowed(true);connection.setForeground(true)
            await("isolated profile ready") {connection.status().stage==VehicleConnection.Stage.READY}
            connection.start("Synthetic held voice controller")
            await("synthetic current grant") {connection.status().stage==VehicleConnection.Stage.CONNECTED}
            mark("connected")

            start("held").let {own->
                press(own);mark("held-pressed")
                await("held request observed") {marked("held-request-observed")}
                assertEquals(NativeTripVoiceController.Phase.REQUESTING,latest.get().phase)
                finish("held",own)
            }
            for((name,stage) in listOf("release-patch" to "patch","release-ready" to "ready")) {
                val own=start(name);press(own);mark(name+"-pressed")
                await(name+" delayed response entered") {marked(name+"-"+stage+"-entered")}
                main {own.release()};mark(name+"-released")
                await(name+" receive connection ready") {latest.get()?.phase==NativeTripVoiceController.Phase.LISTENING}
                mark(name+"-listening")
                await(name+" zero requests checked") {marked(name+"-checked")}
                finish(name,own)
            }
            start("busy").let {own->
                press(own);mark("busy-pressed")
                await("busy floor ended and receive ready") {latest.get()?.phase==NativeTripVoiceController.Phase.LISTENING}
                mark("busy-listening")
                await("busy zero requests checked") {marked("busy-checked")}
                finish("busy",own)
            }
            start("manual").let {own->
                main {own.setParticipation(true)}
                await("manual ON receive connection ready") {latest.get()?.phase==NativeTripVoiceController.Phase.LISTENING}
                mark("manual-listening")
                await("manual zero requests checked") {marked("manual-checked")}
                finish("manual",own)
            }
            mark("complete")
        } finally {
            main {controller?.close()}
            connection.close()
        }
    }
}
