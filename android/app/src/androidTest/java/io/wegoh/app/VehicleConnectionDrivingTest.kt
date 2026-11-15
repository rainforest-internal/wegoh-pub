package io.wegoh.app

import android.content.Intent
import android.os.Bundle
import android.view.accessibility.AccessibilityNodeInfo
import android.accessibilityservice.AccessibilityServiceInfo

/** Actual product Activity/CarUx; host changes only emulator VHAL and restores Park/0. */
class VehicleConnectionDrivingTest: FirstRunPermissionsCompletedTestCase() {
    private fun nodes(): List<AccessibilityNodeInfo> {
        val out=mutableListOf<AccessibilityNodeInfo>()
        fun visit(node: AccessibilityNodeInfo?){if(node==null)return;out.add(node);for(i in 0 until node.childCount)visit(node.getChild(i))}
        instrumentation.uiAutomation.windows.forEach {visit(it.root)};return out
    }
    private fun node(label: String)=nodes().firstOrNull {it.text?.toString()==label||it.contentDescription?.toString()==label}
    private fun await(label: String,check: ()->Boolean) {
        val end=android.os.SystemClock.uptimeMillis()+20000
        while(android.os.SystemClock.uptimeMillis()<end){if(check())return;Thread.sleep(50)}
        fail("Actual connection UI timeout: $label")
    }
    private fun signal(value: String) {instrumentation.sendStatus(0,Bundle().apply {putString("stream",value+"\n")})}
    fun testActualConnectionActivityCarUxBackAndHome() {
        val ui=instrumentation.uiAutomation;val info=ui.serviceInfo;val flags=info.flags
        info.flags=flags or AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS;ui.serviceInfo=info
        val context=instrumentation.targetContext
        val main=instrumentation.startActivitySync(Intent(context,MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK).putExtra("screen","pair")) as MainActivity
        val app=main.application as WegoApplication
        var child: VehicleConnectionActivity?=null
        try {
            await("Park actual setup permission") {app.controller.state.setupAllowed && node("차량 연결")!=null && node("P단에서 이용할 수 있어요")==null}
            val parkOnly=(instrumentation as android.test.InstrumentationTestRunner).arguments.getString("parkOnly")=="true"
            if(!parkOnly) {
                signal("UX_READY_PARKED")
                await("actual CarUx NO_SETUP") {!app.controller.state.setupAllowed && node("P단에서 이용할 수 있어요")!=null}
                assertNull(node("차량 연결 QR 코드"));assertNull(node("새 기기로 등록"));assertNull(node("연결"))
                signal("UX_READY_RESTRICTED")
                await("actual Park restored") {app.controller.state.setupAllowed && node("P단에서 이용할 수 있어요")==null}
            } else signal("CONNECTION_ACTUAL_PARK_ONLY_NO_DRIVE_COMMAND")
            child=instrumentation.startActivitySync(Intent(context,VehicleConnectionActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as VehicleConnectionActivity
            await("child connection body") {node("차량 연결")!=null && node("P단에서 이용할 수 있어요")==null}
            val first=child!!;assertTrue(node("뒤로")!!.performAction(AccessibilityNodeInfo.ACTION_CLICK))
            await("child Back finishes") {first.isFinishing}
            child=instrumentation.startActivitySync(Intent(context,VehicleConnectionActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as VehicleConnectionActivity
            await("Home action") {node("홈")!=null}
            val second=child!!;val monitor=instrumentation.addMonitor(MainActivity::class.java.name,null,false)
            try {
                assertTrue(node("홈")!!.performAction(AccessibilityNodeInfo.ACTION_CLICK))
                val home=instrumentation.waitForMonitorWithTimeout(monitor,5000)
                assertNotNull(home);assertFalse(home!!.isFinishing)
                await("Home finishes actual child") {second.isFinishing}
            } finally {instrumentation.removeMonitor(monitor)}
            signal("CONNECTION_ACTUAL_CARUX_BACK_HOME_PASSED")
        } finally {
            info.flags=flags;ui.serviceInfo=info
            instrumentation.runOnMainSync {child?.takeIf {!it.isFinishing}?.finish()}
        }
    }
}
