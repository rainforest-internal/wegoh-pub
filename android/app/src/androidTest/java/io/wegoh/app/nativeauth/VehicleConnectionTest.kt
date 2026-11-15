package io.wegoh.app.nativeauth

import android.test.InstrumentationTestCase
import android.test.InstrumentationTestRunner
import android.util.Base64
import org.json.JSONObject
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.io.File

/** Isolated synthetic CA/phone. No product profile, live account or VHAL changes. */
class VehicleConnectionTest : InstrumentationTestCase() {
    private fun waitFor(label: String, predicate: ()->Boolean) {
        val end=android.os.SystemClock.elapsedRealtime()+20000
        while(android.os.SystemClock.elapsedRealtime()<end) {if(predicate())return;Thread.sleep(20)}
        fail("Synthetic manager state timeout: $label")
    }
    fun testRetryShowsPendingProgressWithoutDuplicateRequest() {
        val args=(instrumentation as InstrumentationTestRunner).arguments
        val port=args.getString("port")!!.toInt()
        val ca=NativeDeviceIdentity.parseCertificates(String(Base64.decode(args.getString("ca"),Base64.DEFAULT),Charsets.US_ASCII)).single()
        val context=instrumentation.targetContext
        val profile="retry_test_"+java.util.UUID.randomUUID().toString().replace("-","").take(24)
        val connection=VehicleConnection.synthetic(context,profile,port,ca)
        val store=NativeConnectionState(context,profile)
        val entered=File(context.cacheDir,"connection-retry-entered")
        val release=File(context.cacheDir,"connection-retry-release")
        val nonce=args.getString("gpsNonce")!!
        try {
            connection.start("Synthetic background attempt")
            assertEquals(VehicleConnection.Stage.SETUP_BLOCKED,connection.status().stage)
            connection.setForeground(true)
            connection.start("Synthetic restricted attempt")
            assertEquals(VehicleConnection.Stage.SETUP_BLOCKED,connection.status().stage)
            connection.setSetupAllowed(true)
            connection.start("Synthetic retry")
            waitFor("first request failure") {connection.status().stage==VehicleConnection.Stage.RECOVERY_REQUIRED}
            val workerField=VehicleConnection::class.java.getDeclaredField("worker").apply {isAccessible=true}
            val worker=workerField.get(connection) as java.util.concurrent.ExecutorService
            worker.submit {}.get(5,TimeUnit.SECONDS)
            val initial=store.read()
            val installation=initial.getString("installationId")
            val key=NativeDeviceIdentity(context,installation).installationKeyId()
            val original=initial.getJSONObject("access").getJSONObject("authorization").getJSONObject("request").toString()
            assertFalse(initial.getJSONObject("access").has("credentials"))
            connection.start("Synthetic retry")
            waitFor("second request reached the delayed peer") {entered.exists() && entered.readText()==nonce}
            assertEquals("Retry must replace the old error while its real request is pending",VehicleConnection.Stage.CONNECTING,connection.status().stage)
            connection.start("Synthetic duplicate retry")
            connection.start("Synthetic duplicate retry")
            release.writeText(nonce)
            waitFor("second response returns to recoverable failure") {connection.status().stage==VehicleConnection.Stage.RECOVERY_REQUIRED}
            worker.submit {}.get(5,TimeUnit.SECONDS)
            val final=store.read()
            assertEquals(installation,final.getString("installationId"))
            assertEquals(key,NativeDeviceIdentity(context,installation).installationKeyId())
            assertEquals(original,final.getJSONObject("access").getJSONObject("authorization").getJSONObject("request").toString())
            assertFalse(final.getJSONObject("access").has("credentials"))
            assertEquals(VehicleConnection.Stage.RECOVERY_REQUIRED,connection.status().stage)
            connection.close()
            connection.start("Synthetic closed attempt")
        } finally {
            release.writeText(nonce)
            connection.close()
        }
    }

    fun testSingleApprovalRecoveryRememberAndImmediateLogout() {
        val args=(instrumentation as InstrumentationTestRunner).arguments
        val port=args.getString("port")!!.toInt()
        val eventsPort=args.getString("eventsPort")?.toInt()
        val ca=NativeDeviceIdentity.parseCertificates(String(Base64.decode(args.getString("ca"),Base64.DEFAULT),Charsets.US_ASCII)).single()
        val profile="connection_test_"+java.util.UUID.randomUUID().toString().replace("-","").take(24)
        val context=instrumentation.targetContext
        var connection=VehicleConnection.synthetic(context,profile,port,ca,eventsPort)
        val phases=java.util.Collections.synchronizedList(mutableListOf<VehicleConnection.Stage>())
        var observation=connection.observe {phases.add(it.stage)}
        try {
            connection.setForeground(true);connection.setSetupAllowed(false)
            connection.start("Synthetic remembered")
            Thread.sleep(100);assertEquals(VehicleConnection.Stage.SETUP_BLOCKED,connection.status().stage)
            try {VehicleConnection.synthetic(context,profile,port,ca,eventsPort);fail("Second owner accepted")}catch(expected: IllegalStateException){}
            connection.setSetupAllowed(true)
            connection.start("Synthetic remembered",setOf(VehicleConnection.Scope.COURSES,VehicleConnection.Scope.PLAYLISTS))
            waitFor("public QR") {connection.status().stage==VehicleConnection.Stage.APPROVAL_REQUIRED}
            val public=connection.status();assertEquals("ABCD2345",public.userCode)
            assertEquals("https://wegoh.devforest.io/enroll.html?user_code=ABCD2345",public.verificationUri)
            assertFalse(public.toString().contains("ABCD2345"))
            if(args.getString("scenario")=="exchange-loss-logout") {
                waitFor("unconfirmed first exchange") {connection.status().stage==VehicleConnection.Stage.RECOVERY_REQUIRED}
                val pendingStore=NativeConnectionState(context,profile)
                val pending=pendingStore.read().getJSONObject("access").getJSONObject("authorization")
                assertTrue(pending.getJSONObject("response").has("grantId"));assertFalse(pendingStore.read().getJSONObject("access").has("credentials"))
                connection.disconnect()
                waitFor("grant-only ack without credential recovery") {
                    val value=pendingStore.read().getJSONObject("access")
                    !value.has("authorization")&&!value.has("credentials")&&value.getJSONArray("outbox").length()==0
                }
                assertEquals(VehicleConnection.Stage.LOCKED,connection.status().stage)
                return
            }
            waitFor("connected") {connection.status().stage==VehicleConnection.Stage.CONNECTED}
            val store=NativeConnectionState(context,profile)
            if(args.getString("scenario")!!.startsWith("revoke-")) {
                val before=store.read().getJSONObject("access")
                assertFalse(before.getBoolean("keepSignedIn"))
                val credential=before.getJSONObject("credentials")
                observation.close();connection.close()
                connection=VehicleConnection.synthetic(context,profile,port,ca,eventsPort)
                observation=connection.observe {phases.add(it.stage)}
                connection.setSetupAllowed(true);connection.setForeground(true)
                val attempted=File(context.cacheDir,"revocation-attempted")
                waitFor("server committed revoke without a usable ack") {
                    attempted.exists() && attempted.readText()==args.getString("gpsNonce") &&
                        connection.status().stage==VehicleConnection.Stage.REMOTE_REVOCATION_PENDING
                }
                val locked=store.read().getJSONObject("access")
                assertFalse(locked.has("credentials"));assertEquals(1,locked.getJSONArray("outbox").length())
                val request=locked.getJSONArray("outbox").getJSONObject(0).getJSONObject("request").toString()
                VehicleConnection.validateLateReceipt(credential,locked.getJSONArray("outbox"),
                    credential.getString("installationKeyId"),credential.getString("certificateSha256"))
                observation.close();connection.close()
                connection=VehicleConnection.synthetic(context,profile,port,ca,eventsPort)
                observation=connection.observe {phases.add(it.stage)}
                connection.setSetupAllowed(true);connection.setForeground(true)
                connection.start("Synthetic reconnect while revoke pending")
                waitFor("fresh QR despite unconfirmed old revoke") {
                    connection.status().stage==VehicleConnection.Stage.APPROVAL_REQUIRED && connection.status().userCode=="EFGH2345"
                }
                val pending=store.read().getJSONObject("access")
                assertEquals(request,pending.getJSONArray("outbox").getJSONObject(0).getJSONObject("request").toString())
                assertFalse(pending.has("credentials"))
                File(context.cacheDir,"revocation-confirm").writeText(args.getString("gpsNonce")!!)
                connection.check()
                waitFor("already revoked exact-grant acknowledgement clears outbox") {
                    store.read().getJSONObject("access").getJSONArray("outbox").length()==0
                }
                val confirmed=store.read().getJSONObject("access")
                assertFalse(confirmed.has("credentials"));assertTrue(confirmed.has("authorization"))
                assertEquals(VehicleConnection.Stage.APPROVAL_REQUIRED,connection.status().stage)
                return
            }
            if(args.getString("scenario")!!.startsWith("read-methods")) {
                fun <T> receive(call: ((Result<T>)->Unit)->Unit): Result<T> {
                    val output=java.util.concurrent.atomic.AtomicReference<Result<T>?>(null)
                    call {output.set(it)};waitFor("typed read callback") {output.get()!=null};return output.get()!!
                }
                if(args.getString("scenario")=="read-methods-invalid-name") {
                    val result=receive<String> {connection.readAccountDisplayName(it)}
                    assertTrue(result.isFailure);assertEquals("NATIVE_DATA_UNAVAILABLE",result.exceptionOrNull()!!.message)
                    return
                }
                val own=receive<NativeApiClient.Document> {connection.readCourses(it)}.getOrThrow().asObject().getJSONArray("packs")
                assertEquals(1000,own.length());assertEquals(500,own.getJSONObject(999).getString("description").length)
                val catalogue=receive<NativeApiClient.Document> {connection.readPublicPacks(it)}.getOrThrow().asObject().getJSONArray("packs")
                assertEquals("sdk_pack",catalogue.getJSONObject(0).getString("id"))
                val pack=receive<NativeApiClient.PackVersion> {connection.readPackVersion("sdk_pack",1,it)}.getOrThrow()
                assertEquals("sdk_pack",pack.id);assertEquals(1,pack.version)
                val bytes=pack.bytes();assertTrue(bytes.size>65536 && bytes.size<=262144)
                val digest=java.security.MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") {"%02x".format(it.toInt() and 255)}
                assertEquals(args.getString("expectedPackSha256"),digest)
                bytes[0]=42;assertEquals(32,pack.bytes()[0].toInt())
                assertTrue(receive<NativeApiClient.PackVersion> {connection.readPackVersion("too_large",1,it)}.isFailure)
                val playlist=receive<NativeApiClient.Document> {connection.readPlaylist("a".repeat(32),it)}.getOrThrow().asObject()
                assertEquals(1,playlist.getJSONArray("tracks").length())
                assertEquals(1,receive<NativeApiClient.Document> {connection.readPlaylists(it)}.getOrThrow().asObject().getJSONArray("playlists").length())
                assertEquals(String(Character.toChars(0x1f600)).repeat(64),receive<String> {connection.readAccountDisplayName(it)}.getOrThrow())
                val permission=receive<VehicleConnection.Permissions> {connection.readPermissions(it)}.getOrThrow()
                assertEquals(VehicleConnection.DEFAULT_SCOPES,permission.approvedOptionalScopes);assertTrue(permission.keepSignedIn)
                assertEquals(1L,permission.consentVersion);assertTrue(permission.grantExpiresAtMillis>System.currentTimeMillis())
                try {(permission.approvedOptionalScopes as MutableSet<VehicleConnection.Scope>).clear();fail("Mutable permission projection")}
                catch(expected: UnsupportedOperationException) {}
                return
            }
            if(args.getString("scenario")!!.startsWith("scope-upgrade")) {
                assertEquals(VehicleConnection.DEFAULT_SCOPES,connection.status().approvedOptionalScopes)
                val denied=java.util.concurrent.atomic.AtomicReference<Throwable?>()
                connection.readCourses {denied.set(it.exceptionOrNull())}
                waitFor("typed server scope denial") {denied.get()!=null}
                assertTrue(denied.get() is VehicleConnection.ScopeRequired)
                val oldGrant=store.read().getJSONObject("access").getJSONObject("credentials").getString("grantId")
                assertEquals(setOf(VehicleConnection.Scope.COURSES),connection.status().deniedOptionalScopes)
                connection.requestScopes("Synthetic scope approval",setOf(VehicleConnection.Scope.COURSES,VehicleConnection.Scope.ACCOUNT_WRITE))
                waitFor("fresh scope QR") {connection.status().userCode=="EFGH2345"}
                val firstScopeDeadline=connection.status().expiresAtMillis
                assertTrue(connection.status().approvedOptionalScopes.isEmpty())
                assertEquals(oldGrant,store.read().getJSONObject("access").getJSONObject("credentials").getString("grantId"))
                observation.close();connection.close()
                connection=VehicleConnection.synthetic(context,profile,port,ca,eventsPort)
                observation=connection.observe {phases.add(it.stage)}
                connection.setSetupAllowed(true);connection.setForeground(true)
                waitFor("pending approval survives restart without restoring old account") {
                    connection.status().userCode=="EFGH2345"
                }
                assertTrue(connection.status().approvedOptionalScopes.isEmpty())
                if(args.getString("scenario")=="scope-upgrade-expiry") {
                    waitFor("stable repeated pending then authoritative expiry") {
                        val current=connection.status()
                        if(current.userCode=="EFGH2345")assertEquals("Same code keeps its initial projected deadline across pending polls/restart",firstScopeDeadline,current.expiresAtMillis)
                        current.stage==VehicleConnection.Stage.EXPIRED
                    }
                    connection.start("Synthetic explicit expiry retry",VehicleConnection.Scope.entries.toSet())
                    waitFor("new QR after explicit retry") {connection.status().userCode=="JKLM2345"}
                    assertTrue("Fresh code resets deadline",connection.status().expiresAtMillis!!>firstScopeDeadline!!)
                }
                waitFor("new partial phone approval") {connection.status().stage==VehicleConnection.Stage.CONNECTED}
                assertEquals(setOf(VehicleConnection.Scope.PLAYLISTS,VehicleConnection.Scope.ACCOUNT_WRITE),connection.status().approvedOptionalScopes)
                assertFalse(oldGrant==store.read().getJSONObject("access").getJSONObject("credentials").getString("grantId"))
                val playlist=AtomicInteger(0);connection.readPlaylists {it.getOrThrow();playlist.incrementAndGet()}
                waitFor("permitted playlist read") {playlist.get()==1}
                denied.set(null);connection.readCourses {denied.set(it.exceptionOrNull())}
                waitFor("local missing scope") {denied.get()!=null}
                assertTrue(denied.get() is VehicleConnection.ScopeRequired)
                connection.setForeground(false);assertTrue(connection.status().approvedOptionalScopes.isEmpty())
                return
            }
            val renewed=store.read().getJSONObject("access")
            assertEquals(2L,renewed.getJSONObject("credentials").getLong("generation"))
            assertEquals(2L,renewed.getJSONObject("credentials").getLong("credentialEpoch"))
            assertFalse(renewed.has("renewal"))
            val installation=store.read().getString("installationId")
            val keyId=NativeDeviceIdentity(context,installation).installationKeyId()
            observation.close();connection.close()
            // Simulate only this newly-created synthetic public certificate file loss.
            val certificate=File(context.noBackupFilesDir,"wegoh.native.$installation.chain.pem")
            assertTrue(certificate.exists());assertTrue(certificate.delete())
            connection=VehicleConnection.synthetic(context,profile,port,ca,eventsPort)
            observation=connection.observe {phases.add(it.stage)}
            connection.setSetupAllowed(true);connection.setForeground(true)
            waitFor("same-key certificate + remembered cold restore") {connection.status().stage==VehicleConnection.Stage.CONNECTED}
            assertEquals(keyId,NativeDeviceIdentity(context,installation).installationKeyId())
            assertTrue(certificate.exists())
            val opened=AtomicInteger(0);val events=AtomicInteger(0);val unavailable=AtomicInteger(0)
            val handle=java.util.concurrent.atomic.AtomicReference<java.io.Closeable?>()
            connection.connectEvents(object: VehicleEventsListener {
                override fun onOpen(){opened.incrementAndGet()}
                override fun onEvent(event: VehicleEvent){assertTrue(event.type in setOf("snapshot","invalidate"));events.incrementAndGet()}
                override fun onUnavailable(){unavailable.incrementAndGet()}
            }) {result->handle.set(result.getOrThrow())}
            waitFor("actual101 and WSS receive") {opened.get()==1 && events.get()==2 && handle.get()!=null}
            assertEquals(0,unavailable.get())
            if(args.getString("scenario")=="terminal-reauthorize") {
                val terminalCallbacks=AtomicInteger(0)
                connection.readCourses {terminalCallbacks.incrementAndGet()}
                waitFor("authority terminal locks credentials") {connection.status().stage==VehicleConnection.Stage.DENIED && !store.read().getJSONObject("access").has("credentials")}
                assertTrue(store.read().getJSONObject("access").getJSONArray("outbox").length()>0)
                assertEquals(0,terminalCallbacks.get())
                connection.start("Synthetic explicit reconnect")
                waitFor("explicit fresh phone same key") {connection.status().stage==VehicleConnection.Stage.APPROVAL_REQUIRED && connection.status().userCode=="EFGH2345"}
                assertEquals(keyId,NativeDeviceIdentity(context,installation).installationKeyId())
                assertFalse(store.read().getJSONObject("access").has("credentials"))
                return
            }
            val entered=CountDownLatch(1);val release=CountDownLatch(1);val pendingClosed=AtomicInteger(0)
            val pendingResult=java.util.concurrent.atomic.AtomicReference<Result<java.io.Closeable>?>()
            connection.connectEvents(NativeApiClient.EventsConnector {_,_,_,_->
                entered.countDown();check(release.await(5,TimeUnit.SECONDS));java.io.Closeable {pendingClosed.incrementAndGet()}
            }) {pendingResult.set(it)}
            assertTrue(entered.await(5,TimeUnit.SECONDS))
            connection.setForeground(false);connection.setForeground(true);release.countDown()
            waitFor("pending socket canceled after foreground roundtrip") {pendingClosed.get()==1}
            Thread.sleep(100);assertNull(pendingResult.get())
            val callbacks=AtomicInteger(0)
            connection.readCourses {callbacks.incrementAndGet()}
            // Fixture deliberately holds the read for2s; host asserts that the
            // request really reached it before revocation, not a canceled fake IO.
            Thread.sleep(500)
            val start=android.os.SystemClock.elapsedRealtime();connection.disconnect()
            assertTrue(android.os.SystemClock.elapsedRealtime()-start<250)
            assertEquals(VehicleConnection.Stage.LOCKED,connection.status().stage)
            waitFor("durable local privacy lock") {!store.read().getJSONObject("access").has("credentials")}
            Thread.sleep(2300);assertEquals(0,callbacks.get());assertEquals(2,events.get())
            waitFor("revoke receipt") {store.read().getJSONObject("access").getJSONArray("outbox").length()==0}
            assertFalse(store.read().getJSONObject("access").has("credentials"))
            assertTrue(phases.contains(VehicleConnection.Stage.APPROVAL_REQUIRED))
            assertTrue(phases.contains(VehicleConnection.Stage.CONNECTED))
        }finally{observation.close();connection.close()}
    }
}
