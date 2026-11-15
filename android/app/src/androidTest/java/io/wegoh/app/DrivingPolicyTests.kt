package io.wegoh.app

import android.content.Intent
import android.os.Bundle
import android.view.accessibility.AccessibilityNodeInfo

/** Real CarUx callback transitions. Host controls only the official emulator console. */
@Suppress("DEPRECATION")
class DrivingPolicyTests: FirstRunPermissionsCompletedTestCase() {
    private fun nodes(): List<AccessibilityNodeInfo> {
        if(android.os.Build.VERSION.SDK_INT>=34)instrumentation.uiAutomation.clearCache()
        val result=mutableListOf<AccessibilityNodeInfo>()
        fun walk(node: AccessibilityNodeInfo?) {if(node!=null){result.add(node);for(i in 0 until node.childCount)walk(node.getChild(i))}}
        walk(instrumentation.uiAutomation.rootInActiveWindow);return result
    }
    private fun visible(label: String)=nodes().any {it.text?.toString()==label || it.contentDescription?.toString()==label}
    private fun waitFor(label: String,predicate: ()->Boolean) {
        val until=System.currentTimeMillis()+20000
        while(System.currentTimeMillis()<until) {
            var ready=false;instrumentation.runOnMainSync {ready=predicate()}
            if(ready)return
            Thread.sleep(200)
        }
        fail(label)
    }
    private fun signal(value: String) {instrumentation.sendStatus(0,Bundle().apply{putString("stream","\n$value\n")})}
    fun testRealDrivingRestrictionClosesMenuAndRecovers() {
        val activity=instrumentation.startActivitySync(Intent(instrumentation.targetContext,MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        val controller=activity.controller
        waitFor("Parked") {controller.state.setupAllowed && controller.state.storageReady}
        instrumentation.waitForIdleSync();Thread.sleep(500)
        val firstConnection=controller.vehicleAccountConnection?.status()?.stage!=io.wegoh.app.nativeauth.VehicleConnection.Stage.CONNECTED
        val entryAction=if(firstConnection && !controller.firstRunGuide.completed)"다음" else "차량 연결"
        val showingGuide=firstConnection && !controller.firstRunGuide.completed
        if(firstConnection) {
            assertTrue("Connection action is available while parked",visible(entryAction))
            for(label in listOf("전체 메뉴","뒤로","홈"))assertFalse("Initial connection has no app navigation: $label",visible(label))
            if(showingGuide) {
                var n=nodes().first {it.contentDescription?.toString()=="다음"}
                while(!n.isClickable && n.parent!=null)n=n.parent
                assertTrue(n.performAction(AccessibilityNodeInfo.ACTION_CLICK))
                waitFor("Introduction second page") {visible("내 음악을 차에서")}
            }
        } else {
            var node=nodes().firstOrNull {it.contentDescription?.toString()=="전체 메뉴"}
            var clicked=false
            repeat(5){if(!clicked){clicked=node?.performAction(AccessibilityNodeInfo.ACTION_CLICK)==true;node=node?.parent}}
            assertTrue("Menu is actionable while parked",clicked)
            Thread.sleep(500);assertTrue(visible("여행방"));assertTrue(visible("친구"))
        }
        signal("UX_READY_PARKED")
        waitFor("Real CarUx restriction callback") {!controller.state.setupAllowed}
        Thread.sleep(500)
        for(label in listOf("전체 메뉴","화면 상태","여행방","친구","만들기","프로필","출발","도착 알림"))assertFalse("Restricted: $label",visible(label))
        if(showingGuide)for(label in listOf("다음","이전","건너뛰기"))assertFalse("Restricted introduction: $label",visible(label))
        val cpuAt=android.os.Process.getElapsedCpuTime();val wallAt=android.os.SystemClock.elapsedRealtime()
        val pss=mutableListOf<Int>()
        repeat(5){Thread.sleep(2000);assertFalse("Restriction must remain active during resource sample",controller.state.setupAllowed)
            val info=android.os.Debug.MemoryInfo();android.os.Debug.getMemoryInfo(info);pss.add(info.totalPss)}
        val wall=android.os.SystemClock.elapsedRealtime()-wallAt;val cpu=android.os.Process.getElapsedCpuTime()-cpuAt
        val cores=Runtime.getRuntime().availableProcessors()
        val resources=org.json.JSONObject().put("scope","actual-emulator-CarUx-restricted-idle-no-active-journey")
            .put("initialConnectionEntry",firstConnection)
            .put("wallMs",wall).put("processCpuMs",cpu).put("availableCores",cores)
            .put("cpuOneCorePercent",100.0*cpu/wall).put("cpuCapacityPercent",100.0*cpu/wall/cores)
            .put("pssKiB",org.json.JSONArray(pss)).put("peakPssMiB",pss.max()/1024.0)
            .put("limitation","Debug emulator idle window; not active-journey, actual-vehicle or market certification")
        java.io.File(activity.cacheDir,"driving-resource.json").writeText(resources.toString(2))
        signal("UX_RESOURCE_RESTRICTED="+resources.toString())
        signal("UX_READY_RESTRICTED")
        waitFor("Real parked recovery callback") {controller.state.setupAllowed}
        Thread.sleep(500);assertFalse("No stale dialog after parking",visible("어디로 갈까요?"));assertTrue(visible(if(firstConnection)entryAction else "발견"))
        if(showingGuide)assertTrue("Real CarUx return preserves the second introduction page",visible("내 음악을 차에서"))
    }
}
