package io.wegoh.app

import android.content.Intent
import android.graphics.Bitmap
import android.os.SystemClock
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.semantics.*
import io.wegoh.app.nativeauth.*
import io.wegoh.app.ui.*
import java.io.File

@Suppress("DEPRECATION")
class VehiclePreparationDetailTest: EntryDesignTestCase() {
    private fun id(value: Int)=value.toString(16).padStart(32,'0')
    private fun account(value: Int)="team-"+value.toString(16).padStart(40,'0')
    private val members=listOf("사용자A","사용자E","사용자C","사용자B","사용자D").mapIndexed {index,name->
        TripMember(account(index+1),name,true,index==0,index==0,hasVehicle=index in setOf(0,3))
    }
    private val trip=TripDetail(id(1),"서해안 드라이브","서해안 해안도로를 따라 함께 여행해요.",members,listOf(
        TripCar(id(11),"1호차 · 사용자A의 차",account(1),"사용자A",4,true,false,
            listOf(TripPassenger(account(3),"사용자C",false),TripPassenger(account(5),"사용자D",false)),places=listOf(
                TripPlace("합정역 2번 출구",id(21),"pickup",37.549,126.914,selectedBy=listOf(account(3))),
                TripPlace("대천역",id(25),"drop",36.343,126.586,selectedBy=listOf(account(3))))),
        TripCar(id(12),"2호차 · 사용자B의 차",account(4),"사용자B",3,false,false,listOf(TripPassenger(account(2),"사용자E",false)))),
        "2026-11-12","2026-11-13","planned",1,courses=listOf(
            TripCourse("ganwol-lake","간월호 한 바퀴",stopCount=1,addedByName="사용자A",stops=listOf(TripCourseStop("lake","간월호",36.65,126.45))),
            TripCourse("west-coast","서해안 해안도로 코스",stopCount=3,addedByName="사용자A",stops=listOf(
                TripCourseStop("ganwolam","간월암",36.617,126.411),TripCourseStop("kkotji","꽃지해수욕장",36.501,126.337),TripCourseStop("daecheon","대천해수욕장",36.305,126.51))),
            TripCourse("boryeong","보령 해안도로",stopCount=2,addedByName="사용자B")))
    private val courses=AccountCourseState(AccountCourseStatus.READY,listOf(
        AccountCourse(PublishedPack("west-coast",1,"서해안 해안도로 코스","사용자A","간월암 → 꽃지해수욕장 → 대천해수욕장",3,""),true),
        AccountCourse(PublishedPack("taean-coast",1,"태안 해안도로","사용자A","만리포 → 꽃지해수욕장",2,""),true)))
    private val friends=members.drop(1).map {TripInviteFriend(it.id,it.name,it.hasVehicle,"accepted")}
    private val page=TripsPageState(AccountReadStatus.READY,selectedId=trip.id,detail=trip,isCurrent=true,gear=TripGear.PARK,inviteFriends=friends)
    @Volatile private var laidOut=0
    @Volatile private var drawn=0
    private var version=0

    override fun setUp() {
        super.setUp()
        host=instrumentation.startActivitySync(Intent(instrumentation.targetContext,SafFrameworkHarnessActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_MULTIPLE_TASK)) as SafFrameworkHarnessActivity
        val deadline=SystemClock.elapsedRealtime()+5000
        while(SystemClock.elapsedRealtime()<deadline) {
            var ready=false
            instrumentation.runOnMainSync {ready=host.hasWindowFocus() && host.window.decorView.isShown && host.window.decorView.width>0}
            if(ready)return
            Thread.sleep(40)
        }
        fail("Preparation preview host did not become visible and focused")
    }
    override fun tearDown() {
        instrumentation.runOnMainSync {host.setContent {};host.finish()}
        super.tearDown()
    }
    private fun show(width: Int=1700,height: Int=1184,night: Boolean=false,content: @Composable ()->Unit) {
        val next=++version
        render(width,height,night,entry=false) {
            TripLayoutRoot(Modifier.fillMaxSize().background(LocalCarPalette.current.background)
                .padding(CarTokens.Frame).onGloballyPositioned {laidOut=next}.drawWithContent {drawContent();drawn=next}) {content()}
        }
        val deadline=SystemClock.elapsedRealtime()+5000
        while(SystemClock.elapsedRealtime()<deadline) {
            if(laidOut==next && drawn==next)return
            Thread.sleep(40)
        }
        fail("Preparation scene $next did not lay out and draw")
    }
    private fun textValues()=nodes().flatMap {it.config.getOrNull(SemanticsProperties.Text).orEmpty()}.map {it.text}
    private fun disabled(label: String)=control(label).config.contains(SemanticsProperties.Disabled)
    private fun save(name: String) {
        val deadline=SystemClock.elapsedRealtime()+5000
        var shot: Bitmap?=null
        var last: NullPointerException?=null
        while(shot==null && SystemClock.elapsedRealtime()<deadline) {
            try {shot=instrumentation.uiAutomation.takeScreenshot()}catch(error: NullPointerException) {last=error}
            if(shot==null)Thread.sleep(80)
        }
        val screenshot=shot ?: throw AssertionError("Preparation screenshot unavailable after 5 seconds").apply {last?.let {initCause(it)}}
        assertTrue("Preparation stays inside visible display",frame.left>=0 && frame.top>=0 && frame.right<=screenshot.width && frame.bottom<=screenshot.height)
        val crop=Bitmap.createBitmap(screenshot,frame.left,frame.top,frame.width(),frame.height())
        val directory=File(host.cacheDir,"preparation-detail").apply {mkdirs()}
        File(directory,"$name.png").outputStream().use {crop.compress(Bitmap.CompressFormat.PNG,100,it)}
        crop.recycle();screenshot.recycle()
    }
    private fun checkTextLayouts() {
        val rendered=nodes()
        val overflow=mutableListOf<String>()
        var checked=0
        instrumentation.runOnMainSync {
            rendered.filter {node->generateSequence(node.parent) {it.parent}.none {it.config.isClearingSemantics}}.forEach {node->
                val layouts=mutableListOf<androidx.compose.ui.text.TextLayoutResult>()
                node.config.getOrNull(SemanticsActions.GetTextLayoutResult)?.action?.invoke(layouts)
                layouts.forEach {layout->
                    checked++
                    val lines=(0 until layout.lineCount).map {line->
                        val left=layout.getLineLeft(line);val top=layout.getLineTop(line)
                        val right=layout.getLineRight(line);val bottom=layout.getLineBottom(line)
                        val ellipsized=layout.isLineEllipsized(line)
                        val clipped=!left.isFinite() || !top.isFinite() || !right.isFinite() || !bottom.isFinite() ||
                            left < -1f || top < -1f || right > layout.size.width+1f || bottom > layout.size.height+1f
                        Triple(ellipsized,clipped,"$line:[$left,$top,$right,$bottom], ellipsis=$ellipsized")
                    }
                    val end=if(layout.lineCount>0)layout.getLineEnd(layout.lineCount-1,visibleEnd=false) else 0
                    if(layout.multiParagraph.didExceedMaxLines || lines.any {it.first || it.second} || end!=layout.layoutInput.text.length)
                        overflow.add("text=${layout.layoutInput.text.text}, size=${layout.size}, paragraph=${layout.multiParagraph.width}x${layout.multiParagraph.height}, intrinsic=${layout.multiParagraph.intrinsics.maxIntrinsicWidth}, lines=${layout.lineCount}, maxLines=${layout.layoutInput.maxLines}, exceeded=${layout.multiParagraph.didExceedMaxLines}, end=$end/${layout.layoutInput.text.length}, bounds=${lines.map {it.third}}")
                }
            }
        }
        assertTrue("Preparation text layouts must be present",checked>0)
        assertTrue("Preparation text is ellipsized or clipped: ${overflow.joinToString()}",overflow.isEmpty())
    }
    private fun verifyPresets(name: String,content: @Composable ()->Unit) {
        for(night in listOf(false,true))for((width,height) in presets) {
            show(width,height,night,content)
            val texts=textValues()
            assertTrue("Actual trip or car heading remains at $width x $height",texts.any {it==trip.title || it==trip.myCar!!.name || it=="여행에 차 추가"})
            assertFalse("Vehicle preparation must not offer link QR",texts.any {it.contains("QR")})
            checkTextLayouts()
            save("$name-${width}x$height-${if(night)"night" else "day"}")
        }
    }
    fun testGroupsAllPresets()=verifyPresets("groups") {
        TripGroupsPage(trip,true,{},TripUiActions(),{},{},TripGear.PARK,{})
    }
    fun testMembersAllPresets()=verifyPresets("members") {
        TripInvitePage(trip,page,true,TripUiActions(),{},TripGear.PARK,{})
    }
    fun testRouteAllPresets()=verifyPresets("route") {
        TripPreparationRoutePage(trip,true,{},TripUiActions(),courses,{},TripGear.PARK,{})
    }
    fun testCarManagementAllPresets()=verifyPresets("manage") {
        TripCarManagePage(trip,true,TripUiActions(),{},{},{},true,TripGear.PARK)
    }
    fun testCarCreationAllPresets()=verifyPresets("create") {
        val unregistered=trip.copy(cars=trip.cars.drop(1))
        TripCarCreatePage(unregistered,null,true,TripUiActions(),{},TripGear.PARK)
    }
    fun testActualPreparationRoutingAndParkRevocation() {
        var state by mutableStateOf(page)
        show {VehicleTripDetailPage(state,{},{},TripUiActions(),true,courses,{},{},history={})}
        tap("차와 일행")
        assertTrue(textValues().contains("차 2대"))
        tap("일행")
        assertTrue(textValues().contains("친구 초대"))
        tap("경로")
        assertTrue(textValues().contains("내 경로에서 추가"))
        tap("차")
        tap("1호차 · 사용자A의 차 관리")
        assertTrue(textValues().contains("타는 곳"))
        tap("차 설정")
        assertTrue(textValues().contains("차 이름"))
        instrumentation.runOnMainSync {state=state.copy(gear=TripGear.DRIVE)}
        settle()
        assertFalse("P-only form closes when D is reported",textValues().contains("차 이름"))
        assertTrue("Preparation overview remains read-only in D",disabled("여행 시작"))
    }
    fun testMemberReadGateAndExistingCourseAction() {
        val member=trip.copy(members=members.map {it.copy(isMe=it.name=="사용자C")},cars=trip.cars.map {it.copy(isMine=false)})
        var friendLoads=0
        val actions=mutableListOf<TripAction>()
        val callbacks=TripUiActions(perform={action,_->actions.add(action)},inviteFriends={friendLoads++})
        show {TripInvitePage(member,page.copy(detail=member),true,callbacks,{},TripGear.PARK,{})}
        assertTrue("Non-inviter can read accepted roster",textValues().containsAll(listOf("사용자A","사용자E","사용자C","사용자B","사용자D")))
        assertEquals("Read-only roster does not request friends",0,friendLoads)
        assertFalse("Vehicle cannot remove accepted members",textValues().contains("내보내기"))
        show {TripPreparationRoutePage(member,true,{},callbacks,courses,{},TripGear.PARK,{})}
        tap("태안 해안도로 여행에 추가")
        assertEquals(listOf(TripAction.AddCourse("taean-coast")),actions)
        assertFalse("Own courses stay on page",textValues().contains("경로 추가"))
    }
    fun testCreationRequiresParkAndRetainsSeatsContract() {
        val unregistered=trip.copy(cars=trip.cars.drop(1))
        val actions=mutableListOf<TripAction>()
        val callbacks=TripUiActions(perform={action,_->actions.add(action)})
        show {TripCarCreatePage(unregistered,null,true,callbacks,{},TripGear.DRIVE)}
        assertTrue(disabled("차 추가"));assertTrue(disabled("좌석 수 늘리기"))
        assertTrue(nodes().filter {it.config.contains(SemanticsActions.SetText)}.all {it.config.contains(SemanticsProperties.Disabled)})
        show {TripCarCreatePage(unregistered,null,true,callbacks,{},TripGear.PARK)}
        tap("좌석 수 늘리기");tap("차 추가")
        assertEquals(listOf(TripAction.CreateCar("사용자A 차",5)),actions)
    }
    fun testIntroEditRetainsRoleParkValidationAndPassivePhoneHint() {
        val edits=mutableListOf<TripAction>()
        var current by mutableStateOf(page)
        val actions=TripUiActions(perform={action,done->edits.add(action);done()})
        fun fill(label: String,value: String) {
            val input=nodes().single {it.config.contains(SemanticsActions.SetText) &&
                it.config.getOrNull(SemanticsProperties.ContentDescription)?.contains(label)==true}
            val action=checkNotNull(input.config.getOrNull(SemanticsActions.SetText)?.action)
            var handled=false
            instrumentation.runOnMainSync {handled=action(androidx.compose.ui.text.AnnotatedString(value))}
            assertTrue("Text editing is handled: $label",handled)
            settle()
        }
        show {VehicleTripDetailPage(current,{},{},actions,true,courses,{},{},history={})}
        tap("고치기")
        val hint="iPhone 앱의 여행에서 이름과 소개를 고치면 여기에 바로 보여요."
        assertTrue(textValues().contains(hint))
        assertFalse(textValues().contains("휴대전화로 고치기"))
        assertFalse(nodes().filter {it.config.contains(SemanticsActions.OnClick)}.any {node->
            node.config.getOrNull(SemanticsProperties.ContentDescription).orEmpty().any {it.contains("iPhone") || it.contains("휴대전화") || it.contains("QR")}
        })
        checkTextLayouts()
        save("intro-1700x1184-day")
        fill("여행 이름","")
        assertTrue("Blank title cannot save",disabled("저장"))
        assertTrue(edits.isEmpty())
        fill("여행 이름","서해안 함께 드라이브")
        fill("소개 (없어도 돼요)","함께 바닷길을 달려요")
        tap("저장")
        assertEquals(listOf(TripAction.EditIntro("서해안 함께 드라이브","함께 바닷길을 달려요")),edits)
        assertFalse("Save completion returns to the overview",textValues().contains("여행 소개 고치기"))
        val member=trip.copy(members=members.map {it.copy(isMe=it.name=="사용자C")},cars=trip.cars.map {it.copy(isMine=false)})
        instrumentation.runOnMainSync {current=page.copy(detail=member)}
        settle()
        assertFalse("Ordinary members cannot enter the editor",nodes().any {it.config.contains(SemanticsActions.OnClick) &&
            it.config.getOrNull(SemanticsProperties.ContentDescription)?.contains("고치기")==true})
        instrumentation.runOnMainSync {current=current.copy(detail=member.copy(myPermissions=TripPermissions(edit=true)))}
        settle()
        tap("고치기")
        assertFalse("An editor can save in P",disabled("저장"))
        instrumentation.runOnMainSync {current=current.copy(gear=TripGear.DRIVE)}
        settle()
        assertFalse("The introduction editor closes when P is lost",textValues().contains("여행 소개 고치기"))
        assertEquals("No extra mutation occurs after role/P checks",1,edits.size)
    }
    fun testPlanningStripContainsOnlySuppliedStops() {
        val stops=trip.courses!![1].stops!!.map {TripRouteStop(TripRouteItem("course",it.id,"west-coast"),it.name,it.lat,it.lng)}
        show {CarRouteStrip(stops,TripDrivingState(),compact=true,planned=true)}
        assertTrue(textValues().containsAll(stops.map {it.name}))
        assertFalse(textValues().contains("출발"));assertFalse(textValues().contains("지금 여기"))
        show {CarRouteStrip(stops,TripDrivingState(),compact=true)}
        assertTrue("Existing driving-strip default remains unchanged",textValues().contains("출발"))
    }
    fun testCompletedLongRouteAndRecordsRenderAtWideAndNarrowWidths() {
        val stops=(1..11).map {index->TripCourseStop("stop-$index","경로 장소 $index",36.5,126.5)}
        val course=trip.courses!!.first().copy(stopCount=stops.size,stops=stops,completedCarIds=emptyList())
        val finished=trip.copy(state="completed",courses=listOf(course),
            cars=trip.cars.map {it.copy(places=emptyList(),routeOrder=null)},display=null)
        for(width in listOf(1700,840)) {
            show(width) {TripResultPage(finished,{}) {TripText("합성 여행 기록")}}
            val texts=textValues()
            assertTrue("All long-route names are retained at $width",texts.containsAll(stops.mapIndexed {index,stop->"${index+1}. ${stop.name}"}))
            assertTrue(texts.contains("계획한 경로"))
            assertTrue("Missing statistics are not reported as a network failure",texts.contains("주행 기록을 확인할 수 없어요"))
            assertFalse("Completion does not claim every stop was visited",texts.contains("모든 경로에 도착했어요"))
            checkTextLayouts()
            save("result-long-route-${width}x1184")
            tap("여행 기록")
            assertTrue("Records content renders at $width",textValues().contains("합성 여행 기록"))
            tap("뒤로")
            assertTrue("Result returns after records at $width",textValues().contains("계획한 경로"))
        }
    }

}
