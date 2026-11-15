package io.wegoh.app

import android.accessibilityservice.AccessibilityServiceInfo
import android.content.Intent
import android.graphics.Bitmap
import android.os.Handler
import android.os.Looper
import android.test.InstrumentationTestCase
import android.test.InstrumentationTestRunner
import android.view.PixelCopy
import android.view.accessibility.AccessibilityNodeInfo
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import android.content.res.Configuration
import android.graphics.Rect
import kotlin.math.min
import io.wegoh.app.nativeauth.*
import io.wegoh.app.nativebusiness.*
import io.wegoh.app.ui.*
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

@Suppress("DEPRECATION")
class NativePanelRetentionTest: InstrumentationTestCase() {
    private lateinit var activity: MainActivity
    private fun nodes(): List<AccessibilityNodeInfo> {
        if(android.os.Build.VERSION.SDK_INT>=34)instrumentation.uiAutomation.clearCache()
        val result=mutableListOf<AccessibilityNodeInfo>()
        fun walk(node: AccessibilityNodeInfo?) {if(node!=null){result.add(node);for(i in 0 until node.childCount)walk(node.getChild(i))}}
        instrumentation.uiAutomation.windows.filter {it.type==android.view.accessibility.AccessibilityWindowInfo.TYPE_APPLICATION}.mapNotNull {it.root}
            .filter {it.packageName?.toString()==instrumentation.targetContext.packageName}.forEach(::walk)
        return result
    }
    private fun visible(text: String)=nodes().any {it.isVisibleToUser && (it.text?.toString()==text || it.contentDescription?.toString()==text)}
    private fun await(label: String,check: ()->Boolean) {
        val end=android.os.SystemClock.elapsedRealtime()+25_000
        while(android.os.SystemClock.elapsedRealtime()<end){if(check())return;Thread.sleep(120)}
        val owned=nodes().filter {it.isVisibleToUser}.flatMap {listOfNotNull(it.text?.toString(),it.contentDescription?.toString())}
            .map {it.replace('\n',' ')}.filter {it.isNotBlank()}.distinct().take(40)
        if(::activity.isInitialized)runCatching {capture("panel-failure-"+label.replace(Regex("[^A-Za-z0-9]+"),"-").take(60))}
        fail("panel.condition: failed label=$label visible_owned=$owned")
    }
    private fun click(label: String,below: String?=null) {
        await(label) {
            val current=nodes()
            val lowerEdge=if(below==null)Int.MIN_VALUE else current.filter {it.isVisibleToUser &&
                (it.text?.toString()==below || it.contentDescription?.toString()==below)}.maxOfOrNull {
                Rect().apply {it.getBoundsInScreen(this)}.bottom
            } ?: return@await false
            for(candidate in current.filter {it.isVisibleToUser && (it.text?.toString()==label || it.contentDescription?.toString()==label)}) {
                val position=Rect();candidate.getBoundsInScreen(position)
                if(position.top<lowerEdge)continue
                var node: AccessibilityNodeInfo?=candidate
                repeat(5) {
                    if(node?.isEnabled==true && node?.isClickable==true && node?.performAction(AccessibilityNodeInfo.ACTION_CLICK)==true) {
                        Thread.sleep(250);return@await true
                    }
                    node=node?.parent
                }
            }
            nodes().firstOrNull {it.isScrollable}?.performAction(AccessibilityNodeInfo.ACTION_SCROLL_FORWARD)
            false
        }
    }
    private fun assertCachedHistoryUnavailable(label: String) {
        val candidates=nodes().filter {it.isVisibleToUser && (it.text?.toString()==label || it.contentDescription?.toString()==label)}
        var row: AccessibilityNodeInfo?=null
        for(candidate in candidates) {
            var current: AccessibilityNodeInfo?=candidate
            repeat(6) {
                if(row==null && current?.let {it.isCheckable || it.isClickable}==true)row=current
                current=current?.parent
            }
            if(row!=null)break
        }
        val control=requireNotNull(row) {"History row control missing: $label"}
        assertFalse("Cached history control must be disabled",control.isEnabled)
        assertFalse("Cached history must have no click action",control.actionList.any {it.id==AccessibilityNodeInfo.ACTION_CLICK})
        assertFalse("Cached history cannot open a detail",control.performAction(AccessibilityNodeInfo.ACTION_CLICK))
        assertFalse("Cached history remains on the list",visible("목록으로"))
    }
    private fun capture(name: String) {
        val image=Bitmap.createBitmap(activity.window.decorView.width,activity.window.decorView.height,Bitmap.Config.ARGB_8888)
        val done=CountDownLatch(1);var result=-1
        PixelCopy.request(activity.window,image,{result=it;done.countDown()},Handler(Looper.getMainLooper()))
        assertTrue(done.await(5,TimeUnit.SECONDS));assertEquals(PixelCopy.SUCCESS,result)
        File(activity.cacheDir,"$name.png").outputStream().use {image.compress(Bitmap.CompressFormat.PNG,100,it)};image.recycle()
    }
    fun testPanelsRetainTransportFailuresAndClearAuthorityFailures() {
        val args=(instrumentation as InstrumentationTestRunner).arguments
        val context=instrumentation.targetContext
        val ca=NativeDeviceIdentity.parseCertificates(String(android.util.Base64.decode(args.getString("ca"),android.util.Base64.DEFAULT),Charsets.US_ASCII)).single()
        val connection=VehicleConnection.synthetic(context,"panels_"+java.util.UUID.randomUUID().toString().replace("-",""),args.getString("port")!!.toInt(),ca,args.getString("eventsPort")!!.toInt())
        val info=instrumentation.uiAutomation.serviceInfo;val flags=info.flags
        info.flags=flags or AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS;instrumentation.uiAutomation.serviceInfo=info
        val markers=listOf("panel-history-close","panel-business-close","panel-handshake-503","panel-handshake-401","panel-history-updated","panel-business-updated","panel-business","panel-deny")
        fun mark(name: String,value: Boolean=true) {
            check(name in markers);val file=File(context.cacheDir,name)
            if(value)file.writeText(args.getString("gpsNonce")!!)else file.delete()
        }
        markers.forEach {mark(it,false)}
        var windows: CarWindowVisibility?=null
        var historyScale=1f
        try {
            activity=instrumentation.startActivitySync(Intent(context,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
            instrumentation.waitForIdleSync();Thread.sleep(500)
            instrumentation.runOnMainSync {connection.setForeground(true);connection.setSetupAllowed(true);connection.start("Synthetic panels",emptySet())}
            await("connected"){connection.status().stage==VehicleConnection.Stage.CONNECTED}
            instrumentation.runOnMainSync {
                windows=CarWindowVisibility(activity) {}
                activity.setContent {
                    BoxWithConstraints(Modifier.fillMaxSize(),contentAlignment=Alignment.Center) {
                        historyScale=min(constraints.maxWidth/648f,constraints.maxHeight/800f)
                        val configuration=Configuration(LocalConfiguration.current).apply {screenWidthDp=648;screenHeightDp=800}
                        CompositionLocalProvider(LocalDensity provides Density(historyScale,1f),LocalConfiguration provides configuration,
                            LocalVehicleLandingPage provides "trips") {
                            Box(Modifier.requiredSize(648.dp,800.dp)) {WegoCarTheme {ProvideCarWindowVisibility(windows!!) {
                                val childBack=androidx.compose.runtime.remember {CarChildBackState()}
                                CompositionLocalProvider(LocalCarChildBackState provides childBack) {
                                    Column(Modifier.fillMaxSize()) {
                                        TripHeading("서해안 드라이브",onBack={childBack.action?.invoke()})
                                        NativeHistoryPanel(connection,true,{},embedded=true,showEmbeddedHeading=false)
                                    }
                                }
                            }}}
                        }
                    }
                }
            }
            await("history loaded in full embedded route"){visible("Saved history")}
            fun assertTouchHeight(label: String,minimumDp: Float) {
                val node=nodes().first {it.isVisibleToUser && (it.text?.toString()==label || it.contentDescription?.toString()==label)}
                val bounds=Rect();node.getBoundsInScreen(bounds)
                assertTrue("$label retains its full touch area at 648dp: $bounds",bounds.height()+1>=minimumDp*historyScale)
            }
            assertTrue("Fixture heading remains visible",visible("서해안 드라이브"))
            assertTouchHeight("Saved history",CarTokens.Row.value)
            capture("panel-history-embedded-648-list")
            click("Saved history")
            await("narrow selected detail has list back"){visible("목록으로")}
            assertTouchHeight("목록으로",CarTokens.Touch.value)
            capture("panel-history-embedded-648-detail")
            click("목록으로")
            await("list restored with complete row"){visible("Saved history") && !visible("목록으로")}
            assertTouchHeight("Saved history",CarTokens.Row.value)
            click("Saved history")
            await("selected history registers route back"){visible("목록으로")}
            click("뒤로")
            await("route back returns to the full list"){visible("Saved history") && !visible("목록으로")}
            mark("panel-history-close")
            await("history cached"){visible("저장된 기록을 표시합니다. 새로고침으로 현재 상태를 확인하세요")}
            assertTrue(visible("Saved history"));assertCachedHistoryUnavailable("Saved history")
            capture("panel-history-cached")
            mark("panel-handshake-503");click("새로고침",below="Saved history")
            await("failed history reopen"){visible("연결을 확인해 주세요")}
            assertTrue("HTTP503 must retain the last list",visible("Saved history"))
            assertCachedHistoryUnavailable("Saved history")
            mark("panel-handshake-503",false);mark("panel-history-updated");click("새로고침",below="Saved history")
            await("history reconciled"){visible("Updated history")}
            assertTouchHeight("Updated history",CarTokens.Row.value)
            click("Updated history")
            await("current history can open its detail"){visible("Updated history") && visible("목록으로")}
            click("목록으로")
            await("current history returns to list"){visible("Updated history") && !visible("목록으로")}
            mark("panel-handshake-401");click("새로고침",below="Updated history")
            await("history authority cleared"){visible("연결을 확인해 주세요") && !visible("Updated history")}
            mark("panel-handshake-401",false);mark("panel-business")
            instrumentation.runOnMainSync {activity.setContent {WegoCarTheme {ProvideCarWindowVisibility(windows!!) {
                NativeBusinessPanel(connection,true,{},{},initialSection="RECOMMENDATIONS")
            }}}}
            await("settings loaded"){visible("가까운 경로")}
            mark("panel-business-close")
            await("settings cached"){visible("저장된 내용이에요. 새로고침해 주세요")}
            assertTrue(visible("가까운 경로"));capture("panel-business-cached")
            mark("panel-handshake-503");click("새로고침")
            await("failed settings reopen"){visible("저장된 내용이에요. 새로고침해 주세요")}
            assertTrue("HTTP503 must retain settings",visible("가까운 경로"))
            mark("panel-handshake-503",false);mark("panel-business-updated");click("새로고침")
            await("settings reconciled"){visible("장소가 많은 경로")}
            mark("panel-deny");click("새로고침")
            await("functional denial clears settings"){!visible("장소가 많은 경로") &&
                (visible("이 계정에서는 볼 수 없어요") || visible("연결과 이용 권한을 확인해 주세요"))}
            instrumentation.runOnMainSync {connection.disconnect()}
            await("logout clears authority"){connection.status().stage!=VehicleConnection.Stage.CONNECTED}
            assertFalse(visible("장소가 많은 경로"))
        } finally {
            instrumentation.runOnMainSync {connection.close();windows?.close();if(::activity.isInitialized)activity.finish()}
            markers.forEach {mark(it,false)}
            info.flags=flags;instrumentation.uiAutomation.serviceInfo=info
        }
    }
}
