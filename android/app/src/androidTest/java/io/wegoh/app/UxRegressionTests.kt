package io.wegoh.app

import android.accessibilityservice.AccessibilityServiceInfo
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Rect
import android.os.SystemClock
import android.test.InstrumentationTestCase
import android.view.InputDevice
import android.view.MotionEvent
import android.view.accessibility.AccessibilityNodeInfo
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.key
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.google.zxing.BinaryBitmap
import com.google.zxing.MultiFormatReader
import com.google.zxing.RGBLuminanceSource
import com.google.zxing.common.HybridBinarizer
import io.wegoh.app.ui.*
import java.io.File
import org.json.JSONArray
import org.json.JSONObject

/** Synthetic in-memory fixtures; no live pack/visit writes, camera or GPS injection. */
@Suppress("DEPRECATION")
class UxRegressionTests: InstrumentationTestCase() {
    private lateinit var activity: MainActivity
    private var previousFlags=0
    private val observations=JSONArray()
    private var headerFixture=false
    private var businessCalls=0
    override fun setUp() {
        super.setUp()
        val info=instrumentation.uiAutomation.serviceInfo;previousFlags=info.flags
        info.flags=info.flags or AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
        instrumentation.uiAutomation.serviceInfo=info
        activity=instrumentation.startActivitySync(Intent(instrumentation.targetContext,MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
    }
    override fun tearDown() {
        val info=instrumentation.uiAutomation.serviceInfo;info.flags=previousFlags
        instrumentation.uiAutomation.serviceInfo=info
        File(activity.cacheDir,"ux-${name}.json").writeText(observations.toString(2))
        instrumentation.runOnMainSync {activity.finish()}
        super.tearDown()
    }
    private fun nodes(): List<AccessibilityNodeInfo> {
        if(android.os.Build.VERSION.SDK_INT>=34)instrumentation.uiAutomation.clearCache()
        val result=mutableListOf<AccessibilityNodeInfo>()
        fun walk(n: AccessibilityNodeInfo?) {if(n!=null){if(n.isVisibleToUser)result.add(n);for(i in 0 until n.childCount)walk(n.getChild(i))}}
        val windows=instrumentation.uiAutomation.windows
        if(windows.isEmpty())walk(instrumentation.uiAutomation.rootInActiveWindow)else windows.forEach{walk(it.root)}
        return result
    }
    private fun node(label: String): AccessibilityNodeInfo {
        val deadline=SystemClock.uptimeMillis()+6000
        while(SystemClock.uptimeMillis()<deadline) {
            nodes().filter {it.text?.toString()==label || it.contentDescription?.toString()==label}
                .sortedByDescending {it.contentDescription?.toString()==label && it.isClickable}.firstOrNull()?.let{return it}
            Thread.sleep(100)
        }
        capture("missing-element").recycle()
        error("Missing visible UX element: $label")
    }
    private fun bounds(n: AccessibilityNodeInfo)=Rect().also{n.getBoundsInScreen(it)}
    private fun settle(){instrumentation.waitForIdleSync();Thread.sleep(350)}
    private fun click(label: String) {
        val candidates=nodes().filter{it.text?.toString()==label || it.contentDescription?.toString()==label}
        for(candidate in candidates.sortedByDescending{it.isClickable}) {
            var target: AccessibilityNodeInfo?=candidate
            repeat(6){if(target?.isEnabled==true && target?.performAction(AccessibilityNodeInfo.ACTION_CLICK)==true){settle();return};target=target?.parent}
        }
        error("Not clickable: $label; "+candidates.joinToString{"${it.className}:click=${it.isClickable}:checked=${it.isChecked}:selected=${it.isSelected}"})
    }
    private fun fixture(): WegoState {
        val base=PackCodec.decode(activity.assets.open("packs/01-city-story.json").use{PackCodec.read(it)})
        return WegoState(packs=listOf(base),selectedKey=base.key,setupAllowed=true,storageReady=true,locationConsented=true)
    }
    private fun render(route: String,width: Int=1700,dark: Boolean=false) {
        val data=fixture().let {if(headerFixture)it.copy(active=true,completed=setOf(it.selected!!.stops.first().id))else it}
        instrumentation.runOnMainSync {activity.setContent {key("$route-$width-$dark"){WegoCarTheme(dark=dark){Box(Modifier.width(width.dp).fillMaxHeight()){
            PlatformScreen(data,route){exit->WegoVehicleScreen(data,{businessCalls++},{businessCalls++},{businessCalls++},{businessCalls++},{businessCalls++},{businessCalls++},{businessCalls++},{businessCalls++},{businessCalls++},onRootBack=exit,onPlatform=exit)}
        }}}}}
        settle()
    }
    private fun capture(label: String): Bitmap {
        val image=instrumentation.uiAutomation.takeScreenshot() ?: error("Actual display capture unavailable")
        File(activity.cacheDir,"ux-$label.png").outputStream().use{image.compress(Bitmap.CompressFormat.PNG,100,it)}
        val hierarchy=JSONArray()
        nodes().forEach {n->hierarchy.put(JSONObject().put("text",n.text).put("description",n.contentDescription)
            .put("state",n.stateDescription).put("selected",n.isSelected).put("checked",n.isChecked).put("bounds",bounds(n).toShortString()))}
        File(activity.cacheDir,"ux-$label-accessibility.json").writeText(hierarchy.toString(2))
        return image
    }
    fun testSharedPageNavigationAndDiscoverAlignment() {
        headerFixture=true;businessCalls=0
        for(width in listOf(320,628,1700))for(dark in listOf(false,true)) {
            render("discover",width,dark)
            fun header() {
                val back=bounds(node("뒤로"));val home=bounds(node("홈"));val menu=bounds(node("전체 메뉴"))
                val density=activity.resources.displayMetrics.density
                for(hit in listOf(back,home,menu))assertTrue("Header touch height below 80dp: $hit",hit.height()>=80*density-1)
                assertFalse("Back/Home overlap",Rect.intersects(back,home))
                assertFalse("Back/menu overlap",Rect.intersects(back,menu))
                assertFalse("Home/menu overlap",Rect.intersects(home,menu))
                observations.put(JSONObject().put("width",width).put("dark",dark).put("back",back.toShortString()).put("home",home.toShortString()).put("menu",menu.toShortString()))
            }
            header()
            node("차량을 연결해 주세요")
            click("전체 메뉴");click("경로");header()
            click("전체 메뉴");click("친구");header()
            click("뒤로");header();node("경로")
            click("홈");node("차량을 연결해 주세요")
            click("뒤로");node("차량을 연결해 주세요")
            assertEquals("Screen-only navigation invoked controller mutation",0,businessCalls)
            capture("shared-navigation-$width-$dark").recycle()
        }
    }
    fun testMenuAnchorAndPressedPosition() {
        for(width in listOf(628,1700))for(dark in listOf(false,true)) {
            render("friends",width,dark)
            val suffix="$width${if(dark)"-night" else ""}"
            val before=bounds(node("전체 메뉴"))
            // Observe actual label/arrow ink against the actual accessibility hit bounds.
            // The 16/8 contract comes from official Figma primary_button 67:27627.
            val display=capture("menu-insets-$suffix")
            var minX=before.right;var maxX=before.left;var minY=before.bottom;var maxY=before.top
            for(y in before.top until before.bottom)for(x in before.left until before.right) {
                val color=display.getPixel(x,y)
                val r=android.graphics.Color.red(color);val g=android.graphics.Color.green(color);val b=android.graphics.Color.blue(color)
                val ink=if(dark)r>220 && g>220 && b>220 else r<70 && g<70 && b<70
                if(ink){minX=minOf(minX,x);maxX=maxOf(maxX,x);minY=minOf(minY,y);maxY=maxOf(maxY,y)}
            }
            display.recycle();assertTrue("Header label/icon ink absent",maxX>=minX && maxY>=minY)
            val density=activity.resources.displayMetrics.density
            val leftInset=minX-before.left;val rightInset=before.right-maxX-1
            assertTrue("Header label touches trigger edge: $leftInset",leftInset>=16*density-1)
            assertTrue("Header arrow touches trigger edge: $rightInset",rightInset>=16*density-1)
            assertTrue("Header content touches vertical edge",minY-before.top>=8*density-1 && before.bottom-maxY-1>=8*density-1)
            val downTime=SystemClock.uptimeMillis()
            fun touch(action: Int) {
                val event=MotionEvent.obtain(downTime,SystemClock.uptimeMillis(),action,before.exactCenterX(),before.exactCenterY(),0)
                event.source=InputDevice.SOURCE_TOUCHSCREEN
                assertTrue(instrumentation.uiAutomation.injectInputEvent(event,true));event.recycle()
            }
            touch(MotionEvent.ACTION_DOWN);Thread.sleep(100)
            val pressed=bounds(node("전체 메뉴"));capture("menu-pressed-$suffix").recycle()
            touch(MotionEvent.ACTION_UP);settle()
            assertTrue("Header moved horizontally",kotlin.math.abs(before.left-pressed.left)<=1 && kotlin.math.abs(before.right-pressed.right)<=1)
            val menu=bounds(node("발견"))
            assertTrue("Menu is not anchored below trigger: $before / $menu",menu.top>=before.bottom-1)
            assertTrue("Menu is detached from trigger",kotlin.math.abs(menu.left-before.left)<=32)
            capture("menu-open-$suffix").recycle()
            observations.put(JSONObject().put("width",width).put("dark",dark).put("contentLeftInsetPx",leftInset).put("contentRightInsetPx",rightInset).put("contentTopInsetPx",minY-before.top).put("contentBottomInsetPx",before.bottom-maxY-1).put("density",density).put("trigger",before.toShortString()).put("pressed",pressed.toShortString()).put("menu",menu.toShortString()))
            click("발견");node("차량을 연결해 주세요")
        }
    }
    fun testSelectionDatesQrAndDeparture() {
        render("challenge")
        assertTrue(node("함께 완주하기").isChecked || node("함께 완주하기").isSelected)
        click("밥값은 내가");assertTrue(node("밥값은 내가").isChecked || node("밥값은 내가").isSelected);assertFalse(node("함께 완주하기").isChecked || node("함께 완주하기").isSelected)
        val selectedBounds=bounds(node("밥값은 내가"));val selectedImage=capture("selection")
        val density=activity.resources.displayMetrics.density
        val centerX=(selectedBounds.right-48*density).toInt();val centerY=selectedBounds.centerY()
        fun near(actual: Int,r: Int,g: Int,b: Int)=kotlin.math.abs(android.graphics.Color.red(actual)-r)<=3 && kotlin.math.abs(android.graphics.Color.green(actual)-g)<=3 && kotlin.math.abs(android.graphics.Color.blue(actual)-b)<=3
        assertTrue("Selected radio must use reviewed basic900 ring",near(selectedImage.getPixel(centerX+(18*density).toInt(),centerY),19,20,23))
        assertTrue("Selected radio center must be white",near(selectedImage.getPixel(centerX,centerY),255,255,255))
        selectedImage.recycle()
        render("results");capture("dates").recycle()
        for(date in listOf("2026.10.24 (토)","2026.10.18 (일)"))assertTrue("Record date not visible: $date",nodes().any{it.text?.toString()?.contains(date)==true || it.contentDescription?.toString()?.contains(date)==true})
        for(invite in listOf("room"))for(dark in listOf(false,true)) {
            render("room-join",628,dark)
            val label="qr"
            val qr=bounds(node("초대 QR"));val screen=capture("$label-${if(dark)"night" else "day"}")
            assertTrue(qr.left>=0 && qr.top>=0 && qr.right<=screen.width && qr.bottom<=screen.height)
            val pixels=IntArray(qr.width()*qr.height());screen.getPixels(pixels,0,qr.width(),qr.left,qr.top,qr.width(),qr.height())
            val decoded=MultiFormatReader().decode(BinaryBitmap(HybridBinarizer(RGBLuminanceSource(qr.width(),qr.height(),pixels)))).text
            assertEquals("WEGOH-PREVIEW:ROOM:WEGO25",decoded);screen.recycle()
            observations.put(JSONObject().put("invite",invite).put("qrDecoded",decoded).put("dark",dark).put("bounds",qr.toShortString()))
        }
        render("pack",628)
        val action=bounds(node("출발"));val screen=capture("course-before")
        assertTrue("Departure hidden below viewport",action.bottom<=screen.height);screen.recycle()
        click("출발");node("준비 중입니다");assertFalse(activity.controller.state.active)
        capture("course-departure").recycle()
        observations.put(JSONObject().put("selectedStateVerified",true).put("selectedAppearanceVerified",true).put("dateWeekdaysVerified",true).put("departureVisible",true).put("previewDidNotStartLiveSession",true).put("unavailableNoticeVerified",true))
    }
    /** Actual day/night selected pixels and semantics only; not disabled/loading evidence. */
    fun testSelectedControlThemes() {
        for(dark in listOf(false,true)) {
            render("challenge",628,dark)
            click("밥값은 내가")
            val selected=node("밥값은 내가");val unselected=node("함께 완주하기")
            assertTrue(selected.isChecked || selected.isSelected)
            assertFalse(unselected.isChecked || unselected.isSelected)
            val rect=bounds(selected);val density=activity.resources.displayMetrics.density
            val x=(rect.right-48*density).toInt();val y=rect.centerY()
            val image=capture("selection-${if(dark)"night" else "day"}")
            val on=if(dark)intArrayOf(255,255,255)else intArrayOf(19,20,23)
            val mark=if(dark)intArrayOf(19,20,23)else intArrayOf(255,255,255)
            fun matches(color: Int,expected: IntArray)=kotlin.math.abs(android.graphics.Color.red(color)-expected[0])<=3 &&
                kotlin.math.abs(android.graphics.Color.green(color)-expected[1])<=3 && kotlin.math.abs(android.graphics.Color.blue(color)-expected[2])<=3
            val ring=image.getPixel(x+(18*density).toInt(),y);val center=image.getPixel(x,y)
            assertTrue("Selected basic color mismatch for dark=$dark",matches(ring,on))
            assertTrue("Selected mark color mismatch for dark=$dark",matches(center,mark))
            image.recycle()
            observations.put(JSONObject().put("dark",dark).put("selectedRingArgb",ring).put("selectedMarkArgb",center)
                .put("selectedStateVerified",true).put("unselectedStateVerified",true))
        }
    }
    fun testListPagingAndVersions() {
        val base=fixture().packs.first();val packs=(1..16).map{base.copy(id="ux-fixture-$it",version=it,title="합성 코스 $it")}
        val data=mutableStateOf(fixture().copy(packs=packs,selectedKey=packs.first().key))
        instrumentation.runOnMainSync {activity.setContent {WegoCarTheme {WegoVehicleScreen(data.value,
            onSelect={key->data.value=data.value.copy(selectedKey=key)},onImport={},onStart={},onStop={},onNavigate={},onReset={},onBrowse={},onDownload={},onShareVisits={})}}}
        settle();node("경로 목록");node("1 / 16")
        capture("list-initial").recycle()
        assertTrue("Selected course not exposed",nodes().any{(it.contentDescription?.toString()=="합성 코스 1" || it.text?.toString()?.contains("합성 코스 1")==true) && (it.isChecked || it.isSelected || it.stateDescription?.toString()?.contains("선택됨")==true)})
        assertTrue(node("경로 목록 아래로").isEnabled);click("경로 목록 아래로")
        assertTrue(node("경로 목록 위로").isEnabled)
        assertFalse(nodes().any{it.text?.toString()=="1 / 16"})
        assertTrue(nodes().any{it.text?.toString()?.let {value->Regex("\\bv[0-9]+\\b").containsMatchIn(value)}==true})
        capture("list-paging").recycle()
        observations.put(JSONObject().put("syntheticCourses",16).put("pagingVerified",true).put("versionVisible",true))
    }
    fun testNavigationFreshnessAndUnknownTraffic() {
        val metrics=NavigationOverview("synthetic/1",listOf(NavigationLeg("a",60,100),NavigationLeg("b",180,300)),1000,
            listOf(NavigationTraffic(150.0,200.0,"HEAVY")),1000)
        assertEquals("약 1분",metrics.timeLabel(0,1000));assertEquals("약 2분",metrics.timeLabel(1,1000))
        assertEquals("교통 미확인",metrics.trafficLabel(0,1000));assertEquals("정체 포함",metrics.trafficLabel(1,1000))
        assertEquals("시간 미확인",metrics.timeLabel(1,92000));assertEquals("교통 미확인",metrics.trafficLabel(1,92000))
        assertEquals("교통 미확인",metrics.copy(trafficReceivedAt=null).trafficLabel(1,1000))
        assertEquals("시간 미확인",metrics.copy(legs=listOf(NavigationLeg("a",100,100),NavigationLeg("b",50,200))).timeLabel(1,1000))
        observations.put(JSONObject().put("cumulativeToLegSeconds",true).put("unknownAndStaleRejected",true))
    }
}
