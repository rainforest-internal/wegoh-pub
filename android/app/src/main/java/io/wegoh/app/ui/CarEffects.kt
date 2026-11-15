package io.wegoh.app.ui

import android.graphics.Bitmap
import android.graphics.BlurMaskFilter
import android.graphics.Paint
import android.graphics.RectF
import androidx.compose.foundation.Canvas
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.ProgressBarRangeInfo
import androidx.compose.ui.semantics.progressBarRangeInfo
import androidx.compose.ui.semantics.semantics
import kotlin.math.ceil

/** Exact reviewed Linear asset parameters; no Material spinner defaults. */
@Composable
fun CarLoading(modifier: Modifier = Modifier, color: Color = LocalCarPalette.current.text) {
    var frame by remember { mutableFloatStateOf(0f) }
    LaunchedEffect(Unit) {
        val start=withFrameNanos { it }
        while(true) withFrameNanos { now ->
            frame=((now-start)/1_000_000_000.0*PleosEffects.LoadingFps%PleosEffects.LoadingEndFrameExclusive).toFloat()
        }
    }
    Canvas(modifier.semantics { progressBarRangeInfo=ProgressBarRangeInfo.Indeterminate }) {
        val scale=size.minDimension/PleosEffects.LoadingCanvas
        val radius=PleosEffects.LoadingRadius*scale
        val topLeft=Offset(size.width/2-radius,size.height/2-radius)
        val dimensions=Size(radius*2,radius*2)
        val stroke=PleosEffects.LoadingStrokeWidth*scale
        drawCircle(color.copy(alpha=PleosEffects.LoadingBackgroundAlpha),radius,style=Stroke(stroke))
        val angle=frame.coerceAtMost(PleosEffects.LoadingRotationEndFrame)/PleosEffects.LoadingRotationEndFrame*PleosEffects.LoadingRotationDegrees
        drawArc(color.copy(alpha=PleosEffects.LoadingForegroundAlpha),PleosEffects.LoadingTrimOffsetDegrees+angle,
            PleosEffects.LoadingTrimEndPercent*3.6f,false,topLeft,dimensions,style=Stroke(stroke,cap=StrokeCap.Round))
    }
}

internal data class CarShadowLayer(val x: Float,val y: Float,val blur: Float,val argb: Int)

/** Figma blur is represented as Gaussian sigma blur/2, with separate layers.
 * Software bitmap rendering makes the same mask available on API 28+ hardware
 * canvases; a framework elevation value is not treated as a Figma blur radius.
 */
internal fun Modifier.pleosPopupShadow(): Modifier = drawWithCache {
    val pad=64*density
    val bitmap=Bitmap.createBitmap(ceil(size.width+2*pad).toInt().coerceAtLeast(1),
        ceil(size.height+2*pad).toInt().coerceAtLeast(1),Bitmap.Config.ARGB_8888)
    val canvas=android.graphics.Canvas(bitmap)
    val radius=CarTokens.PopupRadius.toPx()
    for(layer in PleosEffects.level2) {
        val paint=Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color=layer.argb
            maskFilter=BlurMaskFilter(layer.blur*density/2,BlurMaskFilter.Blur.NORMAL)
        }
        val x=layer.x*density;val y=layer.y*density
        canvas.drawRoundRect(RectF(pad+x,pad+y,pad+size.width+x,pad+size.height+y),radius,radius,paint)
    }
    val shadow=bitmap.asImageBitmap()
    onDrawBehind { drawImage(shadow,Offset(-pad,-pad)) }
}
