package io.wegoh.app

import android.content.Intent
import android.graphics.Bitmap
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.*
import io.wegoh.app.nativeauth.*
import io.wegoh.app.ui.*
import java.io.File

class VehicleProfileCommonUiTest: EntryDesignTestCase() {
    override fun setUp() {
        super.setUp()
        host=instrumentation.startActivitySync(Intent(instrumentation.targetContext,SafFrameworkHarnessActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_MULTIPLE_TASK)) as SafFrameworkHarnessActivity
        val deadline=android.os.SystemClock.elapsedRealtime()+5000
        var previous: android.graphics.Rect?=null
        var stableSince=0L
        var ready=false
        while(!ready && android.os.SystemClock.elapsedRealtime()<deadline) {
            var current: android.graphics.Rect?=null
            instrumentation.runOnMainSync {
                val view=host.window.decorView
                val visible=android.graphics.Rect()
                if(host.hasWindowFocus() && view.isShown && view.width>0 && view.height>0 && view.getGlobalVisibleRect(visible))current=visible
            }
            val now=android.os.SystemClock.elapsedRealtime()
            if(current==null) {previous=null;stableSince=0L}
            else if(current!=previous) {previous=current;stableSince=now}
            else if(now-stableSince>=500)ready=true
            if(!ready)Thread.sleep(50)
        }
        assertTrue("Host must retain focus and stable visible bounds before rendering",ready)
    }
    override fun tearDown() {
        instrumentation.runOnMainSync {host.finish()}
        super.tearDown()
    }
    private fun reveal(label: String) {
        repeat(16) {
            val r=bounds(control(label))
            if(!r.isEmpty && frame.contains(r))return
            val action=nodes().firstNotNullOfOrNull {it.config.getOrNull(SemanticsActions.ScrollBy)?.action}
            assertNotNull("Reachable scroll container for $label",action)
            instrumentation.runOnMainSync {requireNotNull(action).invoke(0f,frame.height()/2f)}
            settle()
        }
        fail("Action outside viewport: $label")
    }
    private fun text(label: String)=nodes().any {it.config.getOrNull(SemanticsProperties.Text)?.any {value->value.text==label}==true}
    private fun shot(name: String) {
        val until=android.os.SystemClock.elapsedRealtime()+5000
        var image: Bitmap?=null
        while(image==null && android.os.SystemClock.elapsedRealtime()<until) {
            try {image=instrumentation.uiAutomation.takeScreenshot()} catch(_: NullPointerException) {}
            if(image==null)Thread.sleep(80)
        }
        val screen=requireNotNull(image) {"Screenshot provider did not return a frame"}
        val crop=Bitmap.createBitmap(screen,frame.left,frame.top,frame.width(),frame.height())
        val dir=File(host.cacheDir,"profile-common-preview").apply {mkdirs()}
        File(dir,"$name.png").outputStream().use {crop.compress(Bitmap.CompressFormat.PNG,100,it)}
        crop.recycle();screen.recycle()
    }
    fun testOwnInfoRetainsRealFieldsAndCurrentRetryGate() {
        val profile=mutableStateOf(AccountProfileState(AccountReadStatus.READY,"사용자F",vehicleUnavailable=true))
        var retries=0;var external=0
        for((width,height) in listOf(648 to 800,1256 to 800,1700 to 1184))for(night in listOf(false,true)) {
            instrumentation.runOnMainSync {profile.value=profile.value.copy(isCurrent=true)}
            render(width,height,night,entry=false) {AccountProfileScreen(profile.value,{},{external++},{retries++})}
            assertTrue(text("사용자F"));assertFalse("No invented friend code",text("WG-USER-2026"))
            reveal("다시 불러오기");checkButton("다시 불러오기");tap("다시 불러오기")
            shot("own-info-${width}x$height-${if(night)"night" else "day"}")
            instrumentation.runOnMainSync {profile.value=profile.value.copy(isCurrent=false)};settle()
            assertTrue(control("다시 불러오기").config.contains(SemanticsProperties.Disabled))
            assertFalse("Phone changes remain an inline hint only",nodes().any {
                it.config.getOrNull(SemanticsProperties.ContentDescription)?.contains("휴대전화에서 변경")==true
            })
        }
        assertEquals(6,retries);assertEquals("No external handoff callback",0,external)
    }
    fun testFriendListAndDetailMeasureWithoutIntrinsicQueries() {
        val friend=SocialPerson("team-"+"c".repeat(40),"여행 친구")
        val overview=SocialOverview(emptyList(),listOf(friend),emptyList(),emptyList(),emptyList(),true,false,false,false)
        val selected=mutableStateOf<String?>(null)
        for((width,height) in listOf(648 to 800,1256 to 800,1700 to 1184)) {
            instrumentation.runOnMainSync {selected.value=null}
            render(width,height,false,entry=false) {
                VehicleProfilesPage(AccountProfileState(AccountReadStatus.READY,"사용자F"),
                    SocialPageState(AccountReadStatus.READY,overview,isCurrent=true),selected.value,{selected.value=it},{_,_->},{},{},{})
            }
            tap("친구 관리")
            assertTrue(text("나와 친구"))
            checkButton("여행 친구");tap("여행 친구")
            assertEquals(friend.id,selected.value)
            reveal("친구 연결 해제");checkButton("친구 연결 해제")
        }
    }
    fun testFriendDetailRetainsReadOnlyAndBusyGates() {
        val friend=SocialPerson("team-"+"b".repeat(40),"함께 가는 친구")
        val overview=SocialOverview(emptyList(),listOf(friend),emptyList(),emptyList(),emptyList(),true,false,false,false)
        val social=mutableStateOf(SocialPageState(AccountReadStatus.READY,overview,isCurrent=true))
        var mutations=0
        for((width,height) in listOf(648 to 800,1256 to 800,1700 to 1184))for(night in listOf(false,true)) {
            instrumentation.runOnMainSync {social.value=social.value.copy(isCurrent=true,busy=false)}
            render(width,height,night,entry=false) {
                VehicleProfilesPage(AccountProfileState(AccountReadStatus.READY,"사용자F"),social.value,friend.id,{},
                    {_,_->mutations++},{},{},{})
            }
            reveal("차단");checkButton("차단");checkButton("친구 연결 해제")
            shot("friend-detail-${width}x$height-${if(night)"night" else "day"}")
            instrumentation.runOnMainSync {social.value=social.value.copy(busy=true)};settle()
            assertTrue(control("차단").config.contains(SemanticsProperties.Disabled))
            assertTrue(control("친구 연결 해제").config.contains(SemanticsProperties.Disabled))
            instrumentation.runOnMainSync {social.value=social.value.copy(busy=false,isCurrent=false)};settle()
            assertTrue(control("차단").config.contains(SemanticsProperties.Disabled))
        }
        instrumentation.runOnMainSync {social.value=social.value.copy(isCurrent=true,busy=false,overview=SocialOverview(overview.people,overview.friends,overview.requests,overview.blocks,overview.rooms,
            overview.friendsAvailable,overview.roomsAvailable,overview.historyAvailable,true))};settle()
        assertTrue(control("차단").config.contains(SemanticsProperties.Disabled))
        assertEquals("Presentation never mutates friendship",0,mutations)
    }
    fun testPrivacyConsentGatesAndCommonRecoveryActions() {
        val consent=mutableStateOf(true)
        var suspended=0;var withdrawn=0;var retry=0;var connected=0
        for((width,height) in listOf(648 to 800,1256 to 800,1700 to 1184))for(night in listOf(false,true)) {
            instrumentation.runOnMainSync {consent.value=true}
            render(width,height,night,entry=false) {VehiclePrivacyPage(consent.value,{suspended++},{withdrawn++},{},{})}
            assertFalse(text("경로 위치 사용과 기록"));assertFalse(text("3곳"))
            reveal("위치 사용 일시중지");checkButton("위치 사용 일시중지");tap("위치 사용 일시중지")
            instrumentation.runOnMainSync {consent.value=false};settle()
            assertTrue(control("위치 사용 일시중지").config.contains(SemanticsProperties.Disabled))
            reveal("동의 철회 및 기록 삭제");checkButton("동의 철회 및 기록 삭제");tap("동의 철회 및 기록 삭제")
            shot("privacy-${width}x$height-${if(night)"night" else "day"}")
        }
        render(1256,800,false,entry=false) {CarFailureState("불러오지 못했어요",Modifier.fillMaxSize(),onRetry={retry++})}
        checkButton("다시 불러오기");tap("다시 불러오기")
        render(1256,800,false,entry=false) {CarConnectionState("연결이 필요해요",Modifier.fillMaxSize(),onConnect={connected++})}
        checkButton("차량 연결");tap("차량 연결")
        assertEquals(6,suspended);assertEquals(6,withdrawn);assertEquals(1,retry);assertEquals(1,connected)
    }
    fun testCourseCommonStatesShareOneCenteredContentAxisAtBothWidths() {
        for(width in listOf(840,1700))for(kind in 0..2) {
            val title=when(kind) {0->"경로를 불러오는 중";1->"저장한 경로가 없어요";else->"경로를 불러오지 못했어요"}
            val detail="iPhone 앱의 경로에서 확인해 주세요"
            render(width,1184,false,entry=false) {
                when(kind) {
                    0->CarLoadingState(title,Modifier.fillMaxSize())
                    1->CarEmptyState(title,Modifier.fillMaxSize(),detail=detail)
                    else->CarFailureState(title,Modifier.fillMaxSize(),detail=detail,onRetry={})
                }
            }
            val labels=if(kind==0)listOf(title) else listOf(title,detail)
            labels.forEach {label->
                val matches=nodes().filter {it.config.getOrNull(SemanticsProperties.Text)?.any {text->text.text==label}==true}
                assertEquals("One state label",1,matches.size)
                val rectangle=bounds(matches.single())
                assertTrue("State content centered: $label",kotlin.math.abs(rectangle.exactCenterX()-frame.exactCenterX())<=2f)
                assertTrue("State content visible",frame.contains(rectangle))
            }
            if(kind==2)checkButton("다시 불러오기")
            shot("course-state-$kind-$width")
        }
    }
}
