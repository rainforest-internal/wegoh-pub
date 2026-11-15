package io.wegoh.app

import android.content.Intent
import android.os.Bundle
import android.view.KeyEvent
import android.view.WindowInsets
import android.view.WindowManager
import android.view.inputmethod.InputMethodManager
import android.widget.EditText
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.ComposeView
import androidx.compose.ui.viewinterop.AndroidView
import io.wegoh.app.ui.*

/** Emulator framework inputs and actual SDK callbacks; no production debug controls. */
@Suppress("DEPRECATION")
@android.annotation.TargetApi(34)
class EmulatorBoundaryTests: FirstRunPermissionsCompletedTestCase() {
    private lateinit var activity: MainActivity
    private fun start(screen: String="discover") {
        activity=instrumentation.startActivitySync(Intent(instrumentation.targetContext,MainActivity::class.java)
            .putExtra("screen",screen).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
        waitFor("Ready") {activity.controller.state.setupAllowed && activity.controller.state.storageReady}
        instrumentation.waitForIdleSync();Thread.sleep(300)
    }
    private fun waitFor(label: String,predicate: ()->Boolean) {
        val end=System.currentTimeMillis()+20000
        while(System.currentTimeMillis()<end){var yes=false;instrumentation.runOnMainSync{yes=predicate()};if(yes)return;Thread.sleep(100)}
        fail("$label; lifecycle=${activity.lifecycle.currentState}; focus=${activity.hasWindowFocus()}; task=${activity.taskId}; root=${activity.isTaskRoot}")
    }
    private fun nodes(): List<android.view.accessibility.AccessibilityNodeInfo> {
        if(android.os.Build.VERSION.SDK_INT>=34)instrumentation.uiAutomation.clearCache()
        val out=mutableListOf<android.view.accessibility.AccessibilityNodeInfo>()
        fun walk(n: android.view.accessibility.AccessibilityNodeInfo?){if(n!=null){out.add(n);for(i in 0 until n.childCount)walk(n.getChild(i))}}
        walk(instrumentation.uiAutomation.rootInActiveWindow);return out
    }
    private fun visible(label: String)=nodes().any{it.text?.toString()==label || it.contentDescription?.toString()==label}
    private fun awaitVisible(label: String) {
        val end=System.currentTimeMillis()+7000
        while(System.currentTimeMillis()<end){if(visible(label))return;Thread.sleep(100)}
        fail("Missing visible $label; nodes="+nodes().joinToString { "${it.text}/${it.contentDescription}" })
    }
    private fun click(label: String) {
        awaitVisible(label)
        val matches=nodes().filter{it.text?.toString()==label || it.contentDescription?.toString()==label}
            .sortedByDescending{it.isClickable && it.contentDescription?.toString()==label}
        for(match in matches){var n: android.view.accessibility.AccessibilityNodeInfo?=match
            repeat(6){if(n?.performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_CLICK)==true){Thread.sleep(350);return};n=n?.parent}}
        fail("Missing $label")
    }
    fun testActualStandardBackHidesRootWithoutFinishing() {
        start("rooms");click("방 만들기");awaitVisible("공유 설정")
        instrumentation.sendKeyDownUpSync(KeyEvent.KEYCODE_BACK);Thread.sleep(400)
        awaitVisible("여행방");assertFalse(visible("공유 설정"))
        instrumentation.sendKeyDownUpSync(KeyEvent.KEYCODE_BACK);awaitVisible("발견")
        instrumentation.sendKeyDownUpSync(KeyEvent.KEYCODE_BACK)
        waitFor("Root hidden") {!activity.hasWindowFocus()}
        assertFalse("Back hides, not finishes",activity.isFinishing)
    }
    fun testBackgroundLocationReceiptHasNoAudioAndResumeDoesNotReplay() {
        start("journeys")
        val base=instrumentation.targetContext;val id="boundary-runtime-"+java.util.UUID.randomUUID()
        val dir=java.io.File(base.cacheDir,id).apply {mkdirs()}
        val isolated=object: android.content.ContextWrapper(base) {
            override fun getApplicationContext(): android.content.Context=this
            override fun getFilesDir()=java.io.File(dir,"files").apply {mkdirs()}
            override fun getNoBackupFilesDir()=java.io.File(dir,"no-backup").apply {mkdirs()}
            override fun getSharedPreferences(name: String,mode: Int)=base.getSharedPreferences("$id-$name",mode)
            override fun deleteSharedPreferences(name: String)=base.deleteSharedPreferences("$id-$name")
        }
        fun originals()=PackRepository(base).list().sortedBy {it.key}.joinToString {it.key+ProgressStore(base).read(it).sorted().toString()}+VisitedPlaces(base).list().toString()
        val before=originals();lateinit var controller: WegoController
        instrumentation.runOnMainSync {controller=WegoController(isolated,base.applicationContext);controller.setVisible(true)}
        waitFor("Isolated parked owner") {controller.state.setupAllowed && controller.state.storageReady}
        try {
            instrumentation.runOnMainSync {
                controller.select("city-story@1");controller.reset();assertTrue(controller.consentLocation())
                controller.begin("city-story@1")
            }
            waitFor("Active") {controller.state.active}
            instrumentation.runOnMainSync {activity.startActivity(Intent(android.provider.Settings.ACTION_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))}
            waitFor("Background") {!activity.hasWindowFocus()}
            instrumentation.runOnMainSync {controller.setVisible(false)}
            instrumentation.sendStatus(0,Bundle().apply{putString("stream","\nBACKGROUND_GPS_READY\n")})
            waitFor("Real background SDK receipt") {controller.state.completed.contains("gangnam")}
            assertTrue(controller.state.history.contains("AUDIO_SKIPPED_BACKGROUND"))
            assertFalse(controller.state.history.contains("AUDIO_STARTED"))
            // Reordering an existing task does not create an Activity for startActivitySync to await.
            instrumentation.runOnMainSync {activity.startActivity(Intent(activity,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT))}
            waitFor("Returned to foreground") {activity.hasWindowFocus()}
            instrumentation.runOnMainSync {controller.setVisible(true)}
            Thread.sleep(700);assertFalse(controller.state.history.contains("AUDIO_STARTED"))
            assertEquals(setOf("gangnam"),ProgressStore(isolated).read(controller.state.selected!!))
        }finally{instrumentation.runOnMainSync{controller.close()};assertEquals("Background SDK test must preserve original user records",before,originals())}
    }
    fun testActualImeAndNonInputDialogInsets() {
        start();val showing=mutableStateOf(false);lateinit var editor: EditText;var editorReady=false
        var dialog: android.view.Window?=null
        val input=activity.getSystemService(InputMethodManager::class.java)
        try {
            instrumentation.runOnMainSync {
                activity.window.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE)
                activity.setContent {WegoCarTheme {
                    AndroidView(modifier=Modifier.fillMaxSize(),factory={EditText(it).apply{editor=this;editorReady=true;setSingleLine();setText("합성 입력")}})
                    if(showing.value)CarPopup("입력 없는 안내",{showing.value=false},body={CarText("정차 중 팝업 시험")},actions={CarAction("확인",CarSymbol.Check,{showing.value=false})})
                }}
            }
            instrumentation.waitForIdleSync();Thread.sleep(300)
            instrumentation.runOnMainSync {editor.requestFocus();input.showSoftInput(editor,InputMethodManager.SHOW_FORCED)}
            waitFor("Actual IME visible") {activity.window.decorView.rootWindowInsets?.isVisible(WindowInsets.Type.ime())==true}
            instrumentation.runOnMainSync {showing.value=true}
            instrumentation.waitForIdleSync();Thread.sleep(300)
            instrumentation.runOnMainSync {
                fun find(view: android.view.View): android.view.Window? {
                    if(view is androidx.compose.ui.window.DialogWindowProvider)return view.window
                    if(view is android.view.ViewGroup)for(i in 0 until view.childCount)find(view.getChildAt(i))?.let{return it}
                    return null
                }
                dialog=android.view.inspector.WindowInspector.getGlobalWindowViews().filter{it.isShown}.mapNotNull(::find).lastOrNull()
                assertNotNull(dialog)
                assertEquals(0,dialog!!.attributes.fitInsetsTypes and WindowInsets.Type.ime())
                assertEquals(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_NOTHING,dialog!!.attributes.softInputMode and WindowManager.LayoutParams.SOFT_INPUT_MASK_ADJUST)
            }
            val before=dialog!!.decorView.height
            instrumentation.runOnMainSync {input.hideSoftInputFromWindow(editor.windowToken,0)}
            Thread.sleep(400)
            assertEquals("IME dismissal must not move/resize non-input dialog",before,dialog!!.decorView.height)
        }finally{instrumentation.runOnMainSync {if(editorReady)input.hideSoftInputFromWindow(editor.windowToken,0);showing.value=false}}
    }
    override fun tearDown(){if(::activity.isInitialized)instrumentation.runOnMainSync{activity.finish()};super.tearDown()}
}
