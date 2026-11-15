package io.wegoh.app

import android.accessibilityservice.AccessibilityServiceInfo
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Rect
import android.os.SystemClock
import android.view.accessibility.AccessibilityNodeInfo
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.google.zxing.BinaryBitmap
import com.google.zxing.MultiFormatReader
import com.google.zxing.RGBLuminanceSource
import com.google.zxing.common.HybridBinarizer
import io.wegoh.app.nativeauth.VehicleConnection
import io.wegoh.app.ui.WegoCarTheme
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/** Actual product composable with declared synthetic public progress; real profile/API untouched. */
class VehicleConnectionUiTest : FirstRunPermissionsCompletedTestCase() {
    private var uiHost: MainActivity?=null
    private fun focusHost() {
        val host=requireNotNull(uiHost)
        val frames=java.util.concurrent.CountDownLatch(1)
        instrumentation.runOnMainSync {host.window.decorView.postOnAnimation {host.window.decorView.postOnAnimation {frames.countDown()}}}
        assertTrue(frames.await(3,java.util.concurrent.TimeUnit.SECONDS))
        repeat(3) {
            if(!host.hasWindowFocus()) {
                val origin=IntArray(2);instrumentation.runOnMainSync {host.window.decorView.getLocationOnScreen(origin)}
                android.os.ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand(
                    "input tap ${origin[0]+host.window.decorView.width/2} ${origin[1]+host.window.decorView.height/4}")).use {it.readBytes()}
            }
            Thread.sleep(150)
            if(host.hasWindowFocus())return
        }
        assertTrue("Test Main window focused before idle checks",host.hasWindowFocus())
    }
    fun testRechecksRetainConnectedBodyAndDisableActions() = rechecksRetainConnectedBodyAndDisableActions()

    private fun rechecksRetainConnectedBodyAndDisableActions() {
        val automation=instrumentation.uiAutomation
        val info=automation.serviceInfo;val old=info.flags
        info.flags=old or AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS;automation.serviceInfo=info
        val activity=instrumentation.startActivitySync(Intent(instrumentation.targetContext,MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        uiHost=activity
        var actions=0
        var starts=0
        val progress=androidx.compose.runtime.mutableStateOf(VehicleConnection.Progress(VehicleConnection.Stage.CHECKING))
        val bodyWidth=(instrumentation as android.test.InstrumentationTestRunner).arguments.getString("connectionBodyWidth")?.toInt()?.also {require(it==840)}
        fun settle() {
            val frame=java.util.concurrent.CountDownLatch(1)
            instrumentation.runOnMainSync {activity.window.decorView.postOnAnimation {activity.window.decorView.postOnAnimation {frame.countDown()}}}
            assertTrue(frame.await(3,java.util.concurrent.TimeUnit.SECONDS))
            val until=SystemClock.elapsedRealtime()+5000
            while(!activity.hasWindowFocus() && SystemClock.elapsedRealtime()<until)Thread.sleep(25)
            assertTrue("Presentation fixture is focused without injecting an input tap",activity.hasWindowFocus())
        }
        fun awaitText(label: String) {
            val end=SystemClock.elapsedRealtime()+15000
            while(SystemClock.elapsedRealtime()<end) {
                if(nodes().any {it.text?.toString()==label || it.contentDescription?.toString()==label})return
                Thread.sleep(50)
            }
            fail("Connection presentation missing: $label")
        }
        fun shownNode(label: String): AccessibilityNodeInfo {
            awaitText(label)
            return nodes().first {it.text?.toString()==label || it.contentDescription?.toString()==label}
        }
        val geometry=JSONArray()
        try {
            instrumentation.runOnMainSync {activity.setContent {WegoCarTheme {
                Box(if(bodyWidth==null)Modifier else Modifier.width(bodyWidth.dp)) {
                    ConnectionScreen(progress.value,true,{},{},{starts++},{},{},{actions++},{})
                }
            }}}
            settle();awaitText("연결 확인 중")
            assertEquals("Initial connection checking has one status label",1,nodes().count {it.text?.toString()=="연결 확인 중"})
            val initial=instrumentation.uiAutomation.takeScreenshot()!!
            val origin=IntArray(2);instrumentation.runOnMainSync {activity.window.decorView.getLocationOnScreen(origin)}
            val width=bodyWidth ?: activity.window.decorView.width
            val crop=Bitmap.createBitmap(initial,origin[0],origin[1],width,activity.window.decorView.height)
            activity.openFileOutput("connection-checking-ui.png",0).use {crop.compress(Bitmap.CompressFormat.PNG,100,it)}
            crop.recycle();initial.recycle()
            instrumentation.runOnMainSync {progress.value=VehicleConnection.Progress(VehicleConnection.Stage.CONNECTING)}
            instrumentation.waitForIdleSync()
            awaitText("연결 확인 중")
            assertEquals("Connecting has one status label",1,nodes().count {it.text?.toString()=="연결 확인 중"})
            val connected=VehicleConnection.Progress(VehicleConnection.Stage.CONNECTED,approvedOptionalScopes=VehicleConnection.DEFAULT_SCOPES)
            instrumentation.runOnMainSync {progress.value=connected};awaitText("연결됨")
            repeat(3) {
                instrumentation.runOnMainSync {progress.value=VehicleConnection.Progress(VehicleConnection.Stage.CHECKING,previousConnection=connected)}
                awaitText("연결 상태 확인 중")
                assertTrue(nodes().any {it.text?.toString()=="연결됨"})
                assertFalse(nodes().any {it.text?.toString()=="연결 확인 중"})
                shownNode("다른 계정으로 연결").performAction(AccessibilityNodeInfo.ACTION_CLICK)
                instrumentation.runOnMainSync {}
                assertEquals("recheck allowed a connected action",0,actions)
                if(it==2) {
                    val bitmap=automation.takeScreenshot();assertNotNull(bitmap)
                    activity.openFileOutput("connection-recheck-ui.png",0).use {out->bitmap.compress(Bitmap.CompressFormat.PNG,100,out)}
                    bitmap.recycle()
                }
                instrumentation.runOnMainSync {progress.value=connected};awaitText("연결됨")
            }
            for(stage in listOf(VehicleConnection.Stage.UNAVAILABLE,VehicleConnection.Stage.RECOVERY_REQUIRED,
                VehicleConnection.Stage.EXPIRED,VehicleConnection.Stage.DENIED)) {
                instrumentation.runOnMainSync {progress.value=VehicleConnection.Progress(stage)}
                val title=when(stage) {
                    VehicleConnection.Stage.EXPIRED->"연결이 만료됐어요"
                    VehicleConnection.Stage.DENIED->"다시 연결해 주세요"
                    else->"연결을 확인해 주세요"
                }
                settle();awaitText(title)
                assertFalse(nodes().any {it.text?.toString()=="연결됨"})
                if(stage==VehicleConnection.Stage.UNAVAILABLE) {
                    val screenshot=automation.takeScreenshot()!!
                    val panel=Bitmap.createBitmap(screenshot,origin[0],origin[1],width,activity.window.decorView.height)
                    activity.openFileOutput("connection-error-ui.png",0).use {panel.compress(Bitmap.CompressFormat.PNG,100,it)}
                    panel.recycle();screenshot.recycle()
                }
                assertEquals("Connection failure title is not repeated: $stage",1,nodes().count {it.text?.toString()==title})
                var retry: AccessibilityNodeInfo?=shownNode("다시 시도")
                while(retry!=null && !retry.isClickable)retry=retry.parent
                assertNotNull(retry);assertTrue(retry!!.isEnabled)
                val heading=rect(shownNode(title));val button=rect(retry)
                val density=activity.resources.displayMetrics.density
                val frame=Rect(origin[0],rect(shownNode("뒤로")).bottom+(io.wegoh.app.ui.CarTokens.Gap.value*density).toInt(),
                    origin[0]+width,origin[1]+activity.window.decorView.height-(io.wegoh.app.ui.CarTokens.Gap.value*density).toInt())
                val horizontalTolerance=(io.wegoh.app.ui.CarTokens.BorderWidth.value*4*density).toInt().coerceAtLeast(1)
                val verticalTolerance=(io.wegoh.app.ui.CarTokens.Frame.value*density).toInt()
                assertTrue("Failure title stays in the content frame",frame.contains(heading))
                assertTrue("Retry stays in the content frame",frame.contains(button))
                assertTrue("Failure title is horizontally centered",kotlin.math.abs(heading.centerX()-frame.centerX())<=horizontalTolerance)
                assertTrue("Retry is horizontally centered",kotlin.math.abs(button.centerX()-frame.centerX())<=horizontalTolerance)
                assertTrue("Retry is below the title",button.top>=heading.bottom)
                assertTrue("Failure content is vertically centered",kotlin.math.abs((heading.top+button.bottom)/2-frame.centerY())<=verticalTolerance)
                geometry.put(JSONObject().put("stage",stage.name).put("frame",frame.toShortString())
                    .put("heading",heading.toShortString()).put("button",button.toShortString()))
                val before=starts
                assertTrue(retry.performAction(AccessibilityNodeInfo.ACTION_CLICK));instrumentation.runOnMainSync {}
                assertEquals("Retry remains actionable: $stage",before+1,starts)
            }
            assertEquals(0,actions)
            activity.openFileOutput("connection-error-ui-bounds.json",0).use {it.write(geometry.toString(2).toByteArray())}
            instrumentation.runOnMainSync {progress.value=VehicleConnection.Progress(VehicleConnection.Stage.CONNECTING)}
            settle();awaitText("연결 확인 중")
            assertEquals(1,nodes().count {it.text?.toString()=="연결 확인 중"})
            assertFalse(nodes().any {it.text?.toString()=="다시 시도"})
            val screenshot=automation.takeScreenshot()!!
            val panel=Bitmap.createBitmap(screenshot,origin[0],origin[1],width,activity.window.decorView.height)
            activity.openFileOutput("connection-retry-ui.png",0).use {panel.compress(Bitmap.CompressFormat.PNG,100,it)}
            panel.recycle();screenshot.recycle()
        }finally{info.flags=old;automation.serviceInfo=info;instrumentation.runOnMainSync {activity.finish()}}
    }
    fun testWalkthroughSkipRestrictionAndThemes() {
        val info=instrumentation.uiAutomation.serviceInfo;val old=info.flags
        info.flags=old or AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS;instrumentation.uiAutomation.serviceInfo=info
        val context=instrumentation.targetContext
        val profile="guide_ui_"+java.util.UUID.randomUUID()
        val isolated=object: android.content.ContextWrapper(context) {
            override fun getSharedPreferences(name: String,mode: Int)=context.getSharedPreferences(profile+name,mode)
        }
        val guide=FirstRunGuide(isolated)
        val activity=instrumentation.startActivitySync(Intent(context,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        uiHost=activity;focusHost()
        val allowed=androidx.compose.runtime.mutableStateOf(true)
        val dark=androidx.compose.runtime.mutableStateOf(false)
        val directory=File(activity.noBackupFilesDir,"walkthrough-ui-"+java.util.UUID.randomUUID()).apply {mkdir()}
        var dialog: android.app.Dialog?=null
        fun click(label: String) {
            var n: AccessibilityNodeInfo?=node(label)
            while(n!=null && !n.isClickable)n=n.parent
            assertNotNull(n);assertTrue(n!!.performAction(AccessibilityNodeInfo.ACTION_CLICK));instrumentation.waitForIdleSync()
        }
        try {
            instrumentation.runOnMainSync {activity.setContent {WegoCarTheme(dark.value) {Box(Modifier.width(628.dp).fillMaxHeight()) {
                ConnectionEntry(fullScreen=true) {if(!guide.completed)FirstRunWalkthrough(allowed.value,{activity.hasWindowFocus()},guide::complete)
                    else io.wegoh.app.ui.CarText("Synthetic completed introduction")}
            }}}}
            instrumentation.waitForIdleSync()
            if(!activity.hasWindowFocus()) {
                val origin=IntArray(2);instrumentation.runOnMainSync {activity.window.decorView.getLocationOnScreen(origin)}
                android.os.ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand(
                    "input tap ${origin[0]+16} ${origin[1]+120}")).use {it.readBytes()}
            }
            node("경로를 차에서 시작해요");click("다음");node("내 음악을 차에서")
            instrumentation.runOnMainSync {allowed.value=false};node("P단에서 이용할 수 있어요")
            assertFalse(guide.completed);assertFalse(nodes().any {it.contentDescription?.toString() in setOf("다음","건너뛰기")})
            instrumentation.runOnMainSync {allowed.value=true};node("내 음악을 차에서")
            for(night in listOf(false,true)) {
                instrumentation.runOnMainSync {dark.value=night};instrumentation.waitForIdleSync();node("내 음악을 차에서")
                val origin=IntArray(2);instrumentation.runOnMainSync {activity.window.decorView.getLocationOnScreen(origin)}
                for(label in listOf("내 음악을 차에서","저장한 음악 링크를 차에서 열어요","이전","다음","건너뛰기")) {
                    val bounds=rect(node(label))
                    assertTrue("Narrow guide is fully within viewport: $label",bounds.left>=origin[0] && bounds.right<=origin[0]+628 &&
                        bounds.top>=origin[1] && bounds.bottom<=origin[1]+activity.window.decorView.height)
                }
                val frames=java.util.concurrent.CountDownLatch(1)
                instrumentation.runOnMainSync {activity.window.decorView.postOnAnimation {
                    activity.window.decorView.postOnAnimation {frames.countDown()}
                }}
                assertTrue(frames.await(3,java.util.concurrent.TimeUnit.SECONDS))
                val screen=instrumentation.uiAutomation.takeScreenshot()!!
                val crop=Bitmap.createBitmap(screen,origin[0],origin[1],628,activity.window.decorView.height)
                File(directory,if(night)"walkthrough-night.png" else "walkthrough-day.png").outputStream().use {crop.compress(Bitmap.CompressFormat.PNG,100,it)}
                crop.recycle();screen.recycle()
            }
            val staleSkip=node("건너뛰기")
            instrumentation.runOnMainSync {dialog=android.app.Dialog(activity).apply {setContentView(android.widget.TextView(activity).apply {text="Synthetic focus cover"});show()}}
            val end=SystemClock.uptimeMillis()+5000
            while(activity.hasWindowFocus() && SystemClock.uptimeMillis()<end)Thread.sleep(40)
            assertFalse(activity.hasWindowFocus())
            var owner: AccessibilityNodeInfo?=staleSkip
            while(owner!=null && !owner.isClickable)owner=owner.parent
            owner?.performAction(AccessibilityNodeInfo.ACTION_CLICK);instrumentation.waitForIdleSync();assertFalse(guide.completed)
            instrumentation.runOnMainSync {dialog!!.dismiss()};node("건너뛰기");click("건너뛰기")
            node("Synthetic completed introduction");assertTrue(FirstRunGuide(isolated).completed)
            File(directory,"result.json").writeText(JSONObject().put("skipPersists",true).put("restrictionPreservesPage",true)
                .put("staleActionWithoutFocusDoesNotComplete",true).put("themesCaptured",true)
                .put("limits","Isolated preference store and real628dp composable; allowed modeled, actual Dialog focus. No authentication request or real profile mutation.").toString(2))
            instrumentation.sendStatus(0,android.os.Bundle().apply {putString("fixtureDirectory",directory.name)})
        } finally {
            instrumentation.runOnMainSync {dialog?.dismiss();activity.finish()}
            info.flags=old;instrumentation.uiAutomation.serviceInfo=info
        }
    }
    // Current isolated pending fixture exercises real Panel focus/lifecycle,
    // setup restriction and disposal. Observer-handle cleanup is a separate source
    // review boundary; live account/CA/actual CarUx-service transitions are excluded.
    fun testInlinePairQrFocusLifecycleAndRestriction() {
        val info=instrumentation.uiAutomation.serviceInfo;val old=info.flags
        info.flags=old or AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS;instrumentation.uiAutomation.serviceInfo=info
        val context=instrumentation.targetContext
        val noCapture=(instrumentation as android.test.InstrumentationTestRunner).arguments.getString("noCapture")=="true"
        val profile="inline_ui_"+java.util.UUID.randomUUID().toString().replace("-","").take(24)
        val permissionContext=object: android.content.ContextWrapper(context) {
            override fun getSharedPreferences(name: String,mode: Int)=context.getSharedPreferences(profile+name,mode)
        }
        permissionContext.getSharedPreferences("first_run_permissions",android.content.Context.MODE_PRIVATE)
            .edit().putBoolean("completed",true).commit()
        val store=io.wegoh.app.nativeauth.NativeConnectionState(context,profile)
        val uri="https://wegoh.devforest.io/enroll.html?user_code=ABCD2345"
        store.locked {
            store.initialize();val root=store.read()
            io.wegoh.app.nativeauth.NativeDeviceIdentity(context,root.getString("installationId")).initialize()
            root.put("identityInitialized",true).put("publicContract",1)
                .put("access",JSONObject().put("epoch",1).put("phase","pending").put("outbox",JSONArray())
                .put("authorization",JSONObject().put("response",JSONObject().put("state","PENDING"))
                    .put("nextPollAt",System.currentTimeMillis()+3600000)
                    .put("public",JSONObject().put("userCode","ABCD2345").put("verificationUri",uri).put("expiresAt",System.currentTimeMillis()/1000+3600))))
            store.write(root)
        }
        val connection=VehicleConnection.existingProfile(context,profile)
        val activity=instrumentation.startActivitySync(Intent(context,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        uiHost=activity;focusHost()
        val owner=object: androidx.lifecycle.LifecycleOwner {
            val registry=androidx.lifecycle.LifecycleRegistry(this)
            override val lifecycle: androidx.lifecycle.Lifecycle get()=registry
        }
        val allowed=androidx.compose.runtime.mutableStateOf(true)
        val dark=androidx.compose.runtime.mutableStateOf(false)
        val directory=File(activity.noBackupFilesDir,"inline-connection-ui-"+java.util.UUID.randomUUID()).apply {mkdir()}
        var dialog: android.app.Dialog?=null
        fun await(label: String,predicate: ()->Boolean) {
            val end=SystemClock.uptimeMillis()+5000
            while(SystemClock.uptimeMillis()<end){if(predicate())return;Thread.sleep(40)}
            fail(label)
        }
        try {
            instrumentation.runOnMainSync {
                owner.registry.currentState=androidx.lifecycle.Lifecycle.State.RESUMED
                activity.setContent {
                    androidx.compose.runtime.CompositionLocalProvider(androidx.lifecycle.compose.LocalLifecycleOwner provides owner,
                        androidx.compose.ui.platform.LocalContext provides permissionContext) {
                        WegoCarTheme(dark.value) {Box(Modifier.width(628.dp).fillMaxHeight()) {
                            VehicleConnectionPanel(connection,allowed.value,onboarding=true)
                        }}
                    }
                }
            }
            for(night in listOf(false,true)) {
                instrumentation.runOnMainSync {dark.value=night}
                val qr=rect(node("차량 연결 QR 코드"));node("ABCD2345")
                assertFalse(nodes().any {it.contentDescription?.toString() in setOf("뒤로","홈","전체 메뉴")})
                val screen=instrumentation.uiAutomation.takeScreenshot()!!
                val pixels=IntArray(qr.width()*qr.height());screen.getPixels(pixels,0,qr.width(),qr.left,qr.top,qr.width(),qr.height())
                assertEquals(uri,MultiFormatReader().decode(BinaryBitmap(HybridBinarizer(RGBLuminanceSource(qr.width(),qr.height(),pixels)))).text)
                val origin=IntArray(2);instrumentation.runOnMainSync {activity.window.decorView.getLocationOnScreen(origin)}
                val crop=Bitmap.createBitmap(screen,origin[0],origin[1],628,activity.window.decorView.height)
                if(!noCapture)File(directory,if(night)"inline-night.png" else "inline-day.png").outputStream().use {crop.compress(Bitmap.CompressFormat.PNG,100,it)}
                crop.recycle();screen.recycle()
            }
            instrumentation.runOnMainSync {dialog=android.app.Dialog(activity).apply {setContentView(android.widget.TextView(activity).apply {text="Synthetic focus cover"});show()}}
            await("Cover did not take focus") {!activity.hasWindowFocus()}
            await("Inline approval remained exposed without window focus") {connection.status().userCode==null}
            instrumentation.runOnMainSync {dialog!!.dismiss()};node("ABCD2345")
            instrumentation.runOnMainSync {owner.registry.currentState=androidx.lifecycle.Lifecycle.State.CREATED}
            await("Inline approval remained exposed in background") {connection.status().userCode==null}
            instrumentation.runOnMainSync {owner.registry.currentState=androidx.lifecycle.Lifecycle.State.RESUMED};node("ABCD2345")
            instrumentation.runOnMainSync {allowed.value=false};node("P단에서 이용할 수 있어요")
            await("Inline approval survived setup restriction/disposal") {connection.status().userCode==null}
            assertFalse(nodes().any {it.text?.toString()=="ABCD2345"})
            instrumentation.runOnMainSync {allowed.value=true};node("ABCD2345")
            instrumentation.runOnMainSync {owner.registry.currentState=androidx.lifecycle.Lifecycle.State.CREATED}
            await("Paused inline owner retained approval") {connection.status().userCode==null}
            connection.setForeground(true)
            await("Next owner did not receive approval") {connection.status().userCode=="ABCD2345"}
            instrumentation.runOnMainSync {activity.setContent {WegoCarTheme {io.wegoh.app.ui.CarText("Synthetic next page")}}}
            instrumentation.waitForIdleSync()
            assertEquals("Old disposal cleared the next owner", "ABCD2345",connection.status().userCode)
            connection.setForeground(false)
            File(directory,"result.json").writeText(JSONObject().put("inlinePairQrThemesDecoded",true).put("focusCoverMasksApproval",true)
                .put("lifecycleMasksApproval",true).put("setupRestrictionMasksApproval",true).put("disposalPreservesNextOwner",true)
                .put("limits","Isolated pending snapshot with future retry; no live account or server polling assertion. Lifecycle/allowed injected, actual Dialog focus.").toString(2))
            instrumentation.sendStatus(0,android.os.Bundle().apply {putString("fixtureDirectory",directory.name)})
        } finally {
            instrumentation.runOnMainSync {dialog?.dismiss();activity.finish()};connection.close()
            permissionContext.getSharedPreferences("first_run_permissions",android.content.Context.MODE_PRIVATE).edit().clear().commit()
            info.flags=old;instrumentation.uiAutomation.serviceInfo=info
        }
    }
    fun testConnectionDoesNotPresentContentConsents() {
        val info=instrumentation.uiAutomation.serviceInfo;val old=info.flags
        info.flags=old or AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS;instrumentation.uiAutomation.serviceInfo=info
        val noCapture=(instrumentation as android.test.InstrumentationTestRunner).arguments.getString("noCapture")=="true"
        val activity=instrumentation.startActivitySync(Intent(instrumentation.targetContext,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        uiHost=activity;focusHost()
        val allowed=androidx.compose.runtime.mutableStateOf(true);var requests=0
        try {
            instrumentation.runOnMainSync {activity.setContent {WegoCarTheme {ConnectionScreen(
                VehicleConnection.Progress(VehicleConnection.Stage.CONNECTED,approvedOptionalScopes=VehicleConnection.Scope.entries.toSet(),
                    deniedOptionalScopes=setOf(VehicleConnection.Scope.COURSES)),allowed.value,{},{},{},{},{},{},onRequestScopes={requests++})}}}
            instrumentation.waitForIdleSync()
            node("연결됨")
            assertFalse(nodes().any {it.text?.toString() in setOf("이 차로 불러오는 것","권한 필요","허용됨","권한 추가","드라이브 코스","플레이리스트")})
            val directory=File(activity.noBackupFilesDir,"connection-ui-"+java.util.UUID.randomUUID()).apply {mkdir()}
            val screen=instrumentation.uiAutomation.takeScreenshot()!!
            if(!noCapture)File(directory,"connected.png").outputStream().use {screen.compress(Bitmap.CompressFormat.PNG,100,it)};screen.recycle()
            instrumentation.sendStatus(0,android.os.Bundle().apply {putString("fixtureDirectory",directory.name)})
            assertEquals(0,requests)
            instrumentation.runOnMainSync {allowed.value=false};instrumentation.waitForIdleSync();node("P단에서 이용할 수 있어요")
            assertFalse(nodes().any {it.text?.toString()=="권한 추가" || it.text?.toString()=="플레이리스트"})
        }finally{instrumentation.runOnMainSync {activity.finish()};info.flags=old;instrumentation.uiAutomation.serviceInfo=info}
    }
    fun testQrCountdownExpiryRetryAndThemes() {
        val info=instrumentation.uiAutomation.serviceInfo;val old=info.flags
        info.flags=old or AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS;instrumentation.uiAutomation.serviceInfo=info
        val activity=instrumentation.startActivitySync(Intent(instrumentation.targetContext,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        uiHost=activity;focusHost()
        val directory=File(activity.noBackupFilesDir,"qr-countdown-"+java.util.UUID.randomUUID()).apply {mkdir()}
        val deadline=System.currentTimeMillis()+10000
        fun pending(code: String,expires: Long)=VehicleConnection.Progress(VehicleConnection.Stage.APPROVAL_REQUIRED,code,
            "https://wegoh.devforest.io/enroll.html?user_code=$code",expires)
        val progress=androidx.compose.runtime.mutableStateOf(pending("ABCD2345",deadline))
        val dark=androidx.compose.runtime.mutableStateOf(false);val allowed=androidx.compose.runtime.mutableStateOf(true)
        val focused=androidx.compose.runtime.mutableStateOf(true);var retries=0
        fun await(label: String,test: ()->Boolean) {
            val end=SystemClock.elapsedRealtime()+15000
            while(SystemClock.elapsedRealtime()<end) {if(test())return;Thread.sleep(40)}
            fail(label)
        }
        fun capture(name: String) {
            instrumentation.waitForIdleSync()
            val origin=IntArray(2);instrumentation.runOnMainSync {activity.window.decorView.getLocationOnScreen(origin)}
            val screen=instrumentation.uiAutomation.takeScreenshot()!!
            val crop=Bitmap.createBitmap(screen,origin[0],origin[1],628,activity.window.decorView.height)
            File(directory,name+".png").outputStream().use {crop.compress(Bitmap.CompressFormat.PNG,100,it)}
            crop.recycle();screen.recycle()
        }
        fun decode(code: String) {
            val qr=rect(node("차량 연결 QR 코드"));val gauge=rect(node("연결 코드 유효 시간"))
            assertTrue(gauge.contains(qr));assertTrue(qr.left-gauge.left>=8 && gauge.right-qr.right>=8)
            val screen=instrumentation.uiAutomation.takeScreenshot()!!;val pixels=IntArray(qr.width()*qr.height())
            screen.getPixels(pixels,0,qr.width(),qr.left,qr.top,qr.width(),qr.height());screen.recycle()
            assertEquals("https://wegoh.devforest.io/enroll.html?user_code=$code",MultiFormatReader().decode(BinaryBitmap(HybridBinarizer(RGBLuminanceSource(qr.width(),qr.height(),pixels)))).text)
        }
        fun retry() {
            var item: AccessibilityNodeInfo?=node("다시 시도")
            while(item!=null && !item.isClickable)item=item.parent
            assertTrue(item!!.performAction(AccessibilityNodeInfo.ACTION_CLICK))
        }
        try {
            instrumentation.runOnMainSync {activity.setContent {WegoCarTheme(dark.value) {
                Box(Modifier.width(628.dp).fillMaxHeight()) {ConnectionEntry {ConnectionBody(progress.value,allowed.value,
                    onStart={retries++;progress.value=pending(if(retries==1)"EFGH2345" else "JKLM2345",System.currentTimeMillis()+300000)},
                    onRetry={},onDisconnect={},onSwitch={},canInteract={focused.value},onboarding=true)}}
            }}}
            instrumentation.waitForIdleSync()
            if(!activity.hasWindowFocus()) {
                val origin=IntArray(2);instrumentation.runOnMainSync {activity.window.decorView.getLocationOnScreen(origin)}
                android.os.ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand(
                    "input tap ${origin[0]+activity.window.decorView.width/2} ${origin[1]+activity.window.decorView.height/4}")).use {it.readBytes()}
            }
            capture("initial")
            val first=node("연결 코드 유효 시간").rangeInfo.current;assertTrue(first>0.7f)
            await("countdown decreases") {node("연결 코드 유효 시간").rangeInfo.current<0.65f}
            decode("ABCD2345");capture("countdown-day")
            instrumentation.runOnMainSync {dark.value=true};decode("ABCD2345");capture("countdown-night")
            instrumentation.runOnMainSync {focused.value=false};node("연결 확인 중")
            assertFalse(nodes().any {it.contentDescription?.toString()=="차량 연결 QR 코드"})
            await("deadline passes while hidden") {System.currentTimeMillis()>deadline+50}
            instrumentation.runOnMainSync {focused.value=true};node("연결이 만료됐어요")
            assertFalse(nodes().any {it.text?.toString()=="ABCD2345" || it.contentDescription?.toString()=="차량 연결 QR 코드"})
            capture("expired");assertEquals(0,retries);retry();node("EFGH2345")
            assertEquals(1,retries);assertTrue(node("연결 코드 유효 시간").rangeInfo.current>0.98f);decode("EFGH2345");capture("retried")
            instrumentation.runOnMainSync {allowed.value=false};node("P단에서 이용할 수 있어요")
            assertFalse(nodes().any {it.contentDescription?.toString()=="연결 코드 유효 시간" || it.text?.toString()?.startsWith("남은 시간")==true})
            instrumentation.runOnMainSync {allowed.value=true;progress.value=VehicleConnection.Progress(VehicleConnection.Stage.RECOVERY_REQUIRED)}
            node("다시 시도");capture("failed");retry();node("JKLM2345");assertEquals(2,retries)
            File(directory,"result.json").writeText(JSONObject().put("synthetic",true).put("countdownDecreased",true)
                .put("expiryAfterHiddenRemovesQr",true).put("explicitRetryCount",retries).put("bothThemesQrDecoded",true)
                .put("gaugeOutsideQr",true).put("widthDp",628).put("restrictionHidesTimer",true)
                .put("limits","Actual product composable, modeled focus/setup and progress; actual wall clock expiry. Native TLS retry is separate; no live account mutation or actual driving proof.").toString(2))
            instrumentation.sendStatus(0,android.os.Bundle().apply {putString("fixtureDirectory",directory.name)})
        } catch(failure: Throwable) {
            runCatching {capture("failure")}
            File(directory,"failure-ax.txt").writeText(nodes().filter {it.packageName?.toString()==instrumentation.targetContext.packageName}.joinToString("\n") {"${it.text} | ${it.contentDescription} | ${it.rangeInfo?.current}"})
            instrumentation.sendStatus(0,android.os.Bundle().apply {putString("fixtureDirectory",directory.name)})
            throw failure
        } finally {instrumentation.runOnMainSync {activity.finish()};info.flags=old;instrumentation.uiAutomation.serviceInfo=info}
    }
    private fun nodes(): List<AccessibilityNodeInfo> {
        if(android.os.Build.VERSION.SDK_INT>=34)instrumentation.uiAutomation.clearCache()
        val out=mutableListOf<AccessibilityNodeInfo>()
        fun walk(n: AccessibilityNodeInfo?) {if(n!=null){if(n.isVisibleToUser)out.add(n);for(i in 0 until n.childCount)walk(n.getChild(i))}}
        instrumentation.uiAutomation.windows.forEach {walk(it.root)};return out
    }
    private fun node(label: String): AccessibilityNodeInfo {
        val end=SystemClock.uptimeMillis()+5000
        while(SystemClock.uptimeMillis()<end) {
            nodes().firstOrNull {it.text?.toString()==label||it.contentDescription?.toString()==label}?.let{return it}
            uiHost?.takeIf {!it.hasWindowFocus() && it.window.decorView.isShown}?.let {host ->
                val origin=IntArray(2);instrumentation.runOnMainSync {host.window.decorView.getLocationOnScreen(origin)}
                android.os.ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand(
                    "input tap ${origin[0]+host.window.decorView.width/2} ${origin[1]+host.window.decorView.height/4}")).use {it.readBytes()}
            }
            Thread.sleep(40)
        }
        error("Missing synthetic connection UI: $label")
    }
    private fun rect(n: AccessibilityNodeInfo)=Rect().also {n.getBoundsInScreen(it)}
    fun testNativeConnectionQrThemesRestrictionAndBack() {
        val info=instrumentation.uiAutomation.serviceInfo;val old=info.flags
        info.flags=info.flags or AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS;instrumentation.uiAutomation.serviceInfo=info
        val activity=instrumentation.startActivitySync(Intent(instrumentation.targetContext,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        uiHost=activity;focusHost()
        val directory=File(activity.noBackupFilesDir,"connection-ui-"+java.util.UUID.randomUUID());assertTrue(directory.mkdir())
        val args=(instrumentation as android.test.InstrumentationTestRunner).arguments
        val noCapture=args.getString("noCapture")=="true"
        val output=JSONArray();var actions=0;var backs=0;var registrations=0
        val uri="https://wegoh.devforest.io/enroll.html?user_code=ABCD2345"
        val bundle=android.os.Bundle();bundle.putString("fixtureDirectory",directory.name);instrumentation.sendStatus(0,bundle)
        try {
            for(dark in listOf(false,true)) {
                instrumentation.runOnMainSync {activity.setContent {WegoCarTheme(dark){Box(Modifier.width(500.dp).fillMaxHeight()){
                    ConnectionScreen(VehicleConnection.Progress(VehicleConnection.Stage.APPROVAL_REQUIRED,"ABCD2345",uri,System.currentTimeMillis()+300000),true,
                        {backs++},{actions++},{actions++},{actions++},{actions++},{actions++})
                }}}}
                instrumentation.waitForIdleSync();Thread.sleep(200)
                val qr=rect(node("차량 연결 QR 코드"));val code=rect(node("ABCD2345"));val back=rect(node("뒤로"));val home=rect(node("홈"))
                assertTrue(back.width()>=80&&back.height()>=80&&home.width()>=80&&home.height()>=80)
                assertTrue(code.top>=qr.bottom);assertFalse(Rect.intersects(qr,code))
                val screenshot=instrumentation.uiAutomation.takeScreenshot()!!
                val crop=Bitmap.createBitmap(screenshot,qr.left,qr.top,qr.width(),qr.height());val pixels=IntArray(crop.width*crop.height);crop.getPixels(pixels,0,crop.width,0,0,crop.width,crop.height)
                assertEquals(uri,MultiFormatReader().decode(BinaryBitmap(HybridBinarizer(RGBLuminanceSource(crop.width,crop.height,pixels)))).text)
                crop.recycle()
                val origin=IntArray(2);instrumentation.runOnMainSync {activity.window.decorView.getLocationOnScreen(origin)}
                val width=(500*activity.resources.displayMetrics.density).toInt().coerceAtMost(screenshot.width-origin[0])
                val panel=Bitmap.createBitmap(screenshot,origin[0],origin[1],width,(activity.window.decorView.height).coerceAtMost(screenshot.height-origin[1]))
                if(!noCapture)File(directory,if(dark)"night.png" else "day.png").outputStream().use {panel.compress(Bitmap.CompressFormat.PNG,100,it)};panel.recycle();screenshot.recycle()
                output.put(JSONObject().put("dark",dark).put("syntheticWidthDp",500).put("qrDecoded",true).put("touchFloorDp",80))
            }
            instrumentation.runOnMainSync {activity.setContent {WegoCarTheme {ConnectionScreen(
                VehicleConnection.Progress(VehicleConnection.Stage.RECOVERY_REQUIRED,canRegisterAgain=true),true,
                {backs++},{actions++},{actions++},{actions++},{actions++},{actions++},onRegister={registrations++})}}}
            instrumentation.waitForIdleSync()
            node("휴대전화에서 이전 기기의 연결을 해제하세요")
            if(args.getString("captureLoss")=="true") {
                val screenshot=instrumentation.uiAutomation.takeScreenshot()!!;val origin=IntArray(2)
                instrumentation.runOnMainSync {activity.window.decorView.getLocationOnScreen(origin)}
                val width=(500*activity.resources.displayMetrics.density).toInt().coerceAtMost(screenshot.width-origin[0])
                val panel=Bitmap.createBitmap(screenshot,origin[0],origin[1],width,activity.window.decorView.height.coerceAtMost(screenshot.height-origin[1]))
                File(directory,"loss.png").outputStream().use {panel.compress(Bitmap.CompressFormat.PNG,100,it)};panel.recycle();screenshot.recycle()
            }
            // Resolve the enabled clickable semantics owner, not a stale label node
            // collected before screenshot/UIAutomation cache refresh.
            val register=node("새 기기로 등록");val registerRect=rect(register)
            assertTrue(registerRect.width()>=80 && registerRect.height()>=80)
            var owner: AccessibilityNodeInfo?=register
            while(owner!=null && !owner.isClickable)owner=owner.parent
            assertNotNull(owner);assertTrue(owner!!.isEnabled)
            assertTrue(owner.performAction(AccessibilityNodeInfo.ACTION_CLICK));instrumentation.waitForIdleSync()
            assertEquals(1,registrations);assertEquals(0,actions)
            instrumentation.runOnMainSync {activity.setContent {WegoCarTheme {ConnectionScreen(VehicleConnection.Progress(VehicleConnection.Stage.APPROVAL_REQUIRED,"ABCD2345",uri,System.currentTimeMillis()+300000),false,{backs++},{actions++},{actions++},{actions++},{actions++},{actions++})}}}
            instrumentation.waitForIdleSync();node("P단에서 이용할 수 있어요")
            assertFalse(nodes().any {it.contentDescription?.toString()=="차량 연결 QR 코드"||it.text?.toString()=="ABCD2345"})
            val back=node("뒤로");assertTrue(back.performAction(AccessibilityNodeInfo.ACTION_CLICK));instrumentation.waitForIdleSync();assertEquals(1,backs);assertEquals(0,actions)
            File(directory,"result.json").writeText(JSONObject().put("synthetic",true).put("themes",output).put("restrictionHidesCode",true).put("backCallback",1).put("executionCalls",0).put("explicitNewInstallationAction",registrations).put("limits","Width constrained fixture in default display; not official DISPLAY2/form-factor or actual CarUx transition proof.").toString(2))
        } finally {info.flags=old;instrumentation.uiAutomation.serviceInfo=info;instrumentation.runOnMainSync {activity.finish()}}
    }
    fun testLossRecoveryFrameAndExactCrop() {
        val info=instrumentation.uiAutomation.serviceInfo;val old=info.flags
        info.flags=old or AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS;instrumentation.uiAutomation.serviceInfo=info
        val activity=instrumentation.startActivitySync(Intent(instrumentation.targetContext,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        uiHost=activity;focusHost()
        val directory=File(activity.noBackupFilesDir,"connection-loss-"+java.util.UUID.randomUUID());assertTrue(directory.mkdir())
        try {
            instrumentation.runOnMainSync {activity.setContent {WegoCarTheme {Box(Modifier.width(500.dp).fillMaxHeight()) {ConnectionScreen(
                VehicleConnection.Progress(VehicleConnection.Stage.RECOVERY_REQUIRED,canRegisterAgain=true),true,{},{},{},{},{},{},onRegister={})}}}}
            instrumentation.waitForIdleSync()
            val label=rect(node("휴대전화에서 이전 기기의 연결을 해제하세요"));val action=rect(node("새 기기로 등록"))
            val frames=java.util.concurrent.CountDownLatch(1)
            instrumentation.runOnMainSync {activity.window.decorView.postOnAnimation {activity.window.decorView.postOnAnimation {frames.countDown()}}}
            assertTrue(frames.await(3,java.util.concurrent.TimeUnit.SECONDS));instrumentation.waitForIdleSync()
            val origin=IntArray(2);instrumentation.runOnMainSync {activity.window.decorView.getLocationOnScreen(origin)}
            val screenshot=instrumentation.uiAutomation.takeScreenshot()!!;val width=(500*activity.resources.displayMetrics.density).toInt()
            val bounds=Rect(origin[0],origin[1],origin[0]+width,origin[1]+activity.window.decorView.height)
            assertTrue(bounds.contains(label));assertTrue(bounds.contains(action));assertTrue(action.top>=label.bottom+8)
            assertTrue(action.width()>=80&&action.height()>=80)
            val panel=Bitmap.createBitmap(screenshot,bounds.left,bounds.top,bounds.width(),bounds.height())
            File(directory,"loss.png").outputStream().use {panel.compress(Bitmap.CompressFormat.PNG,100,it)};panel.recycle();screenshot.recycle()
            File(directory,"result.json").writeText(JSONObject().put("syntheticWidthDp",500).put("cropContainsBodyAndAction",true)
                .put("label",label.toShortString()).put("action",action.toShortString()).put("touchFloorDp",80)
                .put("limits","Exact500dp constrained product composable; not actual narrow DISPLAY2 or driving transition").toString(2))
            instrumentation.sendStatus(0,android.os.Bundle().apply {putString("fixtureDirectory",directory.name)})
        }finally{info.flags=old;instrumentation.uiAutomation.serviceInfo=info;instrumentation.runOnMainSync {activity.finish()}}
    }

}
