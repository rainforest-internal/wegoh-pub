package io.wegoh.app

import android.accessibilityservice.AccessibilityServiceInfo
import android.content.Intent
import android.os.SystemClock
import android.test.InstrumentationTestCase
import android.test.InstrumentationTestRunner
import android.util.Base64
import android.view.accessibility.AccessibilityNodeInfo
import androidx.activity.compose.setContent
import androidx.compose.runtime.mutableStateOf
import io.wegoh.app.nativeauth.NativeDeviceIdentity
import io.wegoh.app.nativeauth.VehicleConnection
import io.wegoh.app.nativebusiness.NativeBusinessPanel
import io.wegoh.app.ui.CarWindowVisibility
import io.wegoh.app.ui.ProvideCarWindowVisibility
import io.wegoh.app.ui.WegoCarTheme
import java.io.File
import java.util.UUID

@Suppress("DEPRECATION")
class NativeCommandStatusUiTest: InstrumentationTestCase() {
    private fun countVisible(text: String): Int {
        val automation=instrumentation.uiAutomation
        if(android.os.Build.VERSION.SDK_INT>=34)automation.clearCache()
        fun count(node: AccessibilityNodeInfo?): Int {
            if(node==null)return 0
            val matches=node.isVisibleToUser && node.text?.contains(text)==true
            return (if(matches)1 else 0)+(0 until node.childCount).sumOf {count(node.getChild(it))}
        }
        return automation.windows.mapNotNull {it.root}
            .filter {it.packageName?.toString()==instrumentation.targetContext.packageName}.sumOf(::count)
    }

    private fun await(label: String,timeoutMillis: Long=20_000,condition: ()->Boolean) {
        val deadline=SystemClock.elapsedRealtime()+timeoutMillis
        while(SystemClock.elapsedRealtime()<deadline) {
            if(condition())return
            Thread.sleep(120)
        }
        fail("Vehicle request screen did not reach $label")
    }

    fun testVehicleRequestStatusUpdatesAndClearsWithoutCurrentAccess() {
        val args=(instrumentation as InstrumentationTestRunner).arguments
        val context=instrumentation.targetContext
        val ca=NativeDeviceIdentity.parseCertificates(String(Base64.decode(args.getString("ca"),Base64.DEFAULT),Charsets.US_ASCII)).single()
        val connection=VehicleConnection.synthetic(context,"cmd_"+UUID.randomUUID().toString().replace("-",""),
            args.getString("port")!!.toInt(),ca,args.getString("eventsPort")!!.toInt())
        val automation=instrumentation.uiAutomation
        val info=automation.serviceInfo
        val flags=info.flags
        val markers=listOf("command-status-drop","command-status-dropped","command-status-confirmed",
            "command-status-repeat","command-status-repeated","command-status-expired","command-status-denied")
        val nonce=args.getString("gpsNonce")!!
        fun mark(name: String) {File(context.cacheDir,name).writeText(nonce)}
        fun marked(name: String): Boolean {
            val file=File(context.cacheDir,name)
            return file.exists() && file.readText()==nonce
        }
        fun cleanMarkers()=markers.forEach {File(context.cacheDir,it).delete()}
        val allowed=mutableStateOf(true)
        val mounted=mutableStateOf(true)
        var activity: TripScreensPreviewActivity?=null
        var windows: CarWindowVisibility?=null
        try {
            cleanMarkers()
            info.flags=flags or AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
            automation.serviceInfo=info
            val preview=instrumentation.startActivitySync(Intent(context,TripScreensPreviewActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_MULTIPLE_TASK)) as TripScreensPreviewActivity
            activity=preview
            instrumentation.runOnMainSync {
                connection.setForeground(true);connection.setSetupAllowed(true);connection.start("Synthetic command status",emptySet())
            }
            await("authenticated connection",35_000) {connection.status().stage==VehicleConnection.Stage.CONNECTED}
            instrumentation.runOnMainSync {
                windows=CarWindowVisibility(preview) {}
                preview.setContent {WegoCarTheme {ProvideCarWindowVisibility(requireNotNull(windows)) {
                    if(mounted.value)NativeBusinessPanel(connection,allowed.value,{},{},initialSection="COMMANDS")
                }}}
            }
            await("queued") {countVisible("설정 온도")==1 && countVisible("대기 중")==1}
            mark("command-status-drop")
            await("connection lost with request pending") {
                marked("command-status-dropped") && countVisible("저장된 내용이에요")==1 && countVisible("대기 중")==1
            }
            mark("command-status-confirmed")
            fun confirmed()=countVisible("설정 온도")==1 && countVisible("동작 확인됨")==1 && countVisible("대기 중")==0
            await("latest state after reconnect",condition=::confirmed)
            mark("command-status-repeat")
            await("confirmed after repeated invalidation") {marked("command-status-repeated") && confirmed()}
            SystemClock.sleep(2_100)
            mark("command-status-expired")
            await("confirmed history and expired request") {
                countVisible("설정 온도")==1 && countVisible("동작 확인됨")==1 && countVisible("시간 만료")==1
            }
            instrumentation.runOnMainSync {allowed.value=false}
            await("park restriction") {countVisible("정차 후 이용해 주세요")==1 && countVisible("동작 확인됨")==0}
            instrumentation.runOnMainSync {mounted.value=false}
            await("leave vehicle requests") {countVisible("정차 후 이용해 주세요")==0}
            instrumentation.runOnMainSync {allowed.value=true;mounted.value=true}
            await("re-entry after expiry") {countVisible("동작 확인됨")==1 && countVisible("시간 만료")==1}
            mark("command-status-denied")
            await("permission denial") {
                val accessNotice=countVisible("리모컨 수신 설정을 확인해 주세요")>0 ||
                    countVisible("연결과 이용 권한을 확인해 주세요")>0
                accessNotice && countVisible("설정 온도")==0 && countVisible("동작 확인됨")==0 && countVisible("시간 만료")==0
            }
            instrumentation.runOnMainSync {connection.disconnect()}
            await("disconnected") {connection.status().stage!=VehicleConnection.Stage.CONNECTED}
        } finally {
            instrumentation.runOnMainSync {connection.close();windows?.close();activity?.finish()}
            cleanMarkers()
            info.flags=flags;automation.serviceInfo=info
        }
    }
}
