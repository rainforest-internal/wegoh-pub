package io.wegoh.app

import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Rect
import android.os.SystemClock
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.semantics.*
import io.wegoh.app.ui.*
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import junit.framework.AssertionFailedError

@Suppress("DEPRECATION")
class VehicleCourseFeedUiTest: EntryDesignTestCase() {
    private val coast=VehicleCourseFeedCard("coast/1","바다와 호수 드라이브","사용자A",3,
        "간월암 → 간월호 → 대천",listOf("바다","호수"),12,isNew=true)
    private val beach=VehicleCourseFeedCard("beach/1","바다 산책 코스","사용자E",2,
        "만리포 → 꽃지",listOf("바다"),2)
    private val lake=VehicleCourseFeedCard("lake/2","호수 한 바퀴","사용자B",1,"간월호",listOf("호수"))
    private val ready=VehicleCourseFeedState(status=AccountReadStatus.READY,courses=listOf(coast,beach,lake),
        availableTags=listOf("바다","호수"),unreadCount=2,followingNames=listOf("사용자A","사용자B"))
    private var scene=0
    @Volatile private var laidOutScene=0
    @Volatile private var drawnScene=0
    private var sceneDescription="not rendered"

    override fun setUp() {
        super.setUp()
        host=instrumentation.startActivitySync(Intent(instrumentation.targetContext,SafFrameworkHarnessActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_MULTIPLE_TASK)) as SafFrameworkHarnessActivity
    }
    override fun tearDown() {
        try {instrumentation.runOnMainSync {host.setContent {};host.finish()}}finally {super.tearDown()}
    }
    private fun show(width: Int=1700,height: Int=1184,night: Boolean=false,content: @Composable ()->Unit) {
        val version=++scene
        val laidOut=CountDownLatch(1)
        val drawn=CountDownLatch(1)
        sceneDescription="scene=$version width=$width height=$height night=$night"
        render(width,height,night,entry=false) {
            TripLayoutRoot(Modifier.fillMaxSize().background(LocalCarPalette.current.background)
                .onGloballyPositioned {laidOutScene=version;laidOut.countDown()}.drawWithContent {
                    drawContent();drawnScene=version;drawn.countDown()
                }) {content()}
        }
        if(!laidOut.await(5,TimeUnit.SECONDS) || !drawn.await(5,TimeUnit.SECONDS) || laidOutScene!=version || drawnScene!=version)
            failure("Exact scene must lay out and draw; layout=$laidOutScene draw=$drawnScene")
        settle()
    }
    private fun values()=nodes().flatMap {it.config.getOrNull(SemanticsProperties.Text).orEmpty()}.map {it.text}
    private fun has(text: String)=values().any {it==text}
    private fun action(label: String)=nodes().singleOrNull {
        it.config.contains(SemanticsActions.OnClick) && it.config.getOrNull(SemanticsProperties.ContentDescription)==listOf(label)
    }
    private fun scroll(amount: Float) {
        val scroller=nodes().firstOrNull {it.config.getOrNull(SemanticsActions.ScrollBy)?.action!=null}
        val scroll=scroller?.config?.getOrNull(SemanticsActions.ScrollBy)?.action
        assertNotNull("Feed must have a reachable scroll container",scroll)
        instrumentation.runOnMainSync {requireNotNull(scroll).invoke(0f,amount)}
        settle()
        val range=scroller?.config?.getOrNull(SemanticsProperties.VerticalScrollAxisRange) ?: return
        val deadline=SystemClock.uptimeMillis()+5000
        var previous=Float.NaN
        var stableFrames=0
        while(SystemClock.uptimeMillis()<deadline) {
            var value=Float.NaN
            instrumentation.runOnMainSync {value=range.value()}
            stableFrames=if(value==previous)stableFrames+1 else 0
            if(stableFrames>=2)return
            previous=value
            settle()
        }
        failure("Feed scroll must settle before reading action bounds")
    }
    private fun reveal(label: String) {
        repeat(32) {
            val control=action(label)
            if(control!=null) {
                val visible=bounds(control)
                if(!visible.isEmpty && frame.contains(visible) && visible.width()+1>=control.size.width &&
                    visible.height()+1>=control.size.height && visible.height()+1>=CarTokens.Touch.value*scale)return
                var direction=1f
                instrumentation.runOnMainSync {
                    val origin=IntArray(2);host.window.decorView.getLocationOnScreen(origin)
                    if(control.positionInWindow.y+origin[1]<frame.top)direction=-1f
                }
                scroll(direction*frame.height()/3f)
            } else scroll(frame.height()/3f)
        }
        failure("Feed action must become fully visible and at least 80dp: $label; bounds=${action(label)?.let(::bounds)}")
    }
    private fun top()=repeat(8) {scroll(-frame.height().toFloat())}
    private fun click(label: String) {
        reveal(label)
        val control=checkNotNull(action(label))
        assertFalse("Enabled action: $label",control.config.contains(SemanticsProperties.Disabled))
        assertTrue("80dp action: $label",bounds(control).height()+1>=CarTokens.Touch.value*scale)
        var handled=false
        instrumentation.runOnMainSync {handled=control.config.getOrNull(SemanticsActions.OnClick)?.action?.invoke()==true}
        assertTrue("Action handled: $label",handled)
        settle()
    }
    private fun snapshot(name: String) {
        settle()
        val screen=requireNotNull(instrumentation.uiAutomation.takeScreenshot())
        val crop=Bitmap.createBitmap(screen,frame.left,frame.top,frame.width(),frame.height())
        val folder=File(host.cacheDir,"course-feed").apply {mkdirs()}
        try {File(folder,"$name.png").outputStream().use {crop.compress(Bitmap.CompressFormat.PNG,100,it)}}
        finally {crop.recycle();screen.recycle()}
    }
    private fun failure(message: String): Nothing {
        val capture=runCatching {
            val screen=requireNotNull(instrumentation.uiAutomation.takeScreenshot())
            val folder=File(host.cacheDir,"course-feed").apply {mkdirs()}
            val stem="failure-scene-$scene"
            val full=File(folder,"$stem-full.png")
            try {
                full.outputStream().use {screen.compress(Bitmap.CompressFormat.PNG,100,it)}
                if(!frame.isEmpty && Rect(0,0,screen.width,screen.height).contains(frame)) {
                    val crop=Bitmap.createBitmap(screen,frame.left,frame.top,frame.width(),frame.height())
                    try {File(folder,"$stem-crop.png").outputStream().use {crop.compress(Bitmap.CompressFormat.PNG,100,it)}}
                    finally {crop.recycle()}
                }
            } finally {screen.recycle()}
            full.absolutePath
        }.getOrElse {"unavailable:${it.javaClass.simpleName}"}
        throw AssertionFailedError("$message; $sceneDescription frame=$frame scale=$scale screenshot=$capture")
    }
    private fun assertVisibleTouch(label: String) {
        val node=action(label) ?: failure("Expected action is missing: $label")
        val visible=bounds(node)
        if(visible.isEmpty || !frame.contains(visible) || visible.width()+1<node.size.width || visible.height()+1<node.size.height)
            failure("Action must be fully inside the current scene: $label; bounds=$visible actual=${node.size}")
        if(visible.height()+1<CarTokens.Touch.value*scale)
            failure("Action must retain its 80dp minimum: $label; bounds=$visible actual=${node.size} minimum=${CarTokens.Touch.value*scale}")
    }
    fun testFourTabsAndEverySelectedTagUseTheSuppliedLists() {
        val feed=mutableStateOf(ready)
        val opened=mutableListOf<String>();val added=mutableListOf<String>()
        show {
            VehicleCourseFeed(feed.value,onTab={tab->feed.value=ready.copy(tab=tab,courses=when(tab) {
                VehicleCourseFeedTab.RECOMMENDED->ready.courses
                VehicleCourseFeedTab.SUBSCRIPTIONS->listOf(coast)
                VehicleCourseFeedTab.MINE->listOf(lake)
                VehicleCourseFeedTab.SAVED->listOf(beach)
            })},onTag={tag->feed.value=feed.value.copy(selectedTags=if(tag==null)emptySet()
                else if(tag in feed.value.selectedTags)feed.value.selectedTags-tag else feed.value.selectedTags+tag)},
                onRetry={},onConnection={},onOpen={opened+=it},onAdd={added+=it})
        }
        assertTrue(action("추천")?.config?.getOrNull(SemanticsProperties.Selected)==true)
        assertTrue(has(coast.title));assertTrue(has(beach.title));assertTrue(has(lake.title))
        click("#바다")
        assertEquals(listOf(coast.key,beach.key),vehicleCourseFeedCards(feed.value).map {it.key})
        assertTrue(has(coast.title));assertTrue(has(beach.title));assertFalse(has(lake.title))
        click("#호수")
        assertEquals(listOf(coast.key),vehicleCourseFeedCards(feed.value).map {it.key})
        assertTrue(action("#바다")?.config?.getOrNull(SemanticsProperties.Selected)==true)
        assertTrue(action("#호수")?.config?.getOrNull(SemanticsProperties.Selected)==true)
        assertTrue(has(coast.title));assertFalse(has(beach.title));assertFalse(has(lake.title))
        click("${coast.title} 경로 보기");click("${coast.title} 여행에 추가")
        assertEquals(listOf(coast.key),opened);assertEquals(listOf(coast.key),added)
        top();click("전체")
        assertTrue(feed.value.selectedTags.isEmpty())
        click("구독, 새 경로 2개")
        assertTrue(action("구독, 새 경로 2개")?.config?.getOrNull(SemanticsProperties.Selected)==true)
        assertTrue(has("구독한 창작자"));assertTrue(has(coast.title));assertFalse(has(beach.title))
        snapshot("subscriptions-wide")
        top();click("내 경로")
        assertTrue(has(lake.title));assertFalse(has(coast.title))
        top();click("저장한 경로")
        assertTrue(has(beach.title));assertFalse(has(lake.title))
        assertNull(action("구독하기"));assertNull(action("저장"));assertNull(action("별표 추가"))
    }
    fun testConnectionFailureLoadingAndStaleActionsRemainDistinct() {
        var retries=0;var connections=0;var opens=0;var adds=0
        fun content(value: VehicleCourseFeedState): @Composable ()->Unit = {
            VehicleCourseFeed(value,{},{},{retries++},{connections++},{opens++},{adds++})
        }
        show(content=content(ready.copy(status=AccountReadStatus.CONNECTION_REQUIRED)))
        assertTrue(has("차량을 연결해 주세요"));assertFalse(has(coast.title));click("차량 연결")
        show(content=content(ready.copy(status=AccountReadStatus.PERMISSION_REQUIRED)))
        assertTrue(has("경로 공유를 허용해 주세요"));assertFalse(has(coast.title));click("차량 연결")
        show(content=content(ready.copy(status=AccountReadStatus.LOADING)))
        assertTrue(has("경로를 불러오는 중"));assertFalse(has(coast.title))
        assertNull("새로고침은 공통 탭 헤더 한 곳에서 제공해요",action("새로고침"))
        show(content=content(ready.copy(status=AccountReadStatus.UNAVAILABLE)))
        assertTrue(has("경로를 불러오지 못했어요"));assertFalse(has(coast.title));click("다시 불러오기")
        show(content=content(ready.copy(courses=listOf(coast),isCurrent=false)))
        assertTrue(has("경로를 다시 불러와 주세요"))
        reveal("${coast.title} 경로 보기")
        assertTrue(action("${coast.title} 경로 보기")?.config?.contains(SemanticsProperties.Disabled)==true)
        reveal("${coast.title} 여행에 추가")
        assertTrue(action("${coast.title} 여행에 추가")?.config?.contains(SemanticsProperties.Disabled)==true)
        assertEquals(2,connections);assertEquals(1,retries);assertEquals(0,opens);assertEquals(0,adds)
    }
    fun testNarrowAndWideFeedHasReachableActionsAndDoesNotInventMetadata() {
        for((width,height) in presets)for(night in listOf(false,true)) {
            show(width,height,night) {
                VehicleCourseFeed(ready.copy(courses=listOf(lake),unreadCount=null,followingNames=emptyList()),{},{},{},{},{},{})
            }
            assertTrue(action("구독")!=null);assertNull(action("구독, 새 경로 2개"))
            reveal("${lake.title} 경로 보기")
            assertVisibleTouch("${lake.title} 경로 보기")
            reveal("${lake.title} 여행에 추가")
            assertVisibleTouch("${lake.title} 여행에 추가")
            assertFalse(values().any {it.startsWith("별표 ") || it.contains("구독자 ") || it.contains("km")})
            snapshot("feed-${width}x$height-${if(night)"night" else "day"}")
        }
        for(tab in VehicleCourseFeedTab.entries) {
            show {VehicleCourseFeed(ready.copy(tab=tab,courses=emptyList()),{},{},{},{},{},{})}
            assertTrue(has(when(tab) {
                VehicleCourseFeedTab.RECOMMENDED->"추천 경로가 없어요"
                VehicleCourseFeedTab.SUBSCRIPTIONS->"새 경로가 없어요"
                VehicleCourseFeedTab.MINE->"내가 만든 경로가 없어요"
                VehicleCourseFeedTab.SAVED->"저장한 경로가 없어요"
            }))
        }
        assertEquals(listOf(coast.key),vehicleCourseFeedCards(ready.copy(selectedTags=setOf(" #바다 ","#호수"))).map {it.key})
    }
    fun testPublicOpenRequiresVerifiedSelectionInsteadOfAnExistingLocalKey() {
        val published=PublishedPack("public-coast",1,"공개 해안 코스","사용자A","공개 장소",1,"a".repeat(64))
        val summary=CourseLibraryItem(published,emptyList(),false,0,null,null,false,false,null,List(published.stopCount) {"장소 ${it+1}"})
        val library=CourseLibrary(listOf(summary),emptyList(),emptyList(),emptyList(),emptyList(),emptyList(),0)
        val local=DrivePack(published.id,published.version,"다른 로컬 코스","로컬","직접 가져온 장소",
            listOf(Stop("local-place","다른 장소",35.0,128.0,100f,"")))
        val state=mutableStateOf(WegoState(setupAllowed=true,storageReady=true,packs=listOf(local),
            accountCourses=AccountCourseState(AccountCourseStatus.READY),
            accountDiscovery=AccountDiscoveryState(AccountReadStatus.READY,listOf(published),library=library)))
        val downloads=mutableListOf<PublishedPack>();val selected=mutableListOf<String>()
        show {
            VehicleCoursesPage(state.value,{},{},{selected+=it},{},{downloads+=it},{},{})
        }
        click("${published.title} 경로 보기")
        assertEquals(listOf(published),downloads)
        assertTrue("A matching local id/version is not public verification",selected.isEmpty())
        instrumentation.runOnMainSync {
            state.value=state.value.copy(accountDiscovery=state.value.accountDiscovery.copy(
                verifiedSelection=published.copy(checksum="b".repeat(64))))
        }
        settle()
        assertTrue("A different checksum cannot open the public course",selected.isEmpty())
        click("${published.title} 경로 보기")
        val verified=DrivePack(published.id,published.version,published.title,published.author,published.description,
            listOf(Stop("public-place","공개 장소",36.3,126.5,100f,"")),source="공개 경로")
        instrumentation.runOnMainSync {
            state.value=state.value.copy(packs=listOf(verified),accountDiscovery=state.value.accountDiscovery.copy(
                verifiedSelection=published))
        }
        settle()
        assertEquals(listOf(published.key),selected)
        assertEquals(listOf(published,published),downloads)
    }
    fun testPendingPublicOpenIsDiscardedWhenItsVersionLeavesTheCurrentLibrary() {
        val published=PublishedPack("public-coast",1,"공개 해안 코스","사용자A","공개 장소",1,"a".repeat(64))
        val summary=CourseLibraryItem(published,emptyList(),false,0,null,null,false,false,null,List(published.stopCount) {"장소 ${it+1}"})
        val library=CourseLibrary(listOf(summary),emptyList(),emptyList(),emptyList(),emptyList(),emptyList(),0)
        val local=DrivePack(published.id,published.version,"다른 로컬 코스","로컬","직접 가져온 장소",
            listOf(Stop("local-place","다른 장소",35.0,128.0,100f,"")))
        val state=mutableStateOf(WegoState(setupAllowed=true,storageReady=true,packs=listOf(local),
            accountCourses=AccountCourseState(AccountCourseStatus.READY),
            accountDiscovery=AccountDiscoveryState(AccountReadStatus.READY,listOf(published),library=library)))
        val selected=mutableListOf<String>();var downloads=0
        show {VehicleCoursesPage(state.value,{},{},{selected+=it},{},{downloads++},{},{})}
        click("${published.title} 경로 보기")
        assertEquals(1,downloads);assertTrue(selected.isEmpty())
        instrumentation.runOnMainSync {
            state.value=state.value.copy(packs=listOf(local.copy(description="로컬 목록 갱신")),
                accountDiscovery=state.value.accountDiscovery.copy(packs=emptyList(),library=library.copy(public=emptyList()),
                    verifiedSelection=null))
        }
        settle()
        assertTrue("Two absent proofs cannot authorize a local key",selected.isEmpty())
        instrumentation.runOnMainSync {
            state.value=state.value.copy(accountDiscovery=state.value.accountDiscovery.copy(verifiedSelection=published))
        }
        settle()
        assertTrue("A late verification cannot reopen a removed version",selected.isEmpty())
    }
}
