package io.wegoh.app.ui

import org.junit.Assert.assertEquals
import org.junit.Test

class TripAdaptiveRowTest {
    // 진행 화면은 히어로 1.25 : 패널 1. 내용의 최소 폭과 무관하게 두 열이 늘 같은 줄을 나눠 가진다.
    @Test fun wideColumnsSplitTheRowByWeightOnly() {
        assertEquals(listOf(845,677),tripAdaptiveColumnWidths(1554,32,listOf(1.25f,1f)))
    }

    @Test fun roundingLeftoverGoesToTheLastColumnSoTheRowIsFilledExactly() {
        val widths=tripAdaptiveColumnWidths(1001,24,listOf(1f,1f,1f))
        assertEquals(listOf(317,317,319),widths)
        assertEquals(1001,widths.sum()+24*2)
    }

    @Test fun noRoomNeverYieldsNegativeWidths() {
        assertEquals(listOf(0,0),tripAdaptiveColumnWidths(10,32,listOf(1f,1f)))
        assertEquals(emptyList<Int>(),tripAdaptiveColumnWidths(1000,32,emptyList()))
    }
}
