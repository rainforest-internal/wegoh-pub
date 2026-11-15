package io.wegoh.app.ui

import org.junit.Assert.*
import org.junit.Test

/** 가까운 장소 이름이 겹치면 순위가 높은 이름만 남는다. 순위는 서로 달라야 경쟁 결과가 정해진다. */
class CourseMapNameRankTest {
    private val points=listOf(
        CourseMapPoint("a","센터커피 서울역점",37.5550,126.9707),
        CourseMapPoint("b","서울역",37.5547,126.9706),
        CourseMapPoint("c","남산",37.5512,126.9882),
    )

    @Test fun earlierStopsWinWithoutFocus() {
        val ranks=courseMapNameRanks(points,null)
        assertTrue(ranks.getValue("a")>ranks.getValue("b"))
        assertTrue(ranks.getValue("b")>ranks.getValue("c"))
        assertEquals(points.size,ranks.values.toSet().size)
    }

    @Test fun focusedStopWinsOverEveryOtherName() {
        val ranks=courseMapNameRanks(points,"b")
        assertTrue(ranks.getValue("b")>ranks.getValue("a"))
        assertTrue(ranks.getValue("b")>ranks.getValue("c"))
        assertEquals(points.size,ranks.values.toSet().size)
    }

    @Test fun unknownFocusFallsBackToRouteOrder() {
        assertEquals(courseMapNameRanks(points,null),courseMapNameRanks(points,"missing"))
    }
}
