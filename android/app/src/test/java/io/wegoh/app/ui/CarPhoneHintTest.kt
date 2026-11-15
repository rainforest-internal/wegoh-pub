package io.wegoh.app.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class CarPhoneHintTest {
    private val views=listOf("create","course-edit","course-feed","course-save","profile","trip-new","trip-info","trip-route",
        "members","music","music-link","history","together","pickup","drop","stops","car-and-stops","passenger-stops",
        "remote","vehicle","vehicle-link","vehicle-permission")
    private val tabs=setOf("여행","경로","음악","친구","설정")

    @Test fun everyHintNamesAnIphoneTabInOneForm() {
        views.forEach {view->
            val hint=carPhoneHint(view)
            val path=Regex("^iPhone 앱의 (.+?)에서 .+요$").find(hint)?.groupValues?.get(1)
            assertTrue("$view: $hint",path!=null)
            assertTrue("$view: $hint",path!!.split(" → ").first() in tabs)
        }
    }

    @Test fun hintsAreDistinctPerView() {
        assertEquals(views.size,views.map(::carPhoneHint).toSet().size)
    }

    @Test fun profileAndRemotePointToRealIphoneScreens() {
        assertEquals("iPhone 앱의 설정 → 프로필에서 고쳐요",carPhoneHint("profile"))
        assertEquals("iPhone 앱의 여행 → 동승자 리모컨에서 허용 기능을 바꿔요",carPhoneHint("remote"))
    }
}
