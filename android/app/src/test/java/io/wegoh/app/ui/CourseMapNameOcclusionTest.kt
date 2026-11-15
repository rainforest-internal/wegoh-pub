package io.wegoh.app.ui

import org.junit.Assert.*
import org.junit.Test

/**
 * 번호·차 표식과 화면에서 겹치는 다른 장소 이름은 숨기고, 표식은 숨기지 않는다.
 * 이름끼리의 겹침은 이름 레이어의 Same 경쟁이 맡으므로 여기서 다루지 않는다.
 */
class CourseMapNameOcclusionTest {
    private val marker=48
    private val textWidth=200f
    private val textHeight=30f

    private fun name(key: String,x: Float,y: Float)=courseMapNameBox(key,x,y,marker,textWidth,textHeight)
    private fun stop(key: String,x: Float,y: Float)=CourseMapDisc(key,x,y,marker/2f)

    @Test fun nameSitsCenteredBelowItsMarker() {
        val box=name("a",100f,100f)
        assertEquals(124f,box.top)
        assertEquals(154f,box.bottom)
        assertEquals(0f,box.left)
        assertEquals(200f,box.right)
    }

    @Test fun otherStopMarkerOnNameHidesThatName() {
        // 재현: 2번 표식이 1번 이름 가운데에 놓인다.
        val names=listOf(name("a",100f,100f),name("b",110f,170f))
        val discs=listOf(stop("a",100f,100f),stop("b",110f,170f))
        assertEquals(setOf("a"),courseMapNamesHiddenByMarkers(names,discs))
    }

    @Test fun ownMarkerNeverHidesItsName() {
        assertEquals(emptySet<String>(),courseMapNamesHiddenByMarkers(listOf(name("a",100f,100f)),listOf(stop("a",100f,100f))))
    }

    @Test fun distantStopsKeepBothNames() {
        val names=listOf(name("a",100f,100f),name("b",600f,400f))
        val discs=listOf(stop("a",100f,100f),stop("b",600f,400f))
        assertEquals(emptySet<String>(),courseMapNamesHiddenByMarkers(names,discs))
    }

    @Test fun carMarkerHidesNameItCovers() {
        val names=listOf(name("a",100f,100f))
        val car=CourseMapDisc(null,100f,140f,19f)
        assertEquals(setOf("a"),courseMapNamesHiddenByMarkers(names,listOf(stop("a",100f,100f),car)))
    }

    @Test fun carParkedOnItsStopKeepsTheName() {
        // 차 표식(반지름 19)은 장소 표식 반 크기(24) 안이라 그 장소 이름까지 닿지 않는다.
        val names=listOf(name("a",100f,100f))
        val car=CourseMapDisc(null,100f,100f,19f)
        assertEquals(emptySet<String>(),courseMapNamesHiddenByMarkers(names,listOf(stop("a",100f,100f),car)))
    }

    @Test fun touchingEdgeIsNotOverlap() {
        val box=name("a",100f,100f)
        assertFalse(courseMapDiscHitsBox(CourseMapDisc("b",100f,box.bottom+24f,24f),box))
        assertTrue(courseMapDiscHitsBox(CourseMapDisc("b",100f,box.bottom+23f,24f),box))
        // 모서리 근처: 원이 사각형 모서리에 닿지 않으면 겹침이 아니다.
        assertFalse(courseMapDiscHitsBox(CourseMapDisc("b",box.right+20f,box.top-20f,24f),box))
    }
}
