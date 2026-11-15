package io.wegoh.app

import android.accessibilityservice.AccessibilityServiceInfo
import android.content.Intent
import android.content.res.Configuration
import android.graphics.Bitmap
import android.graphics.Rect
import android.os.Bundle
import android.test.InstrumentationTestCase
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo
import android.view.inspector.WindowInspector
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.requiredSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.key
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.LocalSaveableStateRegistry
import androidx.compose.runtime.saveable.SaveableStateRegistry
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.layout.boundsInWindow
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.ViewRootForTest
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.ScrollAxisRange
import androidx.compose.ui.semantics.getAllSemanticsNodes
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import io.wegoh.app.nativeauth.*
import io.wegoh.app.ui.*
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.math.min
import kotlin.math.roundToInt

@Suppress("DEPRECATION")
class TripScreensPreviewTest: InstrumentationTestCase() {
    fun testPrivacyShowsDevicePermissionCardsAndOpensSettings() {
        for (previewWidth in listOf(1704, 800)) {
            var settingsRequests = 0
            render(previewWidth = previewWidth, scaffold = false) {
                WegoVehicleScreen(
                    WegoState(setupAllowed = true, storageReady = true,
                        accountProfile = AccountProfileState(AccountReadStatus.READY, "사용자A", vehicleUnavailable = true)),
                    onSelect = {}, onImport = {}, onStart = {}, onStop = {}, onNavigate = {}, onReset = {},
                    onBrowse = {}, onDownload = {}, onShareVisits = {}, onSystemSettings = { settingsRequests++ },
                )
            }
            click("프로필 탭")
            click("권한 관리")
            await("device permission guidance at ${previewWidth}dp") {
                matching("이 차량의 Android에서 허용된 앱 권한을 확인해요.").isNotEmpty()
            }
            for (permission in listOf("위치", "차량 위치", "마이크", "차량 속도")) {
                await("reachable permission card $permission at ${previewWidth}dp") {
                    if (matching(permission).isNotEmpty()) true else { scrollContent(); false }
                }
                assertTextHasNoOverflow(permission)
            }
            await("reachable device settings at ${previewWidth}dp") {
                if (matching("기기 설정").isNotEmpty() && frame.contains(button("기기 설정").bounds)) true
                else { scrollContent(); false }
            }
            tapButton("기기 설정", enabled = true)
            assertEquals("Device settings must invoke its action at ${previewWidth}dp", 1, settingsRequests)
        }
    }

    fun testTripNamesRefreshOnlyWhenEnteringTheListOrSelectingATrip() {
        val fixture=Fixture()
        var latestName="사용자A"
        var profileName by mutableStateOf("사용자A")
        var trips by mutableStateOf(fixture.page(fixture.driving(TripDrivingPhase.FAR)).copy(selectedId=null,detail=null))
        var entries=0
        var selections=0
        fun refreshedList()=trips.list!!.copy(invitations=listOf(TripInvitation("f".repeat(32),"여행 초대",latestName)))
        render(scaffold=false) {
            WegoVehicleScreen(WegoState(setupAllowed=true,storageReady=true,
                accountProfile=AccountProfileState(AccountReadStatus.READY,profileName,vehicleUnavailable=true)),
                onSelect={},onImport={},onStart={},onStop={},onNavigate={},onReset={},onBrowse={},onDownload={},onShareVisits={},
                tripsState=trips,onTripsRefresh={entries++;trips=trips.copy(list=refreshedList())},
                onTripSelect={selections++;trips=trips.copy(selectedId=it,detail=fixture.trip.copy(
                    members=fixture.trip.members.map {member->if(member.isMe)member.copy(name=latestName) else member}))},
                onTripClose={trips=trips.copy(selectedId=null,detail=null)})
        }
        await("initial travel entry") {entries==1}
        instrumentation.runOnMainSync {latestName="사용자B";profileName=latestName}
        instrumentation.waitForIdleSync()
        assertEquals("Profile recomposition must not reload travel",1,entries)
        assertTrue(nodes().any {it.text?.toString()?.startsWith("사용자A님이 초대")==true})
        click("프로필 탭")
        click("여행 탭")
        await("travel re-entry") {entries==2}
        assertTrue(nodes().any {it.text?.toString()?.startsWith("사용자B님이 초대")==true})
        capture("trip-name-entry-list",fixture.trip.title)
        click(fixture.trip.title)
        await("fresh trip selection") {selections==1 && trips.detail?.me?.name==latestName}
        assertEquals(2,entries)
        click("뒤로")
        await("back to refreshed list") {trips.selectedId==null && entries==3}
        instrumentation.waitForIdleSync()
        assertEquals("State updates must not trigger another entry",3,entries)
    }
    private lateinit var activity: TripScreensPreviewActivity
    private var previousFlags=0
    private var frame=Rect()
    private var scene=0
    @Volatile private var laidOutScene=0
    @Volatile private var drawnScene=0
    private var arrivalRequests=0
    private val actions=TripUiActions(arrive={arrivalRequests++})
    private var width=1704
    private var height=1208
    private val expected=listOf("01-home","02-plan-overview","03-plan-groups","04-plan-members","05-plan-route",
        "06-edit-intro","07-invite","08-car-create","09-car-manage","10-detail","11-detail-scroll","12-finish-dialog",
        "13-departure","14-driving-far","15-driving-near","16-driving-arrived","17-driving-route-end","18-driving-locked",
        "19-tab-car","20-tab-courses","21-tab-profile","22-departure-narrow","23-driving-long-name","24-trip-result","25-signal-request","26-signal-candidates","27-signal-vote","28-signal-majority","29-signal-no-place")

    override fun setUp() {
        super.setUp()
        val info=instrumentation.uiAutomation.serviceInfo
        previousFlags=info.flags
        info.flags=info.flags or AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
        instrumentation.uiAutomation.serviceInfo=info
        activity=instrumentation.startActivitySync(Intent(instrumentation.targetContext,TripScreensPreviewActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_MULTIPLE_TASK)) as TripScreensPreviewActivity
        instrumentation.runOnMainSync {
            WindowCompat.setDecorFitsSystemWindows(activity.window,false)
            WindowCompat.getInsetsController(activity.window,activity.window.decorView).hide(WindowInsetsCompat.Type.systemBars())
        }
        val directory=File(activity.filesDir,"trip-preview")
        assertTrue(directory.isDirectory || directory.mkdirs())
        ensureHostReady()
    }

    private fun ensureHostReady() {
        await("preview host layout") {
            var ready=false
            instrumentation.runOnMainSync {
                val view=activity.window.decorView
                ready=view.isShown && view.width>0 && view.height>0
            }
            ready
        }
        var previous=Rect()
        var stableSince=android.os.SystemClock.uptimeMillis()
        await("preview host focus and stable bounds") {
            val current=Rect()
            var ready=false
            instrumentation.runOnMainSync {
                val view=activity.window.decorView
                ready=activity.hasWindowFocus() && view.isShown && view.getGlobalVisibleRect(current)
            }
            if(!ready || current.isEmpty || current!=previous) {
                previous.set(current);stableSince=android.os.SystemClock.uptimeMillis();false
            } else android.os.SystemClock.uptimeMillis()-stableSince>=500
        }
    }

    override fun tearDown() {
        try {
            if(::activity.isInitialized)instrumentation.runOnMainSync {activity.setContent {};activity.finish()}
            val info=instrumentation.uiAutomation.serviceInfo
            info.flags=previousFlags;instrumentation.uiAutomation.serviceInfo=info
        } finally {super.tearDown()}
    }

    private fun render(previewWidth: Int=1704,scaffold: Boolean=true,previewHeight: Int=1208,content: @Composable ()->Unit) {
        width=previewWidth; height=previewHeight
        instrumentation.runOnMainSync {
            val version=++scene
            activity.setContent {key(version) {
                BoxWithConstraints(Modifier.fillMaxSize().background(Color.Black),contentAlignment=Alignment.Center) {
                    val scale=min(constraints.maxWidth.toFloat()/width,constraints.maxHeight.toFloat()/height)
                    val configuration=Configuration(LocalConfiguration.current).apply {
                        screenWidthDp=width;screenHeightDp=height;smallestScreenWidthDp=min(width,height)
                        orientation=if(width>=height)Configuration.ORIENTATION_LANDSCAPE else Configuration.ORIENTATION_PORTRAIT;fontScale=1f
                    }
                    CompositionLocalProvider(LocalDensity provides Density(scale,1f),LocalConfiguration provides configuration) {
                        Box(Modifier.requiredSize(width.dp,height.dp).drawWithContent {
                            drawContent();drawnScene=version
                        }.onGloballyPositioned {coordinates->
                            val bounds=coordinates.boundsInWindow()
                            val origin=IntArray(2);activity.window.decorView.getLocationOnScreen(origin)
                            frame=Rect(bounds.left.roundToInt()+origin[0],bounds.top.roundToInt()+origin[1],
                                bounds.right.roundToInt()+origin[0],bounds.bottom.roundToInt()+origin[1])
                            laidOutScene=version
                        }) {
                            WegoCarTheme(dark=false) {TripSurface {
                                if(scaffold)CarScreenScaffold("여행",{},items=PlatformRoutes.primary.map {
                                    CarPageItem(PlatformRoutes.titles.getValue(it),PlatformRoutes.symbol(it),it=="trips",{})
                                },primaryTabs=true,receiving=true) {content()}
                                else content()
                            }}
                        }
                    }
                }
            }}
        }
        settle()
        await("preview scene $scene drawn") {laidOutScene==scene && drawnScene==scene && frame.width()>0 && frame.height()>0}
    }

    private fun settle() {
        instrumentation.waitForIdleSync()
        val frames=CountDownLatch(1)
        instrumentation.runOnMainSync {
            activity.window.decorView.postOnAnimation {activity.window.decorView.postOnAnimation {frames.countDown()}}
        }
        assertTrue("Preview frame did not settle",frames.await(5,TimeUnit.SECONDS))
        instrumentation.waitForIdleSync()
    }

    private fun nodes(): List<AccessibilityNodeInfo> {
        if(android.os.Build.VERSION.SDK_INT>=34)instrumentation.uiAutomation.clearCache()
        val result=mutableListOf<AccessibilityNodeInfo>()
        fun walk(node: AccessibilityNodeInfo?) {
            if(node==null)return
            result.add(node);for(index in 0 until node.childCount)walk(node.getChild(index))
        }
        val roots=instrumentation.uiAutomation.windows
            .filter {it.type==AccessibilityWindowInfo.TYPE_APPLICATION}.mapNotNull {it.root}
            .filter {it.packageName?.toString()==instrumentation.targetContext.packageName}
        if(roots.isEmpty())walk(instrumentation.uiAutomation.rootInActiveWindow) else roots.forEach(::walk)
        return result
    }

    private fun matching(label: String)=nodes().filter {
        it.isVisibleToUser && (it.text?.toString()==label || it.contentDescription?.toString()==label)
    }

    private fun await(label: String,condition: ()->Boolean) {
        val end=android.os.SystemClock.elapsedRealtime()+7000
        while(android.os.SystemClock.elapsedRealtime()<end) {
            if(condition())return
            Thread.sleep(80)
        }
        fail("Trip preview missing: $label")
    }

    private fun click(label: String) {
        await(label) {
            for(candidate in matching(label)) {
                var node: AccessibilityNodeInfo?=candidate
                repeat(6) {
                    if(node?.isEnabled==true && node?.isClickable==true && node?.performAction(AccessibilityNodeInfo.ACTION_CLICK)==true)
                        return@await true
                    node=node?.parent
                }
            }
            false
        }
        settle()
    }

    private fun scrollContent() {
        nodes().firstOrNull {node->node.isVisibleToUser && node.isScrollable &&
            node.actionList.any {it.id==AccessibilityNodeInfo.AccessibilityAction.ACTION_SCROLL_DOWN.id}}
            ?.performAction(AccessibilityNodeInfo.ACTION_SCROLL_FORWARD)
    }

    private fun scrollLastContent() {
        nodes().lastOrNull {node->node.isVisibleToUser && node.isScrollable &&
            node.actionList.any {it.id==AccessibilityNodeInfo.AccessibilityAction.ACTION_SCROLL_DOWN.id}}
            ?.performAction(AccessibilityNodeInfo.ACTION_SCROLL_FORWARD)
    }

    private data class PreviewButton(val disabled: Boolean,val bounds: Rect,val selected: Boolean?,val owner: View,val rootBounds: Rect)

    private fun button(label: String,inDialog: Boolean=false): PreviewButton {
        var disabled: Boolean?=null
        var bounds: Rect?=null
        var selected: Boolean?=null
        var owner: View?=null
        var rootBounds: Rect?=null
        instrumentation.runOnMainSync {
            fun inspect(view: View) {
                if(view is ViewRootForTest) {
                    val button=view.semanticsOwner.getAllSemanticsNodes(mergingEnabled=false).singleOrNull {
                        it.config.contains(SemanticsActions.OnClick) &&
                            it.config.getOrNull(SemanticsProperties.ContentDescription)?.contains(label)==true &&
                            generateSequence(it.parent) {node->node.parent}.none {node->node.config.isClearingSemantics}
                    }
                    if(button!=null) {
                        disabled=button.config.contains(SemanticsProperties.Disabled)
                        selected=button.config.getOrNull(SemanticsProperties.Selected)
                        owner=view
                        val local=button.boundsInRoot
                        rootBounds=Rect(local.left.roundToInt(),local.top.roundToInt(),local.right.roundToInt(),local.bottom.roundToInt())
                        val rect=button.boundsInWindow
                        val origin=IntArray(2);view.rootView.getLocationOnScreen(origin)
                        bounds=Rect(rect.left.roundToInt()+origin[0],rect.top.roundToInt()+origin[1],
                            rect.right.roundToInt()+origin[0],rect.bottom.roundToInt()+origin[1])
                    }
                }
                if(view is ViewGroup)for(index in 0 until view.childCount)inspect(view.getChildAt(index))
            }
            if(inDialog)WindowInspector.getGlobalWindowViews().filter {it!==activity.window.decorView}.forEach(::inspect)
            else inspect(activity.window.decorView)
        }
        assertNotNull("Clickable Compose node missing: $label",disabled)
        return PreviewButton(checkNotNull(disabled),checkNotNull(bounds),selected,checkNotNull(owner),checkNotNull(rootBounds))
    }

    private fun assertTextWidth(label: String,minimumDp: Int=100) {
        var bounds: Rect?=null
        instrumentation.runOnMainSync {
            fun inspect(view: View) {
                if(view is ViewRootForTest)view.semanticsOwner.getAllSemanticsNodes(mergingEnabled=false).firstOrNull {
                    it.config.getOrNull(SemanticsProperties.Text)?.any {text->text.text==label}==true
                }?.let {node->
                    val rect=node.boundsInWindow
                    val origin=IntArray(2);view.rootView.getLocationOnScreen(origin)
                    bounds=Rect(rect.left.roundToInt()+origin[0],rect.top.roundToInt()+origin[1],rect.right.roundToInt()+origin[0],rect.bottom.roundToInt()+origin[1])
                }
                if(view is ViewGroup)for(index in 0 until view.childCount)inspect(view.getChildAt(index))
            }
            inspect(activity.window.decorView)
        }
        val text=checkNotNull(bounds) {"Text node missing: $label"}
        val scale=frame.width().toFloat()/width
        assertTrue("Text must retain readable width: $label",text.width()>=minimumDp*scale && text.height()>0)
        assertTrue("Text must be within the preview: $label",frame.contains(text))
    }

    private fun assertSelectedTab(title: String) {
        PlatformRoutes.primary.forEach {route->
            val label=PlatformRoutes.titles.getValue(route)
            assertEquals("Selected primary tab: $label",label==title,button("$label 탭").selected)
        }
    }

    private fun assertCarMenu() {
        val tabs=mutableListOf<Pair<String,Boolean>>()
        instrumentation.runOnMainSync {
            fun inspect(view: View) {
                if(view is ViewRootForTest)view.semanticsOwner.getAllSemanticsNodes(mergingEnabled=true).filter {
                    it.config.getOrNull(SemanticsProperties.Role)==Role.Tab &&
                        it.config.getOrNull(SemanticsProperties.ContentDescription).isNullOrEmpty()
                }.sortedBy {it.boundsInWindow.left}.forEach {node->
                    val label=node.config.getOrNull(SemanticsProperties.Text)?.singleOrNull()?.text
                    if(label!=null)tabs.add(label to (node.config.getOrNull(SemanticsProperties.Selected)==true))
                }
                if(view is ViewGroup)for(index in 0 until view.childCount)inspect(view.getChildAt(index))
            }
            inspect(activity.window.decorView)
        }
        assertTrue("Car overview uses the two-column layout",tabs.isEmpty())
        listOf("차량 연결","차량 요청","주의 기록").forEach {assertTrue("Removed menu: $it",matching(it).isEmpty())}
        assertTrue("Removed recommendation menu must not be visible",matching("추천").isEmpty())
    }

    private fun assertButtonFill(label: String,color: Int,inDialog: Boolean=false) {
        assertFill(label,button(label,inDialog).bounds,color)
    }

    private fun assertFill(label: String,target: Rect,color: Int) {
        val screen=screenshot()
        try {
            assertTrue("Button must be visible: $label",target.intersect(0,0,screen.width,screen.height))
            var matching=0
            var sampled=0
            for(y in target.top until target.bottom step 2)for(x in target.left until target.right step 2) {
                sampled++
                if(screen.getPixel(x,y)==color)matching++
            }
            assertTrue("Button fill differs from the approved design: $label ($matching/$sampled)",sampled>0 && matching.toDouble()/sampled>0.55)
        } finally {screen.recycle()}
    }

    private fun tapButton(label: String,enabled: Boolean) {
        val button=button(label)
        assertEquals("Clickable Compose node disabled state: $label",!enabled,button.disabled)
        val target=Rect()
        instrumentation.runOnMainSync {
            val origin=IntArray(2);button.owner.getLocationOnScreen(origin)
            target.set(button.rootBounds);target.offset(origin[0],origin[1])
            val root=button.owner.rootView
            root.getLocationOnScreen(origin)
            val window=Rect(origin[0],origin[1],origin[0]+root.width,origin[1]+root.height)
            assertTrue("Touch target must intersect the app window: $label",target.intersect(window) && !target.isEmpty)
        }
        val down=android.os.SystemClock.uptimeMillis()
        for((action,time) in listOf(MotionEvent.ACTION_DOWN to down,MotionEvent.ACTION_UP to down+50)) {
            val event=MotionEvent.obtain(down,time,action,target.exactCenterX(),target.exactCenterY(),0)
            try {instrumentation.sendPointerSync(event)} finally {event.recycle()}
        }
        settle()
    }

    private fun screenshot(): Bitmap {
        val deadline=android.os.SystemClock.elapsedRealtime()+5000
        var lastFailure: NullPointerException?=null
        while(android.os.SystemClock.elapsedRealtime()<deadline) {
            try {instrumentation.uiAutomation.takeScreenshot()?.let {return it}}
            catch(error: NullPointerException) {lastFailure=error}
            Thread.sleep(80)
        }
        throw AssertionError("Screenshot provider did not return an image within 5 seconds").apply {
            lastFailure?.let {initCause(it)}
        }
    }

    private fun capture(name: String,visible: String,dimmed: Boolean=false,background: Color?=null) {
        await(visible) {matching(visible).isNotEmpty()}
        settle()
        val bounds=Rect()
        instrumentation.runOnMainSync {bounds.set(frame)}
        if(background!=null)await("painted preview: $name") {
            val screen=screenshot()
            try {screen.getPixel(bounds.left+4,bounds.top+4)==background.toArgb()}
            finally {screen.recycle()}
        }
        if(!dimmed)await("undimmed preview: $name") {
            val screen=screenshot()
            try {screen.getPixel(bounds.centerX(),bounds.top+4)==android.graphics.Color.WHITE}
            finally {screen.recycle()}
        }
        val screen=screenshot()
        try {
            assertTrue("1704x1208dp frame must be on screen",bounds.width()>0 && bounds.height()>0 &&
                bounds.left>=0 && bounds.top>=0 && bounds.right<=screen.width && bounds.bottom<=screen.height)
            val cropped=Bitmap.createBitmap(screen,bounds.left,bounds.top,bounds.width(),bounds.height())
            val normalized=Bitmap.createScaledBitmap(cropped,width,height,true)
            try {
                File(activity.filesDir,"trip-preview/$name.png").outputStream().use {
                    assertTrue(normalized.compress(Bitmap.CompressFormat.PNG,100,it))
                }
            } finally {
                if(normalized!==cropped)normalized.recycle()
                if(cropped!==screen)cropped.recycle()
            }
        } finally {screen.recycle()}
    }

    fun testCarReceiverShowsTripScopeAndSafety() {
        for(previewWidth in listOf(1704,800)) {
            render(previewWidth=previewWidth,scaffold=false) {
                WegoVehicleScreen(WegoState(setupAllowed=true,storageReady=true),{},{},{},{},{},{},{},{},{},
                    remoteReceiving=true,remoteHistory={VehicleRemoteHistoryList(emptyList())})
            }
            click("리모컨 탭")
            assertSelectedTab("리모컨")
            val scope="iPhone 앱의 여행 → 동승자 리모컨에서 허용 기능을 바꿔요"
            await("Trip receiver scope") {matching(scope).isNotEmpty()}
            assertTrue(matching("리모컨 받기").isNotEmpty())
            assertTrue(matching("조절할 수 있는 사람").isEmpty())
            capture("trip-remote-receiver-$previewWidth",scope)
            await("Seat controls remain limited to a parked vehicle") {
                if(matching("시트 열선·통풍과 실내등은 정차 중에만 사용할 수 있어요").isNotEmpty())true else {scrollContent();false}
            }
        }
    }

    fun testTripDetailShowsScoresWithoutMissionNavigationAndClosesMusicWhenDriving() {
        val fixture=Fixture()
        var state by mutableStateOf(fixture.page(fixture.driving(TripDrivingPhase.FAR)))
        var legacyRooms=0
        var musicTrip: String?=null
        render {VehicleTripDetailPage(state,{},{},TripUiActions(),true,AccountCourseState(),{},{legacyRooms++},
            music={trip,allowed,back->
                musicTrip=trip.id
                TripHeading(if(allowed)"현재 여행의 음악" else "음악 이용 제한",onBack=back)
            }) {}}
        await("inline safety scores") {if(matching("안전운전 점수").isNotEmpty())true else {scrollContent();false}}
        assertTrue(matching("함께 미션").isEmpty())
        assertTrue(matching("여행방").isEmpty())
        await("direct trip music entry") {if(matching("여행 음악").isNotEmpty())true else {scrollContent();false}}
        click("여행 음악")
        await("music directly from trip detail") {matching("현재 여행의 음악").isNotEmpty()}
        assertEquals(fixture.trip.id,musicTrip)
        click("뒤로")
        await("direct music returns to trip detail") {matching("우리 경로").isNotEmpty()}
        assertEquals(0,legacyRooms)
        assertTrue(matching("함께 미션").isEmpty())
        assertTrue(matching("여행방").isEmpty())
        instrumentation.runOnMainSync {state=state.copy(gear=TripGear.DRIVE)}
        await("driving view") {matching("주행 중").isNotEmpty()}
        assertTrue(matching("여행방").isEmpty())
        assertTrue(matching("여행 음악").isEmpty())
        instrumentation.runOnMainSync {state=state.copy(gear=TripGear.PARK)}
        await("parked trip detail") {matching("우리 경로").isNotEmpty()}
        await("scores return when parked") {if(matching("안전운전 점수").isNotEmpty())true else {scrollContent();false}}
    }

    fun testPlannedTripHasNoTripEditingOrHistoryEntry() {
        val fixture=Fixture()
        val planned=fixture.trip.copy(state="planned")
        val state=fixture.page(TripDrivingState()).copy(detail=planned)
        render {VehicleTripDetailPage(state,{},{},TripUiActions(),true,AccountCourseState(),{},{}) {}}
        await("trip preparation") {matching(planned.title).isNotEmpty()}
        assertTrue(matching("고치기").isEmpty())
        assertTrue(matching("여행 고치기").isEmpty())
        assertTrue(matching("여행 기록").isEmpty())
    }

    fun testAcceptedMemberCoursePickerWithoutEditPermission() {
        val fixture=Fixture()
        val trip=fixture.trip.copy(state="planned",members=fixture.trip.members.mapIndexed {index,person->person.copy(isMe=index==1)})
        assertFalse(trip.isOwner)
        assertFalse(trip.canEdit)
        var loads=0
        var route by mutableStateOf(false)
        val courses=AccountCourseState(AccountCourseStatus.READY,listOf(AccountCourse(
            PublishedPack("taean-coast",1,"태안 해안도로","사용자C","만리포 → 꽃지해수욕장",2,""),true)))
        render {
            if(route)TripPreparationRoutePage(trip,true,{},TripUiActions(),courses,{loads++},TripGear.PARK,{})
            else TripPlanPage(trip,true,{},TripUiActions(),{},{},{},{},courses,{},onRoute={route=true})
        }
        click("경로 준비 보기")
        await("permanent own-course panel") {matching("내 경로에서 추가").isNotEmpty()}
        assertFalse(button("태안 해안도로 여행에 추가").disabled)
        assertEquals(1,loads)
        capture("member-course-picker","내 경로에서 추가")
    }

    fun testRetiredDrivingDataMenuIsAbsent() {
        render {VehicleCarPage(false,"",{},{},{_,_->},remoteHistory={VehicleRemoteHistoryList(emptyList())})}
        await("Remote page") {matching("리모컨 받기").isNotEmpty()}
        assertCarMenu()
        assertTrue(matching("주행 데이터").isEmpty())
        capture("retired-driving-menu","리모컨 받기")
    }

    fun testCourseDrivingResultsShowScoreCountsAndUnavailableInsteadOfInventedPerfectScore() {
        val fixture=Fixture()
        val original=fixture.trip
        val course=original.courses!!.first()
        val trip=original.copy(courses=original.courses!!.map {if(it.packId==course.packId)it.copy(completedCarIds=listOf(original.myCar!!.id)) else it})
        val result=CourseDrivingResult(1,1,60_000,completed=true)
        val state=fixture.page(fixture.driving(TripDrivingPhase.ROUTE_COMPLETE,true).complete(course.packId))
            .copy(detail=trip,courseResults=mapOf(course.packId to result))
        render(previewWidth=800) {TripActivePage(trip,state,true,TripUiActions(),{},{},{})}
        click("1. ${course.title}")
        await("course result") {if(matching("90점").isNotEmpty())true else {scrollContent();false}}
        assertTextHasNoOverflow("90점")
        assertTrue(matching("급가속 1회").isNotEmpty());assertTrue(matching("급감속 1회").isNotEmpty())
        capture("course-driving-result","90점")
        render(previewWidth=800) {TripSurface {CourseDrivingResultCard(CourseDrivingResult(completed=true))}}
        capture("course-driving-unavailable","측정 불가")
        assertTrue(matching("100점").isEmpty())
    }

    fun testPreparationFormFactorsPreserveActionsAndRestrictions() {
        val people=listOf("사용자A","사용자C","사용자D","사용자B","사용자E").mapIndexed {index,name->
            TripMember(index.toString(),name,true,index==0,index==0,hasVehicle=index in listOf(0,3))
        }
        val cars=listOf(
            TripCar("car-1","1호차 · 사용자A의 차","0","사용자A",4,true,false,listOf(TripPassenger("1","사용자C",false),TripPassenger("2","사용자D",false))),
            TripCar("car-2","2호차 · 사용자B의 차","3","사용자B",4,false,false,listOf(TripPassenger("4","사용자E",false))))
        val trip=TripDetail("a".repeat(32),"서해안 드라이브","함께 떠나는 서해안 여행",people,cars,state="planned",revision=1,
            courses=listOf(TripCourse("previous","간월호 한 바퀴"),TripCourse("current","서해안 해안도로 코스"),TripCourse("future","보령 해안도로")))
        var starts=0
        val actions=TripUiActions(perform={action,_->if(action is TripAction.Start)starts++})
        val presets=listOf(1700 to 1184,840 to 1184,1360 to 948,672 to 948,1274 to 855,628 to 855,
            1640 to 810,800 to 810,1640 to 1400,800 to 1400,1256 to 800,648 to 800)
        for((w,h) in presets) {
            var groupsOpened=0
            render(previewWidth=w,previewHeight=h) {TripPlanPage(trip,true,{},actions,{},{},{},{},AccountCourseState(),{},gear=TripGear.PARK,onGroups={groupsOpened++})}
            assertTrue("Start stays inside ${w}x$h",frame.contains(button("여행 시작").bounds))
            assertTrue(nodes().any {it.text?.toString()=="여행 준비"})
            assertTrue(matching("한눈에 보기").isEmpty())
            capture("preparation-${w}x$h",trip.title)
            await("preparation cars at ${w}x$h") {if(matching("차와 일행").isNotEmpty())true else {scrollLastContent();false}}
            tapButton("차와 일행",enabled=true)
            assertEquals("Groups action routes to the detail screen",1,groupsOpened)
            await("preparation courses at ${w}x$h") {if(matching("+ 경로 추가").isNotEmpty())true else {scrollLastContent();false}}
            assertFalse(button("+ 경로 추가").disabled)
        }
        render(previewWidth=800) {TripPlanPage(trip,false,{},actions,{},{},{},{},AccountCourseState(),{},gear=TripGear.PARK)}
        tapButton("여행 시작",enabled=false)
        assertEquals("Disabled start must not issue action",0,starts)
        val passenger=trip.copy(members=trip.members.mapIndexed {index,person->person.copy(isMe=index==2)})
        render(previewWidth=800) {TripPlanPage(passenger,true,{},actions,{},{},{},{},AccountCourseState(),{},gear=TripGear.PARK)}
        assertTrue("Only owner can start",matching("여행 시작").isEmpty())
    }

    fun testTravelListFormFactorsKeepRealActionsAndPhoneHintReachable() {
        val active=TripSummary("a".repeat(32),"서해안 드라이브",true,"사용자A",5,2,state="active")
        val invite=TripInvitation("b".repeat(32),"보령 해안도로","사용자B",memberCount=5,carCount=2)
        val state=TripsPageState(AccountReadStatus.READY,list=TripList(listOf(active),listOf(invite)),isCurrent=true,gear=TripGear.PARK)
        val presets=listOf(1700 to 1184,840 to 1184,1360 to 948,672 to 948,1274 to 855,628 to 855,
            1640 to 810,800 to 810,1640 to 1400,800 to 1400,1256 to 800,648 to 800)
        var selected=0
        for((w,h) in presets) {
            render(previewWidth=w,previewHeight=h) {VehicleTripListPage(state,{}, {selected++},{_,_,_->},{},{})}
            val open=button(active.title)
            assertTrue("Travel open action inside ${w}x$h",frame.contains(open.bounds))
            assertTrue("80dp travel action at ${w}x$h",open.bounds.height()*w.toFloat()/frame.width()>=79)
            tapButton(active.title,enabled=true)
            await("reachable invitation at ${w}x$h") {
                if(matching("참여").isNotEmpty())true else {scrollContent();false}
            }
            assertEquals("Equal invitation buttons at ${w}x$h",button("참여").bounds.width().toFloat(),button("거절").bounds.width().toFloat(),1f)
            assertTextHasNoOverflow(invite.title)
            capture("travel-list-${w}x$h","참여")
            val hint="iPhone 앱의 여행에서 새 여행을 만들어요"
            await("phone hint at ${w}x$h") {if(matching(hint).isNotEmpty())true else {scrollContent();false}}
            assertFalse(matching(hint).any {it.isClickable})
        }
        assertEquals(presets.size,selected)
    }

    fun testInvitationJoinsWithoutSeparateLocationChoice() {
        val fixture=Fixture()
        val invite=fixture.list.invitations.single()
        val responses=mutableListOf<Pair<Boolean,Boolean?>>()
        val state=fixture.page(TripDrivingState()).copy(selectedId=null,detail=null,list=TripList(emptyList(),listOf(invite)))
        render {VehicleTripListPage(state,{},{},{id,accept,share->
            assertEquals(invite.tripId,id);responses.add(accept to share)
        },{},{})}
        click("참여")
        assertEquals(listOf(true to true),responses)
        assertTrue(matching("내 위치를 공유할까요?").isEmpty())
        assertTrue(matching("공유 없이 참여").isEmpty())
        click("거절")
        assertEquals(listOf(true to true,false to null),responses)
    }

    fun testTripDetailHasNoSeparateLocationSharingControl() {
        val fixture=Fixture()
        var page by mutableStateOf(fixture.page(fixture.driving(TripDrivingPhase.FAR)))
        render {VehicleTripDetailPage(page,{},{},TripUiActions(),true,AccountCourseState(),{},{}) {}}
        assertTrue(matching("내 위치 공유").isEmpty())
        assertTrue(matching("위치 공유 켜기").isEmpty())
        assertTrue(matching("위치 공유 끄기").isEmpty())
        instrumentation.runOnMainSync {page=page.copy(detail=page.detail!!.copy(locationSharing=true,revision=2))};settle()
        assertTrue(matching("여행 불러오는 중").isEmpty())
        assertTrue(matching("내 위치 공유").isEmpty())
    }

    fun testProfileNavigationShowsOwnNameAndPlateAndReturnsFromPrivacy() {
        var profileCurrent by mutableStateOf(true)
        render(scaffold=false) {
            val profile=AccountProfileState(AccountReadStatus.READY,"사용자A",isCurrent=profileCurrent,
                vehicle=VehicleProfile("12가3456","","나의 차",1))
            WegoVehicleScreen(WegoState(setupAllowed=true,storageReady=true,accountProfile=profile),
                onSelect={},onImport={},onStart={},onStop={},onNavigate={},onReset={},onBrowse={},onDownload={},onShareVisits={})
        }
        click("프로필 탭")
        await("vehicle name and number on profile overview") {matching("나의 차").isNotEmpty() && matching("12가3456").isNotEmpty()}
        instrumentation.runOnMainSync {profileCurrent=false}
        settle()
        assertTrue(matching("나의 차").isEmpty());assertTrue(matching("12가3456").isEmpty())

        click("친구 관리")
        await("friends list") {matching("나와 친구").isNotEmpty()}
        assertTrue(matching("권한 관리").isEmpty())
        click("뒤로")
        await("profile from friends") {matching("연결 확인 필요").isNotEmpty()}

        click("권한 관리")
        await("privacy permissions") {matching("기기 설정").isNotEmpty()}
        click("뒤로")
        await("profile from privacy") {matching("연결 확인 필요").isNotEmpty()}
    }

    fun testCaptureAllTripScreens() {
        expected.forEach {File(activity.filesDir,"trip-preview/$it.png").delete()}
        val fixture=Fixture()
        val planned=fixture.trip.copy(state="planned")
        val parked=fixture.page(fixture.driving(TripDrivingPhase.FAR).copy(distanceMeters=98000.0))
        render {VehicleTripListPage(parked.copy(detail=null,selectedId=null,list=fixture.list),{},{},{_,_,_->},{},{})}
        capture("01-home","받은 초대")
        assertSelectedTab("여행")
        assertEquals(112f,button("여행 탭").bounds.height()*width.toFloat()/frame.width(),2f)

        render {TripPlanPage(planned,true,{},actions,{},{},{},{},AccountCourseState(),{})}
        capture("02-plan-overview",planned.title)
        assertTrue(nodes().any {it.text?.toString()=="여행 준비"})
        assertTrue(matching("한눈에 보기").isEmpty())
        render {TripGroupsPage(planned,true,{},actions,{},{},TripGear.PARK,{})}
        capture("03-plan-groups","차 ${planned.cars.size}대")
        render {TripInvitePage(planned,parked.copy(detail=planned,inviteFriends=fixture.friends),true,actions,{},TripGear.PARK,{})}
        capture("04-plan-members","일행 ${planned.members.size}명")
        render {TripPreparationRoutePage(planned,true,{},actions,AccountCourseState(),{},TripGear.PARK,{})}
        capture("05-plan-route","내 경로에서 추가")

        render {TripEditIntroPage(planned,true,actions,{})}
        capture("06-edit-intro","여행 소개 고치기")
        assertButtonFill("저장",0xFF1F5FD6.toInt())
        assertButtonFill("취소",0xFFFFFFFF.toInt())
        render {TripInvitePage(planned,parked.copy(detail=planned,inviteFriends=fixture.friends,
            inviteLink=TripInviteLink("a".repeat(43),"2026-11-21T12:00:00Z")),true,actions,{},TripGear.PARK)}
        capture("07-invite","친구 초대")
        val newDriver=planned.copy(members=planned.members.map {it.copy(isMe=it.name=="사용자B",hasVehicle=it.hasVehicle==true || it.name=="사용자B")},
            cars=planned.cars.map {it.copy(isMine=false,iRide=false)})
        render {TripCarCreatePage(newDriver,null,true,actions,{},TripGear.PARK)}
        capture("08-car-create","여행에 차 추가")
        render {TripCarManagePage(planned,true,actions,{},{},{},true,TripGear.PARK)}
        capture("09-car-manage","동승자 ${planned.myCar!!.passengers.size}명")

        render {TripActivePage(fixture.trip,parked,true,actions,{},{},{})}
        capture("10-detail","우리 경로")
        await("detail lower sections") {
            if(matching("함께 가는 차").isNotEmpty())true
            else {scrollContent();false}
        }
        capture("11-detail-scroll","함께 가는 차")
        click("여행 완료")
        capture("12-finish-dialog","여행을 완료할까요?",dimmed=true)
        assertButtonFill("여행 완료",CarTokens.Ink.toArgb(),inDialog=true)
        click("취소")
        await("finish dialog dismissed") {matching("여행을 완료할까요?").isEmpty()}

        render {TripDeparturePage(fixture.trip,parked,true,actions,{},{})}
        capture("13-departure","저장")
        val far=fixture.driving(TripDrivingPhase.FAR).copy(distanceMeters=98000.0)
        render {TripDrivingPage(fixture.trip,fixture.page(far,TripGear.DRIVE),true,actions)}
        capture("14-driving-far","간월암")
        val near=far.copy(phase=TripDrivingPhase.NEAR,distanceMeters=250.0,enteredNear=true)
        render {TripDrivingPage(fixture.trip,fixture.page(near,TripGear.DRIVE),true,actions)}
        capture("15-driving-near","도착했어요")
        assertButtonFill("도착했어요",0xFF1F5FD6.toInt())
        tapButton("도착했어요",enabled=true)
        assertEquals(1,arrivalRequests)
        val arrived=near.arrive(false)
        render {TripDrivingPage(fixture.trip,fixture.page(arrived,TripGear.DRIVE),true,actions)}
        capture("16-driving-arrived","나중에")
        val end=fixture.driving(TripDrivingPhase.ROUTE_END,last=true)
        render {TripDrivingPage(fixture.trip,fixture.page(end,TripGear.DRIVE),true,actions)}
        capture("17-driving-route-end","경로 완료")
        render {TripDrivingPage(fixture.trip,fixture.page(near,TripGear.DRIVE).copy(isCurrent=false),false,actions)}
        capture("18-driving-locked","정차하면 누를 수 있어요")
        assertButtonFill("도착했어요",0xFFE0E1E6.toInt())
        tapButton("도착했어요",enabled=false)
        assertEquals("Locked touch must not request arrival",1,arrivalRequests)

        var shellAllowed by mutableStateOf(true)
        var shellReady by mutableStateOf(true)
        var refreshRequests=0
        val friends=listOf(SocialPerson("friend-1","사용자E"),SocialPerson("friend-2","사용자C"),SocialPerson("friend-3","사용자D"))
        val social=SocialPageState(AccountReadStatus.READY,
            SocialOverview(emptyList(),friends,emptyList(),emptyList(),emptyList(),true,true,true,false),isCurrent=true)
        render(scaffold=false) {
            var trips by remember {mutableStateOf(parked.copy(detail=null,selectedId=null))}
            WegoVehicleScreen(WegoState(setupAllowed=shellAllowed,storageReady=shellReady,
                accountProfile=AccountProfileState(AccountReadStatus.READY,"사용자A",vehicleUnavailable=true),
                accountCourses=AccountCourseState(AccountCourseStatus.READY,courses=listOf(
                    AccountCourse(PublishedPack("west-coast",1,"서해안 해안도로 코스","사용자A","간월암 → 꽃지해수욕장 → 대천해수욕장",3,""),true),
                    AccountCourse(PublishedPack("ganwol-lake",1,"간월호 한 바퀴","사용자A","간월호 → 간월암",2,""),true),
                    AccountCourse(PublishedPack("boryeong",1,"보령 해안도로","사용자B","대천항 → 무창포해수욕장",2,""),true)))),
                onSelect={},onImport={},onStart={},onStop={},onNavigate={},onReset={},onBrowse={},onDownload={},onShareVisits={},
                tripsState=trips,onTripSelect={trips=parked},onTripClose={trips=trips.copy(detail=null,selectedId=null)},
                tripActions=actions,socialState=social,onTripsRefresh={refreshRequests++},onSocialRefresh={refreshRequests++},
                onAccountRefresh={refreshRequests++},remoteReceiving=true,remoteMessage="여행 중 허용한 동승자의 조작을 기다리고 있습니다",
                remoteHistory={VehicleRemoteHistoryList(emptyList())})
        }
        refreshRequests=0
        click("리모컨 탭");capture("19-tab-car","리모컨 받기")
        assertCarMenu()
        assertSelectedTab("리모컨")
        tapButton("새로고침",enabled=true)
        assertEquals("Remote refresh does not reload social data",0,refreshRequests)
        click("경로 탭");capture("20-tab-courses","내 경로")
        assertSelectedTab("경로")
        click("프로필 탭");capture("21-tab-profile","로그인됨")
        assertSelectedTab("프로필")
        assertTrue("Profile overview already shows identity; no separate 내 정보 step",matching("내 정보").isEmpty())
        click("친구 관리");await("profile list") {matching("나와 친구").isNotEmpty()}
        click("사용자C");await("friend profile") {matching("친구 연결 해제").isNotEmpty()}
        assertTrue(matching("휴대전화에서 함께 보기").isEmpty())
        assertTrue(matching("내 차 리모컨").isEmpty())
        click("뒤로");await("profile list") {matching("나와 친구").isNotEmpty()}
        click("뒤로");await("profile overview from friends") {matching("로그인됨").isNotEmpty()}
        click("권한 관리");await("privacy") {matching("방문 기록").isNotEmpty()}
        click("뒤로");await("profile overview") {matching("로그인됨").isNotEmpty()}
        click("음악 탭");await("music tab entry") {matching("내 플레이리스트").isNotEmpty() || matching("음악 고르기").isNotEmpty()}
        assertSelectedTab("음악")
        assertTrue("Music root has no back button",matching("뒤로").isEmpty())
        click("프로필 탭");await("profile from music") {matching("로그인됨").isNotEmpty()}
        click("여행 탭");click("서해안 드라이브")
        await("trip detail") {matching("우리 경로").isNotEmpty()}
        assertTrue(matching("함께 미션").isEmpty())
        assertTrue(matching("여행방").isEmpty())
        instrumentation.runOnMainSync {shellReady=false};settle()
        val refreshesBeforeDisabledTouches=refreshRequests
        tapButton("리모컨 탭",enabled=false)
        tapButton("새로고침",enabled=false)
        assertEquals(refreshesBeforeDisabledTouches,refreshRequests)
        instrumentation.runOnMainSync {shellAllowed=false};settle()
        assertTrue("CarUx restriction hides primary navigation",matching("여행 탭").isEmpty())

        val longName="서해안 바다와 숲을 함께 둘러보는 아주 긴 이름의 다음 장소 ".repeat(4).take(80)
        assertEquals(80,longName.length)
        val narrowTrip=fixture.trip.copy(cars=fixture.trip.cars.map {car->
            if(!car.isMine)car else car.copy(places=car.places.orEmpty().mapIndexed {index,place->if(index==0)place.copy(name=longName) else place})
        })
        render(previewWidth=900) {TripDeparturePage(narrowTrip,parked.copy(detail=narrowTrip),true,actions,{},{})}
        capture("22-departure-narrow","저장")
        assertTextWidth(longName)
        val longNext=fixture.trip.copy(courses=fixture.trip.courses.orEmpty().map {course->
            if(course.packId!="west-coast")course else course.copy(stops=course.stops.orEmpty().mapIndexed {stopIndex,stop->if(stopIndex==1)stop.copy(name=longName) else stop})
        })
        render(previewWidth=900) {TripDrivingPage(longNext,fixture.page(arrived,TripGear.DRIVE).copy(detail=longNext),true,actions)}
        await("long destination in the driving view") {
            val destination=button("${longName} 길 안내").bounds
            if(frame.contains(destination))true else {scrollContent();false}
        }
        capture("23-driving-long-name","나중에")
        assertTextWidth("간월암에 도착했어요")
        assertTextWidth("다음 장소는 $longName")
        assertTextWidth("${longName} 길 안내")
        assertTrue("Long destination button remains visible",frame.contains(button("${longName} 길 안내").bounds))
        val finished=fixture.trip.copy(state="completed")
        render {VehicleTripDetailPage(parked.copy(detail=finished),{},{},actions,true,AccountCourseState(),{},{}) {
            CarText("기존 여행 기록")
        }}
        capture("24-trip-result","주행 기록")
        assertTrue("Unavailable score panel is hidden",matching("안전운전 대결").isEmpty())
        assertTrue("Real visit fixture is displayed",matching("간월암").isNotEmpty())
        listOf("달린 거리","운전 시간","들른 곳","13 km","10분").forEach {assertTrue("Result statistic is displayed: $it",matching(it).isNotEmpty())}
        assertTrue(matching("여행 기록").isEmpty())
        assertTrue(matching("기존 여행 기록").isEmpty())
        await("result phone hint") {if(matching("점수는 일행에게만 공개돼요. 속도와 위치 원본은 보내지 않아요.").isNotEmpty())true else {scrollLastContent();false}}
        assertTrue(matching("휴대전화로 이어 하기").isEmpty())
        val signalCandidate=SignalCandidate("서산휴게소 (목포 방향)",36.742991,126.565029,"ahead","모든 차 앞쪽",6000.0,180.0,setOf("toilet"))
        val signalOffRoute=SignalCandidate("홍성휴게소",36.552584,126.579514,"off_route","경로 벗어남",11000.0,720.0)
        val signal=TripSignal(idForSignal(),fixture.trip.cars[1].driverId,TripSignalKind.RESTROOM,signalCandidate.destination,
            "2026-11-09T10:00:00Z","valid",0,0,null)
        render(scaffold=false) {TripSignalRequestPage(fixture.trip,
            TripSignalState(checked=true,hint="먼저 왼쪽에서 하나 골라 주세요"),next=null,actions=actions) {}}
        capture("25-signal-request","가까운 안전한 곳에 세워 주세요")
        render(scaffold=false) {TripSignalRequestPage(fixture.trip,
            TripSignalState(checked=true,candidates=listOf(signalCandidate,signalOffRoute)),next=null,actions=actions) {}}
        capture("26-signal-candidates",signalCandidate.name)
        assertTrue(matching(signalOffRoute.name).isEmpty())
        assertTrue(matching("경로 벗어남").isEmpty())
        render(scaffold=false) {TripSignalOverlay(fixture.trip,signal,TripSignalState(overlay=signal),actions)}
        capture("27-signal-vote","동의 1/2",dimmed=true)
        val majority=signal.copy(agrees=1,myVote="agree")
        render(scaffold=false) {TripSignalOverlay(fixture.trip,majority,TripSignalState(overlay=majority,
            result="과반이 동의했어요 · 서산휴게소 (목포 방향)이 경유지로 들어갔어요"),actions)}
        capture("28-signal-majority","과반 동의",dimmed=true)
        val noPlace=signal.copy(destination=null)
        render(scaffold=false) {TripSignalOverlay(fixture.trip,noPlace,TripSignalState(overlay=noPlace),actions)}
        capture("29-signal-no-place","확인",dimmed=true)
        expected.forEach {assertTrue("Missing PNG: $it",File(activity.filesDir,"trip-preview/$it.png").length()>0)}
    }

    fun testSingleOngoingSignalShowsProgressAndRequesterControls() {
        val fixture=Fixture()
        val signal=TripSignal(idForSignal(),checkNotNull(fixture.trip.me).id,TripSignalKind.REST,null,
            "2026-11-09T10:00:00Z","valid",0,0,null)
        val finished=mutableListOf<String>()
        val current=TripUiActions(finishSignal={finished.add(it)})
        render(scaffold=false) {TripSignalRequestPage(fixture.trip,
            TripSignalState(checked=true,hasActiveSignal=true,ongoing=signal),next=null,actions=current) {}}
        assertTrue(matching("1 · 무엇이 필요하세요?").isEmpty())
        assertTrue(matching("진행 중인 요청").isNotEmpty())
        capture("single-signal-in-progress","완료",dimmed=true)
        click("완료")
        assertEquals(listOf("completed"),finished)
        render(scaffold=false) {TripSignalRequestPage(fixture.trip,
            TripSignalState(checked=true,hasActiveSignal=true),next=null,actions=current) {}}
        assertTrue(matching("이 여행에서 손들기가 진행 중이에요").isNotEmpty())
        assertTrue(matching("완료").isEmpty())
    }

    fun testTripComponentsInsideIntrinsicMeasurement() {
        val fixture=Fixture()
        val drive=fixture.driving(TripDrivingPhase.FAR)
        val car=checkNotNull(fixture.trip.myCar)
        val stops=TripRouteOrder.resolve(TripRouteOrder.initial(fixture.trip,car),fixture.trip,car)
        for(previewWidth in listOf(1704,800)) {
            render(previewWidth=previewWidth,scaffold=false) {
                Column(Modifier.width(IntrinsicSize.Max).height(IntrinsicSize.Min)) {
                    TripHeading("Intrinsic 제목",badge="진행 중") {CarButton("기록",{})}
                    TripListRow("Intrinsic 경로",listOf("사용자D 추가 · 장소 3곳"),selected=true,trailing={CarStatusPill("주행 중",true)})
                    CarRouteStrip(stops,drive)
                }
            }
            await("intrinsic components at $previewWidth") {
                matching("Intrinsic 경로").isNotEmpty() && matching("우리 경로").isNotEmpty()
            }
            val arrived=fixture.driving(TripDrivingPhase.NEAR).arrive(false)
            render(previewWidth=previewWidth,scaffold=false) {
                Box(Modifier.width(IntrinsicSize.Max).height(1000.dp)) {
                    TripDrivingPage(fixture.trip,fixture.page(arrived,TripGear.DRIVE),true,actions)
                }
            }
            await("intrinsic driving prompt at $previewWidth") {matching("나중에").isNotEmpty()}
        }
    }

    fun testCaptureNarrowScreens() {
        val fixture=Fixture()
        val longTitle="저장 이동 확인을 위한 아주 긴 서해안 드라이브 경로"
        val trip=fixture.trip.copy(courses=fixture.trip.courses.orEmpty().map {course->
            if(course.packId=="west-coast")course.copy(title=longTitle,addedByName="사용자D") else course
        })
        val parked=fixture.page(fixture.driving(TripDrivingPhase.FAR)).copy(detail=trip)
        val planned=trip.copy(state="planned")
        val courses=AccountCourseState(AccountCourseStatus.READY,courses=trip.courses.orEmpty().map {
            AccountCourse(PublishedPack(it.packId,1,it.title,it.addedByName.orEmpty(),
                it.stops.orEmpty().joinToString(" → ") {stop->stop.name},it.stopCount ?: 0,""),true)
        })
        val profile=AccountProfileState(AccountReadStatus.READY,"사용자A",vehicleUnavailable=true)
        val captured=mutableListOf<String>()
        fun shot(name: String,label: String,dimmed: Boolean=false) {
            val file="$name-narrow"
            capture(file,label,dimmed);captured.add(file)
        }
        fun reveal(label: String) {
            await("narrow content: $label") {if(matching(label).isNotEmpty())true else {scrollContent();false}}
        }
        render(previewWidth=800) {VehicleTripListPage(parked.copy(detail=null,selectedId=null,list=fixture.list),{},{},{_,_,_->},{},{})}
        shot("30-home","내 여행")
        listOf("여행","리모컨","경로","음악","프로필").forEach {assertTrue("Visible narrow tab: $it",frame.contains(button("$it 탭").bounds))}
        reveal("받은 초대");shot("31-invitations","받은 초대")
        render(previewWidth=800) {TripPlanPage(planned,true,{},actions,{},{},{},{},courses,{})}
        shot("32-plan",planned.title)
        reveal("전체 경로");shot("33-plan-route","전체 경로")
        var signals=0
        render(previewWidth=800) {TripActivePage(trip,parked,true,actions,{},{},{},{signals++})}
        shot("34-detail","우리 경로")
        reveal("2. $longTitle");shot("35-detail-route","2. $longTitle")
        assertTrue("Ellipsis preserves the full user title in semantics",matching("2. $longTitle").isNotEmpty())
        reveal("함께 가는 차");shot("36-detail-cards","함께 가는 차")
        reveal("손들기")
        val handBounds=button("손들기").bounds
        assertTrue("Hand raise remains reachable in the narrow app window",frame.contains(handBounds))
        assertTrue("Hand raise keeps its minimum touch height",handBounds.height()*width.toFloat()/frame.width()>=CarTokens.Touch.value)
        tapButton("손들기",enabled=true);assertEquals(1,signals)
        render(previewWidth=800) {VehicleCarPage(true,"",{},{},{_,_->},remoteHistory={VehicleRemoteHistoryList(emptyList())})}
        shot("37-car","리모컨 받기")
        reveal("최근 기록");shot("38-car-history","최근 기록")
        render(previewWidth=800) {VehicleCoursesPage(WegoState(setupAllowed=true,storageReady=true,accountCourses=courses),{},{},{},{},{},{},{})}
        shot("39-courses","내 경로");assertTrue("Ellipsis preserves the full user title in semantics",matching(longTitle).isNotEmpty())
        render(previewWidth=800) {VehicleProfileOverview(profile,8,3,12,{},{},{})}
        shot("40-profile","로그인됨")
        reveal("이 차에서 로그아웃");shot("41-profile-account-actions","이 차에서 로그아웃")
        render(previewWidth=800) {TripResultPage(trip.copy(state="completed"),{}) {CarText("실제 여행 기록")}}
        shot("42-result","주행 기록")
        reveal("여행 안전운전 결과");shot("43-result-score","여행 안전운전 결과")
        assertTrue(matching("경로로 만들어 공유하기").isEmpty())
        render(previewWidth=800) {TripDeparturePage(trip,parked,true,actions,{},{})}
        shot("44-departure","내 차 경로")
        render(previewWidth=800) {TripEditIntroPage(planned,true,actions,{})}
        shot("45-edit","여행 이름")
        render(previewWidth=800) {TripInvitePage(planned,parked.copy(inviteFriends=fixture.friends),true,actions,{},TripGear.PARK)}
        shot("46-invite","친구 초대")
        render(previewWidth=800) {TripCarManagePage(planned,true,actions,{},{},{},true,TripGear.PARK)}
        shot("47-car-manage","동승자 ${planned.myCar!!.passengers.size}명")
        render(previewWidth=800) {TripCarCreatePage(planned,null,true,actions,{},TripGear.PARK)}
        shot("48-car-create","차 이름")
        render(previewWidth=800) {TripDrivingPage(trip,parked.copy(gear=TripGear.DRIVE),false,actions)}
        shot("49-driving","주행 중")
        assertTrue("Driving view has no hand-raise composer",matching("손들기").isEmpty())
        val candidate=SignalCandidate("서산휴게소 (목포 방향)",36.742991,126.565029,"ahead","모든 차 앞쪽",6000.0,180.0,setOf("toilet"))
        val signalState=TripSignalState(checked=true,candidates=listOf(candidate))
        render(previewWidth=800,scaffold=false) {TripSignalRequestPage(trip,signalState,next=null,actions=actions) {}}
        shot("50-signal-request","1 · 무엇이 필요하세요?")
        reveal("서산휴게소 (목포 방향)");shot("51-signal-candidates","서산휴게소 (목포 방향)")
        val signal=TripSignal(idForSignal(),trip.cars[1].driverId,TripSignalKind.RESTROOM,candidate.destination,
            "2026-11-09T10:00:00Z","valid",0,0,null)
        render(previewWidth=800,scaffold=false) {TripSignalOverlay(trip,signal,TripSignalState(overlay=signal),actions)}
        shot("52-signal-vote","손들기",dimmed=true)
        captured.forEach {assertTrue("Missing narrow PNG: $it",File(activity.filesDir,"trip-preview/$it.png").length()>0)}
    }

    private fun assertTextHasNoOverflow(label: String) {
        var found=false
        val overflow=mutableListOf<String>()
        instrumentation.runOnMainSync {
            fun inspect(view: View) {
                if(view is ViewRootForTest)view.semanticsOwner.getAllSemanticsNodes(mergingEnabled=false).filter {
                    it.config.getOrNull(SemanticsProperties.Text)?.any {text->text.text==label}==true &&
                        generateSequence(it.parent) {node->node.parent}.none {node->node.config.isClearingSemantics}
                }.forEach {node->
                    val layouts=mutableListOf<androidx.compose.ui.text.TextLayoutResult>()
                    node.config.getOrNull(SemanticsActions.GetTextLayoutResult)?.action?.invoke(layouts)
                    layouts.forEach {
                        found=true
                        val lines=(0 until it.lineCount).map {line->
                            val left=it.getLineLeft(line);val top=it.getLineTop(line)
                            val right=it.getLineRight(line);val bottom=it.getLineBottom(line)
                            val ellipsized=it.isLineEllipsized(line)
                            val clipped=!left.isFinite() || !top.isFinite() || !right.isFinite() || !bottom.isFinite() ||
                                left < -1f || top < -1f || right > it.size.width+1f || bottom > it.size.height+1f
                            Triple(ellipsized,clipped,"$line:[$left,$top,$right,$bottom], ellipsis=$ellipsized")
                        }
                        val end=if(it.lineCount>0)it.getLineEnd(it.lineCount-1,visibleEnd=false) else 0
                        if(it.multiParagraph.didExceedMaxLines || lines.any {line->line.first || line.second} || end!=it.layoutInput.text.length)
                            overflow.add("size=${it.size}, paragraph=${it.multiParagraph.width}x${it.multiParagraph.height}, intrinsic=${it.multiParagraph.intrinsics.maxIntrinsicWidth}, lines=${it.lineCount}, maxLines=${it.layoutInput.maxLines}, exceeded=${it.multiParagraph.didExceedMaxLines}, end=$end/${it.layoutInput.text.length}, bounds=${lines.map {line->line.third}}")
                    }
                }
                if(view is ViewGroup)for(index in 0 until view.childCount)inspect(view.getChildAt(index))
            }
            inspect(activity.window.decorView)
        }
        assertTrue("Text layout missing: $label",found)
        assertTrue("Text is ellipsized or clipped: $label (${overflow.joinToString()})",overflow.isEmpty())
    }

    fun testTripRootOverlayForwardsSuppliedVoteAction() {
        val fixture=Fixture()
        val signal=TripSignal(idForSignal(),fixture.trip.cars[1].driverId,TripSignalKind.REST,
            SignalDestination("휴게소",36.742991,126.565029),"2026-11-09T10:00:00Z","valid",0,0,null)
        val votes=mutableListOf<String>()
        render(scaffold=false) {
            WegoVehicleScreen(WegoState(setupAllowed=true,storageReady=true),
                onSelect={},onImport={},onStart={},onStop={},onNavigate={},onReset={},onBrowse={},onDownload={},onShareVisits={},
                tripsState=fixture.page(fixture.driving(TripDrivingPhase.FAR)).copy(signals=TripSignalState(overlay=signal)),
                tripActions=TripUiActions(voteSignal={votes.add(it)}),remoteReceiving=null,remoteMessage="",remoteHistory={})
        }
        tapButton("동의",enabled=true)
        assertEquals(listOf("agree"),votes)
    }

    fun testTripSignalControlsWaitForParkAndCarUxPermission()=assertTripSignalControls(actualPolicy=false)

    fun testTripSignalControlsWithRealEmulatorCarUx() {
        val runner=instrumentation as android.test.InstrumentationTestRunner
        if(runner.arguments.getString("actualCarUx")=="1")assertTripSignalControls(actualPolicy=true)
    }

    private fun assertTripSignalControls(actualPolicy: Boolean) {
        val fixture=Fixture()
        val requester=fixture.trip.cars[1]
        val signal=TripSignal(idForSignal(),requester.driverId,TripSignalKind.RESTROOM,
            SignalDestination("서산휴게소",36.742991,126.565029),"2026-11-09T10:00:00Z","valid",0,0,null,
            inProgress=true,decisionRule="other-car-groups-v1",requesterCarId=requester.id,canRespond=true)
        var state by mutableStateOf(fixture.page(fixture.driving(TripDrivingPhase.FAR),
            if(actualPolicy)TripGear.UNKNOWN else TripGear.PARK).copy(
            signals=TripSignalState(checked=true)))
        var setupAllowed by mutableStateOf(!actualPolicy)
        val votes=mutableListOf<String>()
        render(scaffold=false) {
            val actions=TripUiActions(voteSignal={votes.add(it)})
            Box {
                VehicleTripDetailPage(state,{},{},actions,setupAllowed,AccountCourseState(),{},{}) {}
                TripSignalsHost(state,actions,setupAllowed)
            }
        }
        var policy: DrivingPolicy?=null
        var gear: TripGearObserver?=null
        fun marker(value: String)=instrumentation.sendStatus(0,Bundle().apply {putString("stream","\n$value\n")})
        try {
            if(actualPolicy)instrumentation.runOnMainSync {
                policy=DrivingPolicy(activity) {allowed,_,_->setupAllowed=allowed}
                gear=TripGearObserver(activity) {updated->state=state.copy(gear=updated)}
            }
            await("parked signal action") {matching("손들기").isNotEmpty()}
            tapButton("손들기",enabled=true)
            await("parked signal composer") {matching("1 · 무엇이 필요하세요?").isNotEmpty()}
            if(actualPolicy)marker("UX_READY_PARKED") else instrumentation.runOnMainSync {
                setupAllowed=false;state=state.copy(gear=TripGear.DRIVE)
            }
            await("driving gear and blocked CarUx") {state.gear==TripGear.DRIVE && !setupAllowed}
            instrumentation.runOnMainSync {state=state.copy(signals=state.signals.copy(overlay=signal,overlayTrip=fixture.trip))}
            await("composer closes as the driving page opens") {
                matching("1 · 무엇이 필요하세요?").isEmpty() && matching(fixture.trip.title).isNotEmpty()
            }
            assertTrue(matching("손들기").isEmpty())
            assertTrue(matching("동의").isEmpty())
            assertTrue(matching(signal.destination!!.name).isEmpty())
            capture("hand-raise-drive-restricted",fixture.trip.title,dimmed=true)
            if(actualPolicy)marker("UX_READY_RESTRICTED") else {
                instrumentation.runOnMainSync {state=state.copy(gear=TripGear.PARK)}
                settle()
                assertTrue(matching("동의").isEmpty())
                instrumentation.runOnMainSync {setupAllowed=true}
            }
            await("parked group response") {matching(signal.destination!!.name).isNotEmpty()}
            capture("hand-raise-parked","서산휴게소",dimmed=true)
            tapButton("동의",enabled=true)
            assertEquals(listOf("agree"),votes)
        } finally {
            instrumentation.runOnMainSync {gear?.close();policy?.close()}
        }
    }

    fun testSignalReasonsAndFacilityFiltersKeepOnlyAheadChoices() {
        fun fullyVisible(label: String,clickable: Boolean): Boolean {
            val visible=nodes().any {node->
                val bounds=Rect();node.getBoundsInScreen(bounds)
                node.isVisibleToUser && (node.text?.toString()==label || node.contentDescription?.toString()==label) &&
                    !bounds.isEmpty && frame.contains(bounds)
            }
            if(!visible || !clickable)return visible
            val target=runCatching {button(label)}.getOrNull() ?: return false
            return !target.disabled && frame.contains(target.bounds) &&
                target.bounds.height()>=CarTokens.Touch.value*frame.width()/width.toFloat()-2
        }
        fun reveal(label: String,clickable: Boolean=false) {
            repeat(24) {
                if(fullyVisible(label,clickable))return
                var range: ScrollAxisRange?=null
                var before=0f
                var accepted=false
                instrumentation.runOnMainSync {
                    fun inspect(view: View) {
                        if(view is ViewRootForTest && range==null) {
                            val target=view.semanticsOwner.getAllSemanticsNodes(mergingEnabled=false).firstOrNull {node->
                                node.config.getOrNull(SemanticsProperties.Text)?.any {it.text==label}==true ||
                                    node.config.getOrNull(SemanticsProperties.ContentDescription)?.contains(label)==true
                            }
                            generateSequence(target) {it.parent}.firstOrNull {node->
                                node.config.getOrNull(SemanticsProperties.VerticalScrollAxisRange)!=null &&
                                    node.config.getOrNull(SemanticsActions.ScrollBy)?.action!=null
                            }?.let {node->
                                val axis=checkNotNull(node.config.getOrNull(SemanticsProperties.VerticalScrollAxisRange))
                                range=axis;before=axis.value()
                                val remaining=axis.maxValue()-before
                                if(remaining>0)accepted=node.config.getOrNull(SemanticsActions.ScrollBy)?.action
                                    ?.invoke(0f,minOf(node.boundsInWindow.height/3f,remaining))==true
                            }
                        }
                        if(view is ViewGroup)for(index in 0 until view.childCount)inspect(view.getChildAt(index))
                    }
                    inspect(activity.window.decorView)
                }
                assertNotNull("Signal target has a scroll container: $label",range)
                assertTrue("Signal target scroll action is accepted before the end: $label",accepted)
                instrumentation.uiAutomation.waitForIdle(100,1500)
                settle()
                var after=before
                var stableSince=android.os.SystemClock.uptimeMillis()
                await("signal content settles after scrolling to $label") {
                    var value=before
                    instrumentation.runOnMainSync {value=checkNotNull(range).value()}
                    if(value!=after) {after=value;stableSince=android.os.SystemClock.uptimeMillis()}
                    after>before && android.os.SystemClock.uptimeMillis()-stableSince>=200
                }
            }
            assertTrue("Signal target is fully visible after scrolling: $label",fullyVisible(label,clickable))
        }
        val fixture=Fixture()
        val ahead=SignalCandidate("서산휴게소",36.72,126.55,"ahead","모든 차 앞쪽",6000.0,180.0,
            setOf("gasStation","toilet"),fromLeadMeters=4000.0,leaderCarId=fixture.trip.cars.first().id)
        val hidden=ahead.copy(name="경로 밖 후보",verdict="off_route",label="경로 벗어남")
        for(width in listOf(1704,800)) {
            var signalState by mutableStateOf(TripSignalState(checked=true,candidates=listOf(ahead,hidden)))
            val sent=mutableListOf<SignalDestination?>()
            val controls=TripUiActions(loadSignalCandidates={kind->signalState=signalState.copy(kind=kind,requiredFacilities=kind.defaultFacilities)},
                filterSignalFacilities={required->signalState=signalState.copy(requiredFacilities=required)},sendSignal={sent.add(it)})
            render(previewWidth=width,scaffold=false) {TripSignalRequestPage(fixture.trip,signalState,null,controls) {}}
            await("nine reason grid") {
                val labels=nodes().filter {it.isVisibleToUser}.flatMap {listOfNotNull(it.text?.toString(),it.contentDescription?.toString())}.toSet()
                TripSignalKind.entries.all {it.label in labels}
            }
            tapButton("주유",enabled=true)
            assertEquals(TripSignalKind.FUEL,signalState.kind)
            assertEquals(setOf(TripSignalFacility.GAS_STATION),signalState.requiredFacilities)
            reveal("LPG",clickable=true)
            tapButton("LPG",enabled=true)
            reveal("수유실",clickable=true)
            tapButton("수유실",enabled=true)
            assertEquals(setOf(TripSignalFacility.GAS_STATION,TripSignalFacility.LPG,TripSignalFacility.NURSING),signalState.requiredFacilities)
            reveal("LPG",clickable=true)
            tapButton("LPG",enabled=true)
            assertEquals(setOf(TripSignalFacility.GAS_STATION,TripSignalFacility.NURSING),signalState.requiredFacilities)
            reveal(ahead.name)
            assertTrue(matching(hidden.name).isEmpty())
            assertTrue(matching("경로 벗어남").isEmpty())
            capture("signal-filters-$width",ahead.name)
        }
    }

    fun testGroupResponseFillsAppAndSupportsBothRepliesAndRetry() {
        fun revealUpperContent(anchor: String,label: String) {
            if(matching(label).isNotEmpty())return
            val scroller=matching(anchor).asSequence().flatMap {candidate->generateSequence(candidate) {it.parent}}
                .firstOrNull {it.isScrollable && it.actionList.any {action->action.id==AccessibilityNodeInfo.ACTION_SCROLL_FORWARD}}
            assertNotNull("Upper response content scroll container: $anchor",scroller)
            repeat(24) {
                if(matching(label).isNotEmpty())return
                val target=checkNotNull(scroller)
                assertTrue("Upper response content still attached",target.refresh())
                assertTrue("Upper response content scrolls",target.performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_SCROLL_DOWN.id))
                instrumentation.uiAutomation.waitForIdle(100,1500)
                settle()
            }
            fail("Upper response content remains unreachable: $label")
        }
        val fixture=Fixture()
        val requester=fixture.trip.cars[1]
        val mine=checkNotNull(fixture.trip.myCar)
        val signal=TripSignal(idForSignal(),requester.driverId,TripSignalKind.REST,
            SignalDestination("서산휴게소",36.742991,126.565029),"2026-11-09T10:00:00Z","valid",0,0,null,
            resolution="pending",decisionRule="other-car-groups-v1",requesterCarId=requester.id,
            canRespond=true,groupVotes=TripGroupVotes(0,1,2),groupResponses=listOf(
                TripGroupResponse(mine.id,mine.name,null),TripGroupResponse("d".repeat(32),"사용자B의 차","pass")))
        val replies=mutableListOf<String>()
        val current=TripUiActions(voteSignal={replies.add(it)})
        fun root(signals: TripSignalState) {
            render(scaffold=false) {
                WegoVehicleScreen(WegoState(setupAllowed=true,storageReady=true),
                    onSelect={},onImport={},onStart={},onStop={},onNavigate={},onReset={},onBrowse={},onDownload={},onShareVisits={},
                    tripsState=fixture.page(fixture.driving(TripDrivingPhase.FAR)).copy(detail=null,selectedId=null,signals=signals),
                    tripActions=current,remoteReceiving=null,remoteMessage="",remoteHistory={})
            }
        }
        val state=TripSignalState(overlay=signal,overlayTrip=fixture.trip)
        root(state)
        val responseHeader=signal.kind.headline
        capture("group-response-header",responseHeader,dimmed=true,background=CarTokens.Background)
        revealUpperContent(responseHeader,"내 차 응답 대기")
        capture("group-response-regular","내 차 응답 대기",dimmed=true,background=CarTokens.Background)
        val headers=listOf(signal.kind.headline,requester.numberedName,"서산휴게소",
            "전원 동의 시 다음 목적지 앞에 추가해요")
        headers.forEach(::assertTextHasNoOverflow)
        for(label in listOf("동의","다음에")) {
            val bounds=button(label).bounds
            assertTrue("Reply region fills the app width: $label",bounds.width()>frame.width()*0.4f)
            assertTrue("Reply region fills the app height: $label",bounds.height()>frame.height()*0.2f)
            assertTextWidth(label,minimumDp=40)
            assertTextHasNoOverflow(label)
        }
        tapButton("동의",enabled=true)
        assertEquals(listOf("agree"),replies)
        root(state.copy(voting=true))
        revealUpperContent(responseHeader,"답을 보내고 있어요")
        capture("group-response-sending","답을 보내고 있어요",dimmed=true,background=CarTokens.Background)
        tapButton("다음에",enabled=false)
        assertEquals(listOf("agree"),replies)
        render(previewWidth=800,scaffold=false) {
            TripSignalOverlay(fixture.trip,signal,state.copy(result="답을 보내지 못했어요. 다시 눌러 주세요"),current)
        }
        revealUpperContent(responseHeader,"답을 보내지 못했어요. 다시 눌러 주세요")
        capture("group-response-retry-narrow","답을 보내지 못했어요. 다시 눌러 주세요",dimmed=true,background=CarTokens.Background)
        headers.forEach(::assertTextHasNoOverflow)
        assertTextHasNoOverflow("답을 보내지 못했어요. 다시 눌러 주세요")
        assertTextWidth("동의",minimumDp=40);assertTextWidth("다음에",minimumDp=40)
        assertTextHasNoOverflow("동의");assertTextHasNoOverflow("다음에")
        tapButton("다음에",enabled=true)
        assertEquals(listOf("agree","pass"),replies)
        val cancelled=mutableListOf<String>()
        val own=signal.copy(accountId=checkNotNull(fixture.trip.me).id,requesterCarId=mine.id,canRespond=false)
        render(previewWidth=800,scaffold=false) {
            TripSignalRequestPage(fixture.trip,TripSignalState(checked=true,hasActiveSignal=true,ongoing=own),
                next=null,actions=TripUiActions(finishSignal={cancelled.add(it)})) {}
        }
        capture("group-response-requester-cancel","손들기 취소")
        tapButton("손들기 취소",enabled=true)
        assertEquals(listOf("cancelled"),cancelled)
        render(previewWidth=800,scaffold=false) {
            TripGroupSignalStatusPage(fixture.trip,signal.copy(inProgress=false,resolution="passed",canRespond=false),state,current,{})
        }
        capture("group-response-result-narrow","차량별 응답")
        val longTrip=fixture.trip.copy(title="늦가을 바닷길을 따라 함께 떠나는 서해안 여행".repeat(3).take(80),
            cars=fixture.trip.cars.map {if(it.id==requester.id)it.copy(name="가족과 친구가 함께 타는 아주 긴 이름의 차") else it})
        val longSignal=signal.copy(destination=signal.destination!!.copy(name="목포 방향의 가족과 함께 쉬어 가는 서산 휴게소".repeat(3).take(80)),groupVotes=TripGroupVotes(0,1,19),
            groupResponses=List(19) {TripGroupResponse(it.toString(),"${it+1}번째 가족과 함께 여행하는 이름이 긴 차",if(it==18)"pass" else null)})
        render(previewWidth=800,scaffold=false) {TripSignalOverlay(longTrip,longSignal,state,current)}
        capture("group-response-long-header-narrow",signal.kind.headline,dimmed=true,background=CarTokens.Background)
        assertTextHasNoOverflow(signal.kind.headline)
        assertTrue("Ellipsis preserves the full destination in semantics",matching(longSignal.destination!!.name).isNotEmpty())
        revealUpperContent(signal.kind.headline,"내 차 응답 대기")
        capture("group-response-long-groups-narrow","내 차 응답 대기",dimmed=true,background=CarTokens.Background)
        assertTextHasNoOverflow("내 차 응답 대기")
        assertFalse(button("동의").disabled);assertFalse(button("다음에").disabled)
    }

    fun testNewSignalNeedsExplicitNavigationAndOldRouteDraftCannotSave() {
        val fixture=Fixture()
        val car=checkNotNull(fixture.trip.myCar)
        val original=TripRouteOrder.initial(fixture.trip,car)
        val signalItem=TripRouteItem("signal",idForSignal())
        val signalPlace=TripPlace("서산휴게소",idForSignal(),"signal",36.742991,126.565029)
        val oldTrip=fixture.trip.copy(cars=fixture.trip.cars.map {if(it.id==car.id)it.copy(routeOrder=original,routeRevision=1) else it})
        val newTrip=oldTrip.copy(cars=oldTrip.cars.map {if(it.id==car.id)it.copy(
            places=it.places.orEmpty()+signalPlace,routeOrder=listOf(signalItem)+original,routeRevision=2,routeNextKnown=true,routeNext=signalItem) else it})
        val navigations=mutableListOf<TripRouteStop>()
        val current=TripUiActions(navigate={navigations.add(it)})
        render(previewWidth=800,scaffold=false) {
            TripDrivingPage(newTrip,fixture.page(fixture.driving(TripDrivingPhase.FAR)).copy(detail=newTrip),true,current)
        }
        capture("group-route-explicit-navigation","새 경유지가 추가됐어요")
        assertTrue(navigations.isEmpty())
        tapButton("서산휴게소 길 안내",enabled=true)
        assertEquals(listOf(signalItem.key),navigations.map {it.item.key})
        var editing by mutableStateOf(oldTrip)
        val saves=mutableListOf<Pair<Long,List<TripRouteItem>>>()
        val editor=TripUiActions(saveOrder={items,revision,_->saves.add(revision to items)})
        render(previewWidth=800,scaffold=false) {
            TripDeparturePage(editing,fixture.page(fixture.driving(TripDrivingPhase.LATER)).copy(detail=editing),true,editor,{},{})
        }
        instrumentation.runOnMainSync {editing=newTrip}
        capture("group-route-draft-conflict","경로가 바뀌었어요. 새 경로를 불러와 주세요")
        tapButton("저장",enabled=false)
        assertTrue(saves.isEmpty())
        tapButton("새 경로 불러오기",enabled=true)
        capture("group-route-draft-reloaded","서산휴게소")
        tapButton("저장",enabled=true)
        assertEquals(2L,saves.single().first)
        assertEquals(signalItem,saves.single().second.first())
    }

    fun testRemovedCarSelectionRestoresOverview() {
        val registry=object: SaveableStateRegistry by SaveableStateRegistry(null,{true}) {
            var restored=false
            override fun consumeRestored(key: String): Any? {
                if(restored)return null
                restored=true
                return mutableStateOf("RECOMMENDATIONS")
            }
        }
        render {
            CompositionLocalProvider(LocalSaveableStateRegistry provides registry) {
                VehicleCarPage(false,"여행 중 허용한 동승자의 조작을 기다리고 있습니다",{},{},
                    extra={section,_->assertEquals(CarSection.COMMANDS,section)},remoteHistory={})
            }
        }
        await("restored car overview") {matching("리모컨 받기").isNotEmpty()}
        assertFalse("Retired subsection state is no longer restored",registry.restored)
        assertCarMenu()
    }

    fun testTripHistoryScreenBack() {assertTripHistoryBack(systemBack=false)}

    fun testTripHistorySystemBack() {assertTripHistoryBack(systemBack=true)}

    private fun assertTripHistoryBack(systemBack: Boolean) {
        val fixture=Fixture()
        val parked=fixture.page(fixture.driving(TripDrivingPhase.FAR))
        var closedTrips=0
        var rootBacks=0
        render(scaffold=false) {
            var trips by remember {mutableStateOf(parked.copy(detail=null,selectedId=null))}
            WegoVehicleScreen(WegoState(setupAllowed=true,storageReady=true),
                onSelect={},onImport={},onStart={},onStop={},onNavigate={},onReset={},onBrowse={},onDownload={},onShareVisits={},
                onRootBack={rootBacks++},tripsState=trips,onTripSelect={trips=parked},
                onTripClose={closedTrips++;trips=trips.copy(detail=null,selectedId=null)},tripActions=actions,
                remoteReceiving=null,remoteMessage="",remoteHistory={},tripExtras={section->
                    check(section==TripSection.HISTORY)
                    var selected by remember {mutableStateOf(false)}
                    CarChildBackHandler(enabled=selected) {selected=false}
                    CarScreenScaffold("여행 기록",{selected=false},embedded=true) {
                        if(selected)CarText("사용자A의 여행 기록 상세")
                        else CarListRow("사용자A의 여행 기록",onClick={selected=true})
                    }
                })
        }
        fun goBack() {
            if(systemBack) {instrumentation.sendKeyDownUpSync(KeyEvent.KEYCODE_BACK);settle()}
            else tapButton("뒤로",enabled=true)
        }
        repeat(2) {iteration->
            click("서해안 드라이브")
            await("active trip") {matching("우리 경로").isNotEmpty()}
            click("여행 기록")
            click("사용자A의 여행 기록")
            await("selected history record") {matching("사용자A의 여행 기록 상세").isNotEmpty()}
            goBack()
            await("history detail to history list") {
                matching("사용자A의 여행 기록").isNotEmpty() && matching("사용자A의 여행 기록 상세").isEmpty()
            }
            assertEquals("History detail must not close the trip",iteration,closedTrips)
            goBack()
            await("history list to active trip") {matching("우리 경로").isNotEmpty()}
            assertEquals("History list must not close the trip",iteration,closedTrips)
            goBack()
            await("active trip to trip list") {matching("받은 초대").isNotEmpty()}
            assertEquals(iteration+1,closedTrips)
            assertEquals("Nested back must not leave the trips root",0,rootBacks)
        }
    }

    private fun idForSignal()="f".repeat(32)

    private class Fixture {
        private fun id(number: Int)=number.toString(16).padStart(32,'0')
        private fun account(number: Int)="team-"+number.toString(16).padStart(40,'0')
        private val people=listOf("사용자A","사용자E","사용자C","사용자B","사용자D")
        private val members=people.mapIndexed {index,name->TripMember(account(index+1),name,true,index==0,index==0,
            carId=if(index in setOf(0,2,4))id(11) else id(12),hasVehicle=index in setOf(0,3))}
        private val places=listOf(
            TripPlace("합정역 2번 출구",id(21),"pickup",37.549,126.914,selectedBy=listOf(account(3))),
            TripPlace("사당역 1번 출구",id(22),"pickup",37.477,126.982,selectedBy=listOf(account(5))),
            TripPlace("강남역",id(23),"pickup",37.498,127.028,selectedBy=emptyList()),
            TripPlace("대천해수욕장",id(24),"drop",36.305,126.51,selectedBy=listOf(account(5))),
            TripPlace("대천역",id(25),"drop",36.343,126.586,selectedBy=listOf(account(3))))
        private val courses=listOf(
            TripCourse("ganwol-lake","간월호 한 바퀴",1,1,"사용자A",true,true,listOf(id(11),id(12)),listOf(
                TripCourseStop("lake","간월호",36.65,126.45))),
            TripCourse("west-coast","서해안 해안도로 코스",1,3,"사용자A",true,true,emptyList(),listOf(
                TripCourseStop("ganwolam","간월암",36.617,126.411),
                TripCourseStop("kkotji","꽃지해수욕장",36.501,126.337),
                TripCourseStop("daecheon","대천해수욕장",36.305,126.51))),
            TripCourse("boryeong","보령 해안도로",1,2,"사용자B",true,true,emptyList(),listOf(
                TripCourseStop("port","대천항",36.327,126.501),
                TripCourseStop("muchangpo","무창포해수욕장",36.245,126.538))))
        private val order=listOf(TripRouteItem("pickup",id(21)),TripRouteItem("pickup",id(22)),
            TripRouteItem("course","lake","ganwol-lake"),TripRouteItem("course","ganwolam","west-coast"),
            TripRouteItem("course","kkotji","west-coast"),TripRouteItem("course","daecheon","west-coast",id(24)),
            TripRouteItem("course","port","boryeong"),TripRouteItem("course","muchangpo","boryeong"))
        private val cars=listOf(
            TripCar(id(11),"1호차 · 사용자A의 차",account(1),"사용자A",4,true,false,
                listOf(TripPassenger(account(3),"사용자C",false),TripPassenger(account(5),"사용자D",false)),places,order),
            TripCar(id(12),"2호차 · 사용자B의 차",account(4),"사용자B",3,false,false,
                listOf(TripPassenger(account(2),"사용자E",false)),emptyList()))
        val trip=TripDetail(id(1),"서해안 드라이브","서해안 해안도로를 따라 함께 여행해요. 각자 차로 모여 함께 출발해요.",members,cars,
            "2026-11-12","2026-11-13","active",1,courses=courses,rideInvites=emptyList(),
            display=TripDisplay(listOf(TripTimelineEntry("visit:ganwolam","간월암","방문 기록","2026-11-13T02:48:00Z")),1,
                TripMetrics(12.5,600.0),TripMusic("여행 노래","실제 공유 곡",2,"사용자C"),
                listOf(TripCompanionPosition(id(12),null,1400.0,"behind"))))
        val list=TripList(listOf(
            TripSummary(id(1),trip.title,true,"사용자A",5,2,trip.startDate,trip.endDate,"active","내 차 운전"),
            TripSummary(id(2),"양평 두물머리 나들이",false,"사용자C",5,1,"2026-11-21","2026-11-22","planned","차 미정"),
            TripSummary(id(3),"태안 노을 드라이브",false,"사용자D",5,2,"2026-10-24","2026-10-25","completed","내 차 운전")),
            listOf(TripInvitation(id(4),"제주 동쪽 한 바퀴","사용자E","2026-11-28","2026-11-28",3,2)))
        val friends=members.drop(1).map {TripInviteFriend(it.id,it.name,it.hasVehicle,"accepted")}
        fun page(drive: TripDrivingState,gear: TripGear=TripGear.PARK)=TripsPageState(AccountReadStatus.READY,
            list,trip.id,trip,isCurrent=true,gear=gear,driving=drive)
        fun driving(phase: TripDrivingPhase,last: Boolean=false): TripDrivingState {
            val targetIndex=if(last)5 else 3
            val target=order[targetIndex]
            return TripDrivingState(phase,target.key,arrived=order.take(targetIndex).map {it.key}.toSet())
        }
    }
}
