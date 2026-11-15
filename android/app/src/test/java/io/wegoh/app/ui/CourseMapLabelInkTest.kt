package io.wegoh.app.ui

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.compositeOver
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.graphics.toArgb
import com.kakao.vectormap.shape.ShapeLayerPass
import org.junit.Assert.*
import org.junit.Test

/**
 * Kakao 지도 타일은 다크 모드에서도 밝다. 주간 지도 위 장소 글자는 밝은 지도 바탕 기준이어야 하고,
 * 야간에는 타일을 야간 배경색으로 덮은 뒤 야간 글자색을 쓴다.
 */
class CourseMapLabelInkTest {
    private fun contrast(a: Color,b: Color): Double {
        val (light,dark)=listOf(a.luminance(),b.luminance()).sortedDescending()
        return (light+0.05)/(dark+0.05)
    }

    @Test fun mapLabelUsesDayRolesInBothThemes() {
        assertEquals(PleosPalette.Day.text,CarTokens.MapLabelText)
        assertEquals(PleosPalette.Day.background,CarTokens.MapLabelHalo)
        assertNotEquals("다크 테마 글자색을 지도 글자에 쓰면 밝은 지도에서 사라진다",PleosPalette.Night.text,CarTokens.MapLabelText)
    }

    @Test fun mapLabelReadsOnLightMapBackground() {
        assertTrue(contrast(CarTokens.MapLabelText,CarTokens.MapLabelHalo)>=4.5)
        // 회귀 기준: 기존처럼 다크 테마 onSurface를 쓰면 밝은 지도 위 대비가 부족하다.
        assertTrue(contrast(PleosPalette.Night.text,CarTokens.MapLabelHalo)<3.0)
        assertTrue(CarTokens.MapLabelHaloWidth.value>0f)
    }

    @Test fun dayMapKeepsTilesAndDayLabels() {
        val ink=courseMapInk(PleosPalette.Day)
        assertEquals(CarTokens.MapLabelText,ink.text)
        assertEquals(CarTokens.MapLabelHalo,ink.halo)
        assertNull("주간에는 지도 타일을 덮지 않는다",ink.dim)
    }

    @Test fun nightMapDimsTilesAndUsesNightLabels() {
        val ink=courseMapInk(PleosPalette.Night)
        val dim=requireNotNull(ink.dim) {"야간에는 밝은 지도 타일을 덮어야 한다"}
        assertEquals(PleosPalette.Night.background.copy(alpha=CarTokens.MapNightDimAlpha),dim)
        assertEquals(PleosPalette.Night.text,ink.text)
        assertEquals(PleosPalette.Night.background,ink.halo)
        assertTrue(contrast(ink.text,ink.halo)>=4.5)
        // 가장 밝은 타일(흰색)을 덮은 뒤에도 야간 글자가 외곽선 없이 4.5:1 이상이고, 덮은 타일은 원래보다 충분히 어둡다.
        val dimmedWhite=dim.compositeOver(Color.White)
        assertTrue(contrast(ink.text,dimmedWhite)>=4.5)
        assertTrue(dimmedWhite.luminance()<0.2f)
    }

    // Kakao 기본 타일에서 가장 밝은 바탕(흰색)과 가장 어두운 바탕(검정)을 양 끝 경우로 본다.
    private val tiles=listOf(Color.White,Color.Black)

    @Test fun nightMarkersStandOutOnDimmedTiles() {
        val ink=courseMapInk(PleosPalette.Night)
        val dim=requireNotNull(ink.dim)
        tiles.forEach {tile->
            // 비텍스트 하한은 3:1이고, 주행 중 한눈에 찾도록 목표를 4.5:1로 둔다.
            assertTrue("야간 표식 테두리는 덮인 타일 대비 4.5:1 이상",contrast(ink.ring,dim.compositeOver(tile))>=4.5)
        }
        listOf(ink.vehicle,ink.otherCar,ink.staleCar).forEach {core->
            assertTrue("표식 안쪽 색은 테두리와 3:1 이상 구분",contrast(core,ink.ring)>=3.0)
        }
        // 회귀 기준: 카드용 ink를 그대로 쓰면 덮인 흰 타일 위에서 2:1에도 못 미친다.
        assertTrue(contrast(PleosPalette.Night.ink,dim.compositeOver(Color.White))<3.0)
    }

    @Test fun dayMarkersStandOutOnLightTiles() {
        val ink=courseMapInk(PleosPalette.Day)
        // 주간 테두리는 흰 타일과 같은 색이라 표식 안쪽 색이 타일과의 대비를 맡는다.
        assertEquals(Color.White,ink.ring)
        listOf(ink.vehicle,ink.otherCar,ink.staleCar).forEach {core->
            assertTrue("주간 표식은 흰 타일 대비 3:1 이상",contrast(core,Color.White)>=3.0)
        }
    }

    @Test fun nightRouteStandsOutOnDimmedTiles() {
        val ink=courseMapInk(PleosPalette.Night)
        val dim=requireNotNull(ink.dim)
        // 실제 렌더링 순서대로 합성한다. 타일은 덮개 아래, 경로선은 COURSE_MAP_ROUTE_PASS가 정하는 층에 있다.
        val underDim=courseMapShapeUnderDim(COURSE_MAP_ROUTE_PASS)
        assertFalse("경로선은 야간 덮개 위 패스에 그린다",underDim)
        val casing=courseMapSeen(ink.routeCasing,dim,underDim)
        val line=courseMapSeen(ink.route,dim,underDim)
        tiles.forEach {tile->
            val seenTile=courseMapSeen(tile,dim,underDim=true)
            // 비텍스트 하한은 3:1이고, 표식 테두리와 같은 목표 4.5:1(Pleos 아이콘·이미지 대비)을 둔다.
            assertTrue("야간 경로선 외곽선은 덮인 타일 대비 4.5:1 이상",contrast(casing,seenTile)>=4.5)
        }
        assertTrue("경로선 안쪽 색은 외곽선과 3:1 이상 구분",contrast(line,casing)>=3.0)
        assertTrue(CarTokens.MapRouteCasingWidth.value>0f)
        // 회귀 기준: 기존 경로선(야간 accent)은 덮인 흰 타일 위에서 3:1에 못 미친다.
        assertTrue(contrast(PleosPalette.Night.accent,dim.compositeOver(Color.White))<3.0)
    }

    @Test fun routeUnderDimMatchesLiveMeasurement() {
        // #467 실기(160dpi 원본 픽셀): 기본 Shape 레이어의 경로선은 덮개 아래에 그려져 안쪽 #172E5A, 외곽선 #636466으로 보였다.
        // 합성 모델이 이 측정값을 재현하는지 확인해, 위 시험의 덮개 위·아래 계산이 실제 화면과 맞는지 고정한다.
        val ink=courseMapInk(PleosPalette.Night)
        val dim=requireNotNull(ink.dim)
        val underDim=courseMapShapeUnderDim(ShapeLayerPass.Default)
        assertTrue("기본 Shape 패스는 덮개 아래",underDim)
        assertNear(Color(0xFF172E5A),courseMapSeen(ink.route,dim,underDim))
        assertNear(Color(0xFF636466),courseMapSeen(ink.routeCasing,dim,underDim))
        // 덮개 아래에서는 외곽선이 덮인 흰 타일과 거의 같아지고, 안쪽 색도 3:1에 못 미친다(실측 2.25:1).
        val seenWhite=courseMapSeen(Color.White,dim,underDim=true)
        assertTrue(contrast(courseMapSeen(ink.routeCasing,dim,underDim),seenWhite)<1.1)
        assertTrue(contrast(courseMapSeen(ink.route,dim,underDim),seenWhite)<3.0)
    }

    private fun assertNear(expected: Color,actual: Color) {
        val e=expected.toArgb();val a=actual.toArgb()
        listOf(16,8,0).forEach {shift->
            val diff=kotlin.math.abs((e shr shift and 0xFF)-(a shr shift and 0xFF))
            assertTrue("측정 #%06X, 계산 #%06X".format(e and 0xFFFFFF,a and 0xFFFFFF),diff<=2)
        }
    }

    @Test fun dayRouteKeepsContrastOnLightTiles() {
        val ink=courseMapInk(PleosPalette.Day)
        // 주간 외곽선은 흰 타일과 같은 색이라 안쪽 색이 타일과의 대비를 맡고, 기존 경로선(주간 accent)보다 낮아지지 않는다.
        assertEquals(Color.White,ink.routeCasing)
        assertTrue(contrast(ink.route,Color.White)>=4.5)
        assertTrue(contrast(ink.route,Color.White)>=contrast(PleosPalette.Day.accent,Color.White))
    }

    @Test fun routeLineIsNotSelectionIndicator() {
        // 경로선은 지도 전용 색이라 앱의 선택 표시(밑줄·테두리)와 같은 색을 쓰지 않는다.
        listOf(PleosPalette.Day,PleosPalette.Night).forEach {theme->
            val ink=courseMapInk(theme)
            assertNotEquals(theme.selectionIndicator,ink.route)
            assertNotEquals(theme.selectionIndicator,ink.routeCasing)
        }
    }

    @Test fun carMarkersStayDistinct() {
        listOf(PleosPalette.Day,PleosPalette.Night).map(::courseMapInk).forEach {ink->
            assertEquals("내 차·다른 차·늦은 위치 차는 서로 다른 색",3,setOf(ink.vehicle,ink.otherCar,ink.staleCar).size)
            assertTrue("내 차는 다른 차와 밝기로도 구분",contrast(ink.vehicle,ink.otherCar)>=3.0)
            assertTrue(contrast(ink.vehicle,ink.staleCar)>=3.0)
        }
    }

    @Test fun nightThemeCopiesStillCountAsNight() {
        // 카드 톤이 글자색만 바꾼 팔레트도 바탕은 야간 테마 그대로다.
        assertNotNull(courseMapInk(PleosPalette.Night.copy(text=PleosPalette.Night.onInk)).dim)
    }
}
