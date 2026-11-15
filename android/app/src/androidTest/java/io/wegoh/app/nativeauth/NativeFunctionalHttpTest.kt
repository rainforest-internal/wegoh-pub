package io.wegoh.app.nativeauth

import android.test.InstrumentationTestCase
import android.test.InstrumentationTestRunner
import android.util.Base64
import java.io.File
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference
import io.wegoh.app.WegoApplication

/** Real local TLS/mTLS, synthetic CA/phone, isolated UUID profile; no Activity/default manager. */
@Suppress("DEPRECATION")
class NativeFunctionalHttpTest: InstrumentationTestCase() {
    private fun waitFor(label: String,currentStage: (()->VehicleConnection.Stage)?=null,predicate: ()->Boolean) {
        val until=android.os.SystemClock.elapsedRealtime()+25000
        while(android.os.SystemClock.elapsedRealtime()<until) {if(predicate())return;Thread.sleep(20)}
        fail("Functional fixture timeout: $label"+(currentStage?.invoke()?.let {" (stage=${it.name})"} ?: ""))
    }
    fun testTypedFunctionalReadAuthorityAndLateResponses() {
        val args=(instrumentation as InstrumentationTestRunner).arguments
        val context=instrumentation.targetContext
        val application=context.applicationContext as WegoApplication
        val controller=application.javaClass.getDeclaredField("controller\$delegate").apply {isAccessible=true}.get(application) as Lazy<*>
        val vehicle=application.javaClass.getDeclaredField("vehicleConnection\$delegate").apply {isAccessible=true}.get(application) as Lazy<*>
        val controllerWasInitialized=controller.isInitialized();val vehicleWasInitialized=vehicle.isInitialized()
        val ca=NativeDeviceIdentity.parseCertificates(String(Base64.decode(args.getString("ca"),Base64.DEFAULT),Charsets.US_ASCII)).single()
        val profile="functional_"+java.util.UUID.randomUUID().toString().replace("-","").take(24)
        val nonce=args.getString("gpsNonce")!!.also {check(Regex("[a-f0-9]{24}").matches(it))}
        val markers=mutableListOf<File>()
        fun mark(name: String) {File(context.cacheDir,name).also {markers.add(it)}.writeText(nonce)}
        fun marked(name: String)=File(context.cacheDir,name).let {it.isFile && it.readText()==nonce}
        fun remove(name: String) {File(context.cacheDir,name).delete()}
        val connection=VehicleConnection.synthetic(context,profile,args.getString("port")!!.toInt(),ca,args.getString("eventsPort")!!.toInt())
        val store=NativeConnectionState(context,profile)
        val protocol=NativeAccessCodec(context).functional
        assertEquals(4,protocol.disclosureVersion)
        fun receive(): Result<FunctionalPermissions> {
            val result=AtomicReference<Result<FunctionalPermissions>?>(null)
            connection.readFunctionalPermissions {result.set(it)}
            waitFor("typed permission callback") {result.get()!=null};return result.get()!!
        }
        var socket: java.io.Closeable?=null
        try {
            connection.setForeground(true);connection.setSetupAllowed(true)
            waitFor("fresh isolated profile") {connection.status().stage==VehicleConnection.Stage.READY}
            connection.start("Synthetic functional consent")
            waitFor("one approval completed",currentStage={connection.status().stage}) {connection.status().stage==VehicleConnection.Stage.CONNECTED}
            val initial=receive().getOrThrow();assertEquals(0L,initial.revision);assertTrue(initial.approvedPurposes.isEmpty())
            assertEquals(4,initial.disclosureVersion);assertNull(initial.approvedDisclosureVersion)
            val credentials=store.read().getJSONObject("access").getJSONObject("credentials").toString()
            mark("functional-approved")
            val approved=receive().getOrThrow();assertEquals(1L,approved.revision);assertEquals(setOf(FunctionalPurpose.FRIENDS_READ),approved.approvedPurposes)
            assertEquals(4,approved.disclosureVersion);assertEquals(4,approved.approvedDisclosureVersion)
            assertEquals(credentials,store.read().getJSONObject("access").getJSONObject("credentials").toString())
            val invalidations=AtomicInteger(0);val opened=AtomicInteger(0)
            connection.connectEvents(object: VehicleEventsListener {
                override fun onOpen(){opened.incrementAndGet()}
                override fun onEvent(event: VehicleEvent){if(event.type=="invalidate" && event.resources==listOf("devices"))invalidations.incrementAndGet()}
            }) {socket=it.getOrThrow()}
            waitFor("base devices stream") {opened.get()==1 && socket!=null}
            mark("functional-denied");mark("functional-invalidate")
            waitFor("own functional invalidation") {invalidations.get()==1}
            val denied=receive().getOrThrow();assertEquals(2L,denied.revision);assertTrue(denied.approvedPurposes.isEmpty())
            assertEquals(4,denied.disclosureVersion);assertEquals(4,denied.approvedDisclosureVersion)
            mark("functional-wrong-grant");assertTrue(receive().isFailure);remove("functional-wrong-grant")
            assertEquals(credentials,store.read().getJSONObject("access").getJSONObject("credentials").toString())
            val late=AtomicInteger(0)
            mark("functional-late-foreground");connection.readFunctionalPermissions {late.incrementAndGet()}
            waitFor("actual functional GET entered") {marked("functional-entered-foreground")}
            connection.setForeground(false);mark("functional-release-foreground")
            waitFor("late foreground response returned") {marked("functional-completed-foreground")};Thread.sleep(120)
            assertEquals(0,late.get());remove("functional-late-foreground")
            connection.setForeground(true);waitFor("base reverified") {connection.status().stage==VehicleConnection.Stage.CONNECTED}
            val resumed=receive().getOrThrow();assertTrue(resumed.approvedPurposes.isEmpty())
            assertEquals(2L,resumed.revision);assertEquals(4,resumed.approvedDisclosureVersion)
            mark("functional-late-logout");connection.readFunctionalPermissions {late.incrementAndGet()}
            waitFor("actual logout GET entered") {marked("functional-entered-logout")}
            connection.disconnect();mark("functional-release-logout")
            waitFor("late logout response returned") {marked("functional-completed-logout")}
            waitFor("own revoke acknowledged") {store.read().getJSONObject("access").let {!it.has("credentials") && it.getJSONArray("outbox").length()==0}}
            Thread.sleep(120);assertEquals(0,late.get())
            assertEquals(controllerWasInitialized,controller.isInitialized());assertEquals(vehicleWasInitialized,vehicle.isInitialized())
        } finally {
            socket?.close();connection.close();markers.forEach {it.delete()}
            for(name in listOf("functional-entered-foreground","functional-entered-logout","functional-completed-foreground","functional-completed-logout"))File(context.cacheDir,name).delete()
            assertEquals(controllerWasInitialized,controller.isInitialized());assertEquals(vehicleWasInitialized,vehicle.isInitialized())
        }
    }
}
