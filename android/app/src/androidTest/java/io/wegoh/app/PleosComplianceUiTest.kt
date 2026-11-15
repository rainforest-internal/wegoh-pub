package io.wegoh.app

import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Color as AndroidColor
import android.graphics.Rect
import android.os.Build
import android.os.SystemClock
import android.test.InstrumentationTestCase
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.inspector.WindowInspector
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.boundsInWindow
import androidx.compose.ui.platform.ViewRootForTest
import androidx.compose.ui.semantics.*
import androidx.compose.ui.unit.dp
import io.wegoh.app.ui.*
import java.io.File
import org.json.JSONArray
import org.json.JSONObject
import kotlin.math.abs
import kotlin.math.roundToInt
import kotlin.math.sqrt

/**
 * Pixel/interaction checks on the current emulator/device, with synthetic content.
 * Does not claim hardware verification of a different device mode or CarUx state.
 * Independent expected values come from the original design assets:
 * - variables 67:28787..67:28790: popup corner radii S48/L42/W40/WF51.
 * - basic-button states: disabled/loading cannot activate; loading has a loader.
 * - interaction guide: the entire pressed surface shrinks to 95%.
 * - intro guide: day/night brightness and contrast follow the active mode.
 */
@Suppress("DEPRECATION")
class PleosComplianceUiTest : InstrumentationTestCase() {
    private lateinit var host: TripScreensPreviewActivity
    private val density get() = host.resources.displayMetrics.density
    private data class Node(val bounds: Rect, val enabled: Boolean, val progress: Boolean)

    private fun start() {
        host = instrumentation.startActivitySync(
            Intent(instrumentation.targetContext, TripScreensPreviewActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_MULTIPLE_TASK)
        ) as TripScreensPreviewActivity
    }

    private fun finish() = instrumentation.runOnMainSync { host.finish() }

    private fun render(content: @Composable () -> Unit) {
        instrumentation.runOnMainSync { host.setContent(content = content) }
        instrumentation.waitForIdleSync()
    }

    private fun await(message: String, condition: () -> Boolean) {
        val deadline = SystemClock.uptimeMillis() + 8000
        while (SystemClock.uptimeMillis() < deadline) {
            if (condition()) return
            Thread.sleep(40)
        }
        fail(message)
    }

    private fun windowBounds(): Rect {
        var bounds = Rect()
        instrumentation.runOnMainSync {
            val origin = IntArray(2)
            host.window.decorView.getLocationOnScreen(origin)
            bounds = Rect(origin[0], origin[1], origin[0] + host.window.decorView.width,
                origin[1] + host.window.decorView.height)
        }
        return bounds
    }

    private fun semanticNodes(label: String? = null, actionable: Boolean = false): List<Node> {
        val result = mutableListOf<Node>()
        instrumentation.runOnMainSync {
            fun inspect(view: View) {
                if (view is ViewRootForTest) {
                    val origin = IntArray(2)
                    view.rootView.getLocationOnScreen(origin)
                    view.semanticsOwner.getAllSemanticsNodes(mergingEnabled = false).forEach { node ->
                        val config = node.config
                        val matches = label == null ||
                            config.getOrNull(SemanticsProperties.ContentDescription)?.contains(label) == true ||
                            config.getOrNull(SemanticsProperties.Text)?.any { it.text == label } == true
                        if (matches && (!actionable || config.contains(SemanticsActions.OnClick))) {
                            val r = node.boundsInWindow
                            result += Node(Rect(r.left.roundToInt() + origin[0], r.top.roundToInt() + origin[1],
                                r.right.roundToInt() + origin[0], r.bottom.roundToInt() + origin[1]),
                                !config.contains(SemanticsProperties.Disabled),
                                config.contains(SemanticsProperties.ProgressBarRangeInfo))
                        }
                    }
                }
                if (view is ViewGroup) for (index in 0 until view.childCount) inspect(view.getChildAt(index))
            }
            val windows = if (Build.VERSION.SDK_INT >= 29) WindowInspector.getGlobalWindowViews()
                else listOf(host.window.decorView)
            windows.forEach(::inspect)
        }
        return result
    }

    private fun control(label: String): Node = semanticNodes(label, actionable = true).single()

    private fun pointer(action: Int, bounds: Rect, downTime: Long) {
        val event = MotionEvent.obtain(downTime, SystemClock.uptimeMillis(), action,
            bounds.exactCenterX(), bounds.exactCenterY(), 0)
        try { instrumentation.sendPointerSync(event) } finally { event.recycle() }
    }

    private fun tap(bounds: Rect) {
        val downTime = SystemClock.uptimeMillis()
        pointer(MotionEvent.ACTION_DOWN, bounds, downTime)
        pointer(MotionEvent.ACTION_UP, bounds, downTime)
        instrumentation.waitForIdleSync()
    }

    private fun shot(name: String): Bitmap {
        val bitmap = requireNotNull(instrumentation.uiAutomation.takeScreenshot())
        File(instrumentation.targetContext.cacheDir, "pleos-compliance-$name.png").outputStream().use {
            bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)
        }
        return bitmap
    }

    private fun writeMeasurements(name: String, rows: JSONArray) {
        File(instrumentation.targetContext.cacheDir, "pleos-compliance-$name.json").writeText(
            JSONObject().put("device", Build.DEVICE).put("density", density)
                .put("fontScale", host.resources.configuration.fontScale)
                .put("windowBoundsPx", windowBounds().flattenToString())
                .put("scope", "Current device mode; synthetic UI; no real driving/SDK claim")
                .put("measurements", rows).toString(2))
    }

    private fun connectedColorBounds(bitmap: Bitmap, startX: Int, startY: Int, color: Int): Rect {
        check(bitmap.getPixel(startX, startY) == color) { "Popup body seed must be rendered" }
        val width = bitmap.width
        val visited = BooleanArray(width * bitmap.height)
        val pending = IntArray(visited.size)
        var head = 0
        var tail = 0
        var left = startX; var top = startY; var right = startX + 1; var bottom = startY + 1
        fun visit(index: Int) {
            if (visited[index]) return
            visited[index] = true
            if (bitmap.getPixel(index % width, index / width) == color) pending[tail++] = index
        }
        visit(startY * width + startX)
        while (head < tail) {
            val index = pending[head++]
            val x = index % width
            val y = index / width
            left = minOf(left, x); top = minOf(top, y); right = maxOf(right, x + 1); bottom = maxOf(bottom, y + 1)
            if (x > 0) visit(index - 1)
            if (x + 1 < width) visit(index + 1)
            if (y > 0) visit(index - width)
            if (y + 1 < bitmap.height) visit(index + width)
        }
        return Rect(left, top, right, bottom)
    }

    fun testTripSurfaceAndPrimaryHeaderRenderDayAndNight() {
        start()
        val rows = JSONArray()
        try {
            for (night in listOf(false, true)) {
                val expectedBackground = AndroidColor.parseColor(if (night) "#131417" else "#FFFFFF")
                val expectedText = AndroidColor.parseColor(if (night) "#F7F8FA" else "#131417")
                render { WegoCarTheme(dark = night) { TripSurface {
                    Column(Modifier.fillMaxSize()) {
                        CarPrimaryHeader(listOf(CarPageItem("여행", CarSymbol.Route, true, {})),
                            enabled = true, receiving = true, onRefresh = {}, refreshEnabled = true)
                        Spacer(Modifier.weight(1f))
                    }
                } } }
                await("Header laid out") { host.hasWindowFocus() && semanticNodes("여행").isNotEmpty() }
                val window = windowBounds()
                val x = window.left + (4 * density).roundToInt()
                val headerY = window.top + (4 * density).roundToInt()
                val bodyY = window.bottom - (12 * density).roundToInt()
                await("Day/night must reach the rendered header and trip background") {
                    val bitmap = requireNotNull(instrumentation.uiAutomation.takeScreenshot())
                    try { bitmap.getPixel(x, headerY) == expectedBackground &&
                        bitmap.getPixel(x, bodyY) == expectedBackground } finally { bitmap.recycle() }
                }
                val bitmap = shot(if (night) "trip-night" else "trip-day")
                try {
                    val title = semanticNodes("여행").single().bounds
                    var foregroundPixels = 0
                    for (y in title.top until title.bottom) for (px in title.left until title.right) {
                        if (bitmap.getPixel(px, y) == expectedText) foregroundPixels++
                    }
                    assertTrue("Selected header title must retain the active mode's foreground", foregroundPixels > 10)
                    rows.put(JSONObject().put("night", night).put("headerBackgroundArgb", bitmap.getPixel(x, headerY))
                        .put("tripBackgroundArgb", bitmap.getPixel(x, bodyY)).put("expectedBackgroundArgb", expectedBackground)
                        .put("expectedForegroundArgb", expectedText).put("foregroundPixelCount", foregroundPixels))
                } finally { bitmap.recycle() }
            }
            writeMeasurements("day-night", rows)
        } finally { finish() }
    }

    fun testButtonsRenderWholeSurfaceShrinkAndRejectBusyOrDisabledClicks() {
        start()
        val rows = JSONArray()
        var commands = 0
        try {
            render { WegoCarTheme(dark = false) {
                Column(Modifier.fillMaxSize().background(Color.White).padding(32.dp),
                    verticalArrangement = Arrangement.spacedBy(32.dp)) {
                    CarButton("누르기", { commands++ }, Modifier.width(400.dp), primary = true)
                    CarAction("사용 불가", onClick = { commands++ }, modifier = Modifier.width(400.dp), enabled = false)
                    CarAction("처리 중", onClick = { commands++ }, modifier = Modifier.width(400.dp), busy = true)
                }
            } }
            await("Controls laid out") { host.hasWindowFocus() && semanticNodes("누르기", true).size == 1 }
            val primary = control("누르기")
            val disabled = control("사용 불가")
            val busy = control("처리 중")
            for ((label, node) in listOf("primary" to primary, "disabled" to disabled, "busy" to busy)) {
                assertTrue("$label touch width >= 80 dp", node.bounds.width() / density >= 79.5f)
                assertTrue("$label touch height >= 80 dp", node.bounds.height() / density >= 79.5f)
            }
            assertFalse("Disabled action semantics", disabled.enabled)
            assertFalse("Loading action semantics", busy.enabled)
            assertTrue("Loading state exposes an actual progress indicator", semanticNodes().any { it.progress })
            tap(disabled.bounds)
            tap(busy.bounds)
            assertEquals("Disabled/loading controls do not invoke commands", 0, commands)

            fun fillSpan(bitmap: Bitmap): IntRange {
                val y = primary.bounds.centerY()
                val pixels = (primary.bounds.left until primary.bounds.right).filter {
                    bitmap.getPixel(it, y) != AndroidColor.WHITE
                }
                check(pixels.isNotEmpty()) { "Missing button fill" }
                return pixels.first()..pixels.last()
            }
            val beforeBitmap = shot("button-enabled")
            val fillSampleX = primary.bounds.left + (primary.bounds.width() * 0.15f).roundToInt()
            val beforeColor = beforeBitmap.getPixel(fillSampleX, primary.bounds.centerY())
            val before = try { fillSpan(beforeBitmap) } finally { beforeBitmap.recycle() }
            val downTime = SystemClock.uptimeMillis()
            pointer(MotionEvent.ACTION_DOWN, primary.bounds, downTime)
            try {
                await("Pressed state shrinks the full button background") {
                    val bitmap = requireNotNull(instrumentation.uiAutomation.takeScreenshot())
                    try { fillSpan(bitmap).count() < before.count() - (4 * density).roundToInt() }
                    finally { bitmap.recycle() }
                }
                val pressedBitmap = shot("button-pressed")
                val pressedColor = pressedBitmap.getPixel(fillSampleX, primary.bounds.centerY())
                val pressed = try { fillSpan(pressedBitmap) } finally { pressedBitmap.recycle() }
                val expectedWidth = before.count() * 0.95f
                assertTrue("Full surface follows official 95% shrink: before=$before pressed=$pressed",
                    abs(pressed.count() - expectedWidth) <= 2 * density + 1)
                assertTrue("Pressed state changes the background as well as scale", pressedColor != beforeColor)
                assertEquals("Press must not execute before release", 0, commands)
                rows.put(JSONObject().put("actionBoundsPx", primary.bounds.flattenToString())
                    .put("enabledFillWidthPx", before.count()).put("pressedFillWidthPx", pressed.count())
                    .put("enabledBackgroundArgb", beforeColor).put("pressedBackgroundArgb", pressedColor)
                    .put("expectedPressedScale", 0.95).put("disabledEnabled", disabled.enabled)
                    .put("busyEnabled", busy.enabled).put("loaderSemantics", true))
            } finally { pointer(MotionEvent.ACTION_UP, primary.bounds, downTime) }
            await("Release executes once") { commands == 1 }
            writeMeasurements("button-states", rows)
        } finally { finish() }
    }

    fun testPopupRenderedCornerMatchesOfficialCurrentDeviceRadius() {
        start()
        // The current device contract has S/L/W. Waterfall's 51 dp is a preserved
        // source value, not a pretend hardware mode injected through reflection.
        val radiusDp = when (Build.DEVICE) { "CONNECT_L" -> 42f; "CONNECT_W" -> 40f; else -> 48f }
        val popupWidthDp = when (Build.DEVICE) { "CONNECT_L" -> 614f; "CONNECT_W" -> 720f; else -> 808f }
        val largeButtonHeightDp = when (Build.DEVICE) { "CONNECT_L" -> 88f; "CONNECT_W" -> 84f; else -> 100f }
        val rows = JSONArray()
        try {
            render { WegoCarTheme(dark = false) {
                Box(Modifier.fillMaxSize().background(Color.Magenta))
                CarPopup("모서리 검증", {}, body = { Spacer(Modifier.height(48.dp)) }, actions = {
                    CarAction("확인", onClick = {}, modifier = Modifier.weight(1f), primary = true)
                    CarAction("취소", onClick = {}, modifier = Modifier.weight(1f))
                })
            } }
            await("Popup actions laid out") { semanticNodes("확인", true).size == 1 && semanticNodes("취소", true).size == 1 }
            // Dialog semantics/layout can exist before its separate window has
            // reached the screenshot compositor. Wait for a real body pixel in
            // the title's top padding, not just the main-thread idle condition.
            // A missing/unrendered popup still fails after the bounded wait.
            await("Popup body reaches the rendered screenshot") {
                val title = semanticNodes("모서리 검증").singleOrNull()?.bounds
                if (title == null || title.isEmpty) false else {
                    val frame = requireNotNull(instrumentation.uiAutomation.takeScreenshot())
                    try {
                        val sampleX = title.centerX()
                        val sampleY = title.top - (16 * density).roundToInt()
                        sampleX in 0 until frame.width && sampleY in 0 until frame.height &&
                            frame.getPixel(sampleX, sampleY) == AndroidColor.WHITE
                    } finally { frame.recycle() }
                }
            }
            val bitmap = shot("popup-corner")
            try {
                val window = windowBounds()
                val title = semanticNodes("모서리 검증").single().bounds
                // System status/navigation icons also become white while the
                // Dialog dims its parent. Only the contiguous popup body belongs
                // to this geometry measurement; unrelated screen pixels do not.
                val popup = connectedColorBounds(bitmap, title.centerX(),
                    title.top - (16 * density).roundToInt(), AndroidColor.WHITE)
                assertFalse("Popup white body exists", popup.isEmpty)
                assertTrue("Popup body remains within the app window", window.contains(popup))
                val expectedWidth = minOf(popupWidthDp * density, window.width() - 64 * density)
                assertTrue("Rendered popup respects its mode width: actual=${popup.width()} expected=$expectedWidth",
                    abs(popup.width() - expectedWidth) <= 2 * density)
                val radius = radiusDp * density
                for (fraction in listOf(0.2f, 0.35f, 0.5f, 0.7f)) {
                    val offsetY = (radius * fraction).roundToInt()
                    val y = popup.top + offsetY
                    val actualX = (popup.left until popup.centerX()).first { bitmap.getPixel(it, y) == AndroidColor.WHITE } - popup.left
                    val expectedX = radius - sqrt(radius * radius - (radius - offsetY - 0.5f) * (radius - offsetY - 0.5f))
                    assertTrue("Popup corner at y=$offsetY px must use ${radiusDp}dp; x=$actualX expected=$expectedX",
                        abs(actualX - expectedX) <= 2 * density + 0.5f)
                    rows.put(JSONObject().put("popupBoundsPx", popup.flattenToString()).put("expectedRadiusDp", radiusDp)
                        .put("sampleYOffsetPx", offsetY).put("actualFirstOpaqueXPx", actualX)
                        .put("expectedCircleXPx", expectedX).put("antiAliasTolerancePx", 2 * density + 0.5f))
                }
                val confirm = control("확인").bounds
                val cancel = control("취소").bounds
                assertTrue("Popup footer uses the mode's Large button", abs(confirm.height() / density - largeButtonHeightDp) <= 1)
                assertTrue("Horizontal Confirm left of Cancel", confirm.right < cancel.left)
                rows.put(JSONObject().put("confirmBoundsPx", confirm.flattenToString()).put("cancelBoundsPx", cancel.flattenToString())
                    .put("expectedLargeButtonHeightDp", largeButtonHeightDp))
            } finally { bitmap.recycle() }
            writeMeasurements("popup-geometry", rows)
        } finally { finish() }
    }
}
