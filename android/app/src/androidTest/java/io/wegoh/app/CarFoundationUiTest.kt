package io.wegoh.app

import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Rect
import android.test.InstrumentationTestCase
import android.view.accessibility.AccessibilityNodeInfo
import android.view.View
import android.view.ViewGroup
import android.view.MotionEvent
import androidx.compose.ui.platform.ViewRootForTest
import androidx.compose.ui.layout.boundsInWindow
import androidx.compose.ui.semantics.*
import androidx.compose.ui.state.ToggleableState
import kotlin.math.roundToInt
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.toArgb
import io.wegoh.app.ui.*
import java.io.File

@Suppress("DEPRECATION")
class CarFoundationUiTest: InstrumentationTestCase() {
    private fun node(label: String): AccessibilityNodeInfo? {
        instrumentation.uiAutomation.clearCache()
        fun find(n: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
            if(n==null)return null
            if(n.isVisibleToUser && (n.contentDescription?.toString()==label || n.text?.toString()==label))return n
            for(i in 0 until n.childCount)find(n.getChild(i))?.let {return it}
            return null
        }
        return find(instrumentation.uiAutomation.rootInActiveWindow)
    }
    private data class Control(val enabled: Boolean,val checked: Boolean,val bounds: Rect)
    private lateinit var host: SafFrameworkHarnessActivity
    private fun control(label: String): Control? {
        var result: Control?=null
        instrumentation.runOnMainSync {
            fun inspect(view: View) {
                if(view is ViewRootForTest) {
                    val n=view.semanticsOwner.getAllSemanticsNodes(mergingEnabled=false).singleOrNull {
                        it.config.contains(SemanticsActions.OnClick) &&
                            it.config.getOrNull(SemanticsProperties.ContentDescription)?.contains(label)==true
                    }
                    if(n!=null) {
                        val rect=n.boundsInWindow
                        val origin=IntArray(2);view.rootView.getLocationOnScreen(origin)
                        result=Control(!n.config.contains(SemanticsProperties.Disabled),
                            n.config.getOrNull(SemanticsProperties.ToggleableState)==ToggleableState.On ||
                                n.config.getOrNull(SemanticsProperties.Selected)==true,
                            Rect(rect.left.roundToInt()+origin[0],rect.top.roundToInt()+origin[1],
                                rect.right.roundToInt()+origin[0],rect.bottom.roundToInt()+origin[1]))
                    }
                }
                if(view is ViewGroup)for(i in 0 until view.childCount)inspect(view.getChildAt(i))
            }
            inspect(host.window.decorView)
        }
        return result
    }
    private fun tap(control: Control) {
        val down=android.os.SystemClock.uptimeMillis()
        for((action,time) in listOf(MotionEvent.ACTION_DOWN to down,MotionEvent.ACTION_UP to down+50)) {
            val e=MotionEvent.obtain(down,time,action,control.bounds.exactCenterX(),control.bounds.exactCenterY(),0)
            try {instrumentation.sendPointerSync(e)} finally {e.recycle()}
        }
        instrumentation.waitForIdleSync()
    }

    private fun await(label: String,condition: ()->Boolean) {
        val end=android.os.SystemClock.uptimeMillis()+8000
        while(android.os.SystemClock.uptimeMillis()<end) {if(condition())return;Thread.sleep(40)}
        fail(label)
    }
    fun testCommonControlsKeepTouchSizeSelectionAndDisabledActions() {
        val base=instrumentation.targetContext
        host=instrumentation.startActivitySync(Intent(base,SafFrameworkHarnessActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_MULTIPLE_TASK)) as SafFrameworkHarnessActivity
        val dark=mutableStateOf(false)
        var commands=0
        val hint="iPhone 앱의 여행에서 새 여행을 만들어요"
        try {
            instrumentation.runOnMainSync {host.setContent {WegoCarTheme(dark.value) {
                val p=LocalCarPalette.current
                var selected by remember {mutableStateOf(false)}
                Column(Modifier.fillMaxSize().background(p.background).padding(CarTokens.Frame).verticalScroll(rememberScrollState()),
                    verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                    CarCard(tone=CarCardTone.INK) {
                        Row(horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                            CarAvatar("사용자A",CarAvatarTone.INK)
                            CarStatusPill("테스트 중",kind=CarStatusTone.ON_INK)
                            CarGearBadge(TripGear.PARK,onInk=true)
                        }
                        CarText("공통 컴포넌트",style=CarType.Title)
                    }
                    Row(horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                        CarButton("확인",{commands++},Modifier.weight(1f),primary=true)
                        CarButton("사용 불가",{commands++},Modifier.weight(1f),enabled=false)
                    }
                    Row(horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                        CarFilterChip("주유소",selected,{selected=!selected},Modifier.weight(1f))
                        CarChoiceTile("카페",selected,CarSymbol.Pin,Modifier.weight(1f)) {selected=!selected}
                    }
                    CarPhoneHint(hint)
                }
            }}}
            await("common controls") {host.hasWindowFocus() && node("확인")!=null && node("사용 불가")!=null}
            val primary=requireNotNull(control("확인"));val disabled=requireNotNull(control("사용 불가"))
            val bounds=primary.bounds
            assertTrue("button touch height",bounds.height()>=CarTokens.Touch.value*host.resources.displayMetrics.density)
            assertFalse(disabled.enabled)
            tap(disabled)
            instrumentation.waitForIdleSync();assertEquals(0,commands)
            tap(primary)
            await("single action") {commands==1}
            tap(requireNotNull(control("주유소")))
            await("multi-select chip selected") {control("주유소")?.checked==true}
            tap(requireNotNull(control("카페")))
            await("choice clears chip") {control("주유소")?.checked==false}
            assertFalse(requireNotNull(node(hint)).isClickable)
            for(night in listOf(false,true)) {
                instrumentation.runOnMainSync {dark.value=night}
                val origin=IntArray(2)
                instrumentation.runOnMainSync {host.window.decorView.getLocationOnScreen(origin)}
                val expected=(if(night)PleosPalette.Night else PleosPalette.Day).background.toArgb()
                var frame: Bitmap?=null
                await("rendered ${if(night)"night" else "day"} palette") {
                    frame?.recycle()
                    frame=instrumentation.uiAutomation.takeScreenshot()
                    frame?.getPixel(origin[0]+8,origin[1]+8)==expected
                }
                val shot=requireNotNull(frame)
                val crop=Bitmap.createBitmap(shot,origin[0],origin[1],host.window.decorView.width,host.window.decorView.height)
                File(base.cacheDir,if(night)"car-foundation-night.png" else "car-foundation-day.png").outputStream().use {
                    crop.compress(Bitmap.CompressFormat.PNG,100,it)
                }
                crop.recycle();shot.recycle()
            }
        } finally {instrumentation.runOnMainSync {host.finish()}}
    }
}
