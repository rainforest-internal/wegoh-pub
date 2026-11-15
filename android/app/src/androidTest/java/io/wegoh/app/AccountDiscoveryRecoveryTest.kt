package io.wegoh.app

import android.content.Context
import android.content.ContextWrapper
import android.test.InstrumentationTestCase
import android.test.InstrumentationTestRunner
import io.wegoh.app.nativeauth.NativeDeviceIdentity
import io.wegoh.app.nativeauth.VehicleConnection
import java.io.File
import kotlinx.coroutines.*

@Suppress("DEPRECATION")
class AccountDiscoveryRecoveryTest: InstrumentationTestCase() {
    @Volatile private var latestStage="initial"
    private fun main(action: ()->Unit)=instrumentation.runOnMainSync(action)
    private fun await(label: String,condition: ()->Boolean) {
        val end=android.os.SystemClock.elapsedRealtime()+25000
        while(android.os.SystemClock.elapsedRealtime()<end) {
            var done=false;main {done=condition()};if(done)return;Thread.sleep(50)
        }
        fail("Catalogue recovery timeout: $label stage=$latestStage")
    }
    fun testEmptyCatalogueRecoversWithoutPollingOrApproval()=runCatalogue()
    fun testLibraryBindsSavedVersionToVerifiedPublicBytes()=runCatalogue(libraryCase=true)
    private fun runCatalogue(libraryCase: Boolean=false) {
        val args=(instrumentation as InstrumentationTestRunner).arguments
        val scenario=args.getString("scenario")!!
        val base=instrumentation.targetContext
        val profile="catalogue_"+java.util.UUID.randomUUID().toString().replace("-","").take(24)
        val dir=File(base.cacheDir,profile).apply {mkdirs()}
        val isolated=object: ContextWrapper(base) {
            override fun getApplicationContext(): Context=this
            override fun getFilesDir()=File(dir,"files").apply {mkdirs()}
            override fun getNoBackupFilesDir()=File(dir,"no-backup").apply {mkdirs()}
            override fun getSharedPreferences(name: String,mode: Int)=base.getSharedPreferences(profile+name,mode)
        }
        val ca=NativeDeviceIdentity.parseCertificates(String(android.util.Base64.decode(args.getString("ca"),android.util.Base64.DEFAULT),Charsets.US_ASCII)).single()
        val connection=VehicleConnection.synthetic(base,profile,args.getString("port")!!.toInt(),ca,args.getString("eventsPort")!!.toInt())
        val observation=connection.observe {latestStage=it.stage.name}
        val packRepository=PackRepository(isolated)
        lateinit var events: AccountEvents
        lateinit var discovery: DiscoveryRepository
        var ready=0
        val collectors=CoroutineScope(SupervisorJob()+Dispatchers.Main.immediate)
        main {
            events=AccountEvents(connection)
            discovery=DiscoveryRepository(connection,events,packRepository)
            collectors.launch {discovery.states.collect {if(it.status==AccountReadStatus.READY && it.isCurrent)ready++}}
            discovery.setForeground(true);discovery.setSetupAllowed(true)
        }
        fun marker(name: String)=File(base.cacheDir,name).writeText(args.getString("gpsNonce")!!)
        try {
            connection.setForeground(true);connection.setSetupAllowed(true)
            await("ready for synthetic approval") {connection.status().stage==VehicleConnection.Stage.READY}
            connection.start("Synthetic catalogue",VehicleConnection.DEFAULT_SCOPES)
            await("connected") {connection.status().stage==VehicleConnection.Stage.CONNECTED}
            main {discovery.request()}
            await("first successful empty list") {discovery.state.status==AccountReadStatus.READY && ready==1}
            if(libraryCase) {
                val library=checkNotNull(discovery.state.library)
                assertEquals("sdk_pack",library.public.single().published.id)
                assertEquals("sdk_pack_2",library.saved.single().published.id)
                assertEquals(1,library.unreadCount);assertFalse(library.news.single().read)
                assertEquals(listOf("바다"),library.followedTags)
                val selected=library.saved.single().published
                var loaded: DrivePack?=null
                main {discovery.download(selected,{true}) {loaded=it}}
                await("current saved course matches verified public bytes") {
                    discovery.state.verifiedSelection==selected && loaded!=null
                }
                assertEquals(selected.key,checkNotNull(loaded).key)
                assertEquals(selected.checksum,packRepository.verifiedOrigin(checkNotNull(loaded))?.checksum)
                assertEquals(listOf("sdk_pack"),discovery.state.packs.map {it.id})
                main {discovery.setForeground(false);discovery.setSetupAllowed(false)}
                marker("recovery-close");marker("recovery-completed")
                return
            }
            assertTrue(discovery.state.packs.isEmpty())
            Thread.sleep(2200)
            assertEquals(1,ready)
            marker("recovery-close")
            when {
                scenario.endsWith("background") || scenario.endsWith("restricted") || scenario.endsWith("logout") -> {
                    await("retry scheduled") {!discovery.state.isCurrent}
                    when {
                        scenario.endsWith("background") -> {main {discovery.setForeground(false)};connection.setForeground(false)}
                        scenario.endsWith("restricted") -> main {discovery.setSetupAllowed(false)}
                        else -> connection.disconnect()
                    }
                    Thread.sleep(2500)
                    assertEquals(1,ready)
                    if(scenario.endsWith("logout")) {
                        await("terminal logout") {connection.status().stage==VehicleConnection.Stage.LOCKED}
                    } else {
                        if(scenario.endsWith("background")) {
                            connection.setForeground(true);await("foreground verified") {connection.status().stage==VehicleConnection.Stage.CONNECTED}
                        }
                        main {discovery.setForeground(true);discovery.setSetupAllowed(true);discovery.request()}
                        await("single explicit resume") {ready==2 && discovery.state.status==AccountReadStatus.READY}
                    }
                }
                scenario.endsWith("denied") -> {
                    await("permission denial stops retry") {discovery.state.status==AccountReadStatus.PERMISSION_REQUIRED}
                    Thread.sleep(2500);assertEquals(1,ready)
                }
                scenario.endsWith("offline") || scenario.endsWith("flap") -> {
                    Thread.sleep(14000);assertEquals(AccountReadStatus.READY,discovery.state.status);assertFalse(discovery.state.isCurrent)
                    Thread.sleep(2500);assertEquals(1,ready)
                }
                else -> {
                    await("automatic fresh empty list after server closes stream") {ready==2 && discovery.state.status==AccountReadStatus.READY}
                    assertTrue(discovery.state.packs.isEmpty())
                    assertEquals(VehicleConnection.Stage.CONNECTED,connection.status().stage)
                }
            }
            marker("recovery-completed")
        } finally {
            main {collectors.cancel();discovery.close();events.close()};observation.close();connection.close()
        }
    }
}
