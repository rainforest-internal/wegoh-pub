package io.wegoh.app

import android.content.Intent
import android.graphics.Rect
import android.test.InstrumentationTestCase
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import io.wegoh.app.ui.*
import org.json.JSONArray
import org.json.JSONObject

/** Actual constrained Dialog footer, not a simulated physical production display. */
@Suppress("DEPRECATION")
class PopupRoleTests: InstrumentationTestCase() {
    fun testHorizontalAndNarrowVerticalRoles() {
        val activity=instrumentation.startActivitySync(Intent(instrumentation.targetContext,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
        val rows=JSONArray()
        fun find(label: String): android.view.accessibility.AccessibilityNodeInfo {
            fun walk(n: android.view.accessibility.AccessibilityNodeInfo?): android.view.accessibility.AccessibilityNodeInfo? {
                if(n==null)return null
                if(n.isVisibleToUser && n.contentDescription?.toString()==label)return n
                for(i in 0 until n.childCount)walk(n.getChild(i))?.let{return it}
                return null
            }
            return walk(instrumentation.uiAutomation.rootInActiveWindow) ?: error("Missing action $label")
        }
        fun click(label: String) {
            var target: android.view.accessibility.AccessibilityNodeInfo?=find(label)
            repeat(6) {
                if(target?.isEnabled==true && target?.performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_CLICK)==true){instrumentation.waitForIdleSync();return}
                target=target?.parent
            }
            error("No actionable parent for $label")
        }
        try {for(width in listOf(808,300)) {
            var confirmed=0;var cancelled=0
            instrumentation.runOnMainSync {activity.setContent {WegoCarTheme {Dialog(onDismissRequest={}) {
                CompositionLocalProvider(LocalCarLargeAction provides true) {
                    CarPopupActions(Modifier.width(width.dp)) {
                        CarAction("확인",CarSymbol.Check,{confirmed++},Modifier.weight(1f),primary=true)
                        CarAction("취소",CarSymbol.Close,{cancelled++},Modifier.weight(1f))
                    }
                }
            }}}}
            instrumentation.waitForIdleSync();Thread.sleep(500)
            if(android.os.Build.VERSION.SDK_INT>=34)instrumentation.uiAutomation.clearCache()
            val confirmation=Rect().also{find("확인").getBoundsInScreen(it)};val cancellation=Rect().also{find("취소").getBoundsInScreen(it)}
            if(width==808)assertTrue("Horizontal confirmation left / cancellation right",confirmation.right<cancellation.left)
            else assertTrue("Vertical confirmation above cancellation",confirmation.bottom<cancellation.top)
            click("확인")
            assertEquals(1,confirmed);assertEquals(0,cancelled)
            click("취소")
            assertEquals(1,confirmed);assertEquals(1,cancelled)
            rows.put(JSONObject().put("widthDp",width).put("confirmation",confirmation.toShortString()).put("cancellation",cancellation.toShortString()).put("confirmationCallback",confirmed).put("cancellationCallback",cancelled))
        }
        java.io.File(activity.cacheDir,"popup-role-validation.json").writeText(rows.toString(2))
        } finally {instrumentation.runOnMainSync {activity.finish()}}
    }
}
