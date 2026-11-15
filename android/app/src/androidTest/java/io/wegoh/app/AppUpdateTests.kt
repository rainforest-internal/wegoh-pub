package io.wegoh.app

import android.test.InstrumentationTestCase
import android.accessibilityservice.AccessibilityServiceInfo
import android.os.SystemClock
import android.view.accessibility.AccessibilityWindowInfo
import org.json.JSONObject
import org.json.JSONArray
import java.net.ServerSocket
import kotlin.concurrent.thread
import android.content.Intent
import android.view.accessibility.AccessibilityNodeInfo
import androidx.activity.compose.setContent
import androidx.compose.runtime.mutableStateOf
import io.wegoh.app.ui.AppUpdatePrompt
import io.wegoh.app.ui.WegoCarTheme

/** Isolated metadata and loopback HTTP only; no APK install/real user record mutation. */
@Suppress("DEPRECATION")
class AppUpdateTests: InstrumentationTestCase() {
    private val cert="b".repeat(64)
    private fun catalog()=JSONObject().put("schemaVersion",1).put("packageName","io.wegoh.app")
        .put("versionCode",5).put("versionName","0.5.0").put("apkSha256","a".repeat(64))
        .put("signingCertificatesSha256",JSONArray().put(cert))
    fun testVersionSignatureIdentityAndUnknownStates() {
        assertEquals(AppUpdateResult.Available(5),AppUpdate.evaluate(catalog().toString(),4,setOf(cert)))
        assertEquals(AppUpdateResult.Current,AppUpdate.evaluate(catalog().toString(),5,setOf(cert)))
        assertEquals(AppUpdateResult.Unknown,AppUpdate.evaluate(catalog().toString(),4,setOf("c".repeat(64))))
        assertEquals(AppUpdateResult.Unknown,AppUpdate.evaluate(catalog().put("packageName","other.app").toString(),4,setOf(cert)))
        assertEquals(AppUpdateResult.Unknown,AppUpdate.evaluate(catalog().put("versionCode","5").toString(),4,setOf(cert)))
        assertEquals(AppUpdateResult.Unknown,AppUpdate.evaluate(catalog().put("downloadUrl","https://evil").toString(),4,setOf(cert)))
        assertEquals(AppUpdateResult.Unknown,AppUpdate.evaluate(" ".repeat(8193),4,setOf(cert)))
        assertEquals(AppUpdateResult.Unknown,AppUpdate("").check(4,setOf(cert)))
        assertEquals("market://detail?package=io.wegoh.app",AppUpdate.marketIntent().data.toString())
        assertEquals(android.content.Intent.ACTION_VIEW,AppUpdate.marketIntent().action)
        for(url in listOf("http://example.com","https://example.com/path","https://user@example.com","https://example.com?x=1")) {
            try {DistributionPolicy.updateEndpoint(url,false);fail("Unsafe update origin")}catch(_: IllegalArgumentException){}
        }
    }
    fun testActualLoopbackStatusAndRedirectBoundary() {
        for(status in listOf(200,404,302)) {
            ServerSocket(0,1,java.net.InetAddress.getByName("127.0.0.1")).use { server ->
                server.soTimeout=5000
                var requested=""
                val worker=thread {
                    server.accept().use { socket ->
                        socket.soTimeout=5000
                        val input=socket.getInputStream().bufferedReader()
                        requested=input.readLine()
                        while(!input.readLine().isNullOrEmpty()){}
                        val body=catalog().toString()
                        val headers="HTTP/1.1 $status Synthetic\r\nContent-Type: application/json\r\nLocation: http://127.0.0.1:1/never\r\nContent-Length: ${body.toByteArray().size}\r\nConnection: close\r\n\r\n"
                        socket.getOutputStream().write((headers+body).toByteArray())
                    }
                }
                val result=AppUpdate("http://127.0.0.1:${server.localPort}").check(4,setOf(cert))
                worker.join(6000)
                assertFalse(worker.isAlive)
                assertEquals("GET /v1/app-release HTTP/1.1",requested)
                if(status==200)assertEquals(AppUpdateResult.Available(5),result) else assertEquals(AppUpdateResult.Unknown,result)
            }
        }
    }
    fun testOfficialDialogNoContinuesYesIsExplicit() {
        val activity=instrumentation.startActivitySync(Intent(instrumentation.targetContext,MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        val show=mutableStateOf(true)
        var accepted=0
        instrumentation.runOnMainSync {activity.setContent {WegoCarTheme {
            if(show.value)AppUpdatePrompt(onYes={accepted++;show.value=false},onNo={show.value=false})
        }}}
        val originalFlags=instrumentation.uiAutomation.serviceInfo.flags
        val service=instrumentation.uiAutomation.serviceInfo
        service.flags=service.flags or AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
        instrumentation.uiAutomation.serviceInfo=service
        fun nodes(): List<AccessibilityNodeInfo> {
            instrumentation.waitForIdleSync()
            instrumentation.uiAutomation.clearCache()
            val found=mutableListOf<AccessibilityNodeInfo>()
            fun walk(node: AccessibilityNodeInfo?) {
                if(node==null || node.packageName?.toString()!=instrumentation.targetContext.packageName)return
                if(node.isVisibleToUser)found.add(node)
                for(i in 0 until node.childCount)walk(node.getChild(i))
            }
            instrumentation.uiAutomation.windows.filter {
                it.type==AccessibilityWindowInfo.TYPE_APPLICATION && it.isActive
            }.forEach {walk(it.root)}
            return found
        }
        fun matches(node: AccessibilityNodeInfo,label: String)=node.contentDescription?.toString()==label || node.text?.toString()==label
        fun diagnostics(values: List<AccessibilityNodeInfo>)=values.mapNotNull {
            (it.text ?: it.contentDescription)?.toString()?.take(160)
        }.distinct().take(30).joinToString(" | ")
        fun awaitPopup() {
            val end=SystemClock.elapsedRealtime()+5000
            var observed=emptyList<AccessibilityNodeInfo>()
            while(SystemClock.elapsedRealtime()<end) {
                observed=nodes()
                if(listOf("최신 버전이 존재합니다.","업데이트를 위해 페이지를 이동할까요?","나중에","업데이트").all {label->
                    observed.any {matches(it,label)}
                })return
                Thread.yield()
            }
            fail("Visible current-app update popup did not become ready: ${diagnostics(observed)}")
        }
        fun click(label: String) {
            val end=SystemClock.elapsedRealtime()+5000
            var observed=emptyList<AccessibilityNodeInfo>()
            while(SystemClock.elapsedRealtime()<end) {
                observed=nodes()
                for(candidate in observed.filter {matches(it,label)}) {
                    var node: AccessibilityNodeInfo?=candidate
                    repeat(5) {
                        if(node?.isVisibleToUser==true && node?.isEnabled==true && node?.isClickable==true &&
                            node?.performAction(AccessibilityNodeInfo.ACTION_CLICK)==true)return
                        node=node?.parent
                    }
                }
                Thread.yield()
            }
            fail("Missing current-app update choice $label: ${diagnostics(observed)}")
        }
        try {
            awaitPopup()
            click("나중에");instrumentation.waitForIdleSync()
            assertFalse(show.value);assertEquals(0,accepted);assertFalse(activity.isFinishing)
            instrumentation.runOnMainSync {show.value=true}
            awaitPopup()
            click("업데이트");instrumentation.waitForIdleSync()
            assertEquals(1,accepted);assertFalse(show.value)
        } finally {
            val restored=instrumentation.uiAutomation.serviceInfo
            restored.flags=originalFlags;instrumentation.uiAutomation.serviceInfo=restored
            instrumentation.runOnMainSync {activity.recreate()}
        }
    }
}
