package io.wegoh.app

import android.content.Intent
import android.content.res.Configuration
import android.graphics.Bitmap
import android.graphics.Rect
import android.os.Build
import android.test.InstrumentationTestCase
import android.test.InstrumentationTestRunner
import android.view.View
import android.view.ViewGroup
import android.view.ViewTreeObserver
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.layout.boundsInWindow
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.ViewRootForTest
import androidx.compose.ui.semantics.*
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import io.wegoh.app.ui.*
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.math.min
import kotlin.math.roundToInt

@Suppress("DEPRECATION")
abstract class EntryDesignTestCase: InstrumentationTestCase() {
    protected lateinit var host: SafFrameworkHarnessActivity
    protected var frame=Rect()
    protected var scale=1f
    private var scene=0
    private var sceneBounds=Rect()
    private val allPresets=listOf(1700 to 1184,840 to 1184,1360 to 948,672 to 948,1274 to 855,628 to 855,
        1640 to 810,800 to 810,1640 to 1400,800 to 1400,1256 to 800,648 to 800)
    protected val presets: List<Pair<Int,Int>>
        get() {
            val requested=(instrumentation as InstrumentationTestRunner).arguments.getString("capturePreset") ?: return allPresets
            val selected=allPresets.singleOrNull {(width,height)->requested=="${width}x$height"}
                ?: throw AssertionError("Unknown capturePreset: $requested; choose ${allPresets.joinToString {"${it.first}x${it.second}"}}")
            return listOf(selected)
        }

    protected fun nodes(): List<SemanticsNode> {
        val out=mutableListOf<SemanticsNode>()
        instrumentation.runOnMainSync {
            fun inspect(view: View) {
                if(view is ViewRootForTest)out+=view.semanticsOwner.getAllSemanticsNodes(mergingEnabled=false)
                if(view is ViewGroup)for(i in 0 until view.childCount)inspect(view.getChildAt(i))
            }
            inspect(host.window.decorView)
        }
        return out
    }
    protected fun control(label: String)=nodes().single {it.config.contains(SemanticsActions.OnClick) &&
        it.config.getOrNull(SemanticsProperties.ContentDescription)?.contains(label)==true}
    protected fun bounds(node: SemanticsNode): Rect {
        val result=Rect()
        instrumentation.runOnMainSync {
            val r=node.boundsInWindow
            val origin=IntArray(2);host.window.decorView.getLocationOnScreen(origin)
            result.set(r.left.roundToInt()+origin[0],r.top.roundToInt()+origin[1],
                r.right.roundToInt()+origin[0],r.bottom.roundToInt()+origin[1])
        }
        return result
    }
    protected fun tap(label: String) {
        val action=requireNotNull(control(label).config.getOrNull(SemanticsActions.OnClick)?.action)
        var handled=false
        instrumentation.runOnMainSync {handled=action()}
        assertTrue("Semantic action handled: $label",handled)
        settle()
    }
    protected fun settle() {
        instrumentation.waitForIdleSync()
        if(Build.VERSION.SDK_INT<Build.VERSION_CODES.Q)throw AssertionError("Visible frame capture requires API 29 or newer")
        val committed=CountDownLatch(1)
        lateinit var observer: ViewTreeObserver
        lateinit var draw: ViewTreeObserver.OnPreDrawListener
        lateinit var focus: ViewTreeObserver.OnWindowFocusChangeListener
        instrumentation.runOnMainSync {
            val view=host.window.decorView
            assertTrue("Preview host must use hardware rendering",view.isHardwareAccelerated)
            observer=view.viewTreeObserver
            focus=ViewTreeObserver.OnWindowFocusChangeListener {focused->if(focused)view.invalidate()}
            draw=ViewTreeObserver.OnPreDrawListener {
                val visible=Rect()
                if(view.isAttachedToWindow && view.isShown && view.windowVisibility==View.VISIBLE &&
                    view.hasWindowFocus() && view.width>0 && view.height>0 && !view.isLayoutRequested &&
                    view.getGlobalVisibleRect(visible) && !visible.isEmpty) {
                    observer.removeOnPreDrawListener(draw)
                    observer.registerFrameCommitCallback {
                        view.post {view.postOnAnimation {committed.countDown()}}
                    }
                }
                true
            }
            observer.addOnWindowFocusChangeListener(focus)
            observer.addOnPreDrawListener(draw)
            view.invalidate()
        }
        try {
            assertTrue("Focused visible preview must commit a hardware frame",committed.await(5,TimeUnit.SECONDS))
        } finally {
            instrumentation.runOnMainSync {
                if(observer.isAlive) {
                    observer.removeOnPreDrawListener(draw)
                    observer.removeOnWindowFocusChangeListener(focus)
                }
            }
        }
        instrumentation.waitForIdleSync()
        instrumentation.runOnMainSync {
            val view=host.window.decorView
            assertTrue("Preview must remain focused and visible after its frame commits",view.hasWindowFocus() && view.isShown)
            updateFrame()
        }
    }
    private fun updateFrame() {
        val origin=IntArray(2)
        host.window.decorView.getLocationOnScreen(origin)
        frame=Rect(sceneBounds).apply {offset(origin[0],origin[1])}
    }
    protected fun render(width: Int,height: Int,night: Boolean,entry: Boolean=true,content: @Composable ()->Unit) {
        val drawn=CountDownLatch(1)
        instrumentation.runOnMainSync {
            frame=Rect()
            sceneBounds=Rect()
            val version=++scene
            host.setContent {key(version) {
                BoxWithConstraints(Modifier.fillMaxSize(),contentAlignment=Alignment.Center) {
                    scale=min(constraints.maxWidth.toFloat()/width,constraints.maxHeight.toFloat()/height)
                    val configuration=Configuration(LocalConfiguration.current).apply {
                        screenWidthDp=width;screenHeightDp=height;smallestScreenWidthDp=min(width,height)
                        orientation=if(width>=height)Configuration.ORIENTATION_LANDSCAPE else Configuration.ORIENTATION_PORTRAIT
                    }
                    CompositionLocalProvider(LocalDensity provides Density(scale,1f),LocalConfiguration provides configuration) {
                        Box(Modifier.requiredSize(width.dp,height.dp).onGloballyPositioned {
                            val r=it.boundsInWindow()
                            sceneBounds=Rect(r.left.roundToInt(),r.top.roundToInt(),r.right.roundToInt(),r.bottom.roundToInt())
                            updateFrame()
                        }.drawWithContent {drawContent();drawn.countDown()}) {
                            WegoCarTheme(night) {if(entry)ConnectionEntry(fullScreen=true,content=content) else content()}
                        }
                    }
                }
            }}
        }
        assertTrue("New preview scene must draw before its bounds are used",drawn.await(5,TimeUnit.SECONDS))
        settle()
        assertFalse("New preview scene must publish visible bounds",frame.isEmpty)
        assertTrue("Preview width must match the current preset",kotlin.math.abs(frame.width()-width*scale)<=2)
        assertTrue("Preview height must match the current preset",kotlin.math.abs(frame.height()-height*scale)<=2)
    }
    protected fun checkButton(label: String): Rect {
        val r=bounds(control(label))
        assertTrue("$label within $frame: $r",frame.contains(r))
        assertTrue("$label 80dp touch height",r.height()+1>=CarTokens.Touch.value*scale)
        return r
    }
    protected fun checkPair(left: String,right: String) {
        val a=checkButton(left);val b=checkButton(right)
        assertTrue("Equal action widths",kotlin.math.abs(a.width()-b.width())<=1)
        assertEquals("Same action row",a.top,b.top)
    }
    protected fun capture(name: String,button: String,night: Boolean) {
        settle()
        val r=bounds(control(button));val expected=(if(night)PleosPalette.Night else PleosPalette.Day).selectionMark.toArgb()
        val shot=requireNotNull(instrumentation.uiAutomation.takeScreenshot())
        try {
            assertTrue("Current preview stays inside the visible display",Rect(0,0,shot.width,shot.height).contains(frame))
            var matches=0
            for(y in r.top+2 until r.bottom-2)for(x in r.left+2 until r.right-2)if(shot.getPixel(x,y)==expected)matches++
            assertTrue("Primary text uses contrasting selection mark in ${if(night)"night" else "day"}",matches>10)
            val crop=Bitmap.createBitmap(shot,frame.left,frame.top,frame.width(),frame.height())
            try {File(host.cacheDir,"entry-$name.png").outputStream().use {crop.compress(Bitmap.CompressFormat.PNG,100,it)}}
            finally {crop.recycle()}
        } finally {shot.recycle()}
    }

}

class EntryDesignUiTest: EntryDesignTestCase() {
    fun testWalkthroughAndPermissionsFitEveryPresetAndKeepEqualActions() {
        host=instrumentation.startActivitySync(Intent(instrumentation.targetContext,SafFrameworkHarnessActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_MULTIPLE_TASK)) as SafFrameworkHarnessActivity
        try {
            for(night in listOf(false,true))for((width,height) in presets) {
                render(width,height,night) {FirstRunWalkthrough(true,{true},{})}
                val next=checkButton("다음");checkButton("건너뛰기")
                tap("다음");checkPair("이전","다음")
                assertEquals("Primary position stays fixed",next.left,checkButton("다음").left)
                if(width==1700 || width==628)capture("walkthrough-${width}x$height-${if(night)"night" else "day"}","다음",night)
                tap("다음");checkPair("이전","계속")
                render(width,height,night) {FirstRunPermissionScreen(true,false,{},{})}
                checkPair("나중에","권한 설정")
                if(width==1700 || width==628)capture("permissions-${width}x$height-${if(night)"night" else "day"}","권한 설정",night)
            }
        } finally {instrumentation.runOnMainSync {host.finish()}}
    }
}
