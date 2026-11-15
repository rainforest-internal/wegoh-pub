package io.wegoh.nativeaccess.smoke

import android.content.Context
import android.content.ContextWrapper
import android.test.InstrumentationTestCase
import android.test.InstrumentationTestRunner
import android.util.Base64
import io.wegoh.app.nativeauth.*
import java.io.Closeable
import java.io.File
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference
import org.json.JSONObject

/** Actual AAR binary public API against an owned product-PG TLS fixture, never the default profile. */
@Suppress("DEPRECATION")
class NativeSocialAarTest: InstrumentationTestCase() {
    private fun waitFor(label: String,condition: ()->Boolean) {
        val until=android.os.SystemClock.elapsedRealtime()+30000
        while(android.os.SystemClock.elapsedRealtime()<until) {if(condition())return;Thread.sleep(20)}
        fail("Owned social fixture timeout: "+label)
    }
    private fun <T> receive(start: ((Result<T>)->Unit)->Unit): Result<T> {
        val result=AtomicReference<Result<T>?>(null);start {result.set(it)};waitFor("public callback") {result.get()!=null};return result.get()!!
    }
    fun testProductTlsFourCallsAndOwnedLifetime() {
        val args=(instrumentation as InstrumentationTestRunner).arguments
        val target=instrumentation.targetContext
        val nonce=args.getString("socialNonce")!!.also {check(Regex("[a-f0-9]{24}").matches(it))}
        val root=File(target.cacheDir,"social-aar-"+java.util.UUID.randomUUID()).apply {check(mkdir())}
        val context=object: ContextWrapper(target) {
            override fun getApplicationContext(): Context = this
            override fun getNoBackupFilesDir()=File(root,"no-backup").apply {mkdirs()}
            override fun getFilesDir()=File(root,"files").apply {mkdirs()}
            override fun getCacheDir()=File(root,"cache").apply {mkdirs()}
        }
        fun file(name: String)=File(target.cacheDir,"c2_"+nonce+"_"+name)
        fun mark(name: String){file(name).writeText("1")}
        fun marked(name: String)=file(name).let {it.isFile && it.readText()=="1"}
        val ca=CertificateFactory.getInstance("X.509").generateCertificate(Base64.decode(args.getString("ca"),Base64.DEFAULT).inputStream()) as X509Certificate
        // The JVM bridge initializes only this owned fixture; public operations use the packaged AAR.
        val connection=NativeSocialOwnedInitialization.create(context,"aar_social_"+nonce,args.getString("port")!!.toInt(),ca,args.getString("eventsPort")!!.toInt())
        val hostClosed=AtomicInteger(0);val hostInvalidate=AtomicInteger(0);val hostSnapshot=AtomicInteger(0)
        var host: Closeable?=null;var social: NativeSocialClient?=null
        val invalidated=AtomicInteger(0)
        val observedState=AtomicReference("UNOPENED");val traceLock=Any()
        fun phase(name: String,state: String=observedState.get())=synchronized(traceLock) {
            file("phases").appendText(JSONObject().put("phase",name).put("hostInvalidations",hostInvalidate.get())
                .put("ownInvalidations",invalidated.get()).put("hostSnapshots",hostSnapshot.get()).put("hostClosed",hostClosed.get())
                .put("ownState",state).put("elapsedRealtimeMillis",android.os.SystemClock.elapsedRealtime()).toString()+"\n")
        }
        fun before(name: String): Pair<Int,Int> {
            instrumentation.waitForIdleSync()
            var result=0 to 0
            instrumentation.runOnMainSync {result=hostInvalidate.get() to invalidated.get();phase(name+"-before")}
            return result
        }
        fun observed(name: String,watermark: Pair<Int,Int>,own: Boolean=true) {
            waitFor(name+" phase invalidation") {hostInvalidate.get()>watermark.first && (!own || invalidated.get()>watermark.second)}
            instrumentation.waitForIdleSync();instrumentation.runOnMainSync {phase(name+"-observed")}
        }
        val observer=object: NativeSocialObserver {
            override fun onInvalidated(){invalidated.incrementAndGet();phase("own-invalidated")}
            override fun onState(state: NativeSocialClient.State){observedState.set(state.name);phase("own-state",state.name)}
        }
        try {
            connection.setSetupAllowed(true);connection.setForeground(true)
            waitFor("fresh own profile") {connection.status().stage==VehicleConnection.Stage.READY}
            connection.start("Synthetic AAR social")
            waitFor("actual product exchange") {connection.status().stage==VehicleConnection.Stage.CONNECTED}
            connection.connectEvents(object: VehicleEventsListener {
                override fun onEvent(event: VehicleEvent) {
                    if(event.type=="snapshot"){hostSnapshot.incrementAndGet();phase("host-snapshot")}
                    if(event.type=="invalidate" && "devices" in event.resources){hostInvalidate.incrementAndGet();phase("host-invalidated")}
                }
                override fun onClosed(){hostClosed.incrementAndGet()}
                override fun onUnavailable(){hostClosed.incrementAndGet()}
            }) {host=it.getOrThrow()}
            waitFor("host owns baseline feed") {host!=null && hostSnapshot.get()==1}
            var current=connection.social();social=current
            receive<Unit> {current.open(observer,it)}.getOrThrow()
            assertEquals(NativeSocialClient.State.READY,current.status())
            val denied=receive<SocialOverview> {current.readOverview(it)}.exceptionOrNull() as NativeSocialFailure
            assertEquals(NativeSocialFailure.Kind.CONSENT_REQUIRED,denied.kind)
            val purposeWatermark=before("purpose")
            mark("purpose-request");waitFor("explicit owner purpose approval") {marked("purpose-done")}
            observed("purpose",purposeWatermark)
            waitFor("known authority invalidation") {current.status()==NativeSocialClient.State.UNAVAILABLE}
            receive<Unit> {current.open(observer,it)}.getOrThrow()
            val overview=receive<SocialOverview> {current.readOverview(it)}.getOrThrow()
            assertEquals(1,overview.friends.size);assertEquals(1,overview.rooms.size)
            val roomId=overview.rooms.single().id
            val room=receive<SocialRoom> {current.readRoom(roomId,it)}.getOrThrow();assertEquals(roomId,room.id)
            val receipt=receive<SocialSignalReceipt> {current.sendStatusSignal(roomId,SocialSignalKind.REST,it)}.getOrThrow()
            val readback=receive<SocialRoom> {current.readRoom(roomId,it)}.getOrThrow();assertTrue(readback.signals.any {it.id==receipt.id && it.destination==null})
            val history=receive<SocialHistoryPage> {current.readHistoryPage(callback=it)}.getOrThrow();assertEquals(1,history.history.size)
            assertNull(history.nextCursor);assertTrue(history.readOnly)
            val duplicate=receive<Unit> {current.open(observer,it)};assertTrue(duplicate.isFailure);assertEquals(NativeSocialClient.State.READY,current.status())
            assertEquals(0,hostClosed.get())
            current.close();assertEquals(NativeSocialClient.State.CLOSED,current.status())
            val bumpWatermark=before("bump");mark("bump-request");waitFor("owner revision bump") {marked("bump-done")}
            observed("bump",bumpWatermark,false);assertEquals(0,hostClosed.get())
            current=connection.social();social=current;receive<Unit> {current.open(observer,it)}.getOrThrow()
            // An old FIRST permission read must not refill the shared gate after main-thread invalidation.
            val oldPermission=AtomicInteger(0)
            mark("permission-request");waitFor("initial permission hold armed") {marked("permission-armed")}
            current.readOverview {oldPermission.incrementAndGet()}
            waitFor("actual initial permission response held") {marked("permission-entered")}
            val permissionWithdrawWatermark=before("permission-withdraw");mark("permission-withdraw-ready")
            waitFor("purpose withdrawn during initial read") {marked("permission-withdrawn")}
            observed("permission-withdraw",permissionWithdrawWatermark)
            waitFor("old permission client invalidated") {current.status()==NativeSocialClient.State.UNAVAILABLE}
            val reopened=AtomicReference<Result<Unit>?>(null)
            current.open(observer) {reopened.set(it)}
            assertEquals(NativeSocialClient.State.OPENING,current.status());mark("permission-reopen-queued")
            waitFor("old permission return and fresh open") {reopened.get()!=null};reopened.get()!!.getOrThrow()
            val noPurpose=receive<SocialOverview> {current.readOverview(it)}.exceptionOrNull() as NativeSocialFailure
            assertEquals(NativeSocialFailure.Kind.CONSENT_REQUIRED,noPurpose.kind)
            assertEquals(NativeSocialClient.State.READY,current.status());assertEquals(0,oldPermission.get());assertEquals(0,hostClosed.get())
            val permissionRestoreWatermark=before("permission-restore")
            mark("permission-restore-request");waitFor("permission restored explicitly") {marked("permission-restored")}
            observed("permission-restore",permissionRestoreWatermark)
            waitFor("both current feeds observe restored purpose") {current.status()==NativeSocialClient.State.UNAVAILABLE}
            receive<Unit> {current.open(observer,it)}.getOrThrow()
            val late=AtomicInteger(0)
            mark("late-request");waitFor("held product read armed") {marked("late-armed")}
            current.readOverview {late.incrementAndGet()}
            waitFor("actual successful product response held") {marked("late-entered")}
            val withdrawWatermark=before("late-withdraw");mark("late-withdraw-ready")
            waitFor("owner withdrawal") {marked("withdraw-done")}
            observed("late-withdraw",withdrawWatermark)
            waitFor("invalidation before delayed data") {current.status()==NativeSocialClient.State.UNAVAILABLE}
            mark("late-release");waitFor("actual response returned") {marked("late-completed")};instrumentation.waitForIdleSync();assertEquals(0,late.get())
            assertEquals(0,hostClosed.get())
            val restoreWatermark=before("restore")
            mark("restore-request");waitFor("explicit owner restores purposes") {marked("restore-done")}
            observed("restore",restoreWatermark,false)
            receive<Unit> {current.open(observer,it)}.getOrThrow()
            assertEquals(1,receive<SocialHistoryPage> {current.readHistoryPage(callback=it)}.getOrThrow().history.size)
            instrumentation.waitForIdleSync();assertEquals(0,late.get());phase("restore-read-complete",current.status().name)
            // A final real successful read is held across explicit logout; it must never deliver.
            mark("logout-request");waitFor("logout hold armed") {marked("logout-armed")}
            current.readOverview {late.incrementAndGet()};waitFor("logout product read held") {marked("logout-entered")}
            before("logout");connection.disconnect();mark("logout-release")
            waitFor("own revoke terminal acknowledgement") {marked("revoke-ack")}
            instrumentation.waitForIdleSync();assertEquals(0,late.get());phase("complete",current.status().name);mark("complete")
        } finally {social?.close();host?.close();connection.close()}
    }
}
