package io.wegoh.app

import android.content.Intent
import android.content.res.Configuration
import android.graphics.Bitmap
import android.graphics.Rect
import android.test.InstrumentationTestCase
import android.view.View
import android.view.ViewGroup
import android.view.inspector.WindowInspector
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
import androidx.compose.ui.platform.ViewRootForTest
import androidx.compose.ui.semantics.*
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import io.wegoh.app.nativeauth.*
import io.wegoh.app.ui.*
import java.io.Closeable
import java.io.File
import kotlin.math.min
import kotlin.math.roundToInt

@Suppress("DEPRECATION")
class TripMusicUiTest: InstrumentationTestCase() {
    private lateinit var activity: TripScreensPreviewActivity
    private lateinit var windows: CarWindowVisibility
    private lateinit var repository: TripMusicRepository
    private var frame=Rect()
    private var entered=0
    private var opened=0
    private val tripId="a".repeat(32)
    private val account="team-"+"a".repeat(40)
    private val fake=Gateway()
    private fun trip(): TripDetail {
        val car="c".repeat(32)
        return TripDetail(tripId,"강릉 바다 여행","",listOf(TripMember(account,"사용자A",true,true,true,car)),
            listOf(TripCar(car,"사용자A 차",account,"사용자A",4,true,false,emptyList(),emptyList())),state="active",revision=1,
            courses=listOf(TripCourse("sea","바다 한 바퀴",1,1,"사용자A",true,true,emptyList(),listOf(TripCourseStop("beach","경포해변",37.8,128.9)))))
    }
    override fun setUp() {
        super.setUp()
        activity=instrumentation.startActivitySync(Intent(instrumentation.targetContext,TripScreensPreviewActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_MULTIPLE_TASK)) as TripScreensPreviewActivity
        instrumentation.runOnMainSync {
            windows=CarWindowVisibility(activity) {}
            WindowCompat.setDecorFitsSystemWindows(activity.window,false)
            WindowCompat.getInsetsController(activity.window,activity.window.decorView).hide(WindowInsetsCompat.Type.systemBars())
            repository=TripMusicRepository(tripId) {fake}
        }
    }
    override fun tearDown() {
        try {instrumentation.runOnMainSync {activity.setContent {};repository.close();windows.close();activity.finish()}}
        finally {super.tearDown()}
    }
    private fun render(entry: Boolean=true,width: Int=1704) {
        val trip=trip()
        val page=TripsPageState(AccountReadStatus.READY,TripList(listOf(TripSummary(tripId,trip.title,true,"사용자A",1,1,state="active")),emptyList()),
            tripId,trip,isCurrent=true,gear=TripGear.PARK)
        instrumentation.runOnMainSync {activity.setContent {
            BoxWithConstraints(Modifier.fillMaxSize().background(Color.Black),contentAlignment=Alignment.Center) {
                val scale=min(constraints.maxWidth.toFloat()/width,constraints.maxHeight.toFloat()/1208)
                val configuration=Configuration(LocalConfiguration.current).apply {screenWidthDp=width;screenHeightDp=1208;smallestScreenWidthDp=min(width,1208);fontScale=1f}
                CompositionLocalProvider(LocalDensity provides Density(scale,1f),LocalConfiguration provides configuration) {
                    Box(Modifier.requiredSize(width.dp,1208.dp).onGloballyPositioned {
                        val r=it.boundsInWindow();val origin=IntArray(2);activity.window.decorView.getLocationOnScreen(origin)
                        frame=Rect(r.left.roundToInt()+origin[0],r.top.roundToInt()+origin[1],r.right.roundToInt()+origin[0],r.bottom.roundToInt()+origin[1])
                    }) {ProvideCarWindowVisibility(windows) {WegoCarTheme {
                        if(entry)WegoVehicleScreen(WegoState(setupAllowed=true,storageReady=true),{},{},{},{},{},{},{},{},{},
                            tripsState=page,tripMusic={_,allowed,back->entered++;TripMusicBoundPage(repository,trip.title,allowed,back,{}, {opened++;TripMusicOpen.FAILED})})
                        else TripSurface {TripMusicBoundPage(repository,trip.title,true,{},{},{opened++;TripMusicOpen.FAILED})}
                    }}}
                }
            }
        }}
        settle()
    }
    private fun settle(){instrumentation.waitForIdleSync();Thread.sleep(100);instrumentation.waitForIdleSync()}
    private fun allNodes(): List<androidx.compose.ui.semantics.SemanticsNode> {
        val found=mutableListOf<androidx.compose.ui.semantics.SemanticsNode>()
        fun inspect(view: View) {
            if(view is ViewRootForTest)found.addAll(view.semanticsOwner.getAllSemanticsNodes(mergingEnabled=false))
            if(view is ViewGroup)for(index in 0 until view.childCount)inspect(view.getChildAt(index))
        }
        WindowInspector.getGlobalWindowViews().forEach(::inspect)
        return found
    }
    private fun label(node: androidx.compose.ui.semantics.SemanticsNode)=
        node.config.getOrNull(SemanticsProperties.ContentDescription).orEmpty()+node.config.getOrNull(SemanticsProperties.Text).orEmpty().map {it.text}
    private fun has(text: String): Boolean {
        var found=false;instrumentation.runOnMainSync {found=allNodes().any {text in label(it)}};return found
    }
    private fun click(text: String,scroll: Boolean=false) {
        repeat(if(scroll)14 else 20) {
            var clicked=false
            instrumentation.runOnMainSync {
                val nodes=allNodes()
                val target=nodes.firstOrNull {text in label(it) && it.config.contains(SemanticsActions.OnClick) && !it.config.contains(SemanticsProperties.Disabled)}
                clicked=target?.config?.getOrNull(SemanticsActions.OnClick)?.action?.invoke()==true
                if(!clicked && scroll)nodes.firstOrNull {it.config.contains(SemanticsActions.ScrollBy) && it.config.contains(SemanticsProperties.VerticalScrollAxisRange)}
                    ?.config?.getOrNull(SemanticsActions.ScrollBy)?.action?.invoke(0f,800f)
            }
            settle();if(clicked)return
        }
        capture("failure-action");fail("Missing action: $text; sessions=${fake.opens}; source=${repository.state.sourceStatus}")
    }
    private fun disabled(text: String): Boolean {
        var disabled=false
        instrumentation.runOnMainSync {disabled=allNodes().first {text in label(it) && it.config.contains(SemanticsActions.OnClick)}.config.contains(SemanticsProperties.Disabled)}
        return disabled
    }
    private fun assertNoConfirmation() {
        assertFalse(has("여행에 추가할까요?"));assertFalse(has("동의하고 추가"))
        instrumentation.runOnMainSync {assertFalse(allNodes().any {it.config.getOrNull(SemanticsProperties.Role)==Role.Checkbox})}
    }
    private fun capture(name: String) {
        settle();val source=instrumentation.uiAutomation.takeScreenshot() ?: error("No screenshot")
        val bounds=Rect(frame);check(bounds.intersect(0,0,source.width,source.height))
        val image=Bitmap.createBitmap(source,bounds.left,bounds.top,bounds.width(),bounds.height())
        val directory=File(activity.filesDir,"trip-music-picker");check(directory.isDirectory || directory.mkdirs())
        File(directory,"$name.png").outputStream().use {check(image.compress(Bitmap.CompressFormat.PNG,100,it))}
        image.recycle();source.recycle()
    }
    fun testProductionTripEntryAddsOnlyAfterInformedConfirmationAndPreservesCollection() {
        render();capture("00-trip-entry");click("여행 음악",scroll=true)
        assertTrue("Production trip-detail navigation must invoke the music slot",entered>0)
        assertTrue(has("함께 가는 길"));capture("01-trip-playlists")
        click("내 음악에서 추가");assertTrue(has("바다 드라이브"));assertTrue(has("퇴근길 음악"));capture("02-my-music-picker")
        assertNoConfirmation();assertTrue(has("검토를 통과한 음악의 제목과 링크는 일행에게 공개돼요"));assertEquals(0,fake.writes)
        click("바다 드라이브 여행에 추가")
        assertEquals("Choosing a source must not grant sharing or review consent",0,fake.writes)
        assertTrue(has("제목과 링크를 일행과 공유하고 운영 검토를 요청해요."))
        assertTrue(has("공유할 권리가 있는 음악인지 확인해 주세요."));capture("03-add-confirmation")
        click("취소");assertNoConfirmation();assertEquals(0,fake.writes)
        click("바다 드라이브 여행에 추가");click("동의하고 추가")
        assertEquals(1,fake.writes);assertEquals(fake.source.source,fake.posted)
        assertNoConfirmation()
        assertTrue(has("함께 가는 길"));assertTrue(has("바다 드라이브"));assertTrue(has("검토 중"));assertTrue(has("나에게만 표시"))
        assertEquals(2,repository.state.collection?.items?.size);capture("04-added-to-trip")
        click("바다 드라이브 링크 열기");assertEquals(1,opened);assertTrue(has("음악 링크를 열지 못했어요"))
    }
    fun testRefreshingKeepsBothMusicPanesVisibleAndBlocksStaleActions() {
        render(entry=false)
        fake.deferRead=true
        instrumentation.runOnMainSync {repository.refresh()};settle()
        assertTrue(has("함께 가는 길"));assertTrue(has("새로고침 중"))
        assertTrue(disabled("함께 가는 길 링크 열기"))
        capture("08-trip-refresh-retained")
        instrumentation.runOnMainSync {fake.finishRead()};settle()
        instrumentation.runOnMainSync {repository.refresh()};settle()
        assertTrue(has("바다 드라이브"));assertTrue(has("퇴근길 음악"))
        assertTrue(disabled("바다 드라이브 여행에 추가"))
        capture("09-own-refresh-retained")
        instrumentation.runOnMainSync {fake.finishRead()};settle()
        assertFalse(disabled("바다 드라이브 여행에 추가"))
    }

    fun testAddingLocksDuplicateActionsAndFailureKeepsConfirmationForRetry() {
        fake.deferAdd=true
        render(entry=false)
        var oldAdd: (()->Boolean)?=null
        instrumentation.runOnMainSync {oldAdd=allNodes().first {"바다 드라이브 여행에 추가" in label(it)}.config.getOrNull(SemanticsActions.OnClick)?.action}
        click("바다 드라이브 여행에 추가")
        assertEquals(0,fake.writes);click("동의하고 추가")
        assertEquals(1,fake.writes);assertTrue(disabled("동의하고 추가"))
        assertTrue(disabled("바다 드라이브 여행에 추가"));assertTrue(disabled("퇴근길 음악 여행에 추가"))
        instrumentation.runOnMainSync {oldAdd?.invoke();oldAdd?.invoke()}
        assertEquals("A captured second click must not submit while adding",1,fake.writes);capture("03-adding-inline")
        instrumentation.runOnMainSync {fake.finishAdd(Result.failure(IllegalStateException()))};settle()
        assertTrue(has("추가하지 못했어요. 다시 시도해 주세요"));assertTrue(has("동의하고 추가"))
        assertFalse(disabled("바다 드라이브 여행에 추가"));assertFalse(disabled("퇴근길 음악 여행에 추가"));capture("07-add-error-inline")
        fake.deferAdd=false;click("동의하고 추가")
        assertEquals(2,fake.writes);assertEquals(2,repository.state.collection?.items?.size);assertTrue(has("검토 중"));assertTrue(has("나에게만 표시"))
    }
    fun testOwnEmptyAndReadFailureRetryKeepTripSeparate() {
        fake.own=emptyList();render(entry=false,width=800)
        click("내 음악에서 추가");assertTrue(has("저장한 음악이 없어요"));assertFalse(has("QR"));capture("05-own-empty")
        click("여행 음악");assertTrue(has("함께 가는 길"))
        instrumentation.runOnMainSync {fake.failRead=true;repository.refresh()};settle()
        assertTrue(has("여행 음악을 불러오지 못했어요"));capture("06-read-error")
        fake.failRead=false;click("다시 불러오기");assertTrue(has("함께 가는 길"))
    }
    fun testStaleActionsCannotWriteOrOpenAfterFocusLossOrWindowClosure() {
        render(entry=false)
        var oldOpen: (()->Boolean)?=null
        var oldAdd: (()->Boolean)?=null
        instrumentation.runOnMainSync {oldOpen=allNodes().first {"함께 가는 길 링크 열기" in label(it)}.config.getOrNull(SemanticsActions.OnClick)?.action}
        click("내 음악에서 추가")
        instrumentation.runOnMainSync {oldAdd=allNodes().first {"바다 드라이브 여행에 추가" in label(it)}.config.getOrNull(SemanticsActions.OnClick)?.action}
        lateinit var external: android.app.AlertDialog
        instrumentation.runOnMainSync {external=android.app.AlertDialog.Builder(activity).setMessage("다른 창 확인").create();external.show()};settle()
        assertFalse(windows.state.focused)
        instrumentation.runOnMainSync {oldOpen?.invoke();oldAdd?.invoke()}
        assertEquals(0,opened);assertEquals(0,fake.writes)
        instrumentation.runOnMainSync {external.dismiss()};settle()
        assertTrue(windows.state.focused);assertEquals(TripMusicStatus.READY,repository.state.sourceStatus)
        fake.deferAdd=true;click("바다 드라이브 여행에 추가");assertEquals(0,fake.writes)
        click("동의하고 추가");assertEquals(1,fake.writes)
        instrumentation.runOnMainSync {windows.close()};settle()
        assertFalse(windows.state.visible)
        assertNull("Hidden music must discard the trip collection",repository.state.collection)
        assertTrue("Hidden music must discard the personal source list",repository.state.sources.isEmpty())
        instrumentation.runOnMainSync {oldOpen?.invoke();oldAdd?.invoke();fake.finishAdd(Result.success(fake.addedCollection()))}
        assertEquals(0,opened);assertEquals(1,fake.writes);assertEquals(1,fake.cancelledAdds)
        assertNull(repository.state.collection);assertTrue(repository.state.sources.isEmpty())
    }
    fun testChangedSourceInvalidatesPendingConfirmationAndCapturedSubmit() {
        render(entry=false);click("바다 드라이브 여행에 추가")
        var oldConfirm: (()->Boolean)?=null
        instrumentation.runOnMainSync {
            oldConfirm=allNodes().first {"동의하고 추가" in label(it)}.config.getOrNull(SemanticsActions.OnClick)?.action
            fake.own=emptyList();repository.loadSources()
        }
        settle();assertNoConfirmation();assertTrue(has("저장한 음악이 없어요"))
        instrumentation.runOnMainSync {oldConfirm?.invoke()}
        assertEquals("A removed or revoked source must not be shared by an old confirmation",0,fake.writes)
    }
    fun testMusicBarDistinguishesSharedSelectionAndRejectsStaleMediaControls() {
        val mediaKeys=mutableListOf<Int>()
        var musicOpened=0
        val controls=mutableStateOf(true)
        val item=fake.collection.items.single()
        val state=TripMusicState(status=TripMusicStatus.READY,collection=fake.collection.copy(viewerId=account,
            nowPlaying=listOf(TripMusicPlayback(item.id,item.addedById,item.addedByName,"2026-11-14T00:00:00+00:00"))))
        instrumentation.runOnMainSync {activity.setContent {
            ProvideCarWindowVisibility(windows) {WegoCarTheme {
                TripMusicNowPlayingBar(state,controls.value,{musicOpened++},{},
                    onMediaKey={mediaKeys+=it;true})
            }}
        }}
        settle()
        assertTrue(has("최근 선택한 음악"));assertFalse(has("지금 재생 중"))
        assertTrue(has("사용자E님 추천 · 사용자E님 차에서 선택"));assertTrue(has("내 차 음악"))
        var oldNext: (()->Boolean)?=null
        var oldOpen: (()->Boolean)?=null
        instrumentation.runOnMainSync {
            oldNext=allNodes().first {"내 차 음악 다음 곡" in label(it)}.config.getOrNull(SemanticsActions.OnClick)?.action
            oldOpen=allNodes().first {"노래 듣기 열기" in label(it)}.config.getOrNull(SemanticsActions.OnClick)?.action
            oldNext?.invoke();oldOpen?.invoke()
        }
        assertEquals(listOf(android.view.KeyEvent.KEYCODE_MEDIA_NEXT),mediaKeys);assertEquals(1,musicOpened)
        lateinit var external: android.app.AlertDialog
        instrumentation.runOnMainSync {external=android.app.AlertDialog.Builder(activity).setMessage("다른 창 확인").create();external.show()};settle()
        assertFalse(windows.state.focused)
        instrumentation.runOnMainSync {oldNext?.invoke();oldOpen?.invoke()}
        assertEquals(1,mediaKeys.size);assertEquals(1,musicOpened)
        instrumentation.runOnMainSync {external.dismiss();controls.value=false};settle()
        instrumentation.runOnMainSync {oldNext?.invoke();oldOpen?.invoke()}
        assertEquals(1,mediaKeys.size);assertEquals(1,musicOpened)
        instrumentation.runOnMainSync {controls.value=true};settle()
        instrumentation.runOnMainSync {oldNext?.invoke();oldOpen?.invoke()}
        assertEquals(2,mediaKeys.size);assertEquals(2,musicOpened)
        instrumentation.runOnMainSync {windows.close()};settle()
        instrumentation.runOnMainSync {oldNext?.invoke();oldOpen?.invoke()}
        assertEquals(2,mediaKeys.size);assertEquals(2,musicOpened)
        instrumentation.runOnMainSync {activity.setContent {};oldNext?.invoke();oldOpen?.invoke()}
        assertEquals(2,mediaKeys.size);assertEquals(2,musicOpened)
    }
    private inner class Gateway: TripMusicGateway {
        var closed=false
        override val current get()=!closed
        var writes=0
        var opens=0
        var failRead=false
        var deferRead=false
        private var pendingRead: ((Result<TripMusicCollection>)->Unit)?=null
        fun finishRead(){val callback=pendingRead;pendingRead=null;callback?.invoke(Result.success(collection))}
        var deferAdd=false
        var cancelledAdds=0
        private var pendingAdd: ((Result<TripMusicCollection>)->Unit)?=null
        val source=TripMusicSourceItem(TripSavedPlaylistSource("b".repeat(32),7,"d".repeat(32)),"바다 드라이브","멜론")
        var own=listOf(source,TripMusicSourceItem(source.source.copy(trackId="e".repeat(32)),"퇴근길 음악","Spotify"))
        var posted: TripSavedPlaylistSource?=null
        var collection=TripMusicCollection(tripId,listOf(TripSavedPlaylist("1".repeat(32),"함께 가는 길","https://open.spotify.com/playlist/one",
            "team-"+"b".repeat(40),"사용자E","approved")),200,true)
        override fun open(observer: NativeSocialObserver,callback: (Result<Unit>)->Unit){closed=false;opens++;callback(Result.success(Unit))}
        override fun read(callback: (Result<TripMusicCollection>)->Unit): Closeable {
            if(deferRead)pendingRead=callback else callback(if(failRead)Result.failure(IllegalStateException()) else Result.success(collection));return Closeable {}
        }
        override fun sources(callback: (Result<List<TripMusicSourceItem>>)->Unit): Closeable {callback(Result.success(own));return Closeable {}}
        override fun add(source: TripSavedPlaylistSource,rights: Boolean,review: Boolean,callback: (Result<TripMusicCollection>)->Unit): Closeable {
            assertTrue(rights);assertTrue(review);writes++;posted=source
            if(deferAdd)pendingAdd=callback else {collection=addedCollection();callback(Result.success(collection))}
            return Closeable {cancelledAdds++}
        }
        fun addedCollection()=collection.copy(items=collection.items+TripSavedPlaylist("2".repeat(32),"바다 드라이브","https://www.melon.com/mymusic/playlist/one",account,"사용자A","quarantined"))
        fun finishAdd(result: Result<TripMusicCollection>) {val callback=pendingAdd;pendingAdd=null;callback?.invoke(result)}
        var played=mutableListOf<String>()
        override fun play(itemId: String,callback: (Result<TripMusicCollection>)->Unit): Closeable {
            played+=itemId;callback(Result.success(collection));return Closeable {}
        }
        override fun move(itemId: String,afterId: String?,callback: (Result<TripMusicCollection>)->Unit): Closeable {
            callback(Result.success(collection));return Closeable {}
        }
        override fun close(){closed=true}
    }
}
