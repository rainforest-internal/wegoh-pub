package io.wegoh.app.nativeauth

import android.accessibilityservice.AccessibilityServiceInfo
import android.content.Intent
import android.test.InstrumentationTestRunner
import io.wegoh.app.MainActivity
import io.wegoh.app.FirstRunPermissionsCompletedTestCase
import io.wegoh.app.WegoApplication
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.concurrent.atomic.AtomicInteger

class VehicleOptionalScopesLiveTest : FirstRunPermissionsCompletedTestCase() {
    fun testExistingVehiclePhoneApprovalAndReads() {
        check((instrumentation as InstrumentationTestRunner).arguments.getString("allowExistingVehicleScopeApproval")=="true")
        val info=instrumentation.uiAutomation.serviceInfo;val old=info.flags
        info.flags=old or AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS;instrumentation.uiAutomation.serviceInfo=info
        val activity=instrumentation.startActivitySync(Intent(instrumentation.targetContext,MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK).putExtra("screen","pair")) as MainActivity
        val app=activity.application as WegoApplication;val connection=app.vehicleConnection
        fun await(label: String,seconds: Int,predicate: ()->Boolean) {
            val end=android.os.SystemClock.elapsedRealtime()+seconds*1000L
            while(android.os.SystemClock.elapsedRealtime()<end){if(predicate())return;Thread.sleep(100)}
            fail("Live scope verification timeout: $label")
        }
        fun click(label: String) {
            await("visible action",20) {
                instrumentation.uiAutomation.clearCache()
                fun find(n: android.view.accessibility.AccessibilityNodeInfo?): android.view.accessibility.AccessibilityNodeInfo? {
                    if(n==null)return null
                    if(n.isVisibleToUser && n.text?.toString()==label)return n
                    for(i in 0 until n.childCount)find(n.getChild(i))?.let {return it}
                    return null
                }
                var node=instrumentation.uiAutomation.windows.firstNotNullOfOrNull {find(it.root)} ?: return@await false
                while(!node.isClickable)node=node.parent ?: return@await false
                node.isEnabled && node.performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_CLICK)
            }
        }
        try {
            await("parked setup",20){app.controller.state.setupAllowed}
            await("existing connection status",20){connection.status().stage in setOf(VehicleConnection.Stage.READY,VehicleConnection.Stage.LOCKED,VehicleConnection.Stage.CONNECTED,VehicleConnection.Stage.APPROVAL_REQUIRED)}
            val before=connection.status()
            val needsApproval=before.stage!=VehicleConnection.Stage.CONNECTED || !before.approvedOptionalScopes.containsAll(VehicleConnection.Scope.entries) || before.deniedOptionalScopes.isNotEmpty()
            if(before.stage in setOf(VehicleConnection.Stage.READY,VehicleConnection.Stage.LOCKED))click("차량 연결")
            else if(before.stage==VehicleConnection.Stage.CONNECTED && needsApproval)click("권한 추가")
            if(needsApproval) {
                await("visible phone QR",30){connection.status().stage==VehicleConnection.Stage.APPROVAL_REQUIRED}
                instrumentation.sendStatus(0,android.os.Bundle().apply {putString("stage","PHONE_APPROVAL_REQUIRED")})
                await("explicit phone approval",280){
                    check(connection.status().stage !in setOf(VehicleConnection.Stage.DENIED,VehicleConnection.Stage.EXPIRED)) {"PHONE_APPROVAL_NOT_COMPLETED"}
                    connection.status().stage==VehicleConnection.Stage.CONNECTED
                }
            }
            assertEquals(VehicleConnection.Scope.entries.toSet(),connection.status().approvedOptionalScopes)
            val reads=AtomicInteger(0);val failures=AtomicInteger(0)
            connection.readCourses {if(it.isSuccess)reads.incrementAndGet() else failures.incrementAndGet()}
            connection.readPlaylists {if(it.isSuccess)reads.incrementAndGet() else failures.incrementAndGet()}
            await("actual scoped reads",30){reads.get()+failures.get()==2};assertEquals(0,failures.get())
            val directory=File(activity.noBackupFilesDir,"optional-scopes-live-"+java.util.UUID.randomUUID()).apply {mkdir()}
            File(directory,"result.json").writeText(JSONObject().put("existingVehicleProfile",true).put("coursesRead",true).put("playlistsRead",true).put("approvalTransitionObserved",needsApproval)
                .put("approvedOptionalScopes",JSONArray(connection.status().approvedOptionalScopes.map {it.wire}.sorted()))
                .put("limits","Pending-to-connected approval transition only when approvalTransitionObserved=true; operator timing is not independently attested. Actual native reads; no raw account data/credentials retained, no disconnect or key/state cleanup.").toString(2))
            instrumentation.waitForIdleSync()
            instrumentation.uiAutomation.takeScreenshot()?.let {screen ->File(directory,"connected.png").outputStream().use {screen.compress(android.graphics.Bitmap.CompressFormat.PNG,100,it)};screen.recycle()}
            instrumentation.sendStatus(0,android.os.Bundle().apply {putString("stage","LIVE_OPTIONAL_READS_CONFIRMED");putString("proofDirectory",directory.name)})
        } finally {info.flags=old;instrumentation.uiAutomation.serviceInfo=info}
    }
}
