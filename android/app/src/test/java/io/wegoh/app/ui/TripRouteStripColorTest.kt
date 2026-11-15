package io.wegoh.app.ui

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import org.junit.Assert.*
import org.junit.Test

/** 남은 경로 점선과 도착지 표식은 의미 있는 도형이라 카드 바탕 대비 4.5:1 이상이어야 한다. */
class TripRouteStripColorTest {
    private fun contrast(a: Color,b: Color): Double {
        val (light,dark)=listOf(a.luminance(),b.luminance()).sortedDescending()
        return (light+0.05)/(dark+0.05)
    }
    private val palettes=listOf(PleosPalette.Day,PleosPalette.Night)

    @Test fun remainingRouteOnInkCardIsReadable() {
        palettes.forEach {p->
            assertTrue(contrast(tripRouteRemainingColor(p,onInk=true,planned=false),p.ink)>=4.5)
            assertTrue(contrast(tripRouteRemainingColor(p,onInk=true,planned=true),p.ink)>=4.5)
            assertNotEquals("구분선 색은 INK 카드에 묻힌다",p.inkDivider,tripRouteRemainingColor(p,onInk=true,planned=false))
        }
    }

    @Test fun remainingRouteOnPlainCardsIsReadable() {
        palettes.forEach {p->
            listOf(p.background,p.low,p.accentSoft).forEach {surface->
                assertTrue(contrast(tripRouteRemainingColor(p,onInk=false,planned=false),surface)>=4.5)
            }
        }
    }

    @Test fun passedAndRemainingRouteDifferOnInk() {
        palettes.forEach {p->assertNotEquals(p.routeOnInk,tripRouteRemainingColor(p,onInk=true,planned=false))}
    }
}
