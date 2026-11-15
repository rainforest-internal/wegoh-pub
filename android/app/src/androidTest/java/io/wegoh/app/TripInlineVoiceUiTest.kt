package io.wegoh.app

import android.Manifest
import android.accessibilityservice.AccessibilityServiceInfo
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.graphics.Bitmap
import android.graphics.Rect
import android.os.SystemClock
import android.test.InstrumentationTestCase
import android.view.InputDevice
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.boundsInWindow
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.platform.ViewRootForTest
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getAllSemanticsNodes
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import io.wegoh.app.nativeauth.*
import io.wegoh.app.ui.*
import java.io.File
import java.util.concurrent.atomic.AtomicInteger
import kotlin.math.min
import kotlin.math.roundToInt

@Suppress("DEPRECATION")
class TripInlineVoiceUiTest: InstrumentationTestCase() {
    private lateinit var activity: TripScreensPreviewActivity
    private val state=mutableStateOf(TripInlineVoiceUi(TripInlineVoicePhase.LISTENING))
    private val present=mutableStateOf(true)
    private val presses=AtomicInteger()
    private val releases=AtomicInteger()
    private val cancels=AtomicInteger()
    private val participations=mutableListOf<Boolean>()
    private val retries=AtomicInteger()
    private var acceptsRecording=true
    private var frame=Rect()
    private var downAt=0L
    private var previousFlags=0

    override fun setUp() {
        super.setUp()
        val info=instrumentation.uiAutomation.serviceInfo
        previousFlags=info.flags
        info.flags=info.flags or AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS or AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
        instrumentation.uiAutomation.serviceInfo=info
        activity=instrumentation.startActivitySync(Intent(instrumentation.targetContext,TripScreensPreviewActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_MULTIPLE_TASK)) as TripScreensPreviewActivity
        instrumentation.runOnMainSync {
            WindowCompat.setDecorFitsSystemWindows(activity.window,false)
            WindowCompat.getInsetsController(activity.window,activity.window.decorView).hide(WindowInsetsCompat.Type.systemBars())
        }
    }

    override fun tearDown() {
        try {
            if(::activity.isInitialized)instrumentation.runOnMainSync {activity.setContent {};activity.finish()}
            val info=instrumentation.uiAutomation.serviceInfo;info.flags=previousFlags;instrumentation.uiAutomation.serviceInfo=info
        }
        finally {super.tearDown()}
    }

    private fun fixture(): TripDetail {
        val car="1".repeat(32)
        val account="team-"+"1".repeat(40)
        val stops=listOf(TripCourseStop("beach","경포해변",37.805,128.907),TripCourseStop("coffee","안목 커피거리",37.773,128.949))
        return TripDetail("a".repeat(32),"강릉 바다 여행","",listOf(TripMember(account,"사용자A",true,true,true,car)),
            listOf(TripCar(car,"사용자A 차",account,"사용자A",4,true,false,emptyList(),emptyList())),
            "2026-11-14","2026-11-15","active",1,courses=listOf(TripCourse("sea","바다 한 바퀴",1,2,"사용자A",true,true,emptyList(),stops)))
    }

    private fun render(width: Int=1704,dark: Boolean=false,permission: Boolean=false,windowSafety: Boolean=false) {
        val trip=fixture()
        val page=TripsPageState(AccountReadStatus.READY,selectedId=trip.id,detail=trip,isCurrent=true,gear=TripGear.PARK)
        instrumentation.runOnMainSync {activity.setContent {
            if(windowSafety) {
                val view=LocalView.current
                DisposableEffect(view) {
                    fun changed(focused: Boolean) {
                        state.value=state.value.withSafety(NativeVoiceAudioSafety(focused,true),true)
                            .copy(notice=if(focused)null else "정차한 상태에서 여행 화면을 열어 주세요")
                    }
                    val listener=android.view.ViewTreeObserver.OnWindowFocusChangeListener {changed(it)}
                    view.viewTreeObserver.addOnWindowFocusChangeListener(listener)
                    changed(view.hasWindowFocus())
                    onDispose {if(view.viewTreeObserver.isAlive)view.viewTreeObserver.removeOnWindowFocusChangeListener(listener)}
                }
            }
            BoxWithConstraints(Modifier.fillMaxSize().background(Color.Black),contentAlignment=Alignment.Center) {
                val scale=min(constraints.maxWidth.toFloat()/width,constraints.maxHeight.toFloat()/1208)
                val configuration=Configuration(LocalConfiguration.current).apply {
                    screenWidthDp=width;screenHeightDp=1208;smallestScreenWidthDp=min(width,1208);fontScale=1f
                }
                CompositionLocalProvider(LocalDensity provides Density(scale,1f),LocalConfiguration provides configuration) {
                    Box(Modifier.requiredSize(width.dp,1208.dp).onGloballyPositioned {
                        val bounds=it.boundsInWindow();val origin=IntArray(2);activity.window.decorView.getLocationOnScreen(origin)
                        frame=Rect(bounds.left.roundToInt()+origin[0],bounds.top.roundToInt()+origin[1],bounds.right.roundToInt()+origin[0],bounds.bottom.roundToInt()+origin[1])
                    }) {WegoCarTheme(dark=dark) {TripSurface {
                        TripActivePage(trip,page,true,TripUiActions(),{},{},{},voice={modifier->
                            if(present.value) {
                                if(permission)TripInlineVoiceWithMicrophone(state.value,{presses.incrementAndGet();acceptsRecording},{releases.incrementAndGet()},{participations.add(it)},{retries.incrementAndGet()},modifier,onCancel={cancels.incrementAndGet()})
                                else TripInlineVoiceControl(state.value,{presses.incrementAndGet();acceptsRecording},{releases.incrementAndGet()},{participations.add(it)},{retries.incrementAndGet()},modifier,onCancel={cancels.incrementAndGet()})
                            }
                        })
                    }}}
                }
            }
        }}
        settle()
    }

    private fun settle(){instrumentation.waitForIdleSync();Thread.sleep(100);instrumentation.waitForIdleSync()}
    private fun await(label: String,condition: ()->Boolean) {
        val deadline=SystemClock.elapsedRealtime()+6000
        while(SystemClock.elapsedRealtime()<deadline){if(condition())return;Thread.sleep(40)}
        fail(label)
    }

    private fun mic(): Pair<Rect,Boolean> {
        var found: Pair<Rect,Boolean>?=null
        instrumentation.runOnMainSync {
            fun inspect(view: View) {
                if(view is ViewRootForTest) {
                    view.semanticsOwner.getAllSemanticsNodes(mergingEnabled=false).firstOrNull {
                        it.config.getOrNull(SemanticsProperties.TestTag)=="trip-inline-voice-control"
                    }?.let {node->
                        assertEquals(Role.Button,node.config.getOrNull(SemanticsProperties.Role))
                        if(!node.config.contains(SemanticsProperties.Disabled))
                            assertTrue("Available voice control exposes an ordinary click",node.config.contains(SemanticsActions.OnClick))
                        val bounds=node.boundsInWindow;val origin=IntArray(2);activity.window.decorView.getLocationOnScreen(origin)
                        found=Rect(bounds.left.roundToInt()+origin[0],bounds.top.roundToInt()+origin[1],bounds.right.roundToInt()+origin[0],bounds.bottom.roundToInt()+origin[1]) to
                            node.config.contains(SemanticsProperties.Disabled)
                    }
                }
                if(view is ViewGroup)for(index in 0 until view.childCount)inspect(view.getChildAt(index))
            }
            inspect(activity.window.decorView)
        }
        return found ?: error("Inline microphone missing")
    }

    private fun voiceText(): List<String> {
        val values=mutableListOf<String>()
        instrumentation.runOnMainSync {
            fun inspect(view: View) {
                if(view is ViewRootForTest)for(node in view.semanticsOwner.getAllSemanticsNodes(mergingEnabled=false)) {
                    node.config.getOrNull(SemanticsProperties.StateDescription)?.let(values::add)
                    node.config.getOrNull(SemanticsActions.OnClick)?.label?.let(values::add)
                    node.config.getOrNull(SemanticsProperties.Text)?.forEach {values.add(it.text)}
                }
                if(view is ViewGroup)for(index in 0 until view.childCount)inspect(view.getChildAt(index))
            }
            inspect(activity.window.decorView)
        }
        return values
    }

    private fun voiceAction(label: String) {
        var clicked=false
        instrumentation.runOnMainSync {
            fun inspect(view: View) {
                if(view is ViewRootForTest)view.semanticsOwner.getAllSemanticsNodes(mergingEnabled=false).firstOrNull {
                    (if(label=="워키토키")it.config.getOrNull(SemanticsProperties.TestTag)=="trip-inline-voice-control"
                    else it.config.getOrNull(SemanticsProperties.ContentDescription)?.contains(label)==true) &&
                        !it.config.contains(SemanticsProperties.Disabled)
                }?.let {clicked=it.config.getOrNull(SemanticsActions.OnClick)?.action?.invoke()==true || clicked}
                if(view is ViewGroup)for(index in 0 until view.childCount)inspect(view.getChildAt(index))
            }
            inspect(activity.window.decorView)
        }
        assertTrue("Missing voice action: $label",clicked);settle()
    }

    private fun touch(action: Int,bounds: Rect=mic().first,outside: Boolean=false) {
        if(action==MotionEvent.ACTION_DOWN)downAt=SystemClock.uptimeMillis()
        val event=MotionEvent.obtain(downAt,SystemClock.uptimeMillis(),action,
            if(outside)bounds.left-48f else bounds.exactCenterX(),bounds.exactCenterY(),0)
        event.source=InputDevice.SOURCE_TOUCHSCREEN
        try {assertTrue(instrumentation.uiAutomation.injectInputEvent(event,true))} finally {event.recycle()}
        settle()
    }

    private fun clickMic() {
        val bounds=mic().first
        touch(MotionEvent.ACTION_DOWN,bounds)
        touch(MotionEvent.ACTION_UP,bounds)
    }

    private fun showPhase(phase: TripInlineVoicePhase) {
        instrumentation.runOnMainSync {state.value=state.value.copy(phase=phase)}
        settle()
    }

    private fun capture(name: String) {
        settle();val source=instrumentation.uiAutomation.takeScreenshot() ?: error("Missing screenshot")
        val bounds=Rect(frame);assertTrue(bounds.intersect(0,0,source.width,source.height))
        val cropped=Bitmap.createBitmap(source,bounds.left,bounds.top,bounds.width(),bounds.height())
        val directory=File(activity.filesDir,"trip-voice-click-native");check(directory.isDirectory || directory.mkdirs())
        File(directory,"$name.png").outputStream().use {check(cropped.compress(Bitmap.CompressFormat.PNG,100,it))}
        cropped.recycle();source.recycle()
    }

    /** Driving rows and grouped actions measure intrinsics; the control must answer them instead of crashing. */
    fun testControlSupportsIntrinsicMeasurement() {
        val measured=java.util.concurrent.CountDownLatch(1)
        instrumentation.runOnMainSync {activity.setContent {
            Column(Modifier.width(IntrinsicSize.Max)) {
                Row(Modifier.height(IntrinsicSize.Min).onGloballyPositioned {measured.countDown()}) {
                    TripInlineVoiceControl(TripInlineVoiceUi(TripInlineVoicePhase.LISTENING,microphone=false),{false},{},{},{},
                        Modifier.width(320.dp).fillMaxHeight(),onCancel={})
                }
            }
        }}
        instrumentation.waitForIdleSync()
        assertTrue("Intrinsic measurement must lay the control out",measured.await(5,java.util.concurrent.TimeUnit.SECONDS))
    }

    fun testClickRecordsAndOnlyExplicitSendTransmits() {
        render();capture("01-trip-listening")
        assertFalse(mic().second)
        clickMic();assertEquals(1,presses.get())
        showPhase(TripInlineVoicePhase.REQUESTING)
        assertEquals("Preparing a recording must not send",0,releases.get())
        showPhase(TripInlineVoicePhase.TRANSMITTING)
        capture("02-trip-recording");assertEquals(0,releases.get())
        clickMic();assertEquals(1,releases.get())
        assertEquals("Send must never start another recording",1,presses.get())
        assertEquals(0,cancels.get())
    }

    fun testCancelRestrictionAndRemovalDiscardRecordingWithoutSending() {
        render()
        clickMic();showPhase(TripInlineVoicePhase.REQUESTING)
        clickMic();assertEquals(1,cancels.get());assertEquals(0,releases.get())
        showPhase(TripInlineVoicePhase.LISTENING)
        clickMic();showPhase(TripInlineVoicePhase.TRANSMITTING)
        voiceAction("녹음 취소");assertEquals(2,cancels.get());assertEquals(0,releases.get())
        showPhase(TripInlineVoicePhase.LISTENING)
        clickMic();showPhase(TripInlineVoicePhase.TRANSMITTING)
        instrumentation.runOnMainSync {state.value=state.value.copy(permitted=false)};settle()
        assertEquals(3,cancels.get());assertTrue(mic().second);capture("03-trip-restricted")
        instrumentation.runOnMainSync {state.value=TripInlineVoiceUi(TripInlineVoicePhase.LISTENING)};settle()
        clickMic();showPhase(TripInlineVoicePhase.TRANSMITTING)
        instrumentation.runOnMainSync {present.value=false};settle()
        assertEquals("Leaving the trip discards the recording",4,cancels.get())
        assertEquals("Cancellation must never send",0,releases.get())
    }

    fun testNarrowAndNightStates() {
        render(width=800);capture("04-trip-narrow")
        assertTrue(mic().first.width()>0)
        render(width=1704,dark=true);capture("05-trip-night")
        instrumentation.runOnMainSync {state.value=state.value.copy(participating=false,phase=TripInlineVoicePhase.OFF)};settle()
        assertFalse(mic().second);capture("06-trip-off")
    }

    fun testOffClickOnlyConnectsAndRecordingNeedsAnotherClick() {
        state.value=state.value.copy(phase=TripInlineVoicePhase.OFF,participating=false)
        render();assertFalse(mic().second);capture("12-trip-off-ready")
        clickMic();assertEquals(listOf(true),participations);assertEquals(0,presses.get())
        for(next in listOf(TripInlineVoiceUi(TripInlineVoicePhase.LOADING,participating=false),
            TripInlineVoiceUi(TripInlineVoicePhase.LOADING),TripInlineVoiceUi(TripInlineVoicePhase.LISTENING))) {
            instrumentation.runOnMainSync {state.value=next};settle()
            assertEquals("Connecting never starts recording: ${next.phase}",0,presses.get())
            assertEquals(0,releases.get())
        }
        clickMic();assertEquals(1,presses.get())
        showPhase(TripInlineVoicePhase.TRANSMITTING);capture("13-trip-recording-after-connect")
        clickMic();assertEquals(1,releases.get())
    }

    fun testRejectedRecordingReturnsToReadyWithoutPendingSend() {
        acceptsRecording=false
        render();clickMic()
        assertEquals(1,presses.get());assertEquals(0,releases.get());assertEquals(0,cancels.get())
        assertTrue(voiceText().contains("녹음"));assertFalse(voiceText().contains("보내기"))
        acceptsRecording=true
        clickMic();assertEquals(2,presses.get())
        showPhase(TripInlineVoicePhase.TRANSMITTING)
        clickMic();assertEquals(1,releases.get())
    }

    fun testBusyFailureAndExternalOffDiscardRecording() {
        render()
        for((index,terminal) in listOf(TripInlineVoiceUi(TripInlineVoicePhase.HEARING),
            TripInlineVoiceUi(TripInlineVoicePhase.UNAVAILABLE),TripInlineVoiceUi(TripInlineVoicePhase.OFF,participating=false)).withIndex()) {
            instrumentation.runOnMainSync {state.value=TripInlineVoiceUi(TripInlineVoicePhase.LISTENING)};settle()
            clickMic();showPhase(TripInlineVoicePhase.TRANSMITTING)
            instrumentation.runOnMainSync {state.value=terminal};settle()
            assertEquals("${terminal.phase} discards the recording",index+1,cancels.get())
            showPhase(TripInlineVoicePhase.LISTENING)
            assertEquals("Returning to listening requires another click",index+1,presses.get())
            assertEquals("Terminal state must not send",0,releases.get())
        }
    }

    fun testInitialLoadingManualOnAndRetryNeverReserveRecording() {
        state.value=TripInlineVoiceUi(TripInlineVoicePhase.LOADING,participating=false)
        render();assertTrue(mic().second);clickMic();assertEquals(0,presses.get())
        instrumentation.runOnMainSync {state.value=TripInlineVoiceUi(TripInlineVoicePhase.LISTENING)};settle()
        assertEquals(0,presses.get())
        instrumentation.runOnMainSync {state.value=TripInlineVoiceUi(TripInlineVoicePhase.OFF,participating=false)};settle()
        voiceAction("워키토키");assertEquals(listOf(true),participations)
        instrumentation.runOnMainSync {state.value=TripInlineVoiceUi(TripInlineVoicePhase.LOADING)};settle()
        instrumentation.runOnMainSync {state.value=TripInlineVoiceUi(TripInlineVoicePhase.LISTENING)};settle()
        assertEquals(0,presses.get());assertEquals(0,releases.get())
        instrumentation.runOnMainSync {state.value=TripInlineVoiceUi(TripInlineVoicePhase.UNAVAILABLE)};settle()
        voiceAction("워키토키 다시 연결");assertEquals(1,retries.get())
        instrumentation.runOnMainSync {state.value=TripInlineVoiceUi(TripInlineVoicePhase.LOADING)};settle()
        instrumentation.runOnMainSync {state.value=TripInlineVoiceUi(TripInlineVoicePhase.LISTENING)};settle()
        assertEquals(0,presses.get());assertEquals(0,releases.get())
    }

    fun testPointerReleaseStartsRecordingButNeverSendsIt() {
        render();val bounds=mic().first
        touch(MotionEvent.ACTION_DOWN,bounds)
        assertEquals("A finger down is not an activation",0,presses.get())
        touch(MotionEvent.ACTION_UP,bounds)
        assertEquals(1,presses.get());assertEquals(0,releases.get())
        showPhase(TripInlineVoicePhase.RECORDED)
        assertEquals("The recording limit never sends automatically",0,releases.get())
        assertTrue(voiceText().contains("보내기"))
        voiceAction("녹음 취소")
        assertEquals(1,cancels.get());assertEquals(0,releases.get())
    }

    fun testAccessibleClickUsesTheSameRecordAndSendBoundary() {
        render()
        voiceAction("워키토키");assertEquals(1,presses.get());assertEquals(0,releases.get())
        showPhase(TripInlineVoicePhase.REQUESTING)
        assertEquals(0,releases.get())
        showPhase(TripInlineVoicePhase.RECORDED)
        voiceAction("워키토키")
        assertEquals(1,presses.get());assertEquals(1,releases.get());assertEquals(0,cancels.get())
    }

    fun testPermissionDialogFocusLossDoesNotClaimDrivingRestrictionAndCancelRestoresListening() {
        assertEquals(PackageManager.PERMISSION_DENIED,activity.checkSelfPermission(Manifest.permission.RECORD_AUDIO))
        render(permission=true,windowSafety=true)
        await("Parked, focused microphone available") {!mic().second}
        val bounds=mic().first
        touch(MotionEvent.ACTION_DOWN,bounds);touch(MotionEvent.ACTION_UP,bounds)
        await("Permission dialog owns focus") {!activity.window.decorView.hasWindowFocus() &&
            instrumentation.uiAutomation.windows.any {it.root?.packageName?.toString()=="com.android.permissioncontroller"}}
        settle()
        assertTrue("Permission request must disable microphone",mic().second)
        assertTrue("Permission focus loss must explain the permission request",voiceText().contains("마이크 확인"))
        assertFalse("Parked focus loss must not claim a driving restriction",voiceText().any {it.contains("정차")})
        assertEquals(0,presses.get())
        capture("08-trip-permission-focus")
        instrumentation.sendKeyDownUpSync(android.view.KeyEvent.KEYCODE_BACK)
        await("Trip focus restored") {activity.window.decorView.hasWindowFocus() && !mic().second}
        settle()
        assertTrue(voiceText().contains("녹음"))
        assertFalse(voiceText().any {it.contains("정차")})
        assertEquals("Cancelling permission must not transmit",0,presses.get())
        assertEquals(PackageManager.PERMISSION_DENIED,activity.checkSelfPermission(Manifest.permission.RECORD_AUDIO))
        capture("09-trip-permission-cancelled")
    }

    fun testParkedWindowFocusLossDiscardsRecordingAndRestoresListening() {
        render(windowSafety=true)
        await("Parked, focused microphone available") {!mic().second}
        clickMic()
        assertEquals(1,presses.get())
        showPhase(TripInlineVoicePhase.TRANSMITTING)
        lateinit var dialog: android.app.AlertDialog
        instrumentation.runOnMainSync {dialog=android.app.AlertDialog.Builder(activity).setMessage("다른 창을 확인하고 있어요").create();dialog.show()}
        await("Other window owns focus") {!activity.window.decorView.hasWindowFocus() && mic().second}
        settle()
        assertTrue(voiceText().contains("화면 확인"))
        assertFalse("A parked window change is not a driving restriction",voiceText().any {it.contains("정차")})
        assertTrue("Losing focus must discard the recording",cancels.get()>=1)
        assertEquals("Focus loss must not send",0,releases.get())
        instrumentation.runOnMainSync {state.value=state.value.copy(phase=TripInlineVoicePhase.LISTENING);dialog.dismiss()}
        await("Trip focus restored") {activity.window.decorView.hasWindowFocus() && !mic().second}
        settle()
        assertTrue(voiceText().contains("녹음"))
        assertEquals("Focus restoration must not restart transmission",1,presses.get())
        clickMic()
        assertEquals("Only a fresh click may start recording",2,presses.get())
        capture("10-trip-parked-focus-restored")
    }

    fun testDrivingAndUnknownVehicleStateRemainBlockedAheadOfStaleNotices() {
        state.value=state.value.copy(notice="마이크를 허용했어요. 다시 눌러 주세요")
            .withSafety(NativeVoiceAudioSafety(true,false),true)
        render(permission=true)
        assertTrue(mic().second)
        assertTrue(voiceText().contains("P단에서 이용"))
        assertFalse(voiceText().any {it.contains("마이크를 허용했어요")})
        touch(MotionEvent.ACTION_DOWN);touch(MotionEvent.ACTION_UP)
        assertEquals(0,presses.get())
        capture("11-trip-driving-blocked")
        instrumentation.runOnMainSync {state.value=state.value.withSafety(NativeVoiceAudioSafety(true,null),true)};settle()
        assertTrue(mic().second)
        assertTrue(voiceText().contains("차량 확인"))
        assertFalse(voiceText().any {it.contains("정차")})
        instrumentation.runOnMainSync {state.value=state.value.withSafety(NativeVoiceAudioSafety(true,true),false)};settle()
        assertTrue(mic().second)
        assertTrue(voiceText().contains("여행 확인"))
        assertFalse(voiceText().any {it.contains("정차")})
        assertEquals(0,presses.get())
    }

    fun testMicrophonePermissionRequiresAnotherClick() {
        assertEquals("Run this isolated test with microphone permission initially denied",PackageManager.PERMISSION_DENIED,
            activity.checkSelfPermission(Manifest.permission.RECORD_AUDIO))
        render(permission=true);val bounds=mic().first
        touch(MotionEvent.ACTION_DOWN,bounds);touch(MotionEvent.ACTION_UP,bounds)
        assertEquals(0,presses.get())
        var clicked=false
        await("Microphone permission dialog") {
            fun grant(node: android.view.accessibility.AccessibilityNodeInfo?): Boolean {
                if(node==null)return false
                if(node.viewIdResourceName?.endsWith("permission_allow_foreground_only_button")==true ||
                    node.viewIdResourceName?.endsWith("permission_allow_button")==true ||
                    node.text?.toString() in setOf("앱 사용 중에만 허용","Allow only while using the app","While using the app")) {
                    node.parent?.let {row->
                        for(index in 0 until row.childCount) {
                            val item=row.getChild(index)
                            if(item?.viewIdResourceName?.endsWith("car_ui_list_item_touch_interceptor")==true &&
                                item.isEnabled && item.performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_CLICK))return true
                        }
                    }
                    var target: android.view.accessibility.AccessibilityNodeInfo?=node
                    repeat(4) {
                        if(target?.isEnabled==true && target?.isClickable==true &&
                            target?.performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_CLICK)==true)return true
                        target=target?.parent
                    }
                }
                for(index in 0 until node.childCount)if(grant(node.getChild(index)))return true
                return false
            }
            clicked=instrumentation.uiAutomation.windows.any {grant(it.root)} || grant(instrumentation.uiAutomation.rootInActiveWindow);clicked
        }
        assertTrue(clicked)
        await("Microphone grant") {activity.checkSelfPermission(Manifest.permission.RECORD_AUDIO)==PackageManager.PERMISSION_GRANTED}
        settle();assertEquals("Granting permission must not record",0,presses.get())
        clickMic();assertEquals(1,presses.get());assertEquals(0,releases.get())
        showPhase(TripInlineVoicePhase.TRANSMITTING)
        clickMic();assertEquals(1,releases.get())
        capture("07-trip-permission-ready")
    }
}
