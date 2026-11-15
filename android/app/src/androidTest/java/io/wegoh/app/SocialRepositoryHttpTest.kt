package io.wegoh.app

import android.test.InstrumentationTestCase
import android.test.InstrumentationTestRunner
import io.wegoh.app.nativeauth.*
import java.io.File

@Suppress("DEPRECATION")
class SocialRepositoryHttpTest: InstrumentationTestCase() {
    private fun main(block: ()->Unit)=instrumentation.runOnMainSync(block)
    private fun waitFor(label: String,condition: ()->Boolean) {
        val end=android.os.SystemClock.elapsedRealtime()+20000
        while(android.os.SystemClock.elapsedRealtime()<end){var done=false;main {done=condition()};if(done)return;Thread.sleep(80)}
        fail(label)
    }
    fun testSharedCacheAndTransientStreamClosure() {
        val args=(instrumentation as InstrumentationTestRunner).arguments
        val base=instrumentation.targetContext
        val fixture="social_"+java.util.UUID.randomUUID().toString().replace("-","").take(24)
        val ca=NativeDeviceIdentity.parseCertificates(String(android.util.Base64.decode(args.getString("ca"),android.util.Base64.DEFAULT),Charsets.US_ASCII)).single()
        val connection=VehicleConnection.synthetic(base,fixture,args.getString("port")!!.toInt(),ca,args.getString("eventsPort")!!.toInt())
        lateinit var repository: SocialRepository
        fun marker(name: String)=File(base.cacheDir,name).writeText(args.getString("gpsNonce")!!)
        main {connection.setForeground(true);connection.setSetupAllowed(true);repository=SocialRepository(connection);repository.setForeground(true);repository.setSetupAllowed(true);connection.start("Synthetic social pages",emptySet())}
        try {
            waitFor("connected"){connection.status().stage==VehicleConnection.Stage.CONNECTED}
            main {repository.request()}
            waitFor("overview loaded"){repository.state.isCurrent && repository.state.overview?.friends?.size==1}
            repeat(3){main {repository.request()}}
            main {repository.respond("team-"+"c".repeat(40),true)}
            waitFor("accepted request refreshed"){repository.state.isCurrent && repository.state.overview?.friends?.size==2}
            marker("social-close")
            waitFor("transport preserves list read-only"){!repository.state.isCurrent && repository.state.overview?.friends?.size==2 && !repository.state.busy}
            assertEquals(AccountReadStatus.READY,repository.state.status)
            Thread.sleep(500)
            marker("social-offline-changed")
            main {repository.request()}
            waitFor("reopened connection reconciles missed changes"){repository.state.isCurrent && repository.state.overview?.friends?.firstOrNull()?.name=="Offline friend"}
            assertEquals(2,repository.state.overview?.friends?.size)
            marker("social-changed")
            waitFor("event refreshes canonical list"){repository.state.isCurrent && repository.state.overview?.friends?.firstOrNull()?.name=="Updated friend"}
            main {connection.disconnect()}
            waitFor("logout clears private list"){repository.state.overview==null}
        } finally {main {repository.close();connection.close()}}
    }
}
