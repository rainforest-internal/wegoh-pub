package io.wegoh.app.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.ui.layout.*
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.geometry.RoundRect
import androidx.compose.ui.graphics.Outline
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathOperation
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.Dp
import io.wegoh.app.TripDrivingState
import io.wegoh.app.TripRouteStop
import io.wegoh.app.tripNextStop
import io.wegoh.app.tripRouteStripProgress

@Composable
internal fun CarRouteStrip(stops: List<TripRouteStop>,drive: TripDrivingState,onInk: Boolean=false,compact: Boolean=false,showPosition: Boolean=true,planned: Boolean=false,
    companions: List<TripCompanionMarker> = emptyList()) {
    if(stops.isEmpty()) {TripText("경로 없음",secondary=true);return}
    if(compact || onInk) {
        val density=LocalDensity.current
        var measuredWidth by remember {mutableStateOf<Dp?>(null)}
        Layout(modifier=Modifier.fillMaxWidth(),measurePolicy=RouteWidthMeasurePolicy,content={
            Box(Modifier.fillMaxWidth().onSizeChanged {size->
                if(size.width>0)measuredWidth=with(density) {size.width.toDp()}
            }) {RouteStripAtWidth(stops,drive,onInk,compact,showPosition && !planned,measuredWidth ?: LocalTripLayoutWidth.current,planned,companions)}
        })
    } else {
        val nodes=stops.size+if(tripRouteStripProgress(stops,drive,planned).showStart)1 else 0
        RouteStripAtWidth(stops,drive,onInk,compact,showPosition && !planned,maxOf(LocalTripLayoutWidth.current,CarTokens.RouteCell*nodes),planned,companions)
    }
}

private object RouteWidthMeasurePolicy: MeasurePolicy {
    override fun MeasureScope.measure(measurables: List<Measurable>,constraints: Constraints): MeasureResult {
        val child=measurables.single().measure(constraints)
        return layout(child.width,child.height) {child.placeRelative(0,0)}
    }
    override fun IntrinsicMeasureScope.minIntrinsicWidth(measurables: List<IntrinsicMeasurable>,height: Int)=0
    override fun IntrinsicMeasureScope.maxIntrinsicWidth(measurables: List<IntrinsicMeasurable>,height: Int)=0
    override fun IntrinsicMeasureScope.minIntrinsicHeight(measurables: List<IntrinsicMeasurable>,width: Int)=measurables.single().minIntrinsicHeight(width)
    override fun IntrinsicMeasureScope.maxIntrinsicHeight(measurables: List<IntrinsicMeasurable>,width: Int)=measurables.single().maxIntrinsicHeight(width)
}

/** 아직 지나지 않은 경로 점선과 정류장·도착지 테두리 색. */
internal fun tripRouteRemainingColor(palette: CarPalette,onInk: Boolean,planned: Boolean): Color = when {
    onInk && planned->palette.routeOnInk
    onInk->palette.onInkSecondary
    else->palette.secondary
}

@Composable
private fun RouteStripAtWidth(stops: List<TripRouteStop>,drive: TripDrivingState,onInk: Boolean,compact: Boolean,showPosition: Boolean,railWidth: Dp,planned: Boolean,
    companions: List<TripCompanionMarker>) {
    val palette=LocalCarPalette.current
    val passed=if(onInk)palette.routeOnInk else palette.ink
    val foreground=if(onInk)palette.onInk else palette.text
    // 남은 점선과 도착지 표식은 의미가 있는 도형이라 구분선 역할(divider)이 아닌 보조 글자 역할로 그려 대비를 지킨다.
    // 지나간 구간과의 구분은 색(passed)과 선 모양(실선/점선)이 맡는다.
    val line=tripRouteRemainingColor(palette,onInk,planned)
    val canvas=if(onInk)palette.ink else palette.background
    val accent=if(onInk)palette.routeOnInk else palette.accent
    val next=if(planned)null else tripNextStop(stops,drive)
    val (showStart,marker)=tripRouteStripProgress(stops,drive,planned)
    val shift=if(showStart)1 else 0
    val nodes=stops.size+shift
    val others=if(planned)emptyList() else companions.filter {it.position>=0f && it.position<=stops.lastIndex.toFloat()}
    val measurer=rememberTextMeasurer()
    val markerText=CarType.Label.copy(fontWeight=FontWeight.Bold,color=foreground)
    Box(Modifier.fillMaxWidth().semantics(mergeDescendants=true) {contentDescription="우리 경로"
        stateDescription=(listOf(stops.joinToString(" → ") {it.name})+others.map {it.description}).joinToString(". ")}) {
        val cell=railWidth/nodes
        val offset=marker?.let {cell*(it+0.5f)}
        Box(Modifier.fillMaxWidth().then(if(compact)Modifier else Modifier.horizontalScroll(rememberScrollState()))) {
            val metrics=tripRouteStripMetrics(compact,showPosition)
            Box(Modifier.width(railWidth).heightIn(min=metrics.height)) {
                Canvas(Modifier.matchParentSize()) {
                    val step=size.width/nodes
                    val first=step/2
                    val last=size.width-first
                    val y=metrics.axis.toPx()
                    drawLine(line,Offset(first,y),Offset(last,y),CarTokens.RouteLine.toPx(),StrokeCap.Round,pathEffect=PathEffect.dashPathEffect(floatArrayOf(CarTokens.SpaceSmall.toPx(),CarTokens.SpaceSmall.toPx())))
                    marker?.let {position->
                        drawLine(passed,Offset(first,y),Offset(first+step*position,y),CarTokens.RoutePassedLine.toPx(),StrokeCap.Round)
                    }
                    if(showStart)drawCircle(passed,CarTokens.RouteStartDot.toPx(),Offset(first,y))
                    stops.forEachIndexed {index,stop->
                        val center=Offset(first+step*(index+shift),y)
                        val arrived=!planned && stop.key in drive.arrived
                        val skipped=!planned && stop.key in drive.skipped
                        val upcoming=stop.key==next?.key
                        val radius=if(upcoming)CarTokens.RouteCurrentDot.toPx() else CarTokens.RouteDot.toPx()
                        val fill=if(arrived)passed else canvas
                        val border=if(upcoming)accent else line
                        val stroke=Stroke(if(upcoming)CarTokens.RouteCurrentBorder.toPx() else CarTokens.RouteDotBorder.toPx())
                        if(index==stops.lastIndex) {
                            val origin=center-Offset(radius,radius)
                            val box=Size(radius*2,radius*2)
                            val corner=CornerRadius(radius/3)
                            drawRoundRect(fill,origin,box,corner)
                            if(!arrived)drawRoundRect(border,origin,box,corner,style=stroke)
                        } else {
                            drawCircle(fill,radius,center)
                            if(!arrived)drawCircle(border,radius,center,style=stroke)
                        }
                        if(skipped)drawLine(CarTokens.Muted,center-Offset(CarTokens.RouteSkipHalf.toPx(),CarTokens.RouteSkipHalf.toPx()),
                            center+Offset(CarTokens.RouteSkipHalf.toPx(),CarTokens.RouteSkipHalf.toPx()),CarTokens.RouteSkipStroke.toPx(),StrokeCap.Round)
                    }
                    others.forEach {mark->
                        val center=Offset(first+step*(mark.position+shift),y)
                        drawCircle(canvas,CarTokens.RouteMarkerDot.toPx(),center)
                        drawCircle(foreground,CarTokens.RouteMarkerDot.toPx(),center,style=Stroke(CarTokens.RouteDotBorder.toPx()))
                        val text=measurer.measure(mark.label,markerText)
                        drawText(text,topLeft=center-Offset(text.size.width/2f,text.size.height/2f))
                    }
                    if(showPosition)marker?.let {position->
                        val center=Offset(first+step*position,y)
                        drawCircle(canvas,CarTokens.RouteMarkerDot.toPx(),center)
                        drawCircle(accent,CarTokens.RouteMarkerInner.toPx(),center)
                    }
                }
                Row(Modifier.fillMaxWidth().padding(top=metrics.labelTop)) {
                    CompositionLocalProvider(LocalCarTextAlign provides TextAlign.Center) {
                        if(showStart)TripText("출발",Modifier.weight(1f).padding(horizontal=CarTokens.SpaceSmall),secondary=true)
                        stops.forEach {stop->
                            val label=stop.name+when(stop.item.type){"pickup"->" 타는 곳";"drop"->" 내리는 곳";else->""}
                            TripText(label,Modifier.weight(1f).padding(horizontal=CarTokens.SpaceSmall),
                                style=(if(compact)CarType.Label else CarType.Body).copy(fontWeight=if(stop==next)FontWeight.Bold else FontWeight.Normal),color=foreground,
                                secondary=stop!=next,maxLines=2)
                        }
                    }
                }
                if(showPosition && offset!=null) {
                    // 몸통과 꼬리를 한 도형으로 칠해 말풍선 꼬리 끝이 위치 점 테두리에 닿게 한다.
                    val caption=tripRouteCaptionGeometry(compact)
                    CompositionLocalProvider(LocalCarPalette provides palette.copy(text=if(onInk)palette.ink else palette.selectionMark)) {
                        Box(Modifier.offset(x=offset-CarTokens.RouteCaptionWidth/2,y=caption.top).width(CarTokens.RouteCaptionWidth)
                            .height(caption.bodyHeight+caption.tailHeight).background(accent,RouteCaptionBubbleShape)
                            .padding(bottom=caption.tailHeight),contentAlignment=Alignment.Center) {
                            TripText("지금 여기",style=CarType.Body.copy(fontWeight=FontWeight.Bold))
                        }
                    }
                }
            }
        }
    }
}

/** 경로 띠의 최소 높이·축·이름 줄 위치. */
internal data class TripRouteStripMetrics(val height: Dp,val axis: Dp,val labelTop: Dp)

/**
 * compact 띠는 운전 대시보드의 '남은 높이에 다 들어갈 때만 둔다' 칸에 들어가므로, 말풍선 꼬리를 넣으면서도
 * 위치 표시가 있는 띠의 높이는 [CarTokens.RouteCompactHeight] 그대로 둔다. 축과 이름 줄만 아래로 옮기고 아래 여백을 줄인다.
 */
internal fun tripRouteStripMetrics(compact: Boolean,showPosition: Boolean): TripRouteStripMetrics = when {
    !compact->TripRouteStripMetrics(CarTokens.RouteHeight,CarTokens.RouteAxis,CarTokens.RouteLabelTop)
    showPosition->TripRouteStripMetrics(CarTokens.RouteCompactHeight,CarTokens.RouteCompactAxis,CarTokens.RouteCompactLabelTop)
    else->TripRouteStripMetrics(CarTokens.RouteCompactHeight-CarTokens.RouteCompactCaptionHeight,CarTokens.RouteCurrentDot+CarTokens.RouteCurrentBorder,
        CarTokens.RouteCompactLabelTop-CarTokens.RouteCompactCaptionSpace+CarTokens.SpaceSmall)
}

/** '지금 여기' 말풍선의 세로 배치. 꼬리 끝([tip])은 위치 점 바깥 테두리 맨 위에 닿는다. */
internal data class TripRouteCaptionGeometry(val top: Dp,val bodyHeight: Dp,val tailHeight: Dp) {
    val tip: Dp get()=top+bodyHeight+tailHeight
}

internal fun tripRouteCaptionGeometry(compact: Boolean): TripRouteCaptionGeometry {
    val axis=tripRouteStripMetrics(compact,showPosition=true).axis
    val body=if(compact)CarTokens.RouteCompactCaptionHeight else CarTokens.RouteCaptionHeight
    return TripRouteCaptionGeometry(top=axis-CarTokens.RouteMarkerDot-CarTokens.RouteCaptionTail-body,bodyHeight=body,tailHeight=CarTokens.RouteCaptionTail)
}

/** 둥근 몸통 아래 가운데에 뾰족한 꼬리가 붙은 말풍선. 꼬리 높이는 전체 높이 중 [CarTokens.RouteCaptionTail]이다. */
private object RouteCaptionBubbleShape: Shape {
    override fun createOutline(size: Size,layoutDirection: LayoutDirection,density: Density): Outline = with(density) {
        val body=size.height-CarTokens.RouteCaptionTail.toPx()
        val half=CarTokens.RouteCaptionTailWidth.toPx()/2
        val center=size.width/2
        val radius=minOf(CarTokens.RouteCaptionRadius.toPx(),body/2)
        val bubble=Path().apply {addRoundRect(RoundRect(0f,0f,size.width,body,CornerRadius(radius)))}
        // 꼬리 밑변을 몸통 안쪽으로 1px 겹쳐 두 도형 사이에 이음선이 생기지 않게 한다.
        val overlap=1f
        val tail=Path().apply {
            moveTo(center-half,body-overlap);lineTo(center+half,body-overlap);lineTo(center,size.height);close()
        }
        Outline.Generic(Path().apply {op(bubble,tail,PathOperation.Union)})
    }
}
