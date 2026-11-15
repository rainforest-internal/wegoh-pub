package io.wegoh.app.ui

import androidx.compose.ui.unit.dp
import org.junit.Assert.*
import org.junit.Test

/** '지금 여기' 말풍선은 경로 띠 안에 들어가고 꼬리 끝이 위치 점 테두리에 닿아야 한다. */
class TripRouteCaptionGeometryTest {
    private val variants=listOf(false to CarTokens.RouteAxis,true to CarTokens.RouteCompactAxis)

    @Test fun tailTipTouchesMarkerOuterEdge() {
        variants.forEach {(compact,axis)->
            assertEquals(axis-CarTokens.RouteMarkerDot,tripRouteCaptionGeometry(compact).tip)
        }
    }

    @Test fun bubbleStaysInsideStripTop() {
        variants.forEach {(compact,_)->assertTrue(tripRouteCaptionGeometry(compact).top>=0.dp)}
    }

    @Test fun bubbleBodyKeepsCaptionHeight() {
        assertEquals(CarTokens.RouteCaptionHeight,tripRouteCaptionGeometry(false).bodyHeight)
        assertEquals(CarTokens.RouteCompactCaptionHeight,tripRouteCaptionGeometry(true).bodyHeight)
        variants.forEach {(compact,_)->assertTrue(tripRouteCaptionGeometry(compact).tailHeight>0.dp)}
    }

    @Test fun tailPointsInsideMarkerAndFlatBottom() {
        assertTrue("꼬리 밑변은 위치 점보다 좁아야 점을 가리킨다",CarTokens.RouteCaptionTailWidth<CarTokens.RouteMarkerDot*2)
        assertTrue("꼬리는 둥근 모서리를 피한 평평한 밑변에 붙는다",
            CarTokens.RouteCaptionTailWidth<=CarTokens.RouteCaptionWidth-CarTokens.RouteCaptionRadius*2)
    }

    // compact 이름은 CarType.Label 두 줄(maxLines=2)까지 쓴다.
    private val twoLabelLines=(PleosType.LabelLine.value*2).dp

    @Test fun compactLabelsClearCurrentStopDot() {
        listOf(true,false).forEach {showPosition->
            val m=tripRouteStripMetrics(compact=true,showPosition=showPosition)
            assertTrue(m.labelTop>=m.axis+CarTokens.RouteCurrentDot)
        }
        assertTrue(CarTokens.RouteCompactLabelTop>=CarTokens.RouteCompactAxis+CarTokens.RouteCurrentDot+CarTokens.RouteCurrentBorder)
    }

    @Test fun compactStripKeepsDashboardHeightBudget() {
        // 운전 대시보드는 진행 바를 남은 높이에 다 들어갈 때만 둔다. 말풍선 꼬리 때문에 띠가 커지면 D단에서
        // 진행 바가 통째로 빠진다. 위치 표시가 있는 띠는 꼬리 이전과 같은 160dp, 없는 띠는 120dp를 지킨다.
        val shown=tripRouteStripMetrics(compact=true,showPosition=true)
        val hidden=tripRouteStripMetrics(compact=true,showPosition=false)
        assertEquals(160.dp,shown.height)
        assertEquals(120.dp,hidden.height)
        assertEquals(48.dp,hidden.labelTop)
        // 두 줄 이름이 최소 높이 안에 들어가 실제 측정 높이도 최소 높이와 같다.
        listOf(shown,hidden).forEach {assertTrue(it.labelTop+twoLabelLines<=it.height)}
    }

    @Test fun captionUsesStripAxis() {
        listOf(true,false).forEach {compact->
            assertEquals(tripRouteStripMetrics(compact,showPosition=true).axis-CarTokens.RouteMarkerDot,tripRouteCaptionGeometry(compact).tip)
        }
    }
}
