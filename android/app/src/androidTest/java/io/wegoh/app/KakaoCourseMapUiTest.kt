package io.wegoh.app

import android.content.Intent
import android.test.InstrumentationTestCase
import android.view.View
import android.view.ViewGroup
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.ViewRootForTest
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.semantics.getAllSemanticsNodes
import io.wegoh.app.nativeauth.TripRouteItem
import io.wegoh.app.ui.*
import java.io.File

@Suppress("DEPRECATION")
class KakaoCourseMapUiTest: InstrumentationTestCase() {
    private lateinit var host: SafFrameworkHarnessActivity
    override fun setUp() {
        super.setUp()
        host=instrumentation.startActivitySync(Intent(instrumentation.targetContext,SafFrameworkHarnessActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as SafFrameworkHarnessActivity
    }
    override fun tearDown() {
        try {instrumentation.runOnMainSync {host.setContent {};host.finish()}}finally {super.tearDown()}
    }
    private fun texts(): List<String> {
        val result=mutableListOf<String>()
        instrumentation.runOnMainSync {
            fun inspect(view: View) {
                if(view is ViewRootForTest)view.semanticsOwner.getAllSemanticsNodes(mergingEnabled=false).forEach {node->
                    node.config.getOrNull(SemanticsProperties.Text)?.forEach {result.add(it.text)}
                }
                if(view is ViewGroup)for(i in 0 until view.childCount)inspect(view.getChildAt(i))
            }
            inspect(host.window.decorView)
        }
        return result
    }
    private fun waitForRenderedFrames() {
        val rendered=java.util.concurrent.CountDownLatch(1)
        instrumentation.runOnMainSync {
            android.view.Choreographer.getInstance().postFrameCallback {
                android.view.Choreographer.getInstance().postFrameCallback {rendered.countDown()}
            }
        }
        assertTrue("Two UI frames rendered",rendered.await(5,java.util.concurrent.TimeUnit.SECONDS))
        instrumentation.waitForIdleSync()
    }
    fun testFallbackTextContrastsWithItsSurfaceInsideInkCard() {
        val missingKey=BuildConfig.KAKAO_NATIVE_APP_KEY.isBlank()
        val stops=if(missingKey)listOf(TripRouteStop(TripRouteItem("course","seoul","test"),"서울역",37.5547,126.9706)) else emptyList()
        val message=if(missingKey)"지도를 사용할 수 없어요" else "표시할 장소가 없어요"
        val removedDetail="장소 목록과 내비 안내는 계속 이용할 수 있어요"
        for(dark in listOf(false,true)) {
            instrumentation.runOnMainSync {host.setContent {WegoCarTheme(dark=dark) {
                Column(Modifier.fillMaxSize().padding(CarTokens.Frame)) {
                    CarCard(tone=CarCardTone.INK) {
                        KakaoCourseMap(stops,Modifier.fillMaxWidth().height(CarTokens.MapPreviewHeight))
                    }
                }
            }}}
            val deadline=android.os.SystemClock.uptimeMillis()+5000
            while(android.os.SystemClock.uptimeMillis()<deadline && !texts().contains(message))Thread.sleep(80)
            waitForRenderedFrames()
            val colors=mutableMapOf<String,Color>()
            var surfacePoint: Pair<Int,Int>?=null
            instrumentation.runOnMainSync {
                fun inspect(view: View) {
                    if(view is ViewRootForTest)view.semanticsOwner.getAllSemanticsNodes(mergingEnabled=false).forEach {node->
                        val labels=node.config.getOrNull(SemanticsProperties.Text).orEmpty().map {it.text}
                        if(labels.any {it==message}) {
                            val layouts=mutableListOf<androidx.compose.ui.text.TextLayoutResult>()
                            node.config.getOrNull(SemanticsActions.GetTextLayoutResult)?.action?.invoke(layouts)
                            layouts.forEach {colors[it.layoutInput.text.text]=it.layoutInput.style.color}
                        }
                        if(node.config.getOrNull(SemanticsProperties.ContentDescription)?.any {it.startsWith("장소 지도. ")}==true) {
                            val bounds=node.boundsInRoot;val origin=IntArray(2);view.getLocationOnScreen(origin)
                            surfacePoint=(origin[0]+bounds.center.x.toInt()) to (origin[1]+(bounds.top+bounds.height/20).toInt())
                        }
                    }
                    if(view is ViewGroup)for(i in 0 until view.childCount)inspect(view.getChildAt(i))
                }
                inspect(host.window.decorView)
            }
            val bitmap=instrumentation.uiAutomation.takeScreenshot()
            try {
                File(instrumentation.targetContext.filesDir,if(dark)"kakao-map-fallback-night.png" else "kakao-map-fallback-day.png")
                    .outputStream().use {bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG,100,it)}
                assertTrue(texts().contains(message))
                assertEquals(CarTokens.Text,colors[message])
                assertFalse(texts().contains(removedDetail))
                val point=requireNotNull(surfacePoint)
                assertTrue("Map sample is inside screenshot",point.first in 0 until bitmap.width && point.second in 0 until bitmap.height)
                assertEquals("Map surface at $point",CarTokens.Surface.toArgb(),bitmap.getPixel(point.first,point.second))
                val background=Color(bitmap.getPixel(point.first,point.second)).luminance()
                for(label in listOf(message)) {
                    val foreground=requireNotNull(colors[label]).luminance()
                    assertTrue("Fallback text contrast: $label",(maxOf(foreground,background)+.05f)/(minOf(foreground,background)+.05f)>=4.5f)
                }
            } finally {bitmap.recycle()}
        }
    }
    fun testActualKakaoMapStartsAndSurvivesLeavingScreen() {
        instrumentation.runOnMainSync {host.setContent {WegoCarTheme {TripSurface {
            Column(Modifier.fillMaxSize().padding(CarTokens.Frame)) {
                TripText("실제 장소 지도",style=CarType.Title)
                KakaoCourseMap(listOf(
                    TripRouteStop(TripRouteItem("course","seoul","test"),"서울역",37.5547,126.9706),
                    TripRouteStop(TripRouteItem("course","cityhall","test"),"서울시청",37.5663,126.9779)),
                    Modifier.fillMaxWidth().weight(1f),interactive=false)
            }
        }}}}
        if(BuildConfig.KAKAO_NATIVE_APP_KEY.isBlank()) {
            val deadline=android.os.SystemClock.uptimeMillis()+5000
            while(android.os.SystemClock.uptimeMillis()<deadline && !texts().contains("지도를 사용할 수 없어요"))Thread.sleep(80)
            assertTrue(texts().contains("지도를 사용할 수 없어요"))
            return
        }
        val deadline=android.os.SystemClock.uptimeMillis()+25000
        var content=texts()
        while(android.os.SystemClock.uptimeMillis()<deadline && (content.none {it=="실제 장소 지도"} || content.any {it=="지도 불러오는 중"})) {
            Thread.sleep(200);content=texts()
        }
        Thread.sleep(2500)
        val file=File(instrumentation.targetContext.filesDir,"kakao-map-actual.png")
        val bitmap=instrumentation.uiAutomation.takeScreenshot()
        file.outputStream().use {bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG,100,it)}
        bitmap.recycle()
        assertFalse("Map initialization did not finish",content.any {it=="지도 불러오는 중"})
        assertFalse("Map initialization failed; check registered Android package/hash and network",content.any {it.contains("못했어요") || it.contains("사용할 수 없어요")})
        instrumentation.runOnMainSync {host.setContent {WegoCarTheme {TripText("지도 닫힘")}}}
        instrumentation.waitForIdleSync()
        val closedDeadline=android.os.SystemClock.uptimeMillis()+5000
        while(android.os.SystemClock.uptimeMillis()<closedDeadline && !texts().contains("지도 닫힘"))Thread.sleep(80)
        assertTrue(texts().contains("지도 닫힘"))
    }
}
