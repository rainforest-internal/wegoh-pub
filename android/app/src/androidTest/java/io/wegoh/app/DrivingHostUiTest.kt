package io.wegoh.app

import android.content.Intent
import android.accessibilityservice.AccessibilityServiceInfo
import android.content.res.Configuration
import android.graphics.Bitmap
import android.graphics.Rect
import android.test.InstrumentationTestCase
import android.view.View
import android.view.ViewGroup
import android.view.MotionEvent
import android.view.inspector.WindowInspector
import android.view.accessibility.AccessibilityNodeInfo
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.boundsInWindow
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.*
import androidx.compose.ui.semantics.*
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import io.wegoh.app.nativeauth.*
import io.wegoh.app.ui.*
import java.io.File
import kotlin.math.min
import kotlin.math.roundToInt

@Suppress("DEPRECATION")
class DrivingHostUiTest: InstrumentationTestCase() {
    private lateinit var host: SafFrameworkHarnessActivity
    private var previousAccessibilityFlags=0
    private var scene=0
    private var frame=Rect()
    private val presets=listOf(1700 to 1184,840 to 1184,1360 to 948,672 to 948,1274 to 855,628 to 855,
        1640 to 810,800 to 810,1640 to 1400,800 to 1400,1256 to 800,648 to 800)
    private val course=TripCourse("coast","서해안 해안도로 코스",1,3,"사용자A",completedCarIds=emptyList(),stops=listOf(
        TripCourseStop("ganwol","간월암",36.61,126.39),TripCourseStop("kkotji","꽃지해수욕장",36.50,126.33),TripCourseStop("daecheon","대천해수욕장",36.31,126.51)))
    private val car=TripCar("car-one","1호차 · 사용자A의 차","user-a","사용자A",2,true,false,
        listOf(TripPassenger("user-c","사용자C",false),TripPassenger("user-d","사용자D",false)))
    private val trip=TripDetail("trip","서해안 드라이브","",listOf(TripMember("user-a","사용자A",true,true,true),
        TripMember("user-c","사용자C",true,false,false),TripMember("user-d","사용자D",true,false,false)),listOf(car),
        state="active",revision=1,courses=listOf(course))
    private val drive=TripDrivingState(TripDrivingPhase.NEAR,"course:coast:ganwol",250.0,true,remainingSeconds=60)
    private fun state()=TripsPageState(status=AccountReadStatus.READY,detail=trip,isCurrent=true,gear=TripGear.PARK,driving=drive)
    override fun setUp() {
        super.setUp()
        val info=instrumentation.uiAutomation.serviceInfo
        previousAccessibilityFlags=info.flags
        info.flags=info.flags or AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
        instrumentation.uiAutomation.serviceInfo=info
        host=instrumentation.startActivitySync(Intent(instrumentation.targetContext,SafFrameworkHarnessActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_MULTIPLE_TASK)) as SafFrameworkHarnessActivity
    }
    override fun tearDown() {
        try {
            instrumentation.runOnMainSync {host.setContent {};host.finish()}
            instrumentation.waitForIdleSync()
        } finally {
            val info=instrumentation.uiAutomation.serviceInfo
            info.flags=previousAccessibilityFlags
            instrumentation.uiAutomation.serviceInfo=info
            super.tearDown()
        }
    }
    private fun await(message: String,condition: ()->Boolean) {
        val end=android.os.SystemClock.uptimeMillis()+8000
        while(android.os.SystemClock.uptimeMillis()<end) {if(condition())return;Thread.sleep(50)}
        fail(message)
    }
    private fun nodes(): List<AccessibilityNodeInfo> {
        instrumentation.uiAutomation.clearCache()
        val nodes=mutableListOf<AccessibilityNodeInfo>()
        fun add(n: AccessibilityNodeInfo?) {if(n!=null){nodes+=n;for(i in 0 until n.childCount)add(n.getChild(i))}}
        val roots=instrumentation.uiAutomation.windows.mapNotNull {it.root}
            .filter {it.packageName?.toString()==instrumentation.targetContext.packageName}
        if(roots.isEmpty())instrumentation.uiAutomation.rootInActiveWindow
            ?.takeIf {it.packageName?.toString()==instrumentation.targetContext.packageName}?.let(::add)
        else roots.forEach(::add)
        return nodes
    }
    private fun visible(label: String)=nodes().any {it.isVisibleToUser && (it.text?.toString()==label || it.contentDescription?.toString()==label)}
    private fun render(width: Int,height: Int,content: @Composable ()->Unit) {
        instrumentation.runOnMainSync {val version=++scene;host.setContent {key(version) {
            BoxWithConstraints(Modifier.fillMaxSize().background(Color.Black),contentAlignment=Alignment.Center) {
                val scale=min(constraints.maxWidth.toFloat()/width,constraints.maxHeight.toFloat()/height)
                val config=Configuration(LocalConfiguration.current).apply {screenWidthDp=width;screenHeightDp=height;fontScale=1f}
                CompositionLocalProvider(LocalDensity provides Density(scale),LocalConfiguration provides config) {
                    Box(Modifier.requiredSize(width.dp,height.dp).onGloballyPositioned {c->
                        val b=c.boundsInWindow();val origin=IntArray(2);host.window.decorView.getLocationOnScreen(origin)
                        frame=Rect(b.left.roundToInt()+origin[0],b.top.roundToInt()+origin[1],b.right.roundToInt()+origin[0],b.bottom.roundToInt()+origin[1])
                    }) {WegoCarTheme(false) {TripSurface {content()}}}
                }
            }
        }}};instrumentation.waitForIdleSync()
    }
    private fun screenshot(name: String) {
        val root=host.window.decorView
        val marker=java.util.concurrent.CountDownLatch(1)
        instrumentation.runOnMainSync {root.postOnAnimation {root.postOnAnimation {marker.countDown()}}}
        assertTrue(marker.await(3,java.util.concurrent.TimeUnit.SECONDS))
        await("screenshot host focus") {host.hasWindowFocus() && !frame.isEmpty}
        val deadline=android.os.SystemClock.uptimeMillis()+5000
        var captured: Bitmap?=null
        var captureFailure: NullPointerException?=null
        while(captured==null && android.os.SystemClock.uptimeMillis()<deadline) {
            try {captured=instrumentation.uiAutomation.takeScreenshot()}
            catch(error: NullPointerException) {captureFailure=error}
            if(captured==null)Thread.sleep(80)
        }
        val bitmap=captured ?: throw AssertionError("Screenshot capture did not return a frame within 5 seconds",captureFailure)
        val crop=Bitmap.createBitmap(bitmap,frame.left,frame.top,frame.width(),frame.height())
        val folder=File(instrumentation.targetContext.filesDir,"driving-host").apply {mkdirs()}
        File(folder,"$name.png").outputStream().use {crop.compress(Bitmap.CompressFormat.PNG,100,it)}
        crop.recycle();bitmap.recycle()
    }
    private data class Button(val disabled: Boolean,val bounds: Rect)
    private fun button(label: String,inDialog: Boolean=false): Button {
        var result: Button?=null
        instrumentation.runOnMainSync {
            fun inspect(v: View) {
                if(v is ViewRootForTest) v.semanticsOwner.getAllSemanticsNodes(mergingEnabled=false).firstOrNull {
                    it.config.contains(SemanticsActions.OnClick) && it.config.getOrNull(SemanticsProperties.ContentDescription)?.contains(label)==true
                }?.let {n->val b=n.boundsInWindow;val origin=IntArray(2);v.rootView.getLocationOnScreen(origin)
                    result=Button(n.config.contains(SemanticsProperties.Disabled),Rect(b.left.roundToInt()+origin[0],b.top.roundToInt()+origin[1],b.right.roundToInt()+origin[0],b.bottom.roundToInt()+origin[1]))}
                if(v is ViewGroup)for(i in 0 until v.childCount)inspect(v.getChildAt(i))
            }
            if(inDialog)WindowInspector.getGlobalWindowViews().filter {it!==host.window.decorView && it.isShown}.forEach(::inspect)
            else inspect(host.window.decorView)
        }
        return requireNotNull(result) {"Button missing: $label"}
    }
    private fun tap(button: Button) {
        val down=android.os.SystemClock.uptimeMillis()
        for((action,time) in listOf(MotionEvent.ACTION_DOWN to down,MotionEvent.ACTION_UP to down+50)) {
            val event=MotionEvent.obtain(down,time,action,button.bounds.exactCenterX(),button.bounds.exactCenterY(),0)
            try {instrumentation.sendPointerSync(event)}finally {event.recycle()}
        }
        instrumentation.waitForIdleSync()
    }
    fun testDrivingHostHidesOnBackAndBlocksTabsAndSendingUntilCarUxIsRead() {
        var backs=0;var voiceAllowed=true
        val driving=state().copy(gear=TripGear.DRIVE,liveCourseId=course.packId,liveCourseScore=CourseDrivingResult(1,1,60_000))
        render(1700,1184) {
            WegoVehicleScreen(WegoState(setupAllowed=false,storageReady=true),
                onSelect={},onImport={},onStart={},onStop={},onNavigate={},onReset={},onBrowse={},onDownload={},onShareVisits={},
                tripsState=driving,onRootBack={backs++},tripVoice={_,allowed,modifier->
                    voiceAllowed=allowed;CarButton("합성 음성",{},modifier,enabled=allowed)
                })
        }
        await("read-only driving host") {visible("주행 전용 화면") && visible("90점")}
        assertFalse(voiceAllowed)
        assertFalse(visible("여행 탭"));assertFalse(visible("프로필 탭"));assertFalse(visible("도착했어요"))
        tap(button("손들기"));await("car ux pending message") {visible("주행 제한 확인 중")}
        await("dialog close button") {runCatching {button("닫기",inDialog=true)}.isSuccess}
        tap(button("닫기",inDialog=true))
        await("driving host after dialog") {host.hasWindowFocus() && !visible("주행 제한 확인 중")}
        instrumentation.sendKeyDownUpSync(android.view.KeyEvent.KEYCODE_BACK)
        // Pleos Back policy: the top-level driving host hides the app instead of consuming Back.
        instrumentation.waitForIdleSync();assertEquals(1,backs)
        assertTrue(visible("주행 전용 화면"));screenshot("root-driving")
    }
    fun testDrivingLayoutsAcrossAllFormFactors() {
        val driving=state().copy(gear=TripGear.DRIVE,liveCourseId=course.packId,liveCourseScore=CourseDrivingResult(1,1,60_000))
        for((w,h) in presets) {
            render(w,h) {Box(Modifier.fillMaxSize().padding(CarTokens.Frame)) {TripDrivingDashboard(trip,driving,{})}}
            await("driving score at $w x $h") {visible("90점") && visible("안전운전 점수")}
            val hands=button("손들기");val voice=button("워키토키")
            assertEquals("equal driving button widths",hands.bounds.width().toDouble(),voice.bounds.width().toDouble(),2.0)
            assertTrue("driving touch height",hands.bounds.height()>=CarTokens.ButtonDrivingCompact.value*frame.width()/w-2)
            screenshot("driving-${w}x$h")
        }
    }
    fun testUnavailableDrivingScoreHasNoInventedPerfectScore() {
        val driving=state().copy(gear=TripGear.DRIVE,liveCourseId=course.packId,liveCourseScore=null)
        render(648,800) {Box(Modifier.fillMaxSize().padding(CarTokens.Frame)) {TripDrivingDashboard(trip,driving,{})}}
        await("waiting for measurement") {visible("측정 대기")}
        assertFalse(visible("100점"));screenshot("driving-unavailable")
    }

}
