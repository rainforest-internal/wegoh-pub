package io.wegoh.app

import android.content.Intent
import android.content.res.Configuration
import android.graphics.Bitmap
import android.graphics.Rect
import android.os.SystemClock
import android.test.InstrumentationTestCase
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.layout.boundsInWindow
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import io.wegoh.app.nativeauth.VehicleProfile
import io.wegoh.app.ui.*
import java.io.File
import kotlin.math.min
import kotlin.math.roundToInt

@Suppress("DEPRECATION")
class VehicleSecondaryFormFactorTest: InstrumentationTestCase() {
    private lateinit var activity: TripScreensPreviewActivity
    @Volatile private var frame=Rect()
    private var scene=0
    @Volatile private var laidOutScene=0
    @Volatile private var drawnScene=0
    private val sizes=listOf(1700 to 1184,840 to 1184,1360 to 948,672 to 948,1274 to 855,628 to 855,
        1640 to 810,800 to 810,1640 to 1400,800 to 1400,1256 to 800,648 to 800)

    override fun setUp() {
        super.setUp()
        activity=instrumentation.startActivitySync(Intent(instrumentation.targetContext,TripScreensPreviewActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_MULTIPLE_TASK)) as TripScreensPreviewActivity
    }
    override fun tearDown() {
        instrumentation.runOnMainSync {activity.setContent {};activity.finish()}
        super.tearDown()
    }
    private fun awaitStableHost() {
        val deadline=SystemClock.elapsedRealtime()+5000
        var previous: Pair<Rect,Rect>?=null
        var stableSince=0L
        while(SystemClock.elapsedRealtime()<deadline) {
            var current: Pair<Rect,Rect>?=null
            instrumentation.runOnMainSync {
                val view=activity.window.decorView
                val visible=Rect()
                if(activity.hasWindowFocus() && view.isShown && view.width>0 && view.height>0 && view.getLocalVisibleRect(visible)) {
                    val origin=IntArray(2);view.getLocationOnScreen(origin)
                    visible.offset(origin[0],origin[1])
                    current=Rect(origin[0],origin[1],origin[0]+view.width,origin[1]+view.height) to visible
                }
            }
            val now=SystemClock.elapsedRealtime()
            if(current==null) {previous=null;stableSince=0L}
            else if(current!=previous) {previous=current;stableSince=now}
            else if(now-stableSince>=500)return
            Thread.sleep(50)
        }
        throw AssertionError("Preview host did not retain focus and stable visible decor bounds for 500ms within 5 seconds")
    }
    private fun awaitScene(version: Int) {
        val deadline=SystemClock.elapsedRealtime()+5000
        while(SystemClock.elapsedRealtime()<deadline) {
            if(laidOutScene==version && drawnScene==version && frame.width()>0 && frame.height()>0)return
            Thread.sleep(40)
        }
        throw AssertionError("Preview scene $version did not lay out and draw within 5 seconds")
    }
    private fun screenshot(): Bitmap {
        val deadline=SystemClock.elapsedRealtime()+5000
        var lastFailure: NullPointerException?=null
        while(SystemClock.elapsedRealtime()<deadline) {
            try {instrumentation.uiAutomation.takeScreenshot()?.let {return it}}
            catch(error: NullPointerException) {lastFailure=error}
            Thread.sleep(80)
        }
        throw AssertionError("Screenshot provider did not return an image within 5 seconds").apply {
            lastFailure?.let {initCause(it)}
        }
    }
    private fun capture(page: String,width: Int,height: Int,content: @Composable ()->Unit) {
        if(scene==0)awaitStableHost()
        val version=++scene
        instrumentation.runOnMainSync {activity.setContent {key(version) {
            BoxWithConstraints(Modifier.fillMaxSize().background(Color.Black),contentAlignment=Alignment.Center) {
                val scale=min(constraints.maxWidth.toFloat()/width,constraints.maxHeight.toFloat()/height)
                val configuration=Configuration(LocalConfiguration.current).apply {
                    screenWidthDp=width;screenHeightDp=height;smallestScreenWidthDp=min(width,height)
                    orientation=if(width>=height)Configuration.ORIENTATION_LANDSCAPE else Configuration.ORIENTATION_PORTRAIT
                }
                CompositionLocalProvider(LocalDensity provides Density(scale,1f),LocalConfiguration provides configuration) {
                    Box(Modifier.requiredSize(width.dp,height.dp).drawWithContent {
                        drawContent();drawnScene=version
                    }.onGloballyPositioned {
                        val r=it.boundsInWindow();val origin=IntArray(2)
                        activity.window.decorView.getLocationOnScreen(origin)
                        frame=Rect(r.left.roundToInt()+origin[0],r.top.roundToInt()+origin[1],r.right.roundToInt()+origin[0],r.bottom.roundToInt()+origin[1])
                        laidOutScene=version
                    }) {WegoCarTheme(dark=false) {content()}}
                }
            }
        }}}
        awaitScene(version)
        awaitStableHost()
        val screen=screenshot()
        assertTrue("Preview remains inside display",frame.left>=0 && frame.top>=0 && frame.right<=screen.width && frame.bottom<=screen.height)
        val crop=Bitmap.createBitmap(screen,frame.left,frame.top,frame.width(),frame.height())
        val directory=File(instrumentation.targetContext.filesDir,"secondary-layout-preview").apply {mkdirs()}
        File(directory,"$page-${width}x$height.png").outputStream().use {crop.compress(Bitmap.CompressFormat.PNG,100,it)}
        crop.recycle();screen.recycle()
    }
    fun testMyCarAllFormFactors() {
        for((width,height) in sizes)capture("car",width,height) {
            VehicleCarPage(false,"",{},{},{_,_->},remoteHistory={VehicleRemoteHistoryList(emptyList())})
        }
    }
    fun testCoursesAllFormFactors() {
        val state=WegoState(setupAllowed=true,storageReady=true,accountCourses=AccountCourseState(AccountCourseStatus.READY,courses=listOf(
            AccountCourse(PublishedPack("coast",1,"서해안 해안도로 코스","사용자A","간월암 → 꽃지해수욕장 → 대천해수욕장",3,""),true),
            AccountCourse(PublishedPack("lake",1,"간월호 한 바퀴","사용자B","간월호 → 간월암",2,""),true),
            AccountCourse(PublishedPack("boryeong",1,"보령 해안도로","사용자E","대천해수욕장 → 무창포해수욕장",2,""),true))))
        for((width,height) in sizes)capture("courses",width,height) {VehicleCoursesPage(state,{},{},{},{},{},{},{})}
    }
    fun testProfileAllFormFactors() {
        val profile=AccountProfileState(AccountReadStatus.READY,"사용자A",vehicle=VehicleProfile("12가3456","","사용자A의 차",1))
        for((width,height) in sizes)capture("profile",width,height) {VehicleProfileOverview(profile,3,2,1,{},{},{})}
    }
}
