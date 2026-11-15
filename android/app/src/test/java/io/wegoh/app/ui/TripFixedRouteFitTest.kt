package io.wegoh.app.ui

import androidx.compose.ui.unit.Constraints
import org.junit.Assert.assertEquals
import org.junit.Test

/** 고정 경로 카드는 다음 장소·버튼 > 진행 바 > 지도 > 함께 가는 차 줄 순서로 높이를 받는다. */
class TripFixedRouteFitTest {
    private fun fit(maxHeight: Int,top: Int=400,strip: Int=180,extra: Int=50)=
        tripFixedRouteFit(maxHeight,top,strip,extra,gap=16,mapMin=220,mapMax=320)

    @Test fun tallCardKeepsEverythingAtFullMapHeight() {
        assertEquals(TripFixedRouteFit(320,strip=true,extra=true),fit(2000))
        // top 400 + 지도 320 + 진행 바 180 + 함께 가는 차 50, 간격 3개
        assertEquals(TripFixedRouteFit(320,strip=true,extra=true),fit(400+320+180+50+16*3))
    }

    @Test fun companionRowGoesFirstThenMapShrinks() {
        assertEquals(TripFixedRouteFit(320,strip=true,extra=false),fit(400+320+180+50+16*3-1))
        assertEquals(TripFixedRouteFit(250,strip=true,extra=false),fit(400+250+180+16*2))
        assertEquals(TripFixedRouteFit(220,strip=true,extra=false),fit(400+220+180+16*2))
    }

    @Test fun mapDisappearsBelowItsMinimumButProgressBarStays() {
        assertEquals(TripFixedRouteFit(0,strip=true,extra=false),fit(400+219+180+16*2))
        assertEquals(TripFixedRouteFit(0,strip=true,extra=false),fit(400+180+16))
    }

    @Test fun buttonsWinOverACutProgressBar() {
        assertEquals(TripFixedRouteFit(0,strip=false,extra=false),fit(400+180+16-1))
        assertEquals(TripFixedRouteFit(0,strip=false,extra=false),fit(300))
    }

    @Test fun unboundedHeightAndMissingRows() {
        assertEquals(TripFixedRouteFit(320,strip=true,extra=true),fit(Constraints.Infinity))
        assertEquals(TripFixedRouteFit(320,strip=true,extra=false),fit(2000,extra=0))
        assertEquals(TripFixedRouteFit(320,strip=false,extra=false),fit(Constraints.Infinity,strip=0,extra=0))
    }
}
