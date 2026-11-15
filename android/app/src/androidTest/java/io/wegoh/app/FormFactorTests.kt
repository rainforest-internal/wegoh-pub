package io.wegoh.app

import android.app.ActivityOptions
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Rect
import android.os.Handler
import android.os.Looper
import android.test.InstrumentationTestCase
import android.view.PixelCopy
import android.view.accessibility.AccessibilityNodeInfo
import androidx.activity.compose.setContent
import io.wegoh.app.ui.*
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Real official DISPLAY2 windows; synthetic content, no driving/SDK claims. */
@Suppress("DEPRECATION")
class FormFactorTests: InstrumentationTestCase() {
    private lateinit var activity: MainActivity
    private val displayId get()=(instrumentation as android.test.InstrumentationTestRunner).arguments.getString("displayId")!!.toInt()
    private fun nodes(): List<AccessibilityNodeInfo> {
        val automation=instrumentation.uiAutomation
        if(android.os.Build.VERSION.SDK_INT>=34)automation.clearCache()
        val result=mutableListOf<AccessibilityNodeInfo>()
        fun walk(node: AccessibilityNodeInfo?) {if(node!=null){result.add(node);for(i in 0 until node.childCount)walk(node.getChild(i))}}
        val windows=automation.windowsOnAllDisplays.get(displayId).orEmpty()
        windows.filter {it.root?.packageName?.toString()=="io.wegoh.app"}.forEach {walk(it.root)}
        return result
    }
    private fun click(label: String) {
        val end=System.currentTimeMillis()+7000
        while(System.currentTimeMillis()<end) {
            var node=nodes().firstOrNull {it.text?.toString()==label || it.contentDescription?.toString()==label}
            repeat(6){if(node?.performAction(AccessibilityNodeInfo.ACTION_CLICK)==true){settle();return};node=node?.parent}
            Thread.sleep(100)
        }
        fail("DISPLAY2 missing actionable $label")
    }
    private fun settle(){instrumentation.waitForIdleSync();Thread.sleep(250)}
    private fun action(label: String): AccessibilityNodeInfo {
        val end=System.currentTimeMillis()+5000
        while(System.currentTimeMillis()<end) {
            nodes().firstOrNull {it.contentDescription?.toString()==label}?.let{return it}
            Thread.sleep(100)
        }
        val windows=instrumentation.uiAutomation.windowsOnAllDisplays
        fail("Missing $label; dp=${activity.resources.configuration.screenWidthDp}; windows=$windows; nodes="+
            nodes().joinToString {"${it.text}/${it.contentDescription}"})
        error("Missing action")
    }
    private fun capture(name: String) {
        var window=activity.window
        var popupView: android.view.View?=null
        if(name.startsWith("menu"))instrumentation.runOnMainSync {
            check(android.os.Build.VERSION.SDK_INT>=34){"Actual Popup ViewRoot capture requires API 34+"}
            popupView=android.view.inspector.WindowInspector.getGlobalWindowViews()
                .lastOrNull {it.isShown && it.display?.displayId==displayId && it.javaClass.name.contains("PopupLayout")}
                ?: error("Menu must capture its actual Dropdown Popup window")
        }
        if(name.startsWith("consent"))instrumentation.runOnMainSync {
            fun find(view: android.view.View): android.view.Window? {
                if(view is androidx.compose.ui.window.DialogWindowProvider)return view.window
                if(view is android.view.ViewGroup)for(index in 0 until view.childCount)find(view.getChildAt(index))?.let{return it}
                return null
            }
            if(android.os.Build.VERSION.SDK_INT>=29)window=android.view.inspector.WindowInspector.getGlobalWindowViews()
                .filter {it.isShown && it.display?.displayId==displayId}.mapNotNull(::find).lastOrNull()
                ?: error("Consent must capture its actual Dialog window")
            else error("Official emulator API >=29 required")
        }
        val view=popupView ?: window.decorView
        val bitmap=Bitmap.createBitmap(view.width,view.height,Bitmap.Config.ARGB_8888)
        val done=CountDownLatch(1);var status=-1
        if(popupView!=null && android.os.Build.VERSION.SDK_INT>=34) {
            PixelCopy.request(PixelCopy.Request.Builder.ofWindow(view).setDestinationBitmap(bitmap).build(),activity.mainExecutor) {
                status=it.status;done.countDown()
            }
        } else PixelCopy.request(window,bitmap,{status=it;done.countDown()},Handler(Looper.getMainLooper()))
        assertTrue(done.await(5,TimeUnit.SECONDS));assertEquals(PixelCopy.SUCCESS,status)
        File(activity.cacheDir,"formfactor-$name.png").outputStream().use{bitmap.compress(Bitmap.CompressFormat.PNG,100,it)}
        bitmap.recycle()
    }
    fun testRealDisplayWindowDayNightAndConsentBounds() {
        val service=instrumentation.uiAutomation.serviceInfo
        service.flags=service.flags or android.accessibilityservice.AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
        instrumentation.uiAutomation.serviceInfo=service
        activity=instrumentation.startActivitySync(Intent(instrumentation.targetContext,MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_MULTIPLE_TASK),
            ActivityOptions.makeBasic().setLaunchDisplayId(displayId).toBundle()) as MainActivity
        assertEquals(displayId,activity.display!!.displayId)
        val pack=PackRepository(instrumentation.targetContext).list().first().copy(title="긴 여정 이름 ".repeat(10))
        for(dark in listOf(false,true)) {
            instrumentation.runOnMainSync {activity.setContent {androidx.compose.runtime.key(dark){WegoCarTheme(dark=dark){WegoVehicleScreen(
                WegoState(packs=listOf(pack),selectedKey=pack.key,setupAllowed=true,storageReady=true),
                {},{},{},{},{},{},{},{},{})}}}}
            settle()
            capture(if(dark)"night" else "day")
            if(activity.resources.configuration.screenWidthDp<1000)click(pack.title)
            val density=activity.resources.displayMetrics.density
            val root=Rect();instrumentation.runOnMainSync {activity.window.decorView.getGlobalVisibleRect(root)}
            val bounds=mutableMapOf<String,Rect>()
            for(label in listOf("출발","도착 알림")) {
                val node=action(label)
                val rect=Rect();node.getBoundsInScreen(rect);bounds[label]=rect
                assertTrue("Action outside actual window $root: $rect",root.contains(rect))
                assertTrue(rect.width()>=80*density-1 && rect.height()>=80*density-1)
            }
            assertFalse(Rect.intersects(bounds["출발"]!!,bounds["도착 알림"]!!))
            capture(if(dark)"night" else "day")
            click("도착 알림")
            for(label in listOf("취소","동의하고 시작")) {
                val node=action(label)
                val rect=Rect();node.getBoundsInScreen(rect)
                assertTrue("Popup action outside window $root: $rect",root.contains(rect))
                assertTrue(rect.height()>=80*density-1)
            }
            capture(if(dark)"consent-night" else "consent-day");click("취소")
            for(route in PlatformRoutes.primary) {
                instrumentation.runOnMainSync {activity.setContent {androidx.compose.runtime.key("$route-$dark") {WegoCarTheme(dark=dark) {
                    PlatformScreen(WegoState(packs=listOf(pack),selectedKey=pack.key,setupAllowed=true,storageReady=true),route) {exit->
                        WegoVehicleScreen(WegoState(packs=listOf(pack),selectedKey=pack.key,setupAllowed=true,storageReady=true),
                            {},{},{},{},{},{},{},{},{},onRootBack=exit,onPlatform=exit)
                    }
                }}}}
                settle();assertTrue("Missing platform root $route",nodes().any{it.text?.toString()==PlatformRoutes.titles[route]})
                capture("platform-$route-${if(dark)"night" else "day"}")
                if(route=="discover") {
                    click("전체 메뉴")
                    for(label in listOf("발견","여행방","친구","경로","만들기","프로필")) {
                        val rect=Rect();action(label).getBoundsInScreen(rect)
                        assertTrue("Menu outside actual display window: $label $rect",root.contains(rect))
                        assertTrue("Menu target too small: $label",rect.height()>=80*density-1)
                    }
                    capture("menu-${if(dark)"night" else "day"}");click("발견")
                }
            }
        }
    }
    override fun tearDown(){if(::activity.isInitialized)instrumentation.runOnMainSync {activity.finish()};super.tearDown()}
}
