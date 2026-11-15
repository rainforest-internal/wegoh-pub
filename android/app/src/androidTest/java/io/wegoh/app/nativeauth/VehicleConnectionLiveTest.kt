package io.wegoh.app.nativeauth

import android.content.Intent
import android.os.Bundle
import android.test.InstrumentationTestCase
import android.test.InstrumentationTestRunner
import io.wegoh.app.MainActivity
import io.wegoh.app.WegoApplication
import java.util.concurrent.atomic.AtomicInteger

/** Operator-selected new live test installation. Secrets/data never enter output.
 * Run only after reviewed deployment; existing installations are never cleared. */
class VehicleConnectionLiveTest: InstrumentationTestCase() {
    private fun waitFor(label: String, timeout: Long=180000, predicate: ()->Boolean) {
        val end=android.os.SystemClock.elapsedRealtime()+timeout
        while(android.os.SystemClock.elapsedRealtime()<end){if(predicate())return;Thread.sleep(100)}
        fail("Live connection timeout: $label")
    }
    private fun status(stage: String,public: VehicleConnection.Progress?=null) {
        val value=Bundle();value.putString("stage",stage)
        public?.userCode?.let {value.putString("userCode",it)}
        public?.verificationUri?.let {value.putString("verificationUri",it)}
        instrumentation.sendStatus(0,value)
    }
    fun testHighlevelLivePhoneApiEventsAndOwnDisconnect() {
        val args=(instrumentation as InstrumentationTestRunner).arguments
        check(args.getString("allowNewInstallation")=="true")
        val profile=args.getString("profile")!!;check(Regex("live_v2_[a-f0-9]{32}").matches(profile))
        val context=instrumentation.targetContext
        check(!NativeConnectionState(context,profile).hasStateOrKey()) {"Live test profile already exists; preserve it"}
        val main=instrumentation.startActivitySync(Intent(context,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        val app=main.application as WegoApplication
        waitFor("actual parked setup permission",20000){app.controller.state.setupAllowed}
        val connection=VehicleConnection.existingProfile(context,profile)
        var last: VehicleConnection.Stage?=null
        val observation=connection.observe {progress->
            if(progress.stage!=last){last=progress.stage;status(progress.stage.name,if(progress.stage==VehicleConnection.Stage.APPROVAL_REQUIRED)progress else null)}
        }
        val store=NativeConnectionState(context,profile)
        try {
            connection.setForeground(true);connection.setSetupAllowed(app.controller.state.setupAllowed)
            waitFor("ready",20000){connection.status().stage==VehicleConnection.Stage.READY}
            connection.start("WegoH Android 연결 확인",setOf(VehicleConnection.Scope.COURSES,VehicleConnection.Scope.PLAYLISTS))
            waitFor("approved and connected"){connection.status().stage==VehicleConnection.Stage.CONNECTED}
            val reads=AtomicInteger(0);val failures=AtomicInteger(0)
            connection.readCourses {if(it.isSuccess)reads.incrementAndGet() else failures.incrementAndGet()}
            connection.readPlaylists {if(it.isSuccess)reads.incrementAndGet() else failures.incrementAndGet()}
            waitFor("permitted reads",30000){reads.get()+failures.get()==2};assertEquals(0,failures.get())
            val opened=AtomicInteger(0);val events=AtomicInteger(0)
            connection.connectEvents(object:VehicleEventsListener {
                override fun onOpen(){opened.incrementAndGet()}
                override fun onEvent(event:VehicleEvent){events.incrementAndGet()}
                override fun onUnavailable(){failures.incrementAndGet()}
            }) {if(it.isFailure)failures.incrementAndGet()}
            waitFor("WSS101 and initial event",30000){opened.get()==1&&events.get()>0};assertEquals(0,failures.get())
            status("LIVE_API_AND_WSS_CONFIRMED")
            connection.disconnect()
            waitFor("own grant revoked",30000){val state=store.read().getJSONObject("access");!state.has("credentials")&&!state.has("authorization")&&state.getJSONArray("outbox").length()==0}
            status("LIVE_OWN_GRANT_DISCONNECTED")
        }finally{connection.disconnect();observation.close();connection.close()}
    }
}
