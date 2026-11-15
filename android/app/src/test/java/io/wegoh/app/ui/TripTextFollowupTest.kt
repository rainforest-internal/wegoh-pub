package io.wegoh.app.ui

import io.wegoh.app.TripGear
import io.wegoh.app.nativeauth.TripMember
import org.junit.Assert.assertEquals
import org.junit.Test

class TripTextFollowupTest {
    @Test fun onlyParkAndDriveShowGearGlyph() {
        assertEquals("P" to "정차 중",tripGearBadge(TripGear.PARK))
        assertEquals("D" to "주행 중",tripGearBadge(TripGear.DRIVE))
        assertEquals(null to "차량 상태 확인 중",tripGearBadge(TripGear.OTHER))
        assertEquals(null to "차량 상태 확인 중",tripGearBadge(TripGear.UNKNOWN))
    }

    @Test fun waitingRowsKeepInvitationState() {
        fun member(accepted: Boolean)=TripMember("m","사용자B",accepted,isOwner=false,isMe=false)
        assertEquals("초대 수락 전",tripWaitingCarDetail(member(false)))
        assertEquals("탈 차 미정",tripWaitingCarDetail(member(true)))
    }
}
