package io.wegoh.app

import android.content.Intent
import android.test.InstrumentationTestCase
import android.view.View
import android.view.ViewGroup
import android.view.accessibility.AccessibilityNodeInfo
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import kotlin.math.min
import androidx.compose.ui.platform.ViewRootForTest
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsNode
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.semantics.getAllSemanticsNodes
import io.wegoh.app.nativeauth.*
import io.wegoh.app.ui.*

@Suppress("DEPRECATION")
class VehicleRemotePolicyUiTest: InstrumentationTestCase() {
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
    private fun node(label: String): AccessibilityNodeInfo? {
        instrumentation.uiAutomation.clearCache()
        fun find(n: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
            if(n==null)return null
            if(n.isVisibleToUser && (n.text?.toString()==label || n.contentDescription?.toString()==label))return n
            for(i in 0 until n.childCount)find(n.getChild(i))?.let {return it}
            return null
        }
        return find(instrumentation.uiAutomation.rootInActiveWindow)
    }
    private fun await(label: String,condition: ()->Boolean) {
        val deadline=android.os.SystemClock.uptimeMillis()+8000
        while(android.os.SystemClock.uptimeMillis()<deadline) {if(condition())return;Thread.sleep(50)}
        fail(label)
    }
    private fun click(label: String) {
        await("click $label") {
            var n=node(label)
            while(n!=null && !n.isClickable)n=n.parent
            n?.isEnabled==true && n.performAction(AccessibilityNodeInfo.ACTION_CLICK)
        }
        instrumentation.waitForIdleSync()
    }
    private fun assertSummaryHasNoClickActions() {
        var clicks=0
        instrumentation.runOnMainSync {
            fun inspect(view: View) {
                if(view is ViewRootForTest)clicks+=view.semanticsOwner.getAllSemanticsNodes(mergingEnabled=false)
                    .count {it.config.contains(SemanticsActions.OnClick)}
                if(view is ViewGroup)for(i in 0 until view.childCount)inspect(view.getChildAt(i))
            }
            inspect(host.window.decorView)
        }
        assertEquals("Policy summary must remain information only",0,clicks)
    }
    fun testUnknownOnAndOffPoliciesStayPassiveAndDoNotInventPermission() {
        val policy=mutableStateOf<TripRemotePolicy?>(null)
        instrumentation.runOnMainSync {host.setContent {WegoCarTheme {VehicleRemotePolicySummary(policy.value)}}}
        await("unknown policy") {node("허용 설정을 확인할 수 없어요")!=null}
        assertNull(node("허용 안 함"));assertNull(node("허용"));assertSummaryHasNoClickActions()
        val actions=setOf("hvac.temperature","light.cabin","light.reading","light.ambient")
        instrumentation.runOnMainSync {policy.value=TripRemotePolicy(true,actions,"device")}
        await("actual permission groups") {node("공조 1/5")!=null && node("조명")!=null}
        assertNotNull(node("꺼둔 기능 · 창문 · 시트"));assertSummaryHasNoClickActions()
        instrumentation.runOnMainSync {policy.value=TripRemotePolicy(false,actions,"device")}
        await("off removes allowed groups") {node("허용 안 함")!=null && node("조명")==null && node("공조 1/5")==null}
        assertNull(node("꺼둔 기능 · 창문 · 시트"));assertSummaryHasNoClickActions()
        instrumentation.runOnMainSync {policy.value=null}
        await("invalidated policy is unknown") {node("허용 설정을 확인할 수 없어요")!=null && node("허용 안 함")==null}
        assertSummaryHasNoClickActions()
    }
    fun testTripCarRoundTripKeepsSelectedContextAndOtherTabsCloseIt() {
        val policy=TripRemotePolicy(true,setOf("hvac.temperature"),"device")
        val car=TripCar("car","사용자A의 차","me","사용자A",2,true,false,emptyList(),remotePolicy=policy)
        val trip=TripDetail("trip","서해안 드라이브","",listOf(TripMember("me","사용자A",true,true,true)),listOf(car),state="active",revision=1)
        var trips by mutableStateOf(TripsPageState(AccountReadStatus.READY,selectedId=trip.id,detail=trip,isCurrent=true,gear=TripGear.PARK))
        var closes=0
        instrumentation.runOnMainSync {host.setContent {WegoCarTheme {
            WegoVehicleScreen(WegoState(setupAllowed=true,storageReady=true,accountProfile=AccountProfileState(AccountReadStatus.READY,"사용자A")),
                onSelect={},onImport={},onStart={},onStop={},onNavigate={},onReset={},onBrowse={},onDownload={},onShareVisits={},
                tripsState=trips,onTripClose={closes++;trips=trips.copy(selectedId=null,detail=null)},
                remoteHistory={VehicleRemoteHistoryList(emptyList())})
        }}}
        click("리모컨 탭")
        await("retained trip policy scope on remote page") {node("동승자 허용 기능")!=null}
        assertNull("Fixture policy cannot grant another receiver",node("허용"))
        assertEquals(0,closes);assertSame(trip,trips.detail)
        click("여행 탭")
        await("retained selected trip") {node(trip.title)!=null}
        assertEquals(0,closes);assertSame(trip,trips.detail)
        click("리모컨 탭");click("프로필 탭")
        await("other tab closes detail") {closes==1 && trips.detail==null && trips.selectedId==null}
    }
    fun testNoActiveTripAndUnavailablePolicyAreDifferentPassiveStates() {
        val snapshot=mutableStateOf(TripRemotePolicySnapshot(AccountReadStatus.READY))
        instrumentation.runOnMainSync {host.setContent {WegoCarTheme {
            VehicleRemotePolicySummary(null,snapshot=snapshot.value)
        }}}
        await("confirmed no active trip") {node("진행 중인 여행이 없어요")!=null}
        assertNull(node("허용 안 함"));assertSummaryHasNoClickActions()
        instrumentation.runOnMainSync {snapshot.value=TripRemotePolicySnapshot(AccountReadStatus.UNAVAILABLE)}
        await("unknown after failure") {node("허용 설정을 확인할 수 없어요")!=null && node("진행 중인 여행이 없어요")==null}
        assertSummaryHasNoClickActions()
    }
    fun testRequestsAreInlineWithoutRemovedNavigationAtBothWidths() {
        fun semantics(): List<SemanticsNode> {
            val result=mutableListOf<SemanticsNode>()
            instrumentation.runOnMainSync {
                fun inspect(view: View) {
                    if(view is ViewRootForTest)result+=view.semanticsOwner.getAllSemanticsNodes(mergingEnabled=false)
                    if(view is ViewGroup)for(index in 0 until view.childCount)inspect(view.getChildAt(index))
                }
                inspect(host.window.decorView)
            }
            return result
        }
        fun hasText(label: String)=semantics().any {it.config.getOrNull(SemanticsProperties.Text).orEmpty().any {text->text.text==label}}
        fun activate(label: String) {
            val control=semantics().single {it.config.contains(SemanticsActions.OnClick) &&
                it.config.getOrNull(SemanticsProperties.ContentDescription)?.contains(label)==true}
            val action=checkNotNull(control.config.getOrNull(SemanticsActions.OnClick)?.action)
            instrumentation.runOnMainSync {assertTrue(action())}
            instrumentation.waitForIdleSync()
        }
        for(width in listOf(1700,840)) {
            instrumentation.runOnMainSync {host.setContent {key(width) {
                BoxWithConstraints(Modifier.fillMaxSize().testTag("car-extras-width-$width"),contentAlignment=Alignment.Center) {
                    val scale=min(constraints.maxWidth.toFloat()/width,constraints.maxHeight.toFloat()/1184)
                    val config=android.content.res.Configuration(LocalConfiguration.current).apply {screenWidthDp=width;screenHeightDp=1184}
                    CompositionLocalProvider(LocalDensity provides Density(scale),LocalConfiguration provides config) {
                        Box(Modifier.requiredSize(width.dp,1184.dp)) {WegoCarTheme {
                            WegoVehicleScreen(WegoState(setupAllowed=true,storageReady=true),
                                onSelect={},onImport={},onStart={},onStop={},onNavigate={},onReset={},onBrowse={},onDownload={},onShareVisits={},
                                remoteHistory={VehicleRemoteHistoryList(emptyList())},
                                carExtras={section,_->TripText("상세 ${section.name}")})
                        }}
                    }
                }
            }}}
            await("new composition at $width") {semantics().any {it.config.getOrNull(SemanticsProperties.TestTag)=="car-extras-width-$width"}}
            await("car tab at $width") {semantics().any {it.config.getOrNull(SemanticsProperties.ContentDescription)?.contains("리모컨 탭")==true}}
            activate("리모컨 탭")
            await("receiver overview at $width") {hasText("리모컨 받기")}
            await("inline commands at $width") {hasText("상세 COMMANDS")}
            for(label in listOf("차량 연결","차량 요청","주의 기록","뒤로")) {
                assertFalse("Removed navigation stays absent at $width: $label",semantics().any {
                    it.config.contains(SemanticsActions.OnClick) &&
                        it.config.getOrNull(SemanticsProperties.ContentDescription)?.contains(label)==true})
            }
        }
    }

}
