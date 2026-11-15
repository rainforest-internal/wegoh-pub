package io.wegoh.app

import android.accessibilityservice.AccessibilityServiceInfo
import android.content.Intent
import android.graphics.Bitmap
import android.os.Handler
import android.os.Looper
import android.test.InstrumentationTestCase
import android.view.PixelCopy
import android.view.accessibility.AccessibilityNodeInfo
import androidx.activity.compose.setContent
import androidx.compose.runtime.*
import androidx.compose.foundation.layout.*
import androidx.compose.ui.Modifier
import io.wegoh.app.nativeauth.SocialOverview
import io.wegoh.app.nativeauth.SocialPerson
import io.wegoh.app.ui.*
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

@Suppress("DEPRECATION")
class VehicleClientUiStateTests: InstrumentationTestCase() {
    private lateinit var activity: MainActivity
    private var previousFlags=0
    override fun setUp() {
        super.setUp()
        val info=instrumentation.uiAutomation.serviceInfo;previousFlags=info.flags
        info.flags=info.flags or AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
        instrumentation.uiAutomation.serviceInfo=info
        activity=instrumentation.startActivitySync(Intent(instrumentation.targetContext,MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
        val frames=CountDownLatch(1)
        instrumentation.runOnMainSync {activity.window.decorView.postOnAnimation {activity.window.decorView.postOnAnimation {frames.countDown()}}}
        assertTrue(frames.await(3,TimeUnit.SECONDS));settle()
    }
    override fun tearDown() {
        instrumentation.runOnMainSync {activity.finish()}
        val info=instrumentation.uiAutomation.serviceInfo;info.flags=previousFlags;instrumentation.uiAutomation.serviceInfo=info
        super.tearDown()
    }
    private fun settle() {instrumentation.waitForIdleSync();Thread.sleep(250)}
    private fun nodes(): List<AccessibilityNodeInfo> {
        if(android.os.Build.VERSION.SDK_INT>=34)instrumentation.uiAutomation.clearCache()
        val nodes=mutableListOf<AccessibilityNodeInfo>()
        fun walk(node: AccessibilityNodeInfo?) {if(node!=null){nodes.add(node);for(i in 0 until node.childCount)walk(node.getChild(i))}}
        val roots=instrumentation.uiAutomation.windows.mapNotNull {it.root}.filter {it.packageName?.toString()==instrumentation.targetContext.packageName}
        if(roots.isEmpty())walk(instrumentation.uiAutomation.rootInActiveWindow) else roots.forEach(::walk)
        return nodes
    }
    private fun matching(label: String)=nodes().filter {it.isVisibleToUser && (it.text?.toString()==label || it.contentDescription?.toString()==label)}
    private fun await(label: String,condition: ()->Boolean) {
        val end=System.currentTimeMillis()+7000
        while(System.currentTimeMillis()<end){if(condition())return;Thread.sleep(80)}
        fail(label)
    }
    private fun visible(label: String)=await("Missing label: $label") {matching(label).isNotEmpty()}
    private fun click(label: String) {
        val end=System.currentTimeMillis()+7000
        while(System.currentTimeMillis()<end) {
            for(candidate in matching(label)) {
                var node: AccessibilityNodeInfo?=candidate
                repeat(6){if(node?.isClickable==true && node?.isEnabled==true && node?.performAction(AccessibilityNodeInfo.ACTION_CLICK)==true){settle();return};node=node?.parent}
            }
            nodes().firstOrNull {it.isScrollable}?.performAction(AccessibilityNodeInfo.ACTION_SCROLL_FORWARD);Thread.sleep(80)
        }
        fail("Missing action: $label")
    }
    private fun capture(name: String) {
        val bitmap=Bitmap.createBitmap(activity.window.decorView.width,activity.window.decorView.height,Bitmap.Config.ARGB_8888)
        val done=CountDownLatch(1);var result=-1
        PixelCopy.request(activity.window,bitmap,{result=it;done.countDown()},Handler(Looper.getMainLooper()))
        assertTrue(done.await(5,TimeUnit.SECONDS));assertEquals(PixelCopy.SUCCESS,result)
        File(activity.cacheDir,"client-ui-$name.png").outputStream().use {bitmap.compress(Bitmap.CompressFormat.PNG,100,it)};bitmap.recycle()
    }
    fun testFriendManagementKeepsDetailUntilCanonicalSuccess() {
        val friend=SocialPerson("team-"+"b".repeat(40),"여행 친구")
        val overview=SocialOverview(emptyList(),listOf(friend),emptyList(),emptyList(),emptyList(),true,false,false,false)
        val selected=mutableStateOf<String?>(null)
        val social=mutableStateOf(SocialPageState(AccountReadStatus.READY,overview,isCurrent=true))
        var requests=0
        instrumentation.runOnMainSync {activity.setContent {WegoCarTheme {CarScreenScaffold("프로필",{selected.value=null}) {
            VehicleProfilesPage(AccountProfileState(AccountReadStatus.READY,"나",true),social.value,selected.value,
                {selected.value=it},{_,_->requests++;social.value=social.value.copy(busy=true)}, {},{},{})
        }}}}
        settle();click("친구 관리");click("여행 친구");click("친구 연결 해제");click("연결 해제")
        assertEquals(1,requests);assertEquals(friend.id,selected.value);visible("처리 중")
        instrumentation.runOnMainSync {social.value=social.value.copy(busy=false,notice="연결 해제를 완료하지 못했습니다. 다시 시도하세요")}
        settle();visible("여행 친구");visible("연결 해제를 완료하지 못했습니다. 다시 시도하세요");capture("friend-failure")
        click("친구 연결 해제");click("연결 해제");assertEquals(2,requests);assertEquals(friend.id,selected.value)
        instrumentation.runOnMainSync {social.value=social.value.copy(overview=SocialOverview(emptyList(),emptyList(),emptyList(),emptyList(),emptyList(),true,false,false,false),isCurrent=false)}
        settle();assertEquals(friend.id,selected.value)
        instrumentation.runOnMainSync {social.value=social.value.copy(busy=false,isCurrent=true)}
        await("Canonical removal must return to list") {selected.value==null};visible("나와 친구")
    }
    fun testClimateSettingsReflectReceiverStateAndRestrictInteraction() {
        val allowed=mutableStateOf(true)
        val focused=mutableStateOf(true)
        val canToggle=mutableStateOf(false)
        val enabled=mutableStateOf(false)
        val changes=mutableListOf<Boolean>()
        instrumentation.runOnMainSync {
            activity.setContent {WegoCarTheme {
                CarScreenScaffold("내 차 리모컨",{},showHeader=allowed.value) {
                    VehicleClimateSettings(allowed.value,focused.value,enabled.value,"여행 중 허용한 동승자의 조작을 기다립니다",
                        Modifier.weight(1f),canToggle=canToggle.value) {value->
                        changes.add(value)
                        enabled.value=value
                    }
                }
            }}
        }
        fun receiver(): AccessibilityNodeInfo? {
            for(label in matching("리모컨 수신")) {
                var node: AccessibilityNodeInfo?=label
                repeat(6) {
                    if(node?.isCheckable==true)return node
                    node=node?.parent
                }
            }
            return null
        }
        await("Switch is unavailable while checking the car") {receiver()?.isEnabled==false}
        instrumentation.runOnMainSync {canToggle.value=true;enabled.value=true}
        await("Switch reflects the confirmed state") {receiver()?.isChecked==true}
        instrumentation.runOnMainSync {enabled.value=false}
        await("External stop updates open screen") {receiver()?.isChecked==false}
        val stale=requireNotNull(receiver())
        instrumentation.runOnMainSync {focused.value=false};settle()
        assertEquals(false,receiver()?.isEnabled)
        stale.performAction(AccessibilityNodeInfo.ACTION_CLICK);settle();assertTrue(changes.isEmpty())
        instrumentation.runOnMainSync {allowed.value=false};settle();visible("정차 후 리모컨 수신을 설정하세요")
        assertTrue(matching("리모컨 수신").isEmpty());capture("climate-restricted")
        instrumentation.runOnMainSync {allowed.value=true;focused.value=true};settle();click("리모컨 수신")
        assertEquals(listOf(true),changes)
        await("Explicit enable updates open screen") {receiver()?.isChecked==true}
        capture("climate-ready")
    }
}
