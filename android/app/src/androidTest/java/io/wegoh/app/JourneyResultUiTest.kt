package io.wegoh.app

import android.content.Intent
import android.content.res.Configuration
import android.graphics.Bitmap
import android.graphics.Rect
import android.test.InstrumentationTestCase
import android.view.View
import android.view.ViewGroup
import android.view.MotionEvent
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
class JourneyResultUiTest: InstrumentationTestCase() {
    private lateinit var host: SafFrameworkHarnessActivity
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
        host=instrumentation.startActivitySync(Intent(instrumentation.targetContext,SafFrameworkHarnessActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_MULTIPLE_TASK)) as SafFrameworkHarnessActivity
    }
    override fun tearDown() {try {instrumentation.runOnMainSync {host.setContent {};host.finish()}}finally {super.tearDown()}}
    private fun await(message: String,condition: ()->Boolean) {
        val end=android.os.SystemClock.uptimeMillis()+8000
        while(android.os.SystemClock.uptimeMillis()<end) {if(condition())return;Thread.sleep(50)}
        fail(message)
    }
    private fun nodes(): List<AccessibilityNodeInfo> {
        instrumentation.uiAutomation.clearCache()
        val nodes=mutableListOf<AccessibilityNodeInfo>()
        fun add(n: AccessibilityNodeInfo?) {if(n!=null){nodes+=n;for(i in 0 until n.childCount)add(n.getChild(i))}}
        add(instrumentation.uiAutomation.rootInActiveWindow)
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
        val bitmap=requireNotNull(instrumentation.uiAutomation.takeScreenshot())
        val crop=Bitmap.createBitmap(bitmap,frame.left,frame.top,frame.width(),frame.height())
        val folder=File(instrumentation.targetContext.filesDir,"journey-result").apply {mkdirs()}
        File(folder,"$name.png").outputStream().use {crop.compress(Bitmap.CompressFormat.PNG,100,it)}
        crop.recycle();bitmap.recycle()
    }
    private data class Button(val disabled: Boolean,val bounds: Rect)
    private fun button(label: String): Button {
        var result: Button?=null
        instrumentation.runOnMainSync {
            fun inspect(v: View) {
                if(v is ViewRootForTest) v.semanticsOwner.getAllSemanticsNodes(mergingEnabled=false).firstOrNull {
                    it.config.contains(SemanticsActions.OnClick) && it.config.getOrNull(SemanticsProperties.ContentDescription)?.contains(label)==true
                }?.let {n->val b=n.boundsInWindow;val origin=IntArray(2);v.rootView.getLocationOnScreen(origin)
                    result=Button(n.config.contains(SemanticsProperties.Disabled),Rect(b.left.roundToInt()+origin[0],b.top.roundToInt()+origin[1],b.right.roundToInt()+origin[0],b.bottom.roundToInt()+origin[1]))}
                if(v is ViewGroup)for(i in 0 until v.childCount)inspect(v.getChildAt(i))
            };inspect(host.window.decorView)
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
    private val finished=trip.copy(state="completed",courses=listOf(course.copy(completedCarIds=listOf(car.id))),
        display=TripDisplay(emptyList(),3,TripMetrics(13.0,600.0),null,emptyList(),endedAt="2026-11-13T00:00:00Z"))
    private val tripScore=CourseDrivingResult(1,1,60_000,completed=true)
    fun testResultLayoutsAcrossAllFormFactors() {
        for((w,h) in presets) {
            render(w,h) {Box(Modifier.fillMaxSize().padding(CarTokens.Frame)) {TripResultPage(finished,{},tripScore) {TripText("합성 여행 기록")}}}
            await("result statistics at $w x $h") {visible("주행 기록") && visible("13 km")}
            assertTrue(visible("달린 거리"));assertTrue(visible("운전 시간"));assertTrue(visible("들른 곳"))
            screenshot("result-${w}x$h")
        }
    }
    fun testResultHistoryAndHomeActionsRemainAvailable() {
        var homes=0
        render(1700,1184) {Box(Modifier.fillMaxSize().padding(CarTokens.Frame)) {TripResultPage(finished,{homes++},tripScore) {TripText("합성 여행 기록")}}}
        await("result actions") {visible("여행 기록")}
        assertTrue(visible("최종 90점"));assertTrue(visible("급가속 1회"));assertTrue(visible("급감속 1회"))
        assertFalse(visible("휴대전화로 이어 하기"))
        tap(button("여행 기록"));await("history") {visible("합성 여행 기록")}
        instrumentation.sendKeyDownUpSync(android.view.KeyEvent.KEYCODE_BACK)
        await("result after back") {visible("주행 기록")}
        tap(button("여행 홈으로"));await("home callback") {homes==1}
    }
}
