package io.wegoh.app

import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import androidx.activity.compose.setContent
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import io.wegoh.app.ui.LocalVehicleLandingPage
import io.wegoh.app.ui.WegoCarTheme
import io.wegoh.app.ui.WegoVehicleScreen
import android.test.InstrumentationTestCase
import android.test.InstrumentationTestRunner
import io.wegoh.app.nativeauth.NativeDeviceIdentity
import io.wegoh.app.nativeauth.VehicleConnection
import java.io.File
import kotlinx.coroutines.*

@Suppress("DEPRECATION")
class AccountReadRetentionTest: InstrumentationTestCase() {
    private fun main(action: ()->Unit) {
        var failure: Throwable?=null
        instrumentation.runOnMainSync {try {action()}catch(error: Throwable){failure=error}}
        failure?.let {throw it}
    }
    private fun await(label: String,condition: ()->Boolean) {
        val end=android.os.SystemClock.elapsedRealtime()+25000
        while(android.os.SystemClock.elapsedRealtime()<end) {
            var done=false;main {done=condition()};if(done)return;Thread.sleep(50)
        }
        fail("Read retention timeout: $label")
    }
    fun testSuccessfulScreensSurviveDisconnectAndFailedRefresh() {
        val args=(instrumentation as InstrumentationTestRunner).arguments
        val base=instrumentation.targetContext
        val profile="retention_"+java.util.UUID.randomUUID().toString().replace("-","").take(24)
        val dir=File(base.cacheDir,profile).apply {mkdirs()}
        val isolated=object: ContextWrapper(base) {
            override fun getApplicationContext(): Context=this
            override fun getFilesDir()=File(dir,"files").apply {mkdirs()}
            override fun getNoBackupFilesDir()=File(dir,"no-backup").apply {mkdirs()}
            override fun getSharedPreferences(name: String,mode: Int)=base.getSharedPreferences(profile+name,mode)
        }
        val ca=NativeDeviceIdentity.parseCertificates(String(android.util.Base64.decode(args.getString("ca"),android.util.Base64.DEFAULT),Charsets.US_ASCII)).single()
        val connection=VehicleConnection.synthetic(base,profile,args.getString("port")!!.toInt(),ca,args.getString("eventsPort")!!.toInt())
        lateinit var events: AccountEvents
        lateinit var discovery: DiscoveryRepository
        lateinit var courses: CoursesRepository
        lateinit var playlists: PlaylistsRepository
        lateinit var account: ProfileRepository
        val lost=mutableListOf<String>();var track=false
        val collectors=CoroutineScope(SupervisorJob()+Dispatchers.Main.immediate)
        main {
            events=AccountEvents(connection)
            discovery=DiscoveryRepository(connection,events,PackRepository(isolated))
            collectors.launch {discovery.states.collect {if(track && it.status!=AccountReadStatus.READY)lost.add("discovery:${it.status}")}}
            courses=CoursesRepository(connection,PackRepository(isolated),events) {if(track && it.status!=AccountCourseStatus.READY)lost.add("courses:${it.status}")}
            playlists=PlaylistsRepository(connection,events)
            collectors.launch {playlists.states.collect {if(track && it.status!=AccountPlaylistStatus.READY)lost.add("playlists:${it.status}")}}
            account=ProfileRepository(connection,events)
            collectors.launch {account.states.collect {if(track && it.status!=AccountReadStatus.READY)lost.add("profile:${it.status}")}}
            discovery.setForeground(true);discovery.setSetupAllowed(true)
            playlists.setForeground(true);playlists.setSetupAllowed(true)
            account.setForeground(true);account.setSetupAllowed(true)
            courses.setSetupAllowed(true);courses.setForeground(true)
            connection.setSetupAllowed(true);connection.setForeground(true)
        }
        fun marker(name: String)=File(base.cacheDir,name).writeText(args.getString("gpsNonce")!!)
        fun ready()=discovery.state.status==AccountReadStatus.READY && courses.state.status==AccountCourseStatus.READY && playlists.state.status==AccountPlaylistStatus.READY && account.state.status==AccountReadStatus.READY
        var renderer: RetainedRenderer?=null
        try {
            await("ready for synthetic approval") {connection.status().stage==VehicleConnection.Stage.READY}
            connection.start("Synthetic retention",VehicleConnection.Scope.entries.toSet())
            await("connected") {connection.status().stage==VehicleConnection.Stage.CONNECTED}
            main {discovery.request();courses.refresh();playlists.request();account.request()}
            await("four successful screens") {ready()}
            val empty=args.getString("scenario")!!.endsWith("empty")
            if(!empty) {
                main {courses.select(courses.state.courses.single());playlists.select(playlists.state.items.single())}
                await("selected details") {courses.state.selected!=null && playlists.state.selected!=null}
            }
            main {
                courses.setSetupAllowed(false)
                assertTrue(courses.canDisplaySelection());assertFalse(courses.canUse())
                courses.setSetupAllowed(true)
            }
            marker("retention-cache-baseline")
            await("cache baseline acknowledged") {File(base.cacheDir,"retention-cache-baseline-ack").let {if(it.exists())it.readText() else null}==args.getString("gpsNonce")}
            main {repeat(3) {
                val store=androidx.lifecycle.ViewModelStore()
                val model=androidx.lifecycle.ViewModelProvider(store,ProfileViewModel.Factory(account))[ProfileViewModel::class.java]
                assertEquals(account.state.toUiState(),model.uiState.value)
                discovery.request();courses.request();playlists.request();model.load()
                store.clear()
                assertEquals(AccountReadStatus.READY,account.states.value.status)
                if(!empty) {courses.select(courses.state.courses.single());playlists.select(playlists.state.items.single())}
            }}
            Thread.sleep(300)
            marker("retention-cache-checked")
            await("cache reuse acknowledged") {File(base.cacheDir,"retention-cache-checked-ack").let {if(it.exists())it.readText() else null}==args.getString("gpsNonce")}

            marker("retention-force-baseline")
            await("force baseline acknowledged") {File(base.cacheDir,"retention-force-baseline-ack").let {if(it.exists())it.readText() else null}==args.getString("gpsNonce")}
            main {discovery.request(true);courses.request(true);playlists.request(true);ProfileViewModel(account).refresh()}
            await("explicit refresh completes") {ready() && discovery.state.isCurrent && courses.state.isCurrent && playlists.state.isCurrent && account.state.isCurrent}
            marker("retention-force-checked")
            await("force refresh acknowledged") {File(base.cacheDir,"retention-force-checked-ack").let {if(it.exists())it.readText() else null}==args.getString("gpsNonce")}
            if(!empty) {
                main {courses.select(courses.state.courses.single());playlists.select(playlists.state.items.single())}
                await("refreshed details") {courses.state.selected!=null && playlists.state.selected!=null}
            }
            val beforeDiscovery=discovery.state.packs;val beforeCourses=courses.state.courses
            val beforePlaylists=playlists.state.items;val beforeName=account.state.name
            val beforeCourseDetail=courses.state.selected;val beforeMusicDetail=playlists.state.selected
            renderer=RetainedRenderer(isolated,connection,account,courses,playlists,discovery,{
                WegoState(setupAllowed=true,storageReady=true,accountDiscovery=discovery.state,
                    accountCourses=courses.state.copy(selected=null),accountPlaylists=playlists.state,accountProfile=account.state.toUiState())
            },args.getString("scenario")!!)
            main {track=true};marker("retention-offline")
            await("event feed unavailable without discarding cached data") {
                !discovery.state.isCurrent && !courses.state.isCurrent && !playlists.state.isCurrent && !account.state.isCurrent
            }
            assertEquals("A data disconnect is not a session failure",VehicleConnection.Stage.CONNECTED,connection.status().stage)
            Thread.sleep(10000)
            main {
                assertEquals("No error/loading replacement after successful read",emptyList<String>(),lost)
                assertTrue(ready());assertEquals(beforeDiscovery,discovery.state.packs);assertEquals(beforeCourses,courses.state.courses)
                assertEquals(beforePlaylists,playlists.state.items);assertEquals(beforeName,account.state.name)
                assertEquals(beforeCourseDetail,courses.state.selected);assertEquals(beforeMusicDetail,playlists.state.selected)
                assertFalse(courses.canUse());assertFalse(account.state.canEdit)
                beforeMusicDetail?.let {assertNull(playlists.link(it.summary.id,it.summary.revision,it.tracks.single().id))}
            }
            renderer.capture()
            if(args.getString("scenario")!!.endsWith("stale-denial")) {
                val epoch=connection.dataEpoch()
                main {
                    track=false
                    courses.setSetupAllowed(false);playlists.setSetupAllowed(false);discovery.setSetupAllowed(false);account.setSetupAllowed(false)
                    connection.setSetupAllowed(false)
                }
                Thread.sleep(350)
                main {assertTrue("Restriction alone preserves cached reads",ready());assertEquals(beforeCourses,courses.state.courses);assertEquals(beforePlaylists,playlists.state.items)}
                marker("retention-online");connection.check()
                await("restricted account check completes without reloading snapshots") {connection.status().stage==VehicleConnection.Stage.CONNECTED}
                main {
                    assertTrue("Connected NO_SETUP redaction must not erase cached reads",ready())
                    assertFalse(courses.state.isCurrent);assertFalse(playlists.state.isCurrent);assertFalse(discovery.state.isCurrent)
                    assertEquals(beforeDiscovery,discovery.state.packs);assertEquals(beforeCourses,courses.state.courses);assertEquals(beforePlaylists,playlists.state.items)
                }
                marker("retention-denied")
                val denied=java.util.concurrent.atomic.AtomicInteger()
                connection.readCourses {assertTrue(it.exceptionOrNull() is VehicleConnection.ScopeRequired);denied.incrementAndGet()}
                connection.readPlaylists {assertTrue(it.exceptionOrNull() is VehicleConnection.ScopeRequired);denied.incrementAndGet()}
                await("stale restricted denial clears optional snapshots") {
                    denied.get()==2 && courses.state.status==AccountCourseStatus.PERMISSION_REQUIRED &&
                        playlists.state.status==AccountPlaylistStatus.PERMISSION_REQUIRED && discovery.state.status==AccountReadStatus.PERMISSION_REQUIRED
                }
                main {
                    assertEquals("Same account epoch during restricted denial",epoch,connection.dataEpoch())
                    assertEquals("Mandatory profile unaffected by optional denial",beforeName,account.state.name)
                }
            } else {
            marker("retention-online");connection.check()
            await("verified again") {connection.status().stage==VehicleConnection.Stage.CONNECTED}
            main {discovery.request(true);courses.refresh();playlists.request(true);account.request(true)}
            await("fresh screens usable") {ready() && discovery.state.isCurrent && playlists.state.isCurrent && courses.canUse() && account.state.canEdit}
            main {assertTrue(lost.isEmpty());track=false}
            }
            repeat(3) {
                val received=java.util.concurrent.atomic.AtomicInteger()
                val opened=java.util.concurrent.atomic.AtomicReference<java.io.Closeable?>()
                val failure=java.util.concurrent.atomic.AtomicReference<Throwable?>()
                connection.connectEvents(object: io.wegoh.app.nativeauth.VehicleEventsListener {
                    override fun onEvent(event: io.wegoh.app.nativeauth.VehicleEvent) {received.incrementAndGet()}
                    override fun onClosed() {received.incrementAndGet()}
                    override fun onUnavailable() {received.incrementAndGet()}
                }) {it.fold(onSuccess=opened::set,onFailure=failure::set)}
                await("actual TLS close probe opened") {failure.get()!=null || opened.get()!=null && received.get()>0}
                failure.get()?.let {throw it}
                val before=received.get()
                main {opened.get()!!.close();opened.get()!!.close()}
                Thread.sleep(350)
                assertEquals("No callbacks after repeated main-thread close",before,received.get())
            }
            if(!args.getString("scenario")!!.endsWith("stale-denial")) {
            marker("retention-denied")
            main {courses.refresh();playlists.request(true);discovery.request(true)}
            await("explicit scope denial clears optional screens") {
                courses.state.status==AccountCourseStatus.PERMISSION_REQUIRED && playlists.state.status==AccountPlaylistStatus.PERMISSION_REQUIRED && discovery.state.status==AccountReadStatus.PERMISSION_REQUIRED
            }
            }
            main {assertTrue(courses.state.courses.isEmpty());assertTrue(playlists.state.items.isEmpty());assertTrue(discovery.state.packs.isEmpty());assertNull(courses.state.selected);assertNull(playlists.state.selected)}
            var expired=false
            lateinit var expiry: AccountReadSnapshot
            main {
                expiry=AccountReadSnapshot(connection) {expired=true}
                assertFalse("No snapshot does not invalidate initial loading",expiry.invalidated())
                val verified=checkNotNull(connection.verifiedDataBoundary())
                expiry.remember(verified.copy(revision=connection.dataEpoch()+1));assertTrue("Cached epoch mismatch invalidates",expiry.invalidated())
                expiry.remember(verified.copy(storageKey="other:"+verified.storageKey));assertTrue("Cached namespace mismatch invalidates",expiry.invalidated())
                expiry.remember(verified.copy(expiresAtMillis=System.currentTimeMillis()+250))
                assertTrue(expiry.canRetain())
            }
            await("display deadline clears retained snapshot") {expired && !expiry.canRetain()}
            connection.disconnect()
            await("logout clears profile") {account.state.status==AccountReadStatus.CONNECTION_REQUIRED && account.state.name==null}
            await("server received explicit revoke") {File(base.cacheDir,"retention-revoked").let {it.exists() && it.readText()==args.getString("gpsNonce")}}
            renderer.assertLocked()
        } finally {
            renderer?.close()
            main {track=false;collectors.cancel();discovery.close();courses.close();playlists.close();account.close();events.close()};connection.close()
        }
    }
    private inner class RetainedRenderer(context: Context,connection: VehicleConnection,profile: ProfileRepository,courses: CoursesRepository,playlists: PlaylistsRepository,discovery: DiscoveryRepository,
        private val readState: ()->WegoState,private val scenario: String) {
        private val app=instrumentation.targetContext.applicationContext as WegoApplication
        private val field=app.javaClass.getDeclaredField("controller\$delegate").apply {isAccessible=true}
        private val original=field.get(app) as Lazy<*>
        private val wasInitialized=original.isInitialized()
        private lateinit var controller: WegoController
        private val page=mutableStateOf("discover")
        private val rendered=mutableStateOf(readState())
        private val activity: MainActivity
        init {
            main {
                controller=WegoController(context,app)
                controller.javaClass.getDeclaredField("accountConnection").apply {isAccessible=true}.set(controller,connection)
                controller.javaClass.getDeclaredField("profile").apply {isAccessible=true}.set(controller,profile)
                controller.javaClass.getDeclaredField("account").apply {isAccessible=true}.set(controller,courses)
                controller.javaClass.getDeclaredField("playlists").apply {isAccessible=true}.set(controller,playlists)
                controller.javaClass.getDeclaredField("discovery").apply {isAccessible=true}.set(controller,discovery)
                field.set(app,lazyOf(controller))
            }
            activity=instrumentation.startActivitySync(Intent(instrumentation.targetContext,MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
            main {activity.setContent {WegoCarTheme(dark=false) {
                VehicleConnectionPanel(connection,true,manageForeground=false,connectedContent={
                    key(page.value) {CompositionLocalProvider(LocalVehicleLandingPage provides page.value) {
                        WegoVehicleScreen(rendered.value,{},{},{},{},{},{},{},{},{})
                    }}
                })
            }}}
            instrumentation.waitForIdleSync()
            val expected=if(rendered.value.accountDiscovery.packs.isEmpty())"공개 경로가 없어요" else "Synthetic pack"
            val until=android.os.SystemClock.elapsedRealtime()+10000
            fun visible(node: android.view.accessibility.AccessibilityNodeInfo?): Boolean {
                if(node==null)return false
                if(node.isVisibleToUser && node.text?.toString()==expected)return true
                return (0 until node.childCount).any {visible(node.getChild(it))}
            }
            while(android.os.SystemClock.elapsedRealtime()<until && !visible(instrumentation.uiAutomation.rootInActiveWindow))Thread.sleep(100)
            assertTrue("Connected outer panel mounted before disconnect",visible(instrumentation.uiAutomation.rootInActiveWindow))
        }
        fun capture() {
            for(target in listOf("discover","account","music-picker","music","profile")) {
                main {page.value=target;rendered.value=readState()}
                val page=target;val state=rendered.value
                instrumentation.waitForIdleSync();Thread.sleep(300)
                var root: android.view.accessibility.AccessibilityNodeInfo?=null
                val texts=mutableListOf<String>()
                fun inspect(node: android.view.accessibility.AccessibilityNodeInfo?) {
                    if(node==null)return
                    if(node.isVisibleToUser)node.text?.toString()?.let {texts.add(it)}
                    for(i in 0 until node.childCount)inspect(node.getChild(i))
                }
                fun expected()=texts.any {when(page) {
                    "discover"->it=="공개 경로가 없어요" || it=="Synthetic pack"
                    "account"->it=="저장한 경로가 없어요" || it=="Synthetic pack"
                    "music-picker"->it=="저장한 플레이리스트가 없어요" || it=="Synthetic playlist"
                    "music"->it=="저장한 플레이리스트가 없어요" || it=="Synthetic playlist"
                    else->it=="Retained owner"
                }}
                val until=android.os.SystemClock.elapsedRealtime()+10000
                do {
                    if(android.os.Build.VERSION.SDK_INT>=34)instrumentation.uiAutomation.clearCache()
                    root=instrumentation.uiAutomation.rootInActiveWindow;texts.clear();inspect(root)
                    if(expected())break
                    Thread.sleep(100)
                } while(android.os.SystemClock.elapsedRealtime()<until)
                File(instrumentation.targetContext.cacheDir,"$scenario-$page.png").outputStream().use {
                    check(instrumentation.uiAutomation.takeScreenshot().compress(android.graphics.Bitmap.CompressFormat.PNG,100,it))
                }
                assertFalse(texts.any {it.contains("불러올 수 없습니다") || it=="연결을 확인하세요" || it=="연결을 확인해 주세요"})
                assertTrue("Retained body page=$page texts=${texts.take(25)}",expected())
                val action=when(page) {
                    "discover"->state.accountDiscovery.packs.firstOrNull()?.let {"${it.title} v${it.version} 받기"}
                    "account"->state.accountCourses.courses.firstOrNull()?.published?.let {"${it.title} 선택"}
                    "music-picker"->state.accountPlaylists.items.firstOrNull()?.let {"${it.name} 선택"}
                    "music"->state.accountPlaylists.selected?.tracks?.firstOrNull()?.let {"${it.title} 링크 열기"}
                    else->"이름 변경"
                }
                fun find(node: android.view.accessibility.AccessibilityNodeInfo?): android.view.accessibility.AccessibilityNodeInfo? {
                    if(node==null)return null
                    if(node.isVisibleToUser && (node.text?.toString()==action || node.contentDescription?.toString()==action))return node
                    for(i in 0 until node.childCount)find(node.getChild(i))?.let {return it}
                    return null
                }
                if(action!=null) {
                    var node=find(root);assertNotNull("Retained action present: $action",node)
                    var disabled=false
                    repeat(6) {if(node?.isEnabled==false)disabled=true;node=node?.parent}
                    assertTrue("Retained action disabled: $action",disabled)
                }


            }
        }
        fun assertLocked() {
            instrumentation.waitForIdleSync();Thread.sleep(350)
            val root=instrumentation.uiAutomation.rootInActiveWindow
            fun hidden(node: android.view.accessibility.AccessibilityNodeInfo?): Boolean {
                if(node==null)return true
                if(node.isVisibleToUser && node.text?.toString() in setOf("Retained owner","Synthetic pack","Synthetic playlist"))return false
                return (0 until node.childCount).all {hidden(node.getChild(it))}
            }
            assertTrue("Outer connection panel hides retained content after logout",hidden(root))
        }
        fun close() {
            main {activity.finish()}
            await("test host destroyed") {activity.isDestroyed}
            main {controller.close();field.set(app,original)}
            assertEquals("Original account controller initialization preserved",wasInitialized,original.isInitialized())
        }
    }
}
