package io.wegoh.app

import android.content.Intent
import android.graphics.Rect
import android.test.InstrumentationTestCase
import android.view.accessibility.AccessibilityNodeInfo
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.unit.dp
import io.wegoh.app.ui.*
import java.io.File

/** UI fixtures only: never evidence of real driving-state or SDK transitions. */
@Suppress("DEPRECATION")
class DesignContractTests : InstrumentationTestCase() {
    private lateinit var activity: MainActivity
    private fun nodes(): List<AccessibilityNodeInfo> {
        val service=instrumentation.uiAutomation.serviceInfo
        service.flags=service.flags or android.accessibilityservice.AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
        instrumentation.uiAutomation.serviceInfo=service
        if(android.os.Build.VERSION.SDK_INT>=34)instrumentation.uiAutomation.clearCache()
        val result=mutableListOf<AccessibilityNodeInfo>()
        fun walk(node: AccessibilityNodeInfo?) { if(node!=null){result.add(node);for(i in 0 until node.childCount)walk(node.getChild(i))} }
        instrumentation.uiAutomation.windows.sortedByDescending {it.layer}.forEach {window->
            window.root?.takeIf {it.packageName?.toString()==activity.packageName}?.let(::walk)
        }
        return result
    }
    private fun visible(label: String)=nodes().any{it.isVisibleToUser && (it.text?.toString()==label || it.contentDescription?.toString()==label)}
    private fun awaitVisible(label: String) {
        val deadline=System.currentTimeMillis()+7000
        while(System.currentTimeMillis()<deadline){if(visible(label))return
            nodes().firstOrNull {it.isScrollable}?.performAction(AccessibilityNodeInfo.ACTION_SCROLL_FORWARD)
            Thread.sleep(100)}
        capture("failure-visible")
        fail("Missing visible UI: $label\n"+nodes().joinToString("\n"){"${it.text}|${it.contentDescription}|clickable=${it.isClickable}"})
    }
    private fun click(label: String) {
        val deadline=System.currentTimeMillis()+10000
        while(System.currentTimeMillis()<deadline) {
            var node=nodes().firstOrNull{it.isVisibleToUser && (it.text?.toString()==label || it.contentDescription?.toString()==label)}
            repeat(5) { if(node?.performAction(AccessibilityNodeInfo.ACTION_CLICK)==true){settle();return};node=node?.parent }
            nodes().firstOrNull {it.isScrollable}?.performAction(AccessibilityNodeInfo.ACTION_SCROLL_FORWARD)
            Thread.sleep(200)
        }
        fail("Missing actionable UI: $label")
    }
    private fun settle() { instrumentation.waitForIdleSync();Thread.sleep(600) }
    private fun start() {
        // Each fixture owns a fresh Activity/lifecycle; do not reuse a finishing
        // task or another fixture's OnBackPressedDispatcher. App data is retained.
        activity=instrumentation.startActivitySync(Intent(instrumentation.targetContext,MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
    }
    private fun pack()=PackRepository(instrumentation.targetContext).list().first().copy(
        title="긴 여정 이름 ".repeat(10),description="MAIN_MUST_NOT_SHOW_DESCRIPTION")
    private fun capture(name: String) {
        val image=instrumentation.uiAutomation.takeScreenshot() ?: error("Screenshot unavailable")
        File(activity.cacheDir,"design-$name.png").outputStream().use { image.compress(android.graphics.Bitmap.CompressFormat.PNG,100,it) }
        image.recycle()
    }
    fun testCourseListScrollAndSelection() {
        start()
        val courses=(0 until 30).map {pack().copy(id="scroll-$it",title="코스 $it")}
        val state=mutableStateOf(WegoState(packs=courses,selectedKey=courses.first().key,setupAllowed=true,storageReady=true))
        instrumentation.runOnMainSync {activity.setContent {WegoCarTheme {WegoVehicleScreen(state.value,
            {key->state.value=state.value.copy(selectedKey=key)},{},{},{},{},{},{},{},{})}}}
        settle();click("코스 29")
        assertEquals(courses.last().key,state.value.selectedKey)
        val chosen=nodes().first {it.contentDescription?.toString()=="코스 29"}
        assertTrue("Choice must expose RadioButton state",chosen.isCheckable);assertTrue("Choice must expose checked state",chosen.isChecked)
        assertFalse(visible("경로 목록 위로"));assertFalse(visible("경로 목록 아래로"))
        capture("scroll-course-choice")
    }
    fun testRestrictionClosesMenusAndExposesOnlyStop() {
        start()
        val pack=pack()
        val state=mutableStateOf(WegoState(packs=listOf(pack),selectedKey=pack.key,setupAllowed=true,storageReady=true,locationConsented=true,visitedCount=1))
        var started=false
        instrumentation.runOnMainSync { activity.setContent { WegoCarTheme { WegoVehicleScreen(state.value,{}, {},{started=true},{},{},{},{},{},{}) } } }
        settle();click("전체 메뉴");awaitVisible("여행방")
        instrumentation.runOnMainSync { state.value=state.value.copy(setupAllowed=false,active=true,completed=setOf(pack.stops.first().id)) }
        settle()
        listOf("전체 메뉴","더보기","휴대전화에서 계속","방문 기록","출발","도착 알림","둘러보기","진단").forEach {assertFalse("Restricted: $it",visible(it))}
        assertTrue(visible("종료"));assertFalse(started);assertTrue(visible(pack.stops.last().name))
        capture("restricted-fixture")
        instrumentation.runOnMainSync { state.value=state.value.copy(setupAllowed=true,storageReady=true,locationConsented=true,active=false) }
        settle();assertFalse("Do not reopen stale menu",visible("휴대전화에서 계속"))
    }
    fun testNarrowLayoutKeepsActionsInsideAppWindow() {
        start();val pack=pack();var started=false;var rootBack=false;var navigated=0
        instrumentation.runOnMainSync { activity.setContent { WegoCarTheme {
            Box(Modifier.width(560.dp).fillMaxHeight()) { WegoVehicleScreen(
                WegoState(packs=listOf(pack),selectedKey=pack.key,setupAllowed=true,storageReady=true,locationConsented=true,completed=pack.stops.map {it.id}.toSet(),location="RAW_COORDINATES",history=listOf("RAW_LOG")),
                {},{},{started=true},{},{navigated++},{},{},{},{},onRootBack={rootBack=true}) }
        } } }
        settle();click(pack.title)
        assertTrue(visible("출발"));assertTrue(visible("도착 알림"));assertTrue(visible("뒤로"))
        assertTrue("Whole-course card must show the first place despite completed records",nodes().count {it.isVisibleToUser && it.text?.toString()==pack.stops.first().name}>=2)
        listOf("MAIN_MUST_NOT_SHOW_DESCRIPTION","RAW_COORDINATES","RAW_LOG").forEach{assertFalse(visible(it))}
        val back=Rect();nodes().first {it.contentDescription?.toString()=="뒤로"}.getBoundsInScreen(back)
        for(label in listOf("출발","도착 알림")) {
            val rect=Rect();nodes().first{it.contentDescription?.toString()==label}.getBoundsInScreen(rect)
            assertTrue("Action must remain in 560dp pane: $rect",rect.left>=back.left && rect.right<=back.left+560 && rect.width()>=80 && rect.height()>=80)
        }
        capture("narrow-fixture");click("출발");assertEquals(1,navigated);assertFalse(started)
        click("도착 알림");assertTrue(started)
        assertTrue("Back owner must be resumed: ${activity.lifecycle.currentState}",activity.lifecycle.currentState.isAtLeast(androidx.lifecycle.Lifecycle.State.RESUMED))
        instrumentation.runOnMainSync {activity.onBackPressedDispatcher.onBackPressed()};settle()
        capture("back-after-fixture")
        assertFalse("Back returns to list; root=$rootBack finishing=${activity.isFinishing}",visible("출발"));assertFalse(rootBack)
        instrumentation.runOnMainSync {activity.onBackPressedDispatcher.onBackPressed()};settle()
        assertTrue("Root delegates to task-hide handler",rootBack)
    }
    fun testDayNightContrastAndMinimalHome() {
        start();val pack=pack()
        for(dark in listOf(false,true)) {
            var palette: CarPalette?=null
            instrumentation.runOnMainSync { activity.setContent { WegoCarTheme(dark=dark) {
                palette=LocalCarPalette.current
                WegoVehicleScreen(WegoState(packs=listOf(pack),selectedKey=pack.key,setupAllowed=true,storageReady=true,locationConsented=true),{},{},{},{},{},{},{},{},{})
            } } }
            settle()
            if(!visible("출발"))click(pack.title)
            val p=palette!!
            fun contrast(a: androidx.compose.ui.graphics.Color,b: androidx.compose.ui.graphics.Color): Float {
                val x=a.luminance();val y=b.luminance();return (maxOf(x,y)+.05f)/(minOf(x,y)+.05f)
            }
            for(bg in listOf(p.background,p.low,p.selected)) {
                assertTrue("Primary contrast",contrast(p.text,bg)>=4.5f)
                assertTrue("Secondary contrast",contrast(p.secondary,bg)>=4.5f)
            }
            assertTrue(contrast(p.onButton,p.button)>=4.5f)
            assertFalse(visible("MAIN_MUST_NOT_SHOW_DESCRIPTION"))
            assertTrue(visible("출발"));assertTrue(visible("도착 알림"))
            capture(if(dark)"night-fixture" else "day-fixture")
        }
    }
    fun testConsentIsExplicitAndRestrictionDismissesIt() {
        start();val pack=pack();var started=0;var shared=0
        val state=mutableStateOf(WegoState(packs=listOf(pack),selectedKey=pack.key,
            setupAllowed=true,storageReady=true,locationConsented=false,visitedCount=1))
        instrumentation.runOnMainSync {activity.setContent {WegoCarTheme {WegoVehicleScreen(
            state.value,{},{},{started++},{},{},{},{},{},{shared++})}}}
        settle();if(!visible("도착 알림"))click(pack.title);click("도착 알림")
        assertTrue(visible("위치 사용"));assertEquals(0,started);assertEquals(0,shared)
        for(label in listOf("항목: 위치, 방문 장소와 시각, 진행 상태","목적: 장소 도착 확인과 여정 이어가기","보유: 동의 철회와 기록 삭제 전까지","거부할 수 있으며 위치 기반 실행은 제한됩니다"))awaitVisible(label)
        val confirm=Rect();nodes().first {it.contentDescription?.toString()=="동의하고 시작"}.getBoundsInScreen(confirm)
        val cancel=Rect();nodes().first {it.contentDescription?.toString()=="취소"}.getBoundsInScreen(cancel)
        val title=Rect();nodes().first {it.text?.toString()=="위치 사용"}.getBoundsInScreen(title)
        assertTrue("Official popup confirms on the left",confirm.right<cancel.left)
        assertTrue("Official popup title is centered",kotlin.math.abs(title.centerX()-(confirm.left+cancel.right)/2)<=2)
        capture("consent-fixture");click("취소");assertEquals(0,started)
        click("도착 알림")
        instrumentation.runOnMainSync {state.value=state.value.copy(setupAllowed=false)}
        settle();assertFalse(visible("동의하고 시작"));assertEquals(0,started)
        instrumentation.runOnMainSync {state.value=state.value.copy(setupAllowed=true)}
        settle();assertFalse(visible("동의하고 시작"))
        click("도착 알림");click("동의하고 시작");assertEquals(1,started);assertEquals(0,shared)
    }
    fun testWithdrawalNeedsSeparateConfirmationAndRestrictionCancelsIt() {
        start();val pack=pack();var erased=0;var paused=0;var settings=0
        val state=mutableStateOf(WegoState(packs=listOf(pack),selectedKey=pack.key,setupAllowed=true,storageReady=true,locationConsented=true))
        instrumentation.runOnMainSync {activity.setContent {WegoCarTheme {LocalCourseScreen(state.value,{},{},{},{},{},{},onBack={},
            onSuspendConsent={paused++},onWithdrawAndDelete={erased++},onSystemSettings={settings++},onLegalDocument={})}}}
        settle();click("전체 메뉴");assertFalse(visible("내 경로"));assertFalse(visible("내 음악"))
        click("개인정보");click("기기 설정");assertEquals(1,settings)
        click("위치 사용 일시중지");assertEquals(1,paused);assertEquals(0,erased)
        click("동의 철회 및 기록 삭제");awaitVisible("철회 및 삭제");assertEquals(0,erased)
        capture("withdrawal-confirm-fixture");click("취소");assertEquals(0,erased)
        click("동의 철회 및 기록 삭제")
        instrumentation.runOnMainSync {state.value=state.value.copy(setupAllowed=false)};settle()
        assertFalse(visible("철회 및 삭제"));assertEquals(0,erased)
        instrumentation.runOnMainSync {state.value=state.value.copy(setupAllowed=true)};settle()
        click("전체 메뉴");click("개인정보");click("동의 철회 및 기록 삭제");click("철회 및 삭제")
        assertEquals(1,erased)
    }
    fun testCourseReportingNeedsVerifiedOriginAndExplicitReason() {
        start();val pack=pack();var reports=0
        val state=mutableStateOf(WegoState(packs=listOf(pack),selectedKey=pack.key,setupAllowed=true,storageReady=true))
        instrumentation.runOnMainSync {activity.setContent {WegoCarTheme {WegoVehicleScreen(state.value,{},{},{},{},{},{},{},{},{},
            onReport={reason->assertEquals(CourseReportReason.OTHER,reason);reports++;state.value=state.value.copy(reportOutcome=CourseReportOutcome.FAILED)})}}}
        settle();click("더보기");assertFalse("Basic/imported courses must not expose reporting",visible("경로 신고"));click("닫기")
        instrumentation.runOnMainSync {state.value=state.value.copy(reportOrigin=VerifiedPackOrigin(pack.id,pack.version,"0".repeat(64)))}
        settle();click("더보기");click("경로 신고")
        for(label in listOf("유해 콘텐츠","개인정보","권리 침해","기타"))awaitVisible(label)
        assertEquals(0,reports);click("기타");click("신고");awaitVisible("신고를 보내지 못했습니다")
        assertEquals(1,reports);assertFalse(activity.controller.state.active)
        capture("report-failure-fixture");click("확인")
    }
    fun testStorageFailureLocksActionsAndKeepsNativeRecovery() {
        start();val pack=pack();var opened=false
        instrumentation.runOnMainSync {activity.setContent {WegoCarTheme {WegoVehicleScreen(
            WegoState(packs=listOf(pack),selectedKey=pack.key,setupAllowed=true,storageReady=false),
            {},{},{},{},{},{},{},{},{},onSystemSettings={opened=true})}}}
        settle()
        for(label in listOf("출발","도착 알림","더보기","둘러보기"))assertFalse(visible(label))
        capture("storage-error-fixture");click("기기 설정");assertTrue(opened)
    }
    override fun tearDown() { if(::activity.isInitialized)instrumentation.runOnMainSync{activity.finish()};super.tearDown() }
}
