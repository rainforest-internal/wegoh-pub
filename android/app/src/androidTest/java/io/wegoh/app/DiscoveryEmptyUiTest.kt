package io.wegoh.app

import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Rect
import android.test.InstrumentationTestCase
import android.view.accessibility.AccessibilityNodeInfo
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.key
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import io.wegoh.app.ui.*
import java.io.File

@Suppress("DEPRECATION")
class DiscoveryEmptyUiTest: InstrumentationTestCase() {
    private fun node(label: String): AccessibilityNodeInfo? {
        instrumentation.uiAutomation.clearCache()
        fun find(n: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
            if(n==null)return null
            if(n.isVisibleToUser && (n.text?.toString()==label || n.contentDescription?.toString()==label))return n
            for(i in 0 until n.childCount)find(n.getChild(i))?.let {return it}
            return null
        }
        return find(instrumentation.uiAutomation.rootInActiveWindow)
    }
    private fun await(label: String): AccessibilityNodeInfo {
        val until=android.os.SystemClock.elapsedRealtime()+10000
        while(android.os.SystemClock.elapsedRealtime()<until) {
            node(label)?.let {return it};Thread.sleep(80)
        }
        error("Discovery UI missing: $label")
    }
    private fun click(label: String) {
        var n: AccessibilityNodeInfo?=await(label)
        while(n!=null && !n.isClickable)n=n.parent
        assertNotNull(n);assertTrue(n!!.performAction(AccessibilityNodeInfo.ACTION_CLICK))
        instrumentation.waitForIdleSync()
    }
    private fun bounds(label: String)=Rect().also {await(label).getBoundsInScreen(it)}
    fun testEmptyCenterThemesAndStateTransitions() {
        val host=instrumentation.startActivitySync(Intent(instrumentation.targetContext,MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        val directory=File(host.cacheDir,"discovery-empty").apply {mkdirs()}
        var sequence=0
        var downloads=0
        val pack=PublishedPack("empty_ui",1,"바다를 따라가는 드라이브 코스","여행자","해안길",2,"a".repeat(64))
        fun render(width: Int,dark: Boolean,state: AccountDiscoveryState,allowed: Boolean=true) {
            val id=++sequence
            instrumentation.runOnMainSync {host.setContent {key(id) {
                CompositionLocalProvider(LocalVehicleLandingPage provides "discover") {
                    WegoCarTheme(dark) {Box(Modifier.width(width.dp).fillMaxHeight()) {
                        WegoVehicleScreen(WegoState(setupAllowed=allowed,storageReady=true,accountDiscovery=state,
                            policy=if(allowed)"설정 허용"else"주행 제한"),
                            {},{},{},{},{},{},{},{},{},onAccountDiscovery={},onPublicDownload={assertEquals(pack,it);downloads++})
                    }}
                }
            }}}
            val frames=java.util.concurrent.CountDownLatch(1)
            instrumentation.runOnMainSync {host.window.decorView.postOnAnimation {host.window.decorView.postOnAnimation {frames.countDown()}}}
            assertTrue(frames.await(3,java.util.concurrent.TimeUnit.SECONDS))
            if(!host.hasWindowFocus()) {
                val at=IntArray(2);instrumentation.runOnMainSync {host.window.decorView.getLocationOnScreen(at)}
                android.os.ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand(
                    "input tap ${at[0]+width/2} ${at[1]+200}")).use {it.readBytes()}
            }
        }
        fun capture(name: String,width: Int) {
            instrumentation.waitForIdleSync()
            val at=IntArray(2);instrumentation.runOnMainSync {host.window.decorView.getLocationOnScreen(at)}
            val full=instrumentation.uiAutomation.takeScreenshot()
            val pane=Bitmap.createBitmap(full,at[0],at[1],minOf(width,host.window.decorView.width),host.window.decorView.height)
            File(directory,"$name.png").outputStream().use {assertTrue(pane.compress(Bitmap.CompressFormat.PNG,100,it))}
            pane.recycle();full.recycle()
        }
        try {
            val origin=IntArray(2);instrumentation.runOnMainSync {host.window.decorView.getLocationOnScreen(origin)}
            val wide=host.window.decorView.width
            for(width in listOf(wide,628).distinct())for(dark in listOf(false,true)) {
                render(width,dark,AccountDiscoveryState(AccountReadStatus.READY))
                val title=bounds("공개 경로가 없어요")
                assertNull(node("공유된 코스가 여기에 표시됩니다"))
                val footer=bounds("창작자")
                instrumentation.runOnMainSync {host.window.decorView.getLocationOnScreen(origin)}
                val actualWidth=minOf(width,host.window.decorView.width)
                capture("empty-$width-${if(dark)"night"else"day"}",width)
                assertTrue("Centered title $title in x=${origin[0]} width=$actualWidth",kotlin.math.abs(title.centerX()-(origin[0]+actualWidth/2))<=3)
                assertTrue(title.top>origin[1]+host.window.decorView.height/4)
                assertTrue(title.bottom<footer.top-16)
                assertNull(node("0 / 0"));assertNull(node("발견 목록 위로"));assertNull(node("발견 목록 아래로"))
            }
            for((status,label) in listOf(AccountReadStatus.LOADING to "공개 경로를 불러오는 중",
                AccountReadStatus.UNAVAILABLE to "경로를 불러올 수 없습니다",
                AccountReadStatus.PERMISSION_REQUIRED to "경로 공유를 허용해 주세요",
                AccountReadStatus.CONNECTION_REQUIRED to "차량을 연결해 주세요")) {
                render(628,false,AccountDiscoveryState(status));await(label)
                assertNull(node("공개 경로가 없어요"));assertNull(node("공유된 코스가 여기에 표시됩니다"))
            }
            render(628,false,AccountDiscoveryState(AccountReadStatus.READY,listOf(pack)))
            await("${pack.title} v1 받기");assertNotNull(node("1 / 1"));assertNull(node("공개 경로가 없어요"))
            click("${pack.title} v1 받기");assertEquals(1,downloads)
            capture("nonempty",628)
            render(628,false,AccountDiscoveryState(AccountReadStatus.READY),allowed=false)
            await("P단에서 이용할 수 있어요");assertNull(node("공개 경로가 없어요"))
            capture("restricted",628)
        } finally {instrumentation.runOnMainSync {host.finish()}}
    }
}
