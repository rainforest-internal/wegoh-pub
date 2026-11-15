package io.wegoh.app

import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.test.InstrumentationTestRunner
import androidx.activity.compose.setContent
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.runtime.key
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import io.wegoh.app.nativeauth.NativeConnectionState
import io.wegoh.app.nativeauth.NativeDeviceIdentity
import io.wegoh.app.nativeauth.VehicleConnection
import io.wegoh.app.ui.CarWindowVisibility
import io.wegoh.app.ui.ProvideCarWindowVisibility
import io.wegoh.app.ui.WegoCarTheme
import io.wegoh.app.ui.WegoVehicleScreen
import java.io.File
import org.json.JSONObject

@Suppress("DEPRECATION")
class AccountCoursesTest: FirstRunPermissionsCompletedTestCase() {
    private fun onMain(action: ()->Unit)=instrumentation.runOnMainSync(action)
    private fun waitFor(label: String,onUi: Boolean=true,condition: ()->Boolean) {
        val end=android.os.SystemClock.elapsedRealtime()+25000
        while(android.os.SystemClock.elapsedRealtime()<end) {
            var done=false;if(onUi)onMain {done=condition()} else done=condition();if(done)return;Thread.sleep(100)
        }
        fail("Account course fixture timeout: $label")
    }
    private fun shown(label: String): Boolean {
        if(android.os.Build.VERSION.SDK_INT>=34)instrumentation.uiAutomation.clearCache()
        fun visit(node: android.view.accessibility.AccessibilityNodeInfo?): Boolean {
            if(node==null)return false
            if(node.isVisibleToUser && (node.text?.toString()==label || node.contentDescription?.toString()==label))return true
            return (0 until node.childCount).any {visit(node.getChild(it))}
        }
        return visit(instrumentation.uiAutomation.rootInActiveWindow)
    }
    private fun capture(name: String) {
        instrumentation.waitForIdleSync();Thread.sleep(350)
        File(instrumentation.targetContext.cacheDir,name+".png").outputStream().use {
            check(instrumentation.uiAutomation.takeScreenshot().compress(android.graphics.Bitmap.CompressFormat.PNG,100,it))
        }
    }
    private fun click(label: String) {
        fun find(node: android.view.accessibility.AccessibilityNodeInfo?): android.view.accessibility.AccessibilityNodeInfo? {
            if(node==null)return null
            if(node.text?.toString()==label || node.contentDescription?.toString()==label)return node
            for(i in 0 until node.childCount)find(node.getChild(i))?.let{return it}
            return null
        }
        val end=android.os.SystemClock.elapsedRealtime()+10000
        while(android.os.SystemClock.elapsedRealtime()<end) {
            if(android.os.Build.VERSION.SDK_INT>=34)instrumentation.uiAutomation.clearCache()
            var node=find(instrumentation.uiAutomation.rootInActiveWindow)
            repeat(5) {
                node?.performAction(android.view.accessibility.AccessibilityNodeInfo.AccessibilityAction.ACTION_SHOW_ON_SCREEN.id)
                if(node?.performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_CLICK)==true)return
                node=node?.parent
            }
            Thread.sleep(100)
        }
        fail("Account course action unavailable: $label")
    }
    private fun runBoundaryCase(connection: VehicleConnection,context: Context,base: Context,profile: String,scenario: String) {
        lateinit var model: CoursesRepository
        onMain {model=CoursesRepository(connection,PackRepository(context)) {};model.setSetupAllowed(true);model.setForeground(true);connection.setSetupAllowed(true);connection.setForeground(true)}
        try {
            waitFor("boundary fixture ready") {connection.status().stage==VehicleConnection.Stage.READY}
            connection.start("Synthetic boundary",VehicleConnection.Scope.entries.toSet())
            waitFor("boundary WSS refresh") {model.state.courses.firstOrNull()?.published?.title=="Account course 2" && connection.status().stage==VehicleConnection.Stage.CONNECTED}
            onMain {model.select(model.state.courses.first())}
            waitFor("boundary verified selection") {model.state.selected!=null}
            val before=connection.accountDataBoundary()!!
            val stream=connection.dataStreamRevision()
            if(scenario.endsWith("restriction")) {
                onMain {model.setSetupAllowed(false)}
                instrumentation.waitForIdleSync();assertNotNull("Restrictions alone retain the valid grant",model.state.selected)
                val done=java.util.concurrent.CountDownLatch(1)
                connection.readCourses {assertTrue(it.isFailure);done.countDown()}
                assertTrue(done.await(10,java.util.concurrent.TimeUnit.SECONDS))
                waitFor("restricted scope denial clears personal overlay") {model.state.status==AccountCourseStatus.PERMISSION_REQUIRED && model.state.selected==null && model.state.courses.isEmpty()}
                assertEquals(before.revision,connection.dataEpoch());assertNull(connection.accountDataBoundary())
            } else {
                val store=NativeConnectionState(base,profile)
                store.locked {val root=store.read();root.getJSONObject("access").getJSONObject("credentials").put("expiresAt",0L);store.write(root)}
                connection.check()
                waitFor("quiet refreshed socket retains selected details with execution locked") {model.state.status==AccountCourseStatus.READY && !model.state.isCurrent && model.state.selected!=null && connection.status().stage==VehicleConnection.Stage.CONNECTED}
                assertEquals(before,connection.accountDataBoundary());assertTrue(connection.dataStreamRevision()>stream)
            }
            onMain {model.setSetupAllowed(true)}
            connection.disconnect()
            val logout=NativeConnectionState(base,profile)
            waitFor("boundary remote logout receipt",onUi=false) {val state=logout.read().getJSONObject("access");!state.has("credentials") && state.getJSONArray("outbox").length()==0 && connection.status().stage==VehicleConnection.Stage.LOCKED}
        } finally {onMain {model.close()}}
    }
    private fun runBackgroundCase(connection: VehicleConnection,isolated: Context,base: Context,profile: String,args: android.os.Bundle) {
        val app=base.applicationContext as WegoApplication
        val delegate=app.javaClass.getDeclaredField("controller\$delegate").apply {isAccessible=true}
        val original=delegate.get(app)
        val services=base.getSystemService(android.app.ActivityManager::class.java)
        fun serviceActive()=services.getRunningServices(100).any {it.service.className==SessionService::class.java.name && it.foreground}
        assertFalse("Existing journey must not be replaced",serviceActive())
        lateinit var controller: WegoController
        onMain {controller=WegoController(isolated,base.applicationContext);controller.connectAccount(connection);controller.setAppForeground(true);delegate.set(app,lazyOf(controller))}
        var activity: MainActivity?=null
        try {
            activity=instrumentation.startActivitySync(Intent(base,MainActivity::class.java).putExtra("screen","journeys")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
            val host=activity
            waitFor("actual Main setup ready") {controller.state.setupAllowed && controller.state.storageReady && host.hasWindowFocus()}
            waitFor("background fixture ready") {connection.status().stage==VehicleConnection.Stage.READY}
            connection.start("Synthetic background journey",VehicleConnection.Scope.entries.toSet())
            waitFor("background connection ready") {connection.status().stage==VehicleConnection.Stage.CONNECTED}
            click("더보기");click("내 경로")
            waitFor("WSS second catalogue") {controller.state.accountCourses.courses.firstOrNull()?.published?.title=="Account course 2"}
            click("Account course 2 선택")
            waitFor("actual Main account selection") {controller.state.selected?.id=="sdk_pack"}
            val pack=controller.state.selected!!
            val namespace=connection.accountDataBoundary()!!.storageKey
            click("도착 알림");click("동의하고 시작")
            waitFor("actual service foreground") {serviceActive() && controller.state.active && controller.state.location=="위치 수신"}
            assertEquals(NavigationPhase.IDLE,controller.state.navigationPhase)
            click("출발")
            waitFor("OEM navigation response") {controller.state.navigationPhase in setOf(NavigationPhase.OEM_GUIDANCE_REPORTED,NavigationPhase.ACTIVE)}
            val phase=controller.state.navigationPhase
            waitFor("OEM really hides Main") {!host.lifecycle.currentState.isAtLeast(androidx.lifecycle.Lifecycle.State.RESUMED) &&
                host.window.decorView.windowVisibility!=android.view.View.VISIBLE && !controller.state.accountCourses.isCurrent}
            val hiddenAt=android.os.SystemClock.elapsedRealtime()
            assertTrue(controller.state.active);assertNull(controller.state.selected);assertTrue(controller.state.completed.isEmpty());assertFalse(controller.coursesRepository.canUse());assertTrue(controller.state.storageReady)
            assertTrue(ProgressStore(isolated,namespace).read(pack).isEmpty())
            val unexpected=java.util.concurrent.atomic.AtomicBoolean(false)
            connection.readCourses {unexpected.set(true)}
            File(base.cacheDir,"account-course-allow-gps").writeText(args.getString("gpsNonce")!!)
            waitFor("background Fused durable arrival") {ProgressStore(isolated,namespace).read(pack)==setOf("stop")}
            Thread.sleep(1200)
            assertEquals(1,VisitedPlaces(isolated,namespace).list().length())
            assertFalse(unexpected.get());assertTrue(controller.state.completed.isEmpty());assertFalse(controller.coursesRepository.canUse())
            capture("account-courses-background-arrival")
            val arrivedAt=android.os.SystemClock.elapsedRealtime()
            File(base.cacheDir,"account-course-monitor-end").writeText(args.getString("gpsNonce")!!)
            waitFor("background invalidate ends service") {!controller.state.active && !serviceActive()}
            Thread.sleep(1200)
            assertEquals(1,VisitedPlaces(isolated,namespace).list().length())
            File(base.cacheDir,"account-course-background-runtime.json").writeText(JSONObject().put("synthetic",true)
                .put("actualMainRenderer",true).put("actualForegroundService",true).put("mainHiddenAtMillis",hiddenAt)
                .put("arrivalObservedAtMillis",arrivedAt).put("arrivalAfterMainHidden",arrivedAt>hiddenAt)
                .put("navigationPhase",phase.name).put("scopedReceiptCount",1).put("backgroundPayloadCallback",unexpected.get())
                .put("monitorInvalidationStoppedService",true).put("limits","Synthetic grant/API/virtual GPS; OEM arrival callbacks not used; no physical vehicle or uninterrupted long journey claim.").toString(2))
            connection.disconnect()
            val store=NativeConnectionState(base,profile)
            waitFor("background logout receipt",onUi=false) {store.locked {store.read().getJSONObject("access").getJSONArray("outbox").length()==0} && connection.status().stage==VehicleConnection.Stage.LOCKED}
        } catch(failure: Throwable) {
            runCatching {capture("account-courses-background-failure")};throw failure
        } finally {
            try {
                onMain {base.stopService(Intent(base,SessionService::class.java));controller.stop();activity?.finish()}
                waitFor("isolated service destroyed") {!serviceActive() && activity?.isDestroyed!=false}
            } finally {onMain {try {controller.close()} finally {delegate.set(app,original)}}}
        }
    }
    fun testAccountCourseIntegrityLifecycleAndActualRenderer() {
        val args=(instrumentation as InstrumentationTestRunner).arguments
        val base=instrumentation.targetContext
        val fixture="account_course_"+java.util.UUID.randomUUID().toString().replace("-","").take(24)
        val dir=File(base.cacheDir,fixture).apply {mkdirs()}
        val isolated=object: ContextWrapper(base) {
            override fun getApplicationContext(): Context=this
            override fun getFilesDir()=File(dir,"files").apply {mkdirs()}
            override fun getNoBackupFilesDir()=File(dir,"no-backup").apply {mkdirs()}
            override fun getSharedPreferences(name: String,mode: Int)=base.getSharedPreferences(fixture+name,mode)
            override fun deleteSharedPreferences(name: String)=base.deleteSharedPreferences(fixture+name)
        }
        fun originals()=PackRepository(base).list().joinToString {it.key+ProgressStore(base).read(it).sorted()}+VisitedPlaces(base).list().toString()
        val before=originals()
        val ca=NativeDeviceIdentity.parseCertificates(String(android.util.Base64.decode(args.getString("ca"),android.util.Base64.DEFAULT),Charsets.US_ASCII)).single()
        val connection=VehicleConnection.synthetic(base,fixture,args.getString("port")!!.toInt(),ca,args.getString("eventsPort")!!.toInt())
        if(args.getString("scenario")=="account-courses-background") {
            try {runBackgroundCase(connection,isolated,base,fixture,args)} finally {connection.close();assertEquals(before,originals())}
            return
        }
        if(args.getString("scenario") in setOf("account-courses-restriction","account-courses-rotation")) {
            try {runBoundaryCase(connection,isolated,base,fixture,args.getString("scenario")!!)} finally {connection.close();assertEquals(before,originals())}
            return
        }
        val app=base.applicationContext as WegoApplication
        val delegate=app.javaClass.getDeclaredField("controller\$delegate").apply {isAccessible=true}
        val original=delegate.get(app) as Lazy<*>
        val wasInitialized=original.isInitialized()
        lateinit var controller: WegoController
        onMain {controller=WegoController(isolated,base.applicationContext);controller.connectAccount(connection);controller.setAppForeground(true);delegate.set(app,lazyOf(controller))}
        var activity=instrumentation.startActivitySync(Intent(base,MainActivity::class.java).putExtra("screen","journeys").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
        lateinit var windows: CarWindowVisibility
        var observedWindows: CarWindowVisibility?=null
        val focusEvents=org.json.JSONArray()
        val focusHost=activity
        onMain {windows=CarWindowVisibility(focusHost) {windowState ->
            val roots=org.json.JSONArray()
            observedWindows?.let {owner ->
                val field=owner.javaClass.getDeclaredField("views").apply {isAccessible=true}
                (field.get(owner) as Iterable<*>).filterNotNull().forEach {entry ->
                    val view=entry.javaClass.getDeclaredField("view").apply {isAccessible=true}.get(entry) as android.view.View
                    roots.put(JSONObject().put("class",view.javaClass.simpleName).put("attached",view.isAttachedToWindow)
                        .put("shown",view.isShown).put("windowVisibility",view.windowVisibility).put("focused",view.hasWindowFocus()))
                }
            }
            focusEvents.put(JSONObject().put("elapsedMillis",android.os.SystemClock.elapsedRealtime()).put("visible",windowState.visible).put("focused",windowState.focused)
                .put("lifecycle",focusHost.lifecycle.currentState.name).put("views",roots))
            controller.setVisible(windowState.visible,focusHost,windowState.focused)
        };observedWindows=windows}
        val coursesModel=CoursesViewModel(controller.coursesRepository,controller::selectAccountCourse)
        onMain {activity.setContent {val coursesState=coursesModel.uiState.collectAsStateWithLifecycle().value
            ProvideCarWindowVisibility(windows) {WegoCarTheme {WegoVehicleScreen(controller.state.copy(accountCourses=coursesState),
            onSelect=controller::select,onImport={},onStart={if(controller.consentLocation())controller.begin(controller.state.selectedKey!!)},
            onStop=controller::stop,onNavigate=controller::requestNavigation,onReset=controller::reset,onBrowse=controller::loadPublished,
            onDownload=controller::downloadPublished,onShareVisits=controller::shareVisitedPlaces,
            onAccountCourses=coursesModel::load,onAccountSelect=coursesModel::select)}}}}
        try {
            waitFor("actual CarUx ready") {controller.state.setupAllowed && controller.state.storageReady}
            waitFor("synthetic connection ready") {connection.status().stage==VehicleConnection.Stage.READY}
            connection.start("Synthetic account courses",VehicleConnection.Scope.entries.toSet())
            waitFor("account connected before opening catalogue") {connection.status().stage==VehicleConnection.Stage.CONNECTED}
            click("더보기")
            waitFor("owned dialog focus",onUi=false) {shown("내 경로")}
            assertTrue(VehicleConnection.Scope.COURSES in connection.status().approvedOptionalScopes)
            click("내 경로")
            waitFor("second catalogue after actual WSS invalidation") {controller.state.accountCourses.courses.firstOrNull()?.published?.title=="Account course 2"}
            val previousSelection=PrivateSettings(isolated).selected()
            val own=controller.state.accountCourses.courses.first();assertTrue(own.available)
            assertFalse(controller.state.accountCourses.courses.last().available)
            waitFor("account list renderer",onUi=false) {shown("Account course 2 선택")};capture("account-courses-list")
            click("Account course 2 선택")
            waitFor("verified ephemeral selection") {controller.state.selected?.id=="sdk_pack"}
            waitFor("selected course renderer",onUi=false) {shown("Synthetic stop") && !shown("Account course 2 선택")};capture("account-courses-selected")
            val pack=controller.state.selected!!
            assertEquals(CoursesRepository.SOURCE,pack.source);assertEquals(1,controller.state.packs.count {it.key==pack.key})
            assertFalse(PackRepository(isolated).list().any {it.key==pack.key})
            assertEquals(previousSelection,PrivateSettings(isolated).selected());assertTrue(PrivateSettings(isolated).selected()!=pack.key)
            val repo=PackRepository(isolated)
            fun rejects(meta: PublishedPack,raw: ByteArray) {try {repo.accountCourse(meta,raw);fail("Invalid course accepted")}catch(expected: IllegalStateException){}catch(expected: IllegalArgumentException){}}
            val raw=base.assets.open("packs/"+base.assets.list("packs")!!.first()).readBytes()
            val valid=PackCodec.decode(raw.toString(Charsets.UTF_8))
            fun hash(bytes: ByteArray)=java.security.MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") {"%02x".format(it.toInt() and 255)}
            val meta=PublishedPack(valid.id,valid.version,valid.title,valid.author,valid.description,valid.stops.size,hash(raw))
            assertEquals(valid.key,repo.accountCourse(meta,raw).key)
            rejects(meta.copy(checksum="0".repeat(64)),raw)
            rejects(meta.copy(id="different_course"),raw);rejects(meta.copy(version=valid.version+1),raw)
            rejects(meta.copy(stopCount=valid.stops.size+1),raw)
            val malformed=JSONObject(raw.toString(Charsets.UTF_8)).put("schemaVersion",2).toString().toByteArray()
            rejects(meta.copy(checksum=hash(malformed)),malformed)
            rejects(meta.copy(checksum=hash(ByteArray(PackCodec.MAX_BYTES+1))),ByteArray(PackCodec.MAX_BYTES+1))
            val visitsBefore=VisitedPlaces(isolated).list().toString()
            waitFor("verified course permission") {connection.status().stage==VehicleConnection.Stage.CONNECTED}
            val namespace=connection.accountDataBoundary()!!.storageKey
            click("도착 알림");click("동의하고 시작")
            waitFor("real location event from virtual GPS") {controller.state.completed==setOf("stop")}
            val foregroundEventOnce=controller.state.history.count {it.startsWith("EVENT_EXECUTED")}==1
            assertEquals(visitsBefore,VisitedPlaces(isolated).list().toString());assertTrue(ProgressStore(isolated).read(pack).isEmpty())
            assertEquals(setOf("stop"),ProgressStore(isolated,namespace).read(pack))
            assertEquals(1,VisitedPlaces(isolated,namespace).list().length())
            val other=if(namespace=="f".repeat(64))"e".repeat(64) else "f".repeat(64)
            assertTrue(ProgressStore(isolated,other).read(pack).isEmpty());assertEquals(0,VisitedPlaces(isolated,other).list().length())
            PrivateStore(isolated).write("account-$other-progress","[]")
            assertTrue(runCatching {ProgressStore(isolated,other).read(pack)}.isFailure)
            onMain {
                controller.stop()
                controller.select(controller.state.packs.first {it.source!=CoursesRepository.SOURCE}.key)
                controller.selectAccountCourse(own)
            }
            assertEquals(pack.key,controller.state.selectedKey);assertEquals(setOf("stop"),controller.state.completed)
            val late=java.util.concurrent.atomic.AtomicReference<io.wegoh.app.nativeauth.NativeApiClient.PackVersion?>()
            onMain {controller.reset();controller.begin(pack.key) {
                connection.coursesApi.readOriginalPackVersion(own.published.id,own.published.version) {it.onSuccess(late::set)}
                controller.requestNavigation()
            }}
            waitFor("actual NaviHelper response") {controller.state.navigationPhase in setOf(NavigationPhase.ACTIVE,NavigationPhase.OEM_GUIDANCE_REPORTED,NavigationPhase.FAILED)}
            assertTrue(controller.state.navigationPhase!=NavigationPhase.FAILED)
            File(base.cacheDir,"account-course-runtime.json").writeText(JSONObject().put("synthetic",true).put("virtualGps",true)
                .put("courseSource",pack.source).put("locationEventOnce",foregroundEventOnce)
                .put("navigationPhase",controller.state.navigationPhase.name).put("accountCourseDiskCopies",0).put("scopedDurableReceipt",true).put("unscopedRecordsUnchanged",true).toString(2))
            Thread.sleep(250)
            instrumentation.sendKeyDownUpSync(android.view.KeyEvent.KEYCODE_HOME)
            waitFor("actual HOME retains a read-only account snapshot") {!activity.hasWindowFocus() && !controller.state.accountCourses.isCurrent}
            val hiddenCompleted=controller.state.completed
            val hiddenOverview=controller.state.navigationOverview
            val receivedBeforeBackground=late.get()
            Thread.sleep(1000)
            assertFalse(controller.state.accountCourses.courses.isEmpty());assertFalse(controller.coursesRepository.canUse());assertTrue(controller.state.storageReady)
            assertSame("Background must not deliver a new payload",receivedBeforeBackground,late.get());assertTrue(controller.state.active)
            assertEquals(hiddenCompleted,controller.state.completed);assertEquals(hiddenOverview,controller.state.navigationOverview)
            onMain {activity.startActivity(Intent(activity,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT))}
            waitFor("actual Main foreground return") {activity.hasWindowFocus()}
            onMain {controller.setVisible(false,Any())}
            waitFor("real denied/offline fresh catalogue") {controller.state.accountCourses.status==if(args.getString("scenario")!!.endsWith("offline"))AccountCourseStatus.UNAVAILABLE else AccountCourseStatus.PERMISSION_REQUIRED}
            waitFor("denied/offline terminates active execution") {!controller.state.active}
            assertFalse(controller.state.packs.any {it.source==CoursesRepository.SOURCE})
            connection.disconnect()
            waitFor("isolated logout") {connection.status().stage==VehicleConnection.Stage.LOCKED}
            onMain {windows.close();activity.finish()}
            activity=instrumentation.startActivitySync(Intent(base,MainActivity::class.java).putExtra("screen","journeys").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
            waitFor("layout Activity foreground") {activity.hasWindowFocus()}
            val longTitle="아주 긴 이름의 여행 코스 "+"바닷길과 골목 ".repeat(6)
            val layouts=(0 until 70).map {i ->AccountCourse(PublishedPack("layout_$i",1,"$i $longTitle","긴 창작자 이름 ".repeat(6),"Fixture only",3,"1".repeat(64)),true)}
            for(dark in listOf(false,true)) {
                onMain {activity.setContent {key(dark) {WegoCarTheme(dark=dark) {Box(Modifier.width(640.dp).fillMaxHeight()) {
                    WegoVehicleScreen(WegoState(setupAllowed=true,storageReady=true,accountCourses=AccountCourseState(AccountCourseStatus.READY,layouts)),
                        onSelect={},onImport={},onStart={},onStop={},onNavigate={},onReset={},onBrowse={},onDownload={},onShareVisits={})
                }}}}}
                click("더보기");click("내 경로")
                waitFor("narrow long-name list",onUi=false) {shown("${layouts.first().published.title} 선택")}
                capture("account-courses-narrow-"+if(dark)"night" else "day")
                click("내 경로 목록 아래로")
                waitFor("narrow account list scroll",onUi=false) {(2..70).any {shown("$it / 70")}}
            }
        } catch(failure: Throwable) {
            runCatching {capture("account-courses-failure")};throw failure
        } finally {
            try {
                onMain {windows.close();controller.close();activity.finish()}
                waitFor("last isolated Activity destroyed") {activity.isDestroyed}
            } finally {onMain {delegate.set(app,original)};connection.close()}
            assertEquals("Real controller lazy not initialized by fixture",wasInitialized,original.isInitialized())
            File(base.cacheDir,"account-course-focus-events.json").writeText(focusEvents.toString(2))
            assertEquals("Original courses/progress/visits preserved",before,originals())
        }
    }
}
