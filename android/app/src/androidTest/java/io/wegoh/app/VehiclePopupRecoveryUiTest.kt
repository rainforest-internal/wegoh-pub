package io.wegoh.app

import android.content.Intent
import android.test.InstrumentationTestCase
import android.view.accessibility.AccessibilityNodeInfo
import androidx.activity.compose.setContent
import androidx.compose.runtime.*
import io.wegoh.app.nativeauth.*
import io.wegoh.app.ui.*

/**
 * Renders the real root screen/dialogs with synthetic account states and callbacks.
 * The preview Activity isolates this UI test from vehicle SDK/application services;
 * it does not verify real network replies, CarUx transitions, or Pleos OEM windows.
 */
@Suppress("DEPRECATION")
class VehiclePopupRecoveryUiTest: InstrumentationTestCase() {
    private lateinit var host: TripScreensPreviewActivity
    override fun setUp() {
        super.setUp()
        host=instrumentation.startActivitySync(Intent(instrumentation.targetContext,TripScreensPreviewActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_MULTIPLE_TASK)) as TripScreensPreviewActivity
    }
    override fun tearDown() {
        instrumentation.runOnMainSync {host.setContent {};host.finish()}
        super.tearDown()
    }
    private fun settle() {instrumentation.waitForIdleSync();Thread.sleep(250)}
    private fun nodes(): List<AccessibilityNodeInfo> {
        if(android.os.Build.VERSION.SDK_INT>=34)instrumentation.uiAutomation.clearCache()
        val result=mutableListOf<AccessibilityNodeInfo>()
        fun walk(node: AccessibilityNodeInfo?) {if(node!=null){result.add(node);for(i in 0 until node.childCount)walk(node.getChild(i))}}
        walk(instrumentation.uiAutomation.rootInActiveWindow)
        return result
    }
    private fun has(label: String)=nodes().any {it.isVisibleToUser && it.text?.toString()==label}
    private fun click(label: String) {
        val until=android.os.SystemClock.uptimeMillis()+5000
        while(android.os.SystemClock.uptimeMillis()<until) {
            for(candidate in nodes().filter {it.isVisibleToUser && (it.text?.toString()==label || it.contentDescription?.toString()==label)}) {
                var node: AccessibilityNodeInfo?=candidate
                repeat(5) {
                    if(node?.isEnabled==true && node?.isClickable==true && node?.performAction(AccessibilityNodeInfo.ACTION_CLICK)==true) {settle();return}
                    node=node?.parent
                }
            }
            Thread.sleep(100)
        }
        fail("Missing action: $label")
    }
    private fun show(content: @Composable ()->Unit) {
        instrumentation.runOnMainSync {host.setContent {WegoCarTheme {content()}}}
        settle()
    }
    private fun overview(requests: List<SocialFriendRequest>)=
        SocialOverview(emptyList(),emptyList(),requests,emptyList(),emptyList(),true,false,false,false)

    fun testFriendResponseFailureKeepsRequestAndAllowsReloadBeforeRetry() {
        val request=SocialFriendRequest(SocialPerson("team-"+"a".repeat(40),"요청자"),SocialFriendRequest.Direction.INCOMING)
        val social=mutableStateOf(SocialPageState(AccountReadStatus.READY,overview(listOf(request)),isCurrent=true))
        var replies=0;var reloads=0
        show {
            WegoVehicleScreen(WegoState(setupAllowed=true,storageReady=true),{},{},{},{},{},{},{},{},{},
                socialState=social.value,onFriendRespond={_,_->replies++;social.value=social.value.copy(busy=true)},
                onSocialRefresh={reloads++;social.value=social.value.copy(isCurrent=true,notice=null,overview=overview(listOf(request)))})
        }
        click("수락")
        assertEquals(1,replies)
        assertTrue("Pending response stays visible",has("처리 중"))
        instrumentation.runOnMainSync {social.value=social.value.copy(busy=false,isCurrent=false,notice="새로고침으로 현재 상태를 확인해주세요")}
        settle()
        assertTrue("Failure is shown in the request dialog",has("새로고침으로 현재 상태를 확인해주세요"))
        click("다시 불러오기");assertEquals(1,reloads)
        click("수락");assertEquals("Same request can be retried after authoritative refresh",2,replies)
        instrumentation.runOnMainSync {social.value=social.value.copy(busy=false,isCurrent=true,overview=overview(emptyList()))}
        settle()
        assertFalse("Authoritative completion closes the request",has("요청자님의 친구 요청입니다"))
    }

    fun testFriendRequestDisappearsWhenAccountSnapshotIsCleared() {
        val request=SocialFriendRequest(SocialPerson("team-"+"b".repeat(40),"이전 계정 요청자"),SocialFriendRequest.Direction.INCOMING)
        val social=mutableStateOf(SocialPageState(AccountReadStatus.READY,overview(listOf(request)),isCurrent=true))
        show {WegoVehicleScreen(WegoState(setupAllowed=true,storageReady=true),{},{},{},{},{},{},{},{},{},socialState=social.value)}
        assertTrue(has("이전 계정 요청자님의 친구 요청입니다"))
        instrumentation.runOnMainSync {social.value=SocialPageState()};settle()
        assertFalse("Cleared account data cannot stay in a retained dialog",has("이전 계정 요청자님의 친구 요청입니다"))
    }

    fun testCourseAddSelectionFailureShowsRetryAndCompletedOnlyListShowsEmptyState() {
        val pack=PublishedPack("course",1,"시험 코스","작성자","경로",1,"0".repeat(64))
        val item=CourseLibraryItem(pack,emptyList(),false,0,null,null,false,false,null,listOf("시험 장소"))
        val library=CourseLibrary(listOf(item),emptyList(),emptyList(),emptyList(),emptyList(),emptyList(),0)
        val trip=TripSummary("a".repeat(32),"시험 여행",true,"운전자",1,1,state="planned")
        val trips=mutableStateOf(TripsPageState(AccountReadStatus.READY,TripList(listOf(trip),emptyList()),isCurrent=true))
        var retries=0
        show {
            CompositionLocalProvider(LocalVehicleLandingPage provides "home") {
                WegoVehicleScreen(WegoState(setupAllowed=true,storageReady=true,
                    accountDiscovery=AccountDiscoveryState(AccountReadStatus.READY,library=library)),{},{},{},{},{},{},{},{},{},
                    tripsState=trips.value,onTripSelect={id->trips.value=trips.value.copy(selectedId=id,busy=true)},
                    onTripsRefresh={retries++;trips.value=trips.value.copy(busy=true)})
            }
        }
        click("시험 코스 여행에 추가");click("시험 여행")
        assertTrue(has("여행을 불러오는 중"))
        instrumentation.runOnMainSync {trips.value=trips.value.copy(busy=false,isCurrent=false,notice="다시 불러와 주세요")};settle()
        assertFalse("Failure cannot masquerade as perpetual loading",has("여행을 불러오는 중"))
        assertTrue(has("다시 불러와 주세요"));click("다시 불러오기");assertEquals(1,retries)
        click("취소")
        instrumentation.runOnMainSync {trips.value=TripsPageState(AccountReadStatus.READY,
            TripList(listOf(trip.copy(state="completed")),emptyList()),isCurrent=true)};settle()
        click("시험 코스 여행에 추가")
        assertTrue("Filter result, not unfiltered count, controls empty state",has("추가할 여행을 휴대전화에서 먼저 만들어주세요"))
    }
}
