package io.wegoh.app

import android.app.Activity
import android.app.Application
import android.app.Dialog
import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.SystemClock
import android.test.InstrumentationTestCase
import android.view.accessibility.AccessibilityNodeInfo
import androidx.activity.compose.LocalActivityResultRegistryOwner
import androidx.activity.compose.setContent
import androidx.activity.result.ActivityResultRegistry
import androidx.activity.result.ActivityResultRegistryOwner
import androidx.activity.result.contract.ActivityResultContract
import androidx.compose.runtime.*
import androidx.compose.ui.platform.LocalContext
import androidx.core.app.ActivityOptionsCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.LifecycleRegistry
import androidx.lifecycle.compose.LocalLifecycleOwner
import io.wegoh.app.ui.CarText
import io.wegoh.app.ui.CarWindowVisibility
import io.wegoh.app.ui.WegoCarTheme
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean

@Suppress("DEPRECATION")
class FirstRunPermissionsUiTest: InstrumentationTestCase() {
    private fun onMain(action: ()->Unit)=instrumentation.runOnMainSync(action)
    private fun await(label: String,condition: ()->Boolean) {
        val end=SystemClock.uptimeMillis()+10000
        while(SystemClock.uptimeMillis()<end) {if(condition())return;Thread.sleep(50)}
        fail("Permission entry timeout: $label")
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
    private fun action(label: String): AccessibilityNodeInfo? {
        var n=node(label)
        while(n!=null && !n.isClickable)n=n.parent
        return n
    }
    private fun click(label: String) {
        val end=SystemClock.uptimeMillis()+10000
        while(SystemClock.uptimeMillis()<end) {
            val target=action(label)
            if(target?.isEnabled==true && runCatching {target.performAction(AccessibilityNodeInfo.ACTION_CLICK)}.getOrDefault(false)) {
                instrumentation.waitForIdleSync()
                return
            }
            Thread.sleep(50)
        }
        fail("Permission entry click failed: $label")
    }
    private fun awaitAction(label: String,enabled: Boolean): AccessibilityNodeInfo {
        val end=SystemClock.uptimeMillis()+10000
        while(SystemClock.uptimeMillis()<end) {
            val target=action(label)
            if(target!=null && target.isEnabled==enabled)return target
            Thread.sleep(50)
        }
        error("Permission entry action missing: $label enabled=$enabled")
    }
    private class Requests: ActivityResultRegistry(),ActivityResultRegistryOwner {
        override val activityResultRegistry get()=this
        var launches=0
        private var requestCode=0
        override fun <I,O> onLaunch(code: Int,contract: ActivityResultContract<I,O>,input: I,options: ActivityOptionsCompat?) {
            requestCode=code;launches++
        }
        fun deny() {dispatchResult(requestCode,emptyMap<String,Boolean>())}
    }
    private class TestLifecycleOwner: LifecycleOwner {
        val registry=LifecycleRegistry(this)
        override val lifecycle get()=registry
    }
    private inner class Fixture(val introduction: Boolean) {
        val base=instrumentation.targetContext
        val profile="first_permissions_ui_"+java.util.UUID.randomUUID()
        val context=object: ContextWrapper(base) {
            override fun getSharedPreferences(name: String,mode: Int)=base.getSharedPreferences(profile+name,mode)
            override fun checkSelfPermission(permission: String)=PackageManager.PERMISSION_DENIED
        }
        val requests=Requests()
        val registryAvailable=mutableStateOf(true)
        val setupAllowed=mutableStateOf(true)
        val foreground=mutableStateOf(true)
        val policy=AtomicBoolean(true)
        val owner=TestLifecycleOwner()
        lateinit var guide: FirstRunGuide
        @Volatile var host: SafFrameworkHarnessActivity?=null
        var cover: Dialog?=null
        val callbacks=object: Application.ActivityLifecycleCallbacks {
            override fun onActivityCreated(activity: Activity,savedInstanceState: Bundle?) {
                if(activity !is SafFrameworkHarnessActivity)return
                host=activity
                activity.setContent {
                    val windows=remember(activity) {CarWindowVisibility(activity) {}}
                    DisposableEffect(windows) {onDispose {windows.close()}}
                    val locals=listOfNotNull(LocalContext provides context,
                        if(registryAvailable.value)LocalActivityResultRegistryOwner provides requests else null,
                        LocalLifecycleOwner provides owner).toTypedArray()
                    CompositionLocalProvider(*locals) {
                        WegoCarTheme {
                            FirstRunPermissionEntry(guide.completed,!introduction,setupAllowed.value,foreground.value && windows.state.focused,
                                canRequest={policy.get() && activity.hasWindowFocus() &&
                                    activity.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)}) {
                                if(introduction && !guide.completed)ConnectionEntry(fullScreen=true) {
                                    FirstRunWalkthrough(setupAllowed.value && windows.state.focused,
                                        canInteract={policy.get() && activity.hasWindowFocus()},onComplete=guide::complete)
                                } else CarText("Connected content")
                            }
                        }
                    }
                }
            }
            override fun onActivityStarted(activity: Activity) {}
            override fun onActivityResumed(activity: Activity) {}
            override fun onActivityPaused(activity: Activity) {}
            override fun onActivityStopped(activity: Activity) {}
            override fun onActivitySaveInstanceState(activity: Activity,state: Bundle) {}
            override fun onActivityDestroyed(activity: Activity) {}
        }
        fun launch() {
            host=instrumentation.startActivitySync(Intent(base,SafFrameworkHarnessActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_MULTIPLE_TASK)) as SafFrameworkHarnessActivity
            await("fixture focus") {host?.hasWindowFocus()==true}
        }
        fun relaunch() {
            val old=requireNotNull(host)
            onMain {old.finish()};await("fixture destroyed") {old.isDestroyed}
            launch()
        }
        fun resumeCycle()=onMain {
            owner.registry.currentState=Lifecycle.State.STARTED
            owner.registry.currentState=Lifecycle.State.RESUMED
        }
        fun capture(name: String) {
            val frames=java.util.concurrent.CountDownLatch(1)
            onMain {requireNotNull(host).window.decorView.postOnAnimation {
                requireNotNull(host).window.decorView.postOnAnimation {frames.countDown()}
            }}
            assertTrue(frames.await(3,java.util.concurrent.TimeUnit.SECONDS))
            instrumentation.waitForIdleSync()
            val image=requireNotNull(instrumentation.uiAutomation.takeScreenshot())
            File(base.cacheDir,name+".png").outputStream().use {image.compress(android.graphics.Bitmap.CompressFormat.PNG,100,it)}
            image.recycle()
        }
    }
    private fun withFixture(introduction: Boolean=false,registryAvailable: Boolean=true,test: (Fixture)->Unit) {
        val f=Fixture(introduction)
        val app=instrumentation.targetContext.applicationContext as Application
        onMain {
            f.guide=FirstRunGuide(f.context)
            f.registryAvailable.value=registryAvailable
            f.owner.registry.currentState=Lifecycle.State.RESUMED
            app.registerActivityLifecycleCallbacks(f.callbacks)
        }
        try {f.launch();test(f)} finally {
            val host=f.host
            onMain {f.cover?.dismiss();host?.finish();app.unregisterActivityLifecycleCallbacks(f.callbacks)}
            if(host!=null)await("fixture cleanup") {host.isDestroyed}
            f.context.getSharedPreferences("first_run_permissions",Context.MODE_PRIVATE).edit().clear().commit()
            f.context.getSharedPreferences("first_run_guide",Context.MODE_PRIVATE).edit().clear().commit()
        }
    }
    fun testDrivingPreservesConnectedContentAndDefersUntilParked()=withFixture {f->
        onMain {f.policy.set(false);f.setupAllowed.value=false}
        await("connected body while driving") {node("Connected content")!=null}
        assertNull(node("앱 권한"));assertEquals(0,f.requests.launches)
        f.capture("first-permissions-driving-body")
        onMain {f.policy.set(true);f.setupAllowed.value=true}
        await("parked permission entry") {node("앱 권한")!=null}
        assertEquals(0,f.requests.launches)
        f.capture("first-permissions-parked")
    }
    fun testStartAndSkipBothShowPermissions() {
        for(skip in listOf(false,true))withFixture(introduction=true) {f->
            await("introduction") {node("경로를 차에서 시작해요")!=null}
            if(!skip)f.capture("vehicle-onboarding-drive")
            if(skip)click("건너뛰기") else {
                click("다음")
                await("playlist introduction") {node("내 음악을 차에서")!=null}
                f.capture("vehicle-onboarding-music")
                click("다음")
                await("connection introduction") {node("휴대전화로 차량 연결")!=null}
                f.capture("vehicle-onboarding-connect")
                click("계속")
            }
            await("permission entry after introduction") {node("앱 권한")!=null}
            if(!skip)f.capture("vehicle-onboarding-permissions")
            assertNull(node("Connected content"))
        }
    }
    fun testDeniedRequestContinuesAndDoesNotRecur()=withFixture {f->
        click("권한 설정");assertEquals(1,f.requests.launches)
        onMain {f.requests.deny()}
        await("body after denial") {node("Connected content")!=null}
        f.relaunch()
        await("persisted denial choice") {node("Connected content")!=null}
        assertNull(node("앱 권한"));assertEquals(1,f.requests.launches)
    }
    fun testLaterContinuesAndDoesNotRecur()=withFixture {f->
        click("나중에")
        await("body after later") {node("Connected content")!=null}
        f.relaunch()
        await("persisted later choice") {node("Connected content")!=null}
        assertNull(node("앱 권한"));assertEquals(0,f.requests.launches)
    }
    fun testLostResultRecoversOnResumeAndAllowsRetry()=withFixture {f->
        click("권한 설정");assertEquals(1,f.requests.launches)
        awaitAction("권한 설정",enabled=false)
        f.resumeCycle()
        await("lost result recovery") {action("권한 설정")?.isEnabled==true}
        click("권한 설정");assertEquals(2,f.requests.launches)
        onMain {f.requests.deny()}
        await("retried request completes") {node("Connected content")!=null}
    }
    fun testRestoredPendingRequestWithoutDialogAllowsLater()=withFixture {f->
        click("권한 설정");assertEquals(1,f.requests.launches)
        val old=requireNotNull(f.host)
        onMain {old.recreate()}
        await("recreated host") {f.host!==old && f.host?.hasWindowFocus()==true}
        await("restored pending recovery") {action("나중에")?.isEnabled==true}
        click("나중에")
        await("body after restored request") {node("Connected content")!=null}
        assertEquals(1,f.requests.launches)
    }
    fun testFocusLossKeepsGuideAndDoesNotDuplicateActiveRequest()=withFixture {f->
        onMain {f.foreground.value=false}
        await("unfocused guide stays visible") {node("앱 권한")!=null && action("권한 설정")?.isEnabled==false}
        awaitAction("나중에",enabled=false)
        onMain {f.foreground.value=true}
        await("focused guide") {action("권한 설정")?.isEnabled==true}
        val staleRequest=awaitAction("권한 설정",enabled=true)
        click("권한 설정")
        onMain {f.cover=Dialog(requireNotNull(f.host)).apply {
            setContentView(android.widget.TextView(context).apply {text="Synthetic OS permission window"});show()
        }}
        await("permission window owns focus") {f.host?.hasWindowFocus()==false}
        f.resumeCycle();instrumentation.waitForIdleSync()
        staleRequest.performAction(AccessibilityNodeInfo.ACTION_CLICK)
        instrumentation.waitForIdleSync()
        assertEquals(1,f.requests.launches)
        onMain {f.cover!!.dismiss()}
        await("guide remains after focus return") {node("앱 권한")!=null}
        await("buttons recover after window closes") {action("권한 설정")?.isEnabled==true}
        assertEquals(1,f.requests.launches)
    }
    fun testLivePolicyBlocksStaleButtonBeforeRecomposition()=withFixture {f->
        await("enabled parked button") {action("권한 설정")?.isEnabled==true}
        f.policy.set(false)
        click("권한 설정")
        assertEquals(0,f.requests.launches)
        assertNotNull(node("앱 권한"))
        f.policy.set(true)
        click("나중에")
        await("body after allowed choice") {node("Connected content")!=null}
    }
    fun testMissingRegistryDisablesRequestAndCompletedEntryNeedsNoOwner()=withFixture(registryAvailable=false) {f->
        await("guide without registry owner") {node("앱 권한")!=null}
        awaitAction("권한 설정",enabled=false)
        assertEquals(0,f.requests.launches)
        click("나중에")
        await("completed entry without registry owner") {node("Connected content")!=null}
        f.relaunch()
        await("completed relaunch without registry owner") {node("Connected content")!=null}
        assertEquals(0,f.requests.launches)
    }
    fun testIneligibleEntryNeedsNoRegistryOwner()=withFixture(introduction=true,registryAvailable=false) {f->
        await("introduction without registry owner") {node("경로를 차에서 시작해요")!=null}
        assertEquals(0,f.requests.launches)
        click("건너뛰기")
        await("eligible guide without registry owner") {node("앱 권한")!=null}
        awaitAction("권한 설정",enabled=false)
        assertEquals(0,f.requests.launches)
    }
}
