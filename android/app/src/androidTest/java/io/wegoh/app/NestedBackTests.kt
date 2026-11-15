package io.wegoh.app

import android.content.Intent
import android.test.InstrumentationTestCase
import android.view.accessibility.AccessibilityNodeInfo
import androidx.activity.compose.setContent
import androidx.compose.runtime.*
import io.wegoh.app.nativeauth.*
import io.wegoh.app.ui.*
import java.time.Instant

@Suppress("DEPRECATION")
class NestedBackTests: InstrumentationTestCase() {
    private lateinit var activity: MainActivity
    override fun setUp() {
        super.setUp()
        activity=instrumentation.startActivitySync(Intent(instrumentation.targetContext,MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
    }
    override fun tearDown() {
        instrumentation.runOnMainSync {activity.finish()}
        super.tearDown()
    }
    private fun settle() {instrumentation.waitForIdleSync();Thread.sleep(220)}
    private fun nodes(): List<AccessibilityNodeInfo> {
        if(android.os.Build.VERSION.SDK_INT>=34)instrumentation.uiAutomation.clearCache()
        val result=mutableListOf<AccessibilityNodeInfo>()
        fun walk(node: AccessibilityNodeInfo?) {if(node!=null){result.add(node);for(i in 0 until node.childCount)walk(node.getChild(i))}}
        walk(instrumentation.uiAutomation.rootInActiveWindow);return result
    }
    private fun click(label: String) {
        val deadline=System.currentTimeMillis()+5000
        while(System.currentTimeMillis()<deadline) {
            for(candidate in nodes().filter {it.isVisibleToUser && (it.text?.toString()==label || it.contentDescription?.toString()==label)}) {
                var node: AccessibilityNodeInfo?=candidate
                repeat(5){if(node?.isEnabled==true && node?.isClickable==true && node?.performAction(AccessibilityNodeInfo.ACTION_CLICK)==true){settle();return};node=node?.parent}
            }
            Thread.sleep(100)
        }
        fail("Missing action: $label; "+nodes().joinToString {"${it.text}|${it.contentDescription}|${it.className}"})
    }
    private fun tab(label: String): AccessibilityNodeInfo? {
        return nodes().filter {it.isVisibleToUser && it.text?.toString()==label}
            .maxByOrNull {android.graphics.Rect().also(it::getBoundsInScreen).top}
    }
    private fun clickTab(label: String) {
        var target=tab(label) ?: error("Missing tab: $label; "+nodes().joinToString {"${it.text}|${it.contentDescription}|${it.className}"})
        repeat(5) {
            if(target.isClickable && target.isEnabled) {
                assertTrue("Tab must accept click: $label",target.performAction(AccessibilityNodeInfo.ACTION_CLICK))
                settle()
                val labelBounds=android.graphics.Rect().also {tab(label)!!.getBoundsInScreen(it)}
                assertTrue("Tab must be selected: $label",nodes().any {node->
                    node.isSelected && android.graphics.Rect().also(node::getBoundsInScreen).contains(labelBounds.centerX(),labelBounds.centerY())
                })
                return
            }
            target=target.parent ?: error("Missing tab action: $label")
        }
        fail("Missing tab action: $label")
    }
    private fun systemBack(){instrumentation.runOnMainSync {activity.onBackPressedDispatcher.onBackPressed()};settle()}
    private fun fixture()=WegoState(setupAllowed=true,storageReady=true)
    fun testHeaderAndSystemBackCloseRoomBeforeRoot() {
        val room=SocialRoom("a".repeat(32),"함께 가는 방","team-"+"b".repeat(40),null,null,
            SocialPreference.BALANCED,SocialRole.MEMBER,Instant.now().plusSeconds(300),Instant.now(),300.0,null,
            SocialReview("room",SocialReview.State.PRIVATE,false),false,emptyList(),emptyList())
        val overview=SocialOverview(emptyList(),emptyList(),emptyList(),emptyList(),emptyList(),true,true,true,false)
        val social=mutableStateOf(SocialPageState(AccountReadStatus.READY,overview,room,true))
        var rootCalls=0;var closes=0
        instrumentation.runOnMainSync {activity.setContent {WegoCarTheme {
            CompositionLocalProvider(LocalVehicleLandingPage provides "rooms") {
                WegoVehicleScreen(fixture(),{},{},{},{},{},{},{},{},{},socialState=social.value,
                    onRoomClose={closes++;social.value=social.value.copy(room=null)},onRootBack={rootCalls++})
            }
        }}}
        settle();click("뒤로");assertEquals(1,closes);assertEquals(0,rootCalls)
        instrumentation.runOnMainSync {social.value=social.value.copy(room=room)}
        settle();systemBack();assertEquals(2,closes);assertEquals(0,rootCalls)
        systemBack();assertEquals(1,rootCalls)
    }
    fun testEmbeddedChildBackDisposesWhenTabChanges() {
        var rootCalls=0;var closes=0
        val nested=mutableStateOf(true)
        instrumentation.runOnMainSync {activity.setContent {WegoCarTheme {
            CompositionLocalProvider(LocalVehicleLandingPage provides "rooms") {
                WegoVehicleScreen(fixture(),{},{},{},{},{},{},{},{},{},onRootBack={rootCalls++},tripExtras={
                    CarChildBackHandler(nested.value) {closes++;nested.value=false}
                    CarText(if(nested.value)"기록 상세" else "기록 목록")
                })
            }
        }}}
        settle();clickTab("기록");click("뒤로");assertEquals(1,closes);assertEquals(0,rootCalls)
        instrumentation.runOnMainSync {nested.value=true};settle();systemBack()
        assertEquals(2,closes);assertEquals(0,rootCalls)
        instrumentation.runOnMainSync {nested.value=true};settle();clickTab("여행방")
        assertTrue("The room body must be visible",nodes().any {it.isVisibleToUser && it.text?.toString()=="차량 연결이 필요해요"})
        assertFalse("Leaving the history tab must dispose its detail",nodes().any {it.isVisibleToUser && it.text?.toString()=="기록 상세"})
        systemBack()
        assertEquals(2,closes);assertEquals(1,rootCalls)
    }
}
