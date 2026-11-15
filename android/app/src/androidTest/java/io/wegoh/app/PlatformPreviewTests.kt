package io.wegoh.app

import android.content.Intent
import android.graphics.Bitmap
import android.os.Handler
import android.os.Looper
import android.test.InstrumentationTestCase
import android.view.PixelCopy
import android.view.accessibility.AccessibilityNodeInfo
import android.accessibilityservice.AccessibilityServiceInfo
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import io.wegoh.app.ui.*
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Whole-plan UI, fictional fixtures. Never evidence of live friends/accounts/rooms. */
@Suppress("DEPRECATION")
class PlatformPreviewTests: InstrumentationTestCase() {
    private lateinit var activity: MainActivity
    private var previousFlags=0
    override fun setUp() {
        super.setUp()
        val info=instrumentation.uiAutomation.serviceInfo
        previousFlags=info.flags;info.flags=info.flags or AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
        instrumentation.uiAutomation.serviceInfo=info
    }
    override fun tearDown() {
        if(::activity.isInitialized)instrumentation.runOnMainSync {activity.finish()}
        val info=instrumentation.uiAutomation.serviceInfo;info.flags=previousFlags
        instrumentation.uiAutomation.serviceInfo=info
        super.tearDown()
    }
    private fun start() {
        activity=instrumentation.startActivitySync(Intent(instrumentation.targetContext,MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
        val frames=CountDownLatch(1)
        instrumentation.runOnMainSync {activity.window.decorView.postOnAnimation {
            activity.window.decorView.postOnAnimation {frames.countDown()}
        }}
        assertTrue("Main window must finish its initial layout",frames.await(3,TimeUnit.SECONDS))
        instrumentation.waitForIdleSync();Thread.sleep(300)
    }
    private fun nodes(): List<AccessibilityNodeInfo> {
        if(android.os.Build.VERSION.SDK_INT>=34)instrumentation.uiAutomation.clearCache()
        val result=mutableListOf<AccessibilityNodeInfo>()
        fun walk(n: AccessibilityNodeInfo?) {if(n!=null){result.add(n);for(i in 0 until n.childCount)walk(n.getChild(i))}}
        val windows=instrumentation.uiAutomation.windows
            .filter {it.type==android.view.accessibility.AccessibilityWindowInfo.TYPE_APPLICATION}.mapNotNull {it.root}
            .filter {it.packageName?.toString()==instrumentation.targetContext.packageName}
        if(windows.isEmpty())walk(instrumentation.uiAutomation.rootInActiveWindow) else windows.forEach(::walk)
        return result
    }
    private fun visible(label: String)=nodes().any {it.isVisibleToUser && (it.text?.toString()==label || it.contentDescription?.toString()==label)}
    private fun settle(){instrumentation.waitForIdleSync();Thread.sleep(220)}
    private fun awaitVisible(label: String) {
        val end=System.currentTimeMillis()+7000
        while(System.currentTimeMillis()<end){if(visible(label))return;Thread.sleep(100)}
        runCatching{capture("failure-visible",628)}
        fail("Screen label missing: $label\n${describe()}")
    }
    private fun assertProductCopy() {
        val visible=nodes().filter {it.isVisibleToUser}.flatMap {listOfNotNull(it.text?.toString(),it.contentDescription?.toString())}
        val forbidden=listOf("미리보기","예시","가상","목업","실시간 아님","검증 전","출발 보기","참여 보기","게시 보기","공유할 정보","·")
        for(label in visible)assertFalse("Developer copy exposed: $label",forbidden.any {it in label})
    }
    private fun describe()=nodes().joinToString("\n"){"${it.text}|${it.contentDescription}|${it.stateDescription}|checked=${it.isChecked}"}
    private fun click(label: String) {
        val end=System.currentTimeMillis()+7000
        while(System.currentTimeMillis()<end) {
            val candidates=nodes().filter {it.isVisibleToUser && (it.text?.toString()==label || it.contentDescription?.toString()==label)}
                .sortedByDescending {it.isClickable && it.contentDescription?.toString()==label}
            for(candidate in candidates) {
                var node: AccessibilityNodeInfo?=candidate
                repeat(6){if(node?.isClickable==true && node?.isEnabled==true && node?.performAction(AccessibilityNodeInfo.ACTION_CLICK)==true){settle();return};node=node?.parent}
            }
            nodes().firstOrNull {it.isScrollable}?.performAction(AccessibilityNodeInfo.ACTION_SCROLL_FORWARD)
            Thread.sleep(100)
        }
        runCatching{capture("failure-action",628)}
        fail("Missing platform action $label\n${describe()}")
    }
    private fun state(): WegoState {
        val packs=listOf(PackCodec.decode(instrumentation.targetContext.assets.open("packs/01-city-story.json").use {PackCodec.read(it)}))
        return WegoState(packs=packs,selectedKey=packs.first().key,setupAllowed=true,storageReady=true,locationConsented=true)
    }
    private fun capture(name: String,widthDp: Int) {
        val window=activity.window
        val image=Bitmap.createBitmap(window.decorView.width,window.decorView.height,Bitmap.Config.ARGB_8888)
        var status=-1;val done=CountDownLatch(1)
        PixelCopy.request(window,image,{status=it;done.countDown()},Handler(Looper.getMainLooper()))
        assertTrue(done.await(5,TimeUnit.SECONDS));assertEquals(PixelCopy.SUCCESS,status)
        val width=(widthDp*activity.resources.displayMetrics.density).toInt().coerceAtMost(image.width)
        val cropped=Bitmap.createBitmap(image,0,0,width,image.height)
        File(activity.cacheDir,"platform-$name.png").outputStream().use {cropped.compress(Bitmap.CompressFormat.PNG,100,it)}
        if(cropped!==image)cropped.recycle();image.recycle()
    }
    fun testActualRootMenusStayConsistent() {
        start()
        val fixture=state().copy(accountProfile=AccountProfileState(AccountReadStatus.READY,"나",true,
            vehicle=io.wegoh.app.nativeauth.VehicleProfile("123가4567","","나의 차",1)))
        val roots=listOf("home","discover","rooms","car","profile")
        for(route in roots) {
            instrumentation.runOnMainSync {activity.setContent {key(route) {WegoCarTheme {
                PlatformScreen(fixture,route) {exit->WegoVehicleScreen(fixture,{},{},{},{},{},{},{},{},{},onRootBack=exit,
                    onAccountProfile={},onAccountDiscovery={})}
            }}}}
            settle();click("전체 메뉴")
            for(label in listOf("경로","발견","여행방","내 차","프로필"))awaitVisible(label)
            assertFalse(visible("만들기"));assertFalse(visible("새 계정 이름"));assertFalse(visible("차량 번호 입력"))
            instrumentation.sendKeyDownUpSync(android.view.KeyEvent.KEYCODE_BACK);settle()
            val end=System.currentTimeMillis()+3000
            while(nodes().any {it.isVisibleToUser && it.isCheckable && it.contentDescription?.toString()=="경로"} && System.currentTimeMillis()<end)Thread.sleep(80)
            capture("root-$route",1700)
        }
    }
    fun testFriendProfileKeepsFriendActionsWithoutRemoteGrants() {
        start()
        val friend=io.wegoh.app.nativeauth.SocialPerson("team-"+"b".repeat(40),"친구")
        val social=SocialPageState(AccountReadStatus.READY,io.wegoh.app.nativeauth.SocialOverview(emptyList(),listOf(friend),emptyList(),emptyList(),emptyList(),true,false,false,false),isCurrent=true)
        val fixture=state().copy(accountProfile=AccountProfileState(AccountReadStatus.READY,"나",true,vehicle=io.wegoh.app.nativeauth.VehicleProfile("123가4567","","나의 차",1)))
        instrumentation.runOnMainSync {activity.setContent {WegoCarTheme {PlatformScreen(fixture,"profile") {exit->
            WegoVehicleScreen(fixture,{},{},{},{},{},{},{},{},{},onRootBack=exit,socialState=social)
        }}}}
        settle();click("친구 관리");awaitVisible("나와 친구");capture("profile-list",1700)
        click("친구");awaitVisible("친구 연결 해제")
        assertFalse(visible("함께"));assertFalse(visible("휴대전화에서 함께 보기"))
        assertFalse(visible("내 차 리모컨"));assertFalse(visible("허용 상태 확인"));capture("friend-detail",1700)
        instrumentation.runOnMainSync {activity.onBackPressedDispatcher.onBackPressed()};settle();awaitVisible("나")
        click("나");awaitVisible("iPhone 앱의 설정 → 프로필에서 고쳐요")
        assertTrue(visible("나의 차"));assertTrue(visible("123가4567"))
        assertFalse(visible("휴대전화에서 변경"));assertFalse(visible("내 정보 변경"))
    }
    fun testFinalAppearanceVariants() {
        start()
        val friend=io.wegoh.app.nativeauth.SocialPerson("team-"+"b".repeat(40),"함께 가는 친구")
        val social=SocialPageState(AccountReadStatus.READY,io.wegoh.app.nativeauth.SocialOverview(emptyList(),listOf(friend),emptyList(),emptyList(),emptyList(),true,false,false,false),isCurrent=true)
        val fixture=state().copy(accountProfile=AccountProfileState(AccountReadStatus.READY,"나",true,vehicle=io.wegoh.app.nativeauth.VehicleProfile("123가4567","","나의 차",1)))
        for(width in listOf(1700,628))for(dark in listOf(false,true)) {
            instrumentation.runOnMainSync {activity.setContent {key("$width-$dark") {Box(Modifier.width(width.dp).fillMaxHeight()) {WegoCarTheme(dark=dark) {
                PlatformScreen(fixture,"profile") {exit->WegoVehicleScreen(fixture,{},{},{},{},{},{},{},{},{},onRootBack=exit,socialState=social)}
            }}}}}
            settle();awaitVisible("나");awaitVisible("함께 가는 친구");capture("final-${if(dark)"night" else "day"}-$width",width)
        }
        val restricted=fixture.copy(setupAllowed=false,policy="주행 중")
        instrumentation.runOnMainSync {activity.setContent {WegoCarTheme {WegoVehicleScreen(restricted,{},{},{},{},{},{},{},{},{})}}}
        settle();awaitVisible("P단에서 이용할 수 있어요");capture("final-restricted",1700)
    }
    fun testPhoneHandoffHasNoVehicleTextInput() {
        start();val fixture=state().copy(accountProfile=AccountProfileState(AccountReadStatus.READY,"나",true,
            vehicle=io.wegoh.app.nativeauth.VehicleProfile("123가4567","","나의 차",1)))
        var external=0
        instrumentation.runOnMainSync {activity.setContent {WegoCarTheme {PlatformScreen(fixture,"profile") {exit->
            WegoVehicleScreen(fixture,{},{},{},{},{external++},{},{external++},{},{},onRootBack=exit,
                onAccountProfile={},onAccountDiscovery={},onVehicleConnection={external++},
                onLegalDocument={external++},onPlatform={external++})
        }}}}
        settle();awaitVisible("iPhone 앱의 설정 → 프로필에서 고쳐요");assertFalse(visible("내 정보"))
        assertTrue(visible("나"));assertTrue(visible("나의 차"));assertTrue(visible("123가4567"))
        assertFalse(visible("휴대전화에서 변경"));assertFalse(visible("내 정보 변경"))
        assertFalse(visible("휴대전화에서 계속할 QR 코드"))
        assertFalse(visible("이름 변경"));assertFalse(visible("차량 번호 입력"))
        assertEquals("Passive profile hint does not invoke external navigation",0,external)
        capture("profile-inline-hint",1700)
    }
    fun testShortStateKeepsSecondaryActionReachable() {
        start();var continued=false
        instrumentation.runOnMainSync {activity.setContent {WegoCarTheme {
            Box(Modifier.width(628.dp).height(300.dp).background(LocalCarPalette.current.background)) {
                SocialPreparation(SocialPageState(AccountReadStatus.UNAVAILABLE),{},{continued=true})
            }
        }}}
        settle();click("휴대전화에서 확인");assertTrue(continued)
    }
}
