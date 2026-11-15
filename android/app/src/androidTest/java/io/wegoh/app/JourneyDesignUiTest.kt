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
class JourneyDesignUiTest: InstrumentationTestCase() {
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
        val folder=File(instrumentation.targetContext.filesDir,"journey-design").apply {mkdirs()}
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
    private fun assertCompanionTextLayout(label: String,singleLine: Boolean=false) {
        val layouts=mutableListOf<androidx.compose.ui.text.TextLayoutResult>()
        instrumentation.runOnMainSync {
            fun inspect(view: View) {
                if(view is ViewRootForTest)view.semanticsOwner.getAllSemanticsNodes(mergingEnabled=false).filter {
                    it.config.getOrNull(SemanticsProperties.Text)?.any {text->text.text==label}==true
                }.forEach {node->node.config.getOrNull(SemanticsActions.GetTextLayoutResult)?.action?.invoke(layouts)}
                if(view is ViewGroup)for(i in 0 until view.childCount)inspect(view.getChildAt(i))
            }
            inspect(host.window.decorView)
        }
        assertTrue("Companion text layout exists: $label",layouts.isNotEmpty())
        layouts.forEach {
            assertFalse("Companion text is fully readable: $label",it.hasVisualOverflow)
            if(singleLine)assertEquals("Normal car name keeps its readable width",1,it.lineCount)
        }
    }
    private fun scrollVertically(): Boolean {
        var range: ScrollAxisRange?=null
        var before=0f
        var canAdvance=false
        var accepted=false
        instrumentation.runOnMainSync {
            fun inspect(view: View) {
                if(view is ViewRootForTest && range==null)view.semanticsOwner.getAllSemanticsNodes(mergingEnabled=false).firstOrNull {
                    it.config.getOrNull(SemanticsProperties.VerticalScrollAxisRange)!=null &&
                        it.config.getOrNull(SemanticsActions.ScrollBy)?.action!=null && it.boundsInWindow.height>0
                }?.let {node->
                    val axis=checkNotNull(node.config.getOrNull(SemanticsProperties.VerticalScrollAxisRange))
                    range=axis;before=axis.value()
                    val remaining=axis.maxValue()-before
                    canAdvance=remaining>0
                    if(canAdvance)accepted=node.config.getOrNull(SemanticsActions.ScrollBy)?.action
                        ?.invoke(0f,minOf(node.boundsInWindow.height/3f,remaining))==true
                }
                if(view is ViewGroup)for(i in 0 until view.childCount)inspect(view.getChildAt(i))
            }
            inspect(host.window.decorView)
        }
        assertNotNull("The host has vertical scroll semantics",range)
        if(!canAdvance)return false
        assertTrue("The vertical scroll action is accepted",accepted)
        instrumentation.uiAutomation.waitForIdle(100,1500)
        instrumentation.waitForIdleSync()
        var after=before
        var stableSince=android.os.SystemClock.uptimeMillis()
        try {
            await("The visible content advances vertically: before=$before max=${checkNotNull(range).maxValue()}") {
                var value=before
                instrumentation.runOnMainSync {value=checkNotNull(range).value()}
                if(value!=after) {after=value;stableSince=android.os.SystemClock.uptimeMillis()}
                after>before && android.os.SystemClock.uptimeMillis()-stableSince>=200
            }
        } catch(error: AssertionError) {
            runCatching {screenshot("active-scroll-failure")}
            throw error
        }
        return true
    }
    private fun scrollUntil(message: String,condition: ()->Boolean) {
        repeat(24) {
            if(condition())return
            assertTrue("$message: reached the end before the target",scrollVertically())
        }
        assertTrue(message,condition())
    }
    fun testCompanionReadabilityAndNarrowScrollReachability() {
        val name=car.name
        val statuses=listOf("내 차","250m 남음","1분 남음")
        render(1256,800) {TripActivePage(trip,state(),true,TripUiActions(),{},{},{})}
        await("wide companion values") {host.hasWindowFocus() && frame.width()>frame.height() && visible(name) && statuses.all(::visible)}
        assertCompanionTextLayout(name,singleLine=true)
        statuses.forEach {assertCompanionTextLayout(it)}
        screenshot("active-companion-1256x800")
        var departures=0
        render(648,800) {TripActivePage(trip,state(),true,TripUiActions(),{},{departures++},{})}
        await("narrow initial route") {host.hasWindowFocus() && frame.width()<frame.height() && visible("현재 경로")}
        assertFalse("Companions start below the narrow route",visible("함께 가는 차"))
        scrollUntil("scroll reaches narrow companions") {visible(name) && statuses.all(::visible)}
        assertCompanionTextLayout(name)
        statuses.forEach {assertCompanionTextLayout(it)}
        screenshot("active-companion-narrow-scrolled")
        scrollUntil("scroll reaches narrow departure action") {
            val action=runCatching {button("경로 순서")}.getOrNull()
            action!=null && !action.disabled && frame.contains(action.bounds) &&
                action.bounds.height()>=CarTokens.Touch.value*frame.width()/648f-2
        }
        tap(button("경로 순서"))
        await("one departure callback") {departures==1}
        screenshot("active-narrow-actions-scrolled")
    }
    fun testActiveLayoutAcrossAllFormFactors() {
        for((w,h) in presets) {
            render(w,h) {TripActivePage(trip,state(),true,TripUiActions(),{},{},{})}
            await("active heading $w x $h") {visible("서해안 드라이브") && visible("현재 경로")}
            if(w>=CarTokens.Breakpoint.value) {
                await("wide companion column $w x $h") {visible("함께 가는 차")}
                val companion=nodes().first {it.text?.toString()=="함께 가는 차"}
                val bounds=Rect();companion.getBoundsInScreen(bounds)
                assertTrue("Companions use the right column in a wide window",bounds.left>frame.centerX())
            }
            screenshot("active-${w}x$h")
        }
    }
    fun testActiveButtonsKeepDisabledCallbacksBlocked() {
        var navigation=0;var arrivals=0
        val actions=TripUiActions(navigate={navigation++},arrive={arrivals++})
        render(1700,1184) {TripActivePage(trip,state(),false,actions,{},{},{})}
        await("disabled arrival") {host.hasWindowFocus() && runCatching {button("도착했어요").let {it.disabled && frame.contains(it.bounds)}}.getOrDefault(false)}
        val disabled=button("도착했어요");assertTrue(disabled.disabled);tap(disabled)
        assertEquals(0,arrivals)
        render(1700,1184) {TripActivePage(trip,state(),true,actions,{},{},{})}
        await("enabled navigation") {host.hasWindowFocus() && runCatching {button("간월암 길 안내").let {!it.disabled && frame.contains(it.bounds)}}.getOrDefault(false)}
        val navigationButton=button("간월암 길 안내");assertFalse(navigationButton.disabled);tap(navigationButton)
        await("navigation callback") {navigation==1}
        tap(button("도착했어요"));await("arrival callback") {arrivals==1}
    }
}
