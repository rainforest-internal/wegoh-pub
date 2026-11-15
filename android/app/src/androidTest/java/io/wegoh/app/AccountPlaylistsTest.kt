package io.wegoh.app

import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.test.InstrumentationTestRunner
import io.wegoh.app.nativeauth.NativeDeviceIdentity
import io.wegoh.app.nativeauth.VehicleConnection
import java.io.File
import org.json.JSONObject
import org.json.JSONArray
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.key
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import io.wegoh.app.ui.LocalVehicleLandingPage
import io.wegoh.app.ui.WegoCarTheme
import io.wegoh.app.ui.WegoVehicleScreen

@Suppress("DEPRECATION")
class AccountPlaylistsTest: FirstRunPermissionsCompletedTestCase() {
    private fun onMain(action: ()->Unit)=instrumentation.runOnMainSync(action)
    private fun waitFor(label: String,onUi: Boolean=true,condition: ()->Boolean) {
        val end=android.os.SystemClock.elapsedRealtime()+25000
        while(android.os.SystemClock.elapsedRealtime()<end) {
            var done=false;if(onUi)onMain {done=condition()} else done=condition()
            if(done)return;Thread.sleep(100)
        }
        fail("Playlist fixture timeout: $label")
    }
    private fun node(label: String): android.view.accessibility.AccessibilityNodeInfo? {
        if(android.os.Build.VERSION.SDK_INT>=34)instrumentation.uiAutomation.clearCache()
        fun find(item: android.view.accessibility.AccessibilityNodeInfo?): android.view.accessibility.AccessibilityNodeInfo? {
            if(item==null)return null
            if(item.isVisibleToUser && (item.text?.toString()==label || item.contentDescription?.toString()==label))return item
            for(i in 0 until item.childCount)find(item.getChild(i))?.let {return it}
            return null
        }
        return find(instrumentation.uiAutomation.rootInActiveWindow)
    }
    private fun click(label: String) {
        waitFor("visible $label",false) {node(label)!=null}
        var target=node(label)
        repeat(5) {
            if(target?.performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_CLICK)==true)return
            target=target?.parent
        }
        fail("Playlist action unavailable: $label")
    }
    private fun capture(name: String) {
        instrumentation.waitForIdleSync();Thread.sleep(350)
        File(instrumentation.targetContext.cacheDir,name+".png").outputStream().use {
            check(instrumentation.uiAutomation.takeScreenshot().compress(android.graphics.Bitmap.CompressFormat.PNG,100,it))
        }
    }
    fun testActualPlaylistRendererScopeAndInvalidation() {
        val args=(instrumentation as InstrumentationTestRunner).arguments
        val scenario=args.getString("scenario")!!
        val base=instrumentation.targetContext
        val profile="playlist_"+java.util.UUID.randomUUID().toString().replace("-","").take(24)
        val dir=File(base.cacheDir,profile).apply {mkdirs()}
        val isolated=object: ContextWrapper(base) {
            override fun getApplicationContext(): Context=this
            override fun getFilesDir()=File(dir,"files").apply {mkdirs()}
            override fun getNoBackupFilesDir()=File(dir,"no-backup").apply {mkdirs()}
            override fun getSharedPreferences(name: String,mode: Int)=base.getSharedPreferences(profile+name,mode)
            override fun deleteSharedPreferences(name: String)=base.deleteSharedPreferences(profile+name)
        }
        val ca=NativeDeviceIdentity.parseCertificates(String(android.util.Base64.decode(args.getString("ca"),android.util.Base64.DEFAULT),Charsets.US_ASCII)).single()
        val connection=VehicleConnection.synthetic(base,profile,args.getString("port")!!.toInt(),ca,args.getString("eventsPort")!!.toInt())
        if(scenario=="account-playlists-feed") {
            try {runFeedCase(connection,base,profile,args)}finally {connection.close()}
            return
        }
        val app=base.applicationContext as WegoApplication
        val delegate=app.javaClass.getDeclaredField("controller\$delegate").apply {isAccessible=true}
        val original=delegate.get(app) as Lazy<*>
        val initialized=original.isInitialized()
        lateinit var controller: WegoController
        onMain {controller=WegoController(isolated,base.applicationContext);controller.connectAccount(connection);controller.setAppForeground(true);delegate.set(app,lazyOf(controller))}
        var activity: MainActivity?=null
        val monitor=instrumentation.addMonitor(IntentFilterForHttps(),android.app.Instrumentation.ActivityResult(android.app.Activity.RESULT_CANCELED,null),true)
        try {
            activity=instrumentation.startActivitySync(Intent(base,MainActivity::class.java).putExtra("screen","journeys")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
            val host=activity
            waitFor("actual Main ready") {controller.state.setupAllowed && controller.state.storageReady && host.hasWindowFocus() && connection.status().stage==VehicleConnection.Stage.READY}
            val scopes=when(scenario) {
                "account-playlists-only"->setOf(VehicleConnection.Scope.PLAYLISTS)
                "account-playlists-denied"->setOf(VehicleConnection.Scope.COURSES)
                else->VehicleConnection.Scope.entries.toSet()
            }
            connection.start("Synthetic playlists",scopes)
            waitFor("verified connection") {connection.status().stage==VehicleConnection.Stage.CONNECTED}
            click("더보기");click("내 음악")
            if(scenario.endsWith("denied")) {
                waitFor("music scope denied") {controller.state.accountPlaylists.status==AccountPlaylistStatus.PERMISSION_REQUIRED}
                waitFor("permission renderer",false) {node("음악 권한이 필요합니다")!=null};capture(scenario)
                assertNull(controller.playlistLink("a".repeat(32),1,"b".repeat(32)))
            } else {
                waitFor("actual playlist list") {controller.state.accountPlaylists.status==AccountPlaylistStatus.READY && controller.state.accountPlaylists.items.size==1}
                if(scenario.endsWith("only"))assertEquals(AccountCourseStatus.CONNECTION_REQUIRED,controller.state.accountCourses.status)
                click("음악 고르기");capture(scenario+"-list")
                click("Synthetic playlist 1 선택")
                waitFor("actual playlist detail") {controller.state.accountPlaylists.selected?.summary?.revision==1L}
                waitFor("detail renderer",false) {node("Synthetic track")!=null};capture(scenario+"-detail")
                val detail=controller.state.accountPlaylists.selected!!
                val id=detail.summary.id;val track=detail.tracks.single().id
                assertEquals("https://example.test/track?source=original",controller.playlistLink(id,1,track))
                click("Synthetic track 링크 열기")
                waitFor("actual HTTPS ACTION_VIEW intercepted",false) {monitor.hits==1}
                assertEquals(1,monitor.hits)
                assertNull(controller.playlistLink(id,2,track));assertNull(controller.playlistLink("c".repeat(32),1,track))
                val field=controller.javaClass.getDeclaredField("playlists").apply {isAccessible=true}
                val model=field.get(controller) as PlaylistsRepository
                onMain {model.setSetupAllowed(false)};assertNull(controller.playlistLink(id,1,track));onMain {model.setSetupAllowed(true)}
                if(!scenario.endsWith("only")) {
                    File(base.cacheDir,"playlist-check").writeText(args.getString("gpsNonce")!!)
                    connection.check()
                    waitFor("invalidation during routine check reloaded both modules") {connection.status().stage==VehicleConnection.Stage.CONNECTED &&
                        controller.state.accountPlaylists.items.singleOrNull()?.name=="Synthetic playlist 2" && controller.state.accountCourses.status==AccountCourseStatus.READY}
                    assertNull(controller.state.accountPlaylists.selected);assertNull(controller.playlistLink(id,1,track))
                    click("음악 고르기");click("Synthetic playlist 2 선택")
                    waitFor("updated detail") {controller.state.accountPlaylists.selected?.summary?.revision==2L}
                    File(base.cacheDir,"playlist-close").writeText(args.getString("gpsNonce")!!)
                    waitFor("WSS close retains both views with actions locked") {controller.state.accountPlaylists.status==AccountPlaylistStatus.READY && !controller.state.accountPlaylists.isCurrent && controller.state.accountCourses.status==AccountCourseStatus.READY && !controller.state.accountCourses.isCurrent}
                    Thread.sleep(700);assertFalse(controller.state.accountPlaylists.items.isEmpty());assertNull(controller.playlistLink(id,2,track))
                    capture("account-playlists-unavailable")
                    click("새로고침")
                    waitFor("explicit reload") {controller.state.accountPlaylists.status==AccountPlaylistStatus.READY && controller.state.accountPlaylists.isCurrent}
                    File(base.cacheDir,"playlist-account-failure").writeText(args.getString("gpsNonce")!!)
                    val failedRead=java.util.concurrent.atomic.AtomicBoolean(false)
                    connection.check()
                    connection.readPlaylists {assertTrue(it.isFailure);failedRead.set(true)}
                    waitFor("queued failed verification retains playlist with actions locked") {failedRead.get() && controller.state.accountPlaylists.status==AccountPlaylistStatus.READY && !controller.state.accountPlaylists.isCurrent &&
                        connection.status().stage in setOf(VehicleConnection.Stage.RECOVERY_REQUIRED,VehicleConnection.Stage.UNAVAILABLE)}
                    assertFalse(controller.state.accountPlaylists.items.isEmpty())
                }
                onMain {host.startActivity(base.packageManager.getLaunchIntentForPackage("ai.umos.maps.android.navigation.app") ?: error("OEM navigation missing"))}
                waitFor("actual OEM foreground retains read-only music") {!host.lifecycle.currentState.isAtLeast(androidx.lifecycle.Lifecycle.State.RESUMED) && !controller.state.accountPlaylists.isCurrent && controller.state.accountPlaylists.items.isNotEmpty()}
                assertNull(controller.playlistLink(id,1,track))
            }
            connection.disconnect()
            waitFor("logout") {connection.status().stage==VehicleConnection.Stage.LOCKED}
            val store=io.wegoh.app.nativeauth.NativeConnectionState(base,profile)
            waitFor("remote logout receipt",false) {store.locked {val saved=store.read().getJSONObject("access");!saved.has("credentials") && saved.getJSONArray("outbox").length()==0}}
            if(scenario=="account-playlists") {parserBoundaries();renderLayouts(host)}
            File(base.cacheDir,scenario+"-runtime.json").writeText(JSONObject().put("synthetic",true).put("actualMainRenderer",true)
                .put("scenario",scenario).put("httpsViewIntentsIntercepted",monitor.hits).put("originalControllerLazyUnchanged",original.isInitialized()==initialized)
                .put("limits","Synthetic phone/API with actual TLS1.3/mTLS/WSS and Main. HTTPS intent intercepted; no external playback, real account or release approval.").toString(2))
        } catch(failure: Throwable) {
            File(base.cacheDir,scenario+"-failure-runtime.json").writeText(JSONObject().put("synthetic",true)
                .put("lifecycle",activity?.lifecycle?.currentState?.name).put("focused",activity?.hasWindowFocus())
                .put("windowVisibility",activity?.window?.decorView?.windowVisibility).put("playlistStatus",controller.state.accountPlaylists.status.name)
                .put("playlistCount",controller.state.accountPlaylists.items.size).put("connectionStage",connection.status().stage.name).toString(2))
            runCatching {capture(scenario+"-failure")};throw failure
        }
        finally {
            instrumentation.removeMonitor(monitor)
            try {onMain {controller.close();activity?.finish()};if(activity!=null)waitFor("isolated Main destroyed") {activity!!.isDestroyed}}
            finally {onMain {delegate.set(app,original)};connection.close()}
            assertEquals("Original controller lazy preserved",initialized,original.isInitialized())
        }
    }
    private fun IntentFilterForHttps()=android.content.IntentFilter(Intent.ACTION_VIEW).apply {
        addCategory(Intent.CATEGORY_BROWSABLE);addCategory(Intent.CATEGORY_DEFAULT);addDataScheme("https")
    }
    private fun runFeedCase(connection: VehicleConnection,base: Context,profile: String,args: android.os.Bundle) {
        connection.setSetupAllowed(true);connection.setForeground(true)
        waitFor("feed ready") {connection.status().stage==VehicleConnection.Stage.READY}
        connection.start("Synthetic feed",VehicleConnection.Scope.entries.toSet())
        waitFor("feed verified") {connection.status().stage==VehicleConnection.Stage.CONNECTED}
        lateinit var hub: AccountEvents
        lateinit var first: java.io.Closeable
        lateinit var second: java.io.Closeable
        var opened=0;var events=0;var retired=0
        val same=object: io.wegoh.app.nativeauth.VehicleEventsListener {
            override fun onOpen() {opened++}
            override fun onEvent(event: io.wegoh.app.nativeauth.VehicleEvent) {if(event.type=="invalidate")events++}
            override fun onUnavailable() {retired++}
        }
        onMain {hub=AccountEvents(connection)}
        try {
            onMain {first=hub.subscribe(same);second=hub.subscribe(same)}
            waitFor("two distinct tokens for same listener") {opened==2}
            onMain {first.close()}
            File(base.cacheDir,"playlist-feed-invalidate").writeText(args.getString("gpsNonce")!!)
            waitFor("one remaining registration receives invalidate") {events==1}
            assertEquals(2,opened);assertEquals(0,retired)
            var late=0;var finalOpened=0;var hideStarted=false;var hiddenOpened=0
            lateinit var last: java.io.Closeable
            onMain {
                second.close()
                File(base.cacheDir,"playlist-feed-late").writeText(args.getString("gpsNonce")!!)
                hub.subscribe(object: io.wegoh.app.nativeauth.VehicleEventsListener {
                    override fun onOpen(){late++}
                    override fun onEvent(event: io.wegoh.app.nativeauth.VehicleEvent)=Unit
                }).close()
                last=hub.subscribe(object: io.wegoh.app.nativeauth.VehicleEventsListener {
                    override fun onOpen(){finalOpened++}
                    override fun onEvent(event: io.wegoh.app.nativeauth.VehicleEvent) {if(event.type=="invalidate" && event.resources==listOf("devices"))hideStarted=true}
                })
            }
            waitFor("replacement subscription adopted") {finalOpened==1}
            Thread.sleep(400);assertEquals(0,late)
            File(base.cacheDir,"playlist-feed-hide").writeText(args.getString("gpsNonce")!!)
            connection.check()
            waitFor("account verification in flight") {hideStarted && connection.status().stage==VehicleConnection.Stage.CHECKING}
            onMain {
                last.close()
                val pending=hub.subscribe(object: io.wegoh.app.nativeauth.VehicleEventsListener {
                    override fun onOpen(){hiddenOpened++}
                    override fun onEvent(event: io.wegoh.app.nativeauth.VehicleEvent)=Unit
                })
                connection.setForeground(false);pending.close()
            }
            File(base.cacheDir,"playlist-feed-queued").writeText(args.getString("gpsNonce")!!)
            waitFor("inflight verification finished without queued open") {connection.status().stage==VehicleConnection.Stage.CONNECTED}
            Thread.sleep(400);assertEquals(0,hiddenOpened)
            onMain {hub.close()}
            connection.disconnect()
            val store=io.wegoh.app.nativeauth.NativeConnectionState(base,profile)
            waitFor("feed remote logout",false) {store.locked {val saved=store.read().getJSONObject("access");!saved.has("credentials") && saved.getJSONArray("outbox").length()==0} && connection.status().stage==VehicleConnection.Stage.LOCKED}
        } finally {onMain {hub.close()}}
    }
    private fun parserBoundaries() {
        fun value()=JSONObject().put("id","a".repeat(32)).put("name",String(Character.toChars(0x1f600)).repeat(80)).put("revision",1)
            .put("tracks",JSONArray().put(JSONObject().put("id","b".repeat(32)).put("title","원곡").put("url","https://example.test/track?source=original")))
        fun rejects(item: JSONObject) {assertTrue("Malformed playlist accepted",runCatching {PlaylistsRepository.parseDetail(item)}.isFailure)}
        assertEquals(160,PlaylistsRepository.parseDetail(value()).summary.name.length)
        assertTrue(PlaylistsRepository.parseDetail(value().put("tracks",JSONArray())).tracks.isEmpty())
        rejects(value().put("name","x".repeat(81)));rejects(value().put("name","bad\nname"));rejects(value().put("revision",1.5));rejects(value().put("revision",0))
        for(url in listOf("http://example.test","https://user:pass@example.test","https://example.test:444/x","https://example.test/a b")) {
            val item=value();item.getJSONArray("tracks").getJSONObject(0).put("url",url);rejects(item)
        }
        val duplicate=value();duplicate.getJSONArray("tracks").put(duplicate.getJSONArray("tracks").getJSONObject(0));rejects(duplicate)
        assertTrue(runCatching {PlaylistsRepository.parseCatalogue(JSONObject().put("playlists",JSONArray().put(value()).put(value())))}.isFailure)
        rejects(value().put("tracks",JSONArray().apply {repeat(101){put(JSONObject().put("id",it.toString(16).padStart(32,'0')).put("title","Track").put("url","https://example.test"))}}))
    }
    private fun renderLayouts(host: MainActivity) {
        onMain {host.startActivity(Intent(host,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT))}
        waitFor("layout host foreground") {host.hasWindowFocus()}
        val longName="아주 긴 플레이리스트 이름 "+"밤바다와 숲길 ".repeat(6)
        val entries=(0 until 70).map {PlaylistSummary(it.toString(16).padStart(32,'0'),"$it $longName",1,70)}
        val tracks=(0 until 70).map {PlaylistTrack(it.toString(16).padStart(32,'0'),"합성 곡 $it $longName","https://example.test/$it","example.test")}
        for(dark in listOf(false,true))for(picker in listOf(false,true)) {
            val name="account-playlists-narrow-${if(dark)"night" else "day"}-${if(picker)"list" else "detail"}"
            val fixture=androidx.compose.runtime.mutableStateOf(WegoState(setupAllowed=true,storageReady=true,accountPlaylists=AccountPlaylistState(AccountPlaylistStatus.READY,entries,PlaylistDetail(entries.first(),tracks))))
            onMain {host.setContent {key(name) {CompositionLocalProvider(LocalVehicleLandingPage provides if(picker)"music-picker" else "music") {
                WegoCarTheme(dark=dark) {Box(Modifier.width(640.dp).fillMaxHeight()) {WegoVehicleScreen(fixture.value,{},{},{},{},{},{},{},{},{},
                    onPlaylistSelect={item->fixture.value=fixture.value.copy(accountPlaylists=AccountPlaylistState(AccountPlaylistStatus.READY,entries,PlaylistDetail(item,tracks)))})}}
            }}}}
            waitFor("narrow music body",false) {node(if(picker)"${entries.first().name} 선택" else "${tracks.first().title} 링크 열기")!=null}
            capture(name);click("음악 목록 아래로")
            waitFor("narrow music scroll",false) {node(if(picker)"${entries.first().name} 선택" else "${tracks.first().title} 링크 열기")==null}
            if(picker) {
                val visible=entries.first {node("${it.name} 선택")!=null}
                click("${visible.name} 선택")
                waitFor("detail starts at first track",false) {node("${tracks.first().title} 링크 열기")!=null}
                click("음악 목록 아래로")
                waitFor("detail independently scrolls",false) {node("${tracks.first().title} 링크 열기")==null}
                click("음악 고르기")
                waitFor("picker retains its position",false) {node("${visible.name} 선택")!=null && node("${entries.first().name} 선택")==null}
            }
        }
        onMain {host.setContent {WegoCarTheme {CompositionLocalProvider(LocalVehicleLandingPage provides "music") {
            WegoVehicleScreen(WegoState(setupAllowed=false,storageReady=true,policy="주행 제한",accountPlaylists=AccountPlaylistState(AccountPlaylistStatus.READY,entries,PlaylistDetail(entries.first(),tracks))),{},{},{},{},{},{},{},{},{})
        }}}}
        waitFor("restricted music hidden",false) {node("P단에서 이용할 수 있어요")!=null && node("${tracks.first().title} 링크 열기")==null}
        capture("account-playlists-restricted-layout")
    }
}
