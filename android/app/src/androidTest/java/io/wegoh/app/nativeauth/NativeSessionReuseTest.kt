package io.wegoh.app.nativeauth

import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.graphics.Bitmap
import android.test.InstrumentationTestCase
import android.test.InstrumentationTestRunner
import android.util.Base64
import androidx.activity.compose.setContent
import io.wegoh.app.TripScreensPreviewActivity
import io.wegoh.app.ui.TripMusicPage
import io.wegoh.app.ui.TripSurface
import io.wegoh.app.ui.WegoCarTheme
import io.wegoh.app.NativeTripMusicGateway
import io.wegoh.app.TripMusicRepository
import io.wegoh.app.TripMusicStatus
import org.json.JSONArray
import org.json.JSONObject
import java.io.Closeable
import java.io.File
import java.util.concurrent.atomic.AtomicReference
import java.util.concurrent.atomic.AtomicInteger

@Suppress("DEPRECATION")
class NativeSessionReuseTest: InstrumentationTestCase() {
    private fun await(label: String, condition: ()->Boolean) {
        val deadline=android.os.SystemClock.elapsedRealtime()+25000
        while(android.os.SystemClock.elapsedRealtime()<deadline) {if(condition())return;Thread.sleep(10)}
        fail("Session reuse fixture timeout: $label")
    }

    private fun capture(repository: TripMusicRepository) {
        val activity=instrumentation.startActivitySync(Intent(instrumentation.targetContext,TripScreensPreviewActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_MULTIPLE_TASK)) as TripScreensPreviewActivity
        try {
            instrumentation.runOnMainSync {activity.setContent {WegoCarTheme {TripSurface {
                TripMusicPage("인증 재사용 QA 여행",repository.state,true,{},{},{},{},{},{})
            }}}}
            instrumentation.waitForIdleSync();Thread.sleep(250)
            val image=instrumentation.uiAutomation.takeScreenshot() ?: error("No QA screenshot")
            File(instrumentation.targetContext.filesDir,"session-reuse-ready.png").outputStream().use {
                check(image.compress(Bitmap.CompressFormat.PNG,100,it))
            }
            image.recycle()
        } finally {instrumentation.runOnMainSync {activity.setContent {};activity.finish()}}
    }

    fun testMusicAndOtherScreensReuseTheCurrentSession() {
        val args=(instrumentation as InstrumentationTestRunner).arguments
        val target=instrumentation.targetContext
        val nonce=args.getString("reuseNonce")!!.also {check(Regex("[a-f0-9]{24}").matches(it))}
        val trip=args.getString("tripId")!!.also {check(Regex("[a-f0-9]{32}").matches(it))}
        val root=File(target.cacheDir,"session-reuse-"+nonce).apply {check(mkdir())}
        val context=object: ContextWrapper(target) {
            override fun getApplicationContext(): Context=this
            override fun getNoBackupFilesDir()=File(root,"no-backup").apply {mkdirs()}
            override fun getFilesDir()=File(root,"files").apply {mkdirs()}
            override fun getCacheDir()=File(root,"cache").apply {mkdirs()}
        }
        fun marker(stage: String)=File(target.cacheDir,"sessionreuse_"+nonce+"_"+stage)
        fun phase(name: String) {
            marker(name+"-ready").writeText("1")
            await(name+" armed") {marker(name+"-go").let {it.isFile && it.readText()=="1"}}
        }
        fun main(action: ()->Unit)=instrumentation.runOnMainSync(action)
        val ca=NativeDeviceIdentity.parseCertificates(String(Base64.decode(args.getString("ca"),Base64.DEFAULT),Charsets.US_ASCII)).single()
        val connection=VehicleConnection.synthetic(context,"reuse_"+nonce,args.getString("port")!!.toInt(),ca)
        val metrics=JSONArray()
        var host: Closeable?=null
        var music: TripMusicRepository?=null
        var client: NativeSocialClient?=null
        try {
            connection.setSetupAllowed(true);connection.setForeground(true)
            await("isolated profile ready") {connection.status().stage==VehicleConnection.Stage.READY}
            connection.start("Synthetic session reuse")
            await("synthetic current grant") {connection.status().stage==VehicleConnection.Stage.CONNECTED}
            val opened=AtomicReference<Result<Closeable>>()
            main {connection.connectEvents(object: VehicleEventsListener {override fun onEvent(event: VehicleEvent) {}}) {opened.set(it)}}
            await("host feed") {opened.get()!=null}
            host=opened.get().getOrThrow()
            for(index in 0..2) {
                phase("music-$index")
                val repository=TripMusicRepository(trip) {NativeTripMusicGateway(connection,trip)};music=repository
                val start=android.os.SystemClock.elapsedRealtime()
                main {repository.setAvailable(true)}
                await("music collection") {repository.state.status in setOf(TripMusicStatus.READY,TripMusicStatus.UNAVAILABLE)}
                metrics.put(JSONObject().put("case","music-$index").put("durationMs",android.os.SystemClock.elapsedRealtime()-start)
                    .put("ready",repository.state.status==TripMusicStatus.READY))
                if(index==2 && repository.state.status==TripMusicStatus.READY)capture(repository)
                main {repository.close()};music=null
                marker("music-$index-done").writeText("1")
            }
            phase("overview")
            val social=connection.social();client=social
            val complete=AtomicReference<Result<SocialOverview>>()
            val start=android.os.SystemClock.elapsedRealtime()
            main {social.open(object: NativeSocialObserver {}) {result->
                result.fold(onSuccess={social.readOverview {complete.set(it)}},onFailure={complete.set(Result.failure(it))})
            }}
            await("overview") {complete.get()!=null}
            metrics.put(JSONObject().put("case","overview").put("durationMs",android.os.SystemClock.elapsedRealtime()-start)
                .put("ready",complete.get().isSuccess))
            marker("overview-done").writeText("1")
            val max=args.getString("maxMusicMs")!!.toLong()
            for(index in 0 until metrics.length()) {
                val row=metrics.getJSONObject(index)
                assertTrue("Authenticated projection must succeed: "+row.getString("case"),row.getBoolean("ready"))
                assertTrue("Current session must avoid per-screen preparation: "+row.getString("case")+" durationMs="+row.getLong("durationMs"),row.getLong("durationMs")<max)
            }
            if(args.getString("boundaryChecks")=="true") {
                main {client?.close()};client=null
                for(name in listOf("late-background","late-revocation")) {
                    phase(name)
                    val own=connection.tripSocial();client=own
                    val callbacks=AtomicInteger(0);val invalidated=AtomicInteger(0)
                    main {own.open(object: NativeSocialObserver {
                        override fun onInvalidated() {invalidated.incrementAndGet()}
                        override fun onConnectionLost() {invalidated.incrementAndGet()}
                    }) {result->
                        check(result.isSuccess)
                        NativeTripMusicApi(own).read(trip) {callbacks.incrementAndGet()}
                    }}
                    await(name+" successful response held") {marker(name+"-entered").isFile}
                    if(name=="late-background")main {connection.setForeground(false)}
                    await(name+" authority invalidated") {invalidated.get()>0}
                    marker(name+"-invalidated").writeText("1")
                    await(name+" late response released") {marker(name+"-completed").isFile}
                    Thread.sleep(200);instrumentation.waitForIdleSync()
                    assertEquals("A successful old response must never reach the screen",0,callbacks.get())
                    main {own.close()};client=null
                    marker(name+"-done").writeText("1")
                    if(name=="late-background") {
                        connection.setForeground(true)
                        await("same account reverified after background") {connection.status().stage==VehicleConnection.Stage.CONNECTED}
                    }
                }
            }
        } finally {
            File(target.cacheDir,"sessionreuse_"+nonce+"_metrics.json").writeText(metrics.toString())
            main {music?.close();client?.close();host?.close()};connection.close()
        }
    }
}
