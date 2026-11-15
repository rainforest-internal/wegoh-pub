package io.wegoh.app

import android.content.Intent
import android.content.res.Configuration
import android.graphics.Bitmap
import android.graphics.Rect
import android.test.InstrumentationTestCase
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.LocalSaveableStateRegistry
import androidx.compose.runtime.saveable.SaveableStateRegistry
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.layout.boundsInWindow
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.*
import androidx.compose.ui.semantics.*
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import io.wegoh.app.nativeauth.*
import io.wegoh.app.ui.*
import java.io.File
import kotlin.math.min
import kotlin.math.roundToInt

/**
 * Real Compose rendering/touch with synthetic trips, gear values and callbacks.
 * Preview dimensions are scaled fixtures, not a physical vehicle display mode.
 * The preview Activity avoids unrelated SDK/service startup; actual CarUx, GPS,
 * navigation and vehicle hardware contracts remain separate integration tests.
 */
@Suppress("DEPRECATION")
class TripSegmentUiTest: InstrumentationTestCase() {
    private lateinit var host: TripScreensPreviewActivity
    private var scene=0
    @Volatile private var drawnScene=0
    @Volatile private var laidOutScene=0
    private var previewWidth=1704
    @Volatile private var frame=Rect()
    private val pickup=TripRouteItem("pickup","pickup-one")
    private val pickupTwo=TripRouteItem("pickup","pickup-two")
    private val join=TripRouteItem("course","join","coast")
    private val sharedEnd=TripRouteItem("course","end","coast")
    private val drop=TripRouteItem("drop","drop-one")
    private val course=TripCourse("coast","서해안 해안도로 코스",1,2,completedCarIds=emptyList(),stops=listOf(
        TripCourseStop("join","간월암",36.61,126.39),TripCourseStop("end","대천해수욕장",36.31,126.51)))
    private val car=TripCar("car-one","1호차 · 사용자A의 차","user-a","사용자A",2,true,false,
        listOf(TripPassenger("user-c","사용자C",false),TripPassenger("user-d","사용자D",false)),places=listOf(
            TripPlace("합정역 2번 출구","pickup-one","pickup",37.55,126.91,selectedBy=listOf("user-c")),
            TripPlace("당산역 9번 출구","pickup-two","pickup",37.53,126.90,selectedBy=listOf("user-d")),
            TripPlace("합정역 2번 출구","drop-one","drop",37.55,126.91,selectedBy=listOf("user-c"))),
        routeOrder=listOf(pickup,pickupTwo,join,sharedEnd,drop))
    private val base=TripDetail("trip","서해안 드라이브","",listOf(
        TripMember("user-a","사용자A",true,true,true),TripMember("user-c","사용자C",true,false,false),TripMember("user-d","사용자D",true,false,false)),
        listOf(car),state="active",revision=1,courses=listOf(course),routeContractVersion=2)
    private fun trip(phase: String,next: TripRouteItem?)=base.copy(cars=listOf(car.copy(routePlan=TripRoutePlan(2,phase,listOf(
        TripRouteSegment("pickup",listOf(pickup,pickupTwo)),TripRouteSegment("shared",listOf(join,sharedEnd)),TripRouteSegment("drop",listOf(drop))),
        TripJoinPoint("coast","join","간월암",36.61,126.39),null,0,next,TripJoinBarrier(listOf(car.id),2,false)))))
    private fun state(trip: TripDetail,target: TripRouteItem?,gear: TripGear=TripGear.PARK)=TripsPageState(
        status=AccountReadStatus.READY,detail=trip,isCurrent=true,gear=gear,
        driving=TripDrivingState(TripDrivingPhase.NEAR,target?.key,250.0,true,remainingSeconds=60))

    override fun setUp() {
        super.setUp()
        host=instrumentation.startActivitySync(Intent(instrumentation.targetContext,TripScreensPreviewActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_MULTIPLE_TASK)) as TripScreensPreviewActivity
    }
    override fun tearDown() {
        try {instrumentation.runOnMainSync {host.setContent {};host.finish()}}finally {super.tearDown()}
    }
    private fun await(message: String,condition: ()->Boolean) {
        val end=android.os.SystemClock.uptimeMillis()+8000
        while(android.os.SystemClock.uptimeMillis()<end) {if(condition())return;Thread.sleep(80)}
        fail(message)
    }
    private fun render(width: Int=1704,height: Int=1208,restorationKey: String?=null,content: @Composable ()->Unit) {
        previewWidth=width
        instrumentation.runOnMainSync {val version=++scene;host.setContent {key(restorationKey ?: version) {
            BoxWithConstraints(Modifier.fillMaxSize(),contentAlignment=Alignment.Center) {
                val scale=min(constraints.maxWidth.toFloat()/width,constraints.maxHeight.toFloat()/height)
                val config=Configuration(LocalConfiguration.current).apply {screenWidthDp=width;screenHeightDp=height;fontScale=1f}
                CompositionLocalProvider(LocalDensity provides Density(scale),LocalConfiguration provides config) {
                    Box(Modifier.requiredSize(width.dp,height.dp).drawWithContent {drawContent();drawnScene=version}.onGloballyPositioned {coordinates->
                        val b=coordinates.boundsInWindow();val origin=IntArray(2);host.window.decorView.getLocationOnScreen(origin)
                        frame=Rect(b.left.roundToInt()+origin[0],b.top.roundToInt()+origin[1],b.right.roundToInt()+origin[0],b.bottom.roundToInt()+origin[1])
                        laidOutScene=version
                    }) {WegoCarTheme(false) {TripSurface {content()}}}
                }
            }
        }}};instrumentation.waitForIdleSync()
        await("Segment preview scene $scene is focused, laid out and drawn") {
            host.hasWindowFocus() && !frame.isEmpty && laidOutScene==scene && drawnScene==scene
        }
    }
    private fun semantics(read: (List<SemanticsNode>)->Unit) {
        instrumentation.runOnMainSync {
            val result=mutableListOf<SemanticsNode>()
            fun inspect(view: View) {
                if(view is ViewRootForTest)result.addAll(view.semanticsOwner.getAllSemanticsNodes(mergingEnabled=false))
                if(view is ViewGroup)for(index in 0 until view.childCount)inspect(view.getChildAt(index))
            }
            inspect(host.window.decorView)
            read(result)
        }
    }
    private fun text(label: String): Boolean {
        var found=false
        semantics {nodes->found=nodes.any {it.config.getOrNull(SemanticsProperties.Text)?.any {text->text.text==label}==true}}
        return found
    }
    private data class Button(val disabled: Boolean,val bounds: Rect,val width: Int,val height: Int)
    private fun button(label: String): Button? {
        var found: Button?=null
        semantics {nodes->nodes.firstOrNull {it.config.contains(SemanticsActions.OnClick) &&
            it.config.getOrNull(SemanticsProperties.ContentDescription)?.contains(label)==true}?.let {node->
            val b=node.boundsInWindow;val origin=IntArray(2);host.window.decorView.getLocationOnScreen(origin)
            found=Button(node.config.contains(SemanticsProperties.Disabled),
                Rect(b.left.roundToInt()+origin[0],b.top.roundToInt()+origin[1],b.right.roundToInt()+origin[0],b.bottom.roundToInt()+origin[1]),node.size.width,node.size.height)
        }}
        return found
    }
    private fun visibleButton(label: String): Boolean = button(label)?.let {
        !it.bounds.isEmpty && frame.contains(it.bounds) && it.bounds.width()>=it.width-1 && it.bounds.height()>=it.height-1 &&
            it.bounds.height()>=CarTokens.Touch.value*frame.width()/previewWidth.toFloat()-2
    } ?: false
    private fun visibleText(label: String): Boolean {
        var visible=false
        semantics {nodes->visible=nodes.any {node->
            val bounds=node.boundsInWindow
            val origin=IntArray(2);host.window.decorView.getLocationOnScreen(origin)
            val screen=Rect(bounds.left.roundToInt()+origin[0],bounds.top.roundToInt()+origin[1],bounds.right.roundToInt()+origin[0],bounds.bottom.roundToInt()+origin[1])
            node.config.getOrNull(SemanticsProperties.Text)?.any {it.text==label}==true && !screen.isEmpty && frame.contains(screen) &&
                screen.width()>=node.size.width-1 && screen.height()>=node.size.height-1
        }}
        return visible
    }
    private fun reveal(label: String,clickable: Boolean=false) {
        repeat(32) {
            if(if(clickable)visibleButton(label) else visibleText(label))return
            var range: ScrollAxisRange?=null
            var before=0f
            var direction=1f
            var accepted=false
            var targetFound=false
            var targetDescription=""
            var available=""
            var scrollDescription=""
            semantics {nodes->
                val target=nodes.firstOrNull {node->if(clickable)
                    node.config.contains(SemanticsActions.OnClick) && node.config.getOrNull(SemanticsProperties.ContentDescription)?.contains(label)==true
                    else node.config.getOrNull(SemanticsProperties.Text)?.any {it.text==label}==true}
                targetFound=target!=null
                targetDescription=target?.let {"bounds=${it.boundsInWindow}, position=${it.positionInWindow}, size=${it.size}, frame=$frame"}.orEmpty()
                available=nodes.flatMap {node->
                    node.config.getOrNull(SemanticsProperties.Text)?.map {it.text}.orEmpty()+
                        node.config.getOrNull(SemanticsProperties.ContentDescription).orEmpty()
                }.distinct().take(60).joinToString(" | ")
                val ancestors=generateSequence(target) {it.parent}.filter {node->
                    node.config.getOrNull(SemanticsProperties.VerticalScrollAxisRange)!=null &&
                        node.config.getOrNull(SemanticsActions.ScrollBy)?.action!=null
                }.toList()
                for(scroller in ancestors) {
                    val axis=checkNotNull(scroller.config.getOrNull(SemanticsProperties.VerticalScrollAxisRange))
                    val viewportTop=scroller.positionInWindow.y
                    val viewportBottom=viewportTop+scroller.size.height
                    val targetTop=checkNotNull(target).positionInWindow.y
                    val targetBottom=targetTop+target.size.height
                    val offset=when {
                        targetTop<viewportTop->targetTop-viewportTop
                        targetBottom>viewportBottom->targetBottom-viewportBottom
                        else->0f
                    }
                    val current=axis.value()
                    val remaining=if(offset<0)current else axis.maxValue()-current
                    scrollDescription+=" [viewport=$viewportTop..$viewportBottom, clipped=${scroller.boundsInWindow}, value=$current/${axis.maxValue()}, targetOffset=$offset]"
                    // A child can be inside its own scroll viewport yet hidden by
                    // an outer one. Its clipped bounds are then zero/partial;
                    // scrolling that inner viewport cannot reveal the target.
                    if(offset==0f || remaining<=0f || scroller.size.height<=0)continue
                    range=axis;before=current;direction=if(offset<0)-1f else 1f
                    accepted=scroller.config.getOrNull(SemanticsActions.ScrollBy)?.action
                        ?.invoke(0f,direction*minOf(scroller.size.height/3f,remaining,kotlin.math.abs(offset)))==true
                    break
                }
            }
            assertTrue("Target is absent from composed semantics: $label; available=$available",targetFound)
            assertNotNull("Target has no scrollable ancestor that can reveal it: $label; $targetDescription; $scrollDescription",range)
            assertTrue("Actual scroll moves toward the full target: $label; $targetDescription; $scrollDescription",accepted)
            instrumentation.uiAutomation.waitForIdle(100,1500)
            instrumentation.waitForIdleSync()
            var after=before
            var stableSince=android.os.SystemClock.uptimeMillis()
            await("Scroll range stabilizes before checking $label") {
                var value=before
                instrumentation.runOnMainSync {value=checkNotNull(range).value()}
                if(value!=after) {after=value;stableSince=android.os.SystemClock.uptimeMillis()}
                (after-before)*direction>0 && android.os.SystemClock.uptimeMillis()-stableSince>=200
            }
        }
        assertTrue("Full target remains physically reachable: $label",if(clickable)visibleButton(label) else visibleText(label))
    }
    private fun tap(label: String,disabled: Boolean=false) {
        val node=checkNotNull(button(label)) {"Button missing: $label"}
        assertEquals("Button permission: $label",disabled,node.disabled)
        val bounds=node.bounds
        assertTrue("Complete physical touch target is visible: $label",frame.contains(bounds) && !bounds.isEmpty)
        assertTrue("Physical touch target is unclipped: $label",bounds.width()>=node.width-1 && bounds.height()>=node.height-1)
        val down=android.os.SystemClock.uptimeMillis()
        for((action,time) in listOf(MotionEvent.ACTION_DOWN to down,MotionEvent.ACTION_UP to down+50)) {
            instrumentation.runOnMainSync {
                val decor=host.window.decorView
                val origin=IntArray(2);decor.getLocationOnScreen(origin)
                val event=MotionEvent.obtain(down,time,action,bounds.exactCenterX()-origin[0],bounds.exactCenterY()-origin[1],0)
                event.source=android.view.InputDevice.SOURCE_TOUCHSCREEN
                try {
                    val handled=decor.dispatchTouchEvent(event)
                    if(!disabled)assertTrue("Component touch is handled: $label",handled)
                }finally {event.recycle()}
            }
        }
        instrumentation.waitForIdleSync()
    }
    private fun activate(label: String) {
        assertTrue("Complete accessible touch target is visible: $label",visibleButton(label))
        var handled=false
        semantics {nodes->
            val node=nodes.single {it.config.contains(SemanticsActions.OnClick) &&
                it.config.getOrNull(SemanticsProperties.ContentDescription)?.contains(label)==true}
            assertFalse("Accessible action is enabled: $label",node.config.contains(SemanticsProperties.Disabled))
            handled=node.config.getOrNull(SemanticsActions.OnClick)?.action?.invoke()==true
        }
        assertTrue("Accessible action is handled: $label",handled)
        instrumentation.waitForIdleSync()
    }
    private fun screenshot(name: String) {
        val fresh=java.util.concurrent.CountDownLatch(1)
        instrumentation.runOnMainSync {host.window.decorView.postOnAnimation {host.window.decorView.postOnAnimation {fresh.countDown()}}}
        assertTrue("Fresh segment frame is presented",fresh.await(5,java.util.concurrent.TimeUnit.SECONDS))
        await("Fresh screenshot belongs to segment scene $scene") {
            host.hasWindowFocus() && laidOutScene==scene && drawnScene==scene && !frame.isEmpty
        }
        val deadline=android.os.SystemClock.uptimeMillis()+5000
        var bitmap: Bitmap?=null
        var failure: NullPointerException?=null
        while(bitmap==null && android.os.SystemClock.uptimeMillis()<deadline) {
            try {bitmap=instrumentation.uiAutomation.takeScreenshot()}catch(error: NullPointerException) {failure=error}
            if(bitmap==null)Thread.sleep(80)
        }
        val image=bitmap ?: throw AssertionError("No segment screenshot was returned",failure)
        val crop=Bitmap.createBitmap(image,frame.left,frame.top,frame.width(),frame.height())
        val directory=File(host.filesDir,"trip-segments").apply {mkdirs()}
        File(directory,"$name.png").outputStream().use {crop.compress(Bitmap.CompressFormat.PNG,100,it)}
        crop.recycle();image.recycle()
    }

    fun testEveryPreparationHeaderSendsVersionTwoStartRequest() {
        val planned=base.copy(state="planned",revision=7)
        for(tab in TripPlanTab.entries) {
            val requests=mutableListOf<TripActionRequest>()
            val actions=TripUiActions(perform={action,finished->requests.add(TripActionCodec.request(action));finished()})
            render {
                if(tab==TripPlanTab.OVERVIEW)TripPlanPage(planned,true,{},actions,null,{},{},{},
                    AccountCourseState(),{},gear=TripGear.PARK)
                else TripPreparationFrame(planned,true,tab,{},actions,TripGear.PARK,{}) {TripText(tab.title)}
            }
            await("${tab.title} start is physically visible") {visibleButton("여행 시작")}
            activate("여행 시작")
            assertEquals("${tab.title} emits exactly one request",1,requests.size)
            val request=requests.single()
            assertEquals("POST",request.method)
            assertEquals("/start",request.suffix)
            assertEquals(7L,request.body.getLong("revision"))
            assertEquals("${tab.title} must opt in to the three-segment route",2,request.body.getInt("routeContractVersion"))
        }
    }

    fun testParkedSharedConfirmationIsShownWithoutLocationOrActiveNavigation() {
        val shared=trip("shared",sharedEnd)
        val items=mutableListOf<String>()
        render {TripActivePage(shared,state(shared,null).copy(driving=TripDrivingState()),true,
            TripUiActions(arrive={items.add(checkNotNull(shared.myCar?.routePlan?.next).key)}),{},{},{})}
        reveal("도착했어요",clickable=true)
        assertTrue("Shared confirmation is reachable without NEAR or a navigation target",visibleButton("도착했어요"))
        tap("도착했어요")
        assertEquals(listOf(sharedEnd.key),items)
        screenshot("shared-manual-arrival")
        render {TripActivePage(shared,state(shared,null).copy(driving=TripDrivingState()),false,
            TripUiActions(arrive={items.add("unexpected")}),{},{},{})}
        reveal("도착했어요",clickable=true)
        tap("도착했어요",disabled=true)
        assertEquals(listOf(sharedEnd.key),items)
    }

    fun testPickupAndDropParkDriveTransitionsNeverExposeDrivingArrival() {
        for(phase in listOf("pickup","drop")) {
            val next=if(phase=="pickup")pickup else drop
            val currentTrip=trip(phase,next)
            var current by mutableStateOf(state(currentTrip,null).copy(driving=TripDrivingState()))
            var arrivals=0
            var signals=0
            val actions=TripUiActions(arrive={arrivals++})
            val label=if(phase=="pickup")"탔어요" else "우리 차 주행 완료"
            render(width=1704,height=1208) {
                if(current.gear==TripGear.DRIVE)TripDrivingDashboard(currentTrip,current,{signals++},null)
                else TripActivePage(currentTrip,current,true,actions,{},{},{})
            }
            reveal(label,clickable=true);tap(label)
            assertEquals(1,arrivals)
            instrumentation.runOnMainSync {current=current.copy(gear=TripGear.DRIVE)}
            await("$phase D dashboard is visible") {text(if(phase=="pickup")"타는 곳으로 이동 중" else "내리는 곳으로 이동 중")}
            assertNull("$phase D never exposes arrival",button(label))
            assertTrue("$phase D keeps the hand-raise entry physically reachable",visibleButton("손들기"))
            assertEquals("A gear transition must not send a signal",0,signals)
            instrumentation.runOnMainSync {current=current.copy(gear=TripGear.PARK)}
            await("$phase P screen is restored") {button(label)!=null}
            reveal(label,clickable=true);tap(label)
            assertEquals("$phase P regains manual arrival without location",2,arrivals)
        }
    }

    fun testPickupConfirmationUsesServerNextAndWaitingHasNoConfirmation() {
        var arrivals=0
        val controls=TripUiActions(arrive={arrivals++})
        val pickupTrip=trip("pickup",pickup)
        render {TripActivePage(pickupTrip,state(pickupTrip,pickup),true,controls,{},{},{})}
        await("Pickup confirmation is shown") {button("탔어요")!=null}
        screenshot("pickup-parked")
        tap("탔어요")
        assertEquals(1,arrivals)
        render {TripActivePage(pickupTrip,state(pickupTrip,pickupTwo),true,controls,{},{},{})}
        tap("탔어요")
        assertEquals("A different navigation target does not block manual server-next confirmation",2,arrivals)
        val waiting=trip("waiting",sharedEnd)
        render {TripActivePage(waiting,state(waiting,sharedEnd),true,controls,{},{},{})}
        await("Waiting message is shown") {text("합류 대기")}
        assertNull(button("합류 지점 도착"))
        assertNull(button("도착했어요"))
        screenshot("waiting-parked")
        assertEquals(2,arrivals)
    }

    fun testPreparationOnlyMovesPrivateSegmentsAndDrivingKeepsArrivalUnavailable() {
        val prepared=trip("pickup",pickup).copy(state="planned")
        val saved=mutableListOf<List<TripRouteItem>>()
        render {TripDeparturePage(prepared,state(prepared,null),true,TripUiActions(saveOrder={items,_,_->saved.add(items)}),{},{})}
        await("Three departure columns are rendered") {text("타는 곳") && text("함께 가는 경로") && text("내리는 곳")}
        tap("합정역 2번 출구 순서 아래로")
        tap("저장")
        assertEquals(1,saved.size)
        assertEquals(listOf(pickupTwo,pickup),saved.single().filter {it.type=="pickup"})
        assertEquals(listOf(join,sharedEnd),saved.single().filter {it.type=="course"})
        assertEquals(listOf(drop),saved.single().filter {it.type=="drop"})
        screenshot("departure-three-columns")
        val dropped=trip("drop",drop)
        render(width=800,height=810) {TripDrivingDashboard(dropped,state(dropped,drop,TripGear.DRIVE),{},voice=null)}
        await("Driving drop locks comparison") {text("내리는 곳으로 이동 중")}
        assertNull(button("손들기"))
        assertFalse(text("최종 100점"))
        assertNull(button("우리 차 주행 완료"))
        screenshot("drop-driving-narrow")
    }

    fun testPickupDrivingScorePanelKeepsLargeVoiceActionAtNarrowAndWide() {
        for(width in listOf(648,1704)) {
            val pickupTrip=trip("pickup",pickup)
            var voices=0
            var signals=0
            render(width=width,height=if(width==648)800 else 1208) {
                TripDrivingDashboard(pickupTrip,state(pickupTrip,pickup,TripGear.DRIVE),{signals++},voice={modifier->
                    CarButton("워키토키",{voices++},modifier,primary=true,textStyle=CarType.Title)
                })
            }
            await("Actual driving dashboard pickup and locked tile are visible at $width") {
                visibleText("합정역 2번 출구") && visibleText("타는 곳으로 이동 중") && visibleButton("워키토키")
            }
            val voice=checkNotNull(button("워키토키"))
            val scale=frame.width()/width.toFloat()
            val minimum=if(width==648)CarTokens.ButtonDrivingCompact.value else CarTokens.ButtonDriving.value
            assertTrue("Large driving PTT retains full physical height at $width",voice.bounds.height()>=minimum*scale-2)
            assertTrue("Large driving PTT uses its own half-width region at $width",voice.bounds.width()>frame.width()/3)
            assertNull("Pickup D has no hand-raise request action",button("손들기"))
            assertNull("Pickup D has no arrival mutation",button("탔어요"))
            screenshot("pickup-driving-$width")
            tap("워키토키")
            await("The driving PTT callback is preserved at $width") {voices==1}
            assertEquals(0,signals)
        }
    }

    fun testDropParkedShowsReportedTripScoresAndOnlyConfirmsExpectedDropAtNarrowAndWide() {
        val secondDrop=TripRouteItem("drop","drop-two")
        val other=TripCar("car-two","2호차 · 사용자B의 차","user-b","사용자B",2,false,false,emptyList())
        // The current live panel displays reported whole-trip totals. A trip that
        // is still dropping passengers has no final winner presentation.
        val versus=TripDrivingVersus("safe-driving-versus",true,"pending",null,listOf(
            TripDrivingVersusCar(car.id,car.name,true,"ready",null,0,emptyList(),totalScore=90),
            TripDrivingVersusCar(other.id,other.name,true,"ready",null,0,emptyList(),totalScore=85)),
            emptyList(),false,scope="trip")
        fun current(next: TripRouteItem): TripDetail {
            val initial=trip("drop",next)
            val mine=checkNotNull(initial.myCar)
            return initial.copy(members=initial.members+TripMember("user-b","사용자B",true,false,false),cars=listOf(mine.copy(
                places=mine.places.orEmpty()+TripPlace("당산역 9번 출구","drop-two","drop",37.53,126.90,selectedBy=listOf("user-d")),
                routePlan=checkNotNull(mine.routePlan).copy(segments=checkNotNull(mine.routePlan).segments.map {
                    if(it.segment=="drop")it.copy(items=listOf(drop,secondDrop)) else it
                },joinBarrier=TripJoinBarrier(listOf(mine.id,other.id),2,true))),other))
        }
        for(width in listOf(648,1704)) {
            val arrivals=mutableListOf<String>()
            val navigations=mutableListOf<String>()
            fun show(detail: TripDetail,target: TripRouteItem) {
                render(width=width,height=if(width==648)800 else 1208) {
                    TripActivePage(detail,state(detail,target).copy(drivingVersus=versus),true,
                        TripUiActions(arrive={arrivals.add(checkNotNull(detail.myCar?.routePlan?.next).key)},
                            navigate={navigations.add(it.key)}),{},{},{})
                }
            }
            show(current(drop),drop)
            reveal("안전운전 점수")
            assertTrue("Whole-trip score heading is reachable at $width",visibleText("안전운전 점수"))
            reveal("90점")
            assertTrue("Own reported total remains visible at $width",visibleText("90점"))
            reveal("85점")
            assertTrue("Other car's reported total remains visible at $width",visibleText("85점"))
            assertFalse("An ongoing drop must not announce a final winner",text("${car.name} 승리"))
            screenshot("drop-parked-summary-$width")
            reveal("내렸어요",clickable=true)
            assertNull("An earlier drop never exposes the final-drop action",button("우리 차 주행 완료"))
            assertTrue("Navigation uses the expected next drop",visibleButton("합정역 2번 출구 길 안내"))
            screenshot("drop-parked-next-$width")
            tap("합정역 2번 출구 길 안내")
            assertEquals(listOf(drop.key),navigations)
            tap("내렸어요")
            assertEquals(listOf(drop.key),arrivals)
            show(current(secondDrop),drop)
            reveal("우리 차 주행 완료",clickable=true)
            tap("우리 차 주행 완료")
            assertEquals("Confirmation still uses server next despite a different navigation target",listOf(drop.key,secondDrop.key),arrivals)
            show(current(secondDrop),secondDrop)
            reveal("우리 차 주행 완료",clickable=true)
            assertTrue("Last-drop navigation is visible",visibleButton("당산역 9번 출구 길 안내"))
            screenshot("drop-parked-last-$width")
            tap("우리 차 주행 완료")
            assertEquals(listOf(drop.key,secondDrop.key,secondDrop.key),arrivals)
        }
    }

    fun testDepartureSectionsRemainReachableAndPrivateOnlyAtNarrowAndWide() {
        val prepared=trip("pickup",pickup).copy(state="planned")
        for(width in listOf(648,1704)) {
            val saved=mutableListOf<List<TripRouteItem>>()
            render(width=width,height=if(width==648)800 else 1208) {
                TripDeparturePage(prepared,state(prepared,null),true,TripUiActions(saveOrder={items,_,_->saved.add(items)}),{},{})
            }
            reveal("타는 곳")
            assertTrue("Pickup section is physically visible at $width",visibleText("타는 곳"))
            reveal("합정역 2번 출구 순서 아래로",clickable=true)
            screenshot("departure-pickup-$width")
            tap("합정역 2번 출구 순서 아래로")
            reveal("함께 가는 경로")
            assertTrue("Shared section is physically visible at $width",visibleText("함께 가는 경로"))
            reveal("1. ${course.title}")
            assertNull("Shared course has no move-up action",button("${course.title} 순서 위로"))
            assertNull("Shared course has no move-down action",button("${course.title} 순서 아래로"))
            assertTrue("Shared course remains visible and locked at $width",visibleText("1. ${course.title}"))
            screenshot("departure-shared-$width")
            reveal("내리는 곳")
            assertTrue("Drop section is physically visible at $width",visibleText("내리는 곳"))
            reveal("저장",clickable=true)
            screenshot("departure-drop-$width")
            tap("저장")
            assertEquals(1,saved.size)
            assertEquals(listOf(pickupTwo,pickup),saved.single().filter {it.type=="pickup"})
            assertEquals("The shared sequence cannot be changed by private reorder",listOf(join,sharedEnd),saved.single().filter {it.type=="course"})
            assertEquals(listOf(drop),saved.single().filter {it.type=="drop"})
        }
    }
    fun testCarFormRestoresUnsavedNameAndSeats() {
        var registry=SaveableStateRegistry(null) {true}
        val edits=mutableListOf<TripAction>()
        val actions=TripUiActions(perform={action,_->edits.add(action)})
        fun show()=render(restorationKey="car-draft") {
            CompositionLocalProvider(LocalSaveableStateRegistry provides registry) {
                TripCarCreatePage(base,car,true,actions,{},TripGear.PARK)
            }
        }
        show()
        semantics {nodes->
            val field=nodes.single {it.config.contains(SemanticsActions.SetText)}
            assertTrue(checkNotNull(field.config.getOrNull(SemanticsActions.SetText)?.action)
                .invoke(androidx.compose.ui.text.AnnotatedString("새 그룹 이름")))
        }
        tap("자리 수 늘리기")
        instrumentation.runOnMainSync {
            val saved=registry.performSave()
            host.setContent {}
            registry=SaveableStateRegistry(saved) {true}
        }
        instrumentation.waitForIdleSync()
        show()
        reveal("저장",clickable=true);tap("저장")
        assertEquals(listOf(TripAction.EditCar(car.id,"새 그룹 이름",car.seats+1)),edits)
    }

    fun testRouteDraftRestoresOrderAndKeepsOriginalRevisionConflict() {
        var detail=trip("pickup",pickup).copy(state="planned")
        var registry=SaveableStateRegistry(null) {true}
        fun show()=render(restorationKey="route-draft") {
            CompositionLocalProvider(LocalSaveableStateRegistry provides registry) {
                TripSegmentPreparationPage(detail,state(detail,null),true,TripUiActions(),{},{})
            }
        }
        show()
        reveal("합정역 2번 출구 순서 아래로",clickable=true)
        tap("합정역 2번 출구 순서 아래로")
        instrumentation.runOnMainSync {
            val saved=registry.performSave()
            host.setContent {}
            registry=SaveableStateRegistry(saved) {true}
            val currentCar=detail.cars.single()
            detail=detail.copy(cars=listOf(currentCar.copy(routeRevision=currentCar.routeRevision+1)))
        }
        instrumentation.waitForIdleSync()
        show()
        assertTrue("Restored private order survives",text("1. 당산역 9번 출구"))
        assertTrue("Restored draft keeps its original revision",text("경로가 바뀌었어요. 작성 중인 순서는 보존했어요. 새 경로를 불러온 뒤 저장해 주세요."))
        reveal("이 순서로 저장",clickable=true)
        assertTrue(checkNotNull(button("이 순서로 저장")).disabled)
    }

    fun testGroupSignalTimeoutPreservesPendingResponseAndFailure() {
        val signal=TripSignal("request","other",TripSignalKind.RESTROOM,
            SignalDestination("휴게소",37.0,126.8),"2026-11-13T00:00:00Z","valid",0,0,null,
            decisionRule="other-car-groups-v1",requesterCarId="other-car",canRespond=true)
        val response=mutableStateOf(TripSignalState(voting=true))
        val dismissals=java.util.concurrent.atomic.AtomicInteger()
        render {TripGroupSignalResponsePage(base,signal,response.value,
            TripUiActions(dismissSignal={dismissals.incrementAndGet()}),TripGear.PARK)}
        Thread.sleep(16000)
        assertEquals("Submitting must survive the original 15-second notification timeout",0,dismissals.get())
        instrumentation.runOnMainSync {
            response.value=response.value.copy(voting=false,result="답을 보내지 못했어요. 다시 눌러 주세요")
        }
        Thread.sleep(16000)
        assertEquals("Failure remains available for retry",0,dismissals.get())
        assertTrue(text("답을 보내지 못했어요. 다시 눌러 주세요"))
        assertFalse(checkNotNull(button("동의")).disabled)
    }

    fun testGroupSignalResponseKeepsCandidateWaitingActionsAndPhoneHintVisibleAtBothWidths() {
        val places=(1..9).map {TripCourseStop("place-$it","공유 장소 $it",36.6-it/100.0,126.4)}
        val items=places.map {TripRouteItem("course",it.id,course.packId)}
        val original=trip("shared",join)
        val mine=car.copy(places=emptyList(),routeOrder=items,routeNext=items.first(),
            routePlan=checkNotNull(original.cars.single().routePlan).copy(segments=listOf(
                TripRouteSegment("pickup",emptyList()),TripRouteSegment("shared",items),TripRouteSegment("drop",emptyList())),next=items.first()))
        val other=TripCar("car-two","사용자B의 차","user-b","사용자B",2,false,false,
            listOf(TripPassenger("user-e","사용자E",false)),ordinal=2)
        val detail=original.copy(members=original.members+TripMember("user-e","사용자E",true,false,false),
            cars=listOf(mine,other),courses=listOf(course.copy(stopCount=places.size,stops=places)))
        val signal=TripSignal("request","user-e",TripSignalKind.RESTROOM,
            SignalDestination("화성휴게소(목포방향)",37.0,126.8),"2026-11-13T00:00:00Z","valid",0,0,null,
            decisionRule="other-car-groups-v1",requesterCarId=other.id,canRespond=true,
            groupVotes=TripGroupVotes(0,0,1),groupResponses=listOf(TripGroupResponse(mine.id,mine.name,null)),
            candidateDetails=TripSignalCandidateDetails("서해안선","하행",14700,120))
        val hint="차마다 먼저 선택한 답을 보내요"
        for(width in listOf(1700,840)) {
            val response=mutableStateOf(TripSignalState())
            val votes=mutableListOf<String>()
            render(width,1184) {TripGroupSignalResponsePage(detail,signal,response.value,
                TripUiActions(voteSignal={votes+=it}),TripGear.PARK)}
            for(label in listOf("화성휴게소(목포방향)","맨 앞 차에서 14.7 km","예상 2분 추가","서해안선","하행",
                "전원 동의 시 다음 목적지 앞에 추가해요","내 차 응답 대기",hint))
                assertTrue("Initial response text is fully visible at $width: $label",visibleText(label))
            for(label in listOf("다음에","동의")) {
                assertTrue("Full response action is initially visible at $width: $label",visibleButton(label))
                assertFalse("Pending response action is enabled at $width: $label",checkNotNull(button(label)).disabled)
            }
            var hintTop=0
            semantics {nodes->
                val text=nodes.single {it.config.getOrNull(SemanticsProperties.Text)?.any {value->value.text==hint}==true}
                val origin=IntArray(2);host.window.decorView.getLocationOnScreen(origin)
                hintTop=text.boundsInWindow.top.roundToInt()+origin[1]
                assertTrue("Long route retains a horizontal scroll path at $width",nodes.any {
                    it.config.getOrNull(SemanticsProperties.HorizontalScrollAxisRange)?.maxValue()?.let {value->value>0}==true})
            }
            assertTrue("Phone hint is below both actions at $width",hintTop>=maxOf(
                checkNotNull(button("다음에")).bounds.bottom,checkNotNull(button("동의")).bounds.bottom))
            screenshot("signal-response-$width")
            tap("동의");assertEquals(listOf("agree"),votes)
            instrumentation.runOnMainSync {response.value=response.value.copy(voting=true)}
            await("Voting disables both response actions at $width") {
                button("다음에")?.disabled==true && button("동의")?.disabled==true
            }
            assertEquals("Rendering pending state never sends another vote",1,votes.size)
            val agreedPlaces=places+(10..13).map {TripCourseStop("place-$it","공유 장소 $it",36.6-it/100.0,126.4)}
            val agreedItems=agreedPlaces.map {TripRouteItem("course",it.id,course.packId)}
            val agreedMine=mine.copy(routeOrder=agreedItems,routePlan=checkNotNull(mine.routePlan).copy(segments=listOf(
                TripRouteSegment("pickup",emptyList()),TripRouteSegment("shared",agreedItems),TripRouteSegment("drop",emptyList()))))
            val agreedDetail=detail.copy(cars=listOf(agreedMine,other),
                courses=listOf(course.copy(stopCount=agreedPlaces.size,stops=agreedPlaces)))
            render(width,1184) {TripGroupSignalStatusPage(agreedDetail,
                signal.copy(inProgress=false,resolution="agreed",canRespond=false,myGroupChoice="agree",groupVotes=TripGroupVotes(1,0,1)),
                TripSignalState(),TripUiActions(),{})}
            assertTrue("Agreed candidate estimate is initially visible at $width",visibleText("맨 앞 차에서 14.7 km") && visibleText("예상 2분 추가"))
            assertTrue("Agreed long route retains its first place at $width",text(agreedPlaces.first().name))
            assertTrue("Agreed long route retains its last place at $width",text(agreedPlaces.last().name))
            semantics {nodes->assertTrue("All thirteen agreed places retain a horizontal scroll path at $width",nodes.any {
                it.config.getOrNull(SemanticsProperties.HorizontalScrollAxisRange)?.maxValue()?.let {value->value>0}==true})}
            if(width==1700) {
                assertTrue("Wide response column heading is initially visible",visibleText("차량별 응답"))
                assertTrue("Wide return action is initially visible",visibleButton("여행 상세로"))
                semantics {nodes->
                    fun textNode(label: String)=nodes.single {it.config.getOrNull(SemanticsProperties.Text)?.any {value->value.text==label}==true}
                    val candidate=textNode("화성휴게소(목포방향)").boundsInWindow
                    val responses=textNode("차량별 응답").boundsInWindow
                    assertTrue("Wide candidate and response panels remain side by side",candidate.right<=responses.left && candidate.left<responses.left)
                }
            } else semantics {nodes->assertTrue("Narrow status keeps vertical scrolling",nodes.any {
                it.config.getOrNull(SemanticsProperties.VerticalScrollAxisRange)!=null})}
        }
    }
}
