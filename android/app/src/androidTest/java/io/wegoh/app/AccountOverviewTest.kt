package io.wegoh.app

import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.test.InstrumentationTestRunner
import io.wegoh.app.nativeauth.NativeDeviceIdentity
import io.wegoh.app.nativeauth.NativeConnectionState
import io.wegoh.app.nativeauth.VehicleConnection
import java.io.File
import org.json.JSONObject
import org.json.JSONArray
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
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
class AccountOverviewTest: FirstRunPermissionsCompletedTestCase() {
    private fun onMain(action: ()->Unit)=instrumentation.runOnMainSync(action)
    private fun waitFor(label: String,onUi: Boolean=true,condition: ()->Boolean) {
        val end=android.os.SystemClock.elapsedRealtime()+25000
        while(android.os.SystemClock.elapsedRealtime()<end) {
            var done=false;if(onUi)onMain {done=condition()} else done=condition()
            if(done)return;Thread.sleep(100)
        }
        fail("Overview fixture timeout: $label")
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
        waitFor("action available $label",false) {
            var target=node(label)
            var performed=false
            repeat(5) {
                if(!performed && target?.performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_CLICK)==true)performed=true
                if(!performed)target=target?.parent
            }
            performed
        }
        instrumentation.waitForIdleSync()
    }
    private fun capture(name: String) {
        instrumentation.waitForIdleSync();Thread.sleep(350)
        File(instrumentation.targetContext.cacheDir,name+".png").outputStream().use {
            check(instrumentation.uiAutomation.takeScreenshot().compress(android.graphics.Bitmap.CompressFormat.PNG,100,it))
        }
    }
    private fun go(label: String) {click("전체 메뉴");click(label)}
    fun testActualProfileDiscoveryAuthorityAndPublicStorage() {
        val args=(instrumentation as InstrumentationTestRunner).arguments
        val scenario=args.getString("scenario")!!
        val base=instrumentation.targetContext
        val fixture="overview_"+java.util.UUID.randomUUID().toString().replace("-","").take(24)
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
        val app=base.applicationContext as WegoApplication
        val delegate=app.javaClass.getDeclaredField("controller\$delegate").apply {isAccessible=true}
        val original=delegate.get(app) as Lazy<*>;val initialized=original.isInitialized()
        lateinit var controller: WegoController
        onMain {controller=WegoController(isolated,base.applicationContext);controller.connectAccount(connection);controller.setAppForeground(true);delegate.set(app,lazyOf(controller))}
        var activity: MainActivity?=null
        try {
            activity=instrumentation.startActivitySync(Intent(base,MainActivity::class.java).putExtra("screen","profile")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
            val host=activity
            if(scenario=="account-overview-edit") {
                val position=IntArray(2);onMain {host.window.decorView.getLocationOnScreen(position)}
                val time=android.os.SystemClock.uptimeMillis()
                for(action in listOf(android.view.MotionEvent.ACTION_DOWN,android.view.MotionEvent.ACTION_UP)) {
                    val event=android.view.MotionEvent.obtain(time,time,action,position[0]+48f,position[1]+16f,0)
                    instrumentation.uiAutomation.injectInputEvent(event,true);event.recycle()
                }
            }
            waitFor("actual Main ready") {controller.state.setupAllowed && controller.state.storageReady && host.hasWindowFocus() && connection.status().stage==VehicleConnection.Stage.READY}
            assertNull(controller.state.accountProfile.name)
            connection.start("Synthetic overview",if(scenario in setOf("account-overview-mandatory","account-overview-edit"))emptySet() else VehicleConnection.DEFAULT_SCOPES)
            if(scenario=="account-overview-invalid-name") {
                waitFor("invalid name suppressed") {controller.state.accountProfile.status==AccountReadStatus.UNAVAILABLE && connection.status().stage==VehicleConnection.Stage.CONNECTED}
                assertNull(controller.state.accountProfile.name)
                waitFor("invalid profile body",false) {node("프로필을 불러오지 못했어요")!=null};capture(scenario)
            } else {
                waitFor("actual profile name") {controller.state.accountProfile.status==AccountReadStatus.READY && controller.state.accountProfile.name=="Overview owner 1"}
                waitFor("profile renderer",false) {node("Overview owner 1")!=null};capture(scenario+"-profile")
                if(scenario=="account-overview-edit") {
                    editProfile(controller,host,base,args)
                } else {
                assertNull(node("새 계정 이름"));click("휴대전화에서 변경")
                waitFor("phone handoff",false) {node("iPhone 앱의 설정 → 프로필에서 고쳐요")!=null};click("닫기")
                click("웹 계정 안내");waitFor("truthful web guidance",false) {node("표시 이름은 웹 계정을 기준으로 합니다")!=null};capture(scenario+"-web-guidance");click("확인")
                go("발견")
                if(scenario in setOf("account-overview-mandatory","account-overview-denied")) {
                    waitFor("optional course permission denied") {controller.state.accountDiscovery.status==AccountReadStatus.PERMISSION_REQUIRED}
                    assertTrue(controller.state.accountDiscovery.packs.isEmpty());assertEquals("Overview owner 1",controller.state.accountProfile.name)
                    assertFalse(controller.state.catalogueBusy);assertTrue(controller.state.published.isEmpty())
                    waitFor("permission renderer",false) {node("경로 공유를 허용해 주세요")!=null};capture(scenario+"-denied")
                    if(scenario=="account-overview-denied") {
                        assertTrue(VehicleConnection.Scope.COURSES in connection.status().deniedOptionalScopes)
                        go("프로필")
                        waitFor("mandatory profile survives optional denial") {controller.state.accountProfile.status==AccountReadStatus.READY && controller.state.accountProfile.name=="Overview owner 1"}
                        go("발견")
                        waitFor("denied course scope is retained") {controller.state.accountDiscovery.status==AccountReadStatus.PERMISSION_REQUIRED}
                    }
                } else {
                    waitFor("actual public catalogue") {controller.state.accountDiscovery.status==AccountReadStatus.READY && controller.state.accountDiscovery.packs.size==1}
                    waitFor("public row",false) {node("Synthetic pack v1 받기")!=null};capture(scenario+"-catalogue")
                    click("창작자");waitFor("unavailable creator",false) {node("준비 중입니다")!=null};click("확인")
                    click("추천 경로");waitFor("unavailable recommendation",false) {node("준비 중입니다")!=null};click("확인")
                    val metadata=controller.state.accountDiscovery.packs.single()
                    if(scenario=="account-overview-restriction") {
                        restrictedDenial(controller,connection,base,args,metadata)
                    } else {
                    click("Synthetic pack v1 받기")
                    if(scenario=="account-overview-checksum") {
                        waitFor("bad checksum refused") {controller.state.accountDiscovery.status==AccountReadStatus.READY && !controller.state.accountDiscovery.isCurrent}
                        assertFalse(PackRepository(isolated).list().any {it.id=="sdk_pack"})
                        assertFalse(PrivateStore(isolated).exists("origin-sdk_pack-1"));capture(scenario+"-refused")
                    } else {
                        waitFor("public course saved with provenance") {controller.state.packs.any {it.id=="sdk_pack" && it.source=="공개 경로"}}
                        waitFor("saved state renderer",false) {node("Synthetic pack v1 받음")!=null};capture("account-overview-saved")
                        val repo=PackRepository(isolated)
                        val raw=PrivateStore(isolated).read("pack-sdk_pack-1")!!
                        assertEquals(args.getString("expectedPackSha256"),repo.verifiedOrigin(repo.list().single {it.id=="sdk_pack"})!!.checksum)
                        onMain {repo.importPublished(metadata,raw.toByteArray(Charsets.UTF_8))}
                        assertEquals(1,repo.list().count {it.key==metadata.key})
                        assertTrue(runCatching {repo.verifyPublished(metadata.copy(stopCount=2),raw.toByteArray(Charsets.UTF_8))}.isFailure)
                        assertTrue(runCatching {repo.verifyPublished(metadata.copy(checksum="0".repeat(64)),raw.toByteArray(Charsets.UTF_8))}.isFailure)
                        val altered=JSONObject(raw).put("title","Different same version").toString().toByteArray(Charsets.UTF_8)
                        val digest=java.security.MessageDigest.getInstance("SHA-256").digest(altered).joinToString("") {"%02x".format(it.toInt() and 255)}
                        assertTrue(runCatching {repo.importPublished(metadata.copy(title="Different same version",checksum=digest),altered)}.isFailure)
                        assertEquals(raw,PrivateStore(isolated).read("pack-sdk_pack-1"))
                        File(base.cacheDir,"overview-invalidate").writeText(args.getString("gpsNonce")!!)
                        connection.check()
                        waitFor("shared invalidation reloads profile and catalogue") {controller.state.accountProfile.name=="Overview owner 2" && controller.state.accountDiscovery.packs.size==2}
                        assertEquals(1,repo.list().count {it.id=="sdk_pack"})
                        click("Second public pack v1 받기")
                        waitFor("blob request really in flight",false) {File(base.cacheDir,"overview-late-started").let {it.exists() && it.readText()==args.getString("gpsNonce")}}
                        onMain {host.startActivity(base.packageManager.getLaunchIntentForPackage("ai.umos.maps.android.navigation.app") ?: error("OEM navigation missing"))}
                        waitFor("actual Main hidden with caches removed") {!host.lifecycle.currentState.isAtLeast(androidx.lifecycle.Lifecycle.State.RESUMED) &&
                            controller.state.accountProfile.name==null && controller.state.accountDiscovery.packs.isEmpty()}
                        File(base.cacheDir,"overview-late-release").writeText(args.getString("gpsNonce")!!)
                        Thread.sleep(700)
                        assertFalse(repo.list().any {it.id=="sdk_pack_2"});assertEquals(1,repo.list().count {it.id=="sdk_pack"})
                        onMain {host.startActivity(Intent(host,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT))}
                        waitFor("fresh foreground reload") {host.hasWindowFocus() && controller.state.accountProfile.name=="Overview owner 2" && controller.state.accountDiscovery.packs.size==2}
                        File(base.cacheDir,"overview-close").writeText(args.getString("gpsNonce")!!)
                        waitFor("closed stream clears live fields") {controller.state.accountProfile.name==null && controller.state.accountDiscovery.packs.isEmpty()}
                        Thread.sleep(500);assertEquals(1,repo.list().count {it.id=="sdk_pack"});capture("account-overview-unavailable")
                        go("프로필")
                        waitFor("explicit profile retry") {controller.state.accountProfile.status==AccountReadStatus.READY && controller.state.accountProfile.name=="Overview owner 2"}
                        File(base.cacheDir,"overview-offline").writeText(args.getString("gpsNonce")!!)
                        connection.check()
                        waitFor("account failure closes private fields") {controller.state.accountProfile.name==null && controller.state.accountDiscovery.packs.isEmpty() &&
                            connection.status().stage in setOf(VehicleConnection.Stage.RECOVERY_REQUIRED,VehicleConnection.Stage.UNAVAILABLE)}
                        assertEquals(1,repo.list().count {it.id=="sdk_pack"});capture("account-overview-offline")
                    }
                    }
                }
            }
                }
            connection.disconnect()
            val store=NativeConnectionState(base,fixture)
            waitFor("confirmed remote logout",false) {store.locked {val saved=store.read().getJSONObject("access");!saved.has("credentials") && saved.getJSONArray("outbox").length()==0} && connection.status().stage==VehicleConnection.Stage.LOCKED}
            if(scenario=="account-overview") {parserBoundaries();renderLayouts(host)}
            File(base.cacheDir,scenario+"-runtime.json").writeText(JSONObject().put("synthetic",true).put("actualMainRenderer",true).put("scenario",scenario)
                .put("publicSaved",PackRepository(isolated).list().count {it.id=="sdk_pack"}).put("latePublicSaved",PackRepository(isolated).list().count {it.id=="sdk_pack_2"})
                .put("legacyCatalogueBusy",controller.state.catalogueBusy).put("legacyCatalogueRows",controller.state.published.size)
                .put("originalControllerLazyUnchanged",original.isInitialized()==initialized)
                .put("modeledSetupRestriction",scenario=="account-overview-restriction")
                .put("limits","Synthetic phone/API; actual Main/TLS1.3/mTLS/WSS, OEM foreground without route/GPS changes. No real owner or web edit/release approval.").toString(2))
        } catch(failure: Throwable) {
            File(base.cacheDir,scenario+"-failure-runtime.json").writeText(JSONObject().put("synthetic",true)
                .put("setupAllowed",controller.state.setupAllowed).put("policy",controller.state.policy).put("storageReady",controller.state.storageReady).put("focused",activity?.hasWindowFocus()).put("lifecycle",activity?.lifecycle?.currentState?.name).put("profileStatus",controller.state.accountProfile.status.name)
                .put("discoveryStatus",controller.state.accountDiscovery.status.name).put("publicRows",controller.state.accountDiscovery.packs.size)
                .put("connectionStage",connection.status().stage.name).toString(2))
            runCatching {capture(scenario+"-failure")};throw failure
        } finally {
            try {onMain {controller.close();activity?.finish()};if(activity!=null)waitFor("isolated Main destroyed") {activity!!.isDestroyed}}
            finally {onMain {delegate.set(app,original)};connection.close()}
            assertEquals("Real controller lazy state preserved",initialized,original.isInitialized())
            assertEquals("Original course/receipt data preserved",before,originals())
        }
    }
    private fun editProfile(controller: WegoController,host: MainActivity,base: Context,args: android.os.Bundle) {
        assertNull(node("새 계정 이름"));assertNull(node("차량 번호 입력"));assertNull(node("이름 변경"))
        click("휴대전화에서 변경");waitFor("profile handoff QR",false) {node("iPhone 앱의 설정 → 프로필에서 고쳐요")!=null}
        capture("profile-phone-handoff");click("닫기")
        File(base.cacheDir,"profile-mobile-saved").writeText(args.getString("gpsNonce")!!)
        waitFor("mobile changes arrive automatically") {controller.state.accountProfile.name=="Mobile friend" && controller.state.accountProfile.vehicle?.plateNumber=="123가4567"}
        waitFor("mobile values rendered",false) {node("Mobile friend")!=null && node("123가4567")!=null}
        capture("profile-mobile-updated")
        for(dark in listOf(false,true)) {
            onMain {host.setContent {WegoCarTheme(dark=dark) {Box(Modifier.width(640.dp).fillMaxHeight().background(io.wegoh.app.ui.LocalCarPalette.current.background)) {
                io.wegoh.app.ui.AccountProfileScreen(AccountProfileState(AccountReadStatus.READY,"Mobile friend",true,vehicle=io.wegoh.app.nativeauth.VehicleProfile("123가4567","","나의 차",1)),{},{})
            }}}}
            waitFor("narrow profile",false) {node("Mobile friend")!=null && node("나의 차")!=null && node("123가4567")!=null};capture("profile-centered-narrow-"+if(dark)"night" else "day")
        }
    }
    private fun restrictedDenial(controller: WegoController,connection: VehicleConnection,base: Context,args: android.os.Bundle,metadata: PublishedPack) {
        val account=controller.javaClass.getDeclaredField("account").apply {isAccessible=true}.get(controller) as CoursesRepository
        val profile=controller.javaClass.getDeclaredField("profile").apply {isAccessible=true}.get(controller) as ProfileRepository
        val discovery=controller.javaClass.getDeclaredField("discovery").apply {isAccessible=true}.get(controller) as DiscoveryRepository
        val boundary=connection.verifiedDataBoundary()!!
        val denied=java.util.concurrent.atomic.AtomicReference<Throwable?>()
        File(base.cacheDir,"overview-restricted-scope").writeText(args.getString("gpsNonce")!!)
        connection.readCourses {denied.set(it.exceptionOrNull())}
        waitFor("denial request really in flight",false) {File(base.cacheDir,"overview-restriction-started").let {it.exists() && it.readText()==args.getString("gpsNonce")}}
        click("Synthetic pack v1 받기")
        waitFor("public download queued") {discovery.state.downloading==metadata.key}
        try {
            onMain {account.setSetupAllowed(false);profile.setSetupAllowed(false);discovery.setSetupAllowed(false)}
            assertEquals(1,discovery.state.packs.size);assertEquals(metadata.key,discovery.state.downloading)
            File(base.cacheDir,"overview-restriction-release").writeText(args.getString("gpsNonce")!!)
            waitFor("restriction does not suppress authority loss") {denied.get() is VehicleConnection.ScopeRequired && discovery.state.status==AccountReadStatus.PERMISSION_REQUIRED &&
                discovery.state.packs.isEmpty() && discovery.state.downloading==null}
            assertEquals(boundary,connection.verifiedDataBoundary())
            assertNull(connection.contentDataBoundary(VehicleConnection.Scope.COURSES))
            assertEquals("Overview owner 1",profile.state.name)
            assertFalse(controller.repository.list().any {it.id=="sdk_pack"})
            capture("account-overview-restriction-denied")
        } finally {onMain {account.setSetupAllowed(true);profile.setSetupAllowed(true);discovery.setSetupAllowed(true)}}
    }
    private fun parserBoundaries() {
        fun item()=JSONObject().put("id","public_fixture").put("version",1).put("title","새로운 길").put("author","창작자")
            .put("description","첫 줄\n둘째 줄").put("stopCount",2).put("checksum","a".repeat(64))
        fun catalogue(value: JSONObject)=JSONObject().put("packs",JSONArray().put(value))
        assertEquals("첫 줄\n둘째 줄",DiscoveryRepository.parse(catalogue(item())).single().description)
        val emoji=String(Character.toChars(0x1f600))
        assertEquals(100,DiscoveryRepository.parse(catalogue(item().put("title",emoji.repeat(50)))).single().title.length)
        assertTrue(runCatching {DiscoveryRepository.parse(catalogue(item().put("title",emoji.repeat(51))))}.isFailure)
        assertTrue(runCatching {DiscoveryRepository.parse(catalogue(item().put("version",1.5)))}.isFailure)
        assertTrue(runCatching {DiscoveryRepository.parse(catalogue(item().put("stopCount",4)))}.isFailure)
        assertTrue(runCatching {DiscoveryRepository.parse(catalogue(item().put("title","bad\u0000title")))}.isFailure)
        assertTrue(runCatching {DiscoveryRepository.parse(JSONObject().put("packs",JSONArray().put(item()).put(item())))}.isFailure)
    }
    private fun renderLayouts(host: MainActivity) {
        val name=String(Character.toChars(0x1f600)).repeat(64)
        val packs=(0 until 70).map {PublishedPack("layout_$it",1,"$it 아주 긴 공개 코스 "+"바닷길과 숲길 ".repeat(6),"긴 창작자 이름", "공개 경로",3,"1".repeat(64))}
        for(dark in listOf(false,true))for(page in listOf("profile","discover")) {
            val key="account-overview-narrow-$page-${if(dark)"night" else "day"}"
            val fixture=WegoState(setupAllowed=true,storageReady=true,accountProfile=AccountProfileState(AccountReadStatus.READY,name),
                accountDiscovery=AccountDiscoveryState(AccountReadStatus.READY,packs))
            onMain {host.setContent {key(key) {CompositionLocalProvider(LocalVehicleLandingPage provides page) {
                WegoCarTheme(dark=dark) {Box(Modifier.width(640.dp).fillMaxHeight()) {WegoVehicleScreen(fixture,{},{},{},{},{},{},{},{},{})}}
            }}}}
            waitFor("narrow overview body",false) {node(if(page=="profile")name else "${packs.first().title} v1 받기")!=null}
            capture(key)
            if(page=="discover") {
                click("발견 목록 아래로")
                waitFor("narrow discovery scroll",false) {node("${packs.first().title} v1 받기")==null && (2..70).any {node("$it / 70")!=null}}
            } else assertNotNull(node("이름 변경"))
        }
    }
}
