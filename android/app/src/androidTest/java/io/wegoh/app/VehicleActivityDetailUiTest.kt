package io.wegoh.app

import android.content.Intent
import android.graphics.Bitmap
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import io.wegoh.app.nativeauth.*
import io.wegoh.app.nativebusiness.*
import io.wegoh.app.ui.*
import java.io.File
import java.time.Instant

@Suppress("DEPRECATION")
class VehicleActivityDetailUiTest: EntryDesignTestCase() {
    private val member=TripMember("me","사용자A",true,true,true)
    private val mine=TripCar("my-car","사용자A의 차","me","사용자A",3,true,false,emptyList())
    private val other=TripCar("other-car","사용자B의 차","other","사용자B",3,false,false,emptyList())
    private val trip=TripDetail("trip","서해안 드라이브","",listOf(member,TripMember("other","사용자B",true,false,false)),listOf(mine,other),state="active")
    private val signal=TripSignal("signal","other",TripSignalKind.RESTROOM,SignalDestination("서산휴게소",36.0,126.0),
        "2026-11-13T00:00:00Z","valid",0,0,null,decisionRule="other-car-groups-v1",requesterCarId=other.id,
        canRespond=true,groupVotes=TripGroupVotes(0,0,1),groupResponses=listOf(TripGroupResponse(mine.id,mine.name,null)))
    private val pack=DrivePack("coast",1,"서해안 해안도로 코스","사용자A","바다를 따라 달리는 길",listOf(
        Stop("a","간월암",36.0,126.0,100f,""),Stop("b","꽃지해수욕장",36.1,126.1,100f,"")))
    private val published=PublishedPack(pack.id,pack.version,pack.title,pack.author,pack.description,pack.stops.size,"")
    private val course=WegoState(setupAllowed=true,storageReady=true,packs=listOf(pack),selectedKey=pack.key,
        accountCourses=AccountCourseState(AccountCourseStatus.READY,listOf(AccountCourse(published,true))),
        courseResult=CourseDrivingResult(1,1,60_000,completed=true))
    private val saved=TripSavedPlaylist("song","주말 드라이브","https://example.test/music","me","사용자A","approved")
    private val source=TripMusicSourceItem(TripSavedPlaylistSource("list",1,"track"),"새벽 고속도로","멜론")
    private val music=TripMusicState(status=TripMusicStatus.READY,collection=TripMusicCollection(trip.id,listOf(saved),200,true),
        sourceStatus=TripMusicStatus.READY,sources=listOf(source))
    private val time=Instant.parse("2026-11-13T00:00:00Z")
    private val review=SocialReview("history",SocialReview.State.PRIVATE,false)
    private fun historySummary(ended: Instant?)=SocialHistorySummary("history","저장한 서해안 여행","me","사용자A",true,time,time,time,ended,
        "coast",1,1,review,1,0)
    private val record=historySummary(time.plusSeconds(600))
    private val provenance=SocialHistorySource("user-report","me",time)
    private val history=SocialHistoryDetail(record,listOf(SocialHistoryVisit("visit",SocialSelectedPlace("간월암",36.0,126.0),time,
        "private",null,provenance)),emptyList(),provenance,SocialCourse("coast",1,pack.title))
    private val missions=listOf(BusinessLine("함께 장소 방문","진행 중\n다음 간월암"))
    private val pendingVersus=TripDrivingVersus("safe-driving-versus",true,"pending","final-reports-pending",listOf(
        TripDrivingVersusCar(mine.id,mine.name,true,"ready",90.0,1,listOf(TripDrivingVersusCourse("coast",1,"final",90))),
        TripDrivingVersusCar(other.id,other.name,true,"pending",null,0,listOf(TripDrivingVersusCourse("coast",1,"pending",null)))
    ),emptyList(),false)
    private val cautions=listOf(BusinessLine("서산 나들목 진입로","공사\n2026.11.13 (금)\n내 기록"))

    override fun setUp() {
        super.setUp()
        host=instrumentation.startActivitySync(Intent(instrumentation.targetContext,SafFrameworkHarnessActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_MULTIPLE_TASK)) as SafFrameworkHarnessActivity
    }
    override fun tearDown() {
        try {instrumentation.runOnMainSync {host.setContent {};host.finish()}}finally {super.tearDown()}
    }
    private fun texts()=nodes().flatMap {node->
        node.config.getOrNull(SemanticsProperties.Text).orEmpty().map {it.text}+
            node.config.getOrNull(SemanticsProperties.ContentDescription).orEmpty()
    }
    private fun has(text: String)=texts().any {it.contains(text)}
    private fun disabled(label: String)=control(label).config.contains(SemanticsProperties.Disabled)
    private fun snapshot(name: String) {
        settle()
        val source=requireNotNull(instrumentation.uiAutomation.takeScreenshot())
        val crop=Bitmap.createBitmap(source,frame.left,frame.top,frame.width(),frame.height())
        val folder=File(host.cacheDir,"vehicle-activity-details").apply {mkdirs()}
        File(folder,"$name.png").outputStream().use {crop.compress(Bitmap.CompressFormat.PNG,100,it)}
        crop.recycle();source.recycle()
    }
    private fun musicScene(enabled: Boolean=true,onAdd: (TripMusicSourceItem)->Unit={},onOpen: (TripSavedPlaylist)->Unit={}): @Composable ()->Unit = {
        TripSurface {Box(Modifier.fillMaxSize().padding(CarTokens.Frame)) {
            TripMusicPage(trip.title,music,enabled,{},{},{},onAdd,onOpen,{},djName="사용자C")
        }}
    }
    private fun courseScene(value: WegoState=course,onNavigate: ()->Unit={},onAdd: (PublishedPack)->Unit={},
        onJourney: ()->Unit={}): @Composable ()->Unit = {
        VehicleCourseDetailPage(value,0,{},{onNavigate()},onJourney,{},{},{},onAdd)
    }

    fun testActivityDetailsFitEveryPresetAndOmitUnsupportedFacts() {
        for((width,height) in presets) {
            render(width,height,false,entry=false,content=musicScene())
            assertTrue(has("DJ 사용자C"));assertTrue(has(saved.title));snapshot("music-${width}x$height")
            render(width,height,false,entry=false) {BusinessActivityDetail(BusinessSection.MISSIONS,missions,"",true,true,{},{},pendingVersus)}
            assertTrue(has("함께 장소 방문"));assertTrue(has("집계 중"));assertTrue(has("점수 전송 대기"))
            assertFalse(has("승리"));assertFalse(has("100점"));snapshot("missions-${width}x$height")
            render(width,height,false,entry=false) {
                TripGroupSignalStatusPage(trip,signal.copy(inProgress=false,resolution="agreed",canRespond=false,
                    groupResponses=listOf(TripGroupResponse(mine.id,mine.name,"agree","me","사용자A"))),TripSignalState(),TripUiActions(),{})
            }
            assertTrue(has("사용자A님이 답했어요"));assertFalse(has("iPhone에서"));snapshot("signal-result-${width}x$height")
            render(width,height,false,entry=false) {NativeHistoryRecord(record,history,"",Modifier.fillMaxSize(),{})}
            assertTrue(has("사용자가 보고한 방문 기록"));assertTrue(has("10분"));assertTrue(has("여행 시간"))
            assertFalse(has("km"));assertFalse(has("점"));assertFalse(has("손들기로 추가"))
            snapshot("history-detail-${width}x$height")
            render(width,height,false,entry=false,content=courseScene())
            assertTrue(has(pack.title));assertTrue(has("90점"));assertFalse(has("별표"));snapshot("course-detail-${width}x$height")
            render(width,height,false,entry=false) {CautionActivityList(cautions,"현재 도로 상태 미확인",true,Modifier.fillMaxSize(),{})}
            assertTrue(has("서산 나들목 진입로"));assertTrue(has("내 기록"));snapshot("cautions-${width}x$height")
        }
    }

    fun testHistoryDurationUsesOnlyCompleteOrderedTimestamps() {
        for((width,height) in presets) {
            render(width,height,false,entry=false) {NativeHistoryRecord(record,history,"",Modifier.fillMaxSize(),{})}
            assertTrue(has("10분"));assertTrue(has("여행 시간"));assertFalse(has("운전 시간"))
            snapshot("history-duration-${width}x$height")
        }
        for(ended in listOf(null,time.minusSeconds(1))) {
            val summary=historySummary(ended)
            val detail=SocialHistoryDetail(summary,history.visits,history.traces,provenance,history.course)
            render(648,800,false,entry=false) {NativeHistoryRecord(summary,detail,"",Modifier.fillMaxSize(),{})}
            assertFalse(has("여행 시간"));assertFalse(has("10분"));assertFalse(has("0초"))
        }
        render(648,800,false,entry=false) {NativeHistoryRecord(historySummary(null),null,"기록을 불러오는 중입니다",Modifier.fillMaxSize(),{})}
        assertFalse(has("여행 시간"));assertFalse(has("0초"))
    }

    fun testInactiveMissionStateFitsBothPanelLayoutsWithoutShowingCachedRecords() {
        for((width,height) in listOf(1700 to 1184,648 to 800)) {
            render(width,height,false,entry=false) {BusinessActivityDetail(BusinessSection.MISSIONS,missions,"",false,true,{},{},pendingVersus)}
            assertTrue(has("P단에서 이용할 수 있어요"));assertFalse(has("함께 장소 방문"))
            assertFalse(has("평균 90점"));assertFalse(has("점수 전송 대기"))
            assertFalse(nodes().any {it.config.contains(SemanticsActions.OnClick) &&
                it.config.getOrNull(SemanticsProperties.ContentDescription)?.contains("새로고침")==true})
            snapshot("missions-inactive-${width}x$height")
        }
    }

    fun testDrivingVersusUsesServerFinalTieAndKeepsUnavailableDistinctFromMissingReports() {
        val final=pendingVersus.copy(state="final",reason=null,cars=pendingVersus.cars.map {car->
            car.copy(state="ready",averageScore=90.0,measuredCourseCount=1,
                courses=listOf(TripDrivingVersusCourse("coast",1,"final",90)))
        },winnerCarIds=listOf(mine.id,other.id),tied=true)
        for((width,height) in listOf(1700 to 1184,648 to 800)) {
            var refreshes=0
            render(width,height,false,entry=false) {
                BusinessActivityDetail(BusinessSection.MISSIONS,emptyList(),"",true,true,{},{refreshes++},final)
            }
            assertTrue(has("결과 확정"));assertTrue(has("공동 1위"));assertTrue(has("평균 90점"))
            assertFalse(has("미션 시작"));assertFalse(has("참여 동의"));assertFalse(has("100점"))
            snapshot("versus-final-tie-${width}x$height")
            if(width==1700) {tap("대결 새로고침");assertEquals(1,refreshes)}
            val hidden=final.copy(state="unavailable",reason="sharing-unavailable",winnerCarIds=emptyList(),tied=false,
                cars=final.cars.map {car->car.copy(state="sharing-unavailable",averageScore=null,measuredCourseCount=0,
                    courses=car.courses.map {it.copy(state="sharing-unavailable",score=null)})})
            render(width,height,false,entry=false) {
                BusinessActivityDetail(BusinessSection.MISSIONS,emptyList(),"",true,true,{},{},hidden)
            }
            assertTrue(has("비교 불가"));assertTrue(has("공유 상태 확인 필요"))
            assertFalse(has("평균 90점"));assertFalse(has("공동 1위"));assertFalse(has("90점"))
            snapshot("versus-sharing-unavailable-${width}x$height")
            val missing=pendingVersus.copy(cars=pendingVersus.cars.map {car->car.copy(state="pending",averageScore=null,measuredCourseCount=0,
                courses=car.courses.map {it.copy(state="pending",score=null)})})
            render(width,height,false,entry=false) {
                BusinessActivityDetail(BusinessSection.MISSIONS,emptyList(),"",true,true,{},{},missing)
            }
            assertTrue(has("집계 중"));assertTrue(has("점수 전송 대기"));assertFalse(has("측정 불가"))
            val unavailable=missing.copy(state="unavailable",reason="insufficient-measurements",cars=missing.cars.map {car->
                car.copy(state="unavailable",courses=car.courses.map {it.copy(state="unavailable")})
            })
            render(width,height,false,entry=false) {
                BusinessActivityDetail(BusinessSection.MISSIONS,emptyList(),"",true,true,{},{},unavailable)
            }
            assertTrue(has("측정 불가"));assertFalse(has("점수 전송 대기"));assertFalse(has("승리"))
        }
    }

    fun testCompletedTripShowsSuppliedComparisonWithoutAnArchiveOrInventedWinner() {
        val completed=trip.copy(state="completed",routeContractVersion=2)
        render(1700,1184,false,entry=false) {
            TripResultPage(completed,{},drivingVersus=pendingVersus) {TripText("여행 기록")}
        }
        assertTrue(has("안전운전 대결"));assertTrue(has("집계 중"));assertTrue(has("평균 90점"))
        assertFalse(has("승리"));assertFalse(has("100점"));assertFalse(has("참여 동의"))
        snapshot("completed-versus-pending")
        render(648,800,false,entry=false) {
            TripResultPage(completed,{},drivingVersus=null,drivingVersusNotice="연결을 확인한 뒤 다시 시도하세요") {TripText("여행 기록")}
        }
        assertTrue(has("연결을 확인한 뒤 다시 시도하세요"));assertFalse(has("평균 90점"));assertFalse(has("승리"))
        snapshot("completed-versus-unavailable")
    }

    fun testDisabledAndMissingAuthorityKeepActionsAndCachedRowsUnavailable() {
        var added=0;var opened=0;var navigated=0
        render(1700,1184,false,entry=false,content=musicScene(false,{added++},{opened++}))
        assertTrue(disabled("${saved.title} 링크 열기"));assertTrue(disabled("${source.title} 여행에 추가"))
        assertEquals(0,added);assertEquals(0,opened)
        render(1700,1184,false,entry=false,content=courseScene(onNavigate={navigated++},onAdd={added++}))
        tap("여행에 추가");tap("간월암 길 안내")
        assertEquals(1,added);assertEquals(1,navigated)
        render(1700,1184,false,entry=false,content=courseScene(course.copy(courseResult=null,accountCourses=course.accountCourses.copy(isCurrent=false),
            packs=listOf(pack.copy(source=CoursesRepository.SOURCE)))))
        assertFalse(has("90점"));assertFalse(has("100점"));assertFalse(has("여행에 추가"));assertTrue(disabled("간월암 길 안내"))
        assertTrue(disabled("도착 알림"))
        var stopped=0
        render(1700,1184,false,entry=false,content=courseScene(course.copy(active=true,
            accountCourses=course.accountCourses.copy(isCurrent=false),packs=listOf(pack.copy(source=CoursesRepository.SOURCE))),
            onJourney={stopped++}))
        assertTrue(disabled("간월암 길 안내"));assertFalse(disabled("종료"))
        tap("종료");assertEquals(1,stopped)
        render(1700,1184,false,entry=false) {BusinessActivityDetail(BusinessSection.MISSIONS,missions,"",false,true,{},{})}
        assertFalse(has("함께 장소 방문"))
        render(1700,1184,false,entry=false) {CautionActivityList(cautions,"",false,Modifier.fillMaxSize(),{})}
        assertFalse(has("서산 나들목 진입로"))
        val votes=mutableListOf<String>()
        render(1700,1184,false,entry=false) {TripGroupSignalStatusPage(trip,signal,TripSignalState(),TripUiActions(voteOngoingSignal={votes+=it}),{})}
        tap("다음에");assertEquals(listOf("pass"),votes)
        render(1700,1184,false,entry=false) {TripGroupSignalStatusPage(trip,signal.copy(canRespond=false),TripSignalState(),TripUiActions(voteOngoingSignal={votes+=it}),{})}
        assertFalse(nodes().any {it.config.contains(SemanticsActions.OnClick) && it.config.getOrNull(SemanticsProperties.ContentDescription)?.contains("동의")==true})
        assertEquals(listOf("pass"),votes)
    }
}
