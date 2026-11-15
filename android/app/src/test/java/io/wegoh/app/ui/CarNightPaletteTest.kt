package io.wegoh.app.ui

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import org.junit.Assert.*
import org.junit.Test

/** 야간에도 선택 표시·INK 카드·INK 위 글자가 배경과 구분되어야 한다(Pleos 대비 4.5:1, 비텍스트 3:1). */
class CarNightPaletteTest {
    private fun contrast(a: Color,b: Color): Double {
        val (light,dark)=listOf(a.luminance(),b.luminance()).sortedDescending()
        return (light+0.05)/(dark+0.05)
    }
    private val palettes=listOf(PleosPalette.Day,PleosPalette.Night)

    @Test fun selectionIndicatorStandsOutOnEverySurface() {
        palettes.forEach {p->
            listOf(p.background,p.low).forEach {surface->
                assertTrue("선택 밑줄·테두리는 바탕 대비 3:1 이상",contrast(p.selectionIndicator,surface)>=3.0)
            }
        }
    }

    @Test fun nightInkIsItsOwnSurface() {
        val p=PleosPalette.Night
        assertNotEquals("INK 카드와 SOFT 카드가 같은 색이면 위계가 사라진다",p.accentSoft,p.ink)
        assertNotEquals(p.background,p.ink)
        assertNotEquals(p.low,p.ink)
        assertTrue(p.ink.luminance()>p.accentSoft.luminance())
    }

    @Test fun inkCardEdgeSeparatesFromSoftAndBackground() {
        palettes.forEach {p->
            // INK 카드 경계는 면 색 또는 테두리 중 더 강한 쪽이 맡는다. 비텍스트 하한 3:1.
            listOf(p.background,p.accentSoft).forEach {neighbor->
                val edge=maxOf(contrast(p.ink,neighbor),contrast(p.inkBorder,neighbor))
                assertTrue("INK 카드는 배경·SOFT 카드와 3:1 이상 구분",edge>=3.0)
            }
        }
        val night=PleosPalette.Night
        // 회귀 기준: 야간 INK 면만으로는 SOFT 카드와 1.3:1 수준이라 테두리가 필요하다.
        assertTrue(contrast(night.ink,night.accentSoft)<3.0)
        assertNotEquals(night.ink,night.inkBorder)
    }

    @Test fun softCardEdgeSeparatesFromBackground() {
        val night=PleosPalette.Night
        // 야간 SOFT 카드(D단 히어로 등)는 면만으로 배경과 1.3:1이라 테두리가 경계를 맡는다. 비텍스트 하한 3:1.
        assertTrue(contrast(night.accentSoft,night.background)<3.0)
        assertTrue("야간 SOFT 카드 테두리는 배경 대비 3:1 이상",contrast(night.softBorder,night.background)>=3.0)
        // 위계: INK 카드 테두리가 SOFT 카드 테두리보다 배경과 더 강하게 구분된다.
        assertTrue(contrast(night.inkBorder,night.background)>contrast(night.softBorder,night.background))
        // 주간은 테두리를 면과 같은 색으로 두어 기존 화면이 바뀌지 않는다.
        assertEquals(PleosPalette.Day.accentSoft,PleosPalette.Day.softBorder)
    }

    @Test fun contentOnSoftKeepsContrast() {
        palettes.forEach {p->
            // SOFT 면은 바뀌지 않았고, 그 위 글자·보조 글자·파란 경로 표시는 4.5:1을 지킨다.
            listOf(p.text,p.secondary,p.accent).forEach {ink->assertTrue(contrast(ink,p.accentSoft)>=4.5)}
        }
    }

    @Test fun textOnInkKeepsContrast() {
        palettes.forEach {p->
            assertTrue(contrast(p.onInk,p.ink)>=4.5)
            assertTrue(contrast(p.onInkSecondary,p.ink)>=4.5)
            assertTrue("INK 위 파란 글자·표식",contrast(p.routeOnInk,p.ink)>=4.5)
        }
    }

    @Test fun skeletonOnInkStaysVisible() {
        palettes.forEach {p->
            assertNotEquals(p.ink,p.skeletonOnInk)
            assertNotEquals(p.ink,p.skeletonOnInkHighlight)
            assertNotEquals(p.skeletonOnInk,p.skeletonOnInkHighlight)
        }
    }
}
